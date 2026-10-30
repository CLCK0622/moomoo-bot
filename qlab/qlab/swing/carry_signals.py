"""EVO-25 candidate-8 signal adapter: VIX term-structure carry (long-only ETP/cash).

This is the ONLY new modelling code. It maps a pre-registered signal + risk
overlay + real prices into a daily cost-after equity curve, which then flows into
the SAME EVO-130 ``evaluate_curve`` and EVO-149 gates / significance /
multiple_testing used by S1/S5 — no judgment metric is re-implemented here.

Design (all constants frozen in ``CARRY_EVAL_PREREGISTRATION.md`` before any
result was read):

* **Signal** (info as of day *T* close): ``term_ratio = VIX_close / VIX3M_close``
  (CBOE cash indices). ``term_ratio < τ`` ⇒ contango (upward term structure ⇒
  positive short-vol roll). ``τ = 1.00`` is the natural structural boundary — a
  no-fit threshold (guardrail #4). No parameter here is fitted on returns.
* **Instrument** (long-only, no naked short — hard constraint): contango ⇒ hold a
  *long* position in a short-vol ETP (SVXY, −0.5x); otherwise **cash**. Never
  shorts a vol product.
* **Execution / anti-look-ahead** (guardrail #2): VIX settles 16:15 ET, after the
  16:00 ET ETP close, so a signal on ``close(T)`` may only trade from
  ``open(T+1)``. Position returns are therefore **open-to-open**: the exposure
  decided at ``close(T)`` earns ``open(T+2)/open(T+1) − 1`` and pays cost on the
  rebalanced notional at ``open(T+1)``. Nothing prices against a bar the signal
  could not have traded.
* **Risk overlay** (hard constraints; pre-registered conventions, not tuned on
  P&L): volatility target, exposure cap, drawdown circuit-breaker + cooldown,
  abnormal-VIX stop. See ``CarryParams``.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Frozen parameter block (mirrors CARRY_EVAL_PREREGISTRATION.md)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CarryParams:
    tau: float = 1.00              # contango threshold (natural boundary; no-fit)
    target_vol: float = 0.15       # annualized sleeve vol target
    vol_lookback: int = 20         # trailing days for realized-vol estimate
    exposure_cap: float = 0.50     # max fraction of capital in the ETP
    dd_stop: float = 0.15          # strategy-equity drawdown that flattens the book
    cooldown: int = 10             # trading days held flat after a breaker trip
    vix_cap: float = 35.0          # abnormal-VIX hard stop (flatten next period)
    side_frac_base: float = 0.001  # 10 bps/side (EVO-12 CostModel base); ×cost_mult

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# CBOE cash-index loader + term-structure signal
# --------------------------------------------------------------------------- #
def load_cboe_index(csv_path: str | Path) -> pd.DataFrame:
    """Load a CBOE ``*_History.csv`` (DATE,OPEN,HIGH,LOW,CLOSE) → date,close."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[["date", "close"]].dropna()
    df = df[df["close"] > 0].sort_values("date").reset_index(drop=True)
    return df


def build_term_signal(vix_csv: str | Path, vix3m_csv: str | Path) -> pd.DataFrame:
    """Inner-join VIX & VIX3M → date, vix, vix3m, term_ratio (VIX/VIX3M)."""
    vix = load_cboe_index(vix_csv).rename(columns={"close": "vix"})
    v3m = load_cboe_index(vix3m_csv).rename(columns={"close": "vix3m"})
    sig = pd.merge(vix, v3m, on="date", how="inner").sort_values("date").reset_index(drop=True)
    sig["term_ratio"] = sig["vix"] / sig["vix3m"]
    return sig


# --------------------------------------------------------------------------- #
# Core: signal + risk overlay + prices -> daily cost-after equity curve
# --------------------------------------------------------------------------- #
def carry_curve(etp_df: pd.DataFrame, signal_df: pd.DataFrame, params: CarryParams,
                *, cost_mult: float = 1.0, start: str | None = None,
                end: str | None = None) -> dict:
    """Build the EVO-12 daily equity frame for the carry sleeve on one ETP.

    Returns ``{equity_df, trade_log, diagnostics}``. ``equity_df`` carries the
    EVO-12 columns ``date, ret, equity, traded_notional`` verbatim so it flows
    straight into ``evaluate_curve``. Sequential simulation is required because
    the drawdown circuit-breaker depends on realized strategy equity.
    """
    etp = etp_df.copy()
    etp["date"] = pd.to_datetime(etp["date"]).dt.normalize()
    etp = etp.sort_values("date").reset_index(drop=True)
    if start is not None:
        etp = etp[etp["date"] >= pd.Timestamp(start)]
    if end is not None:
        etp = etp[etp["date"] <= pd.Timestamp(end)]
    etp = etp.reset_index(drop=True)

    # backward as-of merge: each ETP date uses the latest signal at or before it
    # (no look-ahead). NYSE-aligned, so this matches same-day almost everywhere.
    sig = signal_df.sort_values("date").reset_index(drop=True)
    m = pd.merge_asof(etp[["date", "open", "close"]], sig, on="date", direction="backward")
    m = m.dropna(subset=["term_ratio", "vix"]).reset_index(drop=True)

    dates = pd.DatetimeIndex(m["date"])
    O = m["open"].to_numpy(float)
    C = m["close"].to_numpy(float)
    tr = m["term_ratio"].to_numpy(float)
    vix = m["vix"].to_numpy(float)
    n = len(m)

    # trailing realized vol (annualized) of the ETP, as of each close k
    cc = np.zeros(n)
    cc[1:] = C[1:] / C[:-1] - 1.0
    rv = pd.Series(cc).rolling(params.vol_lookback).std(ddof=1).to_numpy() * np.sqrt(TRADING_DAYS)

    side = params.side_frac_base * cost_mult
    rows = []                     # (period_end_date, ret, traded_notional, exposure)
    exposures = np.zeros(n)
    eq = 1.0
    peak = 1.0
    cooldown_left = 0
    breaker_trips = 0
    prev_e = 0.0

    # period p spans open(p)->open(p+1); exposure decided at close(p-1) (=index t)
    for p in range(1, n - 1):
        t = p - 1                                   # decision close (< open(p))
        resuming = False
        if cooldown_left > 0:
            e_t = 0.0
            cooldown_left -= 1
            if cooldown_left == 0:
                resuming = True                     # breaker releases: reset HWM on resume
        else:
            regime = tr[t] < params.tau
            abnormal = vix[t] > params.vix_cap
            rvt = rv[t]
            if (not regime) or abnormal or (not np.isfinite(rvt)) or rvt <= 0:
                e_t = 0.0
            else:
                e_t = float(min(params.exposure_cap, params.target_vol / rvt))

        gross = O[p + 1] / O[p] - 1.0               # open(T+1)->open(T+2)
        cost = side * abs(e_t - prev_e)             # rebalanced at open(T+1)
        r = e_t * gross - cost
        eq *= (1.0 + r)
        # `peak` is the breaker's high-water mark ONLY; the reported MDD is
        # recomputed independently on equity_df, so resetting it never hides
        # drawdown. Resetting at resume stops a flat cooldown from permanently
        # re-tripping the breaker against a stale, unrecoverable peak.
        peak = eq if resuming else max(peak, eq)
        rows.append((dates[p + 1], r, abs(e_t - prev_e), e_t))
        exposures[p] = e_t
        # breaker evaluated on realized equity (info known at close of this period)
        if cooldown_left == 0 and (eq / peak - 1.0) < -params.dd_stop:
            cooldown_left = params.cooldown
            breaker_trips += 1
        prev_e = e_t

    if not rows:
        raise ValueError("no periods produced (insufficient overlap of ETP and signal)")
    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional", "exposure"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    equity_df = edf[["date", "ret", "equity", "traded_notional"]].copy()

    # episode-based trade log (one trade = one contiguous exposed spell) for
    # evo12 trade stats (win_rate / profit_factor); does not feed gates.
    trade_log = []
    exp = edf["exposure"].to_numpy(float)
    rr = edf["ret"].to_numpy(float)
    ds = pd.DatetimeIndex(edf["date"])
    i = 0
    N = len(edf)
    while i < N:
        if exp[i] > 0:
            j = i
            comp = 1.0
            while j < N and exp[j] > 0:
                comp *= (1.0 + rr[j])
                j += 1
            trade_log.append({"pnl": float(comp - 1.0),
                              "entry": str(ds[i].date()), "exit": str(ds[j - 1].date()),
                              "hold_days": int(j - i)})
            i = j
        else:
            i += 1

    deployed = edf["exposure"].to_numpy(float)
    diagnostics = {
        "instrument": None,
        "cost_mult": cost_mult,
        "n_periods": int(len(edf)),
        "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "frac_days_deployed": float(np.mean(deployed > 0)),
        "mean_exposure_when_on": float(deployed[deployed > 0].mean()) if (deployed > 0).any() else 0.0,
        "max_exposure": float(deployed.max()),
        "breaker_trips": int(breaker_trips),
        "n_trades": len(trade_log),
        "return_convention": "open-to-open; exposure decided at close(T), executed open(T+1)",
    }
    return {"equity_df": equity_df, "trade_log": trade_log, "diagnostics": diagnostics,
            "exposure_series": edf[["date", "exposure"]]}

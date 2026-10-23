"""EVO-23 candidate-1+2 signal adapter: ETF right-side momentum (long-only / cash).

This is the ONLY new modelling code for EVO-23. It maps a pre-registered signal
(absolute time-series momentum, or top-N relative-strength) + a fixed equal-weight
sizing rule + real OpenD daily ETF bars into a daily cost-after equity curve, which
then flows into the SAME EVO-130 ``swing.evaluate.evaluate_curve`` and EVO-149
``events/{gates,significance,multiple_testing,metrics}`` used by S1/S5/carry. No
judgment metric is re-implemented here.

Design — every constant frozen in ``MOMENTUM_EVAL_PREREGISTRATION.md`` before any
result was read:

* **Signal** (info as of day *T* close): ``mom(T) = close(T)/close(T-L) - 1`` on the
  OpenD daily bar. Two frozen口径:
    - **TSMOM** (``top_n=None``, sleeve A): per-asset *absolute-momentum* in/out —
      each of ``N_universe`` assets gets a fixed ``1/N_universe`` slot, invested only
      while its own ``mom>0``, else cash (Faber 2007 GTAA / MOP 2012 / Antonacci
      2014 absolute filter). Gross exposure = (#positive)/N_universe.
    - **Relative strength** (``top_n=k``, sleeve B): rank assets by ``mom(T)``, hold
      the **top-k** equal-weight (``1/k`` each); a slot is taken only if that asset's
      own ``mom>0`` (dual-momentum overlay), else cash.
  ``L`` (lookback) is a literature convention, pre-fixed, **NOT fitted on returns**
  (no-fit — hard gate #2 clause #4). **Long-only, no shorting, no leverage.**
* **Execution / anti-look-ahead** (hard gate #2): weights are decided at a rebalance
  ``close(T)`` and may only trade from ``open(T+1)``. Position returns are therefore
  **open-to-open**: weights decided at ``close(T)`` earn ``open(p+1)/open(p) - 1``
  each subsequent period and pay cost on the rebalanced notional at the first
  ``open(T+1)``. Nothing prices against a bar the signal could not have traded.
* **Sizing frozen; NO vol target / breaker / stop** — the absolute-momentum cash
  switch IS the risk control (pre-registration §5). ``N_universe`` is the FROZEN
  universe size, not the number of frames supplied: an un-supplied universe symbol
  is a permanently-cash slot (a data gap), so a reduced real universe honestly shows
  as mostly-cash rather than silently re-sizing off the frozen weights.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

TRADING_DAYS = 252
DAYS_PER_MONTH = 21


# --------------------------------------------------------------------------- #
# Frozen parameter block (mirrors MOMENTUM_EVAL_PREREGISTRATION.md)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MomentumParams:
    lookback_months: int = 12       # formation window (literature convention; no-fit)
    top_n: int | None = None        # None ⇒ TSMOM abs-momentum; int ⇒ RS top-N
    rebalance: str = "monthly"      # 'monthly' (verdict) | 'weekly' (sensitivity only)
    abs_filter: bool = True         # dual-momentum: hold a slot only while its own mom>0
    side_frac_base: float = 0.001   # 10 bps/side (EVO-12 CostModel base); ×cost_mult

    @property
    def lookback_days(self) -> int:
        return int(self.lookback_months * DAYS_PER_MONTH)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lookback_days"] = self.lookback_days
        return d


# --------------------------------------------------------------------------- #
# OpenD daily-bar loader
# --------------------------------------------------------------------------- #
def load_daily(path) -> pd.DataFrame:
    """Load an OpenD qfq daily parquet → date, open, close (normalized dates)."""
    df = pd.read_parquet(path)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[["date", "open", "close"]].dropna()
    df = df[(df["open"] > 0) & (df["close"] > 0)].sort_values("date").reset_index(drop=True)
    return df


def _rebalance_mask(dates: pd.DatetimeIndex, mode: str) -> np.ndarray:
    """Boolean mask: True on the last trading day of each month (or ISO week)."""
    s = pd.Series(range(len(dates)), index=dates)
    if mode == "weekly":
        key = [(d.isocalendar().year, d.isocalendar().week) for d in dates]
    else:  # monthly (default / verdict口径)
        key = [(d.year, d.month) for d in dates]
    grp = pd.Series(key, index=range(len(dates)))
    last_idx = grp.groupby(grp, sort=False).apply(lambda g: g.index[-1]).to_numpy()
    mask = np.zeros(len(dates), dtype=bool)
    mask[last_idx] = True
    return mask


# --------------------------------------------------------------------------- #
# Core: signal + fixed sizing + prices -> daily cost-after equity curve
# --------------------------------------------------------------------------- #
def momentum_curve(frames_by_symbol: dict[str, pd.DataFrame], universe: list[str],
                   params: MomentumParams, *, cost_mult: float = 1.0,
                   start: str | None = None, end: str | None = None) -> dict:
    """Build the EVO-12 daily equity frame for a momentum sleeve on ``universe``.

    ``frames_by_symbol`` maps symbol → daily bars (``load_daily`` shape). ``universe``
    is the FROZEN symbol list; its length fixes the per-asset slot (1/N for TSMOM).
    Symbols in ``universe`` but absent from ``frames_by_symbol`` (or without price on
    a date) are permanently-cash slots — a data gap, never silently re-sized away.

    Returns ``{equity_df, trade_log, diagnostics, gross_series, weights_df}``.
    ``equity_df`` carries the EVO-12 columns ``date, ret, equity, traded_notional``
    verbatim so it flows straight into ``evaluate_curve``.
    """
    n_universe = len(universe)
    if n_universe == 0:
        raise ValueError("empty universe")

    # union calendar across all supplied universe symbols
    all_dates = set()
    for sym in universe:
        df = frames_by_symbol.get(sym)
        if df is not None and len(df):
            all_dates.update(pd.to_datetime(df["date"]).tolist())
    if not all_dates:
        raise ValueError("no price data for any universe symbol")
    cal = pd.DatetimeIndex(sorted(all_dates))
    if start is not None:
        cal = cal[cal >= pd.Timestamp(start)]
    if end is not None:
        cal = cal[cal <= pd.Timestamp(end)]
    n = len(cal)
    if n < params.lookback_days + 5:
        raise ValueError("calendar shorter than lookback + margin")

    # aligned open/close matrices (n × n_universe), NaN where a symbol has no bar
    O = np.full((n, n_universe), np.nan)
    C = np.full((n, n_universe), np.nan)
    for j, sym in enumerate(universe):
        df = frames_by_symbol.get(sym)
        if df is None or not len(df):
            continue
        d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"]).dt.normalize()))
        d = d[~d.index.duplicated(keep="last")].reindex(cal)
        O[:, j] = d["open"].to_numpy(float)
        C[:, j] = d["close"].to_numpy(float)

    L = params.lookback_days
    # momentum score at each index t: close(t)/close(t-L)-1, valid only if both present
    mom = np.full((n, n_universe), np.nan)
    mom[L:, :] = C[L:, :] / C[:-L, :] - 1.0

    reb_mask = _rebalance_mask(cal, params.rebalance)
    side = params.side_frac_base * cost_mult

    # ---- decide target weights at each rebalance close (info as of close t) ---- #
    reb_weights: dict[int, np.ndarray] = {}
    for t in np.flatnonzero(reb_mask):
        if t < L:                      # not enough history to form a signal yet
            continue
        w = np.zeros(n_universe)
        m_t = mom[t, :]
        valid = np.isfinite(m_t) & np.isfinite(C[t, :])
        if params.top_n is None:
            # TSMOM: fixed 1/N slot, invested while own mom>0
            take = valid & (m_t > 0.0)
            w[take] = 1.0 / n_universe
        else:
            # RS: rank valid by mom desc, take top-N; abs filter drops mom<=0 slots
            k = int(params.top_n)
            cand = np.flatnonzero(valid)
            if cand.size:
                order = cand[np.argsort(-m_t[cand], kind="stable")]
                chosen = order[:k]
                for idx in chosen:
                    if (not params.abs_filter) or (m_t[idx] > 0.0):
                        w[idx] = 1.0 / k
        reb_weights[int(t)] = w

    reb_idx_sorted = sorted(reb_weights)

    def _weights_for_decision(t: int) -> np.ndarray:
        """Latest rebalance weights decided at an index ≤ t (else all-cash)."""
        r = None
        for ri in reb_idx_sorted:
            if ri <= t:
                r = ri
            else:
                break
        return reb_weights[r] if r is not None else np.zeros(n_universe)

    # ---- open-to-open daily simulation (period p: open(p) -> open(p+1)) ---- #
    rows, gross_hist, weights_hist = [], [], []
    prev_w = np.zeros(n_universe)
    for p in range(1, n - 1):
        t = p - 1                                    # decision close (< open(p))
        w = _weights_for_decision(t)
        o_p = O[p, :]
        o_n = O[p + 1, :]
        tradable = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(n_universe)
        step[tradable] = o_n[tradable] / o_p[tradable] - 1.0
        w_eff = np.where(tradable, w, 0.0)           # untradable held-slot ⇒ cash
        gross_ret = float(np.dot(w_eff, step))
        turnover = float(np.abs(w_eff - prev_w).sum())
        cost = side * turnover
        r = gross_ret - cost
        rows.append((cal[p + 1], r, turnover))
        gross_hist.append(float(w_eff.sum()))
        weights_hist.append(w_eff.copy())
        prev_w = w_eff

    if not rows:
        raise ValueError("no periods produced")
    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    equity_df = edf[["date", "ret", "equity", "traded_notional"]].copy()

    gross = np.array(gross_hist)
    W = np.vstack(weights_hist)
    n_holdings = (W > 0).sum(axis=1)

    # episode-based trade log: one "trade" = a contiguous spell with gross>0
    trade_log = []
    rr = edf["ret"].to_numpy(float)
    ds = pd.DatetimeIndex(edf["date"])
    i, N = 0, len(edf)
    while i < N:
        if gross[i] > 0:
            j, comp = i, 1.0
            while j < N and gross[j] > 0:
                comp *= (1.0 + rr[j])
                j += 1
            trade_log.append({"pnl": float(comp - 1.0),
                              "entry": str(ds[i].date()), "exit": str(ds[j - 1].date()),
                              "hold_days": int(j - i)})
            i = j
        else:
            i += 1

    present = [s for s in universe if frames_by_symbol.get(s) is not None
               and len(frames_by_symbol.get(s))]
    missing = [s for s in universe if s not in present]
    diagnostics = {
        "sleeve": "tsmom" if params.top_n is None else f"rs_top{params.top_n}",
        "cost_mult": cost_mult,
        "n_periods": int(len(edf)),
        "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "frac_days_deployed": float(np.mean(gross > 0)),
        "mean_gross_when_on": float(gross[gross > 0].mean()) if (gross > 0).any() else 0.0,
        "max_gross": float(gross.max()),
        "mean_holdings_when_on": float(n_holdings[gross > 0].mean()) if (gross > 0).any() else 0.0,
        "n_rebalances": int(len(reb_weights)),
        "n_trades": len(trade_log),
        "universe_frozen": list(universe),
        "universe_present": present,
        "universe_missing": missing,
        "data_complete": bool(not missing),
        "return_convention": "open-to-open; weights decided at close(T), executed open(T+1)",
    }
    weights_df = pd.DataFrame(W, columns=list(universe))
    weights_df.insert(0, "date", ds)
    return {"equity_df": equity_df, "trade_log": trade_log, "diagnostics": diagnostics,
            "gross_series": pd.DataFrame({"date": ds, "gross": gross}),
            "weights_df": weights_df}


def buy_and_hold_curve(frames_by_symbol: dict[str, pd.DataFrame], universe: list[str],
                       *, cost_mult: float = 1.0, start=None, end=None,
                       equal_weight: bool = True) -> dict:
    """Risk-frontier / benchmark reference: always-invested equal-weight buy&hold of
    the *present* universe symbols, NO momentum/cash switch, open-to-open. Never a
    verdict cell — exposes the CAGR↔MDD frontier the trend filter avoids (pre-reg §9).
    """
    present = [s for s in universe if frames_by_symbol.get(s) is not None
               and len(frames_by_symbol.get(s))]
    if not present:
        raise ValueError("no present symbols for buy&hold reference")
    p = MomentumParams(lookback_months=0, top_n=None)
    # reuse the aligned-calendar machinery by faking a permanently-positive signal:
    # simplest correct path is a dedicated always-on equal-weight sim.
    all_dates = set()
    for s in present:
        all_dates.update(pd.to_datetime(frames_by_symbol[s]["date"]).tolist())
    cal = pd.DatetimeIndex(sorted(all_dates))
    if start is not None:
        cal = cal[cal >= pd.Timestamp(start)]
    if end is not None:
        cal = cal[cal <= pd.Timestamp(end)]
    n = len(cal)
    O = np.full((n, len(present)), np.nan)
    for j, s in enumerate(present):
        d = frames_by_symbol[s].copy()
        d = d.set_index(pd.DatetimeIndex(pd.to_datetime(d["date"]).dt.normalize()))
        d = d[~d.index.duplicated(keep="last")].reindex(cal)
        O[:, j] = d["open"].to_numpy(float)
    w = np.full(len(present), 1.0 / len(present))
    side = 0.001 * cost_mult
    rows = []
    prev = np.zeros(len(present))
    for k in range(1, n - 1):
        o_p, o_n = O[k, :], O[k + 1, :]
        tr = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(len(present))
        step[tr] = o_n[tr] / o_p[tr] - 1.0
        w_eff = np.where(tr, w, 0.0)
        if w_eff.sum() > 0:
            w_eff = w_eff / w_eff.sum()
        turnover = float(np.abs(w_eff - prev).sum()) if k == 1 else 0.0
        r = float(np.dot(w_eff, step)) - side * turnover
        rows.append((cal[k + 1], r, turnover))
        prev = w_eff
    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    return {"equity_df": edf[["date", "ret", "equity", "traded_notional"]].copy(),
            "present": present}

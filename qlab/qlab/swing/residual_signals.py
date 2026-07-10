"""EVO-162 C1 signal adapter: cross-sectional residual reversal (large-cap, weekly,
market-neutral stat-arb).

This is the ONLY new modelling code for EVO-162 (户部 froze every constant in
``RESIDUAL_REVERSAL_EVAL_PREREGISTRATION.md`` before any result was read; 工部
implements this spec verbatim and tunes NOTHING in parallel). It maps the frozen
residual-reversal signal + a fixed dollar/beta-neutral decile long-short sizing rule +
the frozen leverage overlay + real moomoo OpenD daily bars into a daily cost-after
equity curve carrying the EVO-12 columns ``date, ret, equity, traded_notional`` verbatim,
which then flows into the SAME ``swing.evaluate.evaluate_curve`` and EVO-149
``events/{gates,significance,multiple_testing,metrics}`` used by S1/S5/carry/momentum. No
judgment metric is re-implemented here.

Design — every constant frozen in the pre-registration before any result:

* **Frequency (§3):** weekly. A week's bar is the last OpenD trading day of the ISO week
  (``_rebalance_mask(..., "weekly")`` — reused from ``momentum_signals``). Weekly return
  ``r_{i,t} = close_i(t) / close_i(t-1) - 1`` on consecutive weekly rebalance closes.
* **Factors (§3), 3-factor, OpenD-only:** ``MKT = SPY`` weekly return; ``SMB = IWM - SPY``;
  ``HML = IVE - IVW``. Regressor ETFs are never traded.
* **Per-stock betas (§3), genuinely OOS by construction:** at each weekly rebalance ``t``,
  OLS of ``r_{i,·}`` on ``{1, MKT, SMB, HML}`` over the trailing ``E`` weeks ending at the
  week *before* the formation window (strictly past data); require ``>= min_obs`` valid
  weeks or the stock is excluded that week (a data gap, recorded, never imputed).
* **Residual + reversal signal (§3):** ``eps_{i,τ} = r_{i,τ} - (α̂ + β̂·f_τ)``;
  ``signal_{i,t} = - mean(eps over the F formation weeks)`` (F=1 primary ⇒ the most recent
  single-week residual). Cross-sectionally winsorize at 1/99 pct, then rank.
* **Portfolio (§4):** long the top ``cut`` (decile primary) of the eligible cross-section,
  short the bottom ``cut``, equal-weight within each leg, dollar-neutral (long notional =
  short notional at unit gross), beta-neutral (net ``|β^MKT| ≤ 0.05``; if breached the short
  leg is mechanically rescaled — not a tuned knob). ``N`` is the FROZEN universe size, so an
  un-fetched / excluded symbol is a permanently-absent cross-section slot (data gap), never a
  silent re-size.
* **Leverage overlay (§5):** base/cap gross 2.0× (1.0× long + 1.0× short of NAV); ex-ante
  10% ann. vol target on trailing 26-week realized unit-book vol, gross ∈ [0.5×, 2.0×];
  stress breaker: trailing 5-trading-day book drawdown ≥ 8% ⇒ gross → 0.5× for the next
  full rebalance week. All decided causally from trailing data only.
* **Execution / anti-look-ahead (§7):** weights decided at a weekly rebalance ``close(T)``
  may only trade from ``open(T+1)``; position returns are **open-to-open** — weights decided
  at ``close(T)`` earn ``open(p+1)/open(p) - 1`` each subsequent day and pay cost on the
  rebalanced notional at the first ``open(T+1)``. Nothing prices against a bar the signal
  could not have traded (unit-tested).
* **Costs (§8), moomoo retail, ×1/×2:** commission+spread 10 bps/side base × ``cost_mult``
  on traded notional; short borrow 0.5%/yr on short notional accrued daily; financing 6.8%/yr
  on ``max(0, gross-1)·NAV`` accrued daily; no short rebate.

The residual model needs cross-sectional breadth (``N >> K``). If fewer than
``min_names_per_leg`` names are eligible on a rebalance, that week is flagged
data-insufficient (recorded in diagnostics); the verdict builder labels any such run
``数据不足-仅工程可复跑`` and NEVER达标 (mirrors ``momentum`` universe-gap discipline).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .momentum_signals import _rebalance_mask  # reuse the weekly last-trading-day mask

TRADING_DAYS = 252
WEEKS_PER_YEAR = 52
DAYS_PER_WEEK = 5

# frozen factor-regressor ETFs (pre-registration §2 / §16); regressors only, never traded
FACTOR_ETFS = ("SPY", "IWM", "IVE", "IVW")


class ResidualDataGap(ValueError):
    """Raised when the frozen 3-factor口径 cannot be built (a required factor ETF is absent).

    A subclass of ``ValueError`` so callers that already treat engine failures as a data gap
    keep working; the verdict builder catches it and reports ``数据不足`` honestly.
    """


# --------------------------------------------------------------------------- #
# Frozen parameter block (mirrors RESIDUAL_REVERSAL_EVAL_PREREGISTRATION.md §16)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ResidualParams:
    # --- model (§3) ---
    formation_weeks: int = 1          # F: signal = -mean(eps over last F weeks); primary 1
    estimation_weeks: int = 156       # E: rolling OLS window (3yr); primary 156
    min_obs_weeks: int = 104          # min valid weekly obs in the window (2yr); else excluded
    factor_set: str = "3f"            # "3f" primary (MKT+SMB+HML) | "4f" adds sector demean
    winsor_pct: float = 0.01          # cross-sectional winsorize at 1/99 pct
    # --- portfolio (§4) ---
    cut: float = 0.10                 # decile long / decile short (primary 0.10); quintile 0.20
    beta_neutral_tol: float = 0.05    # force net |β^MKT| into ±tol
    # --- leverage overlay (§5) ---
    gross_base: float = 2.0           # base/cap gross (1.0× long + 1.0× short of NAV)
    gross_cap: float = 2.0            # hard cap, never exceeded
    gross_floor: float = 0.5          # floor
    vol_target_annual: float = 0.10   # 10% ann. vol target on the long-short book
    vol_window_weeks: int = 26        # trailing window for realized-vol estimate
    breaker_dd: float = 0.08          # trailing 5d book DD ≥ 8% ⇒ de-lever
    breaker_lookback_days: int = 5
    breaker_gross: float = 0.5        # de-levered gross after a breaker trip
    # --- risk red-lines (§6) ---
    min_names_per_leg: int = 20       # below this the run is 数据不足 (thin-book), never a verdict
    max_name_frac_gross: float = 0.05 # single-name hard cap (informational check)
    # --- costs (§8) ---
    side_frac_base: float = 0.001     # 10 bps/side base (EVO-12 CostModel); ×cost_mult
    borrow_annual: float = 0.005      # 0.5%/yr on short notional
    financing_annual: float = 0.068   # 6.8%/yr on max(0, gross-1)·NAV
    # --- leverage engagement (risk-frontier reference §14 sets this False) ---
    lever: bool = True                # True = overlay on; False = 1.0× gross, no vol/breaker

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Factor construction (weekly, OpenD-only)
# --------------------------------------------------------------------------- #
def _weekly_close_at(frame: pd.DataFrame, cal: pd.DatetimeIndex,
                     reb_idx: np.ndarray) -> np.ndarray:
    """Symbol close on each weekly rebalance day (NaN where the symbol has no bar)."""
    d = frame.set_index(pd.DatetimeIndex(pd.to_datetime(frame["date"]).dt.normalize()))
    d = d[~d.index.duplicated(keep="last")].reindex(cal)
    close_full = d["close"].to_numpy(float)
    return close_full[reb_idx]


def _factor_returns(factor_frames: dict[str, pd.DataFrame], cal: pd.DatetimeIndex,
                    reb_idx: np.ndarray) -> tuple[np.ndarray | None, list[str]]:
    """Build the weekly factor-return matrix ``[MKT, SMB, HML]`` from OpenD ETF closes.

    Returns ``(F, missing)`` where ``F`` is ``(n_weeks, 3)`` (NaN in the first week) or
    ``None`` if any required factor ETF is absent (a hard data gap — the 3-factor primary
    口径 cannot be built without all four ETFs, so we do NOT silently drop a factor).
    """
    missing = [s for s in FACTOR_ETFS if factor_frames.get(s) is None
               or not len(factor_frames.get(s))]
    if missing:
        return None, missing
    wc = {s: _weekly_close_at(factor_frames[s], cal, reb_idx) for s in FACTOR_ETFS}
    wret = {s: np.concatenate([[np.nan], wc[s][1:] / wc[s][:-1] - 1.0]) for s in FACTOR_ETFS}
    mkt = wret["SPY"]
    smb = wret["IWM"] - wret["SPY"]
    hml = wret["IVE"] - wret["IVW"]
    return np.column_stack([mkt, smb, hml]), missing


def _ols_beta(y: np.ndarray, X: np.ndarray, min_obs: int) -> np.ndarray | None:
    """OLS of ``y`` on ``X`` (design already includes an intercept column).

    Uses only rows where both ``y`` and every regressor are finite. Returns the coefficient
    vector (``[α, β_MKT, β_SMB, β_HML]``) or ``None`` if fewer than ``min_obs`` valid rows
    or the design is rank-deficient.
    """
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    if int(ok.sum()) < max(min_obs, X.shape[1] + 1):
        return None
    Xo, yo = X[ok], y[ok]
    try:
        coef, _, rank, _ = np.linalg.lstsq(Xo, yo, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if rank < X.shape[1]:
        return None
    return coef


# --------------------------------------------------------------------------- #
# Core: residual signal + neutral decile weights → weekly target book
# --------------------------------------------------------------------------- #
def _rebalance_weights(wret: np.ndarray, F: np.ndarray, params: ResidualParams,
                       sectors: np.ndarray | None) -> tuple[dict[int, np.ndarray],
                                                             dict[int, dict]]:
    """Decide the signed unit-book weights at each weekly rebalance (info as of that close).

    ``wret`` is ``(n_weeks, n_stocks)`` weekly returns; ``F`` is ``(n_weeks, 3)`` factor
    returns. At week ``k`` the betas use weeks ending at ``k - formation_weeks`` (strictly
    past), residuals cover the ``formation_weeks`` formation weeks, and the signal is the
    negative mean residual. Long the top ``cut`` / short the bottom ``cut`` of the eligible
    cross-section, equal-weight, dollar-neutral, then beta-neutralized.

    Returns ``({week_k: signed_weight_vec}, {week_k: diag})``; ``signed_weight_vec`` sums to
    ``+1`` on the long leg and ``-1`` on the short leg (unit book = 2.0× gross).
    """
    n_weeks, n_stocks = wret.shape
    Ew, Fw = params.estimation_weeks, params.formation_weeks
    reb_w: dict[int, np.ndarray] = {}
    reb_diag: dict[int, dict] = {}

    for k in range(n_weeks):
        # need Fw formation weeks + Ew estimation weeks strictly before them
        if k - Fw + 1 < 0 or (k - Fw) - Ew + 1 < 0:
            continue
        f_slice = F[k - Fw + 1: k + 1, :]                       # formation weeks' factors
        est_lo, est_hi = (k - Fw) - Ew + 1, (k - Fw) + 1        # estimation window (past)
        Xest = np.column_stack([np.ones(est_hi - est_lo), F[est_lo:est_hi, :]])

        signal = np.full(n_stocks, np.nan)
        betas_mkt = np.full(n_stocks, np.nan)
        for j in range(n_stocks):
            coef = _ols_beta(wret[est_lo:est_hi, j], Xest, params.min_obs_weeks)
            if coef is None:
                continue
            # residuals over the formation weeks (genuinely OOS: coef from strictly earlier data)
            rj = wret[k - Fw + 1: k + 1, j]
            if not np.all(np.isfinite(rj)) or not np.all(np.isfinite(f_slice)):
                continue
            fitted = coef[0] + f_slice @ coef[1:]
            eps = rj - fitted
            signal[j] = -float(np.mean(eps))                    # residual reversal
            betas_mkt[j] = float(coef[1])

        elig = np.flatnonzero(np.isfinite(signal))
        n_elig = int(elig.size)
        if n_elig < 2:
            continue

        # 4-factor robustness cell (§12): cross-sectionally demean the signal within GICS
        # sector buckets (industry-neutralization). Primary口径 is 3f and skips this branch.
        if params.factor_set == "4f" and sectors is not None:
            for grp in np.unique(sectors[elig]):
                gmask = elig[sectors[elig] == grp]
                if gmask.size:
                    signal[gmask] = signal[gmask] - np.mean(signal[gmask])

        # cross-sectional winsorize at 1/99 pct, then rank-select deciles
        s_elig = signal[elig].astype(float)
        lo_q = np.quantile(s_elig, params.winsor_pct)
        hi_q = np.quantile(s_elig, 1.0 - params.winsor_pct)
        s_wins = np.clip(s_elig, lo_q, hi_q)

        n_leg = max(1, int(np.floor(params.cut * n_elig)))
        order = elig[np.argsort(-s_wins, kind="stable")]        # high signal (loser) first
        longs = order[:n_leg]                                   # buy residual losers
        shorts = order[-n_leg:]                                 # short residual winners

        w = np.zeros(n_stocks)
        if n_leg > 0:
            w[longs] = 1.0 / n_leg
            w[shorts] = -1.0 / n_leg

        # beta-neutralize: if net |β^MKT| > tol, mechanically rescale the short leg. This can
        # break exact dollar-neutrality (the prereg §4 accepts that: beta-neutral is the binding
        # constraint), so afterwards renormalize |w| back to ``gross_base`` — the 2.0× gross cap
        # (§5) is a HARD invariant and outranks dollar-neutrality, which outranks nothing here.
        bl = float(np.nansum(w[longs] * betas_mkt[longs]))
        bs = float(np.nansum(w[shorts] * betas_mkt[shorts]))
        net_beta = bl + bs
        beta_adj = 1.0
        if abs(net_beta) > params.beta_neutral_tol and abs(bs) > 1e-9:
            beta_adj = float(np.clip(-bl / bs, 0.5, 2.0))
            w[shorts] *= beta_adj
            net_beta = bl + beta_adj * bs
        gross_raw = float(np.abs(w).sum())
        if gross_raw > 0:
            w *= params.gross_base / gross_raw                 # unit book gross ≡ gross_base

        reb_w[k] = w
        reb_diag[k] = {
            "n_eligible": n_elig, "n_per_leg": n_leg,
            "net_beta_mkt": float(net_beta), "beta_adj": beta_adj,
            "thin_book": bool(n_leg < params.min_names_per_leg),
            "gross_long": float(w[w > 0].sum()), "gross_short": float(-w[w < 0].sum()),
        }
    return reb_w, reb_diag


def residual_curve(stock_frames: dict[str, pd.DataFrame], factor_frames: dict[str, pd.DataFrame],
                   universe: list[str], params: ResidualParams, *, cost_mult: float = 1.0,
                   sectors: dict[str, str] | None = None,
                   start: str | None = None, end: str | None = None) -> dict:
    """Build the EVO-12 daily equity frame for the residual-reversal book on ``universe``.

    ``stock_frames`` maps symbol → daily bars (``load_daily`` shape); ``factor_frames`` maps
    the four regressor ETFs the same way. ``universe`` is the FROZEN symbol list; its length
    fixes the cross-section. Missing symbols are permanently-absent cross-section slots (data
    gaps), never silently re-sized.

    Returns ``{equity_df, trade_log, diagnostics, gross_series, net_beta_series, weights_df}``.
    ``equity_df`` carries the EVO-12 columns ``date, ret, equity, traded_notional`` verbatim so
    it flows straight into ``evaluate_curve``.
    """
    n_universe = len(universe)
    if n_universe == 0:
        raise ValueError("empty universe")
    if params.factor_set not in ("3f", "4f"):
        raise ValueError(f"unknown factor_set {params.factor_set!r}")

    # union daily calendar across supplied stocks + factor ETFs
    all_dates: set = set()
    for sym in universe:
        df = stock_frames.get(sym)
        if df is not None and len(df):
            all_dates.update(pd.to_datetime(df["date"]).tolist())
    for sym in FACTOR_ETFS:
        df = factor_frames.get(sym)
        if df is not None and len(df):
            all_dates.update(pd.to_datetime(df["date"]).tolist())
    if not all_dates:
        raise ValueError("no price data for any universe or factor symbol")
    cal = pd.DatetimeIndex(sorted(all_dates))
    if start is not None:
        cal = cal[cal >= pd.Timestamp(start)]
    if end is not None:
        cal = cal[cal <= pd.Timestamp(end)]
    n = len(cal)
    if n < (params.estimation_weeks + params.formation_weeks + 4) * DAYS_PER_WEEK:
        raise ValueError("calendar shorter than estimation + formation + margin")

    reb_mask = _rebalance_mask(cal, "weekly")
    reb_idx = np.flatnonzero(reb_mask)                          # weekly rebalance day indices
    if len(reb_idx) < params.estimation_weeks + params.formation_weeks + 4:
        raise ValueError("too few weekly rebalances for estimation window")

    # aligned daily open matrix (execution) + weekly close/return matrices (signal)
    O = np.full((n, n_universe), np.nan)
    wret = np.full((len(reb_idx), n_universe), np.nan)
    for j, sym in enumerate(universe):
        df = stock_frames.get(sym)
        if df is None or not len(df):
            continue
        d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"]).dt.normalize()))
        d = d[~d.index.duplicated(keep="last")].reindex(cal)
        O[:, j] = d["open"].to_numpy(float)
        wc = d["close"].to_numpy(float)[reb_idx]
        wret[1:, j] = wc[1:] / wc[:-1] - 1.0

    Fmat, factor_missing = _factor_returns(factor_frames, cal, reb_idx)
    if Fmat is None:
        raise ResidualDataGap(
            f"3-factor primary口径 needs all of {list(FACTOR_ETFS)}; missing {factor_missing}. "
            "Cannot build the residual model without the value/growth ETFs — reported as a data "
            "gap, never silently reduced to fewer factors.")

    sect = None
    if sectors is not None:
        sect = np.array([sectors.get(s, "NA") for s in universe])

    reb_w, reb_diag = _rebalance_weights(wret, Fmat, params, sect)
    if not reb_w:
        raise ValueError("no rebalance produced eligible cross-section (need N >> K breadth)")
    reb_days = {int(reb_idx[k]): w for k, w in reb_w.items()}   # cal-index → signed weights
    reb_days_diag = {int(reb_idx[k]): d for k, d in reb_diag.items()}
    reb_days_sorted = sorted(reb_days)

    def _decision(t: int):
        """Latest weekly rebalance decided at a cal-index ≤ t (else all-cash)."""
        r = None
        for ri in reb_days_sorted:
            if ri <= t:
                r = ri
            else:
                break
        return r

    side = params.side_frac_base * cost_mult
    borrow_daily = params.borrow_annual / TRADING_DAYS
    fin_daily = params.financing_annual / TRADING_DAYS
    vt_daily = params.vol_target_annual / np.sqrt(TRADING_DAYS)
    m_floor, m_cap = params.gross_floor / params.gross_base, params.gross_cap / params.gross_base
    vol_win_days = params.vol_window_weeks * DAYS_PER_WEEK

    # ---- open-to-open daily simulation (period p: open(p) -> open(p+1)) ---- #
    rows, gross_hist, weights_hist, netbeta_hist = [], [], [], []
    unit_ret_hist: list[float] = []                            # realized unit-book (m=1) returns
    equity = 1.0
    equity_hist: list[float] = [1.0]
    prev_sig = np.zeros(n_universe)
    cur_r = None
    ref_m = 1.0 / params.gross_base                            # risk-frontier ref: fixed 1.0× gross
    m = 1.0 if params.lever else ref_m                         # levered m=1⇒gross cap; ref⇒gross 1.0×

    for p in range(1, n - 1):
        t = p - 1                                              # decision close (< open(p))
        r = _decision(t)
        if r is None:                                          # pre-first-rebalance warmup: all cash
            rows.append((cal[p + 1], 0.0, 0.0))
            gross_hist.append(0.0)
            netbeta_hist.append(0.0)
            weights_hist.append(np.zeros(n_universe))
            unit_ret_hist.append(0.0)
            equity_hist.append(equity)
            continue
        w = reb_days[r]

        # a new holding week begins ⇒ decide gross multiplier m causally from trailing data
        if r != cur_r:
            cur_r = r
            if params.lever:
                m_new = 1.0                                    # default = gross cap (2.0×)
                if len(unit_ret_hist) >= vol_win_days:
                    sd = float(np.std(unit_ret_hist[-vol_win_days:], ddof=1))
                    if sd > 0:
                        m_new = float(np.clip(vt_daily / sd, m_floor, m_cap))
                # stress breaker: trailing 5-trading-day book drawdown ≥ 8%
                if len(equity_hist) > params.breaker_lookback_days:
                    tail = np.array(equity_hist[-(params.breaker_lookback_days + 1):])
                    dd = tail[-1] / np.max(tail) - 1.0
                    if dd <= -params.breaker_dd:
                        m_new = params.breaker_gross / params.gross_base
                m = m_new
            else:
                m = ref_m                                      # ref: fixed 1.0× gross

        o_p, o_n = O[p, :], O[p + 1, :]
        tradable = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(n_universe)
        step[tradable] = o_n[tradable] / o_p[tradable] - 1.0
        w_eff = np.where(tradable, w, 0.0)                     # untradable slot ⇒ dropped (gap)

        unit_ret = float(np.dot(w_eff, step))                 # m=1 unit book (gross 2.0)
        sig_now = m * w_eff                                   # signed notional (of NAV)
        turnover = float(np.abs(sig_now - prev_sig).sum())
        gross_notional = float(np.abs(sig_now).sum())
        short_notional = float(np.abs(sig_now[sig_now < 0]).sum())

        commission = side * turnover
        borrow = borrow_daily * short_notional
        financing = fin_daily * max(0.0, gross_notional - 1.0)
        ret = m * unit_ret - commission - borrow - financing

        equity *= (1.0 + ret)
        rows.append((cal[p + 1], ret, turnover))
        gross_hist.append(gross_notional)
        netbeta_hist.append(reb_days_diag[r]["net_beta_mkt"])
        weights_hist.append(sig_now.copy())
        unit_ret_hist.append(unit_ret)
        equity_hist.append(equity)
        prev_sig = sig_now

    if not rows:
        raise ValueError("no periods produced")
    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    equity_df = edf[["date", "ret", "equity", "traded_notional"]].copy()

    gross = np.array(gross_hist)
    ds = pd.DatetimeIndex(edf["date"])

    # weekly-episode trade log: one "trade" per holding week (book pnl compounded over the week),
    # segmenting the daily rows by which weekly rebalance was active for each row.
    rr = edf["ret"].to_numpy(float)
    trade_log = []
    i, N = 0, len(edf)
    # each row i corresponds to cal[p+1] with p = i + 1 ⇒ decision cal-index = i
    active = np.array([_decision(i) if _decision(i) is not None else -1 for i in range(N)])
    while i < N:
        if active[i] < 0:
            i += 1
            continue
        j, comp = i, 1.0
        cur = active[i]
        while j < N and active[j] == cur:
            comp *= (1.0 + rr[j])
            j += 1
        trade_log.append({"pnl": float(comp - 1.0),
                          "entry": str(ds[i].date()), "exit": str(ds[j - 1].date()),
                          "hold_days": int(j - i)})
        i = j

    present = [s for s in universe if stock_frames.get(s) is not None and len(stock_frames.get(s))]
    missing = [s for s in universe if s not in present]
    n_per_leg = [d["n_per_leg"] for d in reb_days_diag.values()]
    thin_weeks = int(sum(1 for d in reb_days_diag.values() if d["thin_book"]))
    diagnostics = {
        "candidate": "residual_reversal",
        "factor_set": params.factor_set, "cost_mult": cost_mult, "levered": params.lever,
        "n_periods": int(len(edf)),
        "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "n_rebalances": len(reb_days),
        "mean_names_per_leg": float(np.mean(n_per_leg)) if n_per_leg else 0.0,
        "min_names_per_leg": int(np.min(n_per_leg)) if n_per_leg else 0,
        "thin_book_weeks": thin_weeks,
        "min_names_per_leg_required": params.min_names_per_leg,
        "any_thin_book": bool(thin_weeks > 0),
        "mean_gross": float(np.mean(gross[gross > 0])) if (gross > 0).any() else 0.0,
        "max_gross": float(gross.max()) if len(gross) else 0.0,
        "mean_abs_net_beta": float(np.mean(np.abs(netbeta_hist))) if netbeta_hist else 0.0,
        "max_abs_net_beta": float(np.max(np.abs(netbeta_hist))) if netbeta_hist else 0.0,
        "n_trades": len(trade_log),
        "factor_etfs_present": [s for s in FACTOR_ETFS if factor_frames.get(s) is not None
                                and len(factor_frames.get(s))],
        "factor_etfs_missing": factor_missing,
        "universe_frozen": list(universe),
        "universe_present": present, "universe_missing": missing,
        "data_complete": bool(not missing and not factor_missing),
        "return_convention": "open-to-open; weekly weights decided at close(T), executed open(T+1)",
        "leverage_convention": (
            f"base/cap gross {params.gross_cap}×, floor {params.gross_floor}×, "
            f"{params.vol_target_annual:.0%} ann vol target on trailing {params.vol_window_weeks}w, "
            f"breaker {params.breaker_dd:.0%}/{params.breaker_lookback_days}d → "
            f"{params.breaker_gross}×" if params.lever else "risk-frontier ref: fixed 1.0× gross, "
            "vol-target/breaker DISABLED"),
    }
    weights_df = pd.DataFrame(np.vstack(weights_hist), columns=list(universe))
    weights_df.insert(0, "date", ds)
    return {"equity_df": equity_df, "trade_log": trade_log, "diagnostics": diagnostics,
            "gross_series": pd.DataFrame({"date": ds, "gross": gross}),
            "net_beta_series": pd.DataFrame({"date": ds, "net_beta_mkt": netbeta_hist}),
            "weights_df": weights_df}

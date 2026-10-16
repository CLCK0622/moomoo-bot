"""EVO-8 方向(b) candidate — cross-sectional RESIDUAL MOMENTUM (large-cap, weekly,
market-neutral). 与 EVO-162 residual reversal 是**同一引擎的动量镜像**：只有横截面
信号不同（残差动量 = 残差赢家做多；残差反转 = 残差输家做多），下游中性分位组合 /
杠杆 overlay / 成本 / 反前视 sim 全部与 `residual_signals.residual_curve` **逐行一致**
（本文件把 `_rebalance_weights` 换成动量版、其余 sim 原样搬运，便于都察院逐行核对差异）。

判据不重实现：曲线出的 OOS 净收益直接灌 `research/gate.certify()`（工部 2026-07-29
接线口径）；本文件不含任何门/DSR/影子分层逻辑。

信号（Blitz–Huij–Martens 2011 residual momentum 的周频实现，预注册冻结）：
  在再平衡周 k：
    * 估计窗 E=156 周（3yr）OLS：`r_i ~ 1 + MKT + SMB + HML`，窗口以 **k−skip 结尾**
      （信息截至决策周，无未来数据）。
    * 残差在**形成窗** F=52 周（12M）上取：weeks [k−skip−F+1 .. k−skip]，
      **skip=4 周**跳过最近 1 个月（规避短期反转污染动量）。
    * signal_i = **+ mean(eps over formation)**（残差动量；反转版是 −mean）。
  横截面 winsorize 1/99 → 十分位做多残差赢家、做空残差输家，等权、美元中性 + β 中性、
  杠杆 overlay（2× 上限，10% 年化波动目标，5d/8% 熔断），成本 x1/x2（佣金+借券+融资）。
  Long-only? 否——市场中性 long-short（"残差动量"腿，与"多因子长偏"腿分开）。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .momentum_signals import _rebalance_mask, load_daily          # noqa: F401 (load_daily re-export)
from .residual_signals import (FACTOR_ETFS, DAYS_PER_WEEK, TRADING_DAYS,
                               ResidualDataGap, _factor_returns, _ols_beta)


@dataclass(frozen=True)
class ResidMomParams:
    # --- model (§3) --- residual momentum
    formation_weeks: int = 52         # F: 12M residual-return formation window; primary 52
    skip_weeks: int = 4               # skip most-recent 4w (~1M) to avoid short-term reversal
    estimation_weeks: int = 156       # E: rolling OLS window (3yr); primary 156
    min_obs_weeks: int = 104          # min valid weekly obs; else excluded
    factor_set: str = "3f"            # 3f primary (MKT+SMB+HML)
    winsor_pct: float = 0.01
    # --- portfolio (§4) --- identical to residual reversal
    cut: float = 0.10                 # decile long/short
    beta_neutral_tol: float = 0.05
    # --- leverage overlay (§5) --- identical
    gross_base: float = 2.0
    gross_cap: float = 2.0
    gross_floor: float = 0.5
    vol_target_annual: float = 0.10
    vol_window_weeks: int = 26
    breaker_dd: float = 0.08
    breaker_lookback_days: int = 5
    breaker_gross: float = 0.5
    # --- risk red-lines (§6) ---
    min_names_per_leg: int = 20
    max_name_frac_gross: float = 0.05
    # --- costs (§8) --- identical
    side_frac_base: float = 0.001
    borrow_annual: float = 0.005
    financing_annual: float = 0.068
    lever: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _rebalance_weights_mom(wret: np.ndarray, F: np.ndarray, params: ResidMomParams,
                           sectors: np.ndarray | None):
    """残差动量的横截面权重。与 residual_signals._rebalance_weights 唯一差异：
    (a) 形成窗跳过最近 skip 周、长度 F 周；(b) signal = +mean(eps)（动量，非反转）。
    其余（winsorize / 十分位 / 美元+β 中性 / gross 归一）逐行一致。"""
    n_weeks, n_stocks = wret.shape
    Ew, Fw, Sk = params.estimation_weeks, params.formation_weeks, params.skip_weeks
    reb_w: dict[int, np.ndarray] = {}
    reb_diag: dict[int, dict] = {}

    for k in range(n_weeks):
        # 形成窗 [k-Sk-Fw+1, k-Sk]，估计窗 E 周以 k-Sk 结尾（≤ 决策周，无未来数据）
        f_hi = k - Sk + 1                         # exclusive
        f_lo = k - Sk - Fw + 1
        est_hi = k - Sk + 1                        # estimation ends at k-Sk (overlaps formation)
        est_lo = (k - Sk) - Ew + 1
        if f_lo < 0 or est_lo < 0:
            continue
        f_slice = F[f_lo:f_hi, :]                  # formation weeks' factors
        Xest = np.column_stack([np.ones(est_hi - est_lo), F[est_lo:est_hi, :]])

        signal = np.full(n_stocks, np.nan)
        betas_mkt = np.full(n_stocks, np.nan)
        for j in range(n_stocks):
            coef = _ols_beta(wret[est_lo:est_hi, j], Xest, params.min_obs_weeks)
            if coef is None:
                continue
            rj = wret[f_lo:f_hi, j]
            if not np.all(np.isfinite(rj)) or not np.all(np.isfinite(f_slice)):
                continue
            fitted = coef[0] + f_slice @ coef[1:]
            eps = rj - fitted
            signal[j] = +float(np.mean(eps))       # residual MOMENTUM (winners high)
            betas_mkt[j] = float(coef[1])

        elig = np.flatnonzero(np.isfinite(signal))
        n_elig = int(elig.size)
        if n_elig < 2:
            continue

        if params.factor_set == "4f" and sectors is not None:
            for grp in np.unique(sectors[elig]):
                gmask = elig[sectors[elig] == grp]
                if gmask.size:
                    signal[gmask] = signal[gmask] - np.mean(signal[gmask])

        s_elig = signal[elig].astype(float)
        lo_q = np.quantile(s_elig, params.winsor_pct)
        hi_q = np.quantile(s_elig, 1.0 - params.winsor_pct)
        s_wins = np.clip(s_elig, lo_q, hi_q)

        n_leg = max(1, int(np.floor(params.cut * n_elig)))
        order = elig[np.argsort(-s_wins, kind="stable")]   # high signal (winner) first
        longs = order[:n_leg]                              # buy residual winners (momentum)
        shorts = order[-n_leg:]                            # short residual losers

        w = np.zeros(n_stocks)
        if n_leg > 0:
            w[longs] = 1.0 / n_leg
            w[shorts] = -1.0 / n_leg

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
            w *= params.gross_base / gross_raw

        reb_w[k] = w
        reb_diag[k] = {
            "n_eligible": n_elig, "n_per_leg": n_leg,
            "net_beta_mkt": float(net_beta), "beta_adj": beta_adj,
            "thin_book": bool(n_leg < params.min_names_per_leg),
            "gross_long": float(w[w > 0].sum()), "gross_short": float(-w[w < 0].sum()),
        }
    return reb_w, reb_diag


def residmom_curve(stock_frames: dict, factor_frames: dict, universe: list,
                   params: ResidMomParams, *, cost_mult: float = 1.0,
                   sectors: dict | None = None,
                   start: str | None = None, end: str | None = None) -> dict:
    """构建残差动量的 EVO-12 日频 cost-after 权益曲线。sim/成本/杠杆与
    residual_signals.residual_curve 逐行一致，仅权重来自 _rebalance_weights_mom。"""
    n_universe = len(universe)
    if n_universe == 0:
        raise ValueError("empty universe")
    if params.factor_set not in ("3f", "4f"):
        raise ValueError(f"unknown factor_set {params.factor_set!r}")

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
    warm = params.estimation_weeks + params.formation_weeks + params.skip_weeks + 4
    if n < warm * DAYS_PER_WEEK:
        raise ValueError("calendar shorter than estimation + formation + skip + margin")

    reb_mask = _rebalance_mask(cal, "weekly")
    reb_idx = np.flatnonzero(reb_mask)
    if len(reb_idx) < warm:
        raise ValueError("too few weekly rebalances for estimation+formation+skip window")

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
            f"3-factor primary口径 needs all of {list(FACTOR_ETFS)}; missing {factor_missing}.")

    sect = None
    if sectors is not None:
        sect = np.array([sectors.get(s, "NA") for s in universe])

    reb_w, reb_diag = _rebalance_weights_mom(wret, Fmat, params, sect)
    if not reb_w:
        raise ValueError("no rebalance produced eligible cross-section (need N >> K breadth)")
    reb_days = {int(reb_idx[k]): w for k, w in reb_w.items()}
    reb_days_diag = {int(reb_idx[k]): d for k, d in reb_diag.items()}
    reb_days_sorted = sorted(reb_days)

    def _decision(t: int):
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

    rows, gross_hist, weights_hist, netbeta_hist = [], [], [], []
    unit_ret_hist: list = []
    equity = 1.0
    equity_hist: list = [1.0]
    prev_sig = np.zeros(n_universe)
    cur_r = None
    ref_m = 1.0 / params.gross_base
    m = 1.0 if params.lever else ref_m

    for p in range(1, n - 1):
        t = p - 1
        r = _decision(t)
        if r is None:
            rows.append((cal[p + 1], 0.0, 0.0))
            gross_hist.append(0.0); netbeta_hist.append(0.0)
            weights_hist.append(np.zeros(n_universe)); unit_ret_hist.append(0.0)
            equity_hist.append(equity)
            continue
        w = reb_days[r]
        if r != cur_r:
            cur_r = r
            if params.lever:
                m_new = 1.0
                if len(unit_ret_hist) >= vol_win_days:
                    sd = float(np.std(unit_ret_hist[-vol_win_days:], ddof=1))
                    if sd > 0:
                        m_new = float(np.clip(vt_daily / sd, m_floor, m_cap))
                if len(equity_hist) > params.breaker_lookback_days:
                    tail = np.array(equity_hist[-(params.breaker_lookback_days + 1):])
                    dd = tail[-1] / np.max(tail) - 1.0
                    if dd <= -params.breaker_dd:
                        m_new = params.breaker_gross / params.gross_base
                m = m_new
            else:
                m = ref_m
        o_p, o_n = O[p, :], O[p + 1, :]
        tradable = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(n_universe)
        step[tradable] = o_n[tradable] / o_p[tradable] - 1.0
        w_eff = np.where(tradable, w, 0.0)
        unit_ret = float(np.dot(w_eff, step))
        sig_now = m * w_eff
        turnover = float(np.abs(sig_now - prev_sig).sum())
        gross_notional = float(np.abs(sig_now).sum())
        short_notional = float(np.abs(sig_now[sig_now < 0]).sum())
        commission = side * turnover
        borrow = borrow_daily * short_notional
        financing = fin_daily * max(0.0, gross_notional - 1.0)
        ret = m * unit_ret - commission - borrow - financing
        equity *= (1.0 + ret)
        rows.append((cal[p + 1], ret, turnover))
        gross_hist.append(gross_notional); netbeta_hist.append(reb_days_diag[r]["net_beta_mkt"])
        weights_hist.append(sig_now.copy()); unit_ret_hist.append(unit_ret)
        equity_hist.append(equity); prev_sig = sig_now

    if not rows:
        raise ValueError("no periods produced")
    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    equity_df = edf[["date", "ret", "equity", "traded_notional"]].copy()
    gross = np.array(gross_hist)
    ds = pd.DatetimeIndex(edf["date"])
    rr = edf["ret"].to_numpy(float)
    trade_log = []
    i, N = 0, len(edf)
    active = np.array([_decision(i) if _decision(i) is not None else -1 for i in range(N)])
    while i < N:
        if active[i] < 0:
            i += 1; continue
        j, comp = i, 1.0
        cur = active[i]
        while j < N and active[j] == cur:
            comp *= (1.0 + rr[j]); j += 1
        trade_log.append({"pnl": float(comp - 1.0), "entry": str(ds[i].date()),
                          "exit": str(ds[j - 1].date()), "hold_days": int(j - i)})
        i = j

    present = [s for s in universe if stock_frames.get(s) is not None and len(stock_frames.get(s))]
    missing = [s for s in universe if s not in present]
    n_per_leg = [d["n_per_leg"] for d in reb_days_diag.values()]
    thin_weeks = int(sum(1 for d in reb_days_diag.values() if d["thin_book"]))
    diagnostics = {
        "candidate": "residual_momentum",
        "signal_convention": f"+mean(eps) over F={params.formation_weeks}w skip={params.skip_weeks}w, "
                             f"betas E={params.estimation_weeks}w ending at k-skip (no future)",
        "factor_set": params.factor_set, "cost_mult": cost_mult, "levered": params.lever,
        "n_periods": int(len(edf)), "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "n_rebalances": len(reb_days),
        "mean_names_per_leg": float(np.mean(n_per_leg)) if n_per_leg else 0.0,
        "min_names_per_leg": int(np.min(n_per_leg)) if n_per_leg else 0,
        "thin_book_weeks": thin_weeks, "min_names_per_leg_required": params.min_names_per_leg,
        "any_thin_book": bool(thin_weeks > 0),
        "mean_gross": float(np.mean(gross[gross > 0])) if (gross > 0).any() else 0.0,
        "max_gross": float(gross.max()) if len(gross) else 0.0,
        "mean_abs_net_beta": float(np.mean(np.abs(netbeta_hist))) if netbeta_hist else 0.0,
        "max_abs_net_beta": float(np.max(np.abs(netbeta_hist))) if netbeta_hist else 0.0,
        "n_trades": len(trade_log),
        "factor_etfs_present": [s for s in FACTOR_ETFS if factor_frames.get(s) is not None
                                and len(factor_frames.get(s))],
        "factor_etfs_missing": factor_missing,
        "universe_frozen": list(universe), "universe_present": present, "universe_missing": missing,
        "data_complete": bool(not missing and not factor_missing),
        "return_convention": "open-to-open; weekly weights decided at close(T), executed open(T+1)",
    }
    weights_df = pd.DataFrame(np.vstack(weights_hist), columns=list(universe))
    weights_df.insert(0, "date", ds)
    return {"equity_df": equity_df, "trade_log": trade_log, "diagnostics": diagnostics,
            "gross_series": pd.DataFrame({"date": ds, "gross": gross}),
            "net_beta_series": pd.DataFrame({"date": ds, "net_beta_mkt": netbeta_hist}),
            "weights_df": weights_df}

"""EVO-8 方向(b) candidate — multi-factor LONG-BIAS + 趋势 overlay。

Qlib（`tools.qlib_gen.factor_export`）出 tidy factors(`datetime,instrument,factor,value`)
→ 本 adapter 横截面 z-score 合成 → 做多 top 分位（long-tilted，无做空、无杠杆）→ 组合级
200d 趋势闸控回撤 → 日频 open-to-open cost-after 权益曲线（EVO-12 列），灌 `research/gate.certify()`。

判据零重实现、不自建门；Qlib 只当因子源、永不作判据（kernels=1）。

因子方向（预注册冻结；+ 表示做多高值、− 表示做多低值）：
  mom12_1(+) mom6_1(+) 12-1/6-1 动量；prox52w(+) 距 52 周高；trend200(+) 200d MA 之上；
  rev21(−) 短期反转（做多近月弱者）；vol60(−) vol120(−) 低波异象；ltrev(−) 长期反转/价值代理。
合成分 = mean( 方向·zscore(factor) )，横截面按 winsor 后 z。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .momentum_signals import _rebalance_mask, load_daily  # noqa: F401

TRADING_DAYS = 252

# 因子方向（+1 做多高值 / −1 做多低值）——预注册冻结
FACTOR_DIRECTION = {
    "mom12_1": +1, "mom6_1": +1, "prox52w": +1, "trend200": +1,
    "rev21": -1, "vol60": -1, "vol120": -1, "ltrev": -1,
}


@dataclass(frozen=True)
class MultiFactorParams:
    cut: float = 0.10                 # 做多 top 分位（decile 主格）
    rebalance: str = "monthly"
    winsor_pct: float = 0.01
    trend_ma_days: int = 200          # 组合级趋势闸：SPY 在 200d MA 之上满仓、之下降敞口
    risk_off_exposure: float = 0.0    # SPY < 200dMA 时的敞口（0 = 全撤到现金，absolute-momentum 闸）
    long_exposure: float = 1.0        # 满仓多头敞口（long-only，无杠杆）
    side_frac_base: float = 0.001     # 10bps/side × cost_mult
    min_names: int = 20               # 低于此判 thin，标注不达标

    def to_dict(self) -> dict:
        return asdict(self)


def _zscore_winsor(x: np.ndarray, wp: float) -> np.ndarray:
    m = np.isfinite(x)
    if m.sum() < 3:
        return np.full_like(x, np.nan, dtype=float)
    lo, hi = np.nanquantile(x[m], wp), np.nanquantile(x[m], 1 - wp)
    xc = np.clip(x, lo, hi)
    mu, sd = np.nanmean(xc[m]), np.nanstd(xc[m])
    z = np.full_like(x, np.nan, dtype=float)
    if sd > 0:
        z[m] = (xc[m] - mu) / sd
    return z


def composite_scores(factors_df: pd.DataFrame, universe: list, factors_subset=None) -> pd.DataFrame:
    """从 tidy factors 造横截面合成分：index=datetime, columns=instrument, value=composite。
    factors_subset 给定时只用该子集（做单因子试验 Sharpe / DSR 的 V）。"""
    fdf = factors_df[factors_df["instrument"].isin(set(universe))].copy()
    fdf["datetime"] = pd.to_datetime(fdf["datetime"]).dt.normalize()
    pool = factors_subset if factors_subset else list(FACTOR_DIRECTION)
    used = [f for f in pool if f in set(fdf["factor"].unique())]
    if not used:
        raise ValueError("factors.parquet 不含任何预注册因子")
    # per (datetime, factor): 横截面 z（含方向），再对因子取均值
    comp = None
    for f in used:
        sub = fdf[fdf["factor"] == f].pivot_table(index="datetime", columns="instrument",
                                                  values="value", aggfunc="last")
        sub = sub.reindex(columns=universe)
        z = sub.apply(lambda row: _zscore_winsor(row.to_numpy(float), 0.01), axis=1,
                      result_type="expand")
        z.columns = sub.columns
        z = z * FACTOR_DIRECTION[f]
        comp = z if comp is None else comp.add(z, fill_value=np.nan)
    comp = comp / len(used)
    return comp, used


def multifactor_curve(factors_df: pd.DataFrame, stock_frames: dict, spy_frame: pd.DataFrame,
                      universe: list, params: MultiFactorParams, *, cost_mult: float = 1.0,
                      start: str = None, end: str = None, factors_subset=None) -> dict:
    """合成分 → 做多 top 分位 + 200d 趋势闸 → 日频 open-to-open 净值。
    factors_subset 给定时用单/子因子（做每因子试验 Sharpe，喂 DSR 的 V）。"""
    comp, used_factors = composite_scores(factors_df, universe, factors_subset=factors_subset)

    # union daily calendar
    all_dates = set()
    for s in universe:
        df = stock_frames.get(s)
        if df is not None and len(df):
            all_dates.update(pd.to_datetime(df["date"]).tolist())
    if spy_frame is not None:
        all_dates.update(pd.to_datetime(spy_frame["date"]).tolist())
    cal = pd.DatetimeIndex(sorted(all_dates))
    if start:
        cal = cal[cal >= pd.Timestamp(start)]
    if end:
        cal = cal[cal <= pd.Timestamp(end)]
    n = len(cal)
    if n < params.trend_ma_days + 40:
        raise ValueError("calendar too short")

    nu = len(universe)
    O = np.full((n, nu), np.nan)
    for j, s in enumerate(universe):
        df = stock_frames.get(s)
        if df is None or not len(df):
            continue
        d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"]).dt.normalize()))
        d = d[~d.index.duplicated(keep="last")].reindex(cal)
        O[:, j] = d["open"].to_numpy(float)

    # SPY 200d 趋势闸（收盘 vs 200d MA），causal
    spy = spy_frame.set_index(pd.DatetimeIndex(pd.to_datetime(spy_frame["date"]).dt.normalize()))
    spy = spy[~spy.index.duplicated(keep="last")].reindex(cal)
    spy_close = spy["close"].to_numpy(float)
    spy_ma = pd.Series(spy_close).rolling(params.trend_ma_days, min_periods=params.trend_ma_days).mean().to_numpy()
    trend_on = spy_close > spy_ma   # True → risk-on

    reb_idx = np.flatnonzero(_rebalance_mask(cal, params.rebalance))
    comp_dates = comp.index

    # decide target weights at each monthly rebalance close t (info as of t)
    reb_w = {}
    for t in reb_idx:
        d_t = cal[t]
        # 最近一个 <= d_t 的合成分横截面
        avail = comp_dates[comp_dates <= d_t]
        if len(avail) == 0:
            continue
        row = comp.loc[avail[-1]].reindex(universe).to_numpy(float)
        elig = np.flatnonzero(np.isfinite(row))
        if elig.size < 5:
            continue
        n_long = max(1, int(np.floor(params.cut * elig.size)))
        order = elig[np.argsort(-row[elig], kind="stable")]   # 高合成分在前
        longs = order[:n_long]
        expo = params.long_exposure if (t < len(trend_on) and bool(trend_on[t])) else params.risk_off_exposure
        w = np.zeros(nu)
        if n_long > 0 and expo > 0:
            w[longs] = expo / n_long
        reb_w[int(t)] = w
    reb_sorted = sorted(reb_w)
    if not reb_sorted:
        raise ValueError("no rebalance produced eligible cross-section")

    def _wfor(t):
        r = None
        for ri in reb_sorted:
            if ri <= t:
                r = ri
            else:
                break
        return reb_w[r] if r is not None else np.zeros(nu)

    side = params.side_frac_base * cost_mult
    rows, gross_hist, nlong_hist = [], [], []
    prev = np.zeros(nu)
    for p in range(1, n - 1):
        w = _wfor(p - 1)
        o_p, o_n = O[p, :], O[p + 1, :]
        tr = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(nu)
        step[tr] = o_n[tr] / o_p[tr] - 1.0
        w_eff = np.where(tr, w, 0.0)
        gross = float(np.dot(w_eff, step))
        turnover = float(np.abs(w_eff - prev).sum())
        ret = gross - side * turnover
        rows.append((cal[p + 1], ret, turnover))
        gross_hist.append(float(w_eff.sum()))
        nlong_hist.append(int((w_eff > 0).sum()))
        prev = w_eff

    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    ds = pd.DatetimeIndex(edf["date"])
    gross = np.array(gross_hist)
    nlong = np.array(nlong_hist)

    # trade log: contiguous invested spells
    rr = edf["ret"].to_numpy(float)
    tl, i, N = [], 0, len(edf)
    while i < N:
        if gross[i] <= 1e-9:
            i += 1; continue
        j, comp_ret = i, 1.0
        while j < N and gross[j] > 1e-9:
            comp_ret *= (1.0 + rr[j]); j += 1
        tl.append({"pnl": float(comp_ret - 1.0), "entry": str(ds[i].date()),
                   "exit": str(ds[j - 1].date()), "hold_days": int(j - i)})
        i = j

    present = [s for s in universe if stock_frames.get(s) is not None and len(stock_frames.get(s))]
    diagnostics = {
        "candidate": "multifactor_longbias", "cost_mult": cost_mult,
        "n_periods": int(len(edf)), "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "n_rebalances": len(reb_w), "used_factors": used_factors,
        "mean_n_long_when_on": float(nlong[gross > 0].mean()) if (gross > 0).any() else 0.0,
        "min_n_long_when_on": int(nlong[gross > 0].min()) if (gross > 0).any() else 0,
        "frac_days_risk_on": float(np.mean(gross > 0)),
        "mean_gross_when_on": float(gross[gross > 0].mean()) if (gross > 0).any() else 0.0,
        "trend_overlay": f"SPY>{params.trend_ma_days}dMA → {params.long_exposure}x, else {params.risk_off_exposure}x",
        "universe_present": present, "universe_frozen_size": nu,
        "return_convention": "open-to-open; monthly weights close(T)→open(T+1); long-only no leverage",
        "any_thin": bool((gross > 0).any() and nlong[gross > 0].min() < params.min_names),
    }
    return {"equity_df": edf[["date", "ret", "equity", "traded_notional"]].copy(),
            "trade_log": tl, "diagnostics": diagnostics}

"""EVO-8 方向(b) 候选 A — 利率 carry（曲线陡度调久期）信号适配，从零写。

机制：陡度 slope=DGS10−DGS2。曲线陡 ⇒ 期限溢价+roll-down 大 ⇒ 上久期；平/倒挂 ⇒ 退短久期。
  slope≥hi → TLT（长久期）; lo≤slope<hi → IEF（中）; slope<lo → SHY（短，避久期）。
单资产 100%、**long/flat 调久期、绝不做空债**（无裸空）；月度再平衡、open(T+1) 执行、open-to-open。
判据不重实现；曲线净收益直灌 research/gate.certify()（信号从零，不接 VIX carry）。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .momentum_signals import _rebalance_mask, load_daily  # noqa: F401

CASH = "CASH"


@dataclass(frozen=True)
class CarryRatesParams:
    hi_thresh: float = 0.50           # slope≥hi → 长久期 TLT（%）
    lo_thresh: float = 0.00           # slope<lo → 短久期 SHY（%）
    long_asset: str = "TLT"
    mid_asset: str = "IEF"
    short_asset: str = "BIL"   # SHY 出口封锁不可得 → BIL(1-3M) 承担短久期/避险腿（工部 2026-07-29 裁定）
    rebalance: str = "monthly"
    side_frac_base: float = 0.001     # 10bps/side ×cost_mult
    leverage: float = 1.0             # ≤2x 预注册；本候选 1.0×

    @property
    def assets(self) -> list:
        return [self.long_asset, self.mid_asset, self.short_asset]

    def to_dict(self) -> dict:
        return asdict(self)


def _choose(slope: float, p: CarryRatesParams) -> str:
    if not np.isfinite(slope):
        return CASH
    if slope >= p.hi_thresh:
        return p.long_asset
    if slope >= p.lo_thresh:
        return p.mid_asset
    return p.short_asset


def carry_rates_curve(slope_series: pd.DataFrame, stock_frames: dict, universe: list,
                      params: CarryRatesParams, *, cost_mult: float = 1.0,
                      start: str = None, end: str = None) -> dict:
    """slope_series: DataFrame[date, slope]（%）。stock_frames: {SHY/IEF/TLT: load_daily 帧}。
    返回 EVO-12 日频 cost-after 权益曲线 + trade_log + diagnostics。"""
    idx = {s: i for i, s in enumerate(universe)}
    all_dates = set()
    for s in universe:
        df = stock_frames.get(s)
        if df is not None and len(df):
            all_dates.update(pd.to_datetime(df["date"]).tolist())
    if not all_dates:
        raise ValueError("no ETF price data")
    cal = pd.DatetimeIndex(sorted(all_dates))
    if start:
        cal = cal[cal >= pd.Timestamp(start)]
    if end:
        cal = cal[cal <= pd.Timestamp(end)]
    n = len(cal)
    if n < 40:
        raise ValueError("calendar too short")

    O = np.full((n, len(universe)), np.nan)
    for j, s in enumerate(universe):
        df = stock_frames.get(s)
        if df is None or not len(df):
            continue
        d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"]).dt.normalize()))
        d = d[~d.index.duplicated(keep="last")].reindex(cal)
        O[:, j] = d["open"].to_numpy(float)

    # slope 对齐到日历（causal：用 ≤ t 的最近一条）
    ss = slope_series.copy()
    ss["date"] = pd.to_datetime(ss["date"]).dt.normalize()
    ss = ss.sort_values("date").drop_duplicates("date").set_index("date")
    slope_daily = ss["slope"].reindex(cal).ffill().to_numpy(float)

    reb_idx = np.flatnonzero(_rebalance_mask(cal, params.rebalance))
    reb_choice = {}
    for t in reb_idx:
        reb_choice[int(t)] = _choose(slope_daily[t] if t < len(slope_daily) else np.nan, params)
    reb_sorted = sorted(reb_choice)
    if not reb_sorted:
        raise ValueError("no rebalance produced")

    def _cfor(t):
        r = None
        for ri in reb_sorted:
            if ri <= t:
                r = ri
            else:
                break
        return reb_choice[r] if r is not None else CASH

    side = params.side_frac_base * cost_mult
    rows, choice_hist = [], []
    prev = np.zeros(len(universe))
    for p in range(1, n - 1):
        choice = _cfor(p - 1)
        w = np.zeros(len(universe))
        if choice != CASH and choice in idx:
            w[idx[choice]] = params.leverage
        o_p, o_n = O[p, :], O[p + 1, :]
        tr = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(len(universe))
        step[tr] = o_n[tr] / o_p[tr] - 1.0
        w_eff = np.where(tr, w, 0.0)
        turnover = float(np.abs(w_eff - prev).sum())
        ret = float(np.dot(w_eff, step)) - side * turnover
        eff = choice if w_eff.sum() > 0 else CASH
        rows.append((cal[p + 1], ret, turnover))
        choice_hist.append(eff)
        prev = w_eff

    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    ds = pd.DatetimeIndex(edf["date"])
    rr = edf["ret"].to_numpy(float)
    ch = np.array(choice_hist)

    trade_log, i, N = [], 0, len(edf)
    while i < N:
        cur = ch[i]
        if cur == CASH:
            i += 1; continue
        j, comp = i, 1.0
        while j < N and ch[j] == cur:
            comp *= (1.0 + rr[j]); j += 1
        trade_log.append({"pnl": float(comp - 1.0), "asset": cur, "entry": str(ds[i].date()),
                          "exit": str(ds[j - 1].date()), "hold_days": int(j - i)})
        i = j

    def _frac(a):
        return float(np.mean(ch == a))
    present = [s for s in universe if stock_frames.get(s) is not None and len(stock_frames.get(s))]
    diagnostics = {
        "candidate": "carry_rates", "cost_mult": cost_mult,
        "n_periods": int(len(edf)), "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "n_rebalances": len(reb_choice),
        "alloc_frac": {a: _frac(a) for a in params.assets}, "cash_frac": _frac(CASH),
        "n_switches": len(trade_log),
        "thresholds": {"hi": params.hi_thresh, "lo": params.lo_thresh},
        "universe_present": present, "universe_frozen": list(universe),
        "return_convention": "open-to-open; monthly close(T)→open(T+1); long/flat duration, no short",
    }
    return {"equity_df": edf[["date", "ret", "equity", "traded_notional"]].copy(),
            "trade_log": trade_log, "diagnostics": diagnostics,
            "alloc_df": pd.DataFrame({"date": ds, "choice": choice_hist})}

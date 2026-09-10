"""EVO-8 方向(b) candidate — GEM (Global Equity Momentum, Antonacci 2014) 信号适配。

GEM = 双动量（dual momentum）资产轮动，规则型择时，**不走发现引擎**（工部尚书
2026-07-24 (b)#1：GEM 立刻开工不等 Qlib）。这是本候选唯一的新建模代码；判据全部
复用 EVO-149/EVO-130 的 `events/{gates,significance,multiple_testing,metrics}` 与
`swing.evaluate.evaluate_curve`，此处不重实现任何指标。

规则（月度再平衡，12 个月回看，close→次 open 执行，全部预注册冻结于
`GEM_EVAL_PREREGISTRATION.md`）：
  在每个再平衡日 close(T)：
    绝对动量闸：若 mom_US(T) > mom_TBILL(T)  → risk-on
        相对动量：在 US(SPY) 与 ex-US(VEU) 中取 12m 动量更高者，100% 持有
    否则（US 12m 动量不及 T-bill）        → risk-off，100% 持有综合债券(AGG)
  单资产、100% 权重、long-only、无杠杆、无做空。T-bill 仅作绝对动量闸的门槛
  （不持有）；risk-off 的避险仓是 AGG，非 T-bill（Antonacci GEM 原版口径）。

执行/反前视（hard gate #2）：权重在 close(T) 决定，只能从 open(T+1) 起交易；
持仓收益 open-to-open：`open(p+1)/open(p) - 1`，成本在再平衡的 open(T+1) 按换手计。
成本 = side_frac_base(10bps/side) × cost_mult × 换手（与动量 sleeve 同一 CostModel）。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .momentum_signals import load_daily, _rebalance_mask, DAYS_PER_MONTH  # 复用同一约定

CASH = "CASH"


@dataclass(frozen=True)
class GemParams:
    lookback_months: int = 12          # 文献惯例（Antonacci 2014）；no-fit
    us: str = "SPY"                    # 美股
    intl: str = "VEU"                 # 非美发达+新兴（FTSE All-World ex-US）
    bond: str = "AGG"                 # 综合债券（risk-off 避险仓）
    tbill: str = "BIL"                # 绝对动量门槛（不持有）
    rebalance: str = "monthly"
    side_frac_base: float = 0.001      # 10 bps/side；×cost_mult

    @property
    def lookback_days(self) -> int:
        return int(self.lookback_months * DAYS_PER_MONTH)

    @property
    def held_assets(self) -> list:
        return [self.us, self.intl, self.bond]

    @property
    def all_symbols(self) -> list:
        return [self.us, self.intl, self.bond, self.tbill]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lookback_days"] = self.lookback_days
        return d


def gem_curve(frames_by_symbol: dict, params: GemParams, *, cost_mult: float = 1.0,
              start: str | None = None, end: str | None = None) -> dict:
    """构建 GEM 的 EVO-12 日频 cost-after 权益曲线。

    返回 {equity_df, trade_log, diagnostics, alloc_df}；equity_df 直接喂 evaluate_curve。
    单资产轮动：每期权重是 SPY/VEU/AGG 之一的 one-hot（避险或不可交易时为现金）。
    """
    syms = params.all_symbols
    held = params.held_assets                          # 可持有资产（不含 T-bill）
    held_idx = {s: i for i, s in enumerate(syms)}

    # 并集日历
    all_dates = set()
    for s in syms:
        df = frames_by_symbol.get(s)
        if df is not None and len(df):
            all_dates.update(pd.to_datetime(df["date"]).tolist())
    if not all_dates:
        raise ValueError("no price data for any GEM symbol")
    cal = pd.DatetimeIndex(sorted(all_dates))
    if start is not None:
        cal = cal[cal >= pd.Timestamp(start)]
    if end is not None:
        cal = cal[cal <= pd.Timestamp(end)]
    n = len(cal)
    if n < params.lookback_days + 5:
        raise ValueError("calendar shorter than lookback + margin")

    # 对齐 open/close 矩阵 (n × len(syms))
    O = np.full((n, len(syms)), np.nan)
    C = np.full((n, len(syms)), np.nan)
    for j, s in enumerate(syms):
        df = frames_by_symbol.get(s)
        if df is None or not len(df):
            continue
        d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"]).dt.normalize()))
        d = d[~d.index.duplicated(keep="last")].reindex(cal)
        O[:, j] = d["open"].to_numpy(float)
        C[:, j] = d["close"].to_numpy(float)

    L = params.lookback_days
    mom = np.full((n, len(syms)), np.nan)
    mom[L:, :] = C[L:, :] / C[:-L, :] - 1.0

    reb_mask = _rebalance_mask(cal, params.rebalance)
    side = params.side_frac_base * cost_mult

    i_us, i_intl, i_bond, i_tb = (held_idx[params.us], held_idx[params.intl],
                                  held_idx[params.bond], held_idx[params.tbill])

    # ---- 每个再平衡 close 决定目标资产（信息截至 close t） ---- #
    reb_choice: dict[int, str] = {}       # t -> 选中的可持有符号（或 CASH）
    for t in np.flatnonzero(reb_mask):
        if t < L:
            continue
        r_us, r_intl, r_bond, r_tb = mom[t, i_us], mom[t, i_intl], mom[t, i_bond], mom[t, i_tb]
        hurdle = r_tb if np.isfinite(r_tb) else 0.0     # T-bill 缺失则退化为 0（绝对动量对现金）
        choice = CASH
        if np.isfinite(r_us) and r_us > hurdle:
            # risk-on：US vs ex-US 相对动量取高
            cand = [(r_us, params.us)]
            if np.isfinite(r_intl):
                cand.append((r_intl, params.intl))
            choice = max(cand, key=lambda x: x[0])[1]
        else:
            # risk-off：综合债券避险
            choice = params.bond if np.isfinite(r_bond) else CASH
        reb_choice[int(t)] = choice

    reb_sorted = sorted(reb_choice)

    def _choice_for(t: int) -> str:
        r = None
        for ri in reb_sorted:
            if ri <= t:
                r = ri
            else:
                break
        return reb_choice[r] if r is not None else CASH

    # ---- open-to-open 日频模拟 ---- #
    rows, choice_hist = [], []
    prev_w = np.zeros(len(syms))
    for p in range(1, n - 1):
        t = p - 1
        choice = _choice_for(t)
        w = np.zeros(len(syms))
        if choice != CASH:
            w[held_idx[choice]] = 1.0
        o_p, o_n = O[p, :], O[p + 1, :]
        tradable = np.isfinite(o_p) & np.isfinite(o_n) & (o_p > 0)
        step = np.zeros(len(syms))
        step[tradable] = o_n[tradable] / o_p[tradable] - 1.0
        w_eff = np.where(tradable, w, 0.0)              # 持仓不可交易 ⇒ 当日现金
        gross_ret = float(np.dot(w_eff, step))
        turnover = float(np.abs(w_eff - prev_w).sum())
        r = gross_ret - side * turnover
        eff_choice = choice if w_eff.sum() > 0 else CASH
        rows.append((cal[p + 1], r, turnover))
        choice_hist.append(eff_choice)
        prev_w = w_eff

    if not rows:
        raise ValueError("no periods produced")
    edf = pd.DataFrame(rows, columns=["date", "ret", "traded_notional"])
    edf["equity"] = np.cumprod(1.0 + edf["ret"].to_numpy(float))
    equity_df = edf[["date", "ret", "equity", "traded_notional"]].copy()

    ds = pd.DatetimeIndex(edf["date"])
    rr = edf["ret"].to_numpy(float)

    # trade_log：一个"trade"=持有同一资产的连续区间（换仓即结束）
    trade_log = []
    i, N = 0, len(edf)
    while i < N:
        cur = choice_hist[i]
        if cur == CASH:
            i += 1
            continue
        j, comp = i, 1.0
        while j < N and choice_hist[j] == cur:
            comp *= (1.0 + rr[j])
            j += 1
        trade_log.append({"pnl": float(comp - 1.0), "asset": cur,
                          "entry": str(ds[i].date()), "exit": str(ds[j - 1].date()),
                          "hold_days": int(j - i)})
        i = j

    # 配置占比诊断
    ch = np.array(choice_hist)
    def _frac(sym):
        return float(np.mean(ch == sym))
    present = [s for s in syms if frames_by_symbol.get(s) is not None and len(frames_by_symbol.get(s))]
    missing = [s for s in syms if s not in present]
    diagnostics = {
        "candidate": "GEM_dual_momentum",
        "cost_mult": cost_mult,
        "n_periods": int(len(edf)),
        "first_date": str(ds[0].date()), "last_date": str(ds[-1].date()),
        "alloc_frac": {params.us: _frac(params.us), params.intl: _frac(params.intl),
                       params.bond: _frac(params.bond), "CASH": _frac(CASH)},
        "n_rebalances": int(len(reb_choice)),
        "n_switches": int(len(trade_log)),
        "symbols": syms, "held_assets": held, "tbill_hurdle_asset": params.tbill,
        "universe_present": present, "universe_missing": missing,
        "data_complete": bool(not missing),
        "return_convention": "open-to-open; weights decided at close(T), executed open(T+1)",
    }
    alloc_df = pd.DataFrame({"date": ds, "choice": choice_hist})
    return {"equity_df": equity_df, "trade_log": trade_log,
            "diagnostics": diagnostics, "alloc_df": alloc_df}

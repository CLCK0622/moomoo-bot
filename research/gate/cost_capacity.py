"""
cost_capacity.py —— 成本 x1x2 + 容量/ADV 早筛

自动挖出的因子多是高换手微结构噪声，死在成本上。把成本门放在**贵的 OOS/DSR 之前**先杀一批，
性价比最高。成本双档：x1=moomoo 零售现实基线，x2=翻倍压力档。

- apply_costs(): 从毛收益按换手扣成本 → 净收益。
- cost_stress_gate(): x1 净 Sharpe<=0 直接早杀；再要求 x1→x2 不使 Sharpe 翻负（鲁棒）。
- capacity_gate(): 所需成交额 / ADV 超上限即拒（零售体量也要建模）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd


# 冻结 cost_model 标签 → 该模型下每单位换手的**权威** x1 成本（每期，比例，单向）。
# 口径对齐本项目已冻结、且用来判过所有候选的 EVO-12 CostModel：**10 bps/单向 = 5 佣金 + 5 滑点**
# （见 qlab/qlab/swing/evaluate.py CostModel.side_frac、momentum/carry/residual_signals 的 side_frac_base=0.001）。
# GEM/残差反转/残差动量的 verdict 全在此 10bps ×1/×2 基准下判出——门地板必须与之一致，否则门比产出判决的
# harness 还松一档。x2 压力档由 cost_stress_gate 内部 ×2，不写这里。
# ⚠️ 若将来候选去做流动性差的票，再按 universe 的 spread/ADV 从免费数据推导上调（都察院/工部把关）。
COST_MODELS = {
    "moomoo_retail_x1": 0.001,   # 10 bps / 单向换手（EVO-12 CostModel：5 佣金 + 5 滑点）
}


def resolve_cost_per_turnover(frozen_cost_model, self_reported=None) -> float:
    """
    以**冻结 cost_model 标签**为地板：effective = max(registry[label], 自报)。
    自报只能更贵不能更便宜（对称于 N/V 的台账地板）；未知标签 → KeyError（预注册完整性问题，
    fail-closed，不许用未登记的便宜成本模型蒙混）。自报 None → 直接用地板。
    """
    if frozen_cost_model not in COST_MODELS:
        raise KeyError(frozen_cost_model)
    floor = COST_MODELS[frozen_cost_model]
    return max(floor, self_reported if self_reported is not None else 0.0)


def apply_costs(gross_returns: Sequence[float], turnover: Sequence[float],
                cost_per_turnover: float, multiplier: float = 1.0) -> pd.Series:
    """
    net_t = gross_t - turnover_t * cost_per_turnover * multiplier
    cost_per_turnover：单位换手的成本（佣金+费+半价差滑点+借券/融资，折算成比例）。
    turnover_t：第 t 期换手率（单边或双边需与 cost_per_turnover 口径一致）。
    """
    g = np.asarray(gross_returns, dtype=float)
    to = np.asarray(turnover, dtype=float)
    if len(g) != len(to):
        raise ValueError("gross_returns 与 turnover 长度须一致")
    net = g - to * cost_per_turnover * multiplier
    return pd.Series(net)


def _sharpe_pp(returns: pd.Series) -> float:
    if len(returns) < 2:
        return float("nan")
    sd = returns.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return returns.mean() / sd


@dataclass
class CostStressResult:
    sharpe_x1: float
    sharpe_x2: float
    passed_early: bool     # x1 净 Sharpe > 0（早筛存活）
    robust: bool           # x2 下仍 > 0（成本鲁棒）


def cost_stress_gate(gross_returns: Sequence[float], turnover: Sequence[float],
                     cost_per_turnover: float) -> CostStressResult:
    net_x1 = apply_costs(gross_returns, turnover, cost_per_turnover, 1.0)
    net_x2 = apply_costs(gross_returns, turnover, cost_per_turnover, 2.0)
    s1 = _sharpe_pp(net_x1)
    s2 = _sharpe_pp(net_x2)
    passed_early = (not np.isnan(s1)) and s1 > 0
    robust = (not np.isnan(s2)) and s2 > 0
    return CostStressResult(sharpe_x1=s1, sharpe_x2=s2,
                            passed_early=passed_early, robust=robust)


@dataclass
class CapacityResult:
    participation: float   # 所需成交额 / ADV
    passed: bool


def capacity_gate(required_notional: float, adv_notional: float,
                  max_participation: float = 0.10) -> CapacityResult:
    """
    零售体量下容量很少 binding，但仍建模：单标的日成交额不得超过 ADV 的 max_participation。
    required_notional / adv_notional > max_participation → 拒。
    """
    if adv_notional <= 0:
        return CapacityResult(participation=float("inf"), passed=False)
    part = required_notional / adv_notional
    return CapacityResult(participation=part, passed=part <= max_participation)

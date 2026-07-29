"""
metrics.py —— 净值口径与联合门 (candidate-agnostic)

所有指标都在 **净收益序列**（已扣成本/融资）上计算，口径钉死、可追问：
- CAGR : 几何年化 = (E_end / E_start) ** (periods_per_year / n_obs) - 1
- MDD  : 日净值峰谷最大回撤（返回正数幅度）
- Sharpe(ann) : mean/std * sqrt(periods_per_year)（rf 可选）
- MAR  : CAGR / MDD

官方门 = Kevin 原定 50/20 联合门（即时上报触发器）。
影子门 = 首辅 2026-07-29 裁定的分层线：组合级 25–35%/<20% 上报门、15–20% 兜底。

危机子窗（2008 GFC / 2020 COVID / 2022 加息）单独取 MDD/CAGR，防止把危机回撤稀释掉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = 252

# 默认危机子窗（可覆盖）。取较宽的 peak→recovery 区间，确保把危机全程包住。
DEFAULT_CRISIS_WINDOWS: Dict[str, Tuple[str, str]] = {
    "2008_GFC": ("2007-10-01", "2009-06-30"),
    "2020_COVID": ("2020-02-01", "2020-04-30"),
    "2022_RATE": ("2022-01-01", "2022-12-31"),
}


def _as_series(returns: Sequence[float], dates: Optional[Sequence] = None) -> pd.Series:
    s = pd.Series(np.asarray(returns, dtype=float))
    if dates is not None:
        s.index = pd.to_datetime(pd.Index(dates))
    return s


def equity_curve(returns: pd.Series, start: float = 1.0) -> pd.Series:
    """净值曲线 = start * cumprod(1 + r)。"""
    return start * (1.0 + returns).cumprod()


def cagr(returns: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    n = len(returns)
    if n == 0:
        return float("nan")
    eq = equity_curve(returns)
    total = float(eq.iloc[-1])
    if total <= 0:  # 破产 → 用 -100% 表达，不做复数开方
        return -1.0
    return total ** (periods_per_year / n) - 1.0


def max_drawdown(returns: pd.Series) -> float:
    """峰谷最大回撤，返回正数幅度（0.2 == -20%）。"""
    if len(returns) == 0:
        return float("nan")
    eq = equity_curve(returns)
    running_max = eq.cummax()
    dd = eq / running_max - 1.0
    return float(-dd.min())  # dd 全 <=0，取最负再翻正


def sharpe(returns: pd.Series, rf: float = 0.0,
           periods_per_year: int = PERIODS_PER_YEAR, annualized: bool = True) -> float:
    """rf 为**每期**无风险利率。annualized=False 返回每期 Sharpe（DSR 用）。"""
    if len(returns) < 2:
        return float("nan")
    excess = returns - rf
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    sr = excess.mean() / sd
    return sr * np.sqrt(periods_per_year) if annualized else sr


def mar(returns: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    mdd = max_drawdown(returns)
    if mdd == 0 or np.isnan(mdd):
        return float("nan")
    return cagr(returns, periods_per_year) / mdd


@dataclass
class GateThresholds:
    """两套并行口径的阈值。"""
    # 官方门（Kevin 原定，即时上报触发器）
    official_cagr: float = 0.50
    official_mdd: float = 0.20
    # 影子上报门（组合级）
    shadow_report_cagr: float = 0.25   # 25% 起进上报门
    shadow_mdd: float = 0.20
    # 影子兜底带（低于上报门但仍可辩护）
    shadow_floor_cagr: float = 0.15


def joint_gate(cagr_val: float, mdd_val: float, cagr_thresh: float, mdd_thresh: float) -> bool:
    """联合门：CAGR 与 MDD 必须**同时**达标，任一不过即 False。"""
    if np.isnan(cagr_val) or np.isnan(mdd_val):
        return False
    return (cagr_val >= cagr_thresh) and (mdd_val <= mdd_thresh)


@dataclass
class MetricsReport:
    n_obs: int
    cagr: float
    mdd: float
    sharpe_ann: float
    sharpe_per_period: float
    mar: float
    skew: float
    kurtosis: float                      # 非超额（正态=3）
    crisis: Dict[str, Dict[str, float]] = field(default_factory=dict)
    official_pass: bool = False
    shadow_report_pass: bool = False     # 过组合级上报门
    shadow_floor_pass: bool = False      # 过兜底带
    # 决策标签：'REPORT_5020' 直接清官方门 / 'DECISION_POINT' 过影子未过官方（带真实数字请 Kevin 拍验收线）/ 'FAIL'
    decision: str = "FAIL"

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def evaluate(returns: Sequence[float], dates: Optional[Sequence] = None,
             thresholds: Optional[GateThresholds] = None,
             crisis_windows: Optional[Dict[str, Tuple[str, str]]] = None,
             rf: float = 0.0, periods_per_year: int = PERIODS_PER_YEAR) -> MetricsReport:
    """在净收益序列上出全套指标 + 官方/影子双口径判定 + 危机子窗单报。"""
    th = thresholds or GateThresholds()
    s = _as_series(returns, dates)

    c = cagr(s, periods_per_year)
    m = max_drawdown(s)
    sr_ann = sharpe(s, rf, periods_per_year, annualized=True)
    sr_pp = sharpe(s, rf, periods_per_year, annualized=False)
    mr = mar(s, periods_per_year)
    sk = float(pd.Series(s.values).skew())
    ku = float(pd.Series(s.values).kurt()) + 3.0  # pandas.kurt 给超额峰度 → +3 变非超额

    crisis: Dict[str, Dict[str, float]] = {}
    windows = crisis_windows or DEFAULT_CRISIS_WINDOWS
    if dates is not None:
        for name, (lo, hi) in windows.items():
            mask = (s.index >= pd.Timestamp(lo)) & (s.index <= pd.Timestamp(hi))
            sub = s[mask]
            if len(sub) >= 2:
                crisis[name] = {
                    "n_obs": int(len(sub)),
                    "cagr": cagr(sub, periods_per_year),
                    "mdd": max_drawdown(sub),
                }
            else:
                # 样本没盖住该危机窗 → 标 tail-incomplete，不能背书
                crisis[name] = {"n_obs": int(len(sub)), "cagr": float("nan"),
                                "mdd": float("nan"), "tail_incomplete": 1.0}

    official = joint_gate(c, m, th.official_cagr, th.official_mdd)
    shadow_report = joint_gate(c, m, th.shadow_report_cagr, th.shadow_mdd)
    shadow_floor = joint_gate(c, m, th.shadow_floor_cagr, th.shadow_mdd)

    if official:
        decision = "REPORT_5020"          # 直接清官方门 → 即刻上报
    elif shadow_report:
        decision = "DECISION_POINT"       # 过影子未过官方 → 带真实数字请 Kevin 拍验收线
    else:
        decision = "FAIL"

    return MetricsReport(
        n_obs=len(s), cagr=c, mdd=m, sharpe_ann=sr_ann, sharpe_per_period=sr_pp,
        mar=mr, skew=sk, kurtosis=ku, crisis=crisis,
        official_pass=official, shadow_report_pass=shadow_report,
        shadow_floor_pass=shadow_floor, decision=decision,
    )

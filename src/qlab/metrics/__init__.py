"""指标计算模块 — 户部 EVO-12「回测口径、数据方案与指标门禁 v1.0」的可验证实现.

This package is the *computation* layer: every metric in v1.0 §2 and every gate in
v1.0 §3 is a pure, fixture-driven function with its own unit tests. The report layer
(`qlab.report`) only *assembles* these results into the B/C/D/E 评估卡 and prints the
gate verdicts — it does not redo any math.

All metrics are computed on the **post-cost** net-equity series (v1.0 §1 铁律 1).
"""

from .core import (
    CoreMetrics,
    compute_core_metrics,
    drawdown_durations,
    geometric_cagr,
    max_drawdown,
    returns_from_equity,
    sharpe,
    sortino,
)
from .gates import GateResult, GateVerdict, evaluate_gates
from .trades import closed_trade_pnls, trade_stats

__all__ = [
    "CoreMetrics",
    "compute_core_metrics",
    "returns_from_equity",
    "geometric_cagr",
    "max_drawdown",
    "drawdown_durations",
    "sharpe",
    "sortino",
    "closed_trade_pnls",
    "trade_stats",
    "GateResult",
    "GateVerdict",
    "evaluate_gates",
]

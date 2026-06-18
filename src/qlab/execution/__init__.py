"""Execution layer: signals → risk-checked orders → broker (paper / live).

Default-safe: dry-run / paper先行, real live ordering is off by default and gated by
both the execution mode and the moomoo gateway's own guardrails.
"""

from .broker import Broker, OrderResult, PaperBroker, Position
from .engine import ExecutionEngine, RunRecord
from .risk import Quote, RiskDecision, RiskManager
from .session import MarketFrame, build_frames, build_marks, run_execution, run_execution_path
from .signals import SignalSet, TargetSignal, load_signals, sanity_check

__all__ = [
    "Broker",
    "PaperBroker",
    "Position",
    "OrderResult",
    "RiskManager",
    "RiskDecision",
    "Quote",
    "ExecutionEngine",
    "RunRecord",
    "MarketFrame",
    "build_frames",
    "build_marks",
    "run_execution",
    "run_execution_path",
    "SignalSet",
    "TargetSignal",
    "load_signals",
    "sanity_check",
]

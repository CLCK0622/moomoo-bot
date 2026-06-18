"""High-level execution session wiring (used by the CLI and tests).

Builds the broker (paper by default), the RiskManager and the engine from
:class:`AppConfig`, derives marks for the signalled symbols, runs one reconcile
cycle and returns the :class:`RunRecord`. Marks come from the fixture data source
(deterministic, offline) so a paper run-through needs no live feed.
"""

from __future__ import annotations

from ..brokers.guardrails import KillSwitch
from ..config import AppConfig, load_config
from ..data.fixture import FixtureDataSource
from .broker import PaperBroker
from .engine import ExecutionEngine, RunRecord
from .risk import RiskManager
from .signals import SignalSet


def build_marks(
    symbols: list[str], fixtures_dir: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Return (last-close marks, prev-close) per symbol from the fixture source."""
    src = FixtureDataSource(fixtures_dir)
    marks: dict[str, float] = {}
    prev: dict[str, float] = {}
    for sym in symbols:
        bars = src.load(sym)
        if not bars:
            continue
        marks[sym] = bars[-1].close
        prev[sym] = bars[-2].close if len(bars) > 1 else bars[-1].close
    return marks, prev


def run_execution(
    sigset: SignalSet,
    config: AppConfig | None = None,
    *,
    mode: str | None = None,
) -> RunRecord:
    config = config or load_config()
    mode = mode or config.execution.mode
    kill = KillSwitch(config.moomoo.kill_switch_file)
    risk = RiskManager(config.risk, kill_switch=kill)

    if mode == "live":
        # Live routing is built explicitly; never the default. Importing here keeps
        # the live broker out of the paper/dry-run path entirely.
        from ..brokers.moomoo import MoomooTradeGateway
        from .moomoo_broker import MoomooExecutionBroker

        broker = MoomooExecutionBroker(MoomooTradeGateway(config.moomoo, kill_switch=kill))
    else:
        broker = PaperBroker(
            config.execution.initial_cash,
            slippage_bps=config.execution.slippage_bps,
            commission_per_trade=config.execution.commission_per_trade,
        )

    engine = ExecutionEngine(broker, risk, mode=mode)
    symbols = [s.symbol for s in sigset.signals]
    marks, prev = build_marks(symbols, config.fixtures_dir)
    return engine.run_cycle(sigset, marks, prev_closes=prev)

"""High-level execution session wiring (used by the CLI and tests).

Two entry points:

- :func:`run_execution` — a single reconcile cycle on the latest fixture bar. Handy
  for a one-shot snapshot, but a single cycle cannot exercise the *path-dependent*
  breakers (intraday loss, 20% drawdown, stale quote) because there is no equity
  series, no realised intraday P&L and no quote-age drift to feed them.
- :func:`run_execution_path` — the **multi-period driver**. It replays a sequence of
  market frames through ONE persistent :class:`RiskManager` + broker, threading the
  real equity series (→ peak/drawdown), the running intraday P&L vs the session
  baseline, and per-quote ages into every cycle. This is what makes the日内损失 /
  回撤熔断 / 行情过期 gates actually reachable in a real run rather than dormant on
  default inputs. A future live loop builds frames from the broker feed; here they
  come from the offline fixture history.

Marks come from the fixture data source (deterministic, offline) so a paper
run-through needs no live feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..brokers.guardrails import KillSwitch
from ..config import AppConfig, load_config
from ..data.fixture import FixtureDataSource
from .broker import Broker, PaperBroker
from .engine import ExecutionEngine, RunRecord
from .risk import RiskManager
from .signals import SignalSet


@dataclass
class MarketFrame:
    """One observed market step fed to a reconcile cycle.

    ``quote_ages`` is seconds since each symbol's quote was sourced. Offline fixture
    replay carries no feed latency (each bar *is* current at its own timestamp), so it
    defaults to 0.0; a live loop fills in the real age so the stale-quote breaker can
    fire when the feed stalls.
    """

    marks: dict[str, float]
    prev_closes: dict[str, float] = field(default_factory=dict)
    quote_ages: dict[str, float] = field(default_factory=dict)
    ts: str | None = None


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


def build_frames(symbols: list[str], fixtures_dir: str) -> list[MarketFrame]:
    """Build a per-bar mark history from the fixture series for the multi-period driver.

    Symbols are aligned by their shared tail length so every frame has a mark for each
    symbol. ``prev_closes`` is the prior bar's close (used by the abnormal-move gate);
    ``quote_ages`` is 0.0 (offline fixtures are never stale). The value of replaying the
    series is the **real equity path** it produces, which feeds the drawdown and
    intraday-loss breakers.
    """
    src = FixtureDataSource(fixtures_dir)
    series = {}
    for sym in symbols:
        bars = src.load(sym)
        if bars:
            series[sym] = bars
    if not series:
        return []
    n = min(len(b) for b in series.values())
    tails = {s: b[-n:] for s, b in series.items()}
    frames: list[MarketFrame] = []
    for i in range(n):
        marks = {s: t[i].close for s, t in tails.items()}
        prev = {s: (t[i - 1].close if i > 0 else t[i].close) for s, t in tails.items()}
        ts = next(iter(tails.values()))[i].ts
        frames.append(MarketFrame(marks=marks, prev_closes=prev, ts=ts))
    return frames


def _build_broker(mode: str, config: AppConfig, kill: KillSwitch) -> Broker:
    if mode == "live":
        # Live routing is built explicitly; never the default. Importing here keeps
        # the live broker out of the paper/dry-run path entirely.
        from ..brokers.moomoo import MoomooTradeGateway
        from .moomoo_broker import MoomooExecutionBroker

        return MoomooExecutionBroker(MoomooTradeGateway(config.moomoo, kill_switch=kill))
    return PaperBroker(
        config.execution.initial_cash,
        slippage_bps=config.execution.slippage_bps,
        commission_per_trade=config.execution.commission_per_trade,
    )


def run_execution(
    sigset: SignalSet,
    config: AppConfig | None = None,
    *,
    mode: str | None = None,
) -> RunRecord:
    """Single reconcile cycle on the latest fixture bar (one-shot snapshot)."""
    config = config or load_config()
    mode = mode or config.execution.mode
    kill = KillSwitch(config.moomoo.kill_switch_file)
    risk = RiskManager(config.risk, kill_switch=kill)
    broker = _build_broker(mode, config, kill)

    engine = ExecutionEngine(broker, risk, mode=mode)
    symbols = [s.symbol for s in sigset.signals]
    marks, prev = build_marks(symbols, config.fixtures_dir)
    return engine.run_cycle(sigset, marks, prev_closes=prev)


def run_execution_path(
    sigset: SignalSet,
    config: AppConfig | None = None,
    *,
    mode: str | None = None,
    frames: list[MarketFrame] | None = None,
    baseline_equity: float | None = None,
) -> list[RunRecord]:
    """Replay ``frames`` through one persistent RiskManager + broker (multi-period).

    Each cycle is fed the running intraday P&L (equity vs the session baseline), the
    per-symbol quote ages and prev-closes, so the path-dependent breakers — intraday
    loss, 20% drawdown, stale quote — are genuinely active. Returns one
    :class:`RunRecord` per frame; a latched halt persists across the remaining frames.

    ``frames`` defaults to the fixture history; a live loop passes real frames built
    from the broker feed. ``baseline_equity`` overrides the intraday baseline (defaults
    to the broker equity at the first frame, i.e. session open).
    """
    config = config or load_config()
    mode = mode or config.execution.mode
    kill = KillSwitch(config.moomoo.kill_switch_file)
    risk = RiskManager(config.risk, kill_switch=kill)
    broker = _build_broker(mode, config, kill)
    engine = ExecutionEngine(broker, risk, mode=mode)

    symbols = [s.symbol for s in sigset.signals]
    if frames is None:
        frames = build_frames(symbols, config.fixtures_dir)

    records: list[RunRecord] = []
    base = baseline_equity
    for frame in frames:
        equity = broker.equity(frame.marks)
        if base is None:
            base = equity  # session-open equity is the intraday P&L reference
        intraday_pnl_pct = (equity / base - 1.0) if base else 0.0
        records.append(
            engine.run_cycle(
                sigset,
                frame.marks,
                prev_closes=frame.prev_closes,
                quote_ages=frame.quote_ages,
                intraday_pnl_pct=intraday_pnl_pct,
            )
        )
    return records

"""End-to-end pipeline wiring the five layers together.

``run_backtest`` and ``train_and_backtest`` are the two reference flows that prove
the whole chain runs on fixture data with no real market feed. Both return the
backtest result plus its computed metrics so callers (CLI, tests, notebooks) can
inspect or persist them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .backtest.engine import BacktestResult, BacktestRunner
from .backtest.walk_forward import run_walk_forward
from .config import AppConfig, CostConfig, load_config
from .data.base import Bar, DataSource
from .data.fixture import FixtureDataSource
from .metrics.core import CoreMetrics, compute_core_metrics
from .metrics.gates import GateVerdict, evaluate_gates, gate1_baseline
from .model.base import Model
from .model.momentum import MomentumModel, MomentumStrategy
from .report.metrics import PerformanceMetrics
from .report.report import ReportGenerator
from .strategy.base import Strategy
from .strategy.sma_cross import SmaCrossStrategy


@dataclass
class PipelineOutput:
    result: BacktestResult
    metrics: PerformanceMetrics
    bars: list[Bar]


@dataclass
class CostStress:
    """成本×2 压力测试 (v1.0 §4): 滑点与手续费统一翻倍后是否仍过关1."""

    base_pass: bool
    stressed_pass: bool
    base_cagr: float
    stressed_cagr: float
    base_mdd: float
    stressed_mdd: float


@dataclass
class EvaluationResult:
    """评估卡 §B-E 的全部计算结果 (报告层只做组装/渲染, 不再算)."""

    symbol: str
    strategy: str
    config: AppConfig
    result: BacktestResult
    bars: list[Bar]
    core: CoreMetrics
    holdout: GateVerdict  # 四关 (gate4 = 70/30 hold-out)
    cost_stress: CostStress
    walk_forward: GateVerdict | None = None  # gate1-3 on stitched OOS curve
    wf_meta: dict | None = None


def _runner(config: AppConfig) -> BacktestRunner:
    return BacktestRunner(cost=config.cost, backtest=config.backtest)


def _report(config: AppConfig) -> ReportGenerator:
    return ReportGenerator(trading_days=config.backtest.trading_days_per_year)


def run_backtest(
    symbol: str,
    *,
    strategy: Strategy | None = None,
    data_source: DataSource | None = None,
    config: AppConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> PipelineOutput:
    config = config or load_config()
    data_source = data_source or FixtureDataSource(config.fixtures_dir)
    strategy = strategy or SmaCrossStrategy()

    bars = data_source.load(symbol, start, end)
    result = _runner(config).run(symbol, bars, strategy)
    metrics = _report(config).build(result)
    return PipelineOutput(result=result, metrics=metrics, bars=bars)


def train_and_backtest(
    symbol: str,
    *,
    data_source: DataSource | None = None,
    config: AppConfig | None = None,
    model_path: str | None = None,
) -> PipelineOutput:
    """Fit a fixture model on the in-sample portion, persist it, then backtest.

    Demonstrates the full train -> save -> reload -> predict -> backtest loop while
    respecting the out-of-sample boundary (the model only ever sees in-sample bars).
    """
    config = config or load_config()
    data_source = data_source or FixtureDataSource(config.fixtures_dir)
    bars = data_source.load(symbol)

    # Train only on the in-sample head so the OOS tail stays untouched.
    runner = _runner(config)
    oos_ts = runner._oos_start(bars)
    train_bars = [b for b in bars if oos_ts is None or b.ts < oos_ts] or bars

    model = MomentumModel().fit(train_bars)
    if model_path:
        model.save(model_path)

    strategy = MomentumStrategy(model)
    result = runner.run(symbol, bars, strategy)
    metrics = _report(config).build(result)
    return PipelineOutput(result=result, metrics=metrics, bars=bars)


def _cost_stress(symbol: str, bars: list[Bar], strategy: Strategy, config: AppConfig) -> CostStress:
    """Rerun the backtest with commission + slippage ×2 and compare against gate 1."""
    P = config.metric.periods_per_year
    base = BacktestRunner(config.cost, config.backtest).run(symbol, bars, strategy)
    doubled = CostConfig(
        commission_rate=config.cost.commission_rate * 2,
        slippage_bps=config.cost.slippage_bps * 2,
        min_commission=config.cost.min_commission * 2,
    )
    stressed = BacktestRunner(doubled, config.backtest).run(symbol, bars, strategy)
    g_base = gate1_baseline([p.equity for p in base.equity_curve], P, config.gate)
    g_str = gate1_baseline([p.equity for p in stressed.equity_curve], P, config.gate)
    return CostStress(
        base_pass=g_base.passed,
        stressed_pass=g_str.passed,
        base_cagr=g_base.metrics["cagr"],
        stressed_cagr=g_str.metrics["cagr"],
        base_mdd=g_base.metrics["mdd"],
        stressed_mdd=g_str.metrics["mdd"],
    )


def evaluate_candidate(
    symbol: str,
    *,
    strategy: Strategy | None = None,
    model_factory: Callable[[], Model] | None = None,
    data_source: DataSource | None = None,
    config: AppConfig | None = None,
    walk_forward: bool = False,
    wf_train_bars: int = 252,
    wf_test_bars: int = 63,
) -> EvaluationResult:
    """Run a candidate through the full v1.0 评估卡: core metrics + 四关门禁 + 成本×2.

    Provide either a static ``strategy`` or a ``model_factory`` (the latter enables
    the Walk-Forward 主口径 when ``walk_forward=True``). All on fixture data — this
    validates the engineering + metric computation, never策略达标.
    """
    config = config or load_config()
    data_source = data_source or FixtureDataSource(config.fixtures_dir)
    bars = data_source.load(symbol)
    P = config.metric.periods_per_year

    if strategy is None:
        if model_factory is None:
            strategy = SmaCrossStrategy()
        else:
            runner = _runner(config)
            oos_ts = runner._oos_start(bars)
            train = [b for b in bars if oos_ts is None or b.ts < oos_ts] or bars
            strategy = MomentumStrategy(model_factory().fit(train))

    result = _runner(config).run(symbol, bars, strategy)
    ts = [p.ts for p in result.equity_curve]
    equity = [p.equity for p in result.equity_curve]
    core = compute_core_metrics(result, config.metric, bars)
    holdout = evaluate_gates(ts, equity, P, config.gate, oos_start_ts=result.oos_start_ts)
    cost_stress = _cost_stress(symbol, bars, strategy, config)

    wf_verdict = None
    wf_meta = None
    if walk_forward and model_factory is not None:
        wf = run_walk_forward(
            symbol, bars, model_factory, config.cost, config.backtest,
            train_bars=wf_train_bars, test_bars=wf_test_bars,
        )
        wf_ts, wf_equity = wf.oos_curve()
        wf_verdict = evaluate_gates(wf_ts, wf_equity, P, config.gate, include_holdout=False)
        wf_meta = {
            "n_folds": wf.n_folds,
            "train_bars": wf_train_bars,
            "test_bars": wf_test_bars,
            "oos_bars": len(wf_equity),
            "oos_start_ts": wf_ts[0] if wf_ts else None,
        }

    return EvaluationResult(
        symbol=symbol,
        strategy=strategy.name,
        config=config,
        result=result,
        bars=bars,
        core=core,
        holdout=holdout,
        cost_stress=cost_stress,
        walk_forward=wf_verdict,
        wf_meta=wf_meta,
    )

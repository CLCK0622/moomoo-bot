"""Configuration loading.

Config is sourced from (in priority order): explicit ``overrides`` dict ->
environment variables -> built-in defaults. Secrets (moomoo account, trade unlock
password, API host) are ONLY ever read from the environment — never hard-coded and
never written back to disk. See ``.env.example`` for the full set of placeholders.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CostConfig:
    """Trading frictions applied by the backtest engine."""

    commission_rate: float = 0.0005  # 5 bps per traded notional
    slippage_bps: float = 1.0  # 1 bp of traded notional, modelled separately
    min_commission: float = 0.0  # absolute floor per trade (e.g. broker minimum)


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    # Fraction of the timeline (by date order) reserved as out-of-sample tail.
    oos_fraction: float = 0.3
    trading_days_per_year: int = 252


@dataclass(frozen=True)
class MetricConfig:
    """指标口径 (户部 EVO-12 v1.0 §1-2). All metrics are computed post-cost."""

    periods_per_year: int = 252  # P: 日频=252, 周频=52, 月频=12
    risk_free_rate_annual: float = 0.0  # r_f (年化); 取 0 时报告显式声明
    mar_annual: float = 0.0  # Sortino MAR (年化)
    turnover_double_sided: bool = False  # 换手成交额单边/双边口径
    capacity_participation: float = 0.10  # 单 bar 可参与成交量上限占比 (5%-10%)
    capacity_decay_tolerance: float = 0.10  # 容量阈值: 年化衰减相对不超过 10%


@dataclass(frozen=True)
class GateConfig:
    """门禁四关阈值 (户部 EVO-12 v1.0 §3). v1.0 固定值。"""

    target_cagr: float = 0.50  # 年化收益门禁
    max_mdd: float = 0.20  # 最大回撤门禁 (正数幅度)
    # 关2 分年度
    yearly_min_cagr: float = 0.35  # 每个完整年度最低 CAGR
    # 关3 滚动窗口 (日频: 12 月窗 ~252 bar, 步长 1 月 ~21 bar)
    rolling_window_bars: int = 252
    rolling_step_bars: int = 21
    rolling_median_min: float = 0.50  # 滚动年化中位数下限
    rolling_hit_ratio_min: float = 0.70  # 达标窗口占比下限
    rolling_negative_max: float = 0.10  # 负年化窗口占比上限
    # 关4 样本外/WF
    oos_degradation_max: float = 0.30  # 样本外相对样本内衰减上限 (过拟合信号)


@dataclass(frozen=True)
class MoomooConfig:
    """moomoo US OpenD connection + safety settings — ALL secrets come from the env.

    None values mean "not configured"; the adapter raises a clear error rather than
    guessing. Nothing here is ever persisted. The safety flags below are the hard
    guardrails (EVO-13 §3): every order path checks them and fails safe by default.
    """

    host: str = "127.0.0.1"
    port: int = 11111
    trade_env: str = "SIMULATE"  # 模式隔离: SIMULATE | REAL
    security_firm: str = "FUTUINC"  # FUTUINC (US) | FUTUSG | FUTUHK
    account_id: str | None = None  # OpenD trade account id (env only)
    unlock_pwd: str | None = None  # trade unlock password (env only; REAL 才需要)

    enabled: bool = False  # never auto-connect unless explicitly enabled
    # 自动交易默认关闭: 下单路径必须显式打开才放行
    allow_orders: bool = False
    # 实盘二次闸门: REAL 环境下单还需要这个显式为 True
    allow_real: bool = False
    # 全局急停: 触发后所有下单被拒；可由文件持久化以跨进程生效
    kill_switch_file: str | None = None
    # 限频: 滚动窗口内最多多少笔下单
    max_orders_per_window: int = 30
    order_window_seconds: float = 30.0
    # 连接异常重连
    connect_retries: int = 3
    connect_backoff_seconds: float = 0.5


@dataclass(frozen=True)
class RiskConfig:
    """风控硬栏杆 (EVO-13 执行层; 缺一视为未完成)。所有阈值正数表示幅度。"""

    max_position_weight: float = 0.25  # 单标的仓位上限 (占权益)
    max_gross_exposure: float = 1.0  # 总仓位上限 (Σ|weight|)
    max_positions: int = 5  # 最多并发持仓数 (对齐 quant-strategies max_positions)
    intraday_loss_limit: float = 0.05  # 日内损失阈值 (占基准权益) -> 停新开仓
    drawdown_breaker: float = 0.20  # 20% 回撤熔断
    abnormal_move_pct: float = 0.15  # 单 bar 异常波动阈值 -> 停机
    stale_quote_seconds: float = 120.0  # 行情过期阈值 (秒) -> 停机


@dataclass(frozen=True)
class ExecutionConfig:
    """执行层默认安全: dry_run / paper / 模拟盘优先, 实盘默认关闭。"""

    mode: str = "paper"  # dry_run | paper | live (live 还需 moomoo.allow_orders)
    initial_cash: float = 100_000.0
    slippage_bps: float = 1.0
    commission_per_trade: float = 1.0


@dataclass(frozen=True)
class AppConfig:
    cost: CostConfig = field(default_factory=CostConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    metric: MetricConfig = field(default_factory=MetricConfig)
    gate: GateConfig = field(default_factory=GateConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    moomoo: MoomooConfig = field(default_factory=MoomooConfig)
    fixtures_dir: str = "fixtures"
    artifacts_dir: str = "artifacts"  # where trained models / reports are written


def _get(overrides: Mapping[str, str], env: Mapping[str, str], key: str) -> str | None:
    if key in overrides:
        return overrides[key]
    return env.get(key)


def _as_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _as_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(overrides: Mapping[str, str] | None = None) -> AppConfig:
    """Build an :class:`AppConfig` from env vars (and optional explicit overrides).

    Recognised environment variables (all optional; sensible defaults apply):

    - ``QLAB_INITIAL_CASH``, ``QLAB_OOS_FRACTION``, ``QLAB_TRADING_DAYS``
    - ``QLAB_COMMISSION_RATE``, ``QLAB_SLIPPAGE_BPS``, ``QLAB_MIN_COMMISSION``
    - ``QLAB_FIXTURES_DIR``, ``QLAB_ARTIFACTS_DIR``
    - ``MOOMOO_HOST``, ``MOOMOO_PORT``, ``MOOMOO_TRADE_ENV``, ``MOOMOO_ENABLED``
    - ``MOOMOO_ACCOUNT_ID``, ``MOOMOO_UNLOCK_PWD_MD5``  (secrets — env only)
    """
    overrides = dict(overrides or {})
    env = os.environ

    cost = CostConfig(
        commission_rate=_as_float(_get(overrides, env, "QLAB_COMMISSION_RATE"), 0.0005),
        slippage_bps=_as_float(_get(overrides, env, "QLAB_SLIPPAGE_BPS"), 1.0),
        min_commission=_as_float(_get(overrides, env, "QLAB_MIN_COMMISSION"), 0.0),
    )
    backtest = BacktestConfig(
        initial_cash=_as_float(_get(overrides, env, "QLAB_INITIAL_CASH"), 1_000_000.0),
        oos_fraction=_as_float(_get(overrides, env, "QLAB_OOS_FRACTION"), 0.3),
        trading_days_per_year=_as_int(_get(overrides, env, "QLAB_TRADING_DAYS"), 252),
    )
    metric = MetricConfig(
        periods_per_year=_as_int(_get(overrides, env, "QLAB_TRADING_DAYS"), 252),
        risk_free_rate_annual=_as_float(_get(overrides, env, "QLAB_RISK_FREE_RATE"), 0.0),
        mar_annual=_as_float(_get(overrides, env, "QLAB_MAR"), 0.0),
        turnover_double_sided=_as_bool(_get(overrides, env, "QLAB_TURNOVER_DOUBLE_SIDED"), False),
        capacity_participation=_as_float(_get(overrides, env, "QLAB_CAPACITY_PARTICIPATION"), 0.10),
    )
    # Gate thresholds are v1.0-fixed; we read them from defaults rather than env so
    # 门禁口径 stays consistent across the whole workspace.
    gate = GateConfig()
    moomoo = MoomooConfig(
        host=_get(overrides, env, "MOOMOO_HOST") or "127.0.0.1",
        port=_as_int(_get(overrides, env, "MOOMOO_PORT"), 11111),
        trade_env=_get(overrides, env, "MOOMOO_TRADE_ENV") or "SIMULATE",
        security_firm=_get(overrides, env, "MOOMOO_SECURITY_FIRM") or "FUTUINC",
        account_id=_get(overrides, env, "MOOMOO_ACCOUNT_ID"),
        unlock_pwd=_get(overrides, env, "MOOMOO_UNLOCK_PWD"),
        enabled=_as_bool(_get(overrides, env, "MOOMOO_ENABLED"), False),
        allow_orders=_as_bool(_get(overrides, env, "MOOMOO_ALLOW_ORDERS"), False),
        allow_real=_as_bool(_get(overrides, env, "MOOMOO_ALLOW_REAL"), False),
        kill_switch_file=_get(overrides, env, "MOOMOO_KILL_SWITCH_FILE"),
        max_orders_per_window=_as_int(_get(overrides, env, "MOOMOO_MAX_ORDERS"), 30),
        order_window_seconds=_as_float(_get(overrides, env, "MOOMOO_ORDER_WINDOW_SEC"), 30.0),
        connect_retries=_as_int(_get(overrides, env, "MOOMOO_CONNECT_RETRIES"), 3),
        connect_backoff_seconds=_as_float(_get(overrides, env, "MOOMOO_CONNECT_BACKOFF"), 0.5),
    )
    risk = RiskConfig(
        max_position_weight=_as_float(_get(overrides, env, "QLAB_MAX_POSITION_WEIGHT"), 0.25),
        max_gross_exposure=_as_float(_get(overrides, env, "QLAB_MAX_GROSS"), 1.0),
        max_positions=_as_int(_get(overrides, env, "QLAB_MAX_POSITIONS"), 5),
        intraday_loss_limit=_as_float(_get(overrides, env, "QLAB_INTRADAY_LOSS_LIMIT"), 0.05),
        drawdown_breaker=_as_float(_get(overrides, env, "QLAB_DRAWDOWN_BREAKER"), 0.20),
        abnormal_move_pct=_as_float(_get(overrides, env, "QLAB_ABNORMAL_MOVE"), 0.15),
        stale_quote_seconds=_as_float(_get(overrides, env, "QLAB_STALE_QUOTE_SEC"), 120.0),
    )
    execution = ExecutionConfig(
        mode=_get(overrides, env, "QLAB_EXEC_MODE") or "paper",
        initial_cash=_as_float(_get(overrides, env, "QLAB_EXEC_CASH"), 100_000.0),
        slippage_bps=_as_float(_get(overrides, env, "QLAB_EXEC_SLIPPAGE_BPS"), 1.0),
        commission_per_trade=_as_float(_get(overrides, env, "QLAB_EXEC_COMMISSION"), 1.0),
    )
    return AppConfig(
        cost=cost,
        backtest=backtest,
        metric=metric,
        gate=gate,
        risk=risk,
        execution=execution,
        moomoo=moomoo,
        fixtures_dir=_get(overrides, env, "QLAB_FIXTURES_DIR") or "fixtures",
        artifacts_dir=_get(overrides, env, "QLAB_ARTIFACTS_DIR") or "artifacts",
    )

"""Core return/risk metrics — v1.0 §2, exact-口径 implementations.

Every function here is pure (takes plain numbers, returns plain numbers) so the
algorithm itself can be unit-tested against hand-computed values, independent of any
backtest. Inputs are the post-cost net-equity series ``E_t`` and/or per-bar net
return series ``r_t`` (see v1.0 §1 记号约定).

口径 notes embedded per function. Where v1.0 leaves a fencepost choice, the choice is
stated explicitly so it stays consistent across the workspace.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field


def returns_from_equity(equity: list[float]) -> list[float]:
    """Per-bar simple returns r_t = E_t / E_{t-1} - 1 (length == len(equity) - 1)."""
    out: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        out.append((equity[i] / prev - 1.0) if prev else 0.0)
    return out


def geometric_cagr(equity: list[float], periods_per_year: int) -> float:
    """几何年化收益 (v1.0 §2.1): (E_end/E_start)^(P/N) - 1.

    口径: N = 已实现收益期数 = len(equity) - 1 (E_start→E_end 跨越的复利步数;
    显式选用 N-1 而非 bar 总数以消除 fencepost 歧义). 复利几何口径，不做算术外推。
    """
    if len(equity) < 2:
        return 0.0
    e_start, e_end = equity[0], equity[-1]
    if e_start <= 0:
        return 0.0
    ratio = e_end / e_start
    if ratio <= 0:
        return -1.0  # capital wiped out
    n = len(equity) - 1
    return ratio ** (periods_per_year / n) - 1.0


def max_drawdown(equity: list[float]) -> float:
    """最大回撤幅度 (v1.0 §2.2), 逐 bar, 返回正数 (e.g. 0.18 表示 -18%)."""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return -worst


@dataclass
class DrawdownDuration:
    longest_underwater_bars: int = 0  # 最长水下时长
    median_underwater_bars: float = 0.0  # 水下时长中位数
    has_unrecovered: bool = False  # 期末是否仍未恢复
    unrecovered_bars: int = 0  # 截至期末已持续且未恢复的 bar 数


def drawdown_durations(equity: list[float]) -> DrawdownDuration:
    """回撤持续期 (v1.0 §2.3).

    水下时长 = 自前高 (peak) 到重新创新高之间的 bar 数。期末仍未恢复的回撤单独标注，
    不计入「已恢复」集合，但参与「最长」比较。
    """
    if len(equity) < 2:
        return DrawdownDuration()
    peak = equity[0]
    peak_idx = 0
    underwater = False
    recovered: list[int] = []
    for i in range(1, len(equity)):
        if equity[i] < peak:
            underwater = True
        if equity[i] >= peak:
            if underwater:
                recovered.append(i - peak_idx)
                underwater = False
            peak = equity[i]
            peak_idx = i
    unrecovered = (len(equity) - 1 - peak_idx) if underwater else 0
    candidates = list(recovered)
    if underwater:
        candidates.append(unrecovered)
    return DrawdownDuration(
        longest_underwater_bars=max(candidates) if candidates else 0,
        median_underwater_bars=float(statistics.median(recovered)) if recovered else 0.0,
        has_unrecovered=underwater,
        unrecovered_bars=unrecovered,
    )


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)  # n-1
    return math.sqrt(var)


def sharpe(returns: list[float], periods_per_year: int, rf_per_bar: float = 0.0) -> float:
    """年化夏普 (v1.0 §2.4): mean(x)/std(x)·sqrt(P), x_t = r_t - r_f,t, std 用 n-1.

    口径: 未做自相关 (Newey-West) 修正 — 高频策略须在评估卡 §C 注明并自行修正。
    """
    if len(returns) < 2:
        return 0.0
    excess = [r - rf_per_bar for r in returns]
    std = _sample_std(excess)
    if std == 0:
        return 0.0
    mean = sum(excess) / len(excess)
    return (mean / std) * math.sqrt(periods_per_year)


def sortino(
    returns: list[float],
    periods_per_year: int,
    rf_per_bar: float = 0.0,
    mar_per_bar: float = 0.0,
) -> float:
    """年化索提诺 (v1.0 §2.5): (mean(x)-MAR)/下行偏差·sqrt(P).

    下行偏差 = sqrt(mean(min(x_t - MAR, 0)^2)); 分母只惩罚下行。x_t = r_t - r_f,t.
    """
    if len(returns) < 2:
        return 0.0
    excess = [r - rf_per_bar for r in returns]
    downside_sq = [min(x - mar_per_bar, 0.0) ** 2 for x in excess]
    dd = math.sqrt(sum(downside_sq) / len(downside_sq))
    if dd == 0:
        return 0.0
    mean = sum(excess) / len(excess)
    return ((mean - mar_per_bar) / dd) * math.sqrt(periods_per_year)


@dataclass
class CoreMetrics:
    """评估卡 §C 成本后核心指标的结构化输出."""

    periods_per_year: int = 252
    cagr: float = 0.0  # 几何 CAGR
    max_drawdown: float = 0.0  # 逐 bar MDD (正数)
    drawdown: DrawdownDuration = field(default_factory=DrawdownDuration)
    annualized_volatility: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    # 交易统计 (§2.6-2.7)
    n_closed_trades: int = 0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    # 换手/容量 (§2.8-2.9)
    annualized_turnover: float = 0.0
    turnover_double_sided: bool = False
    capacity_estimate: float | None = None
    capacity_participation: float = 0.10
    # 成本拆分 (§B 承接)
    total_commission: float = 0.0
    total_slippage: float = 0.0
    rf_annual: float = 0.0
    mar_annual: float = 0.0
    autocorr_adjusted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def annualized_turnover(
    per_bar_turnover: list[float], periods_per_year: int
) -> float:
    """年化换手 (v1.0 §2.8): 单期换手均值 × P."""
    if not per_bar_turnover:
        return 0.0
    return (sum(per_bar_turnover) / len(per_bar_turnover)) * periods_per_year


def compute_core_metrics(result, metric_cfg, bars=None) -> CoreMetrics:
    """Assemble §C core metrics from a :class:`BacktestResult`.

    ``bars`` (the OHLCV list) is optional and only needed for the §2.9 capacity
    estimate (it reads per-bar traded volume). Everything else comes from the
    post-cost equity curve and the trade log.
    """
    from .trades import closed_trade_pnls, trade_stats  # local import avoids cycle

    curve = result.equity_curve
    equity = [p.equity for p in curve]
    P = metric_cfg.periods_per_year
    returns = returns_from_equity(equity)
    rf_per_bar = metric_cfg.risk_free_rate_annual / P if P else 0.0
    mar_per_bar = metric_cfg.mar_annual / P if P else 0.0

    # §2.8 换手: 单 bar 成交额 / 期初(上一 bar 收盘)市值; 年化 = 均值 × P.
    notional_by_ts: dict[str, float] = {}
    for t in result.trades:
        notional_by_ts[t.ts] = notional_by_ts.get(t.ts, 0.0) + t.notional
    per_bar_turnover: list[float] = []
    for i in range(1, len(curve)):
        prev_equity = curve[i - 1].equity
        notional = notional_by_ts.get(curve[i].ts, 0.0)
        per_bar_turnover.append(notional / prev_equity if prev_equity else 0.0)

    # §2.9 容量: 每个成交 bar 在参与度上限下可承载的资金, 取最紧约束 (保守).
    capacity = None
    if bars:
        bar_by_ts = {b.ts: b for b in bars}
        caps: list[float] = []
        for i in range(1, len(curve)):
            ts = curve[i].ts
            notional = notional_by_ts.get(ts, 0.0)
            prev_equity = curve[i - 1].equity
            bar = bar_by_ts.get(ts)
            if notional <= 0 or not bar or prev_equity <= 0:
                continue
            tradable = metric_cfg.capacity_participation * bar.volume * bar.open
            turnover_frac = notional / prev_equity
            if turnover_frac > 0:
                caps.append(tradable / turnover_frac)
        capacity = min(caps) if caps else None

    pnls = closed_trade_pnls(result.trades)
    stats = trade_stats(pnls)

    return CoreMetrics(
        periods_per_year=P,
        cagr=geometric_cagr(equity, P),
        max_drawdown=max_drawdown(equity),
        drawdown=drawdown_durations(equity),
        annualized_volatility=_sample_std(returns) * math.sqrt(P) if len(returns) > 1 else 0.0,
        sharpe=sharpe(returns, P, rf_per_bar),
        sortino=sortino(returns, P, rf_per_bar, mar_per_bar),
        n_closed_trades=stats.n_closed_trades,
        win_rate=stats.win_rate,
        profit_loss_ratio=stats.profit_loss_ratio,
        profit_factor=stats.profit_factor,
        expectancy=stats.expectancy,
        annualized_turnover=annualized_turnover(per_bar_turnover, P),
        turnover_double_sided=metric_cfg.turnover_double_sided,
        capacity_estimate=capacity,
        capacity_participation=metric_cfg.capacity_participation,
        total_commission=result.total_commission,
        total_slippage=result.total_slippage,
        rf_annual=metric_cfg.risk_free_rate_annual,
        mar_annual=metric_cfg.mar_annual,
        autocorr_adjusted=False,
    )

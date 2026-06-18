"""Performance metrics aligned to 户部口径.

Fields produced (every one the 户部 brief asked for):
- 年化收益          annualized_return
- 最大回撤          max_drawdown
- 分年度表现        yearly_returns  (per calendar year)
- 交易成本          total_commission
- 滑点              total_slippage
- 样本外区间        oos_period + oos_metrics (in-sample vs out-of-sample split)

Pure stdlib; computed from the engine's equity curve and trade log.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from ..backtest.engine import BacktestResult, EquityPoint


@dataclass
class PerformanceMetrics:
    period_start: str | None = None
    period_end: str | None = None
    n_bars: int = 0
    total_return: float = 0.0
    annualized_return: float = 0.0  # 年化收益
    annualized_volatility: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0  # 最大回撤 (negative fraction, e.g. -0.18)
    yearly_returns: dict[str, float] = field(default_factory=dict)  # 分年度表现
    total_commission: float = 0.0  # 交易成本
    total_slippage: float = 0.0  # 滑点
    n_trades: int = 0
    turnover: float = 0.0  # sum traded notional / initial cash
    # 样本外区间
    oos_period: dict[str, str] | None = None
    in_sample: dict[str, float] | None = None
    out_of_sample: dict[str, float] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _annualized_return(total_return: float, n_bars: int, trading_days: int) -> float:
    if n_bars <= 1:
        return 0.0
    years = (n_bars - 1) / trading_days
    if years <= 0:
        return 0.0
    base = 1.0 + total_return
    if base <= 0:
        return -1.0  # wiped out
    return base ** (1.0 / years) - 1.0


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 0.0
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            dd = value / peak - 1.0
            max_dd = min(max_dd, dd)
    return max_dd


def _vol_and_sharpe(returns: list[float], trading_days: int) -> tuple:
    if len(returns) < 2:
        return 0.0, 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    ann_vol = std * math.sqrt(trading_days)
    sharpe = (mean / std) * math.sqrt(trading_days) if std > 0 else 0.0
    return ann_vol, sharpe


def _yearly_returns(curve: list[EquityPoint]) -> dict[str, float]:
    by_year_last: dict[str, float] = {}
    by_year_first_prev: dict[str, float] = {}
    prev_equity = curve[0].equity if curve else 0.0
    for point in curve:
        year = point.ts[:4]
        if year not in by_year_first_prev:
            by_year_first_prev[year] = prev_equity
        by_year_last[year] = point.equity
        prev_equity = point.equity
    out: dict[str, float] = {}
    for year in sorted(by_year_last):
        start = by_year_first_prev[year]
        end = by_year_last[year]
        out[year] = (end / start - 1.0) if start else 0.0
    return out


def _segment_metrics(curve: list[EquityPoint], trading_days: int) -> dict[str, float]:
    if len(curve) < 2:
        return {"total_return": 0.0, "annualized_return": 0.0, "max_drawdown": 0.0}
    equity = [p.equity for p in curve]
    total_return = equity[-1] / equity[0] - 1.0
    returns = [
        (equity[i] - equity[i - 1]) / equity[i - 1] if equity[i - 1] else 0.0
        for i in range(1, len(equity))
    ]
    ann_vol, sharpe = _vol_and_sharpe(returns, trading_days)
    return {
        "total_return": total_return,
        "annualized_return": _annualized_return(total_return, len(equity), trading_days),
        "max_drawdown": _max_drawdown(equity),
        "annualized_volatility": ann_vol,
        "sharpe": sharpe,
    }


def compute_metrics(result: BacktestResult, trading_days: int = 252) -> PerformanceMetrics:
    curve = result.equity_curve
    if len(curve) < 2:
        return PerformanceMetrics(n_bars=len(curve))

    equity = [p.equity for p in curve]
    total_return = equity[-1] / equity[0] - 1.0
    returns = result.returns()
    ann_vol, sharpe = _vol_and_sharpe(returns, trading_days)
    turnover = (
        sum(t.notional for t in result.trades) / result.initial_cash
        if result.initial_cash
        else 0.0
    )

    metrics = PerformanceMetrics(
        period_start=curve[0].ts,
        period_end=curve[-1].ts,
        n_bars=len(curve),
        total_return=total_return,
        annualized_return=_annualized_return(total_return, len(curve), trading_days),
        annualized_volatility=ann_vol,
        sharpe=sharpe,
        max_drawdown=_max_drawdown(equity),
        yearly_returns=_yearly_returns(curve),
        total_commission=result.total_commission,
        total_slippage=result.total_slippage,
        n_trades=len(result.trades),
        turnover=turnover,
    )

    # 样本外区间: split the curve at the engine-recorded OOS boundary.
    if result.oos_start_ts:
        split = next((i for i, p in enumerate(curve) if p.ts >= result.oos_start_ts), None)
        if split is not None and 0 < split < len(curve):
            is_curve = curve[: split + 1]  # include the boundary as IS terminal point
            oos_curve = curve[split:]
            metrics.oos_period = {
                "in_sample": f"{curve[0].ts} → {curve[split].ts}",
                "out_of_sample": f"{oos_curve[0].ts} → {curve[-1].ts}",
            }
            metrics.in_sample = _segment_metrics(is_curve, trading_days)
            metrics.out_of_sample = _segment_metrics(oos_curve, trading_days)

    return metrics

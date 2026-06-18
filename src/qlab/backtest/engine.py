"""Event-driven backtest runner.

Mechanics (deliberately conservative to avoid optimistic bias):
- The strategy emits a target weight per bar using only info up to that bar.
- A weight decided on bar *i* is executed at bar ``i+1``'s open, so there is no
  same-bar lookahead.
- Each rebalance trades the notional delta needed to reach the target. Two frictions
  are charged separately and tracked independently so the report can break them out:
    * commission  = |traded_notional| * commission_rate  (with optional floor)
    * slippage     = |traded_notional| * slippage_bps / 10_000
- Equity is marked to market at each bar's close.

Everything is pure Python; no numpy/pandas required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import BacktestConfig, CostConfig
from ..data.base import Bar
from ..strategy.base import Strategy


@dataclass(frozen=True)
class Trade:
    ts: str
    side: str  # "BUY" | "SELL"
    shares: float
    price: float  # execution price (already slippage-adjusted)
    notional: float
    commission: float
    slippage: float


@dataclass(frozen=True)
class EquityPoint:
    ts: str
    equity: float
    position_shares: float
    cash: float
    target_weight: float


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    initial_cash: float = 0.0
    oos_start_ts: str | None = None  # first bar of the out-of-sample tail
    total_commission: float = 0.0
    total_slippage: float = 0.0

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1].equity if self.equity_curve else self.initial_cash

    def returns(self) -> list[float]:
        """Period-over-period equity returns (length == len(curve) - 1)."""
        out: list[float] = []
        curve = self.equity_curve
        for i in range(1, len(curve)):
            prev = curve[i - 1].equity
            out.append((curve[i].equity - prev) / prev if prev else 0.0)
        return out


class BacktestRunner:
    def __init__(self, cost: CostConfig, backtest: BacktestConfig) -> None:
        self.cost = cost
        self.backtest = backtest

    def run(self, symbol: str, bars: list[Bar], strategy: Strategy) -> BacktestResult:
        if len(bars) < 2:
            raise ValueError("need at least 2 bars to run a backtest")

        weights = strategy.target_weights(bars)
        if len(weights) != len(bars):
            raise ValueError("strategy must return one weight per bar")

        oos_start_ts = self._oos_start(bars)
        result = BacktestResult(
            symbol=symbol,
            strategy=strategy.name,
            initial_cash=self.backtest.initial_cash,
            oos_start_ts=oos_start_ts,
        )

        cash = self.backtest.initial_cash
        shares = 0.0
        slip = self.cost.slippage_bps / 10_000.0

        # Decide on bar i, execute on bar i+1's open; mark to market at close.
        for i in range(len(bars)):
            bar = bars[i]
            if i > 0:
                target_w = weights[i - 1]
                equity_pre = cash + shares * bar.open
                target_value = target_w * equity_pre
                target_shares = target_value / bar.open if bar.open else 0.0
                delta = target_shares - shares
                if abs(delta) > 1e-9:
                    side = "BUY" if delta > 0 else "SELL"
                    # Slippage worsens the fill: pay up when buying, receive less when selling.
                    exec_price = bar.open * (1 + slip) if delta > 0 else bar.open * (1 - slip)
                    notional = abs(delta) * bar.open
                    commission = max(notional * self.cost.commission_rate, self.cost.min_commission)
                    slippage_cost = abs(delta) * bar.open * slip
                    cash -= delta * exec_price  # buying spends cash, selling adds
                    cash -= commission
                    shares = target_shares
                    result.total_commission += commission
                    result.total_slippage += slippage_cost
                    result.trades.append(
                        Trade(
                            ts=bar.ts,
                            side=side,
                            shares=abs(delta),
                            price=exec_price,
                            notional=notional,
                            commission=commission,
                            slippage=slippage_cost,
                        )
                    )

            equity = cash + shares * bar.close
            result.equity_curve.append(
                EquityPoint(
                    ts=bar.ts,
                    equity=equity,
                    position_shares=shares,
                    cash=cash,
                    target_weight=weights[i],
                )
            )

        return result

    def _oos_start(self, bars: list[Bar]) -> str | None:
        frac = self.backtest.oos_fraction
        if frac <= 0 or frac >= 1:
            return None
        split_idx = int(round(len(bars) * (1 - frac)))
        split_idx = max(1, min(split_idx, len(bars) - 1))
        return bars[split_idx].ts

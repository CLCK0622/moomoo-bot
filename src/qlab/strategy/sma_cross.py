"""Example fixture strategy: simple moving-average crossover.

Long (+1) when the fast SMA is above the slow SMA, flat (0) otherwise. This is a
textbook demo used only to exercise the pipeline end-to-end — it is NOT a vetted or
profitable strategy and makes no performance claim.
"""

from __future__ import annotations

from ..data.base import Bar
from .base import Strategy


class SmaCrossStrategy(Strategy):
    name = "sma_cross"

    def __init__(self, fast: int = 10, slow: int = 30, allow_short: bool = False) -> None:
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast = fast
        self.slow = slow
        self.allow_short = allow_short

    def target_weights(self, bars: list[Bar]) -> list[float]:
        closes = [b.close for b in bars]
        weights: list[float] = []
        for i in range(len(closes)):
            if i + 1 < self.slow:
                weights.append(0.0)  # not enough history yet
                continue
            fast_ma = sum(closes[i + 1 - self.fast : i + 1]) / self.fast
            slow_ma = sum(closes[i + 1 - self.slow : i + 1]) / self.slow
            if fast_ma > slow_ma:
                weights.append(1.0)
            elif self.allow_short and fast_ma < slow_ma:
                weights.append(-1.0)
            else:
                weights.append(0.0)
        return weights

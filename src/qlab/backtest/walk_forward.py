"""Walk-Forward runner — v1.0 §3 关4 主口径.

Re-fits a model on each training window and applies *only those* parameters to the
immediately following, untouched test window; the contiguous test windows tile the
post-initial-train region, so the engine — run once over the full series — compounds
them into one continuous out-of-sample net-equity curve (the "stitched OOS curve").
Gate 1+2+3 then apply to that curve (the closest-to-live check in v1.0).

No future information leaks into a test window: each fold's parameters come solely
from bars strictly before that window, and ``Model.predict`` is causal per bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import BacktestConfig, CostConfig
from ..data.base import Bar
from ..model.base import Model
from ..strategy.base import Strategy
from .engine import BacktestResult, BacktestRunner


class PrecomputedWeightsStrategy(Strategy):
    """Strategy that simply replays a precomputed per-bar target-weight vector."""

    name = "walk_forward"

    def __init__(self, weights: list[float], name: str = "walk_forward") -> None:
        self._weights = weights
        self.name = name

    def target_weights(self, bars: list[Bar]) -> list[float]:
        if len(self._weights) != len(bars):
            raise ValueError("precomputed weights length must match bars")
        return list(self._weights)


@dataclass
class WalkForwardResult:
    result: BacktestResult  # full-series backtest using the WF-refit weights
    oos_start_index: int  # first bar of the stitched out-of-sample region
    n_folds: int

    def oos_curve(self) -> tuple[list[str], list[float]]:
        """(timestamps, equity) of the stitched OOS curve, starting one bar early
        so the first OOS return is captured."""
        start = max(0, self.oos_start_index - 1)
        pts = self.result.equity_curve[start:]
        return [p.ts for p in pts], [p.equity for p in pts]


def run_walk_forward(
    symbol: str,
    bars: list[Bar],
    model_factory: Callable[[], Model],
    cost: CostConfig,
    backtest: BacktestConfig,
    *,
    train_bars: int = 252,
    test_bars: int = 63,
    anchored: bool = True,
) -> WalkForwardResult:
    """Anchored (default) or rolling Walk-Forward.

    - anchored: train window = all bars before the test window (expanding).
    - rolling:  train window = the trailing ``train_bars`` before the test window.
    """
    n = len(bars)
    if n <= train_bars + 1:
        raise ValueError("not enough bars for a walk-forward (need > train_bars + 1)")

    weights = [0.0] * n  # flat during the initial training region
    pos = train_bars
    n_folds = 0
    while pos < n:
        test_end = min(pos + test_bars, n)
        train_start = 0 if anchored else max(0, pos - train_bars)
        model = model_factory().fit(bars[train_start:pos])
        preds = model.predict(bars[:test_end])  # causal; params fixed for this fold
        for i in range(pos, test_end):
            weights[i] = preds[i]
        pos = test_end
        n_folds += 1

    strategy = PrecomputedWeightsStrategy(weights, name="walk_forward")
    result = BacktestRunner(cost, backtest).run(symbol, bars, strategy)
    return WalkForwardResult(result=result, oos_start_index=train_bars, n_folds=n_folds)

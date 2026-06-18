"""Fixture model: a trivially-trainable momentum threshold.

``fit`` "learns" a lookback and a return threshold by scanning the training bars
for the lookback that best separates up-days from down-days (a toy objective). The
result is a tiny, JSON-serialisable parameter set, demonstrating the full
train -> persist -> reload -> predict loop without any ML dependency.

This is engineering scaffolding to validate the model interface — it is NOT a
researched alpha and asserts nothing about real performance.
"""

from __future__ import annotations

from ..data.base import Bar
from ..strategy.base import Strategy
from .base import Model, register_model


def _momentum(closes: list[float], i: int, lookback: int) -> float:
    if i < lookback or closes[i - lookback] == 0:
        return 0.0
    return closes[i] / closes[i - lookback] - 1.0


@register_model
class MomentumModel(Model):
    kind = "momentum"

    def __init__(self, lookback: int = 20, threshold: float = 0.0) -> None:
        self.lookback = lookback
        self.threshold = threshold

    def fit(self, bars: list[Bar]) -> MomentumModel:
        closes = [b.close for b in bars]
        best_lb, best_score = self.lookback, -1.0
        for lb in (5, 10, 20, 40, 60):
            if lb >= len(closes):
                continue
            hits = total = 0
            for i in range(lb, len(closes) - 1):
                signal_up = _momentum(closes, i, lb) > 0
                next_up = closes[i + 1] > closes[i]
                hits += int(signal_up == next_up)
                total += 1
            score = hits / total if total else 0.0
            if score > best_score:
                best_score, best_lb = score, lb
        self.lookback = best_lb
        self.threshold = 0.0
        return self

    def predict(self, bars: list[Bar]) -> list[float]:
        closes = [b.close for b in bars]
        out: list[float] = []
        for i in range(len(closes)):
            mom = _momentum(closes, i, self.lookback)
            out.append(1.0 if mom > self.threshold else 0.0)
        return out

    def params(self) -> dict:
        return {"lookback": self.lookback, "threshold": self.threshold}

    @classmethod
    def from_params(cls, params: dict) -> MomentumModel:
        return cls(lookback=int(params["lookback"]), threshold=float(params["threshold"]))


class MomentumStrategy(Strategy):
    """Adapter exposing a (trained) :class:`MomentumModel` as a Strategy."""

    name = "momentum_model"

    def __init__(self, model: MomentumModel) -> None:
        self.model = model

    def target_weights(self, bars: list[Bar]) -> list[float]:
        return self.model.predict(bars)

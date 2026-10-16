"""Earnings-surprise sign classification.

Two modes, matching the EVO-24 spec:

* ``analyst`` — when a consensus estimate exists, use the sign of the
  standardized surprise (with a dead-zone so near-zero surprises trade nothing).
* ``abn_return_quantile`` — the fallback when no estimate is available: rank the
  post-announcement abnormal return into quantiles; the top tail is a positive
  surprise (long), the bottom tail a negative surprise (defined-risk options),
  the middle trades nothing. This is exactly "若 analyst estimate 不可得，先用公告后
  abnormal return 分位作为 surprise proxy".

The quantile thresholds are a *fittable* object so walk-forward can fit them on
the training window ONLY and apply them out-of-sample — using full-sample
quantiles in an OOS test would leak future information (EVO-12 §3 关4 / §5.2).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def analyst_sign(z: float | None, dead_zone: float = 0.0) -> int:
    """+1 / 0 / -1 from a standardized analyst surprise, ``None`` → 0."""
    if z is None:
        return 0
    if z > dead_zone:
        return 1
    if z < -dead_zone:
        return -1
    return 0


@dataclass(frozen=True)
class QuantileThresholds:
    """Lower/upper reaction-return cutoffs defining the negative/positive tails."""

    low: float
    high: float
    q: float
    n_fit: int

    @classmethod
    def fit(cls, reactions: list[float], q: float = 0.2) -> "QuantileThresholds":
        """Fit tail cutoffs from a reference set of reaction returns.

        ``q`` is the tail fraction on each side (0.2 → bottom 20% negative, top
        20% positive). Requires enough points to be meaningful; with too few it
        falls back to a symmetric ±small band and records ``n_fit`` so the caller
        can flag low-confidence classification.
        """
        arr = np.asarray([r for r in reactions if r is not None and np.isfinite(r)], dtype=float)
        if arr.size < 5:
            return cls(low=-0.02, high=0.02, q=q, n_fit=int(arr.size))
        low = float(np.quantile(arr, q))
        high = float(np.quantile(arr, 1.0 - q))
        return cls(low=low, high=high, q=q, n_fit=int(arr.size))

    def sign(self, reaction: float | None) -> int:
        if reaction is None or not np.isfinite(reaction):
            return 0
        if reaction >= self.high:
            return 1
        if reaction <= self.low:
            return -1
        return 0

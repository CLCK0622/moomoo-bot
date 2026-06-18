"""Strategy abstraction.

A strategy maps a bar history to a series of *target weights* — one per bar, each
in ``[-1.0, 1.0]`` (fraction of equity; negative = short). The engine consumes the
weights and handles sizing, costs and accounting.

Critical no-lookahead rule: ``target_weights`` returns a list the same length as
``bars``, where element *i* may only use information from bars ``0..i``. The engine
additionally applies each weight to the *next* bar to avoid same-bar fill bias.
Concrete strategies should respect this so backtests are not optimistic.
"""

from __future__ import annotations

import abc

from ..data.base import Bar


class Strategy(abc.ABC):
    name: str = "strategy"

    @abc.abstractmethod
    def target_weights(self, bars: list[Bar]) -> list[float]:
        """Return one target weight per bar, using only past/current information."""
        raise NotImplementedError

    @staticmethod
    def _clamp(weight: float) -> float:
        return max(-1.0, min(1.0, weight))

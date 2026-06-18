"""Strategy layer: abstract :class:`Strategy` + fixture implementations."""

from .base import Strategy
from .sma_cross import SmaCrossStrategy

__all__ = ["Strategy", "SmaCrossStrategy"]

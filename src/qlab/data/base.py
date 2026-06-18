"""Data ingest abstraction.

A :class:`DataSource` yields an ordered, gap-checked list of OHLCV :class:`Bar`
objects for a symbol over a date range. Concrete sources (fixtures, moomoo OpenD,
a future vendor API) only implement :meth:`DataSource._fetch`; validation and
ordering live in the base class so every source behaves identically downstream.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Bar:
    """A single OHLCV bar. ``ts`` is an ISO date string (``YYYY-MM-DD``)."""

    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_date(self) -> date:
        return date.fromisoformat(self.ts)


class DataSource(abc.ABC):
    """Abstract market-data source.

    Subclasses implement :meth:`_fetch`. Callers use :meth:`load`, which guarantees
    the returned bars are date-sorted, de-duplicated and validated.
    """

    @abc.abstractmethod
    def _fetch(self, symbol: str, start: str | None, end: str | None) -> list[Bar]:
        """Return raw bars for ``symbol`` between ``start`` and ``end`` (inclusive)."""
        raise NotImplementedError

    def load(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
    ) -> list[Bar]:
        bars = self._fetch(symbol, start, end)
        return self._normalise(bars, start, end)

    @staticmethod
    def _normalise(bars: list[Bar], start: str | None, end: str | None) -> list[Bar]:
        seen = set()
        cleaned: list[Bar] = []
        for bar in sorted(bars, key=lambda b: b.ts):
            if bar.ts in seen:
                continue
            if start and bar.ts < start:
                continue
            if end and bar.ts > end:
                continue
            if bar.high < bar.low:
                raise ValueError(f"invalid bar {bar.ts}: high < low")
            if bar.close <= 0 or bar.open <= 0:
                raise ValueError(f"invalid bar {bar.ts}: non-positive price")
            seen.add(bar.ts)
            cleaned.append(bar)
        return cleaned

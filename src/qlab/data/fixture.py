"""Fixture data source.

Two modes, both fully offline:

1. CSV-backed: reads ``<fixtures_dir>/<symbol>.csv`` with header
   ``ts,open,high,low,close,volume``.
2. Synthetic: if no CSV exists, generates a deterministic seeded random walk so
   the whole pipeline runs and tests stay reproducible. This is a *fixture only* —
   it is engineering scaffolding, never a claim about strategy performance.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import date, timedelta

from .base import Bar, DataSource


class FixtureDataSource(DataSource):
    def __init__(
        self,
        fixtures_dir: str = "fixtures",
        *,
        synthetic_days: int = 750,
        seed: int = 42,
        start_date: str = "2021-01-04",
    ) -> None:
        self.fixtures_dir = fixtures_dir
        self.synthetic_days = synthetic_days
        self.seed = seed
        self.start_date = start_date

    def _fetch(self, symbol: str, start: str | None, end: str | None) -> list[Bar]:
        path = os.path.join(self.fixtures_dir, f"{symbol}.csv")
        if os.path.exists(path):
            return self._from_csv(path)
        return self._synthetic(symbol)

    @staticmethod
    def _from_csv(path: str) -> list[Bar]:
        bars: list[Bar] = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                bars.append(
                    Bar(
                        ts=row["ts"].strip(),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0) or 0),
                    )
                )
        return bars

    def _synthetic(self, symbol: str) -> list[Bar]:
        # Deterministic LCG so output is reproducible without numpy.
        seed = (self.seed + sum(ord(c) for c in symbol)) & 0xFFFFFFFF
        state = seed or 1

        def rand() -> float:  # uniform in [0, 1)
            nonlocal state
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            return state / 0x7FFFFFFF

        bars: list[Bar] = []
        price = 100.0
        cur = date.fromisoformat(self.start_date)
        produced = 0
        while produced < self.synthetic_days:
            if cur.weekday() < 5:  # skip weekends
                drift = 0.0002
                shock = (rand() - 0.5) * 0.03
                ret = drift + shock
                open_p = price
                close_p = max(0.01, open_p * (1 + ret))
                high_p = max(open_p, close_p) * (1 + rand() * 0.01)
                low_p = min(open_p, close_p) * (1 - rand() * 0.01)
                vol = math.floor(1_000_000 * (0.5 + rand()))
                bars.append(
                    Bar(
                        ts=cur.isoformat(),
                        open=round(open_p, 4),
                        high=round(high_p, 4),
                        low=round(low_p, 4),
                        close=round(close_p, 4),
                        volume=float(vol),
                    )
                )
                price = close_p
                produced += 1
            cur += timedelta(days=1)
        return bars

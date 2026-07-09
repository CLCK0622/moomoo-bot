"""Earnings-announcement event sources.

An :class:`EarningsEvent` is a single scheduled earnings release with, at
minimum, a *timestamp* and a *session* tag (before-market-open / after-market-
close / intraday). The session tag is load-bearing: it decides which daily bar
first reflects the news and therefore the earliest look-ahead-free entry (see
``strategy.py``). Per the EVO-24 hard constraint we ``严格区分盘前/盘后`` — an
announcement whose session cannot be determined is NOT silently bucketed.

Implementations mirror ``qlab/datasource.py``:

* :class:`CsvEventSource` — real earnings timestamps someone fetched and handed
  over (columns ``symbol, announce_time, session[, analyst_surprise]``). This is
  the path to a real verdict; it needs genuine data on disk.
* :class:`SyntheticEventSource` — deterministic seeded events. HARNESS
  VALIDATION ONLY; any returns derived from these are meaningless.

There is deliberately no live "pull earnings calendar from an API" source here:
in this workspace no such feed is wired, and inventing one would hide the gap.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

# US regular trading hours (Eastern). Announcements strictly before the open are
# "bmo" (before market open), strictly at/after the close are "amc" (after market
# close); anything landing inside RTH is "intraday" and flagged, not guessed.
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

VALID_SESSIONS = ("bmo", "amc", "intraday")


def classify_session(ts: pd.Timestamp) -> str:
    """Classify an announcement timestamp into ``bmo`` / ``amc`` / ``intraday``.

    ``ts`` is assumed to be in US market (Eastern) wall-clock time. Callers that
    hold UTC or tz-aware stamps must convert to Eastern *before* calling — the
    session boundary is defined in market local time, and getting the timezone
    wrong silently mislabels bmo/amc, which is exactly the error the constraint
    warns against.
    """
    t = pd.Timestamp(ts).time()
    if t < RTH_OPEN:
        return "bmo"
    if t >= RTH_CLOSE:
        return "amc"
    return "intraday"


@dataclass(frozen=True)
class EarningsEvent:
    """One earnings announcement.

    Attributes
    ----------
    symbol:
        Underlying ticker (no ``US.`` prefix).
    announce_time:
        Wall-clock announcement timestamp in market (Eastern) time.
    session:
        ``bmo`` / ``amc`` / ``intraday`` — see :func:`classify_session`.
    analyst_surprise:
        Signed standardized earnings surprise (e.g. SUE, or (actual-estimate)/|estimate|)
        if a consensus estimate is available; ``None`` when it is not, in which
        case the backtester falls back to the abnormal-return quantile proxy
        (per EVO-24: "若 analyst estimate 不可得，先用公告后 abnormal return 分位
        作为 surprise proxy").
    source:
        Free-text provenance for this single event (e.g. ``sec_8k``, ``vendor_x``).
    """

    symbol: str
    announce_time: pd.Timestamp
    session: str
    analyst_surprise: float | None = None
    source: str = "unknown"

    @property
    def announce_date(self) -> pd.Timestamp:
        return pd.Timestamp(self.announce_time).normalize()

    @classmethod
    def from_parts(cls, symbol: str, announce_time, session: str | None = None,
                   analyst_surprise: float | None = None, source: str = "unknown") -> "EarningsEvent":
        ts = pd.Timestamp(announce_time)
        sess = (session or classify_session(ts)).lower()
        if sess not in VALID_SESSIONS:
            raise ValueError(f"session must be one of {VALID_SESSIONS}, got {session!r}")
        return cls(symbol=symbol.upper(), announce_time=ts, session=sess,
                   analyst_surprise=analyst_surprise, source=source)


class EventSource(Protocol):
    name: str

    def events(self) -> list[EarningsEvent]:
        ...

    def provenance(self) -> dict:
        ...


class CsvEventSource:
    """Load real earnings timestamps from a CSV.

    Required columns: ``symbol``, ``announce_time``. Optional: ``session``
    (else derived from the timestamp), ``analyst_surprise``, ``source``.
    """

    name = "csv"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def events(self) -> list[EarningsEvent]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found. Supply a CSV of real earnings timestamps "
                "(columns symbol, announce_time[, session, analyst_surprise, source]). "
                "This is the only path to a real verdict — no such feed is wired in "
                "this workspace."
            )
        out: list[EarningsEvent] = []
        with self.path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                out.append(EarningsEvent.from_parts(
                    symbol=row["symbol"],
                    announce_time=row["announce_time"],
                    session=(row.get("session") or None),
                    analyst_surprise=(float(row["analyst_surprise"])
                                      if row.get("analyst_surprise") not in (None, "", "nan")
                                      else None),
                    source=row.get("source") or "csv",
                ))
        return sorted(out, key=lambda e: (e.announce_time, e.symbol))

    def provenance(self) -> dict:
        return {
            "source": "csv",
            "path": str(self.path),
            "performance_meaningful": True,
            "note": "real earnings timestamps supplied out-of-band; the verdict is "
                    "only valid if these are genuine announcement times with a "
                    "documented origin and correct bmo/amc tagging.",
        }


class SyntheticEventSource:
    """Deterministic seeded earnings calendar. HARNESS VALIDATION ONLY.

    Produces, per symbol, roughly-quarterly announcements over ``[start, end]``
    with a seeded bmo/amc mix and a seeded latent surprise sign. It is paired
    with :class:`~qlab.events.bars.SyntheticDailyBarSource`, which injects a
    matching post-announcement drift, so the *wiring* (event → entry → drift
    capture) can be proven end-to-end. The magnitudes are generator artifacts,
    never market performance.
    """

    name = "synthetic_seeded"

    def __init__(self, symbols: list[str], start: str, end: str, seed: int = 0,
                 quarters_per_year: int = 4):
        self._symbols = list(symbols)
        self.start = start
        self.end = end
        self.seed = seed
        self.quarters_per_year = quarters_per_year

    def _symbol_seed(self, symbol: str) -> int:
        return (self.seed * 1_000_003 + sum(ord(c) for c in symbol) * 7919) % (2**31 - 1)

    def events(self) -> list[EarningsEvent]:
        out: list[EarningsEvent] = []
        step_days = int(round(252 / self.quarters_per_year))
        bdays = pd.bdate_range(self.start, self.end)
        if len(bdays) == 0:
            return out
        for symbol in self._symbols:
            rng = np.random.RandomState(self._symbol_seed(symbol))
            # first announcement offset into the window, then ~quarterly
            idx = int(rng.randint(5, max(6, step_days)))
            while idx < len(bdays):
                day = bdays[idx]
                session = "bmo" if rng.rand() < 0.5 else "amc"
                hh, mm = (7, 30) if session == "bmo" else (16, 15)
                ts = pd.Timestamp(day.year, day.month, day.day, hh, mm)
                # latent standardized surprise (drives the injected drift sign)
                surprise = float(rng.normal(0.0, 1.0))
                out.append(EarningsEvent.from_parts(
                    symbol=symbol, announce_time=ts, session=session,
                    analyst_surprise=surprise, source="synthetic",
                ))
                idx += step_days + int(rng.randint(-3, 4))
        return sorted(out, key=lambda e: (e.announce_time, e.symbol))

    def provenance(self) -> dict:
        return {
            "source": "synthetic_seeded",
            "seed": self.seed,
            "date_range": [self.start, self.end],
            "quarters_per_year": self.quarters_per_year,
            "performance_meaningful": False,
            "note": "DETERMINISTIC SYNTHETIC EARNINGS CALENDAR — harness validation "
                    "only. Announcement times and surprises are generator artifacts.",
        }

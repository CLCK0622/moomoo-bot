"""Daily OHLCV bar sources for the event-drift package.

The event-drift strategies need **daily bars with a real open AND a real close**
per session — not a close-only series. This is the crux of candidate 5: the
overnight (close→open) return must be computed from the actual ``open[t+1]`` and
``close[t]``, never faked from close-to-close. The contract is therefore a frame
with columns ``[date, open, high, low, close, volume]`` (``date`` a normalized
trading day), plus a derived ``dollar_volume`` for the liquidity filter.

Implementations parallel ``qlab/datasource.py``:

* :class:`ParquetDailyBarSource` — real adjusted daily bars fetched out-of-band
  (``<symbol>_1d.parquet``). Path to a real verdict. In production these come
  from moomoo OpenD ``request_history_kline(ktype=K_DAY)`` (the fetcher already
  exists at ``vendor/qstrat/data/fetcher.py``; add ``"1d": KLType.K_DAY`` to its
  ``TIMEFRAME_MAP`` and persist to parquet) or from a free source (Stooq / SEC).
* :class:`SyntheticDailyBarSource` — deterministic seeded daily bars with a
  post-announcement drift *injected* at each event's reaction bar, so the wiring
  can be validated end-to-end. HARNESS ONLY; magnitudes are artifacts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from .eventsource import EarningsEvent
from .timing import reaction_index

DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def _with_dollar_volume(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values("date").reset_index(drop=True)
    # crude ADV proxy: bar volume × typical price
    df["dollar_volume"] = df["volume"] * (df["high"] + df["low"] + df["close"]) / 3.0
    return df


class DailyBarSource(Protocol):
    name: str

    def symbols(self) -> list[str]:
        ...

    def load(self, symbol: str) -> pd.DataFrame | None:
        ...

    def provenance(self) -> dict:
        ...


class ParquetDailyBarSource:
    """Load real daily bars from ``<dir>/<symbol>_1d.parquet``."""

    name = "parquet_daily"

    def __init__(self, data_dir: str | Path, symbols: list[str]):
        self.data_dir = Path(data_dir)
        self._symbols = list(symbols)

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def load(self, symbol: str) -> pd.DataFrame | None:
        path = self.data_dir / f"{symbol}_1d.parquet"
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        # accept a "time" column as an alias for "date"
        if "date" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "date"})
        missing = [c for c in DAILY_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path} missing columns {missing}")
        return _with_dollar_volume(df[DAILY_COLUMNS])

    def provenance(self) -> dict:
        return {
            "source": "parquet_daily",
            "data_dir": str(self.data_dir),
            "performance_meaningful": True,
            "note": "real daily open/high/low/close/volume supplied out-of-band; "
                    "verdict valid only if these are genuine, split/dividend-"
                    "adjusted bars with documented origin.",
        }


class SyntheticDailyBarSource:
    """Deterministic daily bars with earnings drift injected. HARNESS ONLY.

    A geometric random walk with *distinct* overnight and intraday legs (so
    close→open is a real, non-degenerate quantity), into which each event injects
    an announcement gap at its reaction bar plus a decaying post-announcement
    drift in the direction of the event's latent surprise sign. The drift is
    overnight-weighted so candidate 5 (close-to-open) captures the bulk while
    candidate 4 (buy-and-hold) still sees a positive signal.
    """

    name = "synthetic_daily_seeded"

    def __init__(self, symbols: list[str], start: str, end: str, seed: int = 0,
                 events: list[EarningsEvent] | None = None,
                 gap0: float = 0.05, drift0: float = 0.006, tau: float = 8.0,
                 drift_len: int = 35, overnight_weight: float = 0.6):
        self._symbols = list(symbols)
        self.start = start
        self.end = end
        self.seed = seed
        self._events_by_symbol: dict[str, list[EarningsEvent]] = {}
        for ev in (events or []):
            self._events_by_symbol.setdefault(ev.symbol, []).append(ev)
        self.gap0 = gap0
        self.drift0 = drift0
        self.tau = tau
        self.drift_len = drift_len
        self.overnight_weight = overnight_weight
        self._cache: dict[str, pd.DataFrame] = {}

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def _symbol_seed(self, symbol: str) -> int:
        return (self.seed * 2_650_000_011 + sum(ord(c) for c in symbol) * 6151) % (2**31 - 1)

    def _generate(self, symbol: str) -> pd.DataFrame:
        rng = np.random.RandomState(self._symbol_seed(symbol))
        dates = pd.bdate_range(self.start, self.end)
        n = len(dates)
        if n == 0:
            return _with_dollar_volume(pd.DataFrame(columns=DAILY_COLUMNS))

        # baseline distinct overnight / intraday legs
        overnight = rng.normal(0.0, 0.006, size=n)
        intraday = rng.normal(0.0001, 0.010, size=n)

        # inject drift for each event in the direction of its surprise
        didx = pd.DatetimeIndex(dates)
        for ev in self._events_by_symbol.get(symbol, []):
            r = reaction_index(didx, ev.announce_date, ev.session)
            if r is None:
                continue
            sign = 1.0 if (ev.analyst_surprise or 0.0) >= 0 else -1.0
            mag = min(abs(ev.analyst_surprise or 1.0), 3.0) / 1.5
            # announcement gap on the reaction bar's overnight leg (the surprise
            # signal — the strategy will NOT trade this leg)
            overnight[r] += sign * self.gap0 * mag
            # decaying post-announcement drift, overnight-weighted
            for k in range(self.drift_len):
                j = r + k
                if j >= n:
                    break
                d = sign * self.drift0 * mag * float(np.exp(-k / self.tau))
                overnight[j] += self.overnight_weight * d
                intraday[j] += (1.0 - self.overnight_weight) * d

        prev_close = float(rng.uniform(40.0, 400.0))
        rows = []
        for t in range(n):
            open_px = max(prev_close * (1.0 + overnight[t]), 1.0)
            close_px = max(open_px * (1.0 + intraday[t]), 0.5)
            hi = max(open_px, close_px) * (1.0 + abs(rng.normal(0.0, 0.003)))
            lo = min(open_px, close_px) * (1.0 - abs(rng.normal(0.0, 0.003)))
            vol = float(rng.randint(1_000_000, 8_000_000))
            rows.append((dates[t], open_px, hi, lo, close_px, vol))
            prev_close = close_px

        df = pd.DataFrame(rows, columns=DAILY_COLUMNS)
        return _with_dollar_volume(df)

    def load(self, symbol: str) -> pd.DataFrame | None:
        if symbol not in self._cache:
            self._cache[symbol] = self._generate(symbol)
        return self._cache[symbol].copy()

    def provenance(self) -> dict:
        return {
            "source": "synthetic_daily_seeded",
            "seed": self.seed,
            "date_range": [self.start, self.end],
            "performance_meaningful": False,
            "note": "DETERMINISTIC SYNTHETIC DAILY BARS with injected earnings drift "
                    "— harness validation only. Returns here are an artifact of the "
                    "generator, NOT strategy performance.",
        }

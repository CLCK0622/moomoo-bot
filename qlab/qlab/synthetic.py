"""Deterministic synthetic intraday bars — HARNESS VALIDATION ONLY.

Generates seeded 1m and 15m OHLCV sessions so the full pipeline
(preprocess -> indicators -> engine -> metrics -> battery -> artifacts) can be
exercised end-to-end and proven reproducible (same seed -> identical bytes).

⚠️  Returns produced on these bars are an artifact of the generator, NOT of any
real market. They must never be presented as strategy performance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _trading_days(start: str, end: str) -> list[pd.Timestamp]:
    days = pd.bdate_range(start=start, end=end)
    return [d for d in days]


def _session_1m(rng: np.random.RandomState, day: pd.Timestamp, prev_close: float) -> pd.DataFrame:
    """One 09:30–15:59 session of 1-minute bars (390 bars)."""
    n = 390
    times = [day + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=i) for i in range(n)]

    # Opening gap from previous close
    gap = rng.normal(0.0, 0.004)
    open_px = max(prev_close * (1.0 + gap), 1.0)

    # Per-minute log-return process. The first 15 minutes set the opening range;
    # then with some probability the day trends (breakout) vs mean-reverts.
    base_vol = 0.0010
    drift_sign = rng.choice([-1.0, 0.0, 1.0], p=[0.30, 0.25, 0.45])
    drift = drift_sign * rng.uniform(0.00002, 0.00010)

    rets = rng.normal(drift, base_vol, size=n)
    rets[:15] = rng.normal(0.0, base_vol * 1.4, size=15)  # wider opening range

    close = open_px * np.exp(np.cumsum(rets))
    # Build OHLC around the close path
    opens = np.empty(n)
    opens[0] = open_px
    opens[1:] = close[:-1]
    highs = np.maximum(opens, close) * (1.0 + np.abs(rng.normal(0.0, base_vol * 0.6, size=n)))
    lows = np.minimum(opens, close) * (1.0 - np.abs(rng.normal(0.0, base_vol * 0.6, size=n)))
    vol = rng.randint(20_000, 120_000, size=n).astype(float)
    # Volume spike near random intraday minutes to feed volume_spike indicator
    spike_idx = rng.choice(np.arange(20, n), size=3, replace=False)
    vol[spike_idx] *= rng.uniform(2.5, 4.0)

    return pd.DataFrame({
        "time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": close,
        "volume": vol,
    })


def generate_symbol(symbol: str, start: str, end: str, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (df_1m, df_15m) for one symbol across the date range."""
    # Stable per-symbol seed so output is reproducible and symbol-distinct.
    sym_seed = (seed * 1_000_003 + sum(ord(c) for c in symbol) * 7919) % (2**31 - 1)
    rng = np.random.RandomState(sym_seed)

    prev_close = float(rng.uniform(40.0, 400.0))
    sessions = []
    for day in _trading_days(start, end):
        sess = _session_1m(rng, day, prev_close)
        prev_close = float(sess["close"].iloc[-1])
        sessions.append(sess)

    df_1m = pd.concat(sessions, ignore_index=True)

    # Derive 15m bars by resampling the 1m frame (consistent by construction).
    g = df_1m.set_index("time")
    df_15m = pd.DataFrame({
        "open": g["open"].resample("15min").first(),
        "high": g["high"].resample("15min").max(),
        "low": g["low"].resample("15min").min(),
        "close": g["close"].resample("15min").last(),
        "volume": g["volume"].resample("15min").sum(),
    }).dropna().reset_index()

    return df_1m, df_15m


class SyntheticDataSource:
    """DataSource backed by :func:`generate_symbol`. Validation only."""

    name = "synthetic_seeded"

    def __init__(self, symbols: list[str], start: str, end: str, seed: int = 0):
        self._symbols = list(symbols)
        self.start = start
        self.end = end
        self.seed = seed
        self._cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def _gen(self, symbol: str):
        if symbol not in self._cache:
            self._cache[symbol] = generate_symbol(symbol, self.start, self.end, self.seed)
        return self._cache[symbol]

    def load(self, symbol: str, timeframe: str):
        df_1m, df_15m = self._gen(symbol)
        return df_1m.copy() if timeframe == "1m" else df_15m.copy()

    def provenance(self) -> dict:
        return {
            "source": "synthetic_seeded",
            "seed": self.seed,
            "date_range": [self.start, self.end],
            "performance_meaningful": False,
            "note": "DETERMINISTIC SYNTHETIC DATA — harness validation only. "
                    "Returns here are NOT strategy performance.",
        }

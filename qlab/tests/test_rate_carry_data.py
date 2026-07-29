"""Contract test for candidate A (rate-carry) committed universe bars.

Locks the data 营缮's A backtest depends on: the three total-return Treasury-ETF
parquets gathered into ``data/rate_carry/`` (BIL/IEF/TLT), their schema, the
frozen common window, crisis coverage, and — load-bearing — that they are
DIVIDEND-adjusted (total return), not price-only. Pure pandas, no network.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parents[1] / "data" / "rate_carry"
UNIVERSE = ["BIL", "IEF", "TLT"]
OHLCV = ["date", "open", "high", "low", "close", "volume"]
COMMON_START = pd.Timestamp("2007-05-30")
COMMON_END = pd.Timestamp("2026-07-17")

pytestmark = pytest.mark.skipif(
    not DATA.exists(), reason="data/rate_carry not present on this branch")


def _load(sym: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA / f"{sym}_1d.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


@pytest.mark.parametrize("sym", UNIVERSE)
def test_schema_and_integrity(sym):
    df = _load(sym)
    assert list(df.columns) == OHLCV, f"{sym} schema drift"
    assert df["date"].duplicated().sum() == 0
    assert df[["open", "high", "low", "close"]].isna().sum().sum() == 0
    assert (df["close"] > 0).all()
    assert df["date"].is_monotonic_increasing


@pytest.mark.parametrize("sym", UNIVERSE)
def test_covers_common_window_and_2022(sym):
    df = _load(sym).set_index("date")
    assert df.index.min() <= COMMON_START
    assert df.index.max() >= COMMON_END
    # the killer window must be fully inside
    assert len(df.loc["2022-01-01":"2022-12-31"]) > 200


def test_three_are_calendar_aligned_on_common_window():
    idx = None
    per = {}
    for s in UNIVERSE:
        w = _load(s).set_index("date").loc[COMMON_START:COMMON_END]
        per[s] = len(w)
        idx = set(w.index) if idx is None else (idx & set(w.index))
    # every symbol has exactly the same trading days in the window
    assert len(set(per.values())) == 1, f"row-count mismatch {per}"
    assert len(idx) == next(iter(per.values())), "dates not aligned across symbols"


def test_bars_are_dividend_adjusted_total_return():
    """Bond ETFs: price-only would drift to ~0 CAGR; total-return does not.

    TLT's back-adjusted 2006 start (~44) sits far below its ~88 listing price —
    the fingerprint of ~19y of coupons folded in. A price-only series can't.
    """
    tlt = _load("TLT")
    start_close = tlt["close"].iloc[0]
    assert start_close < 60, (
        f"TLT start close {start_close:.2f} looks price-only (listing ~88); "
        "candidate A needs dividend-adjusted total-return bars")
    yrs = (tlt["date"].iloc[-1] - tlt["date"].iloc[0]).days / 365.25
    cagr = (tlt["close"].iloc[-1] / start_close) ** (1 / yrs) - 1
    assert cagr > 0.02, f"TLT total-return CAGR {cagr:.3f} too low to be total return"

"""Offline unit tests for the EVO-24 out-of-band data fetchers.

No network: the SEC path is exercised through a canned submissions payload so
the load-bearing timezone/session logic and the 8-K item-2.02 filter are pinned
deterministically. The real end-to-end pull lives in fetch_all (network) and is
documented in the manifest, not here.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from qlab.events.datafetch import prices as price_mod
from qlab.events.datafetch.prices import _normalize, _solve_stooq_pow
from qlab.events.datafetch.sec_earnings import (_acceptance_to_eastern,
                                                fetch_symbol_events,
                                                write_earnings_csv)
from qlab.events.eventsource import CsvEventSource, classify_session


# --------------------------------------------------------------------------- #
# Timezone — the load-bearing bmo/amc conversion, pinned to verified fixtures
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("utc_stamp, expect_et_hhmm, expect_session", [
    # Apple, after close (verified against known ~16:30 ET release) — EST & EDT
    ("2026-01-29T21:30:33.000Z", "16:30", "amc"),
    ("2026-04-30T20:30:41.000Z", "16:30", "amc"),
    # JPMorgan, pre-market (verified against known ~06:45 ET release) — EDT & EST
    ("2025-10-14T10:30:57.000Z", "06:30", "bmo"),
    ("2026-01-13T11:41:09.000Z", "06:41", "bmo"),
    # a hypothetical intraday acceptance stays intraday (never silently bucketed)
    ("2020-01-24T17:06:44.000Z", "12:06", "intraday"),
])
def test_acceptance_utc_to_eastern_session(utc_stamp, expect_et_hhmm, expect_session):
    et = _acceptance_to_eastern(utc_stamp)
    assert et.tzinfo is None  # naive Eastern wall-clock
    assert et.strftime("%H:%M") == expect_et_hhmm
    assert classify_session(et) == expect_session


def test_dst_offset_differs_across_year():
    # Jan is EST (UTC-5), Jul is EDT (UTC-4): same 20:30Z maps to different ET
    jan = _acceptance_to_eastern("2024-01-15T20:30:00.000Z")
    jul = _acceptance_to_eastern("2024-07-15T20:30:00.000Z")
    assert jan.strftime("%H:%M") == "15:30"   # EST
    assert jul.strftime("%H:%M") == "16:30"   # EDT


# --------------------------------------------------------------------------- #
# SEC filter — item 2.02 only, date window, dedup, session — via canned JSON
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    """Returns a canned submissions payload for the recent block, no 'files'."""

    def __init__(self, recent):
        self._recent = recent

    def get(self, url, timeout=30):
        return _FakeResp({"filings": {"recent": self._recent, "files": []}})


def test_fetch_symbol_events_filters_and_classifies():
    recent = {
        "form":       ["8-K",        "8-K",   "10-Q",      "8-K",        "8-K"],
        "items":      ["2.02,9.01",  "5.02",  "",          "2.02",       "2.02,9.01"],
        # amc(AAPL-like), non-earnings, wrong-form, bmo(JPM-like), out-of-window
        "acceptanceDateTime": [
            "2024-01-29T21:30:00.000Z",  # -> 16:30 ET amc, in window
            "2024-02-01T21:00:00.000Z",  # item 5.02, dropped
            "2024-02-02T21:00:00.000Z",  # 10-Q, dropped
            "2024-04-12T10:30:00.000Z",  # -> 06:30 ET bmo, in window
            "2018-01-05T21:30:00.000Z",  # before window, dropped
        ],
        "filingDate": ["2024-01-29", "2024-02-01", "2024-02-02", "2024-04-12", "2018-01-05"],
    }
    df = fetch_symbol_events(_FakeSession(recent), "TEST", "0000000000",
                             start="2024-01-01", end="2024-12-31")
    assert list(df["announce_time"]) == ["2024-01-29 16:30:00", "2024-04-12 06:30:00"]
    assert list(df["session"]) == ["amc", "bmo"]
    assert set(df["source"]) == {"sec_8k_2.02"}


def test_fetch_symbol_events_roundtrips_through_csveventsource(tmp_path):
    recent = {
        "form": ["8-K", "8-K"],
        "items": ["2.02", "2.02,9.01"],
        "acceptanceDateTime": ["2024-01-29T21:30:00.000Z", "2024-04-12T10:30:00.000Z"],
        "filingDate": ["2024-01-29", "2024-04-12"],
    }
    df = fetch_symbol_events(_FakeSession(recent), "test", "0000000000",
                             "2024-01-01", "2024-12-31")
    path = tmp_path / "earnings.csv"
    write_earnings_csv(df, path)
    events = CsvEventSource(path).events()
    assert len(events) == 2
    assert {e.symbol for e in events} == {"TEST"}
    assert {e.session for e in events} == {"amc", "bmo"}
    assert all(e.analyst_surprise is None for e in events)  # blank -> quantile proxy


# --------------------------------------------------------------------------- #
# Stooq proof-of-work solver — deterministic, small difficulty
# --------------------------------------------------------------------------- #
def test_solve_stooq_pow():
    body = 'foo(async()=>{const c="ABCDEF",d=2,t=...'
    c, n = _solve_stooq_pow(body)
    assert c == "ABCDEF"
    assert hashlib.sha256((c + str(n)).encode()).hexdigest().startswith("00")


def test_solve_stooq_pow_none_on_no_challenge():
    assert _solve_stooq_pow("Date,Open,High,Low,Close,Volume\n") is None


# --------------------------------------------------------------------------- #
# Price normalization — the ParquetDailyBarSource contract
# --------------------------------------------------------------------------- #
def test_normalize_sorts_dedups_and_keeps_contract():
    raw = pd.DataFrame({
        "date": ["2024-01-03", "2024-01-02", "2024-01-02"],
        "open": [3.0, 1.0, 1.0], "high": [3.5, 1.5, 1.5],
        "low": [2.9, 0.9, 0.9], "close": [3.2, 1.2, 1.2],
        "volume": [30, 10, 10],
    })
    out = _normalize(raw)
    assert list(out.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(out) == 2  # duplicate day collapsed
    assert list(out["date"].dt.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03"]


def test_yahoo_adjclose_rescale_preserves_close_ratio():
    # a fake chart payload with a 2:1 dividend-adjust factor on the first bar
    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"chart": {"result": [{
                "timestamp": [1704240000, 1704326400],
                "indicators": {
                    "quote": [{"open": [10.0, 20.0], "high": [11.0, 21.0],
                               "low": [9.0, 19.0], "close": [10.0, 20.0],
                               "volume": [100, 200]}],
                    "adjclose": [{"adjclose": [5.0, 20.0]}],
                }}]}}

    class _S:
        headers = {}

        def get(self, url, timeout=30):
            return _R()

    df, note = price_mod.fetch_yahoo("TEST", "2024-01-01", "2024-01-05", session=_S())
    # first bar rescaled by 0.5, second untouched; open/close ratio preserved
    assert abs(df.iloc[0]["close"] - 5.0) < 1e-9
    assert abs(df.iloc[0]["open"] - 5.0) < 1e-9
    assert abs(df.iloc[1]["close"] - 20.0) < 1e-9
    assert "adjusted" in note

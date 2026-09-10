"""Tests for the FRED Treasury-yield fetcher (candidate A data).

Offline by default (canned CSV via a fake session), pinning the load-bearing
bits: FRED's ``"."`` missing marker is dropped not filled, blocked pulls degrade
to an honest ``(None, note)`` gap, and multi-series join stays NaN-not-fabricated.
A network-gated live smoke fetches a real 2022 window when FRED is reachable.
"""
from __future__ import annotations

import pandas as pd
import pytest

from qlab.events.datafetch import fred_yields as fy


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status


class _FakeSession:
    """Serves a canned CSV per FRED series id (from the request params)."""

    def __init__(self, csv_by_id, status=200):
        self._csv = csv_by_id
        self._status = status
        self.headers = {}

    def get(self, url, params=None, timeout=30):
        if self._status != 200:
            return _Resp(status=self._status)
        sid = (params or {}).get("id")
        return _Resp(self._csv.get(sid, ""))


_DGS2 = ("observation_date,DGS2\n"
         "2022-01-03,0.78\n"
         "2022-01-04,0.77\n"
         "2022-01-17,.\n"        # MLK holiday -> "." must be dropped, not filled
         "2022-01-18,0.99\n")

_DGS10 = ("observation_date,DGS10\n"
          "2022-01-03,1.63\n"
          "2022-01-18,1.87\n")   # missing 01-04 -> stays NaN in the wide join


def test_missing_marker_dropped_not_filled():
    df, note = fy.fetch_fred_series("DGS2", "2022-01-01", "2022-02-01",
                                    session=_FakeSession({"DGS2": _DGS2}))
    assert df is not None, note
    # 4 rows in, the "." holiday row dropped -> 3 real observations
    assert len(df) == 3
    assert "2022-01-17" not in df["date"].dt.strftime("%Y-%m-%d").tolist()
    assert df["DGS2"].tolist() == [0.78, 0.77, 0.99]
    assert list(df.columns) == ["date", "DGS2"]


def test_blocked_source_is_honest_gap():
    df, note = fy.fetch_fred_series("DGS2", "2022-01-01", "2022-02-01",
                                    session=_FakeSession({}, status=429))
    assert df is None
    assert "http 429" in note


def test_curve_join_keeps_nan_never_fabricates():
    wide, notes = fy.fetch_curve(
        series=["DGS2", "DGS10"], start="2022-01-01", end="2022-02-01",
        session=_FakeSession({"DGS2": _DGS2, "DGS10": _DGS10}))
    assert list(wide.columns) == ["date", "DGS2", "DGS10"]
    # DGS10 has no 2022-01-04 -> that cell is NaN, not forward-filled
    row_0104 = wide[wide["date"] == "2022-01-04"]
    assert len(row_0104) == 1
    assert pd.isna(row_0104["DGS10"].iloc[0])
    assert row_0104["DGS2"].iloc[0] == 0.77
    # union of trading days across both series
    assert wide["date"].is_monotonic_increasing


def test_curve_all_blocked_returns_empty_with_notes():
    wide, notes = fy.fetch_curve(series=["DGS2", "DGS10"],
                                 session=_FakeSession({}, status=503))
    assert wide.empty
    assert all("http 503" in n for n in notes.values())


def test_live_fred_covers_2022_rate_shock():
    """Real fetch (network) — self-skips if FRED is unreachable from this host."""
    df, note = fy.fetch_fred_series("DGS2", "2022-01-01", "2022-12-31")
    if df is None:
        pytest.skip(f"FRED unreachable: {note}")
    assert len(df) > 200                       # ~249 trading days in 2022
    assert df["DGS2"].max() > 4.0              # the 2022 hiking cycle peak
    assert df["DGS2"].min() < 1.0              # started near zero

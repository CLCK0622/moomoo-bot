"""Contract test for candidate C (macro-credit regime) committed signal data.

Locks the BAA10YM data C's backtest depends on: the latest full-history panel
(covers 2008/2020/2022) and the vintage samples (whose publication cutoffs are
the material anti-look-ahead axis). Pure pandas, no network / no API key.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
LATEST = DATA / "credit_baa10ym_latest.parquet"
VINT = DATA / "credit_baa10ym_vintages.parquet"

pytestmark = pytest.mark.skipif(
    not LATEST.exists(), reason="credit BAA10YM data not present on this branch")


def _latest():
    df = pd.read_parquet(LATEST)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def test_latest_schema_and_integrity():
    df = _latest()
    assert list(df.columns) == ["date", "value"]
    assert df["date"].duplicated().sum() == 0
    assert df["value"].notna().all()
    assert df["date"].is_monotonic_increasing


@pytest.mark.parametrize("a,b,label", [
    ("2008-06-01", "2009-06-01", "2008 GFC"),
    ("2020-01-01", "2020-12-01", "2020 COVID"),
    ("2022-01-01", "2022-12-01", "2022 shock"),
])
def test_latest_covers_crisis_windows(a, b, label):
    df = _latest().set_index("date")
    assert len(df.loc[a:b]) >= 6, f"{label} under-covered"


def test_latest_2008_shows_credit_stress():
    # sanity: Baa-10y spread genuinely blew out in the GFC (well above normal ~2%)
    df = _latest().set_index("date")
    assert df.loc["2008-06-01":"2009-06-01", "value"].max() > 4.0


def test_vintages_present_and_publication_cutoff_honored():
    v = pd.read_parquet(VINT)
    assert list(v.columns) == ["as_of", "date", "value"]
    v["as_of"] = pd.to_datetime(v["as_of"])
    v["date"] = pd.to_datetime(v["date"])
    # each vintage snapshot must not contain observations dated after its as_of
    # (that would be look-ahead); and later as_of must know >= earlier as_of
    last_by_asof = v.groupby("as_of")["date"].max().sort_index()
    assert (last_by_asof.index >= last_by_asof.values).all(), "obs dated after as_of — look-ahead leak"
    assert last_by_asof.is_monotonic_increasing
    # brackets both crises we care about
    yrs = {ts.year for ts in last_by_asof.index}
    assert {2020, 2022} <= yrs

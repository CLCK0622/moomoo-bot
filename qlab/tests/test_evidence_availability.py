"""受理时刻 → 公开可得时刻 的派生规则测试（工部 2026-08-08：受理 ≠ 可得，实测 65% 需顺延）。"""
from __future__ import annotations

import pandas as pd
import pytest

from qlab.events.datafetch.evidence_availability import (annotate, derive_available_utc,
                                                          next_trading_open, summarize)

ET = "America/New_York"


def _et(s):
    return pd.Timestamp(s, tz=ET)


def test_intraday_acceptance_is_immediately_available():
    # 周三 14:00 ET 盘中受理 → 即时可得，不顺延
    got = derive_available_utc(_et("2026-06-17 14:00"))
    assert got == _et("2026-06-17 14:00").tz_convert("UTC")


def test_after_1730_rolls_to_next_trading_open():
    # 工部实测例：2026-06-17 18:40 ET 受理 → 次一交易日(6/18) 09:30 ET
    got = derive_available_utc(_et("2026-06-17 18:40"))
    assert got == _et("2026-06-18 09:30").tz_convert("UTC")


def test_exactly_1730_is_after_cutoff():
    got = derive_available_utc(_et("2026-05-29 17:30"))
    # 5/29 是周五 → 顺延到下周一 6/1 09:30
    assert got == _et("2026-06-01 09:30").tz_convert("UTC")


def test_premarket_rolls_to_same_day_open():
    # 07:06 ET 盘前受理 → 当日 09:30 开盘才可交易
    got = derive_available_utc(_et("2026-06-17 07:06"))
    assert got == _et("2026-06-17 09:30").tz_convert("UTC")


def test_weekend_rolls_to_monday_open():
    got = derive_available_utc(_et("2026-06-20 11:00"))   # 周六
    assert got == _et("2026-06-22 09:30").tz_convert("UTC")


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        derive_available_utc(pd.Timestamp("2026-06-17 18:40"))   # 无时区


def test_next_trading_open_skips_weekend():
    assert next_trading_open(_et("2026-06-19 18:00")).date() == pd.Timestamp("2026-06-22").date()


def test_annotate_preserves_original_and_adds_derived():
    recs = [{"source_time_utc": _et("2026-06-17 18:40").tz_convert("UTC").isoformat(), "x": 1}]
    out = annotate(recs)
    assert out[0]["x"] == 1                                   # 原字段不动
    assert out[0]["source_time_utc"] == recs[0]["source_time_utc"]   # 受理时刻留档
    assert out[0]["availability_rolled"] is True
    assert pd.Timestamp(out[0]["evidence_available_utc"]) > pd.Timestamp(recs[0]["source_time_utc"])


def test_annotate_missing_source_time_raises():
    with pytest.raises(ValueError):
        annotate([{"x": 1}])


def test_summarize_counts_rolled():
    recs = annotate([
        {"source_time_utc": _et("2026-06-17 18:40").tz_convert("UTC").isoformat()},   # roll
        {"source_time_utc": _et("2026-06-17 14:00").tz_convert("UTC").isoformat()},   # no roll
    ])
    s = summarize(recs)
    assert s["n"] == 2 and s["n_rolled"] == 1 and s["frac_rolled"] == 0.5

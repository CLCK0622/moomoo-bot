from __future__ import annotations

import json

import pytest

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.bar_archive import (ArchiveIntegrityError, archive_quote_snapshot,
                                        require_settlement_integrity,
                                        unresolved_disagreements)


def _bars(close: float = 101.0):
    return {"IBM": [DailyBar("IBM", "2026-08-31", close=close, open=100.0,
                              high=102.0, low=99.0, volume=7.0,
                              retrieved_utc="2026-08-31T12:00:00+00:00")]}


def test_archives_snapshot_with_content_hash_without_extra_fetch(tmp_path):
    result = archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260831",
                                    executor="single_book")
    record = json.loads((tmp_path / "bar_archive" /
                         result["archive_file"].split("/")[-1]).read_text(encoding="utf-8"))
    assert result["n_bars"] == 1 and result["symbols"] == ["IBM"]
    assert record["content_sha256"] == result["content_sha256"]
    assert record["bars"] == [{"close": 101.0, "date": "2026-08-31", "high": 102.0,
                                "low": 99.0, "open": 100.0, "source": "alphavantage:TIME_SERIES_DAILY",
                                "symbol": "IBM", "volume": 7.0}]


def test_refetch_compares_overlapping_symbol_date_field_by_field(tmp_path):
    archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260831", executor="single_book")
    result = archive_quote_snapshot(_bars(close=102.0), out_dir=str(tmp_path), stamp="20260901",
                                    executor="single_book",
                                    retrieved_utc="2026-09-01T12:00:00+00:00")
    assert result["unresolved_differences"][0]["differences"][0]["fields"]["close"] == {
        "archived": 101.0, "refetched": 102.0}
    assert len(list((tmp_path / "bar_archive").glob("*.json"))) == 2
    assert len(unresolved_disagreements(str(tmp_path))) == 1
    with pytest.raises(ArchiveIntegrityError, match="派生结算不得出"):
        require_settlement_integrity(str(tmp_path))


def test_tampered_archive_fails_closed_before_another_append(tmp_path):
    first = archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260831", executor="single_book")
    path = tmp_path / "bar_archive" / first["archive_file"].split("/")[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["bars"][0]["close"] = 0.01
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArchiveIntegrityError, match="哈希不匹配"):
        archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260901", executor="single_book",
                               retrieved_utc="2026-09-01T12:00:00+00:00")

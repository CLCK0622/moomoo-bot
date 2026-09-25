from __future__ import annotations

import json

import pytest

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.bar_archive import (ArchiveIntegrityError, archive_quote_snapshot,
                                        load_settlement_bars,
                                        require_settlement_integrity,
                                        unresolved_disagreements,
                                        write_disagreement_resolution)


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
    # The gate is deliberately scoped to the bars a settlement will consume:
    # an IBM correction cannot suppress an unrelated reading.
    require_settlement_integrity(str(tmp_path), keys={("CAT", "2026-08-31")})
    with pytest.raises(ArchiveIntegrityError, match="派生结算不得出"):
        require_settlement_integrity(str(tmp_path), keys={("IBM", "2026-08-31")})


def test_append_only_ruling_releases_only_the_same_observed_difference(tmp_path):
    archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260831", executor="single_book")
    changed = archive_quote_snapshot(_bars(close=102.0), out_dir=str(tmp_path), stamp="20260901",
                                     executor="single_book",
                                     retrieved_utc="2026-09-01T12:00:00+00:00")
    write_disagreement_resolution(
        out_dir=str(tmp_path), source_archive_content_sha256=changed["content_sha256"],
        keys={("IBM", "2026-08-31")}, selected_version="refetched",
        basis="数据供应商订正说明", ruling_reference="吏部裁定 #42",
        resolved_utc="2026-09-02T12:00:00+00:00")
    assert unresolved_disagreements(str(tmp_path)) == []
    require_settlement_integrity(str(tmp_path), keys={("IBM", "2026-08-31")})
    assert load_settlement_bars(str(tmp_path))["bars"][("IBM", "2026-08-31")]["close"] == 102.0

    # An identical future refetch is covered by the ruling, but a new provider
    # value is a fresh disagreement and cannot inherit the old ruling.
    archive_quote_snapshot(_bars(close=102.0), out_dir=str(tmp_path), stamp="20260908",
                           executor="single_book", retrieved_utc="2026-09-08T12:00:00+00:00")
    assert unresolved_disagreements(str(tmp_path)) == []
    archive_quote_snapshot(_bars(close=103.0), out_dir=str(tmp_path), stamp="20260915",
                           executor="single_book", retrieved_utc="2026-09-15T12:00:00+00:00")
    with pytest.raises(ArchiveIntegrityError, match="派生结算不得出"):
        require_settlement_integrity(str(tmp_path), keys={("IBM", "2026-08-31")})


def test_tampered_archive_fails_closed_before_another_append(tmp_path):
    first = archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260831", executor="single_book")
    path = tmp_path / "bar_archive" / first["archive_file"].split("/")[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["bars"][0]["close"] = 0.01
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArchiveIntegrityError, match="哈希不匹配"):
        archive_quote_snapshot(_bars(), out_dir=str(tmp_path), stamp="20260901", executor="single_book",
                               retrieved_utc="2026-09-01T12:00:00+00:00")

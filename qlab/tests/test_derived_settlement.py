"""Derived lower-bound settlement consumes immutable decisions and archived bars."""
from __future__ import annotations

import json

import pytest

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.archive_scan_state import write_scanner_state
from qlab.llm_paper.archive_scanner import archive_scan_coverage, scan_missing_archive_bars
from qlab.llm_paper.bar_archive import ArchiveIntegrityError, archive_quote_snapshot
from qlab.llm_paper.derived_settlement import (rebuild_lower_bound_settlement,
                                                require_reading_kind,
                                                SettlementDataUnavailable,
                                                write_lower_bound_settlement)
from qlab.llm_paper.nav_series import cell_nav_series, cumulative_returns


def _bar(symbol: str, day: str, close: float, open_: float | None = None) -> DailyBar:
    return DailyBar(symbol, day, close=close, open=(open_ if open_ is not None else close),
                    high=close + 1, low=close - 1, volume=10,
                    retrieved_utc="2026-08-12T12:00:00+00:00")


def _round() -> dict:
    return {"executor": "single_book", "portfolio_check": {"ok": True}, "nav_point": None,
            "decisions": [
                {"symbol": "IBM", "target_weight": 0.10, "seed": 11,
                 "prompt_variant": "pv1_baseline", "intended_start": "2026-08-10T13:30:00+00:00"},
                {"symbol": "CAT", "target_weight": 0.10, "seed": 11,
                 "prompt_variant": "pv1_baseline", "intended_start": "2026-08-10T13:30:00+00:00"},
            ]}


def _write_round(tmp_path):
    (tmp_path / "round_20260810.json").write_text(json.dumps(_round()), encoding="utf-8")


def _archive(tmp_path, *, ibm_close: float = 110.0):
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", ibm_close)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 105)]},
        out_dir=str(tmp_path), stamp="20260810", executor="single_book")


def test_backfills_every_round_from_decisions_not_round_nav_point(tmp_path):
    _write_round(tmp_path)
    _archive(tmp_path)
    result = write_lower_bound_settlement(str(tmp_path))
    cell = result["payload"]["rounds"][0]["cells"]["seed11×pv1_baseline"]
    assert result["n_rounds"] == 1
    assert result["payload"]["reading_kind"] == "lower_bound"
    assert cell["status"] == "filled"
    assert cell["entries"]["IBM"]["entry_open"] == 100.0
    assert cell["nav_series"][-1]["as_of"] == "2026-08-11"
    assert cell["nav_series"][-1]["nav"] > 100_000
    assert "nav_point" not in cell


def test_weekly_settlement_window_ends_at_next_observed_execution(tmp_path):
    _write_round(tmp_path)
    next_round = _round()
    for decision in next_round["decisions"]:
        decision["intended_start"] = "2026-08-17T13:30:00+00:00"
    (tmp_path / "round_20260817.json").write_text(json.dumps(next_round), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 101),
                 _bar("IBM", "2026-08-17", 102), _bar("IBM", "2026-08-18", 103)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 101),
                 _bar("CAT", "2026-08-17", 102), _bar("CAT", "2026-08-18", 103)]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    result = rebuild_lower_bound_settlement(str(tmp_path))["rounds"]
    first = result[0]["cells"]["seed11×pv1_baseline"]
    second = result[1]["cells"]["seed11×pv1_baseline"]
    assert first["mark_window"]["end_exclusive"] == "2026-08-17"
    assert [point["as_of"] for point in first["nav_series"]] == ["2026-08-10", "2026-08-11"]
    assert second["nav_series"][-1]["as_of"] == "2026-08-18"


def test_settlement_refuses_to_skip_a_missing_mark_inside_its_weekly_window(tmp_path):
    _write_round(tmp_path)
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 101)],
         "CAT": [_bar("CAT", "2026-08-10", 100)]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    cell = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][0]["cells"]["seed11×pv1_baseline"]
    assert cell["status"] == "pending_archived_mark_bar"
    assert cell["missing"] == ["CAT@2026-08-11"]


def test_archive_scanner_raises_hard_alert_before_compact_window_expires(tmp_path):
    _write_round(tmp_path)
    dates = [f"2026-08-{day:02d}" for day in range(10, 31)]
    dates += [f"2026-09-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-10-{day:02d}" for day in range(1, 32)]
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", day, 100) for day in dates],
         "CAT": [_bar("CAT", "2026-08-10", 100)]},
        out_dir=str(tmp_path), stamp="20261031", executor="non_round_archive_scanner")
    coverage = archive_scan_coverage(str(tmp_path))
    assert coverage["oldest_missing"]["remaining_trading_days"] <= 20
    assert coverage["hard_alerts"]


def test_only_lower_bound_enters_authoritative_nav_or_reporting_paths(tmp_path):
    round_ = _round()
    # A deliberately conflicting round-record snapshot must stay an audit
    # artifact, even once the same cell has a valid derived lower-bound series.
    round_["nav_point"] = {"as_of": "2026-08-11", "nav": 999_999.0, "nav_start": 100_000.0}
    (tmp_path / "round_20260810.json").write_text(json.dumps(round_), encoding="utf-8")
    _archive(tmp_path)
    (tmp_path / "derived_settlement").mkdir()
    (tmp_path / "derived_settlement" / "EQUIVALENCE_demo.json").write_text(json.dumps({
        "reading_kind": "equivalence_artifact", "rounds": [{"cells": {"seed99×pv2_riskaware": {
            "status": "filled", "nav_series": [{"as_of": "2026-08-11", "nav": 9_999_999}]}}}]}),
        encoding="utf-8")

    series = cell_nav_series(str(tmp_path))
    assert set(series) == {"seed11×pv1_baseline"}
    assert series["seed11×pv1_baseline"][-1]["nav"] != 999_999.0
    assert series["seed11×pv1_baseline"][-1]["reading_kind"] == "lower_bound"
    reading = cumulative_returns(str(tmp_path))["seed11×pv1_baseline"]
    assert reading["reading_kind"] == "lower_bound" and reading["bar_provenance"] is None
    assert require_reading_kind("equivalence_artifact") == "equivalence_artifact"
    assert require_reading_kind("acceptance") == "acceptance"


def test_authorized_pre_archive_round_is_rebuilt_with_whole_segment_provenance(tmp_path):
    _write_round(tmp_path)
    # The one-time ruling admits this bar because it is immutably archived, but
    # does not recast it as an 08-10 observation or claim a cross-check.
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100)], "CAT": [_bar("CAT", "2026-08-10", 100)]},
        out_dir=str(tmp_path), stamp="20260907", executor="single_book")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    cell = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][0]["cells"]["seed11×pv1_baseline"]
    assert cell["status"] == "filled"
    assert cell["bar_provenance"]["scope"] == "entire_nav_segment"
    assert cell["bar_provenance"]["not_cross_checked"] is True
    assert cell["nav_series"][0]["bar_provenance"] == cell["bar_provenance"]


def test_pre_archive_authorization_automatically_rejects_any_other_round(tmp_path):
    payload = _round()
    (tmp_path / "round_20260907.json").write_text(json.dumps(payload), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100)], "CAT": [_bar("CAT", "2026-08-10", 100)]},
        out_dir=str(tmp_path), stamp="20260907", executor="single_book")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    with pytest.raises(SettlementDataUnavailable, match="自动关闭"):
        rebuild_lower_bound_settlement(str(tmp_path))


def test_non_round_scanner_catches_up_all_persisted_rounds_and_activates_boundary(tmp_path, monkeypatch):
    _write_round(tmp_path)
    (tmp_path / "round_20260831.json").write_text(json.dumps(_round()), encoding="utf-8")
    calls = []

    class Guard:
        def check(self, n, *, purpose):
            calls.append((n, purpose))

    import qlab.llm_paper.archive_scanner as scanner
    monkeypatch.setattr(scanner, "get_daily_closes", lambda symbols, **kwargs: (
        {symbol: [_bar(symbol, "2026-08-10", 100), _bar(symbol, "2026-08-11", 101)]
         for symbol in symbols}, {}))

    result = scan_missing_archive_bars(str(tmp_path), stamp="2026-09-02", guard=Guard())
    assert result["requested_symbols"] == ["CAT", "IBM", "SPY"]
    assert calls == [(3, "marking")]
    assert result["coverage_after"]["missing_count"] == 0
    assert result["scanner_state"]


def test_non_round_scanner_refuses_monday(tmp_path):
    _write_round(tmp_path)
    with pytest.raises(SettlementDataUnavailable, match="周二至周五"):
        scan_missing_archive_bars(str(tmp_path), stamp="2026-09-07")


def test_unresolved_consumed_window_refuses_to_emit_settlement_reading(tmp_path):
    _write_round(tmp_path)
    _archive(tmp_path)
    # A second snapshot revises a bar that this settlement's NAV window uses.
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 90)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 105)]},
        out_dir=str(tmp_path), stamp="20260817", executor="single_book",
        retrieved_utc="2026-08-17T12:00:00+00:00")
    with pytest.raises(ArchiveIntegrityError, match="派生结算不得出"):
        rebuild_lower_bound_settlement(str(tmp_path))

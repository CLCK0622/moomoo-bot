"""Derived lower-bound settlement consumes immutable decisions and archived bars."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.archive_scan_state import write_scanner_state
from qlab.llm_paper.archive_scanner import archive_scan_coverage, scan_missing_archive_bars
from qlab.llm_paper.bar_archive import (ArchiveIntegrityError, archive_quote_snapshot,
                                        write_disagreement_resolution)
from qlab.llm_paper.derived_settlement import (rebuild_lower_bound_settlement,
                                                require_reading_kind,
                                                SettlementDataUnavailable,
                                                verify_settlement_artifact,
                                                verify_settlement_invocation,
                                                write_lower_bound_settlement,
                                                write_settlement_invocation)
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


def _round_on(day: str, *, seed: int = 11, variant: str = "pv1_baseline") -> dict:
    payload = _round()
    for decision in payload["decisions"]:
        decision.update({"seed": seed, "prompt_variant": variant,
                         "intended_start": f"{day}T13:30:00+00:00"})
    return payload


def _write_three_round_history(tmp_path) -> None:
    for stamp in ("20260810", "20260817", "20260824"):
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        (tmp_path / f"round_{stamp}.json").write_text(
            json.dumps(_round_on(day)), encoding="utf-8")


def _archive_three_round_history(tmp_path) -> None:
    closes = {
        "2026-08-10": 100.0,
        "2026-08-11": 101.0,
        "2026-08-17": 102.0,
        "2026-08-18": 103.0,
        "2026-08-24": 104.0,
        "2026-08-25": 105.0,
    }
    archive_quote_snapshot(
        {symbol: [_bar(symbol, day, close) for day, close in closes.items()]
         for symbol in ("IBM", "CAT")},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")


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
    assert cell["reading_kind"] == "lower_bound" and cell["is_performance_reading"] is True
    assert cell["entries"]["IBM"]["entry_open"] == 100.0
    assert cell["nav_series"][-1]["as_of"] == "2026-08-11"
    assert cell["nav_series"][-1]["nav"] > 100_000
    assert "nav_point" not in cell
    # JSON turns tuple bar keys into lists; an identical retry must still reuse
    # the content-addressed file rather than report a false collision.
    retry = write_lower_bound_settlement(str(tmp_path))
    assert retry["settlement_file"] == result["settlement_file"]
    assert len(list((tmp_path / "derived_settlement").glob("SETTLEMENT_*.json"))) == 1


def test_calculation_artifact_is_head_stable_and_invocations_are_separately_hashed(tmp_path):
    _write_round(tmp_path)
    _archive(tmp_path)
    first = write_lower_bound_settlement(str(tmp_path))
    retry = write_lower_bound_settlement(str(tmp_path))
    assert retry["settlement_file"] == first["settlement_file"]
    assert first["payload"]["schema"] == "llm_paper_derived_settlement/v2"
    assert "branch_head_commit" not in first["payload"]["source"]
    assert len(first["payload"]["calculation_identity"][
        "implementation_source_sha256"]) == 64
    assert verify_settlement_artifact(first["settlement_file"])["content_sha256"] == \
        first["content_sha256"]

    command = {"out_dir": str(tmp_path), "equivalence_round": None}
    invoked_a = write_settlement_invocation(
        str(tmp_path), settlement=first, branch_head_commit="head-a", command=command)
    invoked_b = write_settlement_invocation(
        str(tmp_path), settlement=first, branch_head_commit="head-b", command=command)
    assert invoked_a["invocation_file"] != invoked_b["invocation_file"]
    assert verify_settlement_invocation(invoked_a["invocation_file"],
                                        settlement_file=first["settlement_file"])
    assert verify_settlement_invocation(invoked_b["invocation_file"],
                                        settlement_file=first["settlement_file"])

    tampered = json.loads(Path(invoked_a["invocation_file"]).read_text(encoding="utf-8"))
    tampered["unhashed_after_the_fact"] = True
    Path(invoked_a["invocation_file"]).write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ArchiveIntegrityError, match="invocation 内容或 schema 非法"):
        verify_settlement_invocation(invoked_a["invocation_file"],
                                     settlement_file=first["settlement_file"])


def test_legacy_v1_settlement_artifact_remains_verifiable_and_immutable():
    reports = Path(__file__).resolve().parents[1] / "reports" / "llm_paper"
    legacy = reports / "derived_settlement" / "SETTLEMENT_ed655bb09567c9a9.json"
    verified = verify_settlement_artifact(legacy)
    assert verified["schema"] == "llm_paper_derived_settlement/v1"
    assert verified["source"]["branch_head_commit"] == \
        "e359bcd60a299294b5236afa9e17412b3da03f12"


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
    assert second["nav_start"] == first["nav_series"][-1]["nav"]
    assert second["entry_cost"] == pytest.approx(second["turnover_notional"] * 0.001)


def test_pending_middle_segment_blocks_every_later_segment_until_resolved(tmp_path):
    _write_three_round_history(tmp_path)
    _archive_three_round_history(tmp_path)
    disputed = archive_quote_snapshot(
        {"IBM": [DailyBar("IBM", "2026-08-18", close=103.0, open=103.0,
                          high=104.0, low=102.0, volume=11,
                          retrieved_utc="2026-09-03T12:00:00+00:00")]},
        out_dir=str(tmp_path), stamp="20260903", executor="non_round_archive_scanner",
        retrieved_utc="2026-09-03T12:00:00+00:00")

    rounds = rebuild_lower_bound_settlement(str(tmp_path))["rounds"]
    cid = "seed11×pv1_baseline"
    assert [round_["cells"][cid]["status"] for round_ in rounds] == [
        "filled", "pending_archive_integrity", "pending_prior_segment"]
    assert rounds[2]["cells"][cid]["is_performance_reading"] is False
    assert "nav_series" not in rounds[2]["cells"][cid]
    reading = cumulative_returns(str(tmp_path))[cid]
    assert reading["status"] == "pending_sequence"
    assert reading["cumulative_return"] is None

    write_disagreement_resolution(
        out_dir=str(tmp_path),
        source_archive_content_sha256=disputed["content_sha256"],
        keys=[("IBM", "2026-08-18")], selected_version="archived",
        basis="synthetic regression: retain the first immutable observation",
        ruling_reference="test-only://middle-segment-resolution",
        resolved_utc="2026-09-03T13:00:00+00:00")
    restored = rebuild_lower_bound_settlement(str(tmp_path))["rounds"]
    cells = [round_["cells"][cid] for round_ in restored]
    assert [cell["status"] for cell in cells] == ["filled", "filled", "filled"]
    assert cells[1]["nav_start"] == cells[0]["nav_series"][-1]["nav"]
    assert cells[2]["nav_start"] == cells[1]["nav_series"][-1]["nav"]


def test_cumulative_return_uses_original_sequence_start_and_preserves_cost_provenance(tmp_path):
    for stamp in ("20260810", "20260817"):
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        (tmp_path / f"round_{stamp}.json").write_text(
            json.dumps(_round_on(day)), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 110),
                 _bar("IBM", "2026-08-17", 110, 100), _bar("IBM", "2026-08-18", 120)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 105),
                 _bar("CAT", "2026-08-17", 110, 100), _bar("CAT", "2026-08-18", 120)]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")

    rounds = rebuild_lower_bound_settlement(str(tmp_path))["rounds"]
    cid = "seed11×pv1_baseline"
    first, second = (round_["cells"][cid] for round_ in rounds)
    # Independent hand calculation: first segment cash=79,980 and terminal
    # NAV=101,480; rebalance turnover=296, cost=.296, cash=81,183.704,
    # 101.48 shares of each symbol, then both close at 120.
    expected_final = 105_538.904
    assert first["nav_series"][-1]["nav"] == pytest.approx(101_480.0)
    assert second["turnover_notional"] == pytest.approx(296.0)
    assert second["entry_cost"] == pytest.approx(0.296)
    assert second["nav_series"][-1]["nav"] == pytest.approx(expected_final)
    reading = cumulative_returns(str(tmp_path))[cid]
    assert reading["status"] == "complete"
    assert reading["nav_start"] == 100_000.0
    assert reading["nav_end"] == expected_final
    assert reading["cumulative_return"] == pytest.approx(expected_final / 100_000.0 - 1.0)
    assert reading["cumulative_return"] != pytest.approx(
        expected_final / second["nav_start"] - 1.0)
    assert reading["cost"]["entry_cost_total"] == pytest.approx(20.296)
    assert [item["round"] for item in reading["bar_provenance"]["segments"]] == [
        "20260810", "20260817"]
    assert reading["bar_provenance"]["must_not_promote_to_acceptance"] is True


def test_incomplete_cell_history_never_becomes_a_cumulative_performance_reading(tmp_path):
    (tmp_path / "round_20260810.json").write_text(
        json.dumps(_round_on("2026-08-10")), encoding="utf-8")
    (tmp_path / "round_20260817.json").write_text(
        json.dumps(_round_on("2026-08-17", seed=22, variant="pv2_riskaware")),
        encoding="utf-8")
    archive_quote_snapshot(
        {symbol: [_bar(symbol, day, close) for day, close in (
            ("2026-08-10", 100), ("2026-08-11", 101),
            ("2026-08-17", 102), ("2026-08-18", 103))]
         for symbol in ("IBM", "CAT")},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")

    cid = "seed22×pv2_riskaware"
    cell = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][1]["cells"][cid]
    assert cell["status"] == "filled"
    assert cell["sequence"]["status"] == "incomplete_prehistory"
    assert cell["is_performance_reading"] is False
    assert cid not in cell_nav_series(str(tmp_path))


def test_missing_middle_decision_record_breaks_existing_cell_history(tmp_path):
    (tmp_path / "round_20260810.json").write_text(
        json.dumps(_round_on("2026-08-10")), encoding="utf-8")
    (tmp_path / "round_20260817.json").write_text(
        json.dumps(_round_on("2026-08-17", seed=22, variant="pv2_riskaware")),
        encoding="utf-8")
    (tmp_path / "round_20260824.json").write_text(
        json.dumps(_round_on("2026-08-24")), encoding="utf-8")
    _archive_three_round_history(tmp_path)

    cid = "seed11×pv1_baseline"
    rounds = rebuild_lower_bound_settlement(str(tmp_path))["rounds"]
    later = rounds[2]["cells"][cid]
    assert later["status"] == "pending_prior_segment"
    assert later["blocked_by_rounds"] == ["20260817"]
    assert later["is_performance_reading"] is False
    reading = cumulative_returns(str(tmp_path))[cid]
    assert reading["status"] == "pending_sequence"
    assert reading["cumulative_return"] is None


def test_no_rebalance_cell_cannot_emit_a_cash_flatline_until_carry_forward_exists(tmp_path):
    _write_round(tmp_path)
    stopped = _round()
    stopped["portfolio_check"] = {"ok": False}
    (tmp_path / "round_20260817.json").write_text(json.dumps(stopped), encoding="utf-8")
    _archive(tmp_path)
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    cells = rebuild_lower_bound_settlement(str(tmp_path))["rounds"]
    assert cells[0]["cells"]["seed11×pv1_baseline"]["status"] == "pending_no_rebalance_carry_forward"
    assert cells[1]["cells"]["seed11×pv1_baseline"]["status"] == "pending_no_rebalance_carry_forward"


def test_each_cell_uses_its_own_next_book_as_the_mark_window_bound(tmp_path):
    first = _round()
    first = {"executor": "multi_book", "cells": {
        "cell_a": {"decisions": first["decisions"], "portfolio_check": {"ok": True}},
        "cell_b": {"decisions": _round()["decisions"], "portfolio_check": {"ok": True}},
    }}
    second = _round()
    for decision in second["decisions"]:
        decision["intended_start"] = "2026-08-17T13:30:00+00:00"
    second = {"executor": "multi_book", "cells": {
        "cell_a": {"decisions": second["decisions"], "portfolio_check": {"ok": True}},
    }}
    (tmp_path / "round_20260810.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "round_20260817.json").write_text(json.dumps(second), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 101),
                 _bar("IBM", "2026-08-17", 102), _bar("IBM", "2026-08-18", 103)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 101),
                 _bar("CAT", "2026-08-17", 102), _bar("CAT", "2026-08-18", 103)]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    cells = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][0]["cells"]
    assert cells["cell_a"]["mark_window"]["end_exclusive"] == "2026-08-17"
    assert cells["cell_b"]["mark_window"]["end_exclusive"] is None
    assert cells["cell_b"]["nav_series"][-1]["as_of"] == "2026-08-18"


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
    cell = rebuild_lower_bound_settlement(
        str(tmp_path))["rounds"][0]["cells"]["seed11×pv1_baseline"]
    assert cell["status"] == "pending_archive_integrity"
    assert cell["reading_kind"] == "lower_bound" and cell["is_performance_reading"] is False
    assert "nav_series" not in cell and "entries" not in cell
    assert cell["integrity_check"]["status"] == "blocked_unresolved_difference"
    assert cell["integrity_check"]["n_difference_occurrences"] == 1

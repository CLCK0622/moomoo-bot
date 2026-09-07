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
                                                require_supported_settlement_runtime,
                                                SettlementDataUnavailable,
                                                SettlementIdentityMismatch,
                                                settlement_calculation_identity,
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
    assert first["payload"]["schema"] == "llm_paper_derived_settlement/v3"
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


def test_calculation_identity_uses_resolved_prereg_and_logical_paths(tmp_path, monkeypatch):
    _write_round(tmp_path)
    _archive(tmp_path)
    from_root = settlement_calculation_identity(str(tmp_path))
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    from_qlab = settlement_calculation_identity(str(tmp_path.resolve()))
    assert from_qlab == from_root
    assert from_root["input_manifest"]["preregistration"]["path"] == \
        "qlab/llm_paper_prereg.json"
    assert from_root["numeric_accumulation_semantics"] == \
        "math.fsum(sorted-logical-key)/v1"
    assert from_root["supported_runtime"] == "CPython>=3.9,<3.13"


def test_pinned_identity_mismatch_refuses_before_creating_output(tmp_path):
    _write_round(tmp_path)
    _archive(tmp_path)
    with pytest.raises(SettlementIdentityMismatch, match="input manifest mismatch"):
        write_lower_bound_settlement(
            str(tmp_path), expected_input_manifest_sha256="0" * 64)
    assert not (tmp_path / "derived_settlement").exists()


def test_supported_runtime_contract_includes_reviewed_versions_and_rejects_others():
    require_supported_settlement_runtime(implementation="cpython", version=(3, 9, 6))
    require_supported_settlement_runtime(implementation="cpython", version=(3, 12, 13))
    with pytest.raises(RuntimeError, match="supported range"):
        require_supported_settlement_runtime(implementation="cpython", version=(3, 13, 0))
    with pytest.raises(RuntimeError, match="supported range"):
        require_supported_settlement_runtime(implementation="pypy", version=(3, 10, 0))


def test_legacy_v1_settlement_artifact_remains_verifiable_and_immutable():
    reports = Path(__file__).resolve().parents[1] / "reports" / "llm_paper"
    legacy = reports / "derived_settlement" / "SETTLEMENT_ed655bb09567c9a9.json"
    verified = verify_settlement_artifact(legacy)
    assert verified["schema"] == "llm_paper_derived_settlement/v1"
    assert verified["source"]["branch_head_commit"] == \
        "e359bcd60a299294b5236afa9e17412b3da03f12"


def test_previous_v2_settlement_and_v1_invocation_remain_verifiable():
    reports = Path(__file__).resolve().parents[1] / "reports" / "llm_paper"
    settlement = reports / "derived_settlement" / "SETTLEMENT_6af59f5eeaa051f9.json"
    invocation = reports / "derived_settlement" / \
        "INVOCATION_6af59f5eeaa051f9_b44b92f662257d56.json"
    assert verify_settlement_artifact(settlement)["schema"] == \
        "llm_paper_derived_settlement/v2"
    assert verify_settlement_invocation(
        invocation, settlement_file=settlement)["schema"] == \
        "llm_paper_derived_settlement_invocation/v1"


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
    assert second["nav_start"] == pytest.approx(first["cash"] + 200.0 * 102.0)
    assert second["rebalance_provenance"]["boundary_gap"] == pytest.approx(200.0)
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
    for previous, current in zip(cells, cells[1:]):
        boundary = current["rebalance_provenance"]
        assert current["nav_start"] == pytest.approx(
            previous["cash"] + boundary["old_holdings_open_value"])
        assert boundary["boundary_gap"] == pytest.approx(
            current["nav_start"] - previous["nav_series"][-1]["nav"])


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
    # Independent hand calculation under the corrected same-open contract:
    # first cash=79,980 and terminal NAV=101,480.  At the next open the old
    # shares are worth 20,000, so wealth is 99,980 (gap=-1,500); targets are
    # 9,998 each, turnover=4, cost=.004, cash=79,983.996, and final=103,979.196.
    expected_final = 103_979.196
    assert first["nav_series"][-1]["nav"] == pytest.approx(101_480.0)
    assert second["nav_start"] == pytest.approx(99_980.0)
    assert second["rebalance_provenance"]["boundary_gap"] == pytest.approx(-1_500.0)
    assert second["turnover_notional"] == pytest.approx(4.0)
    assert second["entry_cost"] == pytest.approx(0.004)
    assert second["nav_series"][-1]["nav"] == pytest.approx(expected_final)
    reading = cumulative_returns(str(tmp_path))[cid]
    assert reading["status"] == "complete"
    assert reading["nav_start"] == 100_000.0
    assert reading["nav_end"] == expected_final
    assert reading["cumulative_return"] == pytest.approx(expected_final / 100_000.0 - 1.0)
    assert reading["cumulative_return"] != pytest.approx(
        expected_final / second["nav_start"] - 1.0)
    assert reading["cost"]["entry_cost_total"] == pytest.approx(20.004)
    assert reading["segments"][1]["return_base"] == pytest.approx(101_480.0)
    assert reading["segment_return_chain"] == pytest.approx(reading["cumulative_return"])
    assert [item["round"] for item in reading["bar_provenance"]["segments"]] == [
        "20260810", "20260817"]
    assert reading["bar_provenance"]["must_not_promote_to_acceptance"] is True


@pytest.mark.parametrize("rebalance_open,expected_gap", [
    (120.0, 2_000.0), (100.0, -2_000.0), (110.0, 0.0),
])
def test_boundary_gap_is_marked_into_open_wealth_exactly_once(
        tmp_path, rebalance_open, expected_gap):
    for stamp in ("20260810", "20260817"):
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        (tmp_path / f"round_{stamp}.json").write_text(
            json.dumps(_round_on(day)), encoding="utf-8")
    archive_quote_snapshot(
        {symbol: [_bar(symbol, "2026-08-10", 100),
                  _bar(symbol, "2026-08-11", 110),
                  _bar(symbol, "2026-08-17", rebalance_open, rebalance_open),
                  _bar(symbol, "2026-08-18", rebalance_open)]
         for symbol in ("IBM", "CAT")},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")

    cid = "seed11×pv1_baseline"
    first, second = [round_["cells"][cid] for round_ in
                     rebuild_lower_bound_settlement(str(tmp_path))["rounds"]]
    boundary = second["rebalance_provenance"]
    assert boundary["boundary_gap"] == pytest.approx(expected_gap)
    assert second["nav_start"] == pytest.approx(first["cash"] + 200.0 * rebalance_open)
    assert boundary["previous_segment_terminal"]["nav"] == pytest.approx(
        first["nav_series"][-1]["nav"])
    reading = cumulative_returns(str(tmp_path))[cid]
    assert reading["segments"][1]["return_base"] == pytest.approx(
        first["nav_series"][-1]["nav"])
    assert reading["segment_return_chain"] == pytest.approx(reading["cumulative_return"])


def test_continuous_fully_invested_holding_has_zero_turnover_and_gap_once(tmp_path):
    def full_round(day: str) -> dict:
        payload = _round_on(day)
        payload["decisions"] = [payload["decisions"][0]]
        payload["decisions"][0]["target_weight"] = 1.0
        return payload

    for stamp in ("20260810", "20260817"):
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        (tmp_path / f"round_{stamp}.json").write_text(
            json.dumps(full_round(day)), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 110),
                 _bar("IBM", "2026-08-17", 120, 120), _bar("IBM", "2026-08-18", 132)]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    cfg = json.loads((Path(__file__).resolve().parents[1] / "llm_paper_prereg.json").read_text(
        encoding="utf-8"))
    cfg["cost_per_turnover"] = 0.0
    prereg = tmp_path / "zero_cost_prereg.json"
    prereg.write_text(json.dumps(cfg), encoding="utf-8")

    cid = "seed11×pv1_baseline"
    rounds = rebuild_lower_bound_settlement(
        str(tmp_path), preregistration_path=prereg)["rounds"]
    first, second = (round_["cells"][cid] for round_ in rounds)
    assert first["nav_series"][-1]["nav"] == pytest.approx(110_000.0)
    assert second["nav_start"] == pytest.approx(120_000.0)
    assert second["rebalance_provenance"]["boundary_gap"] == pytest.approx(10_000.0)
    assert second["turnover_notional"] == pytest.approx(0.0)
    assert second["entry_cost"] == pytest.approx(0.0)
    assert second["shares"]["IBM"] == pytest.approx(first["shares"]["IBM"])
    assert second["nav_series"][-1]["nav"] == pytest.approx(132_000.0)


def test_mixed_buy_and_sell_turnover_uses_independent_expected_value(tmp_path):
    first_round = _round_on("2026-08-10")
    second_round = _round_on("2026-08-17")
    second_round["decisions"][0]["target_weight"] = 0.20
    second_round["decisions"][1]["target_weight"] = 0.02
    (tmp_path / "round_20260810.json").write_text(json.dumps(first_round), encoding="utf-8")
    (tmp_path / "round_20260817.json").write_text(json.dumps(second_round), encoding="utf-8")
    archive_quote_snapshot(
        {symbol: [_bar(symbol, day, 100) for day in (
            "2026-08-10", "2026-08-11", "2026-08-17", "2026-08-18")]
         for symbol in ("IBM", "CAT")},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    second = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][1]["cells"][
        "seed11×pv1_baseline"]
    assert second["nav_start"] == pytest.approx(99_980.0)
    assert second["turnover_notional"] == pytest.approx(17_996.4)
    assert second["entry_cost"] == pytest.approx(17.9964)


def test_symbol_entry_and_exit_are_both_charged_and_old_exit_open_is_required(tmp_path):
    first_round = _round_on("2026-08-10")
    second_round = _round_on("2026-08-17")
    second_round["decisions"][1]["symbol"] = "MRK"
    (tmp_path / "round_20260810.json").write_text(json.dumps(first_round), encoding="utf-8")
    (tmp_path / "round_20260817.json").write_text(json.dumps(second_round), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", day, 100) for day in (
             "2026-08-10", "2026-08-11", "2026-08-17", "2026-08-18")],
         "CAT": [_bar("CAT", day, 100) for day in (
             "2026-08-10", "2026-08-11", "2026-08-17")],
         "MRK": [_bar("MRK", day, 100) for day in ("2026-08-17", "2026-08-18")]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    second = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][1]["cells"][
        "seed11×pv1_baseline"]
    assert second["turnover_notional"] == pytest.approx(20_000.0)
    assert set(second["shares"]) == {"IBM", "MRK"}
    assert second["old_notionals_at_rebalance"]["CAT"] == pytest.approx(10_000.0)
    assert second["rebalance_provenance"]["old_positions_at_rebalance_open"]["CAT"] == {
        "shares": 100.0, "open": 100.0, "notional": 10_000.0}


def test_missing_exit_symbol_open_refuses_instead_of_using_previous_close(tmp_path):
    first_round = _round_on("2026-08-10")
    second_round = _round_on("2026-08-17")
    second_round["decisions"][1]["symbol"] = "MRK"
    (tmp_path / "round_20260810.json").write_text(json.dumps(first_round), encoding="utf-8")
    (tmp_path / "round_20260817.json").write_text(json.dumps(second_round), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", day, 100) for day in (
             "2026-08-10", "2026-08-11", "2026-08-17", "2026-08-18")],
         "CAT": [_bar("CAT", day, 100) for day in ("2026-08-10", "2026-08-11")],
         "MRK": [_bar("MRK", day, 100) for day in ("2026-08-17", "2026-08-18")]},
        out_dir=str(tmp_path), stamp="20260902", executor="non_round_archive_scanner")
    write_scanner_state(str(tmp_path), scan_date="2026-09-02", report_sha256="test")
    second = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][1]["cells"][
        "seed11×pv1_baseline"]
    assert second["status"] == "pending_archived_rebalance_bar"
    assert second["missing"] == ["CAT@2026-08-17"]
    assert "nav_series" not in second and "nav_start" not in second


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
    assert all(not Path(item["archive_file"]).is_absolute()
               for item in cell["integrity_check"]["unresolved_differences"])
    assert all(item["archive_file"].startswith("bar_archive/")
               for item in cell["integrity_check"]["unresolved_differences"])

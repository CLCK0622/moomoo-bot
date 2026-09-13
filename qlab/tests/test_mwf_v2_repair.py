"""Regression controls for the EVO-609 fail-closed repair."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qlab.llm_paper.mwf_v2 import (
    COST_RATE,
    EXECUTION_SCHEMA,
    EXPERIMENT_VERSION,
    GRID,
    ArtifactConflict,
    FrozenContractError,
    IdempotencyStore,
    content_sha256,
    execute_canonical_once,
    execution_key,
    ingest_planned_round,
    intended_open,
    make_typed_input,
    normalize_cell_decision,
    plan_snapshot_reuse,
    planned_round_key,
    settle_execution,
    validate_runtime_artifact,
    verify_hashed_artifact,
    verify_typed_input,
    version_isolated_statistics,
    write_hashed_artifact,
)
from qlab.llm_paper.scheduled_runner import (
    EXIT_COALESCING,
    EXIT_EXECUTION,
    EXIT_ROUND,
    EXIT_SETTLEMENT,
)


CELL_A = GRID[0]
CELL_B = GRID[1]
SCHEDULED = "2026-09-14T11:00:00Z"
ACTUAL = "2026-09-14T13:30:00Z"
ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "qlab" / "tools" / "run_llm_paper_mwf_v2.py"
OFFLINE_FIXTURE = ROOT / "qlab" / "tests" / "fixtures" / "mwf_v2_offline_delivery.json"


def _market(records, *, kind="archive_snapshot", file="archive.json",
            source="2026-09-11T20:00:00Z", available="2026-09-14T10:00:00Z"):
    return make_typed_input(
        input_kind=kind, file=file, source_time_utc=source,
        evidence_available_utc=available, records=records)


def _decision_input():
    return _market([
        {"symbol": "IBM", "trade_date": "2026-09-11", "open": 99, "close": 100},
        {"symbol": "SPY", "trade_date": "2026-09-11", "open": 499, "close": 500},
    ], file="decision_snapshot.json")


def _execution_input(*, include_actual=True):
    records = []
    if include_actual:
        records = [
            {"symbol": "IBM", "trade_date": "2026-09-14", "open": 100, "close": 101},
            {"symbol": "SPY", "trade_date": "2026-09-14", "open": 500, "close": 501},
        ]
    else:
        records = [
            {"symbol": "IBM", "trade_date": "2026-09-11", "open": 99, "close": 100},
            {"symbol": "SPY", "trade_date": "2026-09-11", "open": 499, "close": 500},
        ]
    source = "2026-09-14T20:00:00Z" if include_actual else "2026-09-11T20:00:00Z"
    available = "2026-09-14T21:00:00Z" if include_actual else "2026-09-11T21:00:00Z"
    return _market(records, file="execution_snapshot.json", source=source,
                   available=available)


def _raw(snapshot=None):
    snapshot = snapshot or _decision_input()
    return {
        "source_time_utc": snapshot["source_time_utc"],
        "evidence_available_utc": snapshot["evidence_available_utc"],
        "decision_ts": "2026-09-14T11:05:00Z",
        "effective_from": intended_open(SCHEDULED),
        "evidence_refs": [{
            "file": snapshot["file"], "input_kind": snapshot["input_kind"],
            "content_sha256": snapshot["content_sha256"],
            "source_time_utc": snapshot["source_time_utc"],
            "evidence_available_utc": snapshot["evidence_available_utc"],
        }],
        "target_weights": {"IBM": 0.10},
    }


def _plan():
    decision = normalize_cell_decision(CELL_A, _raw(), scheduled_at=SCHEDULED)
    return {
        "schema": "llm_paper_execution_plan/v2",
        "experiment_version": EXPERIMENT_VERSION,
        "scheduled_at": SCHEDULED, "actual_start_bar": ACTUAL,
        "cell_id": CELL_A, "execution_key": list(execution_key(ACTUAL, CELL_A)),
        "action": "rebalance", "decision": decision,
        "round_hashes": ["a" * 64], "canonical_round_hash": "a" * 64,
    }


def _rehash(payload):
    payload.pop("content_sha256", None)
    payload["content_sha256"] = content_sha256(payload)
    return payload


def _delivery():
    decision_snapshot = _decision_input()
    payload = {
        "schema": "llm_paper_schedule_delivery/v2",
        "experiment_version": EXPERIMENT_VERSION,
        "delivery_id": "offline-evo609-positive",
        "scheduled_at": SCHEDULED,
        "required_trade_date": "2026-09-11",
        "archive_required": ["IBM"],
        "decision_required": ["IBM"],
        "snapshot": decision_snapshot,
        "execution_snapshot": _execution_input(),
        "cells": {CELL_A: _raw(decision_snapshot)},
        "observed_market_opens": [ACTUAL],
        "previous_books": {},
        "next_actual_start": None,
        "reading_kind": "lower_bound",
        "resolution_inputs": [],
        "acceptance_equity_inputs": [],
        "acceptance_cash_inputs": [],
    }
    return _rehash(payload)


@pytest.mark.parametrize("missing", [
    "source_time_utc", "evidence_available_utc", "decision_ts", "evidence_refs",
])
def test_missing_causal_timestamp_or_evidence_never_normalizes_legal(missing):
    raw = _raw()
    raw.pop(missing)
    with pytest.raises((FrozenContractError, KeyError)):
        normalize_cell_decision(CELL_A, raw, scheduled_at=SCHEDULED)


def test_causal_order_is_strictly_before_market_open_and_schema_is_runtime_enforced(tmp_path):
    raw = _raw()
    raw["decision_ts"] = intended_open(SCHEDULED)
    with pytest.raises(FrozenContractError, match="after market open"):
        normalize_cell_decision(CELL_A, raw, scheduled_at=SCHEDULED)

    invalid_round = {
        "schema": "llm_paper_planned_round/v2",
        "experiment_version": EXPERIMENT_VERSION, "scheduled_at": SCHEDULED,
        "planned_round_key": list(planned_round_key(SCHEDULED)),
        "delivery_content_sha256": "a" * 64, "status": "persisted", "cells": {},
        "archive_snapshot_inputs": [{"file": "archive.json",
                                     "input_kind": "archive_snapshot",
                                     "content_sha256": "a" * 64}],
    }
    with pytest.raises(FrozenContractError, match="non-empty"):
        write_hashed_artifact(tmp_path / "round.json", invalid_round)
    assert not (tmp_path / "round.json").exists()


def test_execution_and_settlement_conditional_schema_controls_fail_closed(tmp_path):
    invalid_execution = {
        "schema": EXECUTION_SCHEMA, "experiment_version": EXPERIMENT_VERSION,
        "execution_key": list(execution_key(ACTUAL, CELL_A)), "cell_id": CELL_A,
        "actual_start_bar": ACTUAL, "status": "filled", "shares": {"IBM": -1},
        "cash": -1, "turnover_notional": 0, "cost_rate": COST_RATE, "entry_cost": 0,
        "opening_inputs": [{"file": "archive.json", "input_kind": "archive_snapshot",
                            "source_identity": "alpha_vantage.TIME_SERIES_DAILY.as_traded",
                            "coverage": {}, "content_sha256": "a" * 64}],
    }
    with pytest.raises(FrozenContractError, match="minimum of 0|non-negative"):
        write_hashed_artifact(tmp_path / "execution.json", invalid_execution)

    execution = execute_canonical_once(
        _plan(), previous_book=None, opening_prices={"IBM": 100},
        opening_inputs=[_execution_input()], state_dir=tmp_path)
    archive = _execution_input()
    settlement = settle_execution(
        execution=execution, next_actual_start=None, archived_bars=None,
        reading_kind="lower_bound", round_inputs=[{"file": "round.json",
                                                    "content_sha256": "a" * 64}],
        archive_inputs=[archive], resolution_inputs=[])
    settlement["is_acceptance_reading"] = True
    _rehash(settlement)
    with pytest.raises(FrozenContractError, match="should not be valid|cannot be an acceptance"):
        validate_runtime_artifact(settlement)


def test_read_after_validator_rejects_tampered_artifact(tmp_path):
    execution = execute_canonical_once(
        _plan(), previous_book=None, opening_prices={"IBM": 100},
        opening_inputs=[_execution_input()], state_dir=tmp_path)
    target = next((tmp_path / "executions").glob("*.json"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["cash"] = -5
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactConflict):
        verify_hashed_artifact(target)


def test_typed_snapshot_rejects_fake_hash_empty_bars_wrong_date_and_source_identity():
    snapshot = _decision_input()
    forged = dict(snapshot)
    forged["content_sha256"] = "0" * 64
    with pytest.raises(FrozenContractError, match="does not match"):
        verify_typed_input(forged)

    empty = dict(snapshot)
    empty["records"] = []
    empty["coverage"] = {"symbols": [], "trade_dates": []}
    _rehash(empty)
    with pytest.raises(FrozenContractError, match="non-empty|should be non-empty"):
        verify_typed_input(empty)

    with pytest.raises(FrozenContractError, match="coverage missing"):
        plan_snapshot_reuse(
            archive_required=["IBM"], decision_required=["IBM"], snapshot=snapshot,
            required_trade_date="2026-09-10")

    future = _market([
        {"symbol": "IBM", "trade_date": "2026-09-11", "open": 99, "close": 100},
        {"symbol": "IBM", "trade_date": "2026-09-12", "open": 100, "close": 101},
        {"symbol": "SPY", "trade_date": "2026-09-11", "open": 499, "close": 500},
        {"symbol": "SPY", "trade_date": "2026-09-12", "open": 500, "close": 501},
    ], source="2026-09-12T20:00:00Z", available="2026-09-12T21:00:00Z")
    with pytest.raises(FrozenContractError, match="latest trade date"):
        plan_snapshot_reuse(
            archive_required=["IBM"], decision_required=["IBM"], snapshot=future,
            required_trade_date="2026-09-11")

    wrong_source = dict(snapshot)
    wrong_source["source_identity"] = "renamed-to-OpenD"
    _rehash(wrong_source)
    with pytest.raises(FrozenContractError, match="source_identity"):
        verify_typed_input(wrong_source)


def test_complete_snapshot_never_invokes_fetch_callback(tmp_path):
    snapshot = _decision_input()
    calls = []

    def forbidden_fetch(symbols):
        calls.append(list(symbols))
        raise AssertionError("must not be called")

    result = ingest_planned_round(
        scheduled_at=SCHEDULED, delivery_payload={"delivery": "offline"},
        state_dir=tmp_path, fetch_snapshot=forbidden_fetch,
        build_cells=lambda view: {CELL_A: _raw(view["typed_inputs"][0])},
        archive_required=["IBM"], decision_required=["IBM"],
        required_trade_date="2026-09-11", reusable_snapshot=snapshot)
    assert result["status"] == "persisted"
    assert calls == []
    assert result["artifact"]["quote_batch"]["fetch_symbols"] == []


def test_decision_evidence_hash_must_bind_to_verified_snapshot(tmp_path):
    snapshot = _decision_input()
    raw = _raw(snapshot)
    raw["evidence_refs"][0]["content_sha256"] = "f" * 64
    result = ingest_planned_round(
        scheduled_at=SCHEDULED, delivery_payload={"delivery": "forged-evidence"},
        state_dir=tmp_path, fetch_snapshot=lambda symbols: pytest.fail(str(symbols)),
        build_cells=lambda _: {CELL_A: raw}, archive_required=["IBM"],
        decision_required=["IBM"], required_trade_date="2026-09-11",
        reusable_snapshot=snapshot)
    assert result["status"] == "technical_gap"
    assert "not bound to verified snapshot" in result["artifact"]["gap_reason"]


def test_source_names_and_arbitrary_bars_cannot_create_acceptance(tmp_path):
    execution = execute_canonical_once(
        _plan(), previous_book=None, opening_prices={"IBM": 100},
        opening_inputs=[_execution_input()], state_dir=tmp_path)
    bars = {("IBM", "2026-09-14"): {"close": 999},
            ("SPY", "2026-09-14"): {"close": 999}}
    with pytest.raises(FrozenContractError, match="exactly match"):
        settle_execution(
            execution=execution, next_actual_start=None, archived_bars=bars,
            reading_kind="acceptance", round_inputs=[{"file": "round.json",
                                                       "content_sha256": "a" * 64}],
            archive_inputs=[_execution_input()], resolution_inputs=[],
            equity_source="OpenD K_DAY qfq return_series",
            cash_source="BIL total_return_series",
            cash_total_return_factors={"2026-09-14": 1.0})


def test_acceptance_requires_and_consumes_verified_opend_qfq_and_bil_inputs(tmp_path):
    execution = execute_canonical_once(
        _plan(), previous_book=None, opening_prices={"IBM": 100},
        opening_inputs=[_execution_input()], state_dir=tmp_path)
    opend = _market([
        {"symbol": "IBM", "trade_date": "2026-09-14", "open": 100, "close": 101,
         "ktype": "K_DAY", "rehab_type": "qfq"},
        {"symbol": "SPY", "trade_date": "2026-09-14", "open": 500, "close": 501,
         "ktype": "K_DAY", "rehab_type": "qfq"},
    ], kind="opend_k_day_qfq", file="opend.json",
       source="2026-09-14T20:00:00Z", available="2026-09-14T21:00:00Z")
    bil = make_typed_input(
        input_kind="bil_total_return", file="bil.json",
        source_time_utc="2026-09-14T20:00:00Z",
        evidence_available_utc="2026-09-14T21:00:00Z",
        records=[{"symbol": "BIL", "trade_date": "2026-09-14",
                  "total_return_factor": 1.0001}])
    result = settle_execution(
        execution=execution, next_actual_start=None, archived_bars=None,
        reading_kind="acceptance", round_inputs=[{"file": "round.json",
                                                   "content_sha256": "a" * 64}],
        archive_inputs=[_execution_input()], resolution_inputs=[],
        acceptance_equity_inputs=[opend], acceptance_cash_inputs=[bil])
    assert result["status"] == "complete"
    assert result["is_acceptance_reading"] is True
    assert result["acceptance_equity_inputs"][0]["source_identity"] == \
        "moomoo.OpenD.K_DAY.qfq"
    assert result["acceptance_cash_inputs"][0]["source_identity"] == "BIL.total_return"


def test_orphan_claim_replay_recovers_artifact_and_preserves_conflict_rejection(tmp_path):
    snapshot = _decision_input()
    payload = {"delivery": "recover-me"}
    digest = content_sha256(payload)
    key = planned_round_key(SCHEDULED)
    target = tmp_path / "rounds" / "planned_20260914T110000Z.json"
    store = IdempotencyStore(tmp_path / "idempotency.jsonl")
    store.begin_artifact("planned_round_key", key, digest, artifact_path=target)
    calls = []

    def forbidden_fetch(symbols):
        calls.append(list(symbols))
        raise AssertionError("full reuse must not fetch")

    kwargs = dict(
        scheduled_at=SCHEDULED, state_dir=tmp_path, fetch_snapshot=forbidden_fetch,
        build_cells=lambda view: {CELL_A: _raw(view["typed_inputs"][0])},
        archive_required=["IBM"], decision_required=["IBM"],
        required_trade_date="2026-09-11", reusable_snapshot=snapshot)
    recovered = ingest_planned_round(delivery_payload=payload, **kwargs)
    assert recovered["status"] == "persisted"
    assert recovered["artifact"]["idempotency_status"] == "recovered"
    assert store.lookup("planned_round_key", key)["state"] == "complete"
    replay = ingest_planned_round(delivery_payload=payload, **kwargs)
    assert replay["status"] == "no_op" and replay["artifact"] is not None
    conflict = ingest_planned_round(delivery_payload={"delivery": "different"}, **kwargs)
    assert conflict["status"] == "IDEMPOTENCY_CONFLICT"
    assert calls == []


def test_pending_execution_claim_recovers_when_frozen_open_arrives(tmp_path):
    pending = execute_canonical_once(
        _plan(), previous_book=None, opening_prices={},
        opening_inputs=[_execution_input(include_actual=False)], state_dir=tmp_path)
    assert pending["status"] == "pending_archived_rebalance_bar"
    assert pending["idempotency_status"] == "incomplete"
    assert not list((tmp_path / "executions").glob("*.json"))

    final_input = _execution_input()
    recovered = execute_canonical_once(
        _plan(), previous_book=None, opening_prices={"IBM": 100},
        opening_inputs=[final_input], state_dir=tmp_path)
    assert recovered["status"] == "filled"
    assert recovered["idempotency_status"] == "recovered"
    assert IdempotencyStore(tmp_path / "idempotency.jsonl").lookup(
        "execution_key", tuple(_plan()["execution_key"]))["state"] == "complete"

    changed = _market([
        {"symbol": "IBM", "trade_date": "2026-09-14", "open": 101, "close": 102},
        {"symbol": "SPY", "trade_date": "2026-09-14", "open": 500, "close": 501},
    ], file="changed_execution.json", source="2026-09-14T20:00:00Z",
       available="2026-09-14T21:00:00Z")
    with pytest.raises(FrozenContractError, match="IDEMPOTENCY_CONFLICT"):
        execute_canonical_once(
            _plan(), previous_book=None, opening_prices={"IBM": 101},
            opening_inputs=[changed], state_dir=tmp_path)


def test_statistics_are_per_version_and_cell_with_missing_round_denominator():
    settlements = [
        {"experiment_version": EXPERIMENT_VERSION, "cell_id": CELL_A,
         "scheduled_at": "2026-09-14T11:00:00Z", "is_performance_reading": True,
         "nav_series": [{"as_of": "2026-09-14", "nav": 100},
                        {"as_of": "2026-09-15", "nav": 110}]},
        {"experiment_version": EXPERIMENT_VERSION, "cell_id": CELL_A,
         "scheduled_at": "2026-09-16T11:00:00Z", "is_performance_reading": False,
         "nav_series": []},
        {"experiment_version": EXPERIMENT_VERSION, "cell_id": CELL_B,
         "scheduled_at": "2026-09-14T11:00:00Z", "is_performance_reading": True,
         "nav_series": [{"as_of": "2026-09-14", "nav": 200},
                        {"as_of": "2026-09-15", "nav": 100}]},
        {"experiment_version": "llm_paper_forward_weekly_v1", "cell_id": CELL_A,
         "is_performance_reading": True,
         "nav_series": [{"as_of": "2026-09-01", "nav": 50},
                        {"as_of": "2026-09-02", "nav": 55}]},
    ]
    stats = version_isolated_statistics(settlements)
    current = stats["versions"][EXPERIMENT_VERSION]
    assert current["total_return"] is None
    assert current["cells"][CELL_A]["total_return"] == pytest.approx(0.10)
    assert current["cells"][CELL_B]["total_return"] == pytest.approx(-0.50)
    assert current["cells"][CELL_A]["planned_rounds"] == 2
    assert current["cells"][CELL_A]["n_gaps"] == 1
    assert stats["versions"]["llm_paper_forward_weekly_v1"]["cells"][CELL_A][
        "total_return"] == pytest.approx(0.10)


def test_statistics_reject_discontinuous_v2_round_sequence():
    settlements = [
        {"experiment_version": EXPERIMENT_VERSION, "cell_id": CELL_A,
         "scheduled_at": "2026-09-14T11:00:00Z", "is_performance_reading": False},
        {"experiment_version": EXPERIMENT_VERSION, "cell_id": CELL_A,
         "scheduled_at": "2026-09-18T11:00:00Z", "is_performance_reading": False},
    ]
    with pytest.raises(FrozenContractError, match="discontinuous"):
        version_isolated_statistics(settlements)


def _run_cli(tmp_path, delivery):
    delivery_path = tmp_path / "delivery.json"
    delivery_path.write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    state = tmp_path / "state"
    completed = subprocess.run(
        [sys.executable, str(CLI), "--delivery", str(delivery_path),
         "--state-dir", str(state)], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed, state


def test_fixed_cli_runs_offline_end_to_end_and_is_idempotent(tmp_path):
    delivery = json.loads(OFFLINE_FIXTURE.read_text(encoding="utf-8"))
    assert validate_runtime_artifact(delivery)["content_sha256"] == _delivery()[
        "content_sha256"]
    first, state = _run_cli(tmp_path, delivery)
    assert first.returncode == 0, first.stderr + first.stdout
    result = json.loads(first.stdout)
    assert result["status"] == "complete" and result["remote_fetches"] == 0
    assert result["published_cutoff_advanced"] is False
    assert len(result["stages"]["executions"]) == 1
    assert len(result["stages"]["settlements"]) == 1
    second = subprocess.run(
        [sys.executable, str(CLI), "--delivery", str(tmp_path / "delivery.json"),
         "--state-dir", str(state)], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert second.returncode == 0, second.stderr + second.stdout
    assert json.loads(second.stdout)["content_sha256"] == result["content_sha256"]


def test_fixed_cli_resumes_same_round_after_execution_input_becomes_available(tmp_path):
    delivery = _delivery()
    delivery["execution_snapshot"] = _execution_input(include_actual=False)
    _rehash(delivery)
    first, state = _run_cli(tmp_path, delivery)
    assert first.returncode == EXIT_EXECUTION
    assert not list((state / "executions").glob("*.json"))

    delivery["execution_snapshot"] = _execution_input(include_actual=True)
    _rehash(delivery)
    (tmp_path / "delivery.json").write_text(
        json.dumps(delivery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    resumed = subprocess.run(
        [sys.executable, str(CLI), "--delivery", str(tmp_path / "delivery.json"),
         "--state-dir", str(state)], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert resumed.returncode == 0, resumed.stderr + resumed.stdout
    result = json.loads(resumed.stdout)
    assert result["status"] == "complete" and result["remote_fetches"] == 0


@pytest.mark.parametrize("stage,exit_code", [
    ("round", EXIT_ROUND),
    ("coalescing", EXIT_COALESCING),
    ("execution", EXIT_EXECUTION),
    ("settlement", EXIT_SETTLEMENT),
])
def test_fixed_cli_stage_failures_are_closed_and_never_publish_success(tmp_path, stage, exit_code):
    delivery = copy.deepcopy(_delivery())
    if stage == "round":
        delivery["cells"][CELL_A].pop("source_time_utc")
    elif stage == "coalescing":
        delivery["observed_market_opens"] = ["2026-09-11T13:30:00Z"]
    elif stage == "execution":
        delivery["execution_snapshot"] = _execution_input(include_actual=False)
    elif stage == "settlement":
        delivery["reading_kind"] = "acceptance"
    _rehash(delivery)
    completed, state = _run_cli(tmp_path, delivery)
    assert completed.returncode == exit_code, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "failed_closed" and result["stage"] == stage
    assert not list((state / "pipeline").glob("result_*.json"))
    failure = json.loads(next((state / "failures").glob(f"*_{stage}.json")).read_text())
    assert failure["published_cutoff_advanced"] is False
    assert failure["success_manifest_written"] is False

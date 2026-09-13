"""Frozen acceptance matrix for ``llm_paper_forward_mwf_v2``."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from qlab.llm_paper.mwf_v2 import (
    ACCEPTANCE_CASH_SOURCE,
    ACCEPTANCE_EQUITY_SOURCE,
    EXPERIMENT_VERSION,
    GRID,
    IdempotencyConflict,
    IdempotencyStore,
    BatchQuotaExceeded,
    FrozenContractError,
    advance_published_cutoff,
    coalesce_rounds,
    content_sha256,
    decision_key,
    execute_canonical,
    execute_canonical_once,
    execution_key,
    historical_decision_backfill_policy,
    ingest_planned_round,
    intended_open,
    load_v2_preregistration,
    make_typed_input,
    normalize_cell_decision,
    plan_snapshot_reuse,
    planned_round_key,
    quota_preflight,
    read_round_compat,
    resolve_actual_start,
    settle_execution,
    settle_execution_once,
    settlement_key,
    trial_registration_metadata,
    validate_schedule_slot,
    version_isolated_statistics,
)

UTC = timezone.utc
CELL = GRID[0]
H64 = "a" * 64


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def _raw(scheduled: str, weights: dict[str, float] | None = None, *,
         decision_offset_minutes: int = 5, evidence_input: dict | None = None) -> dict:
    slot = _parse(scheduled)
    decision = slot + timedelta(minutes=decision_offset_minutes)
    source = (slot - timedelta(hours=2)).isoformat()
    available = (slot - timedelta(hours=1)).isoformat()
    ref = {
        "file": (evidence_input or {}).get("file", "archive.json"),
        "input_kind": (evidence_input or {}).get("input_kind", "archive_snapshot"),
        "content_sha256": (evidence_input or {}).get("content_sha256", H64),
        "source_time_utc": (evidence_input or {}).get("source_time_utc", source),
        "evidence_available_utc": (evidence_input or {}).get(
            "evidence_available_utc", available),
    }
    return {
        "evidence_available_utc": available,
        "decision_ts": decision.isoformat(),
        "effective_from": intended_open(scheduled),
        "source_time_utc": source,
        "evidence_refs": [ref],
        "target_weights": weights if weights is not None else {"IBM": 0.10},
    }


def _round(scheduled: str, *, cell: str = CELL,
           weights: dict[str, float] | None = None) -> dict:
    decision = normalize_cell_decision(cell, _raw(scheduled, weights),
                                       scheduled_at=scheduled)
    payload = {
        "schema": "llm_paper_planned_round/v2",
        "experiment_version": EXPERIMENT_VERSION,
        "scheduled_at": scheduled,
        "planned_round_key": list(planned_round_key(scheduled)),
        "delivery_content_sha256": content_sha256({"scheduled_at": scheduled}),
        "status": "persisted",
        "cells": {cell: decision},
        "archive_snapshot_inputs": [dict(decision["evidence_refs"][0])],
    }
    payload["content_sha256"] = content_sha256(payload)
    return payload


def _plan(*, actual: str = "2026-09-14T13:30:00Z",
          weights: dict[str, float] | None = None, action: str = "rebalance") -> dict:
    scheduled = "2026-09-14T11:00:00Z"
    decision = normalize_cell_decision(CELL, _raw(scheduled, weights),
                                       scheduled_at=scheduled)
    return {"experiment_version": EXPERIMENT_VERSION, "scheduled_at": scheduled,
            "actual_start_bar": actual, "cell_id": CELL,
            "execution_key": list(execution_key(actual, CELL)), "action": action,
            "decision": decision, "round_hashes": [H64],
            "canonical_round_hash": H64}


def _inputs(prefix: str) -> list[dict[str, str]]:
    return [{"file": f"{prefix}.json", "content_sha256": H64}]


def _typed_bars(bars: dict, *, kind: str = "archive_snapshot", file: str = "archive.json",
                source_time: str | None = None, available: str | None = None) -> dict:
    records = []
    for (symbol, day), value in sorted(bars.items()):
        block = dict(value) if isinstance(value, dict) else {"close": value}
        record = {"symbol": symbol, "trade_date": day,
                  "open": block.get("open", block.get("close")),
                  "close": block.get("close", block.get("open"))}
        if kind == "opend_k_day_qfq":
            record.update({"ktype": "K_DAY", "rehab_type": "qfq"})
        records.append(record)
    latest = max(record["trade_date"] for record in records)
    source_time = source_time or f"{latest}T20:00:00Z"
    available = available or f"{latest}T21:00:00Z"
    return make_typed_input(
        input_kind=kind, file=file, source_time_utc=source_time,
        evidence_available_utc=available, records=records)


def _bil(days: list[str]) -> dict:
    latest = max(days)
    return make_typed_input(
        input_kind="bil_total_return", file="bil_total_return.json",
        source_time_utc=f"{latest}T20:00:00Z",
        evidence_available_utc=f"{latest}T21:00:00Z",
        records=[{"symbol": "BIL", "trade_date": day,
                  "total_return_factor": 1.0} for day in days])


def _resolution(symbol: str, day: str, status: str = "unresolved") -> dict:
    return make_typed_input(
        input_kind="resolution", file="RESOLUTION.json",
        source_time_utc="2026-09-14T09:00:00Z",
        evidence_available_utc="2026-09-14T10:00:00Z",
        records=[{"symbol": symbol, "trade_date": day, "status": status,
                  "authoritative_source": "reviewed dispute ledger"}])


def test_normal_mwf_slots_and_first_three_utc_resolve_to_one_segment_each():
    first_three = ["2026-09-14T11:00:00Z", "2026-09-16T11:00:00Z",
                   "2026-09-18T11:00:00Z"]
    opens = [value.replace("11:00:00", "13:30:00") for value in first_three]
    for scheduled, actual in zip(first_three, opens):
        slot = validate_schedule_slot(scheduled)
        resolved = resolve_actual_start(scheduled, [actual])
        assert slot["scheduled_at_et"].endswith("-04:00")
        assert resolved == {"status": "resolved", "intended_start": actual,
                            "actual_start": actual, "rolled": False, "rolled_days": 0}


def test_v2_prereg_is_additive_and_proves_inherited_v1_hash():
    prereg = load_v2_preregistration()
    assert prereg["experiment_version"] == EXPERIMENT_VERSION
    assert prereg["inherited_freeze"]["rewrite_allowed"] is False
    assert prereg["executor"] == {
        "name": "single_book", "mode": "SIMULATE", "switch_authorized": False,
        "overlap_equivalence_sha_only":
            "8dcea3bf4783466523b2c7ee262f6d4ae0e91431",
    }


def test_monday_holiday_rolls_to_tuesday_without_becoming_a_gap():
    scheduled = "2027-01-18T12:00:00Z"  # MLK Day, 07:00 EST
    result = resolve_actual_start(scheduled, ["2027-01-19T14:30:00Z"])
    assert result["actual_start"] == "2027-01-19T14:30:00Z"
    assert result["rolled"] is True and result["rolled_days"] == 1
    assert "gap" not in result["status"]


def test_two_rounds_same_bar_choose_later_and_coalesce_earlier():
    friday = _round("2026-12-25T12:00:00Z")
    monday = _round("2026-12-28T12:00:00Z", weights={"IBM": 0.08})
    result = coalesce_rounds(
        [friday, monday], observed_market_opens=["2026-12-28T14:30:00Z"])
    assert len(result["executions"]) == 1
    execution = result["executions"][0]
    assert execution["scheduled_at"] == monday["scheduled_at"]
    assert execution["decision"]["target_weights"] == {"IBM": 0.08}
    earlier = next(item for item in result["decision_statuses"]
                   if item["status"] == "coalesced_before_entry")
    assert earlier["entry_cost"] == 0 and earlier["has_book"] is False


def test_later_failed_round_does_not_suppress_earlier_legal_round():
    friday = _round("2026-12-25T12:00:00Z")
    failed = {"schema": "llm_paper_planned_round/v2",
              "experiment_version": EXPERIMENT_VERSION,
              "scheduled_at": "2026-12-28T12:00:00Z",
              "planned_round_key": list(planned_round_key("2026-12-28T12:00:00Z")),
              "delivery_content_sha256": H64, "status": "technical_gap",
              "gap_reason": "fixture", "cells": {}}
    failed["content_sha256"] = content_sha256(failed)
    result = coalesce_rounds(
        [friday, failed], observed_market_opens=["2026-12-28T14:30:00Z"])
    assert result["executions"][0]["scheduled_at"] == friday["scheduled_at"]
    assert any(item["status"] == "technical_gap" for item in result["decision_statuses"])


def test_identical_platform_redelivery_is_noop_before_fetch_fee_or_ledger(tmp_path):
    calls = []
    scheduled = "2026-09-14T11:00:00Z"

    def fetch(symbols):
        calls.append(list(symbols))
        return _typed_bars(
            {(symbol, "2026-09-11"): {"open": 100, "close": 101}
             for symbol in symbols})

    kwargs = dict(
        scheduled_at=scheduled, delivery_payload={"delivery": "same"}, state_dir=tmp_path,
        fetch_snapshot=fetch,
        build_cells=lambda snapshot: {
            CELL: _raw(scheduled, evidence_input=snapshot["typed_inputs"][0])},
        archive_required=["IBM"], decision_required=["IBM"],
        required_trade_date="2026-09-11")
    first = ingest_planned_round(**kwargs)
    second = ingest_planned_round(**kwargs)
    assert first["status"] == "persisted" and second["status"] == "no_op"
    assert len(calls) == 1
    assert second["no_fetch"] and second["no_fee"] and second["no_cost"]
    assert second["no_ledger_write"]


def test_same_planned_key_different_hash_refuses_whole_round_without_refetch(tmp_path):
    calls = []
    scheduled = "2026-09-14T11:00:00Z"

    def fetch(symbols):
        calls.append(list(symbols))
        return _typed_bars(
            {(symbol, "2026-09-11"): {"open": 100, "close": 101}
             for symbol in symbols})

    base = dict(scheduled_at=scheduled, state_dir=tmp_path, fetch_snapshot=fetch,
                build_cells=lambda snapshot: {
                    CELL: _raw(scheduled, evidence_input=snapshot["typed_inputs"][0])},
                archive_required=["IBM"], decision_required=["IBM"],
                required_trade_date="2026-09-11")
    assert ingest_planned_round(delivery_payload={"revision": 1}, **base)["status"] == "persisted"
    conflict = ingest_planned_round(delivery_payload={"revision": 2}, **base)
    assert conflict["status"] == "IDEMPOTENCY_CONFLICT"
    assert conflict["whole_round_refused"] is True and len(calls) == 1


def test_atomic_decision_claim_batch_rejects_conflict_without_partial_append(tmp_path):
    store = IdempotencyStore(tmp_path / "ids.jsonl")
    key_a = decision_key("2026-09-14T11:00:00Z", GRID[0])
    key_b = decision_key("2026-09-14T11:00:00Z", GRID[1])
    store.claim("decision_key", key_b, {"revision": 1})
    before = (tmp_path / "ids.jsonl").read_text(encoding="utf-8")
    with pytest.raises(IdempotencyConflict, match="IDEMPOTENCY_CONFLICT"):
        store.claim_many([("decision_key", key_a, {"revision": 1}),
                          ("decision_key", key_b, {"revision": 2})])
    assert (tmp_path / "ids.jsonl").read_text(encoding="utf-8") == before
    assert store.lookup("decision_key", key_a) is None


def test_missing_any_old_holding_open_is_pending_and_never_uses_close():
    previous = {"experiment_version": EXPERIMENT_VERSION, "shares": {"IBM": 10, "CAT": 5},
                "cash": 50_000}
    result = execute_canonical(_plan(), previous_book=previous,
                               opening_prices={"IBM": {"open": 101, "close": 999}})
    assert result["status"] == "pending_archived_rebalance_bar"
    assert result["missing"] == ["CAT@2026-09-14"]
    assert result["entry_cost"] == 0


def test_unresolved_spy_blocks_only_benchmark_alpha_and_acceptance_consumers():
    execution = execute_canonical(
        _plan(), previous_book=None, opening_prices={"IBM": 100})
    bars = {("IBM", "2026-09-14"): {"close": 101},
            ("SPY", "2026-09-14"): {"close": 500}}
    archive = _typed_bars(bars)
    resolution = _resolution("SPY", "2026-09-14")
    lower = settle_execution(
        execution=execution, next_actual_start=None, archived_bars=bars,
        reading_kind="lower_bound", round_inputs=_inputs("round"),
        archive_inputs=[archive], resolution_inputs=[resolution],
        unresolved_keys={("SPY", "2026-09-14")})
    assert lower["returns_through"] == "2026-09-14"
    assert lower["is_performance_reading"] is True
    assert lower["is_acceptance_reading"] is False
    assert lower["benchmark_returns_through"] is None
    assert {item["consumer"] for item in lower["rejected_keys"]} == {"benchmark_alpha"}

    opend = _typed_bars(bars, kind="opend_k_day_qfq", file="opend.json")
    acceptance = settle_execution(
        execution=execution, next_actual_start=None, archived_bars=bars,
        reading_kind="acceptance", round_inputs=_inputs("round"),
        archive_inputs=[archive], resolution_inputs=[resolution],
        unresolved_keys={("SPY", "2026-09-14")},
        acceptance_equity_inputs=[opend],
        acceptance_cash_inputs=[_bil(["2026-09-14"])])
    assert acceptance["is_acceptance_reading"] is False
    assert any(item["consumer"] == "acceptance" for item in acceptance["rejected_keys"])


def test_dst_changes_utc_hour_without_changing_0700_new_york_slot():
    summer = validate_schedule_slot("2026-10-30T11:00:00Z")
    winter = validate_schedule_slot("2026-11-02T12:00:00Z")
    assert "T07:00:00-04:00" in summer["scheduled_at_et"]
    assert "T07:00:00-05:00" in winter["scheduled_at_et"]
    with pytest.raises(FrozenContractError, match="07:00"):
        validate_schedule_slot("2026-11-02T11:00:00Z")


def test_late_per_cell_decision_is_rejected_and_cannot_fake_scheduled_time():
    scheduled = "2026-09-14T11:00:00Z"
    with pytest.raises(FrozenContractError, match="after market open"):
        normalize_cell_decision(CELL, _raw(scheduled, decision_offset_minutes=151),
                                scheduled_at=scheduled)


def test_latest_legal_portfolio_violation_carries_forward_at_zero_cost():
    friday = _round("2026-12-25T12:00:00Z", weights={"IBM": 0.10})
    monday = _round("2026-12-28T12:00:00Z", weights={"IBM": 0.20})
    coalesced = coalesce_rounds(
        [friday, monday], observed_market_opens=["2026-12-28T14:30:00Z"])
    plan = coalesced["executions"][0]
    assert plan["action"] == "carry_forward" and plan["scheduled_at"] == monday["scheduled_at"]
    old = {"experiment_version": EXPERIMENT_VERSION, "shares": {"IBM": 100}, "cash": 90_000}
    result = execute_canonical(plan, previous_book=old, opening_prices={"IBM": 100})
    assert result["status"] == "carried_forward_portfolio_violation"
    assert result["shares"] == old["shares"] and result["cash"] == old["cash"]
    assert result["turnover_notional"] == result["entry_cost"] == 0


def test_turnover_is_absolute_union_once_and_execution_redelivery_costs_once(tmp_path):
    plan = _plan(weights={"IBM": 0.10, "CAT": 0.10})
    previous = {"experiment_version": EXPERIMENT_VERSION,
                "shares": {"IBM": 100.0}, "cash": 90_000.0}
    opens = {"IBM": 100.0, "CAT": 200.0}
    opening_input = _typed_bars({
        ("IBM", "2026-09-14"): {"open": 100.0, "close": 100.0},
        ("CAT", "2026-09-14"): {"open": 200.0, "close": 200.0},
    })
    first = execute_canonical_once(plan, previous_book=previous,
                                   opening_prices=opens, opening_inputs=[opening_input],
                                   state_dir=tmp_path)
    second = execute_canonical_once(plan, previous_book=previous,
                                    opening_prices=opens, opening_inputs=[opening_input],
                                    state_dir=tmp_path)
    # boundary wealth = 100k; old IBM=10k, new IBM=10k and CAT=10k => turnover=10k, not 20k
    assert first["turnover_notional"] == pytest.approx(10_000.0)
    assert first["entry_cost"] == pytest.approx(10.0)
    assert first["cost_charged_once"] is True
    assert second["idempotency_status"] == "no_op" and second["entry_cost"] == first["entry_cost"]
    assert len(list((tmp_path / "executions").glob("*.json"))) == 1


def test_first_v2_entry_normalizes_statistics_before_cost_but_keeps_continuity_wealth():
    previous = {"experiment_version": "llm_paper_forward_weekly_v1",
                "shares": {"IBM": 100.0}, "cash": 100_000.0}
    result = execute_canonical(_plan(weights={"IBM": 0.10}),
                               previous_book=previous, opening_prices={"IBM": 100.0})
    assert result["operational_continuity"]["wealth_at_boundary"] == 110_000.0
    assert result["statistics_normalization"]["normalized_to"] == 100_000.0
    assert result["statistics_normalization"]["entry_cost_included"] is True
    assert result["entry_cost"] > 0 and result["statistics_normalization"]["normalized_entry_cost"] > 0


def test_half_open_settlement_excludes_next_canonical_open_date_and_is_idempotent(tmp_path):
    execution = execute_canonical(
        _plan(), previous_book=None, opening_prices={"IBM": 100})
    bars = {("IBM", "2026-09-14"): {"close": 101},
            ("IBM", "2026-09-15"): {"close": 102},
            ("IBM", "2026-09-16"): {"close": 999},
            ("SPY", "2026-09-14"): {"close": 500},
            ("SPY", "2026-09-15"): {"close": 501},
            ("SPY", "2026-09-16"): {"close": 502}}
    kwargs = dict(execution=execution, next_actual_start="2026-09-16T13:30:00Z",
                  archived_bars=bars, reading_kind="lower_bound",
                  round_inputs=_inputs("round"), archive_inputs=[_typed_bars(bars)],
                  resolution_inputs=[])
    first = settle_execution_once(state_dir=tmp_path, **kwargs)
    second = settle_execution_once(state_dir=tmp_path, **kwargs)
    assert [point["as_of"] for point in first["nav_series"]] == ["2026-09-14", "2026-09-15"]
    assert first["window"]["next_start_open_exclusive"] == "2026-09-16T13:30:00Z"
    assert second["idempotency_status"] == "no_op"


def test_weekly_and_mwf_statistics_are_never_combined():
    base = {"is_performance_reading": True,
            "nav_series": [{"as_of": "2026-09-01", "nav": 100},
                           {"as_of": "2026-09-02", "nav": 101}]}
    weekly = {**base, "experiment_version": "llm_paper_forward_weekly_v1"}
    mwf = {**base, "experiment_version": EXPERIMENT_VERSION,
           "cell_id": CELL, "scheduled_at": "2026-09-14T11:00:00Z",
           "nav_series": [{"as_of": "2026-09-14", "nav": 100},
                          {"as_of": "2026-09-15", "nav": 99}]}
    stats = version_isolated_statistics([weekly, mwf], gaps=[
        {"experiment_version": EXPERIMENT_VERSION, "cell_id": CELL,
         "scheduled_at": "2026-09-16T11:00:00Z", "status": "technical_gap"}])
    assert stats["combined_metrics"] is None
    assert set(stats["versions"]) == {"llm_paper_forward_weekly_v1", EXPERIMENT_VERSION}
    assert stats["versions"][EXPERIMENT_VERSION]["total_return"] is None
    assert stats["versions"][EXPERIMENT_VERSION]["cells"][CELL]["total_return"] == pytest.approx(-0.01)
    assert stats["versions"][EXPERIMENT_VERSION]["n_gaps"] == 1


def test_full_batch_quota_preflight_refuses_over_25_without_dropping_or_splitting():
    with pytest.raises(BatchQuotaExceeded, match="whole batch refused"):
        quota_preflight(archive_required=[f"A{i}" for i in range(13)],
                        decision_required=[f"D{i}" for i in range(13)], other_calls=0)
    ok = quota_preflight(archive_required=[f"A{i}" for i in range(12)],
                         decision_required=[f"D{i}" for i in range(12)], other_calls=0)
    assert ok["total_calls"] == 25 and ok["require_full_batch"] is True
    assert ok["outputsize"] == "compact"


def test_wed_fri_snapshot_reuse_requires_capture_trade_date_and_archive_hash():
    snapshot = _typed_bars({
        ("IBM", "2026-09-15"): {"open": 100, "close": 101},
        ("SPY", "2026-09-15"): {"open": 500, "close": 501},
    }, source_time="2026-09-15T20:00:00Z", available="2026-09-16T02:01:00Z")
    plan = plan_snapshot_reuse(archive_required=["IBM", "CAT"],
                               decision_required=["IBM", "SPY"], snapshot=snapshot,
                               required_trade_date="2026-09-15")
    assert plan["reused_symbols"] == ["IBM", "SPY"]
    assert plan["fetch_symbols"] == ["CAT"]
    assert plan["snapshot_provenance"]["archive_content_sha256"] == snapshot["content_sha256"]
    with pytest.raises(FrozenContractError, match="coverage missing"):
        plan_snapshot_reuse(archive_required=["IBM"], decision_required=["IBM"],
                            snapshot=snapshot, required_trade_date="2026-09-14")


def test_20260907_gap_policy_forbids_backfill():
    policy = historical_decision_backfill_policy("2026-09-07T11:00:00Z")
    assert policy["backfill_allowed"] is False
    assert policy["scheduled_at"] == "2026-09-07T11:00:00Z"


@pytest.mark.parametrize("oauth_ok,push_ok,failures", [
    (False, True, ["oauth"]), (True, False, ["push"]), (False, False, ["oauth", "push"]),
])
def test_oauth_or_push_failure_never_advances_official_cutoff(oauth_ok, push_ok, failures):
    result = advance_published_cutoff(current="2026-09-03", candidate="2026-09-09",
                                      oauth_ok=oauth_ok, push_ok=push_ok)
    assert result["status"] == "not_advanced" and result["cutoff"] == "2026-09-03"
    assert result["failures"] == failures and result["manual_retry_allowed"] is False


def test_acceptance_rejects_av_equity_or_zero_yield_cash_substitution():
    execution = execute_canonical(_plan(), previous_book=None, opening_prices={"IBM": 100})
    bars = {("IBM", "2026-09-14"): {"close": 101},
            ("SPY", "2026-09-14"): {"close": 500}}
    with pytest.raises(FrozenContractError, match="exactly match"):
        settle_execution(
            execution=execution, next_actual_start=None, archived_bars=bars,
            reading_kind="acceptance", round_inputs=_inputs("round"),
            archive_inputs=[_typed_bars(bars)], resolution_inputs=[],
            equity_source="Alpha Vantage as-traded", cash_source="literal zero-yield cash")


def test_four_idempotency_keys_match_frozen_tuple_shapes():
    scheduled = "2026-09-14T11:00:00Z"
    actual = "2026-09-14T13:30:00Z"
    planned = planned_round_key(scheduled)
    decision = decision_key(scheduled, CELL)
    execution = execution_key(actual, CELL)
    settlement = settlement_key(execution=execution, mark_date="2026-09-14",
                                reading_kind="lower_bound",
                                round_hashes=["b" * 64, "a" * 64],
                                archive_hashes=["d" * 64, "c" * 64],
                                resolution_hashes=["e" * 64])
    assert planned == (EXPERIMENT_VERSION, scheduled)
    assert decision == (planned, CELL)
    assert execution == (EXPERIMENT_VERSION, actual, CELL)
    assert settlement[:3] == (execution, "2026-09-14", "lower_bound")
    assert settlement[3:6] == (("a" * 64, "b" * 64),
                                ("c" * 64, "d" * 64), ("e" * 64,))


def test_trial_family_stays_ten_and_project_cumulative_n_does_not_reset_or_add_ten():
    rounds = [_round("2026-09-14T11:00:00Z"),
              _round("2026-09-16T11:00:00Z", cell=GRID[1])]
    result = trial_registration_metadata(immutable_rounds=rounds,
                                         project_cumulative_n_before=47)
    assert result["n_trials_total"] == 10 and result["n_evaluated"] == 2
    assert result["project_cumulative_n_after"] == 47
    assert result["frequency_change_added_trials"] == 0


def test_trial_ledger_persists_version_and_loads_legacy_rows_without_rewrite(tmp_path):
    from research.gate.trial_ledger import TrialLedger

    path = tmp_path / "trials.jsonl"
    legacy = ({"run_id": "legacy", "source": "manual", "n_trials_total": 47,
               "n_evaluated": 47, "candidate_id": "history", "note": "", "ts": "old"})
    original = json.dumps(legacy, ensure_ascii=False) + "\n"
    path.write_text(original, encoding="utf-8")
    loaded = TrialLedger(str(path))
    assert loaded.runs[0].experiment_version is None
    assert path.read_text(encoding="utf-8") == original
    rec = loaded.register_run(run_id="mwf", source="llm_agent", n_trials_total=10,
                              n_evaluated=2, candidate_id="llm_paper",
                              experiment_version=EXPERIMENT_VERSION, now_iso="new")
    assert rec.experiment_version == EXPERIMENT_VERSION


def test_legacy_round_is_read_compatible_in_memory_and_file_is_byte_unchanged(tmp_path):
    path = tmp_path / "round_20260810.json"
    original = b'{"round_decision_ts":"2026-08-07T15:00:00Z","cells":{}}\n'
    path.write_bytes(original)
    result = read_round_compat(path)
    assert result["experiment_version"] == "llm_paper_forward_weekly_v1"
    assert result["scheduled_at"] is None
    assert path.read_bytes() == original


def test_settlement_provenance_lists_files_and_hashes_and_separates_cutoffs():
    execution = execute_canonical(_plan(), previous_book=None, opening_prices={"IBM": 100})
    bars = {("IBM", "2026-09-14"): {"close": 101},
            ("SPY", "2026-09-14"): {"close": 500},
            ("SPY", "2026-09-15"): {"close": 501}}
    result = settle_execution(
        execution=execution, next_actual_start=None, archived_bars=bars,
        reading_kind="lower_bound", round_inputs=_inputs("round"),
        archive_inputs=[_typed_bars(bars)], resolution_inputs=[])
    assert result["returns_through"] == "2026-09-14"
    assert result["data_available_through"] == "2026-09-15"
    assert result["round_inputs"] == _inputs("round")
    assert result["archive_inputs"][0]["input_kind"] == "archive_snapshot"
    assert result["resolution_inputs"] == []
    assert len(result["content_sha256"]) == 64

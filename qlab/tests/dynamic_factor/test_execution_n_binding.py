"""C12/A22-A24. Private sources are counterfactual, not real installation."""

from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor.authority_ledger import FIELDS, records, state
from qlab.dynamic_factor.authority_record_types import _issue_coverage, _HOST_TOKEN
from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.execution_receipts.n_binding import (
    bind_execution_n,
    design_archive_reference,
    execution_configurations,
    stage_budget_mapping,
    STAGES,
)
import authority_host_helpers
from authority_stage1_helpers import archive
from qlab.dynamic_factor.execution_receipts import n_binding


def mapping(stage="independent_reference"):
    return stage_budget_mapping(
        stage=stage, producer_id="PRIVATE-PRODUCER", run_id="PRIVATE-RUN"
    )


def private_bound_source(tmp_path, monkeypatch, *, complete=False):
    """Preserve unknowns/contributions, attach synthetic configuration evidence.

    Reissued private coverage is only the host-source assumption. The real
    production deployment source is still unavailable, and no writer is called.
    """
    configurations = list(execution_configurations().items())

    def with_configurations():
        raw, _, _ = archive()
        rows = records(raw)
        for index, row in enumerate(
            r for r in rows if r.get("run_id") == "PRIVATE-HOST-FIXTURE"
        ):
            row["evidence"] = [
                {"sha256": configurations[index % len(configurations)][1]}
            ]
        for index, row in enumerate(rows[1:], 1):
            row["previous_hash"] = digest(rows[index - 1])
        raw = b"".join(canonical(row) + b"\n" for row in rows)
        coverage = _issue_coverage(
            raw, "PRIVATE-C12-CONFIGURATION-FIXTURE", _HOST_TOKEN
        )
        current = state(rows, trusted_coverage=coverage)
        witness = {key: current[key] for key in FIELDS}
        witness.update(
            ledger_file="EVO891-B-ledger-v2.jsonl", ledger_file_sha256=sha256(raw)
        )
        return raw, witness, coverage

    monkeypatch.setattr(authority_host_helpers, "archive", with_configurations)
    context, snapshot, pin, source = authority_host_helpers.private_host(
        tmp_path, monkeypatch, complete=complete
    )
    traces = []
    for index, row in enumerate(
        r
        for r in records(source["chain_raw"])
        if r.get("run_id") == "PRIVATE-HOST-FIXTURE"
    ):
        (member, fold), config = configurations[index % len(configurations)]
        traces.append(
            dict(
                attempt_id=row["attempt_id"],
                run_id=row["run_id"],
                member_id=member,
                fold_id=fold,
                configuration_sha256=config,
                n_contribution=row["n_contribution"],
                n_evaluated=row["n_evaluated"],
                status="failed" if index % 2 else "nonfinite",
                failure_reason="PRIVATE real retry retained",
                performance_reached=row["performance_viewed"],
            )
        )
    return dict(
        host_context=context,
        installed_snapshot=snapshot,
        run_pin=pin,
        traces=traces,
        expected_run_ids=["PRIVATE-HOST-FIXTURE"],
        stage_mapping=mapping(),
    ), source


def test_G14_design_count_three_is_only_an_accepted_archive_reference():
    ref = design_archive_reference()
    assert ref["value"] == 3
    assert ref["archive_sequence"] == 1380
    assert ref["archive_tip"] == (
        "8e87034167b9d8ad28a91c33b824eecb5cba59c1b47efbb982079e32ddecde4a"
    )
    assert (
        ref["acceptance_sha256"]
        == "40ba00bf7e64a10b4f66990dde6828be02f339365ee1df36dfc324e4fa85b6b0"
    )
    assert ref["gate_N"] is ref["complete_N"] is None
    assert ref["formal_projection_consumer_accepted"] is False


@pytest.mark.parametrize("field", ["value", "seq", "tip"])
def test_G14_old_design_count_sequence_or_tip_is_rejected(monkeypatch, field):
    root = Path(n_binding.__file__).parent / "contracts"
    receipt_path = root / "EVO883-C06CLK-v28-archive-acceptance-v1.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["engineering_handoff"]["C12_design_count_archive_reference"][field] = {
        "value": 2,
        "seq": 1378,
        "tip": "93a5f3b115e1651613d87f08de61d3b327c8aab31b95f8d77202d9fac1c0effb",
    }[field]
    changed = canonical(receipt) + b"\n"
    read_bytes = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: changed if p == receipt_path else read_bytes(p)
    )
    # Bypass only the byte pin to exercise the semantic binding rejection too.
    monkeypatch.setattr(n_binding, "DESIGN_RECEIPT_SHA256", sha256(changed))
    with pytest.raises(ValueError, match="^execution.design_archive_binding_changed$"):
        design_archive_reference()


@pytest.mark.parametrize("replace", ["receipt", "archive", "both"])
def test_G14_v27_receipt_or_archive_cannot_replace_current_binding(
    monkeypatch, replace
):
    root = Path(n_binding.__file__).parent / "contracts"
    old_receipt = (root / "EVO883-G14P1-v27-archive-acceptance-v1.json").read_bytes()
    assert sha256(old_receipt) == (
        "7543d251170dd423a0b4aec42913486e0b02f0de876cc7809d1105b0b1e9d5d6"
    )
    old_archive = (root / "EVO891-B-ledger-v27.jsonl.gz").read_bytes()
    assert json.loads(gzip.decompress(old_archive).splitlines()[-1])["seq"] == 1378
    replacement = {}
    if replace in {"receipt", "both"}:
        replacement[root / "EVO883-C06CLK-v28-archive-acceptance-v1.json"] = old_receipt
    if replace in {"archive", "both"}:
        replacement[root / "EVO891-B-ledger-v28.jsonl.gz"] = old_archive
    read_bytes = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda p: replacement[p] if p in replacement else read_bytes(p),
    )
    with pytest.raises(ValueError, match="^execution.design_archive_identity_changed$"):
        design_archive_reference()


@pytest.mark.parametrize("stage", sorted(STAGES))
def test_G14_stage_and_budget_columns_do_not_infer_zero_usage_or_reset(stage):
    value = mapping(stage)
    assert len(value["adopted_clauses"]) == 5
    assert value["historical_walk_forward"]["token_usage"] is None
    assert value["historical_walk_forward"]["remaining"] is None
    assert value["historical_walk_forward"]["reset_or_reissue"] is False
    assert value["actual_attempt_N"]["contribution"] is None
    assert value["actual_attempt_N"]["failure_and_retry_exemption"] is False
    assert value["actual_attempt_N"]["daily_automatic_charge"] is False
    assert (
        value["budget_mapping_acceptance"]
        is value["stage_acceptance"]
        is value["L0"]
        is None
    )
    assert value["G14"] == "UNVERIFIED"
    assert value["runtime_consumable"] is False
    if stage == "actual_forward_observation":
        assert (
            value["historical_walk_forward"]["disposition"]
            == "SEPARATE_ONLY_AFTER_STAGE_ACCEPTANCE_AND_L0"
        )
    else:
        assert (
            value["historical_walk_forward"]["disposition"]
            == "ORIGINAL_PRODUCER_AUTHORITY_REQUIRED"
        )


def test_A22_production_missing_authority_objects_refuses_with_no_runtime_slot():
    before = len(host._PINS), len(host._SNAPSHOTS)
    result = bind_execution_n(
        host_context=None,
        installed_snapshot=None,
        run_pin=None,
        traces=[],
        expected_run_ids=["none"],
        stage_mapping=mapping(),
    )
    assert result["formal_N_slot"] is None
    assert result["reasons"] == ["ledger.trusted_project_installation_required"]
    assert result["runtime_consumable"] is result["complete"] is False
    assert result["design_count_archive_reference"]["value"] == 3
    assert before == (len(host._PINS), len(host._SNAPSHOTS))
    assert (
        result["N_reader_receipt"]["observations"]["formal_projection_consumption"] == 0
    )


@pytest.mark.parametrize("claim", [2, 3, 308, 1313, 9999])
def test_A23_design_slots_or_book_high_water_never_replace_complete_arm_N(
    tmp_path, monkeypatch, claim
):
    arguments, _ = private_bound_source(tmp_path, monkeypatch)
    result = bind_execution_n(**arguments, request_metrics={"self_report_n": claim})
    assert result["formal_N_slot"] is None
    assert result["reasons"] == ["reception.N_complete_projection_required"]
    assert result["N_reader_receipt"]["details"]["gate_N"] is None
    assert result["N_reader_receipt"]["details"]["request_book_or_high_water"] is None
    child = result["N_reader_receipt"]["details"]["n_acceptance"]
    assert child["details"]["n_evaluated_unknown_count"] == 101
    assert child["details"]["complete_N"] is None
    assert len(result["bound_attempts"]) == 101
    assert all(
        item["trace"]["n_evaluated"] is None for item in result["bound_attempts"]
    )
    assert (
        sum(item["trace"]["n_contribution"] for item in result["bound_attempts"])
        == 1238
    )


@pytest.mark.parametrize(
    "change",
    [
        "drop_retry",
        "retry_zero",
        "unknown_zero",
        "erase_reach",
        "drop_reason",
        "wrong_fold",
        "wrong_member",
        "duplicate",
        "wrong_run",
    ],
)
def test_A23_actual_failures_retries_configurations_and_original_contributions_retained(
    tmp_path, monkeypatch, change
):
    arguments, _ = private_bound_source(tmp_path, monkeypatch, complete=True)
    original = deepcopy(arguments["traces"])
    trace = arguments["traces"][0]
    if change == "drop_retry":
        arguments["traces"].pop()
    elif change == "retry_zero":
        trace["n_contribution"] = 0
    elif change == "unknown_zero":
        trace["n_evaluated"] = 0
    elif change == "erase_reach":
        trace["performance_reached"] = False
    elif change == "drop_reason":
        trace["failure_reason"] = ""
    elif change == "wrong_fold":
        trace["fold_id"] = "not-a-frozen-fold"
    elif change == "wrong_member":
        trace["member_id"] = "NOT-REGISTERED"
    elif change == "duplicate":
        arguments["traces"].append(deepcopy(trace))
    elif change == "wrong_run":
        trace["run_id"] = "OTHER-RUN"
    before = deepcopy(arguments["traces"])
    result = bind_execution_n(**arguments)
    assert result["formal_N_slot"] is None, change
    assert result["reasons"], change
    assert result["reported_attempts"] == before
    assert arguments["traces"] == before
    assert result["runtime_consumable"] is False
    assert original != before


def test_A24_only_private_complete_reader_value_is_consumed_not_a_runtime_release(
    tmp_path, monkeypatch
):
    arguments, source = private_bound_source(tmp_path, monkeypatch, complete=True)
    before = (tmp_path / "EVO891-B-ledger-v2.jsonl").read_bytes()
    result = bind_execution_n(**arguments, request_metrics={"self_report_n": 1313})
    assert result["reasons"] == []
    assert result["formal_N_slot"] == 7
    assert len(execution_configurations()) == 308
    assert len(result["bound_attempts"]) == 101
    assert result["design_count_archive_reference"]["value"] == 3
    assert result["runtime_consumable"] is result["complete"] is False
    assert result["remaining_reception"] == [
        "actual_B_publication",
        "P4_actual_DAG",
        "P7_complete_arm_N",
        "C09_C10_formal_reception",
    ]
    assert (
        (tmp_path / "EVO891-B-ledger-v2.jsonl").read_bytes()
        == before
        == source["chain_raw"]
    )


@pytest.mark.parametrize(
    "field", ["token_usage", "reset_or_reissue", "runtime_consumable"]
)
def test_G14_caller_cannot_turn_mapping_into_budget_exemption(
    tmp_path, monkeypatch, field
):
    arguments, _ = private_bound_source(tmp_path, monkeypatch)
    if field == "runtime_consumable":
        arguments["stage_mapping"][field] = 0  # False must remain an exact bool.
    else:
        arguments["stage_mapping"]["historical_walk_forward"][field] = (
            0 if field == "token_usage" else True
        )
    result = bind_execution_n(**arguments)
    assert result["formal_N_slot"] is None
    assert result["reasons"] == ["execution.stage_budget_mapping_changed"]
    assert result["N_reader_receipt"] is None


def test_A22_serialized_receipts_design_archive_cannot_mint_host_capabilities():
    ref = design_archive_reference()
    result = bind_execution_n(
        host_context={"accepted": True},
        installed_snapshot=ref,
        run_pin={"accepted": True},
        traces=[],
        expected_run_ids=["r"],
        stage_mapping=mapping(),
    )
    assert result["formal_N_slot"] is None
    assert result["reasons"] == ["ledger.trusted_project_installation_required"]
    assert json.loads(json.dumps(result))["complete"] is False

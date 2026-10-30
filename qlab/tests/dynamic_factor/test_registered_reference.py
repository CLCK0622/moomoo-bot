import json
import subprocess
import sys
from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import canonical, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.fold_split import shared_views, reference_view, train_dates
from qlab.dynamic_factor.reference_boundary import run_isolated, prepare_request
from qlab.dynamic_factor.reference_registry import (
    HASHES,
    DISPATCH,
    artifact,
    member_spec,
    registered_request,
)
from qlab.dynamic_factor.reference_evidence import (
    reference_runtime_check,
    seal_static,
    lineage_proof,
)
from qlab.dynamic_factor.reference_harness import (
    runtime_fixture,
    mutate_case,
    audit_read_probe,
)
from qlab.dynamic_factor.reference_check import reference_manifest_check
from qlab.dynamic_factor.v1_harness import producer_fixture


def put(request, doc):
    raw = canonical(doc).decode()
    h = sha256(raw.encode())
    request["evidence_files"][h] = raw
    return h


def mutate_sidecars(request, modify):
    for role in ("candidate", "meta"):
        doc = json.loads(request["evidence_files"][request["sidecars"][role]])
        modify(request, doc)
        request["sidecars"][role] = put(request, doc)


def refused(request, reason):
    report = reference_runtime_check(request)
    assert report["reasons"] == [reason]
    assert not report["certifiable"] and report["runtime_consumable"] is False
    assert (
        report["metrics"]["dsr"] is None
        and report["metrics"]["trials_variance"] is None
    )


def test_registered_bytes_dispatch_and_roles_are_closed():
    for name, expected in HASHES.items():
        assert artifact(name)["sha256"] == expected
    assert reference_manifest_check(registered_request())["ok"]
    assert {member_spec(m)["recipe_id"] for m in DISPATCH} == {
        "F1-L020",
        "F2-L020",
        "F3-L020",
        "F4-L020",
    }
    assert all(
        member_spec(m)["execution_profile_id"] == "CANDIDATE_PROBE_V03"
        for m in DISPATCH
    )
    assert all(
        member_spec(m)["execution_contract"]["parameter_search"] is False
        for m in DISPATCH
    )
    with pytest.raises(ValueError, match="member_not_registered"):
        member_spec("META_POLICY_V03")


def test_all_77_same_object_views_and_seven_proposition_statuses():
    policy = load_conventions()
    seal = seal_static("2026-10-30T03:40:00Z")
    proof = lineage_proof(policy, seal)
    assert len(proof["fold_view_receipts"]) == 77
    assert {p["id"]: p["status"] for p in proof["propositions"]} == {
        "P1": "已证",
        "P2": "已证",
        "P3": "已证",
        "P4": "仅校验器",
        "P5": "已证",
        "P6": "已证",
        "P7": "仅校验器",
    }
    assert proof["actual_run_id"] is None and proof["actual_output_sha256"] is None
    fold = policy.fold_manifest()["folds"][0]
    v = shared_views(policy.calendar, fold, train_days=1260, warmup_days=252)
    with pytest.raises(ValueError, match="shared_splitter_or_fold_object"):
        reference_view(v, dict(fold), train_dates)
    with pytest.raises(ValueError, match="shared_splitter_or_fold_object"):
        reference_view(v, fold, lambda *a: ())
    with pytest.raises(ValueError, match="shared_splitter_or_fold_object"):
        prepare_request(policy, dict(fold), v, {})


def test_isolated_preparation_reads_only_three_inputs_and_emits_no_performance(
    tmp_path,
):
    root = tmp_path / "sealed"
    request = producer_fixture(root, load_conventions())
    report = run_isolated(root, request)
    assert report["accessed_roles"] == ["benchmark", "panel", "profile"]
    assert len(report["train_dates"]) == 1260 and len(report["warmup_dates"]) == 252
    assert report["returns"] is None and report["sr"] is None
    assert not report["runtime_consumable"]
    canary = tmp_path / "candidate-result.json"
    canary.write_text('{"synthetic":true}')
    assert audit_read_probe(root, canary)


@pytest.mark.parametrize("operation", ["write", "process"])
def test_worker_audit_hook_refuses_write_and_process(tmp_path, operation):
    from qlab.dynamic_factor import reference_guard

    root = tmp_path / "sealed"
    root.mkdir()
    code = (
        "import sys,subprocess;sys.path.insert(0,"
        + repr(
            str(
                __import__("pathlib")
                .Path(reference_guard.__file__)
                .resolve()
                .parents[2]
            )
        )
        + ");from qlab.dynamic_factor.reference_guard import install;install(sys.argv[1]);"
    )
    code += (
        "open(sys.argv[1]+'/panel.json','w')"
        if operation == "write"
        else "subprocess.run([sys.executable,'-c','pass'])"
    )
    r = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code, str(root)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode != 0 and "reference.access_boundary_" in r.stderr
    assert not (root / "panel.json").exists()


@pytest.mark.parametrize("tamper", ["dispatch", "short", "profile", "extra_test"])
def test_worker_rejects_self_reported_weakened_contract(tmp_path, tamper):
    root = tmp_path / "sealed"
    request = producer_fixture(root, load_conventions())
    if tamper == "dispatch":
        request["dispatch"]["CREF-F1-L020"]["fixed_rule"]["lookback_sessions"] = 1
    elif tamper == "profile":
        request["profile_binding"]["conventions_version"] = "v0.2"
    elif tamper == "short":
        request["view"]["receipt"]["train_days"] = 1
    else:
        request["view"]["test"] = ["2099-01-01"]
    r = run_isolated(root, request)
    assert r["returns"] is None and "prepared_members" not in r


@pytest.mark.parametrize(
    "case",
    artifact("runtime-evidence-contract.json")["document"]["negative_cases_required"],
)
def test_seven_required_negatives_refuse_with_specific_reason_and_preserve_input(case):
    r = runtime_fixture(load_conventions())
    before = canonical(r)
    bad = mutate_case(r, case)
    report = reference_runtime_check(bad)
    assert not report["ok"] and len(report["reasons"]) == 1
    assert (
        report["metrics"]["dsr"] is None
        and report["metrics"]["trials_variance"] is None
    )
    assert canonical(r) == before


def test_two_hash_domains_accept_synthetic_receipts_without_certifying():
    r = runtime_fixture(load_conventions())
    assert all(
        r["sidecars"][role] != r["manifests"][role]["sha256"]
        for role in ("candidate", "meta")
    )
    result = reference_runtime_check(r)
    assert result["ok"] and result["metrics"]["evidence_valid"]
    assert (
        result["metrics"]["dsr"] is None
        and not result["runtime_consumable"]
        and not result["certifiable"]
    )


@pytest.mark.parametrize("count", [None, True, 2])
def test_unknown_boolean_or_repeated_scale_conversion_refuses(count):
    r = runtime_fixture(load_conventions())

    def modify(req, sidecar):
        sidecar["trials"][0]["scale_conversions"] = count

    mutate_sidecars(r, modify)
    refused(r, "dsr.scale_mismatch_or_repeated_conversion")


@pytest.mark.parametrize(
    "tamper",
    ["missing_retry", "zero_retry", "meta_not_registered", "candidate_omitted"],
)
def test_N_map_and_snapshot_order_refuse_missing_real_computations(tamper):
    r = runtime_fixture(load_conventions())

    def modify(req, sidecar):
        env = sidecar["envelope"]
        tail = json.loads(
            req["evidence_files"][env["authoritative_complete_N_tail_anchor"]]
        )
        attempts = json.loads(req["evidence_files"][tail["attempt_map_sha256"]])
        if tamper in ("missing_retry", "zero_retry"):
            a = deepcopy(attempts[0])
            a["attempt_id"] += "/ACTUAL_RETRY"
            if tamper == "zero_retry":
                a["n_contribution"] = 0
            attempts.append(a)
        elif tamper == "meta_not_registered":
            env["N_meta"].pop("actual_meta_attempt_id")
        else:
            attempts = [a for a in attempts if a["member_id"] != "F1-L005"]
        tail["attempt_map_sha256"] = put(req, attempts)
        env["authoritative_complete_N_tail_anchor"] = put(req, tail)

    mutate_sidecars(r, modify)
    refused(
        r,
        "reference.complete_N_missing_or_retry_not_counted"
        if tamper != "meta_not_registered"
        else "reference.N_snapshot_order_invalid",
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "seal_after_generation",
        "S0_before_generation",
        "source_change",
        "wrong_cost_policy",
        "test_row",
        "NaN",
    ],
)
def test_runtime_lineage_time_policy_window_and_failure_guards(tamper):
    r = runtime_fixture(load_conventions())
    reason = "reference.seal_or_output_not_preperformance"
    if tamper == "source_change":
        seal = json.loads(r["evidence_files"][r["static_seal_sha256"]])
        seal["sources"]["reference_guard.py"] = "0" * 64
        r["static_seal_sha256"] = put(r, seal)
        reason = "reference.static_seal_mismatch"
    elif tamper == "seal_after_generation":
        seal = seal_static("2026-10-30T04:00:00Z")
        r["static_seal_sha256"] = put(r, seal)
    else:

        def modify(req, sidecar):
            if tamper == "S0_before_generation":
                sidecar["envelope"]["current_S0_at"] = "2026-10-30T03:42:00Z"
            elif tamper == "wrong_cost_policy":
                sidecar["trials"][0]["cost_policy_sha256"] = put(
                    req, {"wrong": "policy"}
                )
            else:
                trial = sidecar["trials"][0]
                values = json.loads(
                    req["evidence_files"][trial["source_returns_sha256"]]
                )
                if tamper == "test_row":
                    values["dates"][-1] = "2099-01-01"
                else:
                    values["values"][0] = None
                trial["source_returns_sha256"] = put(req, values)

        mutate_sidecars(r, modify)
        if tamper == "wrong_cost_policy":
            reason = "reference.profile_or_version_mismatch"
        elif tamper == "test_row":
            reason = "reference.different_splitter_or_short_train_or_visible_test"
        elif tamper == "NaN":
            reason = "reference.failed_trial_or_NaN_SR"
    refused(r, reason)

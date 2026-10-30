"""SYNTHETIC ONLY receipt mechanics, never a real run ID or return artifact.

The registered definitions are real. Every runtime receipt/value below is an
explicit unit sentinel kept in temporary harness roots, not research evidence.
"""

import json
import subprocess
import sys
from copy import deepcopy

from .contract import canonical, digest, sha256
from .reference_registry import artifact, registered_request, DISPATCH, member_spec
from .reference_evidence import seal_static, reference_runtime_check


def audit_read_probe(root, forbidden):
    """Attempt a synthetic canary read in a disposable child, never real output."""
    from pathlib import Path

    package = str(Path(__file__).resolve().parents[2])
    code = (
        "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor.reference_guard import install;install(sys.argv[1]);open(sys.argv[2]).read()"
    )
    child = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code, str(root), str(forbidden)],
        capture_output=True,
        text=True,
        env={},
        timeout=15,
    )
    return (
        child.returncode != 0
        and "reference.access_boundary_read_or_write_forbidden" in child.stderr
    )


def wrapped(doc):
    raw = canonical(doc).decode()
    return {"raw": raw, "document": doc, "sha256": sha256(raw.encode())}


def runtime_fixture(policy):
    request = registered_request()
    files = {}

    def add(doc):
        raw = canonical(doc).decode()
        key = sha256(raw.encode())
        files[key] = raw
        return key

    request.update(synthetic_only=True, evidence_files=files, sidecars={})
    seal = seal_static("2026-10-30T03:40:00Z")
    request["static_seal_sha256"] = add(seal)
    source_sha = digest(seal["sources"])
    fold = artifact("fold-bindings.json")["document"]["folds"][0]
    lo, hi = fold["train_index_inclusive"]
    returns_sha = add(
        {
            "SYNTHETIC_UNIT_ONLY_NOT_REFERENCE_RETURNS": True,
            "dates": list(policy.calendar[lo : hi + 1]),
            "values": [0.01, -0.01] * (hi - lo + 1 >> 1),
        }
    )
    view_sha = add(
        {
            "shared_object_verified": True,
            "splitter_source_sha256": seal["sources"]["fold_split.py"],
            "train_calendar_sha256": fold["train_calendar_sha256"],
            "warmup_calendar_sha256": fold["warmup_calendar_sha256"],
        }
    )
    boundary_sha = add(
        {
            "accessed_roles": ["benchmark", "panel", "profile"],
            "producer_code_sha256": source_sha,
            "guard_source_sha256": seal["sources"]["reference_guard.py"],
        }
    )
    dag_sha = add(
        {
            "edges": artifact("lineage-plan.json")["document"]["graph_edges_allowed"],
            "producer_run_id": "SYNTHETIC_UNIT_REFERENCE_NOT_A_RUN",
            "producer_code_sha256": source_sha,
            "output_returns_sha256": [returns_sha],
        }
    )
    anchor = artifact("platform-anchor.json")["document"]
    review_sha = add(
        {
            "anchor_comment_id": anchor["id"],
            "anchor_created_at": anchor["created_at"],
            "reviewer_is_non_author": True,
            "preperformance_verified": True,
            "SYNTHETIC_UNIT_NOT_REVIEW": True,
        }
    )
    inputs_sha = add({"SYNTHETIC_UNIT_NOT_MARKET_INPUT": True})
    cost_sha = add(policy.profile["cost_model"])
    valuation_sha = add(policy.profile["corporate_action_policy"])
    attempts = [
        {
            "attempt_id": "SYNTHETIC_UNIT_ATTEMPT/" + m,
            "trial_id": "SYNTHETIC_UNIT_TRIAL/" + m,
            "run_id": "SYNTHETIC_UNIT_REFERENCE_NOT_A_RUN",
            "member_id": m,
            "n_contribution": 1,
            "registered_at": "2026-10-30T03:41:00Z",
            "sequence": i + 1,
            "kind": "reference",
        }
        for i, m in enumerate(sorted(DISPATCH))
    ]
    for i, m in enumerate(
        policy.document["variance_layers"]["family_definitions"]["candidate_members"]
    ):
        attempts.append(
            {
                "attempt_id": "SYNTHETIC_CANDIDATE/" + m,
                "trial_id": "SYNTHETIC_CANDIDATE_TRIAL/" + m,
                "run_id": "SYNTHETIC_UNIT_CANDIDATE_NOT_A_RUN",
                "member_id": m,
                "n_contribution": 1,
                "registered_at": "2026-10-30T03:45:00Z",
                "sequence": 5 + i,
                "kind": "candidate",
            }
        )
    attempts.append(
        {
            "attempt_id": "SYNTHETIC_META_ATTEMPT",
            "trial_id": "SYNTHETIC_META_TRIAL",
            "run_id": "SYNTHETIC_UNIT_META_NOT_A_RUN",
            "member_id": "META_POLICY_V03",
            "n_contribution": 1,
            "registered_at": "2026-10-30T03:48:00Z",
            "sequence": 21,
            "kind": "meta",
        }
    )
    lid = digest("SYNTHETIC_UNIT_LEDGER_NOT_AUTHORITY")
    tail = {
        "owner": "EVO891",
        "complete": True,
        "ledger_id": lid,
        "sequence": 21,
        "N": 21,
        "n_high_water": 21,
        "genesis_sha256": digest("unit-genesis"),
        "tip": digest("unit-tail"),
        "snapshot_sha256": digest("unit-snapshot"),
        "ledger_file_sha256": digest("unit-ledger"),
        "attempt_map_sha256": add(attempts),
        "complete_history_acceptance_receipt_sha256": add(
            {
                "owner": "EVO891",
                "complete": True,
                "ledger_id": lid,
                "SYNTHETIC_UNIT_NOT_AUTHORITY": True,
            }
        ),
    }
    tail_sha = add(tail)
    for role in ("candidate", "meta"):
        trials = []
        for a in attempts:
            if a["kind"] != "reference" or DISPATCH[a["member_id"]][0] != role:
                continue
            m = member_spec(a["member_id"])
            t = {
                k: digest("unit/" + k)
                for k in artifact("runtime-evidence-contract.json")["document"][
                    "required_per_fold_trial"
                ]
            }
            t.update(
                trial_id=a["trial_id"],
                member_id=m["member_id"],
                profile_id=m["profile_id"],
                return_role=m["return_role"],
                execution_profile_id=m["execution_profile_id"],
                common_profile_sha256=m["common_profile_sha256"],
                panel64_sha256=m["panel64_sha256"],
                cost_x1_sha256=policy.document["cost_mapping"]["x1_sha256"],
                cost_x2_sha256=policy.document["cost_mapping"]["x2_sha256"],
                raw_market_and_corporate_actions_manifest_sha256=inputs_sha,
                cost_policy_sha256=cost_sha,
                valuation_contract_sha256=valuation_sha,
                source_run_id=a["run_id"],
                source_returns_sha256=returns_sha,
                train_calendar_sha256=fold["train_calendar_sha256"],
                warmup_calendar_sha256=fold["warmup_calendar_sha256"],
                splitter_source_and_shared_object_receipt_sha256=view_sha,
                n_observations=1260,
                SR_daily_or_failure_reason=0.0,
                scale_daily=True,
                status="success",
                scale_conversions=0,
                generation_started_at="2026-10-30T03:42:00Z",
                generation_completed_at="2026-10-30T03:43:00Z",
                authoritative_attempt_id_and_N_contribution={
                    "attempt_id": a["attempt_id"],
                    "n_contribution": 1,
                },
            )
            t["1260_dates_no_omission"] = True
            trials.append(t)
        env = {
            k: "SYNTHETIC_UNIT_NOT_RUNTIME"
            for k in artifact("runtime-evidence-contract.json")["document"][
                "required_runtime_envelope"
            ]
        }
        env.update(
            registry_sha256=request["registry"]["sha256"],
            definition_manifest_sha256=request["manifests"][role]["sha256"],
            platform_anchor_comment_id=anchor["id"],
            platform_anchor_created_at=anchor["created_at"],
            independent_anchor_verification_receipt_sha256=review_sha,
            orchestration_batch_id="SYNTHETIC_UNIT_NOT_BATCH",
            actual_reference_producer_run_id="SYNTHETIC_UNIT_REFERENCE_NOT_A_RUN",
            actual_current_candidate_run_id="SYNTHETIC_UNIT_CANDIDATE_NOT_A_RUN",
            actual_current_meta_run_id_or_precreated_task_id="SYNTHETIC_UNIT_META_NOT_A_RUN",
            producer_code_sha256=source_sha,
            isolation_and_access_allowlist_receipt_sha256=boundary_sha,
            DAG_and_input_lineage_sha256=dag_sha,
            authoritative_complete_N_tail_anchor=tail_sha,
            exact_membership_and_attempt_map={
                t["member_id"]: t["authoritative_attempt_id_and_N_contribution"][
                    "attempt_id"
                ]
                for t in trials
            },
            current_S0_at="2026-10-30T03:45:00Z",
            current_S2_at="2026-10-30T03:47:00Z",
            current_S3_at="2026-10-30T03:48:00Z",
            current_S4_at="2026-10-30T03:50:00Z",
            N_candidate={
                "ledger_id": lid,
                "sequence": 20,
                "N": 20,
                "tip": digest("unit-candidate-tip"),
                "at": "2026-10-30T03:46:00Z",
            },
            N_meta={
                "actual_meta_attempt_id": "SYNTHETIC_META_ATTEMPT",
                "ledger_id": lid,
                "sequence": 21,
                "N": 21,
                "tip": digest("unit-meta-tip"),
                "at": "2026-10-30T03:49:00Z",
            },
        )
        request["sidecars"][role] = add(
            {
                "envelope": env,
                "trials": trials,
                "fold_id": "0",
                "sealed_at": "2026-10-30T03:44:00Z",
            }
        )
    return request


def mutate_case(request, case):
    r = deepcopy(request)
    files = r["evidence_files"]

    def add(doc):
        raw = canonical(doc).decode()
        h = sha256(raw.encode())
        files[h] = raw
        return h

    if case == "missing_registry_or_platform_anchor":
        r["registry"].pop("platform_anchor")
    elif case == "definition_SHA_mismatch":
        r["manifests"]["candidate"]["sha256"] = "0" * 64
    elif case == "member_added_removed_or_wrong_role":
        doc = json.loads(r["manifests"]["candidate"]["raw"])
        doc["members"][0]["member_id"] = "NOT_REGISTERED"
        r["manifests"]["candidate"] = wrapped(doc)
    else:
        for role in ("candidate", "meta"):
            sidecar = json.loads(files[r["sidecars"][role]])
            env = sidecar["envelope"]
            if case == "current_output_copy_or_result_cache_read":
                env["actual_reference_producer_run_id"] = env[
                    "actual_current_candidate_run_id"
                ]
            elif case == "different_splitter_or_short_train_or_visible_test":
                for t in sidecar["trials"]:
                    t["train_calendar_sha256"] = "0" * 64
            elif case == "failed_trial_or_NaN_SR":
                sidecar["trials"][0]["status"] = "failed"
                sidecar["trials"][0]["SR_daily_or_failure_reason"] = None
            elif case == "complete_N_missing_or_retry_not_counted":
                tail = json.loads(files[env["authoritative_complete_N_tail_anchor"]])
                tail["complete"] = False
                env["authoritative_complete_N_tail_anchor"] = add(tail)
            else:
                raise AssertionError("unregistered negative case")
            r["sidecars"][role] = add(sidecar)
    return r


def runtime_negative_cases(policy, workdir=None):
    fixture = runtime_fixture(policy)
    baseline = reference_runtime_check(fixture, conventions=policy)
    assert baseline["ok"], baseline["reasons"]
    cases = []
    for case in artifact("runtime-evidence-contract.json")["document"][
        "negative_cases_required"
    ]:
        report = reference_runtime_check(mutate_case(fixture, case), conventions=policy)
        expected_reason = {
            "missing_registry_or_platform_anchor": "reference.platform_anchor_missing_or_mismatch",
            "definition_SHA_mismatch": "reference.manifest_sha_mismatch",
            "member_added_removed_or_wrong_role": "reference.member_not_registered_or_incomplete",
        }.get(case, "reference." + case)
        assert report["reasons"] == [expected_reason], report["reasons"]
        assert (
            not report["ok"]
            and not report["certifiable"]
            and not report["runtime_consumable"]
        )
        assert (
            report["metrics"]["dsr"] is None
            and report["metrics"]["trials_variance"] is None
        )
        if case == "current_output_copy_or_result_cache_read" and workdir is not None:
            root = workdir / "audit-reader"
            root.mkdir()
            forbidden = workdir / "SYNTHETIC_CANDIDATE_CANARY.json"
            forbidden.write_text('{"synthetic":true}')
            assert audit_read_probe(root, forbidden)
        cases.append(
            {
                "case_id": "reference.runtime." + case,
                "required_case": case,
                "status": "PASS",
                "synthetic_only": True,
                "observed": {"reasons": report["reasons"], "dsr": None, "V": None},
            }
        )
    return cases

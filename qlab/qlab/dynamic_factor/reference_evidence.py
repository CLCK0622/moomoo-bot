"""P4/P7 receipt validators. Validation never generates returns or writes N."""

import json
from datetime import datetime
from pathlib import Path

from .contract import digest, is_sha, result, sha256, unavailable
from .conventions import load_conventions
from .fees import finite
from .reference_registry import artifact, HASHES, DISPATCH, member_spec


def timestamp(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("reference.timezone_required")
    return t


def lineage_sources():
    # These include the host mapper and validators as well as the worker graph.
    names = (
        "reference_registry",
        "reference_boundary",
        "reference_guard",
        "reference_inputs",
        "reference_producer",
        "reference_check",
        "reference_evidence",
        "fold_split",
        "folds",
        "authority_ledger",
        "input_scope",
        "scope_reader",
        "scope_proof",
        "continuity",
        "pipeline",
        "execution",
        "valuation",
        "pending",
        "input_disposition",
        "validation",
        "fees",
    )
    return {
        n + ".py": sha256((Path(__file__).parent / (n + ".py")).read_bytes())
        for n in names
    }


def seal_static(sealed_at):
    from .reference_check import static_proof

    anchor = artifact("platform-anchor.json")["document"]
    if timestamp(sealed_at) <= timestamp(anchor["created_at"]):
        raise ValueError("reference.seal_predates_registration")
    return {
        "schema": "EVO884.reference-static-seal/v1",
        "sealed_at": sealed_at,
        "sources": lineage_sources(),
        "registry_sha256": HASHES["predeclared_reference_registry.json"],
        "definition_sha256": {
            r: HASHES[r + "_reference_manifest.json"] for r in ("candidate", "meta")
        },
        "static_proof_sha256": digest(static_proof()),
        "access_boundary": "isolated_python_worker_audit_hook_exact_three_readonly_files_no_network_or_process",
        "first_reference_performance_at": None,
        "requires_independent_preperformance_review": "EVO887",
        "runtime_consumable": False,
    }


def verify_seal(seal):
    expected = seal_static(seal["sealed_at"])
    if seal != expected:
        raise ValueError("reference.static_seal_mismatch")


def lineage_proof(policy, seal):
    from .reference_check import static_proof
    from .fold_split import shared_views, reference_view, train_dates
    from .reference_boundary import calendar_sha

    verify_seal(seal)
    rows = []
    declared = artifact("fold-bindings.json")["document"]["folds"]
    for fold, expected in zip(policy.fold_manifest()["folds"], declared):
        sizes = policy.document["folds"]
        views = shared_views(
            policy.calendar,
            fold,
            train_days=sizes["train_days"],
            warmup_days=sizes["warmup_days"],
        )
        train, warmup = reference_view(views, fold, train_dates)
        if (
            train is not views.train
            or warmup is not views.warmup
            or calendar_sha(train) != expected["train_calendar_sha256"]
            or calendar_sha(warmup) != expected["warmup_calendar_sha256"]
        ):
            raise ValueError("reference.shared_view_proof_failed")
        rows.append(
            {
                "fold_id": fold["fold_id"],
                "train_sha256": calendar_sha(train),
                "warmup_sha256": calendar_sha(warmup),
                "same_object_verified": True,
            }
        )
    if len(rows) != policy.document["folds"]["fold_count"]:
        raise ValueError("reference.fold_count_mismatch")
    proof = static_proof()
    details = {
        "P1": {
            "status": "已证",
            "evidence": "exact registered byte hashes + closed four-member dispatch; no search/evaluator callback",
            "dispatch": {m: digest(member_spec(m)) for m in sorted(DISPATCH)},
        },
        "P2": {
            "status": "已证",
            "evidence": "shared train/warmup tuples, exact three sealed input schemas; no gap/test rows; source proof and all-fold calendar receipts",
        },
        "P3": {
            "status": "已证",
            "evidence": "isolated -I -S child; audit hook before data reads; exact readonly file capabilities; static no forbidden imports/import-time reads",
            "scope": "pinned preparation entry; arbitrary native code/hostile operator excluded",
        },
        "P4": {
            "status": "仅校验器",
            "missing": "actual producer run/output DAG, SHA, generation timestamps and sealed sidecars",
            "dependency": "EVO886",
        },
        "P5": {
            "status": "已证",
            "evidence": "CREF F1/F3 candidate role; MREF F2/F4 meta17 probe-component role; all execute CANDIDATE_PROBE_V03 overrides, no new META_POLICY",
        },
        "P6": {
            "status": "已证",
            "evidence": "single shared callable source + same fold object and tuple identity; all 77 frozen train1260/warmup252 hashes verified",
            "runtime_note": "real per-run identity receipt still required before S0",
        },
        "P7": {
            "status": "仅校验器",
            "missing": "accepted complete-history receipt, unique writer attempt/retry map and actual ordered N snapshots",
            "dependency": "EVO891",
        },
    }
    return {
        "schema": "EVO884.EVO892-lineage-proof/v1",
        "propositions": [
            dict(p, **details[p["id"]])
            for p in artifact("lineage-plan.json")["document"][
                "static_propositions_to_prove"
            ]
        ],
        "static_seal": seal,
        "static_proof": proof,
        "fold_view_receipts": rows,
        "actual_run_id": None,
        "actual_output_sha256": None,
        "runtime_consumable": False,
        "certifiable": False,
        **policy.binding,
    }


def blob(files, sha):
    raw = files.get(sha)
    if not is_sha(sha) or not isinstance(raw, str) or sha256(raw.encode()) != sha:
        raise ValueError("reference.runtime_artifact_sha_missing_or_mismatch")
    return json.loads(raw)


def verify_N(
    tail,
    all_trials,
    candidate,
    meta,
    s0,
    s2,
    s3,
    s4,
    files,
    policy,
    candidate_run,
    meta_run,
):
    """EVO-891 witness field names; complete-history acceptance is a separate receipt.

    The seq20/N75 ancestor remains historical. Current receipts must descend from
    the latest published seq182/N280 witness; complete N remains unaccepted.
    """
    fields = (
        "ledger_id",
        "genesis_sha256",
        "tip",
        "snapshot_sha256",
        "ledger_file_sha256",
    )
    if (
        tail.get("owner") != "EVO891"
        or tail.get("complete") is not True
        or any(not is_sha(tail.get(k)) for k in fields)
        or type(tail.get("sequence")) is not int
        or tail["sequence"] < 0
        or type(tail.get("N")) is not int
        or tail["N"] < 0
        or tail.get("n_high_water", -1) < tail["N"]
    ):
        raise ValueError("reference.complete_N_missing_or_retry_not_counted")
    from .authority_ledger import (
        verify_bytes,
        state as authority_state,
        CURRENT_PUBLISHED,
    )

    raw_ledger = files.get(tail["ledger_file_sha256"])
    try:
        _, authority_rows = verify_bytes(raw_ledger.encode(), tail, CURRENT_PUBLISHED)
    except (ValueError, AttributeError, TypeError, KeyError):
        raise ValueError("reference.complete_N_missing_or_retry_not_counted") from None
    review = blob(files, tail.get("complete_history_acceptance_receipt_sha256"))
    if (
        review.get("owner") != "EVO891"
        or review.get("complete") is not True
        or review.get("ledger_id") != tail["ledger_id"]
    ):
        raise ValueError("reference.complete_N_missing_or_retry_not_counted")
    attempts = blob(files, tail.get("attempt_map_sha256"))
    ids = [a["attempt_id"] for a in attempts]
    if len(ids) != len(set(ids)):
        raise ValueError("reference.complete_N_missing_or_retry_not_counted")
    by_id = {a["attempt_id"]: a for a in attempts}
    runs = {candidate_run, meta_run} | {t["source_run_id"] for t in all_trials}
    actual = {
        r["attempt_id"]: r
        for r in authority_rows[21:]
        if r["event"] == "attempt" and r["run_id"] in runs
    }
    if set(actual) != set(by_id) or any(
        actual[a["attempt_id"]]["seq"] != a["sequence"]
        or actual[a["attempt_id"]]["n_contribution"] != a["n_contribution"]
        for a in attempts
    ):
        raise ValueError("reference.complete_N_missing_or_retry_not_counted")

    current = [
        a for a in attempts if a["kind"] == "candidate" and a["run_id"] == candidate_run
    ]
    expected = policy.document["variance_layers"]["family_definitions"][
        "candidate_members"
    ]
    if (
        len(current) != len(expected)
        or {a["member_id"] for a in current} != set(expected)
        or any(
            a["n_contribution"] != 1
            or a["sequence"] > candidate["sequence"]
            or timestamp(a["registered_at"]) > timestamp(candidate["at"])
            for a in current
        )
    ):
        raise ValueError("reference.N_snapshot_order_invalid")
    actual_meta = by_id.get(meta.get("actual_meta_attempt_id"))
    if (
        actual_meta is None
        or actual_meta["kind"] != "meta"
        or actual_meta["run_id"] != meta_run
        or actual_meta["n_contribution"] != 1
        or not candidate["sequence"] < actual_meta["sequence"] <= meta["sequence"]
        or not timestamp(s3)
        <= timestamp(actual_meta["registered_at"])
        <= timestamp(meta["at"])
        or meta["N"] < candidate["N"] + 1
    ):
        raise ValueError("reference.N_snapshot_order_invalid")
    seen = set()
    for trial in all_trials:
        contribution = trial["authoritative_attempt_id_and_N_contribution"]
        aid = contribution["attempt_id"]
        a = by_id.get(aid)
        if (
            aid in seen
            or a is None
            or contribution["n_contribution"] != 1
            or a["n_contribution"] != 1
            or a["member_id"] != trial["member_id"]
            or a["trial_id"] != trial["trial_id"]
            or a["run_id"] != trial["source_run_id"]
            or timestamp(a["registered_at"]) > timestamp(trial["generation_started_at"])
        ):
            raise ValueError("reference.complete_N_missing_or_retry_not_counted")
        seen.add(aid)
    # The unique writer supplies ALL real retries, including failed/NaN attempts.
    if any(
        a["kind"] == "reference"
        and (a["attempt_id"] not in seen or a["n_contribution"] != 1)
        for a in attempts
    ):
        raise ValueError("reference.complete_N_missing_or_retry_not_counted")
    for snap in (candidate, meta):
        if (
            snap["ledger_id"] != tail["ledger_id"]
            or not is_sha(snap["tip"])
            or snap["sequence"] > tail["sequence"]
            or snap["N"] > tail["N"]
        ):
            raise ValueError("reference.N_snapshot_order_invalid")
        actual_snapshot = authority_state(authority_rows[: snap["sequence"] + 1])
        if any(
            snap[k] != actual_snapshot[k] for k in ("ledger_id", "N", "sequence", "tip")
        ):
            raise ValueError("reference.N_snapshot_order_invalid")
    ref_seq = max(by_id[a]["sequence"] for a in seen)
    if not (
        ref_seq <= candidate["sequence"] <= meta["sequence"]
        and candidate["N"] <= meta["N"]
        and timestamp(s0) <= timestamp(candidate["at"]) < timestamp(s2)
        and timestamp(s3) <= timestamp(meta["at"]) < timestamp(s4)
    ):
        raise ValueError("reference.N_snapshot_order_invalid")


def verify_runtime(request, policy):
    from .reference_check import verify_registry

    verify_registry(
        request.get("registry"),
        request.get("manifests"),
        policy,
        request.get("first_performance_at"),
    )
    files = request.get("evidence_files", {})
    seal = blob(files, request.get("static_seal_sha256"))
    verify_seal(seal)
    contract = artifact("runtime-evidence-contract.json")["document"]
    envelopes = request.get("sidecars")
    if not isinstance(envelopes, dict) or set(envelopes) != {"candidate", "meta"}:
        raise ValueError("reference.runtime_sidecars_missing")
    all_trials, shared, times = [], None, None
    for role, sidecar_sha in envelopes.items():
        sidecar = blob(files, sidecar_sha)
        env, trials = sidecar["envelope"], sidecar["trials"]
        if any(env.get(k) is None for k in contract["required_runtime_envelope"]):
            raise ValueError("reference.runtime_envelope_incomplete")
        if (
            env["registry_sha256"] != HASHES["predeclared_reference_registry.json"]
            or env["definition_manifest_sha256"]
            != HASHES[role + "_reference_manifest.json"]
        ):
            raise ValueError("reference.manifest_sha_mismatch")
        anchor = artifact("platform-anchor.json")["document"]
        if (
            env["platform_anchor_comment_id"] != anchor["id"]
            or env["platform_anchor_created_at"] != anchor["created_at"]
        ):
            raise ValueError("reference.platform_anchor_missing_or_mismatch")
        anchor_review = blob(
            files, env["independent_anchor_verification_receipt_sha256"]
        )
        if (
            anchor_review.get("anchor_comment_id") != anchor["id"]
            or anchor_review.get("anchor_created_at") != anchor["created_at"]
            or anchor_review.get("reviewer_is_non_author") is not True
            or anchor_review.get("preperformance_verified") is not True
        ):
            raise ValueError("reference.independent_anchor_verification_missing")
        producer = env["actual_reference_producer_run_id"]
        if (
            not isinstance(producer, str)
            or not producer
            or producer
            in (
                env["actual_current_candidate_run_id"],
                env["actual_current_meta_run_id_or_precreated_task_id"],
            )
        ):
            raise ValueError("reference.current_output_copy_or_result_cache_read")
        if env["producer_code_sha256"] != digest(seal["sources"]):
            raise ValueError("reference.producer_source_mismatch")
        boundary = blob(files, env["isolation_and_access_allowlist_receipt_sha256"])
        if (
            boundary.get("accessed_roles") != ["benchmark", "panel", "profile"]
            or boundary.get("producer_code_sha256") != env["producer_code_sha256"]
            or boundary.get("guard_source_sha256")
            != seal["sources"]["reference_guard.py"]
        ):
            raise ValueError("reference.current_output_copy_or_result_cache_read")
        dag = blob(files, env["DAG_and_input_lineage_sha256"])
        allowed = set(artifact("lineage-plan.json")["document"]["graph_edges_allowed"])
        required = {
            "SEALED_RAW_INPUTS -> REFERENCE_PRODUCER",
            "SEALED_PROTOCOL_PROFILE -> REFERENCE_PRODUCER",
            "SHARED_SPLITTER_TRAIN_WARMUP_VIEWS -> REFERENCE_PRODUCER",
            "REFERENCE_PRODUCER -> IMMUTABLE_REFERENCE_SIDECARS -> CURRENT_S0",
        }
        if (
            not set(dag["edges"]).issubset(allowed)
            or not required.issubset(dag["edges"])
            or dag["producer_run_id"] != producer
            or dag["producer_code_sha256"] != env["producer_code_sha256"]
        ):
            raise ValueError("reference.current_output_copy_or_result_cache_read")
        expected = {m for m, (r, _) in DISPATCH.items() if r == role}
        if len(trials) != len(expected) or {t["member_id"] for t in trials} != expected:
            raise ValueError("reference.member_not_registered_or_incomplete")
        fold = next(
            f
            for f in artifact("fold-bindings.json")["document"]["folds"]
            if str(f["fold_id"]) == str(sidecar["fold_id"])
        )
        stage_times = tuple(
            env[k]
            for k in (
                "current_S0_at",
                "current_S2_at",
                "current_S3_at",
                "current_S4_at",
            )
        )
        if times is not None and times != stage_times:
            raise ValueError("reference.N_snapshot_order_invalid")
        times = stage_times
        for trial in trials:
            if trial.get("status") != "success" or not finite(
                trial.get("SR_daily_or_failure_reason")
            ):
                raise ValueError("reference.failed_trial_or_NaN_SR")
            if any(trial.get(k) is None for k in contract["required_per_fold_trial"]):
                raise ValueError("reference.trial_evidence_incomplete")
            spec = member_spec(trial["member_id"])
            if (
                trial["profile_id"] != spec["profile_id"]
                or trial["execution_profile_id"] != spec["execution_profile_id"]
                or trial["return_role"] != spec["return_role"]
                or trial["source_run_id"] != producer
            ):
                raise ValueError("reference.execution_role_mismatch")
            bindings = artifact(role + "_reference_manifest.json")["document"][
                "common_contract"
            ]["bindings"]
            for key in (
                "common_profile_sha256",
                "panel64_sha256",
                "cost_x1_sha256",
                "cost_x2_sha256",
            ):
                if trial[key] != bindings[key]:
                    raise ValueError("reference.profile_or_version_mismatch")
            blob(files, trial["raw_market_and_corporate_actions_manifest_sha256"])
            if (
                blob(files, trial["valuation_contract_sha256"])
                != policy.profile["corporate_action_policy"]
                or blob(files, trial["cost_policy_sha256"])
                != policy.profile["cost_model"]
            ):
                raise ValueError("reference.profile_or_version_mismatch")
            view = blob(
                files, trial["splitter_source_and_shared_object_receipt_sha256"]
            )
            if (
                view.get("shared_object_verified") is not True
                or view.get("splitter_source_sha256")
                != seal["sources"]["fold_split.py"]
                or trial["train_calendar_sha256"] != fold["train_calendar_sha256"]
                or trial["warmup_calendar_sha256"] != fold["warmup_calendar_sha256"]
                or view.get("train_calendar_sha256") != fold["train_calendar_sha256"]
                or view.get("warmup_calendar_sha256") != fold["warmup_calendar_sha256"]
            ):
                raise ValueError(
                    "reference.different_splitter_or_short_train_or_visible_test"
                )
            returns = blob(files, trial["source_returns_sha256"])
            lo, hi = fold["train_index_inclusive"]
            dates = list(policy.calendar[lo : hi + 1])
            if (
                returns["dates"] != dates
                or trial["n_observations"] != len(dates)
                or len(returns["values"]) != len(dates)
                or trial["1260_dates_no_omission"] is not True
            ):
                raise ValueError(
                    "reference.different_splitter_or_short_train_or_visible_test"
                )
            if (
                trial.get("status") != "success"
                or not finite(trial["SR_daily_or_failure_reason"])
                or not all(finite(v) for v in returns["values"])
            ):
                raise ValueError("reference.failed_trial_or_NaN_SR")
            if (
                trial["scale_daily"] is not True
                or trial.get("scale_conversions") not in (0, 1)
                or type(trial.get("scale_conversions")) is not int
            ):
                raise ValueError("dsr.scale_mismatch_or_repeated_conversion")
            if not (
                timestamp(anchor["created_at"])
                < timestamp(seal["sealed_at"])
                < timestamp(trial["generation_started_at"])
                <= timestamp(trial["generation_completed_at"])
                < timestamp(sidecar["sealed_at"])
                < timestamp(times[0])
            ):
                raise ValueError("reference.seal_or_output_not_preperformance")
            if trial["source_returns_sha256"] not in dag["output_returns_sha256"]:
                raise ValueError("reference.current_output_copy_or_result_cache_read")
        if env["exact_membership_and_attempt_map"] != {
            t["member_id"]: t["authoritative_attempt_id_and_N_contribution"][
                "attempt_id"
            ]
            for t in trials
        }:
            raise ValueError("reference.complete_N_missing_or_retry_not_counted")
        common = {
            k: env[k]
            for k in (
                "authoritative_complete_N_tail_anchor",
                "N_candidate",
                "N_meta",
                "orchestration_batch_id",
                "actual_reference_producer_run_id",
                "actual_current_candidate_run_id",
                "actual_current_meta_run_id_or_precreated_task_id",
            )
        }
        if shared is not None and shared != common:
            raise ValueError("reference.N_snapshot_order_invalid")
        shared = common
        all_trials.extend(trials)
    verify_N(
        blob(files, shared["authoritative_complete_N_tail_anchor"]),
        all_trials,
        shared["N_candidate"],
        shared["N_meta"],
        *times,
        files,
        policy,
        shared["actual_current_candidate_run_id"],
        shared["actual_current_meta_run_id_or_precreated_task_id"],
    )


def reference_runtime_check(request, *, conventions=None):
    policy = conventions or load_conventions()
    reasons = []
    try:
        verify_runtime(request, policy)
    except (ValueError, KeyError, TypeError, StopIteration, AttributeError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else "reference.runtime_evidence_missing_or_invalid"
        )
    return policy.bind(
        result(
            "reference_runtime_check",
            request,
            reasons=reasons,
            metrics={
                "evidence_valid": not reasons,
                "dsr": None,
                "trials_variance": None,
            },
            availability={
                k: unavailable(
                    reasons[0] if reasons else "dsr.runtime_bindings_pending"
                )
                for k in ("dsr", "trials_variance")
            },
            assumptions=[
                "Receipt hashes check supplied evidence consistency, not authenticity of a self-issued authority claim. Independent review and the unique writer remain external gates.",
                "P4 and P7 are validators only; no real run, return, complete N or authority receipt is created here.",
            ],
        )
    )

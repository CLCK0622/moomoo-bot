"""The sole N01/N02 v3 entrypoints. Module name retained from approved plan."""

from copy import deepcopy

from .arm_n import MISSING, label, valid_arm
from .authority_host import check_pin, check_snapshot, host_data, observe, view_binding
from .authority_ledger import replay_approved_archive
from .contract import digest, is_sha, sha256
from .reception_schema import empty_receipt, strict_json, validate


ENTRYPOINTS = {
    "authority.arm_readout",
    "AttemptLedger.arm_readout",
    "statistics.dsr_eval_arm",
    "statistics.arm_snapshot",
    "pipeline._n_snapshot",
    "pipeline.evaluate_arm",
    "__main__.dsr_eval",
    "dsr_v0.evaluate",
    "run_train_pipeline",
}


def presence(value):
    return (
        "ABSENT"
        if value is MISSING
        else "EXPLICIT_NULL"
        if value is None
        else "EXPLICIT_VALUE"
        if valid_arm(value)
        else "INVALID"
    )


def preflight_authority(host_context):
    """One immutable host buffer, shared V5, then original complete replay."""
    from .authority_prefix import verify_anchor_prefix

    source = observe(host_context)
    checked = verify_anchor_prefix(
        source["chain_raw"], source["anchor"], source["observation"]
    )
    if checked.get("status") != "PASS":
        raise ValueError(
            next(iter(checked.get("reasons", [])), "ledger.anchor_prefix_input_invalid")
        )
    return source, checked


def _refuse(report, reason):
    report["reasons"] = [reason]
    report["state"] = (
        "DEPENDENCY_REQUIRED"
        if reason
        in {
            "ledger.trusted_project_installation_required",
            "ledger.current_release_unbound_or_stale",
            "reception.N_complete_projection_required",
            "reception.N_required_document_missing",
        }
        else "REJECTED"
    )


def _binding(report):
    body = dict(
        schema=report["schema"],
        item_id=report["item_id"],
        input_identities=report["input_identities"],
        arm_tag=report["details"]["arm_tag"],
    )
    if report["item_id"] == "N-02":
        body.update(
            entrypoint=report["details"]["entrypoint"],
            n_acceptance_binding=report["details"]["n_acceptance"]["binding_sha256"],
        )
    return digest(body)


def _finish(report, name, defaults):
    try:
        validate(report, name)
        return report
    except ValueError:
        # Malformed untrusted fields cannot be echoed into the closed root.
        safe = empty_receipt(name, defaults)
        safe["observations"] = dict(report["observations"])
        _refuse(
            safe,
            report["reasons"][0]
            if report["reasons"]
            else "receipt.schema_version_mismatch",
        )
        validate(safe, name)
        return safe


def receive_arm_n(
    approval_bytes,
    projection_bytes,
    *,
    host_context,
    installed_snapshot,
    run_pin,
    arm_tag=MISSING,
):
    details = dict(
        arm_tag=arm_tag if valid_arm(arm_tag) else None,
        arm_tag_presence=presence(arm_tag),
        N_rows=None,
        complete_N=None,
        formal_n_available=False,
        projection_sha256=None,
        coverage_contract_sha256=None,
        acceptance_version=None,
        n_evaluated_unknown_count=None,
        unknown_attempt_refs=None,
        t1_replay=None,
        t1_replay_reason="reception.N_not_replayed",
    )
    report = empty_receipt("N-01.v3.schema.json", details)
    defaults = deepcopy(details)
    obs = report["observations"]
    try:
        obs["label_guard"] += 1
        obs["semantic_validator_entered"] += 1
        if not valid_arm(arm_tag):
            raise ValueError("arm_n.arm_tag_missing_or_invalid")
        if approval_bytes is None or projection_bytes is None:
            raise ValueError("reception.N_required_document_missing")
        # Parse strictly, but do not derive authority from syntax or self-hashes.
        strict_json(approval_bytes)
        projection = strict_json(projection_bytes)
        source, _, coverage = check_snapshot(host_context, installed_snapshot)
        pin_sha = check_pin(host_context, run_pin, arm_tag)
        obs["installed_identity_check"] += 1
        if (
            approval_bytes != source["approval_bytes"]
            or projection_bytes != source["projection_bytes"]
        ):
            raise ValueError("reception.N_untrusted_acceptance")
        if (
            type(projection) is not dict
            or set(projection)
            != {
                "arm_tag",
                "N_rows",
                "complete",
                "relevant_unknowns",
                "reconciliation_sha256",
                "acceptance_version",
            }
            or projection["arm_tag"] != arm_tag
        ):
            raise ValueError("reception.N_object_or_coverage_mismatch")
        source, _ = preflight_authority(host_context)
        replay = replay_approved_archive(
            source["chain_raw"], trusted_release=coverage, witness=source["witness"]
        )
        obs["archive_integrity_check"] += 1
        obs["construction_chain_verify"] += 1
        ids = report["input_identities"]
        for key in ids:
            if key in source["identities"]:
                ids[key] = source["identities"][key]
        ids.update(
            run_pin_sha256=pin_sha,
            approval_sha256=sha256(approval_bytes),
            projection_sha256=sha256(projection_bytes),
        )
        rows = projection["N_rows"]
        details.update(
            N_rows=rows,
            projection_sha256=ids["projection_sha256"],
            coverage_contract_sha256=ids["coverage_contract_sha256"],
            acceptance_version=projection["acceptance_version"],
            n_evaluated_unknown_count=replay["raw_unknown_rows"],
            unknown_attempt_refs=[
                dict(
                    seq=r["seq"],
                    attempt_id=r["attempt_id"],
                    row_sha256=r["raw_line_sha256"],
                )
                for r in replay["unknown_rows"]
            ],
            t1_replay=replay,
            t1_replay_reason=None,
        )
        # Validate exact two-row roles/types before consuming any value.
        report["reasons"] = ["reception.N_validation_in_progress"]
        validate(report, "N-01.v3.schema.json")
        if (
            type(projection["complete"]) is not bool
            or type(projection["relevant_unknowns"]) is not int
            or projection["relevant_unknowns"] < 0
        ):
            raise ValueError("reception.N_complete_projection_required")
        complete = (
            projection["complete"]
            and projection["relevant_unknowns"] == 0
            and rows[0]["known"]
        )
        if replay["raw_unknown_rows"] and complete:
            reconciliation = source.get("reconciliation_bytes")
            if (
                type(reconciliation) is not bytes
                or not is_sha(projection["reconciliation_sha256"])
                or sha256(reconciliation) != projection["reconciliation_sha256"]
            ):
                raise ValueError("reception.N_complete_projection_required")
            replay["accepted_reconciliation_sha256"] = sha256(reconciliation)
        if complete:
            number = rows[0]["value"]
            replay.update(
                stage="formal_N",
                relevant_unresolved_unknowns=0,
                full_authority_projection_complete=True,
                complete_N=number,
                gate_N=number,
                formal_lower_bound=number,
                formal_upper_bound=number,
                n_complete=True,
            )
            details.update(complete_N=number, formal_n_available=True)
        elif rows[0]["known"]:
            raise ValueError("reception.N_complete_projection_required")
        report.update(accepted=True, state="ACCEPTED_IDENTITY", reasons=[])
        obs["formal_projection_consumption"] += 1
        report["binding_sha256"] = _binding(report)
        # Same operation: a post-read change discards the result.
        check_pin(host_context, run_pin, arm_tag)
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        AttributeError,
        IndexError,
    ) as exc:
        report["accepted"] = False
        details["complete_N"] = None
        details["formal_n_available"] = False
        report["binding_sha256"] = None
        _refuse(
            report,
            str(exc)
            if isinstance(exc, ValueError)
            else "reception.N_object_or_coverage_mismatch",
        )
    return _finish(report, "N-01.v3.schema.json", defaults)


def bind_formal_n(
    *,
    host_context,
    request_metrics,
    installed_snapshot,
    entrypoint,
    run_pin,
    arm_tag=MISSING,
    candidate_ledger=None,
):
    if type(entrypoint) is not str or entrypoint not in ENTRYPOINTS:
        raise ValueError("reception.N_unexpected_dispatch_error")
    details = dict(
        entrypoint=entrypoint,
        arm_tag=None,
        arm_tag_presence=presence(arm_tag),
        embedded_tag_presence="ABSENT",
        accepted_N_receipt_sha256=None,
        run_pin_sha256=None,
        gate_N=None,
        request_book_or_high_water=None,
        candidate_ledger_status="NOT_PROVIDED"
        if candidate_ledger is None
        else "NOT_CHECKED",
        legacy_route="FORMAL",
        n_acceptance=None,
        n_acceptance_reason="reception.N_not_received",
    )
    report = empty_receipt("N-02.v3.schema.json", details)
    defaults = deepcopy(details)
    obs = report["observations"]
    try:
        obs["label_guard"] += 1
        obs["semantic_validator_entered"] += 1
        if type(request_metrics) is not dict or entrypoint not in ENTRYPOINTS:
            raise ValueError("reception.N_unexpected_dispatch_error")
        details["embedded_tag_presence"] = presence(
            request_metrics.get("arm_tag", MISSING)
        )
        tag = label(request_metrics, arm_tag)
        details["arm_tag"] = tag if valid_arm(tag) else None
        if not valid_arm(tag):
            raise ValueError("arm_n.arm_tag_missing_or_invalid")
        if candidate_ledger is not None:
            try:
                owner, snapshot, pin, arm = view_binding(candidate_ledger)
                if (
                    owner is not host_context
                    or snapshot is not installed_snapshot
                    or pin is not run_pin
                    or arm != tag
                ):
                    raise ValueError("reception.N_caller_ledger_not_authoritative")
            except ValueError:
                details["candidate_ledger_status"] = "REJECTED"
                raise
            details["candidate_ledger_status"] = "HOST_BOUND_VIEW"
        details["run_pin_sha256"] = check_pin(host_context, run_pin, tag)
        source = host_data(host_context)
        accepted = receive_arm_n(
            source["approval_bytes"],
            source["projection_bytes"],
            host_context=host_context,
            installed_snapshot=installed_snapshot,
            run_pin=run_pin,
            arm_tag=tag,
        )
        details.update(
            n_acceptance=accepted,
            n_acceptance_reason=None,
            accepted_N_receipt_sha256=digest(accepted),
        )
        report["input_identities"] = dict(accepted["input_identities"])
        for key, value in accepted["observations"].items():
            if key not in {"label_guard", "semantic_validator_entered"}:
                obs[key] += value
        if not accepted["accepted"]:
            raise ValueError(accepted["reasons"][0])
        if not accepted["details"]["formal_n_available"]:
            raise ValueError("reception.N_complete_projection_required")
        high = request_metrics.get("self_report_n")
        details["request_book_or_high_water"] = (
            high if type(high) is int and high >= 0 else None
        )
        details["gate_N"] = accepted["details"]["complete_N"]
        report.update(accepted=True, state="ACCEPTED_IDENTITY")
        report["binding_sha256"] = _binding(report)
        check_pin(host_context, run_pin, tag)
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        report["accepted"] = False
        details["gate_N"] = None
        report["binding_sha256"] = None
        _refuse(
            report,
            str(exc)
            if isinstance(exc, ValueError)
            else "reception.N_unexpected_dispatch_error",
        )
    return _finish(report, "N-02.v3.schema.json", defaults)

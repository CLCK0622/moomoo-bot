"""Read-only typed installation identity and same-host summary adapter."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from weakref import WeakKeyDictionary

from . import authority_host as host
from .authority_ledger import replay_approved_archive, records, state, verify_ancestor
from .authority_record_types import _issue_coverage, _HOST_TOKEN
from .contract import digest, sha256
from .reception_schema import contract, empty_receipt, strict_json, validate


TYPE_SHA = "004e9b402d853ebb0ba019fcfa95e7e519eb36c8043e453a2a1dc6aec6130d82"
_VALIDATIONS = WeakKeyDictionary()
GROUPS = tuple(contract("installation.schema.json")["required"])
TIME_KEYS = {
    "L1_created_at_utc",
    "L1_updated_at_utc",
    "anchor_L1_created_at",
    "installation_at_utc",
    "installed_at_utc",
    "nonauthor_readback_at_utc",
}


@dataclass(frozen=True, eq=False)
class ReceiptValidation:
    def __init__(self):
        raise TypeError("receipt.trusted_validation_required")


def _utc(value):
    if type(value) is not str:
        raise ValueError("receipt.timestamp_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("receipt.timestamp_invalid") from None
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("receipt.timestamp_invalid")
    return result


def _typed_statuses(value):
    if type(value) is dict:
        if "status" in value and value["status"] != "PASS":
            raise ValueError("receipt.measured_failure")
        for key, item in value.items():
            if key in TIME_KEYS:
                _utc(item)
            _typed_statuses(item)
    elif type(value) is list:
        for item in value:
            _typed_statuses(item)


def _group(name, document, source):
    value = document[name]
    expected = source["independent_groups"].get(name)
    checked = source["independent_group_results"].get(name)
    if expected is None or checked is None or checked.get("status") != "PASS":
        raise ValueError("receipt.trusted_source_failed:" + name)
    if value != expected:
        raise ValueError("receipt.observed_field_mismatch:" + name)
    _typed_statuses(value)
    refs = checked.get("evidence_refs")
    if type(refs) is not list or not refs:
        raise ValueError("receipt.trusted_evidence_missing:" + name)
    return refs


def validate_identity(document, source):
    refs = _group("identity", document, source)
    if (
        document["identity"]["installer_agent_id"]
        == document["readback"]["nonauthor_readback_agent_id"]
    ):
        raise ValueError("receipt.independent_readback_required")
    return refs


def validate_deployment(document, source):
    refs = _group("deploy_root", document, source)
    value = document["deploy_root"]
    if (
        value["module_realpath"] != source["module_path"]
        or value["module_sha256"] != source["module_sha256"]
        or value["deploy_worktree_clean"] is not True
    ):
        raise ValueError("ledger.observed_object_drift")
    return refs


def validate_ledger(document, source):
    refs = _group("ledger", document, source)
    value = document["ledger"]
    if (
        value["ledger_path"] != source["chain_path"]
        or value["ledger_sha256"] != sha256(source["chain_raw"])
        or value["ledger_bytes"] != len(source["chain_raw"])
    ):
        raise ValueError("ledger.observed_object_drift")
    return refs


def validate_prefix_proofs(document, source):
    return _group("prefix_proofs", document, source)


def validate_witness(document, source):
    refs = _group("witness", document, source)
    value = document["witness"]
    if (
        value["witness_fields"] != source["witness"]
        or value["witness_path"] != source["witness_path"]
        or value["witness_sha256"] != source["witness_sha256"]
        or value["witness_equals_state"] is not True
    ):
        raise ValueError("ledger.tail_or_high_water_mismatch")
    return refs


def validate_anchor(document, source):
    refs = _group("anchor", document, source)
    value = document["anchor"]
    if value["anchor_bytes_sha256"] != sha256(source["published_anchor_bytes"]):
        raise ValueError("ledger.current_release_unbound_or_stale")
    v1, v2, v3, v4, v6 = [
        value[name]["measured"] for name in ("V1", "V2", "V3", "V4", "V6")
    ]
    comparisons = [
        (v1["L1_artifact_sha256"], sha256(source["published_anchor_bytes"])),
        (v1["L2_sha256"], value["anchor_L2_sha256"]),
        (v1["approved_L2_commit"], value["anchor_L2_commit"]),
        (v1["actual_L2_path"], value["anchor_L2_path"]),
        (
            v1["approved_release_sha256"],
            source["identities"]["approved_release_sha256"],
        ),
        (v1["module_sha256"], source["module_sha256"]),
        (v1["equal"], True),
        (v2["publication_actor_id"], value["anchor_L1_author_id"]),
        (v2["revision"], value["anchor_L1_revision"]),
        (v2["current_release_sha256"], source["identities"]["approved_release_sha256"]),
        (v3["L1_created_at_utc"], value["anchor_L1_created_at"]),
        (v3["installation_at_utc"], document["identity"]["installed_at_utc"]),
        (v3["publication_precedes_installation"], True),
        (v4["ledger_id"], source["anchor"]["ledger_id"]),
        (v4["anchor_sequence"], source["anchor"]["sequence"]),
        (v4["observed_prefix_sequence"], source["anchor"]["sequence"]),
        (v4["tip"], source["anchor"]["tip"]),
        (v4["n_high_water"], source["anchor"]["n_high_water"]),
        (v6["ledger_id"], document["ledger"]["ledger_id"]),
        (v6["genesis_sha256"], document["ledger"]["genesis_sha256"]),
        (v6["current_sequence"], document["ledger"]["sequence"]),
        (v6["anchor_sequence"], source["anchor"]["sequence"]),
        (v6["current_high_water"], document["ledger"]["n_high_water"]),
        (v6["anchor_high_water"], source["anchor"]["n_high_water"]),
        (v6["chain_sha256"], source["chain_sha256"]),
        (v6["witness_sha256"], source["witness_sha256"]),
        (v6["current_release_sha256"], source["identities"]["approved_release_sha256"]),
        (v6["same_branch"], True),
        (v6["witness_equals_state"], True),
        (v6["last_row_event"], "checkpoint"),
    ]
    if any(left != right for left, right in comparisons):
        raise ValueError("receipt.anchor_observation_mismatch")
    created = _utc(value["anchor_L1_created_at"])
    updated = _utc(v2["L1_updated_at_utc"])
    installed = _utc(document["identity"]["installed_at_utc"])
    if not created <= updated <= installed:
        raise ValueError("receipt.timestamp_invalid")
    return refs


def validate_code_checks(document, source):
    refs = _group("code_checks", document, source)
    if any(
        document["code_checks"][key] is not True
        for key in ("open_project_ok", "verify_ok", "is_current_authority")
    ):
        raise ValueError("receipt.measured_failure")
    return refs


def validate_uniqueness(document, source):
    refs = _group("uniqueness", document, source)
    if (
        document["uniqueness"]["roots_found"] != 1
        or document["uniqueness"]["git_tracked"] is not False
    ):
        raise ValueError("receipt.deployment_scope_invalid")
    return refs


def validate_readback(document, source):
    refs = _group("readback", document, source)
    if _utc(document["readback"]["nonauthor_readback_at_utc"]) < _utc(
        document["identity"]["installed_at_utc"]
    ):
        raise ValueError("receipt.timestamp_invalid")
    measured = document["readback"]["nonauthor_readback_result"]["measured"]
    for group in ("deploy_root", "ledger", "witness", "anchor"):
        for key, value in document[group].items():
            if key in measured and measured[key] != value:
                raise ValueError("receipt.readback_object_mismatch")
    return refs


def read_approved_release(document, source):
    refs = _group("approved_release", document, source)
    value = document["approved_release"]
    if (
        value["L1_anchor_file_sha256"] != sha256(source["published_anchor_bytes"])
        or value["L2_path"] != document["anchor"]["anchor_L2_path"]
    ):
        raise ValueError("ledger.current_release_unbound_or_stale")
    # The separately approved release comes from the host's original source,
    # never from this group's canonical digest or a filename sequence search.
    if source.get("release_verified") is not True:
        raise ValueError("ledger.current_release_unbound_or_stale")
    return refs


VALIDATORS = dict(
    identity=validate_identity,
    deploy_root=validate_deployment,
    ledger=validate_ledger,
    prefix_proofs=validate_prefix_proofs,
    witness=validate_witness,
    anchor=validate_anchor,
    code_checks=validate_code_checks,
    uniqueness=validate_uniqueness,
    readback=validate_readback,
    approved_release=read_approved_release,
)


def _result(value, status, refs, reasons, measured=None):
    record = dict(
        status=status,
        evidence_refs=refs,
        source_group_sha256=digest(value),
        measured_sha256=digest(value if measured is None else measured),
        reasons=reasons,
    )
    record["validator_result_sha256"] = digest(record)
    return record


def validate_receipt(raw_receipt, trusted_install_context):
    document = strict_json(raw_receipt)
    if type(document) is not dict or set(document) - set(GROUPS):
        raise ValueError("receipt.schema_version_mismatch")
    if set(document) != set(GROUPS):
        raise ValueError("receipt.required_group_missing")
    if (
        sha256(
            (
                Path(__file__).parent / "reception_contracts/installation.schema.json"
            ).read_bytes()
        )
        != TYPE_SHA
    ):
        raise ValueError("receipt.contract_bytes_mismatch")
    validate(document, "installation.schema.json")
    source = host.observe(trusted_install_context)
    if raw_receipt != source["installation_receipt_bytes"]:
        raise ValueError("receipt.trusted_source_failed:installation")
    groups, reasons = {}, []
    for name in GROUPS:
        try:
            refs = (
                VALIDATORS[name](document, source)
                if name in VALIDATORS
                else _group(name, document, source)
            )
            groups[name] = _result(document[name], "PASS", refs, [])
        except (ValueError, KeyError, TypeError) as exc:
            reason = (
                str(exc)
                if isinstance(exc, ValueError)
                else "receipt.trusted_evidence_missing:" + name
            )
            reasons.append(reason)
            groups[name] = _result(
                document[name], "FAIL", ["sha256:" + sha256(raw_receipt)], [reason]
            )
    coverage = _issue_coverage(source["chain_raw"], source["coverage_ref"], _HOST_TOKEN)
    replay = None
    try:
        from .reception_v2 import preflight_authority

        _, prefix = preflight_authority(trusted_install_context)
        replay = replay_approved_archive(
            source["chain_raw"], trusted_release=coverage, witness=source["witness"]
        )
        current = state(records(source["chain_raw"]), trusted_coverage=coverage)
        verify_ancestor(
            records(source["chain_raw"]), source["anchor"], trusted_coverage=coverage
        )
        for field, expected in (
            ("N", current["N"]),
            ("n_high_water", current["n_high_water"]),
            ("ledger_id", current["ledger_id"]),
            ("genesis_sha256", current["genesis_sha256"]),
            ("sequence", current["sequence"]),
            ("tip", current["tip"]),
            ("snapshot_sha256", current["snapshot_sha256"]),
        ):
            if document["ledger"][field] != expected:
                raise ValueError("ledger.tail_or_high_water_mismatch")
        t1 = document["t1"]
        if (
            t1["book_N"] != replay["book_N"]
            or t1["high_water"] != replay["high_water"]
            or t1["null_n_evaluated_rows"] != replay["raw_unknown_rows"]
        ):
            raise ValueError("receipt.t1_observation_mismatch")
        if t1["null_rows_list_sha256"] != digest(replay["unknown_rows"]):
            raise ValueError("receipt.t1_observation_mismatch")
        if document["v5_mandatory_check"]["formal_reception"] != prefix:
            raise ValueError("ledger.anchor_prefix_input_invalid")
        if document["anchor"]["V5"] != prefix:
            raise ValueError("ledger.anchor_prefix_input_invalid")
        # Installation phase is an existing trusted artifact, never executed
        # here. Readback/formal checks use the very same pure function.
        if document["v5_mandatory_check"]["readback"] != prefix:
            raise ValueError("ledger.anchor_prefix_input_invalid")
    except (ValueError, KeyError, TypeError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, ValueError)
            else "receipt.observed_field_mismatch"
        )
        reasons.append(reason)
        for affected in ("ledger", "anchor", "t1", "v5_mandatory_check"):
            groups[affected] = _result(
                document[affected],
                "FAIL",
                ["sha256:" + sha256(source["chain_raw"])],
                [reason],
            )
    record = dict(
        document=deepcopy(document),
        groups=groups,
        reasons=reasons,
        status="FAIL" if reasons else "PASS",
        receipt_bytes_sha256=sha256(raw_receipt),
        receipt_contract_sha256=TYPE_SHA,
        host_context_binding_sha256=host.context_digest(source),
        run_pin_sha256=digest(
            [host.context_digest(source), source["installation_operation"]]
        ),
    )
    record["validation_result_sha256"] = digest(record)
    result = object.__new__(ReceiptValidation)
    _VALIDATIONS[result] = (trusted_install_context, record, replay, coverage)
    return result


def summarize_validated_receipt(result, *, trusted_install_context):
    if type(result) is not ReceiptValidation or result not in _VALIDATIONS:
        raise ValueError("receipt.trusted_validation_required")
    owner, record, _, _ = _VALIDATIONS[result]
    if owner is not trusted_install_context or record[
        "host_context_binding_sha256"
    ] != host.context_digest(host.observe(owner)):
        raise ValueError("ledger.observed_object_drift")
    summary = {}
    for name, item in record["groups"].items():
        summary[name] = {
            key: deepcopy(value) for key, value in item.items() if key != "reasons"
        }
    summary["anchor"]["checks"] = {}
    for name in ("V1", "V2", "V3", "V4", "V5", "V6"):
        raw = record["document"]["anchor"][name]
        # Source/byte failure of the anchor propagates to each typed child.
        checked = _result(
            raw,
            record["groups"]["anchor"]["status"],
            record["groups"]["anchor"]["evidence_refs"],
            [],
            raw["measured"],
        )
        summary["anchor"]["checks"][name] = {
            key: value for key, value in checked.items() if key != "reasons"
        }
    return deepcopy(record), summary


def verify_installation_readonly(
    *,
    host_context,
    runtime_module_path,
    installation_receipt_bytes,
    published_anchor_bytes,
    acceptance_bytes,
):
    details = dict(
        installation_fields=None,
        installation_fields_reason="receipt.not_observed",
        trusted_validation=None,
        trusted_validation_reason="receipt.not_validated",
        verified_summary=None,
        summary_reason="receipt.not_validated",
        complete_N=None,
        recorded_N=None,
        n_high_water=None,
    )
    report = empty_receipt("N-03.v31.schema.json", details)
    try:
        if any(
            value is None
            for value in (
                installation_receipt_bytes,
                published_anchor_bytes,
                acceptance_bytes,
            )
        ):
            raise ValueError("ledger.trusted_project_installation_required")
        document = strict_json(installation_receipt_bytes)
        if type(document) is not dict or set(document) - set(GROUPS):
            raise ValueError("receipt.schema_version_mismatch")
        if set(document) != set(GROUPS):
            raise ValueError("receipt.required_group_missing")
        validate(document, "installation.schema.json")
        report["observations"]["typed_schema_checks"] += 1
        source = host.observe(host_context)
        if (
            runtime_module_path != source["module_path"]
            or str(Path(runtime_module_path).resolve()) != source["module_path"]
        ):
            raise ValueError("ledger.observed_object_drift")
        if (
            published_anchor_bytes != source["published_anchor_bytes"]
            or acceptance_bytes != source["installation_acceptance_bytes"]
        ):
            raise ValueError("receipt.trusted_source_failed:publication")
        result = validate_receipt(installation_receipt_bytes, host_context)
        report["observations"]["trusted_validation_calls"] += 1
        record, summary = summarize_validated_receipt(
            result, trusted_install_context=host_context
        )
        report["observations"]["summary_adaptations"] += 1
        details.update(
            installation_fields=document,
            installation_fields_reason=None,
            trusted_validation={
                key: record[key]
                for key in (
                    "status",
                    "receipt_bytes_sha256",
                    "receipt_contract_sha256",
                    "host_context_binding_sha256",
                    "run_pin_sha256",
                    "validation_result_sha256",
                    "reasons",
                )
            },
            trusted_validation_reason=None,
            verified_summary=summary,
            summary_reason=None,
        )
        ids = report["input_identities"]
        for key in ids:
            if key in record:
                ids[key] = record[key]
        ids.update(
            module_sha256=source["module_sha256"],
            chain_sha256=source["chain_sha256"],
            witness_sha256=source["witness_sha256"],
            genesis_sha256=source["identities"]["genesis_sha256"],
            approved_release_sha256=source["identities"]["approved_release_sha256"],
            published_anchor_bytes_sha256=sha256(published_anchor_bytes),
            acceptance_bytes_sha256=sha256(acceptance_bytes),
            deployment_id=source["identities"]["host_deployment_id"],
            deployment_commit=source["identities"]["deployment_commit"],
            module_realpath=source["module_path"],
            canonical_chain_realpath=source["chain_path"],
            canonical_witness_realpath=source["witness_path"],
            ledger_id=document["ledger"]["ledger_id"],
            sequence=document["ledger"]["sequence"],
            tip=document["ledger"]["tip"],
        )
        details.update(
            recorded_N=document["ledger"]["N"],
            n_high_water=document["ledger"]["n_high_water"],
        )
        if record["status"] != "PASS":
            report.update(state="REJECTED", reasons=record["reasons"])
        else:
            report.update(accepted=True, state="ACCEPTED_IDENTITY")
        report["binding_sha256"] = (
            digest(
                {
                    key: value
                    for key, value in report.items()
                    if key not in ("binding_sha256", "observations")
                }
            )
            if report["accepted"]
            else None
        )
        validate(report, "N-03.v31.schema.json")
        if report["accepted"]:
            _, _, replay, coverage = _VALIDATIONS[result]
            host._retain_snapshot(host_context, report, replay, coverage)
        return report
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        from .reception_v2 import _finish, _refuse

        report["accepted"] = False
        report["binding_sha256"] = None
        _refuse(
            report,
            str(exc)
            if isinstance(exc, ValueError)
            else "receipt.observed_field_mismatch",
        )
        return _finish(
            report,
            "N-03.v31.schema.json",
            dict(
                installation_fields=None,
                installation_fields_reason=report["reasons"][0],
                trusted_validation=None,
                trusted_validation_reason=report["reasons"][0],
                verified_summary=None,
                summary_reason=report["reasons"][0],
                complete_N=None,
                recorded_N=None,
                n_high_water=None,
            ),
        )

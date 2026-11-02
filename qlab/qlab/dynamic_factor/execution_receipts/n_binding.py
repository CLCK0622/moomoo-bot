"""C12 consumes the sole formal reader; it never declares or writes attempts."""

from copy import deepcopy
import gzip
from pathlib import Path

from .. import authority_host as host
from ..authority_ledger import records
from ..contract import digest, sha256
from ..reception_schema import strict_json
from ..reception_v2 import bind_formal_n
from ..reference_definition_v301 import reference_definitions, _same
from ..reference_profile_v301 import solo_profile
from ..reference_registry_v3 import artifact
from .g14 import PROTOCOL_SHA256, adopted_protocol


DESIGN_RECEIPT_SHA256 = (
    "7543d251170dd423a0b4aec42913486e0b02f0de876cc7809d1105b0b1e9d5d6"
)
ARCHIVE_SHA256 = "d57cd84b6b8578e3cfac14d899fcf311eddab755608d4f573e465f1632c4cd08"
STAGES = {
    "historical_train",
    "independent_reference",
    "candidate_probe",
    "meta_diagnostic",
    "actual_forward_observation",
    "historical_walk_forward",
}


def execution_configurations():
    """Frozen member/profile/fold identities, not executed attempts or N."""
    folds = artifact("fold-bindings.json")["document"]["folds"]
    slots = {}
    for definition in reference_definitions():
        profile = solo_profile(definition)
        for fold in folds:
            body = dict(
                member_id=definition["member_id"],
                fold_id=str(fold["fold_id"]),
                definition_sha256=definition["definition_sha256"],
                solo_profile_sha256=profile["profile_sha256"],
                fold_sha256=digest(fold),
            )
            slots[(body["member_id"], body["fold_id"])] = digest(body)
    return slots


def design_archive_reference():
    """Pinned accepted author archive only; never a current installation/N view."""
    root = Path(__file__).parent / "contracts"
    receipt_raw = (root / "EVO883-G14P1-v27-archive-acceptance-v1.json").read_bytes()
    raw = gzip.decompress((root / "EVO891-B-ledger-v27.jsonl.gz").read_bytes())
    if sha256(receipt_raw) != DESIGN_RECEIPT_SHA256 or sha256(raw) != ARCHIVE_SHA256:
        raise ValueError("execution.design_archive_identity_changed")
    receipt = strict_json(receipt_raw)
    rows = records(raw)
    archive = receipt["accepted_archive"]
    charges = [r for r in rows if r.get("record_type") == "design_count"]
    if (
        len(rows) != archive["lines"]
        or rows[-1]["seq"] != archive["sequence"]
        or digest(rows[-1]) != archive["tip"]
        or [r["seq"] for r in charges]
        != receipt["accounting"]["design_charge_sequences"]
        or receipt["authority_bindings"]["formal_release_sha256"] != PROTOCOL_SHA256
    ):
        raise ValueError("execution.design_archive_binding_changed")
    return dict(
        schema="EVO884.DesignCountArchiveReference/v1",
        value=receipt["engineering_handoff"]["C12_design_count_reference"]["value"],
        archive_sequence=archive["sequence"],
        archive_tip=archive["tip"],
        archive_sha256=ARCHIVE_SHA256,
        acceptance_sha256=DESIGN_RECEIPT_SHA256,
        accepted_scope="AUTHOR_ARCHIVE_DESIGN_COUNT_ONLY",
        complete_N=None,
        gate_N=None,
        formal_projection_consumer_accepted=False,
    )


def stage_budget_mapping(*, stage, producer_id, run_id, permissions_sha256=None):
    """G14.P1.1/P1.3/P1.5 mapping, never a budget exemption or API call.

    The mapping retains both columns. Missing producer-stage/N/budget acceptance
    and L0 stay missing, including for a genuine forward observation.
    """
    protocol = adopted_protocol()
    if stage not in STAGES or any(
        type(v) is not str or not v.strip() for v in (producer_id, run_id)
    ):
        raise ValueError("execution.stage_producer_mapping_required")
    from ..contract import is_sha

    if permissions_sha256 is not None and not is_sha(permissions_sha256):
        raise ValueError("execution.stage_permission_identity_invalid")
    return dict(
        schema="EVO884.StageBudgetMapping/v1",
        stage=stage,
        producer_id=producer_id,
        run_id=run_id,
        protocol_sha256=PROTOCOL_SHA256,
        adopted_clauses=[c["id"] for c in protocol["adopted_clauses"]],
        permissions_sha256=permissions_sha256,
        historical_walk_forward=dict(
            token_usage=None,
            disposition="SEPARATE_ONLY_AFTER_STAGE_ACCEPTANCE_AND_L0"
            if stage == "actual_forward_observation"
            else "ORIGINAL_PRODUCER_AUTHORITY_REQUIRED",
            remaining=None,
            reset_or_reissue=False,
        ),
        prospective_observation=dict(
            new_unseen_samples=None, evidence_anchors_required=True
        ),
        actual_attempt_N=dict(
            contribution=None,
            failure_and_retry_exemption=False,
            daily_automatic_charge=False,
        ),
        stage_acceptance=None,
        budget_mapping_acceptance=None,
        L0=None,
        reasons=["execution.per_producer_stage_N_budget_acceptance_required"],
        G14="UNVERIFIED",
        runtime_consumable=False,
    )


def _attempt_map(source, traces, expected_run_ids):
    if (
        type(traces) is not list
        or type(expected_run_ids) not in (list, tuple)
        or not expected_run_ids
    ):
        raise ValueError("execution.attempt_map_required")
    if any(type(v) is not str or not v.strip() for v in expected_run_ids) or len(
        set(expected_run_ids)
    ) != len(expected_run_ids):
        raise ValueError("execution.attempt_run_binding_invalid")
    actual = {
        r["attempt_id"]: r
        for r in records(source["chain_raw"])
        if r.get("event") == "attempt" and r.get("run_id") in expected_run_ids
    }
    ids = [t.get("attempt_id") for t in traces]
    if len(ids) != len(set(ids)) or set(ids) != set(actual) or not actual:
        raise ValueError("execution.real_failure_or_retry_missing_from_map")
    configurations = execution_configurations()
    bound = []
    fields = {
        "attempt_id",
        "run_id",
        "member_id",
        "fold_id",
        "configuration_sha256",
        "n_contribution",
        "n_evaluated",
        "status",
        "failure_reason",
        "performance_reached",
    }
    for trace in traces:
        if set(trace) != fields:
            raise ValueError("execution.attempt_trace_schema")
        row = actual[trace["attempt_id"]]
        config = configurations.get((trace["member_id"], trace["fold_id"]))
        if (
            config is None
            or trace["configuration_sha256"] != config
            or config not in {e["sha256"] for e in row["evidence"]}
            or type(trace["fold_id"]) is not str
            or trace["run_id"] != row["run_id"]
        ):
            raise ValueError("execution.attempt_configuration_binding_missing")
        for name in ("n_contribution", "n_evaluated"):
            if type(trace[name]) is not type(row[name]) or trace[name] != row[name]:
                raise ValueError("execution.original_contribution_or_unknown_changed")
        if (
            trace["status"] not in {"success", "failed", "nonfinite", "refused"}
            or type(trace["performance_reached"]) not in (bool, type(None))
            or (
                trace["status"] != "success"
                and (
                    type(trace["failure_reason"]) is not str
                    or not trace["failure_reason"].strip()
                )
            )
            or (
                "performance_viewed" in row
                and trace["performance_reached"] is not row["performance_viewed"]
            )
        ):
            raise ValueError("execution.failure_or_reach_evidence_missing")
        bound.append(
            dict(
                trace=deepcopy(trace),
                authority_sequence=row["seq"],
                authority_row_sha256=digest(row),
            )
        )
    return bound


def bind_execution_n(
    *,
    host_context,
    installed_snapshot,
    run_pin,
    traces,
    expected_run_ids,
    stage_mapping,
    request_metrics=None,
):
    """Collect N02 and per-attempt bindings; C09 still owns full P4/P7/B reception.

    A serialized receipt, design count, book high-water or 308 definition slots
    cannot be supplied in place of host objects. No complete N is synthesized.
    Traces are retained as reported observations, not independently certified
    outcomes. Original authority contribution/unknown/reach must match exactly.
    """
    report = dict(
        schema="EVO884.ExecutionNSlot/v1",
        formal_N_slot=None,
        design_count_archive_reference=design_archive_reference(),
        reported_attempts=deepcopy(traces),
        bound_attempts=None,
        stage_mapping=deepcopy(stage_mapping),
        N_reader_receipt=None,
        runtime_consumable=False,
        complete=False,
        remaining_reception=[
            "actual_B_publication",
            "P4_actual_DAG",
            "P7_complete_arm_N",
            "C09_C10_formal_reception",
        ],
        reasons=[],
    )
    try:
        expected = stage_budget_mapping(
            **{
                k: stage_mapping[k]
                for k in ("stage", "producer_id", "run_id", "permissions_sha256")
            }
        )
        if not _same(stage_mapping, expected):
            raise ValueError("execution.stage_budget_mapping_changed")
        received = bind_formal_n(
            host_context=host_context,
            installed_snapshot=installed_snapshot,
            run_pin=run_pin,
            request_metrics={} if request_metrics is None else request_metrics,
            entrypoint="run_train_pipeline",
            arm_tag="EVO883_FACTOR",
        )
        report["N_reader_receipt"] = received
        acceptance = received["details"]["n_acceptance"]
        # Even an incomplete formal projection may have a verified archive.
        if acceptance is None or not acceptance["accepted"]:
            raise ValueError(received["reasons"][0])
        source = host.observe(host_context)
        report["bound_attempts"] = _attempt_map(source, traces, expected_run_ids)
        if not received["accepted"]:
            raise ValueError(received["reasons"][0])
        report["formal_N_slot"] = received["details"]["gate_N"]
        host.check_pin(host_context, run_pin, "EVO883_FACTOR")
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        report["formal_N_slot"] = None
        report["reasons"] = [
            str(exc)
            if isinstance(exc, ValueError)
            else "execution.N_binding_input_invalid"
        ]
    return report

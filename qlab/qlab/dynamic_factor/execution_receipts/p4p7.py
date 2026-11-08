"""Owned P4/P7 sidecar evidence, never authority/source permission by wire.

Pending source identities, complete N and reseal are retained explicitly. The
formal receiver cannot fall back to an unbound diagnostic observation.
"""

from copy import deepcopy
import json
from weakref import WeakKeyDictionary

from ..contract import canonical, digest, sha256
from .input_facts import read_facts
from .reference_result import (
    read_observation,
    read_program,
    read_release as observation_release,
)
from .input_facts import read_release as facts_release
from .input_envelope import release_identity
from .n_binding import bind_execution_n, execution_configurations
from .input_data import require_resealed_evidence


_SIDECARS = WeakKeyDictionary()
_PROOFS = WeakKeyDictionary()


class ExecutionSidecar:
    def __init__(self):
        raise TypeError("reference.owned_P4_P7_required")


def prepare_sidecar(observation, input_read, *, n_binding, reference_proofs=None):
    from ..reference_boundary import run_execution_result

    doc, obs_sha = read_observation(observation)
    program, program_sha = read_program(observation)
    facts, facts_sha = read_facts(input_read)
    context, identity = observation_release(observation)
    if facts_release(input_read)[1] != identity:
        raise ValueError("B.release_context_persistent_identity_mismatch")
    release_identity(
        facts["scope"],
        release_context=context,
        expected_release_identity_bytes=identity,
    )
    if identity is not None:
        from ..reference_noncash import validate_packet

        actor = "reference/" + doc["scope"]["member_id"]
        if type(reference_proofs) is not dict or set(reference_proofs) != {actor}:
            raise ValueError("reference.separate_three_proofs_required")
        validate_packet(
            facts["scope"]["guard"],
            actor,
            reference_proofs[actor],
            scope=facts["scope"],
            release_context=context,
            expected_release_identity_bytes=identity,
        )
    elif reference_proofs is not None:
        raise ValueError("B.release_context_scope_mismatch")
    m, scope = facts["manifest"], doc["scope"]
    # P7 consumes the original sole reader and actual chain attempt map. The
    # wire caller cannot submit a numeric N or a copied acceptance receipt.
    n = bind_execution_n(**n_binding)
    reasons = list(n["reasons"])
    configurations = execution_configurations()
    config = configurations.get((scope["member_id"], scope["fold_id"]))
    matched = [
        r
        for r in n["bound_attempts"] or []
        if r["trace"]["attempt_id"] == scope["attempt_id"]
    ]
    trace = matched[0]["trace"] if len(matched) == 1 else None
    if (
        n_binding["stage_mapping"]["run_id"] != doc["run_id"]
        or n_binding["stage_mapping"]["stage"] != "independent_reference"
        or len(matched) != 1
        or trace["run_id"] != doc["run_id"]
        or trace["member_id"] != scope["member_id"]
        or trace["fold_id"] != scope["fold_id"]
        or trace["configuration_sha256"] != config
        or trace["performance_reached"] is not True
        or trace["status"] != "success"
    ):
        reasons.append("reference.P7_actual_attempt_binding_required")
    worker = run_execution_result(observation, input_read=input_read)
    body = dict(
        schema="EVO884.ReferenceP4P7Sidecar/v1",
        run_id=doc["run_id"],
        book_id=doc["book_id"],
        scope=deepcopy(scope),
        input_manifest_sha256=digest(m),
        input_facts_sha256=facts_sha,
        program_sha256=program_sha,
        observation_sha256=obs_sha,
        P4=dict(
            input_fact_binding=worker["input_fact_binding"],
            actual_DAG=doc["DAG"],
            actual_events=doc["events"],
            worker_role=worker["worker_role"],
            worker_execution_steps=worker["execution_steps"],
            source_proof_sha256=worker["source_proof_sha256"],
            source_acceptance="not_checked",
        ),
        P7=dict(
            reader_receipt=n,
            attempt=deepcopy(matched[0]) if len(matched) == 1 else None,
            configuration_sha256=config,
            complete_N=n["formal_N_slot"] if not reasons else None,
            reasons=reasons,
        ),
        series=dict(
            dates=doc["dates"],
            n_observations=len(doc["dates"]),
            active_series_sha256=digest(doc["returns"]),
            active_series_raw=canonical(doc["returns"]).decode("utf-8"),
            scale_daily=True,
            return_receipt_sha256=digest(doc["return_receipt"]),
            benchmark_sha256=doc["benchmark_sha256"],
        ),
        source_receipt_identities=deepcopy(
            facts["boundary"]["declared_source_receipt_sha256"]
        ),
        source_reception=None,
        permission_reception=None,
        B_catalog_release_sha256=None,
        seal_status="seal_pending",
        execution_verified=False,
        complete=False,
        runtime_consumable=False,
        certifiable=False,
    )
    cap = object.__new__(ExecutionSidecar)
    if identity is not None:
        body.update(
            schema="EVO884.ReferenceP4P7Sidecar/v1-BR1",
            release_context_binding=json.loads(identity),
            B_catalog_release_sha256=context.h_r,
        )
        body["P4"]["release_context_binding"] = json.loads(identity)
        body["P7"]["release_context_binding"] = json.loads(identity)
        body["three_proof_publication_binding"] = dict(
            actor=actor,
            release_context_binding=json.loads(identity),
            packet_sha256=digest(reference_proofs[actor]),
            proofs={
                name: digest(reference_proofs[actor][name])
                for name in ("zero_origin", "no_acquisition", "economic_no_read")
            },
        )
    _SIDECARS[cap] = (observation, input_read, canonical(body), dict(n_binding))
    _PROOFS[cap] = deepcopy(reference_proofs)
    return cap


def read_sidecar(cap):
    if type(cap) is not ExecutionSidecar or cap not in _SIDECARS:
        raise ValueError("reference.owned_P4_P7_required")
    observation, input_read, raw, n_binding = _SIDECARS[cap]
    doc = json.loads(raw)
    _, identity = observation_release(observation)
    if facts_release(input_read)[1] != identity:
        raise ValueError("B.release_context_persistent_identity_mismatch")
    if identity is not None and any(
        value != json.loads(identity)
        for value in (
            doc.get("release_context_binding"),
            doc["P4"].get("release_context_binding"),
            doc["P7"].get("release_context_binding"),
        )
    ):
        raise ValueError("B.release_context_persistent_identity_mismatch")
    if identity is not None:
        actor = "reference/" + doc["scope"]["member_id"]
        proofs = _PROOFS[cap]
        if doc["three_proof_publication_binding"] != dict(
            actor=actor,
            release_context_binding=json.loads(identity),
            packet_sha256=digest(proofs[actor]),
            proofs={
                name: digest(proofs[actor][name])
                for name in ("zero_origin", "no_acquisition", "economic_no_read")
            },
        ):
            raise ValueError("B.release_context_persistent_identity_mismatch")
    if (
        read_observation(observation)[1] != doc["observation_sha256"]
        or read_facts(input_read)[1] != doc["input_facts_sha256"]
    ):
        raise ValueError("reference.sidecar_owned_object_drift")
    if digest(bind_execution_n(**n_binding)) != digest(doc["P7"]["reader_receipt"]):
        raise ValueError("reference.sidecar_N_source_drift")
    return doc, sha256(raw)


def receive_sidecar(cap, *, release_context=None, expected_release_identity_bytes=None):
    """Current formal entry fails closed before any numeric reader/worker.

    A future reseal/source receiver requires its separately approved contract;
    deleting a pending marker from a serialized document cannot enable this.
    """
    report = dict(
        schema="EVO884.ReferenceP4P7Reception/v1",
        complete=False,
        returns=None,
        sr=None,
        formal_N=None,
        sidecar_sha256=None,
        reader_calls=0,
        worker_calls=0,
        accessed_roles=[],
        runtime_consumable=False,
        certifiable=False,
        reasons=[],
    )
    try:
        if type(cap) is ExecutionSidecar and cap in _SIDECARS:
            observation, input_read, raw, _ = _SIDECARS[cap]
            declared = json.loads(raw)
            formal = declared.get("schema") == "EVO884.ReferenceP4P7Sidecar/v1-BR1"
            if not formal and (
                release_context is not None
                or expected_release_identity_bytes is not None
            ):
                raise ValueError("B.release_context_scope_mismatch")
            if formal:
                if release_context is None:
                    raise ValueError("B.release_context_required")
                if expected_release_identity_bytes is None:
                    raise ValueError("B.release_context_persistent_identity_required")
                checked = release_identity(
                    read_facts(input_read)[0]["scope"],
                    release_context=release_context,
                    expected_release_identity_bytes=expected_release_identity_bytes,
                )
                if declared.get("release_context_binding") != json.loads(checked):
                    raise ValueError("B.release_context_persistent_identity_mismatch")
        doc, identity = read_sidecar(cap)
        report["sidecar_sha256"] = identity
        if doc["schema"] == "EVO884.ReferenceP4P7Sidecar/v1-BR1":
            observation, input_read, _, _ = _SIDECARS[cap]
            _, owner_identity = observation_release(observation)
            checked = release_identity(
                read_facts(input_read)[0]["scope"],
                release_context=release_context,
                expected_release_identity_bytes=expected_release_identity_bytes,
            )
            if expected_release_identity_bytes is None or checked != owner_identity:
                raise ValueError("B.release_context_persistent_identity_mismatch")
        elif release_context is not None or expected_release_identity_bytes is not None:
            raise ValueError("B.release_context_scope_mismatch")
        require_resealed_evidence(doc)
        # No B publication or SRC/AUTH reception object exists in this phase.
        # Retain the original refusal rather than a permissive placeholder.
        raise ValueError("reference.runtime_B_release_and_actual_proofs_missing")
    except (ValueError, TypeError, KeyError) as exc:
        report["reasons"] = [str(exc)]
    return report

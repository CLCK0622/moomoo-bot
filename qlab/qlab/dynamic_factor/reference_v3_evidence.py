"""V3 P1-P7 source seals and receipt validators; no performance or N writer."""

from .contract import digest, is_sha, result, unavailable
from .conventions import load_conventions
from .reference_check import static_proof, verify_registry
from .reference_evidence import blob, lineage_sources, timestamp
from .execution_receipts.input_data import require_resealed_evidence
from .reference_registry_v3 import (
    HASHES,
    DISPATCH,
    artifact,
    member_spec,
    registered_request,
)
from .fold_split import shared_views, reference_view, train_dates


def prepare_execution_sidecar(observation, input_read, *, n_binding):
    """Collect owned P4/P7 evidence; this never accepts SRC/AUTH or B."""
    from .execution_receipts.p4p7 import prepare_sidecar

    return prepare_sidecar(observation, input_read, n_binding=n_binding)


def receive_execution_sidecar(sidecar):
    """Formal reception remains fail-closed before any numerical read."""
    from .execution_receipts.p4p7 import receive_sidecar

    return receive_sidecar(sidecar)


def seal_static(scope, sealed_at, policy=None):
    p = policy or load_conventions()
    anchor = artifact("platform-anchor.json")["document"]
    if (
        not timestamp(anchor["created_at"])
        < timestamp(scope["sealed_at"])
        <= timestamp(sealed_at)
        < timestamp(scope["first_performance_at"])
    ):
        raise ValueError("reference.registration_scope_or_source_not_preperformance")
    if scope["scope_sha256"] != digest(
        {k: v for k, v in scope.items() if k != "scope_sha256"}
    ):
        raise ValueError("reference.scope_identity_or_schema_invalid")
    r = registered_request()
    verify_registry(r["registry"], r["manifests"], p, scope["first_performance_at"])
    payload = dict(
        schema="EVO900.reference-static-seal/v3",
        sealed_at=sealed_at,
        registry_sha256=HASHES["predeclared_reference_registry.json"],
        definition_sha256={
            r: HASHES[r + "_reference_manifest.json"] for r in ("candidate", "meta")
        },
        anchor=anchor,
        sources=lineage_sources(),
        static_proof=static_proof(),
        scope_sha256=scope["scope_sha256"],
        quarantine_manifest_sha256=scope["quarantine_manifest_sha256"],
        eligible_set_derivation_sha256=scope["eligible_set_derivation_sha256"],
        eligible_set_manifest_sha256=scope["eligible_set_manifest_sha256"],
        B_derivation_sha256=scope["B_derivation_sha256"],
        B_catalog_release_sha256=None,
        independently_verified=False,
        runtime_consumable=False,
        certifiable=False,
        first_reference_performance_at=None,
    )
    return dict(payload, static_seal_sha256=digest(payload))


def lineage_proof(scope, sealed_at, policy=None):
    p = policy or load_conventions()
    seal = seal_static(scope, sealed_at, p)
    declared = artifact("fold-bindings.json")["document"]["folds"]
    rows = []
    for fold, expected in zip(p.fold_manifest()["folds"], declared):
        views = shared_views(p.calendar, fold, train_days=1260, warmup_days=252)
        train, warmup = reference_view(views, fold, train_dates)
        from .reference_boundary import calendar_sha

        if (
            train is not views.train
            or warmup is not views.warmup
            or any(
                calendar_sha(dates) != expected[key + "_calendar_sha256"]
                for key, dates in (("train", train), ("warmup", warmup))
            )
        ):
            raise ValueError("reference.shared_view_proof_failed")
        rows.append(
            dict(
                fold_id=fold["fold_id"],
                same_object_verified=True,
                train_days=len(train),
                warmup_days=len(warmup),
                train_sha256=calendar_sha(train),
                warmup_sha256=calendar_sha(warmup),
            )
        )
    if len(rows) != 77:
        raise ValueError("reference.fold_count_mismatch")
    statuses = {
        "P1": "已证",
        "P2": "机制已证；实际 B 发布待验",
        "P3": "已证",
        "P4": "仅校验器",
        "P5": "已证",
        "P6": "已证",
        "P7": "仅校验器",
    }
    propositions = [
        dict(row, status=statuses[row["id"]])
        for row in artifact("lineage-plan.json")["document"][
            "static_propositions_to_prove"
        ]
    ]
    return dict(
        schema="EVO900.reference-lineage-proof/v3",
        propositions=propositions,
        static_seal=seal,
        fold_view_receipts=rows,
        dispatch={m: digest(member_spec(m)) for m in sorted(DISPATCH)},
        actual_run_id=None,
        actual_output_sha256=None,
        complete_N=None,
        V=None,
        DSR=None,
        runtime_consumable=False,
        certifiable=False,
        **p.binding,
    )


def runtime_check(request, policy=None):
    p = policy or load_conventions()
    reasons = []
    try:
        allowed = {
            "registry",
            "manifests",
            "first_performance_at",
            "scope",
            "static_seal",
            "sidecars",
            "evidence_files",
            "complete_N_receipt",
        }
        if set(request) - allowed:
            raise ValueError("reference.v3_runtime_schema_or_old_V_forbidden")
        verify_registry(
            request.get("registry"),
            request.get("manifests"),
            p,
            request.get("first_performance_at"),
        )
        scope = request["scope"]
        seal = request["static_seal"]
        if seal_static(scope, seal["sealed_at"], p) != seal:
            raise ValueError("reference.static_seal_mismatch")
        sidecars = request.get("sidecars")
        if type(sidecars) is dict:
            for sidecar in sidecars.values():
                # Direct caller claims are not content-addressed sidecars.
                # Preserve their original B/P4/P7 refusal rather than parsing
                # them as if a trusted artifact had been supplied.
                if is_sha(sidecar):
                    require_resealed_evidence(
                        blob(request.get("evidence_files", {}), sidecar)
                    )
        # No B runtime release has been issued. Static candidate protection and
        # synthetic source/route witnesses cannot satisfy this external gate.
        if scope["B_catalog_release_sha256"] is None:
            raise ValueError("reference.runtime_B_release_and_actual_proofs_missing")
        raise ValueError(
            "reference.P4_actual_DAG_and_P7_complete_factor_projection_required"
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        reasons = [
            str(exc)
            if isinstance(exc, ValueError)
            else "reference.v3_runtime_evidence_missing"
        ]
    return p.bind(
        result(
            "reference_runtime_check",
            request,
            reasons=reasons,
            metrics=dict(
                evidence_valid=False, dsr=None, trials_variance=None, complete_N=None
            ),
            availability={
                k: unavailable(reasons[0]) for k in ("dsr", "trials_variance")
            },
        )
    )


def execution_readiness(
    profile,
    scope,
    manifest,
    *,
    expected,
    host_context,
    installed_snapshot,
    run_pin,
    traces,
    expected_run_ids,
    stage_mapping,
):
    """Read-only pre-execution metadata reception; B stays an external gate.

    P4's execution mechanism is inspected, not an invented actual-run receipt.
    P7 consumes the original host reader, never a caller's numeric N. This
    preflight cannot read a price, start a worker or issue a runtime capability.
    The separate owned diagnostic/result channel never bypasses this gate.
    """
    from .execution_receipts.input_envelope import prepare_input_envelope
    from .execution_receipts.n_binding import bind_execution_n
    from .scope_proof import reference_execution_proof

    report = dict(
        schema="EVO884.ReferenceExecutionReadiness/v1",
        complete=False,
        returns=None,
        sr=None,
        reasons=[],
        reader_calls=0,
        accessed_roles=[],
        worker_calls=0,
        formal_N=None,
        P4_actual_run=None,
        P7_reader_receipt=None,
        execution_proof=None,
        seal_status="seal_pending",
        runtime_consumable=False,
        certifiable=False,
    )
    try:
        preparation = prepare_input_envelope(profile, scope, manifest, **expected)
        if not preparation["prepared"]:
            raise ValueError(preparation["reasons"][0])
        if (
            stage_mapping["stage"] != "independent_reference"
            or stage_mapping["run_id"] != manifest["run_id"]
            or manifest["run_id"] not in expected_run_ids
            or not any(
                t["run_id"] == manifest["run_id"]
                and t["member_id"] == manifest["member_id"]
                for t in traces
            )
        ):
            raise ValueError("reference.reference_run_attempt_binding_required")
        received = bind_execution_n(
            host_context=host_context,
            installed_snapshot=installed_snapshot,
            run_pin=run_pin,
            traces=traces,
            expected_run_ids=expected_run_ids,
            stage_mapping=stage_mapping,
        )
        report["P7_reader_receipt"] = received
        if received["formal_N_slot"] is None or received["reasons"]:
            raise ValueError(
                received["reasons"][0]
                if received["reasons"]
                else "reference.complete_N_required"
            )
        report["formal_N"] = received["formal_N_slot"]
        report["execution_proof"] = reference_execution_proof(load_conventions())
        # A non-null release already fails the unchanged original scope
        # validator. Do not synthesize an anchor or a replacement guard.
        raise ValueError("reference.runtime_B_release_and_actual_proofs_missing")
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        report["reasons"] = [
            str(exc)
            if isinstance(exc, ValueError)
            else "reference.execution_reception_invalid"
        ]
    return report

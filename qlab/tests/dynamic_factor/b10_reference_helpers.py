"""Counterfactual full wire protocol, real compiler and isolated subprocess."""

from copy import deepcopy

from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.fold_split import shared_views
from qlab.dynamic_factor.reference_boundary import calendar_sha, run_isolated
from qlab.dynamic_factor.reference_compile_v3 import compile_inputs, compile_panel
from qlab.dynamic_factor.reference_registry_v3 import DISPATCH, member_spec
from v3_reference_helpers import protocol_scope, reference_proofs


def wire_fixture(root):
    p = load_conventions()
    fold = p.fold_manifest()["folds"][0]
    view = shared_views(p.calendar, fold, train_days=1260, warmup_days=252)
    scope = protocol_scope(view.train, view.warmup)
    files = compile_inputs(scope, lambda *a: 100, lambda *a: 100, p)
    root.mkdir()
    bindings = {}
    for role, data in files.items():
        raw = canonical(data)
        (root / (role + ".json")).write_bytes(raw)
        bindings[role] = dict(file=role + ".json", sha256=sha256(raw))
    return dict(
        view=dict(
            train=list(view.train),
            warmup=list(view.warmup),
            receipt=dict(
                fold_id=fold["fold_id"],
                train_days=1260,
                warmup_days=252,
                shared_object_verified=True,
                train_calendar_sha256=calendar_sha(view.train),
                warmup_calendar_sha256=calendar_sha(view.warmup),
            ),
        ),
        inputs=bindings,
        profile_binding={
            k: p.binding[k]
            for k in (
                "conventions_version",
                "conventions_sha256",
                "prereg_sha256",
                "common_profile_sha256",
            )
        },
        dispatch={m: member_spec(m) for m in sorted(DISPATCH)},
        sealed_scope=scope,
        reference_proofs=reference_proofs(scope["guard"]),
    )


def resign_scope(request):
    scope = request["sealed_scope"]
    scope["scope_sha256"] = digest(
        {k: v for k, v in scope.items() if k != "scope_sha256"}
    )


def exercise(root, request, *, with_proofs=False):
    calls = []

    def reader(date, symbol):
        calls.append((date, symbol))
        return 100

    before = deepcopy(request)
    try:
        kwargs = (
            {"reference_proofs": request["reference_proofs"]} if with_proofs else {}
        )
        compile_panel(request["sealed_scope"], reader, **kwargs)
        host = dict(
            complete=True,
            reader_calls=len(calls),
            accessed_roles=["panel"],
            reason=None,
        )
    except ValueError as exc:
        host = dict(
            complete=False, reader_calls=len(calls), accessed_roles=[], reason=str(exc)
        )
    worker = run_isolated(root, request)
    assert request == before
    return dict(host=host, worker=worker)


TIME_CASES = {
    "clean": ({}, True),
    "timezone-equivalent": ({"sealed_at": "2026-10-30T02:00:00-10:00"}, True),
    "cross-day-equivalent": ({"sealed_at": "2026-10-31T00:00:00+12:00"}, True),
    "performance-equivalent": (
        {"first_performance_at": "2026-11-01T02:00:00+02:00"},
        True,
    ),
    "audit-late-offset": (
        {
            "sealed_at": "2026-10-30T12:00:00-12:00",
            "first_performance_at": "2026-10-30T18:00:00Z",
        },
        False,
    ),
    "late-offset-same-performance": ({"sealed_at": "2026-10-31T18:00:00-12:00"}, False),
    "scope-before-guard": ({"sealed_at": "2026-10-30T11:54:00Z"}, False),
    "seal-at-performance": ({"sealed_at": "2026-11-01T00:00:00Z"}, False),
    "offset-at-performance": ({"sealed_at": "2026-10-31T12:00:00-12:00"}, False),
    "foreign-performance": ({"first_performance_at": "2026-11-02T00:00:00Z"}, False),
    "foreign-mode": ({"mode": "forward"}, False),
    "naive-time": ({"sealed_at": "2026-10-30T12:00:00"}, False),
    "malformed-time": ({"sealed_at": "not-a-time"}, False),
}

PROOF_CASES = {
    "clean": None,
    "state-bool-initialization": ("state.initialization_count", True),
    "state-negative-age": ("state.age", {"QQQ": -1}),
    "state-rights-type": ("state.rights", []),
    "foreign-inner-guard": ("noncash_guard_manifest_sha256", digest("foreign guard")),
    "inner-consumer": ("consumer", "cash_valuation"),
    "inner-actor": ("actor", "reference/MREF-F4-L020"),
    "inner-registry": ("registry_sha256", digest("foreign registry")),
    "inner-source": ("source_sha256", digest("foreign source")),
    "inner-origin": ("zero_origin_receipt_sha256", digest("foreign origin")),
    "inner-mechanism": ("guard_mechanism_sha256", digest("foreign mechanism")),
    "inner-reader": ("reader_source_sha256", digest("foreign reader")),
    "inner-value-digest": ("numeric_values_sha256", digest("foreign values")),
}


def mutate_proof(request, case):
    change = PROOF_CASES[case]
    if change is None:
        return
    actor = sorted(request["reference_proofs"])[0]
    packet = request["reference_proofs"][actor]
    if change[0].startswith("state."):
        origin = packet["zero_origin"]
        old_sha = origin["zero_origin_receipt_sha256"]
        origin["initial_state"][change[0].split(".", 1)[1]] = change[1]
        new_sha = digest(
            {k: v for k, v in origin.items() if k != "zero_origin_receipt_sha256"}
        )

        def relink(value):
            if isinstance(value, dict):
                return {k: relink(v) for k, v in value.items()}
            if isinstance(value, list):
                return [relink(v) for v in value]
            return new_sha if value == old_sha else value

        def resign(value):
            if isinstance(value, dict):
                for child in value.values():
                    resign(child)
                keys = [
                    k
                    for k in (
                        "reference_proof_packet_sha256",
                        "economic_no_read_receipt_sha256",
                        "no_acquisition_receipt_sha256",
                        "reference_numeric_receipt_sha256",
                        "numeric_read_receipt_sha256",
                        "route_receipt_sha256",
                    )
                    if k in value
                ]
                if "initial_state" in value:
                    keys.append("zero_origin_receipt_sha256")
                for key in keys:
                    value[key] = digest({k: v for k, v in value.items() if k != key})
            elif isinstance(value, list):
                for child in value:
                    resign(child)

        packet = relink(packet)
        resign(packet)
        request["reference_proofs"][actor] = packet
        return
    read = packet["economic_no_read"]["reads"]["score"]
    inner = read["numeric_receipt"]
    inner[change[0]] = change[1]
    # Re-sign every owned digest; rejection must be semantic, not a bad SHA.
    for document, key in (
        (inner, "numeric_read_receipt_sha256"),
        (read, "reference_numeric_receipt_sha256"),
        (packet["economic_no_read"], "economic_no_read_receipt_sha256"),
        (packet, "reference_proof_packet_sha256"),
    ):
        document[key] = digest({k: v for k, v in document.items() if k != key})

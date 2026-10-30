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
    "foreign-performance": ({"first_performance_at": "2026-11-02T00:00:00Z"}, False),
    "foreign-mode": ({"mode": "forward"}, False),
    "naive-time": ({"sealed_at": "2026-10-30T12:00:00"}, False),
    "malformed-time": ({"sealed_at": "not-a-time"}, False),
}

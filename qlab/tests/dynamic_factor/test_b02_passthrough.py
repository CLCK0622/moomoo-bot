"""Hard AST boundary and private formal guard controls; no runtime approval."""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from qlab.dynamic_factor import b_release_context as b, noncash_v3 as n
from qlab.dynamic_factor.contract import digest
from test_b01_release_context import private_host_source as private_host_source, request
from v3_test_helpers import synthetic_guard


NINE = {
    "allowed_symbols",
    "assert_consumer_symbols",
    "guarded_value",
    "economic_values",
    "economic_read_receipt",
    "zero_origin",
    "acquisition_check",
    "no_dependency_receipt",
    "forward_event",
}
KEYS = {"release_context", "expected_release_identity_bytes"}


def test_nine_functions_fifteen_edges_passthrough_AST_and_original_bytes():
    path = Path(n.__file__)
    repo = path.parents[3]
    original = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "show",
            "f827776c7a4b3f270ad87367191b06314a7f3c28:qlab/qlab/dynamic_factor/noncash_v3.py",
        ]
    )  # Missing Git object is a failure, never a skip.
    assert (
        hashlib.sha256(original).hexdigest()
        == "08301f9d7a5ad5bdcd2fcaae8422dec9896e18b59d197a9c183e81057e106744"
    )
    old_text, new_text = original.decode(), path.read_text()
    old = {
        f.name: f for f in ast.parse(old_text).body if isinstance(f, ast.FunctionDef)
    }
    new = {
        f.name: f for f in ast.parse(new_text).body if isinstance(f, ast.FunctionDef)
    }
    assert set(new) == set(old)
    total_edges = 0
    for name in old:
        if name not in NINE | {"seal_guard", "checked_guard"}:
            assert ast.get_source_segment(
                new_text, new[name]
            ) == ast.get_source_segment(old_text, old[name])
        if name not in NINE:
            continue
        fn = deepcopy(new[name])
        pairs = list(zip(fn.args.kwonlyargs, fn.args.kw_defaults))
        added = [(a, default) for a, default in pairs if a.arg in KEYS]
        assert {a.arg for a, _ in added} == KEYS
        assert all(
            isinstance(default, ast.Constant) and default.value is None
            for _, default in added
        )
        kept = [(a, default) for a, default in pairs if a.arg not in KEYS]
        fn.args.kwonlyargs = [a for a, _ in kept]
        fn.args.kw_defaults = [default for _, default in kept]
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            extra = [k for k in call.keywords if k.arg in KEYS]
            if extra:
                assert isinstance(call.func, ast.Name) and call.func.id in NINE | {
                    "seal_guard",
                    "checked_guard",
                }
                assert {k.arg for k in extra} == KEYS
                assert all(
                    isinstance(k.value, ast.Name) and k.value.id == k.arg for k in extra
                )
                call.keywords = [k for k in call.keywords if k.arg not in KEYS]
                total_edges += 1
        assert ast.dump(fn, include_attributes=False) == ast.dump(
            old[name], include_attributes=False
        ), name
    assert total_edges == 15


def formal(private_host_source):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    raw = b.check_release_context(context, policy=policy, request=req)
    guard = n.seal_guard(
        req, policy, release_context=context, expected_release_identity_bytes=raw
    )
    return policy, context, raw, guard


def test_formal_guard_fixed_A_and_hash_domains(private_host_source):
    policy, context, raw, guard = formal(private_host_source)
    assert guard["schema"] == "EVO883.BRuntimeGuard/v1"
    assert guard["catalog_sha256"] == guard["accepted_catalog_sha256"] == context.h_c
    assert guard["B_catalog_release_sha256"] == context.h_r
    assert guard["B_release_acceptance_sha256"] == context.h_a
    assert guard["B_derivation_sha256"] == context.h_d
    assert guard["catalog_registration_only"] is False
    assert guard["fact_counts"] == {"known_unclosed": 3, "UNKNOWN": 61}
    assert guard["B"] == ["ADP", "APD", "CMCSA", "CMI"]
    assert guard["runtime_consumable"] is guard["certifiable"] is False
    assert guard["seal_status"] == "seal_pending"
    kwargs = dict(release_context=context, expected_release_identity_bytes=raw)
    assert n.checked_guard(guard, policy, **kwargs) == guard
    assert n.seal_guard(guard["request"], policy, **kwargs) == guard
    assert n.allowed_symbols(guard, policy, **kwargs) == {"QQQ"}
    changed = deepcopy(guard)
    changed["accepted_catalog_sha256"] = context.h_r
    with pytest.raises(ValueError, match="^B.guard_identity_mismatch$"):
        n.checked_guard(changed, policy, **kwargs)


@pytest.mark.parametrize("which", ["context", "bytes", "both"])
def test_diagnostic_surplus_rejected_before_checker(
    private_host_source, monkeypatch, which
):
    policy, context, raw, _ = formal(private_host_source)
    guard = synthetic_guard(policy)
    calls = []

    def checker(*args, **kwargs):
        calls.append(1)
        raise AssertionError("diagnostic must not reach common checker")

    monkeypatch.setattr(n, "check_release_context", checker)
    kwargs = dict(
        release_context=context if which in {"context", "both"} else None,
        expected_release_identity_bytes=raw if which in {"bytes", "both"} else None,
    )
    for invoke in [
        lambda: n.checked_guard(guard, policy, **kwargs),
        lambda: n.seal_guard(guard["request"], policy, **kwargs),
    ]:
        with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
            invoke()
    assert calls == []


@pytest.mark.parametrize("name", sorted(NINE))
def test_all_nine_formal_missing_context_stop_before_reader(private_host_source, name):
    policy, context, raw, guard = formal(private_host_source)
    actor = n.actor_ids(policy)[0]
    state = dict(
        inventory={s: 0 for s in policy.profile["universe"] + ["QQQ"]},
        cash=15000,
        nav=15000,
        age={},
        origin={},
        rights={},
        receivables={},
        pending_orders=[],
        unknown_components=[],
        initialization_count=1,
    )
    origin = n.zero_origin(
        guard,
        actor,
        state,
        "a" * 64,
        policy,
        release_context=context,
        expected_release_identity_bytes=raw,
    )
    reads = []

    def reader(symbol):
        reads.append(symbol)
        return 1

    calls = {
        "allowed_symbols": lambda: n.allowed_symbols(guard, policy),
        "assert_consumer_symbols": lambda: n.assert_consumer_symbols(
            guard, "score", ["QQQ"], policy
        ),
        "guarded_value": lambda: n.guarded_value(
            guard, "score", "QQQ", reader, policy=policy
        ),
        "economic_values": lambda: n.economic_values(
            guard, "score", ["QQQ"], reader, policy=policy
        ),
        "economic_read_receipt": lambda: n.economic_read_receipt(
            guard, "score", ["QQQ"], reader, actor=actor, origin=origin, policy=policy
        ),
        "zero_origin": lambda: n.zero_origin(guard, actor, state, "a" * 64, policy),
        "acquisition_check": lambda: n.acquisition_check(
            guard, actor, origin, state, state, "buy", policy
        ),
        "no_dependency_receipt": lambda: n.no_dependency_receipt(
            guard, actor, origin, {}, policy
        ),
        "forward_event": lambda: n.forward_event(
            guard,
            "ADP",
            [],
            "2026-11-07T20:00:00Z",
            "2026-11-09T21:00:00Z",
            state,
            state_source_sha256="a" * 64,
            event_source_sha256="b" * 64,
            other_gates={},
            policy=policy,
        ),
    }
    before = deepcopy(state)
    with pytest.raises(ValueError, match="^B.release_context_required$"):
        calls[name]()
    assert reads == [] and state == before


def test_same_context_reaches_original_owned_numeric_boundaries(private_host_source):
    policy, context, raw, guard = formal(private_host_source)
    kwargs = dict(release_context=context, expected_release_identity_bytes=raw)
    actor = n.actor_ids(policy)[0]
    state = dict(
        inventory={s: 0 for s in policy.profile["universe"] + ["QQQ"]},
        cash=15000,
        nav=15000,
        age={},
        origin={},
        rights={},
        receivables={},
        pending_orders=[],
        unknown_components=[],
        initialization_count=1,
    )
    origin = n.zero_origin(guard, actor, state, "a" * 64, policy, **kwargs)
    calls = []

    def reader(symbol):
        calls.append(symbol)
        return 1

    receipts = {}
    for consumer in sorted(n.CONSUMERS):
        values, receipt = n.economic_read_receipt(
            guard,
            consumer,
            ["QQQ"],
            reader,
            actor=actor,
            origin=origin,
            policy=policy,
            **kwargs,
        )
        assert values == {"QQQ": 1}
        assert (
            receipt["noncash_guard_manifest_sha256"]
            == guard["noncash_guard_manifest_sha256"]
        )
        receipts[consumer] = receipt
    assert calls == ["QQQ"] * 6
    out = n.no_dependency_receipt(guard, actor, origin, receipts, policy, **kwargs)
    assert out["runtime_consumable"] is False
    assert (
        n.acquisition_check(
            guard, actor, origin, state, state, "buy", policy, **kwargs
        )["execution_verified"]
        is False
    )
    with pytest.raises(
        ValueError, match="^B.parent_unknown_or_child_numeric_read_forbidden$"
    ):
        n.guarded_value(guard, "score", "CMI", reader, policy=policy, **kwargs)
    assert calls == ["QQQ"] * 6
    before = deepcopy(state)
    # The fixed R cannot authorize a new event/catalog; original event logic is
    # preserved and the same context refuses the changed catalog before reads.
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        n.forward_event(
            guard,
            "ADP",
            [],
            "2026-11-07T20:00:00Z",
            "2026-11-09T21:00:00Z",
            state,
            state_source_sha256="a" * 64,
            event_source_sha256="b" * 64,
            other_gates={},
            policy=policy,
            **kwargs,
        )
    assert state == before


def test_compiler_release_aliases_and_unknown_stop_without_numeric_read(
    private_host_source,
):
    from qlab.dynamic_factor.isolation import seal_manifest
    from qlab.dynamic_factor.reference_compile_v3 import seal_scope, compile_panel
    from qlab.dynamic_factor.reference_v3_scope import validate_scope

    source, policy = private_host_source
    source["run_time_binding_bytes"] = b._canonical(
        dict(
            mode="history",
            first_performance_at="2026-11-10T14:30:00Z",
            signal_close=None,
        )
    )
    context = b.receive_release_context(policy=policy)
    req = request(context)
    req["mode"] = "history"
    req.pop("signal_close")
    raw = b.check_release_context(context, policy=policy, request=req)
    kwargs = dict(release_context=context, expected_release_identity_bytes=raw)
    guard = n.seal_guard(req, policy, **kwargs)
    sealed = seal_manifest(
        dict(
            role="external_reference_roles",
            records=[],
            mode=req["mode"],
            sealed_at=req["sealed_at"],
            first_performance_at=req["first_performance_at"],
            noncash_guard_manifest=guard,
        ),
        policy,
        **kwargs,
    )
    scope = seal_scope(
        sealed, [policy.calendar[300]], [policy.calendar[299]], policy, **kwargs
    )
    assert scope["schema"] == "EVO900.reference-shared-scope/v3-BR1"
    assert scope["B_catalog_release_sha256"] == context.h_r != context.h_c
    assert scope["B_release_acceptance_sha256"] == context.h_a
    assert scope["B_derivation_sha256"] == context.h_d
    day = scope["days"][policy.calendar[300]]
    assert day["B_catalog_sha256"] == context.h_c
    assert day["synthetic_catalog_sha256"] is None
    assert day["quantity_state"] == "UNKNOWN"
    reads = []

    def reader(date, symbol):
        reads.append((date, symbol))
        return 1

    with pytest.raises(
        ValueError,
        match="^reference.quantity_unknown_or_insufficient_no_QQQ_substitution",
    ):
        compile_panel(scope, reader, policy, **kwargs)
    assert reads == []
    view = dict(train=scope["train"], warmup=scope["warmup"])
    binding = {
        k: policy.binding[k]
        for k in (
            "conventions_version",
            "conventions_sha256",
            "prereg_sha256",
            "common_profile_sha256",
        )
    }
    with pytest.raises(ValueError, match="^B.release_context_required$"):
        validate_scope(scope, view, binding, policy=policy)
    bad = deepcopy(scope)
    bad["B_catalog_release_sha256"] = context.h_c
    bad["scope_sha256"] = digest({k: v for k, v in bad.items() if k != "scope_sha256"})
    with pytest.raises(ValueError, match="^B.release_context_release_mismatch$"):
        validate_scope(bad, view, binding, policy=policy, **kwargs)


@pytest.mark.parametrize("member", ["F1-L020", "CREF-F1-L020", "META_POLICY_V3"])
def test_owned_histories_rebuild_same_context_without_diagnostic_fallback(
    private_host_source, member
):
    from qlab.dynamic_factor.execution_risk_history import RiskHistory
    from test_execution_risk_history import history

    source, policy = private_host_source
    source["run_time_binding_bytes"] = b._canonical(
        dict(
            mode="history",
            first_performance_at="2026-11-10T14:30:00Z",
            signal_close=None,
        )
    )
    context = b.receive_release_context(policy=policy)
    req = request(context)
    req["mode"] = "history"
    req.pop("signal_close")
    raw = b.check_release_context(context, policy=policy, request=req)
    guard = n.seal_guard(
        req, policy, release_context=context, expected_release_identity_bytes=raw
    )
    _, args = history(member)
    args.update(
        guard=guard, release_context=context, expected_release_identity_bytes=raw
    )
    owned = RiskHistory(**args)
    snap = owned.snapshot()
    wire = json.loads(owned.export_bytes())
    assert wire["schema"] == "EVO884.RiskHistory/v1-BR1"
    assert wire["release_context_binding"]["identity"]["h_a"] == context.h_a
    assert snap["release_context_binding"]["identity"]["h_a"] == context.h_a
    assert owned._release_context is context
    assert owned._release_identity_bytes == raw


def test_diagnostic_None_None_guard_paths_match_fixed_main(tmp_path):
    from qlab.dynamic_factor.catalog_v21 import guard_request
    from qlab.dynamic_factor.conventions import load_conventions

    root = Path(n.__file__).parents[3]
    original = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "show",
            "f827776:qlab/qlab/dynamic_factor/noncash_v3.py",
        ]
    )
    path = tmp_path / "main_noncash.py"
    path.write_bytes(original)
    spec = importlib.util.spec_from_file_location(
        "qlab.dynamic_factor.TEST_ONLY_main_noncash", path
    )
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    policy = load_conventions()
    synthetic = synthetic_guard(policy)
    requests = [
        deepcopy(synthetic["request"]),
        guard_request(
            sealed_at="2026-11-07T20:00:00Z",
            first_performance_at="2026-11-10T14:30:00Z",
            policy=policy,
        ),
    ]
    for change in ["missing", "extra", "mode", "late", "status"]:
        req = deepcopy(synthetic["request"])
        if change == "missing":
            req.pop("mode")
        elif change == "extra":
            req["extra"] = 1
        elif change == "mode":
            req["mode"] = "not-a-mode"
        elif change == "late":
            req["sealed_at"] = req["first_performance_at"]
        else:
            req["catalog"]["entries"][0]["status"] = "not-a-status"
        requests.append(req)

    def observed(fn, arg):
        try:
            return ("result", fn(arg, policy))
        except (ValueError, KeyError, TypeError) as exc:
            return (type(exc).__name__, str(exc))

    for req in requests:
        assert observed(old.seal_guard, req) == observed(
            lambda req, p: n.seal_guard(
                req, p, release_context=None, expected_release_identity_bytes=None
            ),
            req,
        )
    bad = deepcopy(synthetic)
    bad["noncash_guard_manifest_sha256"] = "f" * 64
    for guard in [None, {}, synthetic, bad]:
        assert observed(old.checked_guard, guard) == observed(
            lambda g, p: n.checked_guard(
                g, p, release_context=None, expected_release_identity_bytes=None
            ),
            guard,
        )

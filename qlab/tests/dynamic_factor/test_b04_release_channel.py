"""Independent TEST_ONLY host inputs; no actual A, source grant or strategy."""

from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qlab.dynamic_factor import b_release_context as b, noncash_v3 as n
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_receipts.input_envelope import release_identity
from qlab.dynamic_factor.reference_producer_v3 import worker_release
from qlab.dynamic_factor.reference_v3_evidence import receive_execution_sidecar
from test_b01_release_context import private_host_source as private_host_source, request
from v3_test_helpers import synthetic_guard


def bound(source):
    _, policy = source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    raw = b.check_release_context(context, policy=policy, request=req)
    guard = n.seal_guard(
        req, policy, release_context=context, expected_release_identity_bytes=raw
    )
    return policy, context, raw, guard


def preflight(context, raw, guard):
    return dict(scope={"guard": guard}, identity_bytes=raw, a_raw=context.a_raw)


def test_T04_real_checker_host_and_local_reload_keep_same_A_without_permission(
    private_host_source,
):
    policy, context, raw, guard = bound(private_host_source)
    expected = preflight(context, raw, guard)
    assert worker_release(expected, release_context=context) == (context, raw)
    local, binding = worker_release(expected)
    assert type(local) is b.ReleaseContext and local is not context
    assert local.a_raw == context.a_raw and binding == raw
    assert (
        release_identity(
            {"guard": guard},
            policy=policy,
            release_context=context,
            expected_release_identity_bytes=raw,
        )
        == raw
    )
    # JSON identity cannot be substituted for owned P4/P7, N or SRC/AUTH.
    report = receive_execution_sidecar(
        json.loads(raw), release_context=context, expected_release_identity_bytes=raw
    )
    assert report["reasons"] == ["reference.owned_P4_P7_required"]
    assert report["reader_calls"] == report["worker_calls"] == 0
    assert report["returns"] is report["formal_N"] is None
    assert not report["complete"] and not report["runtime_consumable"]


@pytest.mark.parametrize(
    "field",
    [
        "accepted_catalog_sha256",
        "B_catalog_release_sha256",
        "B_release_acceptance_sha256",
        "B_derivation_sha256",
    ],
)
@pytest.mark.parametrize("value", [None, "f" * 64])
def test_T01_T02_T03_half_or_forged_release_binding_stops_before_worker(
    private_host_source, field, value
):
    _, context, raw, guard = bound(private_host_source)
    changed = deepcopy(guard)
    changed[field] = value
    changed["noncash_guard_manifest_sha256"] = digest(
        {k: v for k, v in changed.items() if k != "noncash_guard_manifest_sha256"}
    )
    with pytest.raises(ValueError):
        worker_release(preflight(context, raw, changed), release_context=context)
    assert guard[field] is not None


@pytest.mark.parametrize("which", ["context", "bytes", "both"])
def test_T09_diagnostic_surplus_cannot_change_classification(
    private_host_source, which
):
    policy, context, raw, _ = bound(private_host_source)
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        release_identity(
            {"guard": synthetic_guard(policy)},
            policy=policy,
            release_context=context if which != "bytes" else None,
            expected_release_identity_bytes=raw if which != "context" else None,
        )


@pytest.mark.parametrize("which", ["A", "identity", "scope"])
def test_T14_T17_mixed_host_worker_binding_is_rejected(private_host_source, which):
    _, context, raw, guard = bound(private_host_source)
    expected = preflight(context, raw, deepcopy(guard))
    if which == "A":
        expected["a_raw"] += b" "
    elif which == "identity":
        value = json.loads(raw)
        value["identity"]["h_a"] = "f" * 64
        expected["identity_bytes"] = b._canonical(
            dict(value, identity_sha256=digest(value["identity"]))
        )
    else:
        expected["scope"]["guard"]["request"]["mode"] = "history"
    with pytest.raises(ValueError):
        worker_release(expected, release_context=context)
    assert context.a_raw == preflight(context, raw, guard)["a_raw"]


def test_T04_fresh_isolated_process_cannot_mint_context_from_host_bytes(
    private_host_source,
):
    _, context, raw, guard = bound(private_host_source)
    expected = preflight(context, raw, guard)
    # The original child host adapter remains unavailable. Raw A is not a cap.
    program = (
        "import json;from qlab.dynamic_factor.reference_producer_v3 import worker_release;"
        "from qlab.dynamic_factor.b_release_context import ReleaseContext;"
        "expected=" + repr(expected) + ";"
        "\ntry: worker_release(expected)\nexcept ValueError as e: print(str(e))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parents[2],
    )
    assert result.stdout.strip() == "B.release_context_trust_binding_missing"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "attack",
    ["T05-CMI_CLEAR", "T06-all_UNKNOWN_B", "T07-S1_overclaim", "T08-extra_input"],
)
def test_original_input_identity_prevents_scope_overclaim(private_host_source, attack):
    source, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    req = request(context)
    before = context.a_raw
    if attack == "T08-extra_input":
        source["original_inputs"]["UNACCEPTED.json"] = b"{}"
    else:
        token = (
            "CMI-guard"
            if attack.startswith("T05")
            else "catalog-v21.csv"
            if attack.startswith("T06")
            else "S1-BRKB"
        )
        name = next(name for name in source["original_inputs"] if token in name)
        original = source["original_inputs"][name]
        if attack.startswith("T05"):
            changed = original.replace(b"UNKNOWN", b"CLEAR")
        elif attack.startswith("T06"):
            changed = original.replace(b"UNKNOWN", b"B")
        else:
            value = json.loads(original)
            value["TEST_ONLY_illegal_source_independence_and_rights_claim"] = True
            changed = b._canonical(value)
        assert changed != original
        source["original_inputs"][name] = changed
    with pytest.raises(ValueError):
        b.check_release_context(context, policy=policy, request=req)
    assert context.a_raw == before


@pytest.mark.parametrize(
    "attack",
    [
        "T15-signal_before_acceptance",
        "T16-first_performance_before_publication",
        "T17-mode",
        "T17-U64",
    ],
)
def test_accepted_release_does_not_change_time_mode_or_universe(
    private_host_source, attack
):
    policy, context, raw, guard = bound(private_host_source)
    req = deepcopy(guard["request"])
    if attack.startswith("T15"):
        req["signal_close"] = "2026-11-01T00:00:00Z"
    elif attack.startswith("T16"):
        req["first_performance_at"] = "2026-11-01T00:00:00Z"
    elif attack == "T17-mode":
        req["mode"] = "history"
    else:
        req["catalog"]["universe"].reverse()
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        b.check_release_context(
            context, policy=policy, request=req, expected_release_identity_bytes=raw
        )


@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"identity_sha256":"self"}', b' {"x":1}']
)
def test_T18_strict_binding_encoding_has_no_self_hash_or_noncanonical_escape(
    private_host_source, raw
):
    _, context, _, guard = bound(private_host_source)
    with pytest.raises(ValueError):
        worker_release(preflight(context, raw, guard), release_context=context)


@pytest.mark.parametrize("position", range(4))
def test_T14_reference_three_proofs_keep_actor_ownership_with_same_release(
    private_host_source, position
):
    from qlab.dynamic_factor import reference_noncash as r
    from v3_test_helpers import synthetic_zero_state

    policy, context, raw, guard = bound(private_host_source)
    kwargs = dict(release_context=context, expected_release_identity_bytes=raw)
    actor = r.actors()[position]
    state = synthetic_zero_state(guard)
    initial = r.origin(
        guard, actor, state, digest(["TEST_ONLY", actor]), policy, **kwargs
    )
    routes = {
        route: r.acquisition(
            guard, actor, initial, state, state, route, policy, **kwargs
        )
        for route in sorted(n.ROUTES)
    }
    reads, calls = {}, []

    def reader(symbol):
        calls.append(symbol)
        return 1

    for role in sorted(n.CONSUMERS):
        reads[role] = r.numeric_read(
            guard, actor, role, ["QQQ"], reader, policy, initial=initial, **kwargs
        )[1]
    packet = r.packet(guard, actor, initial, routes, reads, policy, **kwargs)
    assert r.validate_packet(guard, actor, packet, policy, **kwargs) == packet
    assert len(calls) == 6 and packet["runtime_consumable"] is False
    for other in set(r.actors()) - {actor}:
        with pytest.raises(ValueError):
            r.validate_packet(guard, other, packet, policy, **kwargs)
    assert len(calls) == 6


@pytest.mark.parametrize(
    "which", ["diagnostic_context", "diagnostic_bytes", "formal_missing_context"]
)
def test_TEST_ONLY_sidecar_cross_mode_refuses_before_N_read_or_worker(
    monkeypatch, which
):
    from qlab.dynamic_factor.execution_receipts import p4p7

    # Deliberately incomplete private test state, never a positive owned receipt.
    cap = object.__new__(p4p7.ExecutionSidecar)
    schema = "EVO884.ReferenceP4P7Sidecar/v1" + (
        "-BR1" if which.startswith("formal") else ""
    )
    p4p7._SIDECARS[cap] = (None, None, json.dumps(dict(schema=schema)).encode(), {})
    calls = []

    def forbidden_N(*args, **kwargs):
        calls.append("N")
        raise AssertionError("classification must precede N")

    monkeypatch.setattr(p4p7, "bind_execution_n", forbidden_N)
    out = p4p7.receive_sidecar(
        cap,
        release_context=object() if which == "diagnostic_context" else None,
        expected_release_identity_bytes=b"{}" if which == "diagnostic_bytes" else None,
    )
    assert out["reasons"] == [
        "B.release_context_required"
        if which.startswith("formal")
        else "B.release_context_scope_mismatch"
    ]
    assert calls == [] and out["reader_calls"] == out["worker_calls"] == 0


def test_T04_actual_R_UNKNOWN_refuses_preparation_before_bootstrap(private_host_source):
    from qlab.dynamic_factor.isolation import seal_manifest
    from qlab.dynamic_factor.reference_compile_v3 import seal_scope
    from qlab.dynamic_factor.reference_definition_v301 import member_definition
    from qlab.dynamic_factor.reference_profile_v301 import solo_profile
    from qlab.dynamic_factor.execution_receipts.input_run import prepare
    from test_execution_input_envelope import packet

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
    profile = solo_profile(
        member_definition(
            "CREF-F1-L020", execution_role="independent_candidate_reference"
        )
    )
    _, _, manifest, expected = packet()
    manifest.update(
        member_id="CREF-F1-L020",
        scope_sha256=scope["scope_sha256"],
        profile_sha256=profile["profile_sha256"],
    )
    for slot in manifest["inputs"].values():
        slot["requested_dates"] = scope["train"]
    expected.update(
        expected_manifest_sha256=digest(manifest),
        expected_scope_sha256=scope["scope_sha256"],
        expected_profile_sha256=profile["profile_sha256"],
    )

    class TEST_ONLY_ForbiddenRepr(str):
        def __repr__(self):
            raise AssertionError("custom repr must not reach child bootstrap")

    scope["first_performance_at"] = TEST_ONLY_ForbiddenRepr(
        scope["first_performance_at"]
    )
    # Actual adopted R remains UNKNOWN. Do not manufacture a positive pool.
    with pytest.raises(
        ValueError,
        match="^reference.quantity_unknown_or_insufficient_no_QQQ_substitution",
    ):
        prepare(profile, scope, manifest, policy=policy, **expected, **kwargs)
    assert (
        context.a_raw
        == b.receive_release_context(policy=policy, a_raw=context.a_raw).a_raw
    )

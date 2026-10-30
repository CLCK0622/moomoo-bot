"""Separate reference-book witnesses; never accept strategy/monitor receipts."""

from copy import deepcopy

from .contract import code_sha, digest, is_sha
from .conventions import load_conventions
from .noncash_v3 import (
    checked_guard,
    zero_exposure,
    economic_read_receipt,
    assert_consumer_symbols,
    CONSUMERS,
    ROUTES,
)
from .reference_registry_v3 import DISPATCH, HASHES


def actors():
    return tuple("reference/" + m for m in sorted(DISPATCH))


def state_schema(state):
    fields = {
        "inventory",
        "cash",
        "nav",
        "age",
        "origin",
        "rights",
        "receivables",
        "pending_orders",
        "unknown_components",
        "initialization_count",
    }
    if not isinstance(state, dict) or set(state) - fields - {
        "date",
        "retired_ids",
        "exit_intents",
    }:
        raise ValueError("reference.zero_state_schema_invalid")
    for name, kind in (("inventory", int), ("age", int), ("origin", str)):
        value = state.get(name)
        if value is not None and (
            not isinstance(value, dict)
            or any(
                not isinstance(k, str) or type(v) is not kind for k, v in value.items()
            )
        ):
            raise ValueError("reference.zero_state_schema_invalid")


def origin(guard, actor, state, source_sha256, policy=None):
    p = policy or load_conventions()
    checked_guard(guard, p)
    if actor not in actors() or not is_sha(source_sha256):
        raise ValueError("reference.separate_actor_and_source_required")
    state_schema(state)
    zero_exposure(state, guard, initial=True)
    if (
        type(state.get("initialization_count")) is not int
        or state["initialization_count"] != 1
    ):
        raise ValueError("reference.zero_origin_no_capital_restart")
    payload = dict(
        actor=actor,
        producer_kind="reference",
        registry_sha256=HASHES["predeclared_reference_registry.json"],
        initial_state=deepcopy(state),
        source_sha256=source_sha256,
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        mechanism_sha256=code_sha(origin),
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(payload, zero_origin_receipt_sha256=digest(payload))


def acquisition(guard, actor, initial, before, after, route, policy=None):
    p = policy or load_conventions()
    if (
        route not in ROUTES
        or actor not in actors()
        or origin(guard, actor, initial["initial_state"], initial["source_sha256"], p)
        != initial
    ):
        raise ValueError("reference.separate_zero_origin_or_route_required")
    state_schema(before)
    state_schema(after)
    zero_exposure(before, guard)
    zero_exposure(after, guard)
    if (
        before.get("initialization_count") != 1
        or after.get("initialization_count") != 1
    ):
        raise ValueError("reference.capital_restart_forbidden")
    payload = dict(
        actor=actor,
        route=route,
        before=deepcopy(before),
        after=deepcopy(after),
        zero_origin_receipt_sha256=initial["zero_origin_receipt_sha256"],
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        mechanism_sha256=code_sha(acquisition),
        q_B_zero=True,
        runtime_consumable=False,
    )
    return dict(payload, route_receipt_sha256=digest(payload))


def numeric_read(guard, actor, consumer, symbols, reader, policy=None):
    p = policy or load_conventions()
    if actor not in actors() or consumer not in CONSUMERS:
        raise ValueError("reference.separate_actor_and_consumer_required")
    # The common B guard dominates the injected numeric callback. Each actor
    # gets its own invocation and receipt, even when the submitted values match.
    values, inner = economic_read_receipt(guard, consumer, symbols, reader, policy=p)
    payload = dict(
        actor=actor,
        producer_kind="reference",
        consumer=consumer,
        numeric_receipt=inner,
        mechanism_sha256=code_sha(numeric_read),
        registry_sha256=HASHES["predeclared_reference_registry.json"],
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        runtime_consumable=False,
    )
    return values, dict(payload, reference_numeric_receipt_sha256=digest(payload))


def packet(guard, actor, initial, routes, reads, policy=None):
    p = policy or load_conventions()
    if not isinstance(initial, dict) or not {"initial_state", "source_sha256"}.issubset(
        initial
    ):
        raise ValueError("reference.separate_zero_origin_required")
    if (
        actor not in actors()
        or origin(guard, actor, initial["initial_state"], initial["source_sha256"], p)
        != initial
    ):
        raise ValueError("reference.separate_zero_origin_required")
    if set(routes) != ROUTES or set(reads) != CONSUMERS:
        raise ValueError("reference.all_routes_and_numeric_consumers_required")
    for route, receipt in routes.items():
        if (
            not isinstance(receipt, dict)
            or not {"before", "after", "actor"}.issubset(receipt)
            or receipt["actor"] != actor
        ):
            raise ValueError("reference.acquisition_induction_receipt_mismatch")
        if (
            acquisition(
                guard, actor, initial, receipt["before"], receipt["after"], route, p
            )
            != receipt
        ):
            raise ValueError("reference.acquisition_induction_receipt_mismatch")
    for consumer, receipt in reads.items():
        if (
            not isinstance(receipt, dict)
            or set(receipt)
            != {
                "actor",
                "producer_kind",
                "consumer",
                "numeric_receipt",
                "mechanism_sha256",
                "registry_sha256",
                "noncash_guard_manifest_sha256",
                "runtime_consumable",
                "reference_numeric_receipt_sha256",
            }
            or receipt.get("actor") != actor
            or receipt.get("producer_kind") != "reference"
            or receipt.get("consumer") != consumer
            or receipt.get("mechanism_sha256") != code_sha(numeric_read)
            or receipt.get("registry_sha256")
            != HASHES["predeclared_reference_registry.json"]
            or receipt.get("noncash_guard_manifest_sha256")
            != guard["noncash_guard_manifest_sha256"]
            or receipt.get("reference_numeric_receipt_sha256")
            != digest(
                {
                    k: v
                    for k, v in receipt.items()
                    if k != "reference_numeric_receipt_sha256"
                }
            )
        ):
            raise ValueError("reference.separate_numeric_boundary_receipt_required")
        inner = receipt["numeric_receipt"]
        if (
            not inner.get("symbols")
            or inner.get("input_kind") != "numeric_values"
            or inner.get("read_boundary_exercised") is not True
            or inner.get("consumer") != consumer
            or inner.get("noncash_guard_manifest_sha256")
            != guard["noncash_guard_manifest_sha256"]
            or inner.get("numeric_read_receipt_sha256")
            != digest(
                {k: v for k, v in inner.items() if k != "numeric_read_receipt_sha256"}
            )
        ):
            raise ValueError("reference.metadata_hash_is_not_numeric_no_read_proof")
        assert_consumer_symbols(guard, consumer, inner["symbols"], p)
    no_acquisition = dict(
        actor=actor,
        routes=deepcopy(routes),
        zero_origin_receipt_sha256=initial["zero_origin_receipt_sha256"],
        all_acquisition_routes_checked=True,
        mechanism_sha256=code_sha(acquisition),
    )
    no_acquisition["no_acquisition_receipt_sha256"] = digest(no_acquisition)
    no_read = dict(
        actor=actor,
        reads=deepcopy(reads),
        zero_origin_receipt_sha256=initial["zero_origin_receipt_sha256"],
        no_acquisition_receipt_sha256=no_acquisition["no_acquisition_receipt_sha256"],
        mechanism_sha256=code_sha(numeric_read),
        child_price=None,
        child_price_status="CONDITIONAL_NOT_APPLICABLE_MECHANISM_ONLY",
        runtime_consumable=False,
    )
    no_read["economic_no_read_receipt_sha256"] = digest(no_read)
    payload = dict(
        actor=actor,
        producer_kind="reference",
        registry_sha256=HASHES["predeclared_reference_registry.json"],
        noncash_guard_manifest_sha256=guard["noncash_guard_manifest_sha256"],
        zero_origin=deepcopy(initial),
        no_acquisition=no_acquisition,
        economic_no_read=no_read,
        scope="trusted owned boundaries and complete supplied simulator states; not a real account or independent runtime attestation",
        independently_verified=False,
        real_runtime_proven=False,
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(payload, reference_proof_packet_sha256=digest(payload))


def validate_packet(guard, actor, supplied, policy=None):
    expected = packet(
        guard,
        actor,
        supplied["zero_origin"],
        supplied["no_acquisition"]["routes"],
        supplied["economic_no_read"]["reads"],
        policy,
    )
    if expected != supplied:
        raise ValueError("reference.proof_packet_identity_mismatch")
    return expected


def static_proof():
    """Check owned guard dominance, separately from actual-state attestation."""
    import ast
    import inspect

    from .reference_compile_v3 import compile_panel
    from .reference_producer_v3 import prepare

    def calls(function, name):
        tree = ast.parse(inspect.getsource(function))
        return sorted(
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == name
        )

    if (
        len(calls(acquisition, "zero_exposure")) != 2
        or not calls(origin, "zero_exposure")
        or not calls(numeric_read, "economic_read_receipt")
        or calls(numeric_read, "reader")
    ):
        raise ValueError("reference.static_noncash_guard_missing")
    reads = calls(prepare, "read_inputs")
    if not reads or any(
        not calls(prepare, name) or min(calls(prepare, name)) >= min(reads)
        for name in ("validate_scope", "check_reference_packets")
    ):
        raise ValueError("reference.static_worker_read_precedes_guard")
    if min(calls(compile_panel, "validate_scope")) >= min(
        calls(compile_panel, "reader")
    ) or min(calls(compile_panel, "assert_consumer_symbols")) >= min(
        calls(compile_panel, "reader")
    ):
        raise ValueError("reference.static_compiler_read_precedes_guard")
    payload = dict(
        schema="EVO900.reference-noncash-static-proof/v3",
        actors=list(actors()),
        acquisition_routes=sorted(ROUTES),
        economic_consumers=sorted(CONSUMERS),
        source_functions_sha256={
            fn.__name__: code_sha(fn)
            for fn in (
                origin,
                acquisition,
                numeric_read,
                packet,
                prepare,
                compile_panel,
            )
        },
        registry_sha256=HASHES["predeclared_reference_registry.json"],
        B_catalog_release_sha256=None,
        reference_mechanism_proof_completed=True,
        real_runtime_proven=False,
        scope="owned trusted callbacks and supplied complete simulator states; no actual account or independent runtime attestation",
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(payload, reference_static_proof_sha256=digest(payload))

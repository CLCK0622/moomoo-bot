from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.isolation import (
    eligible_day,
    score_day,
    seal_manifest,
    verify_rank_receipt,
)
from qlab.dynamic_factor.noncash_v3 import (
    ACCEPTED_CATALOG_SHA256,
    CONSUMERS,
    ROUTES,
    acquisition_check,
    actor_ids,
    checked_guard,
    economic_values,
    economic_read_receipt,
    forward_event,
    guarded_value,
    no_dependency_receipt,
    seal_guard,
    zero_origin,
)
from test_v2_isolation import synthetic_manifest, synthetic_scores
from v3_test_helpers import synthetic_guard, synthetic_zero_state


P = load_conventions()
ACTORS = actor_ids(P)
PARENT = P.profile["universe"][
    2
]  # Counterfactual ABNB, deliberately not the known three.


def setup_actor(actor=ACTORS[0]):
    guard = synthetic_guard(blocked=[PARENT])
    state = synthetic_zero_state(guard)
    origin = zero_origin(guard, actor, state, digest("SYNTHETIC_STATE_" + actor))
    return guard, state, origin


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(ROUTES))
def test_each_strategy_and_virtual_monitor_rejects_each_B_acquisition_route(
    actor, route
):
    guard, before, origin = setup_actor(actor)
    after = deepcopy(before)
    after["inventory"][PARENT] = 1
    after["age"][PARENT] = 0
    after["origin"][PARENT] = "SYNTHETIC_" + route
    if route == "pending_order":
        after["pending_orders"] = [dict(symbol=PARENT, side="BUY", quantity=1)]
    unchanged = deepcopy(before)
    with pytest.raises(ValueError, match="B.nonzero_initial_or_guarded_exposure"):
        acquisition_check(guard, actor, origin, before, after, route)
    assert before == unchanged


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_route_checks_also_reject_child_inventory_without_price_reads(route):
    guard, before, origin = setup_actor()
    after = deepcopy(before)
    child = guard["children"][0]
    after["inventory"][child] = 1
    after["age"][child] = 0
    after["origin"][child] = "SYNTHETIC"
    with pytest.raises(ValueError):
        acquisition_check(guard, ACTORS[0], origin, before, after, route)


@pytest.mark.parametrize("actor", ACTORS)
def test_actor_zero_origin_and_no_read_receipts_are_separate_and_conditional(actor):
    guard, before, origin = setup_actor(actor)
    for route in ROUTES:
        out = acquisition_check(guard, actor, origin, before, before, route)
        assert out["q_B_zero"] and out["state"] == before
        assert (
            not out["execution_verified"]
            and out["original_execution_gates_still_required"]
        )
    called = []
    reads = {}
    for consumer in CONSUMERS:
        values, numeric_receipt = economic_read_receipt(
            guard,
            consumer,
            ["AAPL", "QQQ"],
            lambda s: called.append((consumer, s)) or 100,
        )
        assert values == {"AAPL": 100, "QQQ": 100}
        reads[consumer] = numeric_receipt
    proof = no_dependency_receipt(guard, actor, origin, reads)
    assert proof["actor"] == actor
    assert len(called) == 2 * len(CONSUMERS)
    assert proof["child_price"] is None and not proof["runtime_consumable"]
    assert not proof["independently_verified"]
    other = next(a for a in ACTORS if a != actor)
    with pytest.raises(ValueError, match="actor_mismatch"):
        acquisition_check(guard, other, origin, before, before, "buy")


@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
@pytest.mark.parametrize("kind", ["parent", "child", "unknown"])
def test_every_economic_consumer_rejects_before_numeric_reader_call(consumer, kind):
    guard = synthetic_guard(blocked=[PARENT], unknown=["APD"])
    symbol = (
        PARENT
        if kind == "parent"
        else guard["children"][0]
        if kind == "child"
        else "APD"
    )

    def poison(_):
        raise AssertionError("forbidden numeric read occurred")

    with pytest.raises(ValueError, match="numeric_read_forbidden"):
        guarded_value(guard, consumer, symbol, poison)


def test_metadata_or_hash_only_read_list_cannot_close_consumer_proof():
    guard, _, origin = setup_actor()
    with pytest.raises(ValueError, match="all_economic_consumers_required"):
        no_dependency_receipt(
            guard, ACTORS[0], origin, {"audit_sha256": [digest("metadata")]}
        )
    reads = {k: [] for k in CONSUMERS}
    with pytest.raises(
        ValueError, match="numeric_boundary_receipt_required_not_catalog_hash"
    ):
        no_dependency_receipt(guard, ACTORS[0], origin, reads)


@pytest.mark.parametrize(
    "field",
    [
        "held",
        "child",
        "rights",
        "receivables",
        "pending",
        "unknown",
        "missing_inventory",
        "missing_pending",
    ],
)
def test_initial_exposure_or_missing_zero_evidence_cannot_become_not_applicable(field):
    guard, state, _ = setup_actor()
    symbol = guard["children"][0] if field == "child" else PARENT
    if field in {"held", "child"}:
        state["inventory"][symbol] = 1
        state["age"][symbol] = 30
        state["origin"][symbol] = "LEGACY"
    if field in {"rights", "receivables"}:
        state[field] = {"LEGACY": 1}
    if field == "pending":
        state["pending_orders"] = [dict(symbol=PARENT, side="BUY", quantity=1)]
    if field == "unknown":
        state["unknown_components"] = ["LEGACY_ENTITLEMENT"]
    if field == "missing_inventory":
        del state["inventory"][PARENT]
    if field == "missing_pending":
        del state["pending_orders"]
    before = deepcopy(state)
    with pytest.raises(ValueError):
        zero_origin(guard, ACTORS[0], state, digest("SYNTHETIC_LEGACY"))
    assert state == before


def test_whole_domain_B_applies_before_gate_values_and_all16_scores():
    blocked = P.profile["universe"][:3]
    request = synthetic_manifest(verified=64)
    request["noncash_guard_manifest"] = synthetic_guard(blocked=blocked)
    for r in request["records"]:
        if r["symbol"] in blocked:
            r.update(state="QUARANTINED", gates_by_date={})
    sealed = seal_manifest(request)
    seen = []
    receipt = score_day(
        sealed,
        P.calendar[600],
        lambda names: seen.append(names) or synthetic_scores(P, names),
    )
    assert len(seen[0]) == 61 and not set(seen[0]).intersection(blocked)
    assert (
        receipt["day"]["verified_count"] == 61
    )  # Synthetic evidence, never real capacity certification.
    assert receipt["day"]["B_catalog_sha256"] is None
    for row in receipt["ranks"].values():
        assert all(row[s] is None for s in blocked)
    request["records"][0]["gates_by_date"] = {"not_a_date": {"raw_price": object()}}
    with pytest.raises(ValueError, match="guarded_numeric_evidence_forbidden"):
        seal_manifest(request)


def test_pending_catalog_membership_is_UNKNOWN_not_a_verified_complement():
    request = synthetic_manifest(verified=64)
    request["noncash_guard_manifest"] = synthetic_guard(
        unknown=P.profile["universe"][49:]
    )
    for r in request["records"][49:]:
        r.update(state="UNKNOWN", gates_by_date={})
    day = eligible_day(seal_manifest(request), P.calendar[600])
    assert day["verified_count"] == 49 and day["upper_bound"] == 64
    assert day["quantity_state"] == "UNKNOWN" and not day["new_tilt_allowed"]


def test_all61_general_UNKNOWN_never_count_or_enter_admission_or_become_B():
    blocked = P.profile["universe"][:3]
    unknown = P.profile["universe"][3:]
    guard = synthetic_guard(blocked=blocked, unknown=unknown)
    assert guard["B"] == sorted(blocked) and guard["unknown"] == sorted(unknown)
    request = synthetic_manifest(verified=64)
    request["noncash_guard_manifest"] = guard
    for row in request["records"]:
        row.update(
            state="QUARANTINED" if row["symbol"] in blocked else "UNKNOWN",
            gates_by_date={},
        )
    sealed = seal_manifest(request)

    def forbidden(names):
        raise AssertionError("UNKNOWN reached scoring/admission")

    receipt = score_day(sealed, P.calendar[600], forbidden)
    day = receipt["day"]
    assert day["verified_count"] == 0 and day["upper_bound"] == 61
    assert day["quantity_state"] == "UNKNOWN" and receipt["ranks"] is None
    forged = deepcopy(receipt)
    forged["day"].update(
        verified_count=61, quantity_state="VERIFIED_GE50", eligible=unknown
    )
    forged["rank_receipt_sha256"] = digest(
        {k: v for k, v in forged.items() if k != "rank_receipt_sha256"}
    )
    with pytest.raises(ValueError, match="ranked_quantity_or_mask_mismatch"):
        verify_rank_receipt(forged, sealed)
    with pytest.raises(ValueError, match="numeric_read_forbidden"):
        guarded_value(guard, "score", unknown[0], forbidden)


def test_bulk_UNKNOWN_reclassification_cannot_infer_an_all_QQQ_portfolio():
    guard = synthetic_guard(unknown=P.profile["universe"])
    assert not guard["B"] and len(guard["unknown"]) == 64
    forged = deepcopy(guard)
    forged["B"] = forged["unknown"]
    forged["unknown"] = []
    with pytest.raises(ValueError, match="identity_mismatch"):
        checked_guard(forged)
    request = deepcopy(guard["request"])
    for row in request["catalog"]["entries"]:
        row["status"] = "UNRESOLVED"
    with pytest.raises(ValueError, match="catalog_evidence_invalid"):
        seal_guard(request)


def test_credible_pending_event_is_guarded_without_promoting_its_underlying_fact():
    guard = synthetic_guard(unknown=[PARENT])
    request = deepcopy(guard["request"])
    row = next(r for r in request["catalog"]["entries"] if r["symbol"] == PARENT)
    row.update(
        credible_event_evidence=True, event_or_candidate_id="SYNTHETIC_PENDING_EVENT"
    )
    updated = seal_guard(request)
    assert PARENT in updated["B"] and PARENT not in updated["unknown"]
    assert row["status"] == "UNKNOWN"


def test_real_catalog_remains_null_and_cannot_be_substituted_by_synthetic_names():
    guard = synthetic_guard(blocked=P.profile["universe"][:3])
    request = deepcopy(guard["request"])
    request["synthetic"] = False
    assert ACCEPTED_CATALOG_SHA256 is None
    with pytest.raises(ValueError, match="catalog_not_accepted"):
        seal_guard(request)
    request["catalog"]["entries"] = request["catalog"]["entries"][:3]
    with pytest.raises(ValueError, match="full_U64_catalog_required"):
        seal_guard(request)


def test_zero_origin_and_migration_cannot_reset_capital_or_leave_pending_B_buys():
    guard, before, origin = setup_actor()
    after = deepcopy(before)
    after["initialization_count"] = 2
    with pytest.raises(ValueError, match="capital_restart_forbidden"):
        acquisition_check(guard, ACTORS[0], origin, before, after, "migration")
    after = deepcopy(before)
    after["pending_orders"] = [dict(symbol=PARENT, side="BUY", quantity=1)]
    with pytest.raises(ValueError, match="guarded_pending_buy"):
        acquisition_check(guard, ACTORS[0], origin, before, after, "pending_order")


@pytest.mark.parametrize(
    "attack", ["after_performance", "tamper", "future_evidence", "outcome_selector"]
)
def test_B_sealing_cannot_follow_outcomes_or_forged_timing(attack):
    guard = synthetic_guard()
    if attack == "tamper":
        changed = deepcopy(guard)
        changed["B"] = [PARENT]
        with pytest.raises(ValueError):
            checked_guard(changed)
        return
    request = deepcopy(guard["request"])
    if attack == "after_performance":
        request["sealed_at"] = request["first_performance_at"]
    if attack == "future_evidence":
        request["catalog"]["entries"][0]["received_at"] = "2027-01-01T00:00:00Z"
    if attack == "outcome_selector":
        request["best_returns"] = [PARENT]
    with pytest.raises(ValueError):
        seal_guard(request)


GATES = dict.fromkeys(
    ["quantity", "M", "valuation", "cash", "fees", "age", "gain", "admission"], True
)


@pytest.mark.parametrize(
    "kind", ["held", "rights", "receivables", "pending", "unknown", "no_evidence"]
)
def test_forward_new_event_adds_B_and_stops_with_exact_state_preservation(kind):
    guard = synthetic_guard(mode="forward")
    state = synthetic_zero_state(guard)
    child = "SYNTHETIC_NEW_CHILD"
    state["inventory"][child] = 0
    if kind == "held":
        state["inventory"][PARENT] = 1
        state["age"][PARENT] = 30
        state["origin"][PARENT] = "LEGACY"
    if kind in {"rights", "receivables"}:
        state[kind] = {"LEGACY": 1}
    if kind == "pending":
        state["pending_orders"] = [dict(symbol=PARENT, side="BUY", quantity=1)]
    if kind == "unknown":
        state["unknown_components"] = ["NECESSARY_STATE"]
    original = deepcopy(state)
    out = forward_event(
        guard,
        PARENT,
        [child],
        "2026-10-04T00:00:00Z",
        "2026-10-04T01:00:00Z",
        state,
        event_source_sha256=digest("SYNTHETIC_RECEIVED_EVENT"),
        state_source_sha256=None
        if kind == "no_evidence"
        else digest("SYNTHETIC_SOURCE"),
        other_gates=GATES,
    )
    m = out["metrics"]
    assert not out["ok"] and m["R2_stop"] and PARENT in m["guard"]["B"]
    assert m["retained_state"] == original == state
    assert (
        m["next_state"] is None
        and not m["automatic_liquidation"]
        and not m["restart_clock"]
    )


def test_forward_proven_flat_continues_other_paths_when_all_original_gates_hold():
    guard = synthetic_guard(mode="forward")
    state = synthetic_zero_state(guard)
    child = "SYNTHETIC_NEW_CHILD"
    state["inventory"][child] = 0
    out = forward_event(
        guard,
        PARENT,
        [child],
        "2026-10-04T00:00:00Z",
        "2026-10-04T01:00:00Z",
        state,
        event_source_sha256=digest("SYNTHETIC_RECEIVED_EVENT"),
        state_source_sha256=digest("SYNTHETIC_SOURCE"),
        other_gates=GATES,
    )
    assert (
        out["ok"]
        and out["metrics"]["continue_other_paths"]
        and not out["metrics"]["R2_stop"]
    )
    assert out["metrics"]["retained_state"] == state
    bad = forward_event(
        guard,
        PARENT,
        [child],
        "2026-10-04T00:00:00Z",
        "2026-10-04T01:00:00Z",
        state,
        event_source_sha256=digest("SYNTHETIC_RECEIVED_EVENT"),
        state_source_sha256=digest("SYNTHETIC_SOURCE"),
        other_gates=dict(GATES, fees=False),
    )
    assert bad["metrics"]["R2_stop"]


def test_forward_no_future_information_or_automatic_restart():
    guard = synthetic_guard(mode="forward")
    state = synthetic_zero_state(guard)
    with pytest.raises(ValueError):
        forward_event(
            guard,
            PARENT,
            [],
            "2026-10-05T00:00:00Z",
            "2026-10-04T01:00:00Z",
            state,
            event_source_sha256=digest("SYNTHETIC_RECEIVED_EVENT"),
            state_source_sha256=digest("SYNTHETIC_SOURCE"),
            other_gates=GATES,
        )
    out = forward_event(
        guard,
        PARENT,
        [],
        "2026-10-04T00:00:00Z",
        "2026-10-04T01:00:00Z",
        state,
        event_source_sha256=digest("SYNTHETIC_RECEIVED_EVENT"),
        state_source_sha256=digest("SYNTHETIC_SOURCE"),
        other_gates=GATES,
        previously_stopped=True,
    )
    assert out["metrics"]["R2_stop"] and out["reasons"] == ["B.no_automatic_restart"]

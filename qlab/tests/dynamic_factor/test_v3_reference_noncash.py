from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.noncash_v3 import CONSUMERS, ROUTES, zero_origin, actor_ids
from qlab.dynamic_factor.reference_noncash import (
    actors,
    origin,
    acquisition,
    numeric_read,
    packet,
    validate_packet,
)
from qlab.dynamic_factor.reference_v3_scope import check_reference_packets
from v3_reference_helpers import unit_scope, reference_proofs, synthetic_numeric_reader
from v3_test_helpers import synthetic_zero_state

ACTORS = actors()


@pytest.fixture(scope="module")
def source():
    scope = unit_scope(real=True)
    return scope, reference_proofs(scope["guard"])


@pytest.mark.parametrize("actor", ACTORS)
def test_reference_actor_has_its_own_three_distinct_nonruntime_witnesses(source, actor):
    scope, proofs = source
    p = proofs[actor]
    assert validate_packet(scope["guard"], actor, p) == p
    assert p["producer_kind"] == "reference" and p["zero_origin"]["actor"] == actor
    assert set(p["no_acquisition"]["routes"]) == ROUTES
    assert set(p["economic_no_read"]["reads"]) == CONSUMERS
    assert all(
        r["actor"] == actor and r["numeric_receipt"]["read_boundary_exercised"]
        for r in p["economic_no_read"]["reads"].values()
    )
    assert p["real_runtime_proven"] is False and p["runtime_consumable"] is False
    assert p["economic_no_read"]["child_price"] is None
    assert (
        len(
            {
                p["zero_origin"]["zero_origin_receipt_sha256"],
                p["no_acquisition"]["no_acquisition_receipt_sha256"],
                p["economic_no_read"]["economic_no_read_receipt_sha256"],
            }
        )
        == 3
    )


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(ROUTES))
def test_every_reference_actor_rejects_every_B_acquisition_route(source, actor, route):
    scope, proofs = source
    g = scope["guard"]
    initial = proofs[actor]["zero_origin"]
    before = deepcopy(initial["initial_state"])
    after = deepcopy(before)
    symbol = next(
        e["symbol"]
        for e in g["request"]["catalog"]["entries"]
        if e["guard_pending_review"]
    )
    after["inventory"][symbol] = 1
    after["age"][symbol] = 0
    after["origin"][symbol] = "SYNTHETIC_ROUTE"
    raw = deepcopy(after)
    with pytest.raises(ValueError, match="exposure"):
        acquisition(g, actor, initial, before, after, route)
    assert after == raw


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_every_reference_economic_boundary_rejects_B_before_numeric_callback(
    source, actor, consumer
):
    scope, _ = source
    g = scope["guard"]
    called = []
    for symbol in g["B"] + ["UNDECLARED_CHILD"]:
        with pytest.raises(ValueError, match="numeric_read_forbidden"):
            numeric_read(g, actor, consumer, [symbol], lambda s: called.append(s) or 99)
    assert not called


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("kind", ["strategy", "virtual_monitor"])
def test_strategy_or_other_reference_receipts_cannot_substitute(source, actor, kind):
    scope, proofs = source
    g = scope["guard"]
    state = synthetic_zero_state(g)
    other_actor = next(a for a in actor_ids() if a.startswith(kind + "/"))
    foreign = zero_origin(g, other_actor, state, digest("SYNTHETIC_FACTOR"))
    with pytest.raises(ValueError, match="separate_zero_origin"):
        packet(
            g,
            actor,
            foreign,
            proofs[actor]["no_acquisition"]["routes"],
            proofs[actor]["economic_no_read"]["reads"],
        )
    other = next(a for a in ACTORS if a != actor)
    with pytest.raises(ValueError):
        validate_packet(g, actor, proofs[other])


@pytest.mark.parametrize("missing", ["inventory", "rights", "pending_orders", "cash"])
def test_unknown_necessary_state_is_not_zero_and_is_preserved(source, missing):
    scope, _ = source
    state = synthetic_zero_state(scope["guard"])
    state[missing] = None
    raw = deepcopy(state)
    with pytest.raises((ValueError, TypeError)):
        origin(scope["guard"], ACTORS[0], state, digest("SYNTHETIC_UNKNOWN"))
    assert state == raw


@pytest.mark.parametrize(
    "attack", ["hash_only", "empty_numeric", "missing_role", "missing_route"]
)
def test_directory_hashes_empty_reads_or_missing_paths_cannot_close_reference_proof(
    source, attack
):
    scope, proofs = source
    g = scope["guard"]
    p = proofs[ACTORS[0]]
    routes = deepcopy(p["no_acquisition"]["routes"])
    reads = deepcopy(p["economic_no_read"]["reads"])
    if attack == "hash_only":
        reads = {role: {"catalog_sha256": g["catalog_sha256"]} for role in CONSUMERS}
    if attack == "empty_numeric":
        reads["score"] = numeric_read(
            g,
            ACTORS[0],
            "score",
            [],
            synthetic_numeric_reader,
            initial=p["zero_origin"],
        )[1]
    if attack == "missing_role":
        reads.pop("label")
    if attack == "missing_route":
        routes.pop("exchange")
    with pytest.raises(ValueError):
        packet(g, ACTORS[0], p["zero_origin"], routes, reads)


def test_worker_requires_all_four_separate_packets(source):
    scope, proofs = source
    check_reference_packets(proofs, scope)
    other = deepcopy(proofs)
    other[ACTORS[0]] = proofs[ACTORS[1]]
    with pytest.raises(ValueError):
        check_reference_packets(other, scope)


def test_resigned_origin_with_old_rights_still_R2_and_preserves_the_raw_state(source):
    scope, proofs = source
    altered = deepcopy(proofs)
    p = altered[ACTORS[0]]
    o = p["zero_origin"]
    o["initial_state"]["rights"] = {"OLD_RIGHT": 1}
    o["zero_origin_receipt_sha256"] = digest(
        {k: v for k, v in o.items() if k != "zero_origin_receipt_sha256"}
    )
    p["reference_proof_packet_sha256"] = digest(
        {k: v for k, v in p.items() if k != "reference_proof_packet_sha256"}
    )
    raw = deepcopy(altered)
    with pytest.raises(ValueError, match="R2_zero_exposure_state_unknown"):
        check_reference_packets(altered, scope)
    assert altered == raw

    other = deepcopy(proofs)
    other.pop(ACTORS[0])
    with pytest.raises(ValueError):
        check_reference_packets(other, scope)


def test_reference_static_proof_checks_the_numeric_boundary_not_just_catalog_hashes(
    monkeypatch,
):
    import inspect
    from qlab.dynamic_factor.reference_noncash import static_proof

    proof = static_proof()
    assert (
        proof["reference_mechanism_proof_completed"]
        and not proof["real_runtime_proven"]
    )
    original = inspect.getsource

    def broken(fn):
        if fn is numeric_read:
            return "def numeric_read(*args):\n    return {}\n"
        return original(fn)

    monkeypatch.setattr(inspect, "getsource", broken)
    with pytest.raises(ValueError, match="static_noncash_guard_missing"):
        static_proof()

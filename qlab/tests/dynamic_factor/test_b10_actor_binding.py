"""B10-F1: the actual K5 consumer cannot borrow another actor's numeric work."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.catalog_v21 import guard_request
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.k5 import k5_dependency_check
from qlab.dynamic_factor.noncash_v3 import (
    CONSUMERS,
    actor_ids,
    economic_read_receipt,
    no_dependency_receipt,
    seal_guard,
    zero_origin,
)
from v3_test_helpers import synthetic_zero_state


def reader(symbol):
    return 100


@pytest.fixture
def subjects():
    guard = seal_guard(
        guard_request(
            sealed_at="2026-10-30T12:00:00Z",
            first_performance_at="2026-11-01T00:00:00Z",
        )
    )
    a = next(a for a in actor_ids() if a.startswith("strategy/"))
    b = next(a for a in actor_ids() if a.startswith("virtual_monitor/"))
    state = synthetic_zero_state(guard)
    origins = {
        actor: zero_origin(guard, actor, state, digest(dict(actor=actor, state=state)))
        for actor in (a, b)
    }
    reads = {
        role: economic_read_receipt(
            guard, role, ["QQQ"], reader, actor=a, origin=origins[a]
        )[1]
        for role in CONSUMERS
    }
    return guard, a, b, state, origins, reads


@pytest.mark.parametrize("attack", ["actor", "origin", "source", "guard"])
def test_resigned_binding_mismatch_refuses_actual_K5_without_target_read(
    subjects, attack
):
    guard, a, b, state, origins, reads = subjects
    proof_a = no_dependency_receipt(guard, a, origins[a], reads)
    other = deepcopy(reads)
    keys = dict(
        actor="actor",
        origin="zero_origin_receipt_sha256",
        source="source_sha256",
        guard="noncash_guard_manifest_sha256",
    )
    row = other["score"]
    row[keys[attack]] = b if attack == "actor" else digest("foreign/" + attack)
    row["numeric_read_receipt_sha256"] = digest(
        {k: v for k, v in row.items() if k != "numeric_read_receipt_sha256"}
    )
    with pytest.raises(ValueError, match="numeric_boundary"):
        no_dependency_receipt(guard, a, origins[a], other)
    request = dict(
        parent=guard["B"][0],
        dependency_role="raw_close",
        noncash_guard_manifest=guard,
        actor=b,
        zero_origin=origins[b],
        numeric_read_receipts=reads,
        no_dependency_receipt=proof_a,
        state=state,
    )
    target_calls = []
    report = k5_dependency_check(request)
    assert not target_calls
    assert not report["ok"] and report["reasons"]
    assert report["metrics"]["inventory_origin_dependency_closed"] is False
    assert report["metrics"]["R2_stop"] is True
    assert report["metrics"]["dependency_value"] is None


def test_original_unbound_read_API_refuses_before_callback(subjects):
    guard, *_ = subjects
    calls = []
    with pytest.raises(ValueError, match="actor_bound"):
        economic_read_receipt(guard, "score", ["QQQ"], lambda s: calls.append(s))
    assert calls == []


def test_each_actor_can_supply_its_own_numeric_receipts(subjects):
    guard, _, b, _, origins, _ = subjects
    reads = {
        role: economic_read_receipt(
            guard, role, ["QQQ"], reader, actor=b, origin=origins[b]
        )[1]
        for role in CONSUMERS
    }
    proof = no_dependency_receipt(guard, b, origins[b], reads)
    assert proof["actor"] == b
    assert all(
        r["actor"] == b and r["source_sha256"] == origins[b]["source_sha256"]
        for r in proof["numeric_read_scopes"].values()
    )

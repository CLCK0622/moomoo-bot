from copy import deepcopy

import pytest

from qlab.dynamic_factor.catalog_v21 import derive, guard_request
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.noncash_v3 import (
    CONSUMERS,
    ROUTES,
    acquisition_check,
    actor_ids,
    economic_values,
    seal_guard,
    zero_origin,
)
from v3_test_helpers import synthetic_zero_state, synthetic_guard


def registered():
    return seal_guard(
        guard_request(
            sealed_at="2026-10-30T12:00:00Z",
            first_performance_at="2026-11-01T00:00:00Z",
        )
    )


def candidate(guard):
    return next(
        e["symbol"]
        for e in guard["request"]["catalog"]["entries"]
        if e["guard_pending_review"]
    )


def test_registered_v21_preserves_facts_raw_rows_nulls_and_candidate_protection():
    d, g = derive(), registered()
    assert d["fact_counts"] == {"known_unclosed": 3, "UNKNOWN": 61}
    assert len(d["raw_declarations"]) == len(g["request"]["catalog"]["entries"]) == 64
    s = candidate(g)
    row = next(e for e in g["request"]["catalog"]["entries"] if e["symbol"] == s)
    assert row["fact_state"] == "UNKNOWN" and row["status"] == "UNKNOWN"
    assert row["B_membership"] is None and s in g["B"] and s not in g["unknown"]
    assert g["B_catalog_release_sha256"] is None and not g["runtime_consumable"]
    assert len(g["B"]) == 4 and len(g["unknown"]) == 60
    field = d["field_evidence"]
    assert field["exchange_ratio"]["use_as_holding_distribution_factor"] is False
    assert field["exchange_ratio"]["use_as_TR_label_or_cash_factor"] is False
    assert not field["cap_difference"]["implies_retained_shares"]
    for k in (
        "actual_residual_shares",
        "entitlement",
        "amount",
        "payment_date",
        "residual_disposition",
    ):
        assert field[k] is None and field[k + "_null_reason"]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_guard_pending_review_rejects_each_acquisition_route_without_erasing_state(
    route,
):
    g = registered()
    before = synthetic_zero_state(g)
    after = deepcopy(before)
    actor = actor_ids()[0]
    origin = zero_origin(g, actor, before, digest("SYNTHETIC_ZERO_SOURCE"))
    after["inventory"][candidate(g)] = 1
    after["age"][candidate(g)] = 0
    after["origin"][candidate(g)] = "SYNTHETIC_ROUTE"
    raw = deepcopy(after)
    with pytest.raises(ValueError, match="exposure"):
        acquisition_check(g, actor, origin, before, after, route)
    assert after == raw


@pytest.mark.parametrize("role", sorted(CONSUMERS))
def test_guard_pending_review_or_null_B_membership_never_permits_numeric_read(role):
    g = registered()
    calls = []
    with pytest.raises(ValueError, match="numeric_read_forbidden"):
        economic_values(g, role, [candidate(g)], lambda s: calls.append(s) or 12.0298)
    assert not calls


def test_other60_untriggered_are_neither_consumer_permission_nor_verified_B_complement():
    g = registered()
    calls = []
    assert len(g["unknown"]) == 60 and not set(g["unknown"]) & set(g["B"])
    for symbol in g["unknown"]:
        with pytest.raises(ValueError, match="numeric_read_forbidden"):
            economic_values(g, "score", [symbol], lambda s: calls.append(s) or 1)
    assert not calls and not derive()["general_unknown_is_verified_complement"]


def test_derived_fact_UNKNOWN_cannot_be_promoted_to_clear_or_all_B_or_runtime_release():
    request = deepcopy(registered()["request"])
    for attack in ("clear", "all_B", "null_is_permission"):
        r = deepcopy(request)
        for e in r["catalog"]["entries"]:
            if attack == "clear":
                e.update(
                    status="CLEAR",
                    fact_state="CLEAR",
                    credible_event_evidence=False,
                    guard_pending_review=False,
                    event_or_candidate_id=None,
                )
            elif attack == "all_B":
                e.update(
                    status="UNRESOLVED",
                    credible_event_evidence=True,
                    event_or_candidate_id="made-up",
                )
            else:
                e["B_membership"] = False
        with pytest.raises(ValueError):
            seal_guard(r)


def test_candidate_column_works_for_a_different_synthetic_identity():
    request = deepcopy(synthetic_guard()["request"])
    e = request["catalog"]["entries"][0]
    e.update(
        status="UNKNOWN",
        fact_state="UNKNOWN",
        guard_pending_review=True,
        credible_event_evidence=True,
        event_or_candidate_id="SYNTHETIC_CANDIDATE",
        B_membership=None,
    )
    g = seal_guard(request)
    assert e["symbol"] in g["B"] and e["symbol"] not in g["unknown"]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_undocumented_child_cannot_bypass_a_protective_catalog(route):
    g = registered()
    before = synthetic_zero_state(g)
    after = deepcopy(before)
    actor = actor_ids()[0]
    origin = zero_origin(g, actor, before, digest("SYNTHETIC_STATE"))
    after["inventory"]["UNDOCUMENTED_CHILD"] = 1
    after["age"]["UNDOCUMENTED_CHILD"] = 0
    after["origin"]["UNDOCUMENTED_CHILD"] = "SYNTHETIC_ROUTE"
    with pytest.raises(ValueError, match="exposure"):
        acquisition_check(g, actor, origin, before, after, route)

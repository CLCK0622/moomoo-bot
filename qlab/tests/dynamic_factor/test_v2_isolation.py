from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.isolation import (
    eligible_day,
    seal_manifest,
    score_day,
    verify_rank_receipt,
    selection_projection,
)


def synthetic_manifest(p=None, verified=50, unknown=0, *, date=None):
    """All evidence and prices are synthetic, never a real qualification mask."""
    p = p or load_conventions()
    date = date or p.calendar[600]
    i = p.calendar.index(date)
    records = []
    for n, s in enumerate(p.profile["universe"]):
        state = (
            "VERIFIED_USABLE"
            if n < verified
            else "UNKNOWN"
            if n < verified + unknown
            else "QUARANTINED"
        )
        records.append(
            dict(
                symbol=s,
                field_role="selection",
                from_date=date,
                to_date_or_null_with_reason=date,
                reason="SYNTHETIC_" + state,
                source_sha256=digest("synthetic_source"),
                dependency_lineage=[
                    dict(
                        id="synthetic/" + s,
                        symbol="SYNTHETIC",
                        field="feature",
                        parents=[],
                        source_sha256=digest("synthetic_lineage"),
                    )
                ]
                if p.document["version"] == "v3.0.0"
                else [digest("synthetic_lineage")],
                evidence_version="SYNTHETIC/v1",
                state=state,
                received_at="2026-10-01T00:00:00Z",
                gates_by_date={
                    date: dict(
                        history_dates=list(p.calendar[i - 251 : i + 1]),
                        raw_price=100,
                        dollar_adv=100000,
                        units_verified=True,
                        security_line_verified=True,
                        recipe_inputs_verified=True,
                    )
                },
            )
        )
    request = dict(
        role="train_solo_probes",
        records=records,
        mode="history",
        sealed_at="2026-10-02T00:00:00Z",
        first_performance_at="2026-10-03T00:00:00Z",
    )
    if p.document["version"] == "v3.0.0":
        from v3_test_helpers import synthetic_guard

        request["noncash_guard_manifest"] = synthetic_guard(p)
    return request


def synthetic_scores(p, names):
    ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
    return {k: {s: float(i // 2) for i, s in enumerate(names)} for k in ids}


def test_U64_50_verified_14_quarantined_scores_only_50_no_zero_padding():
    p = load_conventions()
    sealed = seal_manifest(synthetic_manifest(p), p)
    seen = []

    def scorer(names):
        seen.append(names)
        return synthetic_scores(p, names)

    r = score_day(sealed, p.calendar[600], scorer, p)
    d = verify_rank_receipt(r, sealed, p)
    assert d["verified_count"] == 50 and d["quantity_state"] == "VERIFIED_GE50"
    assert len(seen) == 1 and len(seen[0]) == 50
    for row in r["ranks"].values():
        assert sum(v is None for v in row.values()) == 14
        assert row[seen[0][0]] == row[seen[0][1]] == 1 / 50
        assert max(v for v in row.values() if v is not None) == 49 / 50
    assert not r["strict_count_independently_certified"]


@pytest.mark.parametrize(
    "verified,unknown,state",
    [(49, 1, "UNKNOWN"), (49, 0, "VERIFIED_LT50"), (50, 14, "VERIFIED_GE50")],
)
def test_quantity_three_states_do_not_infer_population_from_capacity(
    verified, unknown, state
):
    p = load_conventions()
    sealed = seal_manifest(synthetic_manifest(p, verified, unknown), p)
    calls = []
    r = score_day(
        sealed,
        p.calendar[600],
        lambda names: calls.append(names) or synthetic_scores(p, names),
        p,
    )
    assert r["day"]["quantity_state"] == state
    assert bool(calls) == (state == "VERIFIED_GE50")
    assert r["day"]["required_M_valuation_cash_fees_still_required"]
    if state != "VERIFIED_GE50":
        assert r["ranks"] is None


@pytest.mark.parametrize(
    "attack",
    ["zero_padding", "missing_member", "nonfinite", "constant", "missing_recipe"],
)
def test_score_rescue_and_padding_refuse_whole_recipe_date(attack):
    p = load_conventions()
    sealed = seal_manifest(synthetic_manifest(p), p)

    def scorer(names):
        scores = synthetic_scores(p, names)
        first = next(iter(scores))
        if attack == "zero_padding":
            scores[first][next(s for s in p.profile["universe"] if s not in names)] = 0
        elif attack == "missing_member":
            scores[first].pop(names[0])
        elif attack == "nonfinite":
            scores[first][names[0]] = float("nan")
        elif attack == "constant":
            scores[first] = dict.fromkeys(names, 1.0)
        else:
            del scores[first]
        return scores

    with pytest.raises(ValueError, match="isolation."):
        score_day(sealed, p.calendar[600], scorer, p)


@pytest.mark.parametrize(
    "selector", ["returns", "SR", "DSR", "rank_winners", "future_labels", "pool"]
)
def test_return_driven_or_future_label_mask_selection_is_rejected(selector):
    request = synthetic_manifest()
    request[selector] = {}
    with pytest.raises(ValueError, match="outcome_selector"):
        seal_manifest(request)


@pytest.mark.parametrize(
    "change",
    [
        "missing_lineage",
        "short_history",
        "units",
        "price",
        "ADV",
        "missing_record",
        "outside_range",
    ],
)
def test_unknown_or_incomplete_gates_cannot_become_verified(change):
    p = load_conventions()
    request = synthetic_manifest(p)
    r = request["records"][0]
    g = r["gates_by_date"][p.calendar[600]]
    if change == "missing_lineage":
        r["dependency_lineage"] = []
        with pytest.raises(ValueError, match="evidence_incomplete"):
            seal_manifest(request, p)
        return
    if change == "short_history":
        g["history_dates"] = g["history_dates"][1:]
    elif change == "units":
        g["units_verified"] = None
    elif change == "price":
        g["raw_price"] = None
    elif change == "ADV":
        g["dollar_adv"] = 0
    elif change == "missing_record":
        request["records"].pop(0)
    else:
        r["from_date"] = r["to_date_or_null_with_reason"] = p.calendar[599]
        r["gates_by_date"] = {}
    day = eligible_day(seal_manifest(request, p), p.calendar[600], p)
    assert day["quantity_state"] == "UNKNOWN" and day["verified_count"] == 49


def test_wrong_denominator_rehashed_receipt_is_rejected():
    p = load_conventions()
    sealed = seal_manifest(synthetic_manifest(p), p)
    r = score_day(sealed, p.calendar[600], lambda names: synthetic_scores(p, names), p)
    for row in r["ranks"].values():
        for s in r["day"]["eligible"]:
            row[s] *= 50 / 64
    r["rank_receipt_sha256"] = digest(
        {k: v for k, v in r.items() if k != "rank_receipt_sha256"}
    )
    with pytest.raises(ValueError, match="denominator"):
        verify_rank_receipt(r, sealed, p)


def test_projection_retains_held_state_blockers_and_audit_rows():
    p = load_conventions()
    sealed = seal_manifest(synthetic_manifest(p), p)
    s = p.profile["universe"][-1]
    item = dict(
        symbol=s, date=p.calendar[600], field="feature", consumer_role="test_meta"
    )
    request = dict(
        isolation_manifest=sealed, inputs=[item, dict(item, field="inventory")]
    )
    projected, removed, days = selection_projection(request, p)
    assert projected["inputs"] == [dict(item, field="inventory")]
    assert len(removed) == 1 and removed[0]["value"] is None
    assert request["inputs"][0] == item


def test_real_fold_precheck_consumes_mask_without_dropping_U64_or_cash_blockers():
    from qlab.dynamic_factor.validation import quarantined_manifest

    p = load_conventions()
    request = synthetic_manifest(p)
    for r in request["records"]:
        if r["symbol"] == "CRH":
            r["state"] = "QUARANTINED"
    sealed = seal_manifest(request, p)
    item = dict(
        symbol="CRH", date=p.calendar[600], field="feature", consumer_role="test_meta"
    )
    m = dict(isolation_manifest=sealed, panel_inputs=[item])
    r = quarantined_manifest(m, [], p)
    assert r["ok"], r["reasons"]
    assert r["metrics"]["pre_score_isolated_inputs"][0]["symbol"] == "CRH"
    assert r["metrics"]["frozen_count"] == 64
    m["panel_inputs"].append(dict(item, field="valuation"))
    assert not quarantined_manifest(m, [], p)["ok"]


@pytest.mark.parametrize(
    "attack", ["after_performance", "late_forward", "post_seal_edit"]
)
def test_preperformance_and_receipt_timing_are_bound(attack):
    request = synthetic_manifest()
    if attack == "after_performance":
        request["sealed_at"] = "2026-10-04T00:00:00Z"
    elif attack == "late_forward":
        request.update(mode="forward", signal_close="2026-09-30T21:00:00Z")
    else:
        sealed = seal_manifest(request)
        sealed["request"]["records"][0]["state"] = "QUARANTINED"
        with pytest.raises(ValueError, match="sealed_identity"):
            eligible_day(sealed, load_conventions().calendar[600])
        return
    with pytest.raises(ValueError, match="isolation."):
        seal_manifest(request)

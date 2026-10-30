import json
from copy import deepcopy
from pathlib import Path

import pytest

from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.conventions import FIXTURES, load_conventions
from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.event_quarantine import (
    BINDINGS,
    INHERITED,
    event_receipts,
    field_rules,
    quarantine_check,
    read_s1_raw_open,
    sources,
)
from qlab.dynamic_factor.folds import run_walk_forward
from qlab.dynamic_factor.input_disposition import panel_input_check
from qlab.dynamic_factor.quarantine_harness import (
    assert_nulls,
    business_case,
    cash_request,
    node,
    prohibitions,
)
from qlab.dynamic_factor.scope_harness import continuity_fixture
from qlab.dynamic_factor.validation import wf_manifest_check
from qlab.dynamic_factor.valuation import integer_cash_valuation


DOC, ACCEPTANCE = sources()
FIELDS = field_rules(DOC)


@pytest.mark.parametrize("index", range(1, 8))
def test_bound_business_negatives(index):
    case = business_case(index)
    assert case["status"] == "PASS"
    assert case["text"] == DOC["engineering_negative_examples"][index - 1]


def test_prohibited_recovery_panel_deletion_skip_and_reset_each_refuse():
    cases = prohibitions()
    assert len(cases) == 5 and all(row["status"] == "PASS" for row in cases)


@pytest.mark.parametrize(
    "decision", DOC["event_decisions"], ids=lambda d: d["event_key"]
)
def test_every_event_retains_exact_evidence_and_nulls_every_dependent_field(decision):
    rows = [node("source", "event", event_keys=[decision["event_key"]])]
    rows += [node(field, field, parents=["source"], value=123) for field in FIELDS]
    request = dict(dependency_nodes=rows)
    before = deepcopy(request)
    r = quarantine_check(request)
    assert_nulls(r)
    assert request == before
    actual = next(
        x for x in r["metrics"]["events"] if x["event_key"] == decision["event_key"]
    )
    assert actual["evidence"] == decision
    assert actual["action"] == decision["action"]
    assert all(
        decision["event_key"] in row["event_keys"]
        for row in r["metrics"]["projected_nodes"]
    )
    assert (
        actual["analytical_D"]
        is actual["receivable"]
        is actual["available_cash"]
        is None
    )
    assert actual["reason"] and actual["reasons"]


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_each_field_is_null_with_reason_in_actual_panel_entry(field):
    request = {"inputs": [dict(symbol="B", date="2010-01-04", field=field, value=5)]}
    r = panel_input_check(request)
    assert not r["ok"]
    affected = r["metrics"]["affected_inputs"][0]
    assert affected["field"] == field and affected["value"] is None
    assert affected["reasons"] and affected["source_reason"]
    assert_nulls(r["metrics"]["event_quarantine"])


def test_all_40_actions_and_15_relations_are_retained_without_new_cash_events():
    r = quarantine_check({})
    assert len(r["metrics"]["events"]) == 40
    assert len(r["metrics"]["unmatched_relations"]) == 15
    assert r["metrics"]["unmatched_relations"] == DOC["unmatched_declaration_relations"]
    assert set(INHERITED) == {"B", "COR"}
    assert len([x for x in event_receipts(DOC) if "SECURITY_LINE" in x["action"]]) == 11
    assert (
        len([x for x in event_receipts(DOC) if "AMOUNT_CONFLICT" in x["action"]]) == 14
    )
    assert not r["runtime_consumable"] and not r["certifiable"]
    # Adoption uses the separate external acceptance. The draft stays pending.
    assert not DOC["reviewer_acceptance_received"]
    assert ACCEPTANCE["external_review_receipt"]
    for name, expected in BINDINGS.items():
        assert sha256((FIXTURES / "evo898" / name).read_bytes()) == expected


@pytest.mark.parametrize("name", list(BINDINGS))
def test_changed_bound_bytes_refuse_before_any_value_is_adopted(monkeypatch, name):
    original = Path.read_bytes

    def corrupt(path):
        return original(path) + (b" " if path.name == name else b"")

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    r = quarantine_check({})
    assert r["reasons"] == ["data.v10_binding_mismatch"]
    assert r["metrics"]["events"] is r["metrics"]["projected_nodes"] is None


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([node("a", "NAV", parents=["absent"])], "parent_missing"),
        ([node("a", "NAV", parents=["b"]), node("b", "cash", parents=["a"])], "cycle"),
        ([node("a", "NAV"), node("a", "cash")], "duplicate_dependency_identity"),
        ([dict(id="a", field="NAV")], "ancestry_missing"),
        ([node("a", "NAV", event_keys=["invented"])], "unknown_event_lineage"),
        ([node("a", "NAV", event_keys="B|2023-08-30")], "unknown_event_lineage"),
    ],
)
def test_missing_or_malformed_lineage_does_not_clear_formal_values(rows, reason):
    r = quarantine_check({"dependency_nodes": rows})
    assert not r["ok"] and reason in r["reasons"][0]
    assert all(v is None for v in r["metrics"]["readouts"].values())
    assert all(a["reason"] for a in r["metric_availability"].values())


def test_post_event_date_or_self_asserted_checkpoint_never_clears_ancestry():
    rows = [node("anchor", "raw_open", symbol="COR", date="2010-01-04", value=5)]
    for field in FIELDS:
        rows.append(
            node(
                field,
                field,
                parents=["anchor"],
                date="2099-01-01",
                value=5,
                reconciliation_checkpoint=dict(verified=True, sha256="1" * 64),
            )
        )
    r = quarantine_check({"dependency_nodes": rows})
    assert_nulls(r)
    assert all(
        "inherited:COR" in row["event_keys"] for row in r["metrics"]["projected_nodes"]
    )


def test_full_daily_carried_state_chain_is_not_limited_by_recursion_or_row_order():
    rows = [node("0", "cash", event_keys=["B|2023-08-30"], value=100)]
    rows += [
        node(str(i), "cash", parents=[str(i - 1)], value=100) for i in range(1, 3191)
    ]
    r = quarantine_check({"dependency_nodes": list(reversed(rows))})
    assert_nulls(r)
    assert len(r["metrics"]["projected_nodes"]) == 3191
    assert all(
        row["event_keys"] == ["B|2023-08-30"] for row in r["metrics"]["projected_nodes"]
    )


def test_sold_holding_remains_in_cash_lineage_and_explicit_cash_fields_have_reasons():
    req = cash_request()
    req["inventory"] = {"QQQ": 1}
    req["marks"] = {"QQQ": 10}
    req["dependency_nodes"] = [
        node("sold-B", "cash", event_keys=["B|2023-08-30"], value=100)
    ]
    r = integer_cash_valuation(req)
    assert not r["ok"] and r["metrics"]["declared_inventory"] == {"QQQ": 1}
    for field in ("nav", "available_cash", "inventory", "receivable_amount"):
        assert r["metrics"][field] is None
        assert r["metric_availability"][field]["reason"]
    assert r["metrics"]["known_available_cash"] == 100


def test_missing_fold_and_actual_later_initialization_are_rejected():
    p = load_conventions()
    req = continuity_fixture(p)
    req["folds"].pop(1)
    r = continuous_path_check(req, conventions=p)
    assert not r["ok"] and "wf.all_original_folds_required" in r["reasons"]
    assert len(r["metrics"]["folds"]) == 77
    req = continuity_fixture(p)
    req["folds"][1]["initialized"] = True
    r = continuous_path_check(req, conventions=p)
    assert "wf.capital_restart_forbidden" in r["reasons"]


def test_manifest_and_walk_forward_block_prior_anchor_before_adapter_or_ledger(
    tmp_path,
):
    p = load_conventions()
    manifest = p.fold_manifest()
    manifest["dependency_nodes"] = [
        node("prior", "raw_open", symbol="COR", date="2010-01-04", value=10)
    ]
    r = wf_manifest_check(manifest, conventions=p)
    assert not r["ok"] and r["reasons"] == ["data.panel_quarantined_input"]

    def forbidden(*a, **kw):
        pytest.fail("quarantined input reached adapter")

    r = run_walk_forward(
        manifest,
        [],
        miner_factory=forbidden,
        fitter_factory=forbidden,
        ledger=None,
        run_id="SYNTHETIC_ONLY",
        conventions=p,
    )
    assert not r["ok"] and r["reasons"] == ["data.panel_quarantined_input"]
    assert len(r["metrics"]["folds"]) == 77
    assert all(row["nav"] is None and row["reasons"] for row in r["metrics"]["folds"])


def test_a_hash_assertion_does_not_authenticate_invented_S1_prices():
    with pytest.raises(ValueError, match="S1_CSV_identity_mismatch"):
        read_s1_raw_open(b"date,raw_open\n2013-10-29,123\n")


def test_S1_pinned_CSV_adopts_exactly_3191_raw_opens_and_four_page_bindings():
    raw = (FIXTURES / "evo898" / "EVO893-S1-BRKB-v10-open-none.csv").read_bytes()
    r = read_s1_raw_open(raw)
    assert len(r["rows"]) == 3191
    assert r["rows"][0]["date"] == "2013-10-29"
    assert r["rows"][-1]["date"] == "2026-07-09"
    assert all(set(row) == {"symbol", "date", "raw_open"} for row in r["rows"])
    assert not r["receipt"]["source_independence"]
    assert not r["receipt"]["complete_execution_path_certified"]
    for broken in (raw + b"\n", raw.replace(b"2013-10-29", b"2013-10-28")):
        with pytest.raises(ValueError, match="S1_CSV_identity_mismatch"):
            read_s1_raw_open(broken)


def test_frozen_input_records_are_not_mutated_by_consumers():
    before = {n: (FIXTURES / "evo898" / n).read_bytes() for n in BINDINGS}
    panel_input_check(
        {"inputs": [dict(symbol="B", date="2010-01-04", field="raw_open")]}
    )
    integer_cash_valuation(cash_request())
    for name, raw in before.items():
        assert (FIXTURES / "evo898" / name).read_bytes() == raw
        assert isinstance(json.loads(raw), dict)

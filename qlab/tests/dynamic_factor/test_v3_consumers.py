from pathlib import Path

import pytest

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution import OrderCosts, calibrate_gain
from qlab.dynamic_factor.isolation import seal_manifest, score_day
from qlab.dynamic_factor.k5 import vsnt_quote, k5_dependency_check
from qlab.dynamic_factor.noncash_v3 import (
    actor_ids,
    zero_origin,
    CONSUMERS,
    economic_read_receipt,
    no_dependency_receipt,
)
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.scope_proof import noncash_isolation_proof
from qlab.dynamic_factor.valuation import integer_cash_valuation, factor_cash_valuation
from qlab.dynamic_factor.v1_harness import unit_context
from test_v2_isolation import synthetic_manifest, synthetic_scores
from v3_test_helpers import synthetic_guard, synthetic_zero_state


class PoisonMarks(dict):
    def __getitem__(self, key):
        raise AssertionError("forbidden child price was read")


class PoisonLabel(dict):
    def __getitem__(self, key):
        if key in {"stock_h10", "qqq_h10", "label_verified"}:
            raise AssertionError("guarded label was read")
        return super().__getitem__(key)


class PoisonEvent(dict):
    def get(self, key, default=None):
        if key in {"declared_cash_amount", "entitled_integer_shares"}:
            raise AssertionError("guarded cash event was valued")
        return super().get(key, default)


def test_order_fee_reader_rejects_parent_and_child_before_prices():
    p = load_conventions()
    guard = synthetic_guard(blocked=["ABNB"])
    costs = OrderCosts(p, p.calendar[600], "research_restored")
    for s in ["ABNB", guard["children"][0]]:
        with pytest.raises(ValueError, match="numeric_read_forbidden"):
            costs.quote({s: 1}, PoisonMarks(), guard=guard)


def test_factor_cash_scope_is_required_while_generic_accounting_is_labeled():
    request = dict(
        known_cash=100,
        inventory={"QQQ": 1},
        marks={"QQQ": 100},
        as_of="2026-01-05",
        events=[],
    )
    generic = integer_cash_valuation(request)
    assert (
        generic["ok"]
        and generic["metrics"]["consumer_scope"] == "unbound_accounting_only"
    )
    assert not generic["metrics"]["factor_arm_numeric_scope_checked"]
    factor = factor_cash_valuation(request)
    assert not factor["ok"] and factor["metrics"]["nav"] is None
    assert factor["metrics"]["consumer_scope"] == "factor_arm"


def test_cash_and_holdings_valuation_refuse_guarded_inputs_before_economic_reads():
    guard = synthetic_guard(blocked=["ABNB"])
    child = guard["children"][0]
    request = dict(
        known_cash=100,
        inventory={child: 1},
        rights={"LEGACY": 1},
        receivables={"LEGACY": 2},
        marks=PoisonMarks({child: 10}),
        as_of="2026-01-05",
        events=[],
        noncash_guard_manifest=guard,
    )
    out = integer_cash_valuation(request)
    assert not out["ok"] and out["metrics"]["R2_stop"] and out["metrics"]["nav"] is None
    assert out["metrics"]["retained_state_declaration"]["inventory"] == {child: 1}
    assert out["metrics"]["retained_state_declaration"]["rights"] == {"LEGACY": 1}
    assert out["metrics"]["retained_state_declaration"]["receivables"] == {"LEGACY": 2}
    assert out["metrics"]["known_available_cash"] == 100
    request.update(
        inventory={},
        events=[
            PoisonEvent(
                symbol="ABNB", declared_cash_amount=1, entitled_integer_shares=1
            )
        ],
    )
    out = integer_cash_valuation(request)
    assert not out["ok"] and out["metrics"]["nav"] is None


def test_calibration_rejects_B_before_reading_a_label_or_future_availability():
    p = load_conventions()
    context = unit_context(p)
    date = context["train_calendar"][50]
    request = synthetic_manifest(p, verified=64, date=date)
    request["noncash_guard_manifest"] = synthetic_guard(blocked=["ABNB"])
    next(r for r in request["records"] if r["symbol"] == "ABNB").update(
        state="QUARANTINED", gates_by_date={}
    )
    sealed = seal_manifest(request, p)
    ranks = score_day(sealed, date, lambda names: synthetic_scores(p, names), p)
    context["isolation"] = dict(manifest=sealed, rank_receipts={date: ranks})
    with pytest.raises(ValueError, match="numeric_read_forbidden"):
        calibrate_gain(
            [PoisonLabel(date=date, symbol="ABNB")],
            {date},
            conventions=p,
            context=context,
        )


def test_v3_K5_never_reads_legacy_child_price_file(monkeypatch):
    original = Path.read_bytes

    def poison(path):
        if path.parent.name == "k5":
            raise AssertionError("legacy child price bytes read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", poison)
    with pytest.raises(ValueError, match="v3_child_price_reader_forbidden"):
        vsnt_quote("2026-01-05", "raw_close", purpose="K5")


def test_static_proof_checks_guards_and_separates_reference_and_real_evidence():
    proof = noncash_isolation_proof(load_conventions())
    assert len(proof["actor_ids"]) == 34 and len(proof["acquisition_routes"]) == 6
    assert proof["numeric_guard_line"] < proof["injected_reader_line"]
    assert proof["B_catalog_sha256"] is None and proof["real_origin_proofs"] is None
    assert not proof["reference_producer_proof_completed"]


def test_static_proof_refuses_missing_numeric_guard_instead_of_hash_only(monkeypatch):
    original = Path.read_bytes

    def changed(path):
        raw = original(path)
        if path.name == "noncash_v3.py":
            raw = raw.replace(
                b"    assert_consumer_symbols(guard, consumer, [symbol], policy)\n", b""
            )
        return raw

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="numeric_guard_not_dominant"):
        noncash_isolation_proof(load_conventions())


def test_v3_K5_closes_only_conditional_new_path_with_all_factor_proofs():
    guard = synthetic_guard(blocked=["ABNB"])
    actor = actor_ids()[0]
    state = synthetic_zero_state(guard)
    origin = zero_origin(guard, actor, state, digest("SYNTHETIC_SOURCE"))
    reads = {
        k: economic_read_receipt(
            guard, k, ["AAPL"], lambda s: 100, actor=actor, origin=origin
        )[1]
        for k in CONSUMERS
    }
    proof = no_dependency_receipt(guard, actor, origin, reads)
    req = dict(
        parent="ABNB",
        dependency_role="raw_close",
        noncash_guard_manifest=guard,
        actor=actor,
        zero_origin=origin,
        numeric_read_receipts=reads,
        no_dependency_receipt=proof,
        state=state,
    )
    out = k5_dependency_check(req)
    assert out["ok"] and not out["metrics"]["R2_stop"]
    assert out["metrics"]["quote"] is out["metrics"]["dependency_value"] is None
    assert (
        out["metrics"]["real_catalog_sha256"] is None and not out["runtime_consumable"]
    )
    state["inventory"]["ABNB"] = 1
    state["age"]["ABNB"] = 30
    state["origin"]["ABNB"] = "LEGACY"
    out = k5_dependency_check(req)
    assert not out["ok"] and out["metrics"]["R2_stop"]
    assert out["metrics"]["retained_state_declaration"] == state


@pytest.mark.parametrize(
    "basis,value", [("WI_high_low_midpoint", 22.50), ("future_12_31_close", 28.07)]
)
def test_v3_no_quote_proxy_or_preinitialization_waiver(basis, value):
    req = dict(
        parent="ADP",
        dependency_role="historical_inventory",
        account_role="train_solo_probes",
        fold_id="0",
        event_date="2014-10-01",
        price_basis=basis,
        execution_price=value,
    )
    out = k5_dependency_check(req)
    assert not out["ok"] and out["metrics"]["R2_stop"]
    assert out["metrics"]["quote"] is out["metrics"]["dependency_value"] is None

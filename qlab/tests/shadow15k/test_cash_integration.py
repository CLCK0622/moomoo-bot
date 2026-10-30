import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from qlab.dynamic_factor.input_disposition import qqq_cash_input
from qlab.shadow15k.cash_harness import (
    prepared,
    packet,
    paid_event,
    marks,
    buy_request,
    fill,
)
from qlab.shadow15k.harness import FIXTURE, fixture_fees
from qlab.shadow15k.ledger import ShadowLedger

GENESIS = json.loads(FIXTURE.read_bytes())["genesis"]


@pytest.fixture
def book(tmp_path):
    return prepared(tmp_path, GENESIS, fixture_fees("x1"))


def test_verified_payment_can_finance_cash_but_never_changes_inventory(book):
    p = packet(paid_event(), rid="paid", at="2022-12-30T14:00:00Z")
    assert book.record_dividend(p)["ok"]
    inventory = book.readout(marks("2022-12-30T14:30:00Z"))["metrics"]["inventory"]
    assert book.register_intent(buy_request("2022-12-30", iid="use-paid", qty=1))["ok"]
    assert book.record_receipt(
        "use-paid",
        fill("2022-12-30", rid="use-paid-fill", oid="use-paid", qty=1, gross="14788"),
    )["ok"]
    r = book.readout(marks("2022-12-30T21:00:00Z"))["metrics"]
    assert (
        r["inventory"] == dict(inventory, QQQ=3) and Decimal(r["available_cash"]) >= 0
    )
    assert (
        Decimal(r["receivable_amount"]) == 0
        and r["account_cash_credited_amount"] is None
    )


def test_missing_payment_evidence_can_be_resolved_by_a_later_append(book):
    bad = paid_event()
    bad.pop("simulated_payment_source_sha256")
    assert book.record_dividend(packet(bad, rid="unknown", at="2022-12-30T18:00:00Z"))[
        "ok"
    ]
    assert book.readout(marks("2022-12-30T18:30:00Z"))["metrics"]["nav"] is None
    assert book.record_dividend(
        packet(paid_event(), rid="resolved", at="2022-12-30T20:00:00Z")
    )["ok"]
    r = book.readout(marks("2022-12-30T21:00:00Z"))["metrics"]
    assert r["nav"] is not None and Decimal(r["receivable_amount"]) == 0


def test_unknown_paydate_preserves_receivable_but_available_cash_unknown(book):
    e = qqq_cash_input("2022-12-19", 2)
    e.update(pay_date=None, pay_date_status="unknown")
    assert book.record_dividend(packet(e))["ok"]
    r = book.readout(marks())["metrics"]
    assert Decimal(r["receivable_amount"]) == Decimal("1.31082")
    assert r["available_cash"] is r["nav"] is None
    assert r["reconciliation_required"]


def test_ex_date_sale_preserves_pre_ex_entitlement_and_cash_separation(book):
    request = buy_request("2022-12-19", iid="sell", qty=2)
    request["orders"][0]["side"] = "SELL"
    assert book.register_intent(request)["ok"]
    assert book.record_receipt("sell", fill("2022-12-19", rid="sell-fill", oid="sell"))[
        "ok"
    ]
    assert book.record_dividend(packet())["ok"]
    r = book.readout(marks())["metrics"]
    assert r["inventory"]["QQQ"] == 0 and Decimal(r["receivable_amount"]) == Decimal(
        "1.31082"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        dict(entitled_integer_shares=3),
        dict(entitled_integer_shares=2.0),
        dict(symbol="SPY"),
        dict(ex_date="bad"),
    ],
)
def test_invalid_event_is_transactionally_rejected_without_inventory_change(
    book, mutation
):
    before = book.readout(marks())["metrics"]
    e = dict(qqq_cash_input("2022-12-19", 2), **mutation)
    r = book.record_dividend(packet(e))
    assert not r["ok"]
    assert book.readout(marks())["metrics"] == before


def test_payment_cannot_be_backdated_into_an_earlier_decision_or_readout(book):
    assert book.record_dividend(packet(paid_event(), at="2022-12-30T20:00:00Z"))["ok"]
    r = book.register_intent(buy_request("2022-12-30", iid="backdated"))
    assert not r["ok"]
    assert "intent.decision_precedes_dividend_receipt" in r["reasons"]
    assert book.readout(marks("2022-12-20T21:00:00Z"))["metrics"]["nav"] is None


def test_concurrent_payment_delivery_and_restart_are_exactly_once(book):
    p = packet(paid_event(), rid="paid", at="2022-12-30T20:00:00Z")
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: book.record_dividend(p), range(8)))
    assert (
        all(r["ok"] for r in reports)
        and sum(r["metrics"]["registered"] for r in reports) == 1
    )
    before = book.readout(marks("2022-12-30T21:00:00Z"))["metrics"]
    after = ShadowLedger(book.root, GENESIS, fixture_fees("x1")).readout(
        marks("2022-12-30T21:00:00Z")
    )["metrics"]
    assert before == after and before["event_count"] == 3


def test_legacy_fee_identity_is_not_silently_replayed_with_new_cash_policy(book):
    import sqlite3

    with sqlite3.connect(book.path) as db:
        row = json.loads(db.execute("SELECT body FROM metadata").fetchone()[0])
        row["fee_binding"] = {
            k: v
            for k, v in row["fee_binding"].items()
            if k in ["params_sha256", "schedule_sha256"]
        }
        from qlab.dynamic_factor.contract import canonical

        db.execute("UPDATE metadata SET body=?", (canonical(row).decode(),))
    with pytest.raises(ValueError, match="genesis_or_fee_binding_conflict"):
        ShadowLedger(book.root, GENESIS, fixture_fees("x1"))


def test_unknown_dividend_does_not_hide_a_previously_planned_confirmed_fill(book):
    assert book.register_intent(buy_request("2022-12-30", iid="existing", qty=1))["ok"]
    bad = paid_event()
    bad.pop("simulated_payment_source_sha256")
    assert book.record_dividend(packet(bad, at="2022-12-30T15:00:30Z"))["ok"]
    r = fill("2022-12-30", rid="existing-fill", oid="existing", qty=1, gross="100")
    assert book.record_receipt("existing", r)["ok"]
    m = book.readout(marks("2022-12-30T21:00:00Z"))["metrics"]
    assert m["inventory"]["QQQ"] == 3 and m["available_cash"] is None
    assert m["reconciliation_required"]

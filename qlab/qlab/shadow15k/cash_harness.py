"""Synthetic QQQ receivable/payment integration probes; no actual account IO."""

from decimal import Decimal

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.input_disposition import qqq_cash_input

from .ledger import ShadowLedger


def buy_request(day, *, iid="buy", qty=2):
    return dict(
        intent_id=iid,
        decision_ts=day + "T15:00:00Z",
        input_hash=digest("SYNTHETIC_UNIT"),
        orders=[
            dict(
                order_id=iid,
                symbol="QQQ",
                side="BUY",
                planned_qty=qty,
                trade_date=day,
                protective=False,
            )
        ],
    )


def fill(day, *, rid="fill", oid="buy", qty=2, gross="200"):
    return dict(
        receipt_id=rid,
        receipt_ts=day + "T15:01:00Z",
        orders=[
            dict(
                order_id=oid,
                confirmed_qty=qty,
                gross_usd=gross,
                fee_known=True,
                status="filled",
            )
        ],
    )


def marks(at="2022-12-20T21:00:00Z"):
    return dict(as_of=at, prices={"QQQ": "100"}, price_basis="cash_bid_ask")


def prepared(root, genesis, fees, day="2022-12-16"):
    ledger = ShadowLedger(root / "shadow15k", genesis, fees)
    assert ledger.register_intent(buy_request(day))["ok"]
    assert ledger.record_receipt("buy", fill(day))["ok"]
    return ledger


def packet(event=None, *, rid="accrue", at="2022-12-20T20:00:00Z"):
    return dict(
        receipt_id=rid,
        as_of=at,
        event=event if event is not None else qqq_cash_input("2022-12-19", 2),
    )


def paid_event():
    return dict(
        qqq_cash_input("2022-12-19", 2),
        simulated_payment_available=True,
        simulated_cash_credited_amount=1.31082,
        simulated_cash_credited_at="2022-12-30",
        simulated_payment_source_sha256=digest("SYNTHETIC_PAYMENT_ONLY"),
    )


def cases(workdir, genesis, fees):
    out = []

    def record(cid, observed):
        out.append(
            dict(
                case_id=cid,
                status="PASS",
                scope="synthetic_accounting_only",
                observed=observed,
            )
        )

    ledger = prepared(workdir / "cash-correct", genesis, fees)
    baseline = ledger.readout(marks())["metrics"]
    assert ledger.record_dividend(packet())["ok"]
    m = ledger.readout(marks())["metrics"]
    assert Decimal(m["receivable_amount"]) == Decimal("1.31082")
    assert (
        m["available_cash"] == baseline["available_cash"]
        and m["inventory"] == baseline["inventory"]
    )
    record(
        "cash.QQQ_mapped_amount_and_separate_receivable",
        dict(
            available_cash=m["available_cash"],
            receivable_amount=m["receivable_amount"],
            account_cash_credited_amount=m["account_cash_credited_amount"],
        ),
    )
    for cid, change in [
        ("cash.QQQ_amount_conflict_null", dict(declared_cash_amount=1.31082)),
        ("cash.QQQ_missing_mapping_null", dict(source_mapping_sha256=None)),
    ]:
        book = prepared(workdir / cid, genesis, fees)
        assert book.record_dividend(
            packet(dict(qqq_cash_input("2022-12-19", 2), **change))
        )["ok"]
        r = book.readout(marks())
        assert (
            r["metrics"]["receivable_amount"] is None
            and r["metrics"]["available_cash"] is None
        )
        record(
            cid, dict(reasons=r["reasons"], receivable_amount=None, available_cash=None)
        )
    unknown = ledger.readout(marks("2022-12-30T21:00:00Z"))["metrics"]
    assert (
        unknown["available_cash"] is unknown["nav"] is None
        and unknown["account_cash_credited_at"] is None
    )
    request = buy_request("2022-12-30", iid="blocked")
    request["decision_ts"] = "2022-12-30T22:00:00Z"
    refused = ledger.register_intent(request)
    assert (
        not refused["ok"]
        and "dividend.cash_reconciliation_required" in refused["reasons"]
    )
    record(
        "cash.exchange_paydate_not_payment_receipt",
        dict(available_cash=None, nav=None, reasons=refused["reasons"]),
    )
    book = prepared(workdir / "cash-bad-payment", genesis, fees)
    e = paid_event()
    e.pop("simulated_payment_source_sha256")
    assert book.record_dividend(packet(e, at="2022-12-30T20:00:00Z"))["ok"]
    r = book.readout(marks("2022-12-30T21:00:00Z"))
    assert r["metrics"]["nav"] is None and r["metrics"]["cash"] is None
    record(
        "cash.payment_without_evidence_null",
        dict(reasons=r["reasons"], available_cash=None),
    )
    book = prepared(workdir / "cash-ex-open", genesis, fees, day="2022-12-19")
    r = book.record_dividend(packet())
    assert not r["ok"] and r["reasons"] == ["dividend.entitlement_mismatch"]
    record("cash.ex_date_entry_cannot_claim_dividend", dict(reasons=r["reasons"]))
    book = prepared(workdir / "cash-unspendable", genesis, fees)
    assert book.record_dividend(packet(at="2022-12-20T14:00:00Z"))["ok"]
    m = book.readout(marks())["metrics"]
    expense = Decimal("14788") + Decimal(
        fees.cumulative(
            qty=1,
            notional="14788",
            side="BUY",
            trade_date="2022-12-20",
            price_basis="cash_bid_ask",
        )["charged"]
    )
    assert (
        Decimal(m["available_cash"])
        < expense
        < Decimal(m["available_cash"]) + Decimal(m["receivable_amount"])
    )
    assert book.register_intent(buy_request("2022-12-20", iid="overspend", qty=1))["ok"]
    r = book.record_receipt(
        "overspend",
        fill("2022-12-20", rid="overspend-fill", oid="overspend", qty=1, gross="14788"),
    )
    assert not r["ok"] and "cash_insufficient_including_fees" in r["reasons"]
    record(
        "cash.unreceived_receivable_not_spendable",
        dict(reasons=r["reasons"], expense=str(expense)),
    )
    p = packet(paid_event(), rid="paid", at="2022-12-30T20:00:00Z")
    assert ledger.record_dividend(p)["ok"]
    paid = ledger.readout(marks("2022-12-30T21:00:00Z"))["metrics"]
    assert (
        Decimal(paid["available_cash"])
        == Decimal(baseline["available_cash"]) + Decimal("1.31082")
        and Decimal(paid["receivable_amount"]) == 0
    )
    again = ShadowLedger(ledger.root, genesis, fees)
    assert not again.record_dividend(p)["metrics"]["registered"]
    assert again.readout(marks("2022-12-30T21:00:00Z"))["metrics"] == paid
    rollback = again.record_dividend(packet(rid="rollback", at="2022-12-30T22:00:00Z"))
    assert not rollback["ok"]
    record(
        "cash.payment_replay_and_rollback_guard",
        dict(
            available_cash=paid["available_cash"],
            receivable_amount=paid["receivable_amount"],
            rollback_reasons=rollback["reasons"],
            account_cash_credited_at=paid["account_cash_credited_at"],
        ),
    )
    return out

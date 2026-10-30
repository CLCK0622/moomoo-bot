"""The original B7 shadow_probe.py requests, with persistent ancestry checks."""

import json

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.event_quarantine import field_rules, sources
from qlab.shadow15k import ShadowLedger
from qlab.shadow15k.harness import FIXTURE, fixture_fees


GENESIS = json.loads(FIXTURE.read_bytes())["genesis"]
FIELDS = field_rules(sources()[0])


def request(symbol, side, *, iid=None):
    iid = iid or side
    return dict(
        intent_id=iid,
        decision_ts="2026-07-09T14:00:00Z",
        input_hash=digest({"synthetic": symbol, "side": side}),
        orders=[
            dict(
                order_id=iid,
                symbol=symbol,
                side=side,
                planned_qty=2,
                trade_date="2026-07-09",
                protective=side == "SELL",
            )
        ],
    )


def receipt(side):
    return dict(
        receipt_id=side,
        receipt_ts="2026-07-09T15:00:00Z",
        orders=[
            dict(
                order_id=side,
                confirmed_qty=2,
                gross_usd="20",
                fee_known=True,
                status="filled",
            )
        ],
    )


def read(book, symbol):
    return book.readout(
        dict(
            as_of="2026-07-09T21:00:00Z",
            price_basis="cash_bid_ask",
            prices={symbol: "10"},
        )
    )


def assert_quarantined(report, symbol, qty):
    assert not report["ok"]
    m = report["metrics"]
    assert not m["valuation_complete"] and m["reconciliation_required"]
    assert m["declared_inventory"] == {symbol: qty}
    for field in ("nav", "available_cash", "cash", "inventory", "receivable_amount"):
        assert m[field] is None and report["metric_availability"][field]["reason"]
    assert m["inventory_value"] is m["gross_pnl"] is m["net_pnl"] is None
    assert m["known_available_cash"] is not None and m["fills"] and m["postings"]
    q = m["event_quarantine"]
    assert not q["ok"] and len(FIELDS) == 42
    for field in FIELDS:
        assert q["metrics"]["readouts"][field] is None
        assert q["metric_availability"][field]["reason"]
        assert report["metric_availability"][field]["reason"]
    assert any(
        "inherited:" + symbol in n["event_keys"]
        for n in q["metrics"]["projected_nodes"]
    )


@pytest.mark.parametrize("symbol", ["B", "COR"])
def test_original_audit_no_dividends_buy_sell_and_reopen_never_clear_ancestry(
    tmp_path, symbol
):
    fees = fixture_fees("x1")
    book = ShadowLedger(tmp_path / symbol / "shadow15k", GENESIS, fees)
    for side, qty in (("BUY", 2), ("SELL", 0)):
        assert book.register_intent(request(symbol, side))["ok"]
        assert book.record_receipt(side, receipt(side))["ok"]
        report = read(book, symbol)
        assert_quarantined(report, symbol, qty)
        reopened = ShadowLedger(book.root, GENESIS, fees)
        assert read(reopened, symbol) == report
        # Idempotent replay does not erase or duplicate ancestry.
        assert reopened.record_receipt(side, receipt(side))["ok"]
        assert read(reopened, symbol) == report
    assert len(report["metrics"]["event_quarantine"]["metrics"]["projected_nodes"]) == 2


@pytest.mark.parametrize("symbol", ["B", "COR"])
def test_sold_and_reopened_cash_cannot_finance_later_clean_BUY(tmp_path, symbol):
    fees = fixture_fees("x1")
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fees)
    for side in ("BUY", "SELL"):
        assert book.register_intent(request(symbol, side))["ok"]
        assert book.record_receipt(side, receipt(side))["ok"]
    book = ShadowLedger(book.root, GENESIS, fees)
    before = read(book, symbol)
    refused = book.register_intent(request("QQQ", "BUY", iid="new-risk"))
    assert not refused["ok"] and "cash_reconciliation_required" in refused["reasons"][0]
    assert read(book, symbol) == before
    assert_quarantined(before, symbol, 0)


def test_clean_symbol_without_dividend_packet_keeps_numeric_cash_and_NAV(tmp_path):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    assert book.register_intent(request("QQQ", "BUY"))["ok"]
    assert book.record_receipt("BUY", receipt("BUY"))["ok"]
    report = read(book, "QQQ")
    assert report["ok"] and report["metrics"]["valuation_complete"]
    assert report["metrics"]["nav"] is not None
    assert report["metrics"]["available_cash"] is not None

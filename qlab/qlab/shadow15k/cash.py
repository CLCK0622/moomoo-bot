"""Integer QQQ cash adapter to the pinned 11-03 tool contract, no account IO."""

from decimal import Decimal

from qlab.dynamic_factor.input_disposition import MAPPING_SHA
from qlab.dynamic_factor.valuation import integer_cash_valuation

from .fees import money
from .contract import report


def entitlement(state, ex_date):
    """Only confirmed inventory from earlier exchange dates is entitled.

    Ex-date entry cannot create entitlement; selling on ex-date does not erase
    earlier ownership. A late/unknown pre-ex receipt requires reconciliation.
    """
    qty = 0
    for intent in state["intents"].values():
        for order in intent["orders"].values():
            spec = order["spec"]
            if spec["symbol"] == "QQQ" and spec["trade_date"] < ex_date:
                if not order["quantity_known"]:
                    return None
                qty += order["qty"] * (1 if spec["side"] == "BUY" else -1)
    return qty if qty >= 0 else None


def cash_view(state, as_of, prices):
    # Trade cash excludes dividends; each event key occurs once. Replaying or
    # re-reading adds no credit twice, and receivables are never spendable.
    events = []
    for packet in state["dividends"].values():
        if packet["as_of"] > as_of:
            continue
        event = dict(packet["event"])
        actual = entitlement(state, event["ex_date"])
        if event.get("entitled_integer_shares") != actual:
            event["entitled_integer_shares"] = None
        events.append(event)
    trade_cash = Decimal(state["cash_gross"]) - money(state["fees"])
    # Isolate dividend credits at zero cash in the imported numeric contract;
    # combine with signed trade cash in Decimal, without float-rounding the
    # whole 15k account or ever spending a receivable.
    r = integer_cash_valuation(
        dict(
            known_cash=0,
            as_of=as_of[:10],
            inventory=state["inventory"],
            marks={s: float(money(v)) for s, v in prices.items()},
            events=events,
        )
    )
    m = dict(r["metrics"])
    for k in ("known_available_cash", "available_cash", "nav"):
        if m.get(k) is not None:
            m[k] = str(Decimal(str(m[k])) + trade_cash)
    m["source_mapping_sha256"] = MAPPING_SHA
    return report(
        "shadow_integer_cash_adapter",
        dict(as_of=as_of, prices=prices, trade_cash=str(trade_cash), events=events),
        metrics=m,
        reasons=r["reasons"],
        artifacts={"integer_cash_valuation": r},
    )


def payment_verified(event, as_of):
    """Only the imported validator's accepted simulated credit locks a row."""
    r = integer_cash_valuation(
        dict(
            known_cash=0,
            as_of=as_of[:10],
            inventory={"QQQ": 0},
            marks={},
            events=[event],
        )
    )
    rows = r["metrics"].get("dividends")
    return bool(
        rows
        and event.get("simulated_payment_available") is True
        and rows[0].get("simulated_cash_credited_amount") is not None
    )

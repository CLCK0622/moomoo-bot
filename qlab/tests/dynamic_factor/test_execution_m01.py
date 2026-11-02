"""M-01 negatives at existing C06 accounting/replay boundaries, no planner."""

from copy import deepcopy
import json

import pytest

from qlab.dynamic_factor.contract import digest
from test_execution_risk_history import (
    accounting,
    at,
    close,
    fill,
    history,
    next_date,
    prepare,
)


def required_exit():
    book, _ = history()
    at(book, 5)
    close(book, [fill(book, prepare(book), 2)])
    at(book, 25)
    intent = prepare(book)
    assert book.snapshot()["state"]["inventory"]["AAPL"] == 2
    assert intent["required_M"]["M"]["AAPL"] == 0
    assert intent["required_M"]["complete"] is True
    return book, intent


def observe(book, date, row, fills, *, expected_accounting_sha256=None):
    return book.observe_close(
        date,
        row,
        fills,
        expected_accounting_sha256=expected_accounting_sha256 or digest(row),
        expected_fills_sha256=digest(fills),
    )


def record(record_property, case, reasons, **observations):
    record_property(
        "M01_actual",
        json.dumps(dict(case=case, reasons=reasons, **observations), sort_keys=True),
    )


def test_M01_P_minus_M_cannot_replace_complete_orders(record_property):
    book, intent = required_exit()
    before, pending = book.snapshot(), book.pending_intents()
    original = before["state"]["inventory"]
    M = intent["required_M"]["M"]
    P = dict(M, QQQ=1)
    optional = {s: P[s] - M[s] for s in P}
    complete = {s: P[s] - original[s] for s in P}
    assert optional["AAPL"] == 0 and complete["AAPL"] == -2
    # Replacing complete orders by P-M omits the necessary AAPL exit. A final
    # inventory claim of P cannot be supported by these actual-fill receipts.
    fills = [fill(book, intent, 1, symbol="QQQ", origin="QQQ_BASE")]
    date = next_date(book)
    row = accounting(book, date, fills, inventory=P)
    with pytest.raises(ValueError) as failure:
        observe(book, date, row, fills)
    assert str(failure.value) == "risk.inventory_change_without_actual_fills"
    assert book.snapshot()["state"] == before["state"]
    assert book.pending_intents() == pending
    assert not book.snapshot()["complete"]
    record(
        record_property,
        "P_minus_M_as_complete_orders",
        [str(failure.value)],
        optional_delta={s: optional[s] for s in ("AAPL", "QQQ")},
        required_complete_delta={s: complete[s] for s in ("AAPL", "QQQ")},
        original_inventory_retained=True,
        intent_retained=True,
    )


def test_M01_M_then_P_cannot_be_two_accounting_phases(record_property):
    book, intent = required_exit()
    date = next_date(book)
    mandatory = [fill(book, intent, -2)]
    optional = [fill(book, intent, 1, symbol="QQQ", origin="QQQ_BASE")]
    # An actual M fill can be observed; it does not authorize a second P
    # accounting/execution phase for that same open. C06 is a daily observer,
    # not the future D1 net-order generator or an actual execution engine.
    first = observe(book, date, accounting(book, date, mandatory), mandatory)
    assert first["state"]["inventory"]["AAPL"] == 0
    assert first["state"]["inventory"]["QQQ"] == 0
    pending = book.pending_intents()
    row = accounting(book, date, optional)
    with pytest.raises(ValueError) as failure:
        observe(book, date, row, optional)
    assert str(failure.value) == "risk.missing_duplicate_or_nonadjacent_close"
    assert book.snapshot()["state"] == first["state"]
    assert book.pending_intents() == pending
    assert not book.snapshot()["complete"]
    record(
        record_property,
        "execute_M_then_execute_P",
        [str(failure.value)],
        first_actual_fill_observed=True,
        second_same_session_phase_accepted=False,
        P_inventory_not_fabricated=True,
    )


def test_M01_missing_state_cannot_be_defaulted_to_zero(record_property):
    book, _ = required_exit()
    before, pending = book.snapshot(), book.pending_intents()
    date = next_date(book)
    unknown = accounting(book, date, nav=None, rights={"AAPL": None})
    with pytest.raises(ValueError) as missing:
        observe(book, date, unknown, [])
    assert str(missing.value) == "state.R2_necessary_state_unknown"
    assert book.snapshot()["state"] == before["state"]
    assert book.pending_intents() == pending
    # A zero-filled replacement is not the host-bound unknown declaration.
    # Reuse its original expected SHA; do not bless the replacement by rehash.
    zeroed = deepcopy(unknown)
    zeroed.update(nav=0, rights={})
    zeroed["inventory"] = {s: 0 for s in zeroed["inventory"]}
    with pytest.raises(ValueError) as replacement:
        observe(
            book,
            date,
            zeroed,
            [],
            expected_accounting_sha256=digest(unknown),
        )
    assert str(replacement.value) == "risk.close_source_binding_mismatch"
    assert book.snapshot()["state"] == before["state"]
    assert book.pending_intents() == pending
    assert not book.snapshot()["complete"]
    declarations = json.loads(book.export_bytes())["declarations"]
    assert declarations[-2]["declaration"]["accounting"] == unknown
    assert declarations[-1]["declaration"]["accounting"] == zeroed
    assert all(row["status"] == "rejected" for row in declarations[-2:])
    record(
        record_property,
        "unknown_state_as_zero",
        [str(missing.value), str(replacement.value)],
        inventory_entitlements_and_intent_retained=True,
        unknown_declaration_retained=True,
    )

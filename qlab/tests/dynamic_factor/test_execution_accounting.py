"""C04 synthetic source facts only: no historical reference/strategy run."""

from copy import deepcopy
import json

import pytest

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.execution_accounting import ExecutionAccount, MODEL
from qlab.dynamic_factor.execution_numbers import amount
from qlab.dynamic_factor.execution_risk import RiskBook
from projection_test_helpers import case, ORACLE


def account():
    inputs, args, signal = case()
    risk = RiskBook(**args)
    book = ExecutionAccount(
        risk_book=risk,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="accepted_actual",
    )
    book.lock_projection(
        inputs,
        risk_signal=signal,
        expected_input_sha256=digest(inputs),
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        expected_signal_sha256=digest(signal),
        selected_plan="P",
        **selection(risk, inputs, "P"),
    )
    return book, inputs, args, signal


def facts(book, inputs):
    ticket = book.intent()["ticket"]
    ts = ticket["execution_session"] + "T14:30:00Z"
    return [
        dict(
            fill_id=key,
            order_id=key,
            book_id=ticket["book_id"],
            intent_sha256=ticket["intent_sha256"],
            symbol=row["symbol"],
            execution_session=ticket["execution_session"],
            quantity=row["quantity"],
            price=inputs["execution_open"]["raw_open"][row["symbol"]],
            source_sha256=digest("SYNTHETIC FILL"),
            executed_at=ts,
            confirmed_at=ts,
            cash_available_at=ts,
            origin="F1-L020",
        )
        for key, row in book.intent()["orders"].items()
    ]


def close_evidence(book, inputs):
    session = book.intent()["ticket"]["execution_session"]
    return dict(
        session=session,
        asof=session + "T20:00:00Z",
        prices=inputs["execution_open"]["raw_open"],
        source_sha256=digest("SYNTHETIC RAW CLOSE"),
        price_kind="verified_raw_close",
        rights_complete=True,
        cash_events_complete=True,
        execution_outcomes={
            k: dict(
                filled_quantity=r["filled"],
                status="verified_DAY_closed",
                source_sha256=digest("SYNTHETIC DAY CLOSE"),
            )
            for k, r in book.intent()["orders"].items()
            if r["session"] == session
        },
    )


def record(book, rows):
    return book.record_actual(rows, expected_fact_sha256=[digest(r) for r in rows])


def test_A19_CF01_actual_DUT_posts_original_seven_fees_once_no_optimizer_x1():
    book, inputs, *_ = account()
    rows = facts(book, inputs)
    record(book, rows)
    before = book.snapshot()
    record(book, rows)  # idempotent exact duplicate
    assert {
        k: v
        for k, v in book.snapshot().items()
        if k not in {"declarations", "account_sha256"}
    } == {
        k: v for k, v in before.items() if k not in {"declarations", "account_sha256"}
    }
    e = close_evidence(book, inputs)
    out = book.close_session(e, expected_evidence_sha256=digest(e))["receipt"]
    assert out["accounting"]["fees_x2"] == "17.4645981"
    assert out["accounting"]["cash"] == "857.5354019"
    assert out["accounting"]["nav"] == "14982.5354019"
    expected = json.loads((ORACLE / "CF01.expected.canonical.json").read_bytes())
    assert (
        sha256((ORACLE / "CF01.expected.canonical.json").read_bytes())
        == "b935b633e29830e30469d9f08bb2666bcb272c2bda2143b7011e7faecaa102b7"
    )
    assert expected["P"] == out["accounting"]["inventory"]
    assert out["x1_replay"]["same_orders_and_quantities"] is True
    assert out["x1_replay"]["additional_orders"] == []
    assert sum(
        (amount(r["fee_x2"]) for r in before["orders"].values()), amount(0)
    ) == amount("17.4645981")


def test_partial_fill_cumulative_fee_once_DAY_remainder_no_rollover():
    book, inputs, *_ = account()
    row = facts(book, inputs)[0]
    assert abs(row["quantity"]) > 1
    sign = 1 if row["quantity"] > 0 else -1
    a = dict(row, quantity=sign, fill_id="partial1")
    b = dict(row, quantity=row["quantity"] - sign, fill_id="partial2")
    record(book, [a])
    record(book, [b])
    one = next(iter(book.snapshot()["orders"].values()))
    assert one["filled"] == row["quantity"]
    assert amount(one["fee_x2"]) == book._fee(
        one, row["quantity"], abs(row["quantity"]) * amount(row["price"]), "x2"
    )
    e = close_evidence(book, inputs)
    out = book.close_session(e, expected_evidence_sha256=digest(e))["receipt"]
    assert len(out["cancelled_DAY_orders"]) == len(book.snapshot()["orders"])
    assert sum(abs(r["remaining"]) for r in out["cancelled_DAY_orders"]) > 0
    with pytest.raises(ValueError, match="current_DAY|scope_or_intent"):
        record(book, [dict(row, fill_id="next-day")])


@pytest.mark.parametrize(
    "mutation", ["price", "fractional", "time", "binding", "unavailable"]
)
def test_A14_A15_actual_bad_fact_retains_earlier_occurred_fill(mutation):
    book, inputs, *_ = account()
    rows = facts(book, inputs)
    first, bad = rows[0], rows[2]
    before = deepcopy(first)
    if mutation == "price":
        bad["price"] = None
    elif mutation == "fractional":
        bad["quantity"] = 0.5
    elif mutation == "time":
        bad["confirmed_at"] = "2000-01-01T14:30:00Z"
    elif mutation == "binding":
        bad["book_id"] = digest("another ledger")
    else:
        bad["cash_available_at"] = bad["confirmed_at"][:10] + "T23:30:00Z"
    with pytest.raises(ValueError):
        record(book, [first, bad])
    result = book.snapshot()
    assert (
        result["complete"] is False and result["NAV"] is None and result["cash"] is None
    )
    assert (
        result["facts"][0]["fact"] == before
        and result["facts"][-1]["status"] == "REJECTED"
    )
    assert (
        result["retained_state"]["inventory"][first["symbol"]]
        == inputs["close_state"]["inventory"][first["symbol"]] + first["quantity"]
    )


def test_A14_missing_close_price_does_not_discard_account_or_intent():
    book, inputs, *_ = account()
    record(book, facts(book, inputs))
    before = book.snapshot()
    e = close_evidence(book, inputs)
    e["prices"] = {}
    with pytest.raises(ValueError, match="close_price_unknown"):
        book.close_session(e, expected_evidence_sha256=digest(e))
    assert book.snapshot()["retained_state"] == before["retained_state"]
    assert book.snapshot()["NAV"] is None


def test_N2_model_cannot_enter_forward_account():
    book, *_ = account()
    with pytest.raises(ValueError, match="named_training_model_only"):
        book.model_open({}, expected_evidence_sha256=digest({}), model_name=MODEL)


def training_account(member="F1-L020", recipe="F1-L020", role="candidate_solo_probe"):
    inputs, args, signal = case(role=role, member=member, recipe=recipe)
    inputs["locked_signal"]["recipe_id"] = recipe
    for symbol in args["state"]["origin"]:
        if symbol != "QQQ":
            args["state"]["origin"][symbol] = recipe
            inputs["close_state"]["origin"][symbol] = recipe
    policy = args["policy"]
    start = policy.fold_manifest()["folds"][0]["train_start"]
    i = policy.calendar.index(start) + 30
    date = policy.calendar[i]
    opened = policy.calendar[i + 1]
    args["scope"].update(kind="independent_training", fold_id="0")
    args["state"]["asof"] = date + "T20:00:00Z"
    args["state"]["_risk_clock"].update(
        close_session=date,
        global_start=start,
        entries={
            s: policy.calendar[i - args["state"]["age"][s] + 1]
            for s, q in args["state"]["inventory"].items()
            if q and s != "QQQ"
        },
    )
    args.update(
        close_session=date, expected_original_state_sha256=digest(args["state"])
    )
    args["prior_risk"]["close_session"] = policy.calendar[i - 1]
    args["expected_prior_risk_sha256"] = digest(args["prior_risk"])
    inputs["close_state"].update(
        signal_close_session=date, execution_open_session=opened
    )
    inputs["execution_open"]["session"] = opened
    inputs["locked_signal"]["signal_session"] = date
    signal.update(signal_session=date, execution_session=opened)
    risk = RiskBook(**args)
    assert risk.snapshot()["complete"], risk.snapshot()["reasons"]
    book = ExecutionAccount(
        risk_book=risk,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="named_training_diagnostic",
    )
    book.lock_projection(
        inputs,
        risk_signal=signal,
        expected_input_sha256=digest(inputs),
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        expected_signal_sha256=digest(signal),
        selected_plan="P",
        **selection(risk, inputs, "P"),
    )
    return book, inputs, args, signal


def test_N2_named_training_model_same_orders_not_verified_actual():
    book, inputs, *_ = training_account()
    date = book.intent()["ticket"]["execution_session"]
    e = dict(
        session=date,
        prices=inputs["execution_open"]["raw_open"],
        source_sha256=digest("SYNTHETIC RAW OPEN"),
        price_kind="verified_tradable_raw_open",
        asof=date + "T14:30:00Z",
    )
    e["origins"] = model_origins(book)
    receipt = book.model_open(e, expected_evidence_sha256=digest(e), model_name=MODEL)
    assert receipt["execution_verified"] is False
    assert all(r["filled"] == r["quantity"] for r in book.snapshot()["orders"].values())
    assert book.snapshot()["fees_x2"] == "17.4645981"
    with pytest.raises(ValueError, match="cannot_be_actual"):
        record(book, [])


def test_N2_missing_late_price_rolls_back_only_hypothetical_batch():
    book, inputs, *_ = training_account()
    before = book.snapshot()
    date = book.intent()["ticket"]["execution_session"]
    prices = deepcopy(inputs["execution_open"]["raw_open"])
    del prices["QQQ"]
    e = dict(
        session=date,
        prices=prices,
        source_sha256=digest("SYNTHETIC"),
        price_kind="verified_tradable_raw_open",
        asof=date + "T14:30:00Z",
    )
    e["origins"] = model_origins(book)
    with pytest.raises(ValueError, match="necessary_price_unknown|raw_open_differs"):
        book.model_open(e, expected_evidence_sha256=digest(e), model_name=MODEL)
    after = book.snapshot()
    assert after["facts"] == before["facts"] and after["orders"] == before["orders"]
    assert after["NAV"] is None and after["fees_x2"] == "0"


def test_A15_sale_not_spendable_until_actual_available_receipt():
    book, inputs, *_ = account()
    row = facts(book, inputs)[0]
    row["cash_available_at"] = row["execution_session"] + "T18:00:00Z"
    oldcash = book.snapshot()["cash"]
    record(book, [row])
    state = book.snapshot()
    assert state["cash"] == oldcash
    receivable = state["retained_state"]["receivables"][row["fill_id"]]
    assert amount(receivable["amount"]) == abs(row["quantity"]) * amount(
        row["price"]
    ) - amount(state["fees_x2"])
    ts = row["cash_available_at"]
    payment = dict(
        receivable_id=row["fill_id"],
        book_id=row["book_id"],
        kind="cash_available",
        symbol=row["symbol"],
        cash_basis="integer_pre_tax_cash",
        amount=receivable["amount"],
        available_at=ts,
        confirmed_at=ts,
        source_sha256=digest("SYNTHETIC ACTUAL AVAILABLE CASH"),
    )
    result = book.settle_cash(payment, expected_event_sha256=digest(payment), asof=ts)
    assert amount(result["cash"]) == amount(oldcash) + amount(receivable["amount"])
    assert (
        result["retained_state"]["receivables"][row["fill_id"]]["payment_state"]
        == "PAID"
    )
    assert (
        result["retained_state"]["receivables"][row["fill_id"]]["source_sha256"]
        == row["source_sha256"]
    )


@pytest.mark.parametrize(
    "cash_basis", ["analytical_fractional_TR", "integer_DRIP", "fractional_DRIP"]
)
def test_A16_fractional_TR_cannot_be_integer_cash_or_free_DRIP(cash_basis):
    book, inputs, *_ = account()
    date = book.intent()["ticket"]["execution_session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis=cash_basis,
        declared_cash_amount="1",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC"),
    )
    before = book.snapshot()
    with pytest.raises(ValueError, match="source_or_units_unknown"):
        book.record_cash_events(
            [event], session=date, expected_event_sha256=[digest(event)]
        )
    after = book.snapshot()
    assert after["retained_state"] == before["retained_state"] and after["NAV"] is None


def test_A15_known_cash_entitlement_from_previous_close_not_ex_open_inventory():
    book, inputs, *_ = account()
    date = book.intent()["ticket"]["execution_session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="0.123456789",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC"),
    )
    book.record_cash_events(
        [event], session=date, expected_event_sha256=[digest(event)]
    )
    assert (
        book.snapshot()["retained_state"]["receivables"]["DIV"]["amount"]
        == "0.493827156"
    )
    assert book.snapshot()["cash"] == inputs["close_state"]["cash"]
    record(book, facts(book, inputs))
    assert book.snapshot()["retained_state"]["inventory"]["COP"] == 3
    assert (
        book.snapshot()["retained_state"]["receivables"]["DIV"]["entitlement_shares"]
        == 4
    )
    e = close_evidence(book, inputs)
    result = book.close_session(e, expected_evidence_sha256=digest(e))
    assert result["receipt"]["accounting"]["nav"] == "14983.029229056"
    assert result["cash_proof"].value == amount("0.493827156")


def test_A13_unknown_non_cash_right_preserved_R2_not_zeroed():
    book, *_ = account()
    event = dict(kind="split", ratio=None, source_sha256=digest("SYNTHETIC"))
    result = book.record_unknown_right(event, expected_event_sha256=digest(event))
    assert result["retained_state"]["rights"][digest(event)] == event
    assert (
        result["NAV"] is None and result["cash"] is None and result["complete"] is False
    )


def test_no_verified_DAY_outcome_cannot_assume_zero_execution():
    book, inputs, *_ = account()
    e = close_evidence(book, inputs)
    e["execution_outcomes"] = {}
    with pytest.raises(ValueError, match="no_assumed_zero_fill"):
        book.close_session(e, expected_evidence_sha256=digest(e))
    assert book.snapshot()["NAV"] is None


def test_C05_C04_C06_three_startup_days_one_account_and_one_risk_path():
    from test_execution_startup import book as startup
    from test_execution_risk_history import history
    from qlab.dynamic_factor.execution_risk_history import RiskHistory
    from qlab.dynamic_factor.conventions import load_conventions

    p = load_conventions()
    seed, args = history("CREF-F1-L020")
    source = startup("CREF-F1-L020")
    args["book_id"] = source.book_id
    hist = RiskHistory(**args)
    ledger = ExecutionAccount(
        risk_book=hist._book,
        expected_snapshot_sha256=hist.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="named_training_diagnostic",
    )
    proofs = {}
    for i in range(3):
        source.prepare_next_open()
        date = source.sessions[i + 1]
        source.execute_open(date + "T14:30:00Z", lambda date, symbol: 100)
        ledger.lock_startup(source, expected_source_sha256=digest(source.snapshot()))
        evidence = dict(
            session=date,
            asof=date + "T14:30:00Z",
            prices={"QQQ": "100"},
            source_sha256=digest(["SYNTHETIC", i]),
            price_kind="verified_tradable_raw_open",
        )
        evidence["origins"] = model_origins(ledger)
        ledger.model_open(
            evidence, expected_evidence_sha256=digest(evidence), model_name=MODEL
        )
        close = close_evidence(ledger, {"execution_open": {"raw_open": {"QQQ": "100"}}})
        out = ledger.close_session(close, expected_evidence_sha256=digest(close))
        a = out["receipt"]["accounting"]
        fills = out["receipt"]["fills"]
        risk = hist.observe_close(
            date,
            a,
            fills,
            expected_accounting_sha256=digest(a),
            expected_fills_sha256=digest(fills),
            cash_proof=out["cash_proof"],
        )
        assert risk["complete"] is True and risk["risk"]["risk_latch"] is False
        assert risk["state"]["inventory"] == a["inventory"]
        assert risk["state"]["nav"] == a["nav"]
        ledger.bind_next_risk(
            hist._book, expected_snapshot_sha256=risk["snapshot_sha256"]
        )
        proofs[out["cash_proof"].sha256] = out["cash_proof"]
        source.close_session(
            date + "T20:00:00Z",
            100,
            dict(rights_value=0, receivables_value=0, components_known=True),
        )
        assert source.snapshot()["complete_account_state"] is None
    assert amount(hist.snapshot()["state"]["cash"]) > 0
    assert hist.snapshot()["state"]["age"]["QQQ"] == 0
    # Hold through positions 3/4/5, then consume the actual sole D1 and D2
    # intent together. No helper-authored M/quantities or P-M posting.
    for _ in range(3):
        date = p.calendar[p.calendar.index(hist.snapshot()["close_session"]) + 1]
        e = dict(
            session=date,
            asof=date + "T20:00:00Z",
            prices={"QQQ": "100"},
            source_sha256=digest("SYNTHETIC CLOSE"),
            price_kind="verified_raw_close",
            rights_complete=True,
            cash_events_complete=True,
            execution_outcomes={},
        )
        out = ledger.close_session(e, expected_evidence_sha256=digest(e))
        a = out["receipt"]["accounting"]
        result = hist.observe_close(
            date,
            a,
            [],
            expected_accounting_sha256=digest(a),
            expected_fills_sha256=digest([]),
            cash_proof=out["cash_proof"],
        )
        proofs[out["cash_proof"].sha256] = out["cash_proof"]
        ledger.bind_next_risk(
            hist._book, expected_snapshot_sha256=result["snapshot_sha256"]
        )
    inputs, _, risk_signal = case()
    snap = hist.snapshot()
    state = snap["state"]
    date = snap["close_session"]
    opened = p.calendar[p.calendar.index(date) + 1]
    inputs["schema"] = "EVO884.ProjectorInput/v1"
    inputs["close_state"].update(
        inventory=deepcopy(state["inventory"]),
        cash=state["cash"],
        NAV_anchor=state["nav"],
        age=state["age"],
        origin=state["origin"],
        rights=state["rights"],
        receivables=state["receivables"],
        signal_close_session=date,
        execution_open_session=opened,
        verified_close_peak=snap["risk"]["peak"],
        prior_risk_latch=snap["risk"]["risk_latch"],
    )
    inputs["execution_open"].update(
        session=opened, cash_availability=dict(mode="research_immediate")
    )
    inputs["locked_signal"]["signal_session"] = date
    risk_signal.update(
        book_id=source.book_id, signal_session=date, execution_session=opened
    )
    prepared = hist.prepare_open(
        risk_signal,
        expected_signal_sha256=digest(risk_signal),
        expected_snapshot_sha256=snap["snapshot_sha256"],
    )
    ticket = ledger.lock_projection(
        inputs,
        risk_signal=risk_signal,
        expected_input_sha256=digest(inputs),
        expected_snapshot_sha256=snap["snapshot_sha256"],
        expected_signal_sha256=digest(risk_signal),
        selected_plan="P",
        **selection(hist._book, inputs, "P"),
    )
    assert ticket["ticket"]["intent_sha256"] == prepared["intent"]["intent_sha256"]
    e = dict(
        session=opened,
        asof=opened + "T14:30:00Z",
        prices=inputs["execution_open"]["raw_open"],
        source_sha256=digest("SYNTHETIC RAW OPEN"),
        price_kind="verified_tradable_raw_open",
        origins=model_origins(ledger),
    )
    ledger.model_open(e, expected_evidence_sha256=digest(e), model_name=MODEL)
    e = close_evidence(ledger, inputs)
    out = ledger.close_session(e, expected_evidence_sha256=digest(e))
    a = out["receipt"]["accounting"]
    fills = out["receipt"]["fills"]
    result = hist.observe_close(
        opened,
        a,
        fills,
        expected_accounting_sha256=digest(a),
        expected_fills_sha256=digest(fills),
        cash_proof=out["cash_proof"],
    )
    proofs[out["cash_proof"].sha256] = out["cash_proof"]
    assert result["complete"] is True and any(
        q for name, q in a["inventory"].items() if name != "QQQ"
    )
    assert result["state"]["cash"] == a["cash"] and result["state"]["nav"] == a["nav"]
    raw = hist.export_bytes()
    restored = RiskHistory.restore(
        raw,
        expected_sha256=sha256(raw),
        expected_book_id=source.book_id,
        expected_scope=args["scope"],
        cash_proofs=proofs,
        policy=p,
    )
    assert restored.export_bytes() == raw
    with pytest.raises(ValueError, match="history_replay_mismatch"):
        RiskHistory.restore(
            raw,
            expected_sha256=sha256(raw),
            expected_book_id=source.book_id,
            expected_scope=args["scope"],
            policy=p,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "paydate_unknown",
        "null_amount",
        "no_timezone",
        "late_payment",
        "wrong_entitlement",
    ],
)
def test_A15_cash_unknowns_reject_no_free_credit_and_preserve_declarations(mutation):
    book, inputs, *_ = account()
    date = book.intent()["ticket"]["execution_session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="0.5",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC"),
    )
    if mutation == "paydate_unknown":
        event["pay_date"] = None
        book.record_cash_events(
            [event], session=date, expected_event_sha256=[digest(event)]
        )
        assert book.snapshot()["retained_state"]["receivables"]["DIV"]["amount"] == "2"
    elif mutation in {"null_amount", "wrong_entitlement"}:
        if mutation == "null_amount":
            event["declared_cash_amount"] = None
        else:
            event["entitled_integer_shares"] = 3
        with pytest.raises(ValueError):
            book.record_cash_events(
                [event], session=date, expected_event_sha256=[digest(event)]
            )
    else:
        book.record_cash_events(
            [event], session=date, expected_event_sha256=[digest(event)]
        )
        payment = dict(
            receivable_id="DIV",
            book_id=event["book_id"],
            kind="cash_available",
            symbol="COP",
            cash_basis="integer_pre_tax_cash",
            amount="2",
            available_at=date + "T18:00:00Z",
            confirmed_at=date + "T18:00:00Z",
            source_sha256=digest("SYNTHETIC"),
        )
        if mutation == "no_timezone":
            payment["available_at"] = date + "T18:00:00"
        else:
            payment["confirmed_at"] = date + "T23:00:00Z"
        with pytest.raises(ValueError):
            book.settle_cash(
                payment, expected_event_sha256=digest(payment), asof=date + "T20:00:00Z"
            )
        assert book.snapshot()["retained_state"]["receivables"]["DIV"]["amount"] == "2"
    result = book.snapshot()
    assert result["cash"] is None and result["NAV"] is None
    assert result["retained_state"]["cash"] == inputs["close_state"]["cash"] or amount(
        result["retained_state"]["cash"]
    ) == amount(inputs["close_state"]["cash"])


def test_A19_M_selection_uses_original_inventory_not_P_minus_M():
    inputs, args, signal = case()
    risk = RiskBook(**args)
    book = ExecutionAccount(
        risk_book=risk,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="accepted_actual",
    )
    out = book.lock_projection(
        inputs,
        risk_signal=signal,
        expected_input_sha256=digest(inputs),
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        expected_signal_sha256=digest(signal),
        selected_plan="M",
        **selection(risk, inputs, "M"),
    )
    assert out["ticket"]["orders"] == [{"symbol": "CVS", "quantity": -3}]
    assert {r["symbol"] for r in out["orders"].values()} == {"CVS"}


def test_cash_proof_cannot_be_wire_dict_or_rebound_to_other_book():
    from qlab.dynamic_factor.noncash_v3 import zero_exposure
    from qlab.dynamic_factor.execution_cash import check_cash_state

    book, inputs, args, _ = account()
    date = book.intent()["ticket"]["execution_session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="0.5",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC"),
    )
    book.record_cash_events(
        [event], session=date, expected_event_sha256=[digest(event)]
    )
    e = close_evidence(book, inputs)
    out = book.close_session(e, expected_evidence_sha256=digest(e))
    state = deepcopy(book.snapshot()["retained_state"])
    check_cash_state(state, args["guard"], out["cash_proof"])
    with pytest.raises(ValueError, match="old_rights"):
        zero_exposure(state, args["guard"])
    with pytest.raises(ValueError):
        check_cash_state(state, args["guard"], {"verified": True})
    state["_risk_clock"]["book_id"] = digest("other ledger")
    with pytest.raises(ValueError):
        check_cash_state(state, args["guard"], out["cash_proof"])


def model_origins(book):
    state = book.snapshot()["retained_state"]
    return {
        r["symbol"]: "QQQ_BASE"
        if r["symbol"] == "QQQ"
        else state["origin"].get(r["symbol"], book._scope["recipe_id"])
        for r in book.intent()["orders"].values()
    }


def test_A14_frozen_fee_file_drift_rejected_before_second_actual_post(
    tmp_path, monkeypatch
):
    from qlab.dynamic_factor import execution

    book, inputs, *_ = account()
    rows = facts(book, inputs)
    record(book, [rows[0]])
    before = book.snapshot()
    (tmp_path / "fee_params_x2.json").write_text("{}")
    monkeypatch.setattr(execution, "FIXTURES", tmp_path)
    with pytest.raises(ValueError, match="fee_params_not_bound"):
        record(book, [rows[1]])
    result = book.snapshot()
    assert result["fees_x2"] == before["fees_x2"]
    assert (
        result["retained_state"]["inventory"] == before["retained_state"]["inventory"]
    )
    assert result["NAV"] is None


def test_N1_ambient_Decimal_context_cannot_change_accepted_fee_lexemes():
    from decimal import localcontext

    book, inputs, *_ = account()
    with localcontext() as context:
        context.prec = 2
        record(book, facts(book, inputs))
        e = close_evidence(book, inputs)
        out = book.close_session(e, expected_evidence_sha256=digest(e))["receipt"]
    assert out["accounting"]["fees_x2"] == "17.4645981"
    assert out["accounting"]["cash"] == "857.5354019"
    assert out["accounting"]["nav"] == "14982.5354019"


def test_N2_model_cannot_change_D1_locked_open_prices():
    book, inputs, *_ = training_account()
    date = book.intent()["ticket"]["execution_session"]
    prices = deepcopy(inputs["execution_open"]["raw_open"])
    prices["QQQ"] = "99"
    e = dict(
        session=date,
        prices=prices,
        source_sha256=digest("SYNTHETIC"),
        price_kind="verified_tradable_raw_open",
        asof=date + "T14:30:00Z",
        origins=model_origins(book),
    )
    with pytest.raises(ValueError, match="differs_from_sole_D1"):
        book.model_open(e, expected_evidence_sha256=digest(e), model_name=MODEL)
    assert book.snapshot()["facts"] == []


@pytest.mark.parametrize(
    "lineage",
    [
        {"dependency_graph": 1},
        {"wrapper": {"dependency_graph": 1}},
        {"ancestry": {}},
        {"Dependency_Graph": []},
    ],
)
def test_A15_cash_event_unknown_lineage_cannot_be_treated_as_empty(lineage):
    book, inputs, *_ = account()
    date = book.intent()["ticket"]["execution_session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="0.5",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC"),
        **lineage,
    )
    with pytest.raises(ValueError, match="unknown_lineage_structure"):
        book.record_cash_events(
            [event], session=date, expected_event_sha256=[digest(event)]
        )
    assert book.snapshot()["NAV"] is None
    assert book.snapshot()["declarations"][-1]["args"][0][0] == event


def selection(risk, inputs, chosen):
    snap = risk.snapshot()
    receipt = dict(
        book_id=snap["book_id"],
        close_session=snap["close_session"],
        execution_session=inputs["execution_open"]["session"],
        input_sha256=digest(inputs),
        snapshot_sha256=snap["snapshot_sha256"],
        selected_plan=chosen,
        execution_role=snap["scope"]["execution_role"],
        decision_source_sha256=digest("SYNTHETIC FINAL SELECTION"),
    )
    return dict(selection_receipt=receipt, expected_selection_sha256=digest(receipt))


@pytest.mark.parametrize(
    "member,recipe,role",
    [
        ("F1-L020", "F1-L020", "candidate_solo_probe"),
        ("CREF-F1-L020", "F1-L020", "independent_candidate_reference"),
        ("CREF-F3-L020", "F3-L020", "independent_candidate_reference"),
        ("MREF-F4-L020", "F4-L020", "independent_meta_reference_probe_component"),
        ("MREF-F2-L020", "F2-L020", "independent_meta_reference_probe_component"),
    ],
)
def test_N2_four_reference_roles_and_candidate_use_one_same_model(member, recipe, role):
    book, inputs, *_ = training_account(member, recipe, role)
    date = book.intent()["ticket"]["execution_session"]
    evidence = dict(
        session=date,
        prices=inputs["execution_open"]["raw_open"],
        source_sha256=digest("SYNTHETIC RAW OPEN"),
        price_kind="verified_tradable_raw_open",
        asof=date + "T14:30:00Z",
        origins=model_origins(book),
    )
    out = book.model_open(
        evidence, expected_evidence_sha256=digest(evidence), model_name=MODEL
    )
    assert out["execution_verified"] is False
    assert (
        out["execution_closure_sha256"]
        == "7677b123fa2fe573343fad3fe3f43887c5f5d2c0fd7c12d9a1de8bc625162e1b"
    )
    assert book.snapshot()["fees_x2"] == "17.4645981"


def test_N1_original_seven_order_fee_lexemes_preserved_individually():
    book, inputs, *_ = account()
    record(book, facts(book, inputs))
    actual = {r["symbol"]: r["fee_x2"] for r in book.snapshot()["orders"].values()}
    assert actual == {
        "CVS": "2.34143962",
        "COP": "2.28834654",
        "COST": "2.29674654",
        "AAPL": "2.38783962",
        "AMZN": "2.33929308",
        "ABBV": "2.4109327",
        "QQQ": "3.4",
    }


def test_A19_host_final_selection_cannot_be_replaced_or_changed():
    inputs, args, signal = case()
    risk = RiskBook(**args)
    book = ExecutionAccount(
        risk_book=risk,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="accepted_actual",
    )
    receipt = selection(risk, inputs, "P")
    receipt["selection_receipt"]["selected_plan"] = "M"
    with pytest.raises(ValueError, match="host_bound_final_selection_required"):
        book.lock_projection(
            inputs,
            risk_signal=signal,
            expected_input_sha256=digest(inputs),
            expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
            expected_signal_sha256=digest(signal),
            selected_plan="P",
            **receipt,
        )
    assert book.intent()["orders"] == {} and book.snapshot()["facts"] == []


def test_account_close_wire_schema_closed_no_x1_orders_or_root_extension():
    from pathlib import Path
    import jsonschema
    import qlab.dynamic_factor.execution_accounting as producer

    path = (
        Path(producer.__file__).parent
        / "fixtures/execution-accounting/account-close.schema.json"
    )
    schema = json.loads(path.read_text())
    book, inputs, *_ = account()
    record(book, facts(book, inputs))
    e = close_evidence(book, inputs)
    receipt = book.close_session(e, expected_evidence_sha256=digest(e))["receipt"]
    jsonschema.validate(receipt, schema)
    for bad in [
        dict(receipt, extra=1),
        dict(
            receipt,
            x1_replay=dict(receipt["x1_replay"], additional_orders=[{"symbol": "QQQ"}]),
        ),
    ]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


@pytest.mark.parametrize(
    "case", ["price", "fee", "B", "model-forward", "paydate", "TR", "rights"]
)
def test_A13_A14_A15_A16_real_subprocess_rejection_observations(case, record_property):
    from pathlib import Path
    import os
    import subprocess
    import sys

    worker = Path(__file__).with_name("accounting_boundary_worker.py")
    process = subprocess.run(
        [sys.executable, "-B", str(worker), "--case", case],
        env=dict(os.environ, PYTHONPATH=""),
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    value = json.loads(process.stdout)
    assert value["complete"] is False and value["NAV"] is None and value["reasons"]
    assert (
        value["reader_calls"] == 0
        and value["worker_calls"] == 0
        and value["accessed_roles"] == []
    )
    if case in {"price", "fee", "B"}:
        assert value["accepted_facts"] == 1
    if case == "paydate":
        assert value["retained_receivables"]["DIV"]["amount"] == "2"
    if case == "rights":
        assert value["retained_rights"]
    record_property("C04_observation", json.dumps(value, sort_keys=True))


def test_N2_verified_zero_execution_preserves_stock_and_DAY_intent_no_fees():
    book, inputs, *_ = account()
    before = book.snapshot()
    ticket = book.intent()["ticket"]
    e = close_evidence(book, inputs)
    result = book.close_session(e, expected_evidence_sha256=digest(e))["receipt"]
    assert result["accounting"]["inventory"] == before["retained_state"]["inventory"]
    assert result["accounting"]["cash"] == before["cash"]
    assert result["accounting"]["fees_x2"] == "0" and result["fills"] == []
    assert any(r["remaining"] for r in result["cancelled_DAY_orders"])
    assert (
        ticket["execution_session"] == e["session"] and book.intent()["ticket"] is None
    )
    journal = json.loads(book.export_bytes())
    assert journal["closes"] == book.close_receipts()
    assert journal["snapshot"]["orders"] == book.snapshot()["orders"]


def test_concurrent_duplicate_actual_receipt_charges_one_order_once():
    from concurrent.futures import ThreadPoolExecutor

    book, inputs, *_ = account()
    row = facts(book, inputs)[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: record(book, [row]), range(8)))
    out = book.snapshot()
    assert len(out["facts"]) == 1
    assert out["fees_x2"] == "2.34143962"
    assert out["retained_state"]["inventory"]["CVS"] == 0


def test_issued_cash_proof_is_immutable_exact_state_capability():
    book, inputs, *_ = account()
    e = close_evidence(book, inputs)
    out = book.close_session(e, expected_evidence_sha256=digest(e))
    with pytest.raises(ValueError, match="immutable"):
        out["cash_proof"]._ledger_sha = digest("other ledger")


def test_N3_new_unspendable_entitlement_cannot_bypass_post_buy_two_percent():
    book, inputs, *_ = account()
    date = book.intent()["ticket"]["execution_session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="100000",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC ADVERSARIAL ONLY"),
    )
    book.record_cash_events(
        [event], session=date, expected_event_sha256=[digest(event)]
    )
    rows = facts(book, inputs)
    with pytest.raises(ValueError, match="post_buy_cash_or_investment_limit"):
        record(book, rows)
    result = book.snapshot()
    assert result["NAV"] is None
    assert result["retained_state"]["receivables"]["DIV"]["amount"] == "400000"
    assert sum(r["status"] == "ACCEPTED_ACTUAL" for r in result["facts"]) == 2
    assert result["retained_state"]["inventory"]["CVS"] == 0
    assert result["retained_state"]["inventory"]["COP"] == 3
    assert result["retained_state"]["inventory"]["COST"] == 0


def test_N3_actual_price_slippage_cannot_bypass_post_buy_two_percent():
    book, inputs, *_ = account()
    rows = facts(book, inputs)
    row = rows[-1]
    # Sells and satellite buys were accepted. The final actual QQQ cost is
    # still cash-positive, but breaches the frozen 2% post-fee NAV buffer.
    row["price"] = "140"
    with pytest.raises(ValueError, match="post_buy_cash_or_investment_limit"):
        record(book, rows)
    result = book.snapshot()
    assert result["NAV"] is None and result["cash"] is None
    assert sum(r["status"] == "ACCEPTED_ACTUAL" for r in result["facts"]) == 6
    assert result["retained_state"]["inventory"]["QQQ"] == 100


def test_known_exdate_cash_before_order_lock_still_requires_current_valuation():
    inputs, args, _ = case()
    risk = RiskBook(**args)
    book = ExecutionAccount(
        risk_book=risk,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="accepted_actual",
    )
    date = inputs["execution_open"]["session"]
    event = dict(
        event_id="DIV",
        book_id=book.snapshot()["book_id"],
        kind="cash_dividend",
        symbol="COP",
        ex_date=date,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="0.5",
        pay_date=date,
        entitled_integer_shares=4,
        source_sha256=digest("SYNTHETIC"),
    )
    result = book.record_cash_events(
        [event], session=date, expected_event_sha256=[digest(event)]
    )
    assert book.intent()["ticket"] is None
    assert result["complete"] is False and result["NAV"] is None
    assert (
        result["cash"] == "3900"
        and result["retained_state"]["receivables"]["DIV"]["amount"] == "2"
    )
    assert "accounting.close_pending" in result["reasons"]

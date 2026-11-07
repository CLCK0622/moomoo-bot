"""C05 / A07, A08, A13: synthetic accounting only, no reference execution."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event

import pytest

from qlab.dynamic_factor.contract import canonical, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_startup import StartupBook
from qlab.dynamic_factor.execution_closure import (
    ADOPTED_SHA256 as CLOSURE_SHA,
    adopted_execution_binding,
)
from qlab.dynamic_factor.reference_registry_v3 import DISPATCH
from qlab.dynamic_factor.v1_harness import unit_context


def initial_state(policy, fold_id="0"):
    fold = next(f for f in policy.fold_manifest()["folds"] if f["fold_id"] == fold_id)
    previous = policy.calendar[policy.calendar.index(fold["train_start"]) - 1]
    return dict(
        asof=previous + "T20:00:00Z",
        inventory={s: 0 for s in sorted(set(policy.profile["universe"]) | {"QQQ"})},
        cash=15000,
        nav=15000,
        fees_x2=0,
        age={},
        origin={},
        rights={},
        receivables={},
        pending_orders=[],
        unknown_components=[],
        initialization_count=1,
        peak=15000,
        risk_latch=False,
    )


def book(member="CREF-F1-L020", fold="0", attempt="C05-SYNTHETIC-ONLY", state=None):
    policy = load_conventions()
    return StartupBook(
        member,
        fold,
        attempt,
        initial_state(policy, fold) if state is None else state,
        unit_context(policy),
        execution_binding=adopted_execution_binding(
            expected_adoption_sha256=CLOSURE_SHA
        ),
        policy=policy,
    )


def day(ledger, position, price=100, close=100, *, valuation=None):
    intent = ledger.prepare_next_open()
    reads = []

    def reader(date, symbol):
        reads.append((date, symbol))
        assert symbol == "QQQ"
        return price

    date = ledger.sessions[position + 1]
    opened = ledger.execute_open(date + "T13:30:00Z", reader)
    marked = ledger.close_session(
        date + "T20:00:00Z",
        close,
        valuation or dict(rights_value=0, receivables_value=0, components_known=True),
    )
    return intent, opened, marked, reads


@pytest.mark.parametrize("member", sorted(DISPATCH))
def test_A07_three_startup_opens_account_frozen_fees_cash_drag_and_no_warmup(
    member, record_property
):
    ledger = book(member)
    seed = ledger.snapshot()
    assert (
        seed["genesis"]["cash"]
        == seed["genesis"]["nav"]
        == seed["genesis"]["peak"]
        == 15000
    )
    assert seed["genesis"]["risk_latch"] is False and set(
        seed["account_state"]["inventory"].values()
    ) == {0}
    outputs = []
    for position in range(3):
        intent, opened, closed, reads = day(
            ledger, position, close=101 if position == 0 else 100
        )
        assert intent["position"] == position
        assert intent["max_buy_notional"] == pytest.approx(0.4 * closed["previous_nav"])
        assert reads == [(ledger.sessions[position + 1], "QQQ")]
        assert opened["one_way_turnover"] <= 0.20
        assert type(opened["quantity"]) is int and opened["fee_x2"] > 0
        assert (
            closed["cash"] == opened["cash"]
            and closed["inventory"]["QQQ"] == opened["inventory"]["QQQ"]
        )
        assert closed["nav"] == pytest.approx(
            closed["cash"]
            + closed["inventory"]["QQQ"] * (101 if position == 0 else 100)
        )
        assert closed["day_return"] == closed["nav"] / closed["previous_nav"] - 1
        outputs.append(
            dict(intent=intent, opened=opened, closed=closed, reader_calls=reads)
        )
        # Durable bytes are sufficient to reconstruct the actual book; no
        # unverified terminal NAV or state is supplied to the restored object.
        raw = ledger.export_bytes()
        restored = StartupBook.restore(
            raw,
            expected_sha256=sha256(raw),
            member_id=member,
            fold_id="0",
            attempt_id="C05-SYNTHETIC-ONLY",
        )
        assert (
            restored.export_bytes() == raw and restored.snapshot() == ledger.snapshot()
        )
        ledger = restored
    first = outputs[0]
    assert first["opened"]["quantity"] == 60
    assert first["closed"]["nav"] == pytest.approx(
        15000 + 60 - first["opened"]["fee_x2"]
    )
    assert 0 < first["closed"]["day_return"] < 0.01  # cash drag + fees; no warmup gain
    assert ledger.snapshot()["account_state"]["fees_x2"] == pytest.approx(
        sum(r["opened"]["fee_x2"] for r in outputs)
    )
    assert ledger.snapshot()["startup_complete"] is True
    assert ledger.snapshot()["current_risk_state"] is None  # no invented C06 transition
    record_property("C05_A07_actual", json.dumps(outputs, sort_keys=True))


def test_A08_unfilled_three_days_cannot_extend_or_topup():
    ledger = book()
    for pos in range(3):
        _, opened, closed, _ = day(ledger, pos, price=10**8, close=10**8)
        assert opened["quantity"] == opened["fee_x2"] == 0
        assert closed["nav"] == closed["cash"] == 15000
    before = ledger.export_bytes()
    with pytest.raises(ValueError, match="no_extension_or_topup"):
        ledger.prepare_next_open()
    reads = []
    with pytest.raises(ValueError, match="no_extension_or_topup"):
        ledger.execute_open(
            ledger.sessions[4] + "T13:30:00Z", lambda *a: reads.append(a)
        )
    assert reads == [] and ledger.export_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "cash",
        "inventory",
        "rights",
        "receivables",
        "pending",
        "unknown",
        "missing",
        "peak",
        "latch",
        "old_close",
        "initialization_count",
        "ancestry",
    ],
)
def test_A13_initial_state_must_be_complete_zero_and_never_erase_exposure(mutation):
    policy = load_conventions()
    state = initial_state(policy)
    if mutation == "cash":
        state["cash"] = 14999
    elif mutation == "inventory":
        state["inventory"]["B"] = 1
    elif mutation in ("rights", "receivables"):
        state[mutation]["QQQ"] = 1
    elif mutation == "pending":
        state["pending_orders"] = [dict(symbol="B", quantity=1)]
    elif mutation == "unknown":
        state["unknown_components"] = ["historical_rights"]
    elif mutation == "missing":
        del state["inventory"]["B"]
    elif mutation == "peak":
        state["peak"] = None
    elif mutation == "latch":
        state["risk_latch"] = None
    elif mutation == "old_close":
        state["asof"] = "2013-10-29T20:00:00Z"
    elif mutation == "initialization_count":
        state["initialization_count"] = True
    else:
        state["ancestry"] = dict(suspect=True)
    before = deepcopy(state)
    with pytest.raises(ValueError):
        book(state=state)
    assert state == before  # failure never rewrites suspect input into zero


def test_A08_calendar_delay_satellite_or_open_before_intent_reads_nothing():
    ledger = book()
    reads = []
    with pytest.raises(ValueError, match="intent_receipt_missing"):
        ledger.execute_open(
            ledger.sessions[1] + "T13:30:00Z", lambda *a: reads.append(a)
        )
    intent = ledger.prepare_next_open()
    with pytest.raises(ValueError, match="session_mismatch"):
        ledger.execute_open(
            ledger.sessions[2] + "T13:30:00Z", lambda *a: reads.append(a)
        )
    with pytest.raises(TypeError):
        ledger.execute_open(
            ledger.sessions[1] + "T13:30:00Z",
            lambda *a: reads.append(a),
            target={"B": 1},
        )
    assert reads == [] and ledger.snapshot()["pending_intent"] == intent


def test_replay_duplicate_execution_and_cross_member_fold_attempt_are_refused():
    ledger = book()
    day(ledger, 0)
    raw = ledger.export_bytes()
    for fields in (
        dict(member_id="CREF-F3-L020", fold_id="0", attempt_id="C05-SYNTHETIC-ONLY"),
        dict(member_id="CREF-F1-L020", fold_id="1", attempt_id="C05-SYNTHETIC-ONLY"),
        dict(member_id="CREF-F1-L020", fold_id="0", attempt_id="RETRY"),
    ):
        with pytest.raises(ValueError, match="book_identity_mismatch|proven_E0_state"):
            StartupBook.restore(raw, expected_sha256=sha256(raw), **fields)
    corrupt = json.loads(raw)
    corrupt["events"][-1]["output"]["nav"] += 100
    with pytest.raises(ValueError, match="book_replay_mismatch"):
        StartupBook.restore(
            canonical(corrupt),
            expected_sha256=sha256(canonical(corrupt)),
            member_id="CREF-F1-L020",
            fold_id="0",
            attempt_id="C05-SYNTHETIC-ONLY",
        )
    with pytest.raises(ValueError, match="intent_receipt_missing"):
        ledger.execute_open(
            ledger.sessions[1] + "T13:30:00Z",
            lambda *_: pytest.fail("price read before duplicate rejection"),
        )


def test_independent_books_cannot_share_state_and_missing_price_preserves_intent():
    first = book(attempt="first")
    second = book(attempt="retry")
    assert first.book_id != second.book_id
    first.prepare_next_open()
    with pytest.raises(ValueError, match="raw_open_price_invalid"):
        first.execute_open(first.sessions[1] + "T13:30:00Z", lambda *_: None)
    failed = first.snapshot()
    assert (
        failed["pending_intent"] is not None
        and failed["account_state"]["cash"] == 15000
    )
    assert set(failed["account_state"]["inventory"].values()) == {0}
    assert (
        second.snapshot()["pending_intent"] is None
        and second.snapshot()["halt_reason"] is None
    )
    restored = StartupBook.restore(
        first.export_bytes(),
        expected_sha256=sha256(first.export_bytes()),
        member_id="CREF-F1-L020",
        fold_id="0",
        attempt_id="first",
    )
    assert restored.snapshot() == first.snapshot()


def test_persisted_current_receipt_rejects_old_prefix_and_replays_current(tmp_path):
    ledger = book()
    old = ledger.export_bytes()
    day(ledger, 0)
    current = ledger.export_bytes()
    (tmp_path / "account.json").write_bytes(current)
    (tmp_path / "current.sha256").write_text(sha256(current))
    kwargs = dict(
        member_id="CREF-F1-L020",
        fold_id="0",
        attempt_id="C05-SYNTHETIC-ONLY",
        expected_sha256=(tmp_path / "current.sha256").read_text(),
    )
    with pytest.raises(ValueError, match="current_book_bytes_mismatch"):
        StartupBook.restore(old, **kwargs)
    restored = StartupBook.restore((tmp_path / "account.json").read_bytes(), **kwargs)
    assert restored.export_bytes() == current
    assert restored.snapshot()["position"] == 1
    # Returning a copy never permits a caller to erase the owned cash or scope.
    snapshot = restored.snapshot()
    snapshot["account_state"]["cash"] = 15000
    snapshot["identity"]["attempt_id"] = "reset"
    assert restored.export_bytes() == current


def test_reader_failure_halts_without_zero_fill_or_retry_and_survives_restore():
    ledger = book()
    ledger.prepare_next_open()

    def failed_reader(*_):
        raise OSError("synthetic failure")

    with pytest.raises(ValueError, match="startup_price_read_failed"):
        ledger.execute_open(ledger.sessions[1] + "T13:30:00Z", failed_reader)
    raw = ledger.export_bytes()
    restored = StartupBook.restore(
        raw,
        expected_sha256=sha256(raw),
        member_id="CREF-F1-L020",
        fold_id="0",
        attempt_id="C05-SYNTHETIC-ONLY",
    )
    assert restored.snapshot()["account_state"]["cash"] == 15000
    with pytest.raises(ValueError, match="book_halted"):
        restored.execute_open(
            restored.sessions[1] + "T13:30:00Z",
            lambda *_: pytest.fail("retry reader reached"),
        )
    assert restored.export_bytes() == raw


def test_same_book_parallel_and_reentrant_open_cannot_double_charge():
    ledger = book()
    ledger.prepare_next_open()
    timestamp = ledger.sessions[1] + "T13:30:00Z"
    entered, release = Event(), Event()
    reads = []

    def reader(*args):
        reads.append(args)
        with pytest.raises(ValueError, match="reentrant_state_transition_forbidden"):
            ledger.execute_open(timestamp, lambda *_: pytest.fail("nested reader"))
        entered.set()
        assert release.wait(5)
        return 100

    def attempt():
        try:
            return ledger.execute_open(timestamp, reader)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(attempt)
        assert entered.wait(5)
        second = pool.submit(attempt)
        release.set()
        outcomes = [first.result(timeout=5), second.result(timeout=5)]
    assert len(reads) == 1
    success = next(value for value in outcomes if isinstance(value, dict))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    state = ledger.snapshot()["account_state"]
    assert state["fees_x2"] == success["fee_x2"]
    assert state["cash"] == success["cash"]
    assert state["inventory"]["QQQ"] == success["quantity"]


@pytest.mark.parametrize(
    "valuation",
    [
        None,
        {},
        dict(rights_value=0, receivables_value=None, components_known=True),
        dict(rights_value=0, receivables_value=0, components_known=False),
    ],
)
def test_unknown_close_components_cannot_be_zero_and_no_next_open(valuation):
    ledger = book()
    ledger.prepare_next_open()
    ledger.execute_open(ledger.sessions[1] + "T13:30:00Z", lambda *_: 100)
    before = ledger.export_bytes()
    with pytest.raises(ValueError, match="necessary_close_valuation_unknown"):
        ledger.close_session(ledger.sessions[1] + "T20:00:00Z", 100, valuation)
    assert ledger.export_bytes() == before
    with pytest.raises(ValueError, match="verified_previous_close_required"):
        ledger.prepare_next_open()

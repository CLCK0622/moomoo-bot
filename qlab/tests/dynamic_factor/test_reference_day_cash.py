"""C08 consumes C04's exact state/proof and the existing C06 result unchanged."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_accounting import ExecutionAccount
from qlab.dynamic_factor.execution_clock import ADOPTED_SHA256
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from qlab.dynamic_factor.reference_day_inputs import BookScopedInputs
from qlab.dynamic_factor.reference_definition_v301 import reference_definitions
from qlab.dynamic_factor.reference_noncash import origin
from qlab.dynamic_factor.reference_profile_v301 import solo_profile
from test_execution_risk_history import at, close, fill, history, prepare, signal
from test_reference_day_inputs import fixture, synthetic_reader, wire
from v3_reference_helpers import protocol_scope
from v3_test_helpers import synthetic_zero_state


def cash_close(*, blocked=False):
    """Synthetic source facts, actual C04 close and actual C06 observation.

    No real source/permission receipt or runtime certification is implied.
    """
    policy = load_conventions()
    start = policy.fold_manifest()["folds"][0]["train_start"]
    date = policy.calendar[policy.calendar.index(start) + 11]
    scope = protocol_scope([date], [], verified=49)
    if blocked:
        scope = fixture(blocked=True)[1]
        day = next(iter(scope["days"].values()))
        day["date"] = date
        day["eligible_set_derivation_sha256"] = digest(
            {k: v for k, v in day.items() if k != "eligible_set_derivation_sha256"}
        )
        scope.update(
            train=[date],
            days={date: day},
            numeric_symbols={date: day["eligible"]},
            eligible_set_derivation_sha256=digest({date: day}),
            eligible_set_manifest_sha256=digest({date: day["eligible"]}),
        )
        scope["scope_sha256"] = digest(
            {k: v for k, v in scope.items() if k != "scope_sha256"}
        )
    _, hargs = history(member="CREF-F1-L020")
    hargs["guard"] = scope["guard"]
    hargs["genesis"]["inventory"] = synthetic_zero_state(scope["guard"])["inventory"]
    hargs["expected_genesis_sha256"] = digest(hargs["genesis"])
    hist = RiskHistory(**hargs)
    at(hist, 5)
    intent = prepare(hist)
    close(hist, [fill(hist, intent, 3)])
    at(hist, 9)
    snap = hist.snapshot()
    account = ExecutionAccount(
        risk_book=hist._book,
        expected_snapshot_sha256=snap["snapshot_sha256"],
        execution_binding=snap["scope"]["execution_binding"],
        execution_mode="accepted_actual",
    )
    exdate = policy.calendar[policy.calendar.index(date) - 1]
    event = dict(
        event_id="C08-DIV",
        book_id=hargs["book_id"],
        kind="cash_dividend",
        symbol="AAPL",
        ex_date=exdate,
        ex_date_status="verified",
        exact_amount_status="verified_exact",
        cash_basis="integer_pre_tax_cash",
        declared_cash_amount="0.5",
        pay_date=date,
        entitled_integer_shares=3,
        source_sha256=digest("SYNTHETIC C08 DIVIDEND SOURCE"),
    )
    account.record_cash_events(
        [event], session=exdate, expected_event_sha256=[digest(event)]
    )
    evidence = dict(
        session=exdate,
        asof=exdate + "T20:00:00Z",
        prices={"AAPL": "100"},
        source_sha256=digest("SYNTHETIC C08 RAW CLOSE"),
        price_kind="verified_raw_close",
        rights_complete=True,
        cash_events_complete=True,
        execution_outcomes={},
    )
    out = account.close_session(evidence, expected_evidence_sha256=digest(evidence))
    accounting, fills = out["receipt"]["accounting"], out["receipt"]["fills"]
    snap = hist.observe_close(
        exdate,
        accounting,
        fills,
        expected_accounting_sha256=digest(accounting),
        expected_fills_sha256=digest(fills),
        cash_proof=out["cash_proof"],
    )
    assert snap["complete"] is True
    initial = origin(
        scope["guard"],
        "reference/CREF-F1-L020",
        synthetic_zero_state(scope["guard"]),
        digest("SYNTHETIC SEPARATE ZERO SOURCE"),
    )
    args = [
        solo_profile(reference_definitions()[0]),
        scope,
        hargs["book_id"],
        snap["state"],
        initial,
        snap["original_state_sha256"],
    ]
    row = signal(hist)
    supplied = dict(
        risk_scope=snap["scope"],
        close_session=snap["close_session"],
        prior_risk=snap["prior_risk"],
        fees_x2=snap["fees_x2"],
        clock_binding=snap["clock_binding"],
        expected_prior_risk_sha256=snap["prior_risk_sha256"],
        expected_clock_binding_sha256=digest(snap["clock_binding"]),
        expected_ruling_sha256=ADOPTED_SHA256,
        expected_snapshot_sha256=snap["snapshot_sha256"],
        signal=row,
        expected_signal_sha256=digest(row),
    )
    return args, supplied, out["cash_proof"], hist


@pytest.mark.parametrize("member", range(4))
def test_A10_C04_canonical_cash_NAV_retained_without_float_projection(member):
    args = fixture(member=member)
    args[3].update(cash="14999.123456789123456789", nav="15000.123456789123456789")
    args[5] = digest(args[3])
    before = deepcopy(args[3])
    supplied = wire(args)
    bound = BookScopedInputs(*args)
    _, result = bound.read(
        args[1]["train"][0], "holdings_valuation", ["QQQ"], synthetic_reader, **supplied
    )
    assert result["inputs_complete"] is True
    assert result["retained_state_sha256"] == digest(before)
    assert bound.retained_state == before
    assert len(result["required_m_receipt"]) == 22


@pytest.mark.parametrize("key", ["cash", "nav"])
@pytest.mark.parametrize("value", ["01", "1.0", "1e3", "NaN", "-1", "１", "", True])
def test_A11_noncanonical_money_still_refuses_shared_R2(key, value):
    args = fixture()
    args[3][key] = value
    args[5] = digest(args[3])
    with pytest.raises(ValueError, match="state.R2_necessary_state_unknown"):
        BookScopedInputs(*args)


def test_A10_C04_issued_cash_proof_reaches_same_C06_M_unchanged(monkeypatch):
    args, supplied, proof, hist = cash_close()
    before = deepcopy(hist.snapshot())
    original = RiskBook.__init__
    observed = []

    def observe(self, **kwargs):
        observed.append(kwargs["cash_proof"])
        original(self, **kwargs)

    monkeypatch.setattr(RiskBook, "__init__", observe)
    bound = BookScopedInputs(*args, cash_proof=proof)
    values, result = bound.read(
        args[1]["train"][0], "cash_valuation", ["AAPL"], synthetic_reader, **supplied
    )
    intent = hist.prepare_open(
        supplied["signal"],
        expected_signal_sha256=supplied["expected_signal_sha256"],
        expected_snapshot_sha256=supplied["expected_snapshot_sha256"],
    )
    assert observed == [proof] and observed[0] is proof
    assert values == {"AAPL": 100.0}
    assert proof.value == 1.5
    assert bound.retained_state == args[3] == before["state"]
    assert bound.retained_state["receivables"]["C08-DIV"]["amount"] == "1.5"
    assert result["required_m_receipt"] == intent["required_M"]
    assert len(result["required_m_receipt"]) == 22
    assert result["risk_snapshot_sha256"] == before["snapshot_sha256"]
    assert result["inputs_complete"] is True
    assert result["complete"] is result["accounting_executed"] is False
    assert result["runtime_consumable"] is result["certifiable"] is False
    assert result["worker_roles"] == []
    assert hist.snapshot() == before


@pytest.mark.parametrize("change", ["missing", "wire", "boolean", "stale", "book"])
def test_A13_cash_proof_substitution_or_drift_refuses_before_M_reader(
    change, monkeypatch
):
    args, supplied, proof, _ = cash_close()
    if change == "missing":
        proof = None
    elif change == "wire":
        proof = {"sha256": proof.sha256, "verified": True}
    elif change == "boolean":
        proof = True
    elif change == "stale":
        args[3]["cash"] = "14999"
    else:
        args[3]["_risk_clock"]["book_id"] = digest("OTHER BOOK")
    args[5] = digest(args[3])
    m_calls, reader_calls = [], []
    monkeypatch.setattr(RiskBook, "required_m", lambda *a, **k: m_calls.append(1))
    with pytest.raises(
        ValueError,
        match="accounting.owned_cash_proof_required|accounting.cash_proof_state_or_scope_mismatch",
    ):
        BookScopedInputs(*args, cash_proof=proof).read(
            args[1]["train"][0],
            "cash_valuation",
            ["AAPL"],
            lambda *a: reader_calls.append(a),
            **supplied,
        )
    assert m_calls == reader_calls == []


@pytest.mark.parametrize(
    "consumer",
    ["score", "label", "calibration", "order", "holdings_valuation", "cash_valuation"],
)
def test_A13_C04_proof_does_not_bypass_whole_batch_B_first(consumer, monkeypatch):
    args, supplied, proof, _ = cash_close(blocked=True)
    bound = BookScopedInputs(*args, cash_proof=proof)
    blocked = args[1]["guard"]["B"][0]
    before = bound.retained_state
    m_calls, reader_calls = [], []
    monkeypatch.setattr(RiskBook, "required_m", lambda *a, **k: m_calls.append(1))
    with pytest.raises(
        ValueError, match="B.parent_unknown_or_child_numeric_read_forbidden"
    ):
        bound.read(
            args[1]["train"][0],
            consumer,
            ["AAPL", blocked],
            lambda *a: reader_calls.append(a),
            **supplied,
        )
    assert m_calls == reader_calls == []
    assert bound.retained_state == before

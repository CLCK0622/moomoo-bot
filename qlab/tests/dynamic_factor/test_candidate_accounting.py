"""Owned C05/C04/C06/C07 coupling on synthetic LT50 paths, no performance run."""

from copy import deepcopy

import pytest

from projection_test_helpers import case
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_accounting import ExecutionAccount, MODEL
from qlab.dynamic_factor.execution_candidate import (
    CandidateIntent,
    CandidateOpen,
    ExecutionObservation,
)
from qlab.dynamic_factor.execution_returns import TrainingReturns
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from qlab.dynamic_factor.execution_signals import DecayHistory
from qlab.dynamic_factor.pipeline import close_execution_day, execution_observation
from test_candidate_startup import candidate_book
from test_execution_accounting import model_origins
from test_execution_risk_history import history
from test_execution_candidate import wire_hash


def born(member="F1-L020"):
    source = candidate_book(member)
    _, args = history(member, attempt=source.identity["attempt_id"])
    args["book_id"] = source.book_id
    risk = RiskHistory(**args)
    account = ExecutionAccount(
        risk_book=risk._book,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="named_training_diagnostic",
    )
    series = TrainingReturns(
        account,
        expected_account_sha256=account.snapshot()["account_sha256"],
        execution_binding=args["scope"]["execution_binding"],
    )
    return source, risk, account, series


def no_tilt_intent(risk):
    # Original input fixture is private synthetic evidence. Its expected bytes
    # are never modified; this new case binds the actual owned account state.
    inputs, _, _ = case()
    snap = risk.snapshot()
    state = snap["state"]
    date = snap["close_session"]
    nxt = risk._policy.calendar[risk._policy.calendar.index(date) + 1]
    close = inputs["close_state"]
    close.update(
        inventory=deepcopy(state["inventory"]),
        cash=state["cash"],
        NAV_anchor=state["nav"],
        age=deepcopy(state["age"]),
        origin=deepcopy(state["origin"]),
        rights=deepcopy(state["rights"]),
        receivables=deepcopy(state["receivables"]),
        unknown_components=[],
        signal_close_session=date,
        execution_open_session=nxt,
    )
    blocked = risk._guard["B"]
    inputs["eligibility"].update(
        B=blocked,
        E_t=[],
        named_count=0,
        quantity_state="VERIFIED_LT50",
        states={
            s: "B_GUARDED" if s in blocked else "VERIFIED_INELIGIBLE"
            for s in risk._policy.profile["universe"]
        },
    )
    inputs["locked_signal"].update(signal_session=date, scores={}, recipe_id="F1-L020")
    inputs["execution_open"].update(
        session=nxt,
        raw_open={"QQQ": "100"},
        ADV20_usd_asof_close={"QQQ": "100000000"},
    )
    signal = dict(
        book_id=snap["book_id"],
        signal_session=date,
        execution_session=nxt,
        ranks={},
        origin_context=None,
    )
    template = {k: v for k, v in inputs.items() if k != "execution_open"}
    intent = CandidateIntent(
        template,
        risk_book=risk._book,
        risk_signal=signal,
        execution_binding=risk._scope["execution_binding"],
        expected_template_sha256=digest(template),
        expected_snapshot_sha256=snap["snapshot_sha256"],
        expected_signal_sha256=digest(signal),
    )
    out = intent.next_open(
        CandidateOpen(
            inputs["execution_open"],
            expected_sha256=wire_hash(inputs["execution_open"]),
        )
    )
    assert out["projection"]["P"] == out["projection"]["M"] == state["inventory"]
    return intent


@pytest.fixture(scope="module")
def owned_candidate():
    source, risk, account, series = born()
    traces = []
    for i, date in enumerate(series._dates):
        if i < 3:
            source.prepare_next_open()
            source.execute_open(date + "T14:30:00Z", lambda *_: 100)
            account.lock_startup(
                source, expected_source_sha256=digest(source.snapshot())
            )
            e = dict(
                session=date,
                asof=date + "T14:30:00Z",
                prices={"QQQ": "100"},
                source_sha256=digest(["SYNTHETIC C13 OPEN", i]),
                price_kind="verified_tradable_raw_open",
                origins=model_origins(account),
            )
            account.model_open(e, expected_evidence_sha256=digest(e), model_name=MODEL)
        if i == 6:
            intent = no_tilt_intent(risk)
            locked = intent.bind_account(account, risk)
            assert locked["ticket"]["orders"] == []
            assert locked["ticket"]["book_id"] == source.book_id
        evidence = dict(
            session=date,
            asof=date + "T20:00:00Z",
            prices={"QQQ": "100"},
            source_sha256=digest(["SYNTHETIC C13 CLOSE", i]),
            price_kind="verified_raw_close",
            rights_complete=True,
            cash_events_complete=True,
            execution_outcomes={
                key: dict(
                    filled_quantity=row["filled"],
                    status="verified_DAY_closed",
                    source_sha256=digest(["SYNTHETIC C13 DAY", i]),
                )
                for key, row in account.intent()["orders"].items()
                if row["session"] == date
            },
        )
        out = close_execution_day(
            account,
            risk,
            evidence,
            expected_evidence_sha256=digest(evidence),
        )
        traces.append(out["trace"])
        assert out["trace"] == ["ACCOUNTING_AND_NAV", "C06_RISK_ONCE"]
        assert out["risk"]["state"] == account._state
        if i < 3:
            source.close_session(
                date + "T20:00:00Z",
                100,
                dict(rights_value=0, receivables_value=0, components_known=True),
            )
    return account, series, traces


def test_C13_owned_candidate_1260_closes_feed_returns_and_pending_formal_rejection(
    owned_candidate,
):
    account, series, traces = owned_candidate
    benchmark = dict(
        schema="EVO884.BenchmarkDaily/v1",
        dates=list(series._dates),
        values=[0.0] * 1260,
        basis="analytical_TR",
        symbol="QQQ",
        role="B1",
        source_sha256=digest("SYNTHETIC C13 TR BENCHMARK"),
    )
    scores = {series._dates[5]: {"AAPL": 1.0, "AMZN": 2.0}}
    observation = ExecutionObservation.from_account(
        series,
        benchmark,
        expected_benchmark_sha256=digest(benchmark),
        scores=scores,
        expected_scores_sha256=digest(scores),
    )
    actual = observation.document()
    result = series.evaluate(benchmark, expected_benchmark_sha256=digest(benchmark))
    assert actual["returns"] == result["active_daily"]
    assert len(actual["returns"]) == len(traces) == 1260
    assert actual["returns"][0] < 0  # owned startup fee, no caller return padding
    assert actual["account_sha256"] == account.snapshot()["account_sha256"]
    assert actual["seal_status"] == "seal_pending"
    with pytest.raises(ValueError, match="pipeline.execution_seal_pending"):
        execution_observation(
            observation,
            context={},
            member_id="F1-L020",
            execution_role="candidate_solo_probe",
        )


def test_C13_solo_rejects_meta_lifecycle_before_accounting():
    _, risk, account, _ = born()
    before = account.export_bytes()
    with pytest.raises(ValueError, match="solo_must_not_read_meta_lifecycle"):
        close_execution_day(
            account, risk, {}, expected_evidence_sha256=digest({}), monitoring={}
        )
    assert account.export_bytes() == before


def test_C13_META_accounting_risk_then_real_20_25_50_decay_phases(record_property):
    source, risk, account, series = born("META_POLICY_V3")
    decay = DecayHistory(
        book_id=source.book_id,
        global_start=series._dates[0],
        execution_role="current_META_POLICY_execution_layer",
        policy=risk._policy,
        execution_binding=risk._scope["execution_binding"],
    )
    observed = {}
    for i, date in enumerate(series._dates[:56]):
        if i < 3:
            source.prepare_next_open()
            source.execute_open(date + "T14:30:00Z", lambda *_: 100)
            account.lock_startup(
                source, expected_source_sha256=digest(source.snapshot())
            )
            opening = dict(
                session=date,
                asof=date + "T14:30:00Z",
                prices={"QQQ": "100"},
                source_sha256=digest(["SYNTHETIC META OPEN", i]),
                price_kind="verified_tradable_raw_open",
                origins=model_origins(account),
            )
            account.model_open(
                opening, expected_evidence_sha256=digest(opening), model_name=MODEL
            )
        evidence = dict(
            session=date,
            asof=date + "T20:00:00Z",
            prices={"QQQ": "100"},
            source_sha256=digest(["SYNTHETIC META CLOSE", i]),
            price_kind="verified_raw_close",
            rights_complete=True,
            cash_events_complete=True,
            execution_outcomes={
                key: dict(
                    filled_quantity=row["filled"],
                    status="verified_DAY_closed",
                    source_sha256=digest(["SYNTHETIC META DAY", i]),
                )
                for key, row in account.intent()["orders"].items()
                if row["session"] == date
            },
        )
        # Explicit independent-template diagnostics, not returns of this meta account.
        monitoring = {k: "-0.01" for k in decay.states}
        out = close_execution_day(
            account,
            risk,
            evidence,
            expected_evidence_sha256=digest(evidence),
            decay=decay,
            monitoring=monitoring,
            expected_monitoring_sha256=digest(monitoring),
        )
        assert out["trace"] == ["ACCOUNTING_AND_NAV", "C06_RISK_ONCE", "DECAY"]
        assert out["decay"]["global_position"] == i
        assert out["risk"]["snapshot_sha256"] == decay.rows[-1]["snapshot_sha256"]
        assert account._state == out["risk"]["state"]
        if i in (20, 25, 50):
            observed[i] = out["decay"]["states"]["F1-L020"]["state"]
        if i < 3:
            source.close_session(
                date + "T20:00:00Z",
                100,
                dict(rights_value=0, receivables_value=0, components_known=True),
            )
    assert observed == {20: "active", 25: "half", 50: "retired"}
    record_property("C13_META_real_phase_actual", str(observed))
    before = account.export_bytes()
    with pytest.raises(ValueError, match="independent_template_monitoring_required"):
        close_execution_day(
            account, risk, {}, expected_evidence_sha256=digest({}), decay=decay
        )
    assert account.export_bytes() == before

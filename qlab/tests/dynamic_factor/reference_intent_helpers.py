"""Replay the auditor's unchanged synthetic C10 inputs through owned engines."""

from copy import deepcopy
import json
from pathlib import Path

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from qlab.dynamic_factor.execution_startup import StartupBook
from qlab.dynamic_factor.reference_execution import ReferenceExecution
from test_execution_accounting import model_origins


CASES = json.loads(
    (Path(__file__).parent / "fixtures/R-C10-locked-inputs.json").read_text()
)["cases"]


def born(case):
    initial = deepcopy(case["initial"])
    startup = StartupBook(**initial["startup"])
    history = RiskHistory(**initial["history"])
    return ReferenceExecution(
        startup,
        history,
        run_id=initial["run_id"],
        expected_startup_sha256=digest(startup.snapshot()),
        expected_snapshot_sha256=history.snapshot()["snapshot_sha256"],
    )


def open_model(ref, date, prices, source=None):
    evidence = dict(
        session=date,
        asof=date + "T14:30:00Z",
        prices=deepcopy(prices),
        source_sha256=source or digest(["R SYNTHETIC OPEN", date]),
        price_kind="verified_tradable_raw_open",
        origins=model_origins(ref.account),
    )
    return ref.model_open(evidence, expected_evidence_sha256=digest(evidence))


def close_evidence(ref, date, prices):
    return dict(
        session=date,
        asof=date + "T20:00:00Z",
        prices=deepcopy(prices),
        source_sha256=digest(["R SYNTHETIC CLOSE", date]),
        price_kind="verified_raw_close",
        rights_complete=True,
        cash_events_complete=True,
        execution_outcomes={
            k: dict(
                filled_quantity=v["filled"],
                status="verified_DAY_closed",
                source_sha256=digest(["R SYNTHETIC DAY", date]),
            )
            for k, v in ref.account.intent()["orders"].items()
            if v["session"] == date
        },
    )


def close(ref, date, prices, *, startup=False):
    evidence = close_evidence(ref, date, prices)
    return ref.close(
        evidence,
        expected_evidence_sha256=digest(evidence),
        startup_valuation=dict(
            raw_close=100,
            valuation=dict(rights_value=0, receivables_value=0, components_known=True),
        )
        if startup
        else None,
    )


def to_first_due(case):
    ref = born(case)
    for i, date in enumerate(ref.series._dates[:10]):
        if i < 3:
            facts = dict(
                timestamp=date + "T14:30:00Z",
                raw_open=100,
                source_sha256=digest(["R SYNTHETIC OPEN", date]),
            )
            ref.startup_open(**facts, expected_input_sha256=digest(facts))
            open_model(ref, date, {"QQQ": "100"}, facts["source_sha256"])
        if ref.history._book.decision_due()["order_intent_due"]:
            assert date == case["signal"]["execution_session"]
            return ref, date
        close(ref, date, {"QQQ": "100"}, startup=i < 3)
    raise AssertionError("auditor input did not reach its first due open")


def lock(ref, case):
    return ref.lock_projection(
        deepcopy(case["inputs"]),
        deepcopy(case["signal"]),
        expected_input_sha256=digest(case["inputs"]),
        expected_signal_sha256=digest(case["signal"]),
    )

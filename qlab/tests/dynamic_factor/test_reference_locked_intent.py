"""F-R-C10-INTENT: nonzero fills use the same owned, locked D2 signal."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from qlab.dynamic_factor.contract import canonical, digest
from reference_intent_helpers import (
    CASES,
    close,
    close_evidence,
    lock,
    open_model,
    to_first_due,
)
from test_reference_execution_channel import no_tilt


@pytest.mark.parametrize(
    "case", CASES, ids=lambda c: c["member"] + "-" + str(c["named_count"])
)
def test_auditor_nonzero_buy_closes_with_same_signal(case, record_property):
    ref, date = to_first_due(case)
    assert set(ref.history._guard["B"]) == {"ADP", "APD", "CMCSA", "CMI"}
    assert not set(case["inputs"]["execution_open"]["raw_open"]) & set(
        ref.history._guard["B"]
    )
    locked = lock(ref, case)
    ticket = locked["ticket"]
    assert any(r["quantity"] > 0 and r["symbol"] != "QQQ" for r in ticket["orders"])
    active = ref.history.pending_intents()["current_day_order_intent"]
    assert active is not None
    assert active["intent_sha256"] == ticket["intent_sha256"]
    prices = case["inputs"]["execution_open"]["raw_open"]
    open_model(ref, date, prices)
    closed = close(ref, date, prices)
    assert closed["trace"] == ["ACCOUNTING_AND_NAV", "C06_RISK_ONCE"]
    assert closed["risk"]["complete"] is True
    assert closed["accounting"]["execution_verified"] is False
    record_property("input_sha256", digest(case["inputs"]))
    record_property("signal_sha256", digest(case["signal"]))
    record_property("initial_sha256", digest(case["initial"]))
    record_property("closed_risk_sha256", closed["risk"]["snapshot_sha256"])


def test_different_valid_signal_cannot_replace_locked_risk_intent():
    case = CASES[0]
    ref, _ = to_first_due(case)
    other = deepcopy(case["signal"])
    symbol = next(iter(other["ranks"]))
    other["ranks"][symbol] += 0.5
    ref.history.prepare_open(
        other,
        expected_signal_sha256=digest(other),
        expected_snapshot_sha256=ref.history.snapshot()["snapshot_sha256"],
    )
    with pytest.raises(ValueError, match="^risk.one_locked_intent_per_open$"):
        lock(ref, case)
    assert (
        ref.history.pending_intents()["current_day_order_intent"]["intent_sha256"]
        != ref.account.intent()["ticket"]["intent_sha256"]
    )


def test_buy_from_another_signal_keeps_original_close_refusal():
    case = CASES[0]
    ref, date = to_first_due(case)
    lock(ref, case)
    other = deepcopy(case["signal"])
    other["ranks"][next(iter(other["ranks"]))] += 0.5
    snap = ref.history.snapshot()
    wrong = ref.history._book.order_intent(
        other,
        expected_signal_sha256=digest(other),
        expected_snapshot_sha256=snap["snapshot_sha256"],
    )
    prices = case["inputs"]["execution_open"]["raw_open"]
    open_model(ref, date, prices)
    evidence = close_evidence(ref, date, prices)
    closed = ref.account.close_session(
        evidence, expected_evidence_sha256=digest(evidence)
    )
    row = closed["receipt"]
    fills = deepcopy(row["fills"])
    buy = next(f for f in fills if f["quantity"] > 0 and f["symbol"] != "QQQ")
    buy["intent_sha256"] = wrong["intent_sha256"]
    with pytest.raises(ValueError, match="^risk.buy_requires_current_locked_intent$"):
        ref.history.observe_close(
            date,
            row["accounting"],
            fills,
            expected_accounting_sha256=digest(row["accounting"]),
            expected_fills_sha256=digest(fills),
            cash_proof=closed["cash_proof"],
        )
    assert ref.history.snapshot()["state"] == snap["state"]


def test_recorded_lock_operation_replays_nonzero_buys_in_isolated_child():
    # Replay the actual recorded public operations, with no out-of-band prepare.
    # This is a seven-day diagnostic child, not a complete 1260-day result worker.
    expected, programs = [], []
    for case in CASES:
        ref, date = to_first_due(case)
        lock(ref, case)
        prices = case["inputs"]["execution_open"]["raw_open"]
        open_model(ref, date, prices)
        expected.append(close(ref, date, prices))
        programs.append(dict(initial=ref._initial, operations=ref._program))
    script = r"""
import json, sys
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from reference_intent_helpers import born
from qlab.dynamic_factor.contract import canonical
out = []
for program in json.load(sys.stdin):
    ref = born(dict(initial=program['initial']))
    for event in program['operations']:
        assert event['operation'] in {'startup_open', 'lock_projection', 'model_open', 'close'}
        value = getattr(ref, event['operation'])(**event['arguments'])
    out.append(value)
sys.stdout.buffer.write(canonical(out))
"""
    tests = Path(__file__).resolve().parent
    child = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(tests.parents[1]), str(tests)],
        input=json.dumps(programs).encode(),
        capture_output=True,
        check=True,
    )
    assert child.stdout == canonical(expected)


def test_next_due_necessary_exit_uses_current_signal_after_nonzero_buy():
    case = CASES[0]
    ref, date = to_first_due(case)
    lock(ref, case)
    prices = case["inputs"]["execution_open"]["raw_open"]
    open_model(ref, date, prices)
    close(ref, date, prices)
    acquired = set(case["inputs"]["locked_signal"]["new_name_order"])
    for date in ref.series._dates[ref.series._dates.index(date) + 1 :]:
        if ref.history._book.decision_due()["order_intent_due"]:
            break
        close(ref, date, prices)
    # Move the original five below rank 20 at the existing age boundary.
    inputs, signal = no_tilt(ref)
    eligible = case["inputs"]["eligibility"]["E_t"]
    ordered = [s for s in eligible if s not in acquired] + sorted(acquired)
    selected = ordered[:5]
    inputs["eligibility"] = deepcopy(case["inputs"]["eligibility"])
    inputs["execution_open"].update(
        raw_open=deepcopy(prices),
        ADV20_usd_asof_close=deepcopy(
            case["inputs"]["execution_open"]["ADV20_usd_asof_close"]
        ),
    )
    inputs["locked_signal"].update(
        scores={s: str(len(ordered) - k) for k, s in enumerate(ordered)},
        weights={
            **{
                s: "0.04" if s in selected else "0"
                for s in ref.history._policy.profile["universe"]
            },
            "QQQ": "0.78",
        },
        new_name_order=selected,
    )
    signal["ranks"] = {s: float(k + 1) for k, s in enumerate(ordered)}
    ref.lock_projection(
        inputs,
        signal,
        expected_input_sha256=digest(inputs),
        expected_signal_sha256=digest(signal),
    )
    active = ref.history.pending_intents()["current_day_order_intent"]
    assert {r["symbol"] for r in active["required_exits"]} == acquired
    open_model(ref, date, prices)
    out = close(ref, date, prices)
    assert out["risk"]["complete"] is True
    assert all(out["risk"]["state"]["inventory"][s] == 0 for s in acquired)

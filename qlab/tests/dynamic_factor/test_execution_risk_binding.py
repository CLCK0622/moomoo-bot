"""C06 append-only EXEC-CLOSURE binding, no market or lifecycle implementation."""

from copy import deepcopy
import json

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_clock import ADOPTED_SHA256 as CLOCK_SHA
from qlab.dynamic_factor.execution_closure import (
    ADOPTED_SHA256,
    DRAFT_SHA256,
    WITHDRAWN_SHA256,
)
from qlab.dynamic_factor.execution_risk import RiskBook
from test_execution_risk import fixture, run
from test_execution_risk_history import history, at, signal, prepare


@pytest.mark.parametrize("bad", [None, "", "0" * 64, *DRAFT_SHA256, WITHDRAWN_SHA256])
def test_EA_C06_missing_wrong_draft_binding_refuses_before_consumption(
    bad, record_property
):
    args, _ = fixture()
    args["scope"]["execution_binding"]["adoption_sha256"] = bad
    before = deepcopy(args["state"])
    with pytest.raises(ValueError, match="formal_closure_adoption_required") as error:
        RiskBook(**args)
    assert args["state"] == before
    record_property(
        "actual",
        json.dumps(dict(reason=str(error.value), reader_calls=0, worker_roles=[])),
    )


@pytest.mark.parametrize(
    "member",
    [
        "F1-L020",
        "CREF-F1-L020",
        "CREF-F3-L020",
        "MREF-F4-L020",
        "MREF-F2-L020",
        "META_POLICY_V3",
    ],
)
def test_EA_candidate_four_references_meta_share_adoption_keep_C06_binding(member):
    book, _ = history(member)
    state = book.snapshot()
    assert state["execution_closure_sha256"] == ADOPTED_SHA256
    assert state["scope"]["execution_binding"]["adoption_sha256"] == ADOPTED_SHA256
    assert state["ruling_sha256"] == CLOCK_SHA
    assert CLOCK_SHA != ADOPTED_SHA256
    assert (
        book.snapshot()["scope"]["execution_role"] == state["scope"]["execution_role"]
    )


@pytest.mark.parametrize("change", ["missing", "old_fold", "old_adoption"])
def test_EA_N5_meta_requires_same_fold_and_formal_adoption(change, record_property):
    args, row = fixture(meta=True)
    if change == "missing":
        row["origin_context"] = None
    elif change == "old_fold":
        row["origin_context"]["fold_id"] = "76"
    else:
        row["origin_context"]["execution_closure_sha256"] = DRAFT_SHA256[1]
    before = deepcopy(args["state"])
    _, result = run(args, row)
    assert result["complete"] is False and result["M"] is None
    assert result["reasons"] == ["risk.origin_context_role_mismatch"]
    assert args["state"] == before
    record_property(
        "actual",
        json.dumps(
            dict(
                complete=result["complete"],
                reasons=result["reasons"],
                reader_calls=0,
                worker_roles=[],
            )
        ),
    )


def test_EA_N5_fold_handoff_must_precede_new_close_intent_no_old_pool(record_property):
    book, _ = history("META_POLICY_V3", kind="stitched_test")
    policy = load_conventions()
    fold = policy.fold_manifest()["folds"][0]
    start = policy.calendar.index(fold["test_start"])
    at(book, policy.calendar.index(fold["test_end"]) - start)
    before = book.snapshot()
    with pytest.raises(
        ValueError, match="new_fold_context_required_no_old_pool"
    ) as error:
        prepare(book)
    assert (
        book.snapshot() == before
        and book.pending_intents()["current_day_order_intent"] is None
    )
    book.advance_fold("1", expected_snapshot_sha256=before["snapshot_sha256"])
    carried = book.snapshot()
    assert carried["state"] == before["state"] and carried["risk"] == before["risk"]
    assert carried["fees_x2"] == before["fees_x2"]
    # The new-fold context is still required after continuity; an old pool
    # cannot be promoted by merely hashing the old permission object again.
    row = signal(book)
    row["origin_context"]["fold_id"] = "0"
    with pytest.raises(ValueError, match="origin_context_role_mismatch"):
        book.prepare_open(
            row,
            expected_signal_sha256=digest(row),
            expected_snapshot_sha256=carried["snapshot_sha256"],
        )
    record_property(
        "actual",
        json.dumps(
            dict(
                reason=str(error.value),
                reader_calls=0,
                worker_roles=[],
                old_state_preserved=True,
            )
        ),
    )


def test_EA_N5_locked_intent_cannot_reselect_or_merge_books():
    book, _ = history()
    at(book, 5)
    row = signal(book)
    first = book.prepare_open(
        row,
        expected_signal_sha256=digest(row),
        expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
    )
    foreign, _ = history("F2-L020")
    at(foreign, 5)
    assert foreign.snapshot()["book_id"] != book.snapshot()["book_id"]
    wrong = signal(foreign)
    with pytest.raises(ValueError, match="signal_binding_mismatch"):
        book.prepare_open(
            wrong,
            expected_signal_sha256=digest(wrong),
            expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
        )
    assert book.pending_intents()["current_day_order_intent"] == first["intent"]

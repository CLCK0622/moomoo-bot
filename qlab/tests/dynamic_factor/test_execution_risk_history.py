"""C06 / A09, A13: owned synthetic trajectories, no market/strategy run."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest

from qlab.dynamic_factor.execution_closure import (
    ADOPTED_SHA256 as CLOSURE_SHA,
    adopted_execution_binding,
)
from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_clock import (
    ADOPTED_SHA256,
    DRAFT_SHA256,
    adopted_clock_binding,
)
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from test_execution_startup import initial_state
from v3_test_helpers import synthetic_guard


def history(
    member="F1-L020", *, kind="independent_training", fold="0", attempt="C06-SYNTHETIC"
):
    policy = load_conventions()
    reference = member.startswith(("CREF", "MREF"))
    recipe = member.split("-", 1)[1] if reference else member
    role = (
        "independent_meta_reference_probe_component"
        if member.startswith("MREF")
        else "independent_candidate_reference"
        if reference
        else "current_META_POLICY_execution_layer"
        if member == "META_POLICY_V3"
        else "candidate_solo_probe"
    )
    scope = dict(
        execution_binding=adopted_execution_binding(
            expected_adoption_sha256=CLOSURE_SHA
        ),
        kind=kind,
        scope_id="SYNTHETIC-C06-" + member + "-" + kind + "-" + fold,
        member_id=member,
        fold_id=fold,
        attempt_id=attempt,
        execution_role=role,
        recipe_id=recipe,
    )
    genesis = initial_state(policy, fold)
    if kind == "stitched_test":
        start = next(
            f for f in policy.fold_manifest()["folds"] if f["fold_id"] == fold
        )["test_start"]
        genesis["asof"] = (
            policy.calendar[policy.calendar.index(start) - 1] + "T20:00:00Z"
        )
    clock = adopted_clock_binding(expected_ruling_sha256=ADOPTED_SHA256)
    args = dict(
        book_id=digest(scope),
        scope=scope,
        genesis=genesis,
        expected_genesis_sha256=digest(genesis),
        guard=synthetic_guard(policy),
        clock_binding=clock,
        expected_clock_binding_sha256=digest(clock),
        expected_ruling_sha256=ADOPTED_SHA256,
        policy=policy,
    )
    return RiskHistory(**args), args


def next_date(book):
    policy = load_conventions()
    return policy.calendar[policy.calendar.index(book.snapshot()["close_session"]) + 1]


def accounting(book, date, fills=(), **changes):
    state = book.snapshot()["state"]
    row = {
        k: deepcopy(state[k])
        for k in (
            "inventory",
            "cash",
            "nav",
            "rights",
            "receivables",
            "pending_orders",
            "unknown_components",
            "initialization_count",
        )
    }
    row.update(asof=date + "T20:00:00Z", fees_x2=book.snapshot()["fees_x2"])
    for fill in fills:
        row["inventory"][fill["symbol"]] += fill["quantity"]
    row.update(changes)
    return row


def close(book, fills=(), **changes):
    date = next_date(book)
    fills = list(fills)
    row = accounting(book, date, fills, **changes)
    return book.observe_close(
        date,
        row,
        fills,
        expected_accounting_sha256=digest(row),
        expected_fills_sha256=digest(fills),
    )


def at(book, position):
    policy = load_conventions()
    start = book.snapshot()["state"]["_risk_clock"]["global_start"]
    target = policy.calendar[policy.calendar.index(start) + position]
    while book.snapshot()["close_session"] < target:
        close(book)


def signal(book, *, rank=1, permissions=None):
    snapshot = book.snapshot()
    return dict(
        book_id=snapshot["book_id"],
        signal_session=snapshot["close_session"],
        execution_session=next_date(book),
        ranks={"AAPL": rank},
        origin_context=dict(
            source_sha256=digest("SYNTHETIC ORIGINAL POOL"),
            fold_id=snapshot["scope"]["fold_id"],
            execution_closure_sha256=CLOSURE_SHA,
            signal_session=snapshot["close_session"],
            permissions=permissions or {"F1-L020": True},
        )
        if snapshot["scope"]["execution_role"] == "current_META_POLICY_execution_layer"
        else None,
    )


def prepare(book, **changes):
    row = signal(book, **changes)
    return book.prepare_open(
        row,
        expected_signal_sha256=digest(row),
        expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
    )


def fill(book, intent, quantity, *, symbol="AAPL", origin=None, suffix=""):
    return dict(
        fill_id=next_date(book) + symbol + str(quantity) + suffix,
        order_id=digest([next_date(book), symbol]),
        source_sha256=digest("SYNTHETIC ACTUAL FILL"),
        intent_sha256=intent["intent"]["intent_sha256"],
        intent_signal_session=book.snapshot()["close_session"],
        execution_session=next_date(book),
        symbol=symbol,
        quantity=quantity,
        origin=origin or book.snapshot()["scope"]["recipe_id"],
    )


def restored(book, args, raw=None, **changes):
    raw = book.export_bytes() if raw is None else raw
    kwargs = dict(
        expected_sha256=sha256(raw),
        expected_book_id=args["book_id"],
        expected_scope=args["scope"],
        policy=args["policy"],
    )
    kwargs.update(changes)
    return RiskHistory.restore(raw, **kwargs)


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
def test_C06_same_adopted_clock_six_roles_keep_independent_actual_trajectories(member):
    book, args = history(member)
    at(book, 5)
    intent = prepare(book)
    output = close(
        book,
        [
            fill(
                book,
                intent,
                2,
                origin="F1-L020" if member == "META_POLICY_V3" else None,
            )
        ],
    )
    assert output["complete"] and output["state"]["age"]["AAPL"] == 1
    assert output["clock_binding"]["ruling_sha256"] == ADOPTED_SHA256
    assert output["state"]["_risk_clock"]["book_id"] == args["book_id"]
    for boundary in (5, 10, 20):
        at(book, boundary + 5)
        result = prepare(book, rank={5: 21, 10: 10, 20: 1}[boundary])
        assert book.snapshot()["state"]["age"]["AAPL"] == boundary
        assert result["required_M"]["M"]["AAPL"] == 0
        # M is a target inventory, never a fabricated fill or signed order delta.
        assert book.snapshot()["state"]["inventory"]["AAPL"] == 2
    other, _ = history(member, attempt="DIFFERENT-ACTUAL-TRAJECTORY")
    at(other, 25)
    assert (
        other.snapshot()["state"]["age"] == {}
        and other.snapshot()["risk"]["risk_latch"] is False
    )
    assert restored(book, args).export_bytes() == book.export_bytes()


def test_C06_partial_fill_unfilled_final_flat_and_five_forbidden_pairs(record_property):
    book, args = history()
    at(book, 5)
    close(book, [fill(book, prepare(book), 2)])
    at(book, 25)
    exit_order = prepare(book)
    first = close(book, [fill(book, exit_order, -1)])
    assert first["state"]["age"]["AAPL"] == 21
    assert first["state"]["inventory"]["AAPL"] == 1
    assert first["state"]["_risk_clock"]["cooldown_anchors"] == {}
    assert book.pending_intents()["required_exits"]["AAPL"]["remaining_quantity"] == 1
    unfilled = prepare(book)
    close(book)  # zero fills: intent survives, DAY order expires, age still advances.
    assert book.snapshot()["state"]["age"]["AAPL"] == 22
    assert book.pending_intents()["current_day_order_intent"] is None
    assert book.snapshot()["state"]["_risk_clock"]["cooldown_anchors"] == {}
    old = fill(book, unfilled, -1)
    old["intent_signal_session"] = unfilled["intent"]["signal_session"]
    before = book.snapshot()["state"]
    with pytest.raises(ValueError, match="cannot_roll_over"):
        close(book, [old])
    assert book.snapshot()["state"] == before and book.snapshot()["risk"] is None
    close(book)  # accepted evidence for that same next close repairs the R2 stop.
    assert book.snapshot()["state"]["age"]["AAPL"] == 23
    final = close(book, [fill(book, prepare(book), -1)])
    e = final["close_session"]
    assert final["state"]["inventory"]["AAPL"] == 0
    assert final["state"]["_risk_clock"]["cooldown_anchors"] == {"AAPL": e}
    outputs = []
    for i in range(6):
        snap = book.snapshot()
        check = book._book.entry_allowed(
            "AAPL",
            expected_snapshot_sha256=snap["snapshot_sha256"],
            expected_execution_session=next_date(book),
        )
        outputs.append(dict(close=snap["close_session"], open=next_date(book), **check))
        assert check["remaining"] == max(0, 5 - i)
        assert check["allowed"] is False
        assert check["reasons"] == [
            "risk.cooldown_active" if i < 5 else "risk.not_regular_decision"
        ]
        close(book)
    assert book.pending_intents() == {
        "required_exits": {},
        "current_day_order_intent": None,
    }
    # The next original grid point can reopen a new actual segment, age 1.
    allowed = book._book.entry_allowed(
        "AAPL",
        expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
        expected_execution_session=next_date(book),
    )
    assert allowed["remaining"] == 0 and allowed["allowed"] is True
    reopened = close(book, [fill(book, prepare(book), 1)])
    assert reopened["state"]["age"]["AAPL"] == 1
    assert reopened["state"]["_risk_clock"]["entries"]["AAPL"] != e
    assert restored(book, args).export_bytes() == book.export_bytes()
    record_property("C06_five_pairs_actual", json.dumps(outputs, sort_keys=True))


def test_C06_additions_and_partial_reductions_never_reset_original_segment():
    book, _ = history()
    at(book, 5)
    close(book, [fill(book, prepare(book), 2)])
    entry = book.snapshot()["state"]["_risk_clock"]["entries"]["AAPL"]
    at(book, 10)
    close(book, [fill(book, prepare(book), 1)])
    assert book.snapshot()["state"]["age"]["AAPL"] == 6
    at(book, 15)
    close(book, [fill(book, prepare(book), -1)])
    assert book.snapshot()["state"]["age"]["AAPL"] == 11
    assert book.snapshot()["state"]["_risk_clock"]["entries"]["AAPL"] == entry


def test_A09_stitched_boundary_keeps_peak_latch_fees_age_origin_and_intent():
    book, args = history(kind="stitched_test")
    at(book, 5)
    close(book, [fill(book, prepare(book), 2)], fees_x2=12)
    close(book, nav=12750)
    assert book.snapshot()["risk"]["risk_latch"] is True
    prepare(book)
    policy = args["policy"]
    fold = policy.fold_manifest()["folds"][0]
    while book.snapshot()["close_session"] < fold["test_end"]:
        close(book)
    before = book.snapshot()
    pending = book.pending_intents()
    after = book.advance_fold("1", expected_snapshot_sha256=before["snapshot_sha256"])
    assert after["complete"] and after["state"] == before["state"]
    assert after["risk"] == before["risk"] and after["fees_x2"] == 12
    assert book.pending_intents() == pending and pending["required_exits"]
    first_next = close(book, nav=18000)
    assert first_next["risk"]["peak"] == "18000"
    assert first_next["risk"]["risk_latch"] is True
    assert first_next["state"]["age"]["AAPL"] == before["state"]["age"]["AAPL"] + 1
    assert first_next["state"]["origin"] == before["state"]["origin"]
    assert restored(book, args).snapshot() == book.snapshot()
    with pytest.raises(ValueError, match="continuous_genesis"):
        history(kind="stitched_test", fold="1")
    training, _ = history(fold="1")
    assert training.snapshot()["risk"]["peak"] == "15000"
    assert training.snapshot()["risk"]["risk_latch"] is False
    with pytest.raises(ValueError, match="never_migrates"):
        training.advance_fold(
            "2", expected_snapshot_sha256=training.snapshot()["snapshot_sha256"]
        )


@pytest.mark.parametrize(
    "attack",
    [
        "nav",
        "cash",
        "rights",
        "inventory",
        "fees",
        "reset",
        "missing_close",
        "overnight",
    ],
)
def test_A13_R2_conserves_raw_declarations_and_last_known_state(
    attack, record_property
):
    book, args = history()
    at(book, 5)
    close(book, [fill(book, prepare(book), 2)], fees_x2=12)
    before = book.snapshot()
    date = next_date(book)
    row = accounting(book, date)
    if attack in ("nav", "cash"):
        row[attack] = None
    elif attack == "rights":
        row["rights"] = {"AAPL": None}
    elif attack == "inventory":
        row["inventory"]["AAPL"] = 0
    elif attack == "fees":
        row["fees_x2"] = 0
    elif attack == "reset":
        row["initialization_count"] = 2
    elif attack == "missing_close":
        date = args["policy"].calendar[args["policy"].calendar.index(date) + 1]
    else:
        row["pending_orders"] = [dict(symbol="AAPL", intent="DAY order from yesterday")]
    with pytest.raises(ValueError) as failure:
        book.observe_close(
            date,
            row,
            [],
            expected_accounting_sha256=digest(row),
            expected_fills_sha256=digest([]),
        )
    stopped = book.snapshot()
    assert (
        stopped["state"] == before["state"]
        and stopped["risk"] is None
        and not stopped["complete"]
    )
    saved = json.loads(book.export_bytes())
    assert saved["declarations"][-1]["declaration"]["accounting"] == row
    assert saved["declarations"][-1]["status"] == "rejected"
    assert restored(book, args).export_bytes() == book.export_bytes()
    record_property(
        "C06_R2_actual",
        json.dumps(
            dict(
                attack=attack,
                reason=str(failure.value),
                complete=False,
                M=None,
                reader_calls=0,
                accessed_roles=[],
            )
        ),
    )


@pytest.mark.parametrize("bad_sha", [None, digest("WRONG ADOPTION"), *DRAFT_SHA256])
@pytest.mark.parametrize(
    "member",
    ["F1-L020", "CREF-F1-L020", "CREF-F3-L020", "MREF-F4-L020", "MREF-F2-L020"],
)
def test_C06_missing_draft_or_different_adoption_refused_for_every_member(
    member, bad_sha
):
    _, args = history(member)
    args["clock_binding"]["ruling_sha256"] = bad_sha
    args["expected_clock_binding_sha256"] = digest(args["clock_binding"])
    args["expected_ruling_sha256"] = bad_sha
    with pytest.raises(ValueError, match="formal_clock_adoption_required"):
        RiskHistory(**args)


@pytest.mark.parametrize("entry_age", [0, False, 2])
def test_C06_reference_cannot_select_a_different_age_clock_even_after_rehash(entry_age):
    _, args = history("CREF-F1-L020")
    args["clock_binding"]["age_clock"]["entry_close_age"] = entry_age
    args["expected_clock_binding_sha256"] = digest(args["clock_binding"])
    with pytest.raises(ValueError, match="clock_binding_mismatch"):
        RiskHistory(**args)


@pytest.mark.parametrize("change", ["missing", "drift"])
def test_C06_original_adoption_file_required(monkeypatch, tmp_path, change):
    import qlab.dynamic_factor.execution_clock as clock

    if change == "drift":
        (tmp_path / clock.NAME).write_bytes(
            (clock.ROOT / clock.NAME).read_bytes() + b"\n"
        )
    monkeypatch.setattr(clock, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="adoption_missing|adoption_identity_mismatch"):
        adopted_clock_binding(expected_ruling_sha256=ADOPTED_SHA256)


def test_C06_restore_rejects_old_receipt_other_scope_and_rehashed_terminal_claim():
    book, args = history()
    old = book.export_bytes()
    close(book)
    raw = book.export_bytes()
    with pytest.raises(ValueError, match="current_history_bytes_mismatch"):
        restored(book, args, old, expected_sha256=sha256(raw))
    wrong = deepcopy(args["scope"])
    wrong["attempt_id"] = "OTHER"
    with pytest.raises(ValueError, match="history_scope_mismatch"):
        restored(book, args, expected_scope=wrong)
    payload = json.loads(raw)
    payload["snapshot"]["state"]["cash"] = 99999
    with pytest.raises(ValueError, match="history_replay_mismatch"):
        restored(book, args, canonical(payload))


def test_C06_duplicate_close_concurrent_cannot_double_age_or_erase_failure():
    book, _ = history()
    date = next_date(book)
    row = accounting(book, date)

    def observe(_):
        try:
            book.observe_close(
                date,
                row,
                [],
                expected_accounting_sha256=digest(row),
                expected_fills_sha256=digest([]),
            )
            return "accepted"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(observe, [0, 1]))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("risk.missing_duplicate_or_nonadjacent_close") == 1
    assert book.snapshot()["close_session"] == date and not book.snapshot()["complete"]
    assert [d["status"] for d in json.loads(book.export_bytes())["declarations"]] == [
        "verified",
        "rejected",
    ]


def test_A09_all_folds_then_forward_carry_same_book_without_reset():
    book, args = history(kind="stitched_test")
    close(book, nav=12750)
    for fold in args["policy"].fold_manifest()["folds"]:
        current = book.snapshot()
        if current["scope"]["fold_id"] != fold["fold_id"]:
            book.advance_fold(
                fold["fold_id"], expected_snapshot_sha256=current["snapshot_sha256"]
            )
        while book.snapshot()["close_session"] < fold["test_end"]:
            close(book, nav=16000)
        assert book.snapshot()["book_id"] == args["book_id"]
        assert book.snapshot()["risk"]["risk_latch"] is True
        assert book.snapshot()["state"]["initialization_count"] == 1
    before = book.snapshot()
    carried = book.continue_forward(expected_snapshot_sha256=before["snapshot_sha256"])
    assert carried["scope"]["kind"] == "forward"
    assert carried["state"] == before["state"] and carried["risk"] == before["risk"]
    close(book, nav=18000)
    assert book.snapshot()["risk"]["risk_latch"] is True
    assert book.snapshot()["risk"]["peak"] == "18000"


def test_C06_C05_actual_startup_receipts_feed_risk_without_reinitializing():
    from test_execution_startup import book as startup_book, day as startup_day

    startup = startup_book()
    book, args = history("CREF-F1-L020")
    for i in range(3):
        intent, opened, marked, reads = startup_day(startup, i)
        date = next_date(book)
        fills = []
        if opened["quantity"]:
            fills = [
                dict(
                    fill_id="C05-" + str(i),
                    order_id="C05-ORDER-" + str(i),
                    source_sha256=digest(marked),
                    intent_sha256=digest(intent),
                    intent_signal_session=book.snapshot()["close_session"],
                    execution_session=date,
                    symbol="QQQ",
                    quantity=opened["quantity"],
                    origin="QQQ_BASE",
                )
            ]
        current = close(
            book,
            fills,
            cash=marked["cash"],
            nav=marked["nav"],
            fees_x2=marked["fees_x2"],
        )
        assert current["state"]["inventory"] == marked["inventory"]
        assert (
            current["state"]["cash"] == marked["cash"]
            and current["state"]["nav"] == marked["nav"]
        )
        assert (
            current["fees_x2"] == marked["fees_x2"]
            and current["state"]["age"]["QQQ"] == 0
        )
        assert current["complete"] and len(reads) == 1
    assert restored(book, args).snapshot() == book.snapshot()


@pytest.mark.parametrize(
    "attack",
    ["training_end", "fold_skip", "forward_genesis", "early_forward", "B", "erase_age"],
)
def test_C06_scope_clock_and_guard_reject_before_numeric_consumer(attack):
    book, args = history()
    reads, roles = [], []
    if attack == "forward_genesis":
        args["scope"]["kind"] = "forward"
        with pytest.raises(ValueError, match="book_scope_required"):
            RiskHistory(**args)
    elif attack == "early_forward":
        with pytest.raises(ValueError, match="continuous_terminal_book"):
            book.continue_forward(
                expected_snapshot_sha256=book.snapshot()["snapshot_sha256"]
            )
    elif attack == "fold_skip":
        book, _ = history(kind="stitched_test")
        with pytest.raises(ValueError, match="fold_skip"):
            book.advance_fold(
                "2", expected_snapshot_sha256=book.snapshot()["snapshot_sha256"]
            )
    elif attack == "training_end":
        # No calendar skip can migrate this independent book into another fold.
        date = args["policy"].fold_manifest()["folds"][1]["test_start"]
        row = accounting(book, date)
        with pytest.raises(ValueError, match="nonadjacent_close"):
            book.observe_close(
                date,
                row,
                [],
                expected_accounting_sha256=digest(row),
                expected_fills_sha256=digest([]),
            )
    else:
        from test_execution_risk import fixture, run

        raw, sig = fixture()
        if attack == "B":
            raw["state"]["inventory"]["ADP"] = 1
            raw["state"]["age"]["ADP"] = 1
            raw["state"]["origin"]["ADP"] = "F1-L020"
        else:
            del raw["state"]["_risk_clock"]
        raw["expected_original_state_sha256"] = digest(raw["state"])
        snap, M = run(raw, sig)
        if M["complete"]:
            reads.append("forbidden")
            roles.append("raw_open")
        assert not snap["complete"] and M["M"] is None
    assert reads == roles == []

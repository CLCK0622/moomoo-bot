"""C08 consumes the real C06 M; accounting/source reception remain separate."""

from copy import deepcopy

import pytest

from v3_reference_helpers import unit_scope, sealed
from v3_test_helpers import synthetic_zero_state, synthetic_guard
from lt50_quantity_harness import CASES, attack

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_clock import ADOPTED_SHA256, adopted_clock_binding
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.isolation import seal_manifest
from qlab.dynamic_factor.noncash_v3 import CONSUMERS, seal_guard
from qlab.dynamic_factor.reference_compile_v3 import seal_scope
from qlab.dynamic_factor.reference_day_inputs import BookScopedInputs
from qlab.dynamic_factor.reference_definition_v301 import reference_definitions
from qlab.dynamic_factor.reference_noncash import origin
from qlab.dynamic_factor.reference_profile_v301 import solo_profile


def synthetic_reader(date, symbol):
    return 100.0


def fixture(*, verified=49, blocked=False, member=0):
    scope = unit_scope(verified=verified)
    if blocked:
        date = scope["train"][0]
        target = next(
            s for s in scope["universe"] if s not in scope["days"][date]["eligible"]
        )
        request = deepcopy(sealed(verified=verified)["request"])
        guard_request = synthetic_guard(blocked=[target])["request"]
        guard_request.update(
            sealed_at="2026-10-30T11:55:00Z",
            first_performance_at=request["first_performance_at"],
        )
        request["noncash_guard_manifest"] = seal_guard(guard_request)
        for row in request["records"]:
            if row["symbol"] == target:
                row["gates_by_date"] = {}
        policy = load_conventions()
        scope = seal_scope(seal_manifest(request, policy), [date], [], policy)
    profile = solo_profile(reference_definitions()[member])
    initial_state = synthetic_zero_state(scope["guard"])
    actor = "reference/" + profile["definition"]["member_id"]
    initial = origin(scope["guard"], actor, initial_state, digest("SYNTHETIC"))
    initial_state = deepcopy(initial_state)
    policy = load_conventions()
    date = scope["train"][0]
    close_date = policy.calendar[policy.calendar.index(date) - 1]
    initial_state["_risk_clock"] = dict(
        book_id=digest("SYNTHETIC BOOK"),
        scope_id="C08-OWNED-SYNTHETIC",
        ruling_sha256=ADOPTED_SHA256,
        close_session=close_date,
        global_start=policy.fold_manifest()["folds"][0]["train_start"],
        entries={},
        cooldown_anchors={},
        pending_required_exits={},
        source_fills_sha256=digest("C08 SYNTHETIC FILLS"),
    )
    return [
        profile,
        scope,
        digest("SYNTHETIC BOOK"),
        initial_state,
        initial,
        digest(initial_state),
    ]


def wire(args, **changes):
    """Private host expected values, not a C09 source/installation attestation."""
    policy = load_conventions()
    definition, scope, book_id, state, _, state_sha = args
    definition = definition["definition"]
    date = scope["train"][0]
    close_date = policy.calendar[policy.calendar.index(date) - 1]
    prior = dict(
        book_id=book_id,
        close_session=policy.calendar[policy.calendar.index(close_date) - 1],
        peak=15000,
        risk_latch=False,
    )
    clock = adopted_clock_binding(expected_ruling_sha256=ADOPTED_SHA256)
    result = dict(
        risk_scope=dict(
            kind="independent_training",
            scope_id="C08-OWNED-SYNTHETIC",
            member_id=definition["member_id"],
            recipe_id=definition["recipe_id"],
            execution_role=definition["execution_role"],
            fold_id="0",
            attempt_id="C08-PRIVATE-ATTEMPT",
        ),
        close_session=close_date,
        prior_risk=prior,
        fees_x2=12,
        clock_binding=clock,
        expected_prior_risk_sha256=digest(prior),
        expected_clock_binding_sha256=digest(clock),
        expected_ruling_sha256=ADOPTED_SHA256,
        signal=dict(
            book_id=book_id,
            signal_session=close_date,
            execution_session=date,
            ranks={s: 1 for s, q in state["inventory"].items() if q},
            origin_context=None,
        ),
    )
    result.update(changes)
    risk = RiskBook(
        book_id=book_id,
        scope=result["risk_scope"],
        close_session=result["close_session"],
        state=state,
        prior_risk=result["prior_risk"],
        fees_x2=result["fees_x2"],
        canonical_scenario="x2",
        expected_original_state_sha256=state_sha,
        expected_prior_risk_sha256=result["expected_prior_risk_sha256"],
        guard=scope["guard"],
        clock_binding=result["clock_binding"],
        expected_clock_binding_sha256=result["expected_clock_binding_sha256"],
        expected_ruling_sha256=result["expected_ruling_sha256"],
    )
    result.setdefault("expected_snapshot_sha256", risk.snapshot()["snapshot_sha256"])
    result.setdefault("expected_signal_sha256", digest(result["signal"]))
    return result


@pytest.mark.parametrize(
    "verified,quantity,tilt",
    [(49, "VERIFIED_LT50", False), (50, "VERIFIED_GE50", True)],
)
def test_A10_input_portion_retains_LT50_date_state_and_pending_accounting(
    verified, quantity, tilt
):
    args = fixture(verified=verified)
    profile, scope, _, state, _, _ = args
    date = scope["train"][0]
    held = next(
        s
        for s in scope["universe"]
        if s not in scope["days"][date]["eligible"]
        and s not in scope["guard"]["B"]
        and s not in scope["guard"]["unknown"]
    )
    state["inventory"].update(QQQ=2, **{held: 3})
    state["age"].update(QQQ=1, **{held: 8})
    state["origin"].update(QQQ="base", **{held: profile["definition"]["recipe_id"]})
    policy = load_conventions()
    close_date = state["_risk_clock"]["close_session"]
    state["_risk_clock"]["entries"][held] = policy.calendar[
        policy.calendar.index(close_date) - 7
    ]
    args[5] = digest(state)
    bound = BookScopedInputs(*args)
    before = deepcopy(state)
    values, report = bound.read(
        date, "holdings_valuation", ["QQQ", held], synthetic_reader, **wire(args)
    )
    assert set(values) == {"QQQ", held}
    assert report["date"] == date
    assert report["quantity_state"] == quantity and report["new_tilt_allowed"] is tilt
    assert bound.retained_state == state == before
    assert report["retained_state_sha256"] == digest(before)
    assert report["accounting_required"] is True
    assert report["required_M"][held] == 3 and report["required_M"]["QQQ"] == 2
    assert report["required_m_receipt"]["complete"] is True
    assert report["inputs_complete"] is True
    assert report["complete"] is report["accounting_executed"] is False
    assert report["runtime_consumable"] is report["certifiable"] is False


@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_A13_every_consumer_rejects_whole_batch_before_first_numeric_read(
    consumer, monkeypatch
):
    args = fixture(blocked=True)
    bound = BookScopedInputs(*args)
    scope = args[1]
    blocked = scope["guard"]["B"][0]
    clean = scope["days"][scope["train"][0]]["eligible"][0]
    calls = []
    m_calls = []
    original_m = RiskBook.required_m

    def observed_m(self, *args, **kwargs):
        m_calls.append(1)
        return original_m(self, *args, **kwargs)

    monkeypatch.setattr(RiskBook, "required_m", observed_m)
    with pytest.raises(
        ValueError, match="B.parent_unknown_or_child_numeric_read_forbidden"
    ):
        bound.read(
            scope["train"][0],
            consumer,
            [clean, blocked],
            lambda *a: calls.append(a) or 100,
            **wire(args),
        )
    assert calls == []
    assert m_calls == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("nav", None),
        ("nav", 0),
        ("cash", None),
        ("cash", True),
        ("unknown_components", ["missing rights"]),
        ("rights", {"unclosed": 1}),
        ("receivables", {"unclosed": 1}),
    ],
)
def test_A11_A13_missing_state_or_old_rights_refuses_without_erasing(key, value):
    args = fixture()
    args[3][key] = value
    args[5] = digest(args[3])
    before = deepcopy(args[3])
    with pytest.raises(ValueError, match="state.R2|B.zero_exposure"):
        BookScopedInputs(*args)
    assert args[3] == before


def test_A13_old_B_inventory_refuses_before_reader_and_remains_in_declaration():
    args = fixture(blocked=True)
    blocked = args[1]["guard"]["B"][0]
    args[3]["inventory"][blocked] = 1
    args[3]["age"][blocked] = 5
    args[3]["origin"][blocked] = "original"
    args[5] = digest(args[3])
    with pytest.raises(ValueError, match="B.nonzero_initial_or_guarded_exposure"):
        BookScopedInputs(*args)
    assert args[3]["inventory"][blocked] == 1


@pytest.mark.parametrize("verified,real", [(0, False), (50, True)])
def test_A12_empty_or_unknown_scope_refuses_without_QQQ_substitution(verified, real):
    args = list(fixture())
    args[1] = unit_scope(verified=verified, real=real)
    with pytest.raises(ValueError, match="quantity_unknown_or_insufficient"):
        BookScopedInputs(*args)


def test_bound_state_is_not_erased_by_later_mutation_of_caller_declaration():
    args = fixture()
    bound = BookScopedInputs(*args)
    before = bound.retained_state
    args[3]["inventory"].clear()
    copy = bound.retained_state
    copy["inventory"].clear()
    assert bound.retained_state == before


@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_valid_consumer_reads_get_actor_specific_guard_receipt(consumer):
    args = fixture()
    scope = args[1]
    date = scope["train"][0]
    clean = scope["days"][date]["eligible"][0]
    _, report = BookScopedInputs(*args).read(
        date, consumer, [clean], synthetic_reader, **wire(args)
    )
    assert report["receipt"]["actor"] == "reference/CREF-F1-L020"
    assert report["receipt"]["numeric_receipt"]["symbols"] == [clean]
    assert report["new_tilt_allowed"] is False


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), "100"])
def test_unknown_numeric_values_are_not_filled_or_marked_complete(value):
    args = fixture()
    date = args[1]["train"][0]
    with pytest.raises(ValueError, match="execution_numeric_value_unknown"):
        BookScopedInputs(*args).read(
            date, "holdings_valuation", ["QQQ"], lambda *a: value, **wire(args)
        )


def test_scope_refusal_and_date_refusal_happen_before_reader():
    args = fixture()
    bound = BookScopedInputs(*args)
    calls = []
    with pytest.raises(ValueError, match="date_outside_train"):
        bound.read(
            "1900-01-01",
            "order",
            ["QQQ"],
            lambda *a: calls.append(a) or 100,
            **wire(args),
        )
    assert calls == []


@pytest.mark.parametrize("case", CASES)
def test_A12_original_three_state_forgeries_still_refuse(case):
    args = list(fixture())
    args[1] = attack({"sealed_scope": args[1]}, case)["sealed_scope"]
    with pytest.raises(ValueError, match="quantity_unknown_or_insufficient"):
        BookScopedInputs(*args)


@pytest.mark.parametrize("old_field", ["inventory", "rights", "receivables"])
def test_A13_erasure_cannot_match_original_owned_snapshot(old_field):
    args = fixture(blocked=True)
    blocked = args[1]["guard"]["B"][0]
    if old_field == "inventory":
        args[3][old_field][blocked] = 1
        args[3]["age"][blocked] = 5
        args[3]["origin"][blocked] = "original"
    else:
        args[3][old_field][blocked] = 1
    args[5] = digest(args[3])
    if old_field == "inventory":
        args[3][old_field][blocked] = 0
    else:
        args[3][old_field].clear()
    with pytest.raises(ValueError, match="book_snapshot_identity_mismatch"):
        BookScopedInputs(*args)


@pytest.mark.parametrize("member", range(4))
@pytest.mark.parametrize("verified", [49, 50])
def test_A10_all_four_members_use_same_C06_and_keep_original_state(member, verified):
    args = fixture(member=member, verified=verified)
    supplied = wire(args)
    calls = []
    values, result = BookScopedInputs(*args).read(
        args[1]["train"][0],
        "holdings_valuation",
        ["QQQ"],
        lambda *a: calls.append(a) or 100,
        **supplied,
    )
    assert values == {"QQQ": 100} and len(calls) == 1
    m = result["required_m_receipt"]
    assert m["complete"] is True
    assert m["snapshot_sha256"] == supplied["expected_snapshot_sha256"]
    assert m["original_state_sha256"] == digest(args[3])
    assert m["signal_sha256"] == supplied["expected_signal_sha256"]
    assert m["ruling_sha256"] == ADOPTED_SHA256
    assert result["required_M"] == m["M"] == args[3]["inventory"]
    assert result["new_tilt_allowed"] is (verified == 50)
    assert result["retained_state_sha256"] == digest(args[3])
    assert result["fees_x2"] == 12 and "fees_x2" not in args[3]
    assert result["inputs_complete"] is True
    assert result["complete"] is result["accounting_executed"] is False
    assert result["runtime_consumable"] is result["certifiable"] is False
    assert result["worker_roles"] == []


@pytest.mark.parametrize(
    "change,reason",
    [
        ("snapshot", "risk.snapshot_binding_mismatch"),
        ("prior", "risk.original_state_or_prior_binding_mismatch"),
        ("signal", "risk.signal_binding_mismatch"),
        ("clock", "risk.clock_binding_required"),
        ("fees", "risk.required_state_unknown"),
        ("book", "risk.signal_binding_mismatch"),
        ("pool", "risk.solo_must_not_read_current_pool"),
    ],
)
def test_A11_real_C06_refusals_are_unmodified_and_dominate_reader(change, reason):
    args = fixture()
    changes = dict(
        snapshot={"expected_snapshot_sha256": digest("OTHER SNAPSHOT")},
        prior={"expected_prior_risk_sha256": digest("OTHER PRIOR")},
        signal={"expected_signal_sha256": digest("OTHER SIGNAL")},
        clock={"clock_binding": None},
        fees={"fees_x2": None},
    )
    if change in {"book", "pool"}:
        row = wire(args)["signal"]
        row["book_id"] = digest("OTHER BOOK") if change == "book" else row["book_id"]
        if change == "pool":
            row["origin_context"] = {"caller_pool": True}
        supplied = wire(args, signal=row)
    else:
        supplied = wire(args, **changes[change])
    before = deepcopy(args[3])
    calls = []
    values, result = BookScopedInputs(*args).read(
        args[1]["train"][0],
        "holdings_valuation",
        ["QQQ"],
        lambda *a: calls.append(a) or 100,
        **supplied,
    )
    assert result["reasons"][0] == reason
    assert result["reasons"] == result["required_m_receipt"]["reasons"]
    assert result["required_m_receipt"]["M"] is result["required_M"] is None
    assert result["required_m_receipt"]["complete"] is False
    assert values == {} and calls == []
    assert result["numeric_reader_calls"] == 0 and result["accessed_roles"] == []
    assert result["inputs_complete"] is result["complete"] is False
    assert args[3] == before


def test_A11_missing_C06_inputs_cannot_use_an_unguarded_alternative():
    args = fixture()
    calls = []
    with pytest.raises(TypeError, match="keyword-only"):
        BookScopedInputs(*args).read(
            args[1]["train"][0],
            "order",
            ["QQQ"],
            lambda *a: calls.append(a) or 100,
        )
    assert calls == []


@pytest.mark.parametrize("change", ["member", "execution_date", "clock_state"])
def test_A13_foreign_member_date_and_retained_clock_refuse_before_numeric_read(change):
    args = fixture()
    supplied = wire(args)
    if change == "member":
        supplied["risk_scope"]["member_id"] = reference_definitions()[1]["member_id"]
    elif change == "execution_date":
        supplied["signal"]["execution_session"] = "1900-01-01"
    else:
        # Host expected state remains the original one; no rehash can hide a
        # caller erasing the C06 generated history evidence.
        args[3]["_risk_clock"]["entries"] = {"FOREIGN": "1900-01-01"}
    calls = []
    with pytest.raises(
        ValueError,
        match="reference.risk_member_scope_mismatch|reference.execution_date_binding_mismatch|reference.book_snapshot_identity_mismatch",
    ):
        BookScopedInputs(*args).read(
            args[1]["train"][0],
            "holdings_valuation",
            ["QQQ"],
            lambda *a: calls.append(a) or 100,
            **supplied,
        )
    assert calls == []


def test_A10_LT50_required_exit_does_not_erase_or_execute_the_old_inventory():
    args = fixture()
    state = args[3]
    date = args[1]["train"][0]
    held = next(
        s
        for s in args[1]["universe"]
        if s not in args[1]["days"][date]["eligible"]
        and s not in args[1]["guard"]["B"]
        and s not in args[1]["guard"]["unknown"]
    )
    state["inventory"].update(QQQ=2, **{held: 3})
    state["age"].update(QQQ=1, **{held: 8})
    state["origin"].update(QQQ="base", **{held: args[0]["definition"]["recipe_id"]})
    policy = load_conventions()
    close = state["_risk_clock"]["close_session"]
    state["_risk_clock"]["entries"][held] = policy.calendar[
        policy.calendar.index(close) - 7
    ]
    args[5] = digest(state)
    row = wire(args)["signal"]
    row["ranks"][held] = 30
    supplied = wire(args, signal=row)
    before = deepcopy(state)
    bound = BookScopedInputs(*args)
    values, report = bound.read(
        date, "holdings_valuation", ["QQQ", held], synthetic_reader, **supplied
    )
    assert report["quantity_state"] == "VERIFIED_LT50"
    assert report["new_tilt_allowed"] is False
    assert report["required_M"][held] == 0 and report["required_M"]["QQQ"] == 2
    assert report["required_m_receipt"]["required_exits"] == [
        dict(symbol=held, quantity=3, reason="rank_exit")
    ]
    assert values == {"QQQ": 100.0, held: 100.0}
    assert bound.retained_state == state == before
    assert report["complete"] is report["accounting_executed"] is False


def test_C06_RiskHistory_current_snapshot_and_M_are_used_byte_for_byte():
    from v3_reference_helpers import protocol_scope
    from test_execution_risk_history import history, at, signal
    from qlab.dynamic_factor.execution_risk_history import RiskHistory

    _, hargs = history(member="CREF-F1-L020")
    policy = load_conventions()
    start = policy.fold_manifest()["folds"][0]["train_start"]
    date = policy.calendar[policy.calendar.index(start) + 6]
    scope = protocol_scope([date], [], verified=49)
    hargs["guard"] = scope["guard"]
    history_book = RiskHistory(**hargs)
    at(history_book, 5)
    snapshot = history_book.snapshot()
    row = signal(history_book)
    # A separate original-format zero-origin declaration, not a projection or
    # rewrite of the richer C05/C06 genesis. C09 must bind its actual source.
    initial = origin(
        scope["guard"],
        "reference/CREF-F1-L020",
        synthetic_zero_state(scope["guard"]),
        digest("PRIVATE ZERO SOURCE"),
    )
    profile = solo_profile(reference_definitions()[0])
    bound = BookScopedInputs(
        profile,
        scope,
        hargs["book_id"],
        snapshot["state"],
        initial,
        snapshot["original_state_sha256"],
    )
    supplied = dict(
        risk_scope=snapshot["scope"],
        close_session=snapshot["close_session"],
        prior_risk=snapshot["prior_risk"],
        fees_x2=snapshot["fees_x2"],
        clock_binding=snapshot["clock_binding"],
        expected_prior_risk_sha256=snapshot["prior_risk_sha256"],
        expected_clock_binding_sha256=digest(snapshot["clock_binding"]),
        expected_ruling_sha256=ADOPTED_SHA256,
        expected_snapshot_sha256=snapshot["snapshot_sha256"],
        signal=row,
        expected_signal_sha256=digest(row),
    )
    before = deepcopy(snapshot)
    _, result = bound.read(
        date, "holdings_valuation", ["QQQ"], synthetic_reader, **supplied
    )
    intent = history_book.prepare_open(
        row,
        expected_signal_sha256=digest(row),
        expected_snapshot_sha256=snapshot["snapshot_sha256"],
    )
    assert result["required_m_receipt"] == intent["required_M"]
    assert result["risk_snapshot_sha256"] == snapshot["snapshot_sha256"]
    assert history_book.snapshot() == snapshot == before
    assert result["complete"] is result["accounting_executed"] is False

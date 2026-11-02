"""Adopted D2 boundaries, synthetic states only, no market performance."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.execution_closure import (
    ADOPTED_SHA256 as CLOSURE_SHA,
    adopted_execution_binding,
)
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_clock import (
    ADOPTED_SHA256,
    adopted_clock_binding,
)
from qlab.dynamic_factor.execution_risk import M_KEYS, SNAPSHOT_KEYS, RiskBook
from v3_test_helpers import synthetic_guard, synthetic_zero_state


def fixture(*, age=8, nav=15000, peak=15000, latch=False, meta=False):
    policy = load_conventions()
    guard = synthetic_guard(policy)
    state = synthetic_zero_state(guard)
    state.update(cash=1000, nav=nav)
    state["inventory"].update(AAPL=2, QQQ=3)
    state["age"].update(AAPL=age, QQQ=40)
    state["origin"].update(AAPL="F1-L020", QQQ="QQQ_BASE")
    start = policy.fold_manifest()["folds"][0]["train_start"]
    index = policy.calendar.index(start) + 30
    date = policy.calendar[index]
    book_id = digest("SYNTHETIC C06 BOOK")
    scope = dict(
        execution_binding=adopted_execution_binding(
            expected_adoption_sha256=CLOSURE_SHA
        ),
        kind="independent_training",
        scope_id="SYNTHETIC",
        fold_id="0",
        member_id="META_POLICY_V3" if meta else "F1-L020",
        attempt_id="SYNTHETIC",
        recipe_id="META_POLICY_V3" if meta else "F1-L020",
        execution_role="current_META_POLICY_execution_layer"
        if meta
        else "candidate_solo_probe",
    )
    prior = dict(
        book_id=book_id,
        close_session=policy.calendar[index - 1],
        peak=peak,
        risk_latch=latch,
    )
    clock = adopted_clock_binding(expected_ruling_sha256=ADOPTED_SHA256)
    state["_risk_clock"] = dict(
        book_id=book_id,
        scope_id=scope["scope_id"],
        ruling_sha256=ADOPTED_SHA256,
        close_session=date,
        global_start=start,
        entries={"AAPL": policy.calendar[index - age + 1]},
        cooldown_anchors={},
        pending_required_exits={},
        source_fills_sha256=digest("SYNTHETIC FILLS"),
    )
    args = dict(
        book_id=book_id,
        scope=scope,
        close_session=date,
        state=state,
        canonical_scenario="x2",
        prior_risk=prior,
        fees_x2=12,
        expected_original_state_sha256=digest(state),
        expected_prior_risk_sha256=digest(prior),
        guard=guard,
        clock_binding=clock,
        expected_clock_binding_sha256=digest(clock),
        expected_ruling_sha256=clock["ruling_sha256"],
        policy=policy,
    )
    signal = dict(
        book_id=book_id,
        signal_session=date,
        execution_session=policy.calendar[index + 1],
        ranks={"AAPL": 4},
        origin_context=dict(
            source_sha256=digest("SYNTHETIC META ORIGIN"),
            fold_id=scope["fold_id"],
            execution_closure_sha256=CLOSURE_SHA,
            signal_session=date,
            permissions={"F1-L020": True},
        )
        if meta
        else None,
    )
    return args, signal


def run(args, signal, **expected_changes):
    book = RiskBook(**args)
    snapshot = book.snapshot()
    expected = dict(
        expected_book_id=args["book_id"],
        expected_close_session=args["close_session"],
        expected_snapshot_sha256=snapshot["snapshot_sha256"],
        expected_original_state_sha256=args["expected_original_state_sha256"],
        expected_signal_sha256=digest(signal),
    )
    expected.update(expected_changes)
    output = book.required_m(signal, **expected)
    assert set(snapshot) == SNAPSHOT_KEYS and set(output) == M_KEYS
    assert snapshot["runtime_consumable"] is snapshot["certifiable"] is False
    assert output["runtime_consumable"] is output["certifiable"] is False
    return snapshot, output


@pytest.mark.parametrize(
    "age,rank,exit_expected",
    [
        (1, 30, False),
        (4, 30, False),
        (5, 20, False),
        (5, 20.5, True),
        (9, 21, True),
        (10, 5, False),
        (10, 5.5, True),
        (19, 1, False),
        (20, 1, True),
        (21, 1, True),
    ],
)
def test_D2_known_age_predicates_use_one_adopted_clock(age, rank, exit_expected):
    args, signal = fixture(age=age)
    signal["ranks"]["AAPL"] = rank
    raw = deepcopy(args["state"])
    snapshot, result = run(args, signal)
    assert snapshot["complete"] and result["complete"]
    assert result["M"]["AAPL"] == (0 if exit_expected else 2)
    assert result["M"]["QQQ"] == 3
    assert snapshot["state"] == args["state"] == raw
    assert result["required_exits"] == (
        []
        if not exit_expected
        else [
            dict(
                symbol="AAPL",
                quantity=2,
                reason="maximum_age" if age >= 20 else "rank_exit",
            )
        ]
    )


@pytest.mark.parametrize(
    "nav,peak,prior_latch,warning,latch",
    [
        (15000, 15000, False, False, False),
        (13500, 15000, False, True, False),
        (12750, 15000, False, True, True),
        (12750.000001, 15000, False, True, False),
        (15300, 18000, False, True, True),
        (18000, 18000, True, False, True),
        (16000, 15000, False, False, False),
    ],
)
def test_D2_exact_close_drawdown_warning_peak_and_monotonic_latch(
    nav, peak, prior_latch, warning, latch
):
    args, signal = fixture(nav=nav, peak=peak, latch=prior_latch, age=1)
    snapshot, result = run(args, signal)
    assert snapshot["risk"]["warning"] is warning
    assert snapshot["risk"]["risk_latch"] is latch
    assert float(snapshot["risk"]["peak"]) == max(15000, peak, nav)
    assert result["M"]["AAPL"] == (0 if latch else 2)
    assert result["M"]["QQQ"] == 3


@pytest.mark.parametrize("permission", [True, False, None])
@pytest.mark.parametrize("age", [4, 5, 10, 20])
def test_D2_meta_origin_preserves_selection_permission_unknown_not_false(
    permission, age
):
    args, signal = fixture(meta=True, age=age)
    signal["origin_context"]["permissions"]["F1-L020"] = permission
    snapshot, result = run(args, signal)
    if permission is None and 5 <= age < 20:
        assert result["M"] is None and not result["complete"]
        assert result["reasons"] == ["risk.rank_or_origin_unknown"]
    else:
        exits = age >= 20 or age >= 5 and permission is False
        assert result["M"]["AAPL"] == (0 if exits else 2)
    assert snapshot["state"]["inventory"]["AAPL"] == 2


def test_D2_solo_rejects_pool_and_actual_meta_requires_original_context():
    args, signal = fixture()
    signal["origin_context"] = {"permissions": {"F1-L020": False}}
    assert run(args, signal)[1]["reasons"] == ["risk.solo_must_not_read_current_pool"]
    args, signal = fixture(meta=True)
    signal["origin_context"] = None
    assert run(args, signal)[1]["reasons"] == ["risk.origin_context_role_mismatch"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("cash", None),
        ("cash", False),
        ("nav", None),
        ("nav", True),
        ("fees_x2", None),
        ("rights", {"AAPL": None}),
        ("receivables", {"AAPL": 10}),
        ("unknown_components", ["SUSPECT_ANCESTOR"]),
    ],
)
def test_D2_R2_unknown_retains_every_original_field_without_forced_sale(field, value):
    args, signal = fixture(latch=True)
    if field == "fees_x2":
        args["fees_x2"] = value
    else:
        args["state"][field] = value
    args["expected_original_state_sha256"] = digest(args["state"])
    original = deepcopy(args["state"])
    snapshot, result = run(args, signal)
    assert snapshot["state"] == args["state"] == original
    assert snapshot["risk"] is None
    assert not result["complete"] and result["M"] is None and result["reasons"]
    assert result["required_exits"] == []


def test_D2_clock_missing_keeps_generated_risk_but_never_complete_M():
    args, signal = fixture(nav=12000)
    args.update(
        clock_binding=None,
        expected_clock_binding_sha256=None,
        expected_ruling_sha256=None,
    )
    snapshot, result = run(args, signal)
    assert snapshot["risk"]["risk_latch"] is True
    assert not snapshot["complete"] and snapshot["clock_binding"] is None
    assert result["M"] is None and result["reasons"] == ["risk.clock_binding_required"]
    original = deepcopy(args["state"])
    assert snapshot["state"] == original


@pytest.mark.parametrize(
    "attack",
    [
        "binding_sha",
        "ruling_sha",
        "empty_age",
        "empty_cooldown",
        "bool_age",
        "extra_age",
        "wrong_count",
    ],
)
def test_D2_clock_requires_both_host_bindings_and_closed_parameters(attack):
    args, signal = fixture()
    clock = args["clock_binding"]
    if attack == "binding_sha":
        args["expected_clock_binding_sha256"] = digest("other")
    elif attack == "ruling_sha":
        args["expected_ruling_sha256"] = digest("other")
    else:
        if attack == "empty_age":
            clock["age_clock"] = {}
        elif attack == "empty_cooldown":
            clock["cooldown_boundary"] = {}
        elif attack == "bool_age":
            clock["age_clock"]["entry_close_age"] = False
        elif attack == "extra_age":
            clock["age_clock"]["default"] = 0
        else:
            clock["cooldown_boundary"]["blocked_sessions"] = 0
        args["expected_clock_binding_sha256"] = digest(clock)
    _, result = run(args, signal)
    assert not result["complete"] and result["M"] is None and result["reasons"]


@pytest.mark.parametrize(
    "field",
    [
        "expected_book_id",
        "expected_close_session",
        "expected_snapshot_sha256",
        "expected_original_state_sha256",
        "expected_signal_sha256",
    ],
)
def test_D2_C08_host_binding_mismatch_rejects_before_any_reader(field):
    args, signal = fixture()
    _, result = run(args, signal, **{field: digest("other")})
    assert result["M"] is None and not result["complete"] and result["reasons"]


@pytest.mark.parametrize(
    "attack",
    ["future_signal", "nonadjacent_open", "caller_M", "caller_returns", "wrong_origin"],
)
def test_D2_source_scope_rejects_even_with_recomputed_signal_hash(attack):
    args, signal = fixture()
    if attack == "future_signal":
        signal["signal_session"] = signal["execution_session"]
    elif attack == "nonadjacent_open":
        signal["execution_session"] = args["policy"].calendar[102]
    elif attack in {"caller_M", "caller_returns"}:
        signal[attack] = []
    else:
        args["state"]["origin"]["AAPL"] = "F2-L020"
        args["expected_original_state_sha256"] = digest(args["state"])
    _, result = run(args, signal)
    assert result["M"] is None and not result["complete"] and result["reasons"]


def test_D2_source_input_and_snapshot_mutations_do_not_change_owned_book():
    args, signal = fixture()
    book = RiskBook(**args)
    original = book.snapshot()
    args["state"]["inventory"]["AAPL"] = 0
    snapshot = book.snapshot()
    snapshot["state"]["inventory"]["AAPL"] = 0
    snapshot["risk"]["risk_latch"] = True
    assert book.snapshot() == original


def test_D2_reference_and_candidate_use_identical_risk_and_M_predicates():
    args, signal = fixture(age=10, nav=12750)
    snapshot, result = run(args, signal)
    for member, role in [
        ("CREF-F1-L020", "independent_candidate_reference"),
        ("MREF-F2-L020", "independent_meta_reference_probe_component"),
    ]:
        ref_args = deepcopy(args)
        recipe = "F1-L020" if member.startswith("CREF") else "F2-L020"
        ref_args["scope"].update(
            member_id=member, execution_role=role, recipe_id=recipe
        )
        ref_args["state"]["origin"]["AAPL"] = recipe
        ref_args["expected_original_state_sha256"] = digest(ref_args["state"])
        ref_snapshot, ref_result = run(ref_args, signal)
        assert ref_snapshot["risk"] == snapshot["risk"]
        assert ref_result["M"] == result["M"]


def test_D2_missing_rank_is_unknown_when_needed_not_an_automatic_exit():
    args, signal = fixture(age=10)
    signal["ranks"] = {}
    snapshot, result = run(args, signal)
    assert result["M"] is None and result["reasons"] == ["risk.rank_or_origin_unknown"]
    assert snapshot["state"]["inventory"]["AAPL"] == 2


def test_D2_constructor_has_no_clock_defaults():
    args, _ = fixture()
    for key in (
        "clock_binding",
        "expected_clock_binding_sha256",
        "expected_ruling_sha256",
    ):
        missing = dict(args)
        del missing[key]
        with pytest.raises(TypeError):
            RiskBook(**missing)


def test_D2_x1_may_not_replace_canonical_risk_book():
    args, _ = fixture()
    args["canonical_scenario"] = "x1"
    with pytest.raises(ValueError, match="canonical_x2_required"):
        RiskBook(**args)


def test_D2_risk_ratio_does_not_inherit_callers_decimal_rounding():
    from decimal import localcontext, ROUND_UP

    args, sig = fixture(nav=12750.000001)
    original = run(args, sig)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        changed = run(args, sig)
    assert changed == original
    assert original[0]["risk"]["risk_latch"] is False

from copy import deepcopy
from fractions import Fraction

import pytest

from projection_test_helpers import case, plan
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_projection import amount, decimal_text
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.execution_signals import DecayHistory, fixed_scores


def meta_case(*, half=False):
    inputs, args, signal = case(
        role="current_META_POLICY_execution_layer",
        member="META_POLICY_V3",
        recipe="META_POLICY_V3",
    )
    locked = inputs["locked_signal"]
    ids = ["F1-L020", "F2-L020", "F3-L020", "F4-L020"]
    locked.update(
        recipe_id="META_POLICY_V3",
        factor_states={k: 0.5 if half and i == 3 else 1 for i, k in enumerate(ids)},
        factor_scores={
            k: {s: float(v) for s, v in locked["scores"].items()} for k in ids
        },
        scores={},
    )
    theta = sum((amount(a) for a in locked["factor_states"].values()), Fraction(0)) / 20
    locked["tilt_fraction"] = decimal_text(theta)
    locked["weights"] = {
        s: decimal_text(theta / 5) if amount(v) > 0 and s != "QQQ" else "0"
        for s, v in locked["weights"].items()
    }
    locked["weights"]["QQQ"] = decimal_text(Fraction(49, 50) - theta)
    signal["origin_context"] = dict(
        source_sha256=digest("SYNTHETIC SOURCE"),
        signal_session=args["close_session"],
        permissions={k: k != ids[3] if half else True for k in ids},
        fold_id=args["scope"]["fold_id"],
        execution_closure_sha256=args["scope"]["execution_binding"]["adoption_sha256"],
    )
    return inputs, args, signal


def test_D1_meta_nets_before_single_floor_and_uses_same_projector():
    inputs, args, signal = meta_case()
    output = plan(inputs, args, signal)
    solo = plan(*case())
    assert output["P"] == solo["P"]
    assert output["M"] == solo["M"]
    assert output["net_orders"] == solo["net_orders"]
    assert output["trace"] == solo["trace"]


def test_D1_selected_half_freezes_all_share_increases_but_not_reductions():
    inputs, args, signal = meta_case(half=True)
    output = plan(inputs, args, signal)
    assert output["P"]["COP"] <= args["state"]["inventory"]["COP"]
    assert all(
        output["P"][s] <= q for s, q in args["state"]["inventory"].items() if s != "QQQ"
    )
    assert output["P"]["QQQ"] > output["M"]["QQQ"]
    assert any("meta_additions_frozen" in reason for reason in output["reasons"])


@pytest.mark.parametrize(
    "role,member,recipe",
    [
        ("candidate_solo_probe", "F1-L020", "F1-L020"),
        ("independent_candidate_reference", "CREF-F1-L020", "F1-L020"),
        ("independent_candidate_reference", "CREF-F3-L020", "F3-L020"),
        ("independent_meta_reference_probe_component", "MREF-F2-L020", "F2-L020"),
        ("independent_meta_reference_probe_component", "MREF-F4-L020", "F4-L020"),
    ],
)
def test_D1_candidate_and_four_references_share_quantity_and_risk(role, member, recipe):
    inputs, args, signal = case(role=role, member=member, recipe=recipe)
    inputs["locked_signal"]["recipe_id"] = recipe
    for s in ("COP", "CVS"):
        inputs["close_state"]["origin"][s] = args["state"]["origin"][s] = recipe
    assert plan(inputs, args, signal)["net_orders"] == plan(*case())["net_orders"]


def test_A05_solo_pool_or_arbitrary_target_rejected():
    inputs, args, signal = case()
    inputs["locked_signal"]["factor_states"] = {"F1-L020": 1}
    with pytest.raises(ValueError, match="solo_must_not_read_meta_pool"):
        plan(inputs, args, signal)
    inputs, args, signal = case()
    inputs["locked_signal"]["weights"]["COST"] = "0.08"
    with pytest.raises(ValueError, match="caller_weights_not_frozen_targets"):
        plan(inputs, args, signal)


@pytest.mark.parametrize("recipe", ["F1-L020", "F2-L020", "F3-L020", "F4-L020"])
def test_C03_four_fixed_formulae_from_same_C_asof_window(recipe):
    _, args, _ = case()
    histories = {
        "AAPL": [decimal_text(100 * Fraction(11, 10) ** i) for i in range(21)],
        "AMZN": [100 if i % 2 == 0 else 80 for i in range(21)],
    }
    actual = fixed_scores(
        recipe,
        histories,
        eligible=list(histories),
        guard=args["guard"],
        policy=args["policy"],
        execution_binding=args["scope"]["execution_binding"],
        expected_histories_sha256=digest(histories),
    )
    # Independent hand worksheet: geometric +10% daily; alternating -.20,+.25.
    # AMZN sample variance is 1.0125/19, downside second moment is .02.
    expected = {
        "F1-L020": {"AAPL": 5.7274999493256, "AMZN": 0.0},
        "F2-L020": {"AAPL": -5.7274999493256, "AMZN": 0.0},
        "F3-L020": {"AAPL": 0.0, "AMZN": -0.23084512921915967},
        "F4-L020": {"AAPL": 0.0, "AMZN": -0.1414213562373095},
    }[recipe]
    assert actual == pytest.approx(expected, rel=1e-15, abs=1e-15)


def test_A13_formula_B_guard_before_histories_consumed():
    _, args, _ = case()
    rows = {"ADP": ["FORBIDDEN"] * 21, "AAPL": [100] * 21}
    with pytest.raises(ValueError, match="B\\."):
        fixed_scores(
            "F1-L020",
            rows,
            eligible=list(rows),
            guard=args["guard"],
            policy=args["policy"],
            execution_binding=args["scope"]["execution_binding"],
            expected_histories_sha256=digest(rows),
        )


def history_fixture():
    _, args, _ = meta_case()
    p = args["policy"]
    start = p.calendar[-80]
    args["state"]["inventory"] = {s: 0 for s in args["state"]["inventory"]}
    args["state"].update(age={}, origin={}, cash=15000, nav=15000)
    args["state"]["_risk_clock"].update(entries={}, global_start=start)
    history = DecayHistory(
        book_id=args["book_id"],
        global_start=start,
        policy=p,
        execution_binding=args["scope"]["execution_binding"],
        execution_role=args["scope"]["execution_role"],
    )
    return args, history


def observe(args, history, i, values):
    args = deepcopy(args)
    p = args["policy"]
    date = p.calendar[p.calendar.index(history.start) + i]
    args["close_session"] = args["state"]["_risk_clock"]["close_session"] = date
    args["prior_risk"]["close_session"] = p.calendar[p.calendar.index(date) - 1]
    args["expected_original_state_sha256"] = digest(args["state"])
    args["expected_prior_risk_sha256"] = digest(args["prior_risk"])
    book = RiskBook(**args)
    assert book.snapshot()["complete"]
    return history.observe(
        book, values, expected_snapshot_sha256=book.snapshot()["snapshot_sha256"]
    )


def test_EA_N4_actual_20_25_50_boundaries_and_monotone_states():
    args, h = history_fixture()
    output = {}
    values = {k: "-0.01" for k in h.states}
    for i in range(56):
        output[i] = observe(args, h, i, values)
    k = "F1-L020"
    assert output[15]["checks"][k]["reason"] == "insufficient"
    assert output[20]["checks"][k]["valid"] is True
    assert output[20]["states"][k]["state"] == "active"
    assert output[25]["states"][k]["state"] == "half"
    assert output[25]["states"][k]["half_at"] == 25
    assert output[46]["states"][k]["state"] == "half"
    assert (
        output[50]["states"][k]["state"]
        == output[55]["states"][k]["state"]
        == "retired"
    )


def test_EA_N4_unknown_breaks_adjacency_not_zero_or_skipped():
    args, h = history_fixture()
    output = {}
    for i in range(51):
        values = {k: None if i == 21 else "-0.01" for k in h.states}
        output[i] = observe(args, h, i, values)
    k = "F1-L020"
    assert output[21]["states"][k]["additions_frozen"] is True
    assert output[25]["checks"][k]["reason"] == "unknown"
    assert output[45]["states"][k]["state"] == "active"
    assert output[50]["states"][k]["state"] == "half"
    assert h.rows[21]["values"][k] is None
    assert output[21]["complete"] is False


def test_EA_N4_no_solo_lifecycle_or_cross_book_close_rollover():
    args, h = history_fixture()
    with pytest.raises(ValueError, match="solo_does_not_inherit_meta_lifecycle"):
        DecayHistory(
            book_id=args["book_id"],
            global_start=h.start,
            policy=args["policy"],
            execution_binding=args["scope"]["execution_binding"],
            execution_role="candidate_solo_probe",
        )
    with pytest.raises(ValueError, match="book_or_close_continuity_mismatch"):
        observe(args, h, 1, {k: "-0.01" for k in h.states})
    assert h.rows == []


def test_EA_N4_returned_state_is_not_a_reactivation_or_history_rewrite_path():
    args, h = history_fixture()
    for i in range(51):
        observe(args, h, i, {k: "-0.01" for k in h.states})
    snapshot = h.states
    snapshot["F1-L020"]["state"] = "active"
    rows = h.rows
    rows.clear()
    assert h.states["F1-L020"]["state"] == "retired"
    assert len(h.rows) == 51


def test_D1_missing_S2_is_not_legitimate_empty_meta_pool():
    inputs, args, signal = meta_case()
    locked = inputs["locked_signal"]
    locked.update(
        factor_states={},
        factor_scores={},
        scores={},
        tilt_fraction="0",
        weights={s: "0.98" if s == "QQQ" else "0" for s in locked["weights"]},
    )
    signal["origin_context"]["permissions"] = {"F1-L020": False}
    with pytest.raises(ValueError, match="empty_meta_pool_requires_original_S2_proof"):
        plan(inputs, args, signal)
    locked["empty_pool_proof"] = {
        "S2_complete": True,
        "pool": [],
        "source_sha256": signal["origin_context"]["source_sha256"],
        "fold_id": args["scope"]["fold_id"],
    }
    output = plan(inputs, args, signal)
    assert all(q == 0 for s, q in output["P"].items() if s != "QQQ")
    assert output["M"]["COP"] == output["M"]["CVS"] == 0


def test_EA_N5_old_signal_or_fold_context_cannot_be_reselected_at_open():
    inputs, args, signal = meta_case()
    old = digest(signal)
    signal["origin_context"]["permissions"]["F1-L020"] = False
    with pytest.raises(ValueError, match="signal_binding_mismatch"):
        plan(inputs, args, signal, expected_signal_sha256=old)
    signal["origin_context"]["fold_id"] = "OLD_FOLD"
    with pytest.raises(ValueError, match="origin_context_role_mismatch"):
        plan(inputs, args, signal)


def test_EA_N5_same_close_is_idempotent_conflicting_close_cannot_rewrite():
    args, h = history_fixture()
    values = {k: "-0.01" for k in h.states}
    first = observe(args, h, 0, values)
    assert observe(args, h, 0, values) == first
    assert len(h.rows) == 1
    values["F1-L020"] = "0.01"
    with pytest.raises(ValueError, match="conflicting_close_replay"):
        observe(args, h, 0, values)
    assert len(h.rows) == 1

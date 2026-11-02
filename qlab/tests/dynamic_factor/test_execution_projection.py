"""D12 real common projector over immutable synthetic states, no strategies."""

from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import pytest

from projection_test_helpers import ORACLE, case, plan
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_amounts import ExactOrderCosts as OrderCosts
from qlab.dynamic_factor.execution_projection import OUTPUT_KEYS, amount, decimal_text


def test_A01_D1_full_publisher_oracle_not_generated_from_DUT():
    inputs, args, signal = case()
    before = deepcopy((inputs, args["state"], signal))
    actual = json.dumps(
        plan(inputs, args, signal),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    assert (
        hashlib.sha256(
            (ORACLE / "CF01.expected.canonical.json").read_bytes()
        ).hexdigest()
        == "b935b633e29830e30469d9f08bb2666bcb272c2bda2143b7011e7faecaa102b7"
    )
    assert actual == (ORACLE / "CF01.expected.canonical.json").read_bytes()
    assert len(actual) == 1747
    assert (inputs, args["state"], signal) == before


@pytest.mark.parametrize("key", ["M", "P", "returns", "required_m"])
def test_A05_caller_plan_or_returns_rejected(key):
    inputs, args, signal = case()
    inputs[key] = {"AAPL": 9}
    with pytest.raises(ValueError, match="caller_plan_or_returns_forbidden"):
        plan(inputs, args, signal)


@pytest.mark.parametrize("change", ["D2", "binding", "signal", "snapshot", "input"])
def test_A02_missing_or_wrong_capabilities_reject_before_any_projection(change):
    inputs, args, signal = case()
    overrides = {
        "D2": dict(risk_book=None),
        "binding": dict(execution_binding=None),
        "signal": dict(expected_signal_sha256=digest("WRONG")),
        "snapshot": dict(expected_snapshot_sha256=digest("WRONG")),
        "input": dict(expected_input_sha256=digest("WRONG")),
    }[change]
    with pytest.raises(ValueError):
        plan(inputs, args, signal, **overrides)


@pytest.mark.parametrize("price", ["19.999999999999999999", "19", "1"])
def test_D1_low_open_cancels_entire_buy_no_reselection_topup_or_redistribution(price):
    inputs, args, signal = case()
    inputs["execution_open"]["raw_open"]["COST"] = price
    result = plan(inputs, args, signal)
    assert result["P"]["COST"] == 0
    assert result["P"]["QQQ"] == 117
    assert result["P"]["AAPL"] == 3
    assert result["reasons"] == ["projection.cancel_buy:COST:price_below20"]
    assert not any(o["symbol"] == "COST" for o in result["net_orders"])


def test_D1_ADV_full_buy_is_cancelled_not_shrunk():
    inputs, args, signal = case()
    inputs["execution_open"]["ADV20_usd_asof_close"]["AAPL"] = "40000"
    result = plan(inputs, args, signal)
    assert result["P"]["AAPL"] == 0  # 3*175 > 400; do not buy 2.
    assert result["P"]["AMZN"] == 2
    assert result["P"]["QQQ"] == 117
    assert result["reasons"] == ["projection.cancel_buy:AAPL:ADV"]


def test_D1_no_T_price_or_GK_denominator_in_close_NAV_anchor():
    inputs, args, signal = case()
    inputs["execution_open"]["raw_open"]["QQQ"] = "125"
    result = plan(inputs, args, signal)
    assert result["NAV_anchor"] == "15000"
    assert result["P"]["QQQ"] == 93  # floor(15000*.78/125), not open NAV.


def test_D1_M_first_and_complete_net_orders_not_P_minus_M():
    inputs, args, signal = case()
    result = plan(inputs, args, signal)
    assert result["M"]["CVS"] == result["P"]["CVS"] == 0
    assert result["net_orders"][0] == dict(
        priority=1, quantity=3, side="SELL", symbol="CVS"
    )
    assert len({o["symbol"] for o in result["net_orders"]}) == 7
    assert set(result) == OUTPUT_KEYS
    assert "returns" not in result


def test_D1_M_infeasible_retains_original_and_intent():
    inputs, args, signal = case()
    original = deepcopy(args["state"])
    inputs["execution_open"]["ADV20_usd_asof_close"]["CVS"] = "100"
    with pytest.raises(
        ValueError, match="necessary_M_infeasible_preserve_state_and_intent"
    ):
        plan(inputs, args, signal)
    assert args["state"] == original


@pytest.mark.parametrize("field", ["cash", "NAV_anchor", "signal_close_session"])
def test_D1_changed_close_state_or_nonadjacent_old_close_rejected(field):
    inputs, args, signal = case()
    inputs["close_state"][field] = (
        "2014-01-02" if field.endswith("session") else "14999"
    )
    with pytest.raises(ValueError, match="close_state_or_locked_date_mismatch"):
        plan(inputs, args, signal)


def test_A13_B_guard_runs_before_numeric_value_access():
    inputs, args, signal = case()
    inputs["execution_open"]["raw_open"]["ADP"] = "DO NOT PARSE ME"
    with pytest.raises(ValueError, match="B\\."):
        plan(inputs, args, signal)


def test_D1_not_regular_close_produces_only_M_no_extra_QQQ_decision():
    inputs, args, signal = case()
    clock = args["state"]["_risk_clock"]
    p = args["policy"]
    clock["global_start"] = p.calendar[p.calendar.index(clock["global_start"]) - 1]
    result = plan(inputs, args, signal)
    assert result["P"] == result["M"]
    assert result["net_orders"] == [
        dict(priority=1, quantity=3, side="SELL", symbol="CVS")
    ]
    assert result["reasons"] == ["projection.not_regular_decision"]


def test_A10_LT50_keeps_inventory_and_computable_M_without_new_scores():
    inputs, args, signal = case()
    day = inputs["eligibility"]
    retained = day["E_t"][:49]
    day.update(E_t=retained, named_count=49, quantity_state="VERIFIED_LT50")
    day["states"] = {
        s: "VERIFIED_USABLE" if s in retained else "VERIFIED_INELIGIBLE"
        for s in day["states"]
    }
    inputs["locked_signal"]["scores"] = {}
    result = plan(inputs, args, signal)
    assert result["P"] == result["M"]
    assert result["P"]["COP"] == 4 and result["P"]["QQQ"] == 100
    assert result["reasons"] == ["projection.LT50_no_new_tilt"]
    assert args["state"]["inventory"]["CVS"] == 3


def test_A12_unknown_or_forged_GE50_does_not_become_empty_pool():
    inputs, args, signal = case()
    day = inputs["eligibility"]
    for s in day["E_t"][49:]:
        day["states"][s] = "UNKNOWN"
    day.update(E_t=day["E_t"][:49], named_count=49, quantity_state="UNKNOWN")
    with pytest.raises(ValueError, match="UNKNOWN_no_formal_plan"):
        plan(inputs, args, signal)
    day["quantity_state"] = "VERIFIED_GE50"
    with pytest.raises(ValueError, match="eligibility_count_or_state_mismatch"):
        plan(inputs, args, signal)


@pytest.mark.parametrize(
    "spelling", ["NaN", "Infinity", "1e-20", "+1", "01", "1.00", "-0", True, None]
)
def test_EA_N1_reject_invalid_canonical_money(spelling):
    with pytest.raises(ValueError):
        amount(spelling)


def test_EA_N1_exact_floor_no_epsilon_or_ambient_context():
    value = amount("0.299999999999999999999999999999")
    assert value // amount("0.1") == 2
    with localcontext() as ctx:
        ctx.prec = 2
        assert value // amount("0.1") == 2
        assert (
            decimal_text(
                amount("1000000000000.000000000001") + amount("0.000000000002")
            )
            == "1000000000000.000000000003"
        )


def test_EA_N1_original_seven_fee_lexemes_and_all_golden_bytes_unchanged():
    inputs, args, signal = case()
    result = plan(inputs, args, signal)
    costs = OrderCosts(
        args["policy"], inputs["execution_open"]["session"], "research_restored"
    )
    expected = [
        "2.34143962",
        "2.28834654",
        "2.29674654",
        "2.38783962",
        "2.33929308",
        "2.4109327",
        "3.4",
    ]
    fees = []
    for o in result["net_orders"]:
        q = o["quantity"] * (-1 if o["side"] == "SELL" else 1)
        s = o["symbol"]
        notional = amount(inputs["execution_open"]["raw_open"][s]) * abs(q)
        fee = costs.quote_exact(
            {s: q},
            {s: Decimal(decimal_text(notional))},
            guard=args["guard"],
            execution_binding=args["scope"]["execution_binding"],
        )
        fees.append(decimal_text(fee))
    assert fees == expected
    assert sum(map(amount, fees), Fraction(0)) == amount("17.4645981")
    assert (
        hashlib.sha256(
            (ORACLE / "fixed-order-fee-worksheet.json").read_bytes()
        ).hexdigest()
        == "45c760b94c7c27a65545f871e5f3b8e86b359608c49b08dd174a86ebf9033f95"
    )


def test_EA_N1_exact_quote_rejects_lossy_input_without_smaller_order():
    inputs, args, _ = case()
    costs = OrderCosts(
        args["policy"], inputs["execution_open"]["session"], "research_restored"
    )
    with pytest.raises(ValueError, match="fee.exact_input_unavailable"):
        costs.quote_exact(
            {"QQQ": 1},
            {"QQQ": Decimal("1000000000000.000000000001")},
            guard=args["guard"],
            execution_binding=args["scope"]["execution_binding"],
        )


def test_product_has_no_oracle_or_literal_expected_access():
    root = Path(__file__).parents[2] / "qlab/dynamic_factor"
    for name in ("execution_projection.py", "execution_signals.py"):
        raw = (root / name).read_text()
        assert (
            "CF01" not in raw
            and "expected.canonical" not in raw
            and "b935b633" not in raw
        )


def test_EA_N3_actual_unspendable_sales_not_research_cash_or_lost_NAV():
    inputs, args, signal = case()
    inputs["schema"] = "EVO884.ProjectorInput/v1"
    inputs["close_state"].update(cash="3100", NAV_anchor="14200")
    args["state"].update(cash=3100, nav=14200)
    inputs["execution_open"]["cash_availability"] = {
        "mode": "accepted_actual",
        "available_sale_proceeds": {"CVS": "0", "COP": "0"},
    }
    actual = plan(inputs, args, signal)
    assert actual["P"]["QQQ"] == 100
    assert "projection.cancel_buy:QQQ:buffer" in actual["reasons"]
    inputs["execution_open"]["cash_availability"]["available_sale_proceeds"] = {
        "CVS": "300",
        "COP": "400",
    }
    funded = plan(inputs, args, signal)
    assert funded["P"]["QQQ"] == 110
    assert funded["NAV_anchor"] == "14200"


def test_EA_N2_N3_forward_never_falls_back_to_ideal_cash_model():
    inputs, args, signal = case()
    inputs["schema"] = "EVO884.ProjectorInput/v1"
    inputs["execution_open"]["cash_availability"] = {"mode": "research_immediate"}
    with pytest.raises(ValueError, match="ideal_cash_model_diagnostic_only"):
        plan(inputs, args, signal)


def test_EA_N3_missing_sale_cash_rejects_instead_of_crediting_it():
    inputs, args, signal = case()
    inputs["schema"] = "EVO884.ProjectorInput/v1"
    inputs["execution_open"]["cash_availability"] = {
        "mode": "accepted_actual",
        "available_sale_proceeds": {},
    }
    with pytest.raises(ValueError, match="actual_sale_cash_availability_unknown"):
        plan(inputs, args, signal)


def test_D1_under_min_age_no_voluntary_reduction_or_age_reset():
    inputs, args, signal = case()
    inputs["close_state"]["age"]["COP"] = args["state"]["age"]["COP"] = 1
    args["state"]["_risk_clock"]["entries"]["COP"] = args["close_session"]
    result = plan(inputs, args, signal)
    assert result["M"]["COP"] == result["P"]["COP"] == 4
    assert not any(o["symbol"] == "COP" for o in result["net_orders"])
    assert args["state"]["age"]["COP"] == 1


def test_D1_cooldown_cancels_full_target_without_changing_other_targets():
    inputs, args, signal = case()
    args["state"]["_risk_clock"]["cooldown_anchors"]["COST"] = args["close_session"]
    result = plan(inputs, args, signal)
    assert result["P"]["COST"] == 0
    assert result["P"]["QQQ"] == 117
    assert result["reasons"] == ["projection.cancel_buy:COST:risk.cooldown_active"]


def test_D1_cancel_full_reduction_instead_of_claiming_target_completed():
    inputs, args, signal = case()
    inputs["execution_open"]["raw_open"]["QQQ"] = "200"
    result = plan(inputs, args, signal)
    assert result["P"]["QQQ"] == 100
    assert "projection.cancel_reduction:QQQ:turnover" in result["reasons"]


def test_D1_nonfinite_in_ignored_metadata_does_not_hash_as_null():
    inputs, args, signal = case()
    inputs["source_declaration"]["new_field"] = float("nan")
    with pytest.raises(ValueError):
        plan(inputs, args, signal)


def test_D1_closed_output_schema_checks_actual_product_payload():
    from jsonschema import Draft202012Validator

    root = Path(__file__).parents[2] / "qlab/dynamic_factor/schemas"
    validator = Draft202012Validator(
        json.loads((root / "execution_projection.schema.json").read_text())
    )
    result = plan(*case())
    assert list(validator.iter_errors(result)) == []
    result["M"]["COP"] = True
    assert list(validator.iter_errors(result))
    result = plan(*case())
    result["generated_at"] = "2000-01-01T00:00:00Z"
    assert list(validator.iter_errors(result))


def test_D1_nonregular_rank_exit_is_diagnostic_not_an_extra_order_day():
    inputs, args, signal = case()
    inputs["close_state"]["age"]["CVS"] = args["state"]["age"]["CVS"] = 19
    p = args["policy"]
    clock = args["state"]["_risk_clock"]
    clock["entries"]["CVS"] = p.calendar[p.calendar.index(args["close_session"]) - 18]
    clock["global_start"] = p.calendar[p.calendar.index(clock["global_start"]) - 1]
    with pytest.raises(ValueError, match="no_locked_decision_for_this_open"):
        plan(inputs, args, signal)


def test_EA_N1_low_ambient_decimal_context_cannot_change_any_oracle_byte():
    with localcontext() as ctx:
        ctx.prec = 2
        result = plan(*case())
    actual = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    assert actual == (ORACLE / "CF01.expected.canonical.json").read_bytes()


def test_A13_B2_lineage_is_rejected_before_economic_projection():
    inputs, args, signal = case()
    inputs["close_state"]["source_benchmark"] = "VTI_analysis_TR"
    with pytest.raises(ValueError, match="B2"):
        plan(inputs, args, signal)

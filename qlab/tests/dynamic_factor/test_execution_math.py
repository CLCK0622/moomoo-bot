import pytest
from qlab.dynamic_factor.conventions import load_conventions, FIXTURES
from qlab.dynamic_factor.execution import (
    OrderCosts,
    calibrate_gain,
    initial_build_turnover_check,
    lock_startup_intent,
    nav_increment,
    startup_intent,
)
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.v1_harness import unit_context as synthetic_context


def startup_request(
    p,
    ledger,
    *,
    position=0,
    cash=15000,
    inventory=None,
    start_id="unit-start",
    scope="test-forward",
):
    inventory = inventory or {}
    nav = cash + inventory.get("QQQ", 0) * 100
    sessions = list(p.calendar[100:110])
    close = sessions[position] + "T16:00:00"
    intent = lock_startup_intent(
        position,
        nav,
        inventory,
        close,
        policy=p,
        ledger=ledger,
        start_id=start_id,
        scope_id=scope,
    )
    return {
        "intent": intent,
        "context": synthetic_context(p),
        "cash": cash,
        "previous_close": close,
        "reference_sessions": sessions,
        "raw_open_prices": {"QQQ": 100},
        "open_timestamp": sessions[position + 1] + "T09:30:00",
        "sell_date": sessions[position + 1],
        "rate_basis": "research_restored",
        "start_id": start_id,
    }


def test_staged_initialization_cash_fees_integer_and_no_extension(tmp_path):
    p = load_conventions()
    ledger = AttemptLedger(tmp_path / "unit.sqlite")
    cash, inventory = 15000, {}
    quantities = []
    for pos in range(6):
        req = startup_request(p, ledger, position=pos, cash=cash, inventory=inventory)
        r = initial_build_turnover_check(req, conventions=p, ledger=ledger)
        assert r["ok"], r["reasons"]
        m = r["metrics"]
        assert m["one_way_turnover"] <= 0.2 and type(m["quantity"]) is int
        cash, inventory = m["cash"], m["inventory"]
        assert cash >= 0.02 * (cash + inventory["QQQ"] * 100)
        quantities.append(m["quantity"])
        if pos == 5:
            assert m["regular_signal_due"] is True
    assert quantities[0] == 60 and quantities[3:] == [0, 0, 0]
    assert sum(quantities) < 147  # fees/cash reserve prevent nominal 98% rounding.
    with pytest.raises(ValueError, match="record_conflict"):
        startup_request(
            p, ledger, start_id="restart-at-next-fold", scope="test-forward"
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda r: r["raw_open_prices"].update(QQQ=None), "raw_open_price_invalid"),
        (lambda r: r["intent"].update(max_buy_notional=14700), "intent_not_locked"),
        (lambda r: r.update(previous_close="2000-01-01"), "intent_not_locked"),
        (lambda r: r.update(open_timestamp=r["previous_close"]), "intent_not_locked"),
        (lambda r: r.update(rate_basis="invented_zero_fees"), "rate_basis_unknown"),
    ],
)
def test_startup_missing_or_mutated_inputs_never_fabricate_fill(
    tmp_path, change, reason
):
    p = load_conventions()
    ledger = AttemptLedger(tmp_path / "unit.sqlite")
    req = startup_request(p, ledger)
    change(req)
    r = initial_build_turnover_check(req, conventions=p, ledger=ledger)
    assert not r["ok"] and r["metrics"]["quantity"] is None
    assert any(reason in s for s in r["reasons"])
    assert ledger.recorded("startup/unit-start/0") is None


def test_first_open_E0_no_98pct_upward_exception():
    p = load_conventions()
    assert (
        startup_intent(0, 15000, {}, "2026-01-01T16:00:00", p)["max_buy_notional"]
        == 6000
    )
    with pytest.raises(ValueError, match="zero_inventory"):
        startup_intent(0, 15000, {"QQQ": 1}, "2026-01-01T16:00:00", p)


@pytest.mark.parametrize(
    "M,P,alpha,mu,cM,cP,G,K,allow",
    [
        ({}, {"S": 20}, {"S": 0.01}, 0, 0, 30, 0.002, 0.003, False),
        ({"QQQ": 20}, {"S": 20}, {"S": 0.02}, 0.03, 10, 10, 0.004, 0, True),
        ({"S": 20}, {"QQQ": 20}, {"S": 0.02}, 0.03, 10, 10, -0.004, 0, False),
        ({}, {"QQQ": 20}, {}, 0.03, 20, 10, 0.006, 0, True),
        ({}, {"S": 20}, {"S": 0.01}, 0, 0, 20, 0.002, 0.002, False),
    ],
)
def test_gain_NAV_units_old_new_QQQ_cash_and_cost_floor(
    M, P, alpha, mu, cM, cP, G, K, allow
):
    out = nav_increment(M, P, {"S": 100, "QQQ": 100}, alpha, mu, 10000, cM, cP)
    assert out["G_H10"] == pytest.approx(G)
    assert out["K"] == pytest.approx(K)
    assert out["allowed"] is allow


def calibration_fixture(p, context):
    ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
    d = context["train_calendar"][0]
    rows = [
        {
            "date": d,
            "symbol": f"S{i:03}",
            "label_end": context["train_calendar"][11],
            "label_entry": context["train_calendar"][1],
            "stock_h10": 0.02 + i * 0.001,
            "qqq_h10": 0.01,
            "ranks": {k: (i + 0.5) / 50 for k in ids},
        }
        for i in range(50)
    ]
    return rows, calibrate_gain(rows, {d}, conventions=p, context=context)


def test_calibration_full_buckets_and_mature_labels_no_interpolation():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    context = synthetic_context(p)
    rows, cal = calibration_fixture(p, context)
    assert cal["mu_Q"] == 0.01
    assert cal["m"]["F1-L005"][0] == pytest.approx(0.012)
    with pytest.raises(ValueError, match="panel_incomplete"):
        calibrate_gain(rows[:-1], {rows[0]["date"]}, conventions=p, context=context)
    with pytest.raises(ValueError, match="outside_mature_train"):
        calibrate_gain(rows, set(), conventions=p, context=context)
    rows[0]["ranks"]["F1-L005"] = None
    with pytest.raises(ValueError, match="rank_invalid"):
        calibrate_gain(rows, {rows[0]["date"]}, conventions=p, context=context)


def test_calibration_rejects_mismatched_H10_interval():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    context = synthetic_context(p)
    rows, _ = calibration_fixture(p, context)
    rows[0]["label_end"] = context["train_calendar"][10]
    with pytest.raises(ValueError, match="interval_mismatch"):
        calibrate_gain(rows, {rows[0]["date"]}, conventions=p, context=context)


@pytest.mark.parametrize("price,quantity", [(50, 100), (1375, 1)])
def test_complete_plan_quote_preserves_existing_fee_frontier_mapping(price, quantity):
    from qlab.dynamic_factor.fees import FIXTURES, fee_frontier

    p = load_conventions()
    costs = OrderCosts(p, "2027-01-04", "effective_date")
    expected = fee_frontier(
        dict(
            price=price,
            ticket_usd=price * quantity,
            gross_edge_bps=0,
            sell_date="2027-01-04",
            rate_basis="effective_date",
            pnl_basis="reference",
        ),
        FIXTURES / "fee_params_x2.json",
        conventions=p,
    )
    quoted = costs.quote({"S": quantity}, {"S": price}) + costs.quote(
        {"S": -quantity}, {"S": price}
    )
    assert quoted == pytest.approx(
        expected["metrics"]["gate_cost_bps"] * price * quantity / 1e4
    )
    assert expected["common_profile_sha256"] == p.binding["common_profile_sha256"]

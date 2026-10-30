import json
import pytest
from qlab.dynamic_factor.fees import FIXTURES, fee_frontier


def fee(**kwargs):
    req = dict(
        price=50,
        ticket_usd=5000,
        gross_edge_bps=10,
        sell_date="2027-01-01",
        rate_basis="effective_date",
        pnl_basis="reference",
    )
    req.update(kwargs)
    return fee_frontier(req, FIXTURES / "fee_params_x1.json")


def test_restored_TAF_budget_all_research_dates():
    for day in ["2010-01-01", "2026-09-30", "2026-10-01", "2026-12-31", "2027-01-01"]:
        r = fee(sell_date=day)
        assert r["ok"] and r["metrics"]["taf_usd"] == pytest.approx(0.0195)
        assert r["metrics"]["rate_basis_effective"] == "research_restored"
        assert r["metrics"]["actual_fee_usd"] is None


def test_per_order_floor_stress_turnover_and_no_double_friction():
    a = fee()["metrics"]
    request = dict(
        price=50,
        ticket_usd=5000,
        gross_edge_bps=10,
        sell_date="2027-01-01",
        pnl_basis="reference",
    )
    b = fee_frontier(request, FIXTURES / "fee_params_x2.json")["metrics"]
    assert a["research_cost_usd"] == 10 and b["research_cost_usd"] == 20
    assert a["net_edge_bps"] == -10 and b["net_edge_bps"] == -30
    assert a["annual_drag_fraction"] is None
    assert fee(one_way_daily_turnover=0)["metrics"]["annual_drag_fraction"] == 0
    cash = fee(pnl_basis="cash_bid_ask")["metrics"]
    assert cash["net_edge_bps"] - a["net_edge_bps"] == pytest.approx(4)
    assert cash["friction_deducted_bps"] == 0


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"price": 0}, "invalid_notional_or_edge"),
        ({"price": float("nan")}, "invalid_notional_or_edge"),
        ({"ticket_usd": 49}, "integer_ticket_unaffordable"),
        ({"algo_order": True}, "algo_orders_not_allowed"),
        ({"pnl_basis": "unknown"}, "pnl_basis_unknown"),
    ],
)
def test_invalid_fee_inputs_refuse(values, reason):
    r = fee(**values)
    assert r["reasons"] == [reason] and r["metrics"]["net_edge_bps"] is None
    json.dumps(r, allow_nan=False)


def test_bound_original_fee_files_cannot_be_repriced(tmp_path):
    raw = (FIXTURES / "fee_params_x1.json").read_bytes()
    params = json.loads(raw)
    params["platform_per_order"] = 3
    path = tmp_path / "altered.json"
    path.write_text(json.dumps(params))
    r = fee_frontier({}, path)
    assert r["reasons"] == ["fee_params_not_bound_to_conventions"]


def test_missing_or_invalid_fee_file_is_refusal(tmp_path):
    path = tmp_path / "missing.json"
    assert fee_frontier({}, path)["reasons"] == ["fee_file_missing"]
    path.write_text("invalid JSON")
    assert fee_frontier({}, path)["reasons"] == ["fee_file_invalid"]


@pytest.mark.parametrize("name", ["fee_params_x1.json", "fee_params_x2.json"])
@pytest.mark.parametrize(
    "day", ["2026-09-30", "2026-10-01", "2026-12-31", "2027-01-01"]
)
def test_legacy_private_date_numeric_path_is_disabled(name, day):
    from qlab.dynamic_factor.fees import _legacy_fee_frontier

    r = _legacy_fee_frontier(
        dict(
            price=50,
            ticket_usd=5000,
            gross_edge_bps=10,
            sell_date=day,
            rate_basis="effective_date",
            pnl_basis="reference",
        ),
        FIXTURES / name,
    )
    assert r["reasons"] == ["fee.legacy_frontier_disabled"]
    assert r["metrics"]["taf_usd"] is r["metrics"]["net_edge_bps"] is None

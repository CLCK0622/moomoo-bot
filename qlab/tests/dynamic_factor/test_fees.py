import json

import pytest

from qlab.dynamic_factor.fees import FIXTURES, fee_frontier


def fee(**kwargs):
    request = dict(
        price=50,
        ticket_usd=5000,
        gross_edge_bps=10,
        sell_date="2027-01-01",
        rate_basis="effective_date",
        pnl_basis="reference",
    )
    request.update(kwargs)
    return fee_frontier(request, FIXTURES / "fee_params_x1.json")


def test_effective_date_boundary_and_missing_history():
    q4 = fee(sell_date="2026-12-31")["metrics"]
    jan = fee(sell_date="2027-01-01")["metrics"]
    assert q4["taf_usd"] == 0
    assert jan["taf_usd"] == pytest.approx(0.0195)
    assert jan["explicit_usd"] - q4["explicit_usd"] == pytest.approx(0.0195 * 1.09)
    assert fee(sell_date="2010-01-01")["reasons"] == [
        "fee_effective_date_uncovered_or_ambiguous"
    ]
    history = fee(sell_date="2010-01-01", rate_basis="research_restored")
    assert history["ok"] and any("not historical" in a for a in history["assumptions"])


def test_cost_crosscheck_and_stress():
    a = fee()["metrics"]
    assert a["cost_bps"] * a["value_usd"] / 1e4 * 2 == pytest.approx(9.892758)
    request = dict(
        price=50,
        ticket_usd=5000,
        gross_edge_bps=10,
        sell_date="2027-01-01",
        rate_basis="effective_date",
        pnl_basis="reference",
    )
    b = fee_frontier(request, FIXTURES / "fee_params_x2.json")["metrics"]
    assert b["cost_bps"] == pytest.approx(2 * a["cost_bps"])
    assert (a["net_edge_bps"], b["net_edge_bps"]) == (-10, -30)
    assert a["annual_drag_fraction"] is None
    assert fee(one_way_daily_turnover=0)["metrics"]["annual_drag_fraction"] == 0


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"price": 0}, "invalid_notional_or_edge"),
        ({"price": float("nan")}, "invalid_notional_or_edge"),
        ({"ticket_usd": 49}, "integer_ticket_unaffordable"),
        ({"algo_order": True}, "algo_orders_not_allowed"),
        ({"sell_date": "2027-01-01T00:00:00Z"}, "fee_input_invalid_or_missing"),
        ({"pnl_basis": "unknown"}, "pnl_basis_unknown"),
        ({"one_way_daily_turnover": None}, None),
    ],
)
def test_fee_boundaries(values, reason):
    r = fee(**values)
    assert r["reasons"] == ([reason] if reason else [])
    json.dumps(r, allow_nan=False)


def test_fees_are_read_from_file(tmp_path):
    params = json.loads((FIXTURES / "fee_params_x1.json").read_bytes())
    params["platform_per_order"] = 3
    path = tmp_path / "params.json"
    path.write_text(json.dumps(params))
    request = dict(
        price=50,
        ticket_usd=5000,
        gross_edge_bps=10,
        sell_date="2027-01-01",
        rate_basis="effective_date",
        pnl_basis="reference",
    )
    r = fee_frontier(request, path)
    assert r["metrics"]["explicit_usd"] > fee()["metrics"]["explicit_usd"]
    assert r["input_sha256"] != fee()["input_sha256"]


def test_bidask_never_pays_baseline_friction_twice():
    cash, ref = fee(pnl_basis="cash_bid_ask"), fee()
    assert ref["metrics"]["cash_net_edge_bps"] - cash["metrics"][
        "cash_net_edge_bps"
    ] == pytest.approx(-4)
    assert cash["metrics"]["friction_deducted_bps"] == 0


def test_missing_or_corrupt_parameter_file_is_structured_refusal(tmp_path):
    missing = tmp_path / "missing.json"
    r = fee_frontier({}, missing)
    assert r["reasons"] == ["fee_file_missing"]
    assert r["missing_inputs"] == ["params_sha256"]
    assert r["metrics"]["net_edge_bps"] is None
    missing.write_bytes(b"not JSON")
    r = fee_frontier({}, missing)
    assert r["reasons"] == ["fee_file_invalid"]
    assert len(r["input_sha256"]) == 64

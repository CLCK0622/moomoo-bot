import json
import subprocess
import sys

import pytest

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.fees import FIXTURES, fee_frontier
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.reference_check import (
    reference_manifest_check,
    register_reference_attempts,
    static_proof,
)
from qlab.dynamic_factor.reference_producer import prepare
from qlab.dynamic_factor.statistics import dsr_eval
from qlab.dynamic_factor.v1_harness import registry_fixture, producer_fixture, wrapped
from qlab.dynamic_factor.valuation import benchmark_valuation, integer_cash_valuation
from qlab.dynamic_factor.validation import wf_manifest_check


@pytest.mark.parametrize("role", ["candidate", "meta"])
@pytest.mark.parametrize(
    "failure",
    [
        "missing_registry",
        "missing_manifest",
        "sha",
        "member",
        "old_profile",
        "late_registration",
    ],
)
def test_registry_manifest_guards_always_leave_DSR_V_null(role, failure):
    p = load_conventions()
    request = registry_fixture(p)
    if failure == "missing_registry":
        request["registry"] = None
    elif failure == "missing_manifest":
        request["manifests"].pop(role)
    elif failure == "sha":
        request["manifests"][role]["sha256"] = "0" * 64
    elif failure == "member":
        doc = json.loads(request["manifests"][role]["raw"])
        doc["members"].append(dict(doc["members"][0], member_id="NOT_REGISTERED"))
        request["manifests"][role] = wrapped(doc)
    elif failure == "old_profile":
        registry = request["registry"]["document"]
        registry["bindings"]["common_profile_sha256"] = (
            "e2ed67fc4ec9ed709c4a77ac5a72165da7dc3843e8030e5fa57aee0164058d30"
        )
        request["registry"] = wrapped(registry)
    else:
        request["first_performance_at"] = "2025-01-01T00:00:00Z"
    r = reference_manifest_check(request, conventions=p)
    assert not r["ok"] and not r["certifiable"] and not r["runtime_consumable"]
    assert r["metrics"]["dsr"] is None and r["metrics"]["trials_variance"] is None


def test_fixture_registry_validation_is_not_runtime_certification_and_refs_count_N(
    tmp_path,
):
    p = load_conventions()
    request = registry_fixture(p)
    r = reference_manifest_check(request, conventions=p)
    assert r["ok"] and r["metrics"]["registry_valid"]
    assert r["metrics"]["dsr"] is None and not r["runtime_consumable"]
    ledger = fixture_ledger(tmp_path / "refs.sqlite", p)
    attempts = register_reference_attempts(
        request["registry"],
        request["manifests"],
        policy=p,
        ledger=ledger,
        fold_id="0",
        first_performance_at=request["first_performance_at"],
    )
    assert len(attempts) == 4 and ledger.snapshot()["cumulative_n_lower_bound"] == 51
    ledger.finish(attempts[0], "failed", reason="fixture_failed")
    ledger.finish(attempts[1], "nan", sharpe=float("nan"))
    assert fixture_ledger(ledger.path, p).snapshot()["cumulative_n_lower_bound"] == 51
    with pytest.raises(ValueError, match="already_claimed"):
        register_reference_attempts(
            request["registry"],
            request["manifests"],
            policy=p,
            ledger=ledger,
            fold_id="0",
            first_performance_at=request["first_performance_at"],
        )
    r = dsr_eval(request, ledger, conventions=p)
    assert r["metrics"]["dsr"] is None and r["metrics"]["trials_variance"] is None
    assert not r["runtime_consumable"]


def test_reference_uses_shared_splitter_and_pinned_three_reader_graph(tmp_path):
    p = load_conventions()
    request = producer_fixture(tmp_path / "inputs", p)
    result = prepare(tmp_path / "inputs", request)
    assert result["train_dates"] == list(request["view"]["train"])
    assert len(result["train_dates"]) == 1260 and result["returns"] is None
    proof = static_proof()
    assert set(proof["import_graph"]) == {
        "reference_producer",
        "reference_inputs",
        "fold_split",
        "reference_guard",
        "input_scope",
    }
    assert proof["reader_sites"][0]["module"] == "reference_inputs"
    assert len(proof["reader_sites"]) == 1
    assert "pipeline" not in proof["import_graph"]["reference_producer"]
    command = [
        sys.executable,
        "-m",
        "qlab.dynamic_factor.reference_producer",
        "--inputs-root",
        str(tmp_path / "inputs"),
    ]
    run = subprocess.run(
        command, input=json.dumps(request) + "\n", capture_output=True, text=True
    )
    assert run.returncode == 2 and json.loads(run.stdout)["returns"] is None


@pytest.mark.parametrize(
    "failure",
    ["candidate_path", "meta_role", "test_row", "copied_output", "candidate_stdin"],
)
def test_producer_cannot_read_or_copy_current_outputs_or_test(tmp_path, failure):
    p = load_conventions()
    root = tmp_path / "inputs"
    request = producer_fixture(root, p)
    if failure == "candidate_path":
        request["inputs"]["panel"]["file"] = "candidate-returns.json"
    elif failure == "meta_role":
        request["inputs"]["meta"] = request["inputs"]["panel"]
    elif failure == "candidate_stdin":
        request["candidate_returns"] = [0.99] * 1260
    else:
        path = root / "panel.json"
        doc = json.loads(path.read_bytes())
        if failure == "test_row":
            doc["rows"].append({"date": "2099-01-01", "prices": {"UNIT": 1}})
        else:
            doc = {
                "schema": "dynamic_factor.candidate_returns",
                "returns": [0.99] * 1260,
            }
        path.write_text(json.dumps(doc))
        request["inputs"]["panel"]["sha256"] = sha256(path.read_bytes())
    with pytest.raises(ValueError, match="reference."):
        prepare(root, request)


def order(qty, status="partial", date="2026-12-01", oid="Q"):
    return dict(
        broker_order_id=oid,
        exchange_local_trade_date=date,
        side="sell",
        quantity=qty,
        notional=qty * 100,
        planned_quantity=100,
        status=status,
        time_in_force="DAY",
    )


def costs(orders, **kwargs):
    request = dict(orders=orders, pnl_basis="reference", normalizer_usd=10000)
    request.update(kwargs)
    return fee_frontier(request, FIXTURES / "fee_params_x2.json")


def test_partial_cumulative_charges_increment_once_and_closes_DAY_remainder():
    r = costs([order(40), order(40), order(60, "eod")])
    assert r["ok"]
    events = r["metrics"]["fee_events"]
    assert events[1]["research_cost_increment_usd"] == 0
    assert (
        sum(e["research_cost_increment_usd"] for e in events)
        == r["metrics"]["research_cost_usd"]
    )
    assert events[-1]["remainder_cancelled"] and events[-1]["residual_quantity"] == 40
    assert r["metrics"]["actual_fee_usd"] is None
    assert any("QQQ startup" in a for a in r["assumptions"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(time_in_force="GTC"),
        lambda x: x.update(quantity=101),
        lambda x: x.update(exchange_local_trade_date="2026-12-02"),
    ],
)
def test_DAY_order_or_crossday_violations_refuse(mutation):
    second = order(60)
    mutation(second)
    r = costs([order(40), second])
    assert not r["ok"] and r["metrics"]["research_cost_usd"] is None


def test_new_date_new_order_gets_new_minima_and_unknown_new_rate_refuses():
    assert costs([order(40, "eod"), order(40, "eod", date="2026-12-02", oid="NEW")])[
        "ok"
    ]
    r = costs(
        [order(40)],
        known_rate_changes=[dict(effective_date="2026-11-01", params_sha256=None)],
    )
    assert r["reasons"] == ["fee.new_rate_receipt_missing"]
    assert (
        r["metrics"]["net_edge_bps"] is None
        and r["metrics"]["research_cost_usd"] is None
    )


def test_QQQ_analytical_uses_bound_D_used_without_claiming_cash_or_formal_returns():
    r = benchmark_valuation(
        dict(
            symbol="QQQ",
            price_basis="raw_close",
            raw_source_sha256=digest("unit"),
            prices=[
                dict(date="2022-12-16", close=100),
                dict(date="2022-12-19", close=99),
                dict(date="2022-12-20", close=100),
            ],
        )
    )
    assert r["ok"]
    assert r["metrics"]["analytical_index"][1]["index"] == pytest.approx(99 + 0.65541)
    assert r["metrics"]["formal_return"] is None and not r["certifiable"]
    assert r["metrics"]["event_statuses"]["2022-12-19"]["D_used_for_TR"] == "0.655410"


@pytest.mark.parametrize("symbol", ["SPY", "VTI"])
def test_VTI_missing_never_uses_SPY_as_B2(symbol):
    r = benchmark_valuation(
        dict(
            symbol=symbol,
            price_basis="raw_close",
            raw_source_sha256=digest("unit"),
            prices=[dict(date="2026-01-05", close=100)],
        )
    )
    assert not r["ok"] and r["metrics"]["analytical_index"] is None
    assert r["metrics"]["formal_return"] is None


def test_formal_calendar_check_requires_VTI_evidence():
    p = load_conventions()
    m = p.fold_manifest()
    m.update(benchmarks=["QQQ", "SPY"])
    assert wf_manifest_check(m, conventions=p)["reasons"] == [
        "data.VTI_fixed_B2_required"
    ]
    m["benchmarks"].append("VTI")
    assert wf_manifest_check(m, conventions=p)["reasons"] == [
        "data.vti_evidence_missing"
    ]


def dividend(**kwargs):
    from qlab.dynamic_factor.input_disposition import qqq_cash_input

    event = qqq_cash_input("2022-12-19", 2)
    event["simulated_payment_available"] = False
    event.update(kwargs)
    return event


def cash_read(event, day="2022-12-20"):
    return integer_cash_valuation(
        dict(
            known_cash=100,
            as_of=day,
            inventory={"QQQ": 2},
            marks={"QQQ": 100},
            events=[event],
        )
    )


def test_supported_receivable_moves_to_cash_only_with_payment_receipt_no_DRIP():
    before = cash_read(dividend())
    assert (
        before["metrics"]["available_cash"] == 100
        and before["metrics"]["receivable_amount"] == 1.31082
    )
    assert before["metrics"]["nav"] == pytest.approx(301.31082)
    paid = cash_read(
        dividend(
            simulated_payment_available=True,
            simulated_cash_credited_amount=1.31082,
            simulated_cash_credited_at="2022-12-30",
            simulated_payment_source_sha256=digest(
                "synthetic_inventory_writer_receipt"
            ),
        ),
        day="2022-12-30",
    )
    assert (
        paid["metrics"]["available_cash"] == pytest.approx(101.31082)
        and paid["metrics"]["receivable_amount"] == 0
    )
    assert paid["metrics"]["inventory"] == {"QQQ": 2} and paid["metrics"][
        "nav"
    ] == pytest.approx(301.31082)


@pytest.mark.parametrize(
    "change",
    [
        dict(declared_cash_amount=None),
        dict(exact_amount_status="aggregate_only"),
        dict(pay_date=None),
        dict(pay_date_status="unknown"),
    ],
)
def test_unknown_dividends_do_not_become_zero_cash(change):
    r = cash_read(dividend(**change))
    assert r["metrics"]["nav"] is None
    assert r["metrics"]["dividends"][0]["cash_credited_amount"] is None
    assert r["metrics"]["known_available_cash"] == 100


def test_ex_open_entry_has_no_dividend_entitlement():
    r = cash_read(dividend(entry_date="2022-12-19"))
    assert r["reasons"] == ["valuation.ex_open_entry_not_dividend_entitled"]


def test_CLI_genesis_override_and_missing_conventions_refuse_before_DB_creation(
    tmp_path,
):
    source = tmp_path / "request.json"
    source.write_text('{"metrics":{}}')
    forged = tmp_path / "genesis.json"
    forged.write_text('{"prior_n":0,"count_complete":true}')
    base = [
        sys.executable,
        "-m",
        "qlab.dynamic_factor",
        "dsr_eval",
        "--input",
        str(source),
        "--ledger",
        str(tmp_path / "forged.sqlite"),
    ]
    r = subprocess.run(base, capture_output=True, text=True)
    assert (
        r.returncode == 2
        and "wf.conventions_required" in json.loads(r.stdout)["reasons"]
    )
    r = subprocess.run(
        base
        + [
            "--conventions",
            str(FIXTURES / "conventions-v1.0.1.json"),
            "--genesis",
            str(forged),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2 and json.loads(r.stdout)["reasons"] == [
        "ledger.custom_genesis_forbidden"
    ]
    assert not (tmp_path / "forged.sqlite").exists()


def test_CLI_startup_refuses_synthetic_unit_ledger(tmp_path):
    policy = load_conventions()
    ledger = fixture_ledger(tmp_path / "ledger.sqlite", policy)
    source = tmp_path / "intent.json"
    source.write_text(
        json.dumps(
            dict(
                position=0,
                previous_nav=15000,
                inventory={},
                previous_close=policy.calendar[0],
                start_id="unit",
                scope_id="synthetic",
            )
        )
    )
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlab.dynamic_factor",
            "startup_intent",
            "--input",
            str(source),
            "--ledger",
            str(ledger.path),
            "--ledger-anchor",
            str(ledger.anchor_path),
            "--conventions",
            str(FIXTURES / "conventions-v1.0.1.json"),
        ],
        capture_output=True,
        text=True,
    )
    report = json.loads(r.stdout)
    assert r.returncode == 2 and not report["ok"]
    assert report["common_profile_sha256"] == policy.binding["common_profile_sha256"]
    assert report["runtime_consumable"] is False
    assert ledger.recorded("startup/unit/intent/0") is None

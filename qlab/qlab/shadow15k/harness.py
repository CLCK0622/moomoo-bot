"""Fixed synthetic inputs, networking disabled, no clock or RNG dependence."""

from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.fees import FIXTURES as TOOL_FIXTURES
from qlab.dynamic_factor.input_disposition import MAPPING_SHA
from qlab.dynamic_factor.conventions import load_conventions

from . import policy
from .contract import ASSUMPTIONS, source_binding
from .fees import FeeBook
from .ledger import ShadowLedger

FIXTURE = Path(__file__).parent / "fixtures" / "cases.json"
FEE_SHAS = {
    "x1": "7e24f9e9b25802a7d4b50bd4b089a60d288b8f8f448ea92aac9482816b7ffdb2",
    "x2": "a81bb5790638e9730dec666a695bbb797ab1ec7fe817e666f744193cfa6f9044",
    "schedule": "c400412f361a659290289517adf640e1fc2610560e203dc79bf76975e87c7fd9",
}
POLICY_TOOLS = (
    policy.pool_admission_check,
    policy.tilt_weights,
    policy.initial_build_turnover_check,
    policy.turnover_check,
    policy.voluntary_trade_gate,
    policy.rebalance_plan,
    policy.retirement_check,
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fixture_fees(scenario):
    return FeeBook(
        TOOL_FIXTURES / ("fee_params_" + scenario + ".json"),
        TOOL_FIXTURES / "fee_schedule.json",
        params_sha256=FEE_SHAS[scenario],
        schedule_sha256=FEE_SHAS["schedule"],
    )


@contextmanager
def offline():
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("network_attempt")
        raise RuntimeError("harness_network_disabled")

    with (
        patch.object(socket, "socket", deny),
        patch.object(socket, "create_connection", deny),
        patch.object(socket, "getaddrinfo", deny),
    ):
        yield attempts
    require(not attempts, "harness attempted networking")


def run(workdir):
    workdir = Path(workdir)
    if workdir.exists() and any(workdir.iterdir()):
        raise ValueError("empty_harness_workdir_required")
    workdir.mkdir(parents=True, exist_ok=True)
    raw = FIXTURE.read_bytes()
    data = json.loads(raw)
    fees = {s: fixture_fees(s) for s in ("x1", "x2")}
    results = []
    with (
        offline() as attempts,
        patch("qlab.shadow15k.ledger.PHYSICAL_ROOT", workdir.resolve()),
    ):
        for case in data["cases"]:
            cid, expected = case["case_id"], case["expected"]
            if "orders" in case:
                ledger = ShadowLedger(
                    workdir / cid / "shadow15k", data["genesis"], fees["x1"]
                )
                request = dict(
                    intent_id="case-intent",
                    decision_ts=data["decision_ts"],
                    input_hash=digest(case),
                    orders=case["orders"],
                )
                require(ledger.register_intent(request)["ok"], cid + " intent")
                for receipt in case["receipts"]:
                    require(
                        ledger.record_receipt("case-intent", receipt)["ok"],
                        cid + " receipt",
                    )
                result = ledger.readout(case["marks"])
                observed = {k: result["metrics"][k] for k in expected}
                for k, value in expected.items():
                    actual = observed[k]
                    require(
                        Decimal(actual) == Decimal(value)
                        if k == "cash" and value is not None
                        else actual == value,
                        cid + " mismatch: " + k + "=" + str(actual),
                    )
                # Same IDs after reopening must never book the snapshots twice.
                reopened = ShadowLedger(ledger.root, data["genesis"], fees["x1"])
                require(
                    not reopened.register_intent(request)["metrics"]["registered"],
                    cid + " duplicate intent",
                )
                repeated = reopened.record_receipt("case-intent", case["receipts"][0])
                require(
                    repeated["ok"] and not repeated["metrics"]["registered"],
                    cid + " duplicate receipt",
                )
                require(
                    result == reopened.readout(case["marks"]),
                    cid + " restart changed report",
                )
                if cid == "intent.retry_requires_reconcile":
                    next_request = dict(request, intent_id="next-intent")
                    require(
                        not reopened.register_intent(next_request)["ok"],
                        "unknown allowed next intent",
                    )
                    observed["new_intent_blocked"] = True
                observed["ledger_sha256"] = result["metrics"]["ledger_sha256"]
                observed["postings"] = result["metrics"]["postings"]
            elif cid == "cost.cash_vs_reference_no_double":
                args = {k: case[k] for k in ("qty", "notional", "side", "trade_date")}
                cash = fees["x1"].cumulative(**args, price_basis="cash_bid_ask")
                ref = fees["x1"].cumulative(**args, price_basis="reference")
                stress = fees["x2"].cumulative(**args, price_basis="cash_bid_ask")
                observed = dict(
                    x1_cash_friction=cash["friction"],
                    x1_reference_friction=ref["friction"],
                    x2_cash_friction=stress["friction"],
                )
                require(
                    all(
                        Decimal(observed[k]) == Decimal(v) for k, v in expected.items()
                    ),
                    cid,
                )
                for key in (
                    "broker",
                    "settlement",
                    "sec",
                    "cat",
                    "taf",
                    "gst",
                    "explicit",
                    "gate_floor_diagnostic",
                ):
                    require(
                        Decimal(stress[key]) == 2 * Decimal(cash[key]),
                        "x2 line not doubled: " + key,
                    )
            elif cid == "cost.partial_cumulative_not_per_fill":
                a, b = [
                    fees["x1"].cumulative(
                        **p,
                        side="BUY",
                        trade_date="2026-12-31",
                        price_basis="cash_bid_ask",
                    )
                    for p in case["partials"]
                ]
                observed = dict(
                    first_fee=a["charged"],
                    total_fee=b["charged"],
                    increment=str(Decimal(b["charged"]) - Decimal(a["charged"])),
                )
                require(
                    all(
                        Decimal(observed[k]) == Decimal(v) for k, v in expected.items()
                    ),
                    str(observed),
                )
            elif cid == "cost.taf_restored_all_dates":
                a, b = [
                    fees["x1"].cumulative(
                        qty=case["qty"],
                        notional=case["notional"],
                        side=case["side"],
                        trade_date=d,
                        price_basis="cash_bid_ask",
                    )
                    for d in case["dates"]
                ]
                observed = dict(
                    before_taf=a["taf"],
                    after_taf=b["taf"],
                    after_explicit=b["explicit"],
                )
                require(
                    all(
                        Decimal(observed[k]) == Decimal(v) for k, v in expected.items()
                    ),
                    str(observed),
                )
            elif cid == "policy.all_interfaces_refuse":
                observations = [tool(case["request"]) for tool in POLICY_TOOLS]
                require(
                    all(
                        r["reasons"] == [expected["reason"]]
                        and not r["ok"]
                        and not r["metrics"]["allowed"]
                        and r["metrics"]["parameters"] is None
                        for r in observations
                    ),
                    cid,
                )
                observed = {
                    "refused": [r["tool"] for r in observations],
                    "reason": expected["reason"],
                }
            elif cid == "namespace.isolated_restart":
                ledger = ShadowLedger(
                    workdir / cid / "shadow15k", data["genesis"], fees["x1"]
                )
                marks = dict(
                    as_of=data["decision_ts"], price_basis="cash_bid_ask", prices={}
                )
                observed = {k: ledger.readout(marks)["metrics"][k] for k in expected}
                require(observed == expected, cid)
            else:
                raise AssertionError("unhandled case: " + cid)
            results.append(
                dict(
                    case_id=cid,
                    status="PASS",
                    input_sha256=digest(case),
                    observed=observed,
                )
            )
        from .cash_harness import cases as cash_cases

        revisions = cash_cases(workdir / "cash-revisions", data["genesis"], fees["x1"])
        from .b4_harness import cases as b4_cases

        revisions.extend(
            b4_cases(workdir / "b4-revisions", data["genesis"], fees["x1"])
        )
    return dict(
        schema="shadow15k.harness/v1",
        status="PASS",
        cases_passed=len(results),
        cases=results,
        input_sha256=digest(
            {
                "cases_sha256": sha256(raw),
                "fees": FEE_SHAS,
                "QQQ_mapping": MAPPING_SHA,
                **load_conventions().binding,
            }
        ),
        **load_conventions().binding,
        QQQ_source_mapping_sha256=MAPPING_SHA,
        revision_cases=revisions,
        revision_cases_passed=len(revisions),
        fixture_sha256={"cases.json": sha256(raw), **FEE_SHAS},
        **source_binding(),
        assumptions=ASSUMPTIONS + fees["x1"].assumptions,
        network_attempts=len(attempts),
        strategy_backtests=0,
        forward_samples=0,
        certifiable=False,
        meta_strategy_status=policy.PENDING,
        dependencies={
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
            "external": [],
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.workdir),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

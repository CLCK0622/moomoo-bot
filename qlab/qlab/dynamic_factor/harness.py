"""Ten fixed offline negative cases. Run with a fresh --workdir; no time or RNG inputs."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from .contract import digest, sha256, source_manifest
from .fees import FIXTURES, fee_frontier
from .folds import run_walk_forward
from .ledger import AttemptLedger
from .receipts import IntentJournal, shadow_readout
from .statistics import dsr_eval
from .validation import wf_manifest_check


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def offline():
    attempts = []

    def denied(*args, **kwargs):
        attempts.append("network_attempt")
        raise RuntimeError("harness_network_disabled")

    with (
        patch.object(socket, "socket", denied),
        patch.object(socket, "create_connection", denied),
        patch.object(socket, "getaddrinfo", denied),
    ):
        yield attempts
    require(not attempts, "harness attempted network access")


def _fee(basis="reference", path="fee_params_x1.json", **kwargs):
    request = dict(
        price=50,
        ticket_usd=5000,
        gross_edge_bps=10,
        sell_date="2027-01-04",
        rate_basis="effective_date",
        pnl_basis=basis,
    )
    request.update(kwargs)
    return fee_frontier(request, FIXTURES / path)


def _receipt(**kwargs):
    leg = dict(symbol="X", planned_qty=100, confirmed_qty=100, fee_usd=1, mark=50)
    leg.update(kwargs)
    return {"legs": [leg]}


def _wf():
    days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    return dict(
        calendar=days,
        label_horizon=1,
        embargo=0,
        folds=[
            dict(
                fold_id="one",
                train_start=days[0],
                train_end=days[1],
                test_start=days[3],
                test_end=days[4],
            )
        ],
        portfolio="portfolio",
        benchmarks=["SPY"],
        series={
            k: [dict(date=d, close=100) for d in days] for k in ("portfolio", "SPY")
        },
    )


def run(workdir):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if any(workdir.iterdir()):
        raise ValueError("harness_workdir_must_be_empty: preserve prior evidence")
    cases = []

    def record(case_id, outputs, observed):
        for output in outputs:
            require(
                output["certifiable"] is False, "negative case unexpectedly certifiable"
            )
            require(
                len(output["source_sha256"]) == 64
                and len(output["input_sha256"]) == 64,
                "missing fingerprints",
            )
        cases.append(
            dict(
                case_id=case_id,
                status="PASS",
                observed=observed,
                input_sha256=digest([r["input_sha256"] for r in outputs]),
            )
        )

    with offline() as network:
        r = _fee()
        require(
            r["ok"] and r["metrics"]["net_edge_bps"] == -10, "10 gross - 20 gate != -10"
        )
        require(not r["metrics"]["positive_net_edge"], "negative edge passed")
        record("fee.positive_gross_negative_net", [r], {"net_edge_bps": -10})

        p = workdir / "attempts.sqlite"
        ledger = AttemptLedger(p)
        for aid, status, sr in [
            ("failed", "failed", None),
            ("nan", "nan", float("nan")),
            ("duplicate-a", "duplicate", None),
            ("duplicate-b", "duplicate", None),
        ]:
            ledger.begin(aid, {"expression": "same"})
            ledger.finish(aid, status, sharpe=sr)
        ledger.begin("interrupted", {"expression": "same"})
        before = ledger.snapshot()
        ledger = AttemptLedger(p)
        require(
            ledger.snapshot() == before and before["local_attempts_n"] == 5,
            "lost attempts",
        )
        ledger.begin("duplicate-a", {"expression": "same"})
        require(ledger.snapshot() == before, "transport replay double-counted")
        r = dsr_eval({"cumulative_n": 1}, ledger)
        require(
            "ledger_authority_unset" in r["reasons"] and r["metrics"]["dsr"] is None,
            "winner-only N accepted",
        )
        record(
            "trial.failed_attempts_persist",
            [r],
            {
                "local_attempts_n": 5,
                "cumulative_n": None,
                "n_ledger_hash": before["n_ledger_hash"],
                "restart_equal": True,
            },
        )

        manifest = _wf()
        manifest["folds"][0]["train_end"] = manifest["calendar"][2]
        calls = []
        r = run_walk_forward(
            manifest,
            [],
            miner_factory=lambda ctx: calls.append(ctx),
            fitter_factory=lambda ctx: calls.append(ctx),
            ledger=ledger,
            run_id="leak",
        )
        require(
            not calls and "wf.future_label_rejected" in r["reasons"],
            "label crossed test boundary",
        )
        # Fit-date falsification is exercised end-to-end in the unit suite as well.
        from .folds import FitReceipt

        class FakeHistory:
            def mine(self, train):
                return [{"expression": "fixed"}]

        class FalseFitter:
            def fit(self, train, proposals):
                return FitReceipt(object(), ("1900-01-01",), "wrong", digest(proposals))

        good = _wf()
        rows = [
            dict(
                date=d,
                features={"x": i},
                target=1,
                label_end=good["calendar"][min(i + 1, 4)],
            )
            for i, d in enumerate(good["calendar"])
        ]
        fake = run_walk_forward(
            good,
            rows,
            miner_factory=lambda ctx: FakeHistory(),
            fitter_factory=lambda ctx: FalseFitter(),
            ledger=ledger,
            run_id="fake",
        )
        require(
            "wf.full_history_or_mutated_fit_rejected" in fake["reasons"],
            "pseudo-fold accepted",
        )
        record(
            "wf.future_label_rejected",
            [r, fake],
            {"label_rejected": True, "full_history_rejected": True},
        )

        reports = [
            dsr_eval(x, ledger)
            for x in (
                {"sharpe_scale": "annualized", "sharpe": 1},
                {"sharpe_scale": "per_period"},
                {"n": None, "v": None},
            )
        ]
        require(
            all(
                "prereg_missing" in x["reasons"]
                and x["metrics"]["dsr"] is None
                and x["metrics"]["trials_variance"] is None
                for x in reports
            ),
            "invented DSR/V",
        )
        record(
            "dsr.scale_and_v_required",
            reports,
            {"dsr": None, "trials_variance": None, "reason": "prereg_missing"},
        )

        r = shadow_readout(_receipt(confirmed_qty=60))
        require(
            r["metrics"]["residual_qty"]["X"] == 40
            and not r["metrics"]["execution_verified"],
            "partial receipt called complete",
        )
        record(
            "paper.partial_is_incomplete",
            [r],
            {"confirmed_qty": 60, "residual_qty": 40},
        )

        receipt = _receipt()
        receipt["legs"].append(
            dict(
                symbol="PROTECTION",
                planned_qty=-100,
                confirmed_qty=0,
                fee_usd=0,
                mark=None,
                protective=True,
            )
        )
        r = shadow_readout(receipt)
        require(
            not r["metrics"]["hedge_verified"]
            and r["metrics"]["actual_inventory"]["X"] == 100
            and r["metrics"]["reconciliation_required"],
            "lost failed-hedge risk",
        )
        record(
            "paper.failed_hedge_retains_risk",
            [r],
            {"actual_exposure": 100, "hedge_verified": False},
        )

        r = shadow_readout(_receipt(mark=None))
        require(
            not r["metrics"]["valuation_complete"]
            and r["metrics"]["sharpe"] is None
            and r["metrics"]["missing_marks"] == ["X"],
            "unknown mark became zero",
        )
        record(
            "nav.missing_mark_is_unknown",
            [r],
            {"valuation_complete": False, "sharpe": None},
        )

        journal_path = workdir / "intents.sqlite"
        journal = IntentJournal(journal_path)
        first = journal.register("known", _receipt())
        retry = IntentJournal(journal_path).register("known", _receipt())
        unknown = journal.register("unknown", _receipt(fee_usd=None))
        blocked = journal.register("next", _receipt())
        require(
            first["metrics"]["registered"]
            and not retry["metrics"]["registered"]
            and retry["metrics"]["intents_count"] == 1,
            "retry duplicated receipt",
        )
        require(
            not blocked["metrics"]["registered"]
            and "intent.reconciliation_required" in blocked["reasons"],
            "unknown fee allowed next intent",
        )
        record(
            "intent.retry_requires_reconcile",
            [first, retry, unknown, blocked],
            {"retry_registered": False, "unknown_blocks_next": True},
        )

        cash, reference = _fee("cash_bid_ask"), _fee()
        stressed = _fee("cash_bid_ask", "fee_params_x2.json")
        require(
            cash["metrics"]["friction_deducted_bps"] == 0
            and reference["metrics"]["friction_deducted_bps"] == 4
            and stressed["metrics"]["friction_deducted_bps"] == 4,
            "friction double counted",
        )
        record(
            "cost.cash_vs_reference_no_double",
            [cash, reference, stressed],
            {"cash_x1_friction_deducted_bps": 0, "cash_x2_increment_bps": 4},
        )

        scan_raw = (FIXTURES / "calendar_gap_scan.json").read_bytes()
        scan = json.loads(scan_raw)
        spy = scan["files"]["SPY"]
        start, end, length = spy["longest_runs"][0]
        require(
            (start, end, length) == ("2011-07-18", "2011-07-27", 8),
            "wrong real SPY gap",
        )
        calendar = [
            "2011-07-15",
            "2011-07-18",
            "2011-07-19",
            "2011-07-20",
            "2011-07-21",
            "2011-07-22",
            "2011-07-25",
            "2011-07-26",
            "2011-07-27",
            "2011-07-28",
        ]
        manifest = _wf()
        manifest.update(
            calendar=calendar,
            label_horizon=0,
            embargo=0,
            folds=[
                dict(
                    fold_id="gap",
                    train_start=calendar[0],
                    train_end=calendar[0],
                    test_start=calendar[-1],
                    test_end=calendar[-1],
                )
            ],
            source={
                "scan_sha256": sha256(scan_raw),
                "spy_sha256": spy["sha256"],
                "prices": "synthetic constants; only missing dates taken from real evidence",
            },
            series={
                "portfolio": [dict(date=d, close=100) for d in calendar],
                "SPY": [dict(date=d, close=100) for d in (calendar[0], calendar[-1])],
            },
        )
        r = wf_manifest_check(manifest)
        require(
            "data.benchmark_calendar_gap" in r["reasons"]
            and r["metrics"]["beta"] is None
            and r["metrics"]["information_ratio"] is None,
            "benchmark gap computed beta/IR",
        )
        require(
            len(r["metrics"]["series_checks"]["SPY"]["missing_dates"]) == 8,
            "gap not preserved",
        )
        record(
            "data.benchmark_calendar_gap",
            [r],
            {
                "real_gap": [start, end, length],
                "beta": None,
                "information_ratio": None,
                "scan_sha256": sha256(scan_raw),
            },
        )

    specified = json.loads((FIXTURES / "harness_cases.json").read_bytes())
    require(
        [c["case_id"] for c in cases]
        == [c["case_id"] for c in specified["cases"]] + ["data.benchmark_calendar_gap"],
        "fixed case ID set drifted",
    )
    return {
        "schema": "dynamic_factor.harness/v1",
        "status": "PASS",
        "cases_passed": len(cases),
        "network_attempts": len(network),
        "dependencies": {"python": sys.version.split()[0], "external": []},
        "source_sha256": digest(source_manifest()),
        "source_files": source_manifest(),
        "fixture_sha256": {
            p.name: sha256(p.read_bytes()) for p in sorted(FIXTURES.glob("*.json"))
        },
        "cases": cases,
        "strategy_backtests": 0,
        "certification": False,
    }


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

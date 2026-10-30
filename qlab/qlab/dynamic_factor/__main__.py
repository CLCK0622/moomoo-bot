"""JSON CLI for deterministic validation/arithmetic (no plugin import from JSON)."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .contract import canonical, result, sha256
from .conventions import ConventionConflict, load_conventions
from .fees import fee_frontier
from .ledger import AttemptLedger
from .pending import (
    pool_admission_check,
    initial_build_turnover_check,
    voluntary_trade_gate,
)
from .receipts import decay_check, shadow_readout
from .statistics import dsr_eval, prereg_check
from .validation import wf_manifest_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tool",
        choices=[
            "prereg_check",
            "wf_manifest_check",
            "dsr_eval",
            "fee_frontier",
            "shadow_readout",
            "decay_check",
            "pool_admission_check",
            "initial_build_turnover_check",
            "voluntary_trade_gate",
            "startup_intent",
            "benchmark_valuation",
            "integer_cash_valuation",
            "reference_manifest_check",
            "reference_runtime_check",
            "authority_ledger_check",
            "panel_input_check",
            "input_migration_check",
            "continuous_path_check",
        ],
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--params", type=Path, help="EVO-882 fee_params_x1/x2.json")
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--genesis", type=Path)
    parser.add_argument("--ledger-anchor", type=Path)
    parser.add_argument("--ledger-bootstrap", type=Path)
    parser.add_argument(
        "--conventions",
        type=Path,
        help="EVO-883 raw JSON, with pinned companion artifacts",
    )
    parser.add_argument("--conventions-sha256")
    parser.add_argument(
        "--out-dir", type=Path, help="write an immutable content-addressed report"
    )
    args = parser.parse_args()
    raw = None
    policy = None
    try:
        raw = args.input.read_bytes()
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("input must be a JSON object")
        policy = (
            load_conventions(args.conventions, expected_sha256=args.conventions_sha256)
            if args.conventions
            else None
        )
        if args.tool in ("dsr_eval", "wf_manifest_check") and policy is None:
            raise ConventionConflict("wf.conventions_required")
        if args.genesis is not None and policy is not None:
            raise ConventionConflict("ledger.custom_genesis_forbidden")
        if args.tool in ("authority_ledger_check", "input_migration_check"):
            from .authority_ledger import AuthorityLedger

            if args.ledger is None or args.ledger_anchor is None:
                raise ValueError("ledger.file_and_witness_required")
            ledger = AuthorityLedger(args.ledger, args.ledger_anchor)
            if args.tool == "input_migration_check":
                from .input_disposition import input_migration_check

                report = input_migration_check(request, ledger, conventions=policy)
            else:
                report = ledger.readout()
        elif args.tool == "continuous_path_check":
            from .continuity import continuous_path_check

            report = continuous_path_check(request, conventions=policy)
        elif args.tool == "panel_input_check":
            from .input_disposition import panel_input_check

            report = panel_input_check(request, conventions=policy)
        elif args.tool == "fee_frontier":
            if args.params is None:
                raise ValueError("--params required")
            kwargs = {"schedule_path": args.schedule} if args.schedule else {}
            report = fee_frontier(request, args.params, conventions=policy, **kwargs)
        elif args.tool == "dsr_eval":
            if args.ledger is None:
                raise ValueError("--ledger required")
            genesis = json.loads(args.genesis.read_bytes()) if args.genesis else None
            ledger = (
                AttemptLedger(args.ledger, genesis)
                if genesis is not None or policy is None
                else AttemptLedger.from_conventions(
                    args.ledger,
                    policy,
                    anchor_path=args.ledger_anchor,
                    bootstrap_receipt=json.loads(args.ledger_bootstrap.read_bytes())
                    if args.ledger_bootstrap
                    else None,
                )
            )
            report = dsr_eval(
                request.get("metrics", {}),
                ledger,
                prereg=request.get("prereg"),
                prereg_sha256=request.get("prereg_sha256"),
                conventions=policy,
            )
        elif args.tool in (
            "benchmark_valuation",
            "integer_cash_valuation",
            "reference_manifest_check",
            "reference_runtime_check",
        ):
            from .valuation import benchmark_valuation, integer_cash_valuation
            from .reference_check import reference_manifest_check
            from .reference_evidence import reference_runtime_check

            report = {
                "benchmark_valuation": benchmark_valuation,
                "integer_cash_valuation": integer_cash_valuation,
                "reference_manifest_check": reference_manifest_check,
                "reference_runtime_check": reference_runtime_check,
            }[args.tool](request, conventions=policy)
        elif args.tool == "startup_intent":
            from .execution import lock_startup_intent

            if policy is None or args.ledger is None:
                raise ValueError("--conventions and --ledger required")
            ledger = AttemptLedger.from_conventions(
                args.ledger,
                policy,
                anchor_path=args.ledger_anchor,
                bootstrap_receipt=json.loads(args.ledger_bootstrap.read_bytes())
                if args.ledger_bootstrap
                else None,
            )
            intent = lock_startup_intent(
                request["position"],
                request["previous_nav"],
                request["inventory"],
                request["previous_close"],
                policy=policy,
                ledger=ledger,
                start_id=request["start_id"],
                scope_id=request["scope_id"],
            )
            report = policy.bind(
                result(
                    "startup_intent",
                    {"request": request, **policy.binding},
                    metrics={
                        "intent": intent,
                        "n_ledger_hash": ledger.snapshot()["n_ledger_hash"],
                    },
                    assumptions=[
                        "Prior-close intent only; next-open prices cannot change the locked budget."
                    ],
                )
            )
        elif args.tool in (
            "pool_admission_check",
            "initial_build_turnover_check",
            "voluntary_trade_gate",
        ):
            if policy is None:
                raise ValueError("--conventions required")
            if args.tool == "voluntary_trade_gate":
                if args.ledger is None:
                    raise ValueError("--ledger required")
                ledger = AttemptLedger.from_conventions(
                    args.ledger,
                    policy,
                    anchor_path=args.ledger_anchor,
                    bootstrap_receipt=json.loads(args.ledger_bootstrap.read_bytes())
                    if args.ledger_bootstrap
                    else None,
                )
                report = voluntary_trade_gate(
                    request, conventions=policy, ledger=ledger
                )
            else:
                if args.ledger is None:
                    raise ValueError("--ledger required")
                ledger = AttemptLedger.from_conventions(
                    args.ledger,
                    policy,
                    anchor_path=args.ledger_anchor,
                    bootstrap_receipt=json.loads(args.ledger_bootstrap.read_bytes())
                    if args.ledger_bootstrap
                    else None,
                )
                report = {
                    "pool_admission_check": pool_admission_check,
                    "initial_build_turnover_check": initial_build_turnover_check,
                }[args.tool](request, conventions=policy, ledger=ledger)
        elif args.tool == "prereg_check":
            report = prereg_check(
                request.get("prereg"), request.get("prereg_sha256"), conventions=policy
            )
        elif args.tool == "wf_manifest_check":
            report = wf_manifest_check(request, conventions=policy)
        else:
            report = {
                "wf_manifest_check": wf_manifest_check,
                "shadow_readout": shadow_readout,
                "decay_check": decay_check,
            }[args.tool](request)
        if policy is not None and "conventions_sha256" not in report:
            report = policy.bind(report)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        report = result(
            args.tool,
            {"raw_input_sha256": sha256(raw) if raw is not None else None},
            reasons=[
                str(exc)
                if isinstance(exc, ConventionConflict)
                or (isinstance(exc, ValueError) and str(exc).startswith("ledger."))
                else f"input_invalid_or_missing:{type(exc).__name__}"
            ],
            missing=["valid tool inputs"],
            metrics={"sharpe": None},
        )
    if policy is not None and "conventions_sha256" not in report:
        report = policy.bind(report)
    report["input_file_sha256"] = sha256(raw) if raw is not None else None
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        encoded = canonical(report) + b"\n"
        target = args.out_dir / f"{args.tool}-{sha256(encoded)}.json"
        try:
            with target.open("xb") as fh:
                fh.write(encoded)
        except FileExistsError:
            if target.read_bytes() != encoded:
                raise ValueError("artifact_identity_conflict")
    print(
        json.dumps(
            report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

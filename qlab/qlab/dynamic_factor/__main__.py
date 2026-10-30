"""JSON CLI for deterministic validation/arithmetic (no plugin import from JSON)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contract import canonical, result, sha256
from .fees import fee_frontier
from .ledger import AttemptLedger
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
        ],
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--params", type=Path, help="EVO-882 fee_params_x1/x2.json")
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--genesis", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, help="write an immutable content-addressed report"
    )
    args = parser.parse_args()
    raw = None
    try:
        raw = args.input.read_bytes()
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("input must be a JSON object")
        if args.tool == "fee_frontier":
            if args.params is None:
                raise ValueError("--params required")
            kwargs = {"schedule_path": args.schedule} if args.schedule else {}
            report = fee_frontier(request, args.params, **kwargs)
        elif args.tool == "dsr_eval":
            if args.ledger is None:
                raise ValueError("--ledger required")
            genesis = json.loads(args.genesis.read_bytes()) if args.genesis else None
            report = dsr_eval(
                request.get("metrics", {}),
                AttemptLedger(args.ledger, genesis),
                prereg=request.get("prereg"),
                prereg_sha256=request.get("prereg_sha256"),
            )
        elif args.tool == "prereg_check":
            report = prereg_check(request.get("prereg"), request.get("prereg_sha256"))
        else:
            report = {
                "wf_manifest_check": wf_manifest_check,
                "shadow_readout": shadow_readout,
                "decay_check": decay_check,
            }[args.tool](request)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        report = result(
            args.tool,
            {"raw_input_sha256": sha256(raw) if raw is not None else None},
            reasons=[f"input_invalid_or_missing:{type(exc).__name__}"],
            missing=["valid tool inputs"],
            metrics={"sharpe": None},
        )
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

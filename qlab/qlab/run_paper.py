"""CLI: run the strategy through the execution engine.

Default is offline PAPER trading over a deterministic synthetic fixture, so it
runs anywhere with no OpenD gateway and no account. Real-money trading is
hard-gated.

Examples
--------
# Paper trade a synthetic fixture (default; fully reproducible, no broker):
python -m qlab.run_paper --mode paper --out qlab/reports/paper_run

# See signals + intended orders only, no fills:
python -m qlab.run_paper --mode dry_run --out qlab/reports/dryrun

# Against a real OpenD SIMULATE account (needs OpenD + SDK; see README):
python -m qlab.run_paper --mode opend_paper --out qlab/reports/opend_paper
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ExecConfig
from .engine import ExecutionEngine
from .params import default_params


def _synthetic_fixture(symbols, start, end, seed):
    from .synthetic import generate_symbol
    return {s: generate_symbol(s, start, end, seed=seed) for s in symbols}


def main(argv=None):
    ap = argparse.ArgumentParser(description="qlab execution engine (paper-first)")
    ap.add_argument("--mode", choices=["dry_run", "paper", "opend_paper", "live"], default="paper")
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--start", default="2025-01-02")
    ap.add_argument("--end", default="2025-02-28")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="qlab/reports/paper_run")
    ap.add_argument("--stdout", action="store_true", help="echo events to stdout")
    ap.add_argument("--i-understand-live", action="store_true",
                    help="extra confirmation required for --mode live")
    args = ap.parse_args(argv)

    cfg = ExecConfig.from_env(mode=args.mode)
    if args.symbols:
        cfg.symbols = [s.upper() for s in args.symbols]
    if args.mode == "live" and not (args.i_understand_live and cfg.allow_live):
        raise SystemExit("Refusing LIVE: pass --i-understand-live AND set QLAB_ALLOW_LIVE=1.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps(cfg.to_dict(), indent=2, default=str))
    (out_dir / "params.json").write_text(json.dumps(default_params(), indent=2))

    engine = ExecutionEngine(cfg, out_dir, also_stdout=args.stdout)
    try:
        if args.mode in ("dry_run", "paper"):
            data = _synthetic_fixture(cfg.symbols, args.start, args.end, args.seed)
            summary = engine.run_replay(data)
        else:
            # Live/opend paths: connect, then a real loop would call engine.on_bar
            # per realtime bar. Connection itself is the precondition that fails
            # without an OpenD gateway — surfaced as a precise blocker (not a crash).
            from .brokers.base import BrokerError
            try:
                engine.connect()  # gateway failure trips the kill switch
                summary = {"mode": args.mode, "status": "connected",
                           "note": "attach a realtime bar loop calling engine.on_bar(rows)"}
            except BrokerError as e:
                summary = {"mode": args.mode, "status": "BLOCKED", "blocker": str(e),
                           "kill_switch": engine.risk.kill_switch}
    finally:
        if args.mode in ("dry_run", "paper"):
            (Path(args.out) / "summary.json").write_text(json.dumps(engine.summary(), indent=2, default=str))
        engine.close()

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI: run the EVO-23 candidate-1+2 ETF right-side momentum evaluation.

    python -m qlab.swing.run_momentum --sleeve tsmom     --prereg-commit <HASH>
    python -m qlab.swing.run_momentum --sleeve sector_rs --prereg-commit <HASH>

Verdict follows the frozen MOMENTUM_EVAL_PREREGISTRATION.md. Data = OpenD qfq daily
ETF bars only (quote-only, TrdEnv.SIMULATE). Symbols with no real bar are reported
as a data gap, never silently re-sized away, and a reduced universe is NEVER达标.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .momentum_evaluate import (SECTOR_UNIVERSE, TSMOM_UNIVERSE, build_momentum_report)
from .momentum_signals import load_daily


def _load_universe(universe, data_dirs):
    frames = {}
    for sym in universe:
        for d in data_dirs:
            p = Path(d) / f"{sym}_1d.parquet"
            if p.exists():
                frames[sym] = load_daily(p)
                break
    return frames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-23 candidate-1+2 ETF momentum evaluation")
    ap.add_argument("--sleeve", choices=["tsmom", "sector_rs"], default="tsmom")
    ap.add_argument("--data-dir", action="append", default=None,
                    help="parquet dir(s) to search, in order (default: data/daily_full then data/daily)")
    ap.add_argument("--nboot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    data_dirs = args.data_dir or ["data/daily_full", "data/daily"]
    universe = TSMOM_UNIVERSE if args.sleeve == "tsmom" else SECTOR_UNIVERSE
    frames = _load_universe(universe, data_dirs)

    rep = build_momentum_report(frames, sleeve=args.sleeve, n_boot=args.nboot,
                                seed=args.seed, prereg_commit=args.prereg_commit)

    out = Path(args.out or f"qlab/reports/momentum_{args.sleeve}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))

    print(f"[EVO-23 momentum/{args.sleeve}] verdict={rep['overall_verdict']}")
    print(f"  {rep['verdict_reason']}")
    print(f"  data_complete={rep['data_complete']}  present={rep['universe_present']}")
    if rep.get("universe_missing"):
        print(f"  MISSING (data gap): {rep['universe_missing']}")
    g1 = rep.get("primary_gate1") or {}
    if g1:
        print(f"  primary ×2: CAGR={g1.get('cagr', 0):.2%}  MDD={g1.get('mdd', 0):.2%}")
    if "risk_frontier_reference" in rep and "cagr" in rep["risk_frontier_reference"]:
        r = rep["risk_frontier_reference"]
        print(f"  ref (equal-weight buy&hold, no filter): CAGR={r['cagr']:.2%}  MDD={r['mdd']:.2%}")
    print(f"  report -> {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

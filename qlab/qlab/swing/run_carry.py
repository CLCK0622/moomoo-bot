"""CLI: run the EVO-25 candidate-8 VIX term-structure carry evaluation.

    python -m qlab.swing.run_carry \
        --vix data/vix_raw/VIX_History.csv --vix3m data/vix_raw/VIX3M_History.csv \
        --etp data/vix_etp/SVXY_1d.parquet --instrument SVXY

Verdict follows the frozen CARRY_EVAL_PREREGISTRATION.md. Signal = CBOE cash
indices; execution = OpenD qfq daily bars (quote-only, SIMULATE); T-close→T+1-open.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .carry_evaluate import build_carry_report
from .carry_signals import CarryParams, build_term_signal


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-25 candidate-8 VIX carry evaluation")
    ap.add_argument("--vix", default="data/vix_raw/VIX_History.csv")
    ap.add_argument("--vix3m", default="data/vix_raw/VIX3M_History.csv")
    ap.add_argument("--etp", default="data/vix_etp/SVXY_1d.parquet")
    ap.add_argument("--instrument", default="SVXY")
    ap.add_argument("--nboot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    sig = build_term_signal(args.vix, args.vix3m)
    etp = pd.read_parquet(args.etp)
    rep = build_carry_report(etp, sig, params=CarryParams(), instrument=args.instrument,
                             n_boot=args.nboot, seed=args.seed, prereg_commit=args.prereg_commit)

    out = Path(args.out or f"qlab/reports/carry_vixts_{args.instrument.lower()}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))
    print(f"[EVO-25 carry/{args.instrument}] verdict={rep['overall_verdict']}")
    print(f"  {rep['verdict_reason']}")
    g1 = rep["primary_gate1"]
    print(f"  primary ×2: CAGR={g1.get('cagr', 0):.2%}  MDD={g1.get('mdd', 0):.2%}")
    if "risk_frontier_reference" in rep:
        r = rep["risk_frontier_reference"]
        print(f"  ref (full-exposure, no overlay): CAGR={r['cagr']:.2%}  MDD={r['mdd']:.2%}")
    print(f"  report -> {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

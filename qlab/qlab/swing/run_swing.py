"""CLI: run the S1 / S5 swing evaluation and emit a report.json.

    python -m qlab.swing.run_swing --candidate s5 --data-dir data/daily_full
    python -m qlab.swing.run_swing --candidate s1 --data-dir data/daily_full

Both consume real full-depth (2006→) daily bars persisted under ``data/daily_full``
and the committed source-cited FOMC calendar. Verdicts follow the frozen
pre-registration (SWING_EVAL_PREREGISTRATION.md @ c025d56).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..events.bars import ParquetDailyBarSource
from .evaluate import build_s1_report, build_s5_report
from .strategies import load_fomc_calendar

# S1 universe: liquid ETFs + the EVO-24 large-caps (all full-depth in data/daily_full).
DEFAULT_S1_UNIVERSE = [
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "CSCO", "INTC", "ORCL",
    "JPM", "BAC", "GS", "WMT", "HD", "KO", "PG", "JNJ", "PFE", "CVX",
]


def _load_frames(data_dir, symbols):
    src = ParquetDailyBarSource(data_dir, symbols)
    frames = {}
    for s in symbols:
        df = src.load(s)
        if df is not None and len(df):
            frames[s] = df
    return frames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Swing S1/S5 evaluation (EVO-130 Phase 2)")
    ap.add_argument("--candidate", choices=["s1", "s5"], required=True)
    ap.add_argument("--data-dir", default="data/daily_full")
    ap.add_argument("--symbols", nargs="+", default=None, help="S1 universe override")
    ap.add_argument("--fomc-csv", default="data/fomc_meetings.csv")
    ap.add_argument("--nboot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.candidate == "s5":
        spy = ParquetDailyBarSource(args.data_dir, ["SPY"]).load("SPY")
        if spy is None or spy.empty:
            raise SystemExit(f"no SPY bars in {args.data_dir}")
        fomc = load_fomc_calendar(args.fomc_csv)
        rep = build_s5_report(spy, fomc, n_boot=args.nboot, seed=args.seed)
        out = Path(args.out or "qlab/reports/swing_s5_fomc")
    else:
        syms = args.symbols or DEFAULT_S1_UNIVERSE
        frames = _load_frames(args.data_dir, syms)
        if not frames:
            raise SystemExit(f"no bars found in {args.data_dir} for {syms}")
        rep = build_s1_report(frames, n_boot=args.nboot, seed=args.seed)
        out = Path(args.out or "qlab/reports/swing_s1_meanrev")

    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))
    print(f"[EVO-130 swing/{args.candidate}] verdict={rep['overall_verdict']}")
    print(f"  {rep['verdict_reason']}")
    print(f"  report -> {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

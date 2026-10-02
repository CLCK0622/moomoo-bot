"""CLI: run the EVO-162 C1 cross-sectional residual-reversal evaluation.

    python -m qlab.swing.run_residual --prereg-commit <HASH>

Verdict follows the frozen ``RESIDUAL_REVERSAL_EVAL_PREREGISTRATION.md`` (primary cell
F=1wk / E=156wk / decile / 3-factor). Data = moomoo OpenD qfq daily bars only (quote-only,
``TrdEnv.SIMULATE``). The frozen universe is the resolved 250-name list in
``RESIDUAL_UNIVERSE_RESOLVED.txt`` (committed BEFORE any results commit); if that file is
absent the run falls back to whatever real stock bars are present, marks
``universe_resolved=False``, and the verdict is labelled ``数据不足-仅工程可复跑`` — a
reduced / unresolved universe is NEVER达标.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .momentum_signals import load_daily
from .residual_evaluate import build_residual_report
from .residual_signals import FACTOR_ETFS


def _load_symbol(sym, data_dirs):
    for d in data_dirs:
        p = Path(d) / f"{sym}_1d.parquet"
        if p.exists():
            return load_daily(p)
    return None


def _resolved_universe(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    syms = [ln.strip().upper() for ln in path.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    return syms or None


def _present_stock_symbols(data_dirs) -> list[str]:
    """Every ``*_1d.parquet`` present, minus the four factor-regressor ETFs (never traded)."""
    seen: dict[str, None] = {}
    for d in data_dirs:
        dd = Path(d)
        if not dd.exists():
            continue
        for p in sorted(dd.glob("*_1d.parquet")):
            sym = p.name[:-len("_1d.parquet")].upper()
            if sym not in FACTOR_ETFS:
                seen.setdefault(sym, None)
    return list(seen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-162 C1 residual-reversal evaluation")
    ap.add_argument("--data-dir", action="append", default=None,
                    help="parquet dir(s) to search, in order (default: data/daily_full then data/daily)")
    ap.add_argument("--universe-file", default="RESIDUAL_UNIVERSE_RESOLVED.txt",
                    help="frozen resolved-universe list (committed before results; cwd-relative, "
                         "next to the prereg docs — matches resolve_universe stage1 --out)")
    ap.add_argument("--sectors-file", default=None,
                    help="optional JSON {symbol: sector} for the 4-factor robustness cell")
    ap.add_argument("--short-leg-reviewed", choices=["yes", "no", "pending"], default="pending",
                    help="锦衣卫 EVO-10 short-leg review outcome (PASS clause 5; default pending)")
    ap.add_argument("--nboot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--out", default="qlab/reports/residual")
    args = ap.parse_args(argv)

    data_dirs = args.data_dir or ["data/daily_full", "data/daily"]

    resolved = _resolved_universe(Path(args.universe_file))
    if resolved is not None:
        universe, universe_resolved = resolved, True
    else:
        universe, universe_resolved = _present_stock_symbols(data_dirs), False

    stock_frames = {s: f for s in universe if (f := _load_symbol(s, data_dirs)) is not None}
    stock_frames = {s: stock_frames[s] for s in universe if s in stock_frames}
    factor_frames = {s: f for s in FACTOR_ETFS if (f := _load_symbol(s, data_dirs)) is not None}

    sectors = None
    if args.sectors_file and Path(args.sectors_file).exists():
        sectors = {k.upper(): v for k, v in json.loads(Path(args.sectors_file).read_text()).items()}

    short_leg = {"yes": True, "no": False, "pending": None}[args.short_leg_reviewed]

    rep = build_residual_report(stock_frames, factor_frames, universe,
                                universe_resolved=universe_resolved, sectors=sectors,
                                short_leg_reviewed=short_leg, n_boot=args.nboot, seed=args.seed,
                                prereg_commit=args.prereg_commit)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))

    print(f"[EVO-162 C1 residual-reversal] verdict={rep['overall_verdict']}")
    print(f"  {rep['verdict_reason']}")
    print(f"  universe_resolved={rep['universe_resolved']}  frozen_size={rep['universe_frozen_size']}"
          f"  present={len(rep['universe_present'])}  missing={rep['universe_missing_count']}")
    print(f"  factor ETFs present={rep['factor_etfs_present']}  missing={rep['factor_etfs_missing']}")
    g1 = rep.get("primary_gate1") or {}
    if g1:
        diag = rep.get("primary_diagnostics") or {}
        print(f"  primary ×2: CAGR={g1.get('cagr', 0):.2%}  MDD={g1.get('mdd', 0):.2%}  "
              f"mean {diag.get('mean_names_per_leg', 0):.1f} names/leg  "
              f"max_gross={diag.get('max_gross', 0):.2f}")
    if "risk_frontier_reference" in rep and "cagr" in rep["risk_frontier_reference"]:
        r = rep["risk_frontier_reference"]
        print(f"  ref (1.0× gross, no overlay): CAGR={r['cagr']:.2%}  MDD={r['mdd']:.2%}")
    print(f"  report -> {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

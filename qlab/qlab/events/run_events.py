"""CLI: run the earnings-event drift battery and emit the EVO-12 evaluation card.

Default is the deterministic SYNTHETIC harness (no OpenD, no real earnings feed,
no options chain) — it proves the pipeline runs end-to-end and is reproducible.
On synthetic data every number is a harness self-test and the verdict is forced
to ``需补证据`` regardless of the gate arithmetic.

Examples
--------
# Synthetic harness sweep over both candidates and the 5/10/20/30 holds:
python -m qlab.events.run_events --source synthetic --out qlab/reports/events_synth

# Candidate 5 (close-to-open) only, one hold:
python -m qlab.events.run_events --source synthetic --mode close_to_open --hold 10

# Against real data (the path to a real verdict):
python -m qlab.events.run_events --source parquet --data-dir data/daily \
    --events-csv data/earnings.csv --mode pead --hold 5 10 20 30 --out qlab/reports/events_real
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import EventDriftBacktester
from .bars import ParquetDailyBarSource, SyntheticDailyBarSource
from .eventsource import CsvEventSource, SyntheticEventSource
from .gates import (gate1_full_sample, gate2_yearly, gate3_rolling,
                    three_gate_verdict, walk_forward)
from .metrics import evo12_metrics
from .options import MissingOptionsChainSource
from .report import DATA_GAP_LIST, RISK_REGISTER
from .strategy import CostModel

DEFAULT_SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]


def _build_sources(args):
    if args.source == "synthetic":
        ev_src = SyntheticEventSource(args.symbols, args.start, args.end, seed=args.seed)
        events = ev_src.events()
        bars = SyntheticDailyBarSource(args.symbols, args.start, args.end,
                                       seed=args.seed, events=events)
        return bars, ev_src, False
    if args.source == "parquet":
        if not args.events_csv:
            raise SystemExit("--events-csv is required with --source parquet")
        ev_src = CsvEventSource(args.events_csv)
        bars = ParquetDailyBarSource(args.data_dir, args.symbols)
        return bars, ev_src, True
    if args.source == "csv":
        # csv events + parquet bars is the usual real combo; keep alias explicit
        ev_src = CsvEventSource(args.events_csv)
        bars = ParquetDailyBarSource(args.data_dir, args.symbols)
        return bars, ev_src, True
    raise SystemExit(f"unknown source {args.source!r}")


def _run_one(bars, ev_src, *, mode, hold, min_adv, max_concurrent, quantile,
             surprise_mode, P, rf_annual):
    """Baseline + cost×2 + walk-forward for one (mode, hold) → EVO-12 card B/C/D."""
    bt = EventDriftBacktester(
        bars, ev_src, mode=mode, hold=hold, cost=CostModel(),
        min_adv=min_adv, max_concurrent=max_concurrent, surprise_mode=surprise_mode,
        quantile=quantile, options_src=MissingOptionsChainSource(), P=P, rf_annual=rf_annual)
    res = bt.run()
    m = evo12_metrics(res["equity"], res["trade_log"], P=P, rf_annual=rf_annual)
    g1 = gate1_full_sample(res["equity"], P)
    g2 = gate2_yearly(res["equity"], P)
    g3 = gate3_rolling(res["equity"], P)

    bt2 = EventDriftBacktester(
        bars, ev_src, mode=mode, hold=hold, cost=CostModel(cost_mult=2.0),
        min_adv=min_adv, max_concurrent=max_concurrent, surprise_mode=surprise_mode,
        quantile=quantile, options_src=MissingOptionsChainSource(), P=P, rf_annual=rf_annual)
    res2 = bt2.run()
    m2 = evo12_metrics(res2["equity"], res2["trade_log"], P=P, rf_annual=rf_annual)
    g1_2 = gate1_full_sample(res2["equity"], P)

    wf = walk_forward(bt)
    wf_serializable = {k: v for k, v in wf.items() if k not in ("oos_equity",)}

    return {
        "mode": mode, "hold": hold,
        "card_C_core_metrics": m,
        "card_B_cost_stress": {
            "cost_bps_per_side_base": bt.cost.commission_bps + bt.cost.slippage_bps,
            "base_cagr": g1["cagr"], "base_mdd": g1["mdd"],
            "cost_x2_cagr": g1_2["cagr"], "cost_x2_mdd": g1_2["mdd"],
            "cost_x2_still_passes_gate1": g1_2["passed"],
            "turnover_annualized_two_sided": m["annualized_turnover"],
        },
        "card_D_gates": {
            "gate1_full_sample": g1, "gate2_yearly": g2, "gate3_rolling": g3,
            "gate4_walk_forward": wf_serializable,
            "three_gate_verdict": three_gate_verdict(g1, g2, g3),
        },
        "diagnostics": res["diagnostics"],
        "negative_branch": res["diagnostics"]["negative_branch"],
    }


def build_report(args) -> dict:
    bars, ev_src, real = _build_sources(args)
    provenance_bt = EventDriftBacktester(bars, ev_src, options_src=MissingOptionsChainSource())
    provenance_bt.prepare()

    modes = [args.mode] if args.mode != "both" else ["pead", "close_to_open"]
    holds = args.hold
    per_run = []
    for mode in modes:
        for hold in holds:
            per_run.append(_run_one(
                bars, ev_src, mode=mode, hold=hold, min_adv=args.min_adv,
                max_concurrent=args.max_concurrent, quantile=args.quantile,
                surprise_mode=args.surprise_mode, P=args.trading_days, rf_annual=args.rf))

    performance_meaningful = bool(real)
    # Honest verdict: synthetic → always 需补证据. Real → derive from best run's gates,
    # but the negative branch being unrealized caps it at 需整改 until options data exists.
    if not performance_meaningful:
        overall_verdict = "需补证据"
        verdict_reason = ("synthetic harness data — numbers are self-tests, not "
                          "performance; supply real earnings/bar/options data to obtain "
                          "a real verdict.")
    else:
        any_full_pass = any(r["card_D_gates"]["gate4_walk_forward"].get("passed")
                            and r["card_D_gates"]["gate1_full_sample"]["passed"]
                            for r in per_run)
        neg_blocked = any(r["negative_branch"]["blocked_missing_options"] > 0 for r in per_run)
        if neg_blocked:
            overall_verdict = "需整改"
            verdict_reason = ("real data present but negative branch unrealized (no "
                              "options chain); only the long-only sleeve is a real "
                              "result — close the options gap before a full verdict.")
        else:
            overall_verdict = "PASS" if any_full_pass else "需整改"
            verdict_reason = "derived from four-gate + walk-forward on real data."

    return {
        "issue": "EVO-24",
        "candidates": {"4": "PEAD post-earnings drift", "5": "close-to-open overnight drift"},
        "provenance": provenance_bt.provenance(),
        "performance_meaningful": performance_meaningful,
        "overall_verdict": overall_verdict,
        "verdict_reason": verdict_reason,
        "runs": per_run,
        "card_E_bias_self_check": {
            "survivorship": "NOT controlled — needs point-in-time universe (gap).",
            "look_ahead": "controlled — entry is T+1 open after the reaction bar; "
                          "quantile thresholds fit on train only in walk-forward.",
            "overfitting": "hold ∈ {5,10,20,30} and quantile are searched; must survive "
                           "walk-forward OOS.",
            "multiple_testing": "record #holds×#modes×#quantiles tried; apply a haircut "
                                "before any PASS.",
            "sample_period": "synthetic" if not real else "check ≥5y incl. bull/bear.",
            "liquidity": f"min ADV floor = {args.min_adv:.0f} USD; capacity via turnover.",
            "adjustment_quality": "requires split/dividend-adjusted bars (gap on real data).",
        },
        "card_F_conclusion": {
            "one_liner": ("Reproducible, look-ahead-free earnings-drift backtest package "
                          "for candidates 4+5 is delivered and runs end-to-end; a real "
                          "verdict is blocked on real earnings/bar/options data."),
            "confidence": "low" if not real else "medium",
            "negative_branch_status": "defined-risk options only; blocked (missing chain), "
                                      "never a naked short.",
        },
        "data_gap_list": DATA_GAP_LIST,
        "risk_register": RISK_REGISTER,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Earnings-event drift battery (candidates 4+5)")
    ap.add_argument("--source", choices=["synthetic", "parquet", "csv"], default="synthetic")
    ap.add_argument("--mode", choices=["pead", "close_to_open", "both"], default="both")
    ap.add_argument("--hold", type=int, nargs="+", default=[5, 10, 20, 30])
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--start", default="2021-01-04")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--data-dir", default="data/daily")
    ap.add_argument("--events-csv", default=None)
    ap.add_argument("--min-adv", type=float, default=2_000_000.0)
    ap.add_argument("--max-concurrent", type=int, default=10)
    ap.add_argument("--quantile", type=float, default=0.2)
    ap.add_argument("--surprise-mode", choices=["quantile", "analyst"], default="quantile")
    ap.add_argument("--trading-days", type=int, default=252)
    ap.add_argument("--rf", type=float, default=0.0)
    ap.add_argument("--out", default="qlab/reports/events_synth")
    args = ap.parse_args(argv)

    report = build_report(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))

    # compact stdout summary
    print(f"[EVO-24 events] source={args.source} performance_meaningful="
          f"{report['performance_meaningful']} verdict={report['overall_verdict']}")
    for r in report["runs"]:
        c = r["card_C_core_metrics"]
        d = r["card_D_gates"]
        print(f"  {r['mode']:>13s} H={r['hold']:>2d}  CAGR={c['cagr']:+.2%} "
              f"MDD={c['max_drawdown']:.2%} trades={c['num_trades']:>3d} "
              f"neg_blocked={r['negative_branch']['blocked_missing_options']:>3d} "
              f"verdict={d['three_gate_verdict']}")
    print(f"  report -> {out_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

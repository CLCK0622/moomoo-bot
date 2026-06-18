"""Command-line entrypoint: ``python -m qlab.cli <command>``.

Commands:
  backtest   Run a fixture-backed backtest and print metrics.
  train      Train + persist the fixture model, then backtest it.
  report     Run a backtest and write markdown + JSON reports to the artifacts dir.

All commands work offline on fixture data. Real data / moomoo OpenD require the
MOOMOO_* env vars and MOOMOO_ENABLED=true (see README).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .config import load_config
from .execution.session import run_execution
from .execution.signals import load_signals, sanity_check
from .model.momentum import MomentumModel
from .pipeline import evaluate_candidate, run_backtest, train_and_backtest
from .report.evaluation_card import to_markdown, write_card
from .report.report import ReportGenerator
from .strategy.sma_cross import SmaCrossStrategy


def _print_metrics(output) -> None:
    m = output.metrics
    summary = {
        "symbol": output.result.symbol,
        "strategy": output.result.strategy,
        "period": [m.period_start, m.period_end],
        "total_return": round(m.total_return, 4),
        "annualized_return": round(m.annualized_return, 4),
        "max_drawdown": round(m.max_drawdown, 4),
        "yearly_returns": {k: round(v, 4) for k, v in m.yearly_returns.items()},
        "total_commission": round(m.total_commission, 2),
        "total_slippage": round(m.total_slippage, 2),
        "n_trades": m.n_trades,
        "oos_period": m.oos_period,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qlab", description="理财方向探索 量化工程骨架 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="run a fixture-backed SMA-cross backtest")
    bt.add_argument("--symbol", default="DEMO")
    bt.add_argument("--fast", type=int, default=10)
    bt.add_argument("--slow", type=int, default=30)

    tr = sub.add_parser("train", help="train + persist the fixture model, then backtest")
    tr.add_argument("--symbol", default="DEMO")
    tr.add_argument("--model-out", default=None, help="path to save the trained model JSON")

    rp = sub.add_parser("report", help="backtest then write markdown + json reports")
    rp.add_argument("--symbol", default="DEMO")
    rp.add_argument("--fast", type=int, default=10)
    rp.add_argument("--slow", type=int, default=30)
    rp.add_argument("--out-dir", default=None, help="artifacts dir (defaults to config)")

    cd = sub.add_parser("card", help="run the v1.0 评估卡 (B/C/D/E + 四关门禁 + 成本×2)")
    cd.add_argument("--symbol", default="DEMO")
    cd.add_argument("--fast", type=int, default=10)
    cd.add_argument("--slow", type=int, default=30)
    cd.add_argument(
        "--model", action="store_true", help="use the momentum model (enables Walk-Forward)"
    )
    cd.add_argument("--walk-forward", action="store_true", help="run the WF 主口径 (needs --model)")
    cd.add_argument("--out-dir", default=None, help="write card files here (else print markdown)")

    ex = sub.add_parser("execute", help="run a default-safe execution cycle from a signals file")
    ex.add_argument("--signals", default="fixtures/signals.json", help="signal handoff JSON")
    ex.add_argument(
        "--mode", default=None, choices=["dry_run", "paper", "live"],
        help="execution mode (default from config; live needs explicit gateway enable)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()

    if args.command == "backtest":
        strategy = SmaCrossStrategy(args.fast, args.slow)
        out = run_backtest(args.symbol, strategy=strategy, config=config)
        _print_metrics(out)
        return 0

    if args.command == "train":
        default_path = os.path.join(config.artifacts_dir, f"{args.symbol}_momentum.json")
        model_path = args.model_out or default_path
        out = train_and_backtest(args.symbol, config=config, model_path=model_path)
        _print_metrics(out)
        print(f"\nmodel saved -> {model_path}", file=sys.stderr)
        return 0

    if args.command == "report":
        out_dir = args.out_dir or config.artifacts_dir
        strategy = SmaCrossStrategy(args.fast, args.slow)
        out = run_backtest(args.symbol, strategy=strategy, config=config)
        paths = ReportGenerator(config.backtest.trading_days_per_year).write(out.result, out_dir)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0

    if args.command == "card":
        if args.model:
            ev = evaluate_candidate(
                args.symbol,
                model_factory=MomentumModel,
                config=config,
                walk_forward=args.walk_forward,
            )
        else:
            ev = evaluate_candidate(
                args.symbol,
                strategy=SmaCrossStrategy(args.fast, args.slow),
                config=config,
            )
        if args.out_dir:
            paths = write_card(ev, args.out_dir)
            print(json.dumps(paths, ensure_ascii=False, indent=2))
        else:
            print(to_markdown(ev))
        return 0

    if args.command == "execute":
        sigset = load_signals(args.signals)
        universe = [s.symbol for s in sigset.signals]
        issues = sanity_check(
            sigset, universe=universe, max_positions=config.risk.max_positions,
            max_gross=config.risk.max_gross_exposure,
        )
        mode = args.mode or config.execution.mode
        record = run_execution(sigset, config, mode=mode)
        out = {
            "mode": record.mode,
            "signal_source": sigset.source,
            "sanity_issues": issues,
            "equity_before": round(record.equity_before, 2),
            "equity_after": round(record.equity_after, 2),
            "halted": record.halted,
            "halt_reason": record.halt_reason,
            "filled": record.filled,
            "rejected": record.rejected,
            "skipped": record.skipped,
            "positions_after": record.positions_after,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

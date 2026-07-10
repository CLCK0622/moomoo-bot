"""EVO-162 C1 universe resolver (首辅 hard constraint #1: ≤300, 看结果前冻结, 不中途换票).

Deterministic, OpenD-only, reproducible selection of the frozen tradable universe per
``RESIDUAL_REVERSAL_EVAL_PREREGISTRATION.md`` §2:

  1. candidate pool = every ``<SYM>_1d.parquet`` in the data dir(s) that is NOT a factor
     ETF (SPY/IWM/IVE/IVW) and (host-side) is a US common stock with a moomoo US quote;
  2. keep names with **≥ 156 weeks (≥ 780 trading days)** of OpenD daily history;
  3. rank by **60-trading-day average dollar volume** (``close × volume``); take the top N;
  4. exclude names with no moomoo share-borrow availability (short leg must be borrowable);
     a dropped name is replaced by the next-ranked, and the substitution is LOGGED — this is
     the only admissible substitution and it happens BEFORE results, never mid-backtest.

The resolved list is written to ``--out`` (default ``qlab/RESIDUAL_UNIVERSE_RESOLVED.txt``)
and MUST be committed to the branch BEFORE any results commit. A JSON audit log
(``<out>.json``) records the full ranking, filters, and substitutions.

**Pool completeness is checked, never faked.** The candidate pool is only the parquets that
exist locally. On this workspace that is the 22-symbol subset (19 stocks), far short of the
250-name target — so the tool refuses to emit a canonical frozen list unless the pool can
actually fill the target, and instead writes a clearly-labelled *preview* (``--allow-partial``
/ default when the pool is short). Producing the real 250-name frozen list requires the full
OpenD cold-fetch on a host with a reachable gateway (see ``fetch_residual_data.py``).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .residual_signals import FACTOR_ETFS

MIN_HISTORY_WEEKS = 156
TRADING_DAYS_PER_WEEK = 5
ADVOL_DAYS = 60


def _dollar_volume_and_history(path: Path, advol_days: int) -> tuple[float, int] | None:
    """Return ``(avg_dollar_volume_last_advol_days, n_bars)`` or ``None`` if unreadable."""
    try:
        df = pd.read_parquet(path)
    except Exception:  # noqa: BLE001
        return None
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "close" not in df.columns or "volume" not in df.columns or "date" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[(df["close"] > 0) & (df["volume"] >= 0)].sort_values("date")
    n = int(len(df))
    if n == 0:
        return None
    tail = df.tail(advol_days)
    advol = float((tail["close"] * tail["volume"]).mean())
    return advol, n


def resolve(data_dirs, *, top_n: int, advol_days: int = ADVOL_DAYS,
            min_history_weeks: int = MIN_HISTORY_WEEKS, exclude: set[str] | None = None,
            borrowable: set[str] | None = None) -> dict:
    """Rank the local candidate pool and return the resolution record (no I/O)."""
    exclude = {s.upper() for s in (exclude or set())} | set(FACTOR_ETFS)
    min_bars = min_history_weeks * TRADING_DAYS_PER_WEEK

    seen: dict[str, Path] = {}
    for d in data_dirs:
        dd = Path(d)
        if not dd.exists():
            continue
        for p in sorted(dd.glob("*_1d.parquet")):
            sym = p.name[:-len("_1d.parquet")].upper()
            if sym not in exclude:
                seen.setdefault(sym, p)

    ranked, too_short, unreadable = [], [], []
    for sym, p in seen.items():
        res = _dollar_volume_and_history(p, advol_days)
        if res is None:
            unreadable.append(sym)
            continue
        advol, n_bars = res
        if n_bars < min_bars:
            too_short.append({"symbol": sym, "n_bars": n_bars, "weeks": round(n_bars / 5, 1)})
            continue
        ranked.append({"symbol": sym, "avg_dollar_volume": advol, "n_bars": n_bars,
                       "weeks": round(n_bars / 5, 1)})
    ranked.sort(key=lambda r: -r["avg_dollar_volume"])

    # borrowability filter with next-ranked substitution (logged)
    substitutions = []
    if borrowable is not None:
        borrowable = {s.upper() for s in borrowable}
        kept, dropped = [], []
        for r in ranked:
            if r["symbol"] in borrowable:
                kept.append(r)
            else:
                dropped.append(r["symbol"])
        if dropped:
            substitutions.append({"dropped_non_borrowable": dropped,
                                  "note": "excluded pre-results; replaced by next-ranked borrowable"})
        ranked = kept

    selected = [r["symbol"] for r in ranked[:top_n]]
    pool_sufficient = len(ranked) >= top_n
    return {
        "top_n_target": top_n, "advol_days": advol_days,
        "min_history_weeks": min_history_weeks,
        "candidate_pool_size": len(seen),
        "eligible_after_history_filter": len(ranked),
        "pool_sufficient_for_target": pool_sufficient,
        "selected": selected, "selected_count": len(selected),
        "ranking": ranked, "too_short_history": too_short, "unreadable": unreadable,
        "borrow_filter_applied": borrowable is not None,
        "substitutions": substitutions,
        "factor_etfs_excluded": list(FACTOR_ETFS),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-162 C1 frozen-universe resolver (OpenD $-volume rank)")
    ap.add_argument("--data-dir", action="append", default=None,
                    help="parquet dir(s) to scan (default: data/daily_full then data/daily)")
    ap.add_argument("--top", type=int, default=250, help="target universe size (frozen 250)")
    ap.add_argument("--advol-days", type=int, default=ADVOL_DAYS)
    ap.add_argument("--min-weeks", type=int, default=MIN_HISTORY_WEEKS)
    ap.add_argument("--exclude", default=None, help="comma-separated extra symbols to exclude")
    ap.add_argument("--borrowable-file", default=None,
                    help="optional text file of moomoo-borrowable symbols (one per line)")
    ap.add_argument("--out", default="qlab/RESIDUAL_UNIVERSE_RESOLVED.txt")
    ap.add_argument("--allow-partial", action="store_true",
                    help="write the list even if the pool is short of --top (marked PREVIEW)")
    args = ap.parse_args(argv)

    data_dirs = args.data_dir or ["data/daily_full", "data/daily"]
    exclude = set(s.strip().upper() for s in args.exclude.split(",")) if args.exclude else set()
    borrowable = None
    if args.borrowable_file and Path(args.borrowable_file).exists():
        borrowable = {ln.strip().upper() for ln in Path(args.borrowable_file).read_text().splitlines()
                      if ln.strip()}

    rec = resolve(data_dirs, top_n=args.top, advol_days=args.advol_days,
                  min_history_weeks=args.min_weeks, exclude=exclude, borrowable=borrowable)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = not rec["pool_sufficient_for_target"]
    if partial and not args.allow_partial:
        # Refuse to write a canonical frozen list from an insufficient pool — write a preview
        # to reports/ instead, so nobody mistakes it for the frozen 250-name universe.
        preview = Path("qlab/reports/residual") / "universe_preview.txt"
        preview.parent.mkdir(parents=True, exist_ok=True)
        header = ("# EVO-162 C1 universe PREVIEW — NOT the frozen list.\n"
                  f"# Pool has only {rec['eligible_after_history_filter']} eligible names "
                  f"(< target {args.top}); full OpenD cold-fetch required to freeze the real list.\n")
        preview.write_text(header + "\n".join(rec["selected"]) + "\n")
        (preview.with_suffix(".json")).write_text(json.dumps(rec, indent=2, default=str))
        rec["written"] = str(preview)
        rec["canonical_frozen_list_written"] = False
        print(f"[resolve_universe] POOL INSUFFICIENT: {rec['eligible_after_history_filter']} eligible "
              f"< target {args.top}. Wrote PREVIEW → {preview} (NOT the frozen list).")
    else:
        tag = "" if not partial else "# PARTIAL (pool < target) — allow-partial forced\n"
        out.write_text(tag + "\n".join(rec["selected"]) + "\n")
        (out.with_suffix(".json")).write_text(json.dumps(rec, indent=2, default=str))
        rec["written"] = str(out)
        rec["canonical_frozen_list_written"] = not partial
        print(f"[resolve_universe] wrote {rec['selected_count']} symbols → {out}"
              + ("  (PARTIAL)" if partial else ""))
    print(f"  pool={rec['candidate_pool_size']}  eligible(≥{args.min_weeks}wk)="
          f"{rec['eligible_after_history_filter']}  target={args.top}  "
          f"sufficient={rec['pool_sufficient_for_target']}")
    if rec["too_short_history"]:
        print(f"  dropped (short history): {[r['symbol'] for r in rec['too_short_history']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

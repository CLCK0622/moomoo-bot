"""CLI: assemble real event/bar data for the earnings-drift battery.

Produces, from free/out-of-band sources:

* ``<out>/earnings.csv``          — SEC EDGAR 8-K item-2.02 timestamps (gap #1)
* ``<out>/daily/<sym>_1d.parquet`` — adjusted daily bars (gap #2)

and a ``<out>/fetch_manifest.json`` recording, per symbol/source, what was
fetched vs. blocked — so a partial pull is self-documenting rather than silently
faking coverage.

Examples
--------
# Earnings only (works from any host with a descriptive UA):
python -m qlab.events.datafetch.fetch_all --what earnings \
    --start 2019-01-01 --end 2024-12-31 --out data

# Everything, free price source (needs a non-blocked / residential egress IP):
python -m qlab.events.datafetch.fetch_all --what all --price-source stooq \
    --start 2019-01-01 --end 2024-12-31 --out data

# Bars via OpenD (needs a host with a reachable OpenD gateway + moomoo SDK):
python -m qlab.events.datafetch.fetch_all --what prices --price-source opend \
    --start 2019-01-01 --end 2024-12-31 --out data

Then run the real backtest:
python -m qlab.events.run_events --source parquet \
    --data-dir data/daily --events-csv data/earnings.csv \
    --symbols AAPL MSFT ... --mode both --hold 5 10 20 30 --out qlab/reports/events_real
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import prices as price_mod
from .sec_earnings import fetch_earnings, write_earnings_csv
from .universe import DEFAULT_SEC_UA, DEFAULT_UNIVERSE, make_session, resolve_ciks


def _fetch_earnings(args, out_dir, manifest):
    session = make_session(args.sec_ua)
    ciks = resolve_ciks(args.symbols, session)
    missing = [s for s in args.symbols if s.upper() not in ciks]
    if missing:
        print(f"[earnings] SEC did not resolve: {missing}")
    df = fetch_earnings(ciks, args.start, args.end, session=session)
    path = out_dir / "earnings.csv"
    write_earnings_csv(df, path)
    by_symbol = df.groupby("symbol").size().to_dict() if not df.empty else {}
    by_session = df.groupby("session").size().to_dict() if not df.empty else {}
    manifest["earnings"] = {
        "path": str(path), "source": "sec_8k_2.02",
        "n_events": int(len(df)), "symbols_resolved": sorted(ciks),
        "symbols_missing": missing, "events_per_symbol": by_symbol,
        "session_breakdown": by_session,
    }
    print(f"[earnings] {len(df)} events → {path}  session={by_session}")


def _fetch_prices(args, out_dir, manifest):
    daily_dir = out_dir / "daily"
    written, blocked = {}, {}

    if args.price_source == "opend":
        from .opend_daily import OpenDUnavailable, fetch_daily_parquet
        try:
            written = fetch_daily_parquet(args.symbols, args.start, args.end,
                                          data_dir=daily_dir)
        except OpenDUnavailable as exc:
            blocked = {s.upper(): str(exc) for s in args.symbols}
    else:
        backend = price_mod.BACKENDS[args.price_source]
        import requests
        session = requests.Session()
        for sym in args.symbols:
            try:
                df, note = backend(sym, args.start, args.end, session=session)
            except Exception as exc:  # noqa: BLE001
                df, note = None, f"{args.price_source}: {exc}"
            if df is not None and not df.empty:
                p = price_mod.write_parquet(df, daily_dir, sym)
                written[sym.upper()] = {"path": str(p), "rows": int(len(df)), "note": note}
                print(f"[prices] {sym}: {len(df)} bars → {p}")
            else:
                blocked[sym.upper()] = note
                print(f"[prices] {sym}: BLOCKED — {note}")
            time.sleep(args.price_pause)

    manifest["prices"] = {
        "source": args.price_source, "data_dir": str(daily_dir),
        "written": written, "blocked": blocked,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch real earnings/bar data (EVO-24)")
    ap.add_argument("--what", choices=["earnings", "prices", "all"], default="all")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--out", default="data")
    ap.add_argument("--price-source", choices=["stooq", "nasdaq", "yahoo", "opend"],
                    default="stooq")
    ap.add_argument("--price-pause", type=float, default=1.0)
    ap.add_argument("--sec-ua", default=DEFAULT_SEC_UA)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"start": args.start, "end": args.end, "symbols": args.symbols}

    if args.what in ("earnings", "all"):
        _fetch_earnings(args, out_dir, manifest)
    if args.what in ("prices", "all"):
        _fetch_prices(args, out_dir, manifest)

    (out_dir / "fetch_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"[manifest] → {out_dir / 'fetch_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

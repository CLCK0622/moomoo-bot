"""EVO-162 C1 full cold-fetch (host-side, OpenD gateway required, quote-only SIMULATE).

One-shot cold pull of the frozen universe + factor ETFs' full daily history into
``data/daily_full`` (per-symbol parquet), staying inside the OpenD 300-symbol / 30-day
historical-K quota. This is the production step that turns the ``数据不足`` engineering
deliverable into a real evaluation; it **must run on a host with a reachable OpenD gateway**
(the workspace has none — ``fetch_daily_parquet`` raises ``OpenDUnavailable`` here, which we
surface as a clear host-side blocker rather than a silent failure).

    # on the OpenD host (after RESIDUAL_UNIVERSE_RESOLVED.txt is frozen & committed):
    python -m qlab.swing.fetch_residual_data --universe-file qlab/RESIDUAL_UNIVERSE_RESOLVED.txt

Quote-only: opens ONLY ``OpenQuoteContext`` via the vendored fetcher; no trade context, no
unlock, no order. Nothing here touches a live credential or mutates the gateway.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .residual_signals import FACTOR_ETFS

QUOTA_MAX_SYMBOLS = 300     # OpenD historical-K quota (EVO-159): 300 symbols / 30-day window


def _read_universe(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — resolve & freeze the universe first "
            "(python -m qlab.swing.resolve_universe --top 250 --out qlab/RESIDUAL_UNIVERSE_RESOLVED.txt).")
    return [ln.strip().upper() for ln in path.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EVO-162 C1 full OpenD cold-fetch (host-side)")
    ap.add_argument("--universe-file", default="qlab/RESIDUAL_UNIVERSE_RESOLVED.txt")
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default="2026-07-10")
    ap.add_argument("--data-dir", default="data/daily_full")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    ap.add_argument("--pause", type=float, default=1.0)
    args = ap.parse_args(argv)

    stocks = _read_universe(Path(args.universe_file))
    symbols = list(dict.fromkeys(stocks + list(FACTOR_ETFS)))   # de-dup, keep order
    if len(symbols) > QUOTA_MAX_SYMBOLS:
        raise SystemExit(
            f"[fetch_residual_data] {len(symbols)} symbols exceeds the OpenD historical-K quota "
            f"({QUOTA_MAX_SYMBOLS}). The frozen universe (≤250 stocks + {len(FACTOR_ETFS)} factor "
            "ETFs = ≤254) must stay ≤300 — refusing to over-pull (pre-registration hard constraint #1).")

    # imported here so `--help` works without the moomoo SDK present
    from ..events.datafetch.opend_daily import fetch_daily_parquet, OpenDUnavailable

    print(f"[fetch_residual_data] cold-fetching {len(symbols)} symbols "
          f"({len(stocks)} stocks + {len(FACTOR_ETFS)} factor ETFs), {args.start}→{args.end}, "
          f"quote-only SIMULATE → {args.data_dir}")
    try:
        result = fetch_daily_parquet(symbols, start=args.start, end=args.end,
                                     data_dir=args.data_dir, host=args.host, port=args.port,
                                     pause=args.pause)
    except OpenDUnavailable as exc:
        print("[fetch_residual_data] BLOCKER: OpenD gateway / moomoo SDK not available on this host.")
        print(f"  {exc}")
        print("  Run this on a host with a reachable OpenD gateway (paper or live), quote-only.")
        return 2

    manifest = Path(args.data_dir) / "fetch_manifest_residual.json"
    manifest.write_text(json.dumps({
        "issue": "EVO-162", "start": args.start, "end": args.end,
        "n_requested": len(symbols), "n_written": len(result["written"]),
        "n_failed": len(result["failed"]),
        "written": result["written"], "failed": result["failed"],
        "quota_note": f"≤{QUOTA_MAX_SYMBOLS} symbols / 30-day historical-K window",
    }, indent=2))
    print(f"  written={len(result['written'])}  failed={len(result['failed'])}  manifest→{manifest}")
    if result["failed"]:
        print(f"  FAILED: {list(result['failed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

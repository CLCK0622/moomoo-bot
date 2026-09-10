"""build_qlib_data — committed adjusted daily parquet  ->  Qlib ``.bin`` store.

Generator-side plumbing ONLY. This turns the repo's already-qfq-adjusted daily
bars (``data/daily_full/<SYM>_1d.parquet``, columns ``date,open,high,low,close,
volume``) into the binary layout Qlib's expression engine reads, so we can use
Qlib purely as a **factor source** (see ``factor_export.py``).

It never runs a backtest and never produces a verdict. Nothing Qlib emits is an
acceptance signal — the only gate is ``qlab.events`` (EVO-149). See README.md.

Prices are already adjusted, so we write ``factor=1.0``: in the resulting store
``$close`` == adjusted close, and any expression over ``$close`` is on adjusted
prices. Output is a *derived* artifact (gitignored) — rebuild it any time with::

    python -m tools.qlib_gen.build_qlib_data \
        --src data/daily_full --out data/qlib_store

CPU-only, no network. Uses the vendored, pinned ``vendor/dump_bin.py``.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

# Qlib's expected per-instrument CSV columns (symbol + date + OHLCV + adj factor).
_PRICE_COLS = ["open", "high", "low", "close", "volume"]
_DUMP_FIELDS = "open,high,low,close,volume,factor"


def _src_parquets(src: Path) -> list[Path]:
    files = sorted(src.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no *.parquet under {src}")
    return files


def _symbol_of(path: Path) -> str:
    """``AAPL_1d.parquet`` -> ``AAPL``  (also tolerates ``AAPL.parquet``)."""
    stem = path.stem
    return stem[:-3].upper() if stem.lower().endswith("_1d") else stem.upper()


def _to_qlib_csv(parquet: Path, csv_dir: Path) -> str:
    df = pd.read_parquet(parquet)
    missing = {"date", *_PRICE_COLS} - set(df.columns)
    if missing:
        raise ValueError(f"{parquet.name}: missing columns {sorted(missing)}")
    sym = _symbol_of(parquet)
    out = df.loc[:, ["date", *_PRICE_COLS]].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.sort_values("date").drop_duplicates("date")
    out["symbol"] = sym
    out["factor"] = 1.0  # bars are pre-adjusted -> no further adjustment
    out.to_csv(csv_dir / f"{sym}.csv", index=False)
    return sym


def build(src: Path, out: Path, *, limit: int | None = None,
          max_workers: int = 4) -> dict:
    """Convert ``src/*.parquet`` -> Qlib store at ``out``. Returns a manifest."""
    # Import the vendored dumper lazily so `-h` works without qlib installed.
    from .vendor.dump_bin import DumpDataAll

    out = out.expanduser().resolve()
    csv_dir = out / "csv"
    bin_dir = out / "bin"
    if out.exists():
        shutil.rmtree(out)
    csv_dir.mkdir(parents=True)

    files = _src_parquets(src.expanduser().resolve())
    if limit is not None:
        files = files[:limit]
    symbols = [_to_qlib_csv(p, csv_dir) for p in files]

    DumpDataAll(
        data_path=str(csv_dir),
        qlib_dir=str(bin_dir),
        freq="day",
        max_workers=max_workers,
        date_field_name="date",
        symbol_field_name="symbol",
        include_fields=_DUMP_FIELDS,
    ).dump()

    return {
        "store": str(bin_dir),
        "n_instruments": len(symbols),
        "symbols": symbols,
        "src": str(src),
        "fields": _DUMP_FIELDS.split(","),
        "note": "derived/gitignored; Qlib is a factor source only, never a gate",
    }


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="data/daily_full", type=Path)
    ap.add_argument("--out", default="data/qlib_store", type=Path)
    ap.add_argument("--limit", type=int, default=None,
                    help="only first N instruments (smoke tests)")
    ap.add_argument("--max-workers", type=int, default=4)
    args = ap.parse_args()
    man = build(args.src, args.out, limit=args.limit, max_workers=args.max_workers)
    print(f"[build_qlib_data] {man['n_instruments']} instruments -> {man['store']}")


if __name__ == "__main__":
    _cli()

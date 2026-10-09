"""EVO-25 candidate-8 data acquisition + provenance (guardrail #1).

Path C boundary (fixed by 工部尚书):
* signal PRIMARY  = CBOE official public history CSV (VIX / VIX3M);
* signal CROSSCHK = yfinance (^VIX / ^VIX3M) — cross-validation only, never primary;
* execution       = moomoo OpenD qfq daily ETP bars (quote-only, no trade context).

Writes raw snapshots into the repo (committed) and a ``carry_provenance.json``
recording source URLs, download date, coverage, and the two-source disagreement.
Run with a download date passed in (scripts have no wall-clock):

    python -m qlab.swing.fetch_carry_data --download-date 2026-07-10
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

CBOE_VIX = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
CBOE_VIX3M = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv"
ETPS = ["SVXY", "SVIX", "VIXY", "UVXY", "VIXM", "SVOL"]
# yfinance cross-check tolerance: CBOE close vs Yahoo close, in vol points
CROSSCHECK_TOL_POINTS = 0.75


def _download_cboe(url, dest: Path):
    import requests
    r = requests.get(url, timeout=90, headers={"User-Agent": "curl/8"})
    r.raise_for_status()
    dest.write_bytes(r.content)
    return len(r.content)


def _crosscheck_yf(cboe_csv: Path, yf_symbol: str):
    """Return {overlap_days, max_abs_diff_points, corr, within_tol, note}."""
    try:
        import yfinance as yf
        from .carry_signals import load_cboe_index
        cb = load_cboe_index(cboe_csv).rename(columns={"close": "cboe"})
        y = yf.Ticker(yf_symbol).history(period="max", auto_adjust=False)
        if y is None or y.empty:
            return {"available": False, "note": f"yfinance returned no data for {yf_symbol}"}
        yv = y.reset_index()[["Date", "Close"]].rename(columns={"Date": "date", "Close": "yf"})
        yv["date"] = pd.to_datetime(yv["date"]).dt.tz_localize(None).dt.normalize()
        j = pd.merge(cb, yv, on="date", how="inner").dropna()
        if len(j) < 30:
            return {"available": True, "overlap_days": int(len(j)), "note": "insufficient overlap"}
        diff = (j["cboe"] - j["yf"]).abs()
        return {"available": True, "overlap_days": int(len(j)),
                "max_abs_diff_points": float(diff.max()),
                "median_abs_diff_points": float(diff.median()),
                "corr": float(j["cboe"].corr(j["yf"])),
                "within_tol": bool(diff.median() <= CROSSCHECK_TOL_POINTS),
                "tol_points": CROSSCHECK_TOL_POINTS}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "note": f"cross-check failed: {exc!r}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-date", required=True, help="YYYY-MM-DD (no wall-clock in scripts)")
    ap.add_argument("--raw-dir", default="data/vix_raw")
    ap.add_argument("--etp-dir", default="data/vix_etp")
    ap.add_argument("--skip-download", action="store_true", help="use already-snapshotted files")
    args = ap.parse_args(argv)

    raw = Path(args.raw_dir); raw.mkdir(parents=True, exist_ok=True)
    prov = {"download_date": args.download_date, "path": "C", "signal_primary": "CBOE public CSV",
            "sources": {}, "execution": {}, "crosscheck_yfinance": {}}

    vix_csv, v3m_csv = raw / "VIX_History.csv", raw / "VIX3M_History.csv"
    if not args.skip_download:
        _download_cboe(CBOE_VIX, vix_csv)
        _download_cboe(CBOE_VIX3M, v3m_csv)
    for name, url, path in (("VIX", CBOE_VIX, vix_csv), ("VIX3M", CBOE_VIX3M, v3m_csv)):
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        d = pd.to_datetime(df["date"])
        prov["sources"][name] = {"url": url, "rows": int(len(df)), "bytes": int(path.stat().st_size),
                                 "coverage": [str(d.min().date()), str(d.max().date())],
                                 "snapshot": str(path)}

    # OpenD ETP execution bars (quote-only) — only if not already present
    from ..events.datafetch.opend_daily import fetch_daily_parquet, OpenDUnavailable
    if not args.skip_download:
        try:
            r = fetch_daily_parquet(ETPS, "2004-01-01", args.download_date, data_dir=args.etp_dir)
            prov["execution"]["opend"] = {"written": r["written"], "failed": r["failed"],
                                          "autype": "qfq", "context": "OpenQuoteContext only (no trade ctx)"}
        except OpenDUnavailable as exc:
            prov["execution"]["opend"] = {"error": str(exc)}
    for p in sorted(Path(args.etp_dir).glob("*.parquet")):
        d = pd.read_parquet(p)
        prov["execution"].setdefault("snapshots", {})[p.stem.replace("_1d", "")] = {
            "rows": int(len(d)), "coverage": [str(d["date"].min().date()), str(d["date"].max().date())],
            "snapshot": str(p)}

    prov["crosscheck_yfinance"]["VIX"] = _crosscheck_yf(vix_csv, "^VIX")
    prov["crosscheck_yfinance"]["VIX3M"] = _crosscheck_yf(v3m_csv, "^VIX3M")

    out = raw.parent / "carry_provenance.json"
    out.write_text(json.dumps(prov, indent=2, default=str))
    print(json.dumps(prov, indent=2, default=str))
    print(f"\nprovenance -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

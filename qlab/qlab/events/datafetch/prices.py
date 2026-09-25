"""Real split/dividend-adjusted daily OHLC bars from free public sources.

Contract (matches :class:`qlab.events.bars.ParquetDailyBarSource`): each symbol
is persisted to ``<data_dir>/<symbol>_1d.parquet`` with columns
``[date, open, high, low, close, volume]`` where ``date`` is a normalized
trading day and OHLC are **split- and dividend-adjusted** (candidate 5 computes
overnight = open[t+1]/close[t]; an unadjusted split day would inject a fake
±hundreds-of-percent overnight gap, so adjustment is mandatory, not optional).

Three interchangeable free backends, each returning ``(DataFrame | None, note)``
so a blocked source degrades to an honest gap instead of faking data:

* ``fetch_stooq``  — Stooq ``q/d/l`` CSV. Split+dividend adjusted. Fronted by a
  SHA-256 proof-of-work JS challenge; we solve it the same way a browser does.
* ``fetch_nasdaq`` — Nasdaq ``api/quote`` historical JSON. Split adjusted.
* ``fetch_yahoo``  — Yahoo ``v8/finance/chart`` JSON (uses ``adjclose`` to
  rescale OHLC to a fully adjusted series).

Datacenter-IP note: as of 2026-07, all three actively block this workspace's
egress IP (Stooq → "Access denied" after PoW, Yahoo → 429, Nasdaq → 0 records).
Run these from a normal/residential host, or use ``opend_daily`` on a gateway
host. See ``README.md`` → Blockers.
"""
from __future__ import annotations

import hashlib
import io
import re
import time
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import requests

DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

Result = Tuple[Optional[pd.DataFrame], str]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[DAILY_COLUMNS].dropna(subset=["open", "close"])
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# Stooq (split + dividend adjusted CSV), with proof-of-work challenge solver
# --------------------------------------------------------------------------- #
def _solve_stooq_pow(body: str) -> Optional[Tuple[str, int]]:
    m = re.search(r'c="([^"]+)"', body)
    if not m:
        return None
    c = m.group(1)
    d = re.search(r",d=(\d+),", body) or re.search(r"d=(\d+)", body)
    target = "0" * (int(d.group(1)) if d else 4)
    n = 0
    while True:  # same SHA-256 grind the page's JS performs client-side
        if hashlib.sha256((c + str(n)).encode()).hexdigest().startswith(target):
            return c, n
        n += 1


def fetch_stooq(symbol: str, start: str, end: str,
                session: Optional[requests.Session] = None) -> Result:
    session = session or requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA})
    d1 = pd.Timestamp(start).strftime("%Y%m%d")
    d2 = pd.Timestamp(end).strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d&d1={d1}&d2={d2}"
    body = session.get(url, timeout=30).text
    if "requires JavaScript" in body or re.search(r'c="', body):
        cn = _solve_stooq_pow(body)
        if cn is None:
            return None, "stooq: unrecognized challenge page"
        c, n = cn
        session.post("https://stooq.com/__verify", data={"c": c, "n": n},
                     headers={"Content-Type": "application/x-www-form-urlencoded"},
                     timeout=30)
        time.sleep(1.0)
        body = session.get(url, timeout=30).text
    if body.startswith("Access denied") or "<html" in body[:200].lower():
        return None, "stooq: access denied (IP blocked) — run from a normal host"
    df = pd.read_csv(io.StringIO(body))
    if "Date" not in df.columns:
        return None, f"stooq: unexpected payload head={body[:60]!r}"
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume"})
    return _normalize(df), "stooq: split+dividend adjusted"


# --------------------------------------------------------------------------- #
# Nasdaq (split adjusted JSON)
# --------------------------------------------------------------------------- #
def fetch_nasdaq(symbol: str, start: str, end: str,
                 session: Optional[requests.Session] = None) -> Result:
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/",
    })
    d1 = pd.Timestamp(start).strftime("%Y-%m-%d")
    d2 = pd.Timestamp(end).strftime("%Y-%m-%d")
    url = (f"https://api.nasdaq.com/api/quote/{symbol.upper()}/historical"
           f"?assetclass=stocks&fromdate={d1}&todate={d2}&limit=9999")
    js = session.get(url, timeout=30).json()
    table = (js.get("data") or {}).get("tradesTable") or {}
    rows = table.get("rows")
    if not rows:
        return None, "nasdaq: 0 records (IP soft-blocked) — run from a normal host"
    def num(x):
        return float(str(x).replace("$", "").replace(",", ""))
    df = pd.DataFrame([{
        "date": r["date"], "open": num(r["open"]), "high": num(r["high"]),
        "low": num(r["low"]), "close": num(r["close"]),
        "volume": num(r.get("volume", 0)),
    } for r in rows])
    return _normalize(df), "nasdaq: split adjusted"


# --------------------------------------------------------------------------- #
# Yahoo (adjclose-rescaled to a fully adjusted OHLC series)
# --------------------------------------------------------------------------- #
def fetch_yahoo(symbol: str, start: str, end: str,
                session: Optional[requests.Session] = None) -> Result:
    session = session or requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA})
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp(end).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        return None, f"yahoo: http {r.status_code} (rate-limited) — run from a normal host"
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    df = pd.DataFrame({
        "date": pd.to_datetime(ts, unit="s").normalize(),
        "open": q["open"], "high": q["high"], "low": q["low"],
        "close": q["close"], "volume": q["volume"],
    })
    if adj is not None:
        # rescale raw OHLC by adjclose/close so overnight/intraday legs stay
        # dividend+split consistent across the whole series
        factor = pd.Series(adj).astype(float) / df["close"].astype(float)
        for c in ("open", "high", "low", "close"):
            df[c] = df[c].astype(float) * factor
    return _normalize(df), "yahoo: adjclose-rescaled (split+dividend adjusted)"


BACKENDS = {"stooq": fetch_stooq, "nasdaq": fetch_nasdaq, "yahoo": fetch_yahoo}


def write_parquet(df: pd.DataFrame, data_dir, symbol: str) -> Path:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{symbol.upper()}_1d.parquet"
    df.to_parquet(path, index=False)
    return path

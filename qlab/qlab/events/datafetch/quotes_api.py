"""quotes_api — free market-data API leg for PAPER mark-to-market.

Scope, deliberately narrow: this supplies **close prices for marking a paper
portfolio**, nothing else. It places no orders, touches no real money, and is
NOT part of the EDGAR/RSS evidence chain (that stays anchored on the source's
own publication timestamps in ``evidence_sources``).

Why an API rather than the scrapers: Yahoo (429) and Stooq (anti-bot HTML) block
this egress, but *quote APIs* are reachable — the block is on scraping-oriented
endpoints, not on market-data APIs. Verified 2026-08-08.

Vendor: **Alpha Vantage** (free key, self-registered via the agent email).

Measured limits (2026-08-08, empirical — not vendor marketing):
  * **25 requests/day** on the free key (message: "25 requests per day").
  * **~1 request/second** burst ceiling: a faster burst returns HTTP 200 with an
    ``Information`` throttle notice and **no data**. Paced at 1.2s, 12/12 calls
    succeeded.
  * ``TIME_SERIES_DAILY&outputsize=compact`` returns ~100 trading days including
    the latest close for **one call per symbol**, so a 10-name book + benchmark
    is ~11 calls/day — inside the 25/day budget with headroom.

The throttle notice is the dangerous failure mode: **HTTP 200 that looks fine
but carries no prices**. So this module is fail-closed on exactly that:

  * a throttle/rate-limit response raises ``RateLimited`` — never returns a
    stale or carried-forward price,
  * ``get_daily_closes`` refuses to invent values; a symbol that did not return
    data is reported in ``failed``, not silently filled,
  * ``mark_to_market`` raises ``StalePriceError`` if any holding's newest bar is
    older than the allowed staleness — a paper mark must never be printed from
    prices we could not actually refresh.

Each bar keeps **the source's own trade date** (the API's date key). We never
substitute our clock, and the returned bar dates are the authoritative trading
calendar — no holiday table, no look-ahead calendar, no scraping SPY.

Key handling (same discipline as the FRED key): read from the environment only
(``ALPHAVANTAGE_API_KEY``), persisted outside the repo at
``~/.config/alphavantage/api.env`` (chmod 600). Never committed, logged, or printed.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import pandas as pd
import requests

AV_URL = "https://www.alphavantage.co/query"
# Empirically measured on the free key (see module docstring).
FREE_TIER = {"requests_per_day": 25, "min_seconds_between_calls": 1.2}


class MissingApiKey(RuntimeError):
    """No ALPHAVANTAGE_API_KEY — refuse to run rather than degrade."""


class RateLimited(RuntimeError):
    """Vendor throttled us: HTTP 200 but no data. Never treated as 'no change'."""


class StalePriceError(RuntimeError):
    """A holding's newest bar is older than allowed — refuse to print a mark."""


def get_api_key(explicit: Optional[str] = None) -> str:
    key = explicit or os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise MissingApiKey(
            "ALPHAVANTAGE_API_KEY not set. Load it from ~/.config/alphavantage/api.env "
            "(chmod 600); this module never falls back to stale or estimated prices.")
    return key


@dataclass
class DailyBar:
    symbol: str
    date: str          # THE source's own trade date (vendor date key), YYYY-MM-DD
    close: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    source: str = "alphavantage:TIME_SERIES_DAILY"
    retrieved_utc: str = ""     # OUR clock, diagnostics only, never a price date


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(text: str, api_key: Optional[str] = None) -> str:
    """把 vendor 回包里回显的 API key 抹掉，再放进异常/日志。

    营缮 2026-08-08 实测（用假 key 验证机制，未回显真 key）：Alpha Vantage 的限速回包
    **原文回显 API key** —— `"We have detected your API key as <KEY> and our standard API
    rate limit is 25 requests per day..."`。原实现把 `str(msg)[:200]` 直接塞进 `RateLimited`，
    于是**任何 traceback / run 日志都会带出 key**，违反「key 不进日志」这条纪律。
    这里在入异常前统一脱敏；`api_key` 缺省时也扫 env，避免调用方忘传。
    """
    if not text:
        return text
    keys = [k for k in (api_key, os.environ.get(ENV_VAR) if "ENV_VAR" in globals() else None,
                        os.environ.get("ALPHAVANTAGE_API_KEY")) if k]
    for k in keys:
        if k and len(k) >= 6:
            text = text.replace(k, "<redacted-api-key>")
    return text


def _check_throttle(payload: dict, symbol: str, api_key: Optional[str] = None) -> None:
    """AV signals throttling via 'Note'/'Information' with HTTP 200. Fail closed.

    异常文本一律经 `_redact` 脱敏（AV 回包会回显 key，不脱敏就会进日志）。
    """
    for field in ("Note", "Information"):
        msg = payload.get(field)
        if msg and "Time Series" not in payload:
            raise RateLimited(f"{symbol}: {field}: {_redact(str(msg), api_key)[:200]}")
    if payload.get("Error Message"):
        raise RuntimeError(f"{symbol}: {_redact(str(payload['Error Message']), api_key)[:200]}")


def fetch_daily(symbol: str, *, api_key: Optional[str] = None,
                outputsize: str = "compact",
                session: Optional[requests.Session] = None) -> list[DailyBar]:
    """Daily bars for one symbol. Raises RateLimited / RuntimeError; never fakes."""
    session = session or requests.Session()
    resolved_key = get_api_key(api_key)          # 解析一次，供脱敏复用（勿再内联）
    r = session.get(AV_URL, params={
        "function": "TIME_SERIES_DAILY", "symbol": symbol,
        "outputsize": outputsize, "apikey": resolved_key}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{symbol}: http {r.status_code}")
    payload = r.json()
    _check_throttle(payload, symbol, api_key=resolved_key)
    key = next((k for k in payload if "Time Series" in k), None)
    if key is None:
        raise RuntimeError(f"{symbol}: unexpected payload keys {list(payload)[:4]}")
    now = _now_iso()
    bars = []
    for d, row in payload[key].items():
        bars.append(DailyBar(
            symbol=symbol, date=d, close=float(row["4. close"]),
            open=float(row.get("1. open", "nan")), high=float(row.get("2. high", "nan")),
            low=float(row.get("3. low", "nan")), volume=float(row.get("5. volume", "nan")),
            retrieved_utc=now))
    bars.sort(key=lambda b: b.date)
    return bars


def get_daily_closes(symbols: Iterable[str], *, api_key: Optional[str] = None,
                     session: Optional[requests.Session] = None,
                     pace_seconds: float = FREE_TIER["min_seconds_between_calls"],
                     sleep=time.sleep) -> tuple[dict[str, list[DailyBar]], dict[str, str]]:
    """Fetch several symbols, paced under the measured burst ceiling.

    Returns ``(bars_by_symbol, failed)``. A symbol that could not be fetched
    lands in ``failed`` with the reason — it is never back-filled or carried
    forward from a previous run.
    """
    key = get_api_key(api_key)
    session = session or requests.Session()
    out: dict[str, list[DailyBar]] = {}
    failed: dict[str, str] = {}
    syms = list(symbols)
    for i, s in enumerate(syms):
        try:
            out[s] = fetch_daily(s, api_key=key, session=session)
        except Exception as e:                       # RateLimited / http / payload
            failed[s] = f"{type(e).__name__}: {e}"[:200]
        if i < len(syms) - 1 and pace_seconds:
            sleep(pace_seconds)
    return out, failed


def trading_days(bars_by_symbol: dict[str, list[DailyBar]]) -> list[str]:
    """The authoritative trading calendar = dates that actually have bars.

    observe-not-predict: a day is a trading day because a bar exists for it, not
    because a holiday table said so. No look-ahead calendar, no SPY scraping.
    """
    days: set[str] = set()
    for bars in bars_by_symbol.values():
        days.update(b.date for b in bars)
    return sorted(days)


def mark_to_market(holdings: dict[str, float], bars_by_symbol: dict[str, list[DailyBar]],
                   *, as_of: Optional[str] = None, max_staleness_days: int = 5
                   ) -> dict:
    """Value a paper book from real closes. Fail-closed on missing/stale prices.

    ``holdings``: symbol -> share count. Raises StalePriceError if a held symbol
    has no bar, or its newest bar is more than ``max_staleness_days`` calendar
    days before ``as_of`` (default: the newest date observed across all symbols).
    """
    if not holdings:
        return {"as_of": as_of, "positions": {}, "market_value": 0.0}
    all_days = trading_days(bars_by_symbol)
    if not all_days:
        raise StalePriceError("no bars at all — refusing to mark")
    as_of = as_of or all_days[-1]
    as_of_ts = pd.Timestamp(as_of)

    positions, missing, stale = {}, [], []
    for sym, qty in holdings.items():
        bars = [b for b in bars_by_symbol.get(sym, []) if b.date <= as_of]
        if not bars:
            missing.append(sym)
            continue
        last = bars[-1]
        age = (as_of_ts - pd.Timestamp(last.date)).days
        if age > max_staleness_days:
            stale.append(f"{sym}(last={last.date}, {age}d old)")
            continue
        positions[sym] = {"qty": qty, "price": last.close, "price_date": last.date,
                          "value": qty * last.close}
    if missing or stale:
        raise StalePriceError(
            f"refusing to mark as_of {as_of}: missing={missing} stale={stale}. "
            "A paper mark must not use carried-forward or estimated prices.")
    return {"as_of": as_of, "positions": positions,
            "market_value": sum(p["value"] for p in positions.values()),
            "price_source": "alphavantage:TIME_SERIES_DAILY (source trade dates)"}


def to_frame(bars_by_symbol: dict[str, list[DailyBar]]) -> pd.DataFrame:
    rows = [{"symbol": b.symbol, "date": b.date, "open": b.open, "high": b.high,
             "low": b.low, "close": b.close, "volume": b.volume,
             "source": b.source, "retrieved_utc": b.retrieved_utc}
            for bars in bars_by_symbol.values() for b in bars]
    df = pd.DataFrame(rows)
    return df.sort_values(["symbol", "date"]).reset_index(drop=True) if not df.empty else df

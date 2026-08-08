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

The 25/day cap is **accounted, not merely documented**: pass an
``api_quota.DailyQuotaGuard`` and every call is checked against a persisted
per-UTC-day ledger *before* it is issued, with a slice of the cap ring-fenced for
marking. Without that, a day's quota can be silently exhausted, the mark refused,
and the NAV series — the only acceptance evidence here — left with an
unrepairable hole. See ``api_quota``.

Detection control (工部 08-08, in place of rotation — unavailable at this vendor):
if the vendor throttles while our own ledger still shows budget left, the
``RateLimited`` is tagged ``QUOTA_DIVERGENCE`` and carries ``ledger_remaining`` /
``vendor_throttled`` / ``utc_day``. That is the observable signature of the only
real risk this key carries — someone else spending its 25/day — and it also makes
any drift between our UTC bucketing and the vendor's undocumented reset boundary
visible instead of silent.

Each bar keeps **the source's own trade date** (the API's date key). We never
substitute our clock, and the returned bar dates are the authoritative trading
calendar — no holiday table, no look-ahead calendar, no scraping SPY.

Key handling (same discipline as the FRED key): read from the environment only
(``ALPHAVANTAGE_API_KEY``), persisted outside the repo at
``~/.config/alphavantage/api.env`` (chmod 600). Never committed, logged, or printed.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import pandas as pd
import requests

from .api_quota import QuotaExceeded  # re-exported: budget breach is fail-closed

AV_URL = "https://www.alphavantage.co/query"
# Empirically measured on the free key (see module docstring).
FREE_TIER = {"requests_per_day": 25, "min_seconds_between_calls": 1.2}


class MissingApiKey(RuntimeError):
    """No ALPHAVANTAGE_API_KEY — refuse to run rather than degrade."""


class RateLimited(RuntimeError):
    """Vendor throttled us: HTTP 200 but no data. Never treated as 'no change'.

    Carries the local budget state at the moment of the throttle so the two very
    different causes are distinguishable:

    * ``divergence=False`` — our ledger also says we're out. Expected exhaustion.
    * ``divergence=True``  — **our ledger still shows budget left** yet the vendor
      throttled. Either someone else is spending this key's quota, or our counter
      has drifted from the vendor's (e.g. their reset boundary differs from our
      UTC bucketing — undocumented, so this makes it observable). Tagged
      ``QUOTA_DIVERGENCE``; it is the detection control for a leaked key, which
      matters more here than rotation (rotation is unavailable at this vendor).
    """

    def __init__(self, message: str, *, ledger_remaining: Optional[int] = None,
                 vendor_throttled: bool = True, utc_day: Optional[str] = None,
                 kind: str = "daily"):
        self.ledger_remaining = ledger_remaining
        self.vendor_throttled = vendor_throttled
        self.utc_day = utc_day
        # burst vs daily 已在 _throttle_kind 分好，但此前只进了 message 文本。
        # 调用方要按类别决定「继续跑还是整批中止」，靠 substring 猜是回退——故显式带出来。
        self.kind = kind
        self.divergence = bool(ledger_remaining is not None and ledger_remaining > 0
                               and vendor_throttled)
        if ledger_remaining is not None:
            message = (f"{message} [ledger_remaining={ledger_remaining}, "
                       f"vendor_throttled={vendor_throttled}"
                       f"{', utc_day=' + utc_day if utc_day else ''}"
                       f"{'] QUOTA_DIVERGENCE' if self.divergence else ']'}")
        super().__init__(message)


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


def _redact(msg: str, api_key: Optional[str] = None) -> str:
    """Strip the API key out of a vendor message before it reaches an exception.

    Alpha Vantage echoes the key back in its daily-quota notice ("We have
    detected your API key as XXXX..."). That message ends up in ``RateLimited``,
    which may be logged, reported, or pasted into a status update — so the key
    must never survive into it. Belt and braces: redact the live key by value,
    then any AV-shaped key token.
    """
    text = str(msg)
    key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY")
    if key:
        text = text.replace(key, "<redacted-api-key>")
    return re.sub(r"\b[A-Z0-9]{12,20}\b", "<redacted-api-key>", text)


def _throttle_kind(msg: str) -> str:
    """Classify AV's throttle notice: per-second ``burst`` vs ``daily`` exhaustion.

    Both notices mention "25 requests per day", so keying on that would conflate
    them. The burst notice is the one that asks us to space requests out; it is
    transient (retry after pacing) and must NOT raise a divergence alarm, or the
    alarm cries wolf on every unpaced burst. Only a DAILY-exhaustion notice while
    our ledger still shows budget is evidence of someone else spending the key.
    """
    low = str(msg).lower()
    if "spreading out" in low or "per second" in low:
        return "burst"
    return "daily"


def _check_throttle(payload: dict, symbol: str,
                    api_key: Optional[str] = None, guard=None,
                    purpose: str = "marking") -> None:
    """AV signals throttling via 'Note'/'Information' with HTTP 200. Fail closed.

    Before raising, read the local budget: being throttled *for the day* while our
    own ledger still shows headroom is the observable signature of a leaked key
    (or of our counter drifting from the vendor's). See ``RateLimited.divergence``.
    """
    for field in ("Note", "Information"):
        msg = payload.get(field)
        if msg and "Time Series" not in payload:
            kind = _throttle_kind(msg)
            remaining, day = None, None
            if guard is not None and kind == "daily":
                try:
                    remaining = guard.remaining(purpose)
                    day = guard.status().get("utc_day")
                except Exception:      # diagnostics must never mask the throttle
                    remaining, day = None, None
            raise RateLimited(
                f"{symbol}: {field} ({kind} throttle): {_redact(msg, api_key)[:200]}",
                ledger_remaining=remaining, vendor_throttled=True, utc_day=day,
                kind=kind)
    if payload.get("Error Message"):
        raise RuntimeError(f"{symbol}: {_redact(payload['Error Message'], api_key)[:200]}")


def fetch_daily(symbol: str, *, api_key: Optional[str] = None,
                outputsize: str = "compact",
                session: Optional[requests.Session] = None,
                guard=None, purpose: str = "marking") -> list[DailyBar]:
    """Daily bars for one symbol. Raises RateLimited / RuntimeError; never fakes.

    ``guard`` (``api_quota.DailyQuotaGuard``) accounts the call against the hard
    daily budget BEFORE it is issued: over budget -> ``QuotaExceeded`` and the
    request never leaves. The spend is recorded only once the call is actually
    made, so a pre-flight rejection does not burn quota.
    """
    session = session or requests.Session()
    resolved_key = get_api_key(api_key)
    if guard is not None:
        guard.check(1, purpose=purpose)      # fail-closed, before any network I/O
    r = session.get(AV_URL, params={
        "function": "TIME_SERIES_DAILY", "symbol": symbol,
        "outputsize": outputsize, "apikey": resolved_key}, timeout=30)
    if guard is not None:
        # The request left the host, so it counts — record BEFORE inspecting the
        # reply. Conservative on purpose: a throttled/failed call still consumed
        # an attempt, and under-counting is what would silently blow the budget.
        guard.record(purpose=purpose, symbol=symbol, note=f"http {r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"{symbol}: http {r.status_code}")
    payload = r.json()
    _check_throttle(payload, symbol, api_key=resolved_key,
                    guard=guard, purpose=purpose)
    ts_key = next((k for k in payload if "Time Series" in k), None)
    if ts_key is None:
        raise RuntimeError(f"{symbol}: unexpected payload keys {list(payload)[:4]}")
    now = _now_iso()
    bars = []
    for d, row in payload[ts_key].items():
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
                     sleep=time.sleep,
                     guard=None, purpose: str = "marking",
                     require_full_batch: bool = True
                     ) -> tuple[dict[str, list[DailyBar]], dict[str, str]]:
    """Fetch several symbols, paced under the measured burst ceiling.

    Returns ``(bars_by_symbol, failed)``. A symbol that could not be fetched
    lands in ``failed`` with the reason — it is never back-filled or carried
    forward from a previous run.

    With a ``guard``, the WHOLE batch is checked up front when
    ``require_full_batch`` (default): if today's budget cannot cover every
    symbol, raise ``QuotaExceeded`` before spending anything, rather than
    burning quota on a partial mark that ``mark_to_market`` would reject anyway.
    """
    key = get_api_key(api_key)
    session = session or requests.Session()
    out: dict[str, list[DailyBar]] = {}
    failed: dict[str, str] = {}
    syms = list(symbols)
    if guard is not None and require_full_batch and syms:
        guard.check(len(syms), purpose=purpose)
    for i, s in enumerate(syms):
        try:
            out[s] = fetch_daily(s, api_key=key, session=session,
                                 guard=guard, purpose=purpose)
        except QuotaExceeded:
            # A budget breach is not a per-symbol data problem — do not bury it
            # in `failed` (that would read as "this symbol was unavailable" and
            # keep the loop burning the remaining quota). Propagate.
            raise
        except RateLimited as e:
            # Same reasoning, and one more that is specific to the alarm: burying a
            # DAILY throttle in `failed` destroys it. `failed[s]` is a 200-char slice
            # of str(e), and the "[ledger_remaining=…] QUOTA_DIVERGENCE" tag is
            # appended LAST — so it is the first thing truncated away (measured with
            # AV's real daily notice: 330-char message -> tag and ledger_remaining
            # both gone). A leaked-key signal must not degrade into vendor prose that
            # reads as "this symbol was unavailable", and the loop must not keep
            # calling a vendor that just refused us for the day.
            # A BURST throttle is the transient exception: per-second pacing, not a
            # budget or leak signal, so it stays a per-symbol failure as before.
            if getattr(e, "kind", "daily") == "burst" and not e.divergence:
                failed[s] = f"RateLimited: {e}"[:200]
            else:
                raise
        except Exception as e:                       # http / payload shape
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

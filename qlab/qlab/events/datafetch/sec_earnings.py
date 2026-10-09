"""Real earnings-announcement timestamps from SEC EDGAR 8-K item 2.02.

Why this source
---------------
An 8-K carrying **item 2.02** ("Results of Operations and Financial Condition")
is the filing a US issuer submits when it releases quarterly/annual results. Its
EDGAR *acceptance* timestamp is a faithful, free, audit-trail proxy for the
announcement session — companies file the 8-K within minutes of the press
release, so the acceptance time lands on the same side of the 09:30 open / 16:00
close boundary as the release itself. The exact minute is NOT load-bearing here;
only which session (bmo / amc / intraday) the news belongs to is, and the
boundary side is robust.

Timezone — the load-bearing detail (EVO-24: "时区别错，最卡最高危")
------------------------------------------------------------------
The submissions API returns ``acceptanceDateTime`` as ``...Z`` (UTC). This was
verified empirically against known reporters:

* JPMorgan (reports pre-market): 2026-01-13T11:41:09Z → 06:41 America/New_York → bmo ✓
* Apple (reports after close):   2026-01-29T21:30:33Z → 16:30 America/New_York → amc ✓

Both match reality **only** when the ``Z`` is honored as UTC and converted to
``America/New_York`` with correct DST. We therefore parse as UTC, tz_convert to
Eastern, drop the tz to get a naive Eastern wall-clock, and classify on that.
Getting this wrong (treating the stamp as Eastern, or ignoring DST) silently
flips bmo↔amc and injects look-ahead — exactly the failure the constraint warns
against.

Output
------
A DataFrame / CSV with columns ``symbol, announce_time, session,
analyst_surprise, source`` where ``announce_time`` is Eastern wall-clock
(naive), ready for :class:`qlab.events.eventsource.CsvEventSource`.
``analyst_surprise`` is left blank on purpose: consensus estimates are a
separate, optional gap (#4), so the backtester falls back to its
abnormal-return quantile proxy per the EVO-24 spec.
"""
from __future__ import annotations

import time
from typing import Dict, List

import pandas as pd

from ..eventsource import classify_session
from .universe import make_session

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EARNINGS_ITEM = "2.02"  # Results of Operations and Financial Condition
MARKET_TZ = "America/New_York"


def _acceptance_to_eastern(raw: str) -> pd.Timestamp:
    """``2026-01-29T21:30:33.000Z`` (UTC) → naive Eastern wall-clock Timestamp."""
    ts_utc = pd.Timestamp(raw)  # tz-aware UTC (the trailing Z)
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.tz_localize("UTC")
    return ts_utc.tz_convert(MARKET_TZ).tz_localize(None)


def _iter_filing_blocks(session, cik: str) -> List[dict]:
    """Yield the ``recent`` block plus any older paginated blocks for one CIK."""
    url = SUBMISSIONS_URL.format(cik=cik)
    data = session.get(url, timeout=30).json()
    blocks = [data["filings"]["recent"]]
    for f in data["filings"].get("files", []):
        older = session.get(
            f"https://data.sec.gov/submissions/{f['name']}", timeout=30
        ).json()
        # older files are the bare column dict, not nested under filings/recent
        blocks.append(older)
        time.sleep(0.15)
    return blocks


def fetch_symbol_events(session, symbol: str, cik: str,
                        start: str, end: str) -> pd.DataFrame:
    """All 8-K item-2.02 earnings events for one symbol in ``[start, end]``."""
    start_d = pd.Timestamp(start).normalize()
    end_d = pd.Timestamp(end).normalize()
    rows = []
    for block in _iter_filing_blocks(session, cik):
        forms = block.get("form", [])
        items = block.get("items", [])
        accepted = block.get("acceptanceDateTime", [])
        filing_dates = block.get("filingDate", [])
        for i in range(len(forms)):
            if forms[i] != "8-K":
                continue
            if EARNINGS_ITEM not in (items[i] or ""):
                continue
            et = _acceptance_to_eastern(accepted[i])
            if not (start_d <= et.normalize() <= end_d):
                continue
            rows.append({
                "symbol": symbol.upper(),
                "announce_time": et.strftime("%Y-%m-%d %H:%M:%S"),
                "session": classify_session(et),
                "analyst_surprise": "",  # optional gap #4 → quantile proxy used
                "source": "sec_8k_2.02",
                "filing_date": filing_dates[i],
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # one earnings release per quarter: drop rare same-day duplicate 2.02 filings
    df = (df.sort_values("announce_time")
            .drop_duplicates(subset=["symbol", "filing_date"], keep="first")
            .reset_index(drop=True))
    return df


def fetch_earnings(ciks: Dict[str, str], start: str, end: str,
                   session=None, pause: float = 0.2) -> pd.DataFrame:
    """Fetch item-2.02 earnings events for every ``symbol→cik`` in ``ciks``."""
    session = session or make_session()
    frames = []
    for symbol, cik in ciks.items():
        try:
            df = fetch_symbol_events(session, symbol, cik, start, end)
            frames.append(df)
        except Exception as exc:  # noqa: BLE001 — report, don't abort the batch
            print(f"[sec_earnings] {symbol} ({cik}) failed: {exc}")
        time.sleep(pause)  # stay well under SEC's 10 req/s fair-access ceiling
    if not frames or all(f.empty for f in frames):
        return pd.DataFrame(
            columns=["symbol", "announce_time", "session", "analyst_surprise", "source"]
        )
    out = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    return out.sort_values(["announce_time", "symbol"]).reset_index(drop=True)


def write_earnings_csv(df: pd.DataFrame, path) -> None:
    cols = ["symbol", "announce_time", "session", "analyst_surprise", "source"]
    df[cols].to_csv(path, index=False)

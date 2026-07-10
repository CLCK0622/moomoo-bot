"""Ticker universe and ticker→CIK resolution for the event-drift battery.

The default universe is a fixed, documented list of large, liquid US names with
clean 8-K item-2.02 earnings and a deliberate bmo/amc mix. It is **survivorship
biased** (every name is a present-day survivor) — that is a known, separately
tracked gap (see the risk register / card_E); this module does not pretend to
solve it. For a real point-in-time study, feed a historical constituent list
via ``--symbols`` instead.
"""
from __future__ import annotations

from typing import Dict, List

import requests

# 19 liquid large caps, sector-spread, with a bmo (financials) / amc (tech)
# mix so both session branches are exercised. Fixed on purpose: reproducibility
# beats coverage here, and the wiring is universe-agnostic.
#
# CIK caveat: resolve_ciks uses SEC's *current* ticker→CIK map. A few tickers
# have been reassigned to a newly-registered holding entity with no filing
# history (e.g. "XOM" now resolves to CIK 0002115436, which has zero 8-K 2.02
# filings), so such names silently yield 0 events. XOM is therefore excluded
# here; add it back only with its legacy CIK if you need energy breadth beyond
# CVX. Always check the manifest's ``events_per_symbol`` for 0-count symbols.
DEFAULT_UNIVERSE: List[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "CSCO", "INTC", "ORCL",
    "JPM", "BAC", "GS", "WMT", "HD", "KO", "PG", "JNJ", "PFE", "CVX",
]

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# A descriptive User-Agent with a contact is REQUIRED by SEC EDGAR's fair-access
# policy; anonymous/browser-spoofing agents get throttled or blocked.
DEFAULT_SEC_UA = "multica-research qlab-events (contact: kevin.zhong@pivothire.tech)"


def make_session(user_agent: str = DEFAULT_SEC_UA) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return s


def resolve_ciks(symbols: List[str], session: requests.Session | None = None
                 ) -> Dict[str, str]:
    """Map each ticker to its zero-padded 10-digit SEC CIK.

    Returns only the symbols SEC knows; unknown tickers are dropped (the caller
    should compare against the input to see what was skipped).
    """
    session = session or make_session()
    raw = session.get(SEC_TICKERS_URL, timeout=30).json()
    by_ticker: Dict[str, str] = {}
    for row in raw.values():
        by_ticker[row["ticker"].upper()] = str(row["cik_str"]).zfill(10)
    out: Dict[str, str] = {}
    for sym in symbols:
        cik = by_ticker.get(sym.upper())
        if cik:
            out[sym.upper()] = cik
    return out

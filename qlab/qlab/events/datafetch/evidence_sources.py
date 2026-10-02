"""evidence_sources — public-information ingestion that PRESERVES the source's own timestamp.

For the thin-alpha / paper-decision track: every decision record must satisfy

    evidence_time <= decision_time <= return_start

and — this is the load-bearing part — ``evidence_time`` must come from **the
information source itself** (EDGAR ``acceptanceDateTime``, RSS ``pubDate``),
NEVER from our own clock. A timestamp we generate is self-attestation: it proves
nothing to an auditor. So this module's contract is:

    **A record without a parseable SOURCE timestamp is REJECTED, not stamped.**

That is fail-closed by design (same discipline as ``fred_vintage``: no key ->
raise, never silently degrade). Dropping the source timestamp anywhere in the
chain voids the whole audit trail, so there is no "fill it in with now()" path.

Sources implemented (all free, no key except FRED):

* ``fetch_edgar_filings``  — SEC EDGAR submissions API. Source time =
  ``acceptanceDateTime`` (UTC, second resolution — when EDGAR actually accepted
  the filing, not the calendar ``filingDate``).
* ``fetch_rss``           — any RSS/Atom feed. Source time = item ``pubDate`` /
  ``published`` / ``updated``, parsed as RFC-822 or ISO-8601.
* FRED numeric series stay in ``fred_yields`` / ``fred_vintage`` (already
  point-in-time aware; the key is reusable from ``~/.config/fred/api.env``).

Every record also carries ``retrieved_utc`` (OUR clock) — kept strictly separate
and clearly labelled, for lag diagnostics only. It is never used as evidence
time. ``retrieved_utc >= source_time`` always; if it isn't, the clock is wrong
and ``validate_records`` flags it.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

import pandas as pd
import requests

SEC_UA = "multica-research qlab-events (contact: kevin.zhong@pivothire.tech)"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Free news feeds verified reachable from this runtime with the SEC_UA above
# (2026-08-08). Note: prnewswire.com 404s under SEC_UA and needs a browser UA —
# left out deliberately rather than shipping a UA-fragile default.
RSS_FEEDS = {
    # per-symbol headlines ({symbol} is formatted in)
    "yahoo_symbol": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
    # broad market news (index proxy, no per-symbol filter)
    "yahoo_market": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    # corporate press releases from public companies
    "globenewswire_public": ("https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/"
                             "GlobeNewswire%20-%20News%20about%20Public%20Companies"),
}


class MissingSourceTimestamp(ValueError):
    """A record carried no parseable source-side timestamp -> unusable as evidence."""


@dataclass
class EvidenceRecord:
    """One piece of public information, anchored to the SOURCE's own clock."""

    source: str              # 'sec_edgar' | 'rss:yahoo_symbol' | ...
    source_time_utc: str     # THE audit anchor — from the source, ISO-8601 UTC
    source_time_field: str   # which upstream field it came from (acceptanceDateTime / pubDate)
    symbol: Optional[str]
    title: str
    url: str
    ref_id: str              # accession number / guid / link — for dedup
    retrieved_utc: str       # OUR clock, diagnostics only, NEVER evidence time
    extra: Optional[dict] = None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_utc_iso(raw: str, *, field: str) -> str:
    """Parse a source timestamp (ISO-8601 or RFC-822) -> ISO-8601 UTC. Fail-closed."""
    if raw is None or not str(raw).strip():
        raise MissingSourceTimestamp(f"empty source timestamp in field {field!r}")
    s = str(raw).strip()
    dt = None
    try:                                   # ISO-8601 (EDGAR: 2026-07-30T20:30:28.000Z)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:                               # RFC-822 (RSS: Sat, 08 Aug 2026 01:30:18 +0000)
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError) as e:
            raise MissingSourceTimestamp(
                f"unparseable source timestamp {s!r} in field {field!r}: {e}") from e
    if dt.tzinfo is None:                  # naive -> the source omitted an offset
        raise MissingSourceTimestamp(
            f"source timestamp {s!r} ({field}) has no timezone — refusing to guess")
    return dt.astimezone(timezone.utc).isoformat()


def make_session(user_agent: str = SEC_UA) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return s


# --------------------------------------------------------------------------- #
# SEC EDGAR — source time = acceptanceDateTime (when EDGAR accepted the filing)
# --------------------------------------------------------------------------- #
def fetch_edgar_filings(cik: str, *, symbol: Optional[str] = None,
                        forms: Optional[Iterable[str]] = None,
                        since: Optional[str] = None,
                        session: Optional[requests.Session] = None
                        ) -> tuple[list[EvidenceRecord], list[dict]]:
    """Recent EDGAR filings as EvidenceRecords. Returns ``(records, rejected)``.

    ``rejected`` holds entries dropped for a missing/unparseable source timestamp —
    surfaced, never silently stamped with our clock.
    """
    session = session or make_session()
    cik10 = str(cik).lstrip("CIK").zfill(10)
    r = session.get(SUBMISSIONS_URL.format(cik=cik10), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"edgar submissions http {r.status_code} for CIK {cik10}")
    recent = (r.json().get("filings") or {}).get("recent") or {}
    n = len(recent.get("accessionNumber", []))
    want = {f.upper() for f in forms} if forms else None
    since_ts = pd.Timestamp(since, tz="UTC") if since else None

    out: list[EvidenceRecord] = []
    rejected: list[dict] = []
    for i in range(n):
        form = recent["form"][i]
        if want and form.upper() not in want:
            continue
        try:
            src = _to_utc_iso(recent.get("acceptanceDateTime", [None] * n)[i],
                              field="acceptanceDateTime")
        except MissingSourceTimestamp as e:
            rejected.append({"accession": recent["accessionNumber"][i],
                             "form": form, "reason": str(e)})
            continue
        if since_ts is not None and pd.Timestamp(src) < since_ts:
            continue
        acc = recent["accessionNumber"][i]
        acc_nodash = acc.replace("-", "")
        doc = recent.get("primaryDocument", [""] * n)[i]
        out.append(EvidenceRecord(
            source="sec_edgar",
            source_time_utc=src,
            source_time_field="acceptanceDateTime",
            symbol=symbol,
            title=f"{form} {recent.get('primaryDocDescription', [''] * n)[i]}".strip(),
            url=f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{acc_nodash}/{doc}",
            ref_id=acc,
            retrieved_utc=_now_utc_iso(),
            extra={"form": form, "filing_date": recent.get("filingDate", [None] * n)[i],
                   "report_date": recent.get("reportDate", [None] * n)[i],
                   "items": recent.get("items", [None] * n)[i]},
        ))
    return out, rejected


# --------------------------------------------------------------------------- #
# RSS / Atom — source time = item pubDate / published / updated
# --------------------------------------------------------------------------- #
_TIME_TAGS = ("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published",
              "{http://www.w3.org/2005/Atom}updated")


def _text(el, *names) -> Optional[str]:
    for nm in names:
        found = el.find(nm)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
        # attribute-style Atom links
        if nm.endswith("link"):
            found = el.find(nm)
            if found is not None and found.get("href"):
                return found.get("href")
    return None


def fetch_rss(feed_url: str, *, source_label: str, symbol: Optional[str] = None,
              session: Optional[requests.Session] = None
              ) -> tuple[list[EvidenceRecord], list[dict]]:
    """Parse an RSS/Atom feed into EvidenceRecords. Returns ``(records, rejected)``."""
    session = session or make_session()
    r = session.get(feed_url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"rss http {r.status_code} for {feed_url}")
    root = ET.fromstring(r.content)
    items = root.iter("item")
    items = list(items) or list(root.iter("{http://www.w3.org/2005/Atom}entry"))

    out: list[EvidenceRecord] = []
    rejected: list[dict] = []
    for it in items:
        raw_t, field = None, None
        for tag in _TIME_TAGS:
            el = it.find(tag)
            if el is not None and (el.text or "").strip():
                raw_t, field = el.text.strip(), tag.split("}")[-1]
                break
        title = _text(it, "title", "{http://www.w3.org/2005/Atom}title") or ""
        link = _text(it, "link", "{http://www.w3.org/2005/Atom}link") or ""
        guid = _text(it, "guid", "id", "{http://www.w3.org/2005/Atom}id") or link
        try:
            src = _to_utc_iso(raw_t, field=field or "pubDate")
        except MissingSourceTimestamp as e:
            rejected.append({"title": title[:120], "url": link, "reason": str(e)})
            continue
        out.append(EvidenceRecord(
            source=f"rss:{source_label}", source_time_utc=src,
            source_time_field=field or "pubDate", symbol=symbol,
            title=title, url=link, ref_id=guid, retrieved_utc=_now_utc_iso(),
        ))
    return out, rejected


# --------------------------------------------------------------------------- #
# Validation + persistence
# --------------------------------------------------------------------------- #
def validate_records(records: Iterable[EvidenceRecord]) -> dict:
    """Assert the audit invariants. Raises on violation (fail-closed)."""
    recs = list(records)
    problems = []
    for r in recs:
        if not r.source_time_utc:
            problems.append(f"{r.ref_id}: no source_time_utc")
            continue
        st = pd.Timestamp(r.source_time_utc)
        rt = pd.Timestamp(r.retrieved_utc)
        if st.tz is None or rt.tz is None:
            problems.append(f"{r.ref_id}: naive timestamp")
        elif rt < st:
            # our clock claims we fetched it BEFORE the source published it
            problems.append(f"{r.ref_id}: retrieved_utc {rt} < source_time_utc {st} (clock skew)")
    if problems:
        raise ValueError("evidence validation failed: " + "; ".join(problems[:5]))
    return {"n_records": len(recs),
            "sources": sorted({r.source for r in recs}),
            "source_time_span": [min((r.source_time_utc for r in recs), default=None),
                                 max((r.source_time_utc for r in recs), default=None)]}


def to_frame(records: Iterable[EvidenceRecord]) -> pd.DataFrame:
    rows = [asdict(r) for r in records]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[f.name for f in EvidenceRecord.__dataclass_fields__.values()])
    return df.sort_values("source_time_utc").reset_index(drop=True)


def write_parquet(records: Iterable[EvidenceRecord], path) -> "pd.DataFrame":
    from pathlib import Path
    df = to_frame(records)
    if "extra" in df.columns:                     # dict -> json string for parquet
        import json
        df["extra"] = df["extra"].map(lambda x: json.dumps(x) if isinstance(x, dict) else x)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return df

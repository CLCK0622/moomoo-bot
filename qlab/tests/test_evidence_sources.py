"""Tests for evidence_sources — the source-timestamp contract.

Offline (canned EDGAR JSON / RSS XML via fake sessions). Pins the one property
the whole decision audit trail rests on: ``evidence_time`` comes from the SOURCE
(EDGAR acceptanceDateTime / RSS pubDate) and a record without a parseable source
timestamp is REJECTED — never stamped with our own clock.
"""
from __future__ import annotations

import pandas as pd
import pytest

from qlab.events.datafetch import evidence_sources as ev


class _Resp:
    def __init__(self, payload=None, content=b"", status=200):
        self._p = payload
        self.content = content
        self.status_code = status

    def json(self):
        return self._p


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.headers = {}

    def get(self, url, timeout=30):
        return self._resp


_EDGAR = {"filings": {"recent": {
    "accessionNumber": ["0000320193-26-000018", "0000320193-26-000019", "0000320193-26-000020"],
    "form": ["8-K", "8-K", "10-Q"],
    "filingDate": ["2026-07-30", "2026-07-29", "2026-07-31"],
    # middle one has NO acceptance time -> must be rejected, not back-filled
    "acceptanceDateTime": ["2026-07-30T20:30:28.000Z", "", "2026-07-31T10:01:02.000Z"],
    "reportDate": ["2026-07-30", "2026-07-29", "2026-06-27"],
    "primaryDocument": ["a.htm", "b.htm", "c.htm"],
    "primaryDocDescription": ["8-K", "8-K", "10-Q"],
    "items": ["2.02", "", ""],
}}}


def test_edgar_uses_acceptance_time_and_rejects_missing():
    recs, rejected = fetch = ev.fetch_edgar_filings(
        "0000320193", symbol="AAPL", session=_FakeSession(_Resp(payload=_EDGAR)))
    assert len(recs) == 2 and len(rejected) == 1
    assert rejected[0]["accession"] == "0000320193-26-000019"
    # the anchor is the SOURCE field, to the second — not filingDate
    r = [x for x in recs if x.ref_id == "0000320193-26-000018"][0]
    assert r.source_time_field == "acceptanceDateTime"
    assert r.source_time_utc == "2026-07-30T20:30:28+00:00"
    assert r.source == "sec_edgar" and r.symbol == "AAPL"
    # our clock is kept separate and never substituted for the source time
    assert r.retrieved_utc != r.source_time_utc


def test_edgar_form_filter_and_since():
    recs, _ = ev.fetch_edgar_filings("0000320193", forms=["10-Q"],
                                     session=_FakeSession(_Resp(payload=_EDGAR)))
    assert [r.extra["form"] for r in recs] == ["10-Q"]
    recs2, _ = ev.fetch_edgar_filings("0000320193", since="2026-07-31",
                                      session=_FakeSession(_Resp(payload=_EDGAR)))
    assert len(recs2) == 1 and recs2[0].extra["form"] == "10-Q"


_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Good item</title><link>http://x/1</link><guid>g1</guid>
      <pubDate>Sat, 08 Aug 2026 01:30:18 +0000</pubDate></item>
<item><title>No date item</title><link>http://x/2</link><guid>g2</guid></item>
<item><title>Naive date</title><link>http://x/3</link><guid>g3</guid>
      <pubDate>2026-08-08 01:30:18</pubDate></item>
</channel></rss>"""


def test_rss_uses_pubdate_and_rejects_missing_or_naive():
    recs, rejected = ev.fetch_rss("http://feed", source_label="test",
                                  session=_FakeSession(_Resp(content=_RSS)))
    assert len(recs) == 1, [r.title for r in recs]
    assert recs[0].source_time_utc == "2026-08-08T01:30:18+00:00"
    assert recs[0].source_time_field == "pubDate"
    assert recs[0].source == "rss:test"
    reasons = " ".join(r["reason"] for r in rejected)
    assert len(rejected) == 2
    assert "empty source timestamp" in reasons     # missing pubDate
    assert "no timezone" in reasons                # naive -> refuse to guess


@pytest.mark.parametrize("bad", ["", None, "not a date", "2026-08-08 01:30:18"])
def test_to_utc_iso_fail_closed(bad):
    with pytest.raises(ev.MissingSourceTimestamp):
        ev._to_utc_iso(bad, field="pubDate")


def test_validate_rejects_clock_skew():
    r = ev.EvidenceRecord(
        source="rss:test", source_time_utc="2026-08-08T01:00:00+00:00",
        source_time_field="pubDate", symbol=None, title="t", url="u", ref_id="g",
        # retrieved BEFORE published -> impossible, must be flagged
        retrieved_utc="2026-08-08T00:00:00+00:00")
    with pytest.raises(ValueError, match="clock skew"):
        ev.validate_records([r])


def test_frame_roundtrip_keeps_both_clocks(tmp_path):
    recs, _ = ev.fetch_edgar_filings("0000320193", symbol="AAPL",
                                     session=_FakeSession(_Resp(payload=_EDGAR)))
    df = ev.write_parquet(recs, tmp_path / "ev.parquet")
    back = pd.read_parquet(tmp_path / "ev.parquet")
    assert {"source_time_utc", "source_time_field", "retrieved_utc"} <= set(back.columns)
    assert back["source_time_utc"].notna().all()
    # sorted by source time, ascending
    assert list(back["source_time_utc"]) == sorted(back["source_time_utc"])

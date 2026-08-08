"""Tests for quotes_api — the paper mark-to-market price leg.

Offline (canned Alpha Vantage payloads). Pins the failure modes that matter:
the vendor's HTTP-200-but-throttled response must NOT look like success, and a
mark must never be printed from missing / carried-forward / stale prices.
"""
from __future__ import annotations

import pytest

from qlab.events.datafetch import quotes_api as q


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


class _FakeSession:
    """Serves a canned payload per symbol (from request params)."""

    def __init__(self, by_symbol):
        self.by_symbol = by_symbol
        self.calls = []

    def get(self, url, params=None, timeout=30):
        sym = (params or {}).get("symbol")
        self.calls.append(sym)
        return _Resp(self.by_symbol[sym])


def _series(rows):
    return {"Meta Data": {"2. Symbol": "X"},
            "Time Series (Daily)": {d: {"1. open": str(c), "2. high": str(c),
                                        "3. low": str(c), "4. close": str(c),
                                        "5. volume": "1000"} for d, c in rows}}


_THROTTLE = {"Information": ("Thank you for using Alpha Vantage! Please consider spreading out "
                             "your free API requests more sparingly (1 request per second)... "
                             "25 requests per day")}


def test_missing_key_fail_closed(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(q.MissingApiKey):
        q.fetch_daily("AAPL")


def test_throttle_raises_not_silent_success(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    s = _FakeSession({"AAPL": _THROTTLE})
    with pytest.raises(q.RateLimited, match="Information"):
        q.fetch_daily("AAPL", session=s)


def test_fetch_daily_keeps_source_dates(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    s = _FakeSession({"AAPL": _series([("2026-08-07", 313.33), ("2026-08-06", 310.0)])})
    bars = q.fetch_daily("AAPL", session=s)
    assert [b.date for b in bars] == ["2026-08-06", "2026-08-07"]   # sorted ascending
    assert bars[-1].close == 313.33
    # our clock is recorded separately and is never the price date
    assert bars[-1].retrieved_utc and bars[-1].retrieved_utc != bars[-1].date


def test_get_daily_closes_reports_failures_without_backfill(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    s = _FakeSession({"AAPL": _series([("2026-08-07", 313.33)]), "MSFT": _THROTTLE})
    bars, failed = q.get_daily_closes(["AAPL", "MSFT"], session=s, sleep=lambda *_: None)
    assert set(bars) == {"AAPL"}
    assert "MSFT" in failed and "RateLimited" in failed["MSFT"]


def test_get_daily_closes_paces_calls(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    s = _FakeSession({x: _series([("2026-08-07", 1.0)]) for x in ("A", "B", "C")})
    slept = []
    q.get_daily_closes(["A", "B", "C"], session=s, pace_seconds=1.2, sleep=slept.append)
    assert slept == [1.2, 1.2]        # paced between calls, not after the last


def test_trading_days_are_observed_not_predicted():
    bars = {"AAPL": [q.DailyBar("AAPL", "2026-08-06", 1.0), q.DailyBar("AAPL", "2026-08-07", 1.0)],
            "MSFT": [q.DailyBar("MSFT", "2026-08-07", 1.0)]}
    assert q.trading_days(bars) == ["2026-08-06", "2026-08-07"]


def test_mark_to_market_values_from_real_closes():
    bars = {"AAPL": [q.DailyBar("AAPL", "2026-08-07", 100.0)],
            "MSFT": [q.DailyBar("MSFT", "2026-08-07", 50.0)]}
    mk = q.mark_to_market({"AAPL": 2, "MSFT": 4}, bars)
    assert mk["as_of"] == "2026-08-07"
    assert mk["market_value"] == pytest.approx(2 * 100.0 + 4 * 50.0)
    assert mk["positions"]["AAPL"]["price_date"] == "2026-08-07"


def test_mark_to_market_refuses_missing_symbol():
    bars = {"AAPL": [q.DailyBar("AAPL", "2026-08-07", 100.0)]}
    with pytest.raises(q.StalePriceError, match="missing"):
        q.mark_to_market({"AAPL": 1, "NOPE": 1}, bars)


def test_mark_to_market_refuses_stale_price():
    # MSFT's newest bar is 30 days behind the as-of date -> refuse, don't carry forward
    bars = {"AAPL": [q.DailyBar("AAPL", "2026-08-07", 100.0)],
            "MSFT": [q.DailyBar("MSFT", "2026-07-01", 50.0)]}
    with pytest.raises(q.StalePriceError, match="stale"):
        q.mark_to_market({"AAPL": 1, "MSFT": 1}, bars, max_staleness_days=5)


def test_mark_to_market_no_bars_at_all():
    with pytest.raises(q.StalePriceError, match="no bars"):
        q.mark_to_market({"AAPL": 1}, {})


# --------------------------------------------------------------------------- #
# Daily quota guard integration (工部 08-08: 25/day must be accounted, not a comment)
# --------------------------------------------------------------------------- #
def _quota(tmp_path, cap=25, reserve=15):
    from qlab.events.datafetch import api_quota as aq
    return aq.DailyQuotaGuard(cap_per_day=cap, reserve_for_marking=reserve,
                              ledger_path=tmp_path / "quota.jsonl")


def test_guard_blocks_call_before_it_is_issued(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    g = _quota(tmp_path, cap=1, reserve=0)
    s = _FakeSession({"AAPL": _series([("2026-08-07", 1.0)]),
                      "MSFT": _series([("2026-08-07", 2.0)])})
    q.fetch_daily("AAPL", session=s, guard=g)
    assert s.calls == ["AAPL"] and g.used() == 1
    # budget exhausted -> the second request must NEVER leave the host
    with pytest.raises(q.QuotaExceeded):
        q.fetch_daily("MSFT", session=s, guard=g)
    assert s.calls == ["AAPL"], "call was issued despite exhausted budget"


def test_batch_checked_up_front_spends_nothing_when_short(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    g = _quota(tmp_path, cap=2, reserve=0)
    s = _FakeSession({x: _series([("2026-08-07", 1.0)]) for x in ("A", "B", "C")})
    with pytest.raises(q.QuotaExceeded):
        q.get_daily_closes(["A", "B", "C"], session=s, guard=g, sleep=lambda *_: None)
    # nothing burned on a mark that could not have completed anyway
    assert s.calls == [] and g.used() == 0


def test_quota_breach_propagates_not_buried_in_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    g = _quota(tmp_path, cap=1, reserve=0)
    s = _FakeSession({x: _series([("2026-08-07", 1.0)]) for x in ("A", "B")})
    # skip the up-front check to reach the mid-loop path
    with pytest.raises(q.QuotaExceeded):
        q.get_daily_closes(["A", "B"], session=s, guard=g,
                           require_full_batch=False, sleep=lambda *_: None)


def test_throttled_call_still_counts_against_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    g = _quota(tmp_path, cap=5, reserve=0)
    s = _FakeSession({"AAPL": _THROTTLE})
    with pytest.raises(q.RateLimited):
        q.fetch_daily("AAPL", session=s, guard=g)
    # the request left the host, so it must be accounted (conservative)
    assert g.used() == 1


def test_exploration_cannot_starve_the_daily_mark(monkeypatch, tmp_path):
    from qlab.events.datafetch.api_quota import EXPLORATION
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "K")
    g = _quota(tmp_path, cap=25, reserve=15)
    s = _FakeSession({f"X{i}": _series([("2026-08-07", 1.0)]) for i in range(11)})
    # burn the entire exploration sub-budget
    q.get_daily_closes([f"X{i}" for i in range(10)], session=s, guard=g,
                       purpose=EXPLORATION, sleep=lambda *_: None)
    with pytest.raises(q.QuotaExceeded):
        q.fetch_daily("X10", session=s, guard=g, purpose=EXPLORATION)
    # the 15-call marking reserve is intact
    assert g.remaining("marking") == 15


def test_throttle_message_redacts_the_api_key(monkeypatch):
    """AV echoes the key back in its quota notice — it must not survive into the
    exception, which may be logged or pasted into a status update."""
    fake_key = "FAKEKEY123456789"          # never the real key, even as fixture data
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", fake_key)
    leaky = {"Information": (f"We have detected your API key as {fake_key} and our "
                             "standard API rate limit is 25 requests per day.")}
    s = _FakeSession({"AAPL": leaky})
    with pytest.raises(q.RateLimited) as ei:
        q.fetch_daily("AAPL", session=s)
    msg = str(ei.value)
    assert fake_key not in msg, "API key leaked into the exception message"
    assert "<redacted-api-key>" in msg


def test_redaction_follows_the_current_key_after_rotation(monkeypatch):
    """_redact reads the key at call time, so a rotated key is covered with no
    code change. Locks the property that makes rotation safe whenever it happens."""
    for new_key in ("ROTATEDKEY1234567", "ANOTHERKEY9876543"):
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", new_key)
        msg = f"We have detected your API key as {new_key} and our rate limit is 25/day."
        out = q._redact(msg)
        assert new_key not in out
        assert "<redacted-api-key>" in out

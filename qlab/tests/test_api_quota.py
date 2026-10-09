"""Tests for api_quota — the accounted hard daily call budget.

Pins the three properties that make 25/day a real budget instead of a comment:
the check fires BEFORE the call, the count survives a restart (two runs on one
day share a counter), and the marking reservation cannot be eaten by
exploratory calls — so today's NAV point always fits.
"""
from __future__ import annotations

import pytest

from qlab.events.datafetch import api_quota as q
from qlab.events.datafetch.api_quota import EXPLORATION, MARKING


def _guard(tmp_path, cap=25, reserve=15):
    return q.DailyQuotaGuard(cap_per_day=cap, reserve_for_marking=reserve,
                             ledger_path=tmp_path / "quota.jsonl")


def test_spend_accounts_and_check_blocks_before_call(tmp_path):
    g = _guard(tmp_path, cap=3, reserve=0)
    for i in range(3):
        g.spend(purpose=MARKING, symbol=f"S{i}")
    assert g.used() == 3 and g.remaining(MARKING) == 0
    with pytest.raises(q.QuotaExceeded, match="only 0 left"):
        g.check(1, purpose=MARKING)


def test_counter_resumes_across_restart(tmp_path):
    g1 = _guard(tmp_path, cap=5, reserve=0)
    g1.spend(purpose=MARKING, symbol="AAPL")
    g1.spend(purpose=MARKING, symbol="MSFT")
    # a second process on the same day must CONTINUE the count, not restart at 0
    g2 = _guard(tmp_path, cap=5, reserve=0)
    assert g2.used() == 2 and g2.remaining(MARKING) == 3


def test_marking_reservation_is_ringfenced(tmp_path):
    # cap 25, reserve 15 -> exploration may use at most 10
    g = _guard(tmp_path, cap=25, reserve=15)
    assert g.exploration_cap == 10
    for i in range(10):
        g.spend(purpose=EXPLORATION, symbol=f"X{i}")
    assert g.remaining(EXPLORATION) == 0
    with pytest.raises(q.QuotaExceeded, match="exploration"):
        g.check(1, purpose=EXPLORATION)
    # ...but the marking reserve is untouched: a full 15-call mark still fits
    assert g.remaining(MARKING) == 15
    g.check(15, purpose=MARKING)


def test_marking_may_use_full_cap_when_unused(tmp_path):
    g = _guard(tmp_path, cap=25, reserve=15)
    g.check(25, purpose=MARKING)
    with pytest.raises(q.QuotaExceeded):
        g.check(26, purpose=MARKING)


def test_day_buckets_are_independent(tmp_path):
    g = _guard(tmp_path, cap=2, reserve=0)
    g.record(purpose=MARKING, symbol="A", day="2026-08-07")
    g.record(purpose=MARKING, symbol="B", day="2026-08-07")
    assert g.used(day="2026-08-07") == 2
    # yesterday's exhaustion must not spill into today
    assert g.used(day="2026-08-08") == 0
    g.check(2, purpose=MARKING, day="2026-08-08")
    with pytest.raises(q.QuotaExceeded):
        g.check(1, purpose=MARKING, day="2026-08-07")


def test_status_reports_both_budgets(tmp_path):
    g = _guard(tmp_path, cap=25, reserve=15)
    g.spend(purpose=MARKING, symbol="SPY")
    g.spend(purpose=EXPLORATION, symbol="NEW")
    s = g.status()
    assert s["cap_per_day"] == 25 and s["used_total"] == 2
    assert s["used_marking"] == 1 and s["used_exploration"] == 1
    assert s["remaining_total"] == 23 and s["remaining_exploration"] == 9


def test_reserve_cannot_exceed_cap(tmp_path):
    with pytest.raises(ValueError):
        q.DailyQuotaGuard(cap_per_day=5, reserve_for_marking=6,
                          ledger_path=tmp_path / "q.jsonl")


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("QLAB_AV_DAILY_CAP", "8")
    monkeypatch.setenv("QLAB_AV_MARK_RESERVE", "5")
    g = q.guard_from_env(tmp_path / "q.jsonl")
    assert g.cap_per_day == 8 and g.reserve_for_marking == 5
    assert g.exploration_cap == 3

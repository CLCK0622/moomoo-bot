"""Archive-window ageing stays honest when its observation clock cannot move."""
from __future__ import annotations

import json

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.archive_scanner import archive_scan_coverage
from qlab.llm_paper.bar_archive import archive_quote_snapshot


def _round() -> dict:
    return {"executor": "single_book", "portfolio_check": {"ok": True},
            "decisions": [
                {"symbol": "IBM", "target_weight": 0.1, "seed": 11,
                 "prompt_variant": "pv1_baseline",
                 "intended_start": "2026-08-10T13:30:00+00:00"},
                {"symbol": "CAT", "target_weight": 0.1, "seed": 11,
                 "prompt_variant": "pv1_baseline",
                 "intended_start": "2026-08-10T13:30:00+00:00"},
            ]}


def _bar(symbol: str, day: str) -> DailyBar:
    return DailyBar(symbol=symbol, date=day, open=100, high=101, low=99, close=100,
                    volume=10, retrieved_utc="2026-08-11T23:00:00+00:00")


def test_empty_archive_does_not_present_constant_100_as_a_live_clock(tmp_path):
    (tmp_path / "round_20260810.json").write_text(json.dumps(_round()), encoding="utf-8")

    coverage = archive_scan_coverage(str(tmp_path), as_of="2026-09-01")

    assert coverage["oldest_missing"]["remaining_trading_days"] == 100
    assert coverage["hard_alerts"] == []  # frozen alert basis is unchanged
    assert coverage["ageing_clock"] == {
        "basis": "archived_source_trade_dates_only",
        "status": "unanchored_empty_archive",
        "as_of": "2026-09-01",
        "observed_through": None,
        "calendar_lag_days_diagnostic_only": None,
        "unobserved_time_excluded": True,
        "hard_alert_semantics": "unchanged_observed_trading_days_le_20",
    }


def test_stopped_archive_exposes_lag_without_predicting_trading_days(tmp_path):
    (tmp_path / "round_20260810.json").write_text(json.dumps(_round()), encoding="utf-8")
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10"), _bar("IBM", "2026-08-11")],
         "CAT": [_bar("CAT", "2026-08-10")]},
        out_dir=str(tmp_path), stamp="20260811", executor="test")

    early = archive_scan_coverage(str(tmp_path), as_of="2026-08-12")
    late = archive_scan_coverage(str(tmp_path), as_of="2026-10-01")

    assert early["oldest_missing"] == late["oldest_missing"]
    assert late["ageing_clock"]["status"] == "lag_visible_observed_days_only"
    assert late["ageing_clock"]["observed_through"] == "2026-08-11"
    assert late["ageing_clock"]["calendar_lag_days_diagnostic_only"] == 51
    assert late["ageing_clock"]["unobserved_time_excluded"] is True
    assert late["hard_alerts"] == []  # no weekday/holiday guess silently changes the <=20 gate

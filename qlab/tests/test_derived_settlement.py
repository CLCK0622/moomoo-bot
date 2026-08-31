"""Derived lower-bound settlement consumes immutable decisions and archived bars."""
from __future__ import annotations

import json

import pytest

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.bar_archive import ArchiveIntegrityError, archive_quote_snapshot
from qlab.llm_paper.derived_settlement import (rebuild_lower_bound_settlement,
                                                write_lower_bound_settlement)


def _bar(symbol: str, day: str, close: float, open_: float | None = None) -> DailyBar:
    return DailyBar(symbol, day, close=close, open=(open_ if open_ is not None else close),
                    high=close + 1, low=close - 1, volume=10,
                    retrieved_utc="2026-08-12T12:00:00+00:00")


def _round() -> dict:
    return {"executor": "single_book", "portfolio_check": {"ok": True}, "nav_point": None,
            "decisions": [
                {"symbol": "IBM", "target_weight": 0.10, "seed": 11,
                 "prompt_variant": "pv1_baseline", "intended_start": "2026-08-10T13:30:00+00:00"},
                {"symbol": "CAT", "target_weight": 0.10, "seed": 11,
                 "prompt_variant": "pv1_baseline", "intended_start": "2026-08-10T13:30:00+00:00"},
            ]}


def _write_round(tmp_path):
    (tmp_path / "round_20260810.json").write_text(json.dumps(_round()), encoding="utf-8")


def _archive(tmp_path, *, ibm_close: float = 110.0):
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", ibm_close)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 105)]},
        out_dir=str(tmp_path), stamp="20260810", executor="single_book")


def test_backfills_every_round_from_decisions_not_round_nav_point(tmp_path):
    _write_round(tmp_path)
    _archive(tmp_path)
    result = write_lower_bound_settlement(str(tmp_path))
    cell = result["payload"]["rounds"][0]["cells"]["seed11×pv1_baseline"]
    assert result["n_rounds"] == 1
    assert cell["status"] == "filled"
    assert cell["entries"]["IBM"]["entry_open"] == 100.0
    assert cell["nav_series"][-1]["as_of"] == "2026-08-11"
    assert cell["nav_series"][-1]["nav"] > 100_000
    assert "nav_point" not in cell


def test_pre_archive_round_is_explicit_gap_not_retroactive_observation(tmp_path):
    _write_round(tmp_path)
    # This snapshot contains an old vendor bar, but the archive did not begin
    # until 09-07 and must not recast that price as an 08-10 observation.
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100)], "CAT": [_bar("CAT", "2026-08-10", 100)]},
        out_dir=str(tmp_path), stamp="20260907", executor="single_book")
    cell = rebuild_lower_bound_settlement(str(tmp_path))["rounds"][0]["cells"]["seed11×pv1_baseline"]
    assert cell["status"] == "pending_archived_entry_bar"
    assert cell["capture_floor"] == "2026-09-07"


def test_unresolved_consumed_window_refuses_to_emit_settlement_reading(tmp_path):
    _write_round(tmp_path)
    _archive(tmp_path)
    # A second snapshot revises a bar that this settlement's NAV window uses.
    archive_quote_snapshot(
        {"IBM": [_bar("IBM", "2026-08-10", 100), _bar("IBM", "2026-08-11", 90)],
         "CAT": [_bar("CAT", "2026-08-10", 100), _bar("CAT", "2026-08-11", 105)]},
        out_dir=str(tmp_path), stamp="20260817", executor="single_book",
        retrieved_utc="2026-08-17T12:00:00+00:00")
    with pytest.raises(ArchiveIntegrityError, match="派生结算不得出"):
        rebuild_lower_bound_settlement(str(tmp_path))

"""Post-round derived equivalence must compare real readings, never pending emptiness."""
from __future__ import annotations

import json

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.bar_archive import archive_quote_snapshot
from qlab.llm_paper.decision_chain import load_prereg
from qlab.llm_paper.derived_equivalence import rebuild_derived_equivalence
from qlab.llm_paper.ledger_bridge import cell_id


STAMP = "20260831"
DTS = "2026-08-31T11:04:36.601931+00:00"
START = "2026-08-31T13:30:00+00:00"


def _decision(symbol: str, weight: float, seed: int, variant: str) -> dict:
    return {
        "symbol": symbol,
        "target_weight": weight,
        "seed": seed,
        "prompt_variant": variant,
        "evidence_available_utc": "2026-08-28T20:00:00+00:00",
        "decision_ts": DTS,
        "intended_start": START,
    }


def _write_rounds(tmp_path) -> None:
    prereg = load_prereg()
    preflight = {"anchor_ok": True, "prereg_frozen_at": "2026-08-08T02:10:26Z"}
    bearing_decisions = [_decision("IBM", 0.10, 11, "pv1_baseline"),
                         _decision("CAT", 0.08, 11, "pv1_baseline")]
    bearing = {
        "round_decision_ts": DTS,
        "executor": "single_book",
        "preflight": preflight,
        "portfolio_check": {"ok": True},
        "decisions": bearing_decisions,
        "ledger": {"n_trials_total": 10, "n_evaluated": 1},
    }
    cells = {}
    for seed in prereg["family"]["seeds"]:
        for variant in prereg["family"]["prompt_variants"]:
            cid = cell_id(seed, variant)
            cells[cid] = {
                "portfolio_check": {"ok": True},
                "decisions": [_decision("IBM", 0.10, seed, variant),
                              _decision("CAT", 0.08, seed, variant)],
            }
    control = {
        "round_decision_ts": DTS,
        "executor": "multi_book_v1",
        "preflight": preflight,
        "cells": cells,
        "cells_missing": [],
        "bars_injected": True,
        "seed_semantics": {"temperature": 0.0},
    }
    report = {
        "shared_quote_snapshot": {"symbols": ["CAT", "IBM", "SPY"], "n_calls": 3},
        "control_quote_calls": 0,
        "control_registered_trials": False,
        "control_error": None,
    }
    control_dir = tmp_path / "control_multi_book"
    control_dir.mkdir()
    (tmp_path / f"round_{STAMP}.json").write_text(json.dumps(bearing), encoding="utf-8")
    (control_dir / f"round_{STAMP}.json").write_text(json.dumps(control), encoding="utf-8")
    (tmp_path / f"CONTROL_{STAMP}.json").write_text(json.dumps(report), encoding="utf-8")


def _archive(tmp_path, *, revised_volume: float | None = None) -> None:
    bars = {symbol: [DailyBar(symbol, "2026-08-31", close=101.0, open=100.0,
                              high=102.0, low=99.0, volume=(revised_volume or 10.0),
                              retrieved_utc="2026-09-01T12:00:00+00:00")]
            for symbol in ("IBM", "CAT")}
    archive_quote_snapshot(bars, out_dir=str(tmp_path), stamp="20260831",
                           executor="parallel_control")


def test_filled_overlap_can_pass_while_nonoverlap_cells_stay_explicit(tmp_path):
    _write_rounds(tmp_path)
    _archive(tmp_path)
    result = rebuild_derived_equivalence(
        str(tmp_path), stamp=STAMP, evidence_commit="abc",
        freeze_is_ancestor=True, records_unchanged=True)
    assert result["reading_kind"] == "equivalence_artifact"
    assert result["decision_capture_promotion"]["eligible"] is True
    assert result["summary"]["overlap_book_nav_equivalence_passed"] is True
    assert result["summary"]["may_take_over"] is True
    assert result["per_grid"]["seed11×pv1_baseline"]["comparison"]["passed"] is True
    target = result["derived_settlements"]["control"]["rounds"][-1]
    assert target["cells"]["seed11×pv1_baseline"]["reading_kind"] == "equivalence_artifact"
    assert target["cells"]["seed11×pv1_baseline"]["is_performance_reading"] is False
    assert result["per_grid"]["seed11×pv2_riskaware"]["comparison"]["status"] == \
        "not_comparable_no_bearing_cell"
    assert result["seed_semantics"]["effective_distinct_decision_sets"] == 2
    assert result["seed_semantics"]["must_not_claim_seed_robustness"] is True


def test_equivalence_carries_common_history_into_target_book(tmp_path):
    _write_rounds(tmp_path)
    target = json.loads((tmp_path / f"round_{STAMP}.json").read_text(encoding="utf-8"))
    prior = dict(target)
    prior["round_decision_ts"] = "2026-08-24T11:00:00+00:00"
    prior["decisions"] = [dict(decision,
                               decision_ts="2026-08-24T11:00:00+00:00",
                               intended_start="2026-08-24T13:30:00+00:00")
                          for decision in target["decisions"]]
    (tmp_path / "round_20260824.json").write_text(json.dumps(prior), encoding="utf-8")
    archive_quote_snapshot(
        {symbol: [DailyBar(symbol, "2026-08-24", close=110.0, open=100.0,
                           high=111.0, low=99.0, volume=10.0,
                           retrieved_utc="2026-08-25T12:00:00+00:00"),
                  DailyBar(symbol, "2026-08-31", close=121.0, open=120.0,
                           high=122.0, low=119.0, volume=10.0,
                           retrieved_utc="2026-09-01T12:00:00+00:00")]
         for symbol in ("IBM", "CAT")},
        out_dir=str(tmp_path), stamp="20260824", executor="parallel_control")

    result = rebuild_derived_equivalence(
        str(tmp_path), stamp=STAMP, evidence_commit="abc",
        freeze_is_ancestor=True, records_unchanged=True)
    bearing_rounds = result["derived_settlements"]["bearing"]["rounds"]
    control_rounds = result["derived_settlements"]["control"]["rounds"]
    a_target = next(item for item in bearing_rounds if item["round"] == STAMP)
    b_target = next(item for item in control_rounds if item["round"] == STAMP)
    cid = "seed11×pv1_baseline"
    assert a_target["cells"][cid]["nav_start"] != 100_000.0
    assert a_target["cells"][cid]["old_notionals_at_rebalance"]
    assert a_target["cells"][cid] == b_target["cells"][cid]
    assert result["summary"]["may_take_over"] is True


def test_pending_integrity_on_both_sides_is_not_equivalence(tmp_path):
    _write_rounds(tmp_path)
    _archive(tmp_path)
    _archive(tmp_path, revised_volume=11.0)
    result = rebuild_derived_equivalence(
        str(tmp_path), stamp=STAMP, evidence_commit="abc",
        freeze_is_ancestor=True, records_unchanged=True)
    overlap = result["per_grid"]["seed11×pv1_baseline"]
    assert overlap["bearing_settlement_status"] == "pending_archive_integrity"
    assert overlap["control_settlement_status"] == "pending_archive_integrity"
    assert overlap["comparison"]["status"] == "blocked_pending_reading"
    assert overlap["comparison"]["passed"] is False
    assert result["decision_capture_promotion"]["eligible"] is True
    assert result["summary"]["may_take_over"] is False

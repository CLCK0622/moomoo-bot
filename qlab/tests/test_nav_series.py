"""权威派生净值与降级轮内快照的边界。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qlab.llm_paper.nav_series import (cell_nav_series, coverage, cumulative_returns,
                                       load_rounds, round_record_nav_series)

REPORTS = Path(__file__).resolve().parents[1] / "reports" / "llm_paper"


def _single(nav=None, seed=11, variant="pv1_baseline", status="filled"):
    p = {"executor": "single_book", "book": {"status": status},
         "decisions": [{"seed": seed, "prompt_variant": variant, "symbol": "IBM",
                        "target_weight": 0.1, "intended_start": "2026-08-10T13:30:00+00:00"}]}
    if nav is not None:
        p["nav_point"] = {"as_of": "2026-08-14", "nav": nav, "nav_x2_cost": nav - 10.0,
                          "nav_start": 100_000.0}
    return p


def _multi(navs, as_of="2026-08-31"):
    return {"executor": "multi_book_v1", "cells": {
        f"seed{s}×{v}": {"seed": s, "prompt_variant": v, "book": {"status": "filled"},
                         "decisions": [{"seed": s, "prompt_variant": v, "symbol": "IBM",
                                        "target_weight": 0.1,
                                        "intended_start": "2026-08-10T13:30:00+00:00"}],
                         "nav_point": {"as_of": as_of, "nav": nav, "nav_x2_cost": nav - 10.0,
                                       "nav_start": 100_000.0}}
        for (s, v), nav in navs.items()}}


def _write(d, name, payload):
    (d / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_round_record_series_spans_the_executor_switch_for_audit_only(tmp_path):
    """轮内快照仍可审计执行器切换，但名字与权威结算序列不再相同。"""
    _write(tmp_path, "round_20260810.json", _single(nav=None, status="pending_entry_bar"))
    _write(tmp_path, "round_20260817.json", _single(nav=101_000.0))
    _write(tmp_path, "round_20260831.json", _multi(
        {(s, v): 102_000.0 + s for s in (11, 22) for v in ("pv1_baseline", "pv2_riskaware")}))

    s = round_record_nav_series(str(tmp_path))
    assert [p["round"] for p in s["seed11×pv1_baseline"]] == ["20260817", "20260831"]
    assert [p["executor"] for p in s["seed11×pv1_baseline"]] == ["single_book", "multi_book_v1"]
    assert len(s["seed22×pv2_riskaware"]) == 1                 # (b) 起才有读数
    assert "20260810" not in {p["round"] for pts in s.values() for p in pts}   # 无仓位不编点

    cov = coverage(str(tmp_path))
    assert cov["executor_switch_rounds"] == [{"round": "20260831", "to": "multi_book_v1"}]
    assert cov["per_round"][0]["n_round_record_nav_points"] == 0
    assert cov["per_round"][2]["n_cells"] == 4


def test_pending_round_contributes_no_point(tmp_path):
    """建仓 bar 未出现的轮次没有净值点 —— 序列里就不该有那一天，不补「持平」。"""
    _write(tmp_path, "round_20260810.json", _single(nav=None, status="pending_entry_bar"))
    assert cell_nav_series(str(tmp_path)) == {}
    assert cumulative_returns(str(tmp_path)) == {}


def test_round_record_nav_cannot_become_authoritative_or_x2_fallback(tmp_path):
    _write(tmp_path, "round_20260831.json", _multi({(11, "pv1_baseline"): 110_000.0,
                                                    (11, "pv2_riskaware"): 95_000.0}))
    assert cell_nav_series(str(tmp_path)) == {}
    assert cumulative_returns(str(tmp_path)) == {}
    with pytest.raises(ValueError, match="不得拿轮内"):
        cumulative_returns(str(tmp_path), cost_track="x2")


def test_ambiguous_single_book_round_is_refused(tmp_path):
    """单 book 轮里出现多格 ⇒ 那一个 nav_point 归属不明，宁可抛也不猜。"""
    p = _single(nav=101_000.0)
    p["decisions"].append({"seed": 22, "prompt_variant": "pv2_riskaware"})
    _write(tmp_path, "round_20260817.json", p)
    with pytest.raises(ValueError, match="归属不明"):
        round_record_nav_series(str(tmp_path))


def test_broken_round_file_is_not_silently_skipped(tmp_path):
    _write(tmp_path, "round_20260817.json", _single(nav=101_000.0))
    (tmp_path / "round_20260824.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="无法解析"):
        load_rounds(str(tmp_path))


def test_reads_the_real_round_one_record():
    """真记录的轮内快照仍为空；归档到位后派生下界序列独立出现。"""
    rounds = load_rounds(str(REPORTS))
    assert any(r["_file"] == "round_20260810.json" for r in rounds)
    cov = coverage(str(REPORTS))
    r1 = next(r for r in cov["per_round"] if r["round"] == "20260810")
    assert r1["executor"] == "single_book"           # 第 1 轮记录早于 executor 字段 → 归 single_book
    assert r1["cells"] == ["seed11×pv1_baseline"] and r1["n_round_record_nav_points"] == 0
    assert round_record_nav_series(str(REPORTS)).get("seed11×pv1_baseline") is None
    derived = cell_nav_series(str(REPORTS))["seed11×pv1_baseline"]
    first_segment = [point for point in derived if point["round"] == "20260810"]
    expected = [
        ("2026-08-10", 100329.81075525786), ("2026-08-11", 100857.24557132414),
        ("2026-08-12", 101156.64594464214), ("2026-08-13", 101262.26702625533),
        ("2026-08-14", 101439.93568183083), ("2026-08-17", 101492.75549050017),
        ("2026-08-18", 101220.89426595987), ("2026-08-19", 101857.94499388215),
        ("2026-08-20", 101385.16684711102), ("2026-08-21", 101940.61723480515),
        ("2026-08-24", 101809.96088327904), ("2026-08-25", 101767.07161679748),
        ("2026-08-26", 101939.74883549285), ("2026-08-27", 101607.73470220654),
        ("2026-08-28", 101206.44232755358),
    ]
    assert [point["as_of"] for point in first_segment] == [item[0] for item in expected]
    assert [point["nav"] for point in first_segment] == pytest.approx(
        [item[1] for item in expected])
    assert len(first_segment) == 15
    assert first_segment[0]["as_of"] == "2026-08-10"
    assert first_segment[-1]["as_of"] == "2026-08-28"
    assert all(point["reading_kind"] == "lower_bound" for point in first_segment)
    assert all(point["book_status"] == "filled" for point in first_segment)
    assert all(point["bar_provenance"]["scope"] == "entire_nav_segment"
               and point["bar_provenance"]["not_cross_checked"] is True
               and point["bar_provenance"]["acceptance_eligible"] is False
               and point["bar_provenance"]["must_not_promote_to_acceptance"] is True
               for point in first_segment)
    reading = cumulative_returns(str(REPORTS))["seed11×pv1_baseline"]
    later_segments = [point for point in derived if point["round"] != "20260810"]
    if reading["status"] == "complete":
        # A later valid segment may lawfully appear.  The fixed first-segment
        # evidence remains intact, while the cumulative reading must advance
        # beyond that segment and retain the original pre-entry base.
        assert later_segments
        assert reading["nav_start"] == 100_000.0
        assert reading["nav_end"] == later_segments[-1]["nav"]
    else:
        # Any pending/incomplete continuation must suppress the old 08-10-only
        # performance number without pinning today's producer status or exact
        # blocker list, both of which legitimately evolve as evidence arrives.
        assert reading["cumulative_return"] is None
        assert "nav_end" not in reading and "as_of" not in reading
        assert reading.get("blockers")
        assert all(blocker.get("status") != "filled"
                   for blocker in reading["blockers"] if "status" in blocker)

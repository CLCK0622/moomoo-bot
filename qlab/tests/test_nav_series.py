"""每格净值序列：从不可改的 round JSON 机械拼出，(a)/(b) 两种落盘格式都认。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qlab.llm_paper.nav_series import (cell_nav_series, coverage, cumulative_returns,
                                       load_rounds)

REPORTS = Path(__file__).resolve().parents[1] / "reports" / "llm_paper"


def _single(nav=None, seed=11, variant="pv1_baseline", status="filled"):
    p = {"executor": "single_book", "book": {"status": status},
         "decisions": [{"seed": seed, "prompt_variant": variant}]}
    if nav is not None:
        p["nav_point"] = {"as_of": "2026-08-14", "nav": nav, "nav_x2_cost": nav - 10.0,
                          "nav_start": 100_000.0}
    return p


def _multi(navs, as_of="2026-08-31"):
    return {"executor": "multi_book_v1", "cells": {
        f"seed{s}×{v}": {"seed": s, "prompt_variant": v, "book": {"status": "filled"},
                         "nav_point": {"as_of": as_of, "nav": nav, "nav_x2_cost": nav - 10.0,
                                       "nav_start": 100_000.0}}
        for (s, v), nav in navs.items()}}


def _write(d, name, payload):
    (d / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_series_spans_the_executor_switch(tmp_path):
    """(a) 那几轮只喂 1 格，(b) 接管后 10 格全有 —— 同一条序列必须接得上。"""
    _write(tmp_path, "round_20260810.json", _single(nav=None, status="pending_entry_bar"))
    _write(tmp_path, "round_20260817.json", _single(nav=101_000.0))
    _write(tmp_path, "round_20260831.json", _multi(
        {(s, v): 102_000.0 + s for s in (11, 22) for v in ("pv1_baseline", "pv2_riskaware")}))

    s = cell_nav_series(str(tmp_path))
    assert [p["round"] for p in s["seed11×pv1_baseline"]] == ["20260817", "20260831"]
    assert [p["executor"] for p in s["seed11×pv1_baseline"]] == ["single_book", "multi_book_v1"]
    assert len(s["seed22×pv2_riskaware"]) == 1                 # (b) 起才有读数
    assert "20260810" not in {p["round"] for pts in s.values() for p in pts}   # 无仓位不编点

    cov = coverage(str(tmp_path))
    assert cov["executor_switch_rounds"] == [{"round": "20260831", "to": "multi_book_v1"}]
    assert cov["per_round"][0]["n_nav_points"] == 0 and cov["per_round"][2]["n_cells"] == 4


def test_pending_round_contributes_no_point(tmp_path):
    """建仓 bar 未出现的轮次没有净值点 —— 序列里就不该有那一天，不补「持平」。"""
    _write(tmp_path, "round_20260810.json", _single(nav=None, status="pending_entry_bar"))
    assert cell_nav_series(str(tmp_path)) == {}
    assert cumulative_returns(str(tmp_path)) == {}


def test_cumulative_returns_are_per_cell_and_two_track(tmp_path):
    _write(tmp_path, "round_20260831.json", _multi({(11, "pv1_baseline"): 110_000.0,
                                                    (11, "pv2_riskaware"): 95_000.0}))
    x1 = cumulative_returns(str(tmp_path))
    assert x1["seed11×pv1_baseline"] == pytest.approx(0.10)
    assert x1["seed11×pv2_riskaware"] == pytest.approx(-0.05)
    x2 = cumulative_returns(str(tmp_path), cost_track="x2")
    assert x2["seed11×pv1_baseline"] == pytest.approx((110_000.0 - 10.0) / 100_000.0 - 1)


def test_ambiguous_single_book_round_is_refused(tmp_path):
    """单 book 轮里出现多格 ⇒ 那一个 nav_point 归属不明，宁可抛也不猜。"""
    p = _single(nav=101_000.0)
    p["decisions"].append({"seed": 22, "prompt_variant": "pv2_riskaware"})
    _write(tmp_path, "round_20260817.json", p)
    with pytest.raises(ValueError, match="归属不明"):
        cell_nav_series(str(tmp_path))


def test_broken_round_file_is_not_silently_skipped(tmp_path):
    _write(tmp_path, "round_20260817.json", _single(nav=101_000.0))
    (tmp_path / "round_20260824.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="无法解析"):
        load_rounds(str(tmp_path))


def test_reads_the_real_round_one_record():
    """对着仓内真记录跑一遍：第 1 轮如期无净值点，序列因此为空（而不是报错或编点）。"""
    rounds = load_rounds(str(REPORTS))
    assert any(r["_file"] == "round_20260810.json" for r in rounds)
    cov = coverage(str(REPORTS))
    r1 = next(r for r in cov["per_round"] if r["round"] == "20260810")
    assert r1["executor"] == "single_book"           # 第 1 轮记录早于 executor 字段 → 归 single_book
    assert r1["cells"] == ["seed11×pv1_baseline"] and r1["n_nav_points"] == 0
    assert cell_nav_series(str(REPORTS)).get("seed11×pv1_baseline") is None

"""台账登记桥接：**第 2 轮起不得被重冻护栏打死**，且 n_trials_total 一格不少登。

原内联写法（`register_run(run_id="llm_paper-<日期>", candidate_id="llm_paper")` 不带 supersedes）
在第 2 轮必然 `RefreezeError`，抛错点在配额已花、决策已产生、round JSON 尚未落盘之处 ⇒ 该轮证据
当场归零。下面第一条测试把那个失败形态钉死，防止将来有人把桥接改回内联。
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from qlab.llm_paper.decision_chain import load_prereg
from qlab.llm_paper.ledger_bridge import (LedgerBridgeError, cells_in_payload,
                                          evaluated_cells_union, register_round, round_id)

CFG = load_prereg()


def _reg(tmp_path, ts, cells, *, out_dir=None, executor="single_book"):
    return register_round(decision_ts=ts, cfg=CFG, cells_this_round=cells,
                          out_dir=str(out_dir or tmp_path / "reports"),
                          executor=executor, ledger_path=str(tmp_path / "led.jsonl"))


def test_raw_register_run_would_break_round_two(tmp_path):
    """被修掉的那个形态本身：同 candidate 换 run_id 不声明 supersedes → 第 2 轮直接抛。"""
    from research.gate import project_ledger
    from research.gate.trial_ledger import RefreezeError
    led = project_ledger(str(tmp_path / "raw.jsonl"))
    led.register_run(run_id="llm_paper-2026-08-10", source="llm_agent", n_trials_total=10,
                     n_evaluated=1, candidate_id="llm_paper", note="r1")
    with pytest.raises(RefreezeError):
        led.register_run(run_id="llm_paper-2026-08-31", source="llm_agent", n_trials_total=10,
                         n_evaluated=1, candidate_id="llm_paper", note="r2")


def test_bridge_carries_the_candidate_across_rounds_counting_once(tmp_path):
    """跨轮登记：恒定一条记录、run_id 跟到最新一轮、N 计一次仍为 10。"""
    from research.gate import project_ledger
    r1 = _reg(tmp_path, pd.Timestamp("2026-08-10T11:00Z"), {(11, "pv1_baseline")})
    assert r1["run_id"] == "llm_paper-2026-08-10" and r1["supersedes"] is None
    assert r1["n_trials_total"] == 10 and r1["n_evaluated"] == 1

    r2 = _reg(tmp_path, pd.Timestamp("2026-08-31T02:00Z"), {(11, "pv1_baseline")})
    assert r2["run_id"] == "llm_paper-2026-08-31"
    assert r2["supersedes"] == "llm_paper-2026-08-10"        # 覆盖计一次，不追加
    led = project_ledger(str(tmp_path / "led.jsonl"))
    assert [r.run_id for r in led.runs] == ["llm_paper-2026-08-31"]
    assert led.cumulative_n() == 10                          # N 没有每周 +10


def test_n_trials_total_stays_full_grid_even_when_one_cell_evaluated(tmp_path):
    """少登即 REJECTED_honesty：n_evaluated 可以是 1，n_trials_total 必须是冻结的 10。"""
    r = _reg(tmp_path, pd.Timestamp("2026-08-31T02:00Z"), {(11, "pv1_baseline")})
    assert r["n_trials_total"] == 10 and r["n_evaluated"] == 1
    assert r["cells_this_round"] == ["seed11×pv1_baseline"]


def test_n_evaluated_is_union_across_rounds(tmp_path):
    """(a) 长期 1 格、(b) 接管后 10 格 —— n_evaluated 取跨轮并集，从不可改的 round JSON 读出。"""
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "round_20260810.json").write_text(json.dumps(
        {"decisions": [{"seed": 11, "prompt_variant": "pv1_baseline"}]}), encoding="utf-8")
    r = _reg(tmp_path, pd.Timestamp("2026-08-31T02:00Z"),
             {(s, v) for s in (11, 22, 33, 44, 55) for v in ("pv1_baseline", "pv2_riskaware")},
             out_dir=reports, executor="multi_book_v1")
    assert r["n_evaluated"] == 10 and r["executor"] == "multi_book_v1"


def test_cells_read_from_both_round_formats(tmp_path):
    assert cells_in_payload({"decisions": [{"seed": 11, "prompt_variant": "pv1_baseline"}]}) == {
        (11, "pv1_baseline")}
    assert cells_in_payload({"cells": {"seed22×pv2_riskaware":
                                       {"seed": 22, "prompt_variant": "pv2_riskaware"}}}) == {
        (22, "pv2_riskaware")}
    assert cells_in_payload({}) == set()


def test_unreadable_history_is_reported_not_swallowed(tmp_path):
    """坏历史文件会让并集偏小（n_evaluated 偏小 = 朝严一侧），但必须说出来，不静默。"""
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "round_20260810.json").write_text("{not json", encoding="utf-8")
    r = _reg(tmp_path, pd.Timestamp("2026-08-31T02:00Z"), {(11, "pv1_baseline")},
             out_dir=reports)
    assert r["unreadable_round_files"] == ["round_20260810.json"]
    assert evaluated_cells_union(str(reports), {(11, "pv1_baseline")}) == {(11, "pv1_baseline")}


def test_same_day_second_registration_is_flagged_not_silent(tmp_path):
    """同日二次登记（如并行对照轮误开 register_trials）：幂等返回旧记录 ⇒ 必须带警示字段。"""
    reports = tmp_path / "reports"
    reports.mkdir()
    ts = pd.Timestamp("2026-08-31T02:00Z")
    _reg(tmp_path, ts, {(11, "pv1_baseline")}, out_dir=reports)
    r2 = _reg(tmp_path, ts,
              {(s, v) for s in (11, 22, 33, 44, 55) for v in ("pv1_baseline", "pv2_riskaware")},
              out_dir=reports, executor="multi_book_v1")
    assert r2["ledger_reused_existing_record"] is True
    assert r2["n_evaluated"] == 1 and r2["n_evaluated_computed_this_round"] == 10
    assert "register_trials=False" in r2["warning"]


def test_more_cells_than_frozen_grid_is_refused(tmp_path):
    with pytest.raises(LedgerBridgeError, match="超过冻结网格"):
        _reg(tmp_path, pd.Timestamp("2026-08-31T02:00Z"),
             {(s, v) for s in (11, 22, 33, 44, 55)
              for v in ("pv1_baseline", "pv2_riskaware")} | {(66, "pv1_baseline")})


def test_multiple_prior_records_refuse_to_guess(tmp_path):
    """候选已有多条记录 = 此前已重复计数；桥接不替人决定覆盖哪一条。"""
    from research.gate import project_ledger
    led = project_ledger(str(tmp_path / "led.jsonl"))
    led.register_run(run_id="llm_paper-2026-08-10", source="llm_agent", n_trials_total=10,
                     n_evaluated=1, candidate_id="llm_paper", note="r1")
    led.runs.append(type(led.runs[0])(**{**led.runs[0].__dict__, "run_id": "llm_paper-dup"}))
    led._save()
    with pytest.raises(LedgerBridgeError, match="多条台账记录"):
        _reg(tmp_path, pd.Timestamp("2026-08-31T02:00Z"), {(11, "pv1_baseline")})


def test_round_id_matches_round_one_naming():
    assert round_id(pd.Timestamp("2026-08-10T11:10:44Z")) == "llm_paper-2026-08-10"

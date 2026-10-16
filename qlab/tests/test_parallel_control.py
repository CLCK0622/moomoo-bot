"""(a)/(b) 并行对照：一次取行情、同一份 bars 喂两条路径，逐位比 book。

按工部尚书 2026-08-27 派单的四条覆盖：
1. **共用快照**：整轮只取一次行情，(a)/(b) 不得各取一遍（对照有效性，不是配额）；
2. **逐位比对**：`shares/entries/gross/cash/nav_point` 全比，任一处不同必须报出来；
3. **不一致就停下**：`may_take_over=False` + 独立 ALERT 落盘，且**不自动切换**；
4. **对照不许伤到承载路径**：(b) 无论怎么炸，(a) 的 round JSON 与台账登记都已完成且完好。
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from qlab.llm_paper.errors import PreflightFailed
from qlab.llm_paper.multi_book import cell_id
from qlab.llm_paper.parallel_control import (CONTROL_SUBDIR, compare_books,
                                             run_parallel_control)

PROBE = {"model": "test-model", "output": '{"a":1}'}
EV = [{"source_time_utc": pd.Timestamp("2026-08-07 10:00", tz="America/New_York")
       .tz_convert("UTC").isoformat(), "ref_id": "r"}]
DTS = pd.Timestamp("2026-08-07 11:00", tz="America/New_York")   # 周五盘中 → intended = 8/10 开盘
CELL = (11, "pv1_baseline")


def _prop(sym, w, **extra):
    return dict({"symbol": sym, "target_weight": w, "confidence": 0.5, "thesis": "t",
                 "evidence_records": EV}, **extra)


def _pa(sym, w):
    """(a) 侧提案带 seed/变体（(a) 的每条决策自带格子标识）。"""
    return _prop(sym, w, seed=CELL[0], prompt_variant=CELL[1])


def _iso(tmp_path, monkeypatch, *, with_baseline=True):
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    bl = tmp_path / "b.json"
    monkeypatch.setenv("QLAB_LLM_DETERMINISM_BASELINE", str(bl))
    if with_baseline:
        from qlab.llm_paper.determinism import record_baseline
        record_baseline(output=PROBE["output"], model=PROBE["model"], round_id="pretest")
    return bl


def _stub_bars(monkeypatch, days, *, price=100.0, calls=None):
    from qlab.events.datafetch.quotes_api import DailyBar
    import qlab.llm_paper.quote_bridge as QB

    def fake(symbols, **kw):
        syms = sorted(symbols)
        if calls is not None:
            calls.append(syms)
        return ({s: [DailyBar(symbol=s, date=d, close=price, open=price * 0.99) for d in days]
                 for s in syms}, {})
    monkeypatch.setattr(QB, "get_daily_closes", fake)


def _no_ledger(tmp_path, monkeypatch):
    """台账隔离：承载侧真的会登记，别写到仓内真台账上。"""
    monkeypatch.setattr("research.gate.DEFAULT_LEDGER_PATH", str(tmp_path / "led.jsonl"))
    monkeypatch.setattr("qlab.llm_paper.ledger_bridge._REPO_ROOT", tmp_path)


def _run(tmp_path, monkeypatch, *, a_props, b_cells, register_trials=False, **kw):
    return run_parallel_control(proposals=a_props, cells=b_cells, decision_ts=DTS,
                                probe=PROBE, out_dir=str(tmp_path / "bearing"),
                                register_trials=register_trials, **kw)


# --------------------------------------------------------------------------- #
# 1. 共用快照 + 逐位相同
# --------------------------------------------------------------------------- #
def test_one_snapshot_feeds_both_paths_and_books_match(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    calls = []
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"], calls=calls)
    props = [_pa("IBM", 0.10), _pa("MRK", 0.06)]
    r = _run(tmp_path, monkeypatch, a_props=props,
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10), _prop("MRK", 0.06)]}])

    assert len(calls) == 1                                   # **整轮只取一次行情**
    assert calls[0] == ["IBM", "MRK", "SPY"]
    assert r["control_quote_calls"] == 0                     # 对照侧零调用（用注入快照）
    assert r["shared_quote_snapshot"]["n_calls"] == 3

    assert r["identical"] is True and r["may_take_over"] is True
    assert r["book_comparison"]["identical"] and r["book_comparison"]["book_status"] == "filled"
    assert r["decision_set_comparison"]["identical"]
    assert r["compared_cell"] == cell_id(*CELL)
    assert r["verdict"] is None                              # 对照不出 verdict

    bearing = tmp_path / "bearing"
    assert (bearing / "round_20260807.json").exists()                    # 承载记录
    assert (bearing / CONTROL_SUBDIR / "round_20260807.json").exists()   # 对照记录，另一目录
    assert not list(bearing.glob("ALERT_control_mismatch_*.json"))
    saved = json.loads((bearing / "CONTROL_20260807.json").read_text(encoding="utf-8"))
    assert saved["may_take_over"] is True and "bearing_payload" not in saved


def test_a_violating_round_still_compares_and_still_lands(tmp_path, monkeypatch):
    """两侧同样违规 ⇒ 两侧同样不调仓、逐位仍相同，轮次照常落盘（吏部 2026-08-27 裁定）。"""
    from qlab.llm_paper.rebalance_policy import NO_REBALANCE
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    over = [_pa("IBM", 0.06), _pa("IBM", 0.06)]              # 聚合 0.12 > 冻结 0.10
    r = _run(tmp_path, monkeypatch, a_props=over,
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.06), _prop("IBM", 0.06)]}])
    assert r["identical"] is True
    assert r["book_comparison"]["book_status"] == NO_REBALANCE
    assert (tmp_path / "bearing" / "round_20260807.json").exists()      # 轮次没丢
    assert r["bearing_payload"]["book"]["violation"]["exceeded_by"]["IBM"] == pytest.approx(0.02)
    # 但两侧都是空持仓 ⇒ book 等价性**没被检验到**，不得据此切换
    assert r["book_equivalence_exercised"] is False and r["may_take_over"] is False


@pytest.mark.parametrize("days, status", [
    (["2026-08-06", "2026-08-07"], "pending_entry_bar"),      # 建仓 bar 未出现
])
def test_empty_book_identity_is_not_a_pass(days, status, tmp_path, monkeypatch):
    """空 book 上的「逐位相同」是**空过**：两侧都没持仓，权重→股数那段算术一行没跑。

    08-31 那轮就是这个形态（决策 11:00Z 盘前，intended_start 当天 13:30Z，价格腿最新 bar
    停在上周五）—— 若把空过读成通过，切换就会建立在从未检验过的等价性上。
    """
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, days)
    r = _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10)]}])
    assert r["book_comparison"]["book_status"] == status
    assert r["identical"] is True                       # 确实逐位相同……
    assert r["book_equivalence_exercised"] is False     # ……但什么都没比到
    assert r["may_take_over"] is False and "空过" in r["take_over_note"]
    assert (tmp_path / "bearing" / "ALERT_control_not_exercised_20260807.json").exists()
    assert not list((tmp_path / "bearing").glob("ALERT_control_mismatch_*.json"))


def test_no_rebalance_on_one_side_only_is_caught(tmp_path, monkeypatch):
    """一侧不调仓、另一侧建仓 ⇒ status 逐位比对必须逮到，不许判「通过」。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = _run(tmp_path, monkeypatch,
             a_props=[_pa("IBM", 0.06), _pa("IBM", 0.06)],              # (a) 违规 → 不调仓
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10)]}])             # (b) 合规 → 建仓
    assert r["identical"] is False and r["may_take_over"] is False
    assert any(d["field"] == "status" for d in r["book_comparison"]["diffs"])
    assert (tmp_path / "bearing" / "ALERT_control_mismatch_20260807.json").exists()


def test_control_artifact_is_not_named_round_so_it_stays_out_of_the_globs(tmp_path, monkeypatch):
    """对照产物不得被 nav_series / 台账并集的 `round_*.json` glob 扫到。"""
    from qlab.llm_paper.ledger_bridge import evaluated_cells_union
    from qlab.llm_paper.nav_series import coverage
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
         b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                   "proposals": [_prop("IBM", 0.10)]}])
    bearing = str(tmp_path / "bearing")
    assert coverage(bearing)["n_rounds"] == 1                # 只看见承载那一轮
    assert evaluated_cells_union(bearing) == {CELL}          # 对照那份不进并集


# --------------------------------------------------------------------------- #
# 2/3. 不一致 → 报出来、落 ALERT、不切换
# --------------------------------------------------------------------------- #
def test_a_weight_difference_is_caught_and_blocks_takeover(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.09)]}])       # 对照侧权重不同
    assert r["identical"] is False and r["may_take_over"] is False
    fields = {d["field"] for d in r["book_comparison"]["diffs"]}
    assert {"shares", "entries", "gross_notional", "cash"} <= fields
    assert any(d["field"] == "target_weight"
               for d in r["decision_set_comparison"]["diffs"])
    alert = tmp_path / "bearing" / "ALERT_control_mismatch_20260807.json"
    assert alert.exists()
    assert json.loads(alert.read_text(encoding="utf-8"))["alert"] == "CONTROL_MISMATCH"
    assert "不得切换" in r["take_over_note"]


def test_compare_books_flags_each_field_it_claims_to_compare():
    """比对器不是橡皮图章：它自称比的每个字段，改动都必须被逮到。"""
    base = {"book": {"status": "filled", "shares": {"IBM": 1.0}, "entries": {},
                     "gross_notional": 10.0, "cash": 90.0, "entry_cost": 0.01,
                     "nav_start": 100.0},
            "book_x2_cost": {"cash": 89.0, "entry_cost": 0.02, "gross_notional": 10.0},
            "nav_point": {"as_of": "d", "nav": 101.0, "nav_x2_cost": 100.0, "nav_start": 100.0}}
    assert compare_books(base, base)["identical"]
    for path, field in [("book", "shares"), ("book", "cash"), ("book", "gross_notional"),
                        ("book", "entries"), ("book", "status"), ("book", "entry_cost"),
                        ("book_x2_cost", "cash"), ("nav_point", "nav"), ("nav_point", "as_of")]:
        other = json.loads(json.dumps(base))
        other[path][field] = "TAMPERED"
        cmp = compare_books(base, other)
        assert not cmp["identical"], (path, field)
        assert any(d["field"] == field for d in cmp["diffs"]), (path, field)
    # 净值点有无之差也算差异（一侧建了仓、一侧没建）
    no_nav = json.loads(json.dumps(base)); no_nav["nav_point"] = None
    assert any(d["kind"] == "nav_point" and d["field"] == "presence"
               for d in compare_books(base, no_nav)["diffs"])


# --------------------------------------------------------------------------- #
# 4. 对照失败绝不伤到承载路径
# --------------------------------------------------------------------------- #
def test_control_blowup_leaves_the_bearing_round_intact(tmp_path, monkeypatch):
    """(b) 抛异常 ⇒ 报告记 control_error，但 (a) 的 round JSON 与台账登记完好无损。"""
    from research.gate import project_ledger
    _iso(tmp_path, monkeypatch)
    _no_ledger(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    import qlab.llm_paper.parallel_control as PC

    def boom(**kw):
        raise RuntimeError("control side exploded")
    monkeypatch.setattr(PC, "run_round_multi", boom)

    r = _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10)]}], register_trials=True)
    assert r["may_take_over"] is False
    assert "control side exploded" in r["control_error"]
    # 承载侧完好：round JSON 落了盘、台账登了记、payload 正常带出
    bearing = tmp_path / "bearing"
    assert (bearing / "round_20260807.json").exists()
    assert r["bearing_payload"]["book"]["status"] == "filled"
    assert r["bearing_payload"]["ledger"]["n_trials_total"] == 10
    assert len(project_ledger(str(tmp_path / "led.jsonl")).runs) == 1
    assert (bearing / "ALERT_control_mismatch_20260807.json").exists()


def test_control_never_registers_trials(tmp_path, monkeypatch):
    """对照侧不登记台账：整轮只应有承载侧那一条记录。"""
    from research.gate import project_ledger
    _iso(tmp_path, monkeypatch)
    _no_ledger(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10)]}], register_trials=True)
    led = project_ledger(str(tmp_path / "led.jsonl"))
    assert len(led.runs) == 1 and led.runs[0].n_trials_total == 10
    assert r["control_registered_trials"] is False
    ctrl = json.loads((tmp_path / "bearing" / CONTROL_SUBDIR / "round_20260807.json")
                      .read_text(encoding="utf-8"))
    assert ctrl["ledger"] is None and ctrl["bars_injected"] is True


# --------------------------------------------------------------------------- #
# fail-closed 入口
# --------------------------------------------------------------------------- #
def test_same_dir_would_let_control_clobber_the_bearing_record(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    with pytest.raises(PreflightFailed, match="静默覆盖"):
        _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10)]}],
             control_dir=str(tmp_path / "bearing"))


def test_missing_baseline_refuses_to_run_a_control_round(tmp_path, monkeypatch):
    """对照轮不该同时是建基线轮——否则 (a) 建、(b) 验刚写下的那份，两侧状态不可比。"""
    _iso(tmp_path, monkeypatch, with_baseline=False)
    with pytest.raises(PreflightFailed, match="基线不存在"):
        _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                       "proposals": [_prop("IBM", 0.10)]}])


def test_probe_checked_before_any_quota_is_spent(tmp_path, monkeypatch):
    from qlab.events.datafetch.api_quota import guard_from_env
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    before = guard_from_env().status()["used_total"]
    with pytest.raises(PreflightFailed, match="金标准复现|不起跑"):
        run_parallel_control(proposals=[_pa("IBM", 0.10)],
                             cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                                     "proposals": [_prop("IBM", 0.10)]}],
                             decision_ts=DTS, probe=None,
                             out_dir=str(tmp_path / "bearing"), register_trials=False)
    assert guard_from_env().status()["used_total"] == before


def test_control_missing_the_cell_under_comparison_is_reported(tmp_path, monkeypatch):
    """(b) 没跑 (a) 那一格 ⇒ 无从对照，记 control_error 而不是悄悄判「通过」。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = _run(tmp_path, monkeypatch, a_props=[_pa("IBM", 0.10)],
             b_cells=[{"seed": 22, "prompt_variant": "pv2_riskaware",     # 别的格
                       "proposals": [_prop("IBM", 0.10)]}])
    assert r["may_take_over"] is False and "未评估" in r["control_error"]


def test_injected_snapshot_missing_a_symbol_is_refused(tmp_path, monkeypatch):
    """部分快照会被记成 missing_entry_open，与「当天真没开盘价」不可区分 ⇒ 整批拒。"""
    from qlab.llm_paper.quote_bridge import require_injected_bars
    with pytest.raises(PreflightFailed, match="缺"):
        require_injected_bars({"IBM": [object()]}, ["IBM", "SPY"])

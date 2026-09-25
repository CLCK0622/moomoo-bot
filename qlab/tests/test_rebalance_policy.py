"""组合约束不过 ⇒ 该格本轮不调仓（吏部 2026-08-27 裁定，08-31 当轮生效）。

覆盖裁定的每一条边界，外加那条**被点名要求**的回归：无违规输入下，加规则前后输出逐位相同
——把「这条规则在正常路径上一行都不执行」从口头保证变成回归证据。
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from qlab.llm_paper.errors import PreflightFailed
from qlab.llm_paper.ledger_bridge import cell_id
from qlab.llm_paper.multi_book import expand_variants, run_round_multi
from qlab.llm_paper.rebalance_policy import (NO_REBALANCE, assert_no_prior_position,
                                             cells_with_position, no_rebalance_book,
                                             violation_report)
from qlab.llm_paper.run_round import run_round

PROBE = {"model": "test-model", "output": '{"a":1}'}
EV = [{"source_time_utc": pd.Timestamp("2026-08-07 10:00", tz="America/New_York")
       .tz_convert("UTC").isoformat(), "ref_id": "r"}]
DTS = pd.Timestamp("2026-08-07 11:00", tz="America/New_York")   # 周五盘中 → intended = 8/10 开盘
CELL = (11, "pv1_baseline")


def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    monkeypatch.setenv("QLAB_LLM_DETERMINISM_BASELINE", str(tmp_path / "b.json"))


def _stub_bars(monkeypatch, days, *, price=100.0):
    from qlab.events.datafetch.quotes_api import DailyBar
    import qlab.llm_paper.quote_bridge as QB
    monkeypatch.setattr(QB, "get_daily_closes", lambda symbols, **kw: (
        {s: [DailyBar(symbol=s, date=d, close=price, open=price * 0.99) for d in days]
         for s in sorted(symbols)}, {}))


def _p(sym, w, **extra):
    return dict({"symbol": sym, "target_weight": w, "confidence": 0.5, "thesis": "t",
                 "evidence_records": EV}, **extra)


def _pa(sym, w):
    return _p(sym, w, seed=CELL[0], prompt_variant=CELL[1])


# 聚合超单标的上限：逐行 0.06 各自合规（≤0.10），聚合 0.12 超限。
# 这是**唯一**能走到 check_portfolio 的单标的违规形态——单行 0.11 会先被 build_decision 拒。
OVER_CAP_ROWS = [_pa("IBM", 0.06), _pa("IBM", 0.06)]
OVER_CAP_CELL_ROWS = [_p("IBM", 0.06), _p("IBM", 0.06)]


# --------------------------------------------------------------------------- #
# 0. 被点名的回归：无违规时，这条规则一行都不执行
# --------------------------------------------------------------------------- #
def test_no_violation_output_is_bit_identical_to_the_pre_rule_path(tmp_path, monkeypatch):
    """正常路径逐位不变 —— 拿「先算一遍完整 payload，再逐字段比」来证，不是靠读代码相信。

    对照的基准是加规则前那条路径的语义：`build_book` → 盯市 → nav_point，且 payload 里
    不出现任何 no_rebalance 痕迹。
    """
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    props = [_pa("IBM", 0.10), _pa("MRK", 0.06)]
    a = run_round(proposals=props, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path / "a"), register_trials=False)

    # 加规则前的行为：filled book、有净值点、book 里没有 no_rebalance 字段
    assert a["book"]["status"] == "filled"
    assert "no_rebalance" not in a["book"] and "violation" not in a["book"]
    assert a["book_x2_cost"] is not None                      # x2 影子腿照旧存在
    assert a["nav_point"]["nav"] == pytest.approx(
        a["book"]["shares"]["IBM"] * 100.0 + a["book"]["shares"]["MRK"] * 100.0 + a["book"]["cash"])
    assert "no_rebalance" not in a["nav_point"]
    assert a["portfolio_check"]["ok"] is True

    # (b) 侧同理：cells 块里 no_rebalance=False、violation=None
    b = run_round_multi(cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                                "proposals": [_p("IBM", 0.10), _p("MRK", 0.06)]}],
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path / "b"),
                        register_trials=False)
    blk = b["cells"][cell_id(*CELL)]
    assert blk["no_rebalance"] is False and blk["violation"] is None
    assert b["cells_no_rebalance"] == []
    # (a)/(b) 仍逐位相同 —— 规则没有在正常路径上引入任何差异
    assert a["book"] == blk["book"] and a["nav_point"] == blk["nav_point"]


def test_a_and_b_handle_the_same_violation_bit_identically(tmp_path, monkeypatch):
    """(a)/(b) 同时遇到同一违规格 ⇒ 两侧处理**逐位一致**（工部尚书 2026-08-27 必配测试 ②）。

    防的是一个会伪装成「执行器不等价」的坑：违规处理若在两处各写一份，只要有一丝不同，
    并行对照就会报不等价——而那是**规则**造成的差异，不是执行器造成的。本轨的做法是把它
    收进 `rebalance_policy` 共用桥接（理由与 ledger_bridge / quote_bridge 相同），
    这条测试是那个决定的回归证据。
    """
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    a = run_round(proposals=OVER_CAP_ROWS, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path / "a"), register_trials=False)
    b = run_round_multi(cells=[{"seed": CELL[0], "prompt_variant": CELL[1],
                                "proposals": OVER_CAP_CELL_ROWS}],
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path / "b"),
                        register_trials=False)
    blk = b["cells"][cell_id(*CELL)]
    assert a["book"]["status"] == blk["book"]["status"] == NO_REBALANCE
    assert a["book"] == blk["book"]                 # 含 violation 留档，逐位相同
    assert a["nav_point"] == blk["nav_point"]
    assert a["book_x2_cost"] is None and blk["book_x2_cost"] is None
    assert a["portfolio_check"] == blk["portfolio_check"]
    # 并行对照因此判等价（规则不会伪装成执行器不等价）
    from qlab.llm_paper.parallel_control import compare_books
    assert compare_books(a, blk)["identical"] is True


def test_pending_entry_bar_round_is_untouched_by_the_rule(tmp_path, monkeypatch):
    """无违规、且建仓 bar 未出现的轮次：仍是 pending_entry_bar、仍无净值点。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-06", "2026-08-07"])       # 无 >= 8/10 的 bar
    r = run_round(proposals=[_pa("IBM", 0.05)], decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    assert r["book"]["status"] == "pending_entry_bar"
    assert r["nav_point"] is None and r["mark_to_market"] is None


# --------------------------------------------------------------------------- #
# 1. 规则本体：不调仓、整轮照常落盘、仍计入 n_evaluated
# --------------------------------------------------------------------------- #
def test_violating_round_still_lands_instead_of_dying(tmp_path, monkeypatch):
    """(a)：约束不过不再整轮 raise —— 该轮照常落盘，book 为全现金。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = run_round(proposals=OVER_CAP_ROWS, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    assert (tmp_path / "round_20260807.json").exists()          # 轮次没丢
    b = r["book"]
    assert b["status"] == NO_REBALANCE and b["no_rebalance"] is True
    assert b["shares"] == {} and b["gross_notional"] == 0.0
    assert b["cash"] == b["nav_start"] == 100_000.0             # 全现金
    assert b["entry_cost"] == 0.0 and r["book_x2_cost"] is None  # 零换手 ⇒ 无成本可加倍
    assert r["nav_point"]["nav"] == 100_000.0
    assert r["nav_point"]["nav_x2_cost"] == 100_000.0
    assert r["nav_point"]["no_rebalance"] is True               # 标记进不可改记录，事后补不了
    assert r["nav_point"]["as_of"] == "2026-08-10"              # 有 as_of，不是 None
    assert r["portfolio_check"]["ok"] is False                  # 违规如实留在原字段
    assert r["verdict"] is None


def test_one_violating_cell_does_not_take_down_the_other_nine(tmp_path, monkeypatch):
    """(b)：一格违规 ⇒ 只有那一格不调仓，其余格照常建仓，整轮照常落盘。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    cells = expand_variants({"pv1_baseline": OVER_CAP_CELL_ROWS,     # 聚合 0.12 > 0.10
                             "pv2_riskaware": [_p("IBM", 0.05)]})    # 合规
    r = run_round_multi(cells=cells, decision_ts=DTS, probe=PROBE,
                        out_dir=str(tmp_path), register_trials=False)
    assert (tmp_path / "round_20260807.json").exists()
    bad = [c for c in r["cells"].values() if c["no_rebalance"]]
    good = [c for c in r["cells"].values() if not c["no_rebalance"]]
    assert len(bad) == 5 and len(good) == 5                    # pv1 五格违规、pv2 五格照常
    assert all(c["book"]["status"] == NO_REBALANCE for c in bad)
    assert all(c["book"]["status"] == "filled" for c in good)
    assert r["cells_no_rebalance"] == sorted(cell_id(s, "pv1_baseline")
                                             for s in (11, 22, 33, 44, 55))
    assert r["n_cells_evaluated"] == 10                        # 格子一个都没掉


def test_violating_cell_still_counts_in_n_evaluated(tmp_path, monkeypatch):
    """边界 3：格子永远不许从 n_evaluated 掉出去——「记下并跳过」这个选项不存在。"""
    from research.gate import project_ledger
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    monkeypatch.setattr("research.gate.DEFAULT_LEDGER_PATH", str(tmp_path / "led.jsonl"))
    monkeypatch.setattr("qlab.llm_paper.ledger_bridge._REPO_ROOT", tmp_path)
    r = run_round_multi(cells=expand_variants({"pv1_baseline": OVER_CAP_CELL_ROWS,
                                               "pv2_riskaware": OVER_CAP_CELL_ROWS}),
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path / "rep"),
                        register_trials=True)
    assert len(r["cells_no_rebalance"]) == 10                  # 十格全违规
    assert r["ledger"]["n_evaluated"] == 10                    # 仍足额 10
    assert r["ledger"]["n_trials_total"] == 10                 # DSR 的 V 不放松
    assert project_ledger(str(tmp_path / "led.jsonl")).runs[0].n_evaluated == 10


# --------------------------------------------------------------------------- #
# 2. 边界：不许扩散
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("props, match", [
    ([_pa("IBM", 0.11)], "超单标的上限"),          # 单行超限 → build_decision，不是本规则
    ([_pa("IBM", -0.05)], "禁做空"),               # 负仓位 → build_decision
])
def test_decision_chain_failures_still_kill_the_round(props, match, tmp_path, monkeypatch):
    """边界 1：只有 check_portfolio 的判定走新规则；决策链路失败仍整轮 fail-closed。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    with pytest.raises(ValueError, match=match):
        run_round(proposals=props, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    assert not list(tmp_path.glob("round_*.json"))


def test_missing_quote_still_kills_the_round(tmp_path, monkeypatch):
    """边界 1：缺价不适用新规则，仍整轮 fail-closed。"""
    from qlab.events.datafetch.quotes_api import DailyBar
    import qlab.llm_paper.quote_bridge as QB
    _iso(tmp_path, monkeypatch)
    monkeypatch.setattr(QB, "get_daily_closes", lambda symbols, **kw: (
        {"IBM": [DailyBar(symbol="IBM", date="2026-08-10", close=100.0, open=99.0)]},
        {"SPY": "HTTPError"}))
    with pytest.raises(PreflightFailed, match="行情缺失"):
        run_round(proposals=[_pa("IBM", 0.05)], decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    assert not list(tmp_path.glob("round_*.json"))


def test_empty_cell_is_still_a_mistake_not_a_cash_position(tmp_path, monkeypatch):
    """边界 2：空格子不适用——没有提案和提案违规是两回事，不许合并。"""
    _iso(tmp_path, monkeypatch)
    with pytest.raises(PreflightFailed, match="空格子不是「持现金」，是漏了"):
        run_round_multi(cells=[{"seed": CELL[0], "prompt_variant": CELL[1], "proposals": []}],
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path),
                        register_trials=False)


def test_no_weight_is_projected_truncated_or_scaled(tmp_path, monkeypatch):
    """边界 4：动作取空动作 —— 违规权重原样留档，绝不压成合规再执行。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = run_round(proposals=OVER_CAP_ROWS, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    v = r["book"]["violation"]
    assert [row["target_weight"] for row in v["proposed_rows"]] == [0.06, 0.06]  # 原始权重
    assert v["aggregated_weights"] == {"IBM": 0.12}                              # 未被压到 0.10
    assert r["book"]["shares"] == {}                                            # 也没有按 0.10 建仓
    assert "禁止" in v["prohibited"]
    # 决策记录本身也不许被改写
    assert [d["target_weight"] for d in r["decisions"]] == [0.06, 0.06]


def test_violation_record_is_enough_to_reconstruct(tmp_path, monkeypatch):
    """边界 5：格子 id / seed × 变体 / 原始权重 / 触发哪条约束 / 超出多少，且 check 原样落盘。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = run_round(proposals=OVER_CAP_ROWS, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    v = json.loads((tmp_path / "round_20260807.json").read_text(encoding="utf-8"))["book"]["violation"]
    assert v["cell_id"] == cell_id(*CELL) and v["seed"] == 11
    assert v["prompt_variant"] == "pv1_baseline"
    assert v["violations_single_name"] == ["IBM"] and v["violations_short"] == []
    assert v["exceeded_by"]["IBM"] == pytest.approx(0.02)      # 0.12 − 0.10
    assert v["single_name_cap"] == 0.1 and v["gross"] == pytest.approx(0.12)
    assert v["portfolio_check"]["ok"] is False                 # 原样落盘，不是一个布尔
    assert set(v["portfolio_check"]) >= {"gross", "violations_single_name", "leverage_ok"}
    assert v["action_taken"] == NO_REBALANCE


def test_gross_cap_violation_records_how_much_it_exceeded(tmp_path, monkeypatch):
    """总仓超限也走同一条路，且「超出多少」如实记。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    rows = [_pa(s, 0.10) for s in ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K")]
    r = run_round(proposals=rows, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    v = r["book"]["violation"]
    assert v["gross"] == pytest.approx(1.10) and v["gross_exceeded_by"] == pytest.approx(0.10)
    assert v["violations_single_name"] == []                   # 每个都恰好在上限内
    assert r["book"]["status"] == NO_REBALANCE


# --------------------------------------------------------------------------- #
# 3. 退化形态的前提：有前轮持仓就不许套用「全现金」
# --------------------------------------------------------------------------- #
def _write_round(d, name, *, status, shares=None, cell=CELL):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({
        "book": {"status": status, "shares": shares or {}},
        "decisions": [{"seed": cell[0], "prompt_variant": cell[1]}]}), encoding="utf-8")


def test_prior_position_blocks_the_degenerate_all_cash_form(tmp_path, monkeypatch):
    """有前轮持仓时套「全现金」＝把不调仓做成清仓，方向相反且静默 —— 必须停。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    _write_round(tmp_path, "round_20260803.json", status="filled", shares={"IBM": 100.0})
    with pytest.raises(PreflightFailed, match="已建过仓|维持上一轮持仓"):
        run_round(proposals=OVER_CAP_ROWS, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    assert not list(tmp_path.glob("round_20260807.json"))


@pytest.mark.parametrize("status", ["pending_entry_bar", "missing_entry_open", NO_REBALANCE])
def test_non_positions_do_not_block_the_degenerate_form(status, tmp_path, monkeypatch):
    """pending / 缺开盘价 / 上一轮也没调仓 —— 三者都不构成持仓，退化形态照常适用。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    _write_round(tmp_path, "round_20260803.json", status=status)
    r = run_round(proposals=OVER_CAP_ROWS, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path), register_trials=False)
    assert r["book"]["status"] == NO_REBALANCE


def test_round_one_on_disk_leaves_every_cell_position_free():
    """08-31 退化形态成立的实测依据：仓内唯一那份 round 记录没有任何持仓。"""
    from pathlib import Path
    reports = Path(__file__).resolve().parents[1] / "reports" / "llm_paper"
    assert cells_with_position(str(reports)) == {}
    assert_no_prior_position(str(reports), cell_id(*CELL))      # 不抛即通过


def test_unreadable_history_refuses_the_degenerate_form(tmp_path):
    """查不清历史 ⇒ 不许走退化形态（不猜有没有持仓）。"""
    (tmp_path / "round_20260803.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(PreflightFailed, match="无法解析"):
        assert_no_prior_position(str(tmp_path), cell_id(*CELL))


def test_no_rebalance_book_holds_no_positions_and_costs_nothing():
    v = violation_report({"ok": False, "gross": 0.12, "gross_cap": 1.0,
                          "violations_single_name": [], "violations_short": [],
                          "leverage_ok": True}, [], {"signal_params": {"single_name_cap": 0.1}})
    b = no_rebalance_book(nav=100_000.0, cfg={"cost_per_turnover": 0.001}, violation=v)
    assert b["shares"] == {} and b["entries"] == {} and b["gross_notional"] == 0.0
    assert b["cash"] == 100_000.0 and b["entry_cost"] == 0.0
    assert set(b) >= {"status", "nav_start", "shares", "entries", "gross_notional", "cash",
                      "entry_cost"}                            # 形状与 filled book 对齐

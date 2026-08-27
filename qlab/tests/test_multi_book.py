"""(b) 多 book 执行器：一次取符号并集、内部按格分账，每格自带净值序列。

覆盖四件必须成立的事：
1. **配额**：10 格一轮仍只取一遍符号并集（≈8 次），不是 10 × 8 = 80；
2. **等价性第 ① 段**：(b) 的决策集与第 1 轮已落盘记录 `round_20260810.json` **逐位相同**
   （symbol / target_weight / seed / prompt_variant / 三时间戳）；
3. **(b) ≡ (a)**：同一批输入下，单格 (b) 与 (a) 的 book / 股数 / gross / 现金 / 净值点逐位相同；
4. **约束按格判、不越格**：每格是独立组合；任一格违规 ⇒ 整轮 fail-closed、零落盘。

外加台账桥接的回归：第 2 轮起的登记不得被重冻护栏打死（原内联写法必崩，实测见 ledger_bridge 模块头）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qlab.llm_paper.multi_book import (EQUIVALENCE_FIELDS, cell_id, compare_decision_sets,
                                       decision_fingerprint, expand_variants, run_round_multi,
                                       symbol_union)
from qlab.llm_paper.run_round import PreflightFailed, run_round

PROBE = {"model": "test-model", "output": '{"a":1}'}
EV = [{"source_time_utc": pd.Timestamp("2026-08-07 10:00", tz="America/New_York")
       .tz_convert("UTC").isoformat(), "ref_id": "r"}]
DTS = pd.Timestamp("2026-08-07 11:00", tz="America/New_York")   # 周五盘中 → intended = 8/10 开盘
ROUND1 = Path(__file__).resolve().parents[1] / "reports" / "llm_paper" / "round_20260810.json"


def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    monkeypatch.setenv("QLAB_LLM_DETERMINISM_BASELINE", str(tmp_path / "b.json"))


def _stub_bars(monkeypatch, days, *, price=100.0, calls=None):
    """打桩行情：记录每次调用的符号数，用来证明「一次取并集」而不是按格各取一遍。

    打桩点只有 quote_bridge 一处——取行情已收进共用桥接，(a)/(b)/并行对照都走它。
    """
    from qlab.events.datafetch.quotes_api import DailyBar
    import qlab.llm_paper.quote_bridge as QB

    def fake(symbols, **kw):
        syms = sorted(symbols)
        if calls is not None:
            calls.append(syms)
        return ({s: [DailyBar(symbol=s, date=d, close=price, open=price * 0.99) for d in days]
                 for s in syms}, {})
    monkeypatch.setattr(QB, "get_daily_closes", fake)


def _prop(sym, w, seed_free=True):
    return {"symbol": sym, "target_weight": w, "confidence": 0.5, "thesis": "t",
            "evidence_records": EV}


# --------------------------------------------------------------------------- #
# 1. 配额：一次取并集
# --------------------------------------------------------------------------- #
def test_full_grid_costs_one_union_fetch_not_one_per_cell(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    calls = []
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"], calls=calls)
    cells = expand_variants({"pv1_baseline": [_prop("IBM", 0.09), _prop("MRK", 0.06)],
                             "pv2_riskaware": [_prop("IBM", 0.07), _prop("MRK", 0.05)]})
    assert len(cells) == 10                                   # 冻结网格足额
    r = run_round_multi(cells=cells, decision_ts=DTS, probe=PROBE,
                        out_dir=str(tmp_path), register_trials=False)
    assert len(calls) == 1                                    # 整轮**一次**取行情
    assert calls[0] == ["IBM", "MRK", "SPY"]                  # 并集 ∪ 基准
    assert r["quote_calls_this_round"] == 3
    assert r["quote_calls_if_naive_per_cell"] == 30           # 朴素做法的代价，如实记进报告
    assert r["n_cells_evaluated"] == 10 and r["cells_missing"] == []


def test_symbol_union_dedupes_across_cells():
    cells = [{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.05)]},
             {"seed": 22, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.05)]}]
    assert symbol_union(cells) == ["IBM", "SPY"]


# --------------------------------------------------------------------------- #
# 2. 等价性第 ① 段：决策集 vs 第 1 轮已落盘记录 f2f7729
# --------------------------------------------------------------------------- #
def test_decision_set_matches_round1_bit_for_bit(tmp_path, monkeypatch):
    """把第 1 轮的 7 条决策原样喂给 (b)，决策集必须与 `round_20260810.json` **逐位相同**。

    这是 (b) 接管前等价性验证的第 ① 段（工部尚书 2026-08-27 指定的比对字段）。第 1 轮
    `status=pending_entry_bar`、没有 book，book 等价性另在与 (a) 并行的那一轮做对照。

    `evidence_records` 用记录里的 `evidence_acceptance_utc` 重建：`derive_available_utc` 对
    信息源时间单调不减 ⇒ max(可得) = 可得(max(受理))，故单条重建与原多条等价；而
    `evidence_available_utc` 是**重新派生**出来的，比对因此是真的过了一遍派生逻辑，不是抄答案。
    """
    _iso(tmp_path, monkeypatch)
    rec = json.loads(ROUND1.read_text(encoding="utf-8"))
    assert rec["book"]["status"] == "pending_entry_bar"       # 前提：那一轮如期无 book

    # 第 1 轮观测到 100 个交易日、且无 >= 2026-08-10 13:30Z 的 bar（决策先于建仓日）
    days = [d.strftime("%Y-%m-%d")
            for d in pd.bdate_range("2026-03-20", "2026-08-07")][-100:]
    assert len(days) == 100
    _stub_bars(monkeypatch, days)

    dts = pd.Timestamp(rec["round_decision_ts"])
    proposals = [{"symbol": d["symbol"], "target_weight": d["target_weight"],
                  "confidence": d["confidence"], "thesis": d["thesis"],
                  "model": d["model"],
                  "evidence_records": [{"source_time_utc": d["evidence_acceptance_utc"],
                                        "ref_id": d["evidence_refs"][0]}]}
                 for d in rec["decisions"]]
    cells = [{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": proposals}]
    r = run_round_multi(cells=cells, decision_ts=dts, probe=PROBE,
                        out_dir=str(tmp_path), register_trials=False)

    blk = r["cells"][cell_id(11, "pv1_baseline")]
    cmp = compare_decision_sets(blk["decisions"], rec["decisions"])
    assert cmp["identical"], cmp["diffs"]
    assert cmp["n_left"] == cmp["n_right"] == 7
    assert set(cmp["fields_compared"]) == set(EQUIVALENCE_FIELDS)
    # 组合读数也对得上（gross 0.49 / 现金 0.51），且同样如期无 book
    assert blk["portfolio_check"]["gross"] == pytest.approx(rec["portfolio_check"]["gross"])
    assert blk["book"]["status"] == "pending_entry_bar" and blk["nav_point"] is None


def test_compare_decision_sets_catches_a_single_flipped_field():
    """比对器本身不能是橡皮图章：改一个字段就必须报出来。"""
    rec = json.loads(ROUND1.read_text(encoding="utf-8"))["decisions"]
    tampered = [dict(d) for d in rec]
    tampered[0]["target_weight"] = tampered[0]["target_weight"] + 0.01
    cmp = compare_decision_sets(tampered, rec)
    assert not cmp["identical"]
    assert cmp["diffs"][0]["field"] == "target_weight"
    assert compare_decision_sets(rec[:-1], rec)["diffs"][0]["kind"] == "n_decisions"


def test_fingerprint_reads_dataclass_and_json_alike():
    from types import SimpleNamespace as NS
    d = NS(symbol="IBM", target_weight=0.05, seed=11, prompt_variant="pv1_baseline",
           evidence_available_utc="a", decision_ts="b", intended_start="c")
    assert decision_fingerprint(d) == decision_fingerprint(
        {"symbol": "IBM", "target_weight": 0.05, "seed": 11, "prompt_variant": "pv1_baseline",
         "evidence_available_utc": "a", "decision_ts": "b", "intended_start": "c"})


# --------------------------------------------------------------------------- #
# 3. (b) ≡ (a)：单格逐位相同（含真 book / 净值点）
# --------------------------------------------------------------------------- #
def test_single_cell_book_identical_to_path_a(tmp_path, monkeypatch):
    """并行对照的机械版本：同输入下 (b) 的单格 book 与 (a) 逐位相同（股数/gross/现金/净值）。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    props = [{"symbol": "IBM", "target_weight": 0.10, "confidence": 0.6, "thesis": "t",
              "evidence_records": EV, "seed": 11, "prompt_variant": "pv1_baseline"},
             {"symbol": "MRK", "target_weight": 0.06, "confidence": 0.4, "thesis": "t2",
              "evidence_records": EV, "seed": 11, "prompt_variant": "pv1_baseline"}]
    a = run_round(proposals=props, decision_ts=DTS, probe=PROBE,
                  out_dir=str(tmp_path / "a"), register_trials=False)
    b = run_round_multi(cells=[{"seed": 11, "prompt_variant": "pv1_baseline",
                                "proposals": props}],
                        decision_ts=DTS, probe=PROBE,
                        out_dir=str(tmp_path / "b"), register_trials=False)
    blk = b["cells"][cell_id(11, "pv1_baseline")]
    assert a["book"]["status"] == blk["book"]["status"] == "filled"
    assert a["book"]["shares"] == blk["book"]["shares"]
    assert a["book"]["gross_notional"] == blk["book"]["gross_notional"]
    assert a["book"]["cash"] == blk["book"]["cash"]
    assert a["book"]["entries"] == blk["book"]["entries"]
    assert a["book_x2_cost"]["cash"] == blk["book_x2_cost"]["cash"]
    assert a["nav_point"] == blk["nav_point"]
    assert compare_decision_sets(a["decisions"], blk["decisions"])["identical"]
    assert a["verdict"] is None and b["verdict"] is None


# --------------------------------------------------------------------------- #
# 4. 按格分账 / 按格判约束 / fail-closed
# --------------------------------------------------------------------------- #
def test_cells_keep_separate_books_and_navs(tmp_path, monkeypatch):
    """两格不同权重 ⇒ 两个不同的 book 与净值点。分账串了这条就会挂。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = run_round_multi(
        cells=[{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.10)]},
               {"seed": 11, "prompt_variant": "pv2_riskaware", "proposals": [_prop("IBM", 0.04)]}],
        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    c1 = r["cells"][cell_id(11, "pv1_baseline")]
    c2 = r["cells"][cell_id(11, "pv2_riskaware")]
    assert c1["book"]["gross_notional"] == pytest.approx(10_000.0)
    assert c2["book"]["gross_notional"] == pytest.approx(4_000.0)
    assert c1["nav_point"]["nav"] != c2["nav_point"]["nav"]
    assert c1["book"]["nav_start"] == c2["book"]["nav_start"] == 100_000.0   # 每格独立起点
    assert r["cells_missing"] and len(r["cells_missing"]) == 8               # 缺格如实记录，不静默


def test_gross_cap_is_per_cell_not_summed_across_cells(tmp_path, monkeypatch):
    """10 格各 49% 是 10 个独立组合，不是 490% —— 加总去判会把合规轮判成超限。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    props = [_prop(s, 0.10) for s in ("IBM", "MRK", "CAT", "GD", "COP")]     # 每格 gross 0.50
    r = run_round_multi(cells=expand_variants({"pv1_baseline": props, "pv2_riskaware": props}),
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path),
                        register_trials=False)
    assert all(c["portfolio_check"]["ok"] for c in r["cells"].values())
    assert all(c["portfolio_check"]["gross"] == pytest.approx(0.50) for c in r["cells"].values())


def test_one_bad_cell_no_longer_takes_down_the_round(tmp_path, monkeypatch):
    """一格聚合超单标的上限 ⇒ **只有那一格不调仓**，整轮照常落盘。

    这条曾断言「整轮不落盘」，被吏部 2026-08-27 裁定取代（08-31 当轮生效）：一格的错换十格
    全灭 + 一个补不回的日历轮次，代价与过错不成比例。细则见 tests/test_rebalance_policy.py。
    """
    from qlab.llm_paper.rebalance_policy import NO_REBALANCE
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    bad = [_prop("IBM", 0.05), _prop("IBM", 0.05), _prop("IBM", 0.05)]       # 聚合 15% > 冻结 10%
    r = run_round_multi(
        cells=[{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.05)]},
               {"seed": 11, "prompt_variant": "pv2_riskaware", "proposals": bad}],
        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    assert list(tmp_path.glob("round_20260807.json"))                        # 轮次没丢
    assert r["cells"][cell_id(11, "pv1_baseline")]["book"]["status"] == "filled"
    assert r["cells"][cell_id(11, "pv2_riskaware")]["book"]["status"] == NO_REBALANCE
    assert r["cells_no_rebalance"] == [cell_id(11, "pv2_riskaware")]
    assert r["n_cells_evaluated"] == 2                                       # 格子没掉


def test_multi_book_requires_gold_probe(tmp_path, monkeypatch):
    """探针没有跳过开关，(b) 与 (a) 一视同仁；且探针在花配额之前。"""
    from qlab.events.datafetch.api_quota import guard_from_env
    _iso(tmp_path, monkeypatch)
    before = guard_from_env().status()["used_total"]
    with pytest.raises(PreflightFailed, match="金标准复现|不起跑"):
        run_round_multi(cells=[{"seed": 11, "prompt_variant": "pv1_baseline",
                                "proposals": [_prop("IBM", 0.05)]}],
                        decision_ts=DTS, probe=None, out_dir=str(tmp_path),
                        register_trials=False)
    assert guard_from_env().status()["used_total"] == before
    assert not list(tmp_path.glob("round_*.json"))


@pytest.mark.parametrize("cells, match", [
    ([{"seed": 99, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.05)]}],
     "不在冻结网格内"),
    ([{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.05)]},
      {"seed": 11, "prompt_variant": "pv1_baseline", "proposals": [_prop("IBM", 0.05)]}],
     "重复出现"),
    ([{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": []}], "无提案"),
    ([{"seed": 11, "prompt_variant": "pv1_baseline",
       "proposals": [dict(_prop("IBM", 0.05), seed=22)]}], "标了 seed"),
])
def test_cell_input_is_fail_closed(cells, match, tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    with pytest.raises(PreflightFailed, match=match):
        run_round_multi(cells=cells, decision_ts=DTS, probe=PROBE,
                        out_dir=str(tmp_path), register_trials=False)


def test_drift_records_all_cells_and_drops_an_alert(tmp_path, monkeypatch):
    """漂移不丢本轮真数据：10 格照记，但带告警落盘 + 独立 ALERT + seed 口径翻转。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    cells = expand_variants({"pv1_baseline": [_prop("IBM", 0.09)],
                             "pv2_riskaware": [_prop("IBM", 0.07)]})
    kw = dict(cells=cells, decision_ts=DTS, out_dir=str(tmp_path), register_trials=False)
    run_round_multi(probe=PROBE, **kw)                                   # 建立基线
    r = run_round_multi(probe={"model": "test-model", "output": '{"a":2}'}, **kw)
    assert r["alerts"] == ["model_drift_detected"]
    assert r["seed_semantics"]["seed_status"] == "nominal_assumption_broken"
    assert len(r["cells"]) == 10 and r["n_decisions"] == 10              # 真数据仍如实记录
    assert list(tmp_path.glob("ALERT_model_drift_*.json"))


def test_quota_divergence_leaves_an_alert_and_no_round(tmp_path, monkeypatch):
    """疑似 key 被盗用：整批不出、无决策无净值，但必须留下独立 ALERT（否则告警只活在 traceback 里）。"""
    import qlab.llm_paper.quote_bridge as QB
    from qlab.events.datafetch.quotes_api import RateLimited
    _iso(tmp_path, monkeypatch)

    def boom(symbols, **kw):
        raise RateLimited("SPY: Information (daily throttle): <redacted-api-key> ...",
                          ledger_remaining=24, vendor_throttled=True,
                          utc_day="2026-08-09", kind="daily")
    monkeypatch.setattr(QB, "get_daily_closes", boom)
    with pytest.raises(RateLimited):
        run_round_multi(cells=[{"seed": 11, "prompt_variant": "pv1_baseline",
                                "proposals": [_prop("IBM", 0.05)]}],
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path),
                        register_trials=False)
    alerts = list(tmp_path.glob("ALERT_quota_divergence_*.json"))
    assert alerts and not list(tmp_path.glob("round_*.json"))
    a = json.loads(alerts[0].read_text(encoding="utf-8"))
    assert a["alert"] == "QUOTA_DIVERGENCE" and a["ledger_remaining"] == 24
    assert a["executor"] == "multi_book_v1"


def test_missing_quote_symbol_blocks_the_round(tmp_path, monkeypatch):
    """并集里缺一只 ⇒ 整轮不产生决策（不用陈旧价、不出假净值）。"""
    import qlab.llm_paper.quote_bridge as QB
    from qlab.events.datafetch.quotes_api import DailyBar
    _iso(tmp_path, monkeypatch)
    monkeypatch.setattr(QB, "get_daily_closes", lambda symbols, **kw: (
        {"IBM": [DailyBar(symbol="IBM", date="2026-08-10", close=100.0, open=99.0)]},
        {"SPY": "HTTPError"}))
    with pytest.raises(PreflightFailed, match="行情缺失"):
        run_round_multi(cells=[{"seed": 11, "prompt_variant": "pv1_baseline",
                                "proposals": [_prop("IBM", 0.05)]}],
                        decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path),
                        register_trials=False)
    assert not list(tmp_path.glob("round_*.json"))


def test_round_payload_is_written_and_readable_by_nav_series(tmp_path, monkeypatch):
    """(b) 的落盘格式必须能被每格净值序列直接读通——切换那一轮就靠这个接得上。"""
    from qlab.llm_paper.nav_series import cell_nav_series, coverage
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    run_round_multi(cells=expand_variants({"pv1_baseline": [_prop("IBM", 0.09)],
                                           "pv2_riskaware": [_prop("IBM", 0.07)]}),
                    decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    assert (tmp_path / "round_20260807.json").exists()
    s = cell_nav_series(str(tmp_path))
    assert len(s) == 10 and all(len(v) == 1 for v in s.values())
    assert coverage(str(tmp_path))["per_round"][0]["executor"] == "multi_book_v1"


def test_expand_variants_refuses_partial_or_foreign_variants():
    with pytest.raises(PreflightFailed, match="pv2_riskaware"):
        expand_variants({"pv1_baseline": [_prop("IBM", 0.05)]})
    with pytest.raises(PreflightFailed, match="不在冻结网格内"):
        expand_variants({"pv1_baseline": [_prop("IBM", 0.05)],
                         "pv2_riskaware": [_prop("IBM", 0.05)],
                         "pv3_wild": [_prop("IBM", 0.05)]})

"""决策轮执行器：前置自检 fail-closed、组合约束、不出 verdict。"""
from __future__ import annotations
import pandas as pd, pytest
from qlab.llm_paper.run_round import preflight, PreflightFailed, run_round

def test_preflight_reports_anchor_grid_and_quota(tmp_path, monkeypatch):
    # 用临时台账隔离：真台账今天已 25/25 用尽（preflight 会正确拒跑，另有测试覆盖）
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    c = preflight(n_symbols_needed=2)
    assert c["anchor_ok"] and c["paradigm"] == "llm_agent" and c["grid_cells"] == 10
    assert c["quota"]["cap_per_day"] == 25 and c["quota"]["reserve_for_marking"] == 15
    assert "quota_caveat" in c            # 台账/供应商可能不一致，如实标注

def test_preflight_fails_closed_when_quota_short(tmp_path, monkeypatch):
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    with pytest.raises(PreflightFailed, match="配额不足"):
        preflight(n_symbols_needed=999)   # 远超 25/天 → 不起跑


def test_preflight_refuses_when_todays_quota_is_spent(tmp_path, monkeypatch):
    """真实场景：当天额度已用尽 → 拒绝起跑（宁可不跑，也不在净值序列留空洞）。"""
    from qlab.events.datafetch.api_quota import guard_from_env, MARKING
    led = tmp_path / "q.jsonl"
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(led))
    g = guard_from_env(); g.record(purpose=MARKING, n=25, note="test: exhaust day")
    with pytest.raises(PreflightFailed, match="不起跑"):
        preflight(n_symbols_needed=2)

def test_run_round_requires_gold_probe(tmp_path, monkeypatch):
    """漂移检查**没有跳过开关**：不传探针结果就不起跑（可跳过的护栏等于没有护栏）。"""
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    monkeypatch.setenv("QLAB_LLM_DETERMINISM_BASELINE", str(tmp_path / "b.json"))
    ev = [{"source_time_utc": pd.Timestamp("2026-08-07 14:00", tz="America/New_York")
           .tz_convert("UTC").isoformat(), "ref_id": "r"}]
    prop = [{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5, "thesis": "t",
             "evidence_records": ev, "seed": 11, "prompt_variant": "pv1_baseline"}]
    for bad in (None, {}, {"model": "m", "output": ""}):
        with pytest.raises(PreflightFailed, match="金标准复现|不起跑"):
            run_round(proposals=prop, decision_ts=pd.Timestamp("2026-08-07 15:00", tz="UTC"),
                      probe=bad, out_dir=str(tmp_path), register_trials=False)
    assert not list(tmp_path.glob("round_*.json"))     # 一条都没落盘
    assert not (tmp_path / "b.json").exists()          # 也没顺手建立基线


def test_run_round_probe_checked_before_spending_quota(tmp_path, monkeypatch):
    """护栏在花配额之前：探针不过时，当天 25 次额度一次都不该被扣。"""
    from qlab.events.datafetch.api_quota import guard_from_env
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    monkeypatch.setenv("QLAB_LLM_DETERMINISM_BASELINE", str(tmp_path / "b.json"))
    ev = [{"source_time_utc": pd.Timestamp("2026-08-07 14:00", tz="America/New_York")
           .tz_convert("UTC").isoformat(), "ref_id": "r"}]
    before = guard_from_env().status()["used_total"]
    with pytest.raises(PreflightFailed):
        run_round(proposals=[{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": ev, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=pd.Timestamp("2026-08-07 15:00", tz="UTC"),
                  probe=None, out_dir=str(tmp_path), register_trials=False)
    assert guard_from_env().status()["used_total"] == before


# ---- 以下用假 bar 打桩，测执行器自身的逻辑：不打网络、不花当天真额度 ----

PROBE = {"model": "test-model", "output": '{"a":1}'}
EV = [{"source_time_utc": pd.Timestamp("2026-08-07 10:00", tz="America/New_York")
       .tz_convert("UTC").isoformat(), "ref_id": "r"}]
DTS = pd.Timestamp("2026-08-07 11:00", tz="America/New_York")   # 周五盘中 → intended = 8/10 开盘


def _stub_bars(monkeypatch, days, *, with_open=True, price=100.0):
    from qlab.events.datafetch.quotes_api import DailyBar
    import qlab.llm_paper.run_round as RR

    def fake(symbols, **kw):
        return ({s: [DailyBar(symbol=s, date=d, close=price,
                              open=(price * 0.99 if with_open else None)) for d in days]
                 for s in symbols}, {})
    monkeypatch.setattr(RR, "get_daily_closes", fake)


def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("QLAB_AV_QUOTA_LEDGER", str(tmp_path / "q.jsonl"))
    monkeypatch.setenv("QLAB_LLM_DETERMINISM_BASELINE", str(tmp_path / "b.json"))


def test_run_round_rejects_shorting_before_any_write(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    with pytest.raises(ValueError, match="禁做空"):      # 负仓位在 build_decision 即被拒
        run_round(proposals=[{"symbol": "IBM", "target_weight": -0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": EV, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    assert not list(tmp_path.glob("round_*.json"))   # 未落盘


def test_book_converts_weights_to_shares_at_entry_open(tmp_path, monkeypatch):
    """权重 → 股数必须过一遍**建仓日开盘价**；早先直接把权重当股数灌进盯市是错的算术。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"], price=100.0)   # open = 99.0
    r = run_round(proposals=[{"symbol": "IBM", "target_weight": 0.10, "confidence": 0.6,
                              "thesis": "t", "evidence_records": EV, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    b = r["book"]
    assert b["status"] == "filled"
    assert b["entries"]["IBM"]["entry_date"] == "2026-08-10"     # 首根建仓 bar
    assert b["entries"]["IBM"]["entry_open"] == 99.0             # 开盘价，不是收盘价
    assert b["shares"]["IBM"] == pytest.approx(100_000.0 * 0.10 / 99.0)
    assert b["entry_cost"] == pytest.approx(10_000.0 * 0.001)    # 10bps/单向
    # 净值点是真美元数量级，不是 0.1 × 收盘价那种无意义数
    assert r["nav_point"]["nav"] == pytest.approx(
        b["shares"]["IBM"] * 100.0 + b["cash"])
    assert r["book_x2_cost"]["entry_cost"] == pytest.approx(2 * b["entry_cost"])  # 双轨 x2
    assert r["verdict"] is None


def test_no_nav_point_before_entry_bar_exists(tmp_path, monkeypatch):
    """决策先于建仓日 ⇒ 仓位尚未建立 ⇒ **不产生净值点**（此刻任何净值都是编的）。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-06", "2026-08-07"])        # 无 >= 8/10 的 bar
    r = run_round(proposals=[{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": EV, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    assert r["book"]["status"] == "pending_entry_bar"
    assert r["nav_point"] is None and r["mark_to_market"] is None
    assert r["actual_start_settlement"]["pending"] == 1


def test_missing_entry_open_does_not_fall_back_to_close(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"], with_open=False)
    r = run_round(proposals=[{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": EV, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    assert r["book"]["status"] == "missing_entry_open" and r["nav_point"] is None


def test_round_payload_carries_determinism_and_seed_caliber(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    r = run_round(proposals=[{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": EV, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    assert r["determinism"]["status"] == "baseline_established"   # 首轮只建基线
    assert r["seed_semantics"]["seed_status"] == "nominal"
    assert r["seed_quantile_caliber"]["lower_quartile_equals_worse_variant"] is True
    assert r["gold_probe_output"] == PROBE["output"]              # 原样留档供外部复核
    assert r["alerts"] == [] and not list(tmp_path.glob("ALERT_*.json"))


def test_drift_records_the_round_and_drops_an_alert_file(tmp_path, monkeypatch):
    """漂移不该丢掉本轮真数据，但必须带告警落盘 + 单独 ALERT 文件 + seed 口径翻转。"""
    _iso(tmp_path, monkeypatch)
    _stub_bars(monkeypatch, ["2026-08-07", "2026-08-10"])
    prop = [{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5, "thesis": "t",
             "evidence_records": EV, "seed": 11, "prompt_variant": "pv1_baseline"}]
    run_round(proposals=prop, decision_ts=DTS, probe=PROBE,
              out_dir=str(tmp_path), register_trials=False)          # 建立基线
    r = run_round(proposals=prop, decision_ts=DTS,
                  probe={"model": "test-model", "output": '{"a":2}'},   # 输出变了
                  out_dir=str(tmp_path), register_trials=False)
    assert r["alerts"] == ["model_drift_detected"]
    assert r["seed_semantics"]["seed_status"] == "nominal_assumption_broken"
    assert r["n_decisions"] == 1                                   # 真数据仍如实记录
    assert list(tmp_path.glob("ALERT_model_drift_*.json"))


def test_quota_divergence_leaves_an_alert_and_no_round(tmp_path, monkeypatch):
    """疑似 key 被盗用（QUOTA_DIVERGENCE）时：整批不出、无决策无净值，但**留下独立 ALERT**。

    否则本轮中止 ⇒ 没有 round JSON ⇒ 告警只以 traceback 形态存在，等于没留痕。
    """
    import qlab.llm_paper.run_round as RR
    from qlab.events.datafetch.quotes_api import RateLimited
    _iso(tmp_path, monkeypatch)

    def boom(symbols, **kw):
        raise RateLimited("SPY: Information (daily throttle): <redacted-api-key> ...",
                          ledger_remaining=24, vendor_throttled=True,
                          utc_day="2026-08-09", kind="daily")
    monkeypatch.setattr(RR, "get_daily_closes", boom)
    with pytest.raises(RateLimited):
        run_round(proposals=[{"symbol": "IBM", "target_weight": 0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": EV, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=DTS, probe=PROBE, out_dir=str(tmp_path), register_trials=False)
    alerts = list(tmp_path.glob("ALERT_quota_divergence_*.json"))
    assert alerts and not list(tmp_path.glob("round_*.json"))
    import json as _j
    a = _j.loads(alerts[0].read_text(encoding="utf-8"))
    assert a["alert"] == "QUOTA_DIVERGENCE" and a["ledger_remaining"] == 24


# ---- 同符号多行：聚合而非覆盖；且聚合后仍受冻结单标的上限约束 ----
# 工部尚书 2026-08-10 实测：两处 bug 互相掩盖——build_book 按符号覆盖让 book 静默缩水
# （掩盖了超限），若只把覆盖改成聚合而 check_portfolio 仍逐行判上限，就会**真的**持有
# 超过冻结 10% 的单一标的。故两条断言必须并存，防止将来只修一半。
def test_same_symbol_rows_aggregate_not_overwrite(monkeypatch, tmp_path):
    from qlab.llm_paper.run_round import build_book
    from types import SimpleNamespace as NS

    class _B:
        def __init__(self, d, o): self.date, self.open = d, o

    bars = {"SPY": [_B("2026-08-11", 100.0)], "AAPL": [_B("2026-08-11", 200.0)]}
    start = "2026-08-11T13:30:00+00:00"
    ds = [NS(symbol="SPY", target_weight=0.05, actual_start=start),
          NS(symbol="SPY", target_weight=0.05, actual_start=start),
          NS(symbol="AAPL", target_weight=0.10, actual_start=start)]
    r = build_book(ds, bars, {"cost_per_turnover": 0.001})
    assert r["status"] == "filled"
    assert r["gross_notional"] == 20_000.0        # 覆盖时会缩水成 15_000
    assert r["shares"]["SPY"] == 100.0            # 0.10×100k/100，不是 0.05 那一行


def test_single_name_cap_applies_to_aggregated_weight():
    from qlab.llm_paper.decision_chain import check_portfolio, load_prereg
    from types import SimpleNamespace as NS
    cfg = load_prereg()
    ds = [NS(symbol="SPY", target_weight=0.05) for _ in range(3)]   # 聚合 15% > 冻结 10%
    r = check_portfolio(ds, cfg)
    assert r["ok"] is False
    assert "SPY" in r["violations_single_name"]

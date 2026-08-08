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

def test_run_round_rejects_shorting_before_any_write(tmp_path):
    ev = [{"source_time_utc": pd.Timestamp("2026-08-07 14:00", tz="America/New_York")
           .tz_convert("UTC").isoformat(), "ref_id": "r"}]
    with pytest.raises(Exception):        # 负仓位在 build_decision 即被拒
        run_round(proposals=[{"symbol": "IBM", "target_weight": -0.05, "confidence": 0.5,
                              "thesis": "t", "evidence_records": ev, "seed": 11,
                              "prompt_variant": "pv1_baseline"}],
                  decision_ts=pd.Timestamp("2026-08-07 15:00", tz="America/New_York"),
                  out_dir=str(tmp_path), register_trials=False)
    assert not list(tmp_path.glob("round_*.json"))   # 未落盘

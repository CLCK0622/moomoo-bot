"""决策链路：三条时序不等式 + 冻结组合约束 + 网格一致性（前向纸面轨）。"""
from __future__ import annotations
import pandas as pd, pytest
from qlab.llm_paper.decision_chain import (load_prereg, frozen_grid, build_decision,
                                            check_portfolio, next_open_after, Decision)

ET = "America/New_York"
def _ev(ts, ref="r1"): return {"source_time_utc": pd.Timestamp(ts, tz=ET).tz_convert("UTC").isoformat(), "ref_id": ref}
def _dts(ts): return pd.Timestamp(ts, tz=ET)

def test_frozen_grid_matches_prereg():
    cfg = load_prereg(); g = frozen_grid(cfg)
    assert len(g) == 10 and cfg["family"]["n_trials_total"] == 10
    assert {x["seed"] for x in g} == {11, 22, 33, 44, 55}

def test_evidence_after_decision_is_rejected():
    # 证据可得晚于决策 = 前视 → 必须拒
    with pytest.raises(ValueError, match="前视"):
        build_decision(symbol="AAPL", target_weight=0.05, confidence=0.6, thesis="t",
                       evidence_records=[_ev("2026-06-18 14:00")], decision_ts=_dts("2026-06-18 10:00"),
                       seed=11, prompt_variant="pv1_baseline")

def test_after_hours_evidence_rolls_and_blocks_same_night_decision():
    # 18:40 ET 受理 → 可得为次日 09:30；当晚 20:00 决策必须被拒（那时还不可交易）
    with pytest.raises(ValueError, match="前视"):
        build_decision(symbol="AAPL", target_weight=0.05, confidence=0.6, thesis="t",
                       evidence_records=[_ev("2026-06-17 18:40")], decision_ts=_dts("2026-06-17 20:00"),
                       seed=11, prompt_variant="pv1_baseline")

def test_valid_decision_orders_three_timestamps():
    # 证据 6/17 18:40 ET 受理 → 可得 6/18 09:30 ET；决策须在可得之后（10:00 ET 合规；
    # 09:00 ET 会被判前视——那正是上一条测试覆盖的边界）
    d = build_decision(symbol="AAPL", target_weight=0.05, confidence=0.7, thesis="t",
                       evidence_records=[_ev("2026-06-17 18:40")], decision_ts=_dts("2026-06-18 10:00"),
                       seed=11, prompt_variant="pv1_baseline")
    assert pd.Timestamp(d.evidence_available_utc) <= pd.Timestamp(d.decision_ts) <= pd.Timestamp(d.effective_from)
    assert d.evidence_acceptance_utc != d.evidence_available_utc   # 原始受理时刻留档且确实早于可得

def test_shorting_and_single_name_cap_enforced():
    with pytest.raises(ValueError, match="禁做空"):
        build_decision(symbol="AAPL", target_weight=-0.01, confidence=0.5, thesis="t",
                       evidence_records=[_ev("2026-06-17 14:00")], decision_ts=_dts("2026-06-17 15:00"),
                       seed=11, prompt_variant="pv1_baseline")
    with pytest.raises(ValueError, match="超单标的上限"):
        build_decision(symbol="AAPL", target_weight=0.20, confidence=0.5, thesis="t",
                       evidence_records=[_ev("2026-06-17 14:00")], decision_ts=_dts("2026-06-17 15:00"),
                       seed=11, prompt_variant="pv1_baseline")

def test_no_evidence_no_decision():
    with pytest.raises(ValueError, match="无据不决策"):
        build_decision(symbol="AAPL", target_weight=0.05, confidence=0.5, thesis="t",
                       evidence_records=[], decision_ts=_dts("2026-06-17 15:00"),
                       seed=11, prompt_variant="pv1_baseline")

def test_gross_cap_and_cash():
    ds = [Decision(symbol=f"S{i}", target_weight=0.10, confidence=0.5, thesis="t", evidence_refs=["r"],
                   evidence_available_utc="2026-06-17T18:00:00+00:00",
                   evidence_acceptance_utc="2026-06-17T18:00:00+00:00",
                   decision_ts="2026-06-17T19:00:00+00:00", effective_from="2026-06-18T13:30:00+00:00",
                   seed=11, prompt_variant="pv1_baseline") for i in range(10)]
    p = check_portfolio(ds); assert p["ok"] and abs(p["gross"] - 1.0) < 1e-9 and p["leverage_ok"]
    ds.append(ds[0]); p2 = check_portfolio(ds); assert not p2["ok"]   # 11×10% > 100% 总仓上限

def test_effective_from_skips_holiday():
    # 2025-08-29(周五) 盘后决策 → 收益起算跳过 09-01 劳动节，落 09-02 开盘
    eff = next_open_after(_dts("2025-08-29 18:00"))
    assert eff == _dts("2025-09-02 09:30").tz_convert("UTC")

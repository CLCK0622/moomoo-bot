"""
门禁单测：证明每道门都能抓住它该抓的失败模式（别只留在纸面口径）。

从 repo 根跑：  python3 -m research.gate.tests.test_gate
无 pytest 依赖，纯 assert + 打印，非 0 退出即失败。
"""
import math

import numpy as np
import pandas as pd

from research.gate import (Candidate, GateThresholds, OOSBudget,
                           OOSBudgetExceeded, TrialLedger, capacity_gate,
                           certify, cost_stress_gate, cpcv_splits,
                           deflated_sharpe_ratio, economic_rationale_gate,
                           evaluate, expected_max_sharpe, freeze_config,
                           joint_gate, cagr, max_drawdown, verify_unchanged,
                           validate_prereg_completeness, walk_forward_splits)
from research.gate.trial_ledger import HonestyError

PASS = 0


def check(name, cond):
    global PASS
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    assert cond, f"ASSERTION FAILED: {name}"
    PASS += 1


def _sinusoid_returns(mean, amp, n=1008, period=3.0):
    """确定性、平滑、总在回升的净收益序列 —— 无 RNG，测试可复现。"""
    idx = np.arange(n)
    return mean + amp * np.sin(idx / period)


def _dates(n=1008, start="2018-01-01"):
    return pd.bdate_range(start=start, periods=n)


# ---------------- 1. metrics: CAGR / MDD / 联合门 ----------------
def test_metrics():
    print("1) metrics —— CAGR/MDD/联合门")
    # 已知回撤：+10% 后 -50%（0.55/1.10-1 = -0.5）
    r = pd.Series([0.10, -0.50, 0.0, 0.0])
    check("MDD 已知序列 ≈ 0.5", abs(max_drawdown(r) - 0.5) < 1e-9)
    # 恒定日收益 → MDD=0，CAGR 正
    r2 = pd.Series([0.001] * 252)
    check("单调上行 MDD=0", max_drawdown(r2) == 0.0)
    check("恒定正收益 CAGR≈28.6%", abs(cagr(r2) - (1.001 ** 252 - 1)) < 1e-9)
    # 联合门：任一不过即 False
    check("联合门 CAGR过MDD不过 → False", joint_gate(0.6, 0.25, 0.5, 0.20) is False)
    check("联合门 双过 → True", joint_gate(0.6, 0.15, 0.5, 0.20) is True)
    # 决策标签
    rep_dp = evaluate(_sinusoid_returns(0.0012, 0.004), _dates())
    check("35%档 → DECISION_POINT（过影子未过官方）", rep_dp.decision == "DECISION_POINT")
    check("  官方门未过", rep_dp.official_pass is False)
    check("  影子上报门过", rep_dp.shadow_report_pass is True)
    rep_50 = evaluate(_sinusoid_returns(0.0017, 0.003), _dates())
    check("53%档 → REPORT_5020（直接清官方门）", rep_50.decision == "REPORT_5020")
    check("  危机子窗有单报字段", "2020_COVID" in rep_50.crisis)


# ---------------- 2. DSR: 多重检验 haircut ----------------
def test_dsr():
    print("2) DSR —— N 越大越难过（选择偏差 haircut）")
    r = _sinusoid_returns(0.0012, 0.004)
    s = pd.Series(r)
    sr_pp = s.mean() / s.std(ddof=1)
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurt()) + 3.0
    V = 0.176  # 试验 SR 方差（每期）
    d1 = deflated_sharpe_ratio(sr_pp, len(r), skew, kurt, n_trials=1, trials_variance=V)
    d5000 = deflated_sharpe_ratio(sr_pp, len(r), skew, kurt, n_trials=5000, trials_variance=V)
    check("N=1 → DSR 高、通过", d1.passed and d1.dsr > 0.95)
    check("N=5000 → DSR 低、拒绝", (not d5000.passed) and d5000.dsr < 0.5)
    check("期望最大 SR 随 N 单调增", expected_max_sharpe(5000, V) > expected_max_sharpe(10, V) > 0)
    # 拿不到 V → 报错（要求 miner 吐全量试验 SR）
    raised = False
    try:
        deflated_sharpe_ratio(sr_pp, len(r), skew, kurt, n_trials=100)
    except ValueError:
        raised = True
    check("无 V → 拒绝计算 DSR（逼 miner 吐全量 N）", raised)


# ---------------- 3. trial_ledger: 诚实计数 ----------------
def test_ledger():
    print("3) trial_ledger —— 诚实试验计数（地基）")
    led = TrialLedger(path=None)
    raised = False
    try:
        led.register_run("r0", "qlib", n_trials_total=None, n_evaluated=3)
    except HonestyError:
        raised = True
    check("未声明全量 N → HonestyError", raised)
    raised = False
    try:
        led.register_run("r1", "qlib", n_trials_total=5, n_evaluated=10)
    except HonestyError:
        raised = True
    check("声明 N 小于实际评估数 → HonestyError", raised)
    led.register_run("r2", "qlib", n_trials_total=158, n_evaluated=3,
                     trial_sharpes=[0.1, -0.2, 0.05], now_iso="2026-07-29T00:00:00Z")
    led.register_run("r3", "rd-agent", n_trials_total=400, n_evaluated=2,
                     trial_sharpes_var=0.02, now_iso="2026-07-29T00:00:00Z")
    check("跨轮累计 N = 158+400 = 558", led.cumulative_n() == 558)
    check("加权试验方差可得", led.pooled_trials_variance() is not None)


# ---------------- 4. walk_forward: purge/embargo/CPCV/OOS 预算 ----------------
def test_walk_forward():
    print("4) walk_forward —— 样本外纪律")
    splits = walk_forward_splits(n_obs=100, n_splits=4, label_horizon=1, embargo=0)
    check("前进式 4 段", len(splits) == 4)
    tr, te = splits[1]
    check("train 全在 test 之前（无未来泄漏）", tr.max() < te.min())
    # purge+embargo：test 边界附近 train 被剔除
    tr0 = set(walk_forward_splits(100, 4, label_horizon=5, embargo=5)[1][0])
    tr_np = set(walk_forward_splits(100, 4, label_horizon=0, embargo=0)[1][0])
    check("label_horizon+embargo 剔掉更多 train", len(tr0) < len(tr_np))
    # CPCV：C(5,2)=10
    cp = cpcv_splits(n_obs=100, n_groups=5, n_test_groups=2)
    check("CPCV C(5,2)=10 个 split", len(cp) == 10)
    # OOS 单发预算
    b = OOSBudget(max_evals=1)
    b.consume("cand-A")
    raised = False
    try:
        b.consume("cand-A")
    except OOSBudgetExceeded:
        raised = True
    check("同一 key 第二次偷看 OOS → 拒绝", raised)


# ---------------- 5. cost / capacity ----------------
def test_cost_capacity():
    print("5) cost_capacity —— 成本 x1x2 + 容量早筛")
    # 有 edge、低换手 → x1 过
    good = cost_stress_gate(_sinusoid_returns(0.0010, 0.003), [0.1] * 1008, 0.0005)
    check("低成本有 edge → x1 早筛存活", good.passed_early)
    # edge 薄、高换手 → 成本吃光 → x1 挂
    bad = cost_stress_gate(_sinusoid_returns(0.0002, 0.01), [2.0] * 1008, 0.0005)
    check("高换手薄 edge → x1 净 Sharpe<=0 早杀", not bad.passed_early)
    # 容量
    check("参与率超上限 → 拒", capacity_gate(2_000_000, 10_000_000, 0.10).passed is False)
    check("参与率合规 → 过", capacity_gate(500_000, 10_000_000, 0.10).passed is True)


# ---------------- 6. prereg ----------------
def test_prereg():
    print("6) prereg —— 冻结 + 经济理由门")
    cfg = {"universe": ["AAPL"], "leverage_cap": 2.0, "signal_params": {"lb": 60},
           "rebalance": "monthly", "cost_model": "x1", "train_test_split": "2019-12-31",
           "gate_thresholds": "50/20"}
    h = freeze_config(cfg)
    check("同配置同哈希（可复现）", h == freeze_config(dict(reversed(list(cfg.items())))))
    cfg2 = dict(cfg); cfg2["signal_params"] = {"lb": 20}
    check("事后改参数 → 哈希不符被抓", verify_unchanged(h, cfg2).unchanged is False)
    check("缺预注册键被抓", validate_prereg_completeness({"universe": []}))
    check("无经济理由 → 隔离", economic_rationale_gate("太短").quarantined is True)
    check("有充分理由 → 接受", economic_rationale_gate(
        "动量溢价：横截面与时序趋势兼具行为（处置效应/羊群）与风险（增长期权）解释，长期稳健。").accepted)


# ---------------- 7. gate.certify 端到端 ----------------
def _base_cfg():
    return {"universe": ["SPY", "EFA", "AGG"], "leverage_cap": 2.0,
            "signal_params": {"lookback": 252}, "rebalance": "monthly",
            "cost_model": "moomoo_retail_x1", "train_test_split": "2017-12-31",
            "gate_thresholds": "official_50_20+shadow"}


def test_certify_end_to_end():
    print("7) certify —— 端到端")
    dates = _dates()
    good_oos = _sinusoid_returns(0.0012, 0.004)         # ~35% CAGR, 小 MDD
    gross = _sinusoid_returns(0.0014, 0.004)
    turnover = [0.1] * len(good_oos)
    cfg = _base_cfg(); h = freeze_config(cfg)
    rationale = ("动量/趋势溢价：有横截面与时序证据，行为(处置效应/羊群)与风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘。")

    # 7a 正常候选 → certified, DECISION_POINT
    cand = Candidate(name="dual_momentum", oos_net_returns=good_oos, oos_dates=dates,
                     gross_returns=gross, turnover=turnover, cost_per_turnover=0.0005,
                     prereg_config=cfg, frozen_hash=h, economic_rationale=rationale,
                     n_trials_cumulative=1, trials_variance=0.176)
    v = certify(cand, oos_budget=OOSBudget(1))
    check("正常候选 → certified", v.certified is True)
    check("  decision=DECISION_POINT", v.decision == "DECISION_POINT")

    # 7b 同候选但跨轮累计 N=5000 → REJECTED_dsr（伪 alpha 嫌疑）
    cand_b = Candidate(name="dm_overmined", oos_net_returns=good_oos, oos_dates=dates,
                       gross_returns=gross, turnover=turnover, prereg_config=cfg,
                       frozen_hash=h, economic_rationale=rationale,
                       n_trials_cumulative=5000, trials_variance=0.176)
    vb = certify(cand_b, oos_budget=OOSBudget(1))
    check("N=5000 → REJECTED_dsr", vb.decision == "REJECTED_dsr" and not vb.certified)

    # 7c 缺预注册键 → REJECTED_prereg
    cand_c = Candidate(name="no_prereg", oos_net_returns=good_oos, oos_dates=dates,
                       prereg_config={"universe": []}, economic_rationale=rationale,
                       n_trials_cumulative=1, trials_variance=0.176)
    check("缺预注册键 → REJECTED_prereg",
          certify(cand_c).decision == "REJECTED_prereg")

    # 7d 无经济理由 → REJECTED_rationale
    cand_d = Candidate(name="no_rationale", oos_net_returns=good_oos, oos_dates=dates,
                       gross_returns=gross, turnover=turnover, prereg_config=cfg,
                       frozen_hash=h, economic_rationale="", n_trials_cumulative=1,
                       trials_variance=0.176)
    check("无经济理由 → REJECTED_rationale",
          certify(cand_d).decision == "REJECTED_rationale")

    # 7e 高换手薄 edge → REJECTED_cost
    cand_e = Candidate(name="high_cost", oos_net_returns=good_oos, oos_dates=dates,
                       gross_returns=_sinusoid_returns(0.0002, 0.01),
                       turnover=[2.0] * len(good_oos), cost_per_turnover=0.0005,
                       prereg_config=cfg, frozen_hash=h, economic_rationale=rationale,
                       n_trials_cumulative=1, trials_variance=0.176)
    check("高成本 → REJECTED_cost", certify(cand_e).decision == "REJECTED_cost")

    # 7f miner 不吐 N（无累计、无 ledger）→ REJECTED_honesty
    cand_f = Candidate(name="no_N", oos_net_returns=good_oos, oos_dates=dates,
                       gross_returns=gross, turnover=turnover, prereg_config=cfg,
                       frozen_hash=h, economic_rationale=rationale,
                       n_trials_cumulative=None, trials_variance=0.176)
    check("无真实 N → REJECTED_honesty", certify(cand_f).decision == "REJECTED_honesty")


def main():
    for t in (test_metrics, test_dsr, test_ledger, test_walk_forward,
              test_cost_capacity, test_prereg, test_certify_end_to_end):
        t()
    print(f"\nALL PASSED — {PASS} checks green.")


if __name__ == "__main__":
    main()

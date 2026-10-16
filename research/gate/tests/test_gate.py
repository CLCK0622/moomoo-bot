"""
门禁单测：证明每道门都能抓住它该抓的失败模式（别只留在纸面口径）。

从 repo 根跑：  python3 -m research.gate.tests.test_gate
无 pytest 依赖，纯 assert + 打印，非 0 退出即失败。
"""
import json
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
            "gate_thresholds": "official_50_20+shadow",
            "paradigm": "quant",          # 范式必填（工部 2026-08-08）：漏写不再静默跳过 LLM 三关
            "family": ["lookback=252"]}   # 定义 V 的冻结试验族（此处单格）


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


# ---------- 8. fail-open 收口：自报 N/V 不得压过持久台账（工部实测复现） ----------
def test_selfreport_cannot_undercut_ledger():
    print("8) 台账地板 —— 自报 N/V 只能更严不能更松")
    dates = _dates()
    good_oos = _sinusoid_returns(0.0012, 0.004)
    cfg = _base_cfg(); h = freeze_config(cfg)
    rationale = ("动量/趋势溢价：横截面与时序证据，行为(处置效应/羊群)+风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘。")

    # 台账诚实记着 5000 次试验
    led = TrialLedger(path=None)
    led.register_run("qlib-miner", "qlib", n_trials_total=5000, n_evaluated=1,
                     trial_sharpes_var=0.176, now_iso="2026-07-29T00:00:00Z")

    def mk(**kw):
        base = dict(name="dm", oos_net_returns=good_oos, oos_dates=dates,
                    gross_returns=_sinusoid_returns(0.0014, 0.004),
                    turnover=[0.1] * len(good_oos), cost_per_turnover=0.0005,
                    prereg_config=cfg, frozen_hash=h, economic_rationale=rationale)
        base.update(kw)
        return Candidate(**base)

    # 8a 工部复现：台账 5000 + 候选自报 N=1 → 必须 HonestyError（旧版是 certified=True）
    raised = False
    try:
        certify(mk(n_trials_cumulative=1, trials_variance=0.176), ledger=led,
                oos_budget=OOSBudget(1))
    except HonestyError:
        raised = True
    check("台账5000 + 自报N=1 → HonestyError（fail-open 已堵）", raised)

    # 8b 正确用法：候选不自报 N，门自台账取 5000 → REJECTED_dsr（不抛，正常驳回）
    vb = certify(mk(n_trials_cumulative=None, trials_variance=0.176), ledger=led,
                 oos_budget=OOSBudget(1))
    check("台账5000 + 自报None → REJECTED_dsr", vb.decision == "REJECTED_dsr")
    check("  用的是台账 N=5000", vb.gates.get("n_trials") == 5000)
    # verdict 自带 N 的可审计出处（都察院复核 cumulative_n 来源，不依赖 gitignore 台账文件）
    prov = vb.gates.get("ledger_provenance")
    check("  verdict 带 ledger_provenance（可审计 N 出处）",
          prov is not None and prov["cumulative_n"] == 5000 and prov["n_runs"] == 1)

    # 8c 自报 N ≥ 台账（更严）→ 不抛，取 max
    vc = certify(mk(n_trials_cumulative=8000, trials_variance=0.176), ledger=led,
                 oos_budget=OOSBudget(1))
    check("自报N=8000≥台账 → 取 max=8000、不抛", vc.gates.get("n_trials") == 8000)

    # 8d 手跑候选无台账、自报 N=2 → 正常采信（合法用途不受影响）
    vd = certify(mk(name="GEM", n_trials_cumulative=2, trials_variance=0.0),
                 oos_budget=OOSBudget(1))
    check("无台账手跑 N=2 → 正常评估（合法用途不误伤）", vd.gates.get("n_trials") == 2)

    # 8e 同类洞：台账 pooled V=0.176 作地板，候选自报极小 V=1e-9 不得压低基准
    led2 = TrialLedger(path=None)
    led2.register_run("m2", "qlib", n_trials_total=1000, n_evaluated=1,
                      trial_sharpes_var=0.176, now_iso="2026-07-29T00:00:00Z")
    ve = certify(mk(n_trials_cumulative=None, trials_variance=1e-9), ledger=led2,
                 oos_budget=OOSBudget(1))
    check("台账V地板生效：自报 V=1e-9 仍 REJECTED_dsr（tiny-V 放松已堵）",
          ve.decision == "REJECTED_dsr")


# ---------- 9. fail-open 收口二：成本以冻结 cost_model 为地板（工部实测复现） ----------
def test_cost_model_is_floor():
    print("9) 成本地板 —— 自报成本不得低于冻结 cost_model")
    dates = _dates()
    good_oos = _sinusoid_returns(0.0012, 0.004)
    # 毛收益均值 0.0003 < 地板 10bps*turnover(1.0)=0.001 → 按地板算净 Sharpe<=0
    gross = _sinusoid_returns(0.0003, 0.004)
    to = [1.0] * len(good_oos)
    cfg = _base_cfg(); h = freeze_config(cfg)   # cost_model = moomoo_retail_x1
    rationale = ("动量/趋势溢价：横截面与时序证据，行为(处置效应/羊群)+风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘，非曲线拟合。")

    # 先证漏洞面存在：裸报 1e-7 成本 cost_stress 会放行，按地板 10bps 则杀
    from research.gate import cost_stress_gate as _csg
    check("裸报 cost=1e-7 → cost_stress 放行（漏洞面）", _csg(gross, to, 1e-7).passed_early)
    check("按地板 cost=10bps → cost_stress 杀", not _csg(gross, to, 0.001).passed_early)

    def mk(cost):
        return Candidate(name="dm", oos_net_returns=good_oos, oos_dates=dates,
                         gross_returns=gross, turnover=to, cost_per_turnover=cost,
                         required_notional=1e5, adv_notional=1e9,  # 容量充足，隔离成本门
                         prereg_config=cfg, frozen_hash=h, economic_rationale=rationale,
                         n_trials_cumulative=1, trials_variance=0.05)

    # 工部复现：自报 1e-7 → 旧版 certified；新版被地板抬到 10bps → REJECTED_cost
    v_tiny = certify(mk(1e-7), oos_budget=OOSBudget(1))
    check("自报 1e-7 → REJECTED_cost（地板生效）", v_tiny.decision == "REJECTED_cost")
    check("  生效成本被抬到地板 10bps", abs(v_tiny.gates["cost_per_turnover_effective"] - 0.001) < 1e-12)
    # 如实报 50bps → 仍 REJECTED_cost（自报更贵，取自报）
    v_honest = certify(mk(0.005), oos_budget=OOSBudget(1))
    check("自报 50bps → REJECTED_cost，生效取更贵 0.005",
          v_honest.decision == "REJECTED_cost" and
          abs(v_honest.gates["cost_per_turnover_effective"] - 0.005) < 1e-12)

    # 未登记的便宜成本模型标签 → REJECTED_prereg（不许蒙混）
    cfg_bad = _base_cfg(); cfg_bad["cost_model"] = "ultra_cheap_unlisted"
    vb = certify(Candidate(name="x", oos_net_returns=good_oos, oos_dates=dates,
                           gross_returns=gross, turnover=to, cost_per_turnover=1e-7,
                           prereg_config=cfg_bad, frozen_hash=freeze_config(cfg_bad),
                           economic_rationale=rationale, n_trials_cumulative=1,
                           trials_variance=0.05), oos_budget=OOSBudget(1))
    check("未登记成本模型标签 → REJECTED_prereg", vb.decision == "REJECTED_prereg")


# ---------- 10. fail-open 收口三：ADV 缺失≠放松（工部实测复现） ----------
def test_capacity_missing_is_not_pass():
    print("10) 容量地基 —— ADV 缺失不得静默跳过")
    dates = _dates()
    good_oos = _sinusoid_returns(0.0012, 0.004)
    cfg = _base_cfg(); h = freeze_config(cfg)
    rationale = ("动量/趋势溢价：横截面与时序证据，行为(处置效应/羊群)+风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘，非曲线拟合。")

    # miner 上下文：小 N 台账让候选过 DSR，从而暴露 step8 容量兜底
    led = TrialLedger(path=None)
    led.register_run("m", "qlib", n_trials_total=2, n_evaluated=1,
                     trial_sharpes_var=0.01, now_iso="2026-07-29T00:00:00Z")

    def mk(**kw):
        base = dict(name="dm", oos_net_returns=good_oos, oos_dates=dates,
                    gross_returns=_sinusoid_returns(0.0014, 0.004),
                    turnover=[0.1] * len(good_oos), cost_per_turnover=0.0005,
                    prereg_config=cfg, frozen_hash=h, economic_rationale=rationale,
                    n_trials_cumulative=None, trials_variance=None)
        base.update(kw)
        return Candidate(**base)

    # 10a miner 候选如实报 ADV 且需求超限 → REJECTED_capacity（正常门）
    va = certify(mk(required_notional=1e9, adv_notional=1e6), ledger=led,
                 oos_budget=OOSBudget(1))
    check("如实报 ADV 超限 → REJECTED_capacity", va.decision == "REJECTED_capacity")

    # 10b 工部复现：miner 候选**不报 ADV**（默认 0）→ 旧版 certified；新版 REJECTED_capacity
    vb = certify(mk(), ledger=led, oos_budget=OOSBudget(1))
    check("miner 不报 ADV → REJECTED_capacity（缺失≠放松）",
          vb.decision == "REJECTED_capacity" and not vb.certified)
    check("  已标记 capacity_unverified", vb.gates.get("capacity_unverified") is True)

    # 10c miner 候选如实报充足 ADV → 正常 certified
    vc = certify(mk(required_notional=1e5, adv_notional=1e9), ledger=led,
                 oos_budget=OOSBudget(1))
    check("如实报充足 ADV → certified", vc.certified and vc.decision == "DECISION_POINT")

    # 10d 无台账手跑候选（自报 N=2）不报 ADV → 不误伤：certified 但标记待人工复核
    vd = certify(mk(n_trials_cumulative=2, trials_variance=0.01),
                 oos_budget=OOSBudget(1))   # 无 ledger
    check("手跑候选不报 ADV → 仍 certified（合法用途不阻断）", vd.certified)
    check("  但打上 capacity_unverified 待都察院人工核", vd.gates.get("capacity_unverified") is True)


# ---------- 11. 台账跨轮真累计 + 持久化 + 幂等去重（工部实测：账本累计不起来） ----------
def test_ledger_accumulates_and_persists():
    print("11) 共享台账 —— 跨候选累计 / 持久 / 幂等")
    import os
    import tempfile
    from research.gate.trial_ledger import DEFAULT_LEDGER_PATH
    d = tempfile.mkdtemp()
    p = os.path.join(d, "shared.jsonl")

    l1 = TrialLedger(p)
    l1.register_run("residmom", "qlib", n_trials_total=4, n_evaluated=1,
                    now_iso="2026-07-29T00:00:00Z")
    l1.register_run("multifactor", "qlib", n_trials_total=158, n_evaluated=3,
                    trial_sharpes_var=0.03, now_iso="2026-07-29T00:00:00Z")
    check("同一共享台账跨候选累计 = 4+158 = 162", l1.cumulative_n() == 162)

    # 持久化：重开同文件仍在（换分支/进程/机器不归零）
    l2 = TrialLedger(p)
    check("重开同文件持久 = 162（不归零）", l2.cumulative_n() == 162)

    # 幂等：重登记同 run_id 不重复计数
    l2.register_run("residmom", "qlib", n_trials_total=4, n_evaluated=1,
                    now_iso="2026-07-29T00:00:00Z")
    check("重登记同 run_id → 不双计，仍 162", l2.cumulative_n() == 162)

    # 去重：文件里混入重复行，加载按 run_id 去重
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"run_id":"residmom","source":"qlib","n_trials_total":4,'
                '"n_evaluated":1,"trial_sharpes_var":null,"note":"dup","ts":"x"}\n')
    l3 = TrialLedger(p)
    check("加载对重复行按 run_id 去重 → 仍 162", l3.cumulative_n() == 162)

    # 反例（工部实测的坏味道）：按候选各建文件 → 各自只看得见本轮
    pa = os.path.join(d, "residmom.jsonl"); pb = os.path.join(d, "multifactor.jsonl")
    la = TrialLedger(pa); la.register_run("a", "qlib", n_trials_total=4, n_evaluated=1,
                                          now_iso="2026-07-29T00:00:00Z")
    lb = TrialLedger(pb); lb.register_run("b", "qlib", n_trials_total=158, n_evaluated=3,
                                          now_iso="2026-07-29T00:00:00Z")
    check("分文件的坏味道：各自 cumulative 只等本轮（4 / 158，不累计）",
          la.cumulative_n() == 4 and lb.cumulative_n() == 158)

    # rmtree 而非 rmdir：加了跨进程互斥后，state_lock 会在同目录留下 <path>.lock，rmdir 要求空目录会失败
    import shutil
    shutil.rmtree(d, ignore_errors=True)

    # 已入库的规范历史基线在位（cumulative_n 有真实历史下限，非本轮 0）
    if os.path.exists(DEFAULT_LEDGER_PATH):
        seeded = TrialLedger(DEFAULT_LEDGER_PATH)
        check("规范台账历史基线已入库（cumulative_n>=14）", seeded.cumulative_n() >= 14)


# ---------- 12. DSR 单位契约：年化 V 不静默误杀（工部实测复现，假阴性方向） ----------
def test_dsr_unit_scale():
    print("12) DSR 单位契约 —— 年化 V 归一/打旗，不误杀真 alpha")
    sr, n_obs, N = 0.04241, 4662, 27      # 工部复现参数
    skew, kurt = 0.0, 3.0
    V_ann, V_pp = 0.027843, 0.00011049    # 年化 V（错）/ 每期 V（对）

    # 现状：年化 V 当每期用 → expected_max 被 √252 抬高、DSR≈0（真 alpha 会被冤杀）
    wrong = deflated_sharpe_ratio(sr, n_obs, skew, kurt, n_trials=N, trials_variance=V_ann)
    check("年化 V 未声明 → expected_max≈0.339（被抬高）", abs(wrong.expected_max_sr - 0.339) < 0.01)
    check("  → DSR≈0（真 alpha 会被误杀）", wrong.dsr < 0.01)
    check("  → scale_warning 打旗（单位不一致不静默）", wrong.scale_warning is True)

    # 声明 ppy=252 归一 → 与直接传每期 V 一致，DSR 回到擦边真值
    fixed = deflated_sharpe_ratio(sr, n_obs, skew, kurt, n_trials=N,
                                  trials_variance=V_ann, trials_periods_per_year=252)
    check("声明 ppy=252 归一 → expected_max≈0.0213", abs(fixed.expected_max_sr - 0.0213) < 0.005)
    check("  → DSR≈0.92（擦边、仍<0.95 被拒，但不再被 15.9× 冤杀）", 0.88 < fixed.dsr < 0.95)
    check("  → scale_warning 清除", fixed.scale_warning is False)

    direct = deflated_sharpe_ratio(sr, n_obs, skew, kurt, n_trials=N, trials_variance=V_pp)
    check("每期 V 与归一后 expected_max 一致",
          abs(direct.expected_max_sr - fixed.expected_max_sr) < 1e-6)


def test_ppy_is_not_a_free_knob():
    """工部 2026-07-30：ppy 是反方向的 fail-open（多报 → V 被重复归一 → 门变松）。
    硬门：声明值须与收益序列实测频率相符。软旗：双侧，放松那一侧必须打旗。"""
    print("13) ppy 反方向护栏（过报 ppy 不得静默放松门）")
    sr, n_obs, skew, kurt, N = 0.04241118830323271, 4662, -0.7858373485840723, 12.331362454271403, 29
    V_pp = 0.027843 / 252

    ok = deflated_sharpe_ratio(sr, n_obs, skew, kurt, n_trials=N, trials_variance=V_pp)
    check("每期 V 不声明 ppy → 无旗、DSR<0.95 判拒", ok.scale_warning is False and not ok.passed)

    abuse = deflated_sharpe_ratio(sr, n_obs, skew, kurt, n_trials=N,
                                  trials_variance=V_pp, trials_periods_per_year=252)
    check("每期 V 却声明 ppy=252 → 打旗（放松侧不得静默）", abuse.scale_warning is True)
    check("  → 旗文点明是重复归一/过松", "过松" in abuse.scale_note)

    stale = deflated_sharpe_ratio(sr, n_obs, skew, kurt, n_trials=N, trials_variance=0.027843)
    check("年化 V 未归一 → 仍打旗（过严侧）", stale.scale_warning is True and "过严" in stale.scale_note)

    dates = _dates()
    oos = _sinusoid_returns(0.0012, 0.004)
    gross = _sinusoid_returns(0.0014, 0.004)
    cfg = _base_cfg(); h = freeze_config(cfg)
    rationale = ("动量/趋势溢价：有横截面与时序证据，行为(处置效应/羊群)与风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘。")

    def mk(ppy):
        return Candidate(name="ppy", oos_net_returns=oos, oos_dates=dates, gross_returns=gross,
                         turnover=[0.1] * len(oos), cost_per_turnover=0.001,
                         adv_notional=1e9, required_notional=1e6, prereg_config=cfg,
                         frozen_hash=h, economic_rationale=rationale,
                         n_trials_cumulative=N, trials_variance=V_pp,
                         trials_periods_per_year=ppy)

    v_bad = certify(mk(10000), oos_budget=OOSBudget(1))
    check("ppy=10000 与实测日频不符 → REJECTED_prereg（频率门）", v_bad.decision == "REJECTED_prereg")
    # ppy=252 对日频序列通过**频率门**（252≈日频）；但此处 V 本就是每期，声明 ppy=252 → 重复归一
    # → 放松侧 → 被**尺度门**硬拒（户部 2026-07-30 裁定）。两门互补：频率门抓错频率，尺度门抓重复归一。
    v_daily = certify(mk(252), oos_budget=OOSBudget(1))
    check("ppy=252 过频率门但 V 已每期 → 放松侧 REJECTED_scale（硬拒，不静默放松）",
          v_daily.decision == "REJECTED_scale")


def test_family_must_be_frozen():
    """工部 2026-07-30(EVO-8 A)：定义 V 的 family 须冻结，不得事后挑紧（否则关掉多重检验罚）。"""
    print("14) family 冻结（V 不得事后挑紧）")
    dates = _dates()
    oos = _sinusoid_returns(0.0012, 0.004)
    gross = _sinusoid_returns(0.0014, 0.004)
    rationale = ("动量/趋势溢价：横截面与时序证据，行为(处置效应/羊群)+风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘。")
    # 缺 family 键 → 完整性拒
    cfg_nofam = {k: v for k, v in _base_cfg().items() if k != "family"}
    v0 = certify(Candidate(name="nofam", oos_net_returns=oos, oos_dates=dates,
                           prereg_config=cfg_nofam, economic_rationale=rationale,
                           n_trials_cumulative=3, trials_variance=0.0002),
                 oos_budget=OOSBudget(1))
    check("缺 family 键 → REJECTED_prereg", v0.decision == "REJECTED_prereg")
    # family=3 格
    cfg = dict(_base_cfg()); cfg["family"] = ["c1", "c2", "c3"]; h = freeze_config(cfg)
    base = dict(oos_net_returns=oos, oos_dates=dates, gross_returns=gross,
                turnover=[0.1] * len(oos), cost_per_turnover=0.001,
                adv_notional=1e9, required_notional=1e6, prereg_config=cfg,
                frozen_hash=h, economic_rationale=rationale, n_trials_cumulative=3)
    v_short = certify(Candidate(name="shrunk", trial_sharpes=[0.03, 0.05], **base),
                      oos_budget=OOSBudget(1))
    check("family=3 却只用 2 个试验（事后挑紧）→ REJECTED_prereg", v_short.decision == "REJECTED_prereg")
    v_ok = certify(Candidate(name="full", trial_sharpes=[0.03, 0.05, 0.04], **base),
                   oos_budget=OOSBudget(1))
    check("family=3 且用满 3 个 → 不因 family 被拒", v_ok.decision != "REJECTED_prereg")


def test_pooled_v_independent_floor():
    """工部 2026-07-30：pooled V 要成为真兜底，须排除候选自己那轮 + 每条登记带 trial_sharpes。"""
    print("15) pooled V 独立地板（排除自身轮 + 须带 trial_sharpes）")
    led = TrialLedger(path=None)
    led.register_run("candA", "qlib", n_trials_total=3, n_evaluated=1,
                     trial_sharpes=[0.026, 0.024, 0.030], now_iso="2026-07-30T00:00:00Z")
    led.register_run("otherB", "qlib", n_trials_total=5, n_evaluated=1,
                     trial_sharpes=[0.10, -0.05, 0.20, 0.02, -0.12], now_iso="2026-07-30T00:00:00Z")
    indep = led.pooled_trials_variance(exclude_run_id="candA")   # 只由 otherB 构成
    own = led.pooled_trials_variance(exclude_run_id="otherB")    # 只由 candA 构成
    check("排除自身轮 → pooled 来自其它轮（独立地板）",
          indep is not None and own is not None and abs(indep - own) > 1e-6)
    check("有独立 V", led.has_independent_v("candA") is True)
    # 退化：历史条目没带 trial_sharpes → 无独立 V
    led2 = TrialLedger(path=None)
    led2.register_run("candA", "qlib", n_trials_total=3, n_evaluated=1,
                      trial_sharpes=[0.026, 0.024, 0.030], now_iso="2026-07-30T00:00:00Z")
    led2.register_run("hist", "manual", n_trials_total=7, n_evaluated=7,
                      now_iso="2026-07-30T00:00:00Z")   # 无 trial_sharpes
    check("历史条目无 trial_sharpes → 无独立 V（地板退化）",
          led2.has_independent_v("candA") is False)
    check("排除自身后 pooled=None（无其它带 V 轮次）",
          led2.pooled_trials_variance(exclude_run_id="candA") is None)


def test_oos_budget_persists():
    """工部 2026-07-30 第八种 fail-open：单发 OOS 预算不落盘 → 每 run 一张新票、跨 run 形同虚设。"""
    print("16) 单发 OOS 预算跨 run 持久")
    import os
    import tempfile
    from research.gate.walk_forward import OOSBudget as _OB
    d = tempfile.mkdtemp(); p = os.path.join(d, "oos.json")
    b1 = _OB(max_evals=1, path=p)
    b1.consume("candK")
    raised = False
    try:
        b1.consume("candK")
    except OOSBudgetExceeded:
        raised = True
    check("进程内第 2 次 consume → 拦", raised)
    # 新建（模拟新 run/新进程）读同一落盘文件 → 仍已用尽（跨 run 守住单发）
    b2 = _OB(max_evals=1, path=p)
    check("新建预算读同文件 → used=1（跨 run 持久）", b2.used("candK") == 1)
    raised = False
    try:
        b2.consume("candK")
    except OOSBudgetExceeded:
        raised = True
    check("  跨 run 第 2 次 → 拦（不再白拿新票）", raised)
    # 对照坏味道：不落盘 → 新建又发新票
    b3 = _OB(max_evals=1); b3.consume("x")
    check("不落盘 → 新建又发新票（坏味道对照，used=0）", _OB(max_evals=1).used("x") == 0)
    import shutil; shutil.rmtree(d, ignore_errors=True)  # lock 文件同目录, rmdir 要空目录


def test_refreeze_guard():
    """工部 2026-07-30(EVO-8 A)：run_id 内嵌 commit，重冻换 key 绕过幂等 → 同候选计两遍。"""
    print("17) 重冻护栏（同候选换 prereg commit 不得重复计数）")
    from research.gate.trial_ledger import RefreezeError as _RF
    led = TrialLedger(path=None)
    led.register_run("carry_A-5d25064", "qlib", n_trials_total=3, n_evaluated=1,
                     candidate_id="carry_rates_A", trial_sharpes=[0.02, 0.03, 0.04],
                     now_iso="2026-07-30T00:00:00Z")
    check("首登 cumulative_n=3", led.cumulative_n() == 3)
    raised = False
    try:
        led.register_run("carry_A-16be273", "qlib", n_trials_total=3, n_evaluated=1,
                         candidate_id="carry_rates_A", trial_sharpes=[0.02, 0.03, 0.04],
                         now_iso="2026-07-30T00:00:00Z")
    except _RF:
        raised = True
    check("重冻未声明 supersedes → RefreezeError", raised)
    check("  台账未被追加，仍 3（没有 N=6 重复计数）", led.cumulative_n() == 3)
    led.register_run("carry_A-16be273", "qlib", n_trials_total=3, n_evaluated=1,
                     candidate_id="carry_rates_A", trial_sharpes=[0.02, 0.03, 0.04],
                     supersedes="carry_A-5d25064", now_iso="2026-07-30T00:00:00Z")
    check("声明 supersedes → 覆盖计一次，仍 3", led.cumulative_n() == 3)
    check("  台账只剩新 run_id", [r.run_id for r in led.runs] == ["carry_A-16be273"])
    led.register_run("newcand-abc", "qlib", n_trials_total=5, n_evaluated=1,
                     candidate_id="new_candidate", now_iso="2026-07-30T00:00:00Z")
    check("不同 candidate_id → 真新试验、累计 3+5=8", led.cumulative_n() == 8)


def test_sleeve_verdict():
    """sleeve 组合级判据：净正 + 低/负相关 + 组合级正贡献（standalone 负≠sleeve 负）。"""
    print("18) sleeve 组合级判据（分散/回撤控制腿）")
    from research.gate.sleeve_eval import sharpe_improves, sleeve_verdict
    n = 2000
    t = np.arange(n)
    book = pd.Series(0.0006 + 0.010 * np.sin(t / 5.0),
                     index=pd.bdate_range("2010-01-01", periods=n))   # 有回撤的库存腿
    cand = pd.Series(0.0004 - 0.010 * np.sin(t / 5.0), index=book.index)  # 净正 + 负相关对冲腿
    check("加负相关腿改善组合 Sharpe（判据式）", sharpe_improves(cand, book))
    v = sleeve_verdict(cand, {"BOOK": book})
    check("  净正", v["criteria"]["net_positive"])
    check("  低/负相关", v["criteria"]["low_corr"])
    check("  组合级正贡献（降 MDD 升 MAR）", v["criteria"]["positive_contribution"])
    check("  → sleeve_pass=True", v["sleeve_pass"] is True)
    # 正相关同向腿：不满足低相关 → sleeve 判负（对照）
    same = pd.Series(0.0004 + 0.010 * np.sin(t / 5.0), index=book.index)
    v2 = sleeve_verdict(same, {"BOOK": book})
    check("正相关同向腿 → 低相关不满足、sleeve_pass=False", v2["sleeve_pass"] is False)


def _oos_worker(args):
    """子进程：屏障同步后争抢同一 key 的 OOS 额度。返回 'GOT'/'BLOCKED'。"""
    path, key, t0 = args
    import time as _t
    from research.gate.walk_forward import OOSBudget, OOSBudgetExceeded
    while _t.time() < t0:
        pass
    try:
        OOSBudget(max_evals=1, path=path).consume(key)
        return "GOT"
    except OOSBudgetExceeded:
        return "BLOCKED"


def _ledger_worker(args):
    """子进程：屏障同步后并发登记各自的一轮试验。"""
    path, i, t0 = args
    import time as _t
    from research.gate.trial_ledger import TrialLedger
    while _t.time() < t0:
        pass
    TrialLedger(path).register_run(f"run-{i}", "qlib", n_trials_total=10, n_evaluated=1,
                                   trial_sharpes=[0.01 * i, 0.02 * i, 0.03 * i],
                                   candidate_id=f"c{i}")
    return i


def test_concurrent_writers_are_atomic():
    """都察院终审必修 2（工部 2026-07-30）：共享状态的并发原子性。

    修复前实测（10 进程同刻）：OOS **10 个全部拿到票**（应 1）、台账仅 3 行落盘且 1 行可解析
    （9 条试验消失 + 文件写坏）。两者都往放松方向失效。此测用**真实多进程**竞争守住回归。
    """
    print("19) 并发原子性 —— 真实多进程竞争（OOS 单发 / 台账不丢不坏）")
    import multiprocessing as mp
    import tempfile
    import time as _t

    import shutil
    ctx = mp.get_context("spawn")   # macOS 默认；显式声明避免 fork 假象
    n = 10
    d = tempfile.mkdtemp()          # 不用 TemporaryDirectory：锁文件会和自动清理抢，teardown 报 Errno 66
    try:
        oos_path = f"{d}/oos.json"
        t0 = _t.time() + 3.0
        with ctx.Pool(n) as p:
            res = p.map(_oos_worker, [(oos_path, "cand-X", t0)] * n)
        check(f"OOS max_evals=1 下 {n} 进程并发 → 恰好 1 个 GOT",
              res.count("GOT") == 1)
        check(f"  其余 {n-1} 个全部 BLOCKED", res.count("BLOCKED") == n - 1)

        led_path = f"{d}/led.jsonl"
        t0 = _t.time() + 3.0
        with ctx.Pool(n) as p:
            p.map(_ledger_worker, [(led_path, i, t0) for i in range(1, n + 1)])
        rows = [json.loads(l) for l in open(led_path, encoding="utf-8") if l.strip()]
        check(f"台账 {n} 进程并发登记 → {n} 条全部落盘（不丢写）", len(rows) == n)
        check("  cumulative_n = 10×10 = 100（N 不被低估→ DSR 不被放松）",
              sum(r["n_trials_total"] for r in rows) == 100)
        check("  文件逐行均可解析（不被交错写坏）",
              all(isinstance(r, dict) and "run_id" in r for r in rows))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_capital_efficiency():
    """吏部 07-30 EVO-8(i)：事件/稀疏腿按在险资金判 edge，不被现金拖累误杀；暴露须预注册+核验。"""
    print("19) 事件类资金效率口径（edge 轴，非现金稀释）")
    from research.gate.capital_efficiency import (EventExposureSpec,
                                                  capital_efficiency_report, verify_exposure)
    n = 2520
    idx = pd.bdate_range("2014-01-01", periods=n)
    act = np.arange(0, n, 10)                       # 每 10 日一次事件，~10% 在险
    exp = np.zeros(n); exp[act] = 1.0
    spec = EventExposureSpec(active_rule="每10个交易日一次事件窗", expected_fraction=len(act) / n)

    # 暴露核验：一致 ok / 事后挑小 f 不 ok / 超杠杆不 ok
    check("暴露与预注册一致 → ok", verify_exposure(exp, spec).ok)
    check("事后谎报大 f（实测远小）→ 拒",
          verify_exposure(exp, EventExposureSpec("x", expected_fraction=0.8)).ok is False)
    exp_lev = exp.copy(); exp_lev[act[0]] = 3.0
    check("在险杠杆超 2x → 拒", verify_exposure(exp_lev, spec).ok is False)

    # 真 edge 的稀疏腿：全额 CAGR 被现金稀释，但 active edge 正、edge_confirmed True
    ret = np.zeros(n); ret[act] = 0.003 + 0.002 * np.sin(np.arange(len(act)))
    rep = capital_efficiency_report(ret, exp, spec, dates=idx, n_trials=1,
                                    trials_variance=0.0004, cost_per_active_x1=0.0002)
    check("暴露核验通过", rep.exposure.ok)
    check("active edge 为正", rep.edge_per_active > 0)
    check("edge_confirmed（正+扛x2成本+过DSR, N=1）", rep.edge_confirmed is True)
    check("active edge Sharpe > 全额资金 Sharpe（现金拖累 ~√f 被去除）",
          rep.active_sharpe_ann > rep.full_sharpe_ann)

    # 无 edge（负）的稀疏腿（如 B FOMC）→ edge_confirmed False
    ret_neg = np.zeros(n); ret_neg[act] = -0.001 + 0.002 * np.sin(np.arange(len(act)))
    rep_neg = capital_efficiency_report(ret_neg, exp, spec, dates=idx, n_trials=1,
                                        trials_variance=0.0004, cost_per_active_x1=0.0002)
    check("负 edge 稀疏腿 → edge_confirmed False", rep_neg.edge_confirmed is False)

    # 暴露不符（谎报大 f）→ 即便 active edge 正也 edge_confirmed False（反 fail-open）
    rep_abuse = capital_efficiency_report(
        ret, exp, EventExposureSpec("x", expected_fraction=0.8),
        dates=idx, n_trials=1, trials_variance=0.0004, cost_per_active_x1=0.0002)
    check("暴露不符 → 正 edge 也不背书（反事后挑 f）", rep_abuse.edge_confirmed is False)


def test_dsr_machine_scale():
    """吏部 07-30：机器挖＝N 暴涨。跨轮累计真 N 的 DSR haircut 须在机器体量下数值稳定并咬得住。"""
    print("20) DSR 机器体量 haircut（N 暴涨仍稳、仍咬）")
    sr, n_obs, V = 0.05, 3000, 0.0004        # 温和的每期 edge
    d1 = deflated_sharpe_ratio(sr, n_obs, 0.0, 3.0, n_trials=1, trials_variance=V)
    dmach = deflated_sharpe_ratio(sr, n_obs, 0.0, 3.0, n_trials=100000, trials_variance=V)
    check("温和 edge 单假设 N=1 → 过", d1.passed)
    check("机器体量 N=1e5 → haircut 判拒（选择偏差压过温和 edge）", not dmach.passed)
    em = expected_max_sharpe(100000, V)
    check("期望最大 SR 在 N=1e5 有限且随 N 增大", 0 < em < 1 and em > expected_max_sharpe(1000, V))


def test_llm_contamination():
    """吏部 08-08 新范式：LLM 前视/污染是结构性坑——历史回放且 cutoff 覆盖评测窗 → 不得作验收证据。"""
    print("21) LLM 范式·污染/前视门")
    from research.gate.llm_paradigm import (admissibility_check,
                                            validate_decision_log)
    # 历史回放：cutoff 覆盖评测窗 → 不可验收（只能当生成器）
    a = admissibility_check("historical_replay", "2023-01-01", model_training_cutoff="2025-06-01")
    check("历史回放 + cutoff 覆盖评测窗 → 不可作验收证据", a.admissible is False)
    check("  理由点明结构性污染", "污染" in a.reason)
    # cutoff 严格早于窗 → 可验收
    b = admissibility_check("historical_replay", "2026-01-01", model_training_cutoff="2024-06-01")
    check("cutoff 严格早于评测窗 → 可验收", b.admissible is True)
    # cutoff 不可核 → 按污染处理（无据自报不采信）
    c = admissibility_check("historical_replay", "2023-01-01")
    check("cutoff 不可核 → 按污染处理、仅生成器", c.admissible is False)
    # 前向纸面跑：窗起点须在预注册冻结之后
    d = admissibility_check("forward_paper", "2026-08-10", prereg_frozen_at="2026-08-08")
    check("前向纸面跑（冻结后开跑）→ 可验收", d.admissible is True)
    e = admissibility_check("forward_paper", "2026-07-01", prereg_frozen_at="2026-08-08")
    check("窗起点早于冻结 → 非真前向、不可验收", e.admissible is False)
    # 决策日志时序
    ok_log = [{"evidence_max_ts": "2026-08-08T09:00", "decision_ts": "2026-08-08T10:00",
               "effective_from": "2026-08-09"}]
    check("合规决策日志 → ok", validate_decision_log(ok_log).ok is True)
    bad1 = [{"evidence_max_ts": "2026-08-08T11:00", "decision_ts": "2026-08-08T10:00",
             "effective_from": "2026-08-09"}]
    check("证据晚于决策（前视）→ 抓住", validate_decision_log(bad1).ok is False)
    bad2 = [{"evidence_max_ts": "2026-08-08T09:00", "decision_ts": "2026-08-08T10:00",
             "effective_from": "2026-08-07"}]
    check("收益起算早于决策（先看结果）→ 抓住", validate_decision_log(bad2).ok is False)


def test_llm_seeds_and_attribution():
    """随机性判保守分位（非最优 seed）；归因区分真 alpha 与 beta/风格暴露。"""
    print("22) LLM 范式·多 seed + 风格归因")
    from research.gate.llm_paradigm import (prescreen, seed_distribution,
                                            style_attribution, trials_from_seeds)
    vals = [0.02, 0.05, 0.09, 0.13, 0.31]          # 5 个 seed 的年化超额
    sr = seed_distribution(vals, quantile=0.25)
    check("判据取 25% 分位、不取最优 seed", sr.judged < sr.best and sr.judged <= sr.median)
    check("最优 seed 仅作参考", abs(sr.best - 0.31) < 1e-12)
    check("每 seed×prompt 变体均计入 N", trials_from_seeds(5, 3) == 15)

    n = 1500
    t = np.arange(n)
    mkt = 0.0004 + 0.010 * np.sin(t / 4.0)          # 市场因子（确定性、可复现）
    noise = 0.004 * np.sin(t / 7.0 + 1.1)           # 特质波动
    # (a) 纯 beta：1.5 倍市场，无 alpha → 控制后 alpha 不显著
    pure_beta = 1.5 * mkt + noise
    ra = style_attribution(pure_beta, {"MKT": mkt})
    check("纯 beta 策略 → 控制后 alpha 不显著（不算选股 alpha）", ra.alpha_significant is False)
    check("  beta≈1.5 被如实报出（高 beta 无处藏）", abs(ra.betas["MKT"] - 1.5) < 0.05)
    # (b) 真 alpha：同样 beta，但每期多 5bps
    true_alpha = 1.5 * mkt + noise + 0.0005
    rb = style_attribution(true_alpha, {"MKT": mkt})
    check("真 alpha 策略 → 控制后 alpha 显著", rb.alpha_significant is True)
    check("  alpha 年化≈12.6%", abs(rb.alpha_ann - 0.0005 * 252) < 0.02)

    # prescreen：污染模式即便有 alpha 也只判生成器级
    dec = [{"evidence_max_ts": "2026-08-08T09:00", "decision_ts": "2026-08-08T10:00",
            "effective_from": "2026-08-09"}]
    v = prescreen("historical_replay", "2023-01-01", dec, vals, true_alpha, {"MKT": mkt},
                  model_training_cutoff="2025-06-01", n_prompt_variants=2)
    check("污染模式 → evidence_grade=GENERATOR_ONLY", v.evidence_grade == "GENERATOR_ONLY")
    check("  即便 alpha 显著也不过预筛", v.passed_prescreen is False)
    check("  试验数 5×2=10 计入台账", v.trials_for_ledger == 10)
    v2 = prescreen("forward_paper", "2026-08-10", dec, vals, true_alpha, {"MKT": mkt},
                   prereg_frozen_at="2026-08-08")
    check("前向纸面 + 真 alpha → 过预筛（再送 certify）", v2.passed_prescreen is True)


def test_llm_prescreen_wired_into_certify():
    """吏部 08-08：三关必须由冻结预注册强制触发，不能做成"记得调才生效"的旁路。"""
    print("23) LLM 三关接线进 certify（非可选旁路）")
    n = 1200
    t = np.arange(n)
    dates = pd.bdate_range("2021-01-01", periods=n)
    mkt = 0.0004 + 0.010 * np.sin(t / 4.0)
    oos = 1.2 * mkt + 0.004 * np.sin(t / 7.0 + 1.1) + 0.0006     # 有真 alpha
    cfg = dict(_base_cfg()); cfg["paradigm"] = "llm_agent"
    h = freeze_config(cfg)
    rationale = ("LLM 定性范式：读公开财报/新闻做论点驱动选股，行为面信息处理速度差异，"
                 "非纯数据挖掘；证据按前向纸面跑累积。")
    dec = [{"evidence_max_ts": "2026-08-08T09:00", "decision_ts": "2026-08-08T10:00",
            "effective_from": "2026-08-09"}]
    seeds = [0.02, 0.05, 0.09, 0.13, 0.31]

    def mk(evidence, run_id=None):
        return Candidate(name="llm", oos_net_returns=oos, oos_dates=dates,
                         gross_returns=oos, turnover=[0.05] * n, cost_per_turnover=0.001,
                         adv_notional=1e9, required_notional=1e6, prereg_config=cfg,
                         frozen_hash=h, economic_rationale=rationale,
                         n_trials_cumulative=10, trials_variance=0.02,
                         llm_evidence=evidence, run_id=run_id)

    # (a) 声明了 llm_agent 却不给三关证据 → 拒（缺失≠放松，不许静默跳过）
    va = certify(mk(None), oos_budget=OOSBudget(1))
    check("声明 llm_agent 但无三关证据 → REJECTED_llm_prescreen",
          va.decision == "REJECTED_llm_prescreen")

    ev_ok = {"mode": "forward_paper", "eval_window_start": "2026-08-10",
             "prereg_frozen_at": "2026-08-08", "decisions": dec, "seed_values": seeds,
             "returns": oos, "factors": {"MKT": mkt}, "n_prompt_variants": 2}
    # (b) 污染模式（历史回放 + cutoff 覆盖）→ 即便有 alpha 也只判生成器级 → 拒
    ev_bad = dict(ev_ok); ev_bad.update({"mode": "historical_replay",
                                         "eval_window_start": "2023-01-01",
                                         "model_training_cutoff": "2025-06-01"})
    vb = certify(mk(ev_bad), oos_budget=OOSBudget(1))
    check("污染模式 → REJECTED_llm_prescreen（GENERATOR_ONLY 不作验收）",
          vb.decision == "REJECTED_llm_prescreen")
    check("  判据记录 evidence_grade", vb.gates["llm_prescreen"]["evidence_grade"] == "GENERATOR_ONLY")

    # (c) seed×prompt 试验数未足额登记进台账 → 拒（吏部点名"最易漏"）
    led = TrialLedger(path=None)
    led.register_run("llm-run1", "llm", n_trials_total=3, n_evaluated=1,
                     trial_sharpes_var=0.02, now_iso="2026-08-08T00:00:00Z")
    vc = certify(mk(ev_ok, run_id="llm-run1"), ledger=led, oos_budget=OOSBudget(1))
    check("5 seed×2 变体=10 试验，台账只登记 3 → REJECTED_honesty",
          vc.decision == "REJECTED_honesty")
    check("  记录 declared=10 vs registered=3",
          vc.gates["llm_seed_trials"]["declared"] == 10
          and vc.gates["llm_seed_trials"]["registered"] == 3)

    # (d) 足额登记 + 前向纸面 + 真 alpha → 三关放行（后续照走老门）
    led2 = TrialLedger(path=None)
    led2.register_run("llm-run2", "llm", n_trials_total=10, n_evaluated=1,
                      trial_sharpes_var=0.02, now_iso="2026-08-08T00:00:00Z")
    vd = certify(mk(ev_ok, run_id="llm-run2"), ledger=led2, oos_budget=OOSBudget(1))
    check("足额登记+前向+真alpha → 不被三关拦（进老门）",
          vd.decision not in ("REJECTED_llm_prescreen", "REJECTED_honesty"))
    check("  三关证据留痕 evidence_grade=ACCEPTANCE",
          vd.gates["llm_prescreen"]["evidence_grade"] == "ACCEPTANCE")

    # (e) 非 llm 范式候选不受影响（老候选零回归）
    cfg_old = _base_cfg()
    v_old = certify(Candidate(name="old", oos_net_returns=oos, oos_dates=dates,
                              prereg_config=cfg_old, frozen_hash=freeze_config(cfg_old),
                              economic_rationale=rationale, n_trials_cumulative=2,
                              trials_variance=0.02), oos_budget=OOSBudget(1))
    check("非 llm 范式候选 → 不触发三关（无回归）",
          "llm_prescreen" not in v_old.gates)


def main():
    for t in (test_metrics, test_dsr, test_ledger, test_walk_forward,
              test_cost_capacity, test_prereg, test_certify_end_to_end,
              test_selfreport_cannot_undercut_ledger,
              test_cost_model_is_floor, test_capacity_missing_is_not_pass,
              test_ledger_accumulates_and_persists, test_dsr_unit_scale,
              test_ppy_is_not_a_free_knob,
              test_family_must_be_frozen, test_pooled_v_independent_floor,
              test_oos_budget_persists, test_refreeze_guard, test_sleeve_verdict,
              test_concurrent_writers_are_atomic,
              test_capital_efficiency, test_dsr_machine_scale,
              test_llm_contamination, test_llm_seeds_and_attribution,
              test_llm_prescreen_wired_into_certify):
        t()
    print(f"\nALL PASSED — {PASS} checks green.")


if __name__ == "__main__":
    main()

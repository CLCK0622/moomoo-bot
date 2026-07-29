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
    # 毛收益均值 0.0003 < 地板 5bps*turnover(1.0)=0.0005 → 按地板算净 Sharpe<=0
    gross = _sinusoid_returns(0.0003, 0.004)
    to = [1.0] * len(good_oos)
    cfg = _base_cfg(); h = freeze_config(cfg)   # cost_model = moomoo_retail_x1
    rationale = ("动量/趋势溢价：横截面与时序证据，行为(处置效应/羊群)+风险(增长期权)双解释，"
                 "跨市场跨年代稳健，非纯数据挖掘，非曲线拟合。")

    # 先证漏洞面存在：裸报 1e-7 成本 cost_stress 会放行，按地板 5bps 则杀
    from research.gate import cost_stress_gate as _csg
    check("裸报 cost=1e-7 → cost_stress 放行（漏洞面）", _csg(gross, to, 1e-7).passed_early)
    check("按地板 cost=5bps → cost_stress 杀", not _csg(gross, to, 0.0005).passed_early)

    def mk(cost):
        return Candidate(name="dm", oos_net_returns=good_oos, oos_dates=dates,
                         gross_returns=gross, turnover=to, cost_per_turnover=cost,
                         required_notional=1e5, adv_notional=1e9,  # 容量充足，隔离成本门
                         prereg_config=cfg, frozen_hash=h, economic_rationale=rationale,
                         n_trials_cumulative=1, trials_variance=0.05)

    # 工部复现：自报 1e-7 → 旧版 certified；新版被地板抬到 5bps → REJECTED_cost
    v_tiny = certify(mk(1e-7), oos_budget=OOSBudget(1))
    check("自报 1e-7 → REJECTED_cost（地板生效）", v_tiny.decision == "REJECTED_cost")
    check("  生效成本被抬到地板 5bps", abs(v_tiny.gates["cost_per_turnover_effective"] - 0.0005) < 1e-12)
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

    for x in (p, pa, pb):
        if os.path.exists(x):
            os.remove(x)
    os.rmdir(d)

    # 已入库的规范历史基线在位（cumulative_n 有真实历史下限，非本轮 0）
    if os.path.exists(DEFAULT_LEDGER_PATH):
        seeded = TrialLedger(DEFAULT_LEDGER_PATH)
        check("规范台账历史基线已入库（cumulative_n>=14）", seeded.cumulative_n() >= 14)


def main():
    for t in (test_metrics, test_dsr, test_ledger, test_walk_forward,
              test_cost_capacity, test_prereg, test_certify_end_to_end,
              test_selfreport_cannot_undercut_ledger,
              test_cost_model_is_floor, test_capacity_missing_is_not_pass,
              test_ledger_accumulates_and_persists):
        t()
    print(f"\nALL PASSED — {PASS} checks green.")


if __name__ == "__main__":
    main()

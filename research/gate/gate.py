"""
gate.py —— EVO-149 冻结门总装 / CERTIFY 决策

架构铁律（本线纪律，任何人不得绕）：
  三工具（Qlib/RD-Agent/AlphaAgent）一律只当**假设生成器**；
  验收权 100% 留在本冻结门；工具自带回测**永不**作接受判据。

candidate（候选因子/策略）走门顺序（**cheap → expensive**，尽早杀）：
  1. 预注册完整性 + 冻结核对（prereg）
  2. 诚实试验计数（trial_ledger：miner 不吐全量 N → 不予评估）
  3. 成本 x1x2 早筛（cost_capacity：x1 净 Sharpe<=0 直接杀）
  4. 容量/ADV（cost_capacity）
  5. 经济理由门（prereg：无理由 → 隔离）
  6. 样本外净值指标 + 危机子窗单报（metrics，OOS 单发预算）
  7. DSR 多重检验 haircut（deflated_sharpe，N=跨轮累计真实数）
  8. 官方 50/20 联合门 + 影子分层线判定（metrics）

certify() 返回结构化 Verdict：只有**全部硬门通过**且 official/shadow 触发上报或决策点，
才 certified=True。CERTIFY 由户部盖章、再走都察院终审。负向静默。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from . import metrics as M
from .cost_capacity import capacity_gate, cost_stress_gate
from .deflated_sharpe import deflated_sharpe_ratio
from .prereg import (economic_rationale_gate, validate_prereg_completeness,
                     verify_unchanged)
from .trial_ledger import HonestyError, TrialLedger
from .walk_forward import OOSBudget, OOSBudgetExceeded


@dataclass
class Candidate:
    """送进门的候选。net_returns 必须是**样本外(OOS)净收益**序列。"""
    name: str
    oos_net_returns: Sequence[float]
    oos_dates: Optional[Sequence] = None
    # 成本早筛用（毛收益 + 换手）
    gross_returns: Optional[Sequence[float]] = None
    turnover: Optional[Sequence[float]] = None
    cost_per_turnover: float = 0.0005
    # 容量
    required_notional: float = 0.0
    adv_notional: float = 0.0
    # 预注册
    prereg_config: Dict[str, Any] = field(default_factory=dict)
    frozen_hash: Optional[str] = None
    economic_rationale: str = ""
    # DSR
    n_trials_cumulative: Optional[int] = None    # 覆盖 ledger.cumulative_n()（可选）
    trials_variance: Optional[float] = None
    trial_sharpes: Optional[Sequence[float]] = None


@dataclass
class Verdict:
    name: str
    certified: bool
    decision: str                        # REPORT_5020 / DECISION_POINT / FAIL / REJECTED_<gate>
    gates: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    metrics: Optional[Dict[str, Any]] = None

    def summary(self) -> str:
        head = f"[{self.name}] certified={self.certified} decision={self.decision}"
        return head + ("\n  - " + "\n  - ".join(self.reasons) if self.reasons else "")


def certify(cand: Candidate,
            ledger: Optional[TrialLedger] = None,
            thresholds: Optional[M.GateThresholds] = None,
            oos_budget: Optional[OOSBudget] = None,
            dsr_threshold: float = 0.95,
            max_participation: float = 0.10) -> Verdict:
    """
    候选过全门 → 结构化 Verdict。候选**在其价值上**未过某门 → 返回 REJECTED_* 判据。
    但**完整性/诚实被违反**（调用方自报 N 低于持久台账）→ 抛 HonestyError（fail-closed，
    与 register_run 同惯例），逼调用方修接线而非把违规当普通驳回静默吞掉。
    正确管线用法（营缮主事）：传 ledger=，把 n_trials_cumulative 留 None，让门自台账取数。
    """
    v = Verdict(name=cand.name, certified=False, decision="FAIL")

    # 1) 预注册完整性 + 冻结核对
    missing = validate_prereg_completeness(cand.prereg_config)
    if missing:
        v.decision = "REJECTED_prereg"
        v.reasons.append(f"预注册不完整，缺键: {missing}")
        return v
    if cand.frozen_hash is not None:
        pc = verify_unchanged(cand.frozen_hash, cand.prereg_config)
        v.gates["prereg_unchanged"] = pc.unchanged
        if not pc.unchanged:
            v.decision = "REJECTED_prereg"
            v.reasons.append("预注册被事后修改（哈希不符）→ 记新试验、重走全门，不放行。")
            return v

    # 2) 诚实试验计数（决定 DSR 的 N）—— 台账是地板，自报 N 只能更严不能更松
    #    fail-open 修复(工部实测复现): 自报 n_trials_cumulative 曾**优先**于持久台账，
    #    调用方传一个更小的 N（如 1）就能静默压过诚实记着 5000 的台账，把 REJECTED_dsr
    #    翻成 certified —— 正是诚实计数这道地基要防的唯一（放松）方向。
    #    现规则：台账存在且自报 N < cumulative_n() → HonestyError（与 register_run 同惯例）；
    #    两者并存时取 max（更保守）；只有无台账的手跑候选（如文献配置 GEM, N=2）才纯采信自报。
    n_self = cand.n_trials_cumulative
    n_ledger = ledger.cumulative_n() if ledger is not None else None
    if n_self is not None and n_ledger is not None and n_self < n_ledger:
        raise HonestyError(
            f"自报 N={n_self} 低于持久台账累计真实数 {n_ledger} → 不予评估。"
            "诚实试验计数是地基：台账存在时自报 N 只能取更严(≥)方向，不得静默压过台账"
            "放松 DSR haircut。手跑候选请不要传 ledger，或把该轮 register_run 登记进台账。"
        )
    if n_self is not None and n_ledger is not None:
        n_trials = max(n_self, n_ledger)
    elif n_self is not None:
        n_trials = n_self
    elif n_ledger is not None:
        n_trials = n_ledger
    else:
        n_trials = None
    if not n_trials or n_trials < 1:
        v.decision = "REJECTED_honesty"
        v.reasons.append("无真实试验数 N（miner 未吐全量含丢弃）→ 不予评估。")
        return v
    v.gates["n_trials"] = n_trials

    # 3) 成本 x1x2 早筛（贵门之前先杀）
    if cand.gross_returns is not None and cand.turnover is not None:
        cs = cost_stress_gate(cand.gross_returns, cand.turnover, cand.cost_per_turnover)
        v.gates["cost_stress"] = cs.__dict__
        if not cs.passed_early:
            v.decision = "REJECTED_cost"
            v.reasons.append(f"成本 x1 净 Sharpe={cs.sharpe_x1:.3f}<=0 → 早筛淘汰。")
            return v
        if not cs.robust:
            v.reasons.append(f"警告：成本 x2 下 Sharpe={cs.sharpe_x2:.3f}<=0，成本鲁棒性不足。")

    # 4) 容量 / ADV
    if cand.adv_notional > 0:
        cap = capacity_gate(cand.required_notional, cand.adv_notional, max_participation)
        v.gates["capacity"] = cap.__dict__
        if not cap.passed:
            v.decision = "REJECTED_capacity"
            v.reasons.append(f"容量不足：参与率 {cap.participation:.2%} > 上限 {max_participation:.0%}。")
            return v

    # 5) 经济理由门
    rr = economic_rationale_gate(cand.economic_rationale)
    v.gates["rationale"] = rr.__dict__
    if rr.quarantined:
        v.decision = "REJECTED_rationale"
        v.reasons.append(rr.reason)
        return v

    # 6) 样本外净值指标 + 危机子窗（消耗 OOS 单发预算）
    if oos_budget is not None:
        try:
            oos_budget.consume(cand.frozen_hash or cand.name)
        except OOSBudgetExceeded as e:
            v.decision = "REJECTED_oos_budget"
            v.reasons.append(str(e))
            return v
    rep = M.evaluate(cand.oos_net_returns, cand.oos_dates, thresholds)
    v.metrics = rep.as_dict()

    # 7) DSR 多重检验 haircut（N = 跨轮累计真实数）
    #    同类 fail-open 一并堵死：试验方差 V 亦是放松旋钮（V 越小 → 期望最大 SR0 越小
    #    → DSR 越易过，一个极小的自报 V 就能把基准压到 ~0）。台账 pooled V 作地板，
    #    自报 V 只能取更严(更大)方向，不得静默压低。无台账时才纯采信自报 V（手跑候选）。
    tv_self = cand.trials_variance
    tv_ledger = ledger.pooled_trials_variance() if ledger is not None else None
    tv_candidates = [x for x in (tv_self, tv_ledger) if x is not None]
    tv = max(tv_candidates) if tv_candidates else None
    try:
        dsr = deflated_sharpe_ratio(
            rep.sharpe_per_period, rep.n_obs, rep.skew, rep.kurtosis,
            n_trials=n_trials, trial_sharpes=cand.trial_sharpes,
            trials_variance=tv, threshold=dsr_threshold,
        )
        v.gates["dsr"] = dsr.__dict__
        if not dsr.passed:
            v.decision = "REJECTED_dsr"
            v.reasons.append(
                f"DSR={dsr.dsr:.3f} < {dsr_threshold}（N={n_trials} 累计试验下选择偏差过大）→ 疑似伪 alpha。")
            return v
    except ValueError as e:
        # 拿不到 V → 无法做 DSR → 不予放行（要求 miner 吐全量试验 SR）
        v.decision = "REJECTED_dsr"
        v.reasons.append(f"DSR 无法计算：{e}")
        return v

    # 8) 官方 50/20 + 影子分层线
    if rep.decision == "FAIL":
        v.decision = "FAIL"
        v.reasons.append(
            f"未过影子上报门（CAGR={rep.cagr:.1%}, MDD={rep.mdd:.1%}）。")
        return v

    # 全部硬门通过 + 触发上报/决策点 → 可 CERTIFY
    v.certified = True
    v.decision = rep.decision
    if rep.decision == "REPORT_5020":
        v.reasons.append(f"直接清官方 50/20（CAGR={rep.cagr:.1%}, MDD={rep.mdd:.1%}）→ 即刻上报。")
    else:  # DECISION_POINT
        v.reasons.append(
            f"过影子上报门未过官方门（CAGR={rep.cagr:.1%}, MDD={rep.mdd:.1%}）"
            "→ 带真实数字上验收线决策点，请 Kevin 拍板。")
    v.reasons.append("CERTIFY 由户部盖章，须再走都察院终审后方可交付。")
    return v

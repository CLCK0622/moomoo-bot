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

import pandas as pd

from . import metrics as M
from .cost_capacity import (capacity_gate, cost_stress_gate,
                            resolve_cost_per_turnover)
from .deflated_sharpe import deflated_sharpe_ratio
from .llm_paradigm import prescreen as _llm_prescreen
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
    cost_per_turnover: Optional[float] = None   # None → 用冻结 cost_model 地板；自报只能更贵
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
    trials_periods_per_year: int = 1             # 试验 Sharpe 的年化尺度；1=每期(契约)，年化则传 ppy
    run_id: Optional[str] = None                 # 候选自己那轮的台账 run_id；用于把它从 pooled V 地板里排除（独立兜底）
    # LLM 定性范式（吏部 2026-08-08 前向纸面轨）三关证据。**当冻结预注册声明
    # paradigm='llm_agent' 时为必填**——缺失即拒（缺失≠放松），不许把三关做成"记得调才生效"的
    # 可选步骤。字段见 llm_paradigm.prescreen 的入参：
    #   mode / eval_window_start / model_training_cutoff / prereg_frozen_at /
    #   decisions / seed_values / factors / n_prompt_variants
    llm_evidence: Optional[Dict[str, Any]] = None


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
    # 1b) family 冻结交叉核验（工部 2026-07-30 EVO-8 A）：定义 V 的那组试验须与冻结 family 一致，
    #     不得事后增删（family 选得越紧 V 越小、多重检验罚越轻）。family 已进 REQUIRED_PREREG_KEYS，
    #     故「跑后改 family」由冻结哈希抓；这里再对**提供了 trial_sharpes** 的候选做条数核验：
    #     实际用于算 V 的试验数须等于冻结 family 的规模。
    family = cand.prereg_config.get("family")
    if cand.trial_sharpes is not None and isinstance(family, (list, tuple)) and len(family) > 0:
        if len(cand.trial_sharpes) != len(family):
            v.decision = "REJECTED_prereg"
            v.reasons.append(
                f"定义 V 的试验数 {len(cand.trial_sharpes)} ≠ 冻结 family 规模 {len(family)} → "
                "family 被事后增删（可借挑紧 family 关掉多重检验罚）→ 不放行。")
            return v

    # 1c) LLM 定性范式三关（吏部 2026-08-08）——**由冻结预注册触发，非可选步骤**。
    #     若把 prescreen 做成"管线记得调才生效"的旁路函数，忘调＝污染/归因/seed 三关静默跳过，
    #     正是本线一路在堵的「机制写对但可绕过」形态。故：冻结 prereg 声明 paradigm='llm_agent'
    #     即**强制**要求三关证据，缺失即拒（缺失≠放松）。权威来源是冻结预注册、不是调用方。
    if cand.prereg_config.get("paradigm") == "llm_agent":
        if not cand.llm_evidence:
            v.decision = "REJECTED_llm_prescreen"
            v.reasons.append(
                "冻结预注册声明 paradigm='llm_agent' 但候选未提供三关证据（污染/seed/归因）→ 不予评估。"
                "缺失≠放松：三关是本范式证据效力的前提，不接受跳过。")
            return v
        ev = dict(cand.llm_evidence)
        try:
            pres = _llm_prescreen(
                mode=ev.get("mode", ""), eval_window_start=ev.get("eval_window_start"),
                decisions=ev.get("decisions") or [], seed_values=ev.get("seed_values") or [],
                returns=ev.get("returns", cand.oos_net_returns),
                factors=ev.get("factors") or {},
                model_training_cutoff=ev.get("model_training_cutoff"),
                prereg_frozen_at=ev.get("prereg_frozen_at"),
                n_prompt_variants=int(ev.get("n_prompt_variants", 1)),
                seed_quantile=float(ev.get("seed_quantile", 0.25)),
                t_threshold=float(ev.get("t_threshold", 2.0)))
        except (ValueError, KeyError) as e:
            v.decision = "REJECTED_llm_prescreen"
            v.reasons.append(f"三关证据不完整/不可解析：{e}")
            return v
        v.gates["llm_prescreen"] = {
            "evidence_grade": pres.evidence_grade,
            "admissible": pres.admissible.as_dict(),
            "seeds": pres.seeds.as_dict() if pres.seeds else None,
            "attribution": pres.attribution.as_dict() if pres.attribution else None,
            "trials_for_ledger": pres.trials_for_ledger,
            "reasons": pres.reasons,
        }
        # 每 seed × 每 prompt 变体全额计一次试验（吏部点名"最易漏"）——结构化核验：
        # 台账里本轮登记的 n_trials_total 不得低于 seeds×variants，否则跑 20 个 seed 只登记 1 次、
        # DSR haircut 被静默放松。台账是权威来源，自报的 seed 数须与之相符。
        if ledger is not None and cand.run_id and pres.trials_for_ledger > 0:
            rec = next((r for r in ledger.runs if r.run_id == cand.run_id), None)
            v.gates["llm_seed_trials"] = {
                "declared": pres.trials_for_ledger,
                "registered": rec.n_trials_total if rec else None}
            if rec is None or rec.n_trials_total < pres.trials_for_ledger:
                v.decision = "REJECTED_honesty"
                v.reasons.append(
                    f"seed×prompt 试验数 {pres.trials_for_ledger} 未足额登记进台账"
                    f"（run_id={cand.run_id} 登记 {rec.n_trials_total if rec else '无'}）→ 不予评估。"
                    "每个 seed / prompt 变体都是一次试验，少登即把 DSR haircut 静默放松。")
                return v
        if pres.evidence_grade != "ACCEPTANCE":
            v.decision = "REJECTED_llm_prescreen"
            v.reasons.append(
                "证据等级 GENERATOR_ONLY（历史回放/污染或非真前向）→ 只能作假设生成器，永不作接受判据。"
                + " | ".join(pres.reasons))
            return v
        if not pres.passed_prescreen:
            v.decision = "REJECTED_llm_prescreen"
            v.reasons.append("三关未全过：" + " | ".join(pres.reasons))
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
    if ledger is not None:
        # N 的**可审计出处**写进 verdict：都察院据此复核 cumulative_n 由哪些轮次累加而来，
        # 不必依赖那份 gitignore 的本地台账文件（工部 d1415117：台账不落库、审计无从查）。
        v.gates["ledger_provenance"] = {
            "path": ledger.path,
            "cumulative_n": n_ledger,
            "n_runs": len(ledger.runs),
            "runs": [{"run_id": r.run_id, "source": r.source,
                      "n_trials_total": r.n_trials_total} for r in ledger.runs],
        }

    # 3) 成本 x1x2 早筛（贵门之前先杀）—— 成本以**冻结 cost_model**为地板，自报只能更贵
    #    fail-open 修复(工部实测): 门曾直接用候选自报的裸 cost_per_turnover，从不拿冻结的
    #    cost_model 标签校验；把 50bps 报成 10bps 就能把「成本杀」翻成 certified。
    #    现在: 从冻结 cost_model 取权威地板，effective=max(地板,自报)；未知标签→REJECTED_prereg。
    if cand.gross_returns is not None and cand.turnover is not None:
        try:
            eff_cost = resolve_cost_per_turnover(
                cand.prereg_config.get("cost_model"), cand.cost_per_turnover)
        except KeyError as e:
            v.decision = "REJECTED_prereg"
            v.reasons.append(f"未知/未登记的冻结成本模型标签 {e} → 不予评估（不许用未登记便宜成本）。")
            return v
        v.gates["cost_per_turnover_effective"] = eff_cost
        cs = cost_stress_gate(cand.gross_returns, cand.turnover, eff_cost)
        v.gates["cost_stress"] = cs.__dict__
        if not cs.passed_early:
            v.decision = "REJECTED_cost"
            v.reasons.append(
                f"成本 x1(地板口径 {eff_cost:.4%}/换手) 净 Sharpe={cs.sharpe_x1:.3f}<=0 → 早筛淘汰。")
            return v
        if not cs.robust:
            v.reasons.append(f"警告：成本 x2 下 Sharpe={cs.sharpe_x2:.3f}<=0，成本鲁棒性不足。")

    # 4) 容量 / ADV —— 缺失≠放松：ADV 未申报不静默跳过，延迟到 step 8 对 miner 候选定夺
    #    fail-open 修复(工部实测): `if adv>0` 意味着不报 ADV 整道容量门直接不跑，
    #    「如实申报被杀、闭嘴就能过」。延迟判定既堵洞又不掩盖更靠前的真实失败原因。
    if cand.adv_notional and cand.adv_notional > 0:
        cap = capacity_gate(cand.required_notional, cand.adv_notional, max_participation)
        v.gates["capacity"] = cap.__dict__
        if not cap.passed:
            v.decision = "REJECTED_capacity"
            v.reasons.append(f"容量不足：参与率 {cap.participation:.2%} > 上限 {max_participation:.0%}。")
            return v
    else:
        v.gates["capacity_unverified"] = True   # ADV 未申报；step 8 对 miner 候选兜底

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
    # ppy 不是自由旋钮（工部 2026-07-30）：声明 ppy>1 会把 V 除以 ppy → 门变松，
    # 是与 N/V/成本/容量同类的 fail-open。权威来源不是调用方，而是**候选自己的收益序列频率**：
    # 一个合法的年化因子必须等于该序列的每年期数（日频≈252、周频≈52、月频≈12）。
    # 声明值与实测频率不符 → 拒绝（例如 ppy=10000，或对月频数据声明 252）。
    ppy_declared = max(int(cand.trials_periods_per_year or 1), 1)
    if ppy_declared > 1:
        derived = None
        if cand.oos_dates is not None and len(cand.oos_dates) > 1:
            dts = pd.to_datetime(pd.Series(list(cand.oos_dates)))
            span_yrs = (dts.iloc[-1] - dts.iloc[0]).days / 365.25
            if span_yrs > 0:
                derived = len(cand.oos_net_returns) / span_yrs
        if derived is None:
            v.decision = "REJECTED_prereg"
            v.reasons.append(
                f"声明 trials_periods_per_year={ppy_declared} 但候选未提供 oos_dates，"
                "无法据收益序列频率核验年化尺度 → 不予评估（ppy 不接受无据自报）。")
            return v
        if not (0.5 * derived <= ppy_declared <= 2.0 * derived):
            v.decision = "REJECTED_prereg"
            v.reasons.append(
                f"声明 trials_periods_per_year={ppy_declared} 与收益序列实测频率 "
                f"≈{derived:.0f}/年 不符 → 拒绝。过报 ppy 会把 V 重复归一、静默放松 DSR（假阳性）。")
            return v

    tv_self = cand.trials_variance
    # pooled V 地板须**独立于候选自己那轮**（排除 cand.run_id），否则退化成 max(x,x)（工部 2026-07-30 实测）。
    tv_ledger = (ledger.pooled_trials_variance(exclude_run_id=cand.run_id)
                 if ledger is not None else None)
    if ledger is not None and cand.run_id is not None:
        independent = ledger.has_independent_v(cand.run_id)
        v.gates["pooled_v_floor"] = {"independent": independent, "value": tv_ledger}
        if not independent:
            v.reasons.append(
                "注意：pooled V 地板不独立（除候选自己那轮外无带 trial_sharpes 的登记）→ 放松侧无结构兜底；"
                "后续每条 register_run 须带 trial_sharpes 才能构成真地板。")
    tv_candidates = [x for x in (tv_self, tv_ledger) if x is not None]
    tv = max(tv_candidates) if tv_candidates else None
    try:
        dsr = deflated_sharpe_ratio(
            rep.sharpe_per_period, rep.n_obs, rep.skew, rep.kurtosis,
            n_trials=n_trials, trial_sharpes=cand.trial_sharpes,
            trials_variance=tv, trials_periods_per_year=cand.trials_periods_per_year,
            threshold=dsr_threshold,
        )
        v.gates["dsr"] = dsr.__dict__
        # 放松侧（√V ≪ 抽样噪声）→ 硬拒（户部 2026-07-30 裁定，工部 ec0aeab 残留项）：
        # 合法试验族的每期 Sharpe 离散度至少是抽样噪声，此情形几乎必是 ppy 重复归一/单位错，门会过松、
        # 假阳性直送 Kevin，比冤杀更糟。这一侧无会误伤的合法情形（紧 family 仍在噪声之上），故硬拒安全。
        if dsr.scale_relaxing:
            v.decision = "REJECTED_scale"
            v.reasons.append("放松侧单位异常（" + (dsr.scale_note or "") +
                             "）→ 硬拒，不静默放松门。产出侧改每期口径 / 删掉多余的 ppy 声明后重验。")
            return v
        if dsr.scale_warning:
            v.reasons.append("警告：DSR 试验 Sharpe 疑似单位不一致（V 尺度 vs 每期 sr）——"
                             + (dsr.scale_note or "请核产出侧年化口径。"))
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

    # 容量未验证兜底：miner 候选（有台账）不申报 ADV 不得 certified（缺失≠放松，同诚实计数地基）
    if v.gates.get("capacity_unverified") and ledger is not None:
        v.decision = "REJECTED_capacity"
        v.reasons.append("miner 候选未如实申报 ADV/required_notional → 容量不可验证，"
                         "不予 certified（缺失≠放松）。传入真实 ADV 后重验。")
        return v

    # 全部硬门通过 + 触发上报/决策点 → 可 CERTIFY
    v.certified = True
    v.decision = rep.decision
    if v.gates.get("capacity_unverified"):   # 无台账手跑候选：容量未验证，certified 但标记待人工复核
        v.reasons.append("注意：手跑候选未申报 ADV，容量未经门验证，须都察院终审时人工确认。")
    if rep.decision == "REPORT_5020":
        v.reasons.append(f"直接清官方 50/20（CAGR={rep.cagr:.1%}, MDD={rep.mdd:.1%}）→ 即刻上报。")
    else:  # DECISION_POINT
        v.reasons.append(
            f"过影子上报门未过官方门（CAGR={rep.cagr:.1%}, MDD={rep.mdd:.1%}）"
            "→ 带真实数字上验收线决策点，请 Kevin 拍板。")
    v.reasons.append("CERTIFY 由户部盖章，须再走都察院终审后方可交付。")
    return v

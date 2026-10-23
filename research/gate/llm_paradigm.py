"""
llm_paradigm.py —— LLM-agent 主观定性投资的评测口径（户部，吏部 08-08 新范式调研轮）

这条范式与因子挖掘是两种东西，故**另立一套评测口径**，但纪律同源：先定后跑、写进预注册、
自报旋钮须对权威来源可核、不静默放松。三个必须机器化处理的坑：

1. **LLM 前视 / 数据污染**（本范式的头号坑，且**结构性不可修**）：
   模型预训练语料已含评测期 → 历史回放天然作弊（它可能"记得"结果），且厂商训练集不可核。
   故：`admissibility_check()` 判定——
     - `forward_paper`（决策在预注册冻结之后、实时做出）= **唯一可作验收证据**的模式；
     - `historical_replay` 且模型 cutoff ≥ 评测窗起点 = **INADMISSIBLE_CONTAMINATED**，
       只能当**假设生成器**（与三工具同一条铁律：生成器≠验收），永不作接受判据。
   叠加**逐条决策的时序核验** `validate_decision_log()`：证据时间 ≤ 决策时间 ≤ 收益起算时间。

2. **决策不可复现 / 随机性**：同 prompt 多次结果不同 ⇒ 策略本身是随机的。必须多 seed 跑，
   判在**保守分位（默认 25%）而非最优 seed**（挑最好的 seed = 选择偏差，与挑 family 同类）；
   且**每个 seed / prompt 变体都是一次试验**，计入累计 N 台账（`trials_from_seeds`）。

3. **归因**：超额若来自 beta / 风格暴露（偏高 beta、偏科技），那不是选股 alpha。
   `style_attribution()` 用 Newey-West(HAC) t 值判**控制因子后**的 alpha 是否显著；
   betas 一并报出，让"高 beta 冒充 alpha"无处藏。

与 `certify()` 的关系（复用为主、只新立必要项）：净值/成本 x1x2/容量/预注册冻结/OOS 单发/
台账 N + DSR haircut **全部照旧适用**；本模块新增的是"可否作为证据"（污染）、"判哪个 seed"
（随机性）、"是不是真 alpha"（归因）三关——三关全过才把净值送进 `certify()`。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .metrics import PERIODS_PER_YEAR

# ---------------------------------------------------------------- 1. 污染 / 前视


class ContaminationError(ValueError):
    """历史回放且模型训练 cutoff 覆盖评测窗 → 结构性污染，不得作验收证据。"""


@dataclass
class AdmissibilityCheck:
    admissible: bool          # 能否作为**验收**证据（False 时只能当生成器）
    mode: str                 # 'forward_paper' | 'historical_replay'
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def admissibility_check(mode: str, eval_window_start, model_training_cutoff=None,
                        prereg_frozen_at=None) -> AdmissibilityCheck:
    """
    判本次评测**能否作验收证据**。
    - forward_paper：要求评测窗起点 ≥ 预注册冻结时间（决策全在冻结之后做出）。
    - historical_replay：模型 cutoff ≥ 评测窗起点即污染（模型可能已知该期结果）→ 不可验收。
      cutoff 未知/不可核 ⇒ 一律按污染处理（不可核的自报不采信，与「无据自报不予评估」同源）。
    """
    ws = pd.Timestamp(eval_window_start)
    if mode == "forward_paper":
        if prereg_frozen_at is None:
            return AdmissibilityCheck(False, mode, "forward_paper 须提供预注册冻结时间以核验决策在冻结之后")
        fz = pd.Timestamp(prereg_frozen_at)
        if ws < fz:
            return AdmissibilityCheck(
                False, mode, f"评测窗起点 {ws.date()} 早于预注册冻结 {fz.date()} → 非真前向，不可验收")
        return AdmissibilityCheck(True, mode, "前向纸面跑、决策在预注册冻结之后 → 可作验收证据")
    if mode == "historical_replay":
        if model_training_cutoff is None:
            return AdmissibilityCheck(
                False, mode, "历史回放但模型训练 cutoff 不可核 → 按污染处理，仅可作生成器")
        cut = pd.Timestamp(model_training_cutoff)
        if cut >= ws:
            return AdmissibilityCheck(
                False, mode,
                f"模型 cutoff {cut.date()} 覆盖评测窗起点 {ws.date()} → 结构性污染（模型可能已知结果），"
                "仅可作假设生成器，永不作接受判据")
        return AdmissibilityCheck(
            True, mode, f"模型 cutoff {cut.date()} 严格早于评测窗 {ws.date()} → 可作验收证据（仍须归因/成本关）")
    return AdmissibilityCheck(False, mode, f"未知模式 '{mode}'")


@dataclass
class DecisionLogCheck:
    ok: bool
    n_decisions: int
    n_violations: int
    violations: List[str] = field(default_factory=list)


def validate_decision_log(decisions: Sequence[Dict[str, Any]]) -> DecisionLogCheck:
    """
    逐条决策时序核验：`evidence_max_ts <= decision_ts <= effective_from`。
    - evidence_max_ts > decision_ts ⇒ 用了决策时点之后才存在的信息（前视）；
    - effective_from < decision_ts ⇒ 收益起算早于决策（等于先看结果再下单）。
    任一违规即 ok=False（不静默）。
    """
    viol: List[str] = []
    for i, d in enumerate(decisions):
        try:
            ev = pd.Timestamp(d["evidence_max_ts"])
            dt = pd.Timestamp(d["decision_ts"])
            ef = pd.Timestamp(d["effective_from"])
        except (KeyError, ValueError) as e:
            viol.append(f"#{i} 决策记录字段缺失/不可解析：{e}")
            continue
        if ev > dt:
            viol.append(f"#{i} 证据时间 {ev} 晚于决策时间 {dt}（前视）")
        if ef < dt:
            viol.append(f"#{i} 收益起算 {ef} 早于决策时间 {dt}（先看结果后下单）")
    return DecisionLogCheck(ok=(len(viol) == 0), n_decisions=len(decisions),
                            n_violations=len(viol), violations=viol)


# ---------------------------------------------------------------- 2. 随机性 / 多 seed


def trials_from_seeds(n_seeds: int, n_prompt_variants: int = 1) -> int:
    """每个 seed × 每个 prompt 变体都是一次试验 —— 全额计入累计 N 台账，不许只报最优那次。"""
    return max(int(n_seeds), 0) * max(int(n_prompt_variants), 1)


@dataclass
class SeedReport:
    n_seeds: int
    values: List[float]
    best: float
    median: float
    judged: float          # 判据取值（保守分位，默认 25%）
    worst: float
    dispersion: float      # 标准差 / |中位数|，衡量"同 prompt 不同结果"的不可复现程度
    quantile: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def seed_distribution(values: Sequence[float], quantile: float = 0.25) -> SeedReport:
    """
    多 seed 结果分布。**判据取保守分位**（默认 25%），不取最优 seed——挑最好的 seed 是选择偏差，
    与"事后挑 family"同类。dispersion 大 ⇒ 策略本身不可复现，须在结论里点明。
    """
    v = np.asarray(list(values), dtype=float)
    if len(v) == 0:
        raise ValueError("seed 结果为空")
    med = float(np.median(v))
    disp = float(v.std(ddof=1) / abs(med)) if len(v) > 1 and med != 0 else float("nan")
    return SeedReport(n_seeds=len(v), values=[float(x) for x in v], best=float(v.max()),
                      median=med, judged=float(np.quantile(v, quantile)),
                      worst=float(v.min()), dispersion=disp, quantile=quantile)


# ---------------------------------------------------------------- 3. 风格 / beta 归因


def _newey_west_ols(y: np.ndarray, X: np.ndarray, lags: int) -> tuple:
    """OLS + Newey-West(HAC) 标准误。返回 (beta, se, t)。X 须已含截距列。"""
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    b = XtX_inv @ (X.T @ y)
    e = y - X @ b
    # Ŝ = Σ e_t² x_t x_t' + Σ_{l=1..L} w_l Σ_t e_t e_{t-l}(x_t x_{t-l}' + x_{t-l} x_t')
    S = (X * (e ** 2)[:, None]).T @ X
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        Xt, Xl = X[l:], X[:-l]
        et, el = e[l:], e[:-l]
        G = (Xt * (et * el)[:, None]).T @ Xl
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, b / se, np.nan)
    return b, se, t


@dataclass
class AttributionReport:
    n_obs: int
    alpha_per_period: float
    alpha_ann: float
    t_alpha: float             # Newey-West HAC t 值
    betas: Dict[str, float]
    t_betas: Dict[str, float]
    r_squared: float
    t_threshold: float
    alpha_significant: bool    # 控制风格/beta 后 alpha 仍显著
    note: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def style_attribution(returns: Sequence[float], factors: Dict[str, Sequence[float]],
                      rf: float = 0.0, periods_per_year: int = PERIODS_PER_YEAR,
                      t_threshold: float = 2.0, hac_lags: Optional[int] = None
                      ) -> AttributionReport:
    """
    风格/beta 归因：把策略超额收益对因子收益回归，看**截距 alpha** 在 HAC t 值下是否显著。
    - factors：{'MKT': 市场超额, 'SIZE': ..., 'VALUE': ..., 'MOM': ...}（ETF 价差代理亦可，
      口径须预注册冻结）；本项目免费数据即可构造。
    - alpha 不显著 ⇒ 超额来自 beta/风格暴露（如偏高 beta、偏科技），**不算选股 alpha**。
    - t_threshold 应随累计试验 N 提高（多重检验），与 DSR haircut 同向；默认 2.0 仅为单假设基线。
    """
    y = np.asarray(list(returns), dtype=float) - rf
    names = list(factors.keys())
    if not names:
        raise ValueError("须至少提供一个因子（至少市场 MKT），否则无法区分 alpha 与 beta")
    F = np.column_stack([np.asarray(list(factors[k]), dtype=float) for k in names])
    if len(F) != len(y):
        raise ValueError("因子与策略收益长度不一致")
    X = np.column_stack([np.ones(len(y)), F])
    n = len(y)
    lags = hac_lags if hac_lags is not None else max(1, int(round(4 * (n / 100.0) ** (2.0 / 9.0))))
    b, se, t = _newey_west_ols(y, X, lags)
    resid = y - X @ b
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = float(1.0 - (resid ** 2).sum() / ss_tot) if ss_tot > 0 else float("nan")
    sig = bool(np.isfinite(t[0]) and t[0] >= t_threshold)
    return AttributionReport(
        n_obs=n, alpha_per_period=float(b[0]), alpha_ann=float(b[0] * periods_per_year),
        t_alpha=float(t[0]), betas={k: float(v) for k, v in zip(names, b[1:])},
        t_betas={k: float(v) for k, v in zip(names, t[1:])}, r_squared=r2,
        t_threshold=t_threshold, alpha_significant=sig,
        note=("控制风格后 alpha 显著" if sig else
              "控制风格后 alpha 不显著 → 超额多来自 beta/风格暴露，不算选股 alpha"))


# ---------------------------------------------------------------- 汇总：三关


@dataclass
class LLMParadigmVerdict:
    admissible: AdmissibilityCheck
    decision_log: Optional[DecisionLogCheck]
    seeds: Optional[SeedReport]
    attribution: Optional[AttributionReport]
    trials_for_ledger: int
    evidence_grade: str        # 'ACCEPTANCE' | 'GENERATOR_ONLY'
    passed_prescreen: bool     # 三关全过 → 才把净值送进 certify()
    reasons: List[str] = field(default_factory=list)


def prescreen(mode: str, eval_window_start, decisions: Sequence[Dict[str, Any]],
              seed_values: Sequence[float], returns: Sequence[float],
              factors: Dict[str, Sequence[float]], model_training_cutoff=None,
              prereg_frozen_at=None, n_prompt_variants: int = 1,
              seed_quantile: float = 0.25, t_threshold: float = 2.0) -> LLMParadigmVerdict:
    """LLM 范式三关预筛：污染/前视 → 随机性（保守分位）→ 归因。全过才送 `certify()` 走老门。"""
    reasons: List[str] = []
    adm = admissibility_check(mode, eval_window_start, model_training_cutoff, prereg_frozen_at)
    grade = "ACCEPTANCE" if adm.admissible else "GENERATOR_ONLY"
    reasons.append(adm.reason)

    dlog = validate_decision_log(decisions) if decisions else None
    if dlog is not None and not dlog.ok:
        reasons.append(f"决策日志时序违规 {dlog.n_violations} 条（前视/先看结果）")

    seeds = seed_distribution(seed_values, seed_quantile) if len(seed_values) else None
    if seeds is not None:
        reasons.append(f"多 seed 判据取 {int(seed_quantile*100)}% 分位 {seeds.judged:.4f}"
                       f"（最优 {seeds.best:.4f} 不作判据）")
    attr = style_attribution(returns, factors, t_threshold=t_threshold) if len(returns) else None
    if attr is not None:
        reasons.append(attr.note)

    trials = trials_from_seeds(len(seed_values), n_prompt_variants)
    ok = (adm.admissible and (dlog is None or dlog.ok) and attr is not None
          and attr.alpha_significant)
    return LLMParadigmVerdict(admissible=adm, decision_log=dlog, seeds=seeds, attribution=attr,
                              trials_for_ledger=trials, evidence_grade=grade,
                              passed_prescreen=bool(ok), reasons=reasons)

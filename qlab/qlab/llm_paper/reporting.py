"""报告口径 —— seed 名义化（工部 2026-08-08 第二节裁定）。

**裁定：不改 `temperature`、不重冻。** 我原先担心「`temperature=0` 下 5 个 seed 输出相同 ⇒
`seed_distribution` 的下四分位就是它本身 ⇒ 护栏显示很稳却什么都没测」。工部验出这个担心在**机制**上不成立：
冻结网格是 **5 份变体 A + 5 份变体 B**，10 个值里较差那个占 5 个，`np.quantile(v, 0.25)` 的插值位置
`0.25×(10−1)=2.25` 落在排序后第 3、4 个之间，**两者都还是较差那个值** ⇒ 下四分位**恰等于两变体中较差者**。
即它自然退化成「取较差的 prompt 变体」——**保守方向，不是空壳**。叠加 DSR 用 N=10 > 有效 2（haircut 更严），
两处都朝严的一侧。故不动机制，理由还有两条：`temperature=0` 的**可复现性本身是审计资产**
（任何人重跑得到同一批决策，对「唯一验收证据」比人造离散度值钱）；提温度要动冻结 `signal_params`
⇒ 第 4 次重冻，换来的是往证据里主动加噪。

**但有一点必须落到口径上：不得把它报成「seed 稳健性通过」。** 本模块就干这一件事——
把这句话做成每轮 round JSON 里的结构化字段（而非散文备注），且**属报告口径，不动冻结文本**。

两个把散文变成可观测量的点：

* `quantile_caliber()` 用**真 `seed_distribution()`** 现算一遍，把「下四分位 = 较差变体」
  从声明变成**每轮实测的证据**；顺带记下该等式成立的边界（较差者需占 ≥4/10；本轨 5/5 结构性满足，
  实测 3/10 时为 0.175 ≠ min），这样万一将来变体数被改动，口径不会**继续声称**一个已不成立的性质。
* `seed_semantics()` 吃 `determinism.py` 的漂移状态：**一旦检出模型漂移，seed 就从名义变成实际**
  （同名模型换了权重，同 seed 不再保证同输出），字段自动翻成 `nominal_assumption_broken`。
  「seed 什么时候从名义变成实际」由数据说，不由我们猜。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

CALIBER_DOC = "qlab/LLM_PAPER_REPORTING_CALIBER.md"

# 报告里**必须**照此措辞，且**不得**声称的东西
MUST_NOT_CLAIM: List[str] = [
    "seed 稳健性通过 / seed-robust",
    "跨 seed 结果稳定（temperature=0 下相同不叫稳定，叫同一次计算）",
    "下四分位体现了 seed 敏感性（它体现的是较差的 prompt 变体）",
]


def quantile_caliber(quantile: float = 0.25, *,
                     n_seeds: int = 5, n_variants: int = 2) -> Dict[str, Any]:
    """用**真** `seed_distribution()` 现算，把「下四分位 = 较差变体」变成每轮实测证据。"""
    from research.gate.llm_paradigm import seed_distribution
    a, b = 0.40, 0.10                                   # 两个变体的假想读数（仅用于验性质）
    per_variant = n_seeds
    vals = [a] * per_variant + [b] * per_variant
    r = seed_distribution(vals, quantile=quantile)
    equals_worse = abs(r.judged - min(vals)) < 1e-12
    # 边界：等式要求较差者占比足以盖住插值位置 quantile×(n−1) 的上取整格
    n = n_seeds * n_variants
    boundary = {}
    for k in range(1, n):
        rk = seed_distribution([b] * k + [a] * (n - k), quantile=quantile)
        boundary[f"worse_count_{k}"] = {"judged": float(rk.judged),
                                        "equals_worse": abs(rk.judged - b) < 1e-12}
    min_k = next((k for k in range(1, n)
                  if boundary[f"worse_count_{k}"]["equals_worse"]), None)
    return {
        "quantile": quantile,
        "grid": f"{n_seeds} seeds × {n_variants} variants = {n} cells",
        "measured_judged": float(r.judged),
        "measured_min": float(min(vals)),
        "lower_quartile_equals_worse_variant": bool(equals_worse),
        "min_worse_count_for_equality": min_k,
        "worse_count_is": per_variant,
        "boundary_scan": boundary,
        "reading": ("在本轨冻结的 5/5 等分网格下，下四分位**结构性地等于较差的 prompt 变体**"
                    "（较差者占 5 ≥ 阈值 {})——保守方向、非空壳；"
                    "该等式在较差者占比低于阈值时不再成立，故变体数一经改动本口径即失效。").format(min_k),
    }


def seed_semantics(determinism_status: Optional[str] = None, *,
                   temperature: float = 0.0, n_seeds: int = 5,
                   n_variants: int = 2) -> Dict[str, Any]:
    """seed 口径块。**报告必须原样带上这块**（工部 2026-08-08 第二节）。"""
    from qlab.llm_paper.determinism import STATUS_DRIFT, STATUS_OK
    nominal = (temperature == 0.0)
    broken = (determinism_status == STATUS_DRIFT)
    return {
        "temperature": temperature,
        "seed_status": ("nominal_assumption_broken" if broken else
                        ("nominal" if nominal else "effective")),
        "statement": (
            "`temperature=0`，**seed 为名义值、不产生离散**；离散度由 2 个 prompt 变体承担；"
            "`seed_distribution` 的 25% 分位在此配置下等于**较差的那个变体**。"),
        "dispersion_carried_by": f"{n_variants} prompt variants (pv1_baseline / pv2_riskaware)",
        "n_seeds_nominal": n_seeds,
        "effective_distinct_outputs": (None if broken else n_variants),
        "dsr_n_used": n_seeds * n_variants,
        "dsr_note": ("DSR 仍按冻结网格 N=10 计（> 有效 2）⇒ 多重检验 haircut 偏严，"
                     "与下四分位取较差变体同朝保守一侧。"),
        "must_not_claim": MUST_NOT_CLAIM,
        "ruling": "工部 2026-08-08 第二节：不改 temperature、不重冻；仅改报告口径措辞。",
        "determinism_status": determinism_status,
        "drift_consequence": (
            "已检出模型漂移 ⇒ **seed 自此由名义变为实际**（同名模型换权重后，同 seed 不再保证同输出），"
            "此前「seed 无离散」的口径对漂移后的区段不再成立，需与工部判定证据期是否重新起算。"
            if broken else
            ("金标准复现逐字一致 ⇒ 「seed 名义化」的前提经本轮实测仍成立。"
             if determinism_status == STATUS_OK else
             "本轮未验证到确定性（无基线或未做比对）⇒ seed 名义化只是**假设**，不得当已验证。")),
        "caliber_doc": CALIBER_DOC,
    }

"""EVO-8 LLM 轨 — 组合约束不过时取什么动作（吏部 2026-08-27 裁定，**08-31 当轮生效**）。

**规则**：某格的 book 未过 `check_portfolio` ⇒ 该格**本轮不调仓**（有前轮持仓则原样维持，无则
全现金），违规如实落盘，**该格仍计入 `n_evaluated`**，本轮其余格与整轮落盘照常进行。

取代的旧行为是整轮 `raise`（`run_round.py` / `multi_book.py` 各一处）——那两处都发生在
**取完行情、产完决策、round JSON 尚未落盘**之处，与台账那条（`RefreezeError`）完全同型：
「跑了等于没跑」。这条轨已经证明它有不止一处这样的路径，不该主动再留第三条。

**本模块只实现退化形态：无前轮持仓 ⇒ 全现金。** 一般形态的 carry-forward（维持上一轮 shares）
归对照通过之后那批。退化形态在 08-31 成立是有实测依据的，不是假设：`qlab/reports/llm_paper/`
下只有 `round_20260810.json` 一份记录且 `book.status = pending_entry_bar`（无 shares、无 gross）
⇒ 每一格的「上一轮持仓」都是空的。全现金也不是新语义：冻结 §2 明写现金上限 100%、允许全现金，
`check_portfolio([])` 实测 `ok=True / gross=0 / cash=1.0`，不需要任何豁免分支。

**但退化形态一旦在有前轮持仓的轮次被误用，就会把「不调仓」做成「清仓」**——方向完全相反且静默。
故 `assert_no_prior_position()` 在动作前查一遍历史落盘记录，查到就 fail-closed，
绝不用退化形态糊弄一般形态。

边界（吏部原文，一条都不许扩散）：

1. **只适用于 `check_portfolio` 对该格自身 book 的判定。** 其他失败一律维持整轮 fail-closed：
   缺价、金标准探针、逐条时序核验、台账、配额、决策链路（`build_decision` 的逐行上限与禁做空
   仍在决策阶段抛，本模块管不到，也不该管）。
2. **空格子不适用**（没有提案 ≠ 提案违规）。
3. **格子永远不许从 `n_evaluated` 掉出去**；本模块不删格、不跳格。
4. **禁止把违规权重投影 / 截断 / 缩放到合规**（0.12 压成 0.10 那类）。那是给冻结策略加了一层
   没预注册的风险覆盖，而且「压谁、按比例还是只削超限腿」有多种做法可选，可调的东西迟早被调。
   违规就是违规，**动作取空动作**。本模块不含任何权重变换。
5. **留档必须够重建**：格子 id、seed × 变体、模型提出的原始权重、触发哪条约束、超出多少；
   `check_portfolio` 的返回原样落盘，不压成一个布尔。

**现金按现状记零收益字面现金**（`nav - gross - cost`）。冻结散文里的「现金即 BIL 口径」与实现
不一致是一条既存偏离，吏部 2026-08-27 已裁 (c)：口径钉死、实现放对照之后、**08-31 轮内一行不改**、
BIL 不进符号并集、不进配额、永不因缺 BIL 死轮。本模块因此不碰计息。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from qlab.llm_paper.errors import PreflightFailed
from qlab.llm_paper.ledger_bridge import cell_id

NO_REBALANCE = "no_rebalance"

Cell = Tuple[int, str]


def _agg_weights(decisions: Sequence[Any]) -> Dict[str, float]:
    agg: Dict[str, float] = {}
    for d in decisions:
        agg[d.symbol] = agg.get(d.symbol, 0.0) + float(d.target_weight)
    return dict(sorted(agg.items()))


def violation_report(port: Dict[str, Any], decisions: Sequence[Any], cfg: Dict[str, Any],
                     *, cell_id: Optional[str] = None) -> Dict[str, Any]:
    """违规留档 —— **够重建**（吏部边界 5）。`check_portfolio` 的返回原样带上，不压成布尔。"""
    sp = cfg["signal_params"]
    cap = float(sp["single_name_cap"])
    agg = _agg_weights(decisions)
    return {
        "cell_id": cell_id,
        "seed": (decisions[0].seed if decisions else None),
        "prompt_variant": (decisions[0].prompt_variant if decisions else None),
        # 模型提出的**原始**权重，逐行原样（聚合前）——重建的起点
        "proposed_rows": [{"symbol": d.symbol, "target_weight": float(d.target_weight),
                           "confidence": float(d.confidence)} for d in decisions],
        "aggregated_weights": agg,              # 上限按聚合值判，故聚合值也要留
        "violations_single_name": list(port.get("violations_single_name") or []),
        "violations_short": list(port.get("violations_short") or []),
        "gross": port.get("gross"), "gross_cap": port.get("gross_cap"),
        "single_name_cap": cap, "leverage_ok": port.get("leverage_ok"),
        # 超出多少：单标的按聚合值算，总仓按 gross 算
        "exceeded_by": {s: round(agg[s] - cap, 12)
                        for s in (port.get("violations_single_name") or []) if s in agg},
        "gross_exceeded_by": (round(float(port["gross"]) - float(port["gross_cap"]), 12)
                              if port.get("gross") is not None
                              and float(port.get("gross", 0)) > float(port.get("gross_cap", 1))
                              else None),
        "portfolio_check": dict(port),          # 原样落盘
        "action_taken": NO_REBALANCE,
        "action_rule": ("吏部 2026-08-27 裁定：约束不过 ⇒ 该格本轮不调仓、如实留档、"
                        "仍计入 n_evaluated；本轮其余格与整轮落盘照常。"),
        "prohibited": ("禁止把违规权重投影 / 截断 / 缩放到合规——违规就是违规，动作取空动作。"
                       "本轮未对任何权重做变换。"),
        "carry_forward_form": ("本轮为退化形态（无前轮持仓 ⇒ 全现金）；"
                               "一般形态 carry-forward 归对照通过之后那批。"),
    }


def cells_with_position(out_dir: str) -> Dict[str, str]:
    """历史落盘记录里**已真正建过仓**的格子 → 该轮 stamp。用于拦住退化形态被误用。

    只认 `status == "filled"` 且 shares 非空：`pending_entry_bar` / `missing_entry_open` /
    `no_rebalance` 三种都不构成持仓。坏文件不静默跳过——查不清历史就不许走退化形态。
    """
    seen: Dict[str, str] = {}
    p = Path(out_dir)
    if not p.exists():
        return seen
    for f in sorted(p.glob("round_*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise PreflightFailed(
                f"{f.name} 无法解析 → 无从判断各格有无前轮持仓，拒绝走「不调仓」退化形态"
                f"（误用会把不调仓做成清仓，方向相反且静默）：{e}") from e
        stamp = f.name.replace("round_", "").replace(".json", "")
        blocks = list((payload.get("cells") or {}).items())
        if not blocks:                                   # (a) 单 book 轮
            keys = {(int(d["seed"]), str(d["prompt_variant"]))
                    for d in payload.get("decisions") or []
                    if "seed" in d and "prompt_variant" in d}
            if len(keys) == 1:
                s, v = next(iter(keys))
                blocks = [(cell_id(s, v), payload)]
        for cid, blk in blocks:
            book = blk.get("book") or {}
            if book.get("status") == "filled" and book.get("shares"):
                seen[cid] = stamp
    return seen


def assert_no_prior_position(out_dir: str, cell_id: str) -> None:
    """退化形态的前提检查：该格此前从未建过仓。查到持仓即 fail-closed。

    **这不是保守，是防反向**：有前轮持仓时套用「全现金」＝把「不调仓」做成「清仓」，
    方向完全相反，而且落盘后看不出来。一般形态未裁定实现之前，这里必须停。
    """
    seen = cells_with_position(out_dir)
    if cell_id in seen:
        raise PreflightFailed(
            f"格 {cell_id} 在 {seen[cell_id]} 那一轮已建过仓 ⇒ 「不调仓」的正确动作是"
            f"**维持上一轮持仓**，而本模块只实现了退化形态（全现金）。"
            "套用退化形态会把不调仓做成清仓，方向相反且静默 —— 停下，"
            "等 carry-forward 一般形态（吏部：归对照通过之后那批）实现后再跑。")


def no_rebalance_book(*, nav: float, cfg: Dict[str, Any],
                      violation: Dict[str, Any]) -> Dict[str, Any]:
    """「不调仓」的 book —— 退化形态：**无前轮持仓 ⇒ 全现金**，零交易、零成本。

    形状与 `build_book` 的 `filled` 对齐（同样的键），只是 `status` 不同、持仓为空，
    好让下游（盯市 / 净值序列 / 并行对照比对）不必为它开特例。
    """
    return {
        "status": NO_REBALANCE,
        "nav_start": float(nav),
        "shares": {}, "entries": {},
        "gross_notional": 0.0,
        "cash": float(nav),                 # 全现金：零收益字面现金（BIL 计息层另裁、未实现）
        "entry_cost": 0.0,                  # 空动作 ⇒ 零换手 ⇒ 零成本，x1/x2 同值
        "cost_rate_per_side": float(cfg["cost_per_turnover"]),
        "cost_mult": None,
        "no_rebalance": True,
        "reason": ("组合约束不过 ⇒ 本轮不调仓（吏部 2026-08-27 裁定）。"
                   "无前轮持仓 ⇒ 该格本轮全现金；冻结 §2 允许全现金，非豁免。"),
        "violation": violation,
        "note": ("现金为零收益字面现金；冻结散文「现金即 BIL 口径」的计息层由吏部 2026-08-27 "
                 "裁 (c) 另行实现（不进符号并集、不进配额、永不因缺 BIL 死轮），本轮未实现。"),
    }


def no_rebalance_nav_point(book: Dict[str, Any], *, as_of: Optional[str]) -> Dict[str, Any]:
    """全现金格的净值点 —— 值是**确定**的（100% 现金），不是估的，故照实落。

    与「未建仓的轮次不补持平点」不冲突：那条禁的是给**尚未确定**的仓位编一个读数；
    这里的仓位已经确定为全现金，其净值恰等于 `nav_start`。
    `no_rebalance` 标记必须此刻写进不可改的记录——落盘后无法补，后来的审计层补不回来。
    """
    return {"as_of": as_of, "nav": book["cash"], "nav_x2_cost": book["cash"],
            "nav_start": book["nav_start"], "no_rebalance": True}

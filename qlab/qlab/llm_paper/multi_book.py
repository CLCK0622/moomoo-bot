"""EVO-8 LLM 轨 — **多 book 执行器**（分叉 (b)，吏部 2026-08-10 裁定 / 工部尚书 2026-08-27 派单）。

冻结 §4 报 `seed_distribution` 的下四分位，隐含**每个网格格子各有自己的业绩读数**（10 个并行 book）。
`run_round()` 一轮只算一个 book，于是第 1 轮只落了第 1 格（`seed11×pv1_baseline`），其余 9 格靠
「权重留档 + 离线重建」。离线重建在数学上精确，但**承载验收判据的路径必须在树上、有单测、跑过**，
不能是每轮手工重建的脚本——两条路径并行数月必然静默分叉。本模块就是把那条路径搬进树里。

形态（吏部裁定的正确形态，也是唯一在配额上成立的形态）：

    **一次取符号并集 → 内部按格分账**    ≈ 8 次/轮，不是 10 × 8 = 80 次

每格自带：决策集、组合约束核验、book、x2 影子 book、盯市读数、净值点。跨轮的**每格净值序列**
由 `nav_series.py` 从各轮不可改的 round JSON 机械拼出（(a)/(b) 两种落盘格式都认）。

**边界（一条都不松）**：
* 冻结文本 / 决策逻辑 / 冻结参数一律不动 —— 决策仍走 `build_decision`，约束仍走 `check_portfolio`，
  建仓仍走 `build_book`，探针仍走 `determinism`，本模块**只做编排**，不复制其中任何一段逻辑；
* 组合约束**按格逐一判**（每格是一个独立组合，不是把 10 格加总去判）；某格不过 ⇒ **该格本轮不调仓**、
  如实留档、仍计入 `n_evaluated`，**本轮其余格与整轮落盘照常**（吏部 2026-08-27 裁定，08-31 当轮生效；
  细则与边界见 `rebalance_policy.py`）。其余任何失败——缺价 / 探针 / 时序核验 / 台账 / 配额 /
  决策链路——**一律维持整轮 fail-closed**，宁可不起跑也不产出半截证据；
* `n_trials_total` 恒按冻结 10 格足额登记（`ledger_bridge`），`n_evaluated` 取跨轮并集；
* **不出 verdict**：中途读数只作监控，判定一律留给 `certify()` + `llm_paradigm`（预注册 §4）。

**接管纪律**：(b) 通过等价性验证前不接管承载路径，轮次照 (a) 跑（证据连续性高于本次重构）。
等价性两段：① 决策集与第 1 轮 `f2f7729` 逐位比对（`tests/test_multi_book.py`，现在就能跑）；
② book 等价性在与 (a) 并行的那一轮做对照。**并行对照轮的 (b) 必须 `register_trials=False`**——
对照不是承载路径，二次登记只会拿到幂等旧记录、把 `n_evaluated` 记歪。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qlab.events.datafetch.api_quota import guard_from_env  # noqa: E402
from qlab.events.datafetch.quotes_api import mark_to_market, trading_days  # noqa: E402
from qlab.llm_paper.decision_chain import (build_decision, check_portfolio,  # noqa: E402
                                           frozen_grid, load_prereg)
from qlab.llm_paper.determinism import (STATUS_DRIFT, ProbeUnverifiable,  # noqa: E402
                                        verify_or_establish)
from qlab.llm_paper.errors import PreflightFailed  # noqa: E402
from qlab.llm_paper.ledger_bridge import (cell_id,  # noqa: E402,F401  （原样再导出）
                                          register_round)
from qlab.llm_paper.price_bridge import settle_actual_start  # noqa: E402
from qlab.llm_paper.quote_bridge import (fetch_round_quotes,  # noqa: E402
                                         require_injected_bars)
from qlab.llm_paper.rebalance_policy import (assert_no_prior_position,  # noqa: E402
                                             no_rebalance_book,
                                             no_rebalance_nav_point, violation_report)
from qlab.llm_paper.reporting import quantile_caliber, seed_semantics  # noqa: E402
from qlab.llm_paper.run_round import (CANDIDATE_ID, OUT_DIR, START_NAV,  # noqa: E402
                                      build_book, preflight)

EXECUTOR = "multi_book_v1"

# 每条决策里**被等价性验证逐位比对**的字段（工部尚书 2026-08-27 指定：symbol/weight/seed/
# prompt_variant/三时间戳）。列在这里而不是散在测试里，是为了让「比了哪几项」本身可审计。
EQUIVALENCE_FIELDS: Tuple[str, ...] = (
    "symbol", "target_weight", "seed", "prompt_variant",
    "evidence_available_utc", "decision_ts", "intended_start",
)


def expand_variants(variant_proposals: Dict[str, Sequence[Dict[str, Any]]],
                    cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """把「每个 prompt 变体一份目标仓位」展开成冻结网格的**足额格子列表**。

    依据是冻结自己的口径：`temperature=0` ⇒ seed 为**名义值、不产生离散**（`reporting.py`），
    故同一变体在 5 个 seed 上逐字同输出。展开而非手写 10 份，是为了让「10 格足额」成为机械结果，
    而不是每轮靠人记得复制 5 遍。**不改 temperature、不重冻**。
    """
    cfg = cfg or load_prereg()
    grid = frozen_grid(cfg)
    missing = sorted({g["prompt_variant"] for g in grid} - set(variant_proposals))
    if missing:
        raise PreflightFailed(
            f"冻结网格含变体 {missing}，但未给出其目标仓位 ⇒ 格子会缺读数。"
            "若本轮确实只跑部分变体，请显式构造 cells（缺格会如实记进 cells_missing）。")
    extra = sorted(set(variant_proposals) - {g["prompt_variant"] for g in grid})
    if extra:
        raise PreflightFailed(f"变体 {extra} 不在冻结网格内（family 跑后不得增删）")
    return [{"seed": g["seed"], "prompt_variant": g["prompt_variant"],
             "proposals": list(variant_proposals[g["prompt_variant"]])} for g in grid]


def _validate_cells(cells: Sequence[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """格子入参自检：都在冻结网格内、不重复、每格提案的 seed/变体不得与格子自相矛盾。"""
    grid = {(g["seed"], g["prompt_variant"]) for g in frozen_grid(cfg)}
    seen, out = set(), []
    for c in cells:
        key = (int(c["seed"]), str(c["prompt_variant"]))
        if key not in grid:
            raise PreflightFailed(f"格子 {cell_id(*key)} 不在冻结网格内（family 跑后不得增删）")
        if key in seen:
            raise PreflightFailed(f"格子 {cell_id(*key)} 重复出现 ⇒ 同一格两个读数，不予评估")
        if not c.get("proposals"):
            raise PreflightFailed(f"格子 {cell_id(*key)} 无提案 —— 空格子不是「持现金」，是漏了")
        for p in c["proposals"]:
            # 提案里若带了 seed/变体，必须与格子一致：不一致说明决策阶段串了格，
            # 静默以格子为准会把 A 格的决策记成 B 格的证据。
            if "seed" in p and int(p["seed"]) != key[0]:
                raise PreflightFailed(f"格子 {cell_id(*key)} 的提案 {p.get('symbol')} 标了 seed={p['seed']}")
            if "prompt_variant" in p and str(p["prompt_variant"]) != key[1]:
                raise PreflightFailed(
                    f"格子 {cell_id(*key)} 的提案 {p.get('symbol')} 标了 variant={p['prompt_variant']}")
        seen.add(key)
        out.append({"seed": key[0], "prompt_variant": key[1], "proposals": list(c["proposals"])})
    return out


def symbol_union(cells: Sequence[Dict[str, Any]], benchmark: str = "SPY") -> List[str]:
    """本轮要取的**符号并集** —— 全部格子的标的 ∪ 基准。配额只按这一份算。"""
    syms = {benchmark}
    for c in cells:
        syms |= {p["symbol"] for p in c["proposals"]}
    return sorted(syms)


def decision_fingerprint(entry: Any) -> Dict[str, Any]:
    """取一条决策的等价性指纹（`Decision` 对象与已落盘 JSON 条目都吃）。"""
    get = (entry.get if isinstance(entry, dict) else lambda k: getattr(entry, k))
    fp = {k: get(k) for k in EQUIVALENCE_FIELDS}
    fp["target_weight"] = float(fp["target_weight"])
    fp["seed"] = int(fp["seed"])
    return fp


def compare_decision_sets(left: Sequence[Any], right: Sequence[Any]) -> Dict[str, Any]:
    """两组决策**逐位比对**（按 symbol 排序后逐字段比）。用于 (b) 接管前的等价性验证第 ① 段。"""
    lf = sorted((decision_fingerprint(d) for d in left), key=lambda x: x["symbol"])
    rf = sorted((decision_fingerprint(d) for d in right), key=lambda x: x["symbol"])
    diffs: List[Dict[str, Any]] = []
    if len(lf) != len(rf):
        diffs.append({"kind": "n_decisions", "left": len(lf), "right": len(rf)})
    for a, b in zip(lf, rf):
        for k in EQUIVALENCE_FIELDS:
            if a[k] != b[k]:
                diffs.append({"kind": "field", "symbol": a["symbol"], "field": k,
                              "left": a[k], "right": b[k]})
    return {"identical": not diffs, "n_left": len(lf), "n_right": len(rf),
            "fields_compared": list(EQUIVALENCE_FIELDS), "diffs": diffs}


def _run_cell(cell: Dict[str, Any], *, decision_ts, bars: Dict[str, Any], days,
              cfg: Dict[str, Any], nav: float, out_dir: str) -> Dict[str, Any]:
    # `out_dir` 在这里只用于查前轮持仓（见 run_round_multi 的 position_history_dir）。
    """单格分账 —— 决策 / 约束 / 建仓 / 盯市，全部复用既有实现，本函数不新写任何一段。"""
    cid = cell_id(cell["seed"], cell["prompt_variant"])
    decisions = [build_decision(
        symbol=p["symbol"], target_weight=p["target_weight"], confidence=p["confidence"],
        thesis=p["thesis"], evidence_records=p["evidence_records"], decision_ts=decision_ts,
        seed=cell["seed"], prompt_variant=cell["prompt_variant"], model=p.get("model", ""),
        cfg=cfg, observed_days=days) for p in cell["proposals"]]

    # 约束按格判：每格是一个**独立组合**，不是把 10 格加总（加总会把 10 个 49% 判成 490% 超限）。
    # 不过**不再整轮 raise**（吏部 2026-08-27 裁定）：该格本轮不调仓、如实留档、仍计入
    # n_evaluated，**本轮其余格与整轮落盘照常**。无违规时下面与加规则前逐位相同。
    port = check_portfolio(decisions, cfg)
    violation = None
    if not port["ok"]:
        assert_no_prior_position(out_dir, cid)   # 有前轮持仓 ⇒ 退化形态不适用，停下
        violation = violation_report(port, decisions, cfg, cell_id=cid)

    settle = settle_actual_start(decisions, bars)
    if violation is not None:
        book = no_rebalance_book(nav=nav, cfg=cfg, violation=violation)
        book_x2 = None                                   # 零换手 ⇒ 无成本可加倍
        mtm = mark_to_market({}, bars, as_of=(days[-1] if days else None))
        nav_point = no_rebalance_nav_point(book, as_of=mtm["as_of"])
    else:
        book = build_book(decisions, bars, cfg, nav=nav)
        book_x2 = (build_book(decisions, bars, cfg, nav=nav, cost_mult=2.0)
                   if book["status"] == "filled" else None)
        if book["status"] == "filled":
            mtm = mark_to_market(book["shares"], bars)
            nav_point = {"as_of": mtm["as_of"], "nav": mtm["market_value"] + book["cash"],
                         "nav_x2_cost": (mtm["market_value"] + book_x2["cash"]) if book_x2 else None,
                         "nav_start": book["nav_start"]}
        else:
            mtm, nav_point = None, None   # 仓位未建立 ⇒ 绝不编净值点（与 (a) 同一条规矩）
    return {"cell_id": cid, "seed": cell["seed"], "prompt_variant": cell["prompt_variant"],
            "n_decisions": len(decisions), "portfolio_check": port,
            "no_rebalance": violation is not None, "violation": violation,
            "actual_start_settlement": settle, "book": book, "book_x2_cost": book_x2,
            "mark_to_market": mtm, "nav_point": nav_point,
            "decisions": [d.to_log_entry() for d in decisions]}


def run_round_multi(*, cells: Sequence[Dict[str, Any]], decision_ts,
                    probe: Optional[Dict[str, str]] = None,
                    benchmark: str = "SPY", out_dir: str = OUT_DIR,
                    cfg: Optional[Dict[str, Any]] = None,
                    rejected_evidence: Optional[Sequence[Dict[str, Any]]] = None,
                    register_trials: bool = True,
                    nav_start: float = START_NAV,
                    bars: Optional[Dict[str, Any]] = None,
                    position_history_dir: Optional[str] = None) -> Dict[str, Any]:
    """执行一次**多 book** 决策轮：一次取符号并集，内部按格分账。

    `cells`：`[{seed, prompt_variant, proposals: [...]}, ...]`（`expand_variants()` 可由每变体
    一份目标仓位展开成足额 10 格）。`proposals` 每项与 `run_round()` 同构：
    {symbol, target_weight, confidence, thesis, evidence_records, model?}。

    `probe`：本轮金标准复现结果，**每轮一次、按轮不按格**（探针测的是模型本身有没有被换权重，
    与格子无关）。缺失即 `PreflightFailed`，不设跳过开关。

    `bars`：**行情注入**，仅用于并行对照轮（同一份快照喂 (a) 与 (b)）。默认 `None` ＝ 自己取数。

    `position_history_dir`：查「各格有无前轮持仓」时读哪个目录，默认同 `out_dir`。并行对照轮
    必须显式指向**承载目录**——对照写在一个每轮新建的子目录里，其历史恒为空，照它判会让 (b)
    在有前轮持仓时仍走全现金退化形态，而 (a) 会正确拒绝。那正是对照本身要发现的分歧，
    不该由目录选择制造出来。
    """
    cfg = cfg or load_prereg()
    cells = _validate_cells(cells, cfg)
    symbols = symbol_union(cells, benchmark)
    pre = preflight(n_symbols_needed=len(symbols), cfg=cfg, skip_quota_check=bars is not None)

    # ---- 金标准复现（放在花配额之前：护栏不过就别浪费当天额度） ----
    if not probe or not probe.get("output"):
        raise PreflightFailed(
            "缺金标准复现结果（probe={'model':…,'output':…}）→ 不起跑。"
            "同名模型被换权重时净值序列不会有任何提示，本轨按年计，这个混淆因子必须逐轮观测；"
            "**不提供跳过开关**——可跳过的护栏等于没有护栏。")
    stamp = pd.Timestamp(decision_ts).strftime("%Y%m%d")
    out = Path(out_dir)
    try:
        det = verify_or_establish(output=probe["output"], model=probe.get("model", ""),
                                  round_id=f"{CANDIDATE_ID}-{stamp}")
    except ProbeUnverifiable as e:
        raise PreflightFailed(f"金标准复现无法测量 → fail-closed：{e}") from e
    seeds_block = seed_semantics(det["status"])

    # ---- 取行情：**整轮一次**，符号并集（(b) 的全部配额意义就在这一行） ----
    injected = bars is not None
    if injected:
        bars = require_injected_bars(bars, symbols)
    else:
        bars = fetch_round_quotes(symbols, stamp=stamp, out_dir=out_dir,
                                  executor=EXECUTOR, guard=guard_from_env())
    days = trading_days(bars)

    # ---- 按格分账（任一格约束不过 → 抛出，整轮零落盘） ----
    results = [_run_cell(c, decision_ts=decision_ts, bars=bars, days=days, cfg=cfg,
                         nav=nav_start, out_dir=(position_history_dir or out_dir))
               for c in cells]
    by_cell = {r["cell_id"]: r for r in results}

    grid = frozen_grid(cfg)
    done = {(c["seed"], c["prompt_variant"]) for c in cells}
    missing = [cell_id(g["seed"], g["prompt_variant"]) for g in grid
               if (g["seed"], g["prompt_variant"]) not in done]

    ledger_rec = None
    if register_trials:
        ledger_rec = register_round(decision_ts=decision_ts, cfg=cfg, cells_this_round=done,
                                    out_dir=out_dir, executor=EXECUTOR)

    alerts = [STATUS_DRIFT] if det["drift"] else []
    payload = {
        "round_decision_ts": pd.Timestamp(decision_ts).isoformat(),
        "executor": EXECUTOR,
        "executor_note": ("多 book：一次取符号并集、内部按格分账；轮内 nav_point 仅为 round-record "
                          "artifact，权威跨轮净值序列由 derived_settlement 重算。"),
        "preflight": pre,
        "symbols_fetched": symbols,
        "quote_calls_this_round": 0 if injected else len(symbols),
        "quote_calls_if_naive_per_cell": len(symbols) * len(cells),
        "bars_injected": injected,      # 并行对照轮共用上游快照 ⇒ 本轮自身零调用
        "n_cells_evaluated": len(cells),
        "n_cells_frozen_grid": len(grid),
        "cells_missing": missing,
        "cells_no_rebalance": sorted(r["cell_id"] for r in results if r["no_rebalance"]),
        "n_decisions": sum(r["n_decisions"] for r in results),
        "cells": by_cell,
        "ledger": ledger_rec,
        "rejected_evidence": list(rejected_evidence or []),
        "determinism": det,
        "gold_probe_output": probe["output"],
        "seed_semantics": seeds_block,
        "seed_quantile_caliber": quantile_caliber(),
        "alerts": alerts,
        "verdict": None,
        "note": "中途读数只作监控、**不出 verdict**；判定一律走 certify()+llm_paradigm（预注册 §4）",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / f"round_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if det["drift"]:
        (out / f"ALERT_model_drift_{stamp}.json").write_text(
            json.dumps({"alert": STATUS_DRIFT, "round": stamp, "determinism": det,
                        "executor": EXECUTOR,
                        "action_required": "立刻回报工部；判定证据期是否重新起算；基线不得改写",
                        "seed_semantics": seeds_block},
                       ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload

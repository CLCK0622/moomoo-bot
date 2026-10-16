"""EVO-8 LLM 轨 — **(a)/(b) 并行对照**（等价性验证第 ② 段：book 等价性）。

工部尚书 2026-08-27 派单：08-31 那轮**一次取行情、同一份 bars 同时喂 (a) 与 (b)**，逐位比
`shares` / `entries` / `gross` / `cash` / `nav_point`，不一致就停下回报、不切换。

**为什么必须共用同一份快照**——不是配额（本轨走 `purpose=MARKING`，可用全额 25，8+8 装得下），
是**对照有效性**：两次取数之间只要有任何一根 bar 变动，比对就会因为与执行器无关的原因而
失败或通过，对照本身白做。(a)/(b) 都是 `(decisions, bars)` 的确定性函数，同一快照喂两边是
结构上唯一正确的做法。

## 三条安全性质（本模块的全部价值都在这里）

1. **承载路径先跑、先落盘。** (a) 是这一轮的真记录；(b) 只是对照。顺序固定为「(a) 跑完 →
   (b) 跑」，且 **(b) 整段包在 try/except 里**——对照侧无论怎么炸都不许波及已落盘的 (a)。
   证据连续性高于对照，用一次对照失败换掉一个补不回来的日历轮次是荒唐的。
2. **对照侧不登记台账**（`register_trials=False`）。对照不是承载路径；同 run_id 二次登记只会
   拿到幂等旧记录，把 `n_evaluated` 记歪（`ledger_bridge` 会标 `ledger_reused_existing_record`）。
3. **两侧落盘目录必须不同。** 两条路径都写 `round_<stamp>.json`——同目录会让 (b) 的对照记录
   **覆盖掉 (a) 的承载记录**，且悄无声息。本模块拒绝同目录启动，不留这条路。
   对照记录默认写进 `<out_dir>/control_multi_book/`（子目录不会被 `round_*.json` 的
   非递归 glob 扫到，故不污染 `nav_series` 与台账并集）。

比对结果落一份 `CONTROL_<stamp>.json`（**刻意不叫 `round_*`**，同上）；不一致时另落
`ALERT_control_mismatch_<stamp>.json`——本轨的教训是「只以返回值形态存在的结论等于没留痕」。

**不出 verdict**，也**不自动切换**：本模块只给出 `may_take_over` 这一个事实判断，
换执行器是另一次人为动作，按裁定放在对照通过后的下一轮。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from qlab.llm_paper.decision_chain import load_prereg
from qlab.llm_paper.determinism import load_baseline
from qlab.llm_paper.errors import PreflightFailed
from qlab.llm_paper.multi_book import (EXECUTOR, cell_id, compare_decision_sets,
                                       run_round_multi, symbol_union)
from qlab.llm_paper.quote_bridge import fetch_round_quotes
from qlab.llm_paper.run_round import OUT_DIR, preflight, run_round

CONTROL_SUBDIR = "control_multi_book"

# 逐位比对的 book 字段（工部尚书 2026-08-27 指定）。列成常量而非散在代码里，
# 是为了让「比了哪几项」本身可审计——和 EQUIVALENCE_FIELDS 同一个理由。
BOOK_FIELDS: Tuple[str, ...] = ("status", "shares", "entries", "gross_notional", "cash",
                                "entry_cost", "nav_start")
NAV_FIELDS: Tuple[str, ...] = ("as_of", "nav", "nav_x2_cost", "nav_start")


def compare_books(a_payload: Dict[str, Any], b_cell: Dict[str, Any]) -> Dict[str, Any]:
    """(a) 的整轮 book 与 (b) 对应格的 book **逐位比对**（含 x2 影子腿与净值点）。"""
    diffs: List[Dict[str, Any]] = []
    a_book, b_book = a_payload.get("book") or {}, b_cell.get("book") or {}
    for f in BOOK_FIELDS:
        if a_book.get(f) != b_book.get(f):
            diffs.append({"kind": "book", "field": f,
                          "a": a_book.get(f), "b": b_book.get(f)})
    a_x2, b_x2 = a_payload.get("book_x2_cost"), b_cell.get("book_x2_cost")
    if (a_x2 is None) != (b_x2 is None):
        diffs.append({"kind": "book_x2_cost", "field": "presence",
                      "a": a_x2 is not None, "b": b_x2 is not None})
    elif a_x2 is not None:
        for f in ("cash", "entry_cost", "gross_notional"):
            if a_x2.get(f) != b_x2.get(f):
                diffs.append({"kind": "book_x2_cost", "field": f,
                              "a": a_x2.get(f), "b": b_x2.get(f)})
    a_nav, b_nav = a_payload.get("nav_point"), b_cell.get("nav_point")
    if (a_nav is None) != (b_nav is None):
        diffs.append({"kind": "nav_point", "field": "presence",
                      "a": a_nav is not None, "b": b_nav is not None})
    elif a_nav is not None:
        for f in NAV_FIELDS:
            if a_nav.get(f) != b_nav.get(f):
                diffs.append({"kind": "nav_point", "field": f,
                              "a": a_nav.get(f), "b": b_nav.get(f)})
    return {"identical": not diffs, "book_status": a_book.get("status"),
            "fields_compared": {"book": list(BOOK_FIELDS), "nav_point": list(NAV_FIELDS)},
            "diffs": diffs}


def _cell_of_path_a(a_payload: Dict[str, Any]) -> Tuple[int, str]:
    """(a) 那一个 book 属于哪一格。多于一格 ⇒ 对不上号，宁可抛也不猜。"""
    keys = {(int(d["seed"]), str(d["prompt_variant"])) for d in a_payload.get("decisions") or []}
    if len(keys) != 1:
        raise PreflightFailed(
            f"(a) 本轮含 {len(keys)} 个格子 {sorted(keys)} —— 它只产生一个 book，"
            "与 (b) 的哪一格对照无法确定，拒绝比对（猜就是造对照结论）。")
    return next(iter(keys))


def run_parallel_control(*, proposals: Sequence[Dict[str, Any]],
                         cells: Sequence[Dict[str, Any]], decision_ts,
                         probe: Optional[Dict[str, str]] = None,
                         benchmark: str = "SPY", out_dir: str = OUT_DIR,
                         control_dir: Optional[str] = None,
                         cfg: Optional[Dict[str, Any]] = None,
                         rejected_evidence: Optional[Sequence[Dict[str, Any]]] = None,
                         register_trials: bool = True) -> Dict[str, Any]:
    """跑一轮 (a) 承载 + (b) 对照，共用同一份行情快照，逐位比 book。

    `proposals` 给 (a)（承载路径，正常落盘 + 登记台账）；`cells` 给 (b)（对照，不登记）。
    返回对照报告；**(a) 的 payload 一并带出**，调用方拿到的仍是这一轮的真记录。
    """
    cfg = cfg or load_prereg()
    out = Path(out_dir)
    ctrl = Path(control_dir) if control_dir else out / CONTROL_SUBDIR
    if out.resolve() == ctrl.resolve():
        raise PreflightFailed(
            "对照目录不得与承载目录相同：两条路径都写 round_<stamp>.json，"
            "同目录会让对照记录**静默覆盖**承载记录。请另给 control_dir。")

    # 探针缺失要在**花配额之前**拦掉：本函数自己取数，(a)/(b) 内部的那道检查已经太晚。
    if not probe or not probe.get("output"):
        raise PreflightFailed(
            "缺金标准复现结果（probe={'model':…,'output':…}）→ 不起跑。"
            "**不提供跳过开关**——可跳过的护栏等于没有护栏。")
    # 基线必须已存在：否则 (a) 先跑会**建立**基线、(b) 随后拿刚写下的基线「验证」通过，
    # 两侧 determinism 状态凭空不同 —— 第 1 轮 determinism_ok/baseline_established 那个
    # 成色问题就是这么来的。对照轮不该同时是建基线轮。
    if load_baseline() is None:
        raise PreflightFailed(
            "金标准基线不存在 → 对照轮不起跑。对照轮同时建基线会让 (a) 建基线、"
            "(b) 验刚写下的基线，两侧 determinism 状态凭空不同、不可比。"
            "请先单独跑一轮 (a) 建立基线。")

    symbols = sorted(set(symbol_union(cells, benchmark)) | {p["symbol"] for p in proposals})
    stamp = pd.Timestamp(decision_ts).strftime("%Y%m%d")

    # ---- 唯一一次取行情：先 preflight 真配额，再取，两条路径共用这份快照 ----
    from qlab.events.datafetch.api_quota import guard_from_env
    pre = preflight(n_symbols_needed=len(symbols), cfg=cfg)
    bars = fetch_round_quotes(symbols, stamp=stamp, out_dir=out_dir,
                             executor="parallel_control", guard=guard_from_env())

    # ---- (a) 承载路径：先跑、先落盘。它是这一轮的真记录 ----
    a_payload = run_round(proposals=proposals, decision_ts=decision_ts, probe=probe,
                          benchmark=benchmark, out_dir=out_dir, cfg=cfg,
                          rejected_evidence=rejected_evidence,
                          register_trials=register_trials, bars=bars)

    report: Dict[str, Any] = {
        "control_of_round": stamp,
        "decision_ts": pd.Timestamp(decision_ts).isoformat(),
        "bearing_path": "single_book (a)",
        "control_path": f"{EXECUTOR} (b)",
        "shared_quote_snapshot": {
            "symbols": symbols, "n_calls": len(symbols),
            "why": ("对照有效性，不是配额：两次取数之间任何一根 bar 变动都会让比对结果"
                    "因与执行器无关的原因而失败或通过。"),
        },
        "bearing_round_file": str(out / f"round_{stamp}.json"),
        "control_round_file": str(ctrl / f"round_{stamp}.json"),
        "control_registered_trials": False,
        "verdict": None,
        "note": "对照只判执行器等价性，**不出 verdict**、不自动切换承载路径。",
    }

    # ---- (b) 对照：整段兜住，绝不许波及已落盘的 (a) ----
    try:
        cell = _cell_of_path_a(a_payload)
        b_payload = run_round_multi(cells=cells, decision_ts=decision_ts, probe=probe,
                                    benchmark=benchmark, out_dir=str(ctrl), cfg=cfg,
                                    rejected_evidence=rejected_evidence,
                                    register_trials=False, bars=bars,
                                    # 前轮持仓按**承载目录**判：对照子目录每轮新建、历史恒为空，
                                    # 照它判会让 (b) 与 (a) 在「有前轮持仓」时行为分歧。
                                    position_history_dir=out_dir)
        cid = cell_id(*cell)
        if cid not in b_payload["cells"]:
            raise PreflightFailed(
                f"(b) 本轮未评估 (a) 所在的格 {cid}（实评 {sorted(b_payload['cells'])}）"
                " ⇒ 无从对照。请让对照侧的 cells 覆盖 (a) 的那一格。")
        b_cell = b_payload["cells"][cid]
        book_cmp = compare_books(a_payload, b_cell)
        dec_cmp = compare_decision_sets(a_payload["decisions"], b_cell["decisions"])
        report.update({
            "compared_cell": cid,
            "control_cells_evaluated": b_payload["n_cells_evaluated"],
            "control_quote_calls": b_payload["quote_calls_this_round"],   # 应为 0（快照注入）
            "book_comparison": book_cmp,
            "decision_set_comparison": dec_cmp,
            "identical": bool(book_cmp["identical"] and dec_cmp["identical"]),
        })
    except Exception as e:                     # noqa: BLE001 —— 对照失败不是轮次失败
        report.update({
            "identical": False,
            "control_error": f"{type(e).__name__}: {e}",
            "control_error_note": ("对照侧失败**不影响本轮承载记录**（(a) 已落盘、已登记）。"
                                   "按裁定：停下回报、不切换。"),
        })

    # **book 等价性是否真的被检验过** —— 空 book 上的「逐位相同」是**空过**，不是通过。
    # 决策先于建仓日的轮次（`pending_entry_bar`）两侧都没有 shares / 没有净值点，比对必然
    # identical；违规不调仓的轮次（`no_rebalance`）两侧都是空持仓，「权重 → 股数按建仓日 open」
    # 那段算术同样一行没跑。拿这种结果去许可切换，正是本轨一路在堵的 fail-open 形态。
    status = (report.get("book_comparison") or {}).get("book_status")
    report["book_equivalence_exercised"] = (status == "filled")
    report["may_take_over"] = bool(
        report.get("identical") and "control_error" not in report
        and report["book_equivalence_exercised"])
    if report["may_take_over"]:
        report["take_over_note"] = (
            "对照通过 ⇒ 可在**下一轮**切换承载路径（裁定：不在对照当轮切，那一轮已同时背着"
            "恢复轮次与台账修复后首次登记两件事，再叠加切换将无法归因）。切换轮次回填进 "
            "EXECUTOR_CHANGE_NOTE.md。")
    elif report.get("identical") and not report["book_equivalence_exercised"]:
        report["take_over_note"] = (
            f"本轮 book 状态为 `{status}` ⇒ **两侧都没有持仓，逐位相同是空过**，"
            "第 ② 段（book 等价性）**未被实际检验**。不得据此切换；"
            "等一个真正产生 filled book 的轮次再跑一次对照。")
    else:
        report["take_over_note"] = "对照未通过 ⇒ **不得切换**，停下回报工部尚书。"

    out.mkdir(parents=True, exist_ok=True)
    # 刻意不叫 round_*.json：那个名字会被 nav_series 与台账并集的 glob 扫到。
    (out / f"CONTROL_{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if report.get("identical") and not report["book_equivalence_exercised"]:
        # 空过与不一致是两回事，留痕也不该同名——同名会让「这轮什么都没比到」被读成「比出了问题」。
        (out / f"ALERT_control_not_exercised_{stamp}.json").write_text(
            json.dumps({"alert": "CONTROL_NOT_EXERCISED", "round": stamp,
                        "book_status": status,
                        "action_required": ("第 ② 段未被实际检验（两侧均无持仓）⇒ 不得切换；"
                                            "等一个真正产生 filled book 的轮次再跑对照"),
                        "report": report}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
    elif not report["may_take_over"]:
        (out / f"ALERT_control_mismatch_{stamp}.json").write_text(
            json.dumps({"alert": "CONTROL_MISMATCH", "round": stamp,
                        "action_required": "停下回报工部尚书；不得切换承载路径；本轮 (a) 记录有效",
                        "report": report}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
    report["bearing_payload"] = a_payload
    report["preflight"] = pre
    return report

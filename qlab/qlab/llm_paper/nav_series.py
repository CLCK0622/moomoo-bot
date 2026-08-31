"""EVO-8 LLM 轨 — **每格净值序列**（派生层唯一权威）。

冻结 §4 要的是 `seed_distribution` 的下四分位，前提是**每格各有一条自己的净值序列**。
权威序列只从派生结算层读取：它由不可改决策与归档 bars 重算，且带正向的
``reading_kind=lower_bound``。轮内 ``nav_point`` 是当时轮次记录的快照工件，
不是结算读数；保留在 ``round_record_nav_series()`` 供审计，绝不进入本模块的
``cell_nav_series()`` 或累计收益路径。

两种落盘格式仍由 ``round_record_nav_series()`` 认出，供核对执行器切换：
* (a) 单 book（第 1 轮起）：整轮一个 `nav_point`，归属该轮 `decisions[]` 里那一格；
* (b) 多 book：`cells{}` 每格各有 `nav_point`。

**不出 verdict。** `cumulative_returns()` 是监控读数（预注册 §4：中途读数仅监控），
判定一律走 `certify()` + `llm_paradigm`；本模块也**不**代为调用 `seed_distribution`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from qlab.llm_paper.multi_book import cell_id


def load_rounds(out_dir: str) -> List[Dict[str, Any]]:
    """按文件名（= 决策日 stamp）升序读出全部 round JSON。坏文件不静默跳过——抛出。"""
    p = Path(out_dir)
    rounds = []
    for f in sorted(p.glob("round_*.json")) if p.exists() else []:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{f.name} 无法解析 → 拒绝拼一条缺轮的净值序列：{e}") from e
        payload.setdefault("_file", f.name)
        rounds.append(payload)
    return rounds


def _cells_of_round(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """把一轮归一化成 {cell_id: {nav_point, book_status, seed, prompt_variant}}。"""
    if payload.get("cells"):                                  # (b) 多 book
        return {cid: {"nav_point": blk.get("nav_point"),
                      "book_status": (blk.get("book") or {}).get("status"),
                      "seed": blk.get("seed"), "prompt_variant": blk.get("prompt_variant")}
                for cid, blk in payload["cells"].items()}
    decisions = payload.get("decisions") or []                # (a) 单 book
    keys = {(int(d["seed"]), str(d["prompt_variant"])) for d in decisions
            if "seed" in d and "prompt_variant" in d}
    if len(keys) != 1:
        # 单 book 轮里出现多格 ⇒ 那一个 nav_point 归属不明，猜就是造数。
        raise ValueError(
            f"{payload.get('_file')} 是单 book 轮却含 {len(keys)} 个格子 {sorted(keys)} —— "
            "整轮只有一个 nav_point，归属不明，拒绝分配。")
    seed, variant = next(iter(keys))
    return {cell_id(seed, variant): {"nav_point": payload.get("nav_point"),
                                     "book_status": (payload.get("book") or {}).get("status"),
                                     "seed": seed, "prompt_variant": variant}}


def round_record_nav_series(out_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """轮内 ``nav_point`` 的审计快照，**不是**权威结算序列。

    这个函数刻意改名而非删除，既保留不可改 round JSON 的取证能力，又避免后人把
    轮内快照与派生结算读数混为同一条净值序列。不得把本函数接到 reporting /
    certification / ``cumulative_returns``。
    """
    series: Dict[str, List[Dict[str, Any]]] = {}
    for payload in load_rounds(out_dir):
        stamp = str(payload.get("_file", "")).replace("round_", "").replace(".json", "")
        executor = payload.get("executor", "single_book")
        for cid, blk in _cells_of_round(payload).items():
            np_ = blk["nav_point"]
            if not np_ or np_.get("nav") is None:
                continue
            series.setdefault(cid, []).append({
                "round": stamp, "as_of": np_.get("as_of"), "nav": float(np_["nav"]),
                "nav_x2_cost": np_.get("nav_x2_cost"), "nav_start": np_.get("nav_start"),
                "executor": executor, "book_status": blk["book_status"]})
    for pts in series.values():
        pts.sort(key=lambda x: (x["as_of"] or "", x["round"]))
    return series


def cell_nav_series(out_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """唯一权威的每格净值序列：派生 ``lower_bound`` 结算输出。

    ``equivalence_artifact`` 仅用于执行器逐位比对，不是业绩读数；它与轮内
    ``nav_point`` 一样永远不得经过这个消费点。这一条让同一时刻只有一条可被
    报告或累计收益消费的净值序列。
    """
    # Local import prevents a module-import cycle: derived settlement uses
    # ``load_rounds`` above, while this consumer owns the authority boundary.
    from qlab.llm_paper.derived_settlement import rebuild_lower_bound_settlement

    settlement = rebuild_lower_bound_settlement(out_dir)
    if settlement.get("reading_kind") != "lower_bound":
        raise ValueError("权威净值序列只接受 reading_kind=lower_bound 的派生结算")
    series: Dict[str, List[Dict[str, Any]]] = {}
    for round_ in settlement.get("rounds", []):
        for cid, cell in (round_.get("cells") or {}).items():
            if cell.get("status") != "filled":
                continue
            for point in cell.get("nav_series") or []:
                if point.get("nav") is None:
                    continue
                series.setdefault(cid, []).append({
                    "round": round_.get("round"), "as_of": point.get("as_of"),
                    "nav": float(point["nav"]), "nav_start": cell.get("nav_start"),
                    "executor": round_.get("executor"), "book_status": cell.get("status"),
                    "reading_kind": "lower_bound",
                    # This is intentionally copied onto every point as well as
                    # the settlement cell: no aggregation consumer may retain a
                    # bare NAV while silently dropping its evidence limitation.
                    "bar_provenance": point.get("bar_provenance") or cell.get("bar_provenance"),
                })
    for pts in series.values():
        pts.sort(key=lambda x: (x["as_of"] or "", x["round"] or ""))
    return series


def coverage(out_dir: str) -> Dict[str, Any]:
    """每格的覆盖情况 —— **哪一轮起换的执行器**在这里一眼可见（审计轨要的就是这个）。"""
    rounds = load_rounds(out_dir)
    per_round = []
    for payload in rounds:
        stamp = str(payload.get("_file", "")).replace("round_", "").replace(".json", "")
        cells = _cells_of_round(payload)
        per_round.append({
            "round": stamp,
            "executor": payload.get("executor", "single_book"),
            "n_cells": len(cells),
            "cells": sorted(cells),
            "n_round_record_nav_points": sum(1 for b in cells.values()
                                               if b["nav_point"] and b["nav_point"].get("nav") is not None),
        })
    switches = [per_round[i] for i in range(1, len(per_round))
                if per_round[i]["executor"] != per_round[i - 1]["executor"]]
    return {"n_rounds": len(rounds), "per_round": per_round,
            "executor_switch_rounds": [{"round": s["round"], "to": s["executor"]} for s in switches],
            "cells_seen": sorted({c for r in per_round for c in r["cells"]})}


def cumulative_returns(out_dir: str, *, cost_track: str = "x1") -> Dict[str, Optional[Dict[str, Any]]]:
    """每格的累计收益（**监控读数，不是 verdict**）及其完整读数标签。

    返回值不再是裸 float：``reading_kind`` 与覆盖整段 NAV 的 ``bar_provenance``
    必须随汇总传播，避免事后回补限制在汇总层被平均掉。没有净值点仍返回 ``None``。
    """
    if cost_track != "x1":
        raise ValueError("派生 lower_bound 尚无 x2 shadow 成本轨；不得拿轮内 nav_point 顶替")
    key = "nav"
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for cid, pts in cell_nav_series(out_dir).items():
        last = next((p for p in reversed(pts) if p.get(key) is not None), None)
        base = last.get("nav_start") if last else None
        out[cid] = ({"cumulative_return": float(last[key]) / float(base) - 1.0,
                     "reading_kind": last["reading_kind"],
                     "bar_provenance": last.get("bar_provenance")}
                    if last and base else None)
    return out

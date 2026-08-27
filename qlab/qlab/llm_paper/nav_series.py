"""EVO-8 LLM 轨 — **每格净值序列**（跨轮拼装）。

冻结 §4 要的是 `seed_distribution` 的下四分位，前提是**每格各有一条自己的净值序列**。
本模块把这条序列从各轮**不可改的 round JSON** 机械拼出来，不维护任何可变的累计文件：
决策与净值点一经落盘不可改，序列就该是它们的确定性函数，而不是第二份需要对账的真值。

两种落盘格式都认，这正是执行器切换那一轮必须能读通的地方：
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


def cell_nav_series(out_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """每格一条净值序列：{cell_id: [{round, as_of, nav, nav_x2_cost, nav_start, executor}, ...]}。

    **只收真净值点**：`book` 尚未建仓（`pending_entry_bar`）或缺开盘价的轮次没有 `nav_point`，
    序列里就不该有那一天 —— 补一个「持平」点等于编数。
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
            "n_nav_points": sum(1 for b in cells.values()
                                if b["nav_point"] and b["nav_point"].get("nav") is not None),
        })
    switches = [per_round[i] for i in range(1, len(per_round))
                if per_round[i]["executor"] != per_round[i - 1]["executor"]]
    return {"n_rounds": len(rounds), "per_round": per_round,
            "executor_switch_rounds": [{"round": s["round"], "to": s["executor"]} for s in switches],
            "cells_seen": sorted({c for r in per_round for c in r["cells"]})}


def cumulative_returns(out_dir: str, *, cost_track: str = "x1") -> Dict[str, Optional[float]]:
    """每格的累计收益（**监控读数，不是 verdict**）：末净值 / `nav_start` − 1。

    `cost_track`: `x1` 为入账口径，`x2` 为影子口径（决策成本双轨）。
    不足 1 个净值点的格子返回 `None` —— 没有读数就是没有，不补零。
    """
    key = "nav" if cost_track == "x1" else "nav_x2_cost"
    out: Dict[str, Optional[float]] = {}
    for cid, pts in cell_nav_series(out_dir).items():
        last = next((p for p in reversed(pts) if p.get(key) is not None), None)
        base = last.get("nav_start") if last else None
        out[cid] = (float(last[key]) / float(base) - 1.0) if last and base else None
    return out

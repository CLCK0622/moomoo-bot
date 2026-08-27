"""EVO-8 LLM 轨 — 台账登记桥接（**(a)/(b) 两条执行路径共用同一份**）。

抽出来是因为原先内联在 `run_round()` 里的那段登记**第 2 轮起必然崩**，且崩的位置最坏：
配额已花、决策已产生、round JSON 尚未落盘 —— 抛错即该轮证据凭空消失，与「空一轮永久少一轮」
同等后果。实测（2026-08-27，用真台账副本模拟第 2 轮）：

    RefreezeError: 候选 candidate_id='llm_paper' 已以 run_id=['llm_paper-2026-08-10'] 登记，
    现又以新 run_id=llm_paper-2026-08-31 重登…须显式 supersedes=<旧 run_id> 覆盖计一次

`TrialLedger` 的重冻护栏（工部 2026-07-30）本身是对的：同 `candidate_id` 换 `run_id` 静默追加
会把同一批试验计两遍、N 虚高 ⇒ DSR haircut 变松。但本轨是**一个候选、一张冻结的 10 格网格、
按周前向推进**——每周不是新增 10 个试验，是同样那 10 格多走了一周。故正确形态是

    **一个候选恒定一条台账记录**：`n_trials_total` 恒为冻结的 10（DSR 的 V 不变、不放松），
    `run_id` 随最新一轮更新，靠 `supersedes` 覆盖计一次。

`n_evaluated` 取**跨轮已评估格子的并集**，从各轮已落盘的 round JSON 机械读出（不可改的记录
是唯一真值来源），不手工维护计数器：(a) 单 book 轨长期是 1 格，(b) 接管后是 10 格，
「哪一轮起变成 10」在台账与 round JSON 两侧都能对上。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

CANDIDATE_ID = "llm_paper"

Cell = Tuple[int, str]


class LedgerBridgeError(RuntimeError):
    """台账状态不是本桥接能安全处理的形态 → 不猜、不覆盖，抛给人看。"""


def round_id(decision_ts) -> str:
    """本轮 run_id —— 与第 1 轮 `llm_paper-2026-08-10` 同构，不改命名。"""
    return f"{CANDIDATE_ID}-{pd.Timestamp(decision_ts).date()}"


def cells_in_payload(payload: Dict[str, Any]) -> Set[Cell]:
    """从一份 round JSON 里读出该轮评估了哪些格子。**两种落盘格式都认**。

    (a) 单 book：`decisions[]` 每条自带 seed/prompt_variant（第 1 轮即此形态）；
    (b) 多 book：`cells{}` 的键值块自带 seed/prompt_variant。
    """
    cells: Set[Cell] = set()
    for blk in (payload.get("cells") or {}).values():
        if "seed" in blk and "prompt_variant" in blk:
            cells.add((int(blk["seed"]), str(blk["prompt_variant"])))
    for d in payload.get("decisions") or []:
        if "seed" in d and "prompt_variant" in d:
            cells.add((int(d["seed"]), str(d["prompt_variant"])))
    return cells


def evaluated_cells_union(out_dir: str, current: Optional[Iterable[Cell]] = None) -> Set[Cell]:
    """跨轮已评估格子的并集 = 历史 round JSON ∪ 本轮。**不含**未落盘的推测。"""
    union: Set[Cell] = set(current or ())
    p = Path(out_dir)
    if not p.exists():
        return union
    for f in sorted(p.glob("round_*.json")):
        try:
            union |= cells_in_payload(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            # 坏文件不静默吞掉整份并集，但也不该让一份坏历史记录拖垮当轮登记：
            # 如实跳过并在下面 register_round 的返回里报出去。
            continue
    return union


def unreadable_rounds(out_dir: str) -> list:
    """列出解析失败的历史 round JSON（并集因此可能偏小 ⇒ n_evaluated 偏小 ⇒ 朝严一侧）。"""
    bad = []
    p = Path(out_dir)
    if not p.exists():
        return bad
    for f in sorted(p.glob("round_*.json")):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            bad.append(f.name)
    return bad


def register_round(*, decision_ts, cfg: Dict[str, Any], cells_this_round: Iterable[Cell],
                   out_dir: str, executor: str,
                   ledger_path: Optional[str] = None) -> Dict[str, Any]:
    """登记本轮试验。**`n_trials_total` 恒为冻结网格值，一格都不少登。**

    返回一个可直接进 round JSON 的字典；任何「登记没按预期生效」的情形都以字段形式如实带出，
    **不静默**（本线一路在堵的 fail-open 形态）。
    """
    from research.gate import project_ledger, DEFAULT_LEDGER_PATH
    from research.gate.trial_ledger import RefreezeError

    path = ledger_path or str(_REPO_ROOT / DEFAULT_LEDGER_PATH)
    led = project_ledger(path)
    fam = cfg["family"]
    rid = round_id(decision_ts)
    cells = set(cells_this_round)
    union = evaluated_cells_union(out_dir, cells)
    n_eval = len(union)
    n_total = int(fam["n_trials_total"])
    if n_eval > n_total:
        raise LedgerBridgeError(
            f"已评估格子 {n_eval} 超过冻结网格 {n_total} —— 跑中被加了格子（family 跑后不得增删）。")

    prior = [r for r in led.runs if r.candidate_id == CANDIDATE_ID and r.run_id != rid]
    if len(prior) > 1:
        raise LedgerBridgeError(
            f"候选 {CANDIDATE_ID} 已有多条台账记录 {[r.run_id for r in prior]} —— "
            "本桥接只处理「恒定一条」的形态，多条意味着此前已重复计数，须人工核对后再跑。")
    supersedes = prior[0].run_id if prior else None

    reused = next((r for r in led.runs if r.run_id == rid), None)
    try:
        rec = led.register_run(
            run_id=rid, source="llm_agent", n_trials_total=n_total, n_evaluated=n_eval,
            candidate_id=CANDIDATE_ID, supersedes=supersedes,
            note=(f"EVO-8 前向纸面轨 {rid}：冻结网格 {n_total} 格足额登记（DSR 的 V 不放松）；"
                  f"n_evaluated={n_eval} 为跨轮已评估格子并集；执行器={executor}"))
    except RefreezeError as e:            # 护栏是对的，形态不在预期内 → 不绕过
        raise LedgerBridgeError(f"台账重冻护栏拒绝了本轮登记，请人工核对后再跑：{e}") from e

    out = {
        "run_id": rec.run_id,
        "n_trials_total": rec.n_trials_total,
        "n_evaluated": rec.n_evaluated,
        "n_evaluated_source": "跨轮已评估格子并集（从各轮 round JSON 机械读出）",
        "cells_this_round": sorted(f"seed{s}×{v}" for s, v in cells),
        "supersedes": supersedes,
        "executor": executor,
        "ledger_path": path,
    }
    bad = unreadable_rounds(out_dir)
    if bad:
        out["unreadable_round_files"] = bad     # 并集可能偏小 → 朝严一侧，但必须说出来
    if reused is not None and rec.n_evaluated != n_eval:
        # 同 run_id 幂等返回旧记录（同日第二次登记，如 (b) 对照轮误开了 register_trials）：
        # 台账里的 n_evaluated 是旧值，不会被更新 —— 这条差异绝不能只活在内存里。
        out["ledger_reused_existing_record"] = True
        out["n_evaluated_computed_this_round"] = n_eval
        out["warning"] = ("同 run_id 已登记 → 幂等返回旧记录，n_evaluated **未更新**。"
                          "同日并行对照轮请用 register_trials=False（对照不是承载路径，不该二次登记）。")
    return out

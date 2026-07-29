"""
trial_ledger.py —— 诚实试验计数（地基）+ 跨轮累计真实 N

铁律：miner 不吐**全量** N（含被丢弃的因子）即不予评估。
自动挖矿工具默认只给你幸存者；没有真实 N，DSR 的多重检验校正就是假的。

- register_run(): 登记一轮挖矿，必须声明 n_trials_total（含丢弃）与实际评估候选数。
  n_trials_total < n_evaluated 或缺失 → HonestyError，拒绝。
- cumulative_n(): 跨所有已登记轮次的累计试验数，喂给 DSR 的 N。
- 台账持久化为 JSON，跨会话累计（DSR 的 N 用累计数，不是单轮数）。

datetime 仅用于台账可读性；为可测试，允许注入 now_iso。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence


class HonestyError(ValueError):
    """miner 未吐全量 N / 声明的 N 小于实际评估数 → 拒绝评估。"""


@dataclass
class RunRecord:
    run_id: str
    source: str                     # 'qlib' | 'rd-agent' | 'manual' | ...
    n_trials_total: int             # 全量试验数（含被丢弃的）—— 必填
    n_evaluated: int                # 实际送进门禁评估的候选数
    trial_sharpes_var: Optional[float] = None  # 该轮试验 SR 方差（做 DSR 的 V，可选）
    note: str = ""
    ts: str = ""


# 全项目**唯一共享**台账的规范路径。JSONL（每行一轮）便于跨分支合并、追加安全。
# 铁律：所有候选共用这一个文件——**勿按候选分文件**，否则 cumulative_n 永远只等于本轮，
# 跨轮累计真 N 从不发生，DSR haircut 被静默关闭（工部 2026-07-29 实测）。此文件**须入库**，
# 否则换分支/worktree/机器就是空的。
DEFAULT_LEDGER_PATH = "research/gate/state/trial_ledger.jsonl"


class TrialLedger:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.runs: List[RunRecord] = []
        if path and os.path.exists(path):
            self._load()

    def _load(self) -> None:
        # JSONL：逐行读，按 run_id 去重（跨分支合并可能产生重复行，保留首个）。
        seen, runs = set(), []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = RunRecord(**json.loads(line))
                if rec.run_id in seen:
                    continue
                seen.add(rec.run_id)
                runs.append(rec)
        self.runs = runs

    def _save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            for r in self.runs:
                f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    def register_run(self, run_id: str, source: str, n_trials_total: Optional[int],
                     n_evaluated: int, trial_sharpes: Optional[Sequence[float]] = None,
                     trial_sharpes_var: Optional[float] = None, note: str = "",
                     now_iso: Optional[str] = None) -> RunRecord:
        # 幂等：同 run_id 已登记 → 返回既有，不重复计数（重跑/跨轮安全）。
        for r in self.runs:
            if r.run_id == run_id:
                return r
        # —— 诚实计数门 ——
        if n_trials_total is None:
            raise HonestyError(
                f"run={run_id} 未声明全量试验数 n_trials_total（含丢弃）→ 不予评估。"
            )
        if n_trials_total < 1 or n_trials_total < n_evaluated:
            raise HonestyError(
                f"run={run_id} 声明 N={n_trials_total} 小于实际评估数 {n_evaluated} 或 <1 → 不予评估。"
            )
        var = trial_sharpes_var
        if var is None and trial_sharpes is not None and len(trial_sharpes) >= 2:
            import numpy as np
            var = float(np.var(np.asarray(trial_sharpes, dtype=float), ddof=1))
        ts = now_iso or datetime.now(timezone.utc).isoformat()
        rec = RunRecord(run_id=run_id, source=source, n_trials_total=int(n_trials_total),
                        n_evaluated=int(n_evaluated), trial_sharpes_var=var,
                        note=note, ts=ts)
        self.runs.append(rec)
        self._save()
        return rec

    def cumulative_n(self) -> int:
        """跨轮累计真实试验数 —— DSR 的 N。含所有历史轮次。"""
        return sum(r.n_trials_total for r in self.runs)

    def pooled_trials_variance(self) -> Optional[float]:
        """按评估量加权的试验 SR 方差（做 DSR 的 V 的近似）。无则 None。"""
        weighted, wsum = 0.0, 0
        for r in self.runs:
            if r.trial_sharpes_var is not None:
                weighted += r.trial_sharpes_var * r.n_trials_total
                wsum += r.n_trials_total
        return (weighted / wsum) if wsum > 0 else None


def project_ledger(path: str = DEFAULT_LEDGER_PATH) -> "TrialLedger":
    """
    打开**全项目唯一共享**台账（默认 DEFAULT_LEDGER_PATH）。所有候选都用它、勿分文件；
    每轮 register_run 后须把该文件提交入库，跨轮累计真 N 才在实际运行里成立。
    """
    return TrialLedger(path)

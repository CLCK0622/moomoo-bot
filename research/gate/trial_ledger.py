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


class TrialLedger:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.runs: List[RunRecord] = []
        if path and os.path.exists(path):
            self._load()

    def _load(self) -> None:
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.runs = [RunRecord(**r) for r in data.get("runs", [])]

    def _save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"runs": [asdict(r) for r in self.runs]}, f,
                      ensure_ascii=False, indent=2)

    def register_run(self, run_id: str, source: str, n_trials_total: Optional[int],
                     n_evaluated: int, trial_sharpes: Optional[Sequence[float]] = None,
                     trial_sharpes_var: Optional[float] = None, note: str = "",
                     now_iso: Optional[str] = None) -> RunRecord:
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

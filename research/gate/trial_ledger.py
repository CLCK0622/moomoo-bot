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

from .filelock import atomic_write_text, state_lock


class HonestyError(ValueError):
    """miner 未吐全量 N / 声明的 N 小于实际评估数 → 拒绝评估。"""


class RefreezeError(ValueError):
    """同一候选换 prereg commit 重登（run_id 变）而未显式声明 supersedes → 拒绝，防重复计数。"""


@dataclass
class RunRecord:
    run_id: str
    source: str                     # 'qlib' | 'rd-agent' | 'manual' | ...
    n_trials_total: int             # 全量试验数（含被丢弃的）—— 必填
    n_evaluated: int                # 实际送进门禁评估的候选数
    trial_sharpes_var: Optional[float] = None  # 该轮试验 SR 方差（做 DSR 的 V，可选）
    # 该轮**全量每期试验 Sharpe**。工部 2026-07-30(EVO-8 A) 实测：只存标量 var 时，pooled V
    # 退化成候选自己那一组（max(自报,台账)=max(x,x)），不构成独立地板。要让 pooled V 成为**跨轮
    # 独立**兜底，每条登记须带上 trial_sharpes；pooled 从各轮 Sharpe 的并集算，且可排除候选自己那轮。
    trial_sharpes: Optional[List[float]] = None
    # 候选的**稳定身份**（如 'carry_rates_A'），与 run_id（内嵌 prereg commit，重冻会变）区分开。
    # 工部 2026-07-30(EVO-8 A)：run_id 内嵌 commit → 重冻换 key → 按 run_id 的幂等被绕过 → 同一候选
    # 计两遍（N 虚高、反噬为假阴性）。带 candidate_id 后可识别"同候选重冻"并去重/拦截。
    candidate_id: Optional[str] = None
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
        # 原子写：临时文件 + os.replace。原来的逐行 write 在并发下会把文件写成半截/交错，
        # 台账一旦损坏后续所有 run 读它都会崩（实测 10 并发 → 仅 3 行、1 行可解析）。
        atomic_write_text(
            self.path,
            "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in self.runs))

    def register_run(self, run_id: str, source: str, n_trials_total: Optional[int],
                     n_evaluated: int, trial_sharpes: Optional[Sequence[float]] = None,
                     trial_sharpes_var: Optional[float] = None, note: str = "",
                     now_iso: Optional[str] = None, candidate_id: Optional[str] = None,
                     supersedes: Optional[str] = None) -> RunRecord:
        """登记一轮试验。**跨进程原子**（工部 2026-07-30，都察院终审必修 2）。

        原实现无锁 read-modify-write：幂等/重冻校验基于进程内陈旧快照，且 `_save()` 全量重写
        整个文件。10 个并发 register_run 实测：仅 3 行落盘、1 行可解析，**9 条试验凭空消失**且
        文件被交错写坏（后续读直接 JSONDecodeError）。漏记 N/V ⇒ DSR 的 haircut 变松，与本线
        一路堵的 fail-open 同向。现改为锁内「重读磁盘 → 校验 → 原子写」。
        """
        with state_lock(self.path):
            if self.path and os.path.exists(self.path):
                self._load()          # 关键：锁内重读，纳入其它进程刚写入的条目
            return self._register_locked(
                run_id, source, n_trials_total, n_evaluated, trial_sharpes,
                trial_sharpes_var, note, now_iso, candidate_id, supersedes)

    def _register_locked(self, run_id: str, source: str, n_trials_total: Optional[int],
                         n_evaluated: int, trial_sharpes: Optional[Sequence[float]],
                         trial_sharpes_var: Optional[float], note: str,
                         now_iso: Optional[str], candidate_id: Optional[str],
                         supersedes: Optional[str]) -> RunRecord:
        # 幂等：同 run_id 已登记 → 返回既有，不重复计数（重跑/跨轮安全）。
        for r in self.runs:
            if r.run_id == run_id:
                return r
        # 重冻护栏（工部 2026-07-30）：同一 candidate_id 已有别的 run_id（＝重冻换了 prereg commit）→
        # 不得静默追加（会把同一候选计两遍、N 虚高）。须显式声明 supersedes=<旧 run_id> 覆盖（计一次），
        # 否则拒绝——逼调用方表态是"同候选重冻覆盖"还是"真的新试验"（新试验请用不同 candidate_id）。
        # supersedes 不得静默失效（工部 2026-08-06 实测）：旧条目若**没带 candidate_id**（早期登记
        # 常见），上面按 candidate_id 匹配的 prior 会是空集 → supersedes 被**悄悄忽略**、直接追加，
        # 同一批试验计两遍（实测 12→24；生产上是 47→59），N 虚高反噬为假阴性。而调用方以为自己
        # 已经覆盖了。故：声明了 supersedes 就必须真的命中一条既有 run_id，否则报错逼其修正。
        if supersedes is not None:
            target = [r for r in self.runs if r.run_id == supersedes]
            if not target:
                raise RefreezeError(
                    f"supersedes='{supersedes}' 未命中任何已登记 run_id → 拒绝。"
                    "（若静默忽略，本轮会被当成全新试验追加、同一批试验计两遍、N 虚高。）"
                    f"现有 run_id: {[r.run_id for r in self.runs]}")
            # 命中即覆盖计一次——不依赖 candidate_id 是否齐备（兼容早期未带 candidate_id 的条目）。
            self.runs = [r for r in self.runs if r.run_id != supersedes]

        if candidate_id is not None:
            prior = [r for r in self.runs
                     if r.candidate_id == candidate_id and r.run_id != run_id]
            if prior:
                if supersedes is not None and any(r.run_id == supersedes for r in prior):
                    self.runs = [r for r in self.runs if r.run_id != supersedes]  # 覆盖，计一次
                else:
                    raise RefreezeError(
                        f"候选 candidate_id='{candidate_id}' 已以 run_id={[r.run_id for r in prior]} 登记，"
                        f"现又以新 run_id={run_id} 重登（多为重冻换 prereg commit）。须显式 "
                        f"supersedes=<旧 run_id> 覆盖计一次，或换 candidate_id 认作真新试验——不静默追加防重复计数。"
                    )
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
        ts_list = [float(s) for s in trial_sharpes] if trial_sharpes is not None else None
        if var is None and ts_list is not None and len(ts_list) >= 2:
            import numpy as np
            var = float(np.var(np.asarray(ts_list, dtype=float), ddof=1))
        ts = now_iso or datetime.now(timezone.utc).isoformat()
        rec = RunRecord(run_id=run_id, source=source, n_trials_total=int(n_trials_total),
                        n_evaluated=int(n_evaluated), trial_sharpes_var=var,
                        trial_sharpes=ts_list, candidate_id=candidate_id, note=note, ts=ts)
        self.runs.append(rec)
        self._save()
        return rec

    def cumulative_n(self) -> int:
        """跨轮累计真实试验数 —— DSR 的 N。含所有历史轮次。"""
        return sum(r.n_trials_total for r in self.runs)

    def pooled_trials_variance(self, exclude_run_id: Optional[str] = None) -> Optional[float]:
        """
        跨轮试验 Sharpe 方差（做 DSR 的 V 的地板）。优先从各轮 **trial_sharpes 的并集**算真方差；
        缺 trial_sharpes 的轮次退化为按 n 加权其 trial_sharpes_var。无则 None。

        `exclude_run_id`：排除某轮（通常是候选自己那轮），使地板**独立于被评估候选**——
        否则 pooled 只由候选自己那组构成、`max(自报,台账)` 退化成 max(x,x)，不是真兜底
        （工部 2026-07-30 实测）。
        """
        pooled_sharpes: List[float] = []
        weighted, wsum = 0.0, 0
        for r in self.runs:
            if exclude_run_id is not None and r.run_id == exclude_run_id:
                continue
            if r.trial_sharpes:
                pooled_sharpes.extend(float(s) for s in r.trial_sharpes)
            elif r.trial_sharpes_var is not None:
                weighted += r.trial_sharpes_var * r.n_trials_total
                wsum += r.n_trials_total
        if len(pooled_sharpes) >= 2:
            import numpy as np
            return float(np.var(np.asarray(pooled_sharpes, dtype=float), ddof=1))
        return (weighted / wsum) if wsum > 0 else None

    def has_independent_v(self, exclude_run_id: str) -> bool:
        """除 exclude_run_id 外是否还有带 V 的轮次——决定 pooled 地板是否**独立**（真兜底）。"""
        for r in self.runs:
            if r.run_id == exclude_run_id:
                continue
            if r.trial_sharpes or (r.trial_sharpes_var is not None):
                return True
        return False


def project_ledger(path: str = DEFAULT_LEDGER_PATH) -> "TrialLedger":
    """
    打开**全项目唯一共享**台账（默认 DEFAULT_LEDGER_PATH）。所有候选都用它、勿分文件；
    每轮 register_run 后须把该文件提交入库，跨轮累计真 N 才在实际运行里成立。
    """
    return TrialLedger(path)

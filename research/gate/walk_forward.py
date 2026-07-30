"""
walk_forward.py —— 严格样本外：purged + embargo 切分 / CPCV / 单发 OOS 预算

- 挖矿只在样本内（train）；OOS 窗留到最后**一次性**验。
- purge：剔除 label 窗与 test 重叠的 train 观测（杀重叠标签泄漏）。
- embargo：test 之后再禁 embargo 期的 train 观测（杀自相关泄漏）。
- CPCV：组合式 purged 交叉验证（López de Prado）。
- OOSBudget：每个预注册/候选只给**一发** OOS；第二次偷看 → 标记/拒绝
  （防止反复在 OOS 上调参，把 OOS 可信度烧光）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import numpy as np

# 全项目**唯一共享**单发 OOS 预算的规范路径。与台账同理**须入库**，否则跨 run/机器每次发新票。
DEFAULT_OOS_BUDGET_PATH = "research/gate/state/oos_budget.json"


def _purge_embargo(train: np.ndarray, test: np.ndarray, label_horizon: int,
                   embargo: int, n: int) -> np.ndarray:
    """从 train 里剔除与 test 的 [t, t+label_horizon] 重叠者 + test 后 embargo 期。"""
    if len(test) == 0:
        return train
    t_lo, t_hi = int(test.min()), int(test.max())
    # purge：train 观测 i 的 label 覆盖 [i, i+label_horizon]，与 test 段有交叠即剔除
    lo = t_lo - label_horizon
    hi = t_hi + label_horizon
    # embargo：test 段之后再禁 embargo 期
    emb_hi = min(n - 1, t_hi + embargo)
    keep = [i for i in train if not (lo <= i <= hi) and not (t_hi < i <= emb_hi)]
    return np.asarray(keep, dtype=int)


def walk_forward_splits(n_obs: int, n_splits: int, label_horizon: int = 1,
                        embargo: int = 0, expanding: bool = True
                        ) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    前进式切分：把序列切 n_splits+1 段，逐段把「下一段」当 test，之前当 train。
    expanding=True 用扩张窗（累积历史），False 用滚动窗（只用上一段）。
    """
    if n_splits < 1 or n_obs < n_splits + 1:
        raise ValueError("n_obs 太小或 n_splits 非法")
    bounds = np.linspace(0, n_obs, n_splits + 2, dtype=int)
    splits = []
    for k in range(1, len(bounds) - 1):
        test = np.arange(bounds[k], bounds[k + 1], dtype=int)
        if expanding:
            train = np.arange(0, bounds[k], dtype=int)
        else:
            train = np.arange(bounds[k - 1], bounds[k], dtype=int)
        train = _purge_embargo(train, test, label_horizon, embargo, n_obs)
        splits.append((train, test))
    return splits


def cpcv_splits(n_obs: int, n_groups: int, n_test_groups: int = 2,
                label_horizon: int = 1, embargo: int = 0
                ) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Combinatorial Purged CV：把序列均分 n_groups 组，每次取 n_test_groups 组作 test，
    其余作 train（含 purge+embargo）。共 C(n_groups, n_test_groups) 个 split。
    """
    if n_test_groups >= n_groups or n_groups < 2:
        raise ValueError("n_test_groups 必须 < n_groups 且 n_groups>=2")
    edges = np.linspace(0, n_obs, n_groups + 1, dtype=int)
    groups = [np.arange(edges[i], edges[i + 1], dtype=int) for i in range(n_groups)]
    splits = []
    for combo in combinations(range(n_groups), n_test_groups):
        test = np.concatenate([groups[g] for g in combo])
        train_groups = [g for g in range(n_groups) if g not in combo]
        train = np.concatenate([groups[g] for g in train_groups]) if train_groups \
            else np.asarray([], dtype=int)
        train = _purge_embargo(train, test, label_horizon, embargo, n_obs)
        splits.append((np.sort(train), np.sort(test)))
    return splits


class OOSBudgetExceeded(RuntimeError):
    """同一 OOS 被评估超过预算次数 → 拒绝（防止在 OOS 上反复调参）。"""


@dataclass
class OOSBudget:
    """
    每个 key（预注册/候选）只给 max_evals 次 OOS。默认 1（单发）。

    **持久化（工部 2026-07-30 第八种 fail-open）**：_used 若只活在进程内，「单发」仅在单个 run
    内成立——每次新建 OOSBudget 都发一张新的"单发票"，跨 run 形同虚设，而它防的正是最基本的过拟合
    「跑→看结果→改→再跑」。传 `path` 即按 key **落盘**，跨 run / 跨进程守住单发；重跑须显式换新
    预注册（新 key = 新试验，走台账 N），而不是白拿一张新票。此文件须入库（否则换机器又归零）。
    """
    max_evals: int = 1
    path: Optional[str] = None
    _used: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path and os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self._used = {str(k): int(v) for k, v in json.load(f).items()}

    def _save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._used, f, ensure_ascii=False, indent=2, sort_keys=True)

    def consume(self, key: str) -> None:
        used = self._used.get(key, 0)
        if used >= self.max_evals:
            raise OOSBudgetExceeded(
                f"OOS 预算耗尽：key='{key}' 已评估 {used} 次（上限 {self.max_evals}）。"
                "OOS 是一次性资源，反复偷看即失可信 —— 需新预注册（记新试验），不是重跑白拿新票。"
            )
        self._used[key] = used + 1
        self._save()

    def used(self, key: str) -> int:
        return self._used.get(key, 0)


def project_oos_budget(max_evals: int = 1,
                       path: str = DEFAULT_OOS_BUDGET_PATH) -> "OOSBudget":
    """打开**全项目唯一共享**、落盘持久的单发 OOS 预算（默认 DEFAULT_OOS_BUDGET_PATH）。
    管线一律用它——别用进程内的 OOSBudget()，否则每 run 一张新票、单发形同虚设。消费后须把文件入库。"""
    return OOSBudget(max_evals=max_evals, path=path)

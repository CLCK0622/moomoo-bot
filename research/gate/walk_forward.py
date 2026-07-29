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

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Tuple

import numpy as np


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
    """每个 key（预注册/候选）只给 max_evals 次 OOS。默认 1（单发）。"""
    max_evals: int = 1
    _used: Dict[str, int] = field(default_factory=dict)

    def consume(self, key: str) -> None:
        used = self._used.get(key, 0)
        if used >= self.max_evals:
            raise OOSBudgetExceeded(
                f"OOS 预算耗尽：key='{key}' 已评估 {used} 次（上限 {self.max_evals}）。"
                "OOS 是一次性资源，反复偷看即失可信 —— 需新预注册（记新试验）。"
            )
        self._used[key] = used + 1

    def used(self, key: str) -> int:
        return self._used.get(key, 0)

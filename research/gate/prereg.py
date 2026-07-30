"""
prereg.py —— 预注册冻结 + ex-ante 经济理由门

- freeze_config(): 把 universe/杠杆/参数/成本模型/切分点/门槛 规范化成 canonical JSON 并取
  sha256。跑前冻结、跑后核对。任何事后改动 → 哈希不符 → 记一次**新试验**（DSR 的 N 要 +1）。
- economic_rationale_gate(): 每个幸存因子必须附 ex-ante 经济假设（风险溢价或行为解释）。
  纯数据挖出、无理由的因子 → 隔离（quarantine），额外重罚 / 转人工复核，不直接放行。
  这是把「发现」和「曲线拟合」分开的人在环。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict


def _canonical(config: Dict[str, Any]) -> str:
    """稳定序列化：排序键、无多余空白 —— 保证同配置同哈希。"""
    return json.dumps(config, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def freeze_config(config: Dict[str, Any]) -> str:
    """返回配置的 sha256 冻结指纹。"""
    return hashlib.sha256(_canonical(config).encode("utf-8")).hexdigest()


@dataclass
class PreregCheck:
    unchanged: bool
    frozen_hash: str
    current_hash: str


def verify_unchanged(frozen_hash: str, current_config: Dict[str, Any]) -> PreregCheck:
    """
    核对当前配置是否等于冻结时。unchanged=False 表示预注册被破坏：
    这不是"重跑一次"，而是一次**新试验**，必须回 trial_ledger 记 N，重新走全套门。
    """
    cur = freeze_config(current_config)
    return PreregCheck(unchanged=(cur == frozen_hash),
                       frozen_hash=frozen_hash, current_hash=cur)


# 冻结时必须齐备的键 —— 少任何一项即预注册不完整
REQUIRED_PREREG_KEYS = (
    "universe",          # 冻结 ticker 清单，跑中不换
    "leverage_cap",      # 预注册杠杆上限（≤2x，不可事后加）
    "signal_params",     # 信号参数（不可事后 grid 重调）
    "rebalance",         # 再平衡节奏
    "cost_model",        # 成本模型
    "train_test_split",  # 训练-测试切分点
    "gate_thresholds",   # 门槛本身
    "family",            # 定义 DSR 的 V 的那组试验（grid/factor set）——须冻结，跑后不得增删。
                         # 工部 2026-07-30(EVO-8 A)：family 选得越紧 V 越小、多重检验罚越轻，
                         # 「事后挑 family」= 第七种 fail-open。冻进 prereg 后由冻结哈希守住。
)


def validate_prereg_completeness(config: Dict[str, Any]) -> list:
    """返回缺失的必备预注册键（空列表 = 完整）。"""
    return [k for k in REQUIRED_PREREG_KEYS if k not in config]


@dataclass
class RationaleResult:
    accepted: bool
    quarantined: bool
    reason: str


def economic_rationale_gate(rationale: str, min_chars: int = 40) -> RationaleResult:
    """
    要求非空、有实质的 ex-ante 经济假设。缺失/过短 → quarantine（不直接毙，转人工/重罚）。
    机器批量产因子时这道门尤其关键：无经济理由的纯数据因子额外重罚。
    """
    text = (rationale or "").strip()
    if len(text) < min_chars:
        return RationaleResult(
            accepted=False, quarantined=True,
            reason=f"经济理由缺失或过短（<{min_chars} 字）→ 隔离，转人工复核 / 额外重罚。",
        )
    return RationaleResult(accepted=True, quarantined=False, reason="ex-ante 经济理由充分。")

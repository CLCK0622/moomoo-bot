"""EVO-8 LLM 轨 — 共用异常。

单独一个模块只为断开循环导入：`quote_bridge` 要抛 `PreflightFailed`，而 `run_round` 要用
`quote_bridge`。`PreflightFailed` 仍从 `run_round` 原样导出，既有 `from ...run_round import
PreflightFailed` 的调用点一律不受影响。
"""
from __future__ import annotations


class PreflightFailed(RuntimeError):
    """起跑前置不满足 → 不产生任何决策（fail-closed）。"""

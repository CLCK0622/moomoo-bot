"""EVO-8 LLM 轨 — 决策链路 ↔ 价格腿的桥接（**不重实现价格腿**）。

价格腿的权威实现是都水的 `qlab.events.datafetch.quotes_api`（`2521837`）：
key 只从 env 读、`Note`/`Information` → `RateLimited`（不当"价格没变"）、缺价/过期 → `StalePriceError`、
每根 bar 留数据源自身交易日、`trading_days()` 由观测 bar 给出。
我原先自写的 `price_leg.py` 与之重复，**已删除**——本轨不再有第二份价格腿实现。

本模块只做一件事：把 `trading_days()`（观测到的真实交易日）接到
`decision_chain.resolve_actual_start`，让**收益起算 = 首根真实 bar**。
日历依赖到此为止：不需要假日表、不刷 SPY、不会撞覆盖边界。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from qlab.events.datafetch.quotes_api import trading_days
from qlab.llm_paper.decision_chain import resolve_actual_start


def settle_actual_start(decisions: Sequence[Any], bars_by_symbol: Dict[str, List[Any]]) -> Dict[str, Any]:
    """用观测到的交易日回填每条决策的 `actual_start`（未到则留 pending，绝不猜）。

    返回 {settled, pending, days_source}；就地更新每条 `Decision` 的
    `actual_start` / `actual_start_rolled_days` / `actual_start_reason`。
    """
    days = trading_days(bars_by_symbol)          # 权威交易日历＝真实 bar 的日期
    settled, pending = 0, 0
    for d in decisions:
        r = resolve_actual_start(d.intended_start, days)
        d.actual_start = r["actual_start"]
        d.actual_start_rolled_days = r["rolled_days"]
        d.actual_start_reason = r["reason"]
        if r["actual_start"]:
            settled += 1
        else:
            pending += 1
    return {"settled": settled, "pending": pending, "n_trading_days_observed": len(days),
            "days_source": "quotes_api.trading_days（观测 bar，非预测日历）",
            "note": "pending 表示价格腿尚无 >= intended 的 bar —— 留待行情到位后回填，不估算"}

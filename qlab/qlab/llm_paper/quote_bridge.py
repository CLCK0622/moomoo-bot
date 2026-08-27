"""EVO-8 LLM 轨 — 取行情 + QUOTA_DIVERGENCE 留痕（**(a)/(b)/并行对照三处共用**）。

抽出来的理由和 `ledger_bridge` 一样：这段是 fail-closed 护栏，多一份拷贝就多一处会静默分叉的
地方。并行对照轮引入第三个调用点时，与其抄第三遍，不如让三处共用同一份。

护栏本身一字未改，逐条留在这里以免将来有人以为它只是「取个数」：

* `require_full_batch=True` —— 缺一只即**整批不出**，绝不半截入账；
* `RateLimited(divergence=True)` 是这把 key 被别人花掉 25/天的**唯一可观测签名**。它不能只以
  traceback 形态存在：本轮会中止、没有 round JSON，告警就跟着没了。故落一份**独立** ALERT
  （不写任何决策/净值），消息已在源头 `_redact` 过；
* `failed` 非空 ⇒ `PreflightFailed`，不用陈旧价、不出假净值。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from qlab.events.datafetch.api_quota import MARKING
from qlab.events.datafetch.quotes_api import RateLimited, get_daily_closes
from qlab.llm_paper.errors import PreflightFailed


def fetch_round_quotes(symbols: Sequence[str], *, stamp: str, out_dir: str, executor: str,
                       guard: Optional[Any] = None) -> Dict[str, Any]:
    """取本轮行情（走盯市预留额度）。缺一只 / 配额分歧 ⇒ 不产生决策，但**留痕**。"""
    out = Path(out_dir)
    try:
        bars, failed = get_daily_closes(symbols, guard=guard, purpose=MARKING,
                                        require_full_batch=True)
    except RateLimited as e:
        if getattr(e, "divergence", False):
            out.mkdir(parents=True, exist_ok=True)
            (out / f"ALERT_quota_divergence_{stamp}.json").write_text(
                json.dumps({"alert": "QUOTA_DIVERGENCE", "round": stamp,
                            "kind": getattr(e, "kind", None),
                            "ledger_remaining": e.ledger_remaining,
                            "vendor_throttled": e.vendor_throttled,
                            "utc_day": e.utc_day, "message": str(e),
                            "executor": executor,
                            "action_required": ("按都水预案：停用这把 key + 切换退路供应商；"
                                                "先比 hash 验可轮换性（AV 教训：重新申请 ≠ 轮换）"),
                            "note": "本轮**未产生任何决策与净值点**（整批不出，绝不半截入账）"},
                           ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    if failed:
        raise PreflightFailed(f"行情缺失 {failed} → 不产生决策（不用陈旧价、不出假净值）")
    return bars


def require_injected_bars(bars: Dict[str, Any], symbols: Sequence[str]) -> Dict[str, Any]:
    """校验注入的行情快照覆盖本轮全部标的（并行对照：一次取数喂两条路径）。

    缺任何一只即 fail-closed —— 部分快照会让 `build_book` 落到 `missing_entry_open`，
    从而把「上游少取了一只」伪装成「这只当天没开盘价」，两者在记录里长得一样。
    """
    missing = sorted(s for s in symbols if not bars.get(s))
    if missing:
        raise PreflightFailed(
            f"注入的行情快照缺 {missing} → 不产生决策。"
            "部分快照会被记成 missing_entry_open，与「当天真的没开盘价」不可区分，故整批拒。")
    return bars

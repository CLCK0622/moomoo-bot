"""EVO-8 LLM 轨 — 一次决策轮的执行器（前向纸面）。

起跑与每周决策都走这一条命令。做四件事，任一环 fail-closed：

1. **前置自检**：冻结锚点已就绪、`paradigm=llm_agent`、冻结网格 = 10 格、配额够（含盯市预留）；
2. **取行情**（都水 `quotes_api`，`purpose=MARKING` 走预留额度）→ `trading_days()` 得**观测**交易日历；
3. **决策落盘**：调用方给出每格（seed × prompt 变体）的目标仓位与论点 → `build_decision` 逐条强制
   `evidence_available_utc ≤ decision_ts ≤ intended_start`，再由观测 bar 回填 `actual_start`；
4. **盯市 + 台账 + 落盘**：`mark_to_market` 缺价即拒（绝不出假净值）；`register_run` 足额登记
   10 格试验（`candidate_id="llm_paper"`）；决策与净值点写入 `qlab/reports/llm_paper/`。

**不出 verdict**：本执行器只诚实记录。中途读数仅监控，判定一律留给 `certify()`（预注册 §4）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qlab.events.datafetch.api_quota import (MARKING, QuotaExceeded,  # noqa: E402
                                             guard_from_env)
from qlab.events.datafetch.quotes_api import (get_daily_closes, mark_to_market,  # noqa: E402
                                              trading_days)
from qlab.llm_paper.decision_chain import (build_decision, check_portfolio,  # noqa: E402
                                            frozen_grid, load_anchor, load_prereg)
from qlab.llm_paper.price_bridge import settle_actual_start

OUT_DIR = "qlab/reports/llm_paper"
CANDIDATE_ID = "llm_paper"


class PreflightFailed(RuntimeError):
    """起跑前置不满足 → 不产生任何决策（fail-closed）。"""


def preflight(*, n_symbols_needed: int, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """决策前自检。**任何一项不过就不跑**——宁可不起跑，也不产出半截证据。"""
    cfg = cfg or load_prereg()
    anchor = load_anchor()                       # status != anchored 会抛
    grid = frozen_grid(cfg)                      # 网格与冻结 n_trials_total 不符会抛
    guard = guard_from_env()
    snap = guard.status()
    checks = {
        "anchor_ok": anchor["status"] == "anchored",
        "prereg_frozen_at": anchor["push_event"]["created_at"],
        "paradigm": cfg["paradigm"],
        "grid_cells": len(grid),
        "quota": snap,
        # ⚠️ 台账与供应商侧可能不一致：**guard 之外发出的调用不计数**（如早期验证/压测）。
        # 故 preflight 通过 ≠ 供应商一定服务。真正的兜底在使用点：get_daily_closes 遇 RateLimited
        # 会抛错、require_full_batch 整批不出，**不会产出假净值**。此处如实记录两侧数字供对账。
        "quota_caveat": "guard 台账仅计经 guard 的调用；vendor 侧可能已被 guard 外调用消耗",
    }
    # 配额：盯市按 MARKING 预检（可用全额，含预留）
    try:
        guard.check(n_symbols_needed, purpose=MARKING)
        checks["quota_ok_for_marking"] = True
    except QuotaExceeded as e:
        checks["quota_ok_for_marking"] = False
        raise PreflightFailed(
            f"盯市配额不足（需 {n_symbols_needed} 次）：{e}。"
            "**不起跑**——当天取不到收盘价就会在净值序列留空洞，事后补即造数。等 UTC 日切。") from e
    if cfg["paradigm"] != "llm_agent":
        raise PreflightFailed("paradigm 必须为 llm_agent（否则污染/多seed/归因三关会被跳过）")
    return checks


def run_round(*, proposals: Sequence[Dict[str, Any]], decision_ts,
              benchmark: str = "SPY", out_dir: str = OUT_DIR,
              cfg: Optional[Dict[str, Any]] = None,
              rejected_evidence: Optional[Sequence[Dict[str, Any]]] = None,
              register_trials: bool = True) -> Dict[str, Any]:
    """执行一次决策轮。

    `proposals`：每项 = {symbol, target_weight, confidence, thesis, evidence_records,
    seed, prompt_variant}（由 LLM 决策阶段产出；证据须带信息源自身时间 `source_time_utc`）。
    """
    cfg = cfg or load_prereg()
    symbols = sorted({p["symbol"] for p in proposals} | {benchmark})
    pre = preflight(n_symbols_needed=len(symbols), cfg=cfg)

    # ---- 取行情（走盯市预留额度）；缺一只即整批不花（require_full_batch） ----
    guard = guard_from_env()
    bars, failed = get_daily_closes(symbols, guard=guard, purpose=MARKING,
                                    require_full_batch=True)
    if failed:
        raise PreflightFailed(f"行情缺失 {failed} → 不产生决策（不用陈旧价、不出假净值）")
    days = trading_days(bars)

    # ---- 决策落盘（三条时序在 build_decision 内强制） ----
    decisions = []
    for p in proposals:
        decisions.append(build_decision(
            symbol=p["symbol"], target_weight=p["target_weight"],
            confidence=p["confidence"], thesis=p["thesis"],
            evidence_records=p["evidence_records"], decision_ts=decision_ts,
            seed=p["seed"], prompt_variant=p["prompt_variant"],
            model=p.get("model", ""), cfg=cfg, observed_days=days))
    port = check_portfolio(decisions, cfg)
    if not port["ok"]:
        raise PreflightFailed(f"组合约束不过：{port} → 不落盘（禁做空/单标的10%/总仓100%/≤1x 不松）")

    settle = settle_actual_start(decisions, bars)      # actual_start = 首根真实 bar

    # ---- 盯市（缺价即拒） ----
    holdings = {d.symbol: d.target_weight for d in decisions}
    mtm = mark_to_market(holdings, bars)

    # ---- 台账：足额登记 10 格（少登即 REJECTED_honesty） ----
    ledger_rec = None
    if register_trials:
        from research.gate import project_ledger, DEFAULT_LEDGER_PATH
        led = project_ledger(str(_REPO_ROOT / DEFAULT_LEDGER_PATH))
        fam = cfg["family"]
        ledger_rec = led.register_run(
            run_id=f"{CANDIDATE_ID}-{pd.Timestamp(decision_ts).date()}",
            source="llm_agent", n_trials_total=fam["n_trials_total"],
            n_evaluated=len({(d.seed, d.prompt_variant) for d in decisions}),
            candidate_id=CANDIDATE_ID,
            note=f"LLM 前向纸面第 1 轮：冻结网格 {fam['n_trials_total']} 格足额登记")

    payload = {
        "round_decision_ts": pd.Timestamp(decision_ts).isoformat(),
        "preflight": pre,
        "n_decisions": len(decisions),
        "portfolio_check": port,
        "actual_start_settlement": settle,
        "mark_to_market": mtm,
        "ledger": ({"run_id": ledger_rec.run_id, "n_trials_total": ledger_rec.n_trials_total}
                   if ledger_rec else None),
        "rejected_evidence": list(rejected_evidence or []),
        "decisions": [d.to_log_entry() for d in decisions],
        "verdict": None,
        "note": "中途读数只作监控、**不出 verdict**；判定一律走 certify()+llm_paradigm（预注册 §4）",
    }
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp(decision_ts).strftime("%Y%m%d")
    (out / f"round_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload

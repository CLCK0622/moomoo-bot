"""EVO-8 LLM 轨 — 一次决策轮的执行器（前向纸面）。

起跑与每周决策都走这一条命令。做四件事，任一环 fail-closed：

1. **前置自检**：冻结锚点已就绪、`paradigm=llm_agent`、冻结网格 = 10 格、配额够（含盯市预留）；
2. **取行情**（都水 `quotes_api`，`purpose=MARKING` 走预留额度）→ `trading_days()` 得**观测**交易日历；
3. **决策落盘**：调用方给出每格（seed × prompt 变体）的目标仓位与论点 → `build_decision` 逐条强制
   `evidence_available_utc ≤ decision_ts ≤ intended_start`，再由观测 bar 回填 `actual_start`；
4. **盯市 + 台账 + 落盘**：`mark_to_market` 缺价即拒（绝不出假净值）；`register_run` 足额登记
   10 格试验（`candidate_id="llm_paper"`）；决策与净值点写入 `qlab/reports/llm_paper/`。

外加两块（工部 2026-08-08 第二、三节）：

* **金标准复现**（`determinism.py`）：每轮必带一次固定输入的模型调用，输出与冻结基线**逐字**比对，
  抓「同名模型被换权重」这个比 seed 离散度严重得多的混淆因子。探针缺失/输出为空/探针被改过一律
  **fail-closed**（`PreflightFailed`）；检出漂移则**如实记录本轮 + 落 ALERT + 标 `model_drift_detected`**
  （决策是真数据，不能因告警丢掉，但必须带着告警落盘并回报工部）。
* **seed 名义化口径**（`reporting.py`）：`temperature=0` 下 seed 不产生离散，逐轮把这句写进 round JSON，
  且下四分位「= 较差变体」这条性质每轮用真 `seed_distribution()` 现算成证据。**不改 temperature、不重冻。**

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
from qlab.llm_paper.determinism import (STATUS_DRIFT, ProbeUnverifiable,  # noqa: E402
                                        probe_request, verify_or_establish)
from qlab.llm_paper.price_bridge import settle_actual_start  # noqa: E402
from qlab.llm_paper.reporting import quantile_caliber, seed_semantics  # noqa: E402

OUT_DIR = "qlab/reports/llm_paper"
CANDIDATE_ID = "llm_paper"
ET_TZ = "America/New_York"
# 记账单位。**不是冻结参数**：任何收益/回撤/Sharpe/MAR 对它都是标度不变量，故不影响任何判定，
# 只决定 round JSON 里的美元数字好不好读。纸面允许小数股（无真实成交、无最小交易单位）。
START_NAV = 100_000.0


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


def build_book(decisions, bars_by_symbol: Dict[str, Any], cfg: Dict[str, Any],
               *, nav: float = START_NAV, cost_mult: float = 1.0) -> Dict[str, Any]:
    """把目标权重换成**股数** —— 按 `actual_start` 当日**开盘价**建仓（预注册：当日开盘执行）。

    这里有一处我自己写错过、必须记下的口径：`mark_to_market(holdings=…)` 吃的是**股数**，
    早先版本直接把 `target_weight` 灌了进去，算出来的 "market_value" 是 `0.05 × 收盘价` 这种
    毫无意义的数——第一个净值点就会是错的算术。权重 → 股数必须显式过一遍建仓价。

    **建仓价按 `actual_start` 那天的 open 取**；该 bar 还没出现（决策日当天必然如此，因为
    决策在建仓日之前）⇒ 返回 `pending_entry_bar`，**本轮不产生净值点**。这不是缺陷而是事实：
    仓位尚未建立，此刻任何"净值"都是编的。等建仓 bar 出现的那一轮再落第一个净值点。
    """
    cost_rate = float(cfg["cost_per_turnover"]) * float(cost_mult)
    pending = [d.symbol for d in decisions if not d.actual_start]
    if pending:
        return {"status": "pending_entry_bar", "pending_symbols": pending,
                "reason": ("建仓 bar 尚未出现（决策先于建仓日）→ 本轮不产生净值点。"
                           "仓位还没建立，此刻的任何净值都是编的；等首根建仓 bar 出现再起算。")}
    shares, entries, missing = {}, {}, []
    for d in decisions:
        day = pd.Timestamp(d.actual_start).tz_convert(ET_TZ).strftime("%Y-%m-%d")
        bar = next((b for b in bars_by_symbol.get(d.symbol, []) if b.date == day), None)
        px = getattr(bar, "open", None) if bar else None
        if px is None:                      # 缺开盘价 → 不拿收盘价凑（那是另一个价格）
            missing.append(f"{d.symbol}@{day}")
            continue
        notional = nav * d.target_weight
        entries[d.symbol] = {"entry_date": day, "entry_open": float(px),
                             "weight": d.target_weight, "notional": notional}
        shares[d.symbol] = notional / float(px)
    if missing:
        return {"status": "missing_entry_open", "missing": missing,
                "reason": "建仓日缺 open → 不用 close 顶替（不同价格），本轮不落净值点"}
    gross = sum(e["notional"] for e in entries.values())
    cost = gross * cost_rate
    return {"status": "filled", "nav_start": nav, "shares": shares, "entries": entries,
            "gross_notional": gross, "cash": nav - gross - cost,
            "entry_cost": cost, "cost_rate_per_side": cost_rate, "cost_mult": cost_mult,
            "note": "纸面允许小数股；建仓成本已扣（x1 为入账口径，x2 见 shadow）"}


def gold_probe_request() -> Dict[str, Any]:
    """决策阶段每轮**必须**先跑这一次固定调用，把原样输出回传给 `run_round(probe=...)`。"""
    return probe_request()


def run_round(*, proposals: Sequence[Dict[str, Any]], decision_ts,
              probe: Optional[Dict[str, str]] = None,
              benchmark: str = "SPY", out_dir: str = OUT_DIR,
              cfg: Optional[Dict[str, Any]] = None,
              rejected_evidence: Optional[Sequence[Dict[str, Any]]] = None,
              register_trials: bool = True) -> Dict[str, Any]:
    """执行一次决策轮。

    `proposals`：每项 = {symbol, target_weight, confidence, thesis, evidence_records,
    seed, prompt_variant}（由 LLM 决策阶段产出；证据须带信息源自身时间 `source_time_utc`）。

    `probe`：本轮金标准复现的结果 = {"model": <模型标识>, "output": <原样输出>}，
    由决策阶段按 `gold_probe_request()` 跑一次得到。**必传**——缺失即 `PreflightFailed`，
    不设跳过开关（可跳过的护栏等于没有护栏，本轨栽过多次的 fail-open 形态）。
    """
    cfg = cfg or load_prereg()
    symbols = sorted({p["symbol"] for p in proposals} | {benchmark})
    pre = preflight(n_symbols_needed=len(symbols), cfg=cfg)

    # ---- 金标准复现（放在花配额之前：护栏不过就别浪费当天额度） ----
    if not probe or not probe.get("output"):
        raise PreflightFailed(
            "缺金标准复现结果（probe={'model':…,'output':…}）→ 不起跑。"
            "同名模型被换权重时净值序列不会有任何提示，本轨按年计，这个混淆因子必须逐轮观测；"
            "**不提供跳过开关**——可跳过的护栏等于没有护栏。")
    stamp = pd.Timestamp(decision_ts).strftime("%Y%m%d")
    try:
        det = verify_or_establish(output=probe["output"], model=probe.get("model", ""),
                                  round_id=f"{CANDIDATE_ID}-{stamp}")
    except ProbeUnverifiable as e:
        raise PreflightFailed(f"金标准复现无法测量 → fail-closed：{e}") from e
    seeds_block = seed_semantics(det["status"])

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

    # ---- 建仓（权重 → 股数，按建仓日 open）+ 盯市（缺价即拒） ----
    book = build_book(decisions, bars, cfg)
    book_x2 = (build_book(decisions, bars, cfg, cost_mult=2.0)
               if book["status"] == "filled" else None)     # 双轨：x2 影子口径
    if book["status"] == "filled":
        mtm = mark_to_market(book["shares"], bars)
        nav_point = {"as_of": mtm["as_of"], "nav": mtm["market_value"] + book["cash"],
                     "nav_x2_cost": (mtm["market_value"] + book_x2["cash"]) if book_x2 else None,
                     "nav_start": book["nav_start"]}
    else:
        mtm, nav_point = None, None                        # 仓位未建立 ⇒ 绝不编净值点

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

    alerts = [STATUS_DRIFT] if det["drift"] else []
    payload = {
        "round_decision_ts": pd.Timestamp(decision_ts).isoformat(),
        "preflight": pre,
        "n_decisions": len(decisions),
        "portfolio_check": port,
        "actual_start_settlement": settle,
        "book": book,
        "book_x2_cost": book_x2,
        "mark_to_market": mtm,
        "nav_point": nav_point,
        "ledger": ({"run_id": ledger_rec.run_id, "n_trials_total": ledger_rec.n_trials_total}
                   if ledger_rec else None),
        "rejected_evidence": list(rejected_evidence or []),
        "decisions": [d.to_log_entry() for d in decisions],
        # 金标准复现：探针输出与其 sha256 原样留档，都察院可拿仓内基线独立复核
        "determinism": det,
        "gold_probe_output": probe["output"],
        "seed_semantics": seeds_block,
        "seed_quantile_caliber": quantile_caliber(),
        "alerts": alerts,
        "verdict": None,
        "note": "中途读数只作监控、**不出 verdict**；判定一律走 certify()+llm_paradigm（预注册 §4）",
    }
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / f"round_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if det["drift"]:
        # 单独落一份显眼的 ALERT：round JSON 会越攒越多，漂移不能只藏在字段里
        (out / f"ALERT_model_drift_{stamp}.json").write_text(
            json.dumps({"alert": STATUS_DRIFT, "round": stamp, "determinism": det,
                        "action_required": "立刻回报工部；判定证据期是否重新起算；基线不得改写",
                        "seed_semantics": seeds_block},
                       ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload

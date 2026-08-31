"""Derived, append-only settlement for the LLM-paper decision records.

Round JSON is an immutable decision record, not a net-asset-value source.  This
module reconstructs the as-traded / literal-cash lower-bound series from those
decisions and the separately archived bars.  It never reads ``nav_point`` and
never rewrites a round record.  The acceptance (total-return) leg remains a
different source and is intentionally not substituted here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from qlab.events.datafetch.api_quota import MARKING, guard_from_env
from qlab.events.datafetch.quotes_api import get_daily_closes
from qlab.llm_paper.bar_archive import (ArchiveIntegrityError, archive_quote_snapshot, load_settlement_bars,
                                         require_settlement_integrity)
from qlab.llm_paper.decision_chain import load_prereg
from qlab.llm_paper.ledger_bridge import cell_id
from qlab.llm_paper.nav_series import load_rounds

ET = "America/New_York"
START_NAV = 100_000.0
READING_KINDS = frozenset({"equivalence_artifact", "lower_bound", "acceptance"})
# 吏部 2026-08-31 的一次性授权。它不是一个可随首份归档日期滑动的规则：
# 只有这两份归档机制上线前已落盘的决策可以使用后来归档到的历史 bar。
PRE_ARCHIVE_BACKFILL_AUTHORIZED_ROUNDS = frozenset({"20260810", "20260831"})


class SettlementDataUnavailable(RuntimeError):
    """A truthful lower-bound settlement cannot yet be constructed."""


def require_reading_kind(value: str) -> str:
    """Validate the positive, mutually exclusive classification of a result."""
    if value not in READING_KINDS:
        raise ValueError(f"未知 reading_kind={value!r}; 必须是 {sorted(READING_KINDS)} 之一")
    return value


def authorized_pre_archive_symbols(out_dir: str, *, benchmark: str = "SPY") -> List[str]:
    """The only symbols permitted in the one-time historical capture.

    This derives the set from the two immutable authorized rounds rather than
    accepting a caller-provided universe.  It is therefore impossible to turn
    the narrow ruling into a convenient all-symbol refresh.
    """
    symbols = {benchmark}
    for payload in load_rounds(out_dir):
        if _stamp(payload) not in PRE_ARCHIVE_BACKFILL_AUTHORIZED_ROUNDS:
            continue
        for block in _cells(payload).values():
            symbols |= {str(decision["symbol"]) for decision in block["decisions"]}
    return sorted(symbols)


def capture_authorized_pre_archive_bars(out_dir: str, *, stamp: str, guard=None,
                                        benchmark: str = "SPY") -> Dict[str, Any]:
    """Perform the single permitted AV compact capture for the two old rounds.

    This is deliberately a non-round-day operation: it must not consume the
    Monday decision run's shared 25-call free-tier budget.  It uses the normal
    marking quota and the same AV endpoint/schema as a regular archive fetch;
    no source substitution or separate evidence store is allowed.
    """
    capture_day = pd.Timestamp(stamp)
    if capture_day.weekday() not in {1, 2, 3, 4}:       # Tuesday through Friday only
        raise SettlementDataUnavailable("一次性定向补取只能在非轮次日（周二至周五）执行")
    archive = load_settlement_bars(out_dir)
    if any(capture.get("executor") == "authorized_pre_archive_backfill"
           for capture in archive["captures"]):
        raise SettlementDataUnavailable("一次性定向补取已执行；不得再次调用或扩大其范围")
    symbols = authorized_pre_archive_symbols(out_dir, benchmark=benchmark)
    if not symbols or symbols == [benchmark]:
        raise SettlementDataUnavailable("未找到两份获授权 round JSON 的持仓标的，拒绝猜测补取范围")
    guard = guard or guard_from_env()
    # get_daily_closes repeats this whole-batch check before issuing calls; keep
    # it explicit here so a caller sees the all-or-nothing budget failure at the
    # authorization boundary rather than halfway through a vendor loop.
    guard.check(len(symbols), purpose=MARKING)
    bars, failed = get_daily_closes(symbols, guard=guard, purpose=MARKING,
                                    require_full_batch=True)
    if failed:
        raise SettlementDataUnavailable(f"一次性定向补取不完整 {failed}；不得写半截归档")
    archived = archive_quote_snapshot(bars, out_dir=out_dir, stamp=capture_day.strftime("%Y%m%d"),
                                      executor="authorized_pre_archive_backfill")
    return {"purpose": "one_time_authorized_pre_archive_backfill",
            "symbols": symbols, "quota_purpose": MARKING, "archive": archived,
            "note": ("同一供应商 AV TIME_SERIES_DAILY / 同一 schema；仅补 08-10、08-31"
                     " 两轮的持仓并集与基准，不能援引为后续轮次回补先例。")}


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stamp(payload: Mapping[str, Any]) -> str:
    return str(payload.get("_file", "")).removeprefix("round_").removesuffix(".json")


def _cells(payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Normalize both executor payload forms without consuming round nav fields."""
    if payload.get("cells"):
        return {name: {"decisions": list(block.get("decisions") or []),
                       "portfolio_check": block.get("portfolio_check") or {}}
                for name, block in payload["cells"].items()}
    decisions = list(payload.get("decisions") or [])
    identities = {(int(d["seed"]), str(d["prompt_variant"])) for d in decisions
                  if "seed" in d and "prompt_variant" in d}
    if len(identities) != 1:
        raise SettlementDataUnavailable(
            f"{payload.get('_file')} 单 book 决策不能唯一归属一个格子，拒绝猜测")
    seed, variant = next(iter(identities))
    return {cell_id(seed, variant): {"decisions": decisions,
                                      "portfolio_check": payload.get("portfolio_check") or {}}}


def _date(value: str) -> str:
    return pd.Timestamp(value).tz_convert(ET).strftime("%Y-%m-%d")


def _archive_date(first_capture_round: str | None) -> str | None:
    """The first archive-run date, used for provenance labelling—not eligibility."""
    if first_capture_round and len(first_capture_round) == 8 and first_capture_round.isdigit():
        return f"{first_capture_round[:4]}-{first_capture_round[4:6]}-{first_capture_round[6:]}"
    return None


def _pre_archive_provenance(*, round_: str, consumed: set[tuple[str, str]],
                            first_archive_date: str | None) -> Dict[str, Any] | None:
    """Label the whole reading when it uses a bar predating archive launch.

    The immutable archive, not a bar-date floor, is the admission criterion.
    The date comparison solely exposes the lower evidence strength: there was
    no contemporaneous archive copy against which a later refetch can be
    cross-checked.  The exceptional admission is hard-coded and closes itself.
    """
    if not first_archive_date:
        return None
    keys = sorted(key for key in consumed if key[1] < first_archive_date)
    if not keys:
        return None
    if round_ not in PRE_ARCHIVE_BACKFILL_AUTHORIZED_ROUNDS:
        raise SettlementDataUnavailable(
            "首份归档前历史 bar 的一次性回补授权已自动关闭："
            f"round={round_} 不在 {sorted(PRE_ARCHIVE_BACKFILL_AUTHORIZED_ROUNDS)}。"
            "该轮读数丢失，停止报告；不得回补或援引 2026-08-31 裁定。")
    return {
        "scope": "entire_nav_segment",
        "kind": "retrospectively_archived_pre_initial_capture",
        "first_archive_date": first_archive_date,
        "pre_initial_archive_keys": [{"symbol": symbol, "date": date} for symbol, date in keys],
        "authorization": "one_time_pre_archive_rounds_20260810_20260831_only",
        "cross_check_baseline": "absent",
        "not_verified": True,
        "not_cross_checked": True,
        "acceptance_eligible": False,
        "must_not_promote_to_acceptance": True,
        "note": ("该 bar 已在不可改归档中，但早于首份归档；没有当时副本可与日后重取逐位比。"
                 "此标签覆盖整段 NAV，不得称已核验或已交叉核对。"),
    }


def _settle_cell(*, decisions: List[Mapping[str, Any]], portfolio_check: Mapping[str, Any],
                 bars: Mapping[tuple[str, str], Mapping[str, Any]],
                 external_keys: set[tuple[str, str]], first_archive_date: str | None,
                 round_: str, out_dir: str, cost_rate: float) -> Dict[str, Any]:
    if not decisions:
        raise SettlementDataUnavailable("空决策格不是持现金，拒绝结算")
    if portfolio_check and not portfolio_check.get("ok", False):
        return {"status": "no_rebalance", "nav_start": START_NAV,
                "nav_series": [{"as_of": None, "nav": START_NAV}],
                "reason": "该格组合约束未过；派生层不提交新目标权重，字面现金收益为零"}

    weights: Dict[str, float] = {}
    intended: Dict[str, str] = {}
    for decision in decisions:
        symbol = str(decision["symbol"])
        weights[symbol] = weights.get(symbol, 0.0) + float(decision["target_weight"])
        intended.setdefault(symbol, _date(str(decision["intended_start"])))
    if any(weight < 0 for weight in weights.values()):
        raise SettlementDataUnavailable("派生层遇到空头权重，拒绝把它算成下界")

    dates_by_symbol: Dict[str, List[str]] = {}
    missing: List[str] = []
    entry_dates: Dict[str, str] = {}
    for symbol in sorted(weights):
        # 准入只问「是否已进入带 hash 的 append-only archive」。不得再按
        # bar 日期 < 首份归档日一刀切；较弱溯源由全段 provenance 如实标出。
        dates = sorted(date for sym, date in bars if sym == symbol and date >= intended[symbol])
        dates_by_symbol[symbol] = dates
        if dates:
            entry_dates[symbol] = dates[0]
        else:
            missing.append(f"{symbol}@{intended[symbol]}")
    if missing:
        return {"status": "pending_archived_entry_bar", "missing": missing,
                "reason": "缺存在于不可改归档的建仓 bar → 不编建仓价或净值"}

    common_dates = set(dates_by_symbol[next(iter(sorted(weights)))])
    for symbol in sorted(weights):
        common_dates &= set(date for date in dates_by_symbol[symbol] if date >= entry_dates[symbol])
    marks = sorted(common_dates)
    if not marks:
        return {"status": "pending_common_mark", "entries_pending": entry_dates,
                "reason": "各持仓尚无同一归档交易日可盯市，拒绝拼不同日期的价格"}

    consumed = {(symbol, entry_dates[symbol]) for symbol in weights}
    consumed |= {(symbol, day) for symbol in weights for day in marks}
    # This is the fail-closed boundary: it runs only after the exact consumed
    # window is known, but before a single derived NAV is emitted.
    require_settlement_integrity(out_dir, keys=consumed)
    external = sorted(consumed & external_keys)
    if external:
        return {"status": "pending_external_ruling_price", "keys": external,
                "reason": "裁定采信 external 版本，但该版本尚未作为独立归档证据提供"}
    provenance = _pre_archive_provenance(round_=round_, consumed=consumed,
                                         first_archive_date=first_archive_date)

    entries: Dict[str, Dict[str, float | str]] = {}
    shares: Dict[str, float] = {}
    gross = 0.0
    for symbol, weight in sorted(weights.items()):
        entry = bars[(symbol, entry_dates[symbol])]
        open_ = entry.get("open")
        if open_ is None or float(open_) <= 0:
            raise SettlementDataUnavailable(f"{symbol}@{entry_dates[symbol]} 缺合法 open，拒绝用 close 顶替")
        notional = START_NAV * weight
        gross += notional
        entries[symbol] = {"entry_date": entry_dates[symbol], "entry_open": float(open_),
                           "weight": weight, "notional": notional}
        shares[symbol] = notional / float(open_)
    # The lower-bound cash leg earns literal zero rather than BIL yield.  The
    # entry cost itself remains the frozen cost parameter, never a local knob.
    entry_cost = gross * cost_rate
    cash = START_NAV - gross - entry_cost
    nav_series = []
    for day in marks:
        value = sum(shares[symbol] * float(bars[(symbol, day)]["close"]) for symbol in weights)
        point: Dict[str, Any] = {"as_of": day, "nav": value + cash}
        if provenance:
            point["bar_provenance"] = provenance
        nav_series.append(point)
    return {"status": "filled", "nav_start": START_NAV, "entries": entries, "shares": shares,
            "gross_notional": gross, "entry_cost": entry_cost, "cash": cash,
            "nav_series": nav_series, "consumed_bar_keys": sorted(consumed),
            "bar_provenance": provenance,
            "basis": "archived as-traded equity price + literal zero-yield cash (non-acceptance lower bound)"}


def rebuild_lower_bound_settlement(out_dir: str) -> Dict[str, Any]:
    """Backfill every persisted decision round into one derived lower-bound artifact.

    It is deterministic from immutable round decisions plus archived bars.  A
    Missing bars remain explicit pending results.  A bar later observed and
    immutably archived can be used only under the one-time pre-archive ruling,
    with a non-promotable whole-segment provenance label.
    """
    archive = load_settlement_bars(out_dir)
    first_archive_date = _archive_date(archive["first_capture_round"])
    cost_rate = float(load_prereg()["cost_per_turnover"])
    result: Dict[str, Any] = {
        "schema": "llm_paper_derived_settlement/v1",
        "reading_kind": require_reading_kind("lower_bound"),
        "basis": "as_traded_equity_and_literal_zero_cash_lower_bound",
        # Compatibility convenience only.  Consumers must classify by the
        # positive reading_kind; False alone cannot distinguish this from an
        # equivalence artifact.
        "is_acceptance_reading": False,
        "source": {"round_records": [], "archive_content_sha256s": archive["archive_content_sha256s"],
                   "first_capture_round": archive["first_capture_round"],
                   "pre_archive_backfill_authorized_rounds": sorted(PRE_ARCHIVE_BACKFILL_AUTHORIZED_ROUNDS)},
        "rounds": [],
        "note": "round-record nav_point is not consumed; missing archival coverage remains explicit.",
    }
    for payload in load_rounds(out_dir):
        stamp = _stamp(payload)
        result["source"]["round_records"].append(payload.get("_file"))
        cells = {name: _settle_cell(decisions=block["decisions"],
                                    portfolio_check=block["portfolio_check"], bars=archive["bars"],
                                    external_keys=archive["external_keys"],
                                    first_archive_date=first_archive_date, round_=stamp,
                                    out_dir=out_dir, cost_rate=cost_rate)
                 for name, block in _cells(payload).items()}
        result["rounds"].append({"round": stamp, "executor": payload.get("executor", "single_book"),
                                 "cells": cells})
    return result


def write_lower_bound_settlement(out_dir: str) -> Dict[str, Any]:
    """Materialize the reconstruction append-only; identical retries reuse it."""
    payload = rebuild_lower_bound_settlement(out_dir)
    payload["content_sha256"] = _hash(payload)
    directory = Path(out_dir) / "derived_settlement"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"SETTLEMENT_{payload['content_sha256'][:16]}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ArchiveIntegrityError("派生结算文件名冲突且内容不同")
    return {"settlement_file": str(path), "content_sha256": payload["content_sha256"],
            "n_rounds": len(payload["rounds"]), "payload": payload}

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

from qlab.llm_paper.bar_archive import (ArchiveIntegrityError, load_settlement_bars,
                                         require_settlement_integrity)
from qlab.llm_paper.archive_scan_state import scanner_activation_date
from qlab.llm_paper.decision_chain import load_prereg
from qlab.llm_paper.ledger_bridge import cell_id
from qlab.llm_paper.nav_series import load_rounds

ET = "America/New_York"
START_NAV = 100_000.0
READING_KINDS = frozenset({"equivalence_artifact", "lower_bound", "acceptance"})


class SettlementDataUnavailable(RuntimeError):
    """A truthful lower-bound settlement cannot yet be constructed."""


def require_reading_kind(value: str) -> str:
    """Validate the positive, mutually exclusive classification of a result."""
    if value not in READING_KINDS:
        raise ValueError(f"未知 reading_kind={value!r}; 必须是 {sorted(READING_KINDS)} 之一")
    return value




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


def _round_execution_date(payload: Mapping[str, Any],
                          bars: Mapping[tuple[str, str], Mapping[str, Any]]) -> str | None:
    """Observed execution date for a persisted round, never a calendar guess.

    The live runner uses the union of fetched bar dates to resolve every
    decision's ``actual_start``.  Settlement reproduces that rule from the
    immutable archive: the next round closes this one only once an observed bar
    establishes its execution date.  Until then the newest round remains open.
    """
    observed_days = sorted({date for _, date in bars})
    intended = [_date(str(decision["intended_start"]))
                for block in _cells(payload).values()
                for decision in block["decisions"]]
    starts = [next((day for day in observed_days if day >= value), None) for value in intended]
    if not starts or any(day is None for day in starts):
        return None
    return max(str(day) for day in starts)


def _cell_execution_date(block: Mapping[str, Any],
                         bars: Mapping[tuple[str, str], Mapping[str, Any]]) -> str | None:
    """Observed execution date for one cell's actual new book."""
    observed_days = sorted({date for _, date in bars})
    intended = [_date(str(decision["intended_start"])) for decision in block["decisions"]]
    starts = [next((day for day in observed_days if day >= value), None) for value in intended]
    if not starts or any(day is None for day in starts):
        return None
    return max(str(day) for day in starts)


def _pre_archive_provenance(*, round_: str, consumed: set[tuple[str, str]],
                            first_archive_date: str | None,
                            scanner_started: str | None) -> Dict[str, Any] | None:
    """Label the whole reading when it uses a bar predating archive launch.

    The immutable archive, not a bar-date floor, is the admission criterion.
    The date comparison solely exposes the lower evidence strength: there was
    no contemporaneous archive copy against which a later refetch can be
    cross-checked.  The exceptional admission is bounded by the first
    successful scanner run, so it includes every already-persisted round and
    closes automatically for later rounds.
    """
    if not first_archive_date:
        return None
    keys = sorted(key for key in consumed if key[1] < first_archive_date)
    if not keys:
        return None
    activation = scanner_started.replace("-", "") if scanner_started else None
    if not activation or round_ >= activation:
        raise SettlementDataUnavailable(
            "首份归档前历史 bar 的一次性回补授权已自动关闭或尚未开启：扫描机制尚未成功运行，"
            "或该轮已在机制到位后落盘。"
            "该轮读数丢失，停止报告；不得回补或援引 2026-08-31 裁定。")
    return {
        "scope": "entire_nav_segment",
        "kind": "retrospectively_archived_pre_initial_capture",
        "first_archive_date": first_archive_date,
        "pre_initial_archive_keys": [{"symbol": symbol, "date": date} for symbol, date in keys],
        "authorization": "one_time_pre_archive_before_scanner_activation_only",
        "scanner_activation_date": scanner_started,
        "cross_check_baseline": "absent",
        "not_verified": True,
        "not_cross_checked": True,
        "acceptance_eligible": False,
        "must_not_promote_to_acceptance": True,
        "note": ("该 bar 已在不可改归档中，但早于首份归档；没有当时副本可与日后重取逐位比。"
                 "此标签覆盖整段 NAV，不得称已核验或已交叉核对。"),
    }


def _refuse_expired_post_scanner_gap(*, round_: str, missing: Iterable[tuple[str, str]],
                                     bars: Mapping[tuple[str, str], Mapping[str, Any]],
                                     scanner_started: str | None) -> None:
    """Close the backfill exception once the compact observation window passed."""
    activation = scanner_started.replace("-", "") if scanner_started else None
    if not activation or round_ < activation:
        return
    observed_days = sorted({date for _, date in bars})
    expired = [(symbol, date) for symbol, date in missing
               if sum(1 for day in observed_days if day > date) >= 100]
    if expired:
        raise SettlementDataUnavailable(
            "扫描机制到位后存在已滑出 compact 窗口的未归档 bar；该轮读数丢失，"
            "停止报告，不得回补、不得援引本裁定：" + repr(expired))


def _settle_cell(*, decisions: List[Mapping[str, Any]], portfolio_check: Mapping[str, Any],
                 bars: Mapping[tuple[str, str], Mapping[str, Any]],
                 external_keys: set[tuple[str, str]], first_archive_date: str | None,
                 scanner_started: str | None, round_: str, out_dir: str, cost_rate: float,
                 window_end: str | None, nav_start: float,
                 previous: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not decisions:
        raise SettlementDataUnavailable("空决策格不是持现金，拒绝结算")
    if portfolio_check and not portfolio_check.get("ok", False):
        return {"status": "pending_no_rebalance_carry_forward",
                "reason": "该格组合约束未过；carry-forward 尚未落地，拒绝把它写成现金平线或出读数"}

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
        _refuse_expired_post_scanner_gap(
            round_=round_, missing=[tuple(item.split("@", 1)) for item in missing],
            bars=bars, scanner_started=scanner_started)
        return {"status": "pending_archived_entry_bar", "missing": missing,
                "reason": "缺存在于不可改归档的建仓 bar → 不编建仓价或净值"}

    common_dates = set(dates_by_symbol[next(iter(sorted(weights)))])
    for symbol in sorted(weights):
        common_dates &= set(date for date in dates_by_symbol[symbol] if date >= entry_dates[symbol])
    # Weekly rebalance means a target book exists only until the next round's
    # observed execution.  Without this strict upper bound each weekly target
    # is silently held to today, overlapping every later book and double
    # counting the same market move in a concatenated NAV series.
    marks = sorted(day for day in common_dates if window_end is None or day < window_end)
    mark_start = max(entry_dates.values())
    observed_days = sorted({date for _, date in bars})
    expected_marks = [day for day in observed_days
                      if day >= mark_start and (window_end is None or day < window_end)]
    missing_marks = [(symbol, day) for symbol in weights for day in expected_marks
                     if (symbol, day) not in bars]
    if missing_marks:
        _refuse_expired_post_scanner_gap(round_=round_, missing=missing_marks,
                                         bars=bars, scanner_started=scanner_started)
        return {"status": "pending_archived_mark_bar",
                "missing": [f"{symbol}@{day}" for symbol, day in sorted(missing_marks)],
                "reason": "盯市窗内缺不可改归档 bar → 不跳过该交易日、不拼残缺净值序列"}
    if not marks:
        return {"status": "pending_common_mark", "entries_pending": entry_dates,
                "reason": "各持仓尚无同一归档交易日可盯市，拒绝拼不同日期的价格"}

    consumed = {(symbol, entry_dates[symbol]) for symbol in weights}
    consumed |= {(symbol, day) for symbol in weights for day in marks}
    # A segment starts from the preceding segment's terminal NAV, never a fresh
    # 100k.  At the rebalance open, old holdings are valued at that open solely
    # to measure actual traded notional; target notionals use the carried NAV.
    rebalance_day = max(entry_dates.values())
    old_notionals: Dict[str, float] = {}
    if previous:
        for symbol, shares in previous["shares"].items():
            old = bars.get((symbol, rebalance_day))
            old_open = old.get("open") if old else None
            if old_open is None or float(old_open) <= 0:
                return {"status": "pending_archived_rebalance_bar",
                        "missing": [f"{symbol}@{rebalance_day}"],
                        "reason": "缺换仓时点旧持仓 open → 无法按 Σ|Δ持仓| 计费"}
            old_notionals[symbol] = float(shares) * float(old_open)
            consumed.add((symbol, rebalance_day))

    # This is the fail-closed boundary: it runs only after the exact consumed
    # window (including old-position rebalance bars) is known, but before a
    # single derived NAV is emitted.
    require_settlement_integrity(out_dir, keys=consumed)
    external = sorted(consumed & external_keys)
    if external:
        return {"status": "pending_external_ruling_price", "keys": external,
                "reason": "裁定采信 external 版本，但该版本尚未作为独立归档证据提供"}
    provenance = _pre_archive_provenance(round_=round_, consumed=consumed,
                                         first_archive_date=first_archive_date,
                                         scanner_started=scanner_started)

    entries: Dict[str, Dict[str, float | str]] = {}
    shares: Dict[str, float] = {}
    gross = 0.0
    for symbol, weight in sorted(weights.items()):
        entry = bars[(symbol, entry_dates[symbol])]
        open_ = entry.get("open")
        if open_ is None or float(open_) <= 0:
            raise SettlementDataUnavailable(f"{symbol}@{entry_dates[symbol]} 缺合法 open，拒绝用 close 顶替")
        notional = nav_start * weight
        gross += notional
        entries[symbol] = {"entry_date": entry_dates[symbol], "entry_open": float(open_),
                           "weight": weight, "notional": notional}
        shares[symbol] = notional / float(open_)
    # `cost_rate_per_side` is the frozen fee rate, while `cost_per_turnover`
    # fixes its base: absolute change in current market notionals across the
    # union.  Buy and sell legs are already both present in Σ|Δ|; do not double
    # it again.  First entry naturally reduces to the old gross formula.
    new_notionals = {symbol: float(entry["notional"]) for symbol, entry in entries.items()}
    turnover_notional = sum(abs(new_notionals.get(symbol, 0.0) - old_notionals.get(symbol, 0.0))
                            for symbol in set(new_notionals) | set(old_notionals))
    entry_cost = turnover_notional * cost_rate
    cash = nav_start - gross - entry_cost
    nav_series = []
    for day in marks:
        value = sum(shares[symbol] * float(bars[(symbol, day)]["close"]) for symbol in weights)
        point: Dict[str, Any] = {"as_of": day, "nav": value + cash}
        if provenance:
            point["bar_provenance"] = provenance
        nav_series.append(point)
    return {"status": "filled", "nav_start": nav_start, "entries": entries, "shares": shares,
            "gross_notional": gross, "turnover_notional": turnover_notional,
            "old_notionals_at_rebalance": old_notionals, "entry_cost": entry_cost, "cash": cash,
            "nav_series": nav_series, "consumed_bar_keys": sorted(consumed),
            "bar_provenance": provenance,
            "basis": "archived as-traded equity price + literal zero-yield cash (non-acceptance lower bound)",
            "mark_window": {"start": min(entry_dates.values()), "end_exclusive": window_end}}


def rebuild_lower_bound_settlement(out_dir: str) -> Dict[str, Any]:
    """Backfill every persisted decision round into one derived lower-bound artifact.

    It is deterministic from immutable round decisions plus archived bars.  A
    Missing bars remain explicit pending results.  A bar later observed and
    immutably archived can be used only under the one-time pre-archive ruling,
    with a non-promotable whole-segment provenance label.
    """
    archive = load_settlement_bars(out_dir)
    first_archive_date = _archive_date(archive["first_capture_round"])
    scanner_started = scanner_activation_date(out_dir)
    cost_rate = float(load_prereg()["cost_per_turnover"])
    rounds = load_rounds(out_dir)
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
                   "scanner_activation_date": scanner_started,
                   "pre_archive_backfill_authorization": (
                       "rounds persisted before the first successful non-round-day scanner only")},
        "rounds": [],
        "note": "round-record nav_point is not consumed; missing archival coverage remains explicit.",
    }
    plans = [{"payload": payload, "cells": _cells(payload)} for payload in rounds]
    blocked_cells = {cid for plan in plans for cid, block in plan["cells"].items()
                     if block["portfolio_check"] and not block["portfolio_check"].get("ok", False)}
    carried: Dict[str, Dict[str, Any]] = {}
    seen_cells: set[str] = set()
    for index, plan in enumerate(plans):
        payload = plan["payload"]
        stamp = _stamp(payload)
        result["source"]["round_records"].append(payload.get("_file"))
        cells: Dict[str, Dict[str, Any]] = {}
        for name, block in plan["cells"].items():
            if name in blocked_cells:
                cells[name] = {"status": "pending_no_rebalance_carry_forward",
                               "reason": ("该格至少一轮未调仓；carry-forward 尚未落地，"
                                          "整条格序列拒绝出读数")}
                continue
            next_block = next((future["cells"][name] for future in plans[index + 1:]
                               if name in future["cells"] and
                               (not future["cells"][name]["portfolio_check"] or
                                future["cells"][name]["portfolio_check"].get("ok", False))), None)
            window_end = _cell_execution_date(next_block, archive["bars"]) if next_block else None
            previous = carried.get(name)
            if name in seen_cells and previous is None:
                cells[name] = {"status": "pending_prior_segment",
                               "reason": "前一段无可核验终点净值；不得从 START_NAV 重启后续段"}
                seen_cells.add(name)
                continue
            cell = _settle_cell(decisions=block["decisions"],
                                portfolio_check=block["portfolio_check"], bars=archive["bars"],
                                external_keys=archive["external_keys"],
                                first_archive_date=first_archive_date, round_=stamp,
                                scanner_started=scanner_started, out_dir=out_dir,
                                cost_rate=cost_rate, window_end=window_end,
                                nav_start=(float(previous["terminal_nav"]) if previous else START_NAV),
                                previous=previous)
            cells[name] = cell
            if cell.get("status") == "filled":
                carried[name] = {"terminal_nav": cell["nav_series"][-1]["nav"],
                                 "shares": cell["shares"]}
            seen_cells.add(name)
        result["rounds"].append({"round": stamp, "executor": payload.get("executor", "single_book"),
                                 "cells": cells})
    return result


def archive_coverage_requirements(out_dir: str) -> Dict[str, Any]:
    """Observed, finite `(symbol, date)` obligations for the archive scanner.

    A date becomes required only after an archived bar proves it was a trading
    day; this deliberately does not synthesize holidays from a calendar.  Each
    round ends at the following round's observed execution, so completed weekly
    windows stop growing forever.  The newest unresolved window is returned as
    ``active_symbols`` for the scanner's next non-round-day observation.
    """
    archive = load_settlement_bars(out_dir)
    bars = archive["bars"]
    observed_days = sorted({date for _, date in bars})
    rounds = load_rounds(out_dir)
    plans = [{"payload": payload, "cells": _cells(payload)} for payload in rounds]
    required: set[tuple[str, str]] = set()
    active_symbols: set[str] = set()
    symbols: set[str] = set()
    details: List[Dict[str, Any]] = []
    for index, plan in enumerate(plans):
        for cid, block in plan["cells"].items():
            if block["portfolio_check"] and not block["portfolio_check"].get("ok", False):
                continue
            next_block = next((future["cells"][cid] for future in plans[index + 1:]
                               if cid in future["cells"] and
                               (not future["cells"][cid]["portfolio_check"] or
                                future["cells"][cid]["portfolio_check"].get("ok", False))), None)
            end = _cell_execution_date(next_block, bars) if next_block else None
            cell_symbols = {str(decision["symbol"]) for decision in block["decisions"]}
            symbols |= cell_symbols
            if end is None:
                active_symbols |= cell_symbols
            entries: Dict[str, str | None] = {}
            intended: Dict[str, str] = {}
            for decision in block["decisions"]:
                symbol = str(decision["symbol"])
                intended[symbol] = _date(str(decision["intended_start"]))
                entries[symbol] = next((date for sym, date in bars
                                        if sym == symbol and date >= intended[symbol]), None)
                if entries[symbol] is None:
                    required.add((symbol, intended[symbol]))
            if all(entries.values()):
                mark_start = max(str(value) for value in entries.values())
                dates = [day for day in observed_days
                         if day >= mark_start and (end is None or day < end)]
                required |= {(symbol, day) for symbol in cell_symbols for day in dates}
                # The end is excluded from NAV marking but is required to value
                # the old book at the next rebalance and compute Σ|Δ| honestly.
                if end:
                    required |= {(symbol, end) for symbol in cell_symbols}
            details.append({"round": _stamp(plan["payload"]), "cell": cid,
                            "symbols": sorted(cell_symbols), "end_exclusive": end,
                            "entries_observed": all(entries.values())})
    missing = sorted(required - set(bars))
    return {"required_keys": sorted(required), "missing_keys": missing,
            "active_symbols": sorted(active_symbols), "symbols": sorted(symbols),
            "observed_trading_days": observed_days, "windows": details}


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

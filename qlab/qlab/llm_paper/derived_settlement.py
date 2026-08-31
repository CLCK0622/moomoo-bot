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


def _capture_floor(first_capture_round: str | None) -> str | None:
    # An archive first introduced on 09-07 may contain a vendor's old 08-10
    # history, but that is not an observation made on 08-10.  Preserve the gap
    # instead of retroactively presenting it as contemporaneous evidence.
    if first_capture_round and len(first_capture_round) == 8 and first_capture_round.isdigit():
        return f"{first_capture_round[:4]}-{first_capture_round[4:6]}-{first_capture_round[6:]}"
    return None


def _settle_cell(*, decisions: List[Mapping[str, Any]], portfolio_check: Mapping[str, Any],
                 bars: Mapping[tuple[str, str], Mapping[str, Any]],
                 external_keys: set[tuple[str, str]], capture_floor: str | None,
                 out_dir: str, cost_rate: float) -> Dict[str, Any]:
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
        dates = sorted(date for sym, date in bars if sym == symbol and
                       date >= intended[symbol] and (capture_floor is None or date >= capture_floor))
        dates_by_symbol[symbol] = dates
        if dates:
            entry_dates[symbol] = dates[0]
        else:
            missing.append(f"{symbol}@{intended[symbol]}")
    if missing:
        return {"status": "pending_archived_entry_bar", "missing": missing,
                "capture_floor": capture_floor,
                "reason": ("缺可用的归档建仓 bar（首份归档之前的历史值不冒充当时观察值）"
                           "→ 不编建仓价或净值")}

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
        nav_series.append({"as_of": day, "nav": value + cash})
    return {"status": "filled", "nav_start": START_NAV, "entries": entries, "shares": shares,
            "gross_notional": gross, "entry_cost": entry_cost, "cash": cash,
            "nav_series": nav_series, "consumed_bar_keys": sorted(consumed),
            "basis": "archived as-traded equity price + literal zero-yield cash (non-acceptance lower bound)"}


def rebuild_lower_bound_settlement(out_dir: str) -> Dict[str, Any]:
    """Backfill every persisted decision round into one derived lower-bound artifact.

    It is deterministic from immutable round decisions plus archived bars.  A
    missing pre-archive interval becomes an explicit pending result, never a
    later vendor history silently relabelled as an old observation.
    """
    archive = load_settlement_bars(out_dir)
    floor = _capture_floor(archive["first_capture_round"])
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
                   "first_capture_round": archive["first_capture_round"]},
        "rounds": [],
        "note": "round-record nav_point is not consumed; missing archival coverage remains explicit.",
    }
    for payload in load_rounds(out_dir):
        stamp = _stamp(payload)
        result["source"]["round_records"].append(payload.get("_file"))
        cells = {name: _settle_cell(decisions=block["decisions"],
                                    portfolio_check=block["portfolio_check"], bars=archive["bars"],
                                    external_keys=archive["external_keys"], capture_floor=floor,
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

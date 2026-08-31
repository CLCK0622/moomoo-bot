"""Catch-up archive scanner for settlement bars; it never runs a decision round.

The Monday runner is perishable evidence.  Historical compact bars are not:
they can be retrieved later (within the provider window), so their collection
lives on this separate Tuesday--Friday MARKING path.  The scanner uses the
same AV ``TIME_SERIES_DAILY`` client and immutable archive as the runner; it
does not create a second quote source or overwrite a prior observation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd

from qlab.events.datafetch.api_quota import MARKING, guard_from_env
from qlab.events.datafetch.quotes_api import get_daily_closes
from qlab.llm_paper.archive_scan_state import write_scanner_state
from qlab.llm_paper.bar_archive import ArchiveIntegrityError, archive_quote_snapshot
from qlab.llm_paper.derived_settlement import (SettlementDataUnavailable,
                                                archive_coverage_requirements)

COMPACT_WINDOW_TRADING_DAYS = 100
HARD_ALERT_REMAINING_TRADING_DAYS = 20
SCANNER_SCHEMA = "llm_paper_archive_scanner/v1"


class ScanDayRefused(SettlementDataUnavailable):
    """Expected no-op: the scanner was invoked outside its Tue--Fri window."""


def _canonical(value: Dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _scan_date(stamp: str) -> str:
    return pd.Timestamp(stamp).strftime("%Y-%m-%d")


def _require_non_round_day(stamp: str) -> str:
    day = pd.Timestamp(stamp)
    if day.weekday() not in {1, 2, 3, 4}:  # Tue--Fri; calendar mechanics only
        raise ScanDayRefused("归档扫描只能在非轮次日（周二至周五）运行")
    return day.strftime("%Y-%m-%d")


def _remaining_trading_days(date: str, observed_days: Iterable[str]) -> int:
    elapsed = sum(1 for day in observed_days if day > date)
    return max(0, COMPACT_WINDOW_TRADING_DAYS - elapsed)


def _write_append_only(directory: Path, prefix: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["content_sha256"] = _hash(payload)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}_{payload['content_sha256'][:16]}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ArchiveIntegrityError("扫描产物文件名冲突且内容不同")
    return {"file": str(path), "content_sha256": payload["content_sha256"]}


def archive_scan_coverage(out_dir: str) -> Dict[str, Any]:
    """Coverage accounting only: no HTTP calls, no calendar prediction."""
    coverage = archive_coverage_requirements(out_dir)
    ageing = [{"symbol": symbol, "date": date,
               "remaining_trading_days": _remaining_trading_days(date, coverage["observed_trading_days"])}
              for symbol, date in coverage["missing_keys"]]
    ageing.sort(key=lambda item: (item["remaining_trading_days"], item["date"], item["symbol"]))
    return {**coverage, "missing_count": len(coverage["missing_keys"]),
            "oldest_missing": ageing[0] if ageing else None,
            "hard_alerts": [item for item in ageing
                            if item["remaining_trading_days"] <= HARD_ALERT_REMAINING_TRADING_DAYS]}


def scan_missing_archive_bars(out_dir: str, *, stamp: str, guard=None,
                              benchmark: str = "SPY") -> Dict[str, Any]:
    """Catch up all observed missing archive keys with AV compact quotes.

    The call is deliberately idempotent: requirements are rebuilt from every
    immutable round on every invocation.  A missed scheduled run therefore
    leaves work for the next run rather than silently losing a weekly window.
    It fetches one compact response only for symbols with an outstanding key,
    plus the currently open round's holdings to observe the next real bar.
    """
    scan_date = _require_non_round_day(stamp)
    before = archive_scan_coverage(out_dir)
    needed = {symbol for symbol, _ in before["missing_keys"]}
    # The current week's window is intentionally open.  Its next actual bar is
    # not knowable until observed, so poll only its current holdings—not every
    # historical holding—and let the returned bar define the required key.
    if before["active_symbols"]:
        needed |= set(before["active_symbols"])
    if needed:
        needed.add(benchmark)
    symbols = sorted(needed)
    archive_result = None
    if symbols:
        guard = guard or guard_from_env()
        # Same endpoint and MARKING ledger as round archival.  Compact is the
        # quotes_api default; daily_full is never requested here.
        guard.check(len(symbols), purpose=MARKING)
        bars, failed = get_daily_closes(symbols, guard=guard, purpose=MARKING,
                                        require_full_batch=True)
        if failed:
            raise SettlementDataUnavailable(
                f"归档扫描不完整 {failed}；不写半截快照，留待下一次追赶")
        archive_result = archive_quote_snapshot(bars, out_dir=out_dir,
                                                stamp=pd.Timestamp(stamp).strftime("%Y%m%d"),
                                                executor="non_round_archive_scanner")
    after = archive_scan_coverage(out_dir)
    report: Dict[str, Any] = {
        "schema": SCANNER_SCHEMA,
        "scan_date": scan_date,
        "executor": "non_round_archive_scanner",
        "quota_purpose": MARKING,
        "source": "AV TIME_SERIES_DAILY compact",
        "requested_symbols": symbols,
        "archive": archive_result,
        "coverage": {"missing_count": after["missing_count"],
                     "oldest_missing": after["oldest_missing"],
                     "missing_keys": [{"symbol": symbol, "date": date}
                                      for symbol, date in after["missing_keys"]]},
        "hard_alerts": after["hard_alerts"],
        "note": ("幂等追赶：每次按全部已落盘轮次重建缺口；只取仍缺键对应标的和当前开窗持仓。"
                 "append-only，不改写既有归档值；供应商差异沿用 RESOLUTION。"),
    }
    report_ref = _write_append_only(Path(out_dir) / "bar_archive" / "scanner", "SCAN", report)
    state_ref = write_scanner_state(out_dir, scan_date=scan_date,
                                    report_sha256=report_ref["content_sha256"])
    alert_ref = None
    if after["hard_alerts"]:
        alert_payload = {"alert": "ARCHIVE_SCAN_WINDOW_EXPIRING", "scan_date": scan_date,
                         "executor": "non_round_archive_scanner",
                         "hard_alerts": after["hard_alerts"],
                         "action_required": "停止静默并回报吏部；仅供人工处理，不进入统计或净值。"}
        alert_ref = _write_append_only(Path(out_dir), "ALERT_archive_scan_window", alert_payload)
    return {"scan_report": report_ref, "scanner_state": state_ref,
            "requested_symbols": symbols, "coverage_before": before,
            "coverage_after": after, "alert": alert_ref}

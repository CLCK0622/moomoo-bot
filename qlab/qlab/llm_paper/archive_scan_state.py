"""Immutable state records for the non-round-day bar archive scanner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable

from qlab.llm_paper.bar_archive import ArchiveIntegrityError, ArchiveRecordCorruptError

SCANNER_STATE_SCHEMA = "llm_paper_archive_scanner_state/v1"


def _canonical(value: Dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _load(path: Path) -> Dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveRecordCorruptError(f"扫描机制记录无法读取: {path.name}: {exc}") from exc
    supplied = record.get("content_sha256")
    unsigned = dict(record)
    unsigned.pop("content_sha256", None)
    if supplied != _hash(unsigned):
        raise ArchiveRecordCorruptError(f"扫描机制记录哈希不匹配: {path.name}")
    if record.get("schema") != SCANNER_STATE_SCHEMA or not record.get("scan_date"):
        raise ArchiveRecordCorruptError(f"扫描机制记录形状非法: {path.name}")
    return record


def scanner_states(out_dir: str) -> Iterable[Dict[str, Any]]:
    directory = Path(out_dir) / "bar_archive" / "scanner"
    if not directory.exists():
        return []
    return [_load(path) for path in sorted(directory.glob("SCANNER_*.json"))]


def scanner_activation_date(out_dir: str) -> str | None:
    """First successful catch-up scan; this is the automatic-close boundary."""
    states = list(scanner_states(out_dir))
    return min((str(state["scan_date"]) for state in states), default=None)


def write_scanner_state(out_dir: str, *, scan_date: str, report_sha256: str) -> Dict[str, Any]:
    """Append a successful activation record; exact retry proves equality."""
    payload: Dict[str, Any] = {
        "schema": SCANNER_STATE_SCHEMA,
        "scan_date": scan_date,
        "report_sha256": report_sha256,
        "note": ("非轮次日扫描机制已成功执行；此后轮次不再适用首份归档前的一次性回补授权。"),
    }
    payload["content_sha256"] = _hash(payload)
    directory = Path(out_dir) / "bar_archive" / "scanner"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"SCANNER_{scan_date}_{payload['content_sha256'][:12]}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        if _load(path) != payload:
            raise ArchiveIntegrityError("扫描机制记录文件名冲突且内容不同")
    return {"scanner_state_file": str(path), "content_sha256": payload["content_sha256"]}

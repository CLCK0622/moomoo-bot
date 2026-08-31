"""Append-only archive for the as-traded bars seen by an LLM-paper round.

The Alpha Vantage snapshot is evidence of what the runner actually observed,
not the settlement source.  It is deliberately captured *after* the normal
quote fetch, so archiving consumes no additional quota and never broadens the
symbol set beyond the holdings plus benchmark requested by the round.

Every successful fetch becomes one immutable JSON record with a content hash.
On later fetches, overlapping ``(symbol, date)`` bars are compared field for
field against every earlier record.  A changed value is an integrity event,
not something this layer is allowed to reconcile silently.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


class ArchiveIntegrityError(RuntimeError):
    """The archive cannot support the requested integrity operation."""


class ArchiveRecordCorruptError(ArchiveIntegrityError):
    """A purportedly immutable archive file was changed or cannot be verified."""


_BAR_FIELDS = ("symbol", "date", "open", "high", "low", "close", "volume", "source")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bar_record(bar: Any) -> Dict[str, Any]:
    """Serialize all price-bearing fields; retrieval time is snapshot metadata."""
    return {name: getattr(bar, name, None) for name in _BAR_FIELDS}


def _load_record(path: Path) -> Dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveRecordCorruptError(f"归档记录无法读取: {path.name}: {exc}") from exc
    supplied = record.get("content_sha256")
    unsigned = dict(record)
    unsigned.pop("content_sha256", None)
    actual = _hash(unsigned)
    if not supplied or supplied != actual:
        raise ArchiveRecordCorruptError(
            f"归档内容哈希不匹配: {path.name} (expected={supplied}, actual={actual})")
    return record


def _existing_records(root: Path) -> Iterable[tuple[Path, Dict[str, Any]]]:
    if not root.exists():
        return []
    return [(path, _load_record(path)) for path in sorted(root.glob("*.json"))]


def _differences(current: Mapping[tuple[str, str], Dict[str, Any]],
                 previous: Mapping[tuple[str, str], Dict[str, Any]]) -> List[Dict[str, Any]]:
    diffs: List[Dict[str, Any]] = []
    for key in sorted(set(current) & set(previous)):
        now, old = current[key], previous[key]
        changed = {field: {"archived": old.get(field), "refetched": now.get(field)}
                   for field in _BAR_FIELDS if old.get(field) != now.get(field)}
        if changed:
            diffs.append({"symbol": key[0], "date": key[1], "fields": changed})
    return diffs


def unresolved_disagreements(out_dir: str) -> List[Dict[str, Any]]:
    """Return every immutable refetch disagreement awaiting a settlement ruling.

    This is intentionally separate from the round runner.  A decision round is
    perishable; settlement is reproducible from the archive and is the layer
    that must refuse to publish a reading while this list is non-empty.
    Corrupt archive files still raise -- an altered evidence record is not a
    provider correction and cannot be treated as an ordinary disagreement.
    """
    root = Path(out_dir) / "bar_archive"
    pending = []
    for path, record in _existing_records(root):
        comparison = record.get("comparison") or {}
        if comparison.get("result") == "unresolved_difference":
            pending.append({"archive_file": str(path),
                            "content_sha256": record.get("content_sha256"),
                            "differences": comparison.get("differences") or []})
    return pending


def require_settlement_integrity(out_dir: str) -> None:
    """Settlement gate: do not emit a reading across an unresolved revision."""
    pending = unresolved_disagreements(out_dir)
    if pending:
        raise ArchiveIntegrityError(
            "归档存在未裁定的供应商历史值分歧；派生结算不得出该窗口读数："
            + json.dumps(pending, ensure_ascii=False, sort_keys=True))


def archive_quote_snapshot(bars_by_symbol: Mapping[str, Iterable[Any]], *, out_dir: str,
                           stamp: str, executor: str,
                           retrieved_utc: str | None = None,
                           consumed_bar_keys: Iterable[tuple[str, str]] = ()) -> Dict[str, Any]:
    """Hash and append the exact bar snapshot, preserving a disagreement as evidence.

    ``out_dir`` is the round's report directory.  The files live below it so a
    control run shares the bearing side's archive rather than creating a second
    competing evidence store.
    """
    root = Path(out_dir) / "bar_archive"
    flat = [_bar_record(bar) for symbol in sorted(bars_by_symbol)
            for bar in bars_by_symbol[symbol]]
    if not flat:
        raise ArchiveIntegrityError("行情快照为空，拒绝归档空证据")
    if {item["symbol"] for item in flat} != set(bars_by_symbol):
        raise ArchiveIntegrityError("归档标的与行情快照不一致，拒绝写入")
    observed = {(item["symbol"], item["date"]): item for item in flat}
    if len(observed) != len(flat):
        raise ArchiveIntegrityError("同一快照含重复 (symbol, date)，拒绝归档")

    disagreements: List[Dict[str, Any]] = []
    for old_path, old in _existing_records(root):
        old_bars = {(item["symbol"], item["date"]): item for item in old.get("bars", [])}
        mismatches = _differences(observed, old_bars)
        if mismatches:
            disagreements.append({"archive": old_path.name, "differences": mismatches})

    retrieved = retrieved_utc or next(
        (getattr(bar, "retrieved_utc", "") for values in bars_by_symbol.values() for bar in values
         if getattr(bar, "retrieved_utc", "")),
        datetime.now(timezone.utc).isoformat())
    payload: Dict[str, Any] = {
        "schema": "llm_paper_as_traded_bar_archive/v1",
        "round": stamp,
        "executor": executor,
        "retrieved_utc": retrieved,
        "symbols": sorted(bars_by_symbol),
        "bars": sorted(flat, key=lambda item: (item["symbol"], item["date"])),
        "comparison": {
            "kind": "same_symbol_same_date_field_by_field",
            "result": "unresolved_difference" if disagreements else "no_prior_difference",
            "differences": disagreements,
            "note": "只比较同一 (symbol, date) 的 as-traded 原始字段；不作复权或插补。",
        },
    }
    payload["content_sha256"] = _hash(payload)
    root.mkdir(parents=True, exist_ok=True)
    safe_time = re.sub(r"[^0-9A-Za-z]+", "-", retrieved).strip("-") or "unknown-time"
    filename = f"archive_{stamp}_{safe_time}_{payload['content_sha256'][:12]}.json"
    path = root / filename
    # Never replace an archive record.  The hash includes retrieval metadata, so
    # an independently fetched snapshot gets its own immutable record.
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        # Exact duplicate retry: prove it is the same immutable payload; do not
        # overwrite it and do not manufacture a second record.
        existing = _load_record(path)
        if existing != payload:
            raise ArchiveIntegrityError(f"归档文件名冲突且内容不同: {path.name}")
    result = {"archive_file": str(path), "content_sha256": payload["content_sha256"],
              "n_bars": len(flat), "symbols": payload["symbols"],
              "unresolved_differences": disagreements}
    # Today no historical bar is consumed by the round runner: newly available
    # bars have no older archive to compare.  Keep the explicit hook anyway so
    # a future in-round settlement cannot accidentally consume a disputed bar.
    consumed = set(consumed_bar_keys)
    consumed_differences = [d for d in disagreements
                            if any((m["symbol"], m["date"]) in consumed
                                   for m in d["differences"])]
    if consumed_differences:
        raise ArchiveIntegrityError(
            "当轮实际消费的 bar 与既有归档不一致，拒绝继续："
            + json.dumps(consumed_differences, ensure_ascii=False, sort_keys=True))
    return result

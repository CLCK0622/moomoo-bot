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
_ARCHIVE_SCHEMA = "llm_paper_as_traded_bar_archive/v1"
_RESOLUTION_SCHEMA = "llm_paper_bar_archive_resolution/v1"


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
    # RESOLUTION files intentionally live below ``resolutions/``.  Do not let
    # their different schema enter the evidence comparison set.
    return [(path, _load_record(path)) for path in sorted(root.glob("archive_*.json"))]


def _resolution_root(root: Path) -> Path:
    return root / "resolutions"


def _load_resolution(path: Path) -> Dict[str, Any]:
    record = _load_record(path)
    if record.get("schema") != _RESOLUTION_SCHEMA:
        raise ArchiveRecordCorruptError(f"裁定记录 schema 非法: {path.name}")
    if not isinstance(record.get("resolved_differences"), list) or not record["resolved_differences"]:
        raise ArchiveRecordCorruptError(f"裁定记录未列出要消解的分歧: {path.name}")
    if not isinstance(record.get("basis"), str) or not record["basis"].strip():
        raise ArchiveRecordCorruptError(f"裁定记录缺少依据: {path.name}")
    if not isinstance(record.get("ruling_reference"), str) or not record["ruling_reference"].strip():
        raise ArchiveRecordCorruptError(f"裁定记录缺少裁定引用: {path.name}")
    if record.get("selected_version") not in {"archived", "refetched", "external"}:
        raise ArchiveRecordCorruptError(f"裁定记录采信版本非法: {path.name}")
    return record


def _existing_resolutions(root: Path) -> Iterable[tuple[Path, Dict[str, Any]]]:
    directory = _resolution_root(root)
    if not directory.exists():
        return []
    return [(path, _load_resolution(path))
            for path in sorted(directory.glob("RESOLUTION_*.json"))]


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


def _key(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        symbol, date = value.get("symbol"), value.get("date")
    else:
        try:
            symbol, date = value
        except (TypeError, ValueError) as exc:
            raise ArchiveIntegrityError("结算窗口键必须是 (symbol, date)") from exc
    if not isinstance(symbol, str) or not symbol or not isinstance(date, str) or not date:
        raise ArchiveIntegrityError("结算窗口键必须含非空 symbol 与 date")
    return symbol, date


def _comparison_items(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Flatten one refetch record's field-level differences by bar key."""
    items: List[Dict[str, Any]] = []
    for group in ((record.get("comparison") or {}).get("differences") or []):
        archive = group.get("archive")
        for item in group.get("differences") or []:
            if not isinstance(item, Mapping):
                raise ArchiveRecordCorruptError("归档差异项形状非法")
            symbol, date = _key(item)
            fields = item.get("fields")
            if not isinstance(fields, Mapping) or not fields:
                raise ArchiveRecordCorruptError("归档差异项缺少字段差异")
            items.append({"archive": archive, "symbol": symbol, "date": date,
                          "fields": dict(fields)})
    return items


def _resolved(item: Mapping[str, Any], resolutions: Iterable[Mapping[str, Any]]) -> bool:
    """A ruling covers the same key *and the same observed field difference*.

    Matching the complete field payload prevents a ruling for ``101 -> 102``
    from silently accepting a later, distinct ``102 -> 103`` provider change.
    It also lets a ruling suppress the identical recurring comparison on later
    snapshots without rewriting either archive record.
    """
    for resolution in resolutions:
        for covered in resolution["resolved_differences"]:
            if (covered.get("symbol"), covered.get("date")) == (item["symbol"], item["date"]) and \
                    covered.get("fields") == item["fields"]:
                return True
    return False


def _validated_resolutions(root: Path,
                           records: Iterable[tuple[Path, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Load rulings only after proving each references real archived evidence."""
    records = list(records)
    by_hash = {record.get("content_sha256"): record for _, record in records}
    resolutions: List[Dict[str, Any]] = []
    for path, resolution in _existing_resolutions(root):
        source = resolution.get("source_archive_content_sha256")
        if source not in by_hash:
            raise ArchiveRecordCorruptError(
                f"裁定记录指向不存在的归档证据: {path.name}")
        source_items = _comparison_items(by_hash[source])
        for covered in resolution["resolved_differences"]:
            if not any(covered == candidate for candidate in source_items):
                raise ArchiveRecordCorruptError(
                    f"裁定记录覆盖了源归档中不存在的分歧: {path.name}")
        resolutions.append(resolution)
    return resolutions


def unresolved_disagreements(out_dir: str) -> List[Dict[str, Any]]:
    """Return every immutable refetch disagreement awaiting a settlement ruling.

    This is intentionally separate from the round runner.  A decision round is
    perishable; settlement is reproducible from the archive and is the layer
    that must refuse to publish a reading while this list is non-empty.
    Corrupt archive files still raise -- an altered evidence record is not a
    provider correction and cannot be treated as an ordinary disagreement.
    """
    root = Path(out_dir) / "bar_archive"
    records = list(_existing_records(root))
    resolutions = _validated_resolutions(root, records)

    pending = []
    for path, record in records:
        comparison = record.get("comparison") or {}
        if comparison.get("result") == "unresolved_difference":
            items = [item for item in _comparison_items(record)
                     if not _resolved(item, resolutions)]
            if items:
                pending.append({"archive_file": str(path),
                                "content_sha256": record.get("content_sha256"),
                                "differences": items})
    return pending


def load_settlement_bars(out_dir: str) -> Dict[str, Any]:
    """Return the ruled as-traded bar view for a derived settlement.

    The view is assembled exclusively from immutable archive records.  An
    ``external`` ruling deliberately has no invented price here: the caller
    receives the affected keys and must wait for the separately archived
    external evidence.  Before a ruling, callers must use the integrity gate;
    this loader keeps the version-selection mechanics separate from that gate.
    """
    root = Path(out_dir) / "bar_archive"
    records = list(_existing_records(root))
    resolutions = _validated_resolutions(root, records)
    by_hash = {record.get("content_sha256"): record for _, record in records}
    by_name = {path.name: record for path, record in records}

    bars: Dict[tuple[str, str], Dict[str, Any]] = {}
    for _, record in records:
        for bar in record.get("bars", []):
            bars[_key(bar)] = dict(bar)       # newest immutable observation wins absent a ruling

    external_keys: set[tuple[str, str]] = set()
    for resolution in resolutions:
        source = by_hash[resolution["source_archive_content_sha256"]]
        for covered in resolution["resolved_differences"]:
            key = _key(covered)
            version = resolution["selected_version"]
            if version == "refetched":
                chosen = next((bar for bar in source.get("bars", []) if _key(bar) == key), None)
            elif version == "archived":
                old = by_name.get(covered.get("archive"))
                chosen = (next((bar for bar in old.get("bars", []) if _key(bar) == key), None)
                          if old else None)
            else:
                external_keys.add(key)
                continue
            if chosen is None:
                raise ArchiveRecordCorruptError("裁定所选版本缺少对应 bar")
            bars[key] = dict(chosen)

    captured_rounds = sorted(str(record.get("round", "")) for _, record in records
                             if str(record.get("round", "")))
    return {"bars": bars, "external_keys": external_keys,
            "first_capture_round": captured_rounds[0] if captured_rounds else None,
            "archive_content_sha256s": sorted(by_hash),
            "captures": [{"round": record.get("round"), "executor": record.get("executor"),
                          "content_sha256": record.get("content_sha256")}
                         for _, record in records]}


def require_settlement_integrity(out_dir: str, *, keys: Iterable[tuple[str, str]]) -> None:
    """Settlement gate: reject only readings whose consumed window is disputed.

    Archive evidence is global, but a derived reading is not.  A CAT correction
    must not block an unrelated symbol/date window.  ``keys`` is therefore the
    exact set of archived bars the caller is about to consume.
    """
    window = {_key(value) for value in keys}
    pending = []
    for disagreement in unresolved_disagreements(out_dir):
        relevant = [item for item in disagreement["differences"]
                    if (item["symbol"], item["date"]) in window]
        if relevant:
            pending.append({**disagreement, "differences": relevant})
    if pending:
        raise ArchiveIntegrityError(
            "归档存在未裁定的供应商历史值分歧；派生结算不得出该窗口读数："
            + json.dumps(pending, ensure_ascii=False, sort_keys=True))


def write_disagreement_resolution(*, out_dir: str, source_archive_content_sha256: str,
                                  keys: Iterable[tuple[str, str]], selected_version: str,
                                  basis: str, ruling_reference: str,
                                  resolved_utc: str | None = None) -> Dict[str, Any]:
    """Append an immutable ruling; never edit the disputed archive evidence.

    This records *how* a competent authority's ruling releases a settlement
    gate.  It deliberately requires the authority's chosen version, rationale
    and reference; this function never chooses a price version itself.
    """
    root = Path(out_dir) / "bar_archive"
    records = list(_existing_records(root))
    source = next((record for _, record in records
                   if record.get("content_sha256") == source_archive_content_sha256), None)
    if source is None:
        raise ArchiveIntegrityError("裁定所指归档记录不存在")
    if (source.get("comparison") or {}).get("result") != "unresolved_difference":
        raise ArchiveIntegrityError("裁定所指归档记录不含待裁定分歧")
    if selected_version not in {"archived", "refetched", "external"}:
        raise ArchiveIntegrityError("采信版本必须是 archived、refetched 或 external")
    if not isinstance(basis, str) or not basis.strip():
        raise ArchiveIntegrityError("裁定依据不得为空")
    if not isinstance(ruling_reference, str) or not ruling_reference.strip():
        raise ArchiveIntegrityError("裁定引用不得为空")
    wanted = {_key(value) for value in keys}
    if not wanted:
        raise ArchiveIntegrityError("裁定必须覆盖至少一个 (symbol, date)")
    source_items = _comparison_items(source)
    covered = [item for item in source_items if (item["symbol"], item["date"]) in wanted]
    if len({(item["symbol"], item["date"]) for item in covered}) != len(wanted):
        raise ArchiveIntegrityError("裁定键不全在所指归档分歧中，拒绝扩大裁定范围")

    resolved = resolved_utc or datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "schema": _RESOLUTION_SCHEMA,
        "resolved_utc": resolved,
        "source_archive_content_sha256": source_archive_content_sha256,
        "resolved_differences": sorted(covered, key=lambda item: (item["symbol"], item["date"])),
        "selected_version": selected_version,
        "basis": basis.strip(),
        "ruling_reference": ruling_reference.strip(),
        "note": "追加式裁定：不回改 archive；同键同字段差异才被此裁定覆盖。",
    }
    payload["content_sha256"] = _hash(payload)
    directory = _resolution_root(root)
    directory.mkdir(parents=True, exist_ok=True)
    safe_time = re.sub(r"[^0-9A-Za-z]+", "-", resolved).strip("-") or "unknown-time"
    path = directory / f"RESOLUTION_{safe_time}_{payload['content_sha256'][:12]}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        if _load_resolution(path) != payload:
            raise ArchiveIntegrityError(f"裁定文件名冲突且内容不同: {path.name}")
    return {"resolution_file": str(path), "content_sha256": payload["content_sha256"],
            "source_archive_content_sha256": source_archive_content_sha256,
            "resolved_keys": sorted({(item["symbol"], item["date"]) for item in covered})}


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
        "schema": _ARCHIVE_SCHEMA,
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

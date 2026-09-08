"""Offline, content-addressed replay of the real LLM-paper executors.

The decision-time 20260831 books are immutable ``pending_entry_bar`` records.
This module does not rewrite them.  It reconstructs their original proposals,
loads only the ruled immutable bar archive, and invokes the production
``run_round`` / ``run_round_multi`` paths through ``run_parallel_control`` in a
temporary directory.  The resulting evidence artifact binds the exact shared
bar snapshot, runtime sources, immutable inputs, filled books, field-by-field
comparison, and the auxiliary derived-settlement reconciliation.

No network, trial-ledger registration, new decision, RESOLUTION write, or
executor switch occurs here.  Identical inputs reuse the same append-only file.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from qlab.events.datafetch.quotes_api import DailyBar
from qlab.llm_paper.bar_archive import (ArchiveIntegrityError,
                                         load_settlement_bars,
                                         require_settlement_integrity,
                                         unresolved_disagreements)
from qlab.llm_paper.decision_chain import (_resolve, load_prereg)
from qlab.llm_paper.derived_settlement import verify_settlement_artifact
from qlab.llm_paper.determinism import (BASELINE_ENV, BASELINE_PATH,
                                        GOLD_PROBE_PATH)
from qlab.llm_paper.ledger_bridge import cell_id
from qlab.llm_paper.parallel_control import run_parallel_control


RUNTIME_REPLAY_SCHEMA = "llm_paper_runtime_replay/v1"
RUNTIME_REPLAY_IMPLEMENTATION_VERSION = "llm_paper_runtime_replay/evo-502-v1"
ARTIFACT_SUBDIR = "runtime_replay"
EXPECTED_ARCHIVE_ROUNDS = ("20260902", "20260903", "20260904")
EXPECTED_ARCHIVE_CONTENT_SHA256S = (
    "65805f8325f2a6e550568a33e0a7bce0acb873f24358d73b392c53ca75604b94",
    "648e2a570c1ecf04dcb6284914dfe2d75990e39a90a458ac7bd100a3ad375629",
    "7a6a3aaf54fbbba4c4af5ec45ea64a664ede0be252bd85b2d7ec4eedb6ca8764",
)
EXPECTED_RESOLUTION_CONTENT_SHA256S = (
    "3b65b52c0fbf1da2d47ffce8e97aa88f53e0b9deb724184cb75e77c17a5c0689",
    "b28639e1502e2f152f9a65c14ade37911818b0b3c76da3aa1df1f949b83291ed",
)
EXPECTED_UNRESOLVED_KEYS = (("SPY", "2026-09-01"), ("SPY", "2026-09-02"))
DEFAULT_SETTLEMENT = "derived_settlement/SETTLEMENT_dfe843379ccb07eb.json"

_ARCHIVE_SCHEMA = "llm_paper_as_traded_bar_archive/v1"
_RESOLUTION_SCHEMA = "llm_paper_bar_archive_resolution/v1"
_BAR_FIELDS = ("symbol", "date", "open", "high", "low", "close", "volume", "source")
_REPLAY_DECISION_FIELDS = (
    "symbol", "target_weight", "confidence", "thesis", "evidence_refs",
    "evidence_available_utc", "evidence_acceptance_utc", "decision_ts",
    "intended_start", "seed", "prompt_variant", "model", "extra",
    "evidence_max_ts",
)
_BOOK_FIELDS = (
    "status", "nav_start", "shares", "entries", "gross_notional", "cash",
    "entry_cost", "cost_rate_per_side", "cost_mult",
)


class RuntimeReplayError(RuntimeError):
    """The immutable inputs cannot support a truthful runtime replay."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeReplayError(f"无法读取 replay 输入 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeReplayError(f"replay 输入必须是 JSON object: {path}")
    return value


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def _manifest_entry(path: Path, root: Path) -> Dict[str, Any]:
    value = _read_json(path)
    entry = {"file": _relative(path, root), "file_sha256": _file_sha256(path)}
    if isinstance(value.get("content_sha256"), str):
        entry["content_sha256"] = value["content_sha256"]
    if isinstance(value.get("schema"), str):
        entry["schema"] = value["schema"]
    return entry


def _archive_inputs(root: Path) -> Tuple[List[Path], List[Path]]:
    archive_root = root / "bar_archive"
    archives = sorted(archive_root.glob("archive_*.json"))
    resolutions = sorted((archive_root / "resolutions").glob("RESOLUTION_*.json"))
    if not archives:
        raise RuntimeReplayError(
            "没有不可改 bar_archive 输入；拒绝从 loose bars JSON 或其他非归档来源 replay")
    rounds, hashes = [], []
    for path in archives:
        record = _read_json(path)
        if record.get("schema") != _ARCHIVE_SCHEMA:
            raise RuntimeReplayError(f"非归档输入或 archive schema 非法: {path.name}")
        rounds.append(str(record.get("round", "")))
        hashes.append(str(record.get("content_sha256", "")))
    if tuple(rounds) != EXPECTED_ARCHIVE_ROUNDS or \
            tuple(hashes) != EXPECTED_ARCHIVE_CONTENT_SHA256S:
        raise RuntimeReplayError(
            "本 replay 只允许 09-02/09-03/09-04 三份固定归档，拒绝消费新段或缺失归档: "
            f"expected_rounds={list(EXPECTED_ARCHIVE_ROUNDS)}, actual_rounds={rounds}, "
            f"expected_hashes={list(EXPECTED_ARCHIVE_CONTENT_SHA256S)}, actual_hashes={hashes}")
    resolution_hashes = []
    for path in resolutions:
        record = _read_json(path)
        if record.get("schema") != _RESOLUTION_SCHEMA:
            raise RuntimeReplayError(f"RESOLUTION schema 非法: {path.name}")
        resolution_hashes.append(str(record.get("content_sha256", "")))
    if tuple(resolution_hashes) != EXPECTED_RESOLUTION_CONTENT_SHA256S:
        raise RuntimeReplayError(
            "本 replay 必须沿用已落盘的两份固定 RESOLUTION，拒绝缺失、新增或替换: "
            f"expected={list(EXPECTED_RESOLUTION_CONTENT_SHA256S)}, actual={resolution_hashes}")
    return archives, resolutions


def _required_paths(root: Path, stamp: str, settlement_file: Path,
                    archives: Sequence[Path], resolutions: Sequence[Path]) -> List[Path]:
    paths = [root / f"round_{stamp}.json",
             root / "control_multi_book" / f"round_{stamp}.json",
             root / f"CONTROL_{stamp}.json", settlement_file]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeReplayError("缺 replay 输入: " + ", ".join(missing))
    return paths + list(archives) + list(resolutions)


def _proposal(entry: Mapping[str, Any], *, include_cell: bool) -> Dict[str, Any]:
    refs = entry.get("evidence_refs")
    acceptance = entry.get("evidence_acceptance_utc")
    if not isinstance(refs, list) or not refs or not isinstance(acceptance, str):
        raise RuntimeReplayError("决策记录缺 evidence_refs/evidence_acceptance_utc，不能重走真实决策链")
    if entry.get("extra") not in ({}, None):
        raise RuntimeReplayError("决策记录含不可由落盘字段无损重建的 extra，拒绝猜测 replay")
    out = {
        "symbol": entry["symbol"],
        "target_weight": entry["target_weight"],
        "confidence": entry["confidence"],
        "thesis": entry["thesis"],
        # The immutable log stores every ref plus the maximum source acceptance
        # time.  Reusing that maximum for each ref preserves both the complete
        # ref list and the exact max-time decision guard without inventing an
        # earlier per-ref timestamp that the record never retained.
        "evidence_records": [{"source_time_utc": acceptance, "ref_id": ref} for ref in refs],
        "model": entry.get("model", ""),
    }
    if include_cell:
        out.update({"seed": int(entry["seed"]),
                    "prompt_variant": str(entry["prompt_variant"])})
    return out


def _cells(control: Mapping[str, Any]) -> List[Dict[str, Any]]:
    cells = []
    for cid, block in (control.get("cells") or {}).items():
        seed = int(block["seed"])
        variant = str(block["prompt_variant"])
        if cid != cell_id(seed, variant):
            raise RuntimeReplayError(f"control cell key 与内容不一致: {cid}")
        cells.append({"seed": seed, "prompt_variant": variant,
                      "proposals": [_proposal(item, include_cell=False)
                                    for item in block.get("decisions") or []]})
    return sorted(cells, key=lambda item: (item["seed"], item["prompt_variant"]))


def _unresolved_keys(root: Path) -> List[Tuple[str, str]]:
    keys = {(item["symbol"], item["date"])
            for group in unresolved_disagreements(str(root))
            for item in group.get("differences") or []}
    return sorted(keys)


def _bar_dict(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: record.get(field) for field in _BAR_FIELDS}


def _bar_snapshot(root: Path, symbols: Sequence[str]) -> Tuple[Dict[str, List[DailyBar]], Dict[str, Any]]:
    archive = load_settlement_bars(str(root))
    unresolved_list = _unresolved_keys(root)
    if tuple(unresolved_list) != EXPECTED_UNRESOLVED_KEYS:
        raise RuntimeReplayError(
            "未裁定键集合变化；不得自行扩大或缩小键域: "
            f"expected={list(EXPECTED_UNRESOLVED_KEYS)}, actual={unresolved_list}")
    unresolved = set(unresolved_list)
    selected = [_bar_dict(bar) for key, bar in sorted(archive["bars"].items())
                if key[0] in symbols and key not in unresolved]
    by_symbol: Dict[str, List[DailyBar]] = {symbol: [] for symbol in symbols}
    for bar in selected:
        by_symbol[bar["symbol"]].append(DailyBar(**bar))
    missing = sorted(symbol for symbol, rows in by_symbol.items() if not rows)
    if missing:
        raise RuntimeReplayError(f"归档快照缺 replay 标的: {missing}")

    consumed_keys = {(bar["symbol"], bar["date"]) for bar in selected}
    require_settlement_integrity(str(root), keys=consumed_keys)

    blocked = []
    for key in sorted(unresolved):
        try:
            require_settlement_integrity(str(root), keys={key})
        except ArchiveIntegrityError as exc:
            blocked.append({"symbol": key[0], "date": key[1], "still_blocked": True,
                            "error_type": type(exc).__name__})
        else:
            raise RuntimeReplayError(f"未裁定键 {key} 未被完整性闸阻断")

    payload: Dict[str, Any] = {
        "schema": "llm_paper_runtime_bar_snapshot/v1",
        "source_kind": "ruled_immutable_bar_archive_only",
        "selector": ("required executor symbols; newest ruled immutable observation per key; "
                     "unresolved keys excluded and separately proved blocked"),
        "symbols": sorted(symbols),
        "bars": selected,
        "n_bars": len(selected),
        "archive_content_sha256s": archive["archive_content_sha256s"],
        "captures": archive["captures"],
        "unresolved_keys_excluded_and_still_blocked": blocked,
    }
    payload["content_sha256"] = _hash(payload)
    return by_symbol, payload


def _assert_decisions_preserved(original: Sequence[Mapping[str, Any]],
                                replayed: Sequence[Mapping[str, Any]], label: str) -> None:
    if len(original) != len(replayed):
        raise RuntimeReplayError(f"{label} replay 决策数变化")
    for index, (before, after) in enumerate(zip(original, replayed)):
        diffs = [field for field in _REPLAY_DECISION_FIELDS
                 if before.get(field) != after.get(field)]
        if diffs:
            raise RuntimeReplayError(
                f"{label} replay 改变不可改决策字段 index={index}, fields={diffs}")


def _stable_preflight(value: Mapping[str, Any]) -> Dict[str, Any]:
    # UTC day and scratch ledger path are invocation diagnostics, not replay
    # calculation inputs.  Keep the guards that establish the offline route.
    return {key: value.get(key) for key in (
        "anchor_ok", "prereg_frozen_at", "paradigm", "grid_cells",
        "quota_check_skipped", "quota_check_skipped_reason", "quota_ok_for_marking",
    )}


def _stable_bearing(payload: Mapping[str, Any]) -> Dict[str, Any]:
    stable = {key: payload.get(key) for key in (
        "round_decision_ts", "executor", "n_decisions", "portfolio_check",
        "actual_start_settlement", "book", "book_x2_cost", "mark_to_market",
        "nav_point", "rejected_evidence", "decisions", "determinism",
        "gold_probe_output", "seed_semantics", "seed_quantile_caliber", "alerts",
        "verdict", "note",
    )}
    stable["preflight"] = _stable_preflight(payload.get("preflight") or {})
    return stable


def _stable_control(payload: Mapping[str, Any]) -> Dict[str, Any]:
    stable = {key: payload.get(key) for key in (
        "round_decision_ts", "executor", "executor_note", "symbols_fetched",
        "quote_calls_this_round", "quote_calls_if_naive_per_cell", "bars_injected",
        "n_cells_evaluated", "n_cells_frozen_grid", "cells_missing",
        "cells_no_rebalance", "n_decisions", "cells", "rejected_evidence",
        "determinism", "gold_probe_output", "seed_semantics",
        "seed_quantile_caliber", "alerts", "verdict", "note",
    )}
    stable["preflight"] = _stable_preflight(payload.get("preflight") or {})
    return stable


def _stable_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: report.get(key) for key in (
        "control_of_round", "decision_ts", "bearing_path", "control_path",
        "shared_quote_snapshot", "control_registered_trials", "verdict", "note",
        "compared_cell", "control_cells_evaluated", "control_quote_calls",
        "book_comparison", "decision_set_comparison", "identical",
        "book_equivalence_exercised", "may_take_over", "take_over_note",
        "control_error", "control_error_note",
    ) if key in report}


def _field_rows(left: Any, right: Any, path: str = "", *,
                left_label: str = "bearing", right_label: str = "control"
                ) -> List[Dict[str, Any]]:
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        left_map = left if isinstance(left, Mapping) else {}
        right_map = right if isinstance(right, Mapping) else {}
        rows = []
        for key in sorted(set(left_map) | set(right_map)):
            child = f"{path}.{key}" if path else str(key)
            rows.extend(_field_rows(left_map.get(key), right_map.get(key), child,
                                    left_label=left_label, right_label=right_label))
        return rows
    if isinstance(left, list) or isinstance(right, list):
        left_list = left if isinstance(left, list) else []
        right_list = right if isinstance(right, list) else []
        rows = []
        for index in range(max(len(left_list), len(right_list))):
            child = f"{path}[{index}]"
            rows.extend(_field_rows(left_list[index] if index < len(left_list) else None,
                                    right_list[index] if index < len(right_list) else None,
                                    child, left_label=left_label, right_label=right_label))
        return rows
    return [{"field": path, left_label: left, right_label: right,
             "identical": left == right}]


def _runtime_view(payload: Mapping[str, Any]) -> Dict[str, Any]:
    book = payload.get("book") or {}
    return {
        "book": {field: book.get(field) for field in _BOOK_FIELDS},
        "mark_to_market": payload.get("mark_to_market"),
        "nav_point": payload.get("nav_point"),
        "actual_start_settlement": payload.get("actual_start_settlement"),
        "portfolio_check": payload.get("portfolio_check"),
    }


def _settlement_view(cell: Mapping[str, Any], bars: Mapping[str, Sequence[DailyBar]]) -> Dict[str, Any]:
    points = cell.get("nav_series") or []
    latest = points[-1] if points else {}
    as_of = latest.get("as_of")
    positions = {}
    for symbol, shares in sorted((cell.get("shares") or {}).items()):
        bar = next((item for item in reversed(bars.get(symbol) or []) if item.date <= as_of), None)
        if bar is None:
            raise RuntimeReplayError(f"SETTLEMENT 对账缺 {symbol}@<={as_of} 的归档 close")
        positions[symbol] = {"qty": shares, "price": bar.close, "price_date": bar.date,
                             "value": shares * bar.close}
    market_value = sum(item["value"] for item in positions.values())
    return {
        "book": {field: (cell.get(field) if field != "cost_rate_per_side" else
                          (cell.get("rebalance_provenance") or {}).get("cost_rate_per_side"))
                 for field in _BOOK_FIELDS},
        "mark_to_market": {"as_of": as_of, "positions": positions,
                           "market_value": market_value,
                           "price_source": "alphavantage:TIME_SERIES_DAILY (source trade dates)"},
        "nav_point": {"as_of": as_of, "nav": latest.get("nav"),
                      "nav_start": cell.get("nav_start")},
    }


def _settlement_reconciliation(runtime_payload: Mapping[str, Any],
                               settlement_cell: Mapping[str, Any],
                               bars: Mapping[str, Sequence[DailyBar]]) -> Dict[str, Any]:
    runtime = _runtime_view(runtime_payload)
    derived = _settlement_view(settlement_cell, bars)
    # Settlement has no x2-cost nav field and no decision-time portfolio block;
    # compare only fields represented on both sides, and state the exclusions.
    runtime = {"book": runtime["book"], "mark_to_market": runtime["mark_to_market"],
               "nav_point": {key: (runtime["nav_point"] or {}).get(key)
                             for key in ("as_of", "nav", "nav_start")}}
    rows = _field_rows(runtime, derived, left_label="runtime",
                       right_label="derived_settlement")
    return {
        "status": "identical" if all(row["identical"] for row in rows) else "differences_found",
        "fields": rows,
        "diffs": [row for row in rows if not row["identical"]],
        "not_compared": ["runtime.book_x2_cost", "runtime.nav_point.nav_x2_cost",
                         "runtime.actual_start_settlement", "runtime.portfolio_check",
                         "settlement.turnover_notional", "settlement.sequence",
                         "settlement.bar_provenance"],
        "note": ("差异预期如实记录：runtime executor 从 START_NAV 独立建仓；派生结算承接前段持仓，"
                 "按换仓 open 财富和双侧 turnover 计费。对账不替代真实 runtime 比较。"),
    }


def _runtime_sources() -> Dict[str, str]:
    here = Path(__file__).resolve()
    package = here.parent
    quote_source = package.parent / "events" / "datafetch" / "quotes_api.py"
    paths = [here, package / "parallel_control.py", package / "run_round.py",
             package / "multi_book.py", package / "decision_chain.py",
             package / "price_bridge.py", package / "quote_bridge.py",
             package / "rebalance_policy.py", package / "bar_archive.py", quote_source]
    return {str(path.relative_to(here.parents[3])): _file_sha256(path) for path in paths}


def _snapshot_unsigned_after_execution(snapshot: Mapping[str, Any],
                                       bars: Mapping[str, Sequence[DailyBar]]) -> Dict[str, Any]:
    after = dict(snapshot)
    after.pop("content_sha256", None)
    after["bars"] = sorted(
        ({field: getattr(bar, field, None) for field in _BAR_FIELDS}
         for symbol in sorted(bars) for bar in bars[symbol]),
        key=lambda item: (item["symbol"], item["date"]))
    after["n_bars"] = len(after["bars"])
    return after


def _distinct_decision_sets(control: Mapping[str, Any]) -> int:
    fingerprints = set()
    for block in (control.get("cells") or {}).values():
        normalized = []
        for decision in block.get("decisions") or []:
            item = dict(decision)
            item.pop("seed", None)
            normalized.append(item)
        fingerprints.add(_hash(sorted(normalized, key=lambda item: item["symbol"])))
    return len(fingerprints)


def verify_runtime_replay_artifact(path: str | Path) -> Dict[str, Any]:
    artifact = _read_json(Path(path))
    if artifact.get("schema") != RUNTIME_REPLAY_SCHEMA:
        raise RuntimeReplayError("runtime replay artifact schema 非法")
    supplied = artifact.get("content_sha256")
    unsigned = dict(artifact)
    unsigned.pop("content_sha256", None)
    actual = _hash(unsigned)
    if supplied != actual:
        raise RuntimeReplayError(
            f"runtime replay artifact 内容哈希不匹配: expected={supplied}, actual={actual}")
    snapshot = artifact.get("shared_bar_snapshot") or {}
    snapshot_supplied = snapshot.get("content_sha256")
    snapshot_unsigned = dict(snapshot)
    snapshot_unsigned.pop("content_sha256", None)
    if snapshot_supplied != _hash(snapshot_unsigned):
        raise RuntimeReplayError("shared bar snapshot 内容哈希不匹配")
    manifest = artifact.get("input_manifest") or {}
    manifest_supplied = manifest.get("content_sha256")
    manifest_unsigned = dict(manifest)
    manifest_unsigned.pop("content_sha256", None)
    if manifest_supplied != _hash(manifest_unsigned):
        raise RuntimeReplayError("input manifest 内容哈希不匹配")
    binding = artifact.get("same_shared_bar_snapshot") or {}
    bound_hashes = {binding.get("bearing_argument_content_sha256"),
                    binding.get("control_argument_content_sha256"),
                    binding.get("after_both_executors_content_sha256")}
    if bound_hashes != {snapshot_supplied}:
        raise RuntimeReplayError("两侧 runtime bars 绑定与 shared snapshot 哈希不一致")
    return artifact


def replay_runtime_equivalence(out_dir: str, *, stamp: str = "20260831",
                               settlement_file: str | Path = DEFAULT_SETTLEMENT,
                               expected_content_sha256: str | None = None) -> Dict[str, Any]:
    """Replay both real executors from immutable archive inputs and write evidence."""
    root = Path(out_dir).resolve()
    if stamp != "20260831":
        raise RuntimeReplayError("本工具只补证不可改的 20260831 轮次，拒绝消费新段")
    settlement_path = Path(settlement_file)
    if not settlement_path.is_absolute():
        settlement_path = root / settlement_path
    try:
        settlement_path.resolve().relative_to((root / "derived_settlement").resolve())
    except ValueError as exc:
        raise RuntimeReplayError("SETTLEMENT 对账输入必须来自 reports/derived_settlement") from exc

    archives, resolutions = _archive_inputs(root)
    input_paths = _required_paths(root, stamp, settlement_path, archives, resolutions)
    bearing_original = _read_json(root / f"round_{stamp}.json")
    control_original = _read_json(root / "control_multi_book" / f"round_{stamp}.json")
    old_control = _read_json(root / f"CONTROL_{stamp}.json")
    settlement = verify_settlement_artifact(settlement_path)

    if bearing_original.get("executor") != "single_book" or \
            control_original.get("executor") != "multi_book_v1":
        raise RuntimeReplayError("原始两侧记录不是 single_book / multi_book_v1，拒绝猜执行器")
    if bearing_original.get("book", {}).get("status") != "pending_entry_bar" or \
            any((cell.get("book") or {}).get("status") != "pending_entry_bar"
                for cell in (control_original.get("cells") or {}).values()):
        raise RuntimeReplayError("原始 20260831 记录不再是待补证的 pending_entry_bar 状态")
    if old_control.get("book_equivalence_exercised") is not False or \
            old_control.get("may_take_over") is not False:
        raise RuntimeReplayError("原 CONTROL 的未检验状态与本补证对象不符")
    if bearing_original.get("round_decision_ts") != control_original.get("round_decision_ts"):
        raise RuntimeReplayError("两侧原始 decision_ts 不同，不能 replay 为同轮对照")

    proposals = [_proposal(item, include_cell=True)
                 for item in bearing_original.get("decisions") or []]
    cells = _cells(control_original)
    symbols = sorted({"SPY"} | {item["symbol"] for item in proposals} |
                     {item["symbol"] for cell in cells for item in cell["proposals"]})
    bars, snapshot = _bar_snapshot(root, symbols)
    snapshot_before = snapshot["content_sha256"]

    config = load_prereg()
    probe = {"model": (bearing_original.get("determinism") or {}).get("model", ""),
             "output": bearing_original.get("gold_probe_output", "")}
    baseline_source = _resolve(BASELINE_PATH).resolve()
    probe_source = _resolve(GOLD_PROBE_PATH).resolve()
    prereg_source = _resolve("qlab/llm_paper_prereg.json").resolve()
    anchor_source = _resolve("qlab/freeze_anchor.json").resolve()
    protected_paths = input_paths + [prereg_source, anchor_source, baseline_source, probe_source]
    source_hashes_before = {_relative(path, root): _file_sha256(path)
                            for path in protected_paths}
    manifest_files = [_manifest_entry(path, root) for path in input_paths]
    external_inputs = {
        "preregistration": {"file": _relative(prereg_source, root),
                            "file_sha256": _file_sha256(prereg_source)},
        "freeze_anchor": {"file": _relative(anchor_source, root),
                          "file_sha256": _file_sha256(anchor_source)},
        "determinism_baseline": {"file": _relative(baseline_source, root),
                                 "file_sha256": _file_sha256(baseline_source)},
        "gold_probe": {"file": _relative(probe_source, root),
                       "file_sha256": _file_sha256(probe_source)},
    }
    runtime_sources = _runtime_sources()
    input_manifest: Dict[str, Any] = {
        "files": manifest_files,
        "external_inputs": external_inputs,
        "runtime_source_sha256s": runtime_sources,
        "shared_bar_snapshot_content_sha256": snapshot_before,
    }
    input_manifest["content_sha256"] = _hash(input_manifest)

    old_quota = os.environ.get("QLAB_AV_QUOTA_LEDGER")
    old_baseline = os.environ.get(BASELINE_ENV)
    try:
        with tempfile.TemporaryDirectory(prefix="llm-paper-runtime-replay-") as scratch_name:
            scratch = Path(scratch_name)
            baseline_copy = scratch / "determinism_baseline.json"
            shutil.copy2(baseline_source, baseline_copy)
            os.environ["QLAB_AV_QUOTA_LEDGER"] = str(scratch / "av_quota.jsonl")
            os.environ[BASELINE_ENV] = str(baseline_copy)
            report = run_parallel_control(
                proposals=proposals, cells=cells,
                decision_ts=bearing_original["round_decision_ts"], probe=probe,
                out_dir=str(scratch / "bearing"), control_dir=str(scratch / "control"),
                cfg=config, rejected_evidence=bearing_original.get("rejected_evidence") or [],
                register_trials=False, bars=bars)
            bearing_replay = report["bearing_payload"]
            control_replay = _read_json(scratch / "control" / f"round_{stamp}.json")
    finally:
        if old_quota is None:
            os.environ.pop("QLAB_AV_QUOTA_LEDGER", None)
        else:
            os.environ["QLAB_AV_QUOTA_LEDGER"] = old_quota
        if old_baseline is None:
            os.environ.pop(BASELINE_ENV, None)
        else:
            os.environ[BASELINE_ENV] = old_baseline

    snapshot_after_payload = _snapshot_unsigned_after_execution(snapshot, bars)
    snapshot_after_hash = _hash(snapshot_after_payload)
    if snapshot_after_hash != snapshot_before:
        raise RuntimeReplayError("执行器改变了注入 bars 快照，拒绝写入混合证据")

    _assert_decisions_preserved(bearing_original.get("decisions") or [],
                                bearing_replay.get("decisions") or [], "single_book")
    for cid, original_cell in (control_original.get("cells") or {}).items():
        replay_cell = (control_replay.get("cells") or {}).get(cid)
        if replay_cell is None:
            raise RuntimeReplayError(f"multi_book replay 缺格 {cid}")
        _assert_decisions_preserved(original_cell.get("decisions") or [],
                                    replay_cell.get("decisions") or [], f"multi_book/{cid}")

    compared = report.get("compared_cell")
    control_cell = (control_replay.get("cells") or {}).get(compared) or {}
    field_rows = _field_rows(_runtime_view(bearing_replay), _runtime_view(control_cell))
    runtime_identical = bool(field_rows and all(row["identical"] for row in field_rows)
                             and report.get("identical") is True)
    all_control_filled = all((cell.get("book") or {}).get("status") == "filled"
                             for cell in (control_replay.get("cells") or {}).values())
    if bearing_replay.get("book", {}).get("status") != "filled" or not all_control_filled:
        raise RuntimeReplayError("真实执行器 replay 未把两侧 20260831 book 推进到 filled，停止补证")

    settlement_round = next((item for item in settlement.get("rounds") or []
                             if str(item.get("round")) == stamp), None)
    settlement_cell = ((settlement_round or {}).get("cells") or {}).get(compared)
    if settlement_cell is None:
        raise RuntimeReplayError(f"SETTLEMENT 缺承载格 {stamp}/{compared}")
    bearing_reconciliation = _settlement_reconciliation(bearing_replay, settlement_cell, bars)
    control_reconciliation = _settlement_reconciliation(control_cell, settlement_cell, bars)

    source_hashes_after = {_relative(path, root): _file_sha256(path)
                           for path in protected_paths}
    runtime_sources_after = _runtime_sources()
    if source_hashes_after != source_hashes_before or runtime_sources_after != runtime_sources:
        raise RuntimeReplayError("replay 期间输入文件发生变化，拒绝写入混合工件")

    per_grid = {}
    for cid, block in (control_replay.get("cells") or {}).items():
        if cid == compared:
            per_grid[cid] = {"bearing_peer": True,
                             "bearing_status": bearing_replay["book"]["status"],
                             "control_status": block["book"]["status"],
                             "passed": runtime_identical,
                             "comparison_scope": "real executor runtime outputs"}
        else:
            per_grid[cid] = {"bearing_peer": False,
                             "control_status": block["book"]["status"],
                             "passed": None,
                             "reason": "not_comparable_no_bearing_cell"}

    payload: Dict[str, Any] = {
        "schema": RUNTIME_REPLAY_SCHEMA,
        "implementation_version": RUNTIME_REPLAY_IMPLEMENTATION_VERSION,
        "implementation_source_sha256": _file_sha256(Path(__file__).resolve()),
        "runtime_source_bundle_sha256": _hash(runtime_sources),
        "input_manifest": input_manifest,
        "reading_kind": "equivalence_artifact",
        "is_performance_reading": False,
        "is_acceptance_reading": False,
        "round": stamp,
        "original_state": {
            "bearing_book_status": bearing_original["book"]["status"],
            "control_book_statuses": sorted({cell["book"]["status"]
                                             for cell in control_original["cells"].values()}),
            "book_equivalence_exercised": old_control["book_equivalence_exercised"],
            "may_take_over": old_control["may_take_over"],
        },
        "runtime_entrypoints": {
            "orchestrator": "qlab.llm_paper.parallel_control.run_parallel_control",
            "bearing": "qlab.llm_paper.run_round.run_round",
            "control": "qlab.llm_paper.multi_book.run_round_multi",
            "network_calls": 0,
            "register_trials": False,
            "source_inputs_read_only": True,
        },
        "shared_bar_snapshot": snapshot,
        "same_shared_bar_snapshot": {
            "status": "passed",
            "snapshot_content_hash_recorded": True,
            "bearing_argument_content_sha256": snapshot_before,
            "control_argument_content_sha256": snapshot_before,
            "after_both_executors_content_sha256": snapshot_after_hash,
            "same_object_injected_by_orchestrator": True,
            "input_unchanged_after_execution": snapshot_before == snapshot_after_hash,
        },
        "runtime_outputs": {
            "bearing": _stable_bearing(bearing_replay),
            "control": _stable_control(control_replay),
        },
        "runtime_comparison": {
            "compared_cell": compared,
            "status": "passed" if runtime_identical else "mismatch",
            "book_equivalence_exercised": bool(report.get("book_equivalence_exercised")),
            "fields": field_rows,
            "diffs": [row for row in field_rows if not row["identical"]],
            "parallel_control_report": _stable_report(report),
            "per_grid": per_grid,
        },
        "derived_settlement_reconciliation": {
            "artifact": {"file": _relative(settlement_path, root),
                         "content_sha256": settlement["content_sha256"],
                         "implementation_source_sha256":
                             (settlement.get("calculation_identity") or {}).get(
                                 "implementation_source_sha256")},
            "bearing": bearing_reconciliation,
            "control": control_reconciliation,
            "role": "auxiliary_reconciliation_not_runtime_equivalence_evidence",
        },
        "source_input_immutability": {
            "status": "passed",
            "files_before_sha256": source_hashes_before,
            "files_after_sha256": source_hashes_after,
        },
        "conclusions": {
            "executor_behavior_equivalence": (
                "established_for_single_overlapping_cell" if runtime_identical else "not_established"),
            "overlapping_cells": 1,
            "control_cells_without_bearing_peer": len(control_replay["cells"]) - 1,
            "effective_distinct_decision_sets": _distinct_decision_sets(control_original),
            "must_not_claim_seed_robustness": True,
            "may_take_over": bool(report.get("may_take_over")),
            "may_take_over_semantics": "existing parallel_control runtime definition; not switch authority",
            "switch_authorized": False,
            "required_authority": "吏部书面核收",
        },
        "not_authorized": ["executor_switch", "new_segment_consumption",
                           "acceptance_performance_claim", "investment_conclusion",
                           "50_20_claim"],
        "verdict": None,
        "note": ("非验收口径。只补 20260831 唯一重叠格真实 executor runtime 行为证据；"
                 "九格无 bearing peer，十格只有两个不同决策集，不证明 seed 稳健性。"),
    }
    payload["content_sha256"] = _hash(payload)
    if expected_content_sha256 is not None and expected_content_sha256 != payload["content_sha256"]:
        raise RuntimeReplayError(
            f"runtime replay content mismatch: expected={expected_content_sha256}, "
            f"actual={payload['content_sha256']}")

    directory = root / ARTIFACT_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"RUNTIME_EQUIVALENCE_{stamp}_{payload['content_sha256'][:16]}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        existing = verify_runtime_replay_artifact(path)
        if _canonical(existing) != _canonical(payload):
            raise RuntimeReplayError("runtime replay 文件名冲突且内容不同")
    return {"artifact_file": str(path), "content_sha256": payload["content_sha256"],
            "file_sha256": _file_sha256(path), "input_manifest_sha256":
                input_manifest["content_sha256"],
            "shared_bar_snapshot_content_sha256": snapshot_before,
            "implementation_source_sha256": payload["implementation_source_sha256"],
            "runtime_source_bundle_sha256": payload["runtime_source_bundle_sha256"],
            "payload": payload}

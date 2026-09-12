"""Frozen M/W/F v2 orchestration for the LLM forward-paper experiment.

This module is deliberately additive.  It does not rewrite weekly-v1 records
and it does not replace the authorised ``single_book`` executor.  Its job is
to make planned-round identity, per-cell coalescing, idempotency, rebalance
costs, archive provenance and version-isolated settlement mechanically
testable before the platform cron is changed.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.gate.filelock import atomic_write_text, state_lock


EXPERIMENT_VERSION = "llm_paper_forward_mwf_v2"
LEGACY_VERSION = "llm_paper_forward_weekly_v1"
ACTIVATION_UTC = "2026-09-14T11:00:00Z"
ET = ZoneInfo("America/New_York")
UTC = timezone.utc
GRID = (
    "seed11×pv1_baseline", "seed11×pv2_riskaware",
    "seed22×pv1_baseline", "seed22×pv2_riskaware",
    "seed33×pv1_baseline", "seed33×pv2_riskaware",
    "seed44×pv1_baseline", "seed44×pv2_riskaware",
    "seed55×pv1_baseline", "seed55×pv2_riskaware",
)
ROUND_SCHEMA = "llm_paper_planned_round/v2"
EXECUTION_SCHEMA = "llm_paper_execution/v2"
SETTLEMENT_SCHEMA = "llm_paper_settlement/v2"
COST_RATE = 0.001
COST_MODEL_VERSION = "moomoo_retail_x1_10bps_per_turnover_v1"
READING_KINDS = {"equivalence_artifact", "lower_bound", "acceptance"}
ACCEPTANCE_EQUITY_SOURCE = "OpenD K_DAY qfq return_series"
ACCEPTANCE_CASH_SOURCE = "BIL total_return_series"
V2_PREREG_PATH = _REPO_ROOT / "qlab" / "llm_paper_prereg_mwf_v2.json"


class FrozenContractError(ValueError):
    """Input would violate the frozen v2 protocol."""


class IdempotencyConflict(FrozenContractError):
    """The same idempotency key was presented with different content."""

    code = "IDEMPOTENCY_CONFLICT"


class BatchQuotaExceeded(FrozenContractError):
    """The entire quote batch must be refused before any vendor call."""


class ArtifactConflict(FrozenContractError):
    """An immutable artifact path already contains different bytes."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False,
                      default=str).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_v2_preregistration(path: str | Path = V2_PREREG_PATH) -> dict[str, Any]:
    """Load the additive freeze and prove the inherited v1 artifact is untouched."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    inherited = payload.get("inherited_freeze") or {}
    inherited_path = _REPO_ROOT / str(inherited.get("file") or "")
    checks = {
        "schema": payload.get("schema") == "llm_paper_preregistration/v2",
        "version": payload.get("experiment_version") == EXPERIMENT_VERSION,
        "activation": (payload.get("activation") or {}).get(
            "scheduled_at_utc_inclusive") == ACTIVATION_UTC,
        "schedule": (payload.get("schedule") or {}).get("cron") == "0 7 * * 1,3,5",
        "timezone": (payload.get("schedule") or {}).get("timezone") == "America/New_York",
        "executor": (payload.get("executor") or {}).get("name") == "single_book",
        "simulate": (payload.get("executor") or {}).get("mode") == "SIMULATE",
        "switch_forbidden": (payload.get("executor") or {}).get("switch_authorized") is False,
        "grid": tuple(inherited.get("family_grid") or ()) == GRID,
        "n_trials_total": inherited.get("n_trials_total") == 10,
        "cost": inherited.get("cost_per_turnover") == COST_RATE,
        "legacy_hash": (inherited_path.is_file() and
                        file_sha256(inherited_path) == inherited.get("sha256")),
        "legacy_rewrite_forbidden": inherited.get("rewrite_allowed") is False,
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise FrozenContractError(f"v2 preregistration integrity failed: {failed}")
    return payload


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    if parsed.tzinfo is None:
        raise FrozenContractError(f"timestamp must include timezone: {value!r}")
    return parsed.astimezone(UTC)


def utc_text(value: Any) -> str:
    return _dt(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def planned_round_key(scheduled_at: Any,
                      experiment_version: str = EXPERIMENT_VERSION) -> tuple[str, str]:
    return experiment_version, utc_text(scheduled_at)


def decision_key(scheduled_at: Any, cell_id: str,
                 experiment_version: str = EXPERIMENT_VERSION
                 ) -> tuple[tuple[str, str], str]:
    return planned_round_key(scheduled_at, experiment_version), str(cell_id)


def execution_key(actual_start_bar: Any, cell_id: str,
                  experiment_version: str = EXPERIMENT_VERSION) -> tuple[str, str, str]:
    return experiment_version, utc_text(actual_start_bar), str(cell_id)


def settlement_key(*, execution: Sequence[Any], mark_date: str, reading_kind: str,
                   round_hashes: Sequence[str], archive_hashes: Sequence[str],
                   resolution_hashes: Sequence[str],
                   cost_model_version: str = COST_MODEL_VERSION) -> tuple[Any, ...]:
    if reading_kind not in READING_KINDS:
        raise FrozenContractError(f"unknown reading_kind={reading_kind!r}")
    hashes = [*round_hashes, *archive_hashes, *resolution_hashes]
    if not all(_is_sha256(value) for value in hashes):
        raise FrozenContractError("settlement provenance hashes must be lowercase sha256")
    return (tuple(execution), str(mark_date), reading_kind,
            tuple(sorted(round_hashes)), tuple(sorted(archive_hashes)),
            tuple(sorted(resolution_hashes)), cost_model_version)


def _key_json(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_key_json(item) for item in value]
    if isinstance(value, list):
        return [_key_json(item) for item in value]
    return value


@dataclass(frozen=True)
class ClaimResult:
    status: str
    kind: str
    key: Any
    content_sha256: str

    @property
    def is_noop(self) -> bool:
        return self.status == "no_op"


class IdempotencyStore:
    """Cross-process, append-logical idempotency registry.

    Claims are written before any external fetch or fee-bearing action.  A
    repeated identical delivery therefore stops at this registry.  A changed
    delivery for the same key is rejected without replacing the first claim.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FrozenContractError(
                    f"idempotency ledger corrupt at line {number}: {exc}") from exc
            unsigned = dict(record)
            supplied = unsigned.pop("record_sha256", None)
            if supplied != content_sha256(unsigned):
                raise FrozenContractError(
                    f"idempotency ledger record hash mismatch at line {number}")
            records.append(record)
        return records

    @staticmethod
    def _identity(kind: str, key: Any) -> str:
        return content_sha256({"kind": kind, "key": _key_json(key)})

    def lookup(self, kind: str, key: Any) -> dict[str, Any] | None:
        identity = self._identity(kind, key)
        return next((record for record in self._records()
                     if record["identity_sha256"] == identity), None)

    def claim(self, kind: str, key: Any, payload: Any) -> ClaimResult:
        return self.claim_many([(kind, key, payload)])[0]

    def claim_many(self, claims: Sequence[tuple[str, Any, Any]]) -> list[ClaimResult]:
        """Atomically preflight every key before appending any new claim."""
        prepared = []
        seen_batch: dict[str, str] = {}
        for kind, key, payload in claims:
            digest = payload if isinstance(payload, str) and _is_sha256(payload) \
                else content_sha256(payload)
            identity = self._identity(kind, key)
            if identity in seen_batch and seen_batch[identity] != digest:
                raise IdempotencyConflict(
                    f"{IdempotencyConflict.code}: duplicate key in batch has different hash")
            seen_batch[identity] = digest
            prepared.append((str(kind), key, digest, identity))

        with state_lock(str(self.path)):
            records = self._records()
            by_identity = {record["identity_sha256"]: record for record in records}
            results: list[ClaimResult] = []
            new_records: list[dict[str, Any]] = []
            for kind, key, digest, identity in prepared:
                old = by_identity.get(identity)
                if old is not None and old["content_sha256"] != digest:
                    raise IdempotencyConflict(
                        f"{IdempotencyConflict.code}: kind={kind} key={_key_json(key)!r} "
                        f"existing={old['content_sha256']} incoming={digest}")
                if old is not None:
                    results.append(ClaimResult("no_op", kind, key, digest))
                    continue
                record = {"schema": "llm_paper_idempotency_claim/v1", "kind": kind,
                          "key": _key_json(key), "identity_sha256": identity,
                          "content_sha256": digest}
                record["record_sha256"] = content_sha256(record)
                new_records.append(record)
                by_identity[identity] = record
                results.append(ClaimResult("claimed", kind, key, digest))
            if new_records:
                text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                               for record in records + new_records)
                atomic_write_text(str(self.path), text)
            return results


def write_hashed_artifact(path: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Write one immutable, content-hashed JSON artifact or reuse identical bytes."""
    target = Path(path)
    materialized = dict(payload)
    materialized.pop("content_sha256", None)
    materialized["content_sha256"] = content_sha256(materialized)
    with state_lock(str(target)):
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if _canonical(existing) != _canonical(materialized):
                raise ArtifactConflict(f"immutable artifact collision: {target.name}")
            return existing
        atomic_write_text(
            str(target), json.dumps(materialized, ensure_ascii=False,
                                    sort_keys=True, indent=2) + "\n")
    return materialized


def verify_hashed_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != content_sha256(unsigned):
        raise ArtifactConflict(f"artifact content hash mismatch: {Path(path).name}")
    return payload


def read_round_compat(path: str | Path) -> dict[str, Any]:
    """Read a v2 or legacy round without ever writing compatibility fields back."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    copy = dict(payload)
    if not copy.get("experiment_version"):
        copy["experiment_version"] = LEGACY_VERSION
        copy["scheduled_at"] = None
        copy["compatibility"] = "legacy_fields_supplied_in_memory_only"
    return copy


def validate_schedule_slot(scheduled_at: Any) -> dict[str, str]:
    when = _dt(scheduled_at)
    if when < _dt(ACTIVATION_UTC):
        raise FrozenContractError(
            f"v2 scheduled_at precedes activation boundary {ACTIVATION_UTC}")
    local = when.astimezone(ET)
    if local.weekday() not in {0, 2, 4} or (local.hour, local.minute, local.second) != (7, 0, 0):
        raise FrozenContractError(
            "v2 scheduled_at must be a natural M/W/F 07:00 America/New_York slot")
    return {"scheduled_at_utc": utc_text(when), "scheduled_at_et": local.isoformat()}


def intended_open(scheduled_at: Any) -> str:
    local = _dt(scheduled_at).astimezone(ET)
    return utc_text(local.replace(hour=9, minute=30, second=0, microsecond=0))


def resolve_actual_start(scheduled_at: Any, observed_market_opens: Sequence[Any]) -> dict[str, Any]:
    """Resolve the first observed open on/after the intended day; never predict holidays."""
    intended = _dt(intended_open(scheduled_at))
    available = sorted(_dt(item) for item in observed_market_opens if _dt(item) >= intended)
    if not available:
        return {"status": "pending_actual_start", "intended_start": utc_text(intended),
                "actual_start": None, "rolled": None, "rolled_days": None}
    actual = available[0]
    rolled_days = (actual.astimezone(ET).date() - intended.astimezone(ET).date()).days
    return {"status": "resolved", "intended_start": utc_text(intended),
            "actual_start": utc_text(actual), "rolled": rolled_days > 0,
            "rolled_days": rolled_days}


def _portfolio_status(weights: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {str(symbol): float(weight) for symbol, weight in weights.items()}
    finite = all(math.isfinite(weight) for weight in normalized.values())
    negative = sorted(symbol for symbol, weight in normalized.items() if weight < 0)
    over = sorted(symbol for symbol, weight in normalized.items() if weight > 0.1 + 1e-12)
    gross = math.fsum(normalized.values()) if finite else math.inf
    ok = finite and not negative and not over and gross <= 1.0 + 1e-12
    return {"ok": ok, "gross": gross, "negative": negative,
            "single_name_over_cap": over, "gross_cap": 1.0,
            "single_name_cap": 0.1, "leverage_cap": 1.0}


def normalize_cell_decision(cell_id: str, raw: Mapping[str, Any], *,
                            scheduled_at: Any) -> dict[str, Any]:
    if cell_id not in GRID:
        raise FrozenContractError(f"cell {cell_id!r} is outside the frozen 10-cell family")
    evidence = _dt(raw["evidence_available_utc"])
    decision = _dt(raw["decision_ts"])
    effective = _dt(raw.get("effective_from") or intended_open(scheduled_at))
    slot = _dt(scheduled_at)
    if decision > _dt(intended_open(scheduled_at)):
        raise FrozenContractError("decision arrived after market open; record a technical gap")
    if not evidence <= decision <= effective:
        raise FrozenContractError(
            "timing violation: evidence_available_utc <= decision_ts <= effective_from")
    if decision < slot:
        raise FrozenContractError("decision_ts precedes its natural scheduled delivery")
    weights = {str(symbol): float(weight)
               for symbol, weight in (raw.get("target_weights") or {}).items()}
    portfolio = _portfolio_status(weights)
    status = "legal" if portfolio["ok"] else "portfolio_violation"
    body = {
        "cell_id": cell_id,
        "decision_key": _key_json(decision_key(scheduled_at, cell_id)),
        "decision_status": status,
        "evidence_available_utc": utc_text(evidence),
        "decision_ts": utc_text(decision),
        "effective_from": utc_text(effective),
        "target_weights": weights,
        "portfolio_check": portfolio,
        "evidence_refs": list(raw.get("evidence_refs") or []),
        "source_time_utc": raw.get("source_time_utc"),
    }
    body["decision_content_sha256"] = content_sha256(body)
    return body


def quota_preflight(*, archive_required: Iterable[str], decision_required: Iterable[str],
                    benchmark: str = "SPY", other_calls: int = 0,
                    limit: int = 25) -> dict[str, Any]:
    """Preflight the whole UTC-day union.  Nothing is split or dropped."""
    if other_calls < 0:
        raise FrozenContractError("other_calls cannot be negative")
    symbols = sorted(set(archive_required) | set(decision_required) | {benchmark})
    total = len(symbols) + int(other_calls)
    result = {"require_full_batch": True, "provider_function": "TIME_SERIES_DAILY",
              "outputsize": "compact", "symbols": symbols, "symbol_calls": len(symbols),
              "other_calls": int(other_calls), "total_calls": total, "limit": int(limit),
              "utc_ledger_shared": True}
    if total > limit:
        raise BatchQuotaExceeded(
            f"whole batch refused before fetch: {total}>{limit}; no symbol drop/split/key rotation")
    return result


def plan_snapshot_reuse(*, archive_required: Iterable[str], decision_required: Iterable[str],
                        snapshot: Mapping[str, Any] | None, required_trade_date: str,
                        benchmark: str = "SPY", other_calls: int = 0) -> dict[str, Any]:
    quota = quota_preflight(archive_required=archive_required,
                            decision_required=decision_required, benchmark=benchmark,
                            other_calls=other_calls)
    required = set(quota["symbols"])
    reused: set[str] = set()
    provenance = None
    if snapshot:
        sha = str(snapshot.get("archive_content_sha256") or "")
        capture = str(snapshot.get("capture_utc") or "")
        trade_date = str(snapshot.get("latest_trade_date") or "")
        symbols = {str(item) for item in snapshot.get("symbols") or []}
        if not _is_sha256(sha) or not capture or trade_date != required_trade_date:
            raise FrozenContractError(
                "snapshot reuse requires capture time, archive hash and exact latest trade date")
        _dt(capture)
        reused = required & symbols
        provenance = {"capture_utc": utc_text(capture), "latest_trade_date": trade_date,
                      "archive_content_sha256": sha, "symbols": sorted(reused)}
    return {**quota, "reused_symbols": sorted(reused),
            "fetch_symbols": sorted(required - reused), "snapshot_provenance": provenance}


def _round_filename(scheduled_at: Any) -> str:
    return "planned_" + _dt(scheduled_at).strftime("%Y%m%dT%H%M%SZ") + ".json"


def _gap_payload(*, scheduled_at: Any, delivery_hash: str, reason: str) -> dict[str, Any]:
    return {"schema": ROUND_SCHEMA, "experiment_version": EXPERIMENT_VERSION,
            "scheduled_at": utc_text(scheduled_at),
            "planned_round_key": _key_json(planned_round_key(scheduled_at)),
            "delivery_content_sha256": delivery_hash, "status": "technical_gap",
            "gap_reason": str(reason), "cells": {}, "n_trials_total": 10,
            "backfill_allowed": False, "actual_start": None}


def ingest_planned_round(*, scheduled_at: Any, delivery_payload: Mapping[str, Any],
                         state_dir: str | Path,
                         fetch_snapshot: Callable[[Sequence[str]], Mapping[str, Any]],
                         build_cells: Callable[[Mapping[str, Any]], Mapping[str, Mapping[str, Any]]],
                         archive_required: Iterable[str], decision_required: Iterable[str],
                         required_trade_date: str, other_calls: int = 0,
                         reusable_snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Persist one natural platform delivery, or one immutable technical gap.

    The planned key is claimed before the callback that can touch the network.
    Thus a duplicate platform delivery cannot take data or charge quota twice.
    """
    load_v2_preregistration()
    validate_schedule_slot(scheduled_at)
    root = Path(state_dir)
    rounds_dir = root / "rounds"
    registry = IdempotencyStore(root / "idempotency.jsonl")
    delivery_hash = content_sha256(delivery_payload)
    try:
        claim = registry.claim("planned_round_key", planned_round_key(scheduled_at), delivery_hash)
    except IdempotencyConflict as exc:
        return {"status": IdempotencyConflict.code, "whole_round_refused": True,
                "scheduled_at": utc_text(scheduled_at), "reason": str(exc)}
    if claim.is_noop:
        target = rounds_dir / _round_filename(scheduled_at)
        return {"status": "no_op", "no_fetch": True, "no_fee": True,
                "no_cost": True, "no_ledger_write": True,
                "artifact": (verify_hashed_artifact(target) if target.exists() else None)}

    try:
        quote_plan = plan_snapshot_reuse(
            archive_required=archive_required, decision_required=decision_required,
            snapshot=reusable_snapshot, required_trade_date=required_trade_date,
            other_calls=other_calls)
        snapshot = dict(fetch_snapshot(quote_plan["fetch_symbols"]))
        fetched_symbols = {str(item) for item in snapshot.get("symbols") or
                           (snapshot.get("bars") or {}).keys()}
        missing_fetch = sorted(set(quote_plan["fetch_symbols"]) - fetched_symbols)
        if missing_fetch:
            raise FrozenContractError(
                f"require_full_batch missing symbols: {missing_fetch}; whole round refused")
        if reusable_snapshot:
            reused_bars = dict(reusable_snapshot.get("bars") or {})
            missing_reused = sorted(set(quote_plan["reused_symbols"]) -
                                    {str(item) for item in reused_bars})
            if missing_reused:
                raise FrozenContractError(
                    f"snapshot provenance claims symbols without reusable bars: {missing_reused}")
            fetched_bars = dict(snapshot.get("bars") or {})
            snapshot["bars"] = {**reused_bars, **fetched_bars}
            snapshot["reused_snapshot_provenance"] = quote_plan["snapshot_provenance"]
        raw_cells = dict(build_cells(snapshot))
        normalized: dict[str, dict[str, Any]] = {}
        failures: dict[str, str] = {}
        for cell in GRID:
            if cell not in raw_cells:
                failures[cell] = "no_legal_persisted_decision"
                continue
            try:
                normalized[cell] = normalize_cell_decision(
                    cell, raw_cells[cell], scheduled_at=scheduled_at)
            except (KeyError, TypeError, ValueError) as exc:
                failures[cell] = str(exc)
        if not normalized:
            raise FrozenContractError("no cell produced a legal persisted decision")
        registry.claim_many([
            ("decision_key", decision_key(scheduled_at, cell), block["decision_content_sha256"])
            for cell, block in sorted(normalized.items())
        ])
        payload = {"schema": ROUND_SCHEMA, "experiment_version": EXPERIMENT_VERSION,
                   "scheduled_at": utc_text(scheduled_at),
                   "planned_round_key": _key_json(planned_round_key(scheduled_at)),
                   "delivery_content_sha256": delivery_hash, "status": "persisted",
                   "gap_reason": None, "cells": normalized, "cell_failures": failures,
                   "n_trials_total": 10, "n_evaluated_this_round": len(normalized),
                   "quote_batch": quote_plan,
                   "archive_snapshot": snapshot.get("archive_snapshot"),
                   "executor": "single_book", "mode": "SIMULATE",
                   "verdict": None, "round_nav_point_consumable": False}
    except IdempotencyConflict as exc:
        return {"status": IdempotencyConflict.code, "whole_round_refused": True,
                "scheduled_at": utc_text(scheduled_at), "reason": str(exc)}
    except Exception as exc:
        payload = _gap_payload(scheduled_at=scheduled_at, delivery_hash=delivery_hash,
                               reason=str(exc))
    artifact = write_hashed_artifact(rounds_dir / _round_filename(scheduled_at), payload)
    return {"status": artifact["status"], "artifact": artifact}


def coalesce_rounds(rounds: Sequence[Mapping[str, Any]], *,
                    observed_market_opens: Sequence[Any]) -> dict[str, Any]:
    """Choose the latest legal persisted decision per cell and actual-start bar."""
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    statuses: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for raw in rounds:
        if raw.get("status") != "persisted":
            statuses.append({"planned_round_key": raw.get("planned_round_key"),
                             "status": raw.get("status", "technical_gap")})
            continue
        resolution = resolve_actual_start(raw["scheduled_at"], observed_market_opens)
        for cell, decision in (raw.get("cells") or {}).items():
            if resolution["actual_start"] is None:
                pending.append({"decision_key": decision["decision_key"], **resolution})
                continue
            candidate = {"experiment_version": raw["experiment_version"],
                         "scheduled_at": raw["scheduled_at"], "round_hash": raw["content_sha256"],
                         "cell_id": cell, "decision": dict(decision), **resolution}
            candidates.setdefault((cell, resolution["actual_start"]), []).append(candidate)

    executions: list[dict[str, Any]] = []
    for (cell, actual), group in sorted(candidates.items()):
        ordered = sorted(group, key=lambda item: _dt(item["scheduled_at"]))
        canonical = ordered[-1]
        ekey = execution_key(actual, cell, canonical["experiment_version"])
        for earlier in ordered[:-1]:
            statuses.append({"decision_key": earlier["decision"]["decision_key"],
                             "status": "coalesced_before_entry",
                             "actual_start": actual, "coalesced_into": _key_json(ekey),
                             "has_book": False, "has_return_segment": False,
                             "entry_cost": 0.0})
        action = ("rebalance" if canonical["decision"]["portfolio_check"]["ok"]
                  else "carry_forward")
        executions.append({"schema": "llm_paper_execution_plan/v2",
                           "experiment_version": canonical["experiment_version"],
                           "scheduled_at": canonical["scheduled_at"],
                           "actual_start_bar": actual, "cell_id": cell,
                           "execution_key": _key_json(ekey), "action": action,
                           "decision": canonical["decision"],
                           "round_hashes": sorted(item["round_hash"] for item in group),
                           "canonical_round_hash": canonical["round_hash"]})
        statuses.append({"decision_key": canonical["decision"]["decision_key"],
                         "status": "canonical", "actual_start": actual,
                         "execution_key": _key_json(ekey), "action": action})
    return {"schema": "llm_paper_coalescing/v2", "executions": executions,
            "decision_statuses": statuses, "pending_actual_start": pending}


def _open_price(opens: Mapping[Any, Any], symbol: str, actual: str) -> float | None:
    value = opens.get((symbol, actual[:10]), opens.get(symbol))
    if isinstance(value, Mapping):
        value = value.get("open")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def execute_canonical(plan: Mapping[str, Any], *, previous_book: Mapping[str, Any] | None,
                      opening_prices: Mapping[Any, Any], start_nav: float = 100_000.0
                      ) -> dict[str, Any]:
    """Execute exactly one canonical segment using scheme A at the shared open."""
    actual = str(plan["actual_start_bar"])
    old_shares = {str(k): float(v) for k, v in (previous_book or {}).get("shares", {}).items()}
    old_cash = float((previous_book or {}).get("cash", start_nav))
    target = {str(k): float(v) for k, v in plan["decision"]["target_weights"].items()}
    required = set(old_shares)
    if plan["action"] == "rebalance":
        required |= set(target)
    missing = sorted(symbol for symbol in required
                     if _open_price(opening_prices, symbol, actual) is None)
    if missing:
        return {"schema": EXECUTION_SCHEMA, "experiment_version": plan["experiment_version"],
                "execution_key": plan["execution_key"], "cell_id": plan["cell_id"],
                "actual_start_bar": actual, "status": "pending_archived_rebalance_bar",
                "missing": [f"{symbol}@{actual[:10]}" for symbol in missing],
                "turnover_notional": 0.0, "cost_rate": COST_RATE, "entry_cost": 0.0,
                "reason": "missing old/new holding open; close substitution forbidden"}

    old_notionals = {symbol: shares * float(_open_price(opening_prices, symbol, actual))
                     for symbol, shares in sorted(old_shares.items())}
    wealth = math.fsum([old_cash, *old_notionals.values()])
    previous_version = (previous_book or {}).get("experiment_version")
    first_v2_entry = previous_version not in {None, EXPERIMENT_VERSION}
    if plan["action"] == "carry_forward":
        return {"schema": EXECUTION_SCHEMA, "experiment_version": plan["experiment_version"],
                "execution_key": plan["execution_key"], "cell_id": plan["cell_id"],
                "scheduled_at": plan["scheduled_at"], "actual_start_bar": actual,
                "status": "carried_forward_portfolio_violation", "shares": old_shares,
                "cash": old_cash, "nav_start_before_cost": wealth,
                "turnover_notional": 0.0, "cost_rate": COST_RATE, "entry_cost": 0.0,
                "round_hashes": plan["round_hashes"], "cost_charged_once": True,
                "operational_continuity": {"from_version": previous_version,
                                           "wealth_at_boundary": wealth},
                "statistics_normalization": ({"wealth_before_entry": wealth,
                                              "normalized_to": start_nav,
                                              "entry_cost_included": True}
                                             if first_v2_entry else None)}

    new_notionals = {symbol: wealth * weight for symbol, weight in sorted(target.items())}
    turnover = math.fsum(abs(new_notionals.get(symbol, 0.0) -
                              old_notionals.get(symbol, 0.0))
                         for symbol in sorted(set(new_notionals) | set(old_notionals)))
    cost = turnover * COST_RATE
    shares = {symbol: notional / float(_open_price(opening_prices, symbol, actual))
              for symbol, notional in sorted(new_notionals.items())}
    cash = wealth - math.fsum(new_notionals.values()) - cost
    normalized_cost = (cost * start_nav / wealth) if first_v2_entry and wealth else cost
    return {"schema": EXECUTION_SCHEMA, "experiment_version": plan["experiment_version"],
            "execution_key": plan["execution_key"], "cell_id": plan["cell_id"],
            "scheduled_at": plan["scheduled_at"], "actual_start_bar": actual,
            "status": "filled", "shares": shares, "cash": cash,
            "old_notionals_at_rebalance": old_notionals,
            "new_target_notionals": new_notionals, "nav_start_before_cost": wealth,
            "turnover_notional": turnover, "cost_rate": COST_RATE, "entry_cost": cost,
            "cost_model_version": COST_MODEL_VERSION, "cost_charged_once": True,
            "round_hashes": plan["round_hashes"],
            "operational_continuity": {"from_version": previous_version,
                                       "wealth_at_boundary": wealth},
            "statistics_normalization": ({"wealth_before_entry": wealth,
                                          "normalized_to": start_nav,
                                          "normalized_entry_cost": normalized_cost,
                                          "entry_cost_included": True}
                                         if first_v2_entry else None)}


def execute_canonical_once(plan: Mapping[str, Any], *,
                           previous_book: Mapping[str, Any] | None,
                           opening_prices: Mapping[Any, Any], state_dir: str | Path
                           ) -> dict[str, Any]:
    root = Path(state_dir)
    registry = IdempotencyStore(root / "idempotency.jsonl")
    input_payload = {"plan": plan, "previous_book": previous_book,
                     "opening_prices": opening_prices}
    try:
        claim = registry.claim("execution_key", tuple(plan["execution_key"]), input_payload)
    except IdempotencyConflict:
        raise
    target = root / "executions" / (
        "execution_" + content_sha256(_key_json(plan["execution_key"]))[:20] + ".json")
    if claim.is_noop:
        if not target.exists():
            raise FrozenContractError("execution claim exists without its immutable artifact")
        existing = verify_hashed_artifact(target)
        return {**existing, "idempotency_status": "no_op"}
    result = execute_canonical(plan, previous_book=previous_book,
                               opening_prices=opening_prices)
    return write_hashed_artifact(target, result)


def _input_list(values: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for value in values:
        file = str(value.get("file") or "")
        digest = str(value.get("content_sha256") or "")
        if not file or not _is_sha256(digest):
            raise FrozenContractError("every evidence input needs file and 64-char content_sha256")
        normalized.append({"file": file, "content_sha256": digest})
    return sorted(normalized, key=lambda item: (item["file"], item["content_sha256"]))


def _bar_value(bars: Mapping[Any, Any], symbol: str, day: str, field: str) -> float | None:
    value = bars.get((symbol, day))
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get(field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def settle_execution(*, execution: Mapping[str, Any], next_actual_start: str | None,
                     archived_bars: Mapping[Any, Any], reading_kind: str,
                     round_inputs: Sequence[Mapping[str, Any]],
                     archive_inputs: Sequence[Mapping[str, Any]],
                     resolution_inputs: Sequence[Mapping[str, Any]],
                     unresolved_keys: Iterable[tuple[str, str]] = (),
                     benchmark: str = "SPY", equity_source: str = "Alpha Vantage as-traded",
                     cash_source: str = "literal zero-yield cash",
                     cash_total_return_factors: Mapping[str, float] | None = None
                     ) -> dict[str, Any]:
    """Build one half-open, provenance-complete settlement record."""
    if reading_kind not in READING_KINDS:
        raise FrozenContractError(f"unknown reading_kind={reading_kind!r}")
    start = str(execution["actual_start_bar"])[:10]
    end = str(next_actual_start)[:10] if next_actual_start else None
    days = sorted({str(key[1]) for key in archived_bars if isinstance(key, tuple) and len(key) == 2
                   and str(key[1]) >= start and (end is None or str(key[1]) < end)})
    mark_date = days[-1] if days else start
    rounds = _input_list(round_inputs)
    archives = _input_list(archive_inputs)
    resolutions = _input_list(resolution_inputs)
    unresolved = {(str(symbol), str(day)) for symbol, day in unresolved_keys}
    shares = {str(k): float(v) for k, v in (execution.get("shares") or {}).items()}
    rejected: list[dict[str, str]] = []
    nav_series: list[dict[str, float | str]] = []
    holdings_blocked = (execution.get("status") not in
                        {"filled", "carried_forward_portfolio_violation"} or not days)

    for day in days:
        consumed = {(symbol, day) for symbol in shares}
        for key in sorted(consumed):
            if key in unresolved:
                rejected.append({"key": f"{key[0]}@{key[1]}",
                                 "consumer": "holdings_nav", "reason": "unresolved_archive_input"})
                holdings_blocked = True
        values = {symbol: _bar_value(archived_bars, symbol, day, "close")
                  for symbol in shares}
        for symbol, value in values.items():
            if value is None:
                rejected.append({"key": f"{symbol}@{day}", "consumer": "holdings_nav",
                                 "reason": "missing_archived_close"})
                holdings_blocked = True
        if not holdings_blocked:
            cash_factor = 1.0
            if reading_kind == "acceptance":
                cash_factor = float((cash_total_return_factors or {}).get(day, math.nan))
                if not math.isfinite(cash_factor) or cash_factor <= 0:
                    rejected.append({"key": f"BIL@{day}", "consumer": "acceptance_cash_leg",
                                     "reason": "missing_total_return_factor"})
                    holdings_blocked = True
                    continue
            nav = math.fsum(float(shares[symbol]) * float(values[symbol])
                            for symbol in sorted(shares))
            nav += float(execution.get("cash", 0.0)) * cash_factor
            nav_series.append({"as_of": day, "nav": nav})

    benchmark_days = []
    for day in days:
        key = (benchmark, day)
        if key in unresolved:
            rejected.append({"key": f"{benchmark}@{day}", "consumer": "benchmark_alpha",
                             "reason": "unresolved_archive_input"})
            continue
        if _bar_value(archived_bars, benchmark, day, "close") is None:
            rejected.append({"key": f"{benchmark}@{day}", "consumer": "benchmark_alpha",
                             "reason": "missing_archived_close"})
            continue
        benchmark_days.append(day)

    acceptance_sources_ok = (equity_source == ACCEPTANCE_EQUITY_SOURCE and
                             cash_source == ACCEPTANCE_CASH_SOURCE)
    acceptance_benchmark_ok = not any(item["consumer"] == "benchmark_alpha"
                                      for item in rejected)
    if reading_kind == "acceptance" and not acceptance_sources_ok:
        rejected.append({"key": "acceptance_sources", "consumer": "acceptance",
                         "reason": "requires OpenD K_DAY qfq equity returns and BIL total returns"})
        holdings_blocked = True
    if reading_kind == "acceptance" and not acceptance_benchmark_ok:
        rejected.append({"key": benchmark, "consumer": "acceptance",
                         "reason": "benchmark inputs incomplete or unresolved"})

    performance = reading_kind in {"lower_bound", "acceptance"} and not holdings_blocked
    acceptance = (reading_kind == "acceptance" and performance and
                  acceptance_sources_ok and acceptance_benchmark_ok)
    skey = settlement_key(
        execution=execution["execution_key"], mark_date=mark_date,
        reading_kind=reading_kind,
        round_hashes=[item["content_sha256"] for item in rounds],
        archive_hashes=[item["content_sha256"] for item in archives],
        resolution_hashes=[item["content_sha256"] for item in resolutions])
    complete = ((reading_kind == "acceptance" and acceptance) or
                (reading_kind != "acceptance" and not holdings_blocked))
    if not complete:
        status = "pending"
    elif any(item["consumer"] == "benchmark_alpha" for item in rejected):
        status = "partial"
    else:
        status = "complete"
    payload = {
        "schema": SETTLEMENT_SCHEMA, "experiment_version": execution["experiment_version"],
        "execution_key": _key_json(tuple(execution["execution_key"])),
        "settlement_key": _key_json(skey),
        "window": {"start_open_inclusive": execution["actual_start_bar"],
                   "next_start_open_exclusive": next_actual_start},
        "status": status,
        "returns_through": (nav_series[-1]["as_of"] if nav_series else None),
        "data_available_through": (max((str(k[1]) for k in archived_bars
                                        if isinstance(k, tuple) and len(k) == 2), default=None)),
        "benchmark_returns_through": (benchmark_days[-1] if benchmark_days else None),
        "rejected_keys": rejected,
        "turnover_notional": float(execution.get("turnover_notional", 0.0)),
        "cost_rate": COST_RATE, "entry_cost": float(execution.get("entry_cost", 0.0)),
        "cost_model_version": COST_MODEL_VERSION, "reading_kind": reading_kind,
        "is_performance_reading": bool(performance and reading_kind != "equivalence_artifact"),
        "is_acceptance_reading": bool(acceptance), "nav_series": nav_series,
        "benchmark_dates": benchmark_days,
        "round_inputs": rounds, "archive_inputs": archives, "resolution_inputs": resolutions,
        "equity_source": equity_source, "cash_source": cash_source,
        "round_nav_point_consumed": False,
    }
    payload["content_sha256"] = content_sha256(payload)
    return payload


def settle_execution_once(*, state_dir: str | Path, **kwargs: Any) -> dict[str, Any]:
    result = settle_execution(**kwargs)
    root = Path(state_dir)
    registry = IdempotencyStore(root / "idempotency.jsonl")
    key = tuple(result["settlement_key"])
    claim = registry.claim("settlement_key", key, result["content_sha256"])
    target = root / "settlements" / (
        "settlement_" + content_sha256(result["settlement_key"])[:20] + ".json")
    if claim.is_noop:
        if not target.exists():
            raise FrozenContractError("settlement claim exists without its immutable artifact")
        return {**verify_hashed_artifact(target), "idempotency_status": "no_op"}
    return write_hashed_artifact(target, result)


def version_isolated_statistics(settlements: Sequence[Mapping[str, Any]],
                                gaps: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Return separate metrics per experiment version; never a combined annualization."""
    versions = sorted({str(item.get("experiment_version") or LEGACY_VERSION)
                       for item in settlements} |
                      {str(item.get("experiment_version") or LEGACY_VERSION) for item in gaps})
    result: dict[str, Any] = {}
    for version in versions:
        all_own = [item for item in settlements
                   if str(item.get("experiment_version") or LEGACY_VERSION) == version]
        own = [item for item in all_own if item.get("is_performance_reading")]
        points = [point for item in own for point in item.get("nav_series") or []]
        navs = [float(point["nav"]) for point in points]
        total_return = (navs[-1] / navs[0] - 1.0) if len(navs) >= 2 and navs[0] else None
        peak = -math.inf
        max_drawdown = 0.0
        for value in navs:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = min(max_drawdown, value / peak - 1.0)
        planned = len(own) + sum(
            str(item.get("experiment_version") or LEGACY_VERSION) == version for item in gaps)
        result[version] = {"sample_count": len(own),
                           "configured_frequency": ("M/W/F" if version == EXPERIMENT_VERSION
                                                    else "weekly"),
                           "n_settlements": len(all_own),
                           "n_performance_settlements": len(own), "n_nav_points": len(navs),
                           "total_return": total_return,
                           "max_drawdown": (max_drawdown if navs else None),
                           "n_gaps": planned - len(own),
                           "gap_rate": ((planned - len(own)) / planned if planned else None)}
    return {"schema": "llm_paper_version_statistics/v2", "combined_metrics": None,
            "versions": result, "operational_continuity_is_not_performance": True}


def trial_registration_metadata(*, immutable_rounds: Sequence[Mapping[str, Any]],
                                project_cumulative_n_before: int) -> dict[str, Any]:
    cells = {cell for round_ in immutable_rounds for cell in (round_.get("cells") or {})}
    if not cells <= set(GRID):
        raise FrozenContractError("immutable round contains a cell outside the frozen family")
    return {"experiment_version": EXPERIMENT_VERSION, "n_trials_total": 10,
            "n_evaluated": len(cells), "n_evaluated_source": "immutable_round_cell_union",
            "project_cumulative_n_before": int(project_cumulative_n_before),
            "project_cumulative_n_after": int(project_cumulative_n_before),
            "frequency_change_added_trials": 0,
            "candidate_supersedes_counted_once": True}


def advance_published_cutoff(*, current: str | None, candidate: str,
                             oauth_ok: bool, push_ok: bool) -> dict[str, Any]:
    """A local calculation never advances the official cutoff without auth + persistence."""
    if oauth_ok and push_ok:
        return {"status": "advanced", "cutoff": candidate}
    failures = []
    if not oauth_ok:
        failures.append("oauth")
    if not push_ok:
        failures.append("push")
    return {"status": "not_advanced", "cutoff": current, "candidate": candidate,
            "failures": failures, "manual_retry_allowed": False}


def historical_decision_backfill_policy(scheduled_at: Any) -> dict[str, Any]:
    """Missing decisions are perishable and can never be reconstructed later."""
    return {"scheduled_at": utc_text(scheduled_at), "backfill_allowed": False,
            "reason": "a later run cannot recreate the information set or decision_ts"}

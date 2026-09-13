"""Runtime contracts for the M/W/F v2 paper-forward pipeline.

The JSON schemas are the machine-readable boundary.  This module wires them
into every v2 artifact read/write and adds the cross-field checks JSON Schema
cannot express clearly (content hashes and timestamp ordering).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker


ROUND_SCHEMA = "llm_paper_planned_round/v2"
COALESCING_SCHEMA = "llm_paper_coalescing/v2"
EXECUTION_SCHEMA = "llm_paper_execution/v2"
SETTLEMENT_SCHEMA = "llm_paper_settlement/v2"
INPUT_SCHEMA = "llm_paper_typed_input/v2"
SCHEDULE_DELIVERY_SCHEMA = "llm_paper_schedule_delivery/v2"

_SCHEMA_FILES = {
    ROUND_SCHEMA: "llm_paper_mwf_v2_round.schema.json",
    COALESCING_SCHEMA: "llm_paper_mwf_v2_coalescing.schema.json",
    EXECUTION_SCHEMA: "llm_paper_mwf_v2_execution.schema.json",
    SETTLEMENT_SCHEMA: "llm_paper_mwf_v2_settlement.schema.json",
    INPUT_SCHEMA: "llm_paper_mwf_v2_input.schema.json",
    SCHEDULE_DELIVERY_SCHEMA: "llm_paper_mwf_v2_schedule_delivery.schema.json",
}
_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

SOURCE_IDENTITIES = {
    "archive_snapshot": "alpha_vantage.TIME_SERIES_DAILY.as_traded",
    "resolution": "llm_paper.RESOLUTION",
    "opend_k_day_qfq": "moomoo.OpenD.K_DAY.qfq",
    "bil_total_return": "BIL.total_return",
}


class FrozenContractError(ValueError):
    """Input or output violates the frozen v2 protocol."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False,
                      default=str).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def is_sha256(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        try:
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError as exc:
            raise FrozenContractError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise FrozenContractError(f"timestamp must include timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: Any) -> str:
    return parse_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _evidence_binding(value: Mapping[str, Any]) -> dict[str, str]:
    """Return the complete content-addressed identity exposed to a decision."""
    return {
        "file": str(value["file"]),
        "input_kind": str(value["input_kind"]),
        "content_sha256": str(value["content_sha256"]),
        "source_time_utc": _utc_text(value["source_time_utc"]),
        "evidence_available_utc": _utc_text(value["evidence_available_utc"]),
    }


def validate_evidence_bindings(refs: Iterable[Mapping[str, Any]],
                               verified_inputs: Iterable[Mapping[str, Any]], *,
                               context: str) -> None:
    """Bind every decision ref to all metadata of its verified hashed input."""
    by_hash: dict[str, dict[str, str]] = {}
    for item in verified_inputs:
        binding = _evidence_binding(item)
        digest = binding["content_sha256"]
        previous = by_hash.get(digest)
        if previous is not None and previous != binding:
            raise FrozenContractError(
                f"{context}: ambiguous verified input metadata for hash {digest}")
        by_hash[digest] = binding

    for ref in refs:
        actual = _evidence_binding(ref)
        digest = actual["content_sha256"]
        expected = by_hash.get(digest)
        if expected is None:
            raise FrozenContractError(
                f"{context}: evidence ref is not bound to a verified input: {digest}")
        differing = sorted(
            field for field in expected if actual[field] != expected[field])
        if differing:
            raise FrozenContractError(
                f"{context}: evidence ref metadata does not match verified input "
                f"for hash {digest}: {differing}")


def _validate_json_schema(payload: Mapping[str, Any]) -> None:
    schema_id = str(payload.get("schema") or "")
    filename = _SCHEMA_FILES.get(schema_id)
    if filename is None:
        raise FrozenContractError(f"unknown runtime schema: {schema_id!r}")
    schema = json.loads((_SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(dict(payload)),
                    key=lambda item: tuple(map(str, item.path)))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise FrozenContractError(f"schema validation failed at {where}: {first.message}")


def _verify_embedded_hash(payload: Mapping[str, Any]) -> None:
    supplied = payload.get("content_sha256")
    if supplied is None:
        return
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != content_sha256(unsigned):
        raise FrozenContractError("artifact content_sha256 does not match canonical content")


def _validate_round_semantics(payload: Mapping[str, Any]) -> None:
    status = payload.get("status")
    cells = payload.get("cells") or {}
    if status == "persisted" and not cells:
        raise FrozenContractError("persisted round must contain at least one cell")
    verified_inputs = payload.get("archive_snapshot_inputs") or []
    local_slot = parse_utc(payload["scheduled_at"]).astimezone(
        ZoneInfo("America/New_York"))
    market_open = local_slot.replace(hour=9, minute=30, second=0, microsecond=0)
    for cell_id, decision in cells.items():
        if decision.get("cell_id") != cell_id:
            raise FrozenContractError(f"cell map key does not match cell_id: {cell_id}")
        expected_key = [[payload["experiment_version"], payload["scheduled_at"]], cell_id]
        if decision.get("decision_key") != expected_key:
            raise FrozenContractError(f"cell {cell_id}: decision_key does not match round")
        unsigned_decision = dict(decision)
        supplied_decision_hash = unsigned_decision.pop("decision_content_sha256", None)
        if supplied_decision_hash != content_sha256(unsigned_decision):
            raise FrozenContractError(f"cell {cell_id}: decision content hash mismatch")
        source = parse_utc(decision["source_time_utc"])
        evidence = parse_utc(decision["evidence_available_utc"])
        decided = parse_utc(decision["decision_ts"])
        effective = parse_utc(decision["effective_from"])
        if effective != market_open.astimezone(timezone.utc):
            raise FrozenContractError(
                f"cell {cell_id}: effective_from must equal intended market open")
        if not source <= evidence <= decided < market_open.astimezone(timezone.utc):
            raise FrozenContractError(
                f"cell {cell_id}: require source_time_utc <= evidence_available_utc "
                "<= decision_ts < market open")
        if not decision.get("evidence_refs"):
            raise FrozenContractError(f"cell {cell_id}: evidence_refs must be non-empty")
        validate_evidence_bindings(
            decision["evidence_refs"], verified_inputs, context=f"cell {cell_id}")


def _validate_execution_semantics(payload: Mapping[str, Any]) -> None:
    shares = payload.get("shares") or {}
    values = [float(value) for value in shares.values()]
    if any(value < 0 for value in values) or float(payload.get("cash", 0.0)) < 0:
        raise FrozenContractError("execution shares and cash must be non-negative")


def _validate_settlement_semantics(payload: Mapping[str, Any]) -> None:
    if (payload.get("reading_kind") == "lower_bound" and
            payload.get("is_acceptance_reading") is True):
        raise FrozenContractError(
            "lower_bound settlement cannot be an acceptance reading")


def _record_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("symbol") or ""), str(record.get("trade_date") or "")


def _validate_typed_input_semantics(payload: Mapping[str, Any]) -> None:
    kind = str(payload["input_kind"])
    expected_source = SOURCE_IDENTITIES[kind]
    if payload.get("source_identity") != expected_source:
        raise FrozenContractError(
            f"{kind} source_identity must be {expected_source!r}")
    if parse_utc(payload["source_time_utc"]) > parse_utc(payload["evidence_available_utc"]):
        raise FrozenContractError("typed input source_time_utc is after evidence availability")
    records = list(payload.get("records") or [])
    if not records:
        raise FrozenContractError(f"{kind} records must be non-empty")
    keys = [_record_key(record) for record in records]
    if any(not symbol or not day for symbol, day in keys):
        raise FrozenContractError(f"{kind} records require symbol and trade_date")
    if len(keys) != len(set(keys)):
        raise FrozenContractError(f"{kind} contains duplicate symbol/trade_date records")
    symbols = sorted({symbol for symbol, _ in keys})
    dates = sorted({day for _, day in keys})
    coverage = payload.get("coverage") or {}
    if coverage.get("symbols") != symbols or coverage.get("trade_dates") != dates:
        raise FrozenContractError(f"{kind} coverage must exactly match records")
    if parse_utc(payload["source_time_utc"]).date().isoformat() < dates[-1]:
        raise FrozenContractError(f"{kind} source_time_utc predates its latest trade date")

    for record in records:
        if kind in {"archive_snapshot", "opend_k_day_qfq"}:
            for field in ("open", "close"):
                value = float(record.get(field, 0.0))
                if not math.isfinite(value) or value <= 0:
                    raise FrozenContractError(f"{kind} {field} must be positive")
        if kind == "opend_k_day_qfq":
            if record.get("ktype") != "K_DAY" or record.get("rehab_type") != "qfq":
                raise FrozenContractError("OpenD input requires K_DAY/qfq on every bar")
        elif kind == "bil_total_return":
            factor = float(record.get("total_return_factor", 0.0))
            if (record.get("symbol") != "BIL" or not math.isfinite(factor) or
                    factor <= 0):
                raise FrozenContractError(
                    "BIL total-return input requires positive BIL factors")
        elif kind == "resolution":
            if record.get("status") not in {"resolved", "unresolved"}:
                raise FrozenContractError("RESOLUTION record status is invalid")


def validate_runtime_artifact(payload: Mapping[str, Any], *, verify_hash: bool = True
                              ) -> dict[str, Any]:
    """Validate one artifact against its checked-in schema and semantics."""
    materialized = dict(payload)
    _validate_json_schema(materialized)
    if verify_hash:
        _verify_embedded_hash(materialized)
    schema_id = materialized["schema"]
    if schema_id == ROUND_SCHEMA:
        _validate_round_semantics(materialized)
    elif schema_id == EXECUTION_SCHEMA:
        _validate_execution_semantics(materialized)
    elif schema_id == SETTLEMENT_SCHEMA:
        _validate_settlement_semantics(materialized)
    elif schema_id == INPUT_SCHEMA:
        _validate_typed_input_semantics(materialized)
    return materialized


def make_typed_input(*, input_kind: str, file: str,
                     source_time_utc: str, evidence_available_utc: str,
                     records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a content-addressed, source-bound input accepted by the pipeline."""
    if input_kind not in SOURCE_IDENTITIES:
        raise FrozenContractError(f"unknown typed input kind: {input_kind!r}")
    copied = [dict(record) for record in records]
    keys = [_record_key(record) for record in copied]
    payload: dict[str, Any] = {
        "schema": INPUT_SCHEMA,
        "input_kind": input_kind,
        "source_identity": SOURCE_IDENTITIES[input_kind],
        "file": str(file),
        "source_time_utc": str(source_time_utc),
        "evidence_available_utc": str(evidence_available_utc),
        "coverage": {
            "symbols": sorted({symbol for symbol, _ in keys}),
            "trade_dates": sorted({day for _, day in keys}),
        },
        "records": copied,
    }
    payload["content_sha256"] = content_sha256(payload)
    return validate_runtime_artifact(payload)


def verify_typed_input(value: Mapping[str, Any], *,
                       expected_kinds: Iterable[str] | None = None,
                       required_symbols: Iterable[str] = (),
                       required_trade_dates: Iterable[str] = ()) -> dict[str, Any]:
    payload = validate_runtime_artifact(value)
    kinds = set(expected_kinds or SOURCE_IDENTITIES)
    if payload["input_kind"] not in kinds:
        raise FrozenContractError(
            f"input kind {payload['input_kind']!r} not in expected {sorted(kinds)}")
    coverage = payload["coverage"]
    missing_symbols = sorted(set(map(str, required_symbols)) - set(coverage["symbols"]))
    missing_dates = sorted(set(map(str, required_trade_dates)) - set(coverage["trade_dates"]))
    if missing_symbols or missing_dates:
        raise FrozenContractError(
            f"typed input coverage missing symbols={missing_symbols} dates={missing_dates}")
    required_pairs = {(str(symbol), str(day)) for symbol in required_symbols
                      for day in required_trade_dates}
    present = {_record_key(record) for record in payload["records"]}
    missing_pairs = sorted(required_pairs - present)
    if missing_pairs:
        raise FrozenContractError(f"typed input missing required bars: {missing_pairs}")
    return payload


def typed_records(values: Sequence[Mapping[str, Any]], *, expected_kinds: Iterable[str]
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inputs = [verify_typed_input(value, expected_kinds=expected_kinds) for value in values]
    records: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for payload in inputs:
        for record in payload["records"]:
            key = _record_key(record)
            if key in seen and canonical_bytes(seen[key]) != canonical_bytes(record):
                raise FrozenContractError(f"conflicting typed records for {key}")
            seen[key] = dict(record)
    records.extend(seen[key] for key in sorted(seen))
    return inputs, records

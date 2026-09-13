"""Deterministic natural-delivery runner for ``llm_paper_forward_mwf_v2``."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from research.gate.filelock import atomic_write_text, state_lock

from qlab.llm_paper.mwf_v2 import (
    EXPERIMENT_VERSION,
    FrozenContractError,
    coalesce_rounds,
    content_sha256,
    execute_canonical_once,
    ingest_planned_round,
    settle_execution_once,
    verify_hashed_artifact,
    write_hashed_artifact,
)
from qlab.llm_paper.mwf_v2_contracts import (
    SCHEDULE_DELIVERY_SCHEMA,
    validate_runtime_artifact,
    verify_typed_input,
)


EXIT_INPUT = 10
EXIT_ROUND = 20
EXIT_COALESCING = 30
EXIT_EXECUTION = 40
EXIT_SETTLEMENT = 50


@dataclass(frozen=True)
class PipelineStageError(RuntimeError):
    stage: str
    exit_code: int
    reason: str

    def __str__(self) -> str:
        return f"{self.stage}: {self.reason}"


def _write_result(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    materialized = dict(payload)
    materialized.pop("content_sha256", None)
    materialized["content_sha256"] = content_sha256(materialized)
    with state_lock(str(path)):
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            unsigned = dict(existing)
            supplied = unsigned.pop("content_sha256", None)
            if supplied != content_sha256(unsigned):
                raise FrozenContractError("pipeline result hash mismatch")
            if existing != materialized:
                raise FrozenContractError("immutable pipeline result collision")
            return existing
        atomic_write_text(
            str(path), json.dumps(materialized, ensure_ascii=False,
                                  sort_keys=True, indent=2) + "\n")
    return materialized


def _stage_failure(root: Path, delivery_hash: str, error: PipelineStageError) -> dict[str, Any]:
    payload = {
        "schema": "llm_paper_pipeline_failure/v2",
        "experiment_version": EXPERIMENT_VERSION,
        "delivery_content_sha256": delivery_hash,
        "status": "failed_closed",
        "failed_stage": error.stage,
        "exit_code": error.exit_code,
        "reason": error.reason,
        "published_cutoff_advanced": False,
        "success_manifest_written": False,
    }
    target = root / "failures" / f"failure_{delivery_hash[:20]}_{error.stage}.json"
    return _write_result(target, payload)


def run_scheduled_delivery(delivery_path: str | Path, *, state_dir: str | Path
                           ) -> dict[str, Any]:
    """Run one frozen local delivery through every stage without network callbacks."""
    root = Path(state_dir)
    try:
        delivery = validate_runtime_artifact(
            json.loads(Path(delivery_path).read_text(encoding="utf-8")))
        if delivery["schema"] != SCHEDULE_DELIVERY_SCHEMA:
            raise FrozenContractError("not an M/W/F v2 schedule delivery")
        snapshot = verify_typed_input(
            delivery["snapshot"], expected_kinds={"archive_snapshot"})
        execution_snapshot = verify_typed_input(
            delivery["execution_snapshot"], expected_kinds={"archive_snapshot"})
    except Exception as exc:
        raise PipelineStageError("input", EXIT_INPUT, str(exc)) from exc

    delivery_hash = str(delivery["content_sha256"])
    planning_hash = content_sha256({
        "delivery_id": delivery["delivery_id"],
        "scheduled_at": delivery["scheduled_at"],
        "required_trade_date": delivery["required_trade_date"],
        "archive_required": delivery["archive_required"],
        "decision_required": delivery["decision_required"],
        "snapshot_content_sha256": snapshot["content_sha256"],
        "cells": delivery["cells"],
    })

    def offline_fetch(symbols):
        raise FrozenContractError(
            f"offline natural runner refuses unfrozen fetch symbols: {list(symbols)}")

    try:
        round_result = ingest_planned_round(
            scheduled_at=delivery["scheduled_at"],
            delivery_payload={"delivery_id": delivery["delivery_id"],
                              "planning_content_sha256": planning_hash},
            state_dir=root, fetch_snapshot=offline_fetch,
            build_cells=lambda _: delivery["cells"],
            archive_required=delivery["archive_required"],
            decision_required=delivery["decision_required"],
            required_trade_date=delivery["required_trade_date"],
            reusable_snapshot=snapshot)
        round_artifact = round_result.get("artifact")
        if not round_artifact or round_artifact.get("status") != "persisted":
            raise FrozenContractError(
                f"planned round did not persist: {round_result.get('status')}")
        round_path = next(
            path for path in sorted((root / "rounds").glob("planned_*.json"))
            if verify_hashed_artifact(path)["content_sha256"] ==
            round_artifact["content_sha256"])
    except Exception as exc:
        error = PipelineStageError("round", EXIT_ROUND, str(exc))
        _stage_failure(root, delivery_hash, error)
        raise error from exc

    try:
        coalescing = coalesce_rounds(
            [round_artifact], observed_market_opens=delivery["observed_market_opens"])
        if coalescing["pending_actual_start"] or not coalescing["executions"]:
            raise FrozenContractError("no canonical execution is ready")
        coalescing_path = root / "coalescing" / f"coalescing_{delivery_hash[:20]}.json"
        coalescing_artifact = write_hashed_artifact(coalescing_path, coalescing)
    except Exception as exc:
        error = PipelineStageError("coalescing", EXIT_COALESCING, str(exc))
        _stage_failure(root, delivery_hash, error)
        raise error from exc

    opening_prices = {
        str(record["symbol"]): {"open": record["open"]}
        for record in execution_snapshot["records"]
        if str(record["trade_date"]) == str(coalescing_artifact["executions"][0][
            "actual_start_bar"])[:10]
    }
    executions: list[dict[str, Any]] = []
    try:
        for plan in coalescing_artifact["executions"]:
            execution = execute_canonical_once(
                plan, previous_book=(delivery.get("previous_books") or {}).get(plan["cell_id"]),
                opening_prices=opening_prices, opening_inputs=[execution_snapshot],
                state_dir=root)
            if execution["status"] not in {"filled", "carried_forward_portfolio_violation"}:
                raise FrozenContractError(f"execution is not final: {execution['status']}")
            executions.append(execution)
    except Exception as exc:
        error = PipelineStageError("execution", EXIT_EXECUTION, str(exc))
        _stage_failure(root, delivery_hash, error)
        raise error from exc

    settlements: list[dict[str, Any]] = []
    try:
        for execution in executions:
            settlement = settle_execution_once(
                state_dir=root, execution=execution,
                next_actual_start=delivery.get("next_actual_start"),
                archived_bars=None, reading_kind=delivery["reading_kind"],
                round_inputs=[{
                    "file": round_path.relative_to(root).as_posix(),
                    "content_sha256": round_artifact["content_sha256"],
                }],
                archive_inputs=[execution_snapshot],
                resolution_inputs=delivery.get("resolution_inputs") or [],
                acceptance_equity_inputs=delivery.get("acceptance_equity_inputs") or [],
                acceptance_cash_inputs=delivery.get("acceptance_cash_inputs") or [])
            if settlement["status"] not in {"complete", "partial"}:
                raise FrozenContractError(f"settlement is not final: {settlement['status']}")
            settlements.append(settlement)
    except Exception as exc:
        error = PipelineStageError("settlement", EXIT_SETTLEMENT, str(exc))
        _stage_failure(root, delivery_hash, error)
        raise error from exc

    manifest = {
        "schema": "llm_paper_pipeline_result/v2",
        "experiment_version": EXPERIMENT_VERSION,
        "delivery_content_sha256": delivery_hash,
        "status": "complete",
        "stages": {
            "round": round_artifact["content_sha256"],
            "coalescing": coalescing_artifact["content_sha256"],
            "executions": [item["content_sha256"] for item in executions],
            "settlements": [item["content_sha256"] for item in settlements],
        },
        "idempotency_key": round_artifact["planned_round_key"],
        "published_cutoff_advanced": False,
        "remote_fetches": 0,
    }
    return _write_result(root / "pipeline" / f"result_{delivery_hash[:20]}.json", manifest)

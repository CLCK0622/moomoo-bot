"""Post-round (a)/(b) equivalence audit using the derived settlement chain.

The in-round comparison necessarily sees ``pending_entry_bar`` because the
decision is made before the entry open exists.  This module leaves that
immutable evidence untouched and applies the same settlement function to the
bearing and control round records after archived bars exist.

Its output is always ``reading_kind=equivalence_artifact``: it is comparison
evidence, never a performance reading and never an acceptance result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from qlab.llm_paper.decision_chain import load_anchor, load_prereg
from qlab.llm_paper.derived_settlement import (SETTLEMENT_IMPLEMENTATION_VERSION,
                                                STABLE_ACCUMULATION_SEMANTICS,
                                                SUPPORTED_RUNTIME,
                                                _cells,
                                                rebuild_settlement_from_rounds,
                                                require_reading_kind)
from qlab.llm_paper.multi_book import (EQUIVALENCE_FIELDS, cell_id,
                                       compare_decision_sets)
from qlab.llm_paper.nav_series import load_rounds

DERIVED_BOOK_FIELDS: Tuple[str, ...] = (
    "status", "nav_start", "entries", "shares", "gross_notional",
    "turnover_notional", "old_notionals_at_rebalance", "entry_cost", "cash",
    "rebalance_provenance", "consumed_bar_keys", "bar_provenance", "basis",
    "mark_window",
)
DERIVED_NAV_FIELDS: Tuple[str, ...] = ("nav_series",)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取等价性输入 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"等价性输入不是 JSON object: {path}")
    payload.setdefault("_file", path.name)
    return payload


def _rule(name: str, passed: bool, evidence: Any, blocker: str | None = None) -> Dict[str, Any]:
    result = {"name": name, "passed": bool(passed), "evidence": evidence}
    if not passed:
        result["blocker"] = blocker or "未满足"
    return result


def _compare_derived_cells(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare every derived book/NAV field; pending equality is not a pass."""
    left_status, right_status = left.get("status"), right.get("status")
    if left_status != "filled" or right_status != "filled":
        return {
            "status": "blocked_pending_reading",
            "identical": None,
            "passed": False,
            "left_status": left_status,
            "right_status": right_status,
            "fields_compared": {"book": list(DERIVED_BOOK_FIELDS),
                                "nav": list(DERIVED_NAV_FIELDS)},
            "diffs": [],
            "blocker": ("两侧至少一侧没有可核验的 filled 派生读数；pending 相同不是等价性通过"),
        }
    diffs = []
    for field in DERIVED_BOOK_FIELDS + DERIVED_NAV_FIELDS:
        if left.get(field) != right.get(field):
            diffs.append({"field": field, "a": left.get(field), "b": right.get(field)})
    return {
        "status": "passed" if not diffs else "mismatch",
        "identical": not diffs,
        "passed": not diffs,
        "left_status": left_status,
        "right_status": right_status,
        "fields_compared": {"book": list(DERIVED_BOOK_FIELDS),
                            "nav": list(DERIVED_NAV_FIELDS)},
        "diffs": diffs,
    }


def _decision_record_valid(cid: str, block: Mapping[str, Any]) -> bool:
    decisions = block.get("decisions") or []
    if not decisions:
        return False
    required = set(EQUIVALENCE_FIELDS)
    return all(required <= set(decision) and
               cell_id(int(decision["seed"]), str(decision["prompt_variant"])) == cid
               for decision in decisions)


def _effective_decision_set_count(cells: Mapping[str, Mapping[str, Any]]) -> int:
    """Count prompt outputs without mislabelling nominal seed copies as robust."""
    fingerprints = set()
    for block in cells.values():
        normalized = []
        for decision in block.get("decisions") or []:
            normalized.append({key: decision.get(key) for key in EQUIVALENCE_FIELDS
                               if key != "seed"})
        fingerprints.add(_canonical({"decisions": sorted(
            normalized, key=lambda item: (str(item.get("symbol")),
                                          str(item.get("prompt_variant"))))}))
    return len(fingerprints)


def rebuild_derived_equivalence(out_dir: str, *, stamp: str,
                                evidence_commit: str | None = None,
                                freeze_is_ancestor: bool | None = None,
                                records_unchanged: bool | None = None) -> Dict[str, Any]:
    """Audit one persisted parallel-control round without running a new round."""
    out = Path(out_dir)
    bearing_path = out / f"round_{stamp}.json"
    control_path = out / "control_multi_book" / f"round_{stamp}.json"
    report_path = out / f"CONTROL_{stamp}.json"
    bearing = _read_json(bearing_path)
    control = _read_json(control_path)
    prior_report = _read_json(report_path)

    bearing_cells = _cells(bearing)
    control_cells = _cells(control)
    prereg = load_prereg()
    anchor = load_anchor()
    expected_cells = set(str(item) for item in prereg["family"]["grid"])
    overlap = sorted(set(bearing_cells) & set(control_cells))

    # Both sides must inherit the complete common history.  Settling only the
    # target round would silently reset NAV to 100k and reduce turnover to a
    # first-entry cost, bypassing the cross-round compounding and Σ|new-old|
    # semantics this audit is required to exercise.
    bearing_history = [payload for payload in load_rounds(out_dir)
                       if str(payload.get("_file", ""))[6:14] <= stamp]
    if not any(str(payload.get("_file", ""))[6:14] == stamp
               for payload in bearing_history):
        raise ValueError(f"承载历史缺 round_{stamp}.json")
    control_history = [payload for payload in bearing_history
                       if str(payload.get("_file", ""))[6:14] < stamp] + [control]
    bearing_settlement = rebuild_settlement_from_rounds(
        out_dir, bearing_history, reading_kind="equivalence_artifact",
        source_kind="bearing_history_through_target_round")
    control_settlement = rebuild_settlement_from_rounds(
        out_dir, control_history, reading_kind="equivalence_artifact",
        source_kind="bearing_history_with_control_target_round")
    settled_a = next(round_["cells"] for round_ in bearing_settlement["rounds"]
                     if round_["round"] == stamp)
    settled_b = next(round_["cells"] for round_ in control_settlement["rounds"]
                     if round_["round"] == stamp)

    decision_comparisons = {
        cid: compare_decision_sets(bearing_cells[cid]["decisions"],
                                   control_cells[cid]["decisions"])
        for cid in overlap
    }
    per_grid: Dict[str, Dict[str, Any]] = {}
    for cid in sorted(expected_cells):
        left, right = settled_a.get(cid), settled_b.get(cid)
        if left is None:
            per_grid[cid] = {
                "bearing_peer": False,
                "control_settlement_status": (right or {}).get("status"),
                "comparison": {
                    "status": "not_comparable_no_bearing_cell",
                    "passed": None,
                    "blocker": ("承载侧 (a) 本轮没有该格；按既定边界只能逐位比较两侧重叠格，"
                                "不得把单侧读数称为等价性验证"),
                },
            }
        elif right is None:
            per_grid[cid] = {
                "bearing_peer": True,
                "bearing_settlement_status": left.get("status"),
                "comparison": {"status": "missing_control_cell", "passed": False,
                               "blocker": "对照侧缺格"},
            }
        else:
            per_grid[cid] = {
                "bearing_peer": True,
                "bearing_settlement_status": left.get("status"),
                "control_settlement_status": right.get("status"),
                "decision_set_comparison": decision_comparisons[cid],
                "comparison": _compare_derived_cells(left, right),
            }

    same_ts = bearing.get("round_decision_ts") == control.get("round_decision_ts")
    bearing_preflight = bearing.get("preflight") or {}
    control_preflight = control.get("preflight") or {}
    same_freeze = bool(
        bearing_preflight.get("anchor_ok") is True and
        control_preflight.get("anchor_ok") is True and
        bearing_preflight.get("prereg_frozen_at") == control_preflight.get("prereg_frozen_at")
    )
    snapshot_evidence = prior_report.get("shared_quote_snapshot") or {}
    same_snapshot = bool(
        snapshot_evidence.get("symbols") and
        int(snapshot_evidence.get("n_calls", -1)) == len(snapshot_evidence["symbols"]) and
        prior_report.get("control_quote_calls") == 0 and
        control.get("bars_injected") is True
    )
    overlap_decisions_equal = bool(overlap) and all(
        comparison["identical"] for comparison in decision_comparisons.values())
    full_grid = set(control_cells) == expected_cells and not control.get("cells_missing")
    decision_records_valid = all(_decision_record_valid(cid, block)
                                 for cid, block in control_cells.items())
    bearing_survived = bool(bearing.get("decisions")) and prior_report.get("control_error") is None
    n_trials_total = (bearing.get("ledger") or {}).get("n_trials_total")

    rules = [
        _rule("same_decision_ts", same_ts,
              {"bearing": bearing.get("round_decision_ts"),
               "control": control.get("round_decision_ts")},
              "两侧 decision_ts 不同"),
        _rule("same_freeze_anchor", same_freeze,
              {"freeze_sha": anchor.get("freeze_sha"),
               "bearing": bearing_preflight.get("prereg_frozen_at"),
               "control": control_preflight.get("prereg_frozen_at")},
              "冻结锚点不一致或 preflight 未通过"),
        _rule("decision_commit_descends_from_freeze", freeze_is_ancestor is True,
              {"evidence_commit": evidence_commit, "freeze_sha": anchor.get("freeze_sha"),
               "verified": freeze_is_ancestor},
              "未提供可核验的 DAG 祖先结果"),
        _rule("same_shared_bar_snapshot", same_snapshot,
              {"control_report": report_path.name, "shared_quote_snapshot": snapshot_evidence,
               "control_bars_injected": control.get("bars_injected"),
               "control_quote_calls": prior_report.get("control_quote_calls"),
               "snapshot_content_hash_recorded": False,
               "verification_basis": "单次 fetch 报告 + 对照侧 injected/0-call 不变量"},
              "既有产物不足以证明两侧共用一次取数"),
        _rule("overlap_decisions_identical", overlap_decisions_equal,
              {"overlap_cells": overlap, "comparisons": decision_comparisons},
              "重叠格决策不一致或不存在"),
        _rule("all_or_none_full_grid", full_grid and decision_records_valid,
              {"expected_cells": sorted(expected_cells), "actual_cells": sorted(control_cells),
               "cells_missing": control.get("cells_missing"),
               "decision_records_valid": decision_records_valid},
              "对照轮不是足额、逐条可验证的冻结网格"),
        _rule("append_only_records_unchanged", records_unchanged is True,
              {"evidence_commit": evidence_commit, "verified": records_unchanged},
              "未提供 git 跟踪且未改写的核验结果"),
        _rule("bearing_round_not_fail_closed", bearing_survived,
              {"bearing_file": bearing_path.name,
               "control_error": prior_report.get("control_error")},
              "承载轮未成功落盘或对照报告记有运行错误"),
        _rule("n_trials_total_remains_10", n_trials_total == 10,
              {"n_trials_total": n_trials_total,
               "n_evaluated": (bearing.get("ledger") or {}).get("n_evaluated"),
               "control_registered_trials": prior_report.get("control_registered_trials")},
              "冻结试验总数不是 10"),
    ]
    promotion_eligible = all(rule["passed"] for rule in rules)
    overlap_book_nav_passed = bool(overlap) and all(
        per_grid[cid]["comparison"].get("passed") is True for cid in overlap)

    blockers = [rule["blocker"] for rule in rules if not rule["passed"]]
    for cid in overlap:
        comparison = per_grid[cid]["comparison"]
        if comparison.get("passed") is not True:
            blockers.append(f"{cid}: {comparison.get('blocker') or comparison.get('status')}")

    payload: Dict[str, Any] = {
        "schema": "llm_paper_derived_executor_equivalence/v2",
        "settlement_calculation_contract": {
            "implementation_version": SETTLEMENT_IMPLEMENTATION_VERSION,
            "numeric_accumulation_semantics": STABLE_ACCUMULATION_SEMANTICS,
            "supported_runtime": SUPPORTED_RUNTIME,
        },
        "reading_kind": require_reading_kind("equivalence_artifact"),
        "is_performance_reading": False,
        "is_acceptance_reading": False,
        "round": stamp,
        "source": {
            "bearing_round_file": str(bearing_path),
            "control_round_file": str(control_path),
            "control_report_file": str(report_path),
            "evidence_commit": evidence_commit,
            "archive_content_sha256s": bearing_settlement["source"]["archive_content_sha256s"],
        },
        "decision_capture_promotion": {
            "eligible": promotion_eligible,
            "rules": rules,
            "n_trials_total": n_trials_total,
            "n_evaluated_unchanged": (bearing.get("ledger") or {}).get("n_evaluated"),
            "note": ("本报告只核验升格条件，不改 trial ledger；若未来计入对照格，"
                     "必须另走有测试的显式开关，禁止递归 glob。"),
        },
        "seed_semantics": {
            "temperature": (control.get("seed_semantics") or {}).get("temperature"),
            "effective_distinct_decision_sets": _effective_decision_set_count(control_cells),
            "must_not_claim_seed_robustness": True,
        },
        "overlap_cells": overlap,
        "comparison_scope": ("(a) 每轮只有一个格；book/NAV 等价性只能验证两侧重叠格，"
                             "其余 (b) 格逐格列出结算状态但不冒充双侧等价性。"),
        "per_grid": per_grid,
        "derived_settlements": {"bearing": bearing_settlement,
                                "control": control_settlement},
        "takeover_contract": {
            "decision_capture": {
                "comparison_object": "immutable decision fields from bearing and control records",
                "covered_cells": overlap,
                "control_grid_cells_recorded": sorted(control_cells),
                "status": "eligible" if promotion_eligible else "blocked",
            },
            "derived_reconstruction_equivalence": {
                "comparison_object": (
                    "bearing/control immutable round records reconstructed by the same "
                    "derived-settlement implementation"),
                "covered_cells": overlap,
                "cells_without_bearing_peer": sorted(expected_cells - set(overlap)),
                "status": "passed" if overlap_book_nav_passed else "blocked",
                "establishes": "reconstruction consistency for overlapping recorded decisions",
                "does_not_establish": (
                    "independent runtime behavior equivalence of single_book and multi_book executors"),
            },
            "executor_behavior_equivalence": {
                "status": "not_established",
                "reason": ("both sides use the same derived reconstruction implementation; persisted "
                           "decision-time books were pending and are not independent filled executions"),
            },
            "switch_authorization": {
                "status": "not_granted",
                "automatic_repository_consumer": False,
                "required_authority": "separate written acceptance by 吏部",
                "volume_resolution_authorizes_switch": False,
            },
        },
        "summary": {
            "decision_capture_promotion_eligible": promotion_eligible,
            "overlap_book_nav_equivalence_passed": overlap_book_nav_passed,
            "may_take_over": bool(promotion_eligible and overlap_book_nav_passed),
            "may_take_over_semantics": (
                "derived qualification fact only; never executor-switch authorization"),
            "switch_authorized": False,
            "blockers": blockers,
        },
        "note": ("pending 两侧相同不构成通过；may_take_over 只表示既有计算资格判据，"
                 "无论真假都不构成执行器切换授权。volume RESOLUTION 只解除数据完整性闸，"
                 "接管仍须吏部另行书面核收。本产物不可进入净值或业绩上报路径。"),
    }
    return payload


def write_derived_equivalence(out_dir: str, *, stamp: str,
                              evidence_commit: str | None = None,
                              freeze_is_ancestor: bool | None = None,
                              records_unchanged: bool | None = None,
                              prepared_payload: Mapping[str, Any] | None = None
                              ) -> Dict[str, Any]:
    """Write one content-addressed append-only equivalence artifact."""
    payload = (dict(prepared_payload) if prepared_payload is not None else
               rebuild_derived_equivalence(
                   out_dir, stamp=stamp, evidence_commit=evidence_commit,
                   freeze_is_ancestor=freeze_is_ancestor,
                   records_unchanged=records_unchanged))
    payload["content_sha256"] = _hash(payload)
    directory = Path(out_dir) / "derived_settlement"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"EQUIVALENCE_{stamp}_{payload['content_sha256'][:16]}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if _canonical(existing) != _canonical(payload):
            raise ValueError("派生等价性文件名冲突且内容不同")
    return {"equivalence_file": str(path), "content_sha256": payload["content_sha256"],
            "payload": payload}

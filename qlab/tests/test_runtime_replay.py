"""Offline replay exercises both real executors without touching source evidence."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from qlab.llm_paper.runtime_replay import (RuntimeReplayError,
                                           replay_runtime_equivalence,
                                           verify_runtime_replay_artifact)


def _real_reports() -> Path:
    return Path(__file__).resolve().parents[1] / "reports" / "llm_paper"


def _copy_inputs(tmp_path: Path) -> Path:
    source = _real_reports()
    target = tmp_path / "llm_paper"
    for relative in ("round_20260831.json", "CONTROL_20260831.json",
                     "control_multi_book/round_20260831.json",
                     "derived_settlement/SETTLEMENT_dfe843379ccb07eb.json"):
        src = source / relative
        dst = target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copytree(source / "bar_archive", target / "bar_archive")
    return target


def test_real_0831_replay_is_filled_hash_bound_and_idempotent(tmp_path):
    reports = _copy_inputs(tmp_path)

    first = replay_runtime_equivalence(str(reports))
    second = replay_runtime_equivalence(str(reports))
    artifact = verify_runtime_replay_artifact(first["artifact_file"])

    assert second["artifact_file"] == first["artifact_file"]
    assert second["content_sha256"] == first["content_sha256"]
    assert second["file_sha256"] == first["file_sha256"]
    assert len(list((reports / "runtime_replay").glob("RUNTIME_EQUIVALENCE_*.json"))) == 1

    assert artifact["runtime_outputs"]["bearing"]["book"]["status"] == "filled"
    assert {cell["book"]["status"]
            for cell in artifact["runtime_outputs"]["control"]["cells"].values()} == {"filled"}
    assert artifact["runtime_comparison"]["status"] == "passed"
    assert artifact["runtime_comparison"]["book_equivalence_exercised"] is True
    assert artifact["runtime_comparison"]["diffs"] == []
    assert artifact["same_shared_bar_snapshot"]["status"] == "passed"
    snapshot_hash = artifact["shared_bar_snapshot"]["content_sha256"]
    binding = artifact["same_shared_bar_snapshot"]
    assert {binding["bearing_argument_content_sha256"],
            binding["control_argument_content_sha256"],
            binding["after_both_executors_content_sha256"]} == {snapshot_hash}
    assert {(item["symbol"], item["date"])
            for item in artifact["shared_bar_snapshot"][
                "unresolved_keys_excluded_and_still_blocked"]} == {
                    ("SPY", "2026-09-01"), ("SPY", "2026-09-02")}
    assert artifact["source_input_immutability"]["status"] == "passed"
    assert artifact["derived_settlement_reconciliation"]["bearing"]["status"] == \
        "differences_found"
    assert artifact["conclusions"]["executor_behavior_equivalence"] == \
        "established_for_single_overlapping_cell"
    assert artifact["conclusions"]["overlapping_cells"] == 1
    assert artifact["conclusions"]["control_cells_without_bearing_peer"] == 9
    assert artifact["conclusions"]["effective_distinct_decision_sets"] == 2
    assert artifact["conclusions"]["switch_authorized"] is False
    assert artifact["verdict"] is None


def test_replay_refuses_loose_non_archive_bars(tmp_path):
    reports = tmp_path / "llm_paper"
    reports.mkdir()
    (reports / "bars.json").write_text(
        json.dumps({"SPY": [{"date": "2026-08-31", "close": 1.0}]}), encoding="utf-8")

    with pytest.raises(RuntimeReplayError, match="非归档|bar_archive"):
        replay_runtime_equivalence(str(reports))


def test_runtime_replay_artifact_tamper_is_rejected(tmp_path):
    reports = _copy_inputs(tmp_path)
    result = replay_runtime_equivalence(str(reports))
    path = Path(result["artifact_file"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["conclusions"]["switch_authorized"] = True
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RuntimeReplayError, match="内容哈希不匹配"):
        verify_runtime_replay_artifact(path)

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
    unresolved = artifact["shared_bar_snapshot"]["unresolved_keys_present"]
    assert {(item["symbol"], item["date"]) for item in unresolved} == {
        ("SPY", "2026-09-01"), ("SPY", "2026-09-02")}
    assert {(item["date"], item["injected_volume"],
             item["source_archive_content_sha256"]) for item in unresolved} == {
        ("2026-09-01", 41126315.0,
         "7a6a3aaf54fbbba4c4af5ec45ea64a664ede0be252bd85b2d7ec4eedb6ca8764"),
        ("2026-09-02", 29566216.0,
         "7a6a3aaf54fbbba4c4af5ec45ea64a664ede0be252bd85b2d7ec4eedb6ca8764"),
    }
    assert {(item["symbol"], item["date"])
            for item in artifact["shared_bar_snapshot"][
                "unresolved_keys_still_blocked_for_integrity_consumers"]} == {
                    ("SPY", "2026-09-01"), ("SPY", "2026-09-02")}
    snapshot_keys = {(item["symbol"], item["date"])
                     for item in artifact["shared_bar_snapshot"]["bars"]}
    assert {("SPY", "2026-09-01"), ("SPY", "2026-09-02")} <= snapshot_keys
    assert artifact["same_shared_bar_snapshot"]["does_not_establish"].startswith("integrity")
    assert artifact["volume_only_runtime_precondition"] == {
        "status": "passed",
        "resolved_key_count": 16,
        "resolution_difference_fields": ["volume"],
        "unresolved_difference_fields": ["volume"],
        "bearing_pending_symbols": ["CRM", "CSCO", "DE", "HD", "INTU", "NVDA", "TGT", "WMT"],
        "spy_is_benchmark_not_holding": True,
        "runtime_price_fields": {"entry": "open", "mark_to_market": "close"},
        "volume_enters_book_or_nav": False,
        "code_locations": ["qlab/qlab/llm_paper/run_round.py:149",
                           "qlab/qlab/llm_paper/run_round.py:154",
                           "qlab/qlab/events/datafetch/quotes_api.py:391"],
        "note": ("两份 RESOLUTION 与剩余 SPY 分歧字段全部且仅 volume；build_book 只从 bar.open "
                 "构造 entry/shares，mark_to_market 只读 close，volume 不进入 book/NAV。"),
    }
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

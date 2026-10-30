"""Committed runtime gaps are evidence records, never fabricated rounds."""
from __future__ import annotations

import json
from pathlib import Path


def test_20260907_session_limit_is_recorded_as_non_backfillable_failed_run():
    repo_root = Path(__file__).resolve().parents[2]
    record = json.loads((repo_root / "qlab" / "reports" / "llm_paper" / "runtime_gaps" /
                         "RUN_GAP_20260907_session_limit.json").read_text(encoding="utf-8"))

    assert record["schema"] == "llm_paper_runtime_gap/v1"
    assert record["run_evidence"]["status"] == "failed"
    assert record["run_evidence"]["result"] is None
    assert record["gap"]["classification"] == "permanent_missing_forward_round"
    assert record["gap"]["classified_as_market_holiday_skip"] is False
    assert record["gap"]["backfill_allowed"] is False
    assert record["gap"]["retry_or_manual_trigger_performed"] is False
    assert record["existing_failure_monitor_coverage"]["covers_this_event"] is False
    assert not (repo_root / "qlab" / "reports" / "llm_paper" /
                "round_20260907.json").exists()

"""The archive scanner has a scheduler-safe CLI, not only a library API."""
from __future__ import annotations

import json

from tools import run_llm_paper_archive_scan as cli


def test_cli_reports_clean_scan(monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan_missing_archive_bars", lambda *_args, **_kwargs: {
        "requested_symbols": [],
        "coverage_after": {"missing_count": 0, "oldest_missing": None, "hard_alerts": []},
        "scan_report": {"file": "scan.json"}, "alert": None,
    })
    assert cli.main(["--out-dir", "reports", "--stamp", "2026-09-02"]) == cli.EXIT_CLEAN
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "clean" and report["coverage"]["missing_count"] == 0


def test_cli_returns_distinct_capture_alert_and_failure_codes(monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan_missing_archive_bars", lambda *_args, **_kwargs: {
        "requested_symbols": ["CAT"],
        "coverage_after": {"missing_count": 1, "oldest_missing": {"remaining_trading_days": 19},
                           "hard_alerts": [{"symbol": "CAT"}]},
        "scan_report": {"file": "scan.json"}, "alert": {"file": "alert.json"},
    })
    assert cli.main([]) == cli.EXIT_HARD_ALERT
    assert json.loads(capsys.readouterr().out)["status"] == "hard_alert"

    monkeypatch.setattr(cli, "scan_missing_archive_bars", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("vendor unavailable")))
    assert cli.main([]) == cli.EXIT_FAILED
    assert json.loads(capsys.readouterr().out)["error_type"] == "RuntimeError"

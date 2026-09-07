"""The archive scanner has a scheduler-safe CLI, not only a library API."""
from __future__ import annotations

import json
from urllib.parse import quote_plus

import pytest

from tools import run_llm_paper_archive_scan as cli


@pytest.fixture(autouse=True)
def _scanner_key_is_already_process_local(monkeypatch):
    """Unit tests never read the host credential file."""
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "unit-test-key")


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
        "coverage_after": {"missing_count": 0, "oldest_missing": None, "hard_alerts": []},
        "scan_report": {"file": "scan.json"}, "alert": None,
    })
    assert cli.main(["--stamp", "2026-09-02"]) == cli.EXIT_CAPTURED
    assert json.loads(capsys.readouterr().out)["status"] == "captured"

    monkeypatch.setattr(cli, "scan_missing_archive_bars", lambda *_args, **_kwargs: {
        "requested_symbols": ["CAT"],
        "coverage_after": {"missing_count": 1, "oldest_missing": {"remaining_trading_days": 19},
                           "hard_alerts": [{"symbol": "CAT"}]},
        "scan_report": {"file": "scan.json"}, "alert": {"file": "alert.json"},
    })
    assert cli.main(["--stamp", "2026-09-02"]) == cli.EXIT_HARD_ALERT
    assert json.loads(capsys.readouterr().out)["status"] == "hard_alert"

    monkeypatch.setattr(cli, "scan_missing_archive_bars", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        cli.ScanDayRefused("归档扫描只能在非轮次日（周二至周五）运行")))
    assert cli.main(["--stamp", "2026-09-07"]) == cli.EXIT_REFUSED_NON_SCAN_DAY
    assert json.loads(capsys.readouterr().out)["status"] == "refused_non_scan_day"

    monkeypatch.setattr(cli, "scan_missing_archive_bars", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("vendor unavailable")))
    assert cli.main(["--stamp", "2026-09-02"]) == cli.EXIT_FAILED
    report = json.loads(capsys.readouterr().out)
    assert report["error_type"] == "RuntimeError"
    assert "coverage" in report


def test_cli_loads_only_the_scanner_key_from_owner_only_file(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / "api.env"
    env_file.write_text("IGNORED=value\nexport ALPHAVANTAGE_API_KEY='process-only-secret'\n",
                        encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY")
    monkeypatch.setattr(cli, "_API_ENV_FILE", env_file)

    def fake_scan(*_args, **_kwargs):
        assert cli.os.environ["ALPHAVANTAGE_API_KEY"] == "process-only-secret"
        assert "IGNORED" not in cli.os.environ
        return {"requested_symbols": [], "coverage_after": {
            "missing_count": 0, "oldest_missing": None, "hard_alerts": [],
            "ageing_clock": {"status": "complete_no_missing_keys"}},
            "scan_report": {"file": "scan.json"}, "alert": None}

    monkeypatch.setattr(cli, "scan_missing_archive_bars", fake_scan)
    assert cli.main(["--out-dir", str(tmp_path), "--stamp", "2026-09-02"]) == cli.EXIT_CLEAN
    output = capsys.readouterr().out
    assert "process-only-secret" not in output
    assert json.loads(output)["coverage"]["ageing_clock"]["status"] == "complete_no_missing_keys"


def test_cli_refuses_group_readable_key_file_without_leaking_value(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / "api.env"
    env_file.write_text("ALPHAVANTAGE_API_KEY=must-not-leak", encoding="utf-8")
    env_file.chmod(0o640)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY")
    monkeypatch.setattr(cli, "_API_ENV_FILE", env_file)
    monkeypatch.setattr(cli, "archive_scan_coverage", lambda *_args, **_kwargs: {
        "missing_count": 0, "oldest_missing": None, "hard_alerts": [],
        "ageing_clock": {"status": "complete_no_missing_keys"}})

    assert cli.main(["--out-dir", str(tmp_path), "--stamp", "2026-09-02"]) == cli.EXIT_FAILED
    output = capsys.readouterr().out
    assert "must-not-leak" not in output
    assert json.loads(output)["error_type"] == "ApiEnvConfigError"


def test_exit_40_refusal_precedes_credential_loading(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / "api.env"
    env_file.write_text("ALPHAVANTAGE_API_KEY=must-not-load", encoding="utf-8")
    env_file.chmod(0o640)  # would be exit 30 on an eligible scan day
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY")
    monkeypatch.setattr(cli, "_API_ENV_FILE", env_file)

    assert cli.main(["--out-dir", str(tmp_path), "--stamp", "2026-09-07"]) == \
        cli.EXIT_REFUSED_NON_SCAN_DAY
    output = capsys.readouterr().out
    assert "must-not-load" not in output
    assert json.loads(output)["status"] == "refused_non_scan_day"
    assert "ALPHAVANTAGE_API_KEY" not in cli.os.environ


def test_exit_30_redacts_scanner_and_coverage_errors_before_truncation(
        monkeypatch, tmp_path, capsys):
    fake_key = "fixture-lower+part/end=42"
    encoded_key = quote_plus(fake_key)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", fake_key)
    monkeypatch.setattr(
        cli, "scan_missing_archive_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("x" * 130 + " url=https://example.invalid/query?apikey=" + encoded_key)),
    )
    monkeypatch.setattr(
        cli, "archive_scan_coverage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("coverage url=https://example.invalid/query?apikey=" + encoded_key)),
    )

    assert cli.main(["--out-dir", str(tmp_path), "--stamp", "2026-09-02"]) == \
        cli.EXIT_FAILED
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    serialised = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "failed" and report["exit_code"] == cli.EXIT_FAILED
    assert len(report["error"]) <= cli._FAILURE_SUMMARY_LIMIT
    assert fake_key not in serialised
    assert encoded_key not in serialised
    assert fake_key[:8] not in serialised
    assert encoded_key[:8] not in serialised
    assert "<redacted-api-key>" in serialised
    assert captured.err == ""


def test_cli_output_scrubs_an_already_truncated_key_parameter(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "scan_missing_archive_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("upstream failed: apikey=recognisable-prefix")),
    )
    monkeypatch.setattr(cli, "archive_scan_coverage", lambda *_args, **_kwargs: {})

    assert cli.main(["--stamp", "2026-09-02"]) == cli.EXIT_FAILED
    output = capsys.readouterr().out
    assert "recognisable-prefix" not in output
    assert "<redacted-api-key>" in output

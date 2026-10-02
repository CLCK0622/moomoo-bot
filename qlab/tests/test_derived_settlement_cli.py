"""The derived settlement CLI stays offline and reports both artifact summaries."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import run_llm_paper_derived_settlement as cli


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_cli_materializes_settlement_and_equivalence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_resolve_out_dir", lambda _value: tmp_path)
    for relative in ("round_20260831.json", "control_multi_book/round_20260831.json",
                     "CONTROL_20260831.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_git", lambda *args: (
        _Proc("head\n") if args == ("rev-parse", "HEAD") else _Proc()))
    monkeypatch.setattr(cli, "_last_commit", lambda _paths: "evidence")
    monkeypatch.setattr(cli, "_records_unchanged", lambda _paths, _commit: True)
    monkeypatch.setattr(cli, "load_anchor", lambda: {"freeze_sha": "freeze"})
    monkeypatch.setattr(cli, "rebuild_derived_equivalence", lambda *_args, **_kwargs: {
        "prepared": True})
    monkeypatch.setattr(cli, "write_lower_bound_settlement", lambda *_args, **_kwargs: {
        "settlement_file": "SETTLEMENT.json", "content_sha256": "settlement-hash",
        "input_manifest_sha256": "input-hash",
        "implementation_version": "implementation-v2",
        "implementation_source_sha256": "implementation-source-hash",
        "payload": {"summary": {"status": "partial"}},
    })
    monkeypatch.setattr(cli, "write_settlement_invocation", lambda *_args, **_kwargs: {
        "invocation_file": "INVOCATION.json", "content_sha256": "invocation-hash",
    })
    monkeypatch.setattr(cli, "write_derived_equivalence", lambda *_args, **_kwargs: {
        "equivalence_file": "EQUIVALENCE.json", "content_sha256": "equivalence-hash",
        "payload": {"summary": {"may_take_over": False}},
    })

    assert cli.main(["--out-dir", "reports", "--equivalence-round", "20260831",
                     "--evidence-commit", "evidence"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "equivalence_content_sha256": "equivalence-hash",
        "equivalence_file": "EQUIVALENCE.json",
        "equivalence_summary": {"may_take_over": False},
        "settlement_content_sha256": "settlement-hash",
        "settlement_file": "SETTLEMENT.json",
        "settlement_implementation_version": "implementation-v2",
        "settlement_implementation_source_sha256": "implementation-source-hash",
        "settlement_input_manifest_sha256": "input-hash",
        "settlement_summary": {"status": "partial"},
        "invocation_branch_head_commit": "head",
        "invocation_content_sha256": "invocation-hash",
        "invocation_file": "INVOCATION.json",
    }


def test_records_unchanged_checks_unstaged_staged_and_evidence_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_REPO_ROOT", tmp_path)

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True,
                              text=True, capture_output=True)

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    record = tmp_path / "record.json"
    record.write_text('{"version": 1}\n', encoding="utf-8")
    git("add", "record.json")
    git("commit", "-m", "evidence")
    evidence_commit = git("rev-parse", "HEAD").stdout.strip()
    assert cli._records_unchanged([record], evidence_commit) is True

    record.write_text('{"version": 2}\n', encoding="utf-8")
    assert cli._records_unchanged([record], evidence_commit) is False
    git("add", "record.json")
    assert cli._records_unchanged([record], evidence_commit) is False
    git("commit", "-m", "changed after evidence")
    assert cli._records_unchanged([record], evidence_commit) is False
    current_commit = git("rev-parse", "HEAD").stdout.strip()
    assert cli._records_unchanged([record], current_commit) is True

    # Only the cached-diff guard can reject this state: HEAD is the old base,
    # while both index and worktree contain the exact bytes of the later named
    # evidence commit.  Removing `git diff --cached` makes this assertion fail.
    git("switch", "--detach", evidence_commit)
    record.write_text('{"version": 2}\n', encoding="utf-8")
    git("add", "record.json")
    assert cli._git("diff", "--quiet", "--", "record.json").returncode == 0
    assert cli._git("diff", "--quiet", current_commit, "--", "record.json").returncode == 0
    assert cli._git("diff", "--cached", "--quiet", "--", "record.json").returncode != 0
    assert cli._records_unchanged([record], current_commit) is False


def test_records_outside_repository_fail_closed(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_REPO_ROOT", repo)
    assert cli._last_commit([outside]) is None
    assert cli._records_unchanged([outside], "abc") is False


def test_cli_rejects_missing_equivalence_inputs_before_any_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_resolve_out_dir", lambda _value: tmp_path)
    called = []
    monkeypatch.setattr(cli, "write_lower_bound_settlement",
                        lambda *_args, **_kwargs: called.append("settlement"))
    with pytest.raises(SystemExit):
        cli.main(["--out-dir", str(tmp_path), "--equivalence-round", "20260831"])
    assert called == []


def test_out_dir_resolution_is_stable_from_repo_root_or_qlab(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    qlab = repo / "qlab"
    reports = qlab / "reports" / "llm_paper"
    reports.mkdir(parents=True)
    monkeypatch.setattr(cli, "_REPO_ROOT", repo)
    monkeypatch.setattr(cli, "_QLAB_ROOT", qlab)

    monkeypatch.chdir(repo)
    assert cli._resolve_out_dir("qlab/reports/llm_paper") == reports.resolve()
    monkeypatch.chdir(qlab)
    assert cli._resolve_out_dir("qlab/reports/llm_paper") == reports.resolve()
    assert cli._resolve_out_dir("reports/llm_paper") == reports.resolve()
    assert cli._resolve_out_dir(str(reports.resolve())) == reports.resolve()

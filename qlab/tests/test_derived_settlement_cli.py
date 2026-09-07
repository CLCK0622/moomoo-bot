"""The derived settlement CLI stays offline and reports both artifact summaries."""
from __future__ import annotations

import json
import subprocess

from tools import run_llm_paper_derived_settlement as cli


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_cli_materializes_settlement_and_equivalence(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", lambda *args: (
        _Proc("head\n") if args == ("rev-parse", "HEAD") else _Proc()))
    monkeypatch.setattr(cli, "_last_commit", lambda _paths: "evidence")
    monkeypatch.setattr(cli, "_records_unchanged", lambda _paths, _commit: True)
    monkeypatch.setattr(cli, "load_anchor", lambda: {"freeze_sha": "freeze"})
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

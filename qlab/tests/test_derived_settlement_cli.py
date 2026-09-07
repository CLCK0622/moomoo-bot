"""The derived settlement CLI stays offline and reports both artifact summaries."""
from __future__ import annotations

import json

from tools import run_llm_paper_derived_settlement as cli


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def test_cli_materializes_settlement_and_equivalence(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_git", lambda *args: (
        _Proc("head\n") if args == ("rev-parse", "HEAD") else _Proc()))
    monkeypatch.setattr(cli, "_last_commit", lambda _paths: "evidence")
    monkeypatch.setattr(cli, "_records_unchanged", lambda _paths: True)
    monkeypatch.setattr(cli, "load_anchor", lambda: {"freeze_sha": "freeze"})
    monkeypatch.setattr(cli, "write_lower_bound_settlement", lambda *_args, **_kwargs: {
        "settlement_file": "SETTLEMENT.json", "content_sha256": "settlement-hash",
        "payload": {"summary": {"status": "partial"}},
    })
    monkeypatch.setattr(cli, "write_derived_equivalence", lambda *_args, **_kwargs: {
        "equivalence_file": "EQUIVALENCE.json", "content_sha256": "equivalence-hash",
        "payload": {"summary": {"may_take_over": False}},
    })

    assert cli.main(["--out-dir", "reports", "--equivalence-round", "20260831"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "equivalence_content_sha256": "equivalence-hash",
        "equivalence_file": "EQUIVALENCE.json",
        "equivalence_summary": {"may_take_over": False},
        "settlement_content_sha256": "settlement-hash",
        "settlement_file": "SETTLEMENT.json",
        "settlement_summary": {"status": "partial"},
        "source_commit": "head",
    }

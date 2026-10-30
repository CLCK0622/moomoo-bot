"""External-anchor parity and R1 regressions on isolated synthetic copies."""

import io
import json
import shutil
import subprocess
import sys
from contextlib import redirect_stdout

from .authority_ledger import AuthorityLedger, FIXTURES, PUBLISHED, TOOL_SHA
from .contract import canonical, digest, sha256
from .harness_helpers import fixture_ledger
from .ledger import AttemptLedger


def cases(workdir, policy):
    reports = []
    source = FIXTURES / "EVO891-B-ledger-v2.jsonl"
    tip = FIXTURES / "EVO891-B-ledger-v2.tip.json"
    ours = AuthorityLedger(source, tip).verify()
    tool = FIXTURES / "EVO891-B-ledger-v2.py"
    assert sha256(tool.read_bytes()) == TOOL_SHA
    child = subprocess.run(
        [
            sys.executable,
            str(tool),
            "verify",
            str(source),
            str(tip),
            "--expect-tip",
            PUBLISHED["tip"],
            "--expect-sequence",
            "20",
            "--expect-high-water",
            "75",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child.returncode == 0 and json.loads(child.stdout) == ours
    reports.append(
        {
            "case_id": "ledger.authority_vendor_parity",
            "status": "PASS",
            "observed": ours,
            "strategy_performance_read": False,
        }
    )
    local, witness = workdir / "authority-unit.jsonl", workdir / "authority-tip.json"
    shutil.copyfile(source, local)
    shutil.copyfile(tip, witness)
    writer = AuthorityLedger(local, witness, writable=True)
    before = local.read_bytes(), witness.read_bytes()
    writer.external_anchor["tip"] = "0" * 64
    try:
        writer.append({"event": "attempt"})
    except ValueError as exc:
        assert "external_anchor" in str(exc)
    else:
        raise AssertionError("wrong authority anchor allowed append")
    assert (local.read_bytes(), witness.read_bytes()) == before
    reports.append(
        {
            "case_id": "ledger.external_anchor_mismatch_append",
            "status": "PASS",
            "observed": {"rejected_before_mutation": True},
        }
    )

    old = fixture_ledger(workdir / "r1-old.sqlite", policy)
    old.begin("seen", {})
    old.observe_self_report_n(500)
    original = old.path.read_bytes(), old.anchor_path.read_bytes()
    reset, reset_tip = workdir / "r1-reset.sqlite", workdir / "r1-reset-tip.json"
    receipt = dict(
        action="bootstrap",
        target=str(reset.resolve()),
        genesis_sha256=digest(old.genesis),
        ledger_id=json.loads(old.anchor_path.read_bytes())["ledger_id"],
        authority_source={
            "reference": "SYNTHETIC_UNIT_REPLAY",
            "sha256": digest("synthetic_bootstrap"),
        },
    )
    try:
        AttemptLedger.from_conventions(
            reset, policy, anchor_path=reset_tip, bootstrap_receipt=receipt
        )
    except ValueError as exc:
        assert str(exc) == "ledger.formal_bootstrap_or_anchor_override_forbidden"
    else:
        raise AssertionError("retargeted bootstrap accepted")
    reports.append(
        {
            "case_id": "audit.new_reset_retargeted_bootstrap",
            "status": "PASS",
            "synthetic_only": True,
            "observed": {"refused": True, "old_high_water": 500},
        }
    )
    from .__main__ import main
    from .conventions import FIXTURES as CONVENTIONS

    request_file, receipt_file = (
        workdir / "r1-request.json",
        workdir / "r1-bootstrap.json",
    )
    request_file.write_bytes(canonical({"metrics": {}}))
    receipt_file.write_bytes(canonical(receipt))
    argv = sys.argv
    try:
        sys.argv = [
            "qlab.dynamic_factor",
            "dsr_eval",
            "--input",
            str(request_file),
            "--ledger",
            str(reset),
            "--ledger-anchor",
            str(reset_tip),
            "--ledger-bootstrap",
            str(receipt_file),
            "--conventions",
            str(CONVENTIONS / "conventions-v1.0.1.json"),
        ]
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main()
        report = json.loads(stdout.getvalue())
        assert code == 2 and report["reasons"] == [
            "ledger.formal_bootstrap_or_anchor_override_forbidden"
        ]
    finally:
        sys.argv = argv
    assert not reset.exists() and not reset_tip.exists()
    assert (old.path.read_bytes(), old.anchor_path.read_bytes()) == original
    reports.append(
        {
            "case_id": "audit.CLI_retargeted_bootstrap",
            "status": "PASS",
            "synthetic_only": True,
            "observed": {
                "refused_before_creation": True,
                "source_witness_unchanged": True,
            },
        }
    )
    return reports

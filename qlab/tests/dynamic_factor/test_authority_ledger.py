import json
import shutil
import subprocess
import sys
from copy import deepcopy

import pytest

from qlab.dynamic_factor.authority_ledger import (
    AuthorityLedger,
    FIXTURES,
    PUBLISHED,
    SOURCE_SHA,
    TOOL_SHA,
)
from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.statistics import dsr_eval


def authority_copy(root):
    root.mkdir(parents=True)
    ledger, tip = root / "ledger.jsonl", root / "tip.json"
    shutil.copyfile(FIXTURES / "EVO891-B-ledger-v2.jsonl", ledger)
    shutil.copyfile(FIXTURES / "EVO891-B-ledger-v2.tip.json", tip)
    return ledger, tip


def vendor(ledger, tip, expected_tip):
    r = subprocess.run(
        [
            sys.executable,
            str(FIXTURES / "EVO891-B-ledger-v2.py"),
            "verify",
            str(ledger),
            str(tip),
            "--expect-tip",
            expected_tip,
            "--expect-sequence",
            "20",
            "--expect-high-water",
            "75",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def attempt(aid="SYNTHETIC_UNIT_ATTEMPT"):
    return dict(
        event="attempt",
        attempt_id=aid,
        run_id="SYNTHETIC_NOT_A_RUN",
        n_trials_total=1,
        n_evaluated=0,
        n_contribution=1,
        scope_labels=["synthetic_unit"],
        evidence=[dict(path="unit-receipt", sha256=digest("unit"))],
    )


def test_published_authority_matches_vendor_every_state_field():
    ledger, tip = (
        FIXTURES / "EVO891-B-ledger-v2.jsonl",
        FIXTURES / "EVO891-B-ledger-v2.tip.json",
    )
    assert sha256(ledger.read_bytes()) == SOURCE_SHA
    assert sha256((FIXTURES / "EVO891-B-ledger-v2.py").read_bytes()) == TOOL_SHA
    ours = AuthorityLedger(ledger, tip).verify()
    assert ours == vendor(ledger, tip, PUBLISHED["tip"])
    assert ours["N"] == 75 and all(ours[k] == v for k, v in PUBLISHED.items())
    r = dsr_eval({}, AuthorityLedger(ledger, tip), conventions=load_conventions())
    assert (
        r["metrics"]["recorded_N"] == 75
        and r["metrics"]["authority_tip"] == PUBLISHED["tip"]
    )
    assert r["metrics"]["cumulative_n"] is None and r["metrics"]["dsr"] is None
    assert not r["certifiable"]


def test_valid_append_continues_published_prefix_and_matches_vendor(tmp_path):
    ledger, tip = authority_copy(tmp_path / "unit")
    original = ledger.read_bytes()
    writer = AuthorityLedger(ledger, tip, writable=True)
    cur = writer.append(attempt())
    assert cur["N"] == 76 and cur["sequence"] == 22
    assert ledger.read_bytes().startswith(original)
    assert cur == vendor(ledger, tip, cur["tip"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("tip", "0" * 64),
        ("ledger_id", "0" * 64),
        ("sequence", 19),
        ("n_high_water", 74),
    ],
)
def test_external_anchor_mismatch_refuses_before_append(tmp_path, field, value):
    ledger, tip = authority_copy(tmp_path / "unit")
    before = ledger.read_bytes(), tip.read_bytes()
    writer = AuthorityLedger(ledger, tip, writable=True)
    writer.external_anchor[field] = value
    with pytest.raises(ValueError, match="external_anchor"):
        writer.append(attempt())
    assert (ledger.read_bytes(), tip.read_bytes()) == before


def test_old_snapshot_replay_with_latest_witness_refuses(tmp_path):
    ledger, tip = authority_copy(tmp_path / "unit")
    old = ledger.read_bytes()
    writer = AuthorityLedger(ledger, tip, writable=True)
    writer.append(attempt())
    ledger.write_bytes(old)
    with pytest.raises(ValueError, match="tail_or_high_water"):
        writer.append(attempt("SECOND"))


def test_formal_project_location_is_fixed_and_cannot_select_another_anchor(
    tmp_path, monkeypatch
):
    from qlab.dynamic_factor import authority_ledger as module

    ledger, tip = authority_copy(tmp_path / "installed-unit-project")
    monkeypatch.setattr(module, "PROJECT_LEDGER", ledger)
    monkeypatch.setattr(module, "PROJECT_WITNESS", tip)
    p = load_conventions()
    formal = AttemptLedger.from_conventions(ledger, p)
    assert formal.snapshot()["recorded_N"] == 75
    with pytest.raises(ValueError, match="project_path_migration"):
        AttemptLedger.from_conventions(tmp_path / "reset.sqlite", p)
    with pytest.raises(ValueError, match="anchor_override_forbidden"):
        AttemptLedger.from_conventions(ledger, p, anchor_path=tip)


def test_R1_retargeted_bootstrap_rejected_by_API_and_CLI_before_mutation(tmp_path):
    p = load_conventions()
    old = fixture_ledger(tmp_path / "old.sqlite", p)
    old.begin("seen", {})
    old.observe_self_report_n(500)
    witness = json.loads(old.anchor_path.read_bytes())
    source_before = old.path.read_bytes(), old.anchor_path.read_bytes()
    reset = tmp_path / "new.sqlite"
    receipt = dict(
        action="bootstrap",
        target=str(reset.resolve()),
        genesis_sha256=digest(old.genesis),
        ledger_id=witness["ledger_id"],
        authority_source=dict(
            reference="SYNTHETIC_UNIT_REPLAY", sha256=digest("synthetic_bootstrap")
        ),
    )
    new_tip = tmp_path / "new-tip.json"
    with pytest.raises(
        ValueError, match="formal_bootstrap_or_anchor_override_forbidden"
    ):
        AttemptLedger.from_conventions(
            reset, p, anchor_path=new_tip, bootstrap_receipt=deepcopy(receipt)
        )
    request, bootstrap = tmp_path / "request.json", tmp_path / "bootstrap.json"
    request.write_text('{"metrics":{}}')
    bootstrap.write_text(json.dumps(receipt))
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlab.dynamic_factor",
            "dsr_eval",
            "--input",
            str(request),
            "--conventions",
            str(
                __import__(
                    "qlab.dynamic_factor.conventions", fromlist=["FIXTURES"]
                ).FIXTURES
                / "conventions-v1.0.1.json"
            ),
            "--ledger",
            str(reset),
            "--ledger-anchor",
            str(new_tip),
            "--ledger-bootstrap",
            str(bootstrap),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2 and json.loads(r.stdout)["reasons"] == [
        "ledger.formal_bootstrap_or_anchor_override_forbidden"
    ]
    assert not reset.exists() and not new_tip.exists()
    assert (old.path.read_bytes(), old.anchor_path.read_bytes()) == source_before

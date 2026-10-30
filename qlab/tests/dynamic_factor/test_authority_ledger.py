import json
import shutil
import subprocess
import sys
from copy import deepcopy

import pytest

from qlab.dynamic_factor.authority_ledger import (
    AuthorityLedger,
    CURRENT_FIXTURES,
    CURRENT_PUBLISHED,
    CURRENT_SOURCE_SHA,
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


def authority_copy(root, latest=False):
    root.mkdir(parents=True)
    ledger, tip = root / "ledger.jsonl", root / "tip.json"
    src = CURRENT_FIXTURES if latest else FIXTURES
    version = "v4" if latest else "v2"
    shutil.copyfile(src / f"EVO891-B-ledger-{version}.jsonl", ledger)
    shutil.copyfile(src / f"EVO891-B-ledger-{version}.tip.json", tip)
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

    ledger, tip = authority_copy(tmp_path / "installed-unit-project", latest=True)
    monkeypatch.setattr(module, "PROJECT_LEDGER", ledger)
    monkeypatch.setattr(module, "PROJECT_WITNESS", tip)
    p = load_conventions()
    formal = AttemptLedger.from_conventions(ledger, p)
    assert formal.snapshot()["recorded_N"] == 280
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


def test_current_published_v4_anchor_matches_vendor_and_keeps_complete_N_null(tmp_path):
    ledger, tip = authority_copy(tmp_path / "current", latest=True)
    assert sha256(ledger.read_bytes()) == CURRENT_SOURCE_SHA
    current = AuthorityLedger(ledger, tip, external_anchor=CURRENT_PUBLISHED)
    cur = current.verify()
    assert cur == vendor(ledger, tip, CURRENT_PUBLISHED["tip"])
    assert cur["N"] == 280 and cur["sequence"] == 182
    assert (
        current.snapshot()["is_current_authority"]
        and current.snapshot()["complete_N"] is None
    )


def test_formal_entry_rejects_old_75_snapshot_even_with_matching_retained_old_witness(
    tmp_path, monkeypatch
):
    from qlab.dynamic_factor import authority_ledger as module

    ledger, tip = authority_copy(tmp_path / "stale")
    assert AuthorityLedger(ledger, tip).verify()["N"] == 75  # Historical read only.
    monkeypatch.setattr(module, "PROJECT_LEDGER", ledger)
    monkeypatch.setattr(module, "PROJECT_WITNESS", tip)
    with pytest.raises(ValueError, match="external_anchor_mismatch"):
        AuthorityLedger(ledger, tip)
    with pytest.raises(ValueError, match="external_anchor_mismatch"):
        AttemptLedger.from_conventions(ledger, load_conventions())


def test_formal_reader_reloads_new_controlled_witness_without_source_change(
    tmp_path, monkeypatch
):
    from qlab.dynamic_factor import authority_ledger as module

    ledger, tip = authority_copy(tmp_path / "installed", latest=True)
    later, later_tip = authority_copy(tmp_path / "authority-unit", latest=True)
    published = tmp_path / "published.json"
    published.write_bytes(tip.read_bytes())
    monkeypatch.setattr(module, "PROJECT_LEDGER", ledger)
    monkeypatch.setattr(module, "PROJECT_WITNESS", tip)
    monkeypatch.setattr(module, "CURRENT_WITNESS_INPUT", published)
    reader = AuthorityLedger.open_project(ledger)
    before = reader.verify()
    future = AuthorityLedger(later, later_tip, writable=True).append(attempt())
    published.write_bytes(later_tip.read_bytes())
    original = ledger.read_bytes(), tip.read_bytes()
    with pytest.raises(ValueError, match="external_anchor_mismatch"):
        reader.verify()
    assert (ledger.read_bytes(), tip.read_bytes()) == original
    ledger.write_bytes(later.read_bytes())
    tip.write_bytes(later_tip.read_bytes())
    assert reader.verify() == future
    assert future["N"] == before["N"] + 1
    assert reader.snapshot()["current_published_anchor"]["tip"] == future["tip"]


@pytest.mark.parametrize(
    "mutation", [{"sequence": 20}, {"tip": "bad"}, {"n_high_water": -1}]
)
def test_invalid_or_old_controlled_witness_is_rejected(tmp_path, monkeypatch, mutation):
    from qlab.dynamic_factor import authority_ledger as module

    witness = json.loads(module.CURRENT_WITNESS_INPUT.read_bytes())
    witness.update(mutation)
    path = tmp_path / "published.json"
    path.write_text(json.dumps(witness))
    monkeypatch.setattr(module, "CURRENT_WITNESS_INPUT", path)
    with pytest.raises(ValueError, match="latest_external_witness_missing_or_invalid"):
        module.latest_external_witness()

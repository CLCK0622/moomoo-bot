import json
import sqlite3
import shutil
from dataclasses import replace

import pytest

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.harness import _wf
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.statistics import DSRPlugin, dsr_eval
from qlab.dynamic_factor.folds import run_walk_forward
from qlab.dynamic_factor.validation import wf_manifest_check


def test_formal_entry_missing_binding_rejects_before_adapters(tmp_path):
    called = []
    manifest = _wf()
    manifest.update(conventions_sha256=load_conventions().raw_sha256, embargo=0)
    r = wf_manifest_check(manifest)
    assert r["reasons"] == ["wf.conventions_required"]
    r = run_walk_forward(
        manifest,
        [],
        miner_factory=lambda c: called.append(c),
        fitter_factory=lambda c: called.append(c),
        ledger=AttemptLedger(tmp_path / "l.sqlite"),
        run_id="unit",
    )
    assert r["reasons"] == ["wf.conventions_required"] and not called


@pytest.mark.parametrize("action", ["tail", "all", "old_snapshot"])
def test_independent_tail_witness_refuses_rollback_before_read_and_append(
    tmp_path, action
):
    p = load_conventions()
    ledger = fixture_ledger(tmp_path / "l.sqlite", p)
    ledger.begin("a", {})
    shutil.copyfile(ledger.path, tmp_path / "old.sqlite")
    ledger.finish("a", "failed")
    ledger.begin("b", {})
    ledger.observe_self_report_n(500)
    if action == "old_snapshot":
        shutil.copyfile(tmp_path / "old.sqlite", ledger.path)
    else:
        with sqlite3.connect(ledger.path) as db:
            db.execute(
                "DELETE FROM events"
                if action == "all"
                else "DELETE FROM events WHERE seq>=3"
            )
    with pytest.raises(ValueError, match="tail_or_high_water"):
        ledger.snapshot()
    with pytest.raises(ValueError, match="tail_or_high_water"):
        ledger.begin("c", {})
    assert ledger.safe_snapshot()["cumulative_n"] is None


def test_new_bound_database_needs_explicit_bootstrap_or_migration_receipt(tmp_path):
    p = load_conventions()
    ledger = fixture_ledger(tmp_path / "old.sqlite", p)
    ledger.begin("seen", {})
    with pytest.raises(ValueError, match="project_path_migration_receipt_required"):
        AttemptLedger.from_conventions(tmp_path / "new.sqlite", p)
    assert not (tmp_path / "new.sqlite").exists()
    with pytest.raises(ValueError, match="formal_bootstrap_or_anchor_override"):
        AttemptLedger.from_conventions(
            tmp_path / "new.sqlite", p, anchor_path=ledger.anchor_path
        )


def test_seed_bytes_cannot_be_replaced_by_declared_sha(tmp_path):
    p = load_conventions()
    with pytest.raises(ValueError, match="seed_bytes_mismatch"):
        AttemptLedger.from_conventions(
            tmp_path / "empty.sqlite", replace(p, seed_raw=b"")
        )
    g = fixture_ledger(tmp_path / "real.sqlite", p).genesis
    with pytest.raises(ValueError, match="bound_genesis_constructor_forbidden"):
        AttemptLedger(
            tmp_path / "forged.sqlite", dict(g, prior_n=0, count_complete=True)
        )


def test_legacy_plugin_never_executes_or_certifies(tmp_path):
    called = []
    ledger = AttemptLedger(tmp_path / "l.sqlite")
    plugin = DSRPlugin(
        "fake", digest({}), digest("source"), lambda *a: called.append(a)
    )
    for policy in (None, load_conventions()):
        r = dsr_eval(
            {"sharpe": 99, "v": 0},
            ledger,
            prereg={"version": "fake"},
            plugin=plugin,
            conventions=policy,
        )
        assert r["metrics"]["dsr"] is None and r["metrics"]["trials_variance"] is None
        assert not r["certifiable"] and r["runtime_consumable"] is False and not called


def test_anchor_itself_is_not_replaced_on_read(tmp_path):
    ledger = fixture_ledger(tmp_path / "l.sqlite", load_conventions())
    ledger.begin("a", {})
    a = json.loads(ledger.anchor_path.read_bytes())
    assert a["sequence"] == 1 and a["n_high_water"] == 48
    before = ledger.anchor_path.read_bytes()
    ledger.snapshot()
    assert ledger.anchor_path.read_bytes() == before


def migration_receipt(ledger, target, anchor):
    old = json.loads(ledger.anchor_path.read_bytes())
    return {
        "action": "migrate",
        "source_anchor_sha256": sha256(ledger.anchor_path.read_bytes()),
        "ledger_id": old["ledger_id"],
        "target": str(target.resolve()),
        "target_anchor": str(anchor.resolve()),
        **{
            k: old[k]
            for k in (
                "sequence",
                "tip",
                "snapshot_sha256",
                "local_n",
                "self_report_n",
                "n_high_water",
            )
        },
        "authority_source": {
            "reference": "SYNTHETIC_UNIT_MIGRATION_ONLY",
            "sha256": digest("unit"),
        },
    }


def test_receipted_migration_preserves_identity_and_retires_original(tmp_path):
    p = load_conventions()
    ledger = fixture_ledger(tmp_path / "source.sqlite", p)
    ledger.begin("failed-attempt", {})
    ledger.finish("failed-attempt", "failed")
    ledger.observe_self_report_n(500)
    before = ledger.snapshot()
    target, anchor = tmp_path / "target.sqlite", tmp_path / "target.tip.json"
    receipt = migration_receipt(ledger, target, anchor)
    migrated = ledger.migrate(target, target_anchor=anchor, receipt=receipt)
    moved = AttemptLedger._from_fixture_conventions(target, p, anchor_path=anchor)
    assert moved.snapshot() == before
    assert migrated["n_ledger_hash"] == before["n_ledger_hash"]
    assert ledger.path.exists() and ledger.anchor_path.exists()
    with pytest.raises(ValueError, match="source_retired"):
        ledger.begin("fork", {})
    moved.begin("new-attempt", {})
    assert json.loads(anchor.read_bytes())["n_high_water"] == 500
    with pytest.raises(ValueError, match="source_retired"):
        ledger.snapshot()


def test_stale_migration_receipt_refuses_without_touching_source_or_target(tmp_path):
    ledger = fixture_ledger(tmp_path / "source.sqlite", load_conventions())
    target, anchor = tmp_path / "target.sqlite", tmp_path / "target.tip.json"
    receipt = migration_receipt(ledger, target, anchor)
    ledger.begin("after-approval", {})
    before = ledger.anchor_path.read_bytes()
    with pytest.raises(ValueError, match="receipt_required_or_stale"):
        ledger.migrate(target, target_anchor=anchor, receipt=receipt)
    assert not target.exists() and not anchor.exists()
    assert ledger.anchor_path.read_bytes() == before

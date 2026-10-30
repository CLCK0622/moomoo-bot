import json

import pytest

from qlab.dynamic_factor.contract import code_sha, digest, sha256
from qlab.dynamic_factor.fees import FIXTURES
from qlab.dynamic_factor.harness import _receipt, offline, run
from qlab.dynamic_factor.ledger import AttemptLedger, DEFAULT_GENESIS
from qlab.dynamic_factor.receipts import IntentJournal
from qlab.dynamic_factor.statistics import DSRPlugin, dsr_eval, prereg_check


def synthetic_plugin(request, snapshot, prereg):
    # Compatibility sentinel: no public DSR route may invoke it.
    return dict(dsr=0.5, trials_variance=0.0, sharpe=0.0, passed=False)


def test_missing_policy_and_authority_produce_nulls(tmp_path):
    ledger = AttemptLedger(tmp_path / "ledger.sqlite")
    r = dsr_eval({"n": 0, "v": 0, "sharpe_scale": "annualized"}, ledger)
    assert not r["certifiable"]
    assert {"prereg_missing", "ledger_authority_unset"} <= set(r["reasons"])
    for metric in ("dsr", "trials_variance", "sharpe"):
        assert r["metrics"][metric] is None
        assert r["metric_availability"][metric] == {
            "available": False,
            "reason": "prereg_missing",
        }
    assert prereg_check(None, None)["missing_inputs"] == ["prereg"]


def test_plugin_is_never_called_even_with_authority_and_matching_scale(tmp_path):
    genesis = dict(
        DEFAULT_GENESIS,
        prior_n=1,
        authority_source={"reference": "synthetic-unit-test", "sha256": "a" * 64},
    )
    ledger = AttemptLedger(tmp_path / "ledger.sqlite", genesis)
    prereg = dict(
        version="TEST ONLY",
        dsr=dict(
            formula_id="sentinel-not-dsr",
            variance_method="sentinel",
            sharpe_scale="per_period",
        ),
        fold_policy="sentinel",
        fee_params_sha256="f" * 64,
        ledger_policy="sentinel",
    )
    pin = digest(prereg)
    plugin = DSRPlugin(
        "sentinel-not-dsr", pin, code_sha(synthetic_plugin), synthetic_plugin
    )
    r = dsr_eval(
        {"sharpe_scale": "annualized"},
        ledger,
        prereg=prereg,
        prereg_sha256=pin,
        plugin=plugin,
    )
    assert (
        "dsr.runtime_bindings_pending" in r["reasons"] and r["metrics"]["dsr"] is None
    )
    r = dsr_eval(
        {"sharpe_scale": "per_period"},
        ledger,
        prereg=prereg,
        prereg_sha256=pin,
        plugin=plugin,
    )
    assert not r["certifiable"] and r["metrics"]["trials_variance"] is None
    assert r["metrics"]["passed"] is False
    r = dsr_eval(
        {"sharpe_scale": "per_period"},
        ledger,
        prereg=prereg,
        prereg_sha256="0" * 64,
        plugin=plugin,
    )
    assert not r["certifiable"] and "dsr.runtime_bindings_pending" in r["reasons"]


def test_offline_guard_rejects_network():
    import socket

    with pytest.raises(RuntimeError, match="network_disabled"):
        with offline():
            socket.create_connection(("example.invalid", 443))


def test_ten_cases_and_repeated_runs_are_identical(tmp_path):
    a = run(tmp_path / "first")
    b = run(tmp_path / "second")
    assert a == b and a["cases_passed"] == 10
    assert a["network_attempts"] == a["strategy_backtests"] == 0
    assert not a["certification"]
    assert json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(
        b, sort_keys=True, allow_nan=False
    )
    with pytest.raises(ValueError, match="must_be_empty"):
        run(tmp_path / "first")


def test_imported_fixture_hashes_match_original_attachments():
    source = json.loads((FIXTURES / "provenance.json").read_bytes())
    for name, rec in source.items():
        assert sha256((FIXTURES / name).read_bytes()) == rec["sha256"]


def test_intent_conflict_does_not_apply_new_receipt(tmp_path):
    journal = IntentJournal(tmp_path / "intents.sqlite")
    first = journal.register("one", _receipt())
    conflict = journal.register("one", _receipt(confirmed_qty=60))
    assert first["metrics"]["registered"]
    assert not conflict["metrics"]["registered"]
    assert conflict["metrics"]["intents_count"] == 1
    assert conflict["reasons"] == ["intent.receipt_conflict_requires_reconcile"]


def test_cli_nulls_exit_status_raw_hash_and_immutable_artifacts(tmp_path):
    import subprocess
    import sys

    source = tmp_path / "input.json"
    source.write_text('{"prereg": null}\n')
    out = tmp_path / "reports"
    command = [
        sys.executable,
        "-m",
        "qlab.dynamic_factor",
        "prereg_check",
        "--input",
        str(source),
        "--out-dir",
        str(out),
    ]
    a = subprocess.run(command, capture_output=True, text=True)
    assert a.returncode == 2
    report = json.loads(a.stdout)
    assert report["input_file_sha256"] == sha256(source.read_bytes())
    assert report["metrics"]["prereg_sha256"] is None
    b = subprocess.run(command, capture_output=True, text=True)
    assert b.returncode == 2 and a.stdout == b.stdout
    artifacts = list(out.glob("*.json"))
    assert len(artifacts) == 1 and json.loads(artifacts[0].read_bytes()) == report
    source.unlink()
    missing = subprocess.run(command, capture_output=True, text=True)
    assert missing.returncode == 2
    assert json.loads(missing.stdout)["input_file_sha256"] is None

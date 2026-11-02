"""Frozen public D records retain real preimages; current authority stays separate."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import runpy
import shutil
import sys
from types import SimpleNamespace

import pytest

from qlab.dynamic_factor import authority_ledger as authority, pipeline, statistics
from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor import historical_authority as historical


FIXTURES = Path(__file__).parent / "fixtures/authority-stage1"
GOLDEN = json.loads((FIXTURES / "D98-public-archive.json").read_bytes())
COMPARISON = FIXTURES / "f1-location/run_factor_compat_comparison.py.fixture"
assert (
    sha256(COMPARISON.read_bytes())
    == json.loads((COMPARISON.parent / "manifest.json").read_bytes())[COMPARISON.name][
        "sha256"
    ]
)
differences = runpy.run_path(str(COMPARISON))["differences"]


def archive(tmp_path, version):
    root = authority.FIXTURES if version == 2 else historical.HISTORICAL_V4_FIXTURES
    raw = root / f"EVO891-B-ledger-v{version}.jsonl"
    witness = root / f"EVO891-B-ledger-v{version}.tip.json"
    shutil.copyfile(raw, tmp_path / "same.jsonl")
    shutil.copyfile(witness, tmp_path / "same.tip.json")
    return authority.AuthorityLedger(
        tmp_path / "same.jsonl", tmp_path / "same.tip.json"
    )


@pytest.mark.parametrize("version", [2, 4])
@pytest.mark.parametrize(
    "entry", ["dsr_eval", "pipeline.evaluate", "run_train_pipeline"]
)
def test_three_frozen_public_entries_match_98_without_hash_exclusions(
    tmp_path, monkeypatch, version, entry, record_property
):
    expected = next(row for row in GOLDEN["cases"] if row["version"] == version)
    ledger = archive(tmp_path, version)
    before = ledger.path.read_bytes(), ledger.witness.read_bytes()
    assert sha256(before[0]) == expected["raw_sha256"]
    assert sha256(before[1]) == expected["witness_sha256"]
    policy = load_conventions()
    assert policy.raw_sha256 == GOLDEN["policy_sha256"]
    inputs = []
    original_result = statistics.result

    def capture(tool, actual_inputs, **kwargs):
        inputs.append(deepcopy(actual_inputs))
        return original_result(tool, actual_inputs, **kwargs)

    monkeypatch.setattr(statistics, "result", capture)
    calls = Counter()
    prior = sys.getprofile()

    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name in (
            "observe_self_report_n",
            "_append",
            "read_inputs",
            "read_strategy_inputs",
            "open_host_context",
            "snapshot",
            "safe_snapshot",
        ):
            calls[frame.f_code.co_name] += 1

    def forbidden(*args, **kwargs):
        calls["consumer"] += 1
        raise AssertionError("frozen diagnostics must not run a consumer")

    sys.setprofile(profile)
    try:
        if entry == "dsr_eval":
            actual = statistics.dsr_eval({}, ledger, conventions=policy)
        elif entry == "pipeline.evaluate":
            actual = pipeline.evaluate({}, ledger, policy)
        else:
            actual = pipeline.run_train_pipeline(
                policy=policy,
                ledger=ledger,
                run_id="D98-FROZEN",
                context={},
                registry=None,
                proposals=[],
                self_report_n=1313,
                probe=forbidden,
                calibrate=forbidden,
                build_meta=forbidden,
            )
    finally:
        sys.setprofile(prior)
    raw_diff = differences(expected["reports"][entry], actual)
    non_source = [
        row
        for row in raw_diff
        if row["pointer"] not in ("/source_files", "/source_sha256")
        and not row["pointer"].startswith("/source_files/")
    ]
    record_property("D_public_actual", json.dumps(actual, sort_keys=True))
    record_property("D_public_raw_diff", json.dumps(raw_diff, sort_keys=True))
    record_property("D_public_calls", json.dumps(calls, sort_keys=True))
    record_property("D_public_preimages", json.dumps(inputs, sort_keys=True))
    assert non_source == [], non_source
    assert all(
        calls[key] == 0
        for key in (
            "observe_self_report_n",
            "_append",
            "read_inputs",
            "read_strategy_inputs",
            "open_host_context",
            "consumer",
            "snapshot",
            "safe_snapshot",
        )
    )
    assert before == (ledger.path.read_bytes(), ledger.witness.read_bytes())
    if entry == "run_train_pipeline":
        assert inputs == []
    else:
        assert len(inputs) == 1
        # Complete original records are consumed, not a filtered current view.
        assert inputs[0]["ledger"] == expected["snapshot"]
        assert actual["input_sha256"] == digest(inputs[0])
        assert actual["runtime_consumable"] is actual["certifiable"] is False


@pytest.mark.parametrize("version", [2, 4])
def test_legacy_diagnostic_record_cannot_replace_current_snapshot(tmp_path, version):
    ledger = archive(tmp_path, version)
    old = historical.historical_diagnostic_snapshot(ledger)
    current = ledger.snapshot()
    assert old == next(
        row["snapshot"] for row in GOLDEN["cases"] if row["version"] == version
    )
    assert current["current_published_anchor"] is None
    assert current["historical_published_anchor"] == old["current_published_anchor"]
    assert current["is_current_authority"] is False
    assert current["complete_N"] is None
    formal = ledger.arm_readout("EVO883_FACTOR")
    assert formal["metrics"]["cumulative_n"] is None
    assert formal["reasons"]


def test_canonical_project_never_uses_historical_diagnostic_fallback(monkeypatch):
    ledger = object.__new__(authority.AuthorityLedger)
    ledger.path = authority.PROJECT_LEDGER

    def forbidden():
        raise AssertionError("historical fallback on canonical project")

    monkeypatch.setattr(historical, "historical_v4_witness", forbidden)
    with pytest.raises(ValueError, match="historical_diagnostic_only"):
        historical.historical_diagnostic_snapshot(ledger)


@pytest.mark.parametrize("ready", [False, True])
def test_helper_omission_remains_formal_refusal_without_any_ledger_operation(ready):
    calls = []

    class NeverRead:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("helper consumed the caller ledger")

    policy = SimpleNamespace(document={"runtime_consumable": ready})
    actual = pipeline._n_snapshot(NeverRead(), 1313, policy)
    assert actual["gate_n"] is actual["n_ledger_hash"] is None
    assert actual["n_complete"] is False
    assert actual["reasons"] == ["arm_n.arm_tag_missing_or_invalid"]
    assert calls == []

"""Integration negatives use verified fixture ledgers and public DSR/readout paths."""

import json
import shutil
import sys
from copy import deepcopy

import pytest

from qlab.dynamic_factor import authority_ledger, __main__ as cli
from qlab.dynamic_factor.arm_n import configuration_id, event
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import FIXTURES, load_conventions
from qlab.dynamic_factor.dsr_v0 import evaluate as legacy_evaluate
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.pipeline import _n_snapshot, evaluate, run_train_pipeline
from qlab.dynamic_factor.statistics import dsr_eval


FACTOR, LLM = "EVO883_FACTOR", "EVO896_LLMCLI"
CONFIG = dict(
    prompt_version="fixture-p1",
    model_snapshot="fixture-model",
    parameters={},
    ruleset="fixture-r1",
)


def write(ledger, kind, arm=FACTOR, config=None, **fields):
    ledger.record(
        str(len(ledger.snapshot()["events"])),
        event(kind, arm, CONFIG if config is None else config, **fields),
    )


def evaluated(ledger, arm=FACTOR, config=None):
    write(ledger, "configuration_reserved", arm, config)
    for i in range(2):
        write(
            ledger,
            "market_outcome_evaluated",
            arm,
            config,
            evaluation_id=str(i),
            evidence_sha256=digest([arm, config, i]),
        )


def reports(ledger, tag):
    witness = (
        ledger.anchor_path if isinstance(ledger, AttemptLedger) else ledger.witness
    )
    before = ledger.path.read_bytes(), witness.read_bytes()
    request = {} if tag is None else {"arm_tag": tag}
    readout = ledger.arm_readout(tag)
    dsr = dsr_eval(request, ledger)
    pipeline = _n_snapshot(ledger, 10**9, tag)
    assert before == (ledger.path.read_bytes(), witness.read_bytes())
    assert readout["metrics"]["arm_n"] == dsr["metrics"]["arm_n"] == pipeline["arm_n"]
    assert (
        readout["metrics"]["N_rows"] == dsr["metrics"]["N_rows"] == pipeline["N_rows"]
    )
    assert (
        not readout["certifiable"]
        and not dsr["certifiable"]
        and not pipeline["n_complete"]
    )
    assert (
        dsr["metrics"]["dsr"]
        is dsr["metrics"]["trials_variance"]
        is pipeline["gate_n"]
        is None
    )
    return dsr["metrics"]["arm_n"]


def test_other_arm_outcomes_cannot_inflate_factor_N_and_requests_are_separate(tmp_path):
    ledger = AttemptLedger(tmp_path / "fixture.sqlite")
    evaluated(ledger)
    # A reserved configuration without observed outcomes is not a market trial.
    write(
        ledger, "configuration_reserved", config=dict(CONFIG, ruleset="document-only")
    )
    for i in range(3):
        evaluated(ledger, LLM, dict(CONFIG, parameters={"variant": i}))
    for arm, count in ((FACTOR, 2), (LLM, 7)):
        for i in range(count):
            config = (
                CONFIG if arm == FACTOR else dict(CONFIG, parameters={"variant": 0})
            )
            write(
                ledger,
                "generation_request",
                arm,
                config,
                actual_request_id=arm + str(i),
                request_count_known=True,
                status="failed" if i == 0 else "success",
                evidence_sha256=digest([arm, i]),
            )
    factor, llm = reports(ledger, FACTOR), reports(ledger, LLM)
    assert [r["observed_N"] for r in factor["rows"]] == [1, 2]
    assert [r["observed_N"] for r in llm["rows"]] == [3, 7]
    assert [r["role"] for r in factor["rows"]] == ["PRIMARY_GATE", "SENSITIVITY"]


@pytest.mark.parametrize("tag", [None, "", "EVO883", [], {}, 0, True])
def test_missing_or_invalid_request_tag_refuses_without_default_or_writes(
    tmp_path, tag
):
    ledger = AttemptLedger(tmp_path / "fixture.sqlite")
    evaluated(ledger)
    arm = reports(ledger, tag)
    assert arm["observed_N_config"] is arm["observed_N_generation_requests"] is None
    assert "arm_n.arm_tag_missing_or_invalid" in arm["reasons"]


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": "arm_n.event/v1", "kind": "generation_request"},
        {"schema": "arm_n.event/v1", "kind": "generation_request", "arm_tag": []},
        {"arm_tag": FACTOR, "kind": "market_outcome_evaluated"},
    ],
)
def test_missing_event_tag_or_legacy_mapping_refuses_real_entries(tmp_path, payload):
    ledger = AttemptLedger(tmp_path / "fixture.sqlite")
    evaluated(ledger)
    ledger.record("bad", payload)
    arm = reports(ledger, FACTOR)
    assert arm["observed_N_config"] is arm["observed_N_generation_requests"] is None
    assert any(
        "event_arm_tag" in r or "legacy_configuration_mapping" in r
        for r in arm["reasons"]
    )


def test_unknown_internal_requests_leave_sensitivity_null_and_complete_N_unavailable(
    tmp_path,
):
    ledger = AttemptLedger(tmp_path / "fixture.sqlite")
    evaluated(ledger)
    write(
        ledger,
        "generation_request",
        actual_request_id="fixture-request",
        request_count_known=False,
        evidence_sha256=digest("request"),
    )
    arm = reports(ledger, FACTOR)
    assert arm["observed_N_config"] == 1
    assert arm["rows"][1]["observed_N"] is None and not arm["request_count_known"]
    assert all(r["complete_N"] is None for r in arm["rows"])
    assert "arm_n.internal_request_count_unknown" in arm["reasons"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_version", "fixture-p2"),
        ("model_snapshot", "fixture-model2"),
        ("parameters", {"temperature": 0.2}),
        ("ruleset", "fixture-r2"),
    ],
)
def test_each_configuration_axis_counts_once_only_after_market_evaluation(
    tmp_path, field, value
):
    ledger = AttemptLedger(tmp_path / "fixture.sqlite")
    changed = dict(CONFIG, **{field: value})
    assert configuration_id(CONFIG) != configuration_id(changed)
    evaluated(ledger)
    evaluated(ledger, config=changed)
    assert reports(ledger, FACTOR)["observed_N_config"] == 2


@pytest.mark.parametrize(
    "case", ["unreserved", "duplicate_request", "missing_evidence", "identity_conflict"]
)
def test_invalid_event_identity_never_yields_arm_N(tmp_path, case):
    ledger = AttemptLedger(tmp_path / "fixture.sqlite")
    if case == "unreserved":
        write(
            ledger,
            "market_outcome_evaluated",
            evaluation_id="x",
            evidence_sha256=digest("x"),
        )
    else:
        evaluated(ledger)
        if case == "identity_conflict":
            write(ledger, "configuration_reserved")
        else:
            fields = dict(
                actual_request_id="same",
                request_count_known=True,
                evidence_sha256=digest("x"),
            )
            if case == "missing_evidence":
                fields.pop("evidence_sha256")
            write(ledger, "generation_request", **fields)
            if case == "duplicate_request":
                write(ledger, "generation_request", **fields)
    assert reports(ledger, FACTOR)["observed_N_config"] is None


def test_all_EVO883_compatibility_calls_refuse_untagged_without_rewriting_counts(
    tmp_path,
):
    policy = load_conventions()
    ledger = fixture_ledger(tmp_path / "seed.sqlite", policy)
    ledger.begin("historical-no-tag", {})
    ledger.observe_self_report_n(100)
    before = (
        ledger.path.read_bytes(),
        ledger.anchor_path.read_bytes(),
        ledger.snapshot(),
    )
    for entry in (
        lambda r: dsr_eval(r, ledger, conventions=policy),
        lambda r: evaluate(r, ledger, policy),
        lambda r: legacy_evaluate(r, ledger, policy),
    ):
        report = entry({"self_report_n": 10**9})
        assert "arm_n.arm_tag_missing_or_invalid" in report["reasons"]
        assert report["metrics"]["cumulative_n_lower_bound"] is None
        assert (
            report["metrics"]["arm_n"]["global_history"]["legacy_count_readout"] == 48
        )
    for tag in (None, FACTOR):
        assert _n_snapshot(ledger, 10**9, tag)["gate_n"] is None
    assert before == (
        ledger.path.read_bytes(),
        ledger.anchor_path.read_bytes(),
        ledger.snapshot(),
    )


def test_train_pipeline_checks_tag_before_callbacks_and_history_mutation(tmp_path):
    policy = load_conventions()
    ledger = fixture_ledger(tmp_path / "seed.sqlite", policy)
    before = ledger.path.read_bytes(), ledger.anchor_path.read_bytes()
    calls = []
    kwargs = dict(
        policy=policy,
        ledger=ledger,
        run_id="fixture",
        registry=None,
        proposals=[],
        probe=lambda *a: calls.append(a),
        build_meta=lambda *a: calls.append(a),
        self_report_n=10**9,
    )
    assert (
        run_train_pipeline(context={}, **kwargs)["reason"]
        == "arm_n.arm_tag_missing_or_invalid"
    )
    assert (
        run_train_pipeline(context={"arm_tag": FACTOR}, **kwargs)["reason"]
        == "dsr.runtime_bindings_pending"
    )
    assert not calls and before == (
        ledger.path.read_bytes(),
        ledger.anchor_path.read_bytes(),
    )


@pytest.mark.parametrize("version,expected", [("v2", 75), ("v4", 280)])
def test_archived_and_current_authority_readout_retains_global_N_but_refuses_arm_inference(
    version, expected
):
    root = (
        authority_ledger.FIXTURES
        if version == "v2"
        else authority_ledger.CURRENT_FIXTURES
    )
    ledger = authority_ledger.AuthorityLedger(
        root / ("EVO891-B-ledger-%s.jsonl" % version),
        root / ("EVO891-B-ledger-%s.tip.json" % version),
    )
    before = ledger.path.read_bytes(), ledger.witness.read_bytes()
    for tag in (None, FACTOR, LLM):
        arm = reports(ledger, tag)
        assert arm["observed_N_config"] is None
        assert arm["global_history"]["recorded_N"] == expected
    assert before == (ledger.path.read_bytes(), ledger.witness.read_bytes())


@pytest.mark.parametrize(
    "outer,inner,reason",
    [
        (None, None, "arm_n.arm_tag_missing_or_invalid"),
        (FACTOR, None, "arm_n.event_arm_tag_missing_or_invalid"),
        (None, LLM, "arm_n.event_arm_tag_missing_or_invalid"),
        (FACTOR, LLM, "arm_n.request_arm_tag_conflict"),
    ],
)
def test_real_CLI_preserves_explicit_tag_and_rejects_conflicts_on_authority_fixture_copy(
    tmp_path, monkeypatch, capsys, outer, inner, reason
):
    ledger, tip = tmp_path / "fixture.jsonl", tmp_path / "fixture.tip.json"
    root = authority_ledger.CURRENT_FIXTURES
    shutil.copyfile(root / "EVO891-B-ledger-v4.jsonl", ledger)
    shutil.copyfile(root / "EVO891-B-ledger-v4.tip.json", tip)
    monkeypatch.setattr(authority_ledger, "PROJECT_LEDGER", ledger)
    monkeypatch.setattr(authority_ledger, "PROJECT_WITNESS", tip)
    request = {"metrics": {}}
    if outer is not None:
        request["arm_tag"] = outer
    if inner is not None:
        request["metrics"]["arm_tag"] = inner
    raw = deepcopy(request)
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dynamic_factor",
            "dsr_eval",
            "--input",
            str(source),
            "--ledger",
            str(ledger),
            "--conventions",
            str(FIXTURES / "conventions-v1.0.1.json"),
        ],
    )
    before = ledger.read_bytes(), tip.read_bytes()
    assert cli.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert reason in report["reasons"]
    if reason != "arm_n.request_arm_tag_conflict":
        assert report["metrics"]["arm_n"]["arm_tag"] == (outer or inner)
    assert before == (ledger.read_bytes(), tip.read_bytes()) and request == raw

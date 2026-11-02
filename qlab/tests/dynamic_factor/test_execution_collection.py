"""C11/A20/A21 and G14.P1.2: synthetic collection, no strategy/authority calls."""

from copy import deepcopy
import hashlib
import importlib.util
import json

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_receipts.collection import (
    ForwardAnchors,
    check_preperformance_collection,
    collect_execution,
)
from qlab.dynamic_factor.execution_receipts.g14 import PROTOCOL_SHA256, adopted_protocol


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "producer.py"
    path.write_text("def prepare():\n    raise AssertionError('no execution')\n")
    spec = importlib.util.spec_from_file_location("synthetic_producer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, body in {
        "dag": dict(
            nodes=["host", "guard", "reader"],
            edges=[["host", "guard"], ["guard", "reader"]],
        ),
        "scope": dict(scope_id="synthetic-train", dates=["2026-11-03"], B=["BLOCKED"]),
        "B": dict(
            book_id="CREF-F1/fold0/attempt1", read_count=0, rejected_symbols=["BLOCKED"]
        ),
    }.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(body))
    return dict(
        source_root=tmp_path,
        evidence_root=tmp_path,
        entrypoints={"reference.prepare": module.prepare},
        shared_modules={"shared": module},
        read_dag="dag.json",
        scope="scope.json",
        ledger_ids=["CREF-F1/fold0/attempt1"],
        ledger_B_proofs={"CREF-F1/fold0/attempt1": "B.json"},
    )


def inventory(registry, time="2026-11-02T04:00:00Z"):
    return collect_execution(run_id="synthetic-run", observed_at=time, **registry)


def test_A20_current_sources_are_collected_without_executing_and_no_seal_is_written(
    registry,
):
    before = {p.name for p in registry["source_root"].iterdir()}
    packet = inventory(registry)
    raw = (registry["source_root"] / "producer.py").read_bytes()
    assert (
        packet["observations"]["sources"]["entrypoints"]["reference.prepare"]["sha256"]
        == hashlib.sha256(raw).hexdigest()
    )
    assert packet["certification"] is None
    assert not {"sealed", "certified", "runtime_consumable", "complete"} & packet.keys()
    assert {p.name for p in registry["source_root"].iterdir()} == before
    assert (
        check_preperformance_collection(
            packet, packet, performance_started_at="2026-11-02T05:00:00Z"
        )
        == packet
    )


@pytest.mark.parametrize("target", ["producer.py", "dag.json", "scope.json", "B.json"])
def test_A20_new_source_or_evidence_cannot_reuse_old_registration(registry, target):
    old = inventory(registry)
    path = registry["source_root"] / target
    path.write_bytes(path.read_bytes() + b"\n")
    new = inventory(registry, "2026-11-02T04:30:00Z")
    with pytest.raises(ValueError, match="collection.preperformance_inventory_changed"):
        check_preperformance_collection(
            new, old, performance_started_at="2026-11-02T05:00:00Z"
        )


@pytest.mark.parametrize("time", ["2026-11-02T05:00:00Z", "2026-11-02T06:00:00Z"])
def test_A21_inventory_or_DAG_cannot_be_backfilled_after_returns(registry, time):
    packet = inventory(registry, time)
    with pytest.raises(ValueError, match="collection.inventory_not_preperformance"):
        check_preperformance_collection(
            packet, packet, performance_started_at="2026-11-02T05:00:00Z"
        )


def test_every_book_missing_proof_survives_as_a_gap(registry):
    registry["ledger_ids"].append("MREF-F2/fold0/attempt1")
    packet = inventory(registry)
    record = packet["observations"]["ledger_B_proofs"]["MREF-F2/fold0/attempt1"]
    assert record["sha256"] is record["document"] is None
    assert (
        "ledger_B_proofs/MREF-F2/fold0/attempt1:collection.file_missing"
        in packet["missing_items"]
    )
    with pytest.raises(ValueError, match="collection.required_evidence_missing"):
        check_preperformance_collection(
            packet, packet, performance_started_at="2026-11-02T05:00:00Z"
        )


def inputs(**changes):
    return (
        dict(
            run_id="fwd",
            rule_sha256="a" * 64,
            protocol_sha256=PROTOCOL_SHA256,
            sample_id="sample-1",
            sample_origin="actual_forward_unseen",
            first_evaluation_id="sample-1",
            event_at="2026-11-03T14:30:00Z",
            available_at="2026-11-03T14:30:01Z",
            observed_at="2026-11-03T14:30:02Z",
            decision_at="2026-11-03T14:30:03Z",
            visible_input_sha256="b" * 64,
            input_manifest_sha256="c" * 64,
        )
        | changes
    )


def log(previous=()):
    return ForwardAnchors(
        run_id="fwd",
        rule_sha256="a" * 64,
        start_at="2026-11-03T14:00:00Z",
        previous=previous,
    )


def output(event):
    return dict(
        input_anchor_sha256=digest(event),
        output_sha256="d" * 64,
        produced_at="2026-11-03T14:30:04Z",
        observed_at="2026-11-03T14:30:05Z",
    )


@pytest.mark.parametrize(
    "origin",
    [
        "offline_replay",
        "data_revision",
        "result_copy",
        "preparatory_observation",
        "reused_old_sample",
    ],
)
def test_G14_five_non_new_samples_refused_without_output_anchor(origin):
    anchors = log()
    with pytest.raises(ValueError, match="collection.not_new_unseen_forward_sample"):
        anchors.observe_input(inputs(sample_origin=origin))
    assert anchors.export() == []


def test_G14_actual_synthetic_positive_has_both_anchors_but_no_certification():
    event, anchors = inputs(), log()
    assert anchors.observe_input(event) == digest(event)
    packet = anchors.observe_output(event["sample_id"], output(event))
    assert packet[0]["input"] == event
    assert packet[0]["output"] == output(event)
    assert log(packet).export() == packet
    assert adopted_protocol()["acceptance_status"]["G14"] == "UNVERIFIED"
    assert not {"OOS", "certified", "runtime_consumable"} & packet[0].keys()


def test_G14_replay_and_rewrite_cannot_replace_original_anchor():
    event, anchors = inputs(), log()
    anchors.observe_input(event)
    original = anchors.observe_output(event["sample_id"], output(event))
    with pytest.raises(ValueError, match="collection.not_new_unseen_forward_sample"):
        anchors.observe_input(event)
    changed = deepcopy(original)
    changed[0]["output"]["output_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="collection.forward_log_rewritten"):
        log(changed)
    leaked = anchors.export()
    leaked[0]["input"]["sample_id"] = "changed"
    assert anchors.export() == original


@pytest.mark.parametrize(
    "change",
    [
        dict(available_at="2026-11-03T14:30:04Z"),
        dict(first_evaluation_id="old-evaluation"),
        dict(protocol_sha256="f" * 64),
    ],
)
def test_G14_visibility_first_identity_and_adoption_bound_before_output(change):
    with pytest.raises(ValueError):
        log().observe_input(inputs(**change))


def test_G14_output_before_input_or_backdated_output_refused():
    event, anchors = inputs(), log()
    with pytest.raises(ValueError, match="collection.forward_input_anchor_required"):
        anchors.observe_output(event["sample_id"], output(event))
    anchors.observe_input(event)
    bad = dict(output(event), produced_at="2026-11-03T14:29:00Z")
    with pytest.raises(ValueError, match="collection.forward_output_binding_or_time"):
        anchors.observe_output(event["sample_id"], bad)
    assert anchors.export() == []

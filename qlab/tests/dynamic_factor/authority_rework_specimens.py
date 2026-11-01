"""Correctly bound original B21R F2 attacks, through public read-only APIs."""

from copy import deepcopy
import json
from pathlib import Path

import authority_host_helpers
from authority_rework_helpers import (
    counterfeit_pair,
    fixture_bytes,
    observed_call,
    rebind_private_receipt,
    ruling_archive,
)
from authority_stage1_helpers import raw_json
from installation_host_helpers import installation_host
from test_reception_n03 import receive
from qlab.dynamic_factor.authority_ledger import (
    FIELDS,
    records,
    replay_approved_archive,
    state,
    verify_bytes,
)
from qlab.dynamic_factor.authority_prefix import verify_anchor_prefix
from qlab.dynamic_factor.authority_release import read_approved_release
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.reception_schema import validate


def refusal(call, reason, *, anchor_calls):
    result, counts = observed_call(call)
    assert result["accepted"] is False
    assert result["reasons"] == [reason], result["reasons"]
    assert counts["validate_anchor"] == anchor_calls
    assert counts["read_inputs"] == counts["read_strategy_inputs"] == 0
    assert counts["run_isolated"] == 0
    return dict(report=result, actual_calls=counts, worker="not_started")


def typed_anchor_case(case, path, monkeypatch):
    _, source, document = installation_host(path, monkeypatch, prefix_stub=False)
    original_publication = source["published_anchor_bytes"]
    original_revision = document["anchor"]["anchor_L1_revision"]
    if case == "A-02":
        document["anchor"]["V2"]["measured"]["revision"] += 1
    else:
        measured = document["anchor"]["V4"]["measured"]
        measured.update(anchor_sequence=182, observed_prefix_sequence=182)
    # A closed-schema failure must never satisfy these original semantic cases.
    validate(document, "installation.schema.json")
    context = rebind_private_receipt(source, document, monkeypatch)
    record = refusal(
        lambda: receive(context, source),
        "receipt.anchor_observation_mismatch",
        anchor_calls=1,
    )
    assert record["actual_calls"]["validate_receipt"] == 1
    assert record["report"]["observations"]["typed_schema_checks"] == 1
    assert source["published_anchor_bytes"] == original_publication
    assert document["anchor"]["anchor_L1_revision"] == original_revision
    record.update(typed_schema_passed=True, document=document)
    return record


def physical_pair_case(case, path, monkeypatch):
    context, source, document = installation_host(path, monkeypatch, prefix_stub=False)
    assert receive(context, source)["accepted"]
    original_receipt = source["installation_receipt_bytes"]
    changed, witness, current = counterfeit_pair(source, wrong_branch=case == "A-06")
    assert witness["ledger_file_sha256"] == sha256(changed)
    assert all(witness[key] == current[key] for key in FIELDS)
    assert sha256(changed) != source["chain_sha256"]
    if case == "A-06":
        assert current["sequence"] > source["witness"]["sequence"]
        assert current["n_high_water"] > source["witness"]["n_high_water"]
        assert current["ledger_id"] != source["witness"]["ledger_id"]
    # Mutate the actual two physical objects, not the candidate receipt.
    chain_path, witness_path = Path(source["chain_path"]), Path(source["witness_path"])
    chain_path.write_bytes(changed)
    witness_path.write_bytes(raw_json(witness) + b"\n")
    before = chain_path.read_bytes(), witness_path.read_bytes()
    record = refusal(
        lambda: receive(context, source), "ledger.observed_object_drift", anchor_calls=0
    )
    assert record["report"]["observations"]["typed_schema_checks"] == 1
    assert (
        source["installation_receipt_bytes"] == original_receipt == raw_json(document)
    )
    assert before == (chain_path.read_bytes(), witness_path.read_bytes())
    record.update(
        typed_schema_passed=True,
        locally_matching_witness=witness,
        local_state=current,
        current_trusted_witness=source["witness"],
        actual_chain_sha256=sha256(before[0]),
        actual_witness_sha256=sha256(before[1]),
        unchanged_receipt_sha256=sha256(original_receipt),
    )
    return record


def original_prefix_case():
    raw, witness, coverage = ruling_archive()
    clean = replay_approved_archive(raw, trusted_release=coverage, witness=witness)
    assert clean["book_N"] == clean["high_water"] == 1313
    prefix = fixture_bytes("seq1148.jsonl.gz")
    witness_raw = fixture_bytes("seq1148.tip.json")
    local = json.loads(witness_raw)
    # Exact independent repro bytes, not a synthetic N75 or a full-archive tip.
    assert (
        sha256(prefix)
        == "268b9da8ba2d479172979cf50e15a2bb8e1738fd983bf44022866f1240292af6"
    )
    assert (
        sha256(witness_raw)
        == "11c52fc87c71a14762766466aa97f8f708b184f0362cb5fcce449fa475d82eec"
    )
    assert prefix == b"".join(raw.splitlines(keepends=True)[:1149])
    current = state(records(prefix))
    assert current["sequence"] == 1148 and current["N"] == 756
    assert local["ledger_file_sha256"] == sha256(prefix)
    assert all(local[key] == current[key] for key in FIELDS)
    try:
        replay_approved_archive(prefix, trusted_release=coverage, witness=local)
    except ValueError as exc:
        reason = str(exc)
    else:
        raise AssertionError("truncated N756 archive unexpectedly accepted")
    assert reason == "ledger.approved_archive_bytes_mismatch", reason
    return dict(
        accepted=False,
        reason=reason,
        prefix_sha256=sha256(prefix),
        witness_sha256=sha256(witness_raw),
        local_state=current,
        locally_matching_witness=local,
        trusted_book_N=clean["book_N"],
        trusted_archive_sha256=sha256(raw),
        worker="not_started",
    )


def old_l2_case(path, monkeypatch):
    monkeypatch.setattr(
        authority_host_helpers, "archive", lambda: ruling_archive(project_witness=True)
    )
    context, source, document = installation_host(path, monkeypatch, prefix_stub=False)
    validate(document, "installation.schema.json")
    clean = receive(context, source)
    assert clean["accepted"], clean["reasons"]
    raw, _, coverage = ruling_archive()
    old_witness = json.loads(fixture_bytes("v4.tip.json"))
    old = {
        key: old_witness[key]
        for key in (
            "ledger_id",
            "sequence",
            "tip",
            "n_high_water",
            "ledger_file_sha256",
        )
    }
    assert old["sequence"] == 182 and old["n_high_water"] == 280
    old_raw = raw_json(old) + b"\n"
    observation = deepcopy(source["observation"])
    observation.update(
        anchor_raw=old_raw,
        anchor_ref="sha256:" + sha256(old_raw),
        anchor_payload_sha256=sha256(old_raw),
        approved_anchor_sha256=sha256(old_raw),
    )
    prefix = verify_anchor_prefix(raw, old, observation)
    assert prefix["status"] == "PASS", prefix["reasons"]
    current, _ = verify_bytes(raw, source["witness"], old, trusted_coverage=coverage)
    assert current["N"] == 1313
    approved = read_approved_release(host_context=context)
    assert approved["sequence"] == 1372
    from qlab.dynamic_factor.authority_install_receipt import (
        verify_installation_readonly,
    )

    record = refusal(
        lambda: verify_installation_readonly(
            host_context=context,
            runtime_module_path=source["module_path"],
            installation_receipt_bytes=source["installation_receipt_bytes"],
            published_anchor_bytes=old_raw,
            acceptance_bytes=source["installation_acceptance_bytes"],
        ),
        "receipt.trusted_source_failed:publication",
        anchor_calls=0,
    )
    assert record["report"]["observations"]["typed_schema_checks"] == 1
    record.update(
        typed_schema_passed=True,
        old_prefix_check=prefix,
        old_anchor=old,
        full_integrity_under_old_ancestor=current,
        current_trusted_anchor=approved,
        clean_current_accepted=clean["accepted"],
    )
    return record

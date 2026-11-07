"""S static-source bindings; no market read, runtime grant or new oracle."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.reference_evidence import verify_seal
from qlab.dynamic_factor.scope_proof import b2_manifest_check


ROOT = Path(__file__).parents[2] / "qlab/dynamic_factor"
FOLDER = ROOT / "evidence/evo884-exec-reseal-v1"
OLD = json.loads(
    (Path(__file__).parent / "fixtures/S-old-f827-source-bindings.json").read_bytes()
)


def document(name):
    return json.loads((FOLDER / name).read_bytes())


def no_read(call, *, reason=None):
    calls = []
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if (
            event == "call"
            and frame.f_globals.get("__name__", "").startswith("qlab.")
            and frame.f_code.co_name
            in {
                "read_inputs",
                "read_strategy_inputs",
                "run_isolated",
                "numeric_read",
                "_worker",
            }
        ):
            calls.append(frame.f_code.co_name)

    try:
        sys.setprofile(observe)
        if reason is None:
            out = call()
        else:
            with pytest.raises(ValueError, match="^" + reason + "$") as refused:
                call()
            out = str(refused.value)
    finally:
        sys.setprofile(previous)
    assert calls == []
    return out


def test_S_single_current_release_exact_bytes_and_no_runtime_permission():
    index = json.loads((ROOT / "evidence/current-seal-index.json").read_bytes())
    current = index["current"]
    assert current["path"] == "evo884-exec-reseal-v1/static-seal.json"
    assert (
        sha256((ROOT / "evidence" / current["path"]).read_bytes()) == current["sha256"]
    )
    release = document("binding-publication.json")
    assert current["binding_publication"]["sha256"] == sha256(
        (FOLDER / "binding-publication.json").read_bytes()
    )
    assert current["B2_manifest"]["sha256"] == sha256(
        (FOLDER / "B2-unavailable-manifest.json").read_bytes()
    )
    assert release["publication_sha256"] == digest(
        {k: v for k, v in release.items() if k != "publication_sha256"}
    )
    for name, expected in release["bindings"].items():
        raw = (FOLDER / name).read_bytes()
        assert sha256(raw) == expected["sha256"] and len(raw) == expected["bytes"]
    inventory = document("source-inventory.json")["files"]
    repo = ROOT.parents[2]
    for name, expected in inventory.items():
        raw = (repo / name).read_bytes()
        assert sha256(raw) == expected["sha256"] and len(raw) == expected["bytes"]
    rows = document("migration-manifest.json")["rows"]
    assert len(rows) == 9
    assert len({r["file"] for r in rows}) == 9
    for row in rows:
        assert row["new_sha256"] == sha256((repo / row["file"]).read_bytes())
        for target in row["new_binding_receipt_or_manifest"]:
            value = document(target["artifact"])
            for token in target["json_pointer"].split("/")[1:]:
                value = value[token.replace("~1", "/").replace("~0", "~")]
            assert value == target["recorded_value"] == row["new_sha256"]
    assert release["runtime_consumable"] is release["certifiable"] is False
    assert current["independent_review"] == "pending EVO887 S"
    assert document("scope.json")["complete_N"] is None
    assert document("scope.json")["gate_N"] is None
    assert document("scope.json")["design_count_archive_reference"] == 6


def test_S_new_source_and_new_seal_and_unavailable_B2_bindings_pass(record_property):
    seal = document("static-seal.json")
    no_read(lambda: verify_seal(seal))
    b2 = no_read(
        lambda: b2_manifest_check(
            document("B2-unavailable-manifest.json"), load_conventions()
        )
    )
    assert b2["input_binding_present"] is True
    assert b2["all_dates_retained"] is True
    assert b2["available"] is False and b2["value"] is None
    assert seal["runtime_consumable"] is False
    record_property(
        "S_new_bindings_actual",
        json.dumps(
            dict(static_seal_accepted=True, B2=b2, reader_calls=0, worker_calls=0),
            sort_keys=True,
        ),
    )


@pytest.mark.parametrize("kind", ["reference_seal", "B2_manifest"])
def test_S_old_source_bindings_refuse_before_reader(kind, record_property):
    if kind == "reference_seal":
        reason = "reference.static_seal_mismatch"
        no_read(lambda: verify_seal(OLD["historical_reference_seal"]), reason=reason)
    else:
        reason = "scope.B2_isolation_manifest_missing_or_invalid"
        no_read(
            lambda: b2_manifest_check(OLD["B2_manifest"], load_conventions()),
            reason=reason,
        )
    record_property(
        "S_old_binding_actual",
        json.dumps(dict(kind=kind, reason=reason, reader_calls=0, worker_calls=0)),
    )


@pytest.mark.parametrize("mutation", ["prefix", "case", "wrong_identity"])
def test_S_source_identity_has_no_prefix_case_or_replacement_exception(mutation):
    seal = deepcopy(document("static-seal.json"))
    original = seal["sources"]["execution.py"]
    seal["sources"]["execution.py"] = (
        original[:12]
        if mutation == "prefix"
        else original.upper()
        if mutation == "case"
        else "0" * 64
    )
    no_read(lambda: verify_seal(seal), reason="reference.static_seal_mismatch")

"""Synthetic observation collection; no strategy, budget or certification calls."""

import hashlib
import importlib.util
import json

import pytest

from qlab.dynamic_factor.prefreeze.collection import collect, format_collection


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "entry.py"
    source.write_text("def entry():\n    raise AssertionError('must not execute')\n")
    spec = importlib.util.spec_from_file_location("synthetic_entry", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(
        source_root=tmp_path,
        evidence_root=tmp_path,
        entrypoints={"reference": module.entry},
        shared_modules={"shared": module},
        ledger_ids=("candidate-ledger", "reference-ledger"),
    )


def test_sources_are_actual_loaded_locations_and_entry_is_never_called(inputs):
    result = collect(**inputs)
    raw = (inputs["source_root"] / "entry.py").read_bytes()
    for record in (
        result["sources"]["entrypoints"]["reference"],
        result["sources"]["shared_modules"]["shared"],
    ):
        assert record["path"] == "entry.py"
        assert record["sha256"] == hashlib.sha256(raw).hexdigest()
        assert record["bytes"] == len(raw)
    assert result["sources"]["entrypoints"]["reference"]["first_line"] == 1


def test_raw_evidence_identity_and_per_ledger_missing_are_preserved(inputs):
    root = inputs["evidence_root"]
    raw = b'{ "nodes": ["host", "reader"], "edges": [["host", "reader"]] }\r\n'
    (root / "dag.json").write_bytes(raw)
    (root / "scope.json").write_text('{"B":null,"scope_id":"synthetic"}\n')
    (root / "B.json").write_text('{"B":[],"claimed_pass":true}\n')
    result = collect(
        **inputs,
        read_dag="dag.json",
        scope="scope.json",
        ledger_B_proofs={"candidate-ledger": "B.json"},
    )
    assert result["read_dag"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["read_dag"]["bytes"] == len(raw)
    assert result["read_dag"]["document"]["edges"] == [["host", "reader"]]
    assert result["scope"]["document"]["B"] is None
    proofs = result["ledger_B_proofs"]
    assert set(proofs) == {"candidate-ledger", "reference-ledger"}
    assert proofs["candidate-ledger"]["document"] == {"B": [], "claimed_pass": True}
    assert proofs["reference-ledger"]["document"] is None
    assert proofs["reference-ledger"]["sha256"] is None
    assert proofs["reference-ledger"]["bytes"] is None
    assert proofs["reference-ledger"]["reasons"] == ["collection.file_missing"]
    assert not {"ok", "complete", "sealed", "certified", "runtime_consumable"} & set(
        result
    )


def test_absent_dag_scope_and_B_are_unknown_not_empty_proofs(inputs):
    result = collect(**inputs)
    for record in [
        result["read_dag"],
        result["scope"],
        *result["ledger_B_proofs"].values(),
    ]:
        assert record["document"] is record["sha256"] is record["bytes"] is None
        assert record["reasons"] == ["collection.file_missing"]


@pytest.mark.parametrize("path", ["../outside.json", "/outside.json"])
def test_outside_evidence_is_not_read(inputs, path):
    result = collect(**inputs, scope=path)
    assert result["scope"]["document"] is None
    assert result["scope"]["reasons"] == ["collection.path_outside_root"]


def test_symlink_is_not_followed(inputs):
    root = inputs["evidence_root"]
    (root / "real.json").write_text('{"B":[]}')
    (root / "link.json").symlink_to(root / "real.json")
    result = collect(**inputs, scope="link.json")
    assert result["scope"]["document"] is None
    assert result["scope"]["reasons"] == ["collection.symlink_not_collected"]


@pytest.mark.parametrize("raw", [b"{", b'{"B":NaN}', b"\xff", b'{"B":[],"B":["x"]}'])
def test_unreadable_JSON_retains_raw_identity_without_a_verdict(inputs, raw):
    root = inputs["evidence_root"]
    (root / "bad.json").write_bytes(raw)
    result = collect(**inputs, scope="bad.json")
    assert result["scope"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["scope"]["document"] is None
    assert result["scope"]["reasons"] == ["collection.json_unreadable"]


def test_unlisted_B_proof_is_not_silently_dropped(inputs):
    with pytest.raises(ValueError, match="collection.unlisted_ledger_proof"):
        collect(**inputs, ledger_B_proofs={"other-ledger": "B.json"})


def test_duplicate_ledger_id_is_rejected(inputs):
    request = dict(inputs, ledger_ids=("candidate-ledger", "candidate-ledger"))
    with pytest.raises(ValueError, match="collection.duplicate_ledger_id"):
        collect(**request)


def test_non_function_source_does_not_execute_an_adapter(inputs):
    class Adapter:
        def __call__(self):
            raise AssertionError("must not execute")

    with pytest.raises(ValueError, match="collection.loaded_python_function_required"):
        collect(**dict(inputs, entrypoints={"reference": Adapter()}))


def test_compiled_module_is_not_misreported_as_source(inputs):
    module = inputs["shared_modules"]["shared"]
    module.__file__ = str(inputs["source_root"] / "entry.pyc")
    result = collect(**inputs)
    record = result["sources"]["shared_modules"]["shared"]
    assert record["sha256"] is None
    assert record["reasons"] == ["collection.python_source_unavailable"]


def test_formatter_is_deterministic_and_does_not_write_markers(inputs):
    before = {p.name for p in inputs["evidence_root"].iterdir()}
    first = format_collection(collect(**inputs))
    second = format_collection(collect(**inputs))
    assert first == second
    assert json.loads(first)["schema"] == "EVO884.PrefreezeCollection/v1"
    assert {p.name for p in inputs["evidence_root"].iterdir()} == before

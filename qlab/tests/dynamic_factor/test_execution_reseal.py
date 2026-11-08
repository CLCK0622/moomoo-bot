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


S_FIXED_HEAD = "2d4bac0c9c787b9abc17178989bb3a1dadf72827"
S_ORIGINAL_ROWS = 9
S_ORIGINAL_SOURCES = 52
B_ROWS = 40
B_SOURCES = 52
B_INVENTORY = 232
_S_REPLAY_RESULTS = {}


def _run_fixed_S(function_name, *, mutate=False):
    import io
    import os
    import subprocess
    import sys
    import tarfile
    import tempfile

    repo = Path(__file__).parents[3]
    raw = subprocess.check_output(["git", "archive", S_FIXED_HEAD], cwd=repo)
    # Missing objects raise: no skip/xfail or fallback to current sources.
    with tempfile.TemporaryDirectory(prefix="B-S-original-") as folder:
        tree = Path(folder)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive.getmembers():
                assert (
                    not Path(member.name).is_absolute()
                    and ".." not in Path(member.name).parts
                )
                assert not member.issym() and not member.islnk()
            archive.extractall(tree)
        original = tree / "qlab/qlab/dynamic_factor/evidence/evo884-exec-reseal-v1"
        assert (
            len(json.loads((original / "migration-manifest.json").read_bytes())["rows"])
            == S_ORIGINAL_ROWS
            == 9
        )
        assert (
            len(json.loads((original / "static-seal.json").read_bytes())["sources"])
            == S_ORIGINAL_SOURCES
            == 52
        )
        assert (
            sha256((original / "static-seal.json").read_bytes())
            == "5ac1110499183549057517decbd252421f1bc6a20d0db91c729841421ebefbe5"
        )
        if mutate:
            target = tree / "qlab/qlab/dynamic_factor/noncash_v3.py"
            target.write_bytes(
                target.read_bytes() + b"\n# TEST_ONLY fixed S byte mutation\n"
            )
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
        }
        env.update(
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        )
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                "--tb=short",
                "tests/dynamic_factor/" + Path(__file__).name + "::" + function_name,
            ],
            cwd=tree / "qlab",
            env=env,
            capture_output=True,
            text=True,
        )


def _S_replay(function):
    from functools import wraps

    @wraps(function)
    def replay(*args, **kwargs):
        if function.__name__ not in _S_REPLAY_RESULTS:
            _S_REPLAY_RESULTS[function.__name__] = _run_fixed_S(function.__name__)
        result = _S_REPLAY_RESULTS[function.__name__]
        assert result.returncode == 0, result.stdout + result.stderr

    return replay


def _B_current_checks():
    from qlab.dynamic_factor.reference_evidence import verify_seal

    root = ROOT
    repo = root.parents[2]
    index = json.loads((root / "evidence/current-seal-index.json").read_bytes())
    assert index["current"]["path"] == "evo884-c1-rework-v1/static-seal.json"
    folder = root / "evidence/evo884-c1-rework-v1"
    raw = (folder / "static-seal.json").read_bytes()
    assert index["current"]["sha256"] == sha256(raw)
    seal = json.loads(raw)
    from qlab.dynamic_factor.contract import digest
    from qlab.dynamic_factor.conventions import load_conventions
    from qlab.dynamic_factor.scope_proof import b2_manifest_check

    assert index["current"]["source_count"] == B_SOURCES == 52
    assert index["current"]["source_map_sha256"] == digest(seal["sources"])
    assert len(seal["sources"]) == B_SOURCES == 52
    for name, expected in seal["sources"].items():
        assert sha256((root / name).read_bytes()) == expected
    verify_seal(seal)
    inventory = json.loads((folder / "source-inventory.json").read_bytes())["files"]
    assert len(inventory) == B_INVENTORY == 232
    for name, binding in inventory.items():
        value = (repo / name).read_bytes()
        assert sha256(value) == binding["sha256"] and len(value) == binding["bytes"]
    migration = json.loads((folder / "migration-manifest-v6.json").read_bytes())
    assert len(migration["rows"]) == S_ORIGINAL_ROWS == 9
    assert len(migration["B_rows"]) == B_ROWS == 40
    for row in migration["B_rows"]:
        assert row["new_sha256"] == sha256((repo / row["file"]).read_bytes())
    previous_raw = (folder / "previous-index.json").read_bytes()
    assert index["previous_index_sha256"] == sha256(previous_raw)
    previous = json.loads(previous_raw)
    assert index["historical"][:-1] == previous["historical"]
    assert index["historical"][-1]["entry"] == previous["current"]
    predecessor = (repo / migration["predecessor_manifest"]["file"]).read_bytes()
    assert sha256(predecessor) == migration["predecessor_manifest"]["sha256"]
    assert migration["rows"] == json.loads(predecessor)["rows"]
    publication_raw = (folder / "binding-publication.json").read_bytes()
    assert index["current"]["binding_publication"]["sha256"] == sha256(publication_raw)
    publication = json.loads(publication_raw)
    assert publication["publication_sha256"] == digest(
        {k: v for k, v in publication.items() if k != "publication_sha256"}
    )
    b2_raw = (folder / "B2-unavailable-manifest.json").read_bytes()
    assert index["current"]["B2_manifest"]["sha256"] == sha256(b2_raw)
    assert (
        b2_manifest_check(json.loads(b2_raw), load_conventions())["available"] is False
    )
    registration = json.loads((folder / "index-registration.json").read_bytes())
    assert registration["new_index_sha256"] == sha256(
        (root / "evidence/current-seal-index.json").read_bytes()
    )
    assert registration["new_index_sha256"].encode() not in publication_raw
    for name, binding in publication["bindings"].items():
        value = (folder / name).read_bytes()
        assert sha256(value) == binding["sha256"] and len(value) == binding["bytes"]
    assert publication["runtime_consumable"] is False


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


@_S_replay
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


@_S_replay
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


def test_B_current_binds_exact_source_bytes_inventory_and_rows():
    _B_current_checks()


@pytest.mark.parametrize(
    "mutation", ["B_current_source_identity", "S_fixed_source_byte"]
)
def test_TEST_ONLY_B_and_S_identity_mutations_stay_red(monkeypatch, mutation):
    if mutation == "S_fixed_source_byte":
        result = _run_fixed_S(
            "test_S_single_current_release_exact_bytes_and_no_runtime_permission",
            mutate=True,
        )
        assert result.returncode == 1 and "FAILED" in result.stdout
        assert (
            "AssertionError" in result.stdout
            or "reference.static_seal_mismatch" in result.stdout
        )
        return
    folder = ROOT / "evidence/evo884-c1-rework-v1"
    seal_path = folder / "static-seal.json"
    index_path = ROOT / "evidence/current-seal-index.json"
    seal = json.loads(seal_path.read_bytes())
    seal["sources"]["noncash_v3.py"] = "f" * 64
    changed = json.dumps(seal, sort_keys=True).encode()
    index = json.loads(index_path.read_bytes())
    index["current"]["sha256"] = sha256(changed)
    overrides = {seal_path: changed, index_path: json.dumps(index).encode()}
    original = Path.read_bytes
    with monkeypatch.context() as fault:
        fault.setattr(
            Path,
            "read_bytes",
            lambda path: overrides[path] if path in overrides else original(path),
        )
        with pytest.raises(AssertionError):
            _B_current_checks()

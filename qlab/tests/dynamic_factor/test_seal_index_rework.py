"""Approved S index wrapper: frozen bytes, existing readers, no new capability."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from qlab.dynamic_factor.contract import canonical, sha256
from test_execution_reseal import (
    test_S_single_current_release_exact_bytes_and_no_runtime_permission as legacy_reader,
)


REPO = Path(__file__).parents[3]
ROOT = REPO / "qlab/qlab/dynamic_factor"
RELEASE = ROOT / "evidence/evo884-exec-reseal-v1"
FIXTURES = Path(__file__).parent / "fixtures/S-index-rework"
INDEX = ROOT / "evidence/current-seal-index.json"
OLD_RAW = (FIXTURES / "14ebe19-index.json.fixture").read_bytes()
S_RAW = (FIXTURES / "4ef96c0-index.json.fixture").read_bytes()
OLD = json.loads(OLD_RAW)
S_INDEX = json.loads(S_RAW)
REVISION = json.loads((RELEASE / "migration-manifest-v2.json").read_bytes())


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
    assert index["current"]["path"] == "evo884-c1-v7-v1/static-seal.json"
    folder = root / "evidence/evo884-c1-v7-v1"
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
    migration = json.loads((folder / "migration-manifest-v7.json").read_bytes())
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


def member(raw, key):
    text = raw.decode()
    start = re.search('"' + key + r'"\s*:\s*', text).end()
    value, end = json.JSONDecoder().raw_decode(text, start)
    return value, text[start:end].encode()


def historical_raw(raw):
    text = raw.decode()
    pos = re.search(r'"historical"\s*:\s*\[', text).end()
    values = []
    while True:
        while text[pos] in " \n\r\t,":
            pos += 1
        if text[pos] == "]":
            return values
        _, end = json.JSONDecoder().raw_decode(text, pos)
        values.append(text[pos:end].encode())
        pos = end


def test_F3b_inner_preserves_all_eight_keys_values_and_original_raw_object():
    assert sha256(OLD_RAW) == (
        "c436a67d62555f4b06f2b457866a5ae022fd9deb7d90e5122a6eb2840b298b7b"
    )
    wrapper_raw = historical_raw(INDEX.read_bytes())[3]
    wrapper = json.loads(wrapper_raw)
    inner, inner_raw = member(wrapper_raw, "entry")
    original, original_raw = member(OLD_RAW, "current")
    assert len(original) == 8 and set(inner) == set(original)
    assert inner == original and inner_raw == original_raw
    assert set(wrapper) == {
        "schema",
        "status",
        "historical_superseded_by_S",
        "attachments_retained",
        "entry",
    }
    assert wrapper["schema"] == "EVO884.HistoricalSealEntry/v1"
    assert wrapper["status"] == "historical_superseded_by_S"
    assert (
        wrapper["attachments_retained"] is wrapper["historical_superseded_by_S"] is True
    )
    binding = REVISION["data_index_changes"][0]["original_current_object"]
    assert sha256(canonical(inner)) == binding["canonical_json_sha256"]
    assert sha256(inner_raw) == binding["raw_object_sha256"]
    assert len(inner_raw) == binding["raw_object_bytes"]


@pytest.mark.parametrize("position", [0, 1, 2])
def test_other_historical_objects_remain_exact_original_bytes(position):
    old = historical_raw(OLD_RAW)[position]
    now = historical_raw(INDEX.read_bytes())[position]
    assert now == old
    item = REVISION["data_index_changes"][0]["other_historical_objects"][position]
    assert item["index"] == position and item["byte_equal"] is True
    assert item["new_sha256"] == item["old_sha256"] == sha256(old)


@_S_replay
def test_current_and_all_nonhistory_metadata_and_pre_S_pointer_remain_unchanged():
    current = json.loads(INDEX.read_bytes())
    before = deepcopy(S_INDEX)
    assert member(INDEX.read_bytes(), "current")[1] == member(S_RAW, "current")[1]
    assert len(current.pop("historical")) == len(OLD["historical"]) + 1
    before.pop("historical")
    assert current == before
    assert current["previous_index_sha256"] == sha256(OLD_RAW)
    assert current["current"]["sha256"] == sha256(
        (RELEASE / "static-seal.json").read_bytes()
    )
    assert current["current"]["runtime_consumable"] is False


@_S_replay
def test_versioned_registration_has_all_index_identities_and_no_mutual_hash_reference():
    v1 = (RELEASE / "migration-manifest.json").read_bytes()
    envelope = (RELEASE / "binding-publication.json").read_bytes()
    assert (
        sha256(v1) == "55ae24cd39271dfc633d9084b09596cb9f8c9191e869a4f01149a4573ca0556e"
    )
    assert (
        sha256(envelope)
        == "3115c44feaf26834bc226c8b2c7e7ba5f40045def5d95b59320d9ef7b558459a"
    )
    assert REVISION["schema"] == "EVO884.SMigrationHandoff/v2"
    assert REVISION["predecessor_manifest"]["sha256"] == sha256(v1)
    row = REVISION["data_index_changes"][0]
    assert row["file"] == "qlab/qlab/dynamic_factor/evidence/current-seal-index.json"
    assert row["old_sha256"] == sha256(OLD_RAW)
    assert row["previous_S_sha256"] == sha256(S_RAW)
    assert row["new_sha256"] == sha256(INDEX.read_bytes())
    assert row["reason"] and row["wrapper"]["attachments_retained_purpose"]
    old_manifest = json.loads(v1)
    assert REVISION["rows"] == old_manifest["rows"]
    assert (
        REVISION["carried_existing_C13_component_rows"]
        == old_manifest["carried_existing_C13_component_rows"]
    )
    assert REVISION["protected"] == old_manifest["protected"]
    assert REVISION["B_release_nine_rows_included"] is False
    assert REVISION["new_seal_generated"] is False
    for raw in (INDEX.read_bytes(), envelope):
        assert row["new_sha256"].encode() not in raw
        assert b"migration-manifest-v2.json" not in raw
        assert (
            sha256((RELEASE / "migration-manifest-v2.json").read_bytes()).encode()
            not in raw
        )


@_S_replay
def test_original_static_seal_keeps_all_52_actual_source_identities():
    raw = (RELEASE / "static-seal.json").read_bytes()
    assert (
        sha256(raw)
        == "5ac1110499183549057517decbd252421f1bc6a20d0db91c729841421ebefbe5"
    )
    sources = json.loads(raw)["sources"]
    assert len(sources) == 52
    for name, expected in sources.items():
        assert sha256((ROOT / name).read_bytes()) == expected


@pytest.mark.parametrize(
    "name,expected_sha,archive_path",
    [
        (
            "README.md",
            "4551a97f5f38f89110ab48e8eef3523ddfcd6950b6e9e4e109bbf2cf1f3e2289",
            "evo884-f3b-v1/static-seal.json",
        ),
        (
            "evidence/evo884-exec-reseal-v1/README.md",
            "8b637d2e141add2245ce0f0ee0d3acab71527bb10a40b9fa50ebad8de459b4c0",
            "evo884-exec-reseal-v1/static-seal.json",
        ),
    ],
)
@_S_replay
def test_each_existing_documentation_reference_still_resolves(
    name, expected_sha, archive_path
):
    raw = (ROOT / name).read_bytes()
    assert sha256(raw) == expected_sha and b"current-seal-index.json" in raw
    assert (ROOT / "evidence" / archive_path).is_file()
    assert json.loads(INDEX.read_bytes())["current"] == S_INDEX["current"]


@_S_replay
def test_existing_executable_index_consumer_passes_unchanged():
    source = Path(__file__).with_name("test_execution_reseal.py").read_bytes()
    assert (
        sha256(source)
        == "d037afdc41ad0b4939e539bb208ffc1901db0631ae9480e07ae8ab0371a7e999"
    )
    legacy_reader()


def test_product_has_no_explicit_index_or_historical_member_reader_to_adapt():
    matches = []
    for path in (REPO / "qlab/qlab").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if (
                    "current-seal-index" in node.value
                    or node.value == "EVO884.effective-seal-index/v1"
                ):
                    matches.append((str(path.relative_to(REPO)), node.lineno))
            key = None
            if isinstance(node, ast.Subscript):
                key = node.slice
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
            ):
                key = node.args[0]
            if isinstance(key, ast.Constant) and key.value == "historical":
                matches.append((str(path.relative_to(REPO)), node.lineno))
    assert matches == []


def test_B_current_binds_exact_source_bytes_inventory_and_rows():
    _B_current_checks()


@pytest.mark.parametrize(
    "mutation", ["B_current_source_identity", "S_fixed_source_byte"]
)
def test_TEST_ONLY_B_and_S_identity_mutations_stay_red(monkeypatch, mutation):
    if mutation == "S_fixed_source_byte":
        result = _run_fixed_S(
            "test_original_static_seal_keeps_all_52_actual_source_identities",
            mutate=True,
        )
        assert result.returncode == 1 and "FAILED" in result.stdout
        assert (
            "AssertionError" in result.stdout
            or "reference.static_seal_mismatch" in result.stdout
        )
        return
    folder = ROOT / "evidence/evo884-c1-v7-v1"
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

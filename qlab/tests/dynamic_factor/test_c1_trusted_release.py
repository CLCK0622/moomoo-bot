"""C1 copied-host controls. All registrations here are TEST_ONLY tmp data.

No trusted source is monkeypatched. Child processes import the copied product
module; the production package never contains a registration or actual A.
"""

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from qlab.dynamic_factor import b_release_context as b, scope_proof
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.conventions import load_conventions


ROOT = Path(b.__file__).parent
ROOT_NAME = "trust-root-platform-readback.json"
CHILD = """
import importlib.util, json, sys
from pathlib import Path
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor import b_release_context as installed
path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('qlab.dynamic_factor.c1_copy', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert Path(module.__file__) == path
assert module._read_trusted_release.__module__ == spec.name
try:
    policy = load_conventions()
    first = module.receive_release_context(policy=policy)
    second = module.receive_release_context(policy=policy, a_raw=first.a_raw)
    assert first.a_raw == second.a_raw
    assert first.implementation_id == module.sha256(path.read_bytes())
    assert first.implementation_sha256 == first.implementation_id
    assert not json.loads(first.a_raw)['runtime_consumable']
    assert not json.loads(first.a_raw)['certifiable']
    print(json.dumps(dict(status='TEST_ONLY_ACCEPTED', h_a=first.h_a,
        accepted_at=first.accepted_at, implementation_id=first.implementation_id)))
except ValueError as exc:
    print(json.dumps(dict(status='REJECTED', reason=str(exc))))
"""


@pytest.fixture
def copied_host(tmp_path):
    module = tmp_path / "copied-host/b_release_context.py"
    module.parent.mkdir()
    shutil.copyfile(Path(b.__file__), module)
    originals = module.parent / "b_release_originals"
    shutil.copytree(ROOT / "b_release_originals", originals)
    registration = dict(
        schema="EVO884.BReleaseTrustRegistration/v1",
        context_version="TEST_ONLY_C1_v1",
        receiver_id="gongbu.original-host:5a307571-9534-4bbc-932c-93ffc9c94d73",
        implementation_id=sha256(module.read_bytes()),
        r_sha256=sha256(
            (originals / "EVO938-B-runtime-release-R-v1.0.0.json").read_bytes()
        ),
        p_sha256=sha256(
            (originals / "EVO938-B-runtime-release-P-v1.0.0.json").read_bytes()
        ),
        adoption_sha256=b.ADOPTION_SHA256,
        policy_binding=b._policy_binding(load_conventions()),
        run_time_binding=dict(
            mode="forward",
            first_performance_at="2026-11-10T14:30:00Z",
            signal_close="2026-11-09T21:00:00Z",
        ),
        purpose="TEST_ONLY copied host acceptance mechanism",
        limitations="TEST_ONLY; no installed authority, real A, B, SRC/AUTH or L0",
    )
    readback = dict(
        type="comment",
        author_type="agent",
        author_id="cc562115-7ef6-4b8f-b4b6-a5b7584b1340",
        issue_id="01a19dab-15f2-7e58-96a0-cf92c87162c2",
        id="TEST_ONLY_C1_REGISTRATION",
        revision=1,
        created_at="2026-11-08T12:00:00Z",
        content=json.dumps(registration, ensure_ascii=False),
    )
    (originals / ROOT_NAME).write_text(json.dumps(readback), encoding="utf-8")
    return module, originals, readback, registration


def run_copy(copied_host, tmp_path):
    module, _, _, _ = copied_host
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
    }
    env.update(
        PYTHONPATH=str(ROOT.parents[1]),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        B_RELEASE_ROOT="/TEST_ONLY_IGNORED/env/root.json",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(module)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write_root(copied_host):
    _, originals, readback, registration = copied_host
    readback["content"] = json.dumps(registration)
    (originals / ROOT_NAME).write_text(json.dumps(readback), encoding="utf-8")


def test_production_C1_missing_root_still_refuses():
    assert not (ROOT / "b_release_originals" / ROOT_NAME).exists()
    with pytest.raises(ValueError, match="^B.release_context_trust_binding_missing$"):
        b.receive_release_context(policy=load_conventions())


def test_tmp_copied_host_accepts_and_reloads_exact_test_A(copied_host, tmp_path):
    result = run_copy(copied_host, tmp_path)
    assert result["status"] == "TEST_ONLY_ACCEPTED"
    assert result["accepted_at"] == copied_host[2]["created_at"]
    assert result["implementation_id"] == sha256(copied_host[0].read_bytes())
    assert run_copy(copied_host, tmp_path) == result
    assert not (ROOT / "b_release_originals" / ROOT_NAME).exists()


def test_missing_root_rejected_in_child(copied_host, tmp_path):
    (copied_host[1] / ROOT_NAME).unlink()
    assert run_copy(copied_host, tmp_path) == dict(
        status="REJECTED", reason="B.release_context_trust_binding_missing"
    )


def test_implementation_id_mismatch_rejected_in_child(copied_host, tmp_path):
    copied_host[3]["implementation_id"] = "0" * 64
    write_root(copied_host)
    assert run_copy(copied_host, tmp_path) == dict(
        status="REJECTED", reason="B.release_context_acceptance_mismatch"
    )


@pytest.mark.parametrize(
    "name", sorted(p.name for p in (ROOT / "b_release_originals").iterdir())
)
def test_every_original_SHA_mismatch_rejected_in_child(copied_host, tmp_path, name):
    path = copied_host[1] / name
    path.write_bytes(path.read_bytes() + b"\nTEST_ONLY corruption")
    assert run_copy(copied_host, tmp_path) == dict(
        status="REJECTED", reason="B.release_context_release_mismatch"
    )


@pytest.mark.parametrize(
    "fault",
    ["author", "issue", "missing_issue", "duplicate_key", "extra_key", "bound_R"],
)
def test_root_structure_and_original_bindings_are_checked(copied_host, tmp_path, fault):
    _, originals, readback, registration = copied_host
    reason = "B.release_context_trust_binding_missing"
    if fault == "author":
        readback["author_id"] = "TEST_ONLY_OTHER_AUTHOR"
    elif fault == "issue":
        readback["issue_id"] = "TEST_ONLY_OTHER_ISSUE"
    elif fault == "missing_issue":
        readback.pop("issue_id")
    elif fault == "extra_key":
        registration["override_root"] = "/TEST_ONLY_IGNORED"
    elif fault == "bound_R":
        registration["r_sha256"] = "0" * 64
        reason = "B.release_context_release_mismatch"
    write_root(copied_host)
    if fault == "duplicate_key":
        readback["content"] = '{"schema":1,"schema":2}'
        (originals / ROOT_NAME).write_text(json.dumps(readback), encoding="utf-8")
        reason = "B.release_context_encoding_invalid"
    assert run_copy(copied_host, tmp_path) == dict(status="REJECTED", reason=reason)


def test_exact_audit_registration_and_full_gate_pass():
    proof = scope_proof.b2_isolation_proof(load_conventions())
    audit = proof["B_release_adapter_scope"]
    assert len(audit["sha256_reads"]) == 15
    assert len(audit["path_only_reads"]) == 2
    assert audit["exact_adapter_read_sites"] == 3
    assert audit["root_sha_in_code"] is False


@pytest.mark.parametrize(
    "fault", ["third_path", "changed_path", "original_without_SHA"]
)
def test_audit_rejects_path_only_table_expansion_or_change(monkeypatch, fault):
    rows = scope_proof.B_RELEASE_PATH_ONLY_READS
    if fault == "third_path":
        rows += (("b_release_context", "b_release_originals/THIRD.json"),)
    elif fault == "changed_path":
        rows = (rows[0], ("b_release_context", "some_other_module.py"))
    else:
        rows += (("b_release_context", scope_proof.B_RELEASE_ADAPTER_READS[0][1]),)
    monkeypatch.setattr(scope_proof, "B_RELEASE_PATH_ONLY_READS", rows)
    with pytest.raises(ValueError, match="^scope.file_access_not_whitelisted$"):
        scope_proof.b2_isolation_proof(load_conventions())


@pytest.mark.parametrize(
    "expression",
    [
        'Path("some_other_module.py")',
        'Path(__file__).with_name("some_other_module.py")',
        "Path(override)",
    ],
)
def test_audit_rejects_any_other_self_read_argument_AST(monkeypatch, expression):
    original = Path.read_bytes
    current = Path(b.__file__)
    raw = (
        current.read_text()
        .replace("Path.read_bytes(self_path)", "Path.read_bytes(" + expression + ")")
        .encode()
    )
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: raw if p == current else original(p)
    )
    with pytest.raises(ValueError, match="^scope.file_access_not_whitelisted$"):
        scope_proof.b2_isolation_proof(load_conventions())


def test_original_registrations_and_other_counts_are_byte_unchanged():
    base = subprocess.check_output(
        ["git", "show", "d9e3887:qlab/qlab/dynamic_factor/scope_proof.py"],
        cwd=ROOT.parents[2],
    ).decode()
    current = Path(scope_proof.__file__).read_text()

    def assignment(text, name):
        tree = ast.parse(text)
        return next(
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        )

    for name in (
        "GATES",
        "FIXED_READS",
        "B_RELEASE_FIXED_READS",
        "FIXED_READER_SOURCES",
        "FILENAME_READS",
        "FILENAME_SOURCE_IDENTITIES",
    ):
        old = ast.get_source_segment(base, assignment(base, name))
        new = ast.get_source_segment(current, assignment(current, name))
        assert old == new, name
    old_counts = next(
        n.comparators[0]
        for n in ast.walk(ast.parse(base))
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Name)
        and n.left.id == "file_reads"
    )
    new_counts = next(
        n.comparators[0]
        for n in ast.walk(ast.parse(current))
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Name)
        and n.left.id == "file_reads"
    )
    old_map, new_map = ast.literal_eval(old_counts), ast.literal_eval(new_counts)
    assert old_map.pop("b_release_context") == 1
    assert new_map.pop("b_release_context") == 4
    assert old_map.pop("scope_proof") == 2
    assert new_map.pop("scope_proof") == 3
    assert old_map == new_map
    old_text = ast.get_source_segment(base, old_counts).splitlines()
    new_text = ast.get_source_segment(current, new_counts).splitlines()
    assert [
        s
        for s in old_text
        if '"b_release_context"' not in s and '"scope_proof"' not in s
    ] == [
        s
        for s in new_text
        if '"b_release_context"' not in s and '"scope_proof"' not in s
    ]

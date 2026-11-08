"""B2 source identity controls for the complete receiver import closure."""

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from qlab.dynamic_factor import b_release_context as b, scope_proof as scope
from qlab.dynamic_factor.conventions import load_conventions


ROOT = Path(b.__file__).parent
REPO = ROOT.parents[2]

CHILD = """
import hashlib,json,sys
from pathlib import Path
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'qlab'))
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.scope_proof import b2_isolation_proof
target=repo/'qlab/qlab/dynamic_factor/contract.py'
source_sha256=hashlib.sha256(target.read_bytes()).hexdigest()
opened=[]
def observe(event,args):
    if event=='open' and isinstance(args[0],str):opened.append(args[0])
sys.addaudithook(observe)
try:
    proof=b2_isolation_proof(load_conventions())
    result=dict(status='ACCEPTED',source_sha256=source_sha256,
                dependency_scope=proof['C1_dependency_scope'])
except ValueError as exc:
    result=dict(status='REJECTED',source_sha256=source_sha256,reason=str(exc))
result['opened_paths']=opened
print(json.dumps(result))
"""


def run_child(repo, cwd):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
    }
    env.update(PYTHONPATH="", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(repo)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "case", ["resolve", "read_bytes", "sha256_body", "sha256_identity"]
)
def test_contract_source_identity_is_rejected_in_B2(tmp_path, record_property, case):
    repo = tmp_path / "candidate"
    shutil.copytree(REPO / "qlab", repo / "qlab")
    path = repo / "qlab/qlab/dynamic_factor/contract.py"
    raw = path.read_bytes()
    if case == "resolve":
        raw += b"\nPath.resolve = lambda self, strict=False: self\n"
    elif case == "read_bytes":
        raw += b"\ndef TEST_ONLY_path_binding():\n    Path.read_bytes = lambda self: b'TEST_ONLY'\n"
    elif case == "sha256_body":
        old = b"    return hashlib.sha256(value).hexdigest()"
        assert raw.count(old) == 1
        raw = raw.replace(old, b"    value = bytes(value)\n" + old)
    else:
        expected = hashlib.sha256(raw).hexdigest()
        old = b"    return hashlib.sha256(value).hexdigest()"
        raw = raw.replace(
            old,
            b'    if value.startswith(b\'"""Deterministic JSON\'):\n'
            + ("        return " + repr(expected) + "\n").encode()
            + old,
        )
    path.write_bytes(raw)
    result = run_child(repo, tmp_path)
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert str(path) in result["opened_paths"]
    assert result["status"] == "REJECTED"
    assert result["reason"] == "scope.file_access_not_whitelisted"
    record_property(
        "contract_binding_observation",
        json.dumps(dict(case=case, candidate_path=str(path), **result), sort_keys=True),
    )


def test_receiver_transitive_import_closure_has_fixed_B2_coverage():
    proof = scope.b2_isolation_proof(load_conventions())
    expected = {
        "b_release_context": {"catalog_v21", "contract"},
        "catalog_v21": {"contract", "conventions"},
        "conventions": {"contract"},
        "contract": set(),
        "__init__": set(),
        "../__init__": set(),
    }
    allowed_standard_library = {
        "__future__",
        "ast",
        "csv",
        "datetime",
        "dataclasses",
        "hashlib",
        "inspect",
        "io",
        "json",
        "math",
        "operator",
        "pathlib",
        "re",
        "statistics",
        "weakref",
    }
    for name, imports in expected.items():
        path = ROOT / (name + ".py")
        raw = path.read_bytes()
        tree = ast.parse(raw)
        local = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level
        }
        assert local == imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    a.name.split(".")[0] in allowed_standard_library for a in node.names
                )
            elif isinstance(node, ast.ImportFrom) and not node.level:
                assert node.module.split(".")[0] in allowed_standard_library
        if name != "b_release_context":
            assert (
                scope.B_RELEASE_DEPENDENCY_SOURCES[name + ".py"]
                == hashlib.sha256(raw).hexdigest()
            )
            assert (
                proof["source_files"][name + ".py"] == hashlib.sha256(raw).hexdigest()
            )
    assert proof["C1_dependency_scope"]["module_count"] == 42
    assert proof["C1_dependency_scope"]["fixed_source_count"] == 40
    assert proof["C1_dependency_scope"]["hits"] == []

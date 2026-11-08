"""Isolated entry, snapshot identities and post-load consistency controls."""

import ast
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import struct
import subprocess
import sys

import pytest

from qlab.dynamic_factor import scope_proof as scope
from qlab.dynamic_factor.conventions import load_conventions


REPO = Path(__file__).parents[3]
ROOT = REPO / "qlab/qlab/dynamic_factor"
ENTRY = REPO / "qlab/tools/c1_source_preflight.py"
ORIGINAL = Path(__file__).parent / "fixtures/C1-R3/original-contract.py.fixture"
ORIGINAL_SHA = "8cbcda793c9abd5722d20aa3674a3eb078af7823060da91008878e66df21ee3f"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def copied_tree(tmp_path):
    target = tmp_path / "candidate"
    shutil.copytree(REPO / "qlab", target / "qlab")
    return target


def run_entry(repo, *, cwd=None, flags=("-I", "-S", "-B")):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
    }
    argv = [sys.executable, *flags, str(repo / "qlab/tools/c1_source_preflight.py")]
    run = subprocess.run(argv, cwd=cwd or repo, env=env, capture_output=True, text=True)
    if run.stdout:
        result = json.loads(run.stdout)
    else:
        result = dict(
            status="REJECTED", reason=run.stderr.strip(), observations=[], events=[]
        )
    return dict(
        result, raw_rc=run.returncode, actual_argv=argv, actual_cwd=str(cwd or repo)
    )


def qlab_imports(result):
    return [
        e
        for e in result["events"]
        if e["event"] == "import"
        and (e["module"] == "qlab" or e["module"].startswith("qlab."))
    ]


def test_formal_entry_snapshot_positive_and_complete_import_binding(record_property):
    result = run_entry(REPO)
    assert result["raw_rc"] == 0 and result["status"] == "VERIFIED"
    assert result["C1_dependency_closed"] is True
    first = next(
        e["sequence"] for e in result["events"] if e["event"] == "preflight_conclusion"
    )
    last = next(e["sequence"] for e in result["events"] if e["event"] == "B2_complete")
    imports = qlab_imports(result)
    assert imports and all(first < e["sequence"] < last for e in imports)
    rows = result["import_binding"]
    assert {r["module"] for r in rows} == {e["module"] for e in imports}
    assert {
        "qlab.dynamic_factor.input_scope",
        "qlab.dynamic_factor.reference_check",
        "qlab.dynamic_factor.input_disposition",
    } <= {r["module"] for r in rows}
    for row in rows:
        assert row["observed_sha256"] == sha(Path(row["path"]).read_bytes())
        if row["binding"] != "receiver_full_AST":
            assert row["observed_sha256"] == row["expected_sha256"]
    proof = result["proof"]
    for name, identity in proof["source_files"].items():
        assert identity == sha((ROOT / name).read_bytes())
    consistency = proof["C1_source_preflight"]["entry_consistency"]
    assert consistency["placeholder_count"] == 1
    assert consistency["execution_trust_added"] is False
    assert (
        result["startup"]["isolated"]
        == result["startup"]["no_site"]
        == result["startup"]["dont_write_bytecode"]
        == 1
    )
    record_property("preflight_positive", json.dumps(result, sort_keys=True))


@pytest.mark.parametrize(
    "case", ["original_read_return", "hashlib_binding", "os_read_wrapper"]
)
def test_three_source_controls_refuse_before_qlab_import(
    copied_tree, case, record_property
):
    target = copied_tree / "qlab/qlab/dynamic_factor/contract.py"
    if case == "original_read_return":
        raw = ORIGINAL.read_bytes()
        assert sha(raw) == ORIGINAL_SHA
    elif case == "hashlib_binding":
        raw = (
            target.read_bytes()
            + b"\nimport hashlib\nhashlib.sha256 = lambda value: None\n"
        )
    else:
        raw = (
            target.read_bytes()
            + b"\nimport os\nos.read = lambda fd, size: b'TEST_ONLY'\n"
        )
    target.write_bytes(raw)
    actual = sha(raw)
    result = run_entry(copied_tree)
    assert result["raw_rc"] == 2 and result["status"] == "REJECTED"
    assert result["reason"] == "scope.preflight_source_identity_mismatch"
    assert qlab_imports(result) == []
    row = next(r for r in result["observations"] if r["path"] == str(target))
    assert row["observed_sha256"] == actual != row["expected_sha256"]
    assert any(
        e["event"] == "open" and e["path"] == str(target) for e in result["events"]
    )
    record_property(
        "preflight_source_refusal",
        json.dumps(
            dict(case=case, independent_sha256=actual, **result), sort_keys=True
        ),
    )


@pytest.mark.parametrize(
    "name",
    [
        "input_scope.py",
        "reference_check.py",
        "input_disposition.py",
        "fees.py",
        "event_quarantine.py",
        "__init__.py",
        "../__init__.py",
    ],
)
def test_import_time_closure_sources_are_all_fixed(copied_tree, name):
    path = copied_tree / "qlab/qlab/dynamic_factor" / name
    path.write_bytes(path.read_bytes() + b"\nTEST_ONLY_additional_binding = 1\n")
    result = run_entry(copied_tree)
    assert result["raw_rc"] == 2
    assert result["reason"] == "scope.preflight_source_identity_mismatch"
    assert qlab_imports(result) == []


def test_receiver_full_template_refuses_before_receiver_import(copied_tree):
    path = copied_tree / "qlab/qlab/dynamic_factor/b_release_context.py"
    path.write_bytes(path.read_bytes() + b"\nTEST_ONLY_additional_binding = 1\n")
    result = run_entry(copied_tree)
    assert result["raw_rc"] == 2
    assert result["reason"] == "scope.file_access_not_whitelisted"
    assert "qlab.dynamic_factor.b_release_context" not in {
        e["module"] for e in qlab_imports(result)
    }


@pytest.mark.parametrize(
    "case",
    [
        "normal",
        "extra_statement",
        "wrong_auditor_SHA",
        "non_SHA_literal",
        "second_placeholder",
        "docstring",
    ],
)
def test_S_checks_complete_E_template_and_unique_placeholder(case, record_property):
    raw = ENTRY.read_bytes()
    actual = sha(Path(scope.__file__).read_bytes())
    if case in {"wrong_auditor_SHA", "non_SHA_literal"}:
        text = raw.decode()
        node = next(
            n
            for n in ast.parse(text).body
            if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "AUDITOR_SHA256"
        )
        lines = text.splitlines()
        lines[node.lineno - 1 : node.end_lineno] = [
            'AUDITOR_SHA256 = "' + "0" * 64 + '"'
            if case == "wrong_auditor_SHA"
            else "AUDITOR_SHA256 = 42"
        ]
        raw = ("\n".join(lines) + "\n").encode()
    elif case == "extra_statement":
        raw += b"\nTEST_ONLY_additional_binding = 1\n"
    elif case == "second_placeholder":
        raw += b'\nTEST_ONLY_second = "C1_AUDITOR_SHA256_PLACEHOLDER"\n'
    elif case == "docstring":
        raw = raw.replace(
            b"Controlled C1 source preflight", b"TEST_ONLY C1 source preflight", 1
        )
    expected = {
        "extra_statement": "scope.preflight_entry_structure_mismatch",
        "wrong_auditor_SHA": "scope.preflight_auditor_binding_mismatch",
        "non_SHA_literal": "scope.preflight_entry_template_invalid",
        "second_placeholder": "scope.preflight_entry_template_invalid",
        "docstring": "scope.preflight_entry_structure_mismatch",
    }
    if case == "normal":
        result = scope._c1_entry_structure(raw, actual)
        assert result["placeholder_count"] == 1 and result["docstrings_compared"]
        reason = None
    else:
        with pytest.raises(ValueError) as caught:
            scope._c1_entry_structure(raw, actual)
        reason = str(caught.value)
        assert reason == expected[case]
    record_property(
        "entry_structure_control",
        json.dumps(
            dict(
                stage="post_execution_AST_unit",
                case=case,
                observed_entry_sha256=sha(raw),
                observed_auditor_sha256=actual,
                reason=reason,
            )
        ),
    )


def test_template_itself_cannot_add_a_second_placeholder(monkeypatch):
    monkeypatch.setattr(
        scope,
        "C1_ENTRY_TEMPLATE",
        scope.C1_ENTRY_TEMPLATE
        + '\nTEST_ONLY_second = "C1_AUDITOR_SHA256_PLACEHOLDER"\n',
    )
    with pytest.raises(ValueError, match="scope.preflight_entry_template_invalid"):
        scope._c1_entry_structure(
            ENTRY.read_bytes(), sha(Path(scope.__file__).read_bytes())
        )


@pytest.mark.parametrize(
    "case", ["extra_statement", "second_placeholder", "non_SHA_literal"]
)
def test_private_E_variants_are_refused_on_the_formal_route(
    copied_tree, case, record_property
):
    path = copied_tree / "qlab/tools/c1_source_preflight.py"
    raw = path.read_bytes()
    if case == "extra_statement":
        raw += b"\nTEST_ONLY_additional_binding = 1\n"
    elif case == "second_placeholder":
        raw += b'\nTEST_ONLY_second = "C1_AUDITOR_SHA256_PLACEHOLDER"\n'
    else:
        text = raw.decode()
        node = next(
            n
            for n in ast.parse(text).body
            if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "AUDITOR_SHA256"
        )
        lines = text.splitlines()
        lines[node.lineno - 1 : node.end_lineno] = ["AUDITOR_SHA256 = 42"]
        raw = ("\n".join(lines) + "\n").encode()
    path.write_bytes(raw)
    result = run_entry(copied_tree)
    expected = {
        "extra_statement": "scope.preflight_entry_structure_mismatch",
        "second_placeholder": "scope.preflight_entry_template_invalid",
        "non_SHA_literal": "scope.preflight_source_identity_mismatch",
    }
    assert result["raw_rc"] == 2 and result["reason"] == expected[case]
    assert result["C1_dependency_closed"] is False
    if case == "non_SHA_literal":
        assert qlab_imports(result) == []
    record_property(
        "formal_entry_structure_control",
        json.dumps(
            dict(case=case, observed_entry_sha256=sha(raw), **result), sort_keys=True
        ),
    )


def test_legacy_direct_B2_does_not_issue_C1_closure():
    proof = scope.b2_isolation_proof(load_conventions())
    assert proof["C1_source_preflight"] == dict(
        dependency_closed=False, reason="scope.preflight_required"
    )


@pytest.mark.parametrize("snapshot", [None, {}, object()])
def test_missing_or_replaced_snapshot_is_not_front_evidence(snapshot):
    with pytest.raises(ValueError, match="scope.preflight_evidence_required"):
        scope.b2_isolation_proof_from_snapshot(load_conventions(), snapshot)


SNAPSHOT_UNIT = r"""
import hashlib,json,os,runpy,sys,tempfile
root=sys.argv[1];case=sys.argv[2];other=sys.argv[3]
path=os.path.join(root,'qlab/tools/c1_source_preflight.py')
ns=runpy.run_path(path,run_name='C1_SNAPSHOT_UNIT')
g=ns['_collect'].__globals__
snapshot,observations,errors=ns['_collect']();assert not errors
target=os.path.join(root,'qlab/qlab/dynamic_factor/scope_proof.py')
before=next(r for r in observations if r['path']==target)
if case=='bytes_replaced':
    g['_STORE'][snapshot]['raw'][target]+=b'\nTEST_ONLY extra bytes\n'
elif case=='identity_replaced':
    g['_STORE'][snapshot]['metadata'][target]['observed_sha256']='0'*64
else:
    for row in observations:
        p=row['path']
        if p.endswith('.py') and p!=path:
            name=os.path.relpath(p,os.path.join(root,'qlab'))[:-3].replace(os.sep,'.')
            if name.endswith('.__init__'):name=name[:-9]
            g['_ALLOWED_IMPORTS'].add(name)
    g['_VERIFIED']=True
    sys.pycache_prefix=tempfile.mkdtemp(prefix='c1-unit-bytecode-')
    sys.path.insert(0,os.path.join(other if case=='other_tree' else root,'qlab'))
    import qlab.dynamic_factor.scope_proof as scope
    if case=='origin_changed':scope.__spec__.origin=os.path.join(other,'qlab/qlab/dynamic_factor/scope_proof.py')
    if case=='inode_replaced':
        raw=open(target,'rb').read();p=target+'.TEST_ONLY';open(p,'wb').write(raw);os.replace(p,target)
try:
    if case in {'bytes_replaced','identity_replaced'}:snapshot.validate()
    else:snapshot.bind_loaded()
    raise AssertionError('unverified snapshot accepted')
except ValueError as exc:reason=str(exc)
loaded=sys.modules.get('qlab.dynamic_factor.scope_proof')
print(json.dumps(dict(stage='snapshot_or_binding_unit',case=case,reason=reason,expected_path=target,expected_identity=before,actual_origin=None if loaded is None else loaded.__spec__.origin,events=g['_EVENTS'])))
"""


@pytest.mark.parametrize(
    "case",
    [
        "bytes_replaced",
        "identity_replaced",
        "other_tree",
        "origin_changed",
        "inode_replaced",
    ],
)
def test_snapshot_and_actual_loaded_object_binding(
    copied_tree, tmp_path, case, record_property
):
    other = tmp_path / "other"
    shutil.copytree(copied_tree / "qlab", other / "qlab")
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            SNAPSHOT_UNIT,
            str(copied_tree),
            case,
            str(other),
        ],
        cwd=copied_tree,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["reason"] == (
        "scope.preflight_snapshot_mismatch"
        if case in {"bytes_replaced", "identity_replaced"}
        else "scope.preflight_loading_mismatch"
    )
    record_property("snapshot_binding_control", json.dumps(result, sort_keys=True))


def test_loaded_candidate_process_cannot_call_entry_again():
    program = """
import os,runpy,sys
root=sys.argv[1];sys.path.insert(0,os.path.join(root,'qlab'))
from qlab.dynamic_factor import contract
runpy.run_path(os.path.join(root,'qlab/tools/c1_source_preflight.py'),run_name='__main__')
"""
    run = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, str(REPO)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert (
        run.returncode != 0 and "scope.preflight_candidate_already_loaded" in run.stderr
    )


def test_nonisolated_startup_is_refused():
    result = run_entry(REPO, flags=("-S", "-B"))
    assert (
        result["raw_rc"] != 0
        and result["reason"] == "scope.preflight_isolation_required"
    )


def test_registered_working_directory_is_required(tmp_path):
    result = run_entry(REPO, cwd=tmp_path)
    assert result["raw_rc"] == 2
    assert result["reason"] == "scope.preflight_workdir_or_arguments_mismatch"
    assert qlab_imports(result) == []


def test_formal_entry_uses_source_instead_of_an_alternate_cached_program(
    copied_tree, tmp_path
):
    target = copied_tree / "qlab/qlab/dynamic_factor/contract.py"
    alternate = tmp_path / "alternate.py"
    alternate.write_text('raise RuntimeError("TEST_ONLY alternate cached program")\n')
    cached = target.parent / "__pycache__" / (
        "contract." + sys.implementation.cache_tag + ".pyc"
    )
    cached.parent.mkdir(exist_ok=True)
    py_compile.compile(
        str(alternate), cfile=str(cached), dfile=str(target), doraise=True
    )
    raw = cached.read_bytes()
    status = target.stat()
    cached.write_bytes(
        raw[:8] + struct.pack("<II", int(status.st_mtime), status.st_size) + raw[16:]
    )
    control = """
import sys
sys.pycache_prefix=None
sys.path.insert(0,sys.argv[1])
from qlab.dynamic_factor import contract
"""
    ordinary = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", control, str(copied_tree / "qlab")],
        cwd=copied_tree,
        capture_output=True,
        text=True,
    )
    assert (
        ordinary.returncode != 0
        and "TEST_ONLY alternate cached program" in ordinary.stderr
    )
    result = run_entry(copied_tree)
    assert result["raw_rc"] == 0 and result["C1_dependency_closed"] is True

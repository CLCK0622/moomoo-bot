"""C1-R1 regressions use archived sources and subprocess-only copied hosts."""

import ast
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from qlab.dynamic_factor import b_release_context as b, scope_proof
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.conventions import load_conventions
from test_c1_trusted_release import copied_host as copied_host
from test_c1_trusted_release import write_root


ROOT = Path(b.__file__).parent
REPO = ROOT.parents[2]
BASE = "d9e38874a43f44c8efc45eb85398645d0babd53d"
RELATIVE = "qlab/qlab/dynamic_factor/"


def child(code, *args, cwd):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
    }
    env.update(
        PYTHONPATH=str(REPO / "qlab"),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


SCOPE_CHILD = """
import importlib.util,json,sys
from pathlib import Path
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'qlab'))
from qlab.dynamic_factor.conventions import load_conventions
path=repo/'qlab/qlab/dynamic_factor/scope_proof.py'
spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.TEST_SCOPE',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
try:
    m.b2_isolation_proof(load_conventions());result={'status':'ACCEPTED'}
except ValueError as exc:
    result={'status':'REJECTED','reason':str(exc)}
print(json.dumps(result))
"""


@pytest.mark.parametrize("missing_original", [False, True])
def test_archived_d9_and_new_head_preserve_dual_fault_first_refusal(
    tmp_path, missing_original
):
    # Missing Git objects fail this control; there is no fallback or skip.
    archive = subprocess.check_output(["git", "archive", BASE], cwd=REPO)
    archived = tmp_path / "d9"
    archived.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(archived)
    current = tmp_path / "new"
    shutil.copytree(REPO / "qlab", current / "qlab")
    results = []
    for repo in (archived, current):
        root = repo / RELATIVE
        reader = root / "scope_reader.py"
        reader.write_bytes(
            reader.read_bytes()
            + b'\ndef TEST_ONLY_extra_read():\n    return Path("TEST_ONLY").read_bytes()\n'
        )
        helper = root / "execution_accounting.py"
        helper.write_bytes(helper.read_bytes() + b"\n# TEST_ONLY pinned helper drift\n")
        if missing_original:
            original = (
                root / "b_release_originals/EVO938-B-runtime-release-R-v1.0.0.json"
            )
            if original.exists():
                original.unlink()
        results.append(child(SCOPE_CHILD, repo, cwd=tmp_path))
    assert (
        results
        == [dict(status="REJECTED", reason="scope.reader_or_role_set_changed")] * 2
    )


def test_legacy_b2_region_is_byte_exact_except_authorized_counter():
    old = subprocess.check_output(
        ["git", "show", BASE + ":" + RELATIVE + "scope_proof.py"], cwd=REPO
    ).decode()
    new = Path(scope_proof.__file__).read_text()
    start = "def b2_isolation_proof("
    end = "    ref = static_proof()\n"

    def region(source):
        first = source.index(start)
        return source[first : source.index(end, first) + len(end)]

    assert region(new) == region(old).replace(
        '"b_release_context": 1,', '"b_release_context": 4,'
    )


@pytest.mark.parametrize(
    "mutation",
    [
        '\n__file__ = "OTHER.py"\n',
        '\nglobals()["__file__"] = "OTHER.py"\n',
        '\nsetattr(object(), "__file__", "OTHER.py")\n',
        '\ndef unused():\n    globals()["__file__"] = "OTHER.py"\n',
        '\ndef unused():\n    global __file__\n    __file__ = "OTHER.py"\n',
    ],
)
def test_whole_module_file_rebinding_rejected(monkeypatch, mutation):
    current = Path(b.__file__)
    raw = current.read_bytes() + mutation.encode()
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: raw if p == current else original(p)
    )
    with pytest.raises(ValueError, match="^scope.file_access_not_whitelisted$"):
        scope_proof.b2_isolation_proof(load_conventions())


def test_global_override_at_self_read_preserves_argument_ast_but_is_rejected(
    monkeypatch,
):
    current = Path(b.__file__)
    text = current.read_text().replace(
        "            self_raw = Path.read_bytes(Path(__file__))",
        '            globals()["__file__"] = str(Path(__file__).with_name("OTHER.py"))\n'
        "            self_raw = Path.read_bytes(Path(__file__))",
    )
    assert text != current.read_text()
    calls = [
        n
        for n in ast.walk(ast.parse(text))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "read_bytes"
        and n.args
        and ast.dump(n.args[0])
        == ast.dump(ast.parse("Path(__file__)", mode="eval").body)
    ]
    assert len(calls) == 1
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: text.encode() if p == current else original(p)
    )
    with pytest.raises(ValueError, match="^scope.file_access_not_whitelisted$"):
        scope_proof.b2_isolation_proof(load_conventions())


@pytest.mark.parametrize(
    "old,new",
    [
        ("compile.__call__(", "other.__call__("),
        ('"co_names",', '"co_name",'),
        ("same_constant(left.co_consts, right.co_consts)", "True"),
    ],
)
def test_exact_compile_and_recursive_comparison_cannot_be_disabled(
    monkeypatch, old, new
):
    current = Path(b.__file__)
    text = current.read_text()
    assert old in text
    raw = text.replace(old, new, 1).encode()
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: raw if p == current else original(p)
    )
    with pytest.raises(ValueError, match="^scope.file_access_not_whitelisted$"):
        scope_proof.b2_isolation_proof(load_conventions())


RUNTIME_CHILD = """
import importlib.util,json,sys
from pathlib import Path
from qlab.dynamic_factor.conventions import load_conventions
path=Path(sys.argv[1]);case=sys.argv[2]
spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.TEST_RUNTIME',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
other=path.with_name('OTHER.py');other.write_bytes(b'TEST_ONLY foreign bytes')
if case=='external_file':m.__file__=str(other)
if case.startswith('hot_'):
    text=path.read_text()
    if case=='hot_consts':text=text.replace('BReleaseTrustRegistration/v1','BReleaseTrustRegistration/v9')
    else:text=text.replace('_utc(accepted_at)', '_pairs(accepted_at)')
    assert text!=path.read_text();path.write_text(text)
    root=path.parent/'b_release_originals/trust-root-platform-readback.json'
    record=json.loads(root.read_text());content=json.loads(record['content'])
    content['implementation_id']=m.sha256(path.read_bytes());record['content']=json.dumps(content)
    root.write_text(json.dumps(record))
opened=[]
def audit(event,args):
    if event=='open':opened.append(str(args[0]))
sys.addaudithook(audit)
try:
    result=m._read_trusted_release()
    status={'status':'ACCEPTED','implementation_id':result['implementation_id']}
except ValueError as exc:status={'status':'REJECTED','reason':str(exc)}
status['foreign_opened']=str(other) in opened
print(json.dumps(status))
"""


@pytest.mark.parametrize(
    "case", ["external_file", "global_file", "direct_file", "hot_consts", "hot_names"]
)
def test_live_code_binding_rejects_tmp_file_retarget_or_disk_code_drift(
    copied_host, tmp_path, case
):
    module = copied_host[0]
    if case in ("global_file", "direct_file"):
        line = 'globals()["__file__"]' if case == "global_file" else "__file__"
        module.write_text(
            module.read_text()
            + "\n"
            + line
            + ' = str(__import__("pathlib").Path(__file__).with_name("OTHER.py"))\n'
        )
        copied_host[3]["implementation_id"] = sha256(module.read_bytes())
        write_root(copied_host)
    result = child(RUNTIME_CHILD, module, case, cwd=tmp_path)
    assert result == dict(
        status="REJECTED",
        reason="B.release_context_acceptance_mismatch",
        foreign_opened=False,
    )


def test_approved_publication_readback_remains_exact():
    original = ROOT / "b_release_originals/publication-platform-readback.json"
    assert (
        sha256(original.read_bytes())
        == "f847be9a107b9293e134bfc4d9a03a3c3cb1eeb823f40991d7b8d28d1533455e"
    )

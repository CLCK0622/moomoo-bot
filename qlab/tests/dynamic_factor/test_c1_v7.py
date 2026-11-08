"""V7 rejects descriptor bypasses without opening a compile exception."""

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from qlab.dynamic_factor import b_release_context as b, scope_proof as scope
from qlab.dynamic_factor.conventions import load_conventions
from test_c1_trusted_release import copied_host as copied_host


ROOT = Path(b.__file__).parent
MODULES = sorted(
    set(scope.IMPORTS)
    | {module for module, _, _ in scope.FIXED_READS}
    | set(scope.FILENAME_READS)
)


def test_final_gate_has_zero_descriptor_hits_and_no_exception():
    proof = scope.b2_isolation_proof(load_conventions())
    scan = proof["C1_call_blindspot_scope"]
    assert scan == dict(
        modules=MODULES, module_count=len(MODULES), hits=[], exceptions=[]
    )
    assert proof["B_release_adapter_scope"]["additional_fixed_compile_sites"] == 0
    assert proof["B_release_adapter_scope"]["dynamic_code_exceptions"] == []


def test_production_predicate_is_the_prelisted_read_only_rule():
    report = json.loads(
        (ROOT / "evidence/evo884-c1-v7-v1/preflight-hit-report.json").read_bytes()
    )
    before = ast.parse(report["rule_source"]).body[0]
    current = next(
        n
        for n in ast.parse(Path(scope.__file__).read_bytes()).body
        if isinstance(n, ast.FunctionDef) and n.name == "_call_descriptor_forbidden"
    )
    assert [ast.dump(n) for n in before.body] == [ast.dump(n) for n in current.body]
    assert report["hit_count"] == 2 and report["additional_hits"] == []


@pytest.fixture(scope="module")
def inspected_trees():
    return {name: ast.parse((ROOT / (name + ".py")).read_bytes()) for name in MODULES}


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("expression", ["compile.__call__", "Path.read_bytes.__call__"])
def test_each_inspected_module_rejects_descriptor_alias_acquisition(
    inspected_trees, module, expression
):
    # Include filename modules that the old loop handles separately.
    trees = dict(inspected_trees)
    trees[module] = deepcopy(trees[module])
    trees[module].body += ast.parse("TEST_ONLY_alias = " + expression).body
    with pytest.raises(ValueError, match="^scope.dynamic_reader_or_code_forbidden$"):
        scope._call_blindspot_scope(trees)


CHILD = """
import importlib.util,json,sys
from pathlib import Path
from qlab.dynamic_factor.conventions import load_conventions
path=Path(sys.argv[1])/'scope_proof.py'
spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.V7_PRIVATE_SCOPE',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
try:
    m.b2_isolation_proof(load_conventions());value={'status':'ACCEPTED'}
except ValueError as exc:value={'status':'REJECTED','reason':str(exc)}
print(json.dumps(value))
"""


def run_gate(root, cwd):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
    }
    env.update(
        PYTHONPATH=str(ROOT.parents[1]),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    p = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(root)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@pytest.mark.parametrize(
    "name", ["open", "eval", "exec", "__import__", "compile", "read_bytes"]
)
@pytest.mark.parametrize("form", ["call", "alias"])
def test_real_copied_gate_rejects_all_named_descriptor_variants(tmp_path, name, form):
    root = tmp_path / "dynamic_factor"
    shutil.copytree(ROOT, root)
    target = root / "b_release_context.py"
    expression = "Path.read_bytes" if name == "read_bytes" else name
    source = (
        "\ndef TEST_ONLY_descriptor():\n    return " + expression + ".__call__(None)\n"
        if form == "call"
        else "\nTEST_ONLY_alias = " + expression + ".__call__\n"
    )
    target.write_text(target.read_text() + source)
    assert run_gate(root, tmp_path) == dict(
        status="REJECTED", reason="scope.dynamic_reader_or_code_forbidden"
    )


@pytest.mark.parametrize("placement", ["top", "reader", "other_function", "lambda"])
def test_compile_anywhere_in_receiver_still_hits_the_unchanged_legacy_ban(
    tmp_path, placement
):
    root = tmp_path / "dynamic_factor"
    shutil.copytree(ROOT, root)
    target = root / "b_release_context.py"
    text = target.read_text()
    call = 'compile("pass", "TEST_ONLY", "exec")'
    if placement == "top":
        text += "\n" + call + "\n"
    elif placement == "reader":
        text = text.replace(
            "    from pathlib import Path\n",
            "    from pathlib import Path\n    " + call + "\n",
            1,
        )
    elif placement == "other_function":
        text = text.replace(
            "def _fail(reason):\n", "def _fail(reason):\n    " + call + "\n", 1
        )
    else:
        text += "\nTEST_ONLY_lambda = lambda: " + call + "\n"
    assert text != target.read_text()
    target.write_text(text)
    assert run_gate(root, tmp_path) == dict(
        status="REJECTED", reason="scope.dynamic_reader_or_code_forbidden"
    )


def test_receiver_has_no_compile_name_or_new_import():
    tree = ast.parse(Path(b.__file__).read_bytes())
    assert not any(
        isinstance(n, ast.Name) and n.id == "compile" for n in ast.walk(tree)
    )
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_read_trusted_release"
    )
    imports = [n for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert len(imports) == 1 and ast.dump(imports[0]) == ast.dump(
        ast.parse("from pathlib import Path").body[0]
    )


def test_unregistered_post_import_disk_drift_still_refuses(copied_host, tmp_path):
    # The process-tampering limitation does not waive the registered module SHA.
    module = copied_host[0]
    program = """
import importlib.util,json,sys
from pathlib import Path
path=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.V7_DRIFT',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
path.write_bytes(path.read_bytes()+b'\\n# TEST_ONLY disk drift after import\\n')
try:m._read_trusted_release();raise AssertionError('unregistered drift accepted')
except ValueError as exc:print(json.dumps({'reason':str(exc)}))
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT.parents[1]), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(module)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == dict(
        reason="B.release_context_acceptance_mismatch"
    )

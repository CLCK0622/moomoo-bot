"""V8 closed structure and event-time contract controls in private copies."""

import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from qlab.dynamic_factor import b_release_context as b, scope_proof as scope
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.conventions import load_conventions
from test_c1_trusted_release import copied_host as copied_host, write_root
from test_c1_rework import SCOPE_CHILD

ROOT = Path(b.__file__).parent


def child(program, *args, cwd):
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
    run = subprocess.run(
        [sys.executable, "-B", "-c", program, *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


TIME_CHILD = """
import importlib.util,json,sys
from pathlib import Path
from qlab.dynamic_factor.conventions import load_conventions
path=Path(sys.argv[1]);case=sys.argv[2]
spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.b_release_context',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
from qlab.dynamic_factor import catalog_v21,noncash_v3
try:
    p=load_conventions();c=m.receive_release_context(policy=p)
    a=json.loads(c.a_raw);mode=a['run_time_binding']['mode']
    req=dict(catalog=catalog_v21.derive(p)['catalog'],synthetic=False,mode=mode,
        sealed_at=c.accepted_at,first_performance_at='2026-11-10T14:30:00Z',
        signal_close=None if mode=='history' else '2026-11-09T21:00:00Z',
        release_binding=dict(h_r=c.h_r,h_a=c.h_a,h_d=c.h_d))
    if case=='first_equal':req['first_performance_at']=c.accepted_at
    if case=='first_before':req['first_performance_at']='2026-11-07T12:00:00Z'
    if case=='first_none':req['first_performance_at']=None
    if case=='first_missing':req.pop('first_performance_at')
    if case=='mode':req['mode']='history' if mode=='forward' else 'forward'
    if case=='signal_before':req['signal_close']='2026-11-07T21:00:00Z'
    if case=='sealed_equal_first':req['sealed_at']=req['first_performance_at']
    raw=m.check_release_context(c,policy=p,request=req)
    if case=='positive':
        noncash_v3.seal_guard(req,p,release_context=c,expected_release_identity_bytes=raw)
    root=(path.parent/'b_release_originals/trust-root-platform-readback.json').read_bytes()
    assert c.acceptance_time_evidence_raw==root
    print(json.dumps(dict(status='TEST_ONLY_ACCEPTED',evidence_raw_exact=True)))
except ValueError as exc:print(json.dumps(dict(status='REJECTED',reason=str(exc))))
"""


@pytest.mark.parametrize("mode", ["history", "forward"])
@pytest.mark.parametrize(
    "case",
    [
        "positive",
        "first_equal",
        "first_before",
        "first_none",
        "first_missing",
        "mode",
        "signal_before",
        "sealed_equal_first",
    ],
)
def test_pre_performance_registration_with_real_request_time(
    copied_host, tmp_path, mode, case
):
    run = copied_host[3]["run_time_binding"]
    run.update(
        mode=mode,
        first_performance_at=None,
        performance_state="pre_performance",
        signal_close=None,
    )
    write_root(copied_host)
    value = child(TIME_CHILD, copied_host[0], case, cwd=tmp_path)
    if case == "positive":
        assert value == dict(status="TEST_ONLY_ACCEPTED", evidence_raw_exact=True)
    else:
        assert value["status"] == "REJECTED"


@pytest.mark.parametrize("mode", ["history", "forward"])
@pytest.mark.parametrize(
    "case", ["no_state", "state_with_time", "wrong_state", "equal", "before"]
)
def test_registration_rejects_all_invalid_event_shapes(
    copied_host, tmp_path, mode, case
):
    run = copied_host[3]["run_time_binding"]
    run.update(
        mode=mode, signal_close=None if mode == "history" else run["signal_close"]
    )
    if case in {"no_state", "wrong_state"}:
        run["first_performance_at"] = None
        if case == "wrong_state":
            run["performance_state"] = "unknown"
    elif case == "state_with_time":
        run["performance_state"] = "pre_performance"
    else:
        run["first_performance_at"] = (
            copied_host[2]["created_at"] if case == "equal" else "2026-11-07T12:00:00Z"
        )
    write_root(copied_host)
    assert (
        child(TIME_CHILD, copied_host[0], "positive", cwd=tmp_path)["status"]
        == "REJECTED"
    )


VARIANTS = {
    "method_direct": '    Path.resolve = lambda value: value.with_name("OTHER.py")\n',
    "method_alias": '    locator = Path\n    locator.resolve = lambda value: value.with_name("OTHER.py")\n',
    "path_alias": "    locator = Path.resolve\n",
    "unlisted_call": "    object()\n",
    "global_file": '    globals()["__file__"] = str(Path(__file__).with_name("OTHER.py"))\n',
    "namespace_file": '    vars()["__file__"] = "OTHER.py"\n',
    "binding_replace": "    global _json\n    _json = lambda raw, **kwargs: {}\n",
    "direct_file": '    global __file__\n    __file__ = str(Path(__file__).with_name("OTHER.py"))\n',
    "self_argument": "",
}

OBSERVE = """
import importlib.util,json,sys
from pathlib import Path
path=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.V8_OBSERVE',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
other=path.with_name('OTHER.py');other.write_bytes(b'TEST_ONLY alternative bytes')
opened=[]
def audit(event,args):
    if event=='open':opened.append(str(args[0]))
sys.addaudithook(audit)
try:
    source=m._read_trusted_release()
    result=dict(status='TEST_ONLY_ACCEPTED',implementation_id=source['implementation_id'])
except Exception as exc:result=dict(status='REJECTED',reason=str(exc),exception_type=type(exc).__name__)
result.update(opened=opened,other_opened=str(other)in opened,self_opened=str(path)in opened)
print(json.dumps(result))
"""


@pytest.mark.parametrize("case", ["normal", *VARIANTS])
def test_same_source_static_decision_and_private_runtime_observation(
    copied_host, tmp_path, case, record_property
):
    module = copied_host[0]
    if case != "normal":
        text = module.read_text()
        if case == "self_argument":
            text = text.replace(
                "Path.read_bytes(self_path)",
                'Path.read_bytes(Path(__file__).with_name("OTHER.py"))',
            )
        else:
            text = text.replace(
                "    from pathlib import Path\n",
                "    from pathlib import Path\n" + VARIANTS[case],
                1,
            )
        module.write_text(text)
        copied_host[3]["implementation_id"] = sha256(module.read_bytes())
        write_root(copied_host)
    identity = sha256(module.read_bytes())
    repo = tmp_path / "scope_copy"
    target = repo / "qlab/qlab/dynamic_factor"
    shutil.copytree(ROOT, target)
    shutil.copyfile(ROOT.parent / "__init__.py", target.parent / "__init__.py")
    shutil.copyfile(module, target / "b_release_context.py")
    assert sha256((target / "b_release_context.py").read_bytes()) == identity
    static = child(SCOPE_CHILD, repo, cwd=tmp_path)
    observed = child(OBSERVE, module, cwd=tmp_path)
    record_property(
        "binding_observation",
        json.dumps(
            dict(case=case, source_sha256=identity, static=static, runtime=observed)
        ),
    )
    if case == "normal":
        assert static == dict(status="ACCEPTED")
        assert observed["status"] == "TEST_ONLY_ACCEPTED" and observed["self_opened"]
        assert (
            not observed["other_opened"] and observed["implementation_id"] == identity
        )
    else:
        assert static["status"] == "REJECTED"


@pytest.mark.parametrize(
    "statement",
    [
        "Path.resolve = lambda value: value",
        "locator = Path\nlocator.resolve = lambda value: value",
        'globals()["_json"] = None',
        'setattr(Path, "resolve", None)',
        'delattr(Path, "resolve")',
        'Path.__dict__["resolve"] = None',
        'sys.modules["pathlib"].Path.resolve = None',
        '__file__ = "OTHER.py"',
    ],
)
def test_other_inspected_source_rejects_dependency_binding_changes(tmp_path, statement):
    repo = tmp_path / "scope_copy"
    root = repo / "qlab/qlab/dynamic_factor"
    shutil.copytree(ROOT, root)
    shutil.copyfile(ROOT.parent / "__init__.py", root.parent / "__init__.py")
    path = root / "valuation.py"
    path.write_text(path.read_text() + "\n" + statement + "\n")
    assert child(SCOPE_CHILD, repo, cwd=tmp_path)["status"] == "REJECTED"


def test_literal_template_precedes_candidate_and_compares_docstrings():
    assert not re.search(r"[0-9a-f]{64}", scope.B_RELEASE_MODULE_TEMPLATE)
    proof = scope.b2_isolation_proof(load_conventions())
    assert proof["C1_dependency_scope"] == dict(
        module_count=42,
        fixed_source_count=40,
        hits=[],
        unresolved_changes=[],
        docstrings_compared=True,
    )
    tree = ast.parse(Path(b.__file__).read_bytes())
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_read_trusted_release"
    )
    fn.body[0].value.value += " TEST_ONLY additional text"
    with pytest.raises(ValueError, match="scope.file_access_not_whitelisted"):
        scope._b_release_adapter_scope(
            tree, ast.parse(Path(scope.__file__).read_bytes())
        )


ACCEPTANCE_CHILD = """
import importlib.util,json,sys,pytest
from pathlib import Path
sys.path.insert(0,sys.argv[3])
from test_b01_release_context import private_host_source
from qlab.dynamic_factor.contract import code_sha,sha256
path=Path(sys.argv[1]);case=sys.argv[2]
spec=importlib.util.spec_from_file_location('qlab.dynamic_factor.V8_ACCEPTANCE',path)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
with pytest.MonkeyPatch.context() as mp:
    source,policy=private_host_source.__wrapped__(mp)
    source['expected_sha256']['implementation_sha256']=code_sha(m.receive_release_context)
    time=json.loads(source['acceptance_time_evidence_raw'])
    if case=='legacy':time=dict(context_version=source['context_version'],receiver_id=source['receiver_id'],accepted_at=source['accepted_at'])
    if case=='author':time['author_id']='TEST_ONLY_OTHER'
    if case=='issue':time['issue_id']='TEST_ONLY_OTHER'
    if case=='created_at':time['created_at']='2026-11-07T19:00:00Z'
    if case in {'context','receiver'}:
        content=json.loads(time['content']);content['context_version' if case=='context' else 'receiver_id']='TEST_ONLY_OTHER';time['content']=json.dumps(content)
    if case=='missing_content':time.pop('content')
    if case=='content_list':time['content']='[]'
    raw=m._canonical(time)
    if case=='invalid_json':raw=b'{'
    source['acceptance_time_evidence_raw']=raw
    source['expected_acceptance_time_bytes']=m._canonical(time)
    source['expected_sha256']['acceptance_time_evidence_raw']=sha256(raw) if case!='sha' else '0'*64
    try:m._acceptance(source,policy);result=dict(status='TEST_ONLY_ACCEPTED')
    except ValueError as exc:result=dict(status='REJECTED',reason=str(exc))
    print(json.dumps(result))
"""


@pytest.mark.parametrize(
    "case",
    [
        "full",
        "legacy",
        "sha",
        "author",
        "issue",
        "created_at",
        "context",
        "receiver",
        "missing_content",
        "content_list",
        "invalid_json",
    ],
)
def test_acceptance_old_and_new_refusal_codes(tmp_path, case, record_property):
    old = tmp_path / "old.py"
    raw = subprocess.check_output(
        ["git", "show", "3feadf6:qlab/qlab/dynamic_factor/b_release_context.py"],
        cwd=ROOT.parents[2],
    )
    old.write_bytes(raw)
    values = [
        child(ACCEPTANCE_CHILD, path, case, Path(__file__).parent, cwd=tmp_path)
        for path in (old, Path(b.__file__))
    ]
    record_property(
        "acceptance_comparison",
        json.dumps(dict(case=case, old=values[0], new=values[1])),
    )
    if case == "full":
        assert values == [
            dict(status="REJECTED", reason="B.release_context_acceptance_mismatch"),
            dict(status="TEST_ONLY_ACCEPTED"),
        ]
    elif case == "legacy":
        assert values == [
            dict(status="TEST_ONLY_ACCEPTED"),
            dict(status="REJECTED", reason="B.release_context_acceptance_mismatch"),
        ]
    else:
        reason = (
            "B.release_context_encoding_invalid"
            if case == "invalid_json"
            else "B.release_context_acceptance_mismatch"
        )
        assert values == [dict(status="REJECTED", reason=reason)] * 2


@pytest.mark.parametrize(
    "statement",
    [
        "Path.__new__ = None",
        "locator = Path\nlocator.arbitrary_method = None",
        "writer = object.__setattr__\nwriter(Path, '__new__', None)",
        "writer = getattr(object, '__setattr__')\nwriter(Path, '__new__', None)",
        "mapping = ast.__dict__\nmapping['TEST_ONLY'] = None",
        "globals()['__file__'] = 'OTHER.py'",
        "object()",
        "str = None",
    ],
)
def test_audit_module_itself_rejects_unlisted_function_structure(tmp_path, statement):
    repo = tmp_path / "scope_copy"
    root = repo / "qlab/qlab/dynamic_factor"
    shutil.copytree(ROOT, root)
    path = root / "scope_proof.py"
    text = path.read_text()
    fn = next(
        n
        for n in ast.parse(text).body
        if isinstance(n, ast.FunctionDef) and n.name == "_call_descriptor_forbidden"
    )
    lines = text.splitlines(keepends=True)
    # The extra statements follow an unconditional return. The real gate reads
    # their structure without executing them in this private observation.
    added = "".join("    " + line + "\n" for line in statement.splitlines())
    path.write_text(
        "".join(lines[: fn.end_lineno]) + added + "".join(lines[fn.end_lineno :])
    )
    assert child(SCOPE_CHILD, repo, cwd=tmp_path) == dict(
        status="REJECTED", reason="scope.file_access_not_whitelisted"
    )

"""Host path, snapshot and authenticated receipt controls in private tmp trees."""

import ast
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest


REPO = Path(__file__).parents[3]
ENTRY = "qlab/tools/c1_source_preflight.py"
HOST = "qlab/tools/c1_host_launcher.py"
DF = "qlab/qlab/dynamic_factor"
spec = importlib.util.spec_from_file_location("c1_host_unit", REPO / HOST)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def sample(repo, opdir):
    """Synthetic mechanism data; it has no platform credentials or authority."""
    literals = {
        n.targets[0].id: ast.literal_eval(n.value)
        for n in ast.parse((repo / ENTRY).read_bytes()).body
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id in {"SOURCE_FILES", "DATA_FILES"}
    }
    names = {
        str((repo / DF / n).resolve().relative_to(repo))
        for n in literals["SOURCE_FILES"] + literals["DATA_FILES"]
    } | {HOST}
    d = dict(
        schema="EVO884.C1HostRegistration/v1",
        context_version="MECHANISM_SAMPLE_ONLY",
        source_commit="mechanism-sample",
        repository_root=str(repo),
        operator_directory=str(opdir),
        entry=ENTRY,
        launcher=HOST,
        files={n: sha((repo / n).read_bytes()) for n in sorted(names)},
        interpreter=dict(
            path=os.path.realpath(sys.executable),
            sha256=sha(Path(os.path.realpath(sys.executable)).read_bytes()),
        ),
        operators=["MECHANISM_SAMPLE_OPERATOR"],
        authors=sorted(host.AUTHORS),
        reviewer="MECHANISM_SAMPLE_REVIEWER",
        limits=dict(timeout_seconds=60, output_bytes=16 * 1024 * 1024),
    )
    _, own = host.identity(str(repo / HOST))
    own.update(relative=HOST, expected_sha256=d["files"][HOST])
    q = dict(
        schema="EVO884.C1OperatorPrecheck/v1",
        run_id=str(uuid.uuid4()),
        nonce=str(uuid.uuid4()),
        context_version=d["context_version"],
        registration_sha256=sha(host.canonical(d)),
        registration_ref=dict(
            comment_id="00000000-0000-0000-0000-000000000001", revision=1
        ),
        operator_id=d["operators"][0],
        task_id="MECHANISM_SAMPLE_TASK",
        session_id="MECHANISM_SAMPLE_SESSION",
        launcher_identity=own,
        system_hash_command="shasum -a 256",
        system_hash_sha256=d["files"][HOST],
    )
    return d, q


@pytest.fixture
def tree(tmp_path):
    repo = (tmp_path / "candidate").resolve()
    shutil.copytree(
        REPO / "qlab",
        repo / "qlab",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    op = (tmp_path / "operator-sample").resolve()
    op.mkdir()
    d, q = sample(repo, op)
    return repo, op, d, q


def launch(tree, requested=None):
    repo, op, d, q = tree
    config = op / ("D-" + str(uuid.uuid4()) + ".json")
    precheck = op / ("Q0-" + str(uuid.uuid4()) + ".json")
    config.write_bytes(host.canonical(d))
    precheck.write_bytes(host.canonical(q))
    output = op / ("run-" + str(uuid.uuid4()))
    argv = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(repo / HOST),
        "observe",
        "--registration",
        str(config),
        "--precheck",
        str(precheck),
        "--entry",
        str(requested or repo / ENTRY),
        "--output",
        str(output),
    ]
    run = subprocess.run(argv, cwd=op, capture_output=True)
    assert run.stdout, run.stderr.decode()
    result = json.loads(run.stdout)
    return (
        result,
        output,
        dict(
            argv=argv,
            cwd=str(op),
            returncode=run.returncode,
            stderr=run.stderr.decode(),
        ),
    )


def record(record_property, name, result, output, execution):
    evidence = dict(
        receipt=result,
        launch=execution,
        actual_open_paths=[r["path"] for r in result.get("before") or []],
    )
    child = output / "child-stdout.raw"
    evidence["child_events"] = (
        json.loads(child.read_bytes()).get("events", []) if child.exists() else None
    )
    record_property(name, json.dumps(evidence, sort_keys=True))


def test_host_positive_pending_formal_intake(tree, record_property):
    r, output, run = launch(tree)
    assert r["status"] == "VERIFIED_MECHANISM", r
    assert r["formal_result"] is r["C1_dependency_closed"] is False
    assert r["before"] == r["after"] and len(r["before"]) == 99
    assert r["checks"]["entry_path"]["accepted"]
    assert r["checks"]["source_sha_complete"]
    assert r["secondary_reasons"] == []
    assert len(r["held_after"]) == 102
    assert r["interpreter_before"] == r["interpreter_after"]
    p = json.loads((output / "candidate-proof.json").read_bytes())
    assert p["host_finalization_pending"] and not p["C1_dependency_closed"]
    assert p["startup"]["entry"] == str(tree[0] / ENTRY)
    assert r["child"]["argv"][1:4] == ["-I", "-S", "-B"]
    assert r["child"]["cwd"] == str(tree[0])
    events = p["events"]
    first = next(e["sequence"] for e in events if e["event"] == "preflight_conclusion")
    last = next(e["sequence"] for e in events if e["event"] == "B2_complete")
    imports = [
        e
        for e in events
        if e["event"] == "import"
        and (e["module"] == "qlab" or e["module"].startswith("qlab."))
    ]
    assert imports and all(first < e["sequence"] < last for e in imports)
    assert {e["module"] for e in imports} == {m["module"] for m in p["import_binding"]}
    assert all(
        row["observed_sha256"] == row["expected_sha256"] for row in p["import_binding"]
    )
    with pytest.raises(ValueError, match="host.receipt_required"):
        host.intake(str(output), r["run_id"], r["context_version"], {}, {}, {})
    record(record_property, "host_positive", r, output, run)


@pytest.mark.parametrize(
    "case",
    [
        "renamed_request",
        "hardlink_request",
        "registered_change_and_renamed",
        "registered_change_only",
    ],
)
def test_original_path_experiments_and_separate_sha_guard(tree, case, record_property):
    repo = tree[0]
    original = repo / ENTRY
    other = original.with_name("MECHANISM_SAMPLE_renamed_entry.py")
    if case == "hardlink_request":
        os.link(original, other)
        assert original.stat().st_ino == other.stat().st_ino
    else:
        other.write_bytes(original.read_bytes())
    if case.startswith("registered_change"):
        original.write_bytes(
            original.read_bytes() + b"\nMECHANISM_SAMPLE_ADDED = True\n"
        )
    requested = original if case == "registered_change_only" else other
    r, output, run = launch(tree, requested)
    expected = (
        "host.source_sha_mismatch"
        if case == "registered_change_only"
        else ("host.entry_path_not_registered")
    )
    assert r["reason"] == expected and r["child"] is None
    assert r["secondary_reasons"] == (
        ["host.source_sha_mismatch"] if case == "registered_change_and_renamed" else []
    )
    assert r["checks"]["entry_path"]["accepted"] == (case == "registered_change_only")
    assert r["checks"]["source_sha_complete"] and len(r["before"]) == 99
    mismatches = [
        row for row in r["before"] if row["observed_sha256"] != row["expected_sha256"]
    ]
    assert [row["path"] for row in mismatches] == (
        [str(original)] if case.startswith("registered_change") else []
    )
    record(record_property, "path_experiment_" + case, r, output, run)


@pytest.mark.parametrize("changed_sources", [0, 1, 2])
def test_path_check_precedes_reads_and_sha_checks_finish(
    tree, monkeypatch, changed_sources, record_property
):
    repo, op, d, q = tree
    other = repo / "qlab/tools/MECHANISM_SAMPLE_renamed_entry.py"
    other.write_bytes((repo / ENTRY).read_bytes())
    for name in [ENTRY, DF + "/contract.py"][:changed_sources]:
        path = repo / name
        path.write_bytes(path.read_bytes() + b"\nMECHANISM_SAMPLE_ADDED = True\n")
    controls = [op / "D.json", op / "Q0.json"]
    for path, value in zip(controls, [d, q]):
        path.write_bytes(host.canonical(value))
    output = op / "observations"
    output.mkdir()
    events = []
    real_check, real_identity = host.entry_path_check, host.identity

    def check(*args):
        result = real_check(*args)
        events.append(dict(event="entry_path_check", result=result))
        return result

    def identity(path, *args):
        events.append(dict(event="registered_read", path=str(path)))
        return real_identity(path, *args)

    monkeypatch.chdir(op)
    monkeypatch.setattr(host, "__file__", str(repo / HOST))
    monkeypatch.setattr(sys, "path", [])
    # Match a fresh launcher's module state during in-process observation.
    for name in list(sys.modules):
        if name == "qlab" or name.startswith("qlab."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(host, "entry_path_check", check)
    monkeypatch.setattr(host, "identity", identity)
    r = host.observe(d, q, str(output), str(other), list(map(str, controls)))
    assert events[0]["event"] == "entry_path_check"
    assert not events[0]["result"]["accepted"]
    assert len([e for e in events if e["event"] == "registered_read"]) == 102
    assert len(r["before"]) == 99 and r["checks"]["source_sha_complete"]
    assert (
        sum(row["observed_sha256"] != row["expected_sha256"] for row in r["before"])
        == changed_sources
    )
    assert r["reason"] == "host.entry_path_not_registered" and r["child"] is None
    assert r["secondary_reasons"] == (
        ["host.source_sha_mismatch"] if changed_sources else []
    )
    record_property(
        "path_check_read_order",
        json.dumps(dict(receipt=r, events=events), sort_keys=True),
    )


@pytest.mark.parametrize(
    "case", ["original_read_return", "hashlib_binding", "os_read_wrapper"]
)
def test_three_original_source_controls_before_child(tree, case, record_property):
    path = tree[0] / DF / "contract.py"
    if case == "original_read_return":
        raw = (
            Path(__file__).parent / "fixtures/C1-R3/original-contract.py.fixture"
        ).read_bytes()
        assert (
            sha(raw)
            == "8cbcda793c9abd5722d20aa3674a3eb078af7823060da91008878e66df21ee3f"
        )
    elif case == "hashlib_binding":
        raw = (
            path.read_bytes()
            + b"\nimport hashlib\nhashlib.sha256 = lambda value: None\n"
        )
    else:
        raw = (
            path.read_bytes()
            + b"\nimport os\nos.read = lambda fd, size: b'TEST_ONLY'\n"
        )
    path.write_bytes(raw)
    r, output, run = launch(tree)
    assert r["reason"] == "host.source_sha_mismatch" and r["child"] is None
    row = next(x for x in r["before"] if x["path"] == str(path))
    assert row["observed_sha256"] == sha(raw) != row["expected_sha256"]
    record(record_property, "original_source_control_" + case, r, output, run)


def entry_run(tree, output, entry=None):
    repo = tree[0]
    m = output / "host-source-manifest.json"
    argv = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(entry or repo / ENTRY),
        "--host-manifest",
        str(m),
        "--host-manifest-sha256",
        sha(m.read_bytes()),
    ]
    run = subprocess.run(argv, cwd=repo, capture_output=True)
    assert run.stdout, run.stderr.decode()
    return json.loads(run.stdout)


@pytest.mark.parametrize("case", ["rename", "hardlink", "new_inode", "different_bytes"])
def test_E_checks_own_path_inode_and_sha_independently(tree, case, record_property):
    r, output, _ = launch(tree)
    assert r["status"] == "VERIFIED_MECHANISM"
    original = tree[0] / ENTRY
    other = original.with_name("MECHANISM_SAMPLE_alternate_entry.py")
    if case == "hardlink":
        os.link(original, other)
    else:
        other.write_bytes(original.read_bytes())
    entry = original
    if case in {"rename", "hardlink"}:
        entry = other
        expected = "scope.host_entry_path_mismatch"
    elif case == "new_inode":
        os.replace(other, original)
        expected = "scope.host_entry_identity_mismatch"
    else:
        raw = original.read_bytes().replace(b"Controlled C1", b"CONTROLLED C1", 1)
        assert len(raw) == original.stat().st_size
        original.write_bytes(raw)
        expected = "scope.host_entry_sha_mismatch"
    p = entry_run(tree, output, entry)
    assert p["reason"] == expected
    assert not any(
        e["event"] == "import" and e["module"].startswith("qlab") for e in p["events"]
    )
    record_property("E_identity_" + case, json.dumps(p, sort_keys=True))


@pytest.mark.parametrize(
    "case",
    ["missing", "duplicate_key", "extra_field", "snapshot_bytes", "manifest_digest"],
)
def test_E_manifest_schema_and_snapshot_controls(tree, case):
    r, output, _ = launch(tree)
    assert r["status"] == "VERIFIED_MECHANISM"
    mp = output / "host-source-manifest.json"
    if case == "missing":
        run = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(tree[0] / ENTRY)],
            cwd=tree[0],
            capture_output=True,
        )
        assert json.loads(run.stdout)["reason"] == "scope.host_manifest_required"
        return
    raw = mp.read_bytes()
    os.chmod(mp, 0o600)
    m = json.loads(raw)
    if case == "duplicate_key":
        mp.write_bytes(raw.replace(b"{", b'{"root":0,', 1))
    elif case == "extra_field":
        m["extra"] = True
        mp.write_bytes(host.canonical(m))
    elif case == "snapshot_bytes":
        m["files"][0]["raw_base64"] = base64.b64encode(b"different").decode()
        mp.write_bytes(host.canonical(m))
    else:
        m["files"][0]["expected_sha256"] = "0" * 64
        mp.write_bytes(host.canonical(m))
    p = entry_run(tree, output)
    assert p["status"] == "REJECTED"
    assert p["reason"] in {
        "scope.host_manifest_encoding_invalid",
        "scope.host_manifest_scope_mismatch",
        "scope.host_snapshot_mismatch",
    }


@pytest.mark.parametrize("case", ["symlink", "directory", "changed_read"])
def test_host_regular_file_and_stable_read(tmp_path, monkeypatch, case):
    p = tmp_path / "regular"
    p.write_bytes(b"a")
    if case == "symlink":
        link = tmp_path / "link"
        link.symlink_to(p)
        with pytest.raises(OSError):
            host.identity(str(link))
    elif case == "directory":
        with pytest.raises(ValueError, match="host.file_not_regular"):
            host.identity(str(tmp_path))
    else:
        original = host.os.read

        def changed(fd, count):
            p.write_bytes(b"longer")
            return original(fd, count)

        monkeypatch.setattr(host.os, "read", changed)
        with pytest.raises(ValueError, match="host.file_changed_during_read"):
            host.identity(str(p))


@pytest.mark.parametrize("case", ["timeout", "output_limit", "child_failure"])
def test_host_bounded_child(tmp_path, case):
    program = {
        "timeout": "import time;time.sleep(3)",
        "output_limit": "print('x'*50000)",
        "child_failure": "raise SystemExit(7)",
    }[case]
    result = host.child(
        [sys.executable, "-I", "-S", "-B", "-c", program],
        str(tmp_path),
        dict(timeout_seconds=1, output_bytes=1000),
    )
    if case == "child_failure":
        assert result["returncode"] == 7
    else:
        assert result["reason"] == "host.child_" + case


@pytest.mark.parametrize(
    "case",
    [
        "missing_R",
        "missing_Q1",
        "missing_F",
        "foreign_run",
        "foreign_context",
        "synthetic_source",
    ],
)
def test_outer_intake_requires_receipt_provenance_and_current_run(
    tree, case, monkeypatch
):
    r, output, _ = launch(tree)
    assert r["status"] == "VERIFIED_MECHANISM"
    (output / "operator-final-platform-readback.json").write_bytes(b"{}\n")
    (output / "host-bound-proof.json").write_bytes(b"{}\n")
    if case.startswith("missing_"):
        name = {
            "missing_R": "host-launch-receipt.json",
            "missing_Q1": "operator-final-platform-readback.json",
            "missing_F": "host-bound-proof.json",
        }[case]
        (output / name).unlink()
    called = []

    def reject_local_claim(*args):
        called.append(args)
        raise host.Refusal("host.receipt_provenance_invalid")

    monkeypatch.setattr(host, "platform_record", reject_local_claim)
    reason = (
        "host.receipt_required"
        if case.startswith("missing_")
        else "host.receipt_replay"
        if case in {"foreign_run", "foreign_context"}
        else "host.receipt_provenance_invalid"
    )
    with pytest.raises(ValueError, match=reason):
        host.intake(
            str(output),
            "other" if case == "foreign_run" else r["run_id"],
            "other" if case == "foreign_context" else r["context_version"],
            {},
            {},
            {},
        )
    assert bool(called) == (case == "synthetic_source")


def test_live_platform_reader_is_mandatory_not_author_fields(monkeypatch):
    def failed_cli(argv, **kwargs):
        assert argv[:4] == ["multica", "issue", "comment", "list"]
        assert "--compact" not in argv and "--output" in argv
        return subprocess.CompletedProcess(argv, 1, b"", b"unauthenticated")

    monkeypatch.setattr(host.subprocess, "run", failed_cli)
    with pytest.raises(ValueError, match="host.receipt_provenance_invalid"):
        host.platform_record(
            dict(comment_id=str(uuid.uuid4()), revision=1), host.RUN_ISSUE
        )


@pytest.mark.parametrize(
    "bad",
    [
        b'{"a":1,"a":2}\n',
        b'{ "a":1}\n',
        b'{"a":NaN}\n',
        b'{"a":1.0}\n',
        b"{}",
        b"\xef\xbb\xbf{}\n",
    ],
)
def test_canonical_json_controls(bad):
    with pytest.raises(ValueError):
        host.parse(bad)


def test_source_hashes_are_data_only():
    paths = [
        REPO / p
        for p in (HOST, ENTRY, DF + "/scope_proof.py", DF + "/b_release_context.py")
    ]
    hashes = [sha(p.read_bytes()) for p in paths]
    for p in paths[:3]:
        assert all(h.encode() not in p.read_bytes() for h in hashes)
    entry = ast.parse((REPO / ENTRY).read_bytes())
    assert not any(
        isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and len(n.value) == 64
        and set(n.value) <= set("0123456789abcdef")
        for n in ast.walk(entry)
    )


POST_UNIT = r"""
import json,os,runpy,sys
root,op,dp,qp,out,case=sys.argv[1:]
ns=runpy.run_path(os.path.join(root,'qlab/tools/c1_host_launcher.py'),run_name='HOST_POST_UNIT')
g=ns['observe'].__globals__;original=g['child']
def changed(argv,cwd,limits):
    result=original(argv,cwd,limits)
    assert result['returncode']==0,result
    if case=='file_identity':
        target=os.path.join(root,'qlab/qlab/dynamic_factor/contract.py')
        raw=open(target,'rb').read();other=target+'.MECHANISM_SAMPLE';open(other,'wb').write(raw);os.replace(other,target)
    elif case=='manifest_bytes':
        target=argv[6];os.chmod(target,0o600);open(target,'ab').write(b'\n')
    elif case=='proof_binding':
        p=json.loads(result['stdout']);p['manifest_sha256']='0'*64;result['stdout']=g['canonical'](p)
    elif case=='control_identity':
        raw=open(dp,'rb').read();other=dp+'.MECHANISM_SAMPLE';open(other,'wb').write(raw);os.replace(other,dp)
    return result
g['child']=changed
os.mkdir(out);os.chdir(op)
r=ns['observe'](ns['read'](dp),ns['read'](qp),out,os.path.join(root,'qlab/tools/c1_source_preflight.py'),(dp,qp))
sys.stdout.buffer.write(ns['canonical'](r))
"""


@pytest.mark.parametrize(
    "case", ["file_identity", "manifest_bytes", "proof_binding", "control_identity"]
)
def test_host_post_observation_controls(tree, case, record_property):
    repo, op, d, q = tree
    dp, qp, output = op / "D-post.json", op / "Q0-post.json", op / "post-observation"
    dp.write_bytes(host.canonical(d))
    qp.write_bytes(host.canonical(q))
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            POST_UNIT,
            str(repo),
            str(op),
            str(dp),
            str(qp),
            str(output),
            case,
        ],
        cwd=op,
        capture_output=True,
    )
    assert run.returncode == 0, run.stderr.decode()
    r = json.loads(run.stdout)
    assert (
        r["reason"]
        == {
            "file_identity": "host.postrun_identity_mismatch",
            "manifest_bytes": "host.manifest_changed",
            "proof_binding": "host.proof_manifest_mismatch",
            "control_identity": "host.manifest_changed",
        }[case]
    )
    assert r["formal_result"] is False and r["child"]["returncode"] == 0
    record(
        record_property, "host_post_" + case, r, output, dict(returncode=run.returncode)
    )


def test_atomic_publication_is_exclusive_and_complete(tmp_path):
    path = host.save(str(tmp_path), "object.json", b"{}\n")
    assert (
        Path(path).read_bytes() == b"{}\n"
        and Path(path).stat().st_mode & 0o777 == 0o444
    )
    with pytest.raises(FileExistsError):
        host.save(str(tmp_path), "object.json", b'{"other":1}\n')
    assert (
        Path(path).read_bytes() == b"{}\n" and list(tmp_path.glob(".pending-*")) == []
    )


def test_live_preflight_refuses_local_data_without_registered_author(tree, monkeypatch):
    d, q = tree[2:]

    def records(ref, issue):
        return (
            dict(author_id="MECHANISM_SAMPLE_AUTHOR"),
            d if issue == host.ROOT_ISSUE else q,
            b"[]\n",
        )

    monkeypatch.setattr(host, "platform_record", records)
    with pytest.raises(ValueError, match="host.registration_provenance_invalid"):
        host.live_preflight(
            d, q, q["registration_ref"], dict(comment_id=str(uuid.uuid4()), revision=1)
        )


def test_live_preflight_requires_platform_task_identity(tree, monkeypatch):
    d, q = tree[2:]

    def records(ref, issue):
        return (
            dict(
                author_id=host.REGISTRAR
                if issue == host.ROOT_ISSUE
                else q["operator_id"],
                source_task_id="DIFFERENT_PLATFORM_TASK",
            ),
            d if issue == host.ROOT_ISSUE else q,
            b"[]\n",
        )

    monkeypatch.setattr(host, "platform_record", records)
    with pytest.raises(ValueError, match="host.operator_precheck_invalid"):
        host.live_preflight(
            d, q, q["registration_ref"], dict(comment_id=str(uuid.uuid4()), revision=1)
        )


def test_outer_intake_refuses_unknown_receipt_version_before_platform(tmp_path):
    for name in (
        "host-launch-receipt.json",
        "operator-final-platform-readback.json",
        "host-bound-proof.json",
    ):
        (tmp_path / name).write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="host.receipt_binding_mismatch"):
        host.intake(str(tmp_path), "sample", "sample", {}, {}, {})


@pytest.mark.parametrize("kind", ["package", "extension"])
def test_import_spec_is_source_bound_before_any_qlab_import(
    tree, kind, record_property
):
    repo = tree[0]
    if kind == "package":
        extra = repo / DF / "scope_proof/__init__.py"
        extra.parent.mkdir()
        extra.write_text(
            'raise RuntimeError("MECHANISM_SAMPLE_unregistered_package")\n'
        )
    else:
        from importlib.machinery import EXTENSION_SUFFIXES

        extra = repo / DF / ("scope_proof" + EXTENSION_SUFFIXES[0])
        extra.write_bytes(b"MECHANISM_SAMPLE_NOT_A_LIBRARY")
    r, output, run = launch(tree)
    assert r["reason"] == "host.child_failed"
    p = json.loads((output / "child-stdout.raw").read_bytes())
    assert p["reason"] == "scope.preflight_loading_mismatch"
    assert not any(
        e["event"] == "import"
        and (e["module"] == "qlab" or e["module"].startswith("qlab."))
        for e in p["events"]
    )
    assert any(
        e["event"] == "module_spec"
        and e["path"] == str(extra)
        and e["expected_path"] != str(extra)
        for e in p["events"]
    )
    record_property(
        "module_spec_" + kind,
        json.dumps(dict(extra_path=str(extra), result=p, launch=run), sort_keys=True),
    )


@pytest.mark.parametrize("module", ["ast", "pathlib"])
def test_standard_library_resolution_does_not_search_candidate_parent(
    tree, module, record_property
):
    repo = tree[0]
    extra = repo / "qlab" / (module + ".py")
    extra.write_text('raise RuntimeError("MECHANISM_SAMPLE_unregistered_module")\n')
    r, output, run = launch(tree)
    assert r["status"] == "VERIFIED_MECHANISM", r
    p = json.loads((output / "candidate-proof.json").read_bytes())
    assert not any(
        e["event"] == "open" and e["path"] == str(extra) for e in p["events"]
    )
    assert all(
        not path.startswith(str(repo) + os.sep) for path in p["stdlib_origins"].values()
    )
    record_property(
        "stdlib_resolution_" + module,
        json.dumps(
            dict(
                origins=p["stdlib_origins"],
                events=p["events"],
                launch=run,
                extra_path=str(extra),
            ),
            sort_keys=True,
        ),
    )

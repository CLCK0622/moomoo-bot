"""One-shot host observations and authenticated outer receipt intake.

Receipts describe pre/post observations, not complete execution images. Formal
intake always reads D/Q0/Q1 through the authenticated platform CLI. Local JSON,
file mode bits and matching digests alone never establish provenance. Changes
restored between observations, same-UID interference and changed host/runtime
libraries are outside this mechanism. The receiver API remains unchanged.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import selectors
import stat
import subprocess
import sys
import time
import uuid


ENTRY = "qlab/tools/c1_source_preflight.py"
LAUNCHER = "qlab/tools/c1_host_launcher.py"
AUDITOR = "qlab/qlab/dynamic_factor/scope_proof.py"
RECEIVER = "qlab/qlab/dynamic_factor/b_release_context.py"
ROOT_ISSUE = "01a19dab-15f2-7e58-96a0-cf92c87162c2"
RUN_ISSUE = "01a18a63-0661-763c-8801-934689b0954e"
REGISTRAR = "cc562115-7ef6-4b8f-b4b6-a5b7584b1340"
AUTHORS = {"5a307571-9534-4bbc-932c-93ffc9c94d73"}
LIMIT = 16 * 1024 * 1024


class Refusal(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise Refusal(code)


def canonical(value):
    def check(item):
        require(
            type(item) in (dict, list, str, int, bool, type(None)),
            "host.encoding_invalid",
        )
        if type(item) is dict:
            require(all(type(k) is str for k in item), "host.encoding_invalid")
            for v in item.values():
                check(v)
        elif type(item) is list:
            for v in item:
                check(v)

    check(value)
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            require(key not in obj, "host.encoding_invalid")
            obj[key] = value
        return obj

    require(len(raw) <= LIMIT, "host.encoding_invalid")
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        require(canonical(value) == raw, "host.encoding_invalid")
        return value
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise Refusal("host.encoding_invalid") from exc


def fields(value, keys, code="host.scope_mismatch"):
    require(type(value) is dict and set(value) == set(keys.split()), code)


def identity(path, held=None):
    """Read a regular final component without following a symbolic link."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    retained = False
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), "host.file_not_regular")
        require(before.st_size <= 128 * 1024 * 1024, "host.file_not_regular")
        chunks = []
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            chunks.append(part)
            require(sum(map(len, chunks)) <= 128 * 1024 * 1024, "host.file_not_regular")
        raw = b"".join(chunks)
        after = os.fstat(fd)

        def signature(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns

        require(
            signature(before) == signature(after) and len(raw) == before.st_size,
            "host.file_changed_during_read",
        )
        row = dict(
            path=os.path.realpath(path),
            bytes=len(raw),
            st_dev=before.st_dev,
            st_ino=before.st_ino,
            st_mtime_ns=before.st_mtime_ns,
            observed_sha256=sha(raw),
        )
        if held is not None:
            held.append((fd, dict(row)))
            retained = True
        return raw, row
    finally:
        if not retained:
            os.close(fd)


def read(path):
    return parse(identity(path)[0])


def save(folder, name, raw):
    path = os.path.join(folder, name)
    temporary = os.path.join(folder, ".pending-" + str(uuid.uuid4()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            require(count > 0, "host.output_failed")
            view = view[count:]
        os.fsync(fd)
        os.fchmod(fd, 0o444)
    finally:
        os.close(fd)
    try:
        # link is an atomic no-replace publication of the completed inode.
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)
    return path


def registration(d):
    fields(
        d,
        "schema context_version source_commit repository_root operator_directory "
        "entry launcher interpreter files operators authors reviewer limits",
    )
    require(d["schema"] == "EVO884.C1HostRegistration/v1", "host.scope_mismatch")
    root = d["repository_root"]
    require(
        type(root) is str and type(d["operator_directory"]) is str,
        "host.scope_mismatch",
    )
    require(os.path.isabs(root) and os.path.realpath(root) == root, "host.cwd_mismatch")
    opdir = d["operator_directory"]
    forbidden = [
        os.path.expanduser("~/multica-reports/evo353"),
        os.path.expanduser("~/opend_snapshot"),
        root,
    ]
    require(
        os.path.isabs(opdir)
        and os.path.realpath(opdir) == opdir
        and all(os.path.commonpath((opdir, p)) != p for p in forbidden),
        "host.cwd_mismatch",
    )
    require(
        d["entry"] == ENTRY and d["launcher"] == LAUNCHER,
        "host.entry_path_not_registered",
    )
    fields(d["interpreter"], "path sha256")
    fields(d["limits"], "timeout_seconds output_bytes")
    require(
        type(d["limits"]["timeout_seconds"]) is int
        and 0 < d["limits"]["timeout_seconds"] <= 3600
        and type(d["limits"]["output_bytes"]) is int
        and 0 < d["limits"]["output_bytes"] <= LIMIT,
        "host.scope_mismatch",
    )
    require(
        type(d["files"]) is dict
        and all(
            type(p) is str
            and not os.path.isabs(p)
            and ".." not in p.split("/")
            and type(h) is str
            and len(h) == 64
            and set(h) <= set("0123456789abcdef")
            for p, h in d["files"].items()
        ),
        "host.scope_mismatch",
    )
    require(
        {ENTRY, AUDITOR, RECEIVER, LAUNCHER} <= set(d["files"]), "host.scope_mismatch"
    )
    require(
        type(d["operators"]) is list
        and d["operators"]
        and type(d["authors"]) is list
        and d["authors"]
        and not (set(d["operators"]) & (set(d["authors"]) | AUTHORS | {d["reviewer"]})),
        "host.operator_precheck_invalid",
    )
    return root


def precheck(d, q0):
    fields(
        q0,
        "schema run_id nonce context_version registration_sha256 registration_ref "
        "operator_id task_id session_id launcher_identity system_hash_command system_hash_sha256",
    )
    try:
        require(
            str(uuid.UUID(q0["run_id"])) == q0["run_id"],
            "host.operator_precheck_invalid",
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise Refusal("host.operator_precheck_invalid") from exc
    require(
        q0["schema"] == "EVO884.C1OperatorPrecheck/v1"
        and q0["operator_id"] in d["operators"]
        and q0["context_version"] == d["context_version"]
        and q0["registration_sha256"] == sha(canonical(d))
        and all(
            type(q0[k]) is str and q0[k]
            for k in ("run_id", "nonce", "task_id", "session_id")
        )
        and q0["system_hash_command"] == "shasum -a 256"
        and q0["system_hash_sha256"] == d["files"][LAUNCHER],
        "host.operator_precheck_invalid",
    )
    fields(q0["registration_ref"], "comment_id revision")


def collect(d, requested_entry, observations=None, held=None):
    root = registration(d)
    observations = [] if observations is None else observations
    snapshots = []
    # Identity refusal has precedence over a simultaneous requested-name error.
    for relative, expected in sorted(d["files"].items()):
        if relative == LAUNCHER:
            continue
        path = os.path.join(root, relative)
        require(os.path.realpath(path) == path, "host.file_identity_mismatch")
        raw, row = identity(path, held)
        row.update(
            relative=relative,
            expected_sha256=expected,
            role="source" if relative.endswith(".py") else "data",
        )
        observations.append(row)
        require(row["observed_sha256"] == expected, "host.source_sha_mismatch")
        if relative != LAUNCHER:
            snapshots.append(
                dict(row, raw_base64=base64.b64encode(raw).decode("ascii"))
            )
    actual_entry = os.path.abspath(requested_entry)
    require(
        actual_entry == os.path.join(root, ENTRY)
        and os.path.realpath(actual_entry) == actual_entry,
        "host.entry_path_not_registered",
    )
    return observations, snapshots


def child(argv, cwd, limits):
    """Bound output while draining both pipes; no shell or candidate imports."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PYTEST", "QLAB_"))
    }
    out, err = bytearray(), bytearray()
    start = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        shell=False,
    )
    reason = None
    with selectors.DefaultSelector() as selector:
        for stream, target in ((process.stdout, out), (process.stderr, err)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, target)
        try:
            while selector.get_map():
                if time.monotonic() - start > limits["timeout_seconds"]:
                    reason = "host.child_timeout"
                    break
                for key, _ in selector.select(0.1):
                    value = os.read(key.fileobj.fileno(), 65536)
                    if not value:
                        selector.unregister(key.fileobj)
                    else:
                        key.data.extend(value)
                    if len(out) + len(err) > limits["output_bytes"]:
                        reason = "host.child_output_limit"
                        break
                if reason:
                    break
        finally:
            if reason:
                process.kill()
            try:
                process.wait(
                    timeout=max(
                        0.01, limits["timeout_seconds"] - (time.monotonic() - start)
                    )
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                reason = "host.child_timeout"
            process.stdout.close()
            process.stderr.close()
    return dict(
        pid=process.pid,
        argv=argv,
        cwd=cwd,
        returncode=process.returncode,
        reason=reason,
        stdout=bytes(out),
        stderr=bytes(err),
    )


def observe(d, q0, folder, requested_entry, control_paths, platform_evidence=None):
    """Produce observations. Only authenticated intake can recognize a result."""
    r = dict(
        schema="EVO884.C1HostLaunchReceipt/v1",
        status="REJECTED",
        reason=None,
        failure_stage="precheck",
        formal_result=False,
        C1_dependency_closed=False,
        registration_sha256=sha(canonical(d)),
        precheck_sha256=sha(canonical(q0)),
        run_id=q0.get("run_id"),
        context_version=d.get("context_version"),
        manifest_sha256=None,
        proof_sha256=None,
        before=None,
        after=None,
        child=None,
        interpreter_before=None,
        interpreter_after=None,
        authority="pending_authenticated_outer_intake",
        actual_A_issued=False,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        controls_before=None,
        controls_after=None,
        nonce=q0.get("nonce"),
        launcher_identity=q0.get("launcher_identity"),
        runtime_consumable=False,
        certifiable=False,
        held_after=None,
        preflight_authority="authenticated_readbacks"
        if platform_evidence
        else "mechanism_sample_only",
        host_monotonic_ns=time.monotonic_ns(),
    )
    held = []
    try:
        control_reads = [identity(path, held) for path in control_paths]
        require(
            [raw for raw, _ in control_reads] == [canonical(d), canonical(q0)],
            "host.manifest_changed",
        )
        r["controls_before"] = [row for _, row in control_reads]
        root = registration(d)
        precheck(d, q0)
        require(
            os.path.abspath(__file__) == os.path.join(root, LAUNCHER),
            "host.entry_path_not_registered",
        )
        require(
            os.path.realpath(os.getcwd()) == d["operator_directory"],
            "host.cwd_mismatch",
        )
        require(
            os.path.realpath(sys.executable) == d["interpreter"]["path"],
            "host.interpreter_mismatch",
        )
        require(
            not any(
                p and os.path.commonpath((root, os.path.realpath(p))) == root
                for p in sys.path
            ),
            "host.cwd_mismatch",
        )
        require(
            not any(n == "qlab" or n.startswith("qlab.") for n in sys.modules),
            "host.candidate_already_loaded",
        )
        raw_python, python_before = identity(d["interpreter"]["path"], held)
        require(
            sha(raw_python) == d["interpreter"]["sha256"], "host.interpreter_mismatch"
        )
        r["interpreter_before"] = python_before
        r["before"] = []
        before, snapshots = collect(d, requested_entry, r["before"], held)
        launcher = q0["launcher_identity"]
        require(
            launcher["path"] == os.path.join(root, LAUNCHER)
            and launcher["relative"] == LAUNCHER
            and launcher["observed_sha256"]
            == launcher["expected_sha256"]
            == d["files"][LAUNCHER],
            "host.operator_precheck_invalid",
        )
        intent = dict(
            root=root,
            entry=d["entry"],
            interpreter=d["interpreter"],
            flags=["-I", "-S", "-B"],
            manifest_sha256_argument="sha256_of_final_manifest_bytes",
        )
        save(
            folder,
            "launch-intent.json",
            canonical(intent),
        )
        m = dict(
            schema="EVO884.C1HostSourceManifest/v1",
            run_id=q0["run_id"],
            nonce=q0["nonce"],
            context_version=d["context_version"],
            root=root,
            source_commit=d["source_commit"],
            registration_sha256=r["registration_sha256"],
            precheck_sha256=r["precheck_sha256"],
            launcher_identity=launcher,
            interpreter=d["interpreter"],
            files=snapshots,
            launch_intent=intent,
            launch_intent_sha256=sha(canonical(intent)),
            platform_evidence=platform_evidence,
            host_clock=dict(utc=r["started_at"], monotonic_ns=r["host_monotonic_ns"]),
            policy=dict(
                runtime_consumable=False,
                certifiable=False,
                exact_file_count=99,
                manifest_max_bytes=LIMIT,
                fixed_set_version="C1_HOST_V1",
            ),
        )
        mr = canonical(m)
        require(len(mr) <= LIMIT, "host.encoding_invalid")
        mp = save(folder, "host-source-manifest.json", mr)
        r["manifest_sha256"] = sha(mr)
        argv = [
            d["interpreter"]["path"],
            "-I",
            "-S",
            "-B",
            os.path.join(root, ENTRY),
            "--host-manifest",
            mp,
            "--host-manifest-sha256",
            sha(mr),
        ]
        r["failure_stage"] = "child"
        run = child(argv, root, d["limits"])
        save(folder, "child-stdout.raw", run["stdout"])
        save(folder, "child-stderr.raw", run["stderr"])
        r["child"] = {k: v for k, v in run.items() if k not in {"stdout", "stderr"}}
        r["child"].update(
            stdout_sha256=sha(run["stdout"]),
            stderr_sha256=sha(run["stderr"]),
            interpreter_version=sys.version,
        )
        require(not run["reason"], run["reason"])
        require(run["returncode"] == 0, "host.child_failed")
        p = parse(run["stdout"])
        require(
            p.get("status") == "VERIFIED"
            and p.get("host_finalization_pending") is True
            and p.get("C1_dependency_closed") is False
            and p.get("manifest_sha256") == sha(mr)
            and p.get("run_id") == q0["run_id"]
            and p.get("registration_sha256") == r["registration_sha256"]
            and p.get("precheck_sha256") == r["precheck_sha256"]
            and p.get("launcher_identity") == launcher
            and p.get("launch_intent_sha256") == m["launch_intent_sha256"],
            "host.proof_manifest_mismatch",
        )
        snapshot_hashes = {row["path"]: row["observed_sha256"] for row in snapshots}
        require(
            all(
                snapshot_hashes.get(
                    os.path.normpath(
                        os.path.join(root, "qlab/qlab/dynamic_factor", name)
                    )
                )
                == value
                for name, value in p["proof"]["source_files"].items()
            ),
            "host.proof_manifest_mismatch",
        )
        save(folder, "candidate-proof.json", run["stdout"])
        r["proof_sha256"] = sha(run["stdout"])
        r["failure_stage"] = "postrun"
        r["after"] = []
        try:
            after, _ = collect(d, requested_entry, r["after"])
        except (ValueError, OSError) as exc:
            raise Refusal("host.postrun_identity_mismatch") from exc
        require(before == after, "host.postrun_identity_mismatch")
        require(identity(mp)[0] == mr, "host.manifest_changed")
        _, python_after = identity(d["interpreter"]["path"])
        r["interpreter_after"] = python_after
        require(python_before == python_after, "host.interpreter_mismatch")
        r["controls_after"] = [identity(path)[1] for path in control_paths]
        require(r["controls_before"] == r["controls_after"], "host.manifest_changed")
        held_after = []
        for fd, before_fd in held:
            current = os.fstat(fd)
            require(
                stat.S_ISREG(current.st_mode)
                and (
                    current.st_dev,
                    current.st_ino,
                    current.st_size,
                    current.st_mtime_ns,
                )
                == (
                    before_fd["st_dev"],
                    before_fd["st_ino"],
                    before_fd["bytes"],
                    before_fd["st_mtime_ns"],
                ),
                "host.postrun_identity_mismatch",
            )
            held_after.append(dict(before_fd))
        r["held_after"] = held_after
        r.update(status="VERIFIED_MECHANISM", failure_stage=None)
    except (KeyError, TypeError) as exc:
        r["reason"] = "host.scope_mismatch"
        r["reason_detail"] = str(exc)
    except (ValueError, OSError) as exc:
        r["reason"] = str(exc)
    r["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        save(folder, "host-launch-receipt.json", canonical(r))
        return r
    finally:
        for fd, _ in held:
            os.close(fd)


def platform_record(ref, issue):
    """Never accept caller-supplied author fields as platform authentication."""
    fields(ref, "comment_id revision")
    require(
        type(ref["comment_id"]) is str
        and len(ref["comment_id"]) == 36
        and type(ref["revision"]) is int
        and ref["revision"] > 0,
        "host.receipt_provenance_invalid",
    )
    result = subprocess.run(
        [
            "multica",
            "issue",
            "comment",
            "list",
            issue,
            "--thread",
            ref["comment_id"],
            "--tail",
            "0",
            "--output",
            "json",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        check=False,
    )
    require(result.returncode == 0, "host.receipt_provenance_invalid")
    try:
        rows = json.loads(result.stdout)
        row = next(row for row in rows if row.get("id") == ref["comment_id"])
        require(
            row.get("revision") == ref["revision"],
            "host.registration_revision_mismatch",
        )
        require(
            row.get("issue_id") == issue
            and row.get("author_type") == "agent"
            and row.get("parent_id") is None,
            "host.receipt_provenance_invalid",
        )
        payload = json.loads(row["content"])
        return row, payload, result.stdout
    except Refusal:
        raise
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise Refusal("host.receipt_provenance_invalid") from exc


def live_preflight(d, q0, registration_ref, q0_ref):
    author, published, draw = platform_record(registration_ref, ROOT_ISSUE)
    operator, precheck_data, qraw = platform_record(q0_ref, RUN_ISSUE)
    require(
        author["author_id"] == REGISTRAR and published == d,
        "host.registration_provenance_invalid",
    )
    registration(d)
    precheck(d, q0)
    require(
        precheck_data == q0
        and operator["author_id"] == q0["operator_id"]
        and operator.get("source_task_id") == q0["task_id"]
        and q0["registration_ref"] == registration_ref,
        "host.operator_precheck_invalid",
    )
    evidence = dict(
        registration=dict(
            issue_id=ROOT_ISSUE,
            ref=registration_ref,
            author_id=author["author_id"],
            readback_sha256=sha(draw),
        ),
        operator_precheck=dict(
            issue_id=RUN_ISSUE,
            ref=q0_ref,
            author_id=operator["author_id"],
            readback_sha256=sha(qraw),
        ),
    )
    return evidence, draw, qraw


def intake(folder, expected_run_id, expected_context, registration_ref, q0_ref, q1_ref):
    """Outer formal receipt gate: no offline, synthetic-author or test mode."""
    names = (
        "host-launch-receipt.json",
        "operator-final-platform-readback.json",
        "host-bound-proof.json",
    )
    require(
        all(os.path.isfile(os.path.join(folder, n)) for n in names),
        "host.receipt_required",
    )
    rraw, _ = identity(os.path.join(folder, names[0]))
    fraw, _ = identity(os.path.join(folder, names[2]))
    r, f = parse(rraw), parse(fraw)
    require(
        r.get("schema") == "EVO884.C1HostLaunchReceipt/v1",
        "host.receipt_binding_mismatch",
    )
    require(
        r.get("run_id") == expected_run_id
        and r.get("context_version") == expected_context,
        "host.receipt_replay",
    )
    author, d, draw = platform_record(registration_ref, ROOT_ISSUE)
    require(author["author_id"] == REGISTRAR, "host.registration_provenance_invalid")
    registration(d)
    operator0, q0, q0raw = platform_record(q0_ref, RUN_ISSUE)
    operator1, q1, q1raw = platform_record(q1_ref, RUN_ISSUE)
    precheck(d, q0)
    require(
        q0["registration_ref"] == registration_ref,
        "host.registration_revision_mismatch",
    )
    require(
        os.path.realpath(folder)
        == os.path.join(d["operator_directory"], "c1-host-runs", expected_run_id),
        "host.receipt_replay",
    )
    require(
        operator0["author_id"] == operator1["author_id"] == q0["operator_id"]
        and q0["operator_id"] in d["operators"],
        "host.receipt_provenance_invalid",
    )
    require(
        operator0.get("source_task_id")
        == operator1.get("source_task_id")
        == q0["task_id"],
        "host.receipt_provenance_invalid",
    )

    def at(value):
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(stamp.tzinfo is not None, "host.receipt_provenance_invalid")
        return stamp

    require(
        at(author["created_at"])
        <= at(operator0["created_at"])
        <= at(r["started_at"])
        <= at(r["finished_at"])
        <= at(operator1["created_at"]),
        "host.receipt_provenance_invalid",
    )
    fields(
        q1,
        "schema run_id context_version nonce task_id session_id receipt_sha256 "
        "manifest_sha256 registration_sha256 precheck_sha256",
    )
    require(
        q1["schema"] == "EVO884.C1OperatorFinalization/v1",
        "host.receipt_provenance_invalid",
    )
    for key in ("run_id", "nonce", "task_id", "session_id", "context_version"):
        require(q1[key] == q0[key], "host.receipt_replay")
    require(
        q0["run_id"] == expected_run_id and q0["context_version"] == expected_context,
        "host.receipt_replay",
    )
    mr, _ = identity(os.path.join(folder, "host-source-manifest.json"))
    pr, _ = identity(os.path.join(folder, "candidate-proof.json"))
    m, p = parse(mr), parse(pr)
    require(
        r["preflight_authority"] == "authenticated_readbacks"
        and m["platform_evidence"]
        == dict(
            registration=dict(
                issue_id=ROOT_ISSUE,
                ref=registration_ref,
                author_id=author["author_id"],
                readback_sha256=sha(draw),
            ),
            operator_precheck=dict(
                issue_id=RUN_ISSUE,
                ref=q0_ref,
                author_id=operator0["author_id"],
                readback_sha256=sha(q0raw),
            ),
        ),
        "host.receipt_provenance_invalid",
    )
    expected_argv = [
        d["interpreter"]["path"],
        "-I",
        "-S",
        "-B",
        os.path.join(d["repository_root"], ENTRY),
        "--host-manifest",
        os.path.join(os.path.realpath(folder), "host-source-manifest.json"),
        "--host-manifest-sha256",
        sha(mr),
    ]
    require(r["child"]["argv"] == expected_argv, "host.argv_mismatch")
    require(r["child"]["cwd"] == d["repository_root"], "host.cwd_mismatch")
    require(
        r["interpreter_before"] == r["interpreter_after"]
        and r["interpreter_before"]["observed_sha256"] == d["interpreter"]["sha256"],
        "host.interpreter_mismatch",
    )
    require(
        {row["relative"]: row["observed_sha256"] for row in r["before"]}
        == {path: value for path, value in d["files"].items() if path != LAUNCHER}
        and all(
            row["expected_sha256"] == row["observed_sha256"]
            and row["path"] == os.path.join(d["repository_root"], row["relative"])
            for row in r["before"]
        ),
        "host.receipt_binding_mismatch",
    )
    require(
        r["status"] == "VERIFIED_MECHANISM"
        and r["reason"] is None
        and r["before"]
        and r["before"] == r["after"]
        and r["controls_before"] == r["controls_after"]
        and r["child"]["returncode"] == 0,
        "host.receipt_binding_mismatch",
    )
    expected_held = (
        r["controls_before"]
        + [r["interpreter_before"]]
        + [
            {
                key: row[key]
                for key in (
                    "path",
                    "bytes",
                    "st_dev",
                    "st_ino",
                    "st_mtime_ns",
                    "observed_sha256",
                )
            }
            for row in r["before"]
        ]
    )
    require(
        r["held_after"] == expected_held
        and r["launcher_identity"] == q0["launcher_identity"]
        and r["child"]["stdout_sha256"] == sha(pr)
        and r["child"]["stderr_sha256"]
        == sha(identity(os.path.join(folder, "child-stderr.raw"))[0]),
        "host.receipt_binding_mismatch",
    )
    require(
        q1["receipt_sha256"] == sha(rraw)
        and q1["manifest_sha256"] == sha(mr) == r["manifest_sha256"]
        and q1["registration_sha256"] == sha(canonical(d)) == r["registration_sha256"]
        and q1["precheck_sha256"] == sha(canonical(q0)) == r["precheck_sha256"]
        and r["proof_sha256"] == sha(pr)
        and p["manifest_sha256"] == sha(mr)
        and m["run_id"] == p["run_id"] == expected_run_id,
        "host.receipt_binding_mismatch",
    )
    require(
        identity(os.path.join(folder, names[1]))[0] == q1raw,
        "host.receipt_provenance_invalid",
    )
    fields(
        f,
        "schema run_id context_version manifest_sha256 proof_sha256 receipt_sha256 "
        "final_platform_readback_sha256 registration_platform_readback_sha256 "
        "precheck_platform_readback_sha256 launcher_identity",
    )
    require(
        f
        == dict(
            schema="EVO884.C1HostBoundProof/v1",
            run_id=expected_run_id,
            context_version=expected_context,
            manifest_sha256=sha(mr),
            proof_sha256=sha(pr),
            receipt_sha256=sha(rraw),
            final_platform_readback_sha256=sha(q1raw),
            registration_platform_readback_sha256=sha(draw),
            precheck_platform_readback_sha256=sha(q0raw),
            launcher_identity=q0["launcher_identity"],
        ),
        "host.receipt_binding_mismatch",
    )
    consumed = os.path.join(folder, "formal-intake-" + expected_run_id + ".json")
    try:
        save(
            folder,
            os.path.basename(consumed),
            canonical(dict(receipt_sha256=sha(rraw), proof_sha256=sha(fraw))),
        )
    except FileExistsError as exc:
        raise Refusal("host.receipt_replay") from exc
    return dict(
        status="VERIFIED_HOST_RECEIPT",
        run_id=expected_run_id,
        host_bound_proof_sha256=sha(fraw),
        actual_A_issued=False,
    )


def main():
    require(
        sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode,
        "host.isolation_required",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("observe", "launch"):
        launch = commands.add_parser(command)
        launch.add_argument("--registration", required=True)
        launch.add_argument("--precheck", required=True)
        launch.add_argument("--entry", required=True)
        launch.add_argument("--output", required=True)
        if command == "launch":
            launch.add_argument("--registration-ref", required=True)
            launch.add_argument("--q0-ref", required=True)
    for command in ("finalize", "intake"):
        formal = commands.add_parser(command)
        formal.add_argument("--folder", required=True)
        formal.add_argument("--run-id", required=True)
        formal.add_argument("--context", required=True)
        for name in ("registration", "q0", "q1"):
            formal.add_argument("--" + name + "-ref", required=True)
    args = parser.parse_args()
    try:
        if args.command in ("observe", "launch"):
            d, q0 = read(args.registration), read(args.precheck)
            evidence = None
            if args.command == "launch":
                evidence, draw, qraw = live_preflight(
                    d, q0, read(args.registration_ref), read(args.q0_ref)
                )
                require(
                    os.path.abspath(args.output)
                    == os.path.join(
                        d["operator_directory"], "c1-host-runs", q0["run_id"]
                    ),
                    "host.cwd_mismatch",
                )
            os.mkdir(args.output, 0o700)
            if evidence:
                save(args.output, "host-registration-platform-readback.json", draw)
                save(args.output, "operator-precheck-platform-readback.json", qraw)
            result = observe(
                d,
                q0,
                args.output,
                args.entry,
                (args.registration, args.precheck),
                evidence,
            )
        else:
            if args.command == "finalize":
                require(
                    os.path.isfile(
                        os.path.join(args.folder, "host-launch-receipt.json")
                    ),
                    "host.receipt_required",
                )
                refs = [
                    read(path)
                    for path in (args.registration_ref, args.q0_ref, args.q1_ref)
                ]
                records = [
                    platform_record(refs[0], ROOT_ISSUE),
                    platform_record(refs[1], RUN_ISSUE),
                    platform_record(refs[2], RUN_ISSUE),
                ]
                # Finalization does not authenticate a local sample. The same
                # mandatory intake runs afterwards and may still refuse it.
                raw_objects = [
                    identity(os.path.join(args.folder, name))[0]
                    for name in (
                        "host-source-manifest.json",
                        "candidate-proof.json",
                        "host-launch-receipt.json",
                    )
                ]
                envelope = dict(
                    schema="EVO884.C1HostBoundProof/v1",
                    run_id=args.run_id,
                    context_version=args.context,
                    manifest_sha256=sha(raw_objects[0]),
                    proof_sha256=sha(raw_objects[1]),
                    receipt_sha256=sha(raw_objects[2]),
                    registration_platform_readback_sha256=sha(records[0][2]),
                    precheck_platform_readback_sha256=sha(records[1][2]),
                    final_platform_readback_sha256=sha(records[2][2]),
                    launcher_identity=records[1][1]["launcher_identity"],
                )
                for name, value in zip(
                    (
                        "host-registration-platform-readback.json",
                        "operator-precheck-platform-readback.json",
                        "operator-final-platform-readback.json",
                    ),
                    records,
                ):
                    existing = os.path.join(args.folder, name)
                    if os.path.exists(existing):
                        require(
                            identity(existing)[0] == value[2],
                            "host.receipt_provenance_invalid",
                        )
                    else:
                        save(args.folder, name, value[2])
                save(args.folder, "host-bound-proof.json", canonical(envelope))
            result = intake(
                args.folder,
                args.run_id,
                args.context,
                read(args.registration_ref),
                read(args.q0_ref),
                read(args.q1_ref),
            )
        rc = 0 if result["status"].startswith("VERIFIED") else 2
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
    ) as exc:
        result = dict(status="REJECTED", reason=str(exc), actual_A_issued=False)
        rc = 2
    sys.stdout.buffer.write(canonical(result))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

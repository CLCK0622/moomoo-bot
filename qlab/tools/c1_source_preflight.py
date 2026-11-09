"""Controlled C1 source preflight; independent review binds this artifact."""

import sys

_EVENTS = []
_VERIFIED = False
_PHASE = "startup"
_ALLOWED_IMPORTS = set()


def _audit(event, args):
    if event == "import":
        name = args[0]
        _EVENTS.append(
            dict(sequence=len(_EVENTS), event=event, module=name, phase=_PHASE)
        )
        if name == "qlab" or name.startswith("qlab."):
            if not _VERIFIED or name not in _ALLOWED_IMPORTS:
                raise RuntimeError("scope.preflight_import_not_registered")
    elif event == "open" and isinstance(args[0], str):
        _EVENTS.append(
            dict(sequence=len(_EVENTS), event=event, path=args[0], phase=_PHASE)
        )


sys.addaudithook(_audit)
if any(name == "qlab" or name.startswith("qlab.") for name in sys.modules):
    raise SystemExit("scope.preflight_candidate_already_loaded")
if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
    raise SystemExit("scope.preflight_isolation_required")

import base64  # noqa: E402
import hashlib  # noqa: E402 - isolation and audit checks precede other imports
import importlib.machinery  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402


SOURCE_FILES = (
    "../../tools/c1_source_preflight.py",
    "../__init__.py",
    "__init__.py",
    "b_release_context.py",
    "catalog_members.py",
    "catalog_v21.py",
    "continuity.py",
    "contract.py",
    "conventions.py",
    "event_quarantine.py",
    "execution.py",
    "execution_accounting.py",
    "execution_amounts.py",
    "execution_candidate.py",
    "execution_cash.py",
    "execution_clock.py",
    "execution_closure.py",
    "execution_exposure.py",
    "execution_numbers.py",
    "execution_projection.py",
    "execution_receipts/input_data.py",
    "execution_receipts/input_guard.py",
    "execution_receipts/input_reader.py",
    "execution_returns.py",
    "execution_risk.py",
    "execution_risk_history.py",
    "execution_signals.py",
    "execution_startup.py",
    "execution_state.py",
    "fees.py",
    "fold_split.py",
    "folds.py",
    "historical_authority.py",
    "input_disposition.py",
    "input_scope.py",
    "isolation.py",
    "k5.py",
    "noncash_v3.py",
    "pending.py",
    "pipeline.py",
    "reference_check.py",
    "reference_definition_v301.py",
    "reference_guard.py",
    "reference_inputs.py",
    "reference_producer.py",
    "reference_producer_v3.py",
    "reference_profile_v301.py",
    "reference_registry_v3.py",
    "reference_v3_scope.py",
    "reference_validation.py",
    "scope_proof.py",
    "scope_reader.py",
    "state_v2.py",
    "validation.py",
    "valuation.py",
)
DATA_FILES = (
    "b_release_originals/EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json",
    "b_release_originals/EVO883-EVO893-v10-ruling.json",
    "b_release_originals/EVO883-S1-BRKB-field-receipt.json",
    "b_release_originals/EVO883-S2-v14-field-receipt.json",
    "b_release_originals/EVO883-S3-v12-final-receipt.json",
    "b_release_originals/EVO883-S4-v11-receipt.json",
    "b_release_originals/EVO883-v10-engineering-scope-receipt.json",
    "b_release_originals/EVO883-v20.1-final-receipt.json",
    "b_release_originals/EVO883-v21-final-receipt.json",
    "b_release_originals/EVO893-B-CMI-guard-v21.json",
    "b_release_originals/EVO893-B-noncash-catalog-v21.csv",
    "b_release_originals/EVO938-B-runtime-release-P-v1.0.0.json",
    "b_release_originals/EVO938-B-runtime-release-R-v1.0.0.json",
    "b_release_originals/annotation-platform-readback.json",
    "b_release_originals/publication-platform-readback.json",
    "fixtures/calendar-folds-v0.1.json",
    "fixtures/catalog-v21/EVO883-v21-final-receipt.json",
    "fixtures/catalog-v21/EVO893-B-CMI-guard-v21.json",
    "fixtures/catalog-v21/EVO893-B-noncash-catalog-v21.csv",
    "fixtures/common-calendar-v0.1.txt",
    "fixtures/common-profile-v3.json",
    "fixtures/conventions-v0.1.json",
    "fixtures/conventions-v3.0.0.json",
    "fixtures/disposition/EVO883-EVO886-minimum-scope-ruling-v1.json",
    "fixtures/disposition/EVO883-EVO886-minimum-scope-ruling-v1.md",
    "fixtures/disposition/EVO883-EVO891-disposition-draft-v1.json",
    "fixtures/disposition/EVO883-EVO891-ruling-v1.md",
    "fixtures/disposition/QQQ-source-row-bindings-v1.json",
    "fixtures/evo892-v3/candidate_reference_manifest.json",
    "fixtures/evo892-v3/meta_reference_manifest.json",
    "fixtures/evo892-v3/predeclared_reference_registry.json",
    "fixtures/execution-v3.0.1/EVO883-C06-CLOCK-adopted-protocol-v1.0.0.json",
    "fixtures/execution-v3.0.1/EVO883-D12-addendum-v3.0.1.md",
    "fixtures/execution-v3.0.1/EVO883-D12-common-profile-v3.0.1.json",
    "fixtures/execution-v3.0.1/EVO883-D12-shared-execution-contract-v3.0.1.json",
    "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.json",
    "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.md",
    "fixtures/fee_params_x1.json",
    "fixtures/historical-seed-e51f8023.jsonl",
    "fixtures/noncash-exposure-policy-v3.json",
    "fixtures/prereg-v3.json",
    "fixtures/provenance-v2.json",
    "fixtures/provenance-v3.json",
    "fixtures/provenance.json",
)
POLICY_FILES = {
    "raw_document": "fixtures/conventions-v3.0.0.json",
    "raw_profile": "fixtures/prereg-v3.json",
    "raw_date_manifest": "fixtures/calendar-folds-v0.1.json",
    "seed_raw": "fixtures/historical-seed-e51f8023.jsonl",
}

_HASH = hashlib.sha256
_DUMPS = json.dumps
_LOADS = json.loads
_OPEN = os.open
_READ = os.read
_FSTAT = os.fstat
_CLOSE = os.close
_STORE = {}
_ENTRY = os.path.realpath(__file__)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_ENTRY)))
_DF = os.path.join(_ROOT, "qlab", "qlab", "dynamic_factor")


class _Refusal(Exception):
    pass


def _digest(value):
    return _HASH(
        _DUMPS(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _path(relative):
    path = os.path.normpath(os.path.join(_DF, relative))
    if os.path.commonpath((_ROOT, path)) != _ROOT:
        raise _Refusal("scope.preflight_path_not_registered")
    return path


def _read_file(path):
    fd = _OPEN(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = _FSTAT(fd)
        if not stat.S_ISREG(before.st_mode):
            raise _Refusal("scope.preflight_regular_file_required")
        chunks = []
        while True:
            chunk = _READ(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = _FSTAT(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(raw) != before.st_size:
            raise _Refusal("scope.preflight_file_changed")
        return raw, dict(
            path=path,
            bytes=len(raw),
            st_dev=before.st_dev,
            st_ino=before.st_ino,
            st_mtime_ns=before.st_mtime_ns,
            observed_sha256=_HASH(raw).hexdigest(),
        )
    finally:
        _CLOSE(fd)


class _Snapshot:
    __slots__ = ()

    def validate(self):
        if type(self) is not _Snapshot or self not in _STORE:
            raise ValueError("scope.preflight_evidence_required")
        data = _STORE[self]
        actual = {
            name: dict(sha256=_HASH(raw).hexdigest(), bytes=len(raw))
            for name, raw in data["raw"].items()
        }
        if _digest(actual) != data["anchor"]:
            raise ValueError("scope.preflight_snapshot_mismatch")
        for name, row in actual.items():
            if (
                row["sha256"] != data["metadata"][name]["observed_sha256"]
                or row["bytes"] != data["metadata"][name]["bytes"]
            ):
                raise ValueError("scope.preflight_snapshot_mismatch")
        return True

    def raw(self, relative):
        try:
            return _STORE[self]["raw"][_path(relative)]
        except (KeyError, TypeError) as exc:
            raise ValueError("scope.preflight_snapshot_missing") from exc

    def identity(self, relative):
        try:
            return _STORE[self]["metadata"][_path(relative)]["observed_sha256"]
        except (KeyError, TypeError) as exc:
            raise ValueError("scope.preflight_snapshot_missing") from exc

    def entry_source(self):
        return _STORE[self]["raw"][_ENTRY]

    def entry_path(self):
        return _ENTRY

    def path(self, relative):
        return _path(relative)

    def digest(self, value):
        return _digest(value)

    def bind_policy(self, policy):
        for field, relative in POLICY_FILES.items():
            if getattr(policy, field) != self.raw(relative):
                raise ValueError("scope.preflight_policy_mismatch")
        document = _LOADS(self.raw(POLICY_FILES["raw_document"]))
        profile = _LOADS(self.raw(POLICY_FILES["raw_profile"]))
        _STORE[self]["profile"] = profile
        _STORE[self]["binding"] = dict(
            conventions_version=document["version"],
            conventions_sha256=self.identity(POLICY_FILES["raw_document"]),
            conventions_status=document["status"],
            profile_sha256=self.identity(POLICY_FILES["raw_profile"]),
            prereg_sha256=self.identity(POLICY_FILES["raw_profile"]),
            prereg_version=profile["version"],
            common_profile_sha256=document["variance_layers"]["probe_profile"][
                "common_profile_sha256"
            ],
        )

    def policy_binding(self):
        return dict(_STORE[self]["binding"])

    def policy_profile(self):
        return _LOADS(_DUMPS(_STORE[self]["profile"]))

    def bind_loaded(self):
        self.validate()
        rows = []
        data = _STORE[self]
        imported = {
            e["module"]
            for e in _EVENTS
            if e["event"] == "import"
            and (e["module"] == "qlab" or e["module"].startswith("qlab."))
        }
        for name, module in sorted(sys.modules.items()):
            if name != "qlab" and not name.startswith("qlab."):
                continue
            if name not in imported:
                raise ValueError("scope.preflight_import_event_missing")
            spec = module.__spec__
            if spec is None or spec.origin is None:
                raise ValueError("scope.preflight_loading_mismatch")
            path = os.path.normpath(os.path.abspath(spec.origin))
            if path not in data["metadata"]:
                raise ValueError("scope.preflight_loading_mismatch")
            before = data["metadata"][path]
            fd = _OPEN(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                current = _FSTAT(fd)
            finally:
                _CLOSE(fd)
            if not stat.S_ISREG(current.st_mode) or (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            ) != (
                before["st_dev"],
                before["st_ino"],
                before["bytes"],
                before["st_mtime_ns"],
            ):
                raise ValueError("scope.preflight_loading_mismatch")
            relative = os.path.relpath(path, _DF)
            kind = (
                "auditor_raw_SHA"
                if relative == "scope_proof.py"
                else "receiver_full_AST"
                if relative == "b_release_context.py"
                else "fixed_raw_SHA"
            )
            if kind == "fixed_raw_SHA" and relative not in SOURCE_FILES:
                raise ValueError("scope.preflight_import_not_registered")
            rows.append(
                dict(
                    module=name,
                    path=path,
                    observed_sha256=before["observed_sha256"],
                    expected_sha256=data["metadata"][path]["expected_sha256"],
                    binding=kind,
                    st_dev=current.st_dev,
                    st_ino=current.st_ino,
                    bytes=current.st_size,
                )
            )
        return rows


def _canonical(value):
    return (
        _DUMPS(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _parse(raw):
    def types(item):
        if type(item) not in (dict, list, str, int, bool, type(None)):
            raise _Refusal("scope.host_manifest_encoding_invalid")
        if type(item) is dict:
            for child in item.values():
                types(child)
        elif type(item) is list:
            for child in item:
                types(child)

    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise _Refusal("scope.host_manifest_encoding_invalid")
            obj[key] = value
        return obj

    try:
        value = _LOADS(raw, object_pairs_hook=pairs)
        types(value)
        if _canonical(value) != raw:
            raise _Refusal("scope.host_manifest_encoding_invalid")
        return value
    except (ValueError, UnicodeError, TypeError) as exc:
        raise _Refusal("scope.host_manifest_encoding_invalid") from exc


def _collect(manifest_path, expected_sha256):
    global _ROOT, _DF
    manifest_raw, _ = _read_file(manifest_path)
    if (
        len(manifest_raw) > 16 * 1024 * 1024
        or _HASH(manifest_raw).hexdigest() != expected_sha256
    ):
        raise _Refusal("scope.host_manifest_sha_mismatch")
    manifest = _parse(manifest_raw)
    if (
        type(manifest) is not dict
        or set(manifest)
        != {
            "schema",
            "run_id",
            "nonce",
            "context_version",
            "root",
            "source_commit",
            "registration_sha256",
            "precheck_sha256",
            "launcher_identity",
            "interpreter",
            "files",
            "launch_intent",
            "launch_intent_sha256",
            "platform_evidence",
            "host_clock",
            "policy",
        }
        or manifest["schema"] != "EVO884.C1HostSourceManifest/v1"
    ):
        raise _Refusal("scope.host_manifest_scope_mismatch")
    root = manifest["root"]
    if not os.path.isabs(root) or root != os.path.realpath(root):
        raise _Refusal("scope.host_manifest_scope_mismatch")
    _ROOT = root
    _DF = os.path.join(root, "qlab", "qlab", "dynamic_factor")
    intent = manifest["launch_intent"]
    if _HASH(_canonical(intent)).hexdigest() != manifest[
        "launch_intent_sha256"
    ] or intent != dict(
        root=root,
        entry="qlab/tools/c1_source_preflight.py",
        interpreter=manifest["interpreter"],
        flags=["-I", "-S", "-B"],
        manifest_sha256_argument="sha256_of_final_manifest_bytes",
    ):
        raise _Refusal("scope.host_manifest_scope_mismatch")
    fixed_entry = _path("../../tools/c1_source_preflight.py")
    if _ENTRY != fixed_entry or os.path.abspath(__file__) != fixed_entry:
        raise _Refusal("scope.host_entry_path_mismatch")
    if os.path.realpath(sys.executable) != manifest["interpreter"]["path"]:
        raise _Refusal("scope.host_manifest_scope_mismatch")
    expected_paths = {_path(name) for name in SOURCE_FILES + DATA_FILES}
    rows = manifest["files"]
    if type(rows) is not list or len(rows) != len(expected_paths):
        raise _Refusal("scope.host_manifest_scope_mismatch")
    raw, metadata = {}, {}
    for row in rows:
        if type(row) is not dict or set(row) != {
            "path",
            "relative",
            "bytes",
            "st_dev",
            "st_ino",
            "st_mtime_ns",
            "observed_sha256",
            "expected_sha256",
            "raw_base64",
            "role",
        }:
            raise _Refusal("scope.host_manifest_scope_mismatch")
        path = row["path"]
        if (
            type(path) is not str
            or type(row["relative"]) is not str
            or type(row["raw_base64"]) is not str
            or any(
                type(row[key]) is not int or row[key] < 0
                for key in ("bytes", "st_dev", "st_ino", "st_mtime_ns")
            )
            or any(
                type(row[key]) is not str
                or len(row[key]) != 64
                or set(row[key]) - set("0123456789abcdef")
                for key in ("observed_sha256", "expected_sha256")
            )
            or row["role"] != ("source" if path.endswith(".py") else "data")
            or os.path.normpath(os.path.join(root, row["relative"])) != path
        ):
            raise _Refusal("scope.host_manifest_scope_mismatch")
        if path not in expected_paths or path in raw or os.path.realpath(path) != path:
            raise _Refusal("scope.host_manifest_scope_mismatch")
        try:
            value = base64.b64decode(row["raw_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise _Refusal("scope.host_manifest_encoding_invalid") from exc
        digest = _HASH(value).hexdigest()
        if (
            digest != row["observed_sha256"]
            or digest != row["expected_sha256"]
            or len(value) != row["bytes"]
        ):
            raise _Refusal("scope.host_snapshot_mismatch")
        raw[path] = value
        metadata[path] = {k: v for k, v in row.items() if k != "raw_base64"}
    actual_raw, actual = _read_file(_ENTRY)
    own = metadata[_ENTRY]
    if any(own[k] != actual[k] for k in ("path", "st_dev", "st_ino", "bytes")):
        raise _Refusal("scope.host_entry_identity_mismatch")
    if _HASH(actual_raw).hexdigest() != own["observed_sha256"]:
        raise _Refusal("scope.host_entry_sha_mismatch")
    snapshot = object.__new__(_Snapshot)
    _STORE[snapshot] = dict(
        raw=raw,
        metadata=metadata,
        manifest=manifest,
        anchor=_digest(
            {
                name: dict(sha256=_HASH(value).hexdigest(), bytes=len(value))
                for name, value in raw.items()
            }
        ),
    )
    return snapshot, list(metadata.values()), []


def main():
    global _VERIFIED, _PHASE
    observations = []
    try:
        if (
            len(sys.argv) != 5
            or sys.argv[1] != "--host-manifest"
            or sys.argv[3] != "--host-manifest-sha256"
        ):
            raise _Refusal("scope.host_manifest_required")
        if (
            __name__ != "__main__"
            or type(__loader__).__name__ != "SourceFileLoader"
            or os.path.realpath(__loader__.get_filename("__main__")) != _ENTRY
        ):
            raise _Refusal("scope.preflight_startup_mismatch")
        original = getattr(sys, "orig_argv", None)
        if original is not None and (
            len(original) != 9
            or original[1:4] != ["-I", "-S", "-B"]
            or os.path.realpath(original[4]) != _ENTRY
        ):
            raise _Refusal("scope.preflight_startup_mismatch")
        _PHASE = "snapshot"
        snapshot, observations, errors = _collect(sys.argv[2], sys.argv[4])
        if os.path.realpath(os.getcwd()) != _ROOT:
            raise _Refusal("scope.preflight_workdir_or_arguments_mismatch")
        if errors:
            raise _Refusal("scope.preflight_source_identity_mismatch")
        for row in observations:
            path = row["path"]
            if path == _ENTRY or not path.endswith(".py"):
                continue
            relative = os.path.relpath(path, os.path.join(_ROOT, "qlab"))
            name = relative[:-3].replace(os.sep, ".")
            if name.endswith(".__init__"):
                name = name[:-9]
            _ALLOWED_IMPORTS.add(name)
            search = (
                os.path.dirname(os.path.dirname(path))
                if os.path.basename(path) == "__init__.py"
                else os.path.dirname(path)
            )
            spec = importlib.machinery.PathFinder.find_spec(name, [search])
            _EVENTS.append(
                dict(
                    sequence=len(_EVENTS),
                    event="module_spec",
                    module=name,
                    path=None if spec is None else spec.origin,
                    expected_path=path,
                    loader=None if spec is None else type(spec.loader).__name__,
                    phase="snapshot",
                )
            )
            if (
                spec is None
                or type(spec.loader) is not importlib.machinery.SourceFileLoader
                or spec.origin != path
            ):
                raise _Refusal("scope.preflight_loading_mismatch")
        _EVENTS.append(
            dict(sequence=len(_EVENTS), event="preflight_conclusion", status="VERIFIED")
        )
        _VERIFIED = True
        _PHASE = "candidate_import"
        with tempfile.TemporaryDirectory(prefix="c1-preflight-bytecode-") as bytecode:
            sys.pycache_prefix = bytecode
            package_parent = os.path.join(_ROOT, "qlab")
            sys.path.insert(0, package_parent)
            try:
                import qlab
            finally:
                sys.path.remove(package_parent)
            if (
                qlab.__spec__.origin != snapshot.path("../__init__.py")
                or list(qlab.__path__)
                != [os.path.dirname(snapshot.path("../__init__.py"))]
                or any(
                    p and os.path.commonpath((_ROOT, os.path.realpath(p))) == _ROOT
                    for p in sys.path
                )
            ):
                raise _Refusal("scope.preflight_loading_mismatch")
            from qlab.dynamic_factor import scope_proof

            scope_proof._c1_snapshot_structure(snapshot)
            from qlab.dynamic_factor import b_release_context
            from qlab.dynamic_factor.conventions import load_conventions

            policy = load_conventions()
            if b_release_context.__spec__.origin != snapshot.path(
                "b_release_context.py"
            ):
                raise ValueError("scope.preflight_loading_mismatch")
            snapshot.bind_policy(policy)
            _PHASE = "snapshot_B2"
            proof = scope_proof.b2_isolation_proof_from_snapshot(policy, snapshot)
            _PHASE = "loaded_binding"
            loaded = snapshot.bind_loaded()
            stdlib_origins = {
                name: os.path.realpath(sys.modules[name].__spec__.origin)
                for name in ("ast", "pathlib")
            }
            if any(
                os.path.commonpath((os.path.realpath(sys.base_prefix), path))
                != os.path.realpath(sys.base_prefix)
                for path in stdlib_origins.values()
            ):
                raise _Refusal("scope.preflight_loading_mismatch")
            consistency = proof["C1_source_preflight"]["entry_consistency"]
            proof["C1_source_preflight"] = dict(
                dependency_closed=False,
                source="controlled_entry_snapshot",
                snapshot_sha256=_STORE[snapshot]["anchor"],
                auditor_sha256=snapshot.identity("scope_proof.py"),
                entry_consistency=consistency,
                loaded_modules=loaded,
            )
            _EVENTS.append(
                dict(sequence=len(_EVENTS), event="B2_complete", status="VERIFIED")
            )
        result = dict(
            schema="EVO884.C1CandidateProof/v1",
            status="VERIFIED",
            C1_dependency_closed=False,
            host_finalization_pending=True,
            manifest_sha256=sys.argv[4],
            run_id=_STORE[snapshot]["manifest"]["run_id"],
            registration_sha256=_STORE[snapshot]["manifest"]["registration_sha256"],
            precheck_sha256=_STORE[snapshot]["manifest"]["precheck_sha256"],
            launcher_identity=_STORE[snapshot]["manifest"]["launcher_identity"],
            launch_intent_sha256=_STORE[snapshot]["manifest"]["launch_intent_sha256"],
            proof=proof,
            observations=observations,
            import_binding=loaded,
            stdlib_origins=stdlib_origins,
            authority="mechanism_only_pending_independent_review",
            startup=dict(
                executable=sys.executable,
                argv=sys.argv,
                original_argv=getattr(sys, "orig_argv", None),
                isolated=sys.flags.isolated,
                no_site=sys.flags.no_site,
                dont_write_bytecode=sys.flags.dont_write_bytecode,
                cwd=os.getcwd(),
                entry=_ENTRY,
            ),
        )
        rc = 0
    except (_Refusal, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        if isinstance(exc, (KeyError, TypeError)):
            exc = _Refusal("scope.host_manifest_scope_mismatch")
        _EVENTS.append(dict(sequence=len(_EVENTS), event="refusal", code=str(exc)))
        result = dict(
            schema="EVO884.C1SourcePreflight/v1",
            status="REJECTED",
            C1_dependency_closed=False,
            reason=str(exc),
            observations=observations,
        )
        rc = 2
    result["events"] = _EVENTS
    sys.stdout.buffer.write(_canonical(result))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

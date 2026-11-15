"""P0 transport tests never execute Claude, authenticate or contact a provider."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from threading import Event

import pytest

from qlab.llm_direct import archive as archive_module
from qlab.llm_direct import launcher as launcher_module
from qlab.llm_direct import preflight as p0
from qlab.llm_direct.archive import Archive
from qlab.llm_direct.contract import bindings, canonical, digest, sha
from qlab.llm_direct.launcher import BinaryBinding, ConfigBinding, SubprocessLauncher, candidate_argv

START = "2026-11-15T17:00:00Z"
END = "2026-11-15T17:00:01Z"


@pytest.fixture(autouse=True)
def private_host(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_module, "PREFLIGHT_ROOT", tmp_path / "private-p0")
    monkeypatch.setattr(archive_module, "PHYSICAL_ROOT", tmp_path / "private-e0")

    def no_process(*args, **kwargs):
        pytest.fail("test attempted an uninjected subprocess")

    monkeypatch.setattr(subprocess, "run", no_process)


@pytest.fixture
def small_input(monkeypatch):
    # Transport unit tests do not repeat the unrelated 65x252 input validation.
    # The real-input prepare/verify integration case below retains that path.
    monkeypatch.setattr(p0, "fixture_fees", lambda _: None)
    monkeypatch.setattr(p0, "payload", lambda _: {"synthetic": True})
    monkeypatch.setattr(p0, "build_decision", lambda value: value)


@pytest.fixture
def binding(tmp_path):
    root = tmp_path / "isolated-binary"
    root.mkdir()
    binary = root / "claude"
    binary.write_bytes(b"non-executable, offline test bytes; not a Claude binary")
    return BinaryBinding(binary, root, binary_sha256=sha(binary.read_bytes()))


@pytest.fixture
def ar():
    return Archive(archive_module.PREFLIGHT_ROOT / "case", mode="p0_offline_test")


class FakeAuthority(p0.AuthorityPort):
    def __init__(self, *, accept=True, append=True, identity_changes=None):
        self.accept = accept
        self.can_append = append
        self.contexts = []
        self.attempts = []
        self.identity_changes = identity_changes or {}

    def verify_before_dispatch(self, context, receipts):
        self.contexts.append(context)
        accepted = self.accept and all(
            raw.startswith(b"OFFLINE_TEST_ONLY:") for raw in receipts.blobs().values()
        )
        if not accepted:
            return False
        return dict(dict(
            chain_id=p0.AUTHORITY_CHAIN_ID, arm_tag=p0.ARM,
            configuration_id=context["configuration_id"], purpose=p0.PURPOSE, verified=True,
        ), **self.identity_changes)

    def append_attempt(self, context, attempt):
        self.attempts.append(attempt)
        if not self.can_append:
            raise ValueError("synthetic append unavailable")
        return canonical(dict(
            mode="OFFLINE_TEST_ONLY", context_sha256=digest(context),
            attempt_sha256=digest(attempt),
        ))

    def verify_append(self, context, attempt, receipt):
        return json.loads(receipt)["attempt_sha256"] == digest(attempt)


class FakeProvider(p0.EvidencePort):
    def __init__(self, **changes):
        self.changes = changes

    def extract(self, stdout, context):
        # This is explicitly fake provider evidence, never a production parser.
        response = canonical(dict(status="SYNTHETIC", no_market_outcome=True))
        policy = b"OFFLINE_TEST_ONLY:no-managed-policy"
        request_id = "private-org-123:owner@example.test"
        effective = canonical(dict(
            system_prompt_sha256=context["prompt_sha256"],
            user_input_sha256=context["input_sha256"],
            output_schema_sha256=context["schema_sha256"], tools=[], mcp_servers={},
            managed_policy_sha256=sha(policy),
        ))
        mapping = canonical([dict(
            provider_model=p0.MODEL, provider_request_id=request_id,
            response_sha256=sha(response), retry_of=None,
        )])
        return replace(p0.Evidence(
            p0.MODEL, request_id, response, effective, policy, mapping,
            1, True, False,
        ), **self.changes)


class UnknownProvider(p0.EvidencePort):
    def extract(self, stdout, context):
        return None


class FakeProcess:
    def __init__(self, binding, *, mode="success", stdout=None):
        self.binding, self.mode, self.calls = binding, mode, []
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        assert kwargs["shell"] is False
        assert isinstance(kwargs["input"], bytes)
        assert kwargs["env"]["DISABLE_UPDATES"] == "1"
        if argv[-1] == "--version":
            version = "0.0.0" if self.mode == "wrong_version" else self.binding.version
            return subprocess.CompletedProcess(argv, 0, (version + " (Claude Code)\n").encode(), b"")
        if self.mode == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=b"partial stream", stderr=b"secret error")
        if self.mode == "binary_change":
            self.binding.executable.write_bytes(b"changed during synthetic dispatch")
        return subprocess.CompletedProcess(
            argv, 7 if self.mode == "failure" else 0,
            self.stdout if self.stdout is not None else b'RAW_PRIVATE_STREAM owner@example.test org-private-123\n',
            b'Authorization: Bearer secret-token\nowner@example.test',
        )


def receipts(**changes):
    return replace(p0.Receipts(*[
        ("OFFLINE_TEST_ONLY:" + key).encode()
        for key in ("grant", "reservation", "append", "route", "usage_credits")
    ]), **changes)


def isolated_config(ar, name="chosen-config"):
    # Explicit test approval of newly created empty directories. No auth data.
    root = ar.anchor / "approved-configs"
    root.mkdir(mode=0o700, exist_ok=True)
    directory = root / name
    directory.mkdir(mode=0o700, exist_ok=True)
    identity = [
        dict(device=p.lstat().st_dev, inode=p.lstat().st_ino) for p in (root, directory)
    ]
    return ConfigBinding(
        root, directory, directory.resolve(), digest(identity),
        sha(b"OFFLINE_TEST_ONLY:isolated-directory-approval"),
    )


def dispatch(
    ar, binding, *, process=None, provider=None, authority=None, proof=None,
    config=True, transport_changes=None,
):
    process = process or FakeProcess(binding)
    approved = isolated_config(ar) if config else None
    transport_args = dict(
        runner=process, config_dir=approved.directory if approved else None,
        config_binding=approved,
    )
    transport_args.update(transport_changes or {})
    transport = SubprocessLauncher(binding, **transport_args)
    report = p0.run_preflight(
        ar, binding, "case", receipts=proof if proof is not None else receipts(),
        authority=authority or FakeAuthority(), evidence_port=provider or FakeProvider(),
        launcher=transport, start=START, end_clock=lambda: END,
    )
    return report, process


def test_single_fake_dispatch_raw_log_and_hash_only_export(ar, binding, small_input):
    authority = FakeAuthority()
    report, process = dispatch(ar, binding, authority=authority)
    assert all(report["checks"].values())
    assert report["mode"] == "p0_offline_test"
    assert report["argv_is_tested"] is False
    assert report["status"] == "VERSION_UNVERIFIED"
    assert report["N_config_delta"] == 0 and report["N_request_delta"] == 1
    assert not any(report[k] for k in ("certifiable", "runtime_consumable", "G09_N_passed"))
    assert len([a for a, _ in process.calls if "-p" in a]) == 1
    attempt = authority.attempts[0]
    assert ar.get(attempt["raw_output_sha256"]).startswith(b"RAW_PRIVATE_STREAM")
    stderr = ar.get(attempt["stderr_redacted_sha256"])
    assert b"secret-token" not in stderr
    assert json.loads(stderr)["redaction"] == "entire_stream"
    exported = json.dumps(report)
    assert not any(s in exported for s in ("owner@", "org-private", "private-org", "secret-token", str(ar.root)))
    assert not (ar.anchor / "version-registry.sqlite3").exists()
    required = set(bindings()["N_accounting"]["required_attempt_fields"])
    assert required.issubset(attempt)


def test_missing_authority_grant_refuses_before_any_process(ar, binding, small_input):
    with pytest.raises(ValueError, match="separate_dispatch_grant"):
        p0.run_preflight(ar, binding, "case", start=START, end_clock=lambda: END)
    report = p0.manifest(ar)
    assert not report["checks"]["dispatch_recorded"]
    assert "separate_dispatch_grant" in report["dispatch_gate_reason"]


@pytest.mark.parametrize("missing", ["chief_dispatch_grant", "reservation", "append_readiness", "subscription_route", "usage_credits"])
def test_each_required_proof_missing_refuses_before_spawn(ar, binding, small_input, missing):
    process = FakeProcess(binding)
    with pytest.raises(ValueError, match="required_proof_missing"):
        dispatch(ar, binding, process=process, proof=receipts(**{missing: b""}))
    assert not process.calls
    assert not p0.manifest(ar)["checks"]["dispatch_gate_verified"]


def test_route_or_usage_assertion_is_not_a_trusted_receipt(ar, binding, small_input):
    process = FakeProcess(binding)
    with pytest.raises(ValueError, match="subscription_unverified"):
        dispatch(ar, binding, process=process, authority=FakeAuthority(accept=False))
    assert not process.calls
    assert p0.manifest(ar)["dispatch_gate_reason"] == "dispatch_receipts_or_subscription_unverified"


def test_fixture_receipt_rejected_even_when_adapter_would_accept(ar, binding, small_input):
    class TooPermissive(FakeAuthority):
        def verify_before_dispatch(self, context, receipts):
            return dict(
                chain_id=p0.AUTHORITY_CHAIN_ID, arm_tag=p0.ARM,
                configuration_id=context["configuration_id"], purpose=p0.PURPOSE, verified=True,
            )

    proof = receipts(reservation=canonical(dict(
        schema="arm_n.fixture_receipt/v1", arm_tag=p0.ARM, pre_reserved=True,
    )))
    process = FakeProcess(binding)
    with pytest.raises(ValueError):
        dispatch(ar, binding, process=process, authority=TooPermissive(), proof=proof)
    assert not process.calls
    assert p0.manifest(ar)["authority_receipt_status"] == "回执不可用"


@pytest.mark.parametrize("change", [
    {"chain_id": "0" * 64}, {"arm_tag": "EVO883_FACTOR"},
    {"configuration_id": "0" * 64}, {"purpose": "S0"}, {"verified": False},
])
def test_reservation_wrong_chain_arm_configuration_or_purpose_refused(
    ar, binding, small_input, change,
):
    process = FakeProcess(binding)
    with pytest.raises(ValueError, match="subscription_unverified"):
        dispatch(ar, binding, process=process, authority=FakeAuthority(identity_changes=change))
    assert not process.calls
    assert p0.manifest(ar)["authority_receipt_status"] == "回执不可用"


def test_config_location_is_explicit_and_not_created_or_read(ar, binding, small_input):
    process = FakeProcess(binding)
    with pytest.raises(ValueError, match="config_location_not_selected"):
        dispatch(ar, binding, process=process, config=False)
    assert not process.calls
    assert not (ar.anchor / "chosen-config").exists()


def test_parent_environment_is_not_inherited(ar, binding, small_input, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "never-use-this-parent-key")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    report, process = dispatch(ar, binding)
    assert report["checks"]["execution_completed"]
    for _, kwargs in process.calls:
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        assert "CLAUDE_CODE_USE_BEDROCK" not in kwargs["env"]


def test_config_location_is_bound_to_the_sealed_plan(ar, binding, small_input):
    first = SubprocessLauncher(binding, config_dir=ar.anchor / "config-a")
    p0.prepare(ar, binding, "case", launcher=first)
    second = SubprocessLauncher(binding, config_dir=ar.anchor / "config-b")
    with pytest.raises(ValueError, match="identity_conflict"):
        p0.prepare(ar, binding, "case", launcher=second)


@pytest.mark.parametrize("variable", [
    "ANTHROPIC_API_KEY", "FUTURE_VENDOR_APIKEY", "CLAUDE_CODE_OAUTH_TOKEN",
    "CUSTOM_AUTH_HEADER", "ANTHROPIC_BASE_URL", "FUTURE_MODEL_ENDPOINT",
    "HTTPS_PROXY", "AWS_PROFILE", "GOOGLE_APPLICATION_CREDENTIALS",
    "CLAUDE_CODE_USE_BEDROCK", "AZURE_RESOURCE", "api_key",
])
def test_metered_route_categories_refuse_before_any_version_or_dispatch(
    ar, binding, small_input, monkeypatch, variable,
):
    real_environment = launcher_module.child_environment

    def polluted(*args, **kwargs):
        return dict(real_environment(*args, **kwargs), **{variable: "must-not-be-read"})

    monkeypatch.setattr(launcher_module, "child_environment", polluted)
    process = FakeProcess(binding)
    report, _ = dispatch(ar, binding, process=process)
    assert not process.calls
    assert not report["checks"]["execution_completed"]
    assert report["N_request_delta"] is None
    assert report["launch_rejection"] == "metered_route_environment_forbidden"


@pytest.mark.parametrize("change", ["bare", "nonempty_sources", "settings_override"])
def test_forbidden_argv_stops_before_any_subprocess(ar, binding, small_input, monkeypatch, change):
    original = candidate_argv

    def changed(*args):
        argv = original(*args)
        if change == "bare":
            argv.append("--bare")
        elif change == "nonempty_sources":
            argv[argv.index("--setting-sources") + 1] = "user"
        else:
            argv += ["--settings", '{"apiKeyHelper":"forbidden"}']
        return argv

    monkeypatch.setattr(launcher_module, "candidate_argv", changed)
    process = FakeProcess(binding)
    report, _ = dispatch(ar, binding, process=process)
    assert not process.calls
    assert not report["checks"]["execution_completed"]
    assert report["launch_rejection"] == (
        "bare_forbidden" if change == "bare" else "settings_sources_must_be_empty"
    )


def test_transport_itself_refuses_without_dispatch_authorization(ar, binding):
    process = FakeProcess(binding)
    launcher = SubprocessLauncher(binding, runner=process, config_dir=ar.anchor / "config")
    with pytest.raises(ValueError, match="separate_dispatch_authorization_required"):
        launcher.launch(prompt=b"prompt", schema=b"{}", input_bytes=b"{}", workdir=ar.anchor / "work")
    assert not process.calls


@pytest.mark.parametrize("mode", ["wrong_version", "binary_change", "failure", "timeout"])
def test_binary_and_process_failures_retain_evidence_without_retry(ar, binding, small_input, mode):
    process = FakeProcess(binding, mode=mode)
    report, _ = dispatch(ar, binding, process=process, provider=UnknownProvider())
    assert not report["checks"]["provider_context_and_requests_verified"]
    assert report["N_request_delta"] is None
    assert len([argv for argv, _ in process.calls if "-p" in argv]) <= 1
    attempt = next(e["body"] for e in ar.events() if e["body"]["kind"] == "p0_attempt")
    if mode == "timeout":
        assert ar.get(attempt["raw_output_sha256"]) == b"partial stream"
    elif mode != "wrong_version":
        assert ar.get(attempt["raw_output_sha256"]).startswith(b"RAW_PRIVATE_STREAM")


@pytest.mark.parametrize("changes", [
    {"provider_model": "latest"}, {"provider_request_id": "unknown"},
    {"complete": False}, {"fallback": True}, {"request_count": 2},
    {"request_count": None}, {"request_count": True},
    {"effective_context": b"{}"}, {"request_map": b"[]"},
])
def test_unverified_or_multiple_requests_stay_unknown(ar, binding, small_input, changes):
    report, _ = dispatch(ar, binding, provider=FakeProvider(**changes))
    assert report["requires_extended_audit"]
    assert report["N_request_delta"] is None
    assert not report["checks"]["provider_context_and_requests_verified"]


def test_failed_authority_append_freezes_further_dispatch(ar, binding, small_input):
    process = FakeProcess(binding)
    report, _ = dispatch(ar, binding, process=process, authority=FakeAuthority(append=False))
    assert not report["checks"]["authority_append_verified"]
    reopened = Archive(ar.root, mode="p0_offline_test")
    with pytest.raises(ValueError, match="event_already_claimed"):
        dispatch(reopened, binding, process=process)
    assert len([argv for argv, _ in process.calls if "-p" in argv]) == 1


def test_same_dispatch_racing_twice_has_one_winner(ar, binding, small_input):
    process = FakeProcess(binding)

    def run(_):
        try:
            dispatch(ar, binding, process=process)
            return True
        except ValueError as exc:
            assert "already_claimed" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, [1, 2])) == [False, True]
    assert len([argv for argv, _ in process.calls if "-p" in argv]) == 1


def test_concurrent_duplicate_blob_never_observes_partial_bytes(ar, monkeypatch):
    created, release, second_started = Event(), Event(), Event()
    raw = b"complete immutable response" * 100
    target = str(ar.blobs / sha(raw))
    real_open = os.open

    def pause_after_create(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if str(path) == target and flags & os.O_EXCL:
            created.set()
            assert release.wait(5)
        return fd

    def second():
        second_started.set()
        return Archive(ar.root, mode="p0_offline_test").put(raw)

    monkeypatch.setattr(os, "open", pause_after_create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ar.put, raw)
        assert created.wait(5)
        other = pool.submit(second)
        assert second_started.wait(5)
        release.set()
        assert first.result() == other.result() == sha(raw)
    assert ar.get(sha(raw)) == raw


def test_crash_claim_survives_restart_and_is_not_reissued(ar):
    ar.append("p0:dispatch", dict(kind="p0_dispatch", blob_sha256s=[]), require_new=True)
    with pytest.raises(ValueError, match="already_claimed"):
        Archive(ar.root, mode="p0_offline_test").append(
            "p0:dispatch", dict(kind="p0_dispatch", blob_sha256s=[]), require_new=True,
        )
    assert p0.manifest(ar)["status"] == "INCOMPLETE_DISPATCH"


def test_archive_modes_cannot_relabel_existing_synthetic_data(ar):
    with pytest.raises(ValueError, match="identity_mismatch"):
        Archive(ar.root, mode="p0_subscription_preflight")
    old = Archive(archive_module.PHYSICAL_ROOT / "old")
    with pytest.raises(ValueError, match="distinct_archive_identity"):
        p0.manifest(old)
    with pytest.raises(ValueError, match="private_physical_root"):
        Archive(old.root, mode="p0_subscription_preflight")


def test_readonly_verification_does_not_modify_or_create(ar, binding, small_input):
    report, _ = dispatch(ar, binding)
    before = {p.name: (p.stat().st_mtime_ns, sha(p.read_bytes())) for p in ar.root.iterdir() if p.is_file()}
    readonly = Archive(ar.root, mode="p0_offline_test", readonly=True)
    assert p0.manifest(readonly, expected_tip=report["archive_tip_sha256"]) == report
    with pytest.raises(ValueError, match="readonly"):
        readonly.put(b"new")
    with pytest.raises(ValueError, match="readonly"):
        readonly.append("new", {})
    after = {p.name: (p.stat().st_mtime_ns, sha(p.read_bytes())) for p in ar.root.iterdir() if p.is_file()}
    assert before == after
    missing = ar.anchor / "missing"
    with pytest.raises(sqlite3.OperationalError):
        Archive(missing, mode="p0_offline_test", readonly=True)
    assert not missing.exists()


def test_corruption_and_wrong_external_anchor_are_detected(ar, binding, small_input):
    report, _ = dispatch(ar, binding)
    with pytest.raises(ValueError, match="external_anchor_mismatch"):
        p0.manifest(ar, expected_tip="0" * 64)
    (ar.blobs / report["blob_sha256s"][0]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="blob_hash_mismatch"):
        p0.manifest(ar)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "outside", "installed"])
def test_binary_aliases_and_installed_paths_are_rejected(binding, tmp_path, kind):
    if kind == "symlink":
        path = binding.isolated_root / "other" / "claude"
        path.parent.mkdir()
        path.symlink_to(binding.executable)
    elif kind == "hardlink":
        path = binding.isolated_root / "other" / "claude"
        path.parent.mkdir()
        os.link(binding.executable, path)
    elif kind == "outside":
        path = tmp_path / "claude"
    else:
        # Rejected lexically without opening or inspecting the actual CLI.
        path = Path.home() / ".local" / "bin" / "claude"
    with pytest.raises(ValueError, match="isolated_binary|regular_binary"):
        replace(binding, executable=path).fingerprint()


def test_cli_real_synthetic_input_prepare_and_readonly_verify(binding, capsys):
    argv = ["--run-id", "integration", "--binary", str(binding.executable),
            "--binary-root", str(binding.isolated_root),
            "--binary-sha256", binding.binary_sha256]
    assert p0.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "OFFLINE_PREPARED"
    assert not report["checks"]["dispatch_recorded"]
    assert p0.main(["--run-id", "integration", "--verify", "--expected-tip", report["archive_tip_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out) == report


def test_cli_has_no_dispatch_flag():
    with pytest.raises(SystemExit) as exc:
        p0.main(["--run-id", "case", "--dispatch"])
    assert exc.value.code == 2


@pytest.mark.parametrize("sources", [
    ["--setting-sources", "", "--setting-sources=user"],
    ["--setting-sources=", "--setting-sources", ""],
    ["--setting-sources=", "--setting-sources="],
    ["--setting-sources", "", "--setting-sources", ""],
    ["--setting-sources=user"], ["--setting-sources", "user"],
    ["--setting-sources"], [],
])
def test_all_source_argument_forms_reject_duplicates_or_nonempty(
    ar, binding, small_input, monkeypatch, sources,
):
    original = candidate_argv

    def changed(*args):
        argv = original(*args)
        index = argv.index("--setting-sources")
        return argv[:index] + sources + argv[index + 2:]

    monkeypatch.setattr(launcher_module, "candidate_argv", changed)
    process = FakeProcess(binding)
    report, _ = dispatch(ar, binding, process=process)
    assert process.calls == []
    assert report["launch_rejection"] == "settings_sources_must_be_empty"


def test_one_inline_empty_source_is_parsed_as_empty(ar, binding, small_input, monkeypatch):
    original = candidate_argv

    def inline(*args):
        argv = original(*args)
        index = argv.index("--setting-sources")
        return argv[:index] + ["--setting-sources="] + argv[index + 2:]

    monkeypatch.setattr(launcher_module, "candidate_argv", inline)
    report, process = dispatch(ar, binding)
    assert report["checks"]["execution_completed"]
    assert len([argv for argv, _ in process.calls if "-p" in argv]) == 1


@pytest.mark.parametrize("inherited", [False, True])
def test_unimplemented_provider_is_rejected_before_any_subprocess(
    ar, binding, small_input, inherited,
):
    class InheritsStub(p0.EvidencePort):
        pass

    process = FakeProcess(binding)
    provider = InheritsStub() if inherited else p0.EvidencePort()
    with pytest.raises(ValueError, match="provider_extraction_adapter_required"):
        dispatch(ar, binding, process=process, provider=provider)
    assert process.calls == []
    report = p0.manifest(ar)
    assert not report["checks"]["dispatch_recorded"]
    assert report["dispatch_gate_reason"] == "provider_extraction_adapter_required"


@pytest.mark.parametrize("escaped", [
    '{"schema":"arm_n.fixture_receipt/v1"}',
    r'{"schema":"arm_n.fixture_receipt\/v1"}',
    r'{"schema":"arm_n.fixture_receipt\u002fv1"}',
    r'{"sch\u0065ma":"arm_n.fixture_receipt\u002fv1"}',
    r'{"wrapped":{"schema":"arm_n.fixture_receipt\u002fv1"}}',
])
@pytest.mark.parametrize("where", ["reservation", "append"])
def test_structured_fixture_schemas_cannot_be_escaped(
    ar, binding, small_input, escaped, where,
):
    class PermissiveAuthority(FakeAuthority):
        def verify_before_dispatch(self, context, proof):
            return dict(
                chain_id=p0.AUTHORITY_CHAIN_ID, arm_tag=p0.ARM,
                configuration_id=context["configuration_id"], purpose=p0.PURPOSE, verified=True,
            )

        def append_attempt(self, context, attempt):
            return escaped.encode()

        def verify_append(self, context, attempt, receipt):
            pytest.fail("fixture append reached authority verification")

    process = FakeProcess(binding)
    authority = PermissiveAuthority()
    if where == "reservation":
        with pytest.raises(ValueError, match="fixture_receipt_not_authoritative"):
            dispatch(
                ar, binding, process=process, authority=authority,
                proof=receipts(reservation=escaped.encode()),
            )
        assert process.calls == []
    else:
        report, _ = dispatch(ar, binding, process=process, authority=authority)
        assert not report["checks"]["authority_append_verified"]
        appended = next(e["body"] for e in ar.events() if e["body"]["kind"] == "p0_append_receipt")
        assert ar.get(appended["receipt_sha256"]) == escaped.encode()
        assert not appended["verified"]
    assert p0.manifest(ar)["authority_receipt_status"] == "回执不可用"


@pytest.mark.parametrize("values", [
    {"overageEnabled": True, "errorCode": "rate_limit"},
    {"overageEnabled": False, "errorCode": None},
    {},
    {"errorCode": "credits_required"},
])
@pytest.mark.parametrize("nested", [False, True])
def test_usage_events_are_projected_without_inventing_disabled_state(
    ar, binding, small_input, values, nested,
):
    event = dict(type="rate_limit_event")
    if nested:
        event["rate_limit_info"] = values
    else:
        event.update(values)
    raw = canonical(event) + b"\n"
    process = FakeProcess(binding, stdout=raw)
    report, _ = dispatch(ar, binding, process=process, provider=UnknownProvider())
    attempt = next(e["body"] for e in ar.events() if e["body"]["kind"] == "p0_attempt")
    for key in ("overageEnabled", "errorCode"):
        expected = values.get(key, "unknown")
        assert attempt[key] == report[key] == expected
        assert attempt[key + "_present"] == report[key + "_present"] == (key in values)
    assert attempt["usage_events"] == report["usage_events"]
    assert ar.get(attempt["raw_output_sha256"]) == raw
    assert report["N_request_delta"] is None
    assert not report["checks"]["provider_context_and_requests_verified"]


def test_usage_history_keeps_values_before_a_later_missing_event(ar, binding, small_input):
    raw = b"\n".join([
        canonical(dict(type="rate_limit_event", overageEnabled=True)),
        canonical(dict(type="rate_limit_event", errorCode="credits_required")),
        canonical(dict(type="rate_limit_event")),
    ])
    report, _ = dispatch(ar, binding, process=FakeProcess(binding, stdout=raw))
    assert report["overageEnabled"] == report["errorCode"] == "unknown"
    assert report["usage_events"][0]["overageEnabled"] is True
    assert report["usage_events"][1]["errorCode"] == "credits_required"
    assert report["usage_events"][2]["overageEnabled_present"] is False


@pytest.mark.parametrize("kind", ["shared", "symlink", "relative", "dotdot", "unapproved", "missing_binding"])
def test_config_isolation_rejected_before_first_version_probe(
    ar, binding, small_input, monkeypatch, tmp_path, kind,
):
    approved = isolated_config(ar)
    fake_home = tmp_path / "fake-home"
    shared = fake_home / ".claude"
    shared.mkdir(mode=0o700, parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    selected, supplied = approved.directory, approved
    if kind == "shared":
        selected = shared
        supplied = replace(approved, directory=shared, realpath=shared)
    elif kind == "symlink":
        selected = approved.root / "shared-link"
        selected.symlink_to(shared, target_is_directory=True)
        supplied = replace(approved, directory=selected, realpath=selected)
    elif kind == "relative":
        selected = Path("approved-configs") / "chosen-config"
    elif kind == "dotdot":
        selected = approved.root / ".." / "approved-configs" / "chosen-config"
    elif kind == "unapproved":
        root = ar.anchor / "unapproved-configs"
        root.mkdir(mode=0o700)
        selected = root / "chosen-config"
        selected.mkdir(mode=0o700)
        supplied = replace(approved, root=root, directory=selected, realpath=selected)
    elif kind == "missing_binding":
        supplied = None
    process = FakeProcess(binding)
    if kind == "relative":
        with pytest.raises(ValueError, match="absolute_config_location"):
            dispatch(ar, binding, process=process, transport_changes=dict(
                config_dir=selected, config_binding=supplied,
            ))
    else:
        report, _ = dispatch(ar, binding, process=process, transport_changes=dict(
            config_dir=selected, config_binding=supplied,
        ))
        assert report["launch_rejection"] == "isolated_config_not_verified"
    assert process.calls == []


def test_both_version_probes_use_one_verified_config_directory(ar, binding, small_input):
    approved = isolated_config(ar)
    report, process = dispatch(ar, binding)
    assert report["checks"]["execution_completed"]
    probes = [kwargs for argv, kwargs in process.calls if argv[-1] == "--version"]
    assert len(probes) == 2
    assert {kwargs["env"]["CLAUDE_CONFIG_DIR"] for kwargs in probes} == {str(approved.realpath)}
    context = next(e["body"]["context"] for e in ar.events() if e["body"]["kind"] == "p0_plan")
    assert context["config_isolation_binding"] == approved.manifest()


@pytest.mark.parametrize("replace_after", ["version", "dispatch"])
def test_config_identity_swap_is_rejected_before_the_next_subprocess(
    ar, binding, small_input, replace_after,
):
    approved = isolated_config(ar)

    class ConfigSwapProcess(FakeProcess):
        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            trigger = argv[-1] == "--version" if replace_after == "version" else "-p" in argv
            if trigger:
                approved.directory.rename(approved.root / "original-config")
                approved.directory.mkdir(mode=0o700)
            return result

    process = ConfigSwapProcess(binding)
    report, _ = dispatch(ar, binding, process=process)
    assert not report["checks"]["binary_verified"]
    assert len([argv for argv, _ in process.calls if argv[-1] == "--version"]) == 1
    assert len([argv for argv, _ in process.calls if "-p" in argv]) == (replace_after == "dispatch")


def test_archive_refuses_escape_before_any_directory_creation(tmp_path):
    target = tmp_path / "escape"
    with pytest.raises(ValueError, match="private_physical_root"):
        Archive(target, mode="p0_subscription_preflight")
    assert not target.exists()

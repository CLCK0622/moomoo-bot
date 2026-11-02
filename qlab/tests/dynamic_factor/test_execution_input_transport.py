"""C09 isolated data transport. Synthetic values never become runtime evidence."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.reference_boundary import (
    prepare_execution_inputs,
    run_isolated,
)
from qlab.dynamic_factor.reference_check import static_proof
from qlab.dynamic_factor.execution_receipts import input_data
from qlab.dynamic_factor.execution_receipts.input_run import (
    InputPreparation,
    read_preparation,
)
from test_execution_input_envelope import packet


ROLES = ("raw", "rights", "adv", "cash")


def fixture(root, *, member=0, verified=49):
    args = packet(member=member, verified=verified)
    profile, scope, manifest, expected = args
    payloads = {}
    for role in ROLES:
        value = (
            {"raw_open": "100.1", "raw_close": None}
            if role == "raw"
            else {"adv20_dollar": "123456.789"}
            if role == "adv"
            else {role + "_events": []}
        )
        data = dict(
            schema="EVO884.RestrictedExecutionRows/v1",
            role=role,
            **{k: manifest[k] for k in input_data.IDENTITIES},
            records=[
                dict(
                    date=d,
                    symbol=s,
                    available_at="2026-11-01T00:00:00Z",
                    values=deepcopy(value),
                )
                for d in manifest["inputs"][role]["requested_dates"]
                for s in manifest["inputs"][role]["symbols"]
            ],
        )
        payloads[role] = data
    write(root, args, payloads)
    return args, payloads


def write(root, args, payloads):
    for role, value in payloads.items():
        raw = canonical(value)
        (root / (role + ".json")).write_bytes(raw)
        args[2]["inputs"][role]["sha256"] = sha256(raw)
    args[3]["expected_manifest_sha256"] = digest(args[2])


def execute(root, args):
    capability = prepare_execution_inputs(*args[:3], **args[3])
    request, expected = read_preparation(capability)
    return run_isolated(root, request, input_preparation=capability)


def assert_pending(report):
    assert report["seal_status"] == "seal_pending"
    assert all(
        report[k] is False
        for k in (
            "economic_content_validated",
            "accounting_executed",
            "evidence_accepted",
            "complete",
            "runtime_consumable",
            "certifiable",
        )
    )
    assert report["returns"] is report["sr"] is None


@pytest.mark.parametrize("member", range(4))
@pytest.mark.parametrize("verified", [49, 50])
def test_A06_A21_four_roles_real_isolated_child_keeps_unknowns_and_pending(
    tmp_path, member, verified
):
    args, data = fixture(tmp_path, member=member, verified=verified)
    report = execute(tmp_path, args)
    assert report["transport_complete"] is True
    assert report["data"] == data
    assert report["data"]["raw"]["records"][0]["values"]["raw_close"] is None
    assert report["accessed_roles"] == list(ROLES) and report["reader_calls"] == 4
    receipt = report["access_boundary_receipt"]
    assert receipt["schema"] == "EVO884.ExecutionInputBoundary/v1"
    assert receipt["source_acceptance"] == "not_checked"
    assert receipt["declared_input_manifest"] == args[2]
    assert receipt["declared_source_receipt_sha256"] == {
        r: args[2]["inputs"][r]["source_receipt_sha256"] for r in ROLES
    }
    assert (
        receipt["isolated_child"] is True and receipt["seal_status"] == "seal_pending"
    )
    assert receipt["input_file_sha256"] == {
        r: args[2]["inputs"][r]["sha256"] for r in ROLES
    }
    assert_pending(report)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("attack", ["missing", "symlink", "hardlink"])
def test_A06_all_file_paths_preflight_before_first_open(tmp_path, role, attack):
    args, _ = fixture(tmp_path)
    target = tmp_path / (role + ".json")
    saved = tmp_path / "unapproved.json"
    if attack != "missing":
        target.rename(saved)
    else:
        target.unlink()
    if attack == "symlink":
        target.symlink_to(saved)
    elif attack == "hardlink":
        os.link(saved, target)
    report = execute(tmp_path, args)
    assert report["reason"] == "execution_input.read_path_not_whitelisted"
    assert report["reader_calls"] == 0 and report["accessed_roles"] == []
    assert_pending(report)


@pytest.mark.parametrize("role", ROLES)
def test_A21_changed_original_bytes_report_the_real_failed_read(tmp_path, role):
    args, _ = fixture(tmp_path)
    with (tmp_path / (role + ".json")).open("ab") as handle:
        handle.write(b" ")
    report = execute(tmp_path, args)
    assert report["reason"] == "execution_input.original_file_sha_mismatch"
    assert report["accessed_roles"] == list(ROLES[: ROLES.index(role) + 1])
    assert report["reader_calls"] == ROLES.index(role) + 1
    assert_pending(report)


@pytest.mark.parametrize(
    "attack", ["future", "B", "duplicate", "missing", "injection", "identity", "field"]
)
def test_A05_A06_payload_self_rehash_cannot_expand_declared_inputs(tmp_path, attack):
    args, data = fixture(tmp_path)
    rows = data["raw"]["records"]
    if attack == "future":
        rows[0]["date"] = "2099-01-01"
    elif attack == "B":
        rows[0]["symbol"] = "FORBIDDEN_CHILD"
    elif attack == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif attack == "missing":
        rows.clear()
    elif attack == "injection":
        rows[0]["returns"] = [0.1]
    elif attack == "identity":
        data["raw"]["book_id"] = digest("other book")
    else:
        rows[0]["values"]["M"] = 0
    write(tmp_path, args, data)
    report = execute(tmp_path, args)
    assert (
        report["transport_complete"] is False and "execution_input." in report["reason"]
    )
    assert report["accessed_roles"] == ["raw"]
    assert_pending(report)


@pytest.mark.parametrize("role", ROLES)
def test_original_B_guard_refuses_before_preparation_or_worker(
    tmp_path, role, monkeypatch
):
    args = packet(blocked=True)
    args[2]["inputs"][role]["symbols"] += [args[1]["guard"]["B"][0]]
    args[3]["expected_manifest_sha256"] = digest(args[2])

    def forbidden(*args, **kwargs):
        raise AssertionError("worker entered before B rejection")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(
        ValueError, match="B.parent_unknown_or_child_numeric_read_forbidden"
    ):
        execute(tmp_path, args)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("forged", [{"source_verified": True}, None])
def test_wire_dictionary_cannot_replace_host_preparation(tmp_path, forged):
    with pytest.raises(ValueError, match="host_preparation_required"):
        run_isolated(tmp_path, {}, input_preparation=forged or object())
    with pytest.raises(TypeError, match="host_preparation_required"):
        InputPreparation()


def test_stdin_rebinding_is_refused_in_host_before_subprocess(tmp_path, monkeypatch):
    args, _ = fixture(tmp_path)
    capability = prepare_execution_inputs(*args[:3], **args[3])
    request, _ = read_preparation(capability)
    request["manifest"]["run_id"] += "other"
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: seen.append(a))
    with pytest.raises(ValueError, match="host_request_binding_mismatch"):
        run_isolated(tmp_path, request, input_preparation=capability)
    assert seen == []


def test_preparation_cannot_be_combined_with_formal_authority_objects(tmp_path):
    args, _ = fixture(tmp_path)
    capability = prepare_execution_inputs(*args[:3], **args[3])
    request, _ = read_preparation(capability)
    with pytest.raises(ValueError, match="preparation_is_not_authority_reception"):
        run_isolated(tmp_path, request, input_preparation=capability, run_pin=object())


def test_native_metadata_repr_cannot_enter_subprocess_bootstrap(tmp_path):
    args, _ = fixture(tmp_path)

    class HostileHash(str):
        def __repr__(self):
            raise AssertionError("native metadata repr entered bootstrap")

        def __deepcopy__(self, memo):
            return self

    args[2]["book_id"] = HostileHash(args[2]["book_id"])
    args[3]["expected_manifest_sha256"] = digest(args[2])
    cap = prepare_execution_inputs(*args[:3], **args[3])
    request, expected = read_preparation(cap)
    assert type(expected["book_id"]) is str
    report = run_isolated(tmp_path, request, input_preparation=cap)
    assert report["transport_complete"] is True
    assert_pending(report)


def test_legacy_entry_via_changed_host_also_marks_reads_seal_pending(tmp_path):
    from qlab.dynamic_factor.conventions import load_conventions, FIXTURES
    from test_registered_reference import producer_fixture

    policy = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    root = tmp_path / "legacy-inputs"
    request = producer_fixture(root, policy)
    report = run_isolated(root, request)
    assert report["accessed_roles"] == ["benchmark", "panel", "profile"]
    assert report["seal_status"] == "seal_pending"
    assert report["access_boundary_receipt"]["seal_status"] == "seal_pending"
    assert report["returns"] is None and report["runtime_consumable"] is False


@pytest.mark.parametrize("placement", ["root", "envelope", "trial", "boundary"])
def test_A22_real_runtime_entry_refuses_pending_before_any_authority_read(
    monkeypatch, placement
):
    from qlab.dynamic_factor import authority_host
    from qlab.dynamic_factor.reference_registry_v3 import registered_request
    from qlab.dynamic_factor.reference_v3_evidence import lineage_proof, runtime_check
    from v3_reference_helpers import unit_scope

    scope = unit_scope(real=True)
    request = registered_request()
    request.update(
        scope=scope,
        static_seal=lineage_proof(scope, "2026-10-30T12:10:00Z")["static_seal"],
    )
    marker = dict(seal_status="seal_pending")
    sidecar = marker if placement == "root" else {placement: [marker]}
    raw = canonical(sidecar)
    request.update(
        sidecars={"candidate": sha256(raw)}, evidence_files={sha256(raw): raw.decode()}
    )
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("authority")
        raise AssertionError("pending sidecar reached authority reader")

    monkeypatch.setattr(authority_host, "observe", forbidden)
    report = runtime_check(request)
    assert report["reasons"] == ["reference.seal_pending"] and not report["ok"]
    assert (
        report["metrics"]["complete_N"] is None
        and report["metrics"]["evidence_valid"] is False
    )
    assert not calls and report["runtime_consumable"] is False


def test_A22_caller_sealed_label_does_not_supply_missing_B_P4_P7():
    from qlab.dynamic_factor.reference_registry_v3 import registered_request
    from qlab.dynamic_factor.reference_v3_evidence import lineage_proof, runtime_check
    from v3_reference_helpers import unit_scope

    scope = unit_scope(real=True)
    request = registered_request()
    request.update(
        scope=scope,
        static_seal=lineage_proof(scope, "2026-10-30T12:10:00Z")["static_seal"],
    )
    raw = canonical(dict(seal_status="sealed", source_verified=True, complete=True))
    request.update(
        sidecars={"candidate": sha256(raw)}, evidence_files={sha256(raw): raw.decode()}
    )
    report = runtime_check(request)
    assert report["reasons"] == [
        "reference.runtime_B_release_and_actual_proofs_missing"
    ]
    assert report["metrics"]["evidence_valid"] is False and not report["ok"]


def test_A05_header_batch_is_checked_before_any_value(monkeypatch):
    args = packet()

    class Canary(dict):
        def __getitem__(self, key):
            raise AssertionError("numeric value accessed before header rejection")

        def __iter__(self):
            raise AssertionError("numeric value accessed before header rejection")

    data = dict(
        schema="EVO884.RestrictedExecutionRows/v1",
        role="raw",
        **{k: args[2][k] for k in input_data.IDENTITIES},
        records=[
            dict(date="2099-01-01", symbol="QQQ", available_at="", values=Canary())
        ],
    )
    monkeypatch.setattr(input_data, "strict_json", lambda raw: data)
    with pytest.raises(ValueError, match="exact_declared_date_symbol_batch_required"):
        input_data.validate_data(b"canary", "raw", args[2])


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_noncanonical_json_aliases_and_nonfinite_refuse(raw):
    with pytest.raises(ValueError):
        input_data.strict_json(raw)


def test_original_event_bytes_are_retained_and_not_interpreted_as_cash(tmp_path):
    args, data = fixture(tmp_path)
    original = '{ "symbol": "QQQ", "amount": null, "pay_date": "2026-11-05" }'
    event = dict(raw=original, sha256=sha256(original.encode()))
    data["cash"]["records"][0]["values"]["cash_events"] = [event]
    data["rights"]["records"][0]["values"]["rights_events"] = None
    write(tmp_path, args, data)
    report = execute(tmp_path, args)
    assert report["transport_complete"] is True
    assert report["data"]["cash"]["records"][0]["values"]["cash_events"] == [event]
    assert_pending(report)


@pytest.mark.parametrize(
    "attack",
    ["event_sha", "duplicate_event_key", "array_event", "dict_value", "bool_amount"],
)
def test_event_and_scalar_transport_failures_never_become_known(tmp_path, attack):
    args, data = fixture(tmp_path)
    if attack in {"dict_value", "bool_amount"}:
        data["raw"]["records"][0]["values"]["raw_open"] = (
            {} if attack == "dict_value" else True
        )
    else:
        raw = '{"x":1,"x":2}' if attack == "duplicate_event_key" else "[]"
        data["rights"]["records"][0]["values"]["rights_events"] = [
            dict(raw=raw, sha256=sha256(raw.encode()))
        ]
        if attack == "event_sha":
            data["rights"]["records"][0]["values"]["rights_events"][0]["sha256"] = (
                digest("other")
            )
    write(tmp_path, args, data)
    report = execute(tmp_path, args)
    assert report["transport_complete"] is False
    assert_pending(report)


def test_static_proof_names_old_and_new_readers_separately():
    proof = static_proof()
    assert set(proof["module_import_graph"]) == set(proof["import_graph"]) | {
        "execution_receipts.input_data",
        "execution_receipts.input_guard",
        "execution_receipts.input_reader",
    }
    assert set(proof["execution_preparation_import_graph"]) == {
        "reference_producer_v3",
        "execution_receipts.input_data",
        "execution_receipts.input_guard",
        "execution_receipts.input_reader",
    }
    assert proof["read_whitelist"] == dict(
        panel="panel.json", benchmark="benchmark.json", profile="profile.json"
    )
    assert proof["execution_preparation_read_whitelist"] == {
        r: r + ".json" for r in ROLES
    }
    assert {r["module"] for r in proof["reader_sites"]} == {
        "reference_inputs",
    }
    assert {r["module"] for r in proof["execution_preparation_reader_sites"]} == {
        "execution_receipts.input_reader",
    }


def test_stdin_cannot_rebind_worker_expectations_even_if_host_is_bypassed(tmp_path):
    args, _ = fixture(tmp_path)
    cap = prepare_execution_inputs(*args[:3], **args[3])
    request, expected = read_preparation(cap)
    request["manifest"]["book_id"] = digest("other book")
    package = str(Path(__file__).resolve().parents[2])
    code = (
        "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,"
        + repr(package)
        + ");from qlab.dynamic_factor.reference_producer_v3 import execution_main;"
        + "raise SystemExit(execution_main("
        + repr(expected)
        + "))"
    )
    child = subprocess.run(
        [sys.executable, "-B", "-I", "-S", "-c", code, "--inputs-root", str(tmp_path)],
        input=json.dumps(request),
        env={},
        close_fds=True,
        capture_output=True,
        text=True,
    )
    assert child.returncode == 2 and child.stderr == ""
    report = json.loads(child.stdout)
    assert report["reason"] == "execution_input.host_request_binding_mismatch"
    assert report["accessed_roles"] == [] and report["reader_calls"] == 0
    assert_pending(report)


@pytest.mark.parametrize(
    "attack",
    [
        "returns",
        "complete",
        "economic_content_validated",
        "evidence_accepted",
        "accounting_executed",
        "certifiable",
        "runtime_consumable",
        "seal_status",
        "extra_M",
        "roles",
        "reader_calls",
        "transport_type",
    ],
)
def test_untrusted_worker_reply_cannot_upgrade_preparation(
    tmp_path, monkeypatch, attack
):
    args, _ = fixture(tmp_path)
    cap = prepare_execution_inputs(*args[:3], **args[3])
    request, _ = read_preparation(cap)
    report = dict(
        schema="EVO884.ExecutionInputTransport/v1",
        transport_complete=False,
        economic_content_validated=False,
        accounting_executed=False,
        evidence_accepted=False,
        complete=False,
        runtime_consumable=False,
        certifiable=False,
        seal_status="seal_pending",
        returns=None,
        sr=None,
        reason="SYNTHETIC REFUSAL",
        accessed_roles=[],
        reader_calls=0,
    )
    if attack == "returns":
        report["returns"] = [0.01]
    elif attack == "seal_status":
        report["seal_status"] = "sealed"
    elif attack == "extra_M":
        report["M"] = {"QQQ": 1}
    elif attack == "roles":
        report["accessed_roles"] = ["candidate_returns"]
        report["reader_calls"] = 1
    elif attack == "reader_calls":
        report["reader_calls"] = 1
    elif attack == "transport_type":
        report["transport_complete"] = 1
    else:
        report[attack] = True

    def child(argv, **kw):
        assert "-I" in argv and "-S" in argv
        assert kw["env"] == {} and kw["close_fds"] is True
        return subprocess.CompletedProcess(argv, 2, json.dumps(report), "")

    monkeypatch.setattr(subprocess, "run", child)
    with pytest.raises(ValueError, match="execution_input.unexpected_worker_output"):
        run_isolated(tmp_path, request, input_preparation=cap)


@pytest.mark.parametrize(
    "attack",
    [
        "foreign_import",
        "reader_in_parser",
        "guard_after_read",
        "extension_in_legacy_entry",
    ],
)
def test_static_dependency_and_guard_order_mutations_are_rejected(monkeypatch, attack):
    original = Path.read_bytes

    def changed(path):
        raw = original(path)
        if attack == "foreign_import" and path.name == "input_reader.py":
            return raw + b"\nimport socket\n"
        if attack == "reader_in_parser" and path.name == "input_data.py":
            return raw + b"\ndef bad(p):\n    return p.read_bytes()\n"
        if attack == "guard_after_read" and path.name == "reference_producer_v3.py":
            return raw.replace(
                b"reads = install_execution(args.inputs_root)", b"reads = []"
            ).replace(
                b"data = read_execution(args.inputs_root, request, expected)",
                b"data = read_execution(args.inputs_root, request, expected)\n        reads = install_execution(args.inputs_root)",
            )
        if (
            attack == "extension_in_legacy_entry"
            and path.name == "reference_producer_v3.py"
        ):
            return raw.replace(
                b"def prepare(root, request, mechanisms=None):",
                b"def prepare(root, request, mechanisms=None):\n    from .execution_receipts.input_reader import read_inputs as bad",
            )
        return raw

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(
        ValueError,
        match="static_dependency_forbidden|static_reader_forbidden|audit_hook_must_precede|execution_import_outside_entry",
    ):
        static_proof()


@pytest.mark.parametrize("operation", ["outside_read", "write", "network", "listdir"])
def test_new_guard_real_isolated_child_forbids_unlisted_capabilities(
    tmp_path, operation
):
    package = str(Path(__file__).resolve().parents[2])
    outside = tmp_path / "outside.json"
    outside.write_text("CANARY")
    ops = {
        "outside_read": "outside.read_bytes()",
        "write": "(root / 'raw.json').write_bytes(b'overwrite')",
        "network": "socket.socket()",
        "listdir": "os.listdir(root)",
    }
    code = (
        "import sys,json,os,socket;from pathlib import Path;sys.dont_write_bytecode=True;"
        + "sys.path.insert(0,"
        + repr(package)
        + ");"
        + "from qlab.dynamic_factor.execution_receipts.input_guard import install;"
        + "root=Path("
        + repr(str(tmp_path))
        + ");outside=root/'outside.json';reads=install(root)\n"
        + "try:\n "
        + ops[operation]
        + "\nexcept ValueError as e:\n print(json.dumps(dict(reason=str(e),reads=reads)))\nelse:\n raise SystemExit(99)"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-S", "-c", code],
        env={},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stderr == ""
    report = json.loads(result.stdout)
    assert report["reads"] == [] and report["reason"].startswith(
        "execution_input.access_boundary_"
    )
    assert outside.read_text() == "CANARY" and not (tmp_path / "raw.json").exists()

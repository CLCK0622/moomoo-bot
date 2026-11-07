"""C09 independent metadata preparation; no runtime or source acceptance."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import validate, ValidationError

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_receipts.input_envelope import (
    prepare_input_envelope,
    SCHEMA,
    SLOTS,
    MANIFEST_KEYS,
    SLOT_KEYS,
)
from qlab.dynamic_factor.noncash_v3 import CONSUMERS
from test_reference_day_inputs import fixture


def packet(*, member=0, verified=49, blocked=False):
    profile, scope, book, *_ = fixture(
        member=member, verified=verified, blocked=blocked
    )
    manifest = dict(
        schema=SCHEMA,
        book_id=book,
        run_id="C09-SYNTHETIC-PREFLIGHT",
        member_id=profile["definition"]["member_id"],
        scope_sha256=scope["scope_sha256"],
        profile_sha256=profile["profile_sha256"],
        inputs={
            role: dict(
                file=role + ".json",
                sha256=digest([role, "SYNTHETIC FILE"]),
                source_receipt_sha256=digest([role, "UNAUTHENTICATED RECEIPT"]),
                requested_dates=scope["train"],
                requested_consumer="holdings_valuation",
                symbols=["QQQ"],
            )
            for role in SLOTS
        },
    )
    expected = dict(
        book_id=book,
        run_id=manifest["run_id"],
        expected_manifest_sha256=digest(manifest),
        expected_scope_sha256=scope["scope_sha256"],
        expected_profile_sha256=profile["profile_sha256"],
    )
    return profile, scope, manifest, expected


def prepare(args, *, rehash=False):
    profile, scope, manifest, expected = args
    if rehash:
        expected["expected_manifest_sha256"] = digest(manifest)
    return prepare_input_envelope(profile, scope, manifest, **expected)


def assert_unexecuted(result):
    assert (
        result["accounting_executed"]
        is result["evidence_accepted"]
        is result["complete"]
        is False
    )
    assert result["certifiable"] is result["runtime_consumable"] is False
    assert result["reader_calls"] == result["executor_calls"] == 0
    assert result["accessed_roles"] == result["worker_roles"] == []
    assert result["source_acceptance"] == "not_checked"


@pytest.mark.parametrize("member", range(4))
@pytest.mark.parametrize("verified", [49, 50])
def test_A01_A24_prepared_metadata_never_claims_accounting_or_evidence(
    member, verified
):
    args = packet(member=member, verified=verified)
    before = deepcopy(args)
    result = prepare(args)
    assert result["prepared"] is True and result["reasons"] == []
    assert result["manifest"] == args[2] and result["manifest_sha256"] == digest(
        args[2]
    )
    assert result["phase"] == "input_preparation"
    assert_unexecuted(result)
    result["manifest"]["inputs"]["raw"]["symbols"].clear()
    assert args == before


@pytest.mark.parametrize(
    "key",
    [
        "M",
        "P",
        "returns",
        "current_candidate",
        "current_meta_pool",
        "source_verified",
        "runtime_consumable",
    ],
)
def test_A05_caller_injection_rejected_before_metadata_can_be_prepared(key):
    args = packet()
    args[2][key] = True
    result = prepare(args, rehash=True)
    assert result["prepared"] is False
    assert result["reasons"] == ["input_manifest.schema_or_injection_forbidden"]
    assert_unexecuted(result)


@pytest.mark.parametrize("role", SLOTS)
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_slot",
        "missing_receipt",
        "wire_receipt",
        "filename",
        "payload_injection",
    ],
)
def test_A05_missing_source_receipt_alias_or_inline_result_refuses(role, mutation):
    args = packet()
    slot = args[2]["inputs"][role]
    if mutation == "missing_slot":
        del args[2]["inputs"][role]
    elif mutation == "missing_receipt":
        slot["source_receipt_sha256"] = None
    elif mutation == "wire_receipt":
        slot["source_receipt_sha256"] = {"PASS": True}
    elif mutation == "filename":
        slot["file"] = "../" + role + ".json"
    else:
        slot["M"] = {"QQQ": 1}
    result = prepare(args, rehash=True)
    assert result["prepared"] is False and result["reasons"]
    assert result["manifest"] is None
    assert_unexecuted(result)


@pytest.mark.parametrize("role", SLOTS)
@pytest.mark.parametrize(
    "dates", [["2099-01-01"], ["not-a-date"], [], ["2016-03-18", "2016-03-18"]]
)
def test_A06_requested_future_gap_or_invalid_calendar_refuses(role, dates):
    args = packet()
    args[2]["inputs"][role]["requested_dates"] = dates
    result = prepare(args, rehash=True)
    assert result["prepared"] is False and result["reasons"]
    assert_unexecuted(result)


@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_A13_entire_declared_B_batch_refuses_with_original_guard(consumer):
    args = packet(blocked=True)
    args[2]["inputs"]["cash"].update(
        requested_consumer=consumer,
        symbols=["QQQ", args[1]["guard"]["B"][0]],
    )
    before = deepcopy(args[2])
    result = prepare(args, rehash=True)
    assert result["reasons"] == ["B.parent_unknown_or_child_numeric_read_forbidden"]
    assert result["prepared"] is False and args[2] == before
    assert_unexecuted(result)


@pytest.mark.parametrize(
    "change", ["manifest", "book", "run", "member", "scope", "profile"]
)
def test_host_expected_identity_is_separate_and_cannot_be_repaired_by_rehash(change):
    args = packet()
    if change == "manifest":
        args[3]["expected_manifest_sha256"] = digest("OTHER")
    elif change == "member":
        args[2]["member_id"] = "META_POLICY_V3"
    else:
        key = {
            "book": "book_id",
            "run": "run_id",
            "scope": "scope_sha256",
            "profile": "profile_sha256",
        }[change]
        args[2][key] = digest("OTHER")
    result = prepare(args, rehash=change != "manifest")
    assert result["prepared"] is False and result["reasons"]
    assert_unexecuted(result)


def test_machine_schema_has_exact_four_slots_and_closed_fields():
    from qlab.dynamic_factor.execution_receipts import input_envelope

    schema = json.loads(
        (
            Path(input_envelope.__file__).parent / "schemas/input-manifest.schema.json"
        ).read_bytes()
    )
    manifest = packet()[2]
    validate(manifest, schema)
    assert set(schema["required"]) == MANIFEST_KEYS
    assert set(schema["properties"]["inputs"]["required"]) == set(SLOTS)
    assert set(schema["$defs"]["slot"]["required"]) == SLOT_KEYS
    assert (
        set(schema["$defs"]["slot"]["properties"]["requested_consumer"]["enum"])
        == CONSUMERS
    )
    for role in SLOTS:
        bad = deepcopy(manifest)
        bad["inputs"][role]["returns"] = []
        with pytest.raises(ValidationError):
            validate(bad, schema)


@pytest.mark.parametrize(
    "attack,reason",
    [
        ("control", None),
        ("missing", "input_manifest.source_receipt_identity_required"),
        ("window", "input_manifest.outside_train_warmup_view"),
        ("injection", "input_manifest.schema_or_injection_forbidden"),
        ("B", "B.parent_unknown_or_child_numeric_read_forbidden"),
    ],
)
def test_four_scaffold_classes_and_control_in_fresh_process_before_reads(
    tmp_path, attack, reason
):
    args = packet(blocked=attack == "B")
    if attack == "missing":
        args[2]["inputs"]["raw"]["source_receipt_sha256"] = None
    elif attack == "window":
        args[2]["inputs"]["raw"]["requested_dates"] = ["2099-01-01"]
    elif attack == "injection":
        args[2]["returns"] = [0]
    elif attack == "B":
        args[2]["inputs"]["raw"]["symbols"].append(args[1]["guard"]["B"][0])
    args[3]["expected_manifest_sha256"] = digest(args[2])
    for role in SLOTS:
        (tmp_path / (role + ".json")).write_text("CANARY: MUST NOT BE READ")
    package = str(Path(__file__).resolve().parents[2])
    script = """import json,sys
sys.path.insert(0, PACKAGE)
from qlab.dynamic_factor.execution_receipts.input_envelope import prepare_input_envelope
calls=[]
def audit(event,args):
    if event=='open' and str(args[0]).split('/')[-1] in ('raw.json','rights.json','adv.json','cash.json'):
        calls.append(str(args[0])); raise RuntimeError('NUMERIC_INPUT_OPENED')
    if event.startswith(('socket.','subprocess.','os.exec','os.spawn')):
        raise RuntimeError('PROCESS_OR_NETWORK_USED')
sys.addaudithook(audit)
p,s,m,e=json.loads(sys.stdin.read())
r=prepare_input_envelope(p,s,m,**e)
print(json.dumps(dict(result=r,observed_numeric_reads=calls,worker_roles=[])))
""".replace("PACKAGE", repr(package))
    child = subprocess.run(
        [sys.executable, "-B", "-I", "-S", "-c", script],
        input=json.dumps(args),
        cwd=tmp_path,
        env={},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    value = json.loads(child.stdout)
    assert value["observed_numeric_reads"] == value["worker_roles"] == []
    result = value["result"]
    assert result["prepared"] is (attack == "control")
    assert result["reasons"] == ([] if reason is None else [reason])
    assert_unexecuted(result)

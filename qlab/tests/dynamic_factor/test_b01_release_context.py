"""Private host-adapter mechanism tests; never a real A or runtime approval."""

from copy import copy, deepcopy
import json
from pathlib import Path
import pickle
import subprocess
import sys

import pytest

from qlab.dynamic_factor import b_release_context as b
from qlab.dynamic_factor import noncash_v3, scope_proof
from qlab.dynamic_factor.contract import code_sha, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_cash import CashProof


ORIGINALS = Path(__file__).parent / "fixtures/b-release/B01-originals"


@pytest.fixture
def private_host_source(monkeypatch):
    """Explicit private source adapter. No production authority is installed."""
    policy = load_conventions()

    def read(name):
        return (ORIGINALS / name).read_bytes()

    r_raw = read("EVO938-B-runtime-release-R-v1.0.0.json")
    p_raw = read("EVO938-B-runtime-release-P-v1.0.0.json")
    r, p = json.loads(r_raw), json.loads(p_raw)
    publication = dict(
        comment_id=b.PUBLICATION_COMMENT,
        revision=1,
        created_at="2026-11-02T20:01:45Z",
        R=dict(sha256=sha256(r_raw), platform=p["actual_core_attachment"]),
        P=dict(sha256=sha256(p_raw)),
    )
    comment = json.loads(read("annotation-platform-readback.json"))
    annotation = dict(
        issue_id=b.ISSUE,
        comment_id=comment["id"],
        revision=comment["revision"],
        content=comment["content"],
    )
    # TEST ONLY time evidence, explicitly not a real reception clock/approval.
    time = dict(
        context_version="PRIVATE_TEST_ONLY_v1",
        receiver_id="PRIVATE_TEST_ONLY_receiver",
        accepted_at="2026-11-07T20:00:00Z",
    )
    inputs = {}
    for entry in r["accepted_input_manifest"]["entries"][:-1]:
        item = entry["accepted_receipt"]
        inputs[item["file"]] = read(item["file"])
    for key in ("catalog_csv", "CMI_guard"):
        name = r["accepted_input_manifest"]["entries"][0][key]["file"]
        inputs[name] = read(name)
    source = dict(
        r_raw=r_raw,
        p_raw=p_raw,
        adoption_raw=read("EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json"),
        original_inputs=inputs,
        publication_raw=b._canonical(publication),
        annotation_raw=b._canonical(annotation),
        acceptance_time_evidence_raw=b._canonical(time),
        **time,
        implementation_id="PRIVATE_TEST_ONLY_implementation",
        expected_policy_binding_bytes=b._canonical(b._policy_binding(policy)),
        expected_publication_bytes=b._canonical(publication),
        expected_annotation_bytes=b._canonical(annotation),
        expected_acceptance_time_bytes=b._canonical(time),
        run_time_binding_bytes=b._canonical(
            dict(
                mode="forward",
                first_performance_at="2026-11-10T14:30:00Z",
                signal_close="2026-11-09T21:00:00Z",
            )
        ),
    )
    keys = [
        "r_raw",
        "p_raw",
        "adoption_raw",
        "publication_raw",
        "annotation_raw",
        "acceptance_time_evidence_raw",
    ]
    source["expected_sha256"] = {k: sha256(source[k]) for k in keys}
    source["expected_sha256"].update(
        implementation_sha256=code_sha(b.receive_release_context),
        original_inputs={k: sha256(v) for k, v in inputs.items()},
    )
    monkeypatch.setattr(b, "_read_trusted_release", lambda: source)
    return source, policy


def request(context):
    return dict(
        catalog=json.loads(context.r_raw)["catalog"],
        synthetic=False,
        mode="forward",
        sealed_at="2026-11-07T20:00:00Z",
        signal_close="2026-11-09T21:00:00Z",
        first_performance_at="2026-11-10T14:30:00Z",
        release_binding=dict(h_r=context.h_r, h_a=context.h_a, h_d=context.h_d),
    )


def test_no_request_or_serialization_can_mint_host_capability():
    with pytest.raises(TypeError, match="trust_binding_missing"):
        b.ReleaseContext(approved=True)
    with pytest.raises(ValueError, match="trust_binding_missing"):
        b.receive_release_context(policy=load_conventions())
    forged = object.__new__(b.ReleaseContext)
    with pytest.raises(ValueError, match="trust_binding_missing"):
        b.check_release_context(forged, policy=None, request={})


@pytest.mark.parametrize(
    "context,reason",
    [(None, "required"), ({}, "type_mismatch"), (object(), "type_mismatch")],
)
def test_exact_type_precedes_all_other_checks(context, reason):
    with pytest.raises(ValueError, match="^B.release_context_" + reason + "$"):
        b.check_release_context(context, policy=None, request={})


def test_private_mechanism_fixed_A_rechecks_originals_and_returns_contract_bytes(
    private_host_source,
):
    source, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    raw = b.check_release_context(context, policy=policy, request=request(context))
    assert CashProof.binding_bytes(json.loads(raw)) == raw
    assert noncash_v3.ReleaseContext is b.ReleaseContext
    assert noncash_v3.check_release_context is b.check_release_context
    assert copy(context) is deepcopy(context) is context
    with pytest.raises(AttributeError):
        context.h_a = "0" * 64
    with pytest.raises(TypeError):
        pickle.dumps(context)
    restored = b.receive_release_context(policy=policy, a_raw=context.a_raw)
    assert restored.a_raw == context.a_raw
    assert (
        b.check_release_context(
            restored,
            policy=policy,
            request=request(context),
            expected_release_identity_bytes=raw,
        )
        == raw
    )
    assert json.loads(context.a_raw)["runtime_consumable"] is False
    source["original_inputs"]["EVO883-S1-BRKB-field-receipt.json"] += b" "
    with pytest.raises(ValueError, match="release_mismatch"):
        b.check_release_context(context, policy=policy, request=request(context))


@pytest.mark.parametrize("key", ["r_raw", "p_raw", "adoption_raw", "publication_raw"])
def test_untrusted_release_self_hash_does_not_replace_host_expected(
    private_host_source, key
):
    source, policy = private_host_source
    obj = json.loads(source[key])
    obj["SELF_ASSERTED_APPROVED"] = True
    source[key] = b._canonical(obj)
    with pytest.raises(ValueError, match="release_mismatch"):
        b.receive_release_context(policy=policy)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":1e999}',
        b"{}\n",
        b"\xef\xbb\xbf{}",
    ],
)
def test_strict_c_encoding_rejects_invalid_or_noncanonical(raw):
    with pytest.raises(ValueError, match="encoding_invalid"):
        b._json(raw, canonical=True)


def test_expected_identity_precedes_request_scope_and_cannot_reissue_A(
    private_host_source,
):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    value = json.loads(
        b.check_release_context(context, policy=policy, request=request(context))
    )
    value["identity"]["context_version"] = "OTHER_VERSION"
    value["identity_sha256"] = sha256(b._canonical(value["identity"]))
    with pytest.raises(ValueError, match="persistent_identity_mismatch"):
        b.check_release_context(
            context,
            policy=policy,
            request={},
            expected_release_identity_bytes=b._canonical(value),
        )
    with pytest.raises(ValueError, match="acceptance_mismatch"):
        b.receive_release_context(
            policy=policy, a_raw=b._canonical({"schema": "forged"})
        )


def test_C05_A_mismatch_precedes_missing_annotation_on_reload(private_host_source):
    source, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    wrong = json.loads(context.a_raw)
    wrong["context_version"] = "OTHER_VERSION"
    source["annotation_raw"] = b"{}"
    with pytest.raises(ValueError, match="^B.release_context_acceptance_mismatch$"):
        b.receive_release_context(policy=policy, a_raw=b._canonical(wrong))
    with pytest.raises(
        ValueError, match="^B.release_context_annotation_missing_or_invalid$"
    ):
        b.receive_release_context(policy=policy, a_raw=context.a_raw)


@pytest.mark.parametrize(
    "change", ["mode", "synthetic", "catalog", "h_a", "signal_close", "sealed_at"]
)
def test_request_cannot_expand_host_accepted_domain(private_host_source, change):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    value = request(context)
    if change == "h_a":
        value["release_binding"]["h_a"] = "0" * 64
    else:
        value[change] = {
            "mode": "history",
            "synthetic": True,
            "catalog": {},
            "signal_close": "2026-11-10T21:00:00Z",
            "sealed_at": "2026-11-02T20:00:00Z",
        }[change]
    with pytest.raises(ValueError, match="scope_mismatch"):
        b.check_release_context(context, policy=policy, request=value)


def test_exact_noncash_import_edge_has_no_fourth_module_grant():
    assert "b_release_context" in scope_proof.IMPORTS["noncash_v3"]
    assert "UNAPPROVED_MODULE" not in scope_proof.IMPORTS["noncash_v3"]


def test_formal_guard_without_context_cannot_fall_back_to_diagnostic(
    private_host_source,
):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    guard = dict(schema="EVO883.BRuntimeGuard/v1", request=request(context))
    assert CashProof.release_requested(guard, None, None) is True
    with pytest.raises(ValueError, match="^B.release_context_required$"):
        CashProof.release_guard(guard, policy, None, None)


def test_diagnostic_guard_with_context_is_not_accepted_as_formal(
    private_host_source,
):
    # Safety outcome only. The request-classification conflict in the existing
    # bridge is recorded separately; this is not proof of B02 classification.
    from v3_test_helpers import synthetic_guard

    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    guard = synthetic_guard(policy)
    before = deepcopy(guard)
    with pytest.raises(ValueError, match="^B.release_context_scope_mismatch$"):
        CashProof.release_guard(guard, policy, context, None)
    assert guard == before


def test_exact_replay_source_pin_does_not_allow_unregistered_source(tmp_path):
    from qlab.dynamic_factor.execution_receipts.replay_files import REPLAY_FIXED_FILES

    root = Path(b.__file__).parent
    registered = root / "b_release_context.py"
    assert REPLAY_FIXED_FILES["b_release_context.py"] == sha256(registered.read_bytes())
    unregistered = tmp_path / "unregistered_source.py"
    unregistered.write_text("# this source has no read grant\n", encoding="utf-8")
    code = (
        "import json,sys;from pathlib import Path;"
        "from qlab.dynamic_factor.execution_receipts.replay_guard import install;"
        "p=Path(sys.argv[1]);q=Path(sys.argv[3]);"
        "install({str(p):sys.argv[2]});p.read_bytes();\n"
        "try:q.read_bytes()\n"
        "except ValueError as e:print(json.dumps({'reason':str(e)}))\n"
        "else:raise AssertionError('unregistered source was read')\n"
    )
    run = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            code,
            str(registered),
            REPLAY_FIXED_FILES["b_release_context.py"],
            str(unregistered),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["reason"] == (
        "reference.replay_input_or_write_forbidden:" + str(unregistered)
    )

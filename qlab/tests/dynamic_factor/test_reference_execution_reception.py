"""C09 pre-execution reception; private authority fixtures are counterfactual."""

import json
import pytest
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.reference_v3_evidence import execution_readiness
from test_execution_input_envelope import packet
from test_execution_n_binding import private_bound_source


def readiness_args(tmp_path, monkeypatch, *, complete=True):
    n, _ = private_bound_source(tmp_path, monkeypatch, complete=complete)
    # A genuinely bound original private attempt, not a caller numeric N.
    trace = next(t for t in n["traces"] if t["member_id"] == "CREF-F1-L020")
    profile, scope, manifest, expected = packet(blocked=True)
    manifest["run_id"] = trace["run_id"]
    expected["run_id"] = trace["run_id"]
    expected["expected_manifest_sha256"] = digest(manifest)
    n["stage_mapping"]["run_id"] = trace["run_id"]
    return profile, scope, manifest, expected, n


def test_C09_all_preexecution_metadata_and_private_N_leave_only_external_gates(
    tmp_path, monkeypatch, record_property
):
    profile, scope, manifest, expected, n = readiness_args(tmp_path, monkeypatch)
    out = execution_readiness(profile, scope, manifest, expected=expected, **n)
    assert out["P7_reader_receipt"]["reasons"] == []
    assert out["formal_N"] == 7  # private host reconciliation, never 1313/design 4
    assert out["execution_proof"]["schema"] == "EVO884.ReferenceExecutionScope/v1"
    assert out["reasons"] == ["reference.runtime_B_release_and_actual_proofs_missing"]
    assert out["remaining_external_gates"] == [
        dict(
            gate="B_RUNTIME_RELEASE",
            reason="reference.runtime_B_release_and_actual_proofs_missing",
            accepted=False,
        ),
        dict(
            gate="SRC_AUTH_RECEPTION",
            reason="reference.SRC_AUTH_source_and_permission_reception_required",
            accepted=False,
        ),
    ]
    assert out["returns"] is out["sr"] is out["P4_actual_run"] is None
    assert (
        out["reader_calls"] == out["worker_calls"] == 0 and out["accessed_roles"] == []
    )
    assert out["complete"] is out["runtime_consumable"] is out["certifiable"] is False
    record_property("C09_external_gates_actual", json.dumps(out, sort_keys=True))


@pytest.mark.parametrize(
    "attack", ["N_incomplete", "fake_B", "run", "stage", "manifest", "B_read"]
)
def test_C09_metadata_or_formal_N_cannot_be_borrowed_before_B_gate(
    tmp_path, monkeypatch, attack
):
    profile, scope, manifest, expected, n = readiness_args(
        tmp_path, monkeypatch, complete=attack != "N_incomplete"
    )
    if attack == "fake_B":
        scope["B_catalog_release_sha256"] = digest("SYNTHETIC CLAIM NOT A RELEASE")
        scope["scope_sha256"] = digest(
            {k: v for k, v in scope.items() if k != "scope_sha256"}
        )
        expected["expected_scope_sha256"] = manifest["scope_sha256"] = scope[
            "scope_sha256"
        ]
    elif attack == "run":
        n["expected_run_ids"] = ["OTHER RUN"]
    elif attack == "stage":
        n["stage_mapping"]["stage"] = "actual_forward_observation"
    elif attack == "manifest":
        manifest["inputs"]["raw"]["file"] = "../other.json"
    elif attack == "B_read":
        manifest["inputs"]["raw"]["symbols"] = [scope["guard"]["B"][0]]
    expected["expected_manifest_sha256"] = digest(manifest)
    out = execution_readiness(profile, scope, manifest, expected=expected, **n)
    assert out["reasons"] and out["reasons"] != [
        "reference.runtime_B_release_and_actual_proofs_missing"
    ]
    assert out["remaining_external_gates"] == []
    assert out["returns"] is None and out["reader_calls"] == out["worker_calls"] == 0

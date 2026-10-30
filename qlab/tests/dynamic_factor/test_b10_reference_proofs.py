from copy import deepcopy

import pytest

from b10_reference_helpers import PROOF_CASES, exercise, mutate_proof, wire_fixture


@pytest.fixture(scope="module")
def wire(tmp_path_factory):
    root = tmp_path_factory.mktemp("b10-proofs") / "inputs"
    return root, wire_fixture(root)


@pytest.mark.parametrize("case", PROOF_CASES)
def test_resigned_nested_proof_refuses_real_compiler_and_worker_before_read(wire, case):
    root, original = wire
    request = deepcopy(original)
    mutate_proof(request, case)
    observed = exercise(root, request, with_proofs=True)
    for side in ("host", "worker"):
        report = observed[side]
        assert report["complete"] is (case == "clean")
        if case != "clean":
            assert report["reader_calls"] == 0
            assert report["accessed_roles"] == []
            assert report["reason"]
    if case == "clean":
        assert observed["worker"]["accessed_roles"] == ["benchmark", "panel", "profile"]


def test_host_and_worker_import_the_identical_pure_validator():
    from qlab.dynamic_factor import reference_noncash, reference_v3_scope
    from qlab.dynamic_factor.reference_validation import validate_packet_document

    assert reference_noncash.validate_packet_document is validate_packet_document
    assert reference_v3_scope.validate_packet_document is validate_packet_document

from qlab.dynamic_factor.invariance_harness import probe
from qlab.dynamic_factor.conventions import load_conventions


def test_replacing_only_VTI_bytes_changes_B2_binding_but_not_seven_role_outputs(
    tmp_path,
):
    r = probe(tmp_path, load_conventions())
    assert r["output_sha256_before"] == r["output_sha256_after"]
    assert len(r["output_sha256_before"]) == 7
    assert r["VTI_source_sha256"][0] != r["VTI_source_sha256"][1]
    assert r["B2_receipt_input_sha256"][0] != r["B2_receipt_input_sha256"][1]
    assert r["actual_reference_returns"] is r["actual_reference_run_id"] is None

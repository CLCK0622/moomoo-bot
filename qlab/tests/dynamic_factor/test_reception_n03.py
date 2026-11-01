from copy import deepcopy
import json

import pytest

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor.authority_install_receipt import (
    verify_installation_readonly,
    summarize_validated_receipt,
)
from qlab.dynamic_factor.reception_schema import validate
from authority_stage1_helpers import raw_json
from installation_host_helpers import installation_host


def receive(context, source, raw=None, module=None):
    return verify_installation_readonly(
        host_context=context,
        runtime_module_path=source["module_path"] if module is None else module,
        installation_receipt_bytes=source["installation_receipt_bytes"]
        if raw is None
        else raw,
        published_anchor_bytes=source["published_anchor_bytes"],
        acceptance_bytes=source["installation_acceptance_bytes"],
    )


def test_twelve_groups_and_typed_V2_are_one_new_root(tmp_path, monkeypatch):
    context, source, document = installation_host(
        tmp_path, monkeypatch, prefix_stub=False
    )
    result = receive(context, source)
    assert result["accepted"] is True, result["reasons"]
    validate(result, "N-03.v31.schema.json")
    assert set(result["details"]["installation_fields"]) == set(document)
    assert type(result["details"]["installation_fields"]["anchor"]["V2"]) is dict
    assert (
        result["details"]["verified_summary"]["anchor"]["checks"]["V2"]["status"]
        == "PASS"
    )
    assert result["details"]["complete_N"] is None
    assert host.installed_snapshot(context) is not None


@pytest.mark.parametrize(
    "group", ["identity", "anchor", "readback"], ids=["S02", "S05", "S09"]
)
def test_caller_all_PASS_cannot_override_actual_trusted_source_FAIL(
    tmp_path, monkeypatch, group, record_property
):
    context, source, document = installation_host(
        tmp_path, monkeypatch, source_fail=group, prefix_stub=False
    )
    before = len(host._SNAPSHOTS)
    result = receive(context, source)
    record_property("N03_source_FAIL_report", json.dumps(result, sort_keys=True))
    assert result["accepted"] is False
    assert result["details"]["trusted_validation"]["status"] == "FAIL"
    assert result["details"]["verified_summary"][group]["status"] == "FAIL"
    assert any("trusted_source_failed" in reason for reason in result["reasons"])
    assert len(host._SNAPSHOTS) == before
    assert all(
        result["observations"][key] == 0
        for key in (
            "formal_N_projection",
            "economic_reader",
            "worker_read_inputs",
            "authority_writes",
            "budget_api",
        )
    )


@pytest.mark.parametrize(
    "variant",
    ["old_root", "boolean_V2", "missing_group", "caller_context", "wrong_module"],
)
def test_old_mixed_missing_or_untrusted_objects_refuse(tmp_path, monkeypatch, variant):
    context, source, document = installation_host(
        tmp_path, monkeypatch, prefix_stub=False
    )
    changed = deepcopy(document)
    module = None
    if variant == "old_root":
        changed = {
            "schema": "PROPOSAL.EVO884.InstalledAuthorityReceipt/v2",
            "accepted": True,
        }
    elif variant == "boolean_V2":
        changed["anchor"]["V2"] = True
    elif variant == "missing_group":
        del changed["approved_release"]
    elif variant == "caller_context":
        context = {"accepted": True, "source_verified": True}
    elif variant == "wrong_module":
        module = "/other/authority_ledger.py"
    result = receive(context, source, raw_json(changed), module)
    assert not result["accepted"]
    assert result["reasons"]
    assert result["binding_sha256"] is None
    assert result["observations"]["retired_schema_dispatches"] == 0
    assert result["observations"]["unexpected_typeerror"] == 0


def test_json_summary_cannot_be_adapted_into_trusted_result():
    with pytest.raises(ValueError, match="trusted_validation_required"):
        summarize_validated_receipt(
            {"status": "PASS"}, trusted_install_context={"accepted": True}
        )

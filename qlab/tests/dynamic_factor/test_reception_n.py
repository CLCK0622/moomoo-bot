import pytest

from qlab.dynamic_factor.arm_n import MISSING
from qlab.dynamic_factor.reception_v2 import ENTRYPOINTS, receive_arm_n, bind_formal_n
from qlab.dynamic_factor.reception_schema import validate
from authority_host_helpers import private_host


def test_identity_acceptance_does_not_convert_1313_or_101_unknowns(
    tmp_path, monkeypatch
):
    context, snapshot, pin, source = private_host(tmp_path, monkeypatch)
    result = receive_arm_n(
        source["approval_bytes"],
        source["projection_bytes"],
        host_context=context,
        installed_snapshot=snapshot,
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    validate(result, "N-01.v3.schema.json")
    assert result["accepted"] is True
    assert result["details"]["complete_N"] is None
    assert result["details"]["n_evaluated_unknown_count"] == 101
    assert len(result["details"]["unknown_attempt_refs"]) == 101
    bound = bind_formal_n(
        host_context=context,
        request_metrics={"self_report_n": 9999},
        installed_snapshot=snapshot,
        entrypoint="statistics.dsr_eval_arm",
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    assert not bound["accepted"] and bound["details"]["gate_N"] is None


@pytest.mark.parametrize("entrypoint", sorted(ENTRYPOINTS))
def test_one_binder_for_every_original_dispatch(tmp_path, monkeypatch, entrypoint):
    context, snapshot, pin, source = private_host(tmp_path, monkeypatch, complete=True)
    result = bind_formal_n(
        host_context=context,
        request_metrics={"self_report_n": 9999},
        installed_snapshot=snapshot,
        entrypoint=entrypoint,
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    assert result["accepted"] is True, result["reasons"]
    assert result["details"]["gate_N"] == 7
    child = result["details"]["n_acceptance"]
    assert child["details"]["N_rows"][1]["value"] == 101
    assert child["details"]["t1_replay"]["unknown_rows"][0]["n_evaluated"] is None
    assert child["input_identities"] == result["input_identities"]


@pytest.mark.parametrize("tag", [MISSING, None, "OTHER", 0])
def test_bad_labels_never_consume_projection(tmp_path, monkeypatch, tag):
    context, snapshot, pin, source = private_host(tmp_path, monkeypatch, complete=True)
    result = bind_formal_n(
        host_context=context,
        request_metrics={},
        installed_snapshot=snapshot,
        entrypoint="statistics.dsr_eval_arm",
        run_pin=pin,
        arm_tag=tag,
    )
    assert not result["accepted"]
    assert result["reasons"] == ["arm_n.arm_tag_missing_or_invalid"]
    assert result["observations"]["formal_projection_consumption"] == 0


def test_conflict_and_caller_ledger_are_rejected_without_method_call(
    tmp_path, monkeypatch
):
    context, snapshot, pin, source = private_host(tmp_path, monkeypatch, complete=True)

    class CallerLedger:
        def arm_readout(self, *args):
            raise AssertionError("caller method must not be invoked")

    for metrics, ledger, reason in [
        ({"arm_tag": "EVO896_LLMCLI"}, None, "arm_n.request_arm_tag_conflict"),
        ({}, CallerLedger(), "reception.N_caller_ledger_not_authoritative"),
    ]:
        result = bind_formal_n(
            host_context=context,
            request_metrics=metrics,
            installed_snapshot=snapshot,
            entrypoint="statistics.dsr_eval_arm",
            run_pin=pin,
            arm_tag="EVO883_FACTOR",
            candidate_ledger=ledger,
        )
        assert result["reasons"] == [reason]
        assert result["observations"]["formal_projection_consumption"] == 0


def test_self_signed_projection_and_snapshot_json_cannot_mint_trust(
    tmp_path, monkeypatch
):
    context, snapshot, pin, source = private_host(tmp_path, monkeypatch, complete=True)
    for approval, supplied in [
        (b'{"accepted":true}', snapshot),
        (source["approval_bytes"], {"accepted": True}),
    ]:
        result = receive_arm_n(
            approval,
            source["projection_bytes"],
            host_context=context,
            installed_snapshot=supplied,
            run_pin=pin,
            arm_tag="EVO883_FACTOR",
        )
        assert not result["accepted"]
        assert result["details"]["complete_N"] is None


def test_file_drift_and_wrong_arm_pin_stop_before_projection(tmp_path, monkeypatch):
    context, snapshot, pin, source = private_host(tmp_path, monkeypatch, complete=True)
    from pathlib import Path

    Path(source["chain_path"]).write_bytes(source["chain_raw"] + b" ")
    result = bind_formal_n(
        host_context=context,
        request_metrics={},
        installed_snapshot=snapshot,
        entrypoint="run_train_pipeline",
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    assert result["reasons"] == ["ledger.observed_object_drift"]
    assert result["observations"]["formal_projection_consumption"] == 0

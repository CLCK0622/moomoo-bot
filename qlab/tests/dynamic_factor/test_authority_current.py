"""Current opaque receivers and historical fixtures cannot substitute for each other."""

from copy import deepcopy
from pathlib import Path

import pytest

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor import authority_ledger as ledger
from qlab.dynamic_factor import statistics, pipeline
from qlab.dynamic_factor.authority_release import read_approved_release
from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.scope_harness import continuity_fixture
from qlab.dynamic_factor.conventions import load_conventions
from installation_host_helpers import installation_host
from test_reception_n03 import receive


def current(tmp_path, monkeypatch, *, complete=False):
    context, source, document = installation_host(
        tmp_path, monkeypatch, prefix_stub=False, complete=complete
    )
    assert receive(context, source)["accepted"]
    snapshot = host.installed_snapshot(context)
    pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id="CURRENT-PRIVATE")
    return context, snapshot, pin, source


def test_current_loader_retains_full_anchor_with_real_shared_V5(tmp_path, monkeypatch):
    context, snapshot, pin, source = current(tmp_path, monkeypatch)
    # Approved-release observation comes from the host, not a request flag.
    host._HOSTS[context]["release_verified"] = True
    actual = read_approved_release(host_context=context)
    assert actual == source["anchor"]
    assert actual["ledger_file_sha256"]
    Path(source["chain_path"]).write_bytes(source["chain_raw"] + b"\n")
    with pytest.raises(ValueError, match="drift"):
        read_approved_release(host_context=context)


def test_missing_current_installation_never_loads_v4(monkeypatch):
    def forbidden():
        raise AssertionError("historical fallback")

    from qlab.dynamic_factor import historical_authority

    monkeypatch.setattr(historical_authority, "historical_v4_witness", forbidden)
    with pytest.raises(ValueError, match="trusted_project_installation_required"):
        ledger.latest_external_witness()


@pytest.mark.parametrize("supplied", [None, {"accepted": True}])
def test_current_continuity_keeps_grid_and_all_declarations_before_refusal(supplied):
    policy = load_conventions()
    request = continuity_fixture(policy)
    request["folds"].append(deepcopy(request["folds"][0]))
    original = deepcopy(request)
    report = continuous_path_check(
        request, conventions=policy, installed_snapshot=supplied
    )
    assert not report["metrics"]["state_receipt_grid_complete"]
    assert len(report["metrics"]["folds"]) == 77
    assert all(row["nav"] is None for row in report["metrics"]["folds"])
    assert [
        row["raw_declaration"] for row in report["metrics"]["submitted_declarations"]
    ] == request["folds"]
    assert report["reasons"] == ["ledger.trusted_project_installation_required"]
    assert request == original


def test_current_continuity_uses_bound_1313_high_water_and_detects_drift(
    tmp_path, monkeypatch
):
    context, snapshot, pin, source = current(tmp_path, monkeypatch)
    policy = load_conventions()
    request = continuity_fixture(policy)
    report = continuous_path_check(
        request, conventions=policy, installed_snapshot=snapshot
    )
    assert report["reasons"] == ["ledger.N_receipt_initial_mismatch"]
    assert len(report["metrics"]["submitted_declarations"]) == 77
    Path(source["witness_path"]).write_bytes(b"{}\n")
    report = continuous_path_check(
        request, conventions=policy, installed_snapshot=snapshot
    )
    assert report["reasons"] == ["ledger.observed_object_drift"]


@pytest.mark.parametrize(
    "entry", ["authority", "attempt", "statistics", "snapshot", "pipeline"]
)
def test_actual_formal_adapters_require_the_registered_same_operation_view(
    tmp_path, monkeypatch, entry
):
    context, snapshot, pin, source = current(tmp_path, monkeypatch, complete=True)
    view = host.host_view(context, snapshot, pin, "EVO883_FACTOR")
    from qlab.dynamic_factor.ledger import AttemptLedger

    calls = {
        "authority": lambda obj: ledger.AuthorityLedger.arm_readout(
            obj, "EVO883_FACTOR"
        ),
        "attempt": lambda obj: AttemptLedger.arm_readout(obj, "EVO883_FACTOR"),
        "statistics": lambda obj: statistics.dsr_eval_arm(
            {"arm_tag": "EVO883_FACTOR"}, obj
        ),
        "snapshot": lambda obj: statistics.arm_snapshot(
            obj, 99999, arm_tag="EVO883_FACTOR"
        ),
        "pipeline": lambda obj: pipeline._n_snapshot(
            obj, 99999, arm_tag="EVO883_FACTOR"
        ),
    }
    output = calls[entry](view)
    metrics = output.get("metrics", output)
    assert metrics["cumulative_n"] == 7
    assert metrics["arm_n"]["global_history"]["recorded_N"] == 1313
    assert metrics["N_rows"][0]["complete_N"] == 7

    # A numerically complete caller object still does not have that capability.
    class Caller:
        def arm_readout(self, *args):
            raise AssertionError("caller method consumed")

    refused = calls[entry](Caller())
    rejected = refused.get("metrics", refused)
    assert rejected["cumulative_n"] is None
    assert refused["reasons"]

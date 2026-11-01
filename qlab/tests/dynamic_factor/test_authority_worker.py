"""Real isolated worker must refuse a drifted host binding before read_inputs."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor import reference_boundary as boundary
from b10_reference_helpers import wire_fixture
from installation_host_helpers import installation_host
from test_reception_n03 import receive


@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "other_chain",
        "other_run",
        "other_deployment",
        "source_drift",
        "clean",
    ],
)
def test_bound_worker_real_subprocess_precedes_every_data_reader(
    tmp_path, monkeypatch, attack, record_property
):
    inputs = tmp_path / "inputs"
    request = wire_fixture(inputs, verified=49)
    authority = tmp_path / "authority"
    authority.mkdir()
    context, source, _ = installation_host(authority, monkeypatch, prefix_stub=False)
    assert receive(context, source)["accepted"]
    snapshot = host.installed_snapshot(context)
    pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id="WORKER-PRIVATE")
    actual_run = boundary.subprocess.run
    child_codes = []

    def subprocess_attack(*args, **kwargs):
        wire = json.loads(kwargs["input"])
        if attack == "missing":
            del wire["authority_binding"]
        elif attack == "other_chain":
            wire["authority_binding"]["chain_sha256"] = "0" * 64
        elif attack in ("other_run", "other_deployment"):
            key = "run_pin_sha256" if attack == "other_run" else "host_context_sha256"
            wire["authority_binding"][key] = "0" * 64
        elif attack == "source_drift":
            key = next(iter(wire["authority_binding"]["source_manifest"]))
            wire["authority_binding"]["source_manifest"][key] = "0" * 64
        kwargs["input"] = json.dumps(wire) + "\n"
        result = actual_run(*args, **kwargs)
        child_codes.append(result.returncode)
        return result

    monkeypatch.setattr(boundary.subprocess, "run", subprocess_attack)
    original = deepcopy(request)
    result = boundary.run_isolated(
        inputs,
        request,
        host_context=context,
        installed_snapshot=snapshot,
        run_pin=pin,
        arm_tag="EVO883_FACTOR",
    )
    record_property("worker_report", json.dumps(result, sort_keys=True))
    record_property("child_exit_codes", json.dumps(child_codes))
    assert request == original
    assert child_codes == [2]
    assert result["returns"] is result["sr"] is None
    if attack == "clean":
        assert result["complete"] is True
        assert result["reader_calls"] > 0
        assert result["accessed_roles"] == ["benchmark", "panel", "profile"]
    else:
        assert result["complete"] is False
        assert result["reader_calls"] == 0 and result["accessed_roles"] == []
        assert result["reason"] == "ledger.worker_authority_unbound"


def test_host_discards_worker_result_if_witness_drifts_during_subprocess(
    tmp_path, monkeypatch
):
    inputs = tmp_path / "inputs"
    request = wire_fixture(inputs, verified=49)
    authority = tmp_path / "authority"
    authority.mkdir()
    context, source, _ = installation_host(authority, monkeypatch, prefix_stub=False)
    assert receive(context, source)["accepted"]
    snapshot = host.installed_snapshot(context)
    pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id="POST-CHILD-PRIVATE")
    actual_run = boundary.subprocess.run

    def drift(*args, **kwargs):
        result = actual_run(*args, **kwargs)
        Path(source["witness_path"]).write_bytes(b"{}\n")
        return result

    monkeypatch.setattr(boundary.subprocess, "run", drift)
    with pytest.raises(ValueError, match="observed_object_drift"):
        boundary.run_isolated(
            inputs,
            request,
            host_context=context,
            installed_snapshot=snapshot,
            run_pin=pin,
            arm_tag="EVO883_FACTOR",
        )

from copy import deepcopy

import pytest

from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.scope_harness import continuity_fixture
from test_v2_state import synthetic_state


@pytest.mark.parametrize("failure", ["quarantined_cash_ancestor", "unknown_container"])
def test_pre_grid_quarantine_failure_only_R2_preserves_all_four_state_classes(
    monkeypatch, failure
):
    request = continuity_fixture(load_conventions())
    for row in request["folds"]:
        row["input_state"] = synthetic_state()
        row["output_state"] = deepcopy(row["input_state"])
        row["inventory"] = deepcopy(row["input_state"]["inventory"])
        for k in ("input_state", "output_state"):
            row[k + "_sha256"] = digest(row[k])
    if failure == "quarantined_cash_ancestor":
        request["dependency_nodes"] = [
            dict(id="cash-source", field="cash", symbol="B", parents=[], value=100)
        ]
    else:
        request["unregistered"] = {"lineage": []}
    before = deepcopy(request)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "state validation must follow the upstream quarantine check"
        )

    monkeypatch.setattr(
        "qlab.dynamic_factor.state_v2.state_transition_check", forbidden
    )
    report = continuous_path_check(request)
    assert request == before and not report["ok"]
    assert report["metrics"]["R2_stop"]
    assert not report["metrics"]["state_receipt_grid_complete"]
    assert len(report["metrics"]["folds"]) == 77
    for submitted, output in zip(before["folds"], report["metrics"]["folds"]):
        assert output["R2_stop"] and output["status"] == "blocked"
        assert output["nav"] is output["returns"] is output["predictions"] is None
        assert output["last_known_state"] == submitted["input_state"]
        assert output["retained_state_declarations"] == [submitted]
        for field in ("inventory", "rights", "receivables", "cash"):
            assert output["last_known_state"][field] == submitted["input_state"][field]
    assert report["metrics"]["A"] is report["metrics"]["IR"] is None

from copy import deepcopy

import pytest

from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.conventions import load_conventions, FIXTURES
from qlab.dynamic_factor.f3_harness import check_rejection, rejection_request


@pytest.mark.parametrize(
    "case,reason",
    [
        ("early_hard_rejection", "wf.continuous_state_link_mismatch"),
        ("late_hard_rejection", "wf.continuous_state_link_mismatch"),
        ("missing_fold", "wf.all_original_folds_required"),
    ],
)
def test_hard_rejection_preserves_all_submitted_metadata_by_frozen_fold_id(
    case, reason
):
    policy = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    request = rejection_request(policy, case)
    original = deepcopy(request)
    report = check_rejection(request, policy)
    assert report["reasons"] == [reason]
    assert request == original
    # Output metadata must be an independent copy, including nested N/budget.
    report["metrics"]["folds"][-1]["budget_state"]["consumed"] = False
    report["metrics"]["folds"][-1]["N_receipt"]["N_after"] = -1
    assert request == original
    if case == "missing_fold":
        missing = report["metrics"]["folds"][1]
        assert not missing["attempted"] and "N_receipt" not in missing


def test_unchecked_declarations_are_retained_without_normalization_or_acceptance():
    policy = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    request = rejection_request(policy, "early_hard_rejection")
    last = request["folds"][-1]
    last.update(attempted="UNVERIFIED", budget_state={"consumed": None}, N_receipt={})
    report = continuous_path_check(request, conventions=policy)
    out = report["metrics"]["folds"][-1]
    assert out["attempted"] == "UNVERIFIED"
    assert out["budget_state"] == last["budget_state"]
    assert out["N_receipt"] == {}
    assert out["metadata_validation_status"] == "pending"
    assert out["status"] == "blocked" and out["returns"] is None

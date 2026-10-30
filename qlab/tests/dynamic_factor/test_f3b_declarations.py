from copy import deepcopy

import pytest

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.f3b_harness import check_declarations, duplicate_request


@pytest.mark.parametrize("append_retry", [False, True])
def test_duplicate_attempts_and_budget_N_are_retained_in_original_order(append_retry):
    policy = load_conventions()
    request = duplicate_request(policy, append_retry=append_retry)
    original = deepcopy(request)
    report = check_declarations(request, policy)
    assert report["reasons"] == ["wf.all_original_folds_required"]
    grid = report["metrics"]["folds"]
    assert grid[0]["declaration_indices"] == [0, 77 if append_retry else 32]
    # A duplicate has no unambiguous singular attempt/budget/N projection.
    assert (
        grid[0]["attempt_id"] is grid[0]["attempted"] is grid[0]["budget_state"] is None
    )
    assert grid[0]["N_receipt"] is None
    declarations = report["metrics"]["submitted_declarations"]
    same_fold = [
        row for row in declarations if row["fold_id"] == request["folds"][0]["fold_id"]
    ]
    assert [row["attempt_id"] for row in same_fold] == [
        "ORIGINAL_CONSUMED",
        "RETRY_CONSUMED",
    ]
    assert [
        (row["N_receipt"]["N_before"], row["N_receipt"]["N_after"]) for row in same_fold
    ] == [(280, 281), (281, 282)]
    assert request == original
    declarations[0]["N_receipt"]["N_after"] = -1
    declarations[0]["raw_declaration"]["budget_state"]["consumed"] = False
    assert request == original


@pytest.mark.parametrize("extra", [{"fold_id": 999, "attempt_id": "UNKNOWN"}, None])
def test_unknown_fold_or_malformed_row_is_retained_before_shape_validation(extra):
    policy = load_conventions()
    request = duplicate_request(policy, append_retry=True)
    request["folds"].append(extra)
    report = check_declarations(request, policy)
    assert report["metrics"]["submitted_declarations"][-1]["raw_declaration"] == extra

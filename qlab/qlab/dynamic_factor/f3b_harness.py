"""Ordered raw declarations survive duplicate-fold and extra-retry refusals."""

from copy import deepcopy

from .contract import digest
from .continuity import continuous_path_check
from .f3_harness import METADATA
from .scope_harness import continuity_fixture


def duplicate_request(policy, *, append_retry):
    request = continuity_fixture(policy)
    original = deepcopy(request["folds"][0])
    original["attempt_id"] = "ORIGINAL_CONSUMED"
    original["N_receipt"].update(
        attempt_id=original["attempt_id"], N_before=280, N_after=281
    )
    retry = deepcopy(original)
    retry["attempt_id"] = "RETRY_CONSUMED"
    retry["retry_of"] = original["attempt_id"]
    retry["budget_state"]["authorization_sha256"] = digest("SEPARATE_RETRY_BUDGET")
    retry["N_receipt"].update(attempt_id=retry["attempt_id"], N_before=281, N_after=282)
    request["folds"][0] = original
    if append_retry:
        request["folds"].append(retry)
    else:
        # Byte-for-byte field construction from the fifth-batch minimal probe.
        request["folds"][32] = retry
    return request


def check_declarations(request, policy):
    report = continuous_path_check(request, conventions=policy)
    raw = report["metrics"]["submitted_declarations"]
    assert len(raw) == len(request["folds"])
    for index, (before, after) in enumerate(zip(request["folds"], raw)):
        assert after["input_index"] == index
        assert after["raw_declaration"] == before
        assert after["metadata_validation_status"] == "pending"
        if isinstance(before, dict):
            for key in ("fold_id", *METADATA):
                assert after[key] == before.get(key), (index, key)
    grid = report["metrics"]["folds"]
    assert [row["fold_id"] for row in grid] == [
        row["fold_id"] for row in policy.fold_manifest()["folds"]
    ]
    assert not report["ok"] and not report["metrics"]["state_receipt_grid_complete"]
    assert all(
        row["returns"] is row["predictions"] is row["nav"] is None for row in grid
    )
    assert all(
        report["metrics"][key] is None
        for key in ("A", "IR", "interval", "B2", "complete_N", "dsr")
    )
    assert not report["runtime_consumable"] and not report["certifiable"]
    return report


def cases(policy):
    out = []
    for append_retry in (False, True):
        request = duplicate_request(policy, append_retry=append_retry)
        report = check_declarations(request, policy)
        assert report["reasons"] == ["wf.all_original_folds_required"]
        declarations = report["metrics"]["submitted_declarations"]
        assert report["metrics"]["folds"][0]["declaration_indices"] == [
            0,
            77 if append_retry else 32,
        ]
        out.append(
            dict(
                case_id="wf.F3b_"
                + ("appended_retry" if append_retry else "duplicate_and_missing"),
                status="PASS",
                input_rows=len(request["folds"]),
                declarations_retained=len(declarations),
                declarations_sha256=digest(declarations),
                original_and_retry_retained=True,
                all_declarations_pending=True,
                frozen_grid_rows=len(report["metrics"]["folds"]),
                reasons=report["reasons"],
                A=None,
                IR=None,
            )
        )
    return out

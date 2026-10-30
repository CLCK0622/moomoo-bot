"""Synthetic rejection receipts: preserve declarations before checking the grid."""

from .contract import digest
from .continuity import continuous_path_check
from .scope_harness import continuity_fixture


METADATA = ("attempt_id", "attempted", "budget_state", "N_receipt")


def rejection_request(policy, case):
    request = continuity_fixture(policy)
    for i, row in enumerate(request["folds"]):
        row["attempt_id"] = "REVIEWER_RETRY_UNIT_%03d" % i
        row["N_receipt"]["attempt_id"] = row["attempt_id"]
        row["budget_state"] = dict(
            authorization_sha256=digest("B3_REVIEWER_LICENSE_%03d" % i),
            consumed=True,
            seen_result=True,
        )
    if case == "missing_fold":
        request["folds"].pop(1)
    else:
        # Index 31 reproduces the third-batch audit's exact hard rejection.
        index = {"early_hard_rejection": 1, "late_hard_rejection": 31}[case]
        request["folds"][index]["input_state_sha256"] = "9" * 64
    return request


def check_rejection(request, policy):
    report = continuous_path_check(request, conventions=policy)
    outputs = report["metrics"]["folds"]
    supplied = {row["fold_id"]: row for row in request["folds"]}
    assert not report["ok"] and not report["metrics"]["state_receipt_grid_complete"]
    assert [row["fold_id"] for row in outputs] == [
        row["fold_id"] for row in policy.fold_manifest()["folds"]
    ]
    for row in outputs:
        if row["fold_id"] in supplied:
            before = supplied[row["fold_id"]]
            assert {k: row.get(k) for k in METADATA} == {
                k: before.get(k) for k in METADATA
            }, row["fold_id"]
        assert row["returns"] is row["predictions"] is None
        if row["status"] == "blocked":
            assert row["nav"] is None
    # The exact 45-row suffix named in the finding must remain attributable.
    assert len(outputs[32:77]) == 45
    assert all(row["metadata_validation_status"] == "pending" for row in outputs[32:])
    assert all(
        report["metrics"][key] is None
        for key in ("A", "IR", "interval", "B2", "complete_N", "dsr")
    )
    assert not report["runtime_consumable"] and not report["certifiable"]
    return report


def cases(policy):
    receipts = []
    for case in ("early_hard_rejection", "late_hard_rejection", "missing_fold"):
        request = rejection_request(policy, case)
        report = check_rejection(request, policy)
        outputs = report["metrics"]["folds"]
        receipts.append(
            dict(
                case_id="wf.F3_metadata_preserved_" + case,
                status="PASS",
                reasons=report["reasons"],
                folds_retained=len(outputs),
                submitted_receipts_preserved=len(request["folds"]),
                suffix_32_76_receipts_preserved=len(outputs[32:]),
                suffix_metadata_sha256=digest(
                    [{k: row[k] for k in METADATA} for row in outputs[32:]]
                ),
                suffix_metadata_validation_status="pending",
                A=None,
                IR=None,
            )
        )
    return receipts

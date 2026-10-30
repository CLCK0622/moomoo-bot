"""Independent sealed-input preparation entry; never generates returns.

Run as `python -m qlab.dynamic_factor.reference_producer --inputs-root DIR`.
The parent binds the four EVO-892 definitions and the shared train/warmup view.
No result input or evaluator callback is accepted; execution belongs to EVO-886.
"""

import argparse
import hashlib
import json

from .fold_split import train_slice
from .reference_inputs import read_inputs
from .reference_guard import install


def prepare(root, request):
    if set(request) != {"view", "inputs", "profile_binding", "dispatch"}:
        raise ValueError("reference.request_contains_non_train_inputs")
    if (
        hashlib.sha256(
            json.dumps(
                request["profile_binding"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        != "a6e3f48e604b0917a82d69ccf3fef4b7520f4e21043338d7bebf6f2adef0635d"
    ):
        raise ValueError("reference.profile_mismatch")
    view = request["view"]
    if set(view) != {"train", "warmup", "receipt"}:
        raise ValueError("reference.request_contains_non_train_inputs")
    dates = tuple(view["warmup"]) + tuple(view["train"])
    receipt = view["receipt"]
    if (
        len(view["train"]) != receipt["train_days"]
        or len(view["warmup"]) != receipt["warmup_days"]
        or receipt["shared_object_verified"] is not True
        or len(dates) != len(set(dates))
        or list(dates) != sorted(dates)
    ):
        raise ValueError("reference.only_complete_train_warmup_visible")
    for role in ("train", "warmup"):
        raw = "".join(d + "\n" for d in view[role]).encode()
        if hashlib.sha256(raw).hexdigest() != receipt[role + "_calendar_sha256"]:
            raise ValueError("reference.view_hash_mismatch")
    inputs = read_inputs(root, request["inputs"], dates)
    projection_raw = inputs["profile"]["fold_bindings_raw"]
    if (
        hashlib.sha256(projection_raw.encode()).hexdigest()
        != "8c40536cf6cc1780a61081548c5935256e2080e50e82c7c2953b051901ea0514"
    ):
        raise ValueError("reference.frozen_fold_projection_mismatch")
    projection = next(
        f
        for f in json.loads(projection_raw)["folds"]
        if str(f["fold_id"]) == str(receipt["fold_id"])
    )
    if (
        receipt["train_days"] != projection["train_session_count"]
        or receipt["warmup_days"] != projection["warmup_sessions"]
        or any(
            receipt[k + "_calendar_sha256"] != projection[k + "_calendar_sha256"]
            for k in ("train", "warmup")
        )
    ):
        raise ValueError("reference.only_complete_train_warmup_visible")
    for key, value in request["profile_binding"].items():
        if inputs["profile"].get(key) != value:
            raise ValueError("reference.profile_mismatch")
    # Already bound to exact registered definitions by the parent. No evaluator,
    # parameter search, result input, or callback can be supplied to this entry.
    expected = {"CREF-F1-L020", "CREF-F3-L020", "MREF-F2-L020", "MREF-F4-L020"}
    if set(request["dispatch"]) != expected:
        raise ValueError("reference.member_not_registered_or_incomplete")
    if (
        hashlib.sha256(
            json.dumps(
                request["dispatch"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        != "ae78c7ee255560a65f8e15bf428b979c979bca0e80ebfd1b92a885da7486ecbc"
    ):
        raise ValueError("reference.registered_dispatch_mismatch")
    for member, spec in request["dispatch"].items():
        if (
            spec["member_id"] != member
            or spec["execution_profile_id"] != "CANDIDATE_PROBE_V03"
            or spec["execution_contract"]["parameter_search"] is not False
        ):
            raise ValueError("reference.execution_role_mismatch")
    payload = json.dumps(
        inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return {
        "schema": "reference.producer/v1.0.0",
        "train_dates": list(view["train"]),
        "warmup_dates": list(view["warmup"]),
        "train_input_sha256": hashlib.sha256(payload).hexdigest(),
        "train_rows": len(train_slice(inputs["panel"]["rows"], view["train"])),
        "view_receipt": receipt,
        "prepared_members": sorted(request["dispatch"]),
        "returns": None,
        "sr": None,
        "reason": "reference_runtime_evidence_pending_EVO886_EVO891",
        "runtime_consumable": False,
        "certifiable": False,
        **request["profile_binding"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-root", required=True)
    args = parser.parse_args()
    try:
        request = json.loads(input())
        reads = install(args.inputs_root)
        report = prepare(args.inputs_root, request)
        report["accessed_roles"] = reads
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        StopIteration,
        AttributeError,
    ) as exc:
        report = {
            "returns": None,
            "sr": None,
            "certifiable": False,
            "runtime_consumable": False,
            "reason": str(exc)
            if isinstance(exc, ValueError)
            else "reference.input_invalid",
        }
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

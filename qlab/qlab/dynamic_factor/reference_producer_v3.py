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
from .reference_v3_scope import validate_scope, check_panel, check_reference_packets


def prepare(root, request, mechanisms=None):
    if set(request) != {
        "view",
        "inputs",
        "profile_binding",
        "dispatch",
        "sealed_scope",
        "reference_proofs",
    }:
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
        != "046280489ddc8c362a750c4b9aac167283046ecffa4d8b62f0e3098e70b55d1c"
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
    scope = validate_scope(request["sealed_scope"], view, request["profile_binding"])
    check_reference_packets(request["reference_proofs"], scope, mechanisms)
    inputs = read_inputs(root, request["inputs"], dates)
    check_panel(scope, inputs["panel"]["rows"], dates)
    projection_raw = inputs["profile"]["fold_bindings_raw"]
    if (
        hashlib.sha256(projection_raw.encode()).hexdigest()
        != "f4ce91be042287d9e51f5117e0781f5c5e79cbf7d93d4808afe7ef391320d81b"
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
        != "49dcd7bb5ab34015952437545a14489c13a644d4c6df477e8790db99d53a7219"
    ):
        raise ValueError("reference.registered_dispatch_mismatch")
    for member, spec in request["dispatch"].items():
        if (
            spec["member_id"] != member
            or spec["execution_profile_id"] != "CANDIDATE_PROBE_V3"
            or spec["execution_contract"]["parameter_search"] is not False
        ):
            raise ValueError("reference.execution_role_mismatch")
    payload = json.dumps(
        inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return {
        "schema": "reference.producer/v3.0.0",
        "complete": True,
        "shared_scope_sha256": scope["scope_sha256"],
        "eligible_set_manifest_sha256": scope["eligible_set_manifest_sha256"],
        "B_derivation_sha256": scope["B_derivation_sha256"],
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


def main(mechanisms=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-root", required=True)
    args = parser.parse_args()
    reads = []
    try:
        request = json.loads(input())
        reads = install(args.inputs_root)
        report = prepare(args.inputs_root, request, mechanisms)
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
            "complete": False,
            "returns": None,
            "sr": None,
            "certifiable": False,
            "runtime_consumable": False,
            "reason": str(exc)
            if isinstance(exc, ValueError)
            else "reference.input_invalid",
        }
    report["accessed_roles"] = list(reads)
    report["reader_calls"] = len(reads)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

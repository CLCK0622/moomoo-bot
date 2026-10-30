"""Independent stdin/stdout fixture entry; no reference strategy is defined.

Run as `python -m qlab.dynamic_factor.reference_producer --inputs-root DIR`.
The request has only the sealed train contract and three input bindings. Actual
member rules await EVO-892; this entry cannot generate real reference returns.
"""

import argparse
import hashlib
import json

from .fold_split import train_dates, train_slice
from .reference_inputs import read_inputs


def prepare(root, request):
    if set(request) != {
        "calendar",
        "train_fold",
        "inputs",
        "common_profile_sha256",
    } or set(request["train_fold"]) != {"train_start", "history_end"}:
        raise ValueError("reference.request_contains_non_train_inputs")
    dates = train_dates(request["calendar"], request["train_fold"])
    inputs = read_inputs(root, request["inputs"], dates)
    panel = train_slice(inputs["panel"]["rows"], dates)
    benchmark = train_slice(inputs["benchmark"]["rows"], dates)
    if inputs["profile"]["common_profile_sha256"] != request["common_profile_sha256"]:
        raise ValueError("reference.profile_mismatch")
    payload = json.dumps(
        {"panel": panel, "benchmark": benchmark, "profile": inputs["profile"]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return {
        "schema": "reference.producer/v1",
        "train_dates": list(dates),
        "train_input_sha256": hashlib.sha256(payload).hexdigest(),
        "returns": None,
        "sr": None,
        "reason": "reference_member_rules_pending_EVO892",
        "runtime_consumable": False,
        "certifiable": False,
        **{key: value for key, value in inputs["profile"].items() if key != "schema"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-root", required=True)
    args = parser.parse_args()
    try:
        request = json.loads(input())
        report = prepare(args.inputs_root, request)
    except (ValueError, KeyError, TypeError, OSError) as exc:
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

"""Re-signed scope attacks through the real host and isolated worker."""

import json
from copy import deepcopy

from b10_reference_helpers import exercise, resign_scope

from qlab.dynamic_factor.contract import digest


CASES = (
    "UNKNOWN_upper50_label_LT50",
    "verified49_label_GE50",
    "LT50_new_tilt_true",
    "verified50_label_LT50",
    "verified49_unknown0_upper49_label_GE50",
    "LT50_tiny_positive_tilt",
)


def rehash(request):
    scope = request["sealed_scope"]
    for day in scope["days"].values():
        day["eligible_set_derivation_sha256"] = digest(
            {k: v for k, v in day.items() if k != "eligible_set_derivation_sha256"}
        )
    scope["eligible_set_derivation_sha256"] = digest(scope["days"])
    scope["eligible_set_manifest_sha256"] = digest(
        {date: day["eligible"] for date, day in scope["days"].items()}
    )
    union = sorted({s for day in scope["days"].values() for s in day["eligible"]})
    scope["numeric_symbols"] = {
        date: scope["days"][date]["eligible"] if date in scope["days"] else union
        for date in scope["warmup"] + scope["train"]
    }
    resign_scope(request)


def attack(original, case):
    request = deepcopy(original)
    scope = request["sealed_scope"]
    day = scope["days"][scope["train"][0]]
    assert day["verified_count"] == 49
    if case == "UNKNOWN_upper50_label_LT50":
        unused = next(
            s
            for s in day["states"]
            if s not in day["eligible"]
            and s not in scope["guard"]["B"]
            and s not in scope["guard"]["unknown"]
        )
        day["states"][unused] = "UNKNOWN"
        day["upper_bound"] = 50
    elif case in {
        "verified49_label_GE50",
        "verified49_unknown0_upper49_label_GE50",
    }:
        day["quantity_state"] = "VERIFIED_GE50"
        if case == "verified49_unknown0_upper49_label_GE50":
            # Also make the claimed GE50 permission coherent with the lie, so
            # rejection cannot depend on only the original False flag.
            day["new_tilt_allowed"] = True
            assert not any(v == "UNKNOWN" for v in day["states"].values())
            assert day["upper_bound"] == 49
    elif case == "LT50_new_tilt_true":
        day["new_tilt_allowed"] = True
    elif case == "verified50_label_LT50":
        extra = next(
            s
            for s in day["states"]
            if s not in day["eligible"]
            and s not in scope["guard"]["B"]
            and s not in scope["guard"]["unknown"]
        )
        day["states"][extra] = "VERIFIED_USABLE"
        day["eligible"] = sorted(day["eligible"] + [extra])
        day.update(verified_count=50, upper_bound=50)
    elif case == "LT50_tiny_positive_tilt":
        # The existing scope exposes a boolean permission, not a numeric
        # planner. Even the smallest positive float must not count as False.
        day["new_tilt_allowed"] = 5e-324
    else:
        raise AssertionError(case)
    rehash(request)
    return request


def refused(root, request):
    out = exercise(root, request, with_proofs=True)
    diagnostics = []
    for side in ("host", "worker"):
        report = out[side]
        assert report["complete"] is False
        assert report["reader_calls"] == 0 and report["accessed_roles"] == []
        code, raw = report["reason"].split(": ", 1)
        assert code == "reference.quantity_unknown_or_insufficient_no_QQQ_substitution"
        details = json.loads(raw)
        assert set(details) == {"date", "reported", "recomputed"}
        assert set(details["recomputed"]) == {
            "verified_count",
            "upper_bound",
            "quantity_state",
            "new_tilt_allowed",
        }
        diagnostics.append(details)
    assert diagnostics[0] == diagnostics[1]
    worker = out["worker"]
    assert worker["returns"] is worker["sr"] is None
    assert worker["runtime_consumable"] is worker["certifiable"] is False
    return out

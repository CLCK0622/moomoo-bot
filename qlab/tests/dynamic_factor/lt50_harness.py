"""Synthetic LT50 preparation protocol; never executes reference performance.

Run with PYTHONPATH=qlab and a fresh --workdir. The expanded train/warmup
fixture is counterfactual wire data, not an adopted eligibility mask or trial.
"""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

from b10_reference_helpers import exercise, resign_scope, wire_fixture
from v3_reference_helpers import unit_scope

from qlab.dynamic_factor.contract import digest, sha256, source_manifest
from qlab.dynamic_factor.harness import offline, run as gate_harness
from qlab.dynamic_factor.reference_compile_v3 import compile_panel
from qlab.dynamic_factor.reference_registry_v3 import registered_request
from qlab.dynamic_factor.reference_v3_evidence import runtime_check, seal_static


PENDING = "reference_runtime_evidence_pending_EVO886_EVO891"
QUANTITY = "reference.quantity_unknown_or_insufficient_no_QQQ_substitution"
SCOPE_CASES = {
    "unknown_day": QUANTITY,
    "count_mismatch": QUANTITY,
    "zero_eligible": QUANTITY,
    "QQQ_substitution": "reference.same_E_t_required",
}


def preparation_refused(report):
    assert report["returns"] is report["sr"] is None
    assert report["runtime_consumable"] is report["certifiable"] is False


def scope_attack(original, case):
    request = deepcopy(original)
    scope = request["sealed_scope"]
    day = scope["days"][scope["train"][0]]
    if case == "unknown_day":
        day["quantity_state"] = "UNKNOWN"
    elif case == "count_mismatch":
        day["verified_count"] += 1
    elif case == "zero_eligible":
        day.update(eligible=[], verified_count=0, upper_bound=0)
        day["states"] = {symbol: "QUARANTINED" for symbol in scope["universe"]}
    elif case == "QQQ_substitution":
        day["eligible"] = ["QQQ"]
        day["verified_count"] = 1
    else:
        raise AssertionError(case)
    # Re-sign all owned hashes so rejection tests semantics, not a stale hash.
    day["eligible_set_derivation_sha256"] = digest(
        {k: v for k, v in day.items() if k != "eligible_set_derivation_sha256"}
    )
    scope["eligible_set_derivation_sha256"] = digest(scope["days"])
    scope["eligible_set_manifest_sha256"] = digest(
        {date: d["eligible"] for date, d in scope["days"].items()}
    )
    union = sorted({s for d in scope["days"].values() for s in d["eligible"]})
    scope["numeric_symbols"] = {
        date: scope["days"][date]["eligible"] if date in scope["days"] else union
        for date in scope["warmup"] + scope["train"]
    }
    # Leave complete=true deliberately: the receiver must reject the forgery.
    assert scope["complete"] is True
    resign_scope(request)
    return request


def scope_negative(root, original, case):
    out = exercise(root, scope_attack(original, case), with_proofs=True)
    for side in ("host", "worker"):
        report = out[side]
        assert report["complete"] is False
        assert report["reason"].split(":", 1)[0] == SCOPE_CASES[case]
        assert report["reader_calls"] == 0 and report["accessed_roles"] == []
    preparation_refused(out["worker"])
    return out


def missing_member(root, original):
    request = deepcopy(original)
    request["dispatch"].pop(sorted(request["dispatch"])[0])
    out = exercise(root, request, with_proofs=True)
    assert out["host"]["complete"] is True
    worker = out["worker"]
    assert worker["complete"] is False
    assert worker["reason"] == "reference.member_not_registered_or_incomplete"
    assert worker["accessed_roles"] == ["benchmark", "panel", "profile"]
    preparation_refused(worker)
    return out


def downstream_negative(original, preparation, case):
    if case == "preparation_complete_is_not_reference_usable":
        assert preparation["complete"] is True
        # Feed the actual preparation report into the public runtime consumer.
        request = deepcopy(preparation)
        expected = "reference.v3_runtime_schema_or_old_V_forbidden"
    else:
        request = registered_request()
        scope = original["sealed_scope"]
        request.update(
            scope=scope,
            static_seal=seal_static(scope, "2026-10-30T12:10:00Z"),
            sidecars={},
        )
        if case != "missing_returns":
            value = {"null": None, "nan": float("nan"), "inf": float("inf")}[case]
            # Hostile synthetic claims only. No actual performance is read or
            # generated. The current v3 gate must stop before trusting sidecars.
            request["sidecars"] = {"candidate": {"returns": [value], "sr": value}}
        expected = "reference.runtime_B_release_and_actual_proofs_missing"
    report = runtime_check(request)
    assert report["reasons"] == [expected]
    assert (
        report["ok"] is report["runtime_consumable"] is report["certifiable"] is False
    )
    assert report["metrics"]["dsr"] is report["metrics"]["trials_variance"] is None
    return dict(reasons=report["reasons"], V=None, DSR=None, runtime_consumable=False)


def positive(root, request):
    scope = unit_scope(verified=49)
    assert scope["complete"] is True
    day = next(iter(scope["days"].values()))
    assert day["quantity_state"] == "VERIFIED_LT50"
    assert day["verified_count"] == len(day["eligible"]) == 49
    assert day["new_tilt_allowed"] is False
    assert day["required_M_valuation_cash_fees_still_required"] is True
    calls = []
    compile_panel(scope, lambda d, s: calls.append((d, s)) or 100)
    assert len(calls) == 49 and "QQQ" not in {s for _, s in calls}
    out = exercise(root, request, with_proofs=True)
    assert out["host"]["complete"] is True
    assert out["host"]["reader_calls"] == 49 * (1260 + 252)
    worker = out["worker"]
    assert worker["complete"] is True
    assert worker["reader_calls"] == 3
    assert worker["accessed_roles"] == ["benchmark", "panel", "profile"]
    assert worker["reason"] == PENDING
    assert len(worker["prepared_members"]) == 4
    preparation_refused(worker)
    return out


def run(workdir):
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("harness_workdir_must_be_empty: preserve prior evidence")
    with offline() as network:
        inputs = root / "inputs"
        request = wire_fixture(inputs, verified=49)
        accepted = positive(inputs, request)
        cases = [
            dict(
                case_id=case,
                status="PASS",
                observed=scope_negative(inputs, request, case),
            )
            for case in SCOPE_CASES
        ]
        cases.append(
            dict(
                case_id="missing_family_member",
                status="PASS",
                observed=missing_member(inputs, request),
            )
        )
        cases.append(
            dict(
                case_id="returns_missing_or_nonfinite",
                status="PASS",
                observed={
                    case: downstream_negative(request, accepted["worker"], case)
                    for case in ("missing_returns", "null", "nan", "inf")
                },
            )
        )
        cases.append(
            dict(
                case_id="preparation_complete_is_not_reference_usable",
                status="PASS",
                observed=downstream_negative(
                    request,
                    accepted["worker"],
                    "preparation_complete_is_not_reference_usable",
                ),
            )
        )
    sources = source_manifest()
    test_sources = {
        name: sha256(Path(__file__).with_name(name).read_bytes())
        for name in (
            "lt50_harness.py",
            "v3_reference_helpers.py",
            "b10_reference_helpers.py",
        )
    }
    lt50 = dict(
        schema="EVO884.LT50PreparationHarness/v1",
        status="PASS",
        synthetic_only=True,
        adopted_masks=0,
        reference_performance_runs=0,
        network_attempts=len(network),
        source_files=sources,
        source_sha256=digest(sources),
        test_sources=test_sources,
        input_sha256=digest(request),
        positive=accepted,
        negative_cases=cases,
        negative_cases_passed=len(cases),
        returns=None,
        sr=None,
        V=None,
        DSR=None,
        runtime_consumable=False,
        certifiable=False,
    )
    report = gate_harness(root / "gates")
    report["lt50"] = lt50
    assert report["dependencies"]["python"] == sys.version.split()[0]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.workdir),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )

"""Four minimum-scope negatives. Flat NAV fixtures are synthetic receipts only."""

from copy import deepcopy

from .authority_ledger import CURRENT_PUBLISHED as PUBLISHED
from .continuity import continuous_path_check
from .contract import digest
from .execution import calibrate_gain, initial_build_turnover_check
from .folds import _features, run_walk_forward
from .input_scope import ROLES
from .pending import pool_admission_check
from .pipeline import run_train_pipeline, select_pool
from .reference_inputs import read_inputs
from .scope_reader import read_strategy_inputs
from .scope_proof import b2_isolation_proof
from .valuation import integer_cash_valuation


def continuity_fixture(policy):
    state = dict(
        date=policy.calendar[0],
        nav=policy.document["initialization"]["initial_cash_usd"],
        inventory={},
        cash=policy.document["initialization"]["initial_cash_usd"],
        age={},
        retired_ids=[],
        exit_intents=[],
        initialization_count=1,
    )
    rows = []
    base = PUBLISHED["n_high_water"]
    for i, f in enumerate(policy.fold_manifest()["folds"]):
        dates = list(
            policy.calendar[
                policy.calendar.index(f["test_start"]) : policy.calendar.index(
                    f["test_end"]
                )
                + 1
            ]
        )
        final = dict(state, date=dates[-1])
        aid = "SYNTHETIC_UNIT_NO_PERFORMANCE/" + str(i)
        rows.append(
            dict(
                fold_id=f["fold_id"],
                dates=dates,
                status="success",
                reasons=[],
                nav=[state["nav"]] * len(dates),
                initialized=i == 0,
                attempt_id=aid,
                attempted=True,
                budget_state=dict(
                    authorization_sha256=digest("SYNTHETIC_UNIT_LICENSE"),
                    consumed=True,
                    seen_result=True,
                ),
                inventory={},
                exit_intents=[],
                input_state=deepcopy(state),
                output_state=deepcopy(final),
                input_state_sha256=digest(state),
                output_state_sha256=digest(final),
                N_receipt=dict(
                    attempt_id=aid,
                    contribution=1,
                    N_before=base + i,
                    N_after=base + i + 1,
                ),
            )
        )
        state = final
    return {
        "run_id": "SYNTHETIC_UNIT_NO_PERFORMANCE",
        "folds": rows,
        "initial_recorded_N": base,
    }


def expect_scope_refusal(call):
    try:
        report = call()
    except ValueError as exc:
        assert str(exc) == "scope.B2_dependency_forbidden", str(exc)
    else:
        assert report["reasons"] == ["scope.B2_dependency_forbidden"], report["reasons"]
        assert not report["ok"] and not report["runtime_consumable"]


def role_calls(workdir, policy):
    def canary(*a, **k):
        raise AssertionError("strategy adapter invoked")

    return {
        "features": lambda: _features({"features": {"VTI_close": 1}}),
        "qqq_labels": lambda: run_walk_forward(
            policy.fold_manifest(),
            [{"features": {"VTI": 1}}],
            miner_factory=canary,
            fitter_factory=canary,
            ledger=None,
            run_id="UNIT",
            conventions=policy,
        ),
        "calibration": lambda: calibrate_gain(
            [], [], conventions=policy, context={"VTI": []}
        ),
        "admission": lambda: pool_admission_check({"VTI": []}, conventions=policy),
        "reference": lambda: read_inputs(workdir, {"VTI": {}}, []),
        "holdings_cash": lambda: integer_cash_valuation(
            {"inventory": {"VTI": 1}}, conventions=policy
        ),
        "orders": lambda: initial_build_turnover_check(
            {"raw_open_prices": {"VTI": 100}}, conventions=policy
        ),
    }


def cases(workdir, policy):
    roles = role_calls(workdir, policy)
    for role in ROLES:
        expect_scope_refusal(roles[role])
        expect_scope_refusal(
            lambda: read_strategy_inputs(
                workdir, {"VTI": {"file": "VTI.json"}}, [], role=role, policy=policy
            )
        )
    proof = b2_isolation_proof(policy)
    cases = [
        dict(
            case_id="scope.B2_strategy_read_forbidden",
            status="PASS",
            observed=dict(
                rejected_roles=list(ROLES),
                proof_source_sha256=proof["source_sha256"],
                no_adapter_invoked=True,
            ),
        )
    ]
    skip = continuity_fixture(policy)
    skip["folds"].pop(1)
    report = continuous_path_check(skip, conventions=policy)
    assert report["reasons"] == ["wf.all_original_folds_required"]
    assert len(report["metrics"]["folds"]) == len(policy.fold_manifest()["folds"])
    invalid = continuity_fixture(policy)
    invalid["folds"][1].update(
        status="failed", nav=None, reasons=["UNIT_STATE_UNKNOWN"]
    )
    propagated = continuous_path_check(invalid, conventions=policy)
    assert "wf.continuation_after_invalid_state_forbidden" in propagated["reasons"]
    assert all(r["nav"] is None for r in propagated["metrics"]["folds"][1:])
    assert propagated["metrics"]["A"] is propagated["metrics"]["IR"] is None
    cases.append(
        dict(
            case_id="scope.invalid_fold_skip_rejected",
            status="PASS",
            observed=dict(
                all_original_folds_retained=len(report["metrics"]["folds"]),
                dependent_future_NAV=None,
                A=None,
                IR=None,
            ),
        )
    )
    restart = continuity_fixture(policy)
    restart["folds"][2]["initialized"] = True
    r = continuous_path_check(restart, conventions=policy)
    assert "wf.capital_restart_forbidden" in r["reasons"] and r["metrics"]["A"] is None
    cases.append(
        dict(
            case_id="scope.capital_restart_rejected",
            status="PASS",
            observed={"reason": "wf.capital_restart_forbidden", "A": None, "IR": None},
        )
    )
    calls = []
    request = {
        "candidate_id": "UNIT",
        "pool": [],
        "fallback_holdings": {"QQQ": 1},
        "N": None,
        "V": None,
        "candidate_SR": None,
    }
    from .harness_helpers import fixture_ledger

    ledger = fixture_ledger(workdir / "scope-admission-unit.sqlite", policy)
    admission = pool_admission_check(request, conventions=policy, ledger=ledger)
    assert not admission["ok"] and admission["metrics"]["pool"] is None
    assert (
        admission["metrics"]["fallback_holdings"] is None
        and "pool.S2_unavailable_not_empty" in admission["reasons"]
    )
    try:
        select_pool({}, {}, policy, [])
    except ValueError as exc:
        assert str(exc) == "pool.S2_unavailable_not_empty"
    else:
        raise AssertionError("unavailable admission became empty pool")
    run = run_train_pipeline(
        policy=policy,
        ledger=ledger,
        run_id="UNIT",
        context={},
        registry=None,
        proposals=[],
        probe=lambda *a: calls.append(a),
        build_meta=lambda *a: calls.append(a),
        self_report_n=None,
    )
    assert run["candidate"] is run["meta"] is None and not calls
    cases.append(
        dict(
            case_id="scope.S2_unavailable_not_empty_QQQ",
            status="PASS",
            observed=dict(pool=None, fallback_holdings=None, meta_calls=0),
        )
    )
    return cases

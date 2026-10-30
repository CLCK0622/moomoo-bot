"""Clearly synthetic unit inputs for the reviewed v0.2 mechanism (no strategy)."""

from __future__ import annotations

import json
import math

from .contract import digest
from .execution import initial_build_turnover_check, nav_increment, lock_startup_intent
from .ledger import AttemptLedger
from .pipeline import run_train_pipeline
from .statistics import dsr_eval


def synthetic_context(policy):
    fold = policy.date_manifest["folds"][0]
    a, b = fold["train_index_inclusive"]
    data_sha = digest({"synthetic_unit_only": "no_market_prices_or_strategy"})
    return {
        "fold_id": str(fold["fold_id"]),
        "retired_ids": [],
        "train_calendar": list(policy.calendar[a : b + 1]),
        "universe_and_data_sha256": data_sha,
        "cost_model_sha256": policy.document["cost_mapping"]["x2_sha256"],
        "common_profile_sha256": policy.document["variance_layers"]["probe_profile"][
            "common_profile_sha256"
        ],
        "price_basis_receipt": {
            "source_sha256": digest("synthetic_unit_receipt_not_market_evidence"),
            "universe_and_data_sha256": data_sha,
            "execution_price_basis_verified": True,
            "total_return_basis_verified": True,
            "cross_anchor_comparability_verified": True,
        },
    }


def synthetic_returns(n, sr):
    z = [(-1 if i % 2 else 1) for i in range(n)]
    # sample sd of this zero-mean balanced unit series
    return [(x + sr * math.sqrt(n / (n - 1))) * 0.001 for x in z]


def synthetic_registry(policy, context):
    document = {}
    for layer in ("candidate", "meta"):
        trials = {}
        for i, sr in enumerate((0.1, 0.2)):
            tid = f"synthetic-external-{layer}-{i}"
            returns = synthetic_returns(len(context["train_calendar"]), sr)
            trials[tid] = {
                "trial_id": tid,
                "return_role": policy.document["N"]["DSR_SR_basis"],
                "source_run_id": "synthetic_external_registry",
                "source_returns_sha256": digest(returns),
                "profile_id_and_sha256": {
                    "id": policy.document["variance_layers"]["independent_reference"][
                        f"{layer}_reference_profile"
                    ],
                    "sha256": context["common_profile_sha256"],
                },
                "universe_and_data_sha256": context["universe_and_data_sha256"],
                "cost_model_sha256": context["cost_model_sha256"],
                "train_calendar_sha256": digest(context["train_calendar"]),
                "scale": "daily",
                "returns": returns,
            }
        document[layer] = {"members": list(trials), "trials": trials}
    return {
        "document": document,
        "sha256": digest(document),
        "semantic_sha256": digest(document),
    }


def synthetic_ledger(path, policy, *, complete=False):
    # Never use this fixture to reconcile a real ledger. The normal constructor
    # imports the unchanged 47 lower bound with count_complete=False.
    if not complete:
        return AttemptLedger.from_conventions(path, policy)
    return AttemptLedger(
        path,
        {
            "namespace": "evo881.dynamic_factor",
            "prior_n": 47,
            "count_complete": True,
            "authority_source": {
                "reference": "SYNTHETIC_UNIT_ONLY_NOT_A_REAL_N_RECONCILIATION",
                "sha256": digest("synthetic_audit"),
            },
            "attempt_counting_policy": policy.document["N_counting"],
            **policy.binding,
        },
    )


def synthetic_callbacks(policy, context, calls, *, failed=None, meta_sr=-0.5):
    ids = policy.document["variance_layers"]["family_definitions"]["candidate_members"]
    d = context["train_calendar"][0]
    scores = {d: {f"S{s:03}": s for s in range(50)}}

    def probe(proposal, profile):
        calls.append(proposal["id"])
        assert profile["DSR_admission"] is False
        if proposal["id"] == failed:
            raise ValueError("synthetic_probe_failure")
        return {
            "returns": synthetic_returns(
                len(context["train_calendar"]), 1 + ids.index(proposal["id"]) * 0.01
            ),
            "scores": scores,
        }

    def meta(pool, calibration):
        assert calibration["conventions_sha256"] == policy.raw_sha256
        calls.append("meta")
        return {"returns": synthetic_returns(len(context["train_calendar"]), meta_sr)}

    return probe, meta


def synthetic_gain_rows(policy, context):
    ids = policy.document["variance_layers"]["family_definitions"]["candidate_members"]
    d = context["train_calendar"][0]
    rows = [
        {
            "date": d,
            "symbol": f"S{i:03}",
            "label_entry": context["train_calendar"][1],
            "label_end": context["train_calendar"][11],
            "stock_h10": 0.02 + i * 0.001,
            "qqq_h10": 0.01,
            "ranks": {k: (i + 0.5) / 50 for k in ids},
        }
        for i in range(50)
    ]
    return {"rows": rows, "matured_dates": [d]}


def run_synthetic(
    path,
    policy,
    *,
    complete=True,
    registry=True,
    context=None,
    failed=None,
    run_id="synthetic",
):
    context = context or synthetic_context(policy)
    ledger = synthetic_ledger(path, policy, complete=complete)
    calls = []
    probe, meta = synthetic_callbacks(policy, context, calls, failed=failed)
    registry = (
        synthetic_registry(policy, context)
        if registry is True
        else (None if registry is False else registry)
    )
    outcome = run_train_pipeline(
        policy=policy,
        ledger=ledger,
        run_id=run_id,
        context=context,
        registry=registry,
        proposals=[
            {"id": x}
            for x in policy.document["variance_layers"]["family_definitions"][
                "candidate_members"
            ]
        ],
        probe=probe,
        build_meta=meta,
        self_report_n=1,
        calibrate=lambda: synthetic_gain_rows(policy, context),
    )
    return outcome, ledger, calls


def revision_cases(workdir, policy):
    outcome, ledger, calls = run_synthetic(workdir / "dag-unit.sqlite", policy)
    assert outcome["reason"] is None
    candidate, meta = outcome["candidate"], outcome["meta"]
    assert candidate["pool"] == ["F4-L060"] and len(calls) == 17
    assert math.isclose(
        candidate["family_variance"], 0.0022666666666666664, abs_tol=1e-12
    )
    assert math.isclose(candidate["trials_variance"], 0.005, abs_tol=1e-12)
    assert meta["trials_variance"] > candidate["trials_variance"] and meta["dsr"] < 0.95
    assert candidate["gate_n"] == 63 and meta["gate_n"] == 64
    assert ledger.recorded("v02/synthetic/0/S2")["pool"] == candidate["pool"]
    r = dsr_eval(
        {"run_id": "synthetic", "fold_id": "0", "layer": "meta"},
        ledger,
        conventions=policy,
    )
    assert r["metrics"]["dsr"] == meta["dsr"] and not r["certifiable"]
    missing, incomplete, missing_calls = run_synthetic(
        workdir / "missing-reference-unit.sqlite",
        policy,
        complete=False,
        registry=False,
    )
    assert (
        missing["candidate"] is None
        and missing["meta"] is None
        and "meta" not in missing_calls
    )
    assert incomplete.snapshot()["cumulative_n"] is None

    startup_ledger = AttemptLedger(workdir / "startup-unit.sqlite")
    context = synthetic_context(policy)
    cash, inv = 15000, {}
    quantities, taus = [], []
    sessions = list(policy.calendar[100:106])
    for pos in range(4):
        nav = cash + inv.get("QQQ", 0) * 100
        close = sessions[pos] + "T16:00:00"
        intent = lock_startup_intent(
            pos,
            nav,
            inv,
            close,
            policy=policy,
            ledger=startup_ledger,
            start_id="synthetic-start",
            scope_id="synthetic-test-forward",
        )
        report = initial_build_turnover_check(
            {
                "intent": intent,
                "context": context,
                "cash": cash,
                "previous_close": close,
                "raw_open_prices": {"QQQ": 100},
                "open_timestamp": sessions[pos + 1] + "T09:30:00",
                "reference_sessions": sessions,
                "sell_date": sessions[pos + 1],
                "rate_basis": "research_restored",
                "start_id": "synthetic-start",
            },
            conventions=policy,
            ledger=startup_ledger,
        )
        assert report["ok"], report["reasons"]
        m = report["metrics"]
        cash, inv = m["cash"], m["inventory"]
        quantities.append(m["quantity"])
        taus.append(m["one_way_turnover"])
        assert m["one_way_turnover"] <= 0.2 and cash >= 0.02 * (cash + inv["QQQ"] * 100)
    assert quantities[0] == 60 and quantities[3] == 0
    gain = nav_increment(
        {"QQQ": 20}, {"S": 20}, {"S": 100, "QQQ": 100}, {"S": 0.01}, 0.03, 10000, 0, 30
    )
    assert (
        math.isclose(gain["G_H10"], 0.002)
        and math.isclose(gain["K"], 0.003)
        and gain["allowed"] is False
    )
    # Affine qfq: adding B changes ratios, so ratio-only evidence cannot pass.
    assert 110 / 100 - 1 != (110 + 10) / (100 + 10) - 1
    invalid_context = json.loads(json.dumps(context))
    invalid_context["price_basis_receipt"]["total_return_basis_verified"] = False
    invalid, _, invalid_calls = run_synthetic(
        workdir / "basis-unit.sqlite", policy, context=invalid_context
    )
    assert invalid["reason"] == "data.price_basis_unverified" and not invalid_calls
    return [
        {
            "case_id": "dsr.admission_meta_family_dag",
            "status": "PASS",
            "synthetic_only": True,
            "candidate_V": candidate["trials_variance"],
            "meta_V": meta["trials_variance"],
            "candidate_N": candidate["gate_n"],
            "meta_N": meta["gate_n"],
            "meta_failure_did_not_reselect": True,
            "missing_reference": missing["reason"],
        },
        {
            "case_id": "startup.three_sessions_no_upward_exception",
            "status": "PASS",
            "synthetic_only": True,
            "quantities": quantities,
            "turnover": taus,
            "after_O2_topup": False,
        },
        {
            "case_id": "gain.nav_weight_old_new_QQQ_and_net_cost",
            "status": "PASS",
            "synthetic_only": True,
            "gain": gain["G_H10"],
            "incremental_cost": gain["K"],
            "allowed": gain["allowed"],
        },
        {
            "case_id": "data.affine_qfq_ratio_not_invariant",
            "status": "PASS",
            "synthetic_only": True,
            "reason": invalid["reason"],
        },
    ]

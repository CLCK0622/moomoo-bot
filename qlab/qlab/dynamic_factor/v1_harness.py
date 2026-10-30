"""Synthetic-only v1/audit cases. No registered research family is invented."""

from __future__ import annotations

import json
import io
import shutil
import sqlite3
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace

from .contract import canonical, digest, sha256
from .conventions import FIXTURES
from .dsr_v0 import formula
from .execution import nav_increment
from .fees import fee_frontier
from .harness_helpers import fixture_ledger
from .ledger import AttemptLedger
from .reference_check import (
    reference_manifest_check,
    register_reference_attempts,
    static_proof,
)
from .reference_producer import prepare
from .statistics import DSRPlugin, dsr_eval
from .valuation import benchmark_valuation, integer_cash_valuation


def unit_context(policy):
    fold = policy.date_manifest["folds"][0]
    lo, hi = fold["train_index_inclusive"]
    data_sha = digest("SYNTHETIC_UNIT_DATA_NOT_MARKET")
    return {
        "fold_id": str(fold["fold_id"]),
        "train_calendar": list(policy.calendar[lo : hi + 1]),
        "retired_ids": [],
        "universe_and_data_sha256": data_sha,
        "cost_model_sha256": policy.document["cost_mapping"]["x2_sha256"],
        "common_profile_sha256": policy.binding["common_profile_sha256"],
        "price_basis_receipt": {
            "source_sha256": digest("synthetic_receipt"),
            "universe_and_data_sha256": data_sha,
            "execution_price_basis_verified": True,
            "total_return_basis_verified": True,
            "cross_anchor_comparability_verified": True,
        },
    }


def wrapped(document):
    raw = canonical(document).decode()
    return {"raw": raw, "document": document, "sha256": sha256(raw.encode())}


def registry_fixture(policy):
    from .reference_registry import registered_request

    return registered_request()


def producer_fixture(root, policy):
    from .fold_split import shared_views
    from .reference_boundary import prepare_request
    from .reference_registry import artifact

    root.mkdir(parents=True)
    fold = policy.fold_manifest()["folds"][0]
    contract = policy.document["folds"]
    view = shared_views(
        policy.calendar,
        fold,
        train_days=contract["train_days"],
        warmup_days=contract["warmup_days"],
    )
    dates = view.warmup + view.train
    binding = {
        k: policy.binding[k]
        for k in (
            "conventions_version",
            "conventions_sha256",
            "prereg_sha256",
            "common_profile_sha256",
        )
    }
    data = {
        "panel": {
            "schema": "reference.train_panel/v1",
            "rows": [{"date": d, "prices": {"UNIT": 100}} for d in dates],
        },
        "benchmark": {
            "schema": "reference.train_benchmark/v1",
            "symbol": "QQQ",
            "rows": [{"date": d, "close": 100} for d in dates],
        },
        "profile": {
            "schema": "reference.profile/v1",
            **binding,
            "fold_bindings_raw": artifact("fold-bindings.json")["raw"],
        },
    }
    bindings = {}
    for role, payload in data.items():
        raw = canonical(payload)
        (root / (role + ".json")).write_bytes(raw)
        bindings[role] = {"file": role + ".json", "sha256": sha256(raw)}
    return prepare_request(policy, fold, view, bindings)


def revision_cases(workdir, policy):
    from .folds import run_walk_forward
    from .validation import wf_manifest_check
    from .harness import _wf

    cases = []

    def record(name, observed):
        cases.append(
            {
                "case_id": name,
                "status": "PASS",
                "synthetic_only": True,
                "observed": observed,
            }
        )

    called = []
    r = run_walk_forward(
        _wf(),
        [],
        miner_factory=lambda c: called.append(c),
        fitter_factory=lambda c: called.append(c),
        ledger=AttemptLedger(workdir / "unbound.sqlite"),
        run_id="audit",
    )
    assert "wf.conventions_required" in r["reasons"] and not called
    assert "wf.conventions_required" in wf_manifest_check(_wf())["reasons"]
    record("audit.fold_unbound_short_embargo", {"refused": True, "adapter_calls": 0})

    for action in ("tail", "all", "old_snapshot"):
        ledger = fixture_ledger(workdir / (action + ".sqlite"), policy)
        ledger.begin("one", {})
        old = workdir / (action + ".old.sqlite")
        shutil.copyfile(ledger.path, old)
        ledger.finish("one", "failed")
        ledger.begin("two", {})
        ledger.observe_self_report_n(500)
        if action == "old_snapshot":
            shutil.copyfile(old, ledger.path)
        else:
            with sqlite3.connect(ledger.path) as db:
                db.execute(
                    "DELETE FROM events"
                    if action == "all"
                    else "DELETE FROM events WHERE seq>=3"
                )
        refused = False
        try:
            ledger.begin("forbidden_after_rollback", {})
        except ValueError:
            refused = True
        assert refused and ledger.safe_snapshot()["cumulative_n"] is None
        record("audit.ledger_" + action, {"read_and_append_refused": True, "n": None})
    try:
        AttemptLedger.from_conventions(workdir / "new_unapproved.sqlite", policy)
    except ValueError as exc:
        assert "receipt" in str(exc)
    else:
        raise AssertionError("unapproved new bound ledger")
    record("audit.ledger_new_db_requires_receipt", {"refused": True})

    try:
        AttemptLedger.from_conventions(
            workdir / "seed_forgery.sqlite", replace(policy, seed_raw=b"")
        )
    except ValueError as exc:
        assert "seed_bytes" in str(exc)
    else:
        raise AssertionError("declared SHA replaced actual seed")
    record("audit.seed_actual_bytes_required", {"refused": True})

    from .__main__ import main as cli_main

    request_file = workdir / "cli-request.json"
    genesis_file = workdir / "forged-genesis.json"
    request_file.write_bytes(canonical({"metrics": {}}))
    genesis_file.write_bytes(canonical({"prior_n": 0, "count_complete": True}))
    argv = sys.argv
    try:
        sys.argv = [
            "qlab.dynamic_factor",
            "dsr_eval",
            "--input",
            str(request_file),
            "--ledger",
            str(workdir / "cli-forgery.sqlite"),
            "--conventions",
            str(FIXTURES / "conventions-v1.0.1.json"),
            "--genesis",
            str(genesis_file),
        ]
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cli_main()
        cli_report = json.loads(stdout.getvalue())
        assert code == 2 and cli_report["reasons"] == [
            "ledger.custom_genesis_forbidden"
        ]
        assert not (workdir / "cli-forgery.sqlite").exists()
    finally:
        sys.argv = argv
    record("audit.CLI_bound_genesis_override", {"refused_before_DB_creation": True})
    ledger = fixture_ledger(workdir / "pending.sqlite", policy)
    called = []
    plugin = DSRPlugin(
        "forged", digest({}), digest("fake"), lambda *a: called.append(a)
    )
    for version in (None, policy):
        r = dsr_eval(
            {"v": 0, "sharpe": 999},
            ledger,
            prereg={"version": "forged"},
            plugin=plugin,
            conventions=version,
        )
        assert (
            r["metrics"]["dsr"] is None
            and r["metrics"]["trials_variance"] is None
            and not r["certifiable"]
            and not r["runtime_consumable"]
        )
    assert not called
    record(
        "audit.pending_legacy_certification_bypass",
        {"dsr": None, "V": None, "plugin_calls": 0},
    )

    for mode in ("missing", "sha", "member"):
        request = registry_fixture(policy)
        if mode == "missing":
            request["registry"] = None
        elif mode == "sha":
            request["manifests"]["candidate"]["sha256"] = "0" * 64
        else:
            doc = json.loads(request["manifests"]["candidate"]["raw"])
            doc["members"].append(dict(doc["members"][0], member_id="UNREGISTERED"))
            request["manifests"]["candidate"] = wrapped(doc)
        r = reference_manifest_check(request, conventions=policy)
        assert (
            not r["ok"]
            and r["metrics"]["dsr"] is None
            and r["metrics"]["trials_variance"] is None
        )
        record(
            "reference.registry_" + mode,
            {"reasons": r["reasons"], "dsr": None, "V": None},
        )
    request = registry_fixture(policy)
    count_before = ledger.snapshot()["local_counted_n"]
    attempts = register_reference_attempts(
        request["registry"],
        request["manifests"],
        policy=policy,
        ledger=ledger,
        fold_id="0",
        first_performance_at=request["first_performance_at"],
    )
    assert ledger.snapshot()["local_counted_n"] == count_before + len(attempts) == 4
    record(
        "reference.all_trials_count_N", {"reference_attempts": 4, "complete_N": None}
    )

    request = producer_fixture(workdir / "producer-inputs", policy)
    prepared = prepare(workdir / "producer-inputs", request)
    assert (
        len(prepared["train_dates"]) == policy.document["folds"]["train_days"]
        and prepared["returns"] is None
    )
    bad = deepcopy(request)
    bad["inputs"]["panel"]["file"] = "candidate-returns.json"
    try:
        prepare(workdir / "producer-inputs", bad)
    except ValueError as exc:
        assert "whitelisted" in str(exc)
    else:
        raise AssertionError("producer read candidate output")
    record(
        "reference.producer_candidate_read_refused",
        {"refused": True, "proof": static_proof()},
    )

    r = benchmark_valuation(
        {
            "symbol": "VTI",
            "price_basis": "raw_close",
            "raw_source_sha256": digest("unit"),
            "prices": [{"date": "2026-01-05", "close": 100}],
            "evidence": None,
        },
        conventions=policy,
    )
    assert (
        r["metrics"]["analytical_index"] is None
        and "data.vti_evidence_missing" in r["reasons"]
    )
    record(
        "data.VTI_missing_evidence_no_SPY_fallback",
        {"reason": "data.vti_evidence_missing", "B2": None},
    )

    orders = [
        {
            "broker_order_id": "Q",
            "exchange_local_trade_date": "2026-12-01",
            "side": "buy",
            "quantity": q,
            "notional": q * 100,
            "planned_quantity": 100,
            "status": status,
            "time_in_force": "DAY",
        }
        for q, status in [(40, "partial"), (100, "filled")]
    ]
    r = fee_frontier(
        {"orders": orders, "pnl_basis": "reference", "normalizer_usd": 10000},
        FIXTURES / "fee_params_x2.json",
        conventions=policy,
    )
    assert (
        r["ok"]
        and sum(e["research_cost_increment_usd"] for e in r["metrics"]["fee_events"])
        == r["metrics"]["research_cost_usd"]
    )
    record(
        "fee.partial_cumulative_increment",
        {"research_cost": r["metrics"]["research_cost_usd"], "actual_fee": None},
    )
    gap = fee_frontier(
        {
            "orders": orders,
            "pnl_basis": "reference",
            "known_rate_changes": [
                {"effective_date": "2026-11-01", "params_sha256": None}
            ],
        },
        FIXTURES / "fee_params_x2.json",
        conventions=policy,
    )
    assert (
        gap["reasons"] == ["fee.new_rate_receipt_missing"]
        and gap["metrics"]["research_cost_usd"] is None
    )
    record("fee.new_rate_receipt_gap", {"new_risk_refused": True, "cost": None})

    cash = integer_cash_valuation(
        {
            "known_cash": 100,
            "as_of": "2026-01-06",
            "inventory": {"QQQ": 2},
            "marks": {"QQQ": 100},
            "events": [
                {
                    "ex_date": "2026-01-05",
                    "declared_cash_amount": None,
                    "analytical_D_used": 0.65541,
                    "exact_amount_status": "inferred",
                    "ex_date_status": "unverified",
                    "pay_date": None,
                    "entitled_integer_shares": 2,
                    "source_sha256": digest("unit"),
                }
            ],
        },
        conventions=policy,
    )
    assert (
        cash["metrics"]["nav"] is None and cash["metrics"]["receivable_amount"] is None
    )
    record(
        "valuation.analytical_D_not_spendable_cash",
        {"nav": None, "receivable": None, "known_cash": 100},
    )
    gain = nav_increment(
        {"QQQ": 20}, {"S": 20}, {"QQQ": 100, "S": 100}, {"S": 0.01}, 0.03, 10000, 0, 30
    )
    assert gain["G_H10"] == 0.002 and gain["K"] == 0.003 and not gain["allowed"]
    record("gain.NAV_units_math_only", {"G": 0.002, "K": 0.003, "allowed": False})
    _, value = formula(
        policy,
        SR=0.2903200204700225,
        n=60,
        N=81,
        V=0.0102,
        skew=0,
        kurt=1.7314285714285709,
        n_complete=False,
    )
    assert abs(value - 0.6265006201845557) < 1e-12
    record(
        "dsr.formula_external_V_math_only",
        {"pure_formula_DSR": value, "runtime_DSR": None},
    )
    return cases

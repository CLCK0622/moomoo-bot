import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.conventions import FIXTURES, load_conventions
from qlab.dynamic_factor.folds import run_walk_forward, _run_walk_forward_unbound
from qlab.dynamic_factor.input_scope import ROLES
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.pipeline import select_pool
from qlab.dynamic_factor.reference_boundary import run_isolated
from qlab.dynamic_factor.scope_harness import (
    cases,
    continuity_fixture,
    role_calls,
    expect_scope_refusal,
)
from qlab.dynamic_factor.scope_proof import b2_isolation_proof
from qlab.dynamic_factor.scope_reader import read_strategy_inputs
from qlab.dynamic_factor.validation import wf_manifest_check
from qlab.dynamic_factor.v1_harness import producer_fixture


@pytest.mark.parametrize("role", ROLES)
def test_actual_role_entry_and_market_reader_reject_VTI_before_consumer(tmp_path, role):
    policy = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    expect_scope_refusal(role_calls(tmp_path, policy)[role])
    with pytest.raises(ValueError, match="B2_dependency_forbidden"):
        read_strategy_inputs(
            tmp_path, {"VTI": dict(file="VTI.json")}, [], role=role, policy=policy
        )
    (tmp_path / "QQQ.json").write_bytes(
        canonical({"symbol": "QQQ", "rows": [{"date": "2026-01-05", "close": 100}]})
    )
    binding = {
        "QQQ": dict(
            symbol="QQQ",
            file="QQQ.json",
            sha256=sha256((tmp_path / "QQQ.json").read_bytes()),
        )
    }
    good = read_strategy_inputs(
        tmp_path, binding, ["2026-01-05"], role=role, policy=policy
    )
    assert set(good) == {"QQQ"} and good["QQQ"][0]["close"] == 100
    # Renaming a VTI payload or using an allowed filename does not grant access.
    (tmp_path / "QQQ.json").write_bytes(canonical({"symbol": "VTI", "rows": []}))
    binding["QQQ"]["sha256"] = sha256((tmp_path / "QQQ.json").read_bytes())
    with pytest.raises(ValueError, match="B2_dependency_forbidden"):
        read_strategy_inputs(tmp_path, binding, [], role=role, policy=policy)


def test_reference_benchmark_header_cannot_be_VTI_in_isolated_worker(tmp_path):
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    req = producer_fixture(tmp_path / "input", p)
    path = tmp_path / "input" / "benchmark.json"
    doc = json.loads(path.read_bytes())
    doc["symbol"] = "VTI"
    path.write_bytes(canonical(doc))
    req["inputs"]["benchmark"]["sha256"] = sha256(path.read_bytes())
    report = run_isolated(path.parent, req)
    assert report["reason"] == "scope.B2_dependency_forbidden"
    assert report["returns"] is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("import", "static_import_not_whitelisted"),
        ("guard", "guard_does_not_dominate_consumer"),
        ("reader", "file_access_not_whitelisted"),
    ],
)
def test_static_proof_rejects_new_dependency_reader_or_read_before_guard(
    monkeypatch, mutation, reason
):
    real = Path.read_bytes

    def altered(path):
        raw = real(path)
        if path.name == "folds.py":
            if mutation == "import":
                raw += b"\nimport socket\n"
            if mutation == "guard":
                raw = raw.replace(
                    b"def _features(row):\n",
                    b'def _features(row):\n    touched = row["features"]\n',
                )
            if mutation == "reader":
                raw += b"\ndef extra_reader(path):\n    return path.read_text()\n"
        return raw

    monkeypatch.setattr(Path, "read_bytes", altered)
    with pytest.raises(ValueError, match=reason):
        b2_isolation_proof(load_conventions(FIXTURES / "conventions-v1.0.1.json"))


def b2_manifest(policy):
    proof = b2_isolation_proof(policy)
    return dict(
        status="unavailable",
        reason="UNIT_EVENT_EVIDENCE_MISSING",
        missing_fields=["dividend_amount"],
        source_sha256=digest("SYNTHETIC_UNIT_SOURCE"),
        dates=list(policy.calendar),
        calendar_sha256=digest(list(policy.calendar)),
        affected_scope=["B2"],
        strategy_dependencies={r: [] for r in ROLES},
        isolation_source_sha256=proof["source_sha256"],
    )


def test_independent_B2_null_keeps_original_primary_precheck_and_full_dates():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    m = p.fold_manifest()
    m.update(
        portfolio="portfolio",
        benchmarks=["QQQ", "VTI"],
        series={
            s: [dict(date=d, close=100) for d in p.calendar]
            for s in ["portfolio", "QQQ"]
        },
        b2_manifest=b2_manifest(p),
        jump_reversal_policy=json.loads((FIXTURES / "spy-anomalies.json").read_bytes())[
            "jump_reversal_policy"
        ],
    )
    r = wf_manifest_check(m, conventions=p)
    assert r["ok"], r["reasons"]
    assert r["metrics"]["B2"]["value"] is None and not r["metrics"]["B2"]["available"]
    assert (
        r["metrics"]["B2"]["input_binding_present"]
        and r["metrics"]["B2"]["all_dates_retained"]
    )
    assert (
        r["metrics"]["data_bindings_complete"]
        and not r["metrics"]["all_readouts_available"]
    )
    assert len(m["calendar"]) == 3191 and len(m["folds"]) == 77
    assert not r["runtime_consumable"] and not r["certifiable"]
    for key, value in [
        ("dates", list(p.calendar)[1:]),
        ("isolation_source_sha256", "0" * 64),
        ("strategy_dependencies", {r: ["VTI"] for r in ROLES}),
        ("fallback", "SPY"),
    ]:
        bad = deepcopy(m)
        bad["b2_manifest"][key] = value
        assert wf_manifest_check(bad, conventions=p)["reasons"] == [
            "scope.B2_isolation_manifest_missing_or_invalid"
        ]

    truncated = deepcopy(m)
    for name in truncated["series"]:
        truncated["series"][name] = truncated["series"][name][-10:]
    assert wf_manifest_check(truncated, conventions=p)["reasons"] == [
        "data.QQQ_full_frozen_calendar_required"
    ]


def test_full_grid_receipt_is_consistent_but_never_claims_N_or_profitability():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    request = continuity_fixture(p)
    r = continuous_path_check(request, conventions=p)
    assert r["ok"] and r["metrics"]["state_receipt_grid_complete"]
    assert r["metrics"]["strategy_path_complete"] is None
    assert r["metrics"]["S2_admission_accepted"] is None
    assert len(r["metrics"]["folds"]) == 77
    assert r["metrics"]["A"] is r["metrics"]["IR"] is r["metrics"]["complete_N"] is None
    assert r["metrics"]["receipt_consistency_only"] and not r["certifiable"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing_fold", "all_original_folds_required"),
        ("only_valid", "invalid_fold_may_not_be_skipped"),
        ("restart", "capital_restart_forbidden"),
        ("hidden_restart", "continuous_state_link_mismatch"),
        ("refund", "OOS_budget_refund_forbidden"),
        ("erase_seen", "seen_result_may_not_be_erased"),
        ("failed_unaccounted", "failure_or_retry_not_counted"),
        ("duplicate_attempt", "fold_attempt_identity_reused"),
    ],
)
def test_invalid_path_cannot_create_fragment_stats_or_restore_budget(change, reason):
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    req = continuity_fixture(p)
    if change == "missing_fold":
        req["folds"].pop(1)
    elif change == "only_valid":
        req["valid_only"] = True
    elif change == "restart":
        req["folds"][1]["initialized"] = True
    elif change == "hidden_restart":
        row = req["folds"][1]
        row["input_state"] = deepcopy(req["folds"][0]["input_state"])
        row["input_state_sha256"] = digest(row["input_state"])
    elif change == "refund":
        req["folds"][1]["budget_state"]["consumed"] = False
    elif change == "erase_seen":
        req["folds"][1]["budget_state"]["seen_result"] = False
    elif change == "failed_unaccounted":
        req["folds"][1].update(status="failed", nav=None)
        req["folds"][1]["N_receipt"]["contribution"] = 0
    else:
        req["folds"][1]["attempt_id"] = req["folds"][0]["attempt_id"]
    r = continuous_path_check(req, conventions=p)
    assert any(reason in x for x in r["reasons"]), r["reasons"]
    assert (
        len(r["metrics"]["folds"]) == 77 and not r["metrics"]["strategy_path_complete"]
    )
    assert r["metrics"]["A"] is r["metrics"]["IR"] is r["metrics"]["interval"] is None


def test_unknown_NAV_stops_all_future_values_retains_inventory_intents_N_and_budget():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    req = continuity_fixture(p)
    req["folds"][1].update(
        status="failed",
        nav=None,
        reasons=["UNIT_NAV_UNKNOWN"],
        inventory={"QQQ": 2},
        exit_intents=["UNIT_RETAIN_EXIT"],
    )
    r = continuous_path_check(req, conventions=p)
    assert not r["ok"]
    folds = r["metrics"]["folds"]
    assert all(x["nav"] is None for x in folds[1:])
    assert folds[1]["inventory"] == {"QQQ": 2} and folds[1]["exit_intents"] == [
        "UNIT_RETAIN_EXIT"
    ]
    assert (
        folds[1]["budget_state"]["consumed"]
        and folds[1]["N_receipt"]["contribution"] == 1
    )
    assert all(x["status"] == "blocked" for x in folds[2:])
    assert all(
        x["inventory"] == {"QQQ": 2} and x["exit_intents"] == ["UNIT_RETAIN_EXIT"]
        for x in folds[2:]
    )


class FailingMiner:
    def mine(self, train):
        raise RuntimeError("UNIT_FAILURE")


def test_actual_fold_mechanism_stops_after_failure_and_persists_all_77_records(
    tmp_path,
):
    calendar = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(237)]
    folds = [
        dict(
            fold_id=str(i),
            train_start=calendar[3 * i],
            train_end=calendar[3 * i + 1],
            test_start=calendar[3 * i + 3],
            test_end=calendar[3 * i + 4],
        )
        for i in range(77)
    ]
    budget = {
        "consumed": True,
        "seen_result": True,
        "authorization_sha256": digest("UNIT_LICENSE"),
    }
    m = dict(
        calendar=calendar,
        folds=folds,
        label_horizon=1,
        embargo=0,
        budget_state_by_fold={f["fold_id"]: budget for f in folds},
    )
    rows = [
        dict(
            date=d,
            features={"unit": 1},
            target=0,
            label_end=calendar[min(i + 1, len(calendar) - 1)],
        )
        for i, d in enumerate(calendar)
    ]
    calls = []

    def factory(ctx):
        calls.append(ctx.fold_id)
        return FailingMiner()

    ledger = AttemptLedger(tmp_path / "unit.sqlite")
    for run in ["UNIT_FAILURE", "UNIT_NEW_RETRY"]:
        r = _run_walk_forward_unbound(
            m,
            rows,
            miner_factory=factory,
            fitter_factory=lambda ctx: object(),
            ledger=ledger,
            run_id=run,
        )
        assert len(r["metrics"]["folds"]) == 77
        assert r["metrics"]["folds"][0]["status"] == "invalid"
        assert all(x["status"] == "blocked" for x in r["metrics"]["folds"][1:])
        assert r["metrics"]["A"] is r["metrics"]["IR"] is None
    assert calls == ["0", "0"] and ledger.snapshot()["local_attempts_n"] == 2
    for f in folds:
        row = AttemptLedger(ledger.path).recorded(
            "walk-forward-status/UNIT_FAILURE/" + f["fold_id"]
        )
        assert row["budget_state"] == budget


def test_formal_pending_path_also_retains_all_77_folds_without_invoking_adapters():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    calls = []
    r = run_walk_forward(
        p.fold_manifest(),
        [],
        miner_factory=lambda *a: calls.append(a),
        fitter_factory=lambda *a: calls.append(a),
        ledger=None,
        run_id="UNIT",
        conventions=p,
    )
    assert len(r["metrics"]["folds"]) == 77 and not calls
    assert all(
        not x["attempted"] and x["predictions"] is None for x in r["metrics"]["folds"]
    )


def test_S2_missing_SR_N_V_never_becomes_empty_QQQ_pool():
    p = load_conventions(FIXTURES / "conventions-v1.0.1.json")
    with pytest.raises(ValueError, match="S2_unavailable_not_empty"):
        select_pool({}, {}, p, [])


def test_four_required_minimum_scope_negatives(tmp_path):
    r = cases(tmp_path, load_conventions(FIXTURES / "conventions-v1.0.1.json"))
    assert len(r) == 4 and all(c["status"] == "PASS" for c in r)

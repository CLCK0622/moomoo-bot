import json

import pytest

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import ConventionConflict, load_conventions
from qlab.dynamic_factor.execution import (
    OrderCosts,
    calibrate_gain,
    initial_build_turnover_check,
    lock_startup_intent,
    nav_increment,
    startup_intent,
    voluntary_trade_gate,
)
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.pending import pool_admission_check
from qlab.dynamic_factor.pipeline import oos_dsr, read_pinned, run_train_pipeline
from qlab.dynamic_factor.statistics import dsr_eval
from qlab.dynamic_factor.v02_harness import (
    run_synthetic,
    synthetic_callbacks,
    synthetic_context,
    synthetic_ledger,
    synthetic_gain_rows,
    synthetic_registry,
)


def test_v02_exact_raw_and_profile_are_bound():
    p = load_conventions()
    assert p.binding["conventions_version"] == "v0.2"
    assert (
        p.raw_sha256
        == "b873b30b754695bef82ff37b95fc7628b0cc45ad7eb76e9cb091f9164cfc0a17"
    )
    assert p.family_size == 17
    assert p.profile["variance_layers"] == p.document["variance_layers"]


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["variance_layers"]["steps"][2].update(depends_on=["S4"]),
        lambda p: p["variance_layers"].update(
            meta_results_feedback_to_candidate_admission=True
        ),
        lambda p: p["initialization"].update(upward_startup_exception=True),
        lambda p: p["gain_model"].update(label_return_times_horizon_again=True),
        lambda p: p["V"].update(candidate_formula="meta_reference_V"),
        lambda p: p["benchmark_missing_days"].update(forward_fill="allow"),
    ],
)
def test_v02_conflicting_companion_or_contract_refused(tmp_path, change):
    document = load_conventions().document
    change(document)
    raw = json.dumps(document).encode()
    path = tmp_path / "altered.json"
    path.write_bytes(raw)
    with pytest.raises(ConventionConflict):
        load_conventions(path, expected_sha256=sha256(raw))


def test_separate_layers_no_meta_feedback_and_no_duplicate_probe_N(tmp_path):
    p = load_conventions()
    out, ledger, calls = run_synthetic(tmp_path / "unit.sqlite", p)
    candidate, meta = out["candidate"], out["meta"]
    assert out["reason"] is None and len(calls) == 17
    assert candidate["pool"] == ["F4-L060"]
    assert candidate["trials_variance"] == pytest.approx(0.005)
    assert meta["trials_variance"] > candidate["trials_variance"]
    assert meta["dsr"] < 0.95
    assert candidate["gate_n"] == 63 and meta["gate_n"] == 64
    assert ledger.snapshot()["local_counted_n"] == 17
    candidate_hash = digest(ledger.recorded("v02/synthetic/0/S2"))
    r = pool_admission_check(
        {"run_id": "synthetic", "fold_id": "0", "candidate_id": "F4-L060"},
        conventions=p,
        ledger=ledger,
    )
    assert r["metrics"]["dsr"] >= 0.95 and r["metrics"]["pool"] == candidate["pool"]
    assert not r["certifiable"]
    assert digest(ledger.recorded("v02/synthetic/0/S2")) == candidate_hash
    # A delivery retry reads sealed results; a second evaluation cannot run.
    probe, meta_cb = synthetic_callbacks(p, synthetic_context(p), [])
    with pytest.raises(ValueError, match="already_consumed"):
        run_train_pipeline(
            policy=p,
            ledger=ledger,
            run_id="synthetic",
            context=synthetic_context(p),
            registry=synthetic_registry(p, synthetic_context(p)),
            proposals=[],
            probe=probe,
            build_meta=meta_cb,
            self_report_n=1,
        )


@pytest.mark.parametrize(
    "layer,field,value",
    [
        ("candidate", "profile_id_and_sha256", {"id": "v01", "sha256": "a" * 64}),
        ("candidate", "source_run_id", "synthetic"),
        ("candidate", "derived_from_runs", ["synthetic"]),
        ("candidate", "scale", "annual"),
        ("candidate", "train_calendar_sha256", "a" * 64),
        ("candidate", "universe_and_data_sha256", "a" * 64),
        ("candidate", "cost_model_sha256", "a" * 64),
        ("candidate", "source_returns_sha256", "a" * 64),
        (
            "meta",
            "profile_id_and_sha256",
            {"id": "CANDIDATE_PROBE_V02", "sha256": "a" * 64},
        ),
    ],
)
def test_reference_provenance_scale_window_and_layer_mismatch(
    tmp_path, layer, field, value
):
    p = load_conventions()
    context = synthetic_context(p)
    registry = synthetic_registry(p, context)
    trial = registry["document"][layer]["members"][0]
    registry["document"][layer]["trials"][trial][field] = value
    # Simulates a separately pinned but incompatible external registry, not a hash error.
    registry["sha256"] = registry["semantic_sha256"] = digest(registry["document"])
    out, ledger, calls = run_synthetic(tmp_path / "unit.sqlite", p, registry=registry)
    assert out["meta"] is None and out["reason"].startswith("dsr.reference")
    if layer == "candidate":
        assert out["candidate"] is None and "meta" not in calls
        assert ledger.snapshot()["local_counted_n"] == 16
    else:
        assert out["candidate"]["pool"] == ["F4-L060"]
        assert calls.count("meta") == 1
        assert ledger.recorded("v02/synthetic/0/S2")["pool"] == ["F4-L060"]


def test_failed_probe_persists_all_attempts_no_winner_subset_or_empty_pool(tmp_path):
    p = load_conventions()
    out, ledger, calls = run_synthetic(tmp_path / "unit.sqlite", p, failed="F1-L005")
    assert out["reason"] == "pipeline.candidate_family_incomplete"
    assert len(calls) == 16 and "meta" not in calls
    assert out["candidate"] is None and out["meta"] is None
    assert ledger.snapshot()["local_counted_n"] == 16
    assert any(e.get("status") == "failed" for e in ledger.snapshot()["events"])


@pytest.mark.parametrize(
    "registry,complete,reason",
    [
        (False, True, "dsr.candidate_reference_missing"),
        (True, False, "ledger_history_incomplete"),
    ],
)
def test_missing_external_V_or_complete_N_does_not_build_meta(
    tmp_path, registry, complete, reason
):
    p = load_conventions()
    out, ledger, calls = run_synthetic(
        tmp_path / "unit.sqlite", p, complete=complete, registry=registry
    )
    assert out["reason"] == reason and out["candidate"] is None
    assert "meta" not in calls
    r = dsr_eval(
        {"run_id": "synthetic", "fold_id": "0", "layer": "meta"}, ledger, conventions=p
    )
    assert r["metrics"]["dsr"] is None and not r["certifiable"]
    assert reason in r["reasons"]
    if not complete:
        assert (
            r["metrics"]["cumulative_n"] is None
            and r["metrics"]["cumulative_n_lower_bound"] == 63
        )


def test_unverified_price_basis_stops_before_callbacks(tmp_path):
    p = load_conventions()
    context = synthetic_context(p)
    context["price_basis_receipt"]["total_return_basis_verified"] = False
    out, _, calls = run_synthetic(tmp_path / "unit.sqlite", p, context=context)
    assert out["reason"] == "data.price_basis_unverified" and not calls


def test_registry_read_requires_raw_sha_and_detects_mutation(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text('{"candidate": {}}\n')
    pinned = read_pinned(path, sha256(path.read_bytes()))
    assert pinned["semantic_sha256"] == digest(pinned["document"])
    with pytest.raises(ValueError, match="hash_mismatch"):
        read_pinned(path, "a" * 64)


def startup_request(
    p,
    ledger,
    *,
    position=0,
    cash=15000,
    inventory=None,
    start_id="unit-start",
    scope="test-forward",
):
    inventory = inventory or {}
    nav = cash + inventory.get("QQQ", 0) * 100
    sessions = list(p.calendar[100:110])
    close = sessions[position] + "T16:00:00"
    intent = lock_startup_intent(
        position,
        nav,
        inventory,
        close,
        policy=p,
        ledger=ledger,
        start_id=start_id,
        scope_id=scope,
    )
    return {
        "intent": intent,
        "context": synthetic_context(p),
        "cash": cash,
        "previous_close": close,
        "reference_sessions": sessions,
        "raw_open_prices": {"QQQ": 100},
        "open_timestamp": sessions[position + 1] + "T09:30:00",
        "sell_date": sessions[position + 1],
        "rate_basis": "research_restored",
        "start_id": start_id,
    }


def test_staged_initialization_cash_fees_integer_and_no_extension(tmp_path):
    p = load_conventions()
    ledger = AttemptLedger(tmp_path / "unit.sqlite")
    cash, inventory = 15000, {}
    quantities = []
    for pos in range(6):
        req = startup_request(p, ledger, position=pos, cash=cash, inventory=inventory)
        r = initial_build_turnover_check(req, conventions=p, ledger=ledger)
        assert r["ok"], r["reasons"]
        m = r["metrics"]
        assert m["one_way_turnover"] <= 0.2 and type(m["quantity"]) is int
        cash, inventory = m["cash"], m["inventory"]
        assert cash >= 0.02 * (cash + inventory["QQQ"] * 100)
        quantities.append(m["quantity"])
        if pos == 5:
            assert m["regular_signal_due"] is True
    assert quantities[0] == 60 and quantities[3:] == [0, 0, 0]
    assert sum(quantities) < 147  # fees/cash reserve prevent nominal 98% rounding.
    with pytest.raises(ValueError, match="record_conflict"):
        startup_request(
            p, ledger, start_id="restart-at-next-fold", scope="test-forward"
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda r: r["raw_open_prices"].update(QQQ=None), "raw_open_price_invalid"),
        (lambda r: r["intent"].update(max_buy_notional=14700), "intent_not_locked"),
        (lambda r: r.update(previous_close="2000-01-01"), "intent_not_locked"),
        (lambda r: r.update(open_timestamp=r["previous_close"]), "intent_not_locked"),
        (lambda r: r.update(rate_basis="invented_zero_fees"), "rate_basis_unknown"),
    ],
)
def test_startup_missing_or_mutated_inputs_never_fabricate_fill(
    tmp_path, change, reason
):
    p = load_conventions()
    ledger = AttemptLedger(tmp_path / "unit.sqlite")
    req = startup_request(p, ledger)
    change(req)
    r = initial_build_turnover_check(req, conventions=p, ledger=ledger)
    assert not r["ok"] and r["metrics"]["quantity"] is None
    assert any(reason in s for s in r["reasons"])
    assert ledger.recorded("startup/unit-start/0") is None


def test_first_open_E0_no_98pct_upward_exception():
    p = load_conventions()
    assert (
        startup_intent(0, 15000, {}, "2026-01-01T16:00:00", p)["max_buy_notional"]
        == 6000
    )
    with pytest.raises(ValueError, match="zero_inventory"):
        startup_intent(0, 15000, {"QQQ": 1}, "2026-01-01T16:00:00", p)


@pytest.mark.parametrize(
    "M,P,alpha,mu,cM,cP,G,K,allow",
    [
        ({}, {"S": 20}, {"S": 0.01}, 0, 0, 30, 0.002, 0.003, False),
        ({"QQQ": 20}, {"S": 20}, {"S": 0.02}, 0.03, 10, 10, 0.004, 0, True),
        ({"S": 20}, {"QQQ": 20}, {"S": 0.02}, 0.03, 10, 10, -0.004, 0, False),
        ({}, {"QQQ": 20}, {}, 0.03, 20, 10, 0.006, 0, True),
        ({}, {"S": 20}, {"S": 0.01}, 0, 0, 20, 0.002, 0.002, False),
    ],
)
def test_gain_NAV_units_old_new_QQQ_cash_and_cost_floor(
    M, P, alpha, mu, cM, cP, G, K, allow
):
    out = nav_increment(M, P, {"S": 100, "QQQ": 100}, alpha, mu, 10000, cM, cP)
    assert out["G_H10"] == pytest.approx(G)
    assert out["K"] == pytest.approx(K)
    assert out["allowed"] is allow


def calibration_fixture(p, context):
    ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
    d = context["train_calendar"][0]
    rows = [
        {
            "date": d,
            "symbol": f"S{i:03}",
            "label_end": context["train_calendar"][11],
            "label_entry": context["train_calendar"][1],
            "stock_h10": 0.02 + i * 0.001,
            "qqq_h10": 0.01,
            "ranks": {k: (i + 0.5) / 50 for k in ids},
        }
        for i in range(50)
    ]
    return rows, calibrate_gain(rows, {d}, conventions=p, context=context)


def test_calibration_full_buckets_and_mature_labels_no_interpolation():
    p = load_conventions()
    context = synthetic_context(p)
    rows, cal = calibration_fixture(p, context)
    assert cal["mu_Q"] == 0.01
    assert cal["m"]["F1-L005"][0] == pytest.approx(0.012)
    with pytest.raises(ValueError, match="panel_incomplete"):
        calibrate_gain(rows[:-1], {rows[0]["date"]}, conventions=p, context=context)
    with pytest.raises(ValueError, match="outside_mature_train"):
        calibrate_gain(rows, set(), conventions=p, context=context)
    rows[0]["ranks"]["F1-L005"] = None
    with pytest.raises(ValueError, match="rank_invalid"):
        calibrate_gain(rows, {rows[0]["date"]}, conventions=p, context=context)


def gain_request(p, ledger):
    context = synthetic_context(p)
    cal = ledger.recorded("v02/synthetic/0/S1")["calibration"]
    chosen = ledger.recorded("v02/synthetic/0/S2")["pool"][0]
    r = {
        "run_id": "synthetic",
        "fold_id": "0",
        "account_scope": "unit-account",
        "signal_close": context["train_calendar"][-1],
        "context": context,
        "M": {"QQQ": 80},
        "P": {"QQQ": 60, "S": 20},
        "original_inventory": {"QQQ": 80},
        "raw_open_prices": {"QQQ": 100, "S": 100},
        "cash": 2000,
        "pool": [chosen],
        "factor_states": {chosen: 1},
        "ranks": {"S": {chosen: 0.05}},
        "calibration": cal,
        "required_exit_symbols": [],
        "execution_date": p.calendar[
            p.calendar.index(context["train_calendar"][-1]) + 1
        ],
        "sell_date": p.calendar[p.calendar.index(context["train_calendar"][-1]) + 1],
        "rate_basis": "research_restored",
    }
    r["feasibility_receipt"] = {
        "source_sha256": digest("synthetic_planner"),
        "plans_sha256": digest(
            {
                k: r[k]
                for k in ("M", "P", "original_inventory", "raw_open_prices", "cash")
            }
        ),
        "all_constraints_verified": True,
    }
    return r


def test_gain_complete_plans_netted_costs_and_unknown_forecast_keeps_M(tmp_path):
    p = load_conventions()
    _, ledger, _ = run_synthetic(tmp_path / "gain.sqlite", p)
    req = gain_request(p, ledger)
    r = voluntary_trade_gate(req, conventions=p, ledger=ledger)
    assert r["ok"] and not r["certifiable"]
    assert r["metrics"]["G_H10"] == pytest.approx(0.2 * 0.012)
    costs = OrderCosts(p, req["sell_date"], req["rate_basis"])
    assert r["metrics"]["C2_P"] == costs.quote(
        {"QQQ": -20, "S": 20}, req["raw_open_prices"]
    )
    req["ranks"] = {}
    req["account_scope"] = "separate-unit-account"
    missing = voluntary_trade_gate(req, conventions=p, ledger=ledger)
    assert not missing["ok"] and missing["metrics"]["G_H10"] is None
    assert (
        missing["metrics"]["allowed"] is False
        and missing["metrics"]["selected_holdings"] == req["M"]
    )


def test_gain_no_post_approval_plan_change_or_required_exit_undo(tmp_path):
    p = load_conventions()
    _, ledger, _ = run_synthetic(tmp_path / "gain.sqlite", p)
    req = gain_request(p, ledger)
    req["P"]["S"] = 21
    assert voluntary_trade_gate(req, conventions=p, ledger=ledger)["reasons"] == [
        "gain.final_plan_feasibility_missing"
    ]
    req = gain_request(p, ledger)
    req["required_exit_symbols"] = ["S"]
    assert voluntary_trade_gate(req, conventions=p, ledger=ledger)["reasons"] == [
        "gain.optional_plan_undoes_required_exit"
    ]


def test_oos_uses_every_frozen_fold_max_no_new_OOS_reference_controls():
    p = load_conventions()
    receipts = {
        str(i): {
            "conventions_sha256": p.raw_sha256,
            "stage_ledger_hash": digest(i),
            "trials_variance": v,
        }
        for i, v in enumerate([0.01, 0.02, 0.005])
    }
    n = {"gate_n": 100, "n_complete": True}
    r = oos_dsr([-0.01, 0.02, 0.03] * 20, receipts, ["0", "1", "2"], n, p)
    assert r["trials_variance"] == 0.02 and not r["certifiable"]
    with pytest.raises(ValueError, match="missing"):
        oos_dsr([-0.01, 0.02], receipts, ["0", "1", "2", "3"], n, p)
    with pytest.raises(ValueError, match="missing"):
        oos_dsr([-0.01, 0.02], receipts, ["0", "1", "2"], dict(n, n_complete=False), p)


@pytest.mark.parametrize("bad_receipt", [False, True])
def test_v02_fold_train_only_order_and_full_history_rejection(tmp_path, bad_receipt):
    from dataclasses import asdict
    from qlab.dynamic_factor.folds import FitReceipt, run_walk_forward

    p = load_conventions()
    manifest = p.fold_manifest()
    calendar = manifest["calendar"]
    fold = manifest["folds"][0]
    context = synthetic_context(p)
    manifest.update(
        research_context_by_fold={fold["fold_id"]: context},
        reference_registry=synthetic_registry(p, context),
        self_report_n=1,
    )
    rows = [
        dict(
            date=d,
            features={"x": i},
            target=0.01,
            label_entry=calendar[
                min(i + manifest["label_entry_offset"], len(calendar) - 1)
            ],
            label_end=calendar[min(i + manifest["label_horizon"], len(calendar) - 1)],
            template_end=calendar[
                min(i + manifest["template_path_offset"], len(calendar) - 1)
            ],
        )
        for i, d in enumerate(calendar)
    ]
    ids = p.document["variance_layers"]["family_definitions"]["candidate_members"]
    calls = []
    probe_cb, meta_cb = synthetic_callbacks(p, context, calls)

    class Miner:
        def mine(self, train):
            assert train[-1].template_end == fold["history_end"]
            return [{"id": x} for x in ids]

    class Model:
        def predict(self, test):
            assert test[0].date == fold["test_start"]
            assert not hasattr(test[0], "target")
            raise ValueError("synthetic_stop_before_predictions")

    class Fitter:
        def probe(self, train, history, proposal, profile):
            assert len(history) == p.document["folds"]["train_days"]
            assert len(train) == len(history) - manifest["template_path_offset"]
            assert history[-1].date < fold["test_start"]
            out = probe_cb(proposal, profile)
            return dict(
                out,
                fit_dates=[r.date for r in train],
                train_sha256=digest([asdict(r) for r in train]),
            )

        def calibration_rows(self, train, history, proposals):
            assert len(calls) == 16
            return synthetic_gain_rows(p, context)

        def fit_meta(self, train, history, proposals, pool, calibration):
            assert len(calls) == 16 and pool == ("F4-L060",)
            dates = tuple(r.date for r in train)
            receipt = FitReceipt(
                Model(),
                ("full-history",) if bad_receipt else dates,
                digest([asdict(r) for r in train]),
                digest(proposals),
            )
            return dict(meta_cb(pool, calibration), receipt=receipt)

    ledger = synthetic_ledger(tmp_path / "fold-unit.sqlite", p, complete=True)
    r = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: Miner(),
        fitter_factory=lambda ctx: Fitter(),
        ledger=ledger,
        run_id="unit-fold",
        conventions=p,
    )
    assert calls.count("meta") == 1 and len(calls) == 17
    reason = (
        "wf.full_history_or_mutated_fit_rejected"
        if bad_receipt
        else "synthetic_stop_before_predictions"
    )
    assert reason in r["reasons"]
    assert ledger.snapshot()["local_counted_n"] == 17
    assert (ledger.recorded("v02/unit-fold/0/0/S4") is None) is bad_receipt


def test_gain_delivery_retry_is_identical_and_second_subset_is_refused(tmp_path):
    p = load_conventions()
    _, ledger, _ = run_synthetic(tmp_path / "gain.sqlite", p)
    req = gain_request(p, ledger)
    first = voluntary_trade_gate(req, conventions=p, ledger=ledger)
    before = ledger.snapshot()
    assert voluntary_trade_gate(req, conventions=p, ledger=ledger) == first
    assert ledger.snapshot() == before
    req["P"]["S"] = 10
    req["feasibility_receipt"]["plans_sha256"] = digest(
        {k: req[k] for k in ("M", "P", "original_inventory", "raw_open_prices", "cash")}
    )
    second = voluntary_trade_gate(req, conventions=p, ledger=ledger)
    assert second["reasons"] == ["ledger.record_conflict"]
    assert second["metrics"]["G_H10"] is None
    assert ledger.snapshot() == before


def test_retired_recipes_do_not_resurrect_and_valid_empty_pool_is_distinct(tmp_path):
    p = load_conventions()
    context = synthetic_context(p)
    context["retired_ids"] = p.document["variance_layers"]["family_definitions"][
        "candidate_members"
    ]
    out, _, calls = run_synthetic(tmp_path / "retired.sqlite", p, context=context)
    assert out["reason"] is None and out["candidate"]["pool"] == []
    assert (
        calls.count("meta") == 1
    )  # fixed base-only policy, not a missing-input default.


def test_uncalculable_correlation_isolates_candidate_and_keeps_V_population():
    from qlab.dynamic_factor.pipeline import select_pool

    p = load_conventions()
    evaluations = {
        k: {"mean": m, "dsr": 0.99} for k, m in [("bad", 3), ("good", 2), ("other", 1)]
    }
    scores = {
        "bad": {"d": {str(i): 1 for i in range(50)}},
        "good": {"d": {str(i): i for i in range(50)}},
        "other": {"different": {str(i): i for i in range(50)}},
    }
    selected = select_pool(evaluations, scores, p, [])
    assert selected["pool"] == ["good"]
    assert set(selected["isolated"]) == {"bad", "other"}


def test_calibration_rejects_mismatched_H10_interval():
    p = load_conventions()
    context = synthetic_context(p)
    rows, _ = calibration_fixture(p, context)
    rows[0]["label_end"] = context["train_calendar"][10]
    with pytest.raises(ValueError, match="interval_mismatch"):
        calibrate_gain(rows, {rows[0]["date"]}, conventions=p, context=context)


def test_v02_corrupt_ledger_readout_remains_null(tmp_path):
    import sqlite3

    p = load_conventions()
    ledger = AttemptLedger.from_conventions(tmp_path / "ledger.sqlite", p)
    ledger.record("unit", {"value": 1})
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE events SET body = '{}' WHERE seq=1")
    r = dsr_eval(
        {"run_id": "unit", "fold_id": "0", "layer": "meta"}, ledger, conventions=p
    )
    assert r["reasons"] == ["ledger_unreadable_or_corrupt"]
    assert r["metrics"]["dsr"] is None and r["metrics"]["cumulative_n"] is None


@pytest.mark.parametrize("price,quantity", [(50, 100), (1375, 1)])
def test_complete_plan_quote_preserves_existing_fee_frontier_mapping(price, quantity):
    from qlab.dynamic_factor.fees import FIXTURES, fee_frontier

    p = load_conventions()
    costs = OrderCosts(p, "2027-01-04", "effective_date")
    expected = fee_frontier(
        dict(
            price=price,
            ticket_usd=price * quantity,
            gross_edge_bps=0,
            sell_date="2027-01-04",
            rate_basis="effective_date",
            pnl_basis="reference",
        ),
        FIXTURES / "fee_params_x2.json",
        conventions=p,
    )
    quoted = costs.quote({"S": quantity}, {"S": price}) + costs.quote(
        {"S": -quantity}, {"S": price}
    )
    assert quoted == pytest.approx(
        expected["metrics"]["gate_cost_bps"] * price * quantity / 1e4
    )
    assert "费用政策待 EVO-883 下一版" in expected["assumptions"]

from copy import deepcopy

import pytest

from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.continuity import continuous_path_check
from qlab.dynamic_factor.harness_helpers import fixture_ledger
from qlab.dynamic_factor.pending import pool_admission_check
from qlab.dynamic_factor.pipeline import run_train_pipeline
from qlab.dynamic_factor.scope_harness import continuity_fixture
from qlab.dynamic_factor.state_v2 import state_transition_check


def synthetic_state():
    return dict(
        inventory={"APD": 2},
        cash=100.0,
        age={"APD": 30},
        origin={"APD": "SYNTHETIC_ORIGIN"},
        rights={"child": 1.0},
        receivables={"cash_event": 2.0},
        unknown_components=[],
        nav=302.0,
        initialization_count=1,
    )


def test_isolation_preserves_known_inventory_age_origin_rights_receivables_cash():
    before = synthetic_state()
    r = state_transition_check(dict(before=before, after=deepcopy(before)))
    assert r["ok"] and r["metrics"]["next_state"] == before
    assert not r["metrics"]["new_exit_policy"] and not r["certifiable"]


@pytest.mark.parametrize(
    "field", ["inventory", "cash", "age", "origin", "rights", "receivables", "nav"]
)
def test_quarantining_a_held_name_must_not_erase_state(field):
    before = synthetic_state()
    after = deepcopy(before)
    after[field] = {} if isinstance(after[field], dict) else 0
    r = state_transition_check(dict(before=before, after=after))
    assert not r["ok"] and r["metrics"]["R2_stop"]
    assert r["metrics"]["next_state"] is None
    assert r["metrics"]["last_known_state"] == before


@pytest.mark.parametrize(
    "field", ["cash", "nav", "rights", "receivables", "origin", "age"]
)
def test_unknown_necessary_state_cannot_become_last_price_zero_or_sale(field):
    before = synthetic_state()
    before[field] = None
    r = state_transition_check(dict(before=before, after=synthetic_state()))
    assert r["reasons"] == ["state.R2_necessary_state_unknown"]
    assert r["metrics"]["last_known_state"][field] is None
    assert r["metrics"]["next_state"] is None


@pytest.mark.parametrize("flag", ["skip_fold", "restart_capital", "valid_only"])
def test_R2_cannot_skip_fold_reset_capital_or_stitch_good_fragments(flag):
    request = dict(before=synthetic_state(), after=synthetic_state(), **{flag: True})
    assert state_transition_check(request)["reasons"] == [
        "state.skip_or_capital_reset_forbidden"
    ]


def test_no_new_isolation_liquidation_or_minimum_age_exception():
    before, after = synthetic_state(), synthetic_state()
    after["inventory"] = {}
    receipt = dict(
        event_type="isolation_forced_exit",
        source_sha256=digest("synthetic"),
        before_state_sha256=digest(before),
        after_state_sha256=digest(after),
        common_profile_sha256=load_conventions().binding["common_profile_sha256"],
        changed_fields=["inventory"],
    )
    r = state_transition_check(
        dict(before=before, after=after, transition_receipts=[receipt])
    )
    assert r["reasons"] == ["state.original_transition_receipt_required"]


def complete_grid(p):
    request = continuity_fixture(p)
    for row in request["folds"]:
        for key in ("input_state", "output_state"):
            row[key].update(origin={}, rights={}, receivables={}, unknown_components=[])
            row[key + "_sha256"] = digest(row[key])
    return request


def test_full_v2_grid_and_R2_keep_all77_folds_and_raw_state():
    p = load_conventions()
    request = complete_grid(p)
    assert continuous_path_check(request, conventions=p)["ok"]
    request["folds"][2]["output_state"]["rights"] = {"VSNT": None}
    request["folds"][2]["output_state_sha256"] = digest(
        request["folds"][2]["output_state"]
    )
    r = continuous_path_check(request, conventions=p)
    assert not r["ok"] and len(r["metrics"]["folds"]) == 77
    assert "state.R2_necessary_state_unknown" in r["reasons"]
    for row in r["metrics"]["folds"][3:]:
        assert (
            row["nav"] is None
            and row["last_known_state"] == request["folds"][2]["input_state"]
        )
    assert r["metrics"]["A"] is r["metrics"]["IR"] is None


def test_missing_S2_does_not_build_QQQ_meta_delete_fold_or_register_performance(
    tmp_path,
):
    p = load_conventions()
    ledger = fixture_ledger(tmp_path / "synthetic.sqlite", p)
    before = ledger.snapshot()

    def forbidden(*a, **kw):
        raise AssertionError("performance producer called")

    out = run_train_pipeline(
        policy=p,
        ledger=ledger,
        run_id="synthetic",
        context={},
        registry=None,
        proposals=[],
        probe=forbidden,
        build_meta=forbidden,
        self_report_n=1313,
    )
    assert out["candidate"] is out["meta"] is None
    r = pool_admission_check({}, conventions=p, ledger=ledger)
    assert r["metrics"]["pool"] is r["metrics"]["fallback_holdings"] is None
    assert ledger.snapshot() == before


@pytest.mark.parametrize(
    "verified,unknown,reason",
    [(49, 0, "VERIFIED_LT50"), (49, 1, "UNKNOWN"), (50, 0, "isolated_optional_buy")],
)
def test_trade_consumer_keeps_computable_M_without_fabricating_tilt(
    tmp_path, verified, unknown, reason
):
    from qlab.dynamic_factor.execution import voluntary_trade_gate
    from qlab.dynamic_factor.isolation import seal_manifest
    from qlab.dynamic_factor.ledger import AttemptLedger
    from qlab.dynamic_factor.v1_harness import unit_context
    from test_v2_isolation import synthetic_manifest

    p = load_conventions()
    ledger = AttemptLedger(tmp_path / "synthetic-plans.sqlite")
    state = dict(
        inventory={"QQQ": 1},
        cash=14900,
        age={"QQQ": 30},
        origin={"QQQ": "SYNTHETIC"},
        rights={},
        receivables={},
        unknown_components=[],
        nav=15000,
    )
    req = dict(
        context=unit_context(p),
        account_scope="SYNTHETIC",
        signal_close=p.calendar[600],
        execution_date=p.calendar[601],
        sell_date=p.calendar[601],
        run_id="SYNTHETIC",
        fold_id="0",
        rate_basis="research_restored",
        M={"QQQ": 1},
        P={"QQQ": 1},
        original_inventory={"QQQ": 1},
        raw_open_prices={"QQQ": 100},
        cash=14900,
        calibration={},
        pool=[],
        required_exit_symbols=[],
        required_state=state,
        isolation_manifest=seal_manifest(synthetic_manifest(p, verified, unknown), p),
    )
    if verified == 50:
        isolated = p.profile["universe"][-1]
        req["P"][isolated] = 1
        req["raw_open_prices"][isolated] = 100
    req["feasibility_receipt"] = dict(
        source_sha256=digest("SYNTHETIC_FEASIBILITY"),
        all_constraints_verified=True,
        plans_sha256=digest(
            {
                k: req[k]
                for k in ("M", "P", "original_inventory", "raw_open_prices", "cash")
            }
        ),
    )
    ledger.record("v02/SYNTHETIC/0/S1", {"calibration": {}})
    ledger.record("v02/SYNTHETIC/0/S2", {"pool": []})
    r = voluntary_trade_gate(req, conventions=p, ledger=ledger)
    assert not r["ok"] and reason in r["reasons"][0]
    assert r["metrics"]["selected_holdings"] == req["M"]
    assert r["metrics"]["selected_plan"] == "M"

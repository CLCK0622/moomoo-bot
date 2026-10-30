import csv
from decimal import Decimal

import pytest

from qlab.dynamic_factor.conventions import (
    load_conventions as load_historical_conventions,
    FIXTURES,
)
from qlab.dynamic_factor.isolation import seal_manifest
from qlab.dynamic_factor.k5 import k5_dependency_check, vsnt_quote
from qlab.dynamic_factor.valuation import integer_cash_valuation
from test_v2_isolation import synthetic_manifest


def load_conventions():
    """Legacy K5 quote/entitlement cases remain explicitly bound to v2."""
    return load_historical_conventions(FIXTURES / "conventions-v2.0.0.json")


def dependency(parent, role="historical_inventory", fold="0", **kw):
    dates = dict(ADP="2014-10-01", APD="2016-10-03", CMCSA="2026-01-05")
    return dict(
        parent=parent,
        event_date=dates[parent],
        fold_id=fold,
        account_role="train_solo_probes",
        dependency_role=role,
        **kw,
    )


def test_ADP_closes_only_pre_initialization_inventory_for_every_registered_ledger():
    p = load_conventions()
    for fold in p.date_manifest["folds"]:
        for scope in ("train_solo_probes", "train_meta", "continuous_test"):
            req = dependency("ADP", fold=str(fold["fold_id"]))
            req["account_role"] = scope
            r = k5_dependency_check(req, conventions=p)
            assert r["ok"] and r["metrics"]["inventory_origin_dependency_closed"]
            assert (
                r["metrics"]["warmup_verified"]
                is r["metrics"]["TR_verified"]
                is r["metrics"]["labels_verified"]
                is None
            )
            assert r["metrics"]["dependency_value"] is None


@pytest.mark.parametrize("role", ["warmup", "TR", "label"])
def test_ADP_inventory_fact_never_certifies_warmup_TR_labels_or_252_day_release(role):
    r = k5_dependency_check(dependency("ADP", role), conventions=load_conventions())
    assert not r["ok"] and r["metrics"]["R2_stop"]
    assert r["metrics"]["dependency_value"] is None


@pytest.mark.parametrize(
    "parent,fold,scope",
    [
        ("APD", "0", "train_solo_probes"),
        ("CMCSA", "74", "train_solo_probes"),
        ("CMCSA", "72", "continuous_test"),
    ],
)
def test_reachable_candidate_paths_remain_unknown_without_actual_E_t_admission_and_contract(
    parent, fold, scope
):
    req = dependency(parent, fold=fold)
    req["account_role"] = scope
    r = k5_dependency_check(req, conventions=load_conventions())
    assert not r["ok"] and r["metrics"]["reachability"]["possible"] is None
    assert (
        r["metrics"]["entitlement"]
        is r["metrics"]["cash_available"]
        is r["metrics"]["nav"]
        is None
    )


def test_K5_paths_are_derived_per_fold_from_dates_not_static23_4_counts():
    p = load_conventions()
    early = k5_dependency_check(dependency("APD", fold="0"), conventions=p)
    late = k5_dependency_check(dependency("APD", fold="76"), conventions=p)
    assert not early["ok"] and late["ok"]
    assert (
        early["metrics"]["reachability"]["initialization"]
        != late["metrics"]["reachability"]["initialization"]
    )
    assert late["metrics"]["TR_verified"] is None


def test_preperformance_all_prior_buy_signals_excluded_closes_only_inventory_dependency():
    p = load_conventions()
    request = synthetic_manifest(p)
    row = next(r for r in request["records"] if r["symbol"] == "APD")
    row.update(
        state="QUARANTINED",
        from_date=p.calendar[0],
        to_date_or_null_with_reason=p.calendar[-1],
        gates_by_date={},
    )
    request["records"] = [row]
    sealed = seal_manifest(request, p)
    req = dependency("APD", isolation_manifest=sealed)
    r = k5_dependency_check(req, conventions=p)
    assert r["ok"] and r["metrics"]["reachability"]["possible"] is False
    assert len(r["metrics"]["reachability"]["signal_dates"]) > 1
    req["dependency_role"] = "TR"
    assert not k5_dependency_check(req, conventions=p)["ok"]


def test_VSNT_256_exact_source_fields_are_K5_quotes_only():
    rows = list(csv.DictReader((FIXTURES / "k5/VSNT-open-close-none.csv").open()))
    assert len(rows) == 128
    for row in rows:
        for field in ("raw_open", "raw_close"):
            q = vsnt_quote(row["date"], field, purpose="K5", policy=load_conventions())
            assert Decimal(q["value"]) == Decimal(row[field + "_none"])
            assert (
                q["entitlement"]
                is q["disposal_contract"]
                is q["cash_available"]
                is None
            )
            assert not q["complete_K5_execution"]


def test_known_VSNT_price_does_not_impute_entitlement_or_spend_unknown_cash():
    req = dependency("CMCSA", fold="72", quote_date="2026-01-05")
    req["account_role"] = "continuous_test"
    r = k5_dependency_check(req, conventions=load_conventions())
    assert r["metrics"]["quote"]["value"] == "40.57"
    assert (
        r["metrics"]["entitlement"]
        is r["metrics"]["receivable"]
        is r["metrics"]["cash_available"]
        is r["metrics"]["nav"]
        is None
    )
    assert r["metrics"]["R2_stop"]
    cash = integer_cash_valuation(
        dict(
            known_cash=100,
            inventory={"VSNT": 1},
            marks={"VSNT": 40.57},
            as_of="2026-01-05",
            events=[],
            k5_dependencies=[req],
        ),
        conventions=load_conventions(),
    )
    assert (
        cash["metrics"]["nav"] is None
        and cash["metrics"]["known_available_cash"] == 100
    )
    assert not cash["ok"]


@pytest.mark.parametrize(
    "attack", ["tax_fmv", "disposal", "post_result_zero", "wrong_date"]
)
def test_no_tax_FMV_raw_close_substitution_new_disposal_or_post_result_exemption(
    attack,
):
    req = dependency("APD")
    if attack == "tax_fmv":
        req.update(tax_fmv=22.50, price_basis="Form8937_FMV")
    elif attack == "disposal":
        req["force_disposal"] = True
    elif attack == "post_result_zero":
        req["observed_zero_after_performance"] = True
    else:
        req["event_date"] = "2014-01-01"
    r = k5_dependency_check(req, conventions=load_conventions())
    assert (
        not r["ok"] and r["metrics"]["dependency_value"] is r["metrics"]["nav"] is None
    )


@pytest.mark.parametrize("purpose", ["selection", "calibration", "ordinary_mark"])
def test_VSNT_quotes_cannot_enter_selection_panel(purpose):
    with pytest.raises(ValueError, match="role_or_field"):
        vsnt_quote(
            "2026-01-05", "raw_close", purpose=purpose, policy=load_conventions()
        )
    request = synthetic_manifest()
    request["records"][0]["symbol"] = "VSNT"
    with pytest.raises(ValueError, match="evidence_incomplete"):
        seal_manifest(request)


def test_VSNT_wrong_receipt_SHA_refuses_before_using_values(tmp_path, monkeypatch):
    import qlab.dynamic_factor.k5 as k5

    local = tmp_path / "k5"
    local.mkdir()
    (local / "S2-field-receipt-v1.json").write_bytes(b"{}")
    (local / "VSNT-open-close-none.csv").write_bytes(
        (FIXTURES / "k5/VSNT-open-close-none.csv").read_bytes()
    )
    monkeypatch.setattr(k5, "FIXTURES", tmp_path)
    with pytest.raises(ValueError, match="identity_mismatch"):
        vsnt_quote("2026-01-05", "raw_close", purpose="K5", policy=load_conventions())

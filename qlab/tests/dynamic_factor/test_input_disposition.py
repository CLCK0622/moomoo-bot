from qlab.dynamic_factor.authority_ledger import CURRENT_PUBLISHED
from copy import deepcopy

import pytest

from qlab.dynamic_factor.authority_ledger import AuthorityLedger
from qlab.dynamic_factor.contract import sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.disposition_harness import cases, migration_input
from qlab.dynamic_factor.input_disposition import (
    MAPPING_SHA,
    HASHES,
    cash_bindings,
    input_migration_check,
    panel_input_check,
    qqq_cash_input,
    sources,
)
from qlab.dynamic_factor.valuation import benchmark_valuation, VTI_REQUIREMENTS
from qlab.dynamic_factor.validation import wf_manifest_check
from test_authority_ledger import authority_copy, attempt, vendor
from test_v1_increment import cash_read


def test_pinned_disposition_and_all_53_cash_mappings_preserve_source_distinction():
    raw = sources()
    assert {n: sha256(b) for n, b in raw.items()} == HASHES
    rows = cash_bindings()
    assert len(rows) == 53
    row = rows["2022-12-19"]
    assert row["supported_cash_amount_per_share"] == "0.655410"
    assert row["original_declared_cash_amount"] == "1.310820"
    for ex, mapping in rows.items():
        event = qqq_cash_input(ex, 2)
        read = cash_read(event, day=ex)
        assert read["ok"], read["reasons"]
        assert read["metrics"]["receivable_amount"] == pytest.approx(
            2 * float(mapping["supported_cash_amount_per_share"])
        )
        assert read["metrics"]["account_cash_credited_amount"] is None
        assert read["metrics"]["account_cash_credited_at"] is None
        assert read["metrics"]["source_mapping_sha256"] == MAPPING_SHA


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"declared_cash_amount": 1.31082}, "valuation.QQQ_cash_amount_conflict"),
        ({"source_mapping_sha256": "0" * 64}, "valuation.QQQ_cash_mapping_missing"),
        ({"source_sha256": "0" * 64}, "valuation.QQQ_cash_source_conflict"),
        ({"ex_date": "2099-01-01"}, "valuation.QQQ_cash_mapping_missing"),
        ({"pay_date": "2022-12-29"}, "valuation.QQQ_paydate_conflict"),
    ],
)
def test_missing_or_conflicting_QQQ_input_never_becomes_receivable(change, reason):
    event = qqq_cash_input("2022-12-19", 2)
    event.update(change)
    r = cash_read(event, day="2099-01-02")
    assert reason in r["reasons"]
    assert r["metrics"]["receivable_amount"] is None and r["metrics"]["nav"] is None
    assert r["metrics"]["known_available_cash"] == 100


def test_exchange_paydate_alone_is_not_simulated_or_actual_account_arrival():
    event = qqq_cash_input("2022-12-19", 2)
    r = cash_read(event, day="2022-12-30")
    assert r["reasons"] == ["valuation.simulated_payment_availability_unknown"]
    assert r["metrics"]["available_cash"] is None
    assert r["metrics"]["receivable_amount"] == 1.31082
    event.update(
        simulated_payment_available=True,
        simulated_cash_credited_amount=1.31082,
        simulated_cash_credited_at="2022-12-30",
        simulated_payment_source_sha256="1" * 64,
    )
    r = cash_read(event, day="2022-12-30")
    assert r["ok"] and r["metrics"]["available_cash"] == pytest.approx(101.31082)
    assert r["metrics"]["inventory"] == {"QQQ": 2}
    row = r["metrics"]["dividends"][0]
    assert row["cash_ledger_kind"] == "simulation_pre_tax_integer"
    assert row["exchange_pay_date"] == "2022-12-30"
    assert row["simulated_cash_credited_amount"] == 1.31082
    assert (
        row["account_cash_credited_amount"] is row["account_cash_credited_at"] is None
    )


@pytest.mark.parametrize(
    "symbol,date,field",
    [
        ("B", "2013-11-25", "total_return"),
        ("COR", "2013-12-27", "feature"),
        ("APD", "2016-10-03", "valuation"),
        ("BA", "2019-08-08", "label"),
        ("COP", "2023-09-27", "gain"),
        ("CRH", "2010-01-04", "raw_close"),
        ("BRK.B", "2020-01-02", "raw_close"),
        ("COHR", "2020-01-02", "raw_close"),
    ],
)
def test_each_quarantined_dependency_is_null_without_replacement(symbol, date, field):
    r = panel_input_check({"inputs": [dict(symbol=symbol, date=date, field=field)]})
    assert not r["ok"] and r["metrics"]["affected_inputs"][0]["value"] is None
    assert (
        r["metrics"]["certified_usable_count"] is None
        and r["metrics"]["replacements"] == []
    )
    m = load_conventions().fold_manifest()
    m["panel_inputs"] = [dict(symbol=symbol, date=date, field=field)]
    assert wf_manifest_check(m, conventions=load_conventions())["reasons"] == [
        "data.panel_quarantined_input"
    ]


def test_quarantine_is_not_permanent_drop_or_automatic_56_member_acceptance():
    r = panel_input_check(
        {
            "inputs": [
                {
                    "symbol": "BA",
                    "date": "2019-08-07",
                    "field": "label",
                    "dependency_end": "2019-08-07",
                },
                {"symbol": "BA", "date": "2019-08-08", "field": "raw_close"},
            ]
        }
    )
    assert r["ok"] and r["metrics"]["affected_inputs"] == []
    assert not r["certifiable"] and r["metrics"]["certified_usable_count"] is None
    assert not panel_input_check({"inputs": [], "replacement_symbols": ["AAPL"]})["ok"]


def test_even_self_asserted_VTI_booleans_do_not_accept_full_period_or_suffix():
    p = load_conventions()
    r = benchmark_valuation(
        dict(
            symbol="VTI",
            price_basis="raw_close",
            raw_source_sha256="1" * 64,
            evidence={
                **{k: True for k in VTI_REQUIREMENTS},
                "source_sha256": "1" * 64,
                "profile_sha256": p.binding["common_profile_sha256"],
            },
            use_suffix=True,
            prices=[dict(date="2026-01-05", close=100)],
        )
    )
    assert r["reasons"] == ["data.VTI_formal_full_period_unavailable"]
    assert r["metrics"]["formal_return"] is r["metrics"]["analytical_index"] is None


def test_idempotent_delivery_is_distinct_from_recompute_or_retry(tmp_path):
    ledger, tip = authority_copy(tmp_path / "unit")
    writer = AuthorityLedger(ledger, tip, writable=True)
    first = writer.append(attempt())
    data = ledger.read_bytes(), tip.read_bytes()
    assert writer.append(attempt()) == first
    assert (ledger.read_bytes(), tip.read_bytes()) == data
    bad = attempt()
    bad["n_evaluated"] = 1
    with pytest.raises(ValueError, match="identity_payload_conflict"):
        writer.append(bad)
    for name in ("FAILED_RETRY", "NAN_RETRY"):
        next_state = writer.append(attempt(name))
    assert next_state["N"] == 78
    assert next_state == vendor(ledger, tip, next_state["tip"])


def test_zero_continuation_requires_explicit_existing_run_artifact_identity(tmp_path):
    ledger, tip = authority_copy(tmp_path / "unit")
    writer = AuthorityLedger(ledger, tip, writable=True)
    original = attempt()
    writer.append(original)
    continuation = dict(
        attempt("CONTINUATION"),
        n_contribution=0,
        n_trials_total=0,
        same_cells_as=original["attempt_id"],
        continuation_evidence=dict(
            kind="continuous_trial",
            attempt_id=original["attempt_id"],
            run_id=original["run_id"],
            artifact_or_log_sha256=original["evidence"][0]["sha256"],
        ),
    )
    bad = deepcopy(continuation)
    bad["continuation_evidence"]["artifact_or_log_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="same_parameter_cells_not_exempt"):
        writer.append(bad)
    assert writer.append(continuation)["N"] == 76
    assert writer.verify() == vendor(ledger, tip, writer.verify()["tip"])
    bad = dict(continuation, attempt_id="REAL_RETRY", n_evaluated=1)
    with pytest.raises(ValueError, match="same_parameter_cells_not_exempt"):
        writer.append(bad)


def test_same_chain_versioned_input_migration_receipt_binds_current_tip_and_both_QQQ_sources(
    tmp_path,
):
    ledger, tip = authority_copy(tmp_path / "unit", latest=True)
    writer = AuthorityLedger(ledger, tip, writable=True)
    before = ledger.read_bytes(), tip.read_bytes()
    request = migration_input(writer)
    r = input_migration_check(request, writer)
    receipt = r["metrics"]["receipt"]
    assert r["ok"] and receipt["old_anchor"]["tip"] == CURRENT_PUBLISHED["tip"]
    assert (
        receipt["new_anchor"]["N"] == 280 and receipt["new_anchor"]["sequence"] == 182
    )
    assert receipt["complete_N"] is None and not receipt["installed"]
    assert (
        not receipt["SQLite_conversion_accepted"]
        and not receipt["project_path_change_accepted"]
    )
    assert (ledger.read_bytes(), tip.read_bytes()) == before
    writer.append(attempt())
    replay = input_migration_check(request, writer)
    assert replay["reasons"] == ["ledger.migration_old_anchor_mismatch"]
    assert replay["metrics"]["receipt"] is None


def test_five_required_disposition_negatives(tmp_path):
    report = cases(tmp_path, load_conventions())
    assert len(report) == 5 and all(r["status"] == "PASS" for r in report)


def test_higher_self_report_is_retained_as_high_water_without_claiming_complete_N(
    tmp_path,
):
    ledger, tip = authority_copy(tmp_path / "unit")
    writer = AuthorityLedger(ledger, tip, writable=True)
    writer.append(dict(event="self_report_n", value=500))
    snap = writer.snapshot()
    assert snap["recorded_N"] == 75 and snap["n_high_water"] == 500
    assert snap["cumulative_n_lower_bound"] == 500 and snap["cumulative_n"] is None
    assert not snap["n_complete"] and snap["complete_N"] is None


def test_malformed_panel_dependency_refuses_with_a_structured_receipt():
    report = panel_input_check({"inputs": [{"symbol": "BA"}]})
    assert not report["ok"] and report["metrics"]["affected_inputs"] is None
    assert report["reasons"] == ["data.panel_input_missing_or_invalid"]


def test_pre_event_signal_label_crossing_unresolved_event_is_also_quarantined():
    row = dict(
        symbol="BA",
        date="2019-08-01",
        field="label",
        dependency_start="2019-08-02",
        dependency_end="2019-08-15",
    )
    r = panel_input_check({"inputs": [row]})
    assert r["reasons"] == ["data.panel_quarantined_input"]
    assert r["metrics"]["affected_inputs"][0]["dependency_end"] == "2019-08-15"
    row.pop("dependency_end")
    r = panel_input_check({"inputs": [row]})
    assert r["reasons"] == ["data.panel_dependency_range_missing"]


def test_affected_held_stock_makes_NAV_null_without_deleting_inventory_or_known_cash():
    from qlab.dynamic_factor.valuation import integer_cash_valuation

    r = integer_cash_valuation(
        dict(
            known_cash=100,
            as_of="2019-08-08",
            inventory={"BA": 2},
            marks={"BA": 100},
            events=[],
        )
    )
    assert r["reasons"] == ["data.panel_quarantined_input"]
    assert r["metrics"]["nav"] is None and r["metrics"]["inventory"] == {"BA": 2}
    assert r["metrics"]["known_available_cash"] == 100

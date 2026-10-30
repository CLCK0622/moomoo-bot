"""Post-freeze refusal receipts. All writes are isolated synthetic unit copies."""

import json
import shutil

from .authority_ledger import AuthorityLedger, FIXTURES
from .contract import digest, sha256
from .conventions import FIXTURES as INPUTS
from .input_disposition import (
    MAPPING_SHA,
    input_migration_check,
    panel_input_check,
    qqq_cash_input,
)
from .valuation import benchmark_valuation, integer_cash_valuation


def migration_input(ledger):
    current = ledger.verify()
    return {
        "old_anchor": current,
        "new_anchor": dict(current),
        "new_ledger_raw": ledger.path.read_text(),
        "new_witness": json.loads(ledger.witness.read_bytes()),
        "old_QQQ_event_table_sha256": sha256(
            (INPUTS / "qqq-events-v1.csv").read_bytes()
        ),
        "new_QQQ_mapping_sha256": MAPPING_SHA,
    }


def cases(workdir, policy):
    reports = []

    def refused(case_id, report, key, reason):
        assert (
            not report["ok"]
            and not report["certifiable"]
            and not report["runtime_consumable"]
        )
        assert report["metrics"][key] is None and reason in report["reasons"]
        reports.append(
            {
                "case_id": case_id,
                "status": "PASS",
                "reasons": report["reasons"],
                "observed": {key: None, "refused": True},
            }
        )

    vti = benchmark_valuation(
        {
            "symbol": "VTI",
            "price_basis": "raw_close",
            "raw_source_sha256": digest("SYNTHETIC_UNIT"),
            "prices": [{"date": "2026-01-05", "close": 100}],
            "evidence": {"historical_44_amounts_verified": True},
            "use_suffix": True,
            "fallback": "SPY",
        },
        conventions=policy,
    )
    refused(
        "disposition.VTI_partial_full_period_refused",
        vti,
        "analytical_index",
        "data.vti_evidence_missing",
    )
    panel = panel_input_check(
        {"inputs": [{"symbol": "BA", "date": "2019-08-08", "field": "label"}]},
        conventions=policy,
    )
    refused(
        "disposition.panel_quarantine_no_replacement",
        panel,
        "certified_usable_count",
        "data.panel_quarantined_input",
    )
    assert (
        panel["metrics"]["affected_inputs"][0]["value"] is None
        and panel["metrics"]["replacements"] == []
    )
    event = qqq_cash_input("2022-12-19", 2)
    event["declared_cash_amount"] = (
        1.31082  # Uncorrected vendor amount, never receivable.
    )
    cash = integer_cash_valuation(
        {
            "events": [event],
            "known_cash": 100,
            "as_of": "2022-12-20",
            "inventory": {"QQQ": 2},
            "marks": {"QQQ": 100},
        },
        conventions=policy,
    )
    refused(
        "disposition.QQQ_conflict_not_receivable",
        cash,
        "receivable_amount",
        "valuation.QQQ_cash_amount_conflict",
    )

    local, witness = workdir / "dedup-unit.jsonl", workdir / "dedup-tip.json"
    shutil.copyfile(FIXTURES / "EVO891-B-ledger-v2.jsonl", local)
    shutil.copyfile(FIXTURES / "EVO891-B-ledger-v2.tip.json", witness)
    writer = AuthorityLedger(local, witness, writable=True)
    before = local.read_bytes(), witness.read_bytes()
    try:
        writer.append(
            {
                "event": "attempt",
                "attempt_id": "SYNTHETIC_ZERO",
                "run_id": "SYNTHETIC",
                "n_trials_total": 0,
                "n_evaluated": 0,
                "n_contribution": 0,
                "same_cells_as": "P01",
                "scope_labels": ["unit"],
                "evidence": [{"path": "unit", "sha256": digest("unit")}],
            }
        )
    except ValueError as exc:
        assert str(exc) == "ledger.same_parameter_cells_not_exempt"
    else:
        raise AssertionError("same parameter cells exemption accepted")
    assert before == (local.read_bytes(), witness.read_bytes())
    reports.append(
        {
            "case_id": "disposition.same_parameter_cells_not_exempt",
            "status": "PASS",
            "observed": {"refused_before_mutation": True, "recorded_N": 75},
        }
    )
    request = migration_input(writer)
    request["new_anchor"]["N"] = request["new_anchor"]["n_high_water"] = 74
    migration = input_migration_check(request, writer, conventions=policy)
    refused(
        "disposition.migration_N_rollback",
        migration,
        "receipt",
        "ledger.migration_N_rollback",
    )
    assert before == (local.read_bytes(), witness.read_bytes())
    return reports

"""Pinned post-freeze input receipts; no design, universe or account changes."""

import json
from decimal import Decimal, InvalidOperation

from .contract import result, sha256
from .conventions import FIXTURES, load_conventions
from .fees import iso_date
from .event_quarantine import (
    quarantine_check,
    s1_scope,
    field_rules,
    sources as v10_sources,
)

HASHES = {
    "EVO883-EVO886-minimum-scope-ruling-v1.md": "56d97ab77b8389abcd8fcc7c9df2d7094cfc38b3da39954f3b92439d061b05da",
    "EVO883-EVO886-minimum-scope-ruling-v1.json": "730931cdd7b9c2f62db9841438235e0aa4887f27ef4a842844d63b6570fd7ede",
    "QQQ-source-row-bindings-v1.json": "71953b090c92ca6fc02cb1a2a5e493a02b991ff35e43e3bf4c07136da8441260",
    "EVO883-EVO891-ruling-v1.md": "641c03afea7ff86bfab99d5392e3185606e1241669f110a315fa8379b5e7684c",
    "EVO883-EVO891-disposition-draft-v1.json": "75685ab429e05a74fb5f1c9187c5da144b98b6932795569516f9137f8f608f87",
}
MAPPING_SHA = HASHES["QQQ-source-row-bindings-v1.json"]
RULING_SHA = HASHES["EVO883-EVO891-ruling-v1.md"]


def sources():
    raw = {n: (FIXTURES / "disposition" / n).read_bytes() for n in HASHES}
    if any(sha256(b) != HASHES[n] for n, b in raw.items()):
        raise ValueError("data.disposition_identity_mismatch")
    return raw


def cash_bindings():
    rows = json.loads(sources()["QQQ-source-row-bindings-v1.json"])
    return {r["ex_date"]: r for r in rows}


def qqq_cash_input(ex_date, entitled_integer_shares):
    """Explicit corrected input version, never a silent repair of caller bytes.

    Entitlement is supplied by the simulated inventory writer, not inferred from
    current holdings or the source sidecar's null entitlement field.
    """
    r = cash_bindings()[ex_date]
    return {
        "symbol": "QQQ",
        "input_version": "QQQ.cash-source-mapped/v1",
        "source_mapping_sha256": MAPPING_SHA,
        "event_table_sha256": r["event_table_sha256"],
        "archived_vendor_amount": r["original_declared_cash_amount"],
        "original_event_source_sha256": r["original_event_source_sha256"],
        "source_sha256": r["exchange_source_sha256"],
        "declared_cash_amount": float(r["supported_cash_amount_per_share"]),
        "analytical_D_used": float(r["D_used_for_TR"]),
        "exact_amount_status": "verified_exact",
        "ex_date_status": "verified",
        "ex_date": ex_date,
        "pay_date": r["pay_date"],
        "pay_date_status": "verified",
        "entitled_integer_shares": entitled_integer_shares,
    }


def cash_source_reason(event):
    row = cash_bindings().get(event.get("ex_date"))
    if (
        row is None
        or event.get("symbol") != "QQQ"
        or event.get("source_mapping_sha256") != MAPPING_SHA
        or event.get("input_version") != "QQQ.cash-source-mapped/v1"
    ):
        return "valuation.QQQ_cash_mapping_missing"
    try:
        if Decimal(str(event.get("declared_cash_amount"))) != Decimal(
            row["supported_cash_amount_per_share"]
        ):
            return "valuation.QQQ_cash_amount_conflict"
    except (InvalidOperation, TypeError, ValueError):
        return "valuation.QQQ_cash_amount_unknown"
    if (
        event.get("source_sha256") != row["exchange_source_sha256"]
        or event.get("event_table_sha256") != row["event_table_sha256"]
        or event.get("archived_vendor_amount") != row["original_declared_cash_amount"]
        or event.get("original_event_source_sha256")
        != row["original_event_source_sha256"]
    ):
        return "valuation.QQQ_cash_source_conflict"
    if event.get("pay_date") is not None and event["pay_date"] != row["pay_date"]:
        return "valuation.QQQ_paydate_conflict"
    return None


def _panel_input_check(request, *, conventions=None):
    policy = conventions or load_conventions()
    isolated, days = [], {}
    if policy.document["version"] in ("v2.0.0", "v3.0.0") and "isolation_manifest" in request:
        from .isolation import selection_projection

        request, isolated, days = selection_projection(request, policy)
    doc = json.loads(sources()["EVO883-EVO891-disposition-draft-v1.json"])
    panel = doc["panel_disposition"]
    overlay = quarantine_check(request)
    affected, reasons = [], []
    v10_fields = field_rules(v10_sources()[0])
    for node in overlay["metrics"]["projected_nodes"] or []:
        if node["reasons"]:
            affected.append(
                dict(
                    node["submitted"],
                    value=None,
                    source_reason="data.v10_quarantined_dependency",
                    reasons=node["reasons"],
                    event_keys=node["event_keys"],
                )
            )
    if affected:
        reasons.append("data.panel_quarantined_input")
    elif not overlay["ok"]:
        reasons.extend(overlay["reasons"])
    by_symbol = {r["symbol"]: r for r in panel["stock_dispositions"]}
    for item in request.get("inputs", []):
        # The v10 receipt adopts only S1 raw_open metadata. Values supplied by a
        # caller are not authenticated by repeating its CSV hash here.
        if s1_scope(item):
            continue
        row = by_symbol.get(item["symbol"])
        if row is None:
            continue  # Absence from this list does not certify eligibility.
        date = iso_date(item["date"])
        first = row["known_first_unresolved_event"]
        field = item["field"]
        if field not in v10_fields and field not in (
            "raw_close",
            "total_return",
            "feature",
            "label",
            "gain",
            "valuation",
            "nav",
        ):
            raise ValueError("data.panel_dependency_invalid")
        if item["symbol"] in ("B", "COR"):
            continue  # Full-span unknown anchor ancestry already projected.
        raw_status = row["source_matrix_row"]["raw_price_status"]
        raw_unverified = "未核实" in raw_status or "不一致" in raw_status
        derived = field in (
            "total_return",
            "feature",
            "label",
            "gain",
            "valuation",
            "nav",
        )
        end = item.get("dependency_end")
        if end is not None:
            end = iso_date(end)
            if (
                item.get("dependency_start") is not None
                and iso_date(item["dependency_start"]) > end
            ):
                raise ValueError("data.panel_dependency_range_invalid")
        scope_end = max(date, end) if end is not None else date
        range_missing = (
            field in ("feature", "label", "gain")
            and end is None
            and first is not None
            and date < first
        )
        if range_missing or (
            (first is None or scope_end >= first) and (raw_unverified or derived)
        ):
            affected.append(
                {
                    **item,
                    "first_unresolved_event": first,
                    "dependency_end": end,
                    "value": None,
                    "source_reason": row["reason"],
                }
            )
            reasons.append(
                "data.panel_dependency_range_missing"
                if range_missing
                else "data.panel_quarantined_input"
            )
    if request.get("replacement_symbols") or request.get("truncate_sample"):
        reasons.append("data.panel_or_sample_change_requires_design_version")
    return policy.bind(
        result(
            "panel_input_check",
            {"request": request, "disposition_sha256": HASHES},
            reasons=reasons,
            metrics={
                "affected_inputs": affected,
                "certified_usable_count": None,
                "frozen_count": panel["frozen_count"],
                "replacements": [],
                "dsr": None,
                "event_quarantine": overlay,
                "pre_score_isolated_inputs": isolated,
                "daily_eligibility": days,
            },
            assumptions=[
                "Retain frozen membership; only the source-specified affected date/dependency is quarantined. Passing this receipt is not 252-session/min50 eligibility acceptance."
            ],
        )
    )


def panel_input_check(request, *, conventions=None):
    policy = conventions or load_conventions()
    try:
        return _panel_input_check(request, conventions=policy)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return policy.bind(
            result(
                "panel_input_check",
                {"request": request, "disposition_sha256": HASHES},
                reasons=[
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "data.panel_input_missing_or_invalid"
                ],
                metrics={
                    "affected_inputs": None,
                    "certified_usable_count": None,
                    "replacements": [],
                    "dsr": None,
                },
            )
        )


def input_migration_check(request, ledger, *, conventions=None):
    """Propose/verify a versioned receipt; no installation or SQLite conversion.

    A project path change still needs separate acceptance and trusted install.
    Rechecking against the retained current witness prevents snapshot rollback.
    """
    policy = conventions or load_conventions()
    reasons, receipt = [], None
    try:
        old = ledger.verify()
        if request.get("old_anchor") != old:
            raise ValueError("ledger.migration_old_anchor_mismatch")
        new = request["new_anchor"]
        if not isinstance(new, dict):
            raise ValueError("ledger.migration_evidence_missing")
        if (
            new.get("N", -1) < old["N"]
            or new.get("n_high_water", -1) < old["n_high_water"]
        ):
            raise ValueError("ledger.migration_N_rollback")
        # Only a byte-preserving same-chain copy is covered by this receipt.
        if new != old:
            raise ValueError("ledger.migration_chain_mapping_acceptance_required")
        from .authority_ledger import verify_bytes, TOOL_SHA, latest_external_witness

        cur, _ = verify_bytes(
            request["new_ledger_raw"].encode("utf-8"),
            request["new_witness"],
            latest_external_witness(),
        )
        if cur != new:
            raise ValueError("ledger.migration_new_anchor_mismatch")
        raw_qqq = (FIXTURES / "qqq-events-v1.csv").read_bytes()
        if request.get("old_QQQ_event_table_sha256") != sha256(raw_qqq):
            raise ValueError("valuation.migration_old_QQQ_identity_mismatch")
        if request.get("new_QQQ_mapping_sha256") != MAPPING_SHA:
            raise ValueError("valuation.migration_QQQ_mapping_missing")
        sources()
        receipt = {
            "schema": "EVO884.input-migration-receipt/v1",
            "old_anchor": old,
            "new_anchor": cur,
            "old_QQQ_event_table_sha256": sha256(raw_qqq),
            "new_QQQ_mapping_sha256": MAPPING_SHA,
            "mapped_original_event_table_sha256": sorted(
                {r["event_table_sha256"] for r in cash_bindings().values()}
            ),
            "ruling_sha256": RULING_SHA,
            "historical_bytes_preserved": True,
            "migration_kind": "reader_policy_and_QQQ_input_adoption_preserving_original_JSONL",
            "old_ledger_reader_sha256": TOOL_SHA,
            "new_ledger_reader_policy": "explicit_attempt_identity_or_continuation_evidence_v1",
            "historical_P02_disposition": "preserved_pending_execution_identity_evidence",
            "complete_N": None,
            "installed": False,
            "SQLite_conversion_accepted": False,
            "project_path_change_accepted": False,
        }
    except (ValueError, KeyError, TypeError, OSError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else "ledger.migration_evidence_missing"
        )
    return policy.bind(
        result(
            "input_migration_check",
            {"request": request, **policy.binding},
            metrics={"receipt": receipt, "complete_N": None, "dsr": None},
            reasons=reasons,
            assumptions=[
                "Receipt validation does not install, retire or create a project ledger; JSONL to SQLite needs separate acceptance."
            ],
        )
    )

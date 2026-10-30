"""Scoped K5 dependency readouts; no new spin-off valuation/disposal algorithm."""

import csv
from decimal import Decimal
import io
import json

from .contract import digest, result, sha256
from .conventions import FIXTURES, load_conventions
from .fees import iso_date
from .input_scope import reject_b2_inputs

FIELD_RECEIPT_SHA = "9b5fd1e87a2cae26df8a0c1a8ee9fbd880c07234e05a9253ff9886d4dcb7711f"
VSNT_CSV_SHA = "cde9f7c01f4e68a0c61f8480215a25649843df1780ab8f82a5920c1f83e9d2c3"
CHILDREN = {"ADP": "CDK", "APD": "VSM", "CMCSA": "VSNT"}
EVENT_DATES = {"ADP": "2014-10-01", "APD": "2016-10-03", "CMCSA": "2026-01-05"}


def vsnt_quote(date, field, *, purpose, policy=None):
    p = policy or load_conventions()
    if purpose != "K5" or field not in ("raw_open", "raw_close"):
        raise ValueError("K5.quote_role_or_field_forbidden")
    receipt_raw = (FIXTURES / "k5/S2-field-receipt-v1.json").read_bytes()
    data = (FIXTURES / "k5/VSNT-open-close-none.csv").read_bytes()
    if (
        sha256(receipt_raw) != FIELD_RECEIPT_SHA
        or sha256(data) != VSNT_CSV_SHA
        or p.document["source_evidence_precedence"]["S2_VSNT_receipt_sha256"]
        != FIELD_RECEIPT_SHA
    ):
        raise ValueError("K5.quote_receipt_or_csv_identity_mismatch")
    receipt = json.loads(receipt_raw)
    spec = next(
        s for s in receipt["accepted_source_fields"] if s["target_field"] == field
    )
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    dates = [r["date"] for r in rows]
    expected = [d for d in p.calendar if spec["from_date"] <= d <= spec["to_date"]]
    if (
        len(rows) != spec["rows"]
        or dates != expected
        or spec["source_csv_sha256"] != VSNT_CSV_SHA
        or any(
            r["source_raw_sha256"] != spec["source_original_sha256"]
            or any(
                not Decimal(r[f]).is_finite() or Decimal(r[f]) <= 0
                for f in ("raw_open_none", "raw_close_none")
            )
            for r in rows
        )
    ):
        raise ValueError("K5.quote_calendar_or_source_mismatch")
    row = next((r for r in rows if r["date"] == iso_date(date)), None)
    if row is None:
        raise ValueError("K5.quote_outside_accepted_window")
    return {
        "symbol": "VSNT",
        "date": date,
        "field": field,
        "value": row[spec["source_field"]],
        "field_receipt_sha256": FIELD_RECEIPT_SHA,
        "merged_sha256": VSNT_CSV_SHA,
        "source_original_sha256": spec["source_original_sha256"],
        "purpose": "K5",
        "entitlement": None,
        "disposal_contract": None,
        "cash_available": None,
        "complete_K5_execution": False,
    }


def inventory_reachability(request, policy):
    """Derive per-fold possible exposure; no 23/4 list or post-result zero proof."""
    parent = request["parent"]
    if parent not in CHILDREN:
        raise ValueError("K5.parent_not_registered")
    event = iso_date(request["event_date"])
    if event != EVENT_DATES[parent]:
        raise ValueError("K5.event_candidate_identity_mismatch")
    folded = next(
        f
        for f in policy.date_manifest["folds"]
        if str(f["fold_id"]) == str(request["fold_id"])
    )
    scope = request["account_role"]
    if scope in ("train_solo_probes", "train_meta"):
        start, end = folded["train_dates_inclusive"]
    elif scope == "continuous_test":
        start = policy.date_manifest["folds"][0]["test_dates_inclusive"][0]
        end = policy.date_manifest["folds"][-1]["test_dates_inclusive"][1]
    else:
        raise ValueError("K5.unregistered_account_role")
    calendar = list(policy.calendar)
    first_signal = (
        calendar.index(start)
        + policy.document["initialization"]["first_regular_signal_close_position"]
    )
    first_buy = (
        calendar.index(start)
        + policy.document["initialization"]["first_regular_reference_open_position"]
    )
    if event <= calendar[first_buy]:
        return {
            "possible": False,
            "reason": "K5.event_precedes_possible_parent_inventory",
            "initialization": start,
            "event_before_initialization": event < start,
            "signal_dates": [],
        }
    if event > end:
        return {
            "possible": False,
            "reason": "K5.event_after_registered_account_window",
            "initialization": start,
            "signal_dates": [],
        }
    from .isolation import eligible_day

    sealed = request.get("isolation_manifest")
    if sealed is None:
        return {
            "possible": None,
            "reason": "K5.actual_E_t_and_admission_path_missing",
            "initialization": start,
            "signal_dates": None,
        }
    signal_dates = [
        d
        for i, d in enumerate(calendar)
        if i >= first_signal
        and d < event
        and (i - calendar.index(start))
        % policy.document["initialization"]["first_regular_signal_close_position"]
        == 0
    ]
    states = {
        d: eligible_day(sealed, d, policy)["states"][parent] for d in signal_dates
    }
    possible = (
        True
        if "VERIFIED_USABLE" in states.values()
        else None
        if "UNKNOWN" in states.values()
        else False
    )
    return {
        "possible": possible,
        "reason": "K5.E_t_does_not_prove_admission_or_entitlement"
        if possible
        else "K5.preperformance_path_unknown"
        if possible is None
        else "K5.all_prior_buy_signals_excluded_by_E_t",
        "initialization": start,
        "signal_dates": signal_dates,
        "eligibility_states": states,
        "quarantine_manifest_sha256": sealed["quarantine_manifest_sha256"],
        "actual_entitled_inventory": None,
    }


def k5_dependency_check(request, *, conventions=None):
    p = conventions or load_conventions()
    metrics = {
        "dependency_value": None,
        "entitlement": None,
        "receivable": None,
        "cash_available": None,
        "nav": None,
        "quote": None,
        "reachability": None,
        "inventory_origin_dependency_closed": False,
        "warmup_verified": None,
        "TR_verified": None,
        "labels_verified": None,
        "R2_stop": True,
    }
    metrics["event_date_status"] = (
        "v2_ADP_premises"
        if request.get("parent") == "ADP"
        else "conditional_candidate_not_independently_verified"
    )
    reasons = []
    try:
        reject_b2_inputs(request, "holdings_cash")
        if request["dependency_role"] not in {
            "historical_inventory",
            "TR",
            "warmup",
            "label",
            "rights",
            "cash",
            "nav",
            "raw_close",
        }:
            raise ValueError("K5.dependency_role_invalid")
        if (
            request.get("price_basis") in ("Form8937_FMV", "tax_fair_market_value")
            or "tax_fmv" in request
        ):
            raise ValueError("K5.tax_FMV_is_not_raw_close")
        if request.get("observed_zero_after_performance") or request.get(
            "force_disposal"
        ):
            raise ValueError("K5.post_result_waiver_or_new_disposal_forbidden")
        reach = inventory_reachability(request, p)
        metrics["reachability"] = reach
        if (
            request["dependency_role"] == "historical_inventory"
            and reach["possible"] is False
        ):
            metrics.update(inventory_origin_dependency_closed=True, R2_stop=False)
        else:
            if request["parent"] == "CMCSA" and request.get("quote_date") is not None:
                metrics["quote"] = vsnt_quote(
                    request["quote_date"], "raw_close", purpose="K5", policy=p
                )
            reasons.append(
                "K5.required_entitlement_analysis_or_disposal_contract_missing"
            )
    except (ValueError, KeyError, TypeError, StopIteration, OSError) as exc:
        reasons.append(
            str(exc) if isinstance(exc, ValueError) else "K5.required_evidence_missing"
        )
    return p.bind(
        result(
            "k5_dependency_check",
            request,
            metrics=metrics,
            reasons=reasons,
            assumptions=[
                "Per-fold E(t) bounds are possible paths, not observed holdings. Quotes do not attest entitlement, fractional shares, disposal, cash or NAV. No liquidation rule or automatic 252-day release exists."
            ],
        )
    )

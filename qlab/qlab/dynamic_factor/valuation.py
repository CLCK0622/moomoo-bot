"""Conditional analytical TR and integer dividend cash are distinct contracts.

No market data acquisition, fractional cash DRIP, or account writer lives here.
QQQ's aggregate/inferred analytical distributions never become spendable cash.
"""

from __future__ import annotations

import csv
import io
import math

from .contract import is_sha, result, sha256, unavailable
from .conventions import FIXTURES, load_conventions
from .fees import finite, iso_date
from .input_disposition import (
    MAPPING_SHA,
    RULING_SHA,
    cash_source_reason,
    panel_input_check,
)
from .input_scope import reject_b2_inputs


VTI_REQUIREMENTS = (
    "historical_44_amounts_verified",
    "two_suspected_omissions_resolved",
    "historical_paydates_verified",
    "price_gap_2026_06_26_explained",
)


def vti_evidence_check(evidence, policy):
    if (
        not isinstance(evidence, dict)
        or not is_sha(evidence.get("source_sha256"))
        or evidence.get("profile_sha256") != policy.binding["common_profile_sha256"]
        or not all(evidence.get(k) is True for k in VTI_REQUIREMENTS)
    ):
        raise ValueError("data.vti_evidence_missing")
    # The adopted disposition has no accepted closure/equivalence receipt for
    # the full frozen interval. Self-asserted booleans cannot enable a suffix.
    raise ValueError("data.VTI_formal_full_period_unavailable")


def qqq_events(policy):
    raw = (FIXTURES / "qqq-events-v1.csv").read_bytes()
    expected = policy.document["corporate_action_policy"]["QQQ_analysis_TR"][
        "event_table_sha256"
    ]
    if sha256(raw) != expected:
        raise ValueError("valuation.QQQ_event_table_hash_mismatch")
    return {r["ex"]: r for r in csv.DictReader(io.StringIO(raw.decode()))}, sha256(raw)


def analytical_index(prices, events):
    """Pure close-to-close, exdate-close fractional, zero-fee pre-tax index."""
    dates = [iso_date(r["date"]) for r in prices]
    if (
        not dates
        or dates != sorted(set(dates))
        or any(not finite(r["close"]) or r["close"] <= 0 for r in prices)
    ):
        raise ValueError("valuation.raw_close_invalid_or_missing")
    value, quantity = 100.0, 100.0 / prices[0]["close"]
    output = [{"date": dates[0], "index": value, "return": None}]
    for row in prices[1:]:
        dividend = events.get(row["date"], 0)
        if not finite(dividend) or dividend < 0:
            raise ValueError("valuation.analytical_distribution_unknown")
        quantity *= 1 + dividend / row["close"]
        next_value = quantity * row["close"]
        output.append(
            {"date": row["date"], "index": next_value, "return": next_value / value - 1}
        )
        value = next_value
    return output


def benchmark_valuation(request, *, conventions=None):
    policy = conventions or load_conventions()
    metrics = {
        "analytical_index": None,
        "formal_return": None,
        "formal_available": False,
    }
    reasons = []
    event_sha = None
    try:
        symbol = request["symbol"]
        if request["price_basis"] != "raw_close":
            raise ValueError("valuation.qfq_not_raw_close")
        if not is_sha(request.get("raw_source_sha256")):
            raise ValueError("valuation.raw_close_evidence_missing")
        if symbol == "QQQ":
            rows, event_sha = qqq_events(policy)
            events = {
                d: float(r["D_used_for_TR"]) if r["D_used_for_TR"] else None
                for d, r in rows.items()
            }
            index = analytical_index(request["prices"], events)
            metrics.update(
                analytical_index=index,
                conditional_analysis=True,
                event_statuses={
                    d: {
                        k: r[k]
                        for k in ("amount_status", "exdate_status", "D_used_for_TR")
                    }
                    for d, r in rows.items()
                    if d in {p["date"] for p in request["prices"]}
                },
            )
        elif symbol == "VTI":
            vti_evidence_check(request.get("evidence"), policy)
        else:
            raise ValueError("valuation.primary_benchmark_must_be_QQQ_or_VTI")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else "valuation.input_invalid_or_missing"
        )
    return policy.bind(
        result(
            "benchmark_valuation",
            {"request": request, "event_table_sha256": event_sha, **policy.binding},
            metrics=metrics,
            reasons=reasons,
            missing=[r for r in reasons if "missing" in r],
            availability={
                "formal_return": unavailable(
                    "valuation.formal_execution_and_total_return_evidence_unmet"
                )
            },
            assumptions=[
                "QQQ uses the bound EVO-889 D_used_for_TR event table; per-event exact amounts, exdates and paydates remain separately qualified.",
                "Analytical fractional exdate-close reinvestment is conditional pre-tax zero-fee arithmetic, not an integer cash account or open-to-open execution proof.",
                "VTI is fixed B2; missing evidence never switches to SPY.",
            ],
        )
    )


def integer_cash_valuation(request, *, conventions=None):
    policy = conventions or load_conventions()
    metrics = {
        "nav": None,
        "available_cash": None,
        "known_available_cash": None,
        "receivable_amount": None,
        "dividends": None,
        "cash_ledger_kind": "simulation_pre_tax_integer",
        "source_mapping_sha256": MAPPING_SHA,
        "account_cash_credited_amount": None,
        "account_cash_credited_at": None,
        "account_verified": False,
    }
    reasons = []
    try:
        reject_b2_inputs(request, "holdings_cash")
        cash = request["known_cash"]
        as_of = iso_date(request["as_of"])
        inventory = request["inventory"]
        if (
            not finite(cash)
            or cash < 0
            or any(type(q) is not int or q < 0 for q in inventory.values())
        ):
            raise ValueError("valuation.integer_inventory_or_cash_invalid")
        holdings_check = panel_input_check(
            {
                "inputs": [
                    {"symbol": s, "date": as_of, "field": "valuation"}
                    for s, q in inventory.items()
                    if q
                ]
            },
            conventions=policy,
        )
        metrics.update(
            known_available_cash=cash,
            inventory=inventory,
            data_invalid_holdings=holdings_check["metrics"]["affected_inputs"],
        )
        reasons.extend(holdings_check["reasons"])
        received, receivables, credits = [], [], []
        seen = set()
        for event in request["events"]:
            # Analytical distributions never become cash through this path.
            fields = policy.document["corporate_action_policy"]["integer_cash_ledger"][
                "required_event_fields"
            ]
            row = {k: event.get(k) for k in fields}
            row.update(
                symbol=event.get("symbol"),
                ex_date=event.get("ex_date"),
                source_mapping_sha256=MAPPING_SHA,
                cash_ledger_kind="simulation_pre_tax_integer",
                account_cash_credited_amount=None,
                account_cash_credited_at=None,
            )
            row.update(
                {
                    k: event.get(k)
                    for k in (
                        "input_version",
                        "event_table_sha256",
                        "archived_vendor_amount",
                        "original_event_source_sha256",
                        "simulated_payment_source_sha256",
                    )
                }
            )
            ex = iso_date(event["ex_date"])
            key = (event.get("symbol"), ex)
            if key in seen:
                raise ValueError("valuation.duplicate_dividend_event")
            seen.add(key)
            entitlement = event["entitled_integer_shares"]
            amount = event.get("declared_cash_amount")
            source_reason = cash_source_reason(event)
            amount_known = (
                source_reason is None
                and event.get("symbol") in inventory
                and finite(amount)
                and amount >= 0
                and event.get("exact_amount_status") == "verified_exact"
                and event.get("ex_date_status") == "verified"
                and is_sha(event.get("source_sha256"))
                and type(entitlement) is int
                and entitlement >= 0
            )
            if event.get("entry_date") == ex and entitlement:
                raise ValueError("valuation.ex_open_entry_not_dividend_entitled")
            if ex > as_of:
                continue
            if not amount_known:
                row.update(
                    receivable_amount=None,
                    cash_credited_amount=None,
                    cash_credited_at=None,
                )
                reasons.append(
                    source_reason or "valuation.dividend_amount_or_entitlement_unknown"
                )
                receivables.append(None)
                credits.append(None)
            else:
                payable = amount * entitlement
                paydate = event.get("pay_date")
                if paydate is not None and iso_date(paydate) < ex:
                    raise ValueError("valuation.paydate_precedes_exdate")
                if paydate is None or event.get("pay_date_status") != "verified":
                    row.update(
                        receivable_amount=payable,
                        cash_credited_amount=None,
                        cash_credited_at=None,
                    )
                    receivables.append(payable)
                    credits.append(None)
                    reasons.append("valuation.dividend_paydate_unknown")
                elif (
                    iso_date(paydate) <= as_of
                    and event.get("simulated_payment_available") is True
                ):
                    credited = event.get("simulated_cash_credited_amount")
                    when = event.get("simulated_cash_credited_at")
                    if (
                        not finite(credited)
                        or credited != payable
                        or when is None
                        or not is_sha(event.get("simulated_payment_source_sha256"))
                        or not paydate <= iso_date(when) <= as_of
                    ):
                        raise ValueError(
                            "valuation.payment_receipt_missing_or_inconsistent"
                        )
                    row.update(
                        receivable_amount=0,
                        cash_credited_amount=credited,
                        cash_credited_at=when,
                    )
                    receivables.append(0)
                    credits.append(credited)
                elif (
                    iso_date(paydate) <= as_of
                    and event.get("simulated_payment_available") is not False
                ):
                    row.update(
                        receivable_amount=payable,
                        cash_credited_amount=None,
                        cash_credited_at=None,
                    )
                    receivables.append(payable)
                    credits.append(None)
                    reasons.append("valuation.simulated_payment_availability_unknown")
                else:
                    row.update(
                        receivable_amount=payable,
                        cash_credited_amount=0,
                        cash_credited_at=None,
                    )
                    receivables.append(payable)
                    credits.append(0)
            received.append(row)
        for row in received:
            row["simulated_cash_credited_amount"] = row["cash_credited_amount"]
            row["simulated_cash_credited_at"] = row["cash_credited_at"]
            row["exchange_pay_date"] = row["pay_date"]
        known_credits = math.fsum(v for v in credits if v is not None)
        available = cash + known_credits
        metrics.update(
            known_available_cash=available,
            available_cash=available if all(v is not None for v in credits) else None,
            receivable_amount=math.fsum(receivables)
            if all(v is not None for v in receivables)
            else None,
            dividends=received,
            inventory=inventory,
        )
        prices = request["marks"]
        if any(
            s not in prices or not finite(prices[s]) or prices[s] <= 0
            for s, q in inventory.items()
            if q
        ):
            reasons.append("valuation.mark_unknown")
        elif holdings_check["ok"] and (
            metrics["available_cash"] is not None
            and metrics["receivable_amount"] is not None
        ):
            metrics["nav"] = (
                available
                + metrics["receivable_amount"]
                + math.fsum(q * prices[s] for s, q in inventory.items() if q)
            )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else "valuation.input_invalid_or_missing"
        )
    return policy.bind(
        result(
            "integer_cash_valuation",
            {
                "request": request,
                "source_mapping_sha256": MAPPING_SHA,
                "ruling_sha256": RULING_SHA,
                **policy.binding,
            },
            metrics=metrics,
            reasons=reasons,
            assumptions=[
                "Known cash after other transactions is reported separately from total verified cash; unknown dividends are not zero or spendable.",
                "No free fractional DRIP, inventory change or account write occurs; this is a versioned readout for an independent integer writer.",
                "All cash, receivable and legacy cash_credited_* fields are simulated pre-tax inventory cash. Exchange paydate is not account receipt; account amount/time remain null.",
            ],
            availability={
                "nav": unavailable(reasons[0] if reasons else "valuation.incomplete")
                if metrics["nav"] is None
                else {"available": True, "reason": None}
            },
        )
    )

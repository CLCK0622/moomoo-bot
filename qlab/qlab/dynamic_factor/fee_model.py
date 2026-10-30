"""Frozen v1 research costs per net DAY order × exchange trading date.

This module calculates versioned readouts; the separate EVO-885 writer owns its
shadow state. Unknown actual per-fill billing remains null, including QQQ orders.
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from pathlib import Path

from .contract import result, sha256, unavailable
from .fees import finite, iso_date


def order_cost(p, side, quantity, notional, floor, basis):
    def D(v):
        return Decimal(str(v))

    if (
        type(quantity) is not int
        or quantity < 0
        or not finite(notional)
        or notional < 0
        or (quantity == 0) != (notional == 0)
    ):
        raise ValueError("fee.cumulative_fill_invalid")
    if side not in ("buy", "sell"):
        raise ValueError("fee.side_invalid")
    if not quantity:
        return {
            "research_cost_usd": 0.0,
            "model_fee_usd": 0.0,
            "taf_usd": 0.0,
            "friction_usd": 0.0,
        }
    q, value = D(quantity), D(notional)
    broker = D(p["commission_per_order"]) + D(p["platform_per_order"])
    settlement = min(
        D(p["settlement_per_share"]) * q,
        D(p["settlement_cap_fraction_of_value"]) * value,
    )
    sec = (
        max(D(p["sec_fraction_of_sell_value"]) * value, D(p["sec_min_per_sell"]))
        if side == "sell"
        else D(0)
    )
    taf = (
        min(
            max(D(p["taf_per_share_sell_restored"]) * q, D(p["taf_min_per_sell"])),
            D(p["taf_max_per_sell"]),
        )
        if side == "sell"
        else D(0)
    )
    passthrough = settlement + sec + taf + D(p["cat_per_share_each_side"]) * q
    gst = (broker + passthrough if p["gst_base"] == "all_fees" else broker) * D(
        p["gst_rate"]
    )
    explicit = broker + passthrough + gst
    friction = (
        value
        * (D(p["spread_roundtrip_bps"]) + D(p["extra_slippage_roundtrip_bps"]))
        / D(20000)
    )
    budget = max(explicit + friction, D(floor) * value) * D(p["cost_multiplier"])
    # Baseline x1 bid/ask friction is already included in cash P&L.
    if basis == "cash_bid_ask":
        budget -= friction
    return {
        "research_cost_usd": float(budget),
        "model_fee_usd": float(explicit * D(p["cost_multiplier"])),
        "taf_usd": float(taf),
        "friction_usd": float(friction),
    }


def calculate(request, p, policy, params_sha):
    if request.get("algo_order", False):
        raise ValueError("algo_orders_not_allowed")
    if request.get("rate_basis", "research_restored") not in (
        "effective_date",
        "research_restored",
    ):
        raise ValueError("rate_basis_unknown")
    basis = request["pnl_basis"]
    if basis not in ("reference", "cash_bid_ask"):
        raise ValueError("pnl_basis_unknown")
    floor = float(
        re.search(
            r",([0-9.]+)\*filled_notional\)",
            policy.document["cost_mapping"]["floor_policy"]["x1"],
        )[1]
    )
    fields = (
        "commission_per_order",
        "platform_per_order",
        "settlement_per_share",
        "settlement_cap_fraction_of_value",
        "sec_fraction_of_sell_value",
        "sec_min_per_sell",
        "cat_per_share_each_side",
        "taf_per_share_sell_restored",
        "taf_min_per_sell",
        "taf_max_per_sell",
        "gst_rate",
        "spread_roundtrip_bps",
        "extra_slippage_roundtrip_bps",
        "cost_multiplier",
        "days_per_year",
    )
    if not all(finite(p.get(k)) and p[k] >= 0 for k in fields):
        raise ValueError("invalid_fee_parameters")
    flat = "orders" not in request
    if flat:
        price, budget, gross = (
            request[k] for k in ("price", "ticket_usd", "gross_edge_bps")
        )
        if (
            not all(finite(v) for v in (price, budget, gross))
            or min(price, budget) <= 0
        ):
            raise ValueError("invalid_notional_or_edge")
        quantity = math.floor(budget / price)
        if quantity < 1:
            raise ValueError("integer_ticket_unaffordable")
        date = iso_date(request["sell_date"])
        orders = [
            dict(
                broker_order_id=side,
                exchange_local_trade_date=date,
                side=side,
                quantity=quantity,
                notional=quantity * price,
                planned_quantity=quantity,
                status="filled",
                time_in_force="DAY",
            )
            for side in ("buy", "sell")
        ]
        normalizer = quantity * price
    else:
        orders = request["orders"]
        if not isinstance(orders, list) or not orders:
            raise ValueError("fee.orders_missing")
        normalizer = request.get("normalizer_usd")
        if normalizer is not None and (not finite(normalizer) or normalizer <= 0):
            raise ValueError("fee.normalizer_invalid")
        gross = request.get("gross_edge_bps")
        if gross is not None and not finite(gross):
            raise ValueError("invalid_notional_or_edge")
    states, events, id_dates = {}, [], {}
    actual_total = 0.0
    actual_known = True
    for order in orders:
        date = iso_date(order["exchange_local_trade_date"])
        oid = order["broker_order_id"]
        if not isinstance(oid, str) or not oid or order.get("time_in_force") != "DAY":
            raise ValueError("fee.DAY_order_required")
        if oid in id_dates and id_dates[oid] != date:
            raise ValueError("fee.cross_day_order_execution_violation")
        id_dates[oid] = date
        for change in request.get("known_rate_changes", []):
            if (
                iso_date(change["effective_date"]) <= date
                and change.get("params_sha256") != params_sha
            ):
                raise ValueError("fee.new_rate_receipt_missing")
        key = (oid, date)
        prev = states.get(key)
        qty, value = order["quantity"], order["notional"]
        status = order["status"]
        planned = order["planned_quantity"]
        if (
            type(planned) is not int
            or planned < 0
            or type(qty) is not int
            or qty > planned
            or status not in ("partial", "filled", "cancelled", "eod")
        ):
            raise ValueError("fee.order_state_invalid")
        if status == "filled" and qty != planned:
            raise ValueError("fee.order_state_invalid")
        if prev and (
            qty < prev["quantity"]
            or value < prev["notional"]
            or order["side"] != prev["side"]
            or planned != prev["planned_quantity"]
            or (
                prev["status"] in ("filled", "cancelled", "eod")
                and (
                    qty != prev["quantity"]
                    or value != prev["notional"]
                    or status != prev["status"]
                )
            )
        ):
            raise ValueError("fee.cumulative_fill_rewrite_or_terminal")
        cost = order_cost(p, order["side"], qty, value, floor, basis)
        delta = cost["research_cost_usd"] - (
            prev["cost"]["research_cost_usd"] if prev else 0
        )
        if delta < -1e-10:
            raise ValueError("fee.cumulative_cost_decreased")
        actual = order.get("actual_fee_usd")
        if actual is None or order.get("actual_fee_verified") is not True:
            actual_known = False
        elif not finite(actual) or actual < 0:
            raise ValueError("fee.actual_fee_invalid")
        states[key] = dict(order, cost=cost)
        events.append(
            {
                "fee_key": [oid, date],
                "research_cost_increment_usd": delta,
                "research_cost_cumulative_usd": cost["research_cost_usd"],
                "remainder_cancelled": status in ("cancelled", "eod"),
                "residual_quantity": planned - qty,
                "actual_fee_usd": actual
                if order.get("actual_fee_verified") is True
                else None,
            }
        )
    total = math.fsum(x["cost"]["research_cost_usd"] for x in states.values())
    if actual_known:
        actual_total = math.fsum(x["actual_fee_usd"] for x in states.values())
    bps = total / normalizer * 1e4 if normalizer else None
    net = gross - bps if gross is not None and bps is not None else None
    tau = request.get("one_way_daily_turnover")
    if tau is not None and (not finite(tau) or not 0 <= tau <= 1):
        raise ValueError("invalid_turnover")
    metrics = {
        "research_cost_usd": total,
        "actual_fee_usd": actual_total if actual_known else None,
        "gate_cost_bps": bps,
        "cost_bps": bps,
        "net_edge_bps": net,
        "cash_net_edge_bps": net,
        "positive_net_edge": None if net is None else net > 0,
        "annual_drag_fraction": None
        if tau is None or bps is None
        else p["days_per_year"] * tau * bps / 1e4,
        "taf_usd": math.fsum(x["cost"]["taf_usd"] for x in states.values()),
        "taf_rate_field": "taf_per_share_sell_restored",
        "rate_basis_effective": "research_restored",
        "fee_events": events,
        "orders": list(states.values()),
    }
    if flat:
        metrics["friction_deducted_bps"] = (
            p["spread_roundtrip_bps"] + p["extra_slippage_roundtrip_bps"]
        ) * (p["cost_multiplier"] if basis == "reference" else p["cost_multiplier"] - 1)
        metrics["explicit_usd"] = (
            math.fsum(x["cost"]["model_fee_usd"] for x in states.values())
            / p["cost_multiplier"]
        )
        metrics.update(
            shares=quantity, value_usd=normalizer, unused_budget_usd=budget - normalizer
        )
    return metrics


def evaluate(request, params_path, schedule_path, policy):
    inputs = {"request": request, **policy.binding}
    reasons = []
    metrics = {
        k: None
        for k in (
            "net_edge_bps",
            "cash_net_edge_bps",
            "annual_drag_fraction",
            "research_cost_usd",
            "actual_fee_usd",
        )
    }
    assumptions = [
        "Restored TAF research budget applies to all history and shadow dates, including 2026 Q4; not actual billing.",
        "SEC/TAF use order × exchange trading date as an unverified research assumption for all orders, including QQQ startup orders.",
        "Actual order-versus-fill minimum fees and account eligibility are unresolved; actual_fee_usd is null without an explicit verified bill.",
        "Per-order per-side floor before x2 is a research choice; it is not identical to the old roundtrip reference implementation.",
    ]
    try:
        raw = Path(params_path).read_bytes()
        schedule = Path(schedule_path).read_bytes()
        inputs.update(params_sha256=sha256(raw), schedule_sha256=sha256(schedule))
        json.loads(schedule)
        if policy.document["version"] not in ("v1.0.1", "v2.0.0", "v3.0.0"):
            raise ValueError("fee.conventions_version_obsolete")
        p = json.loads(raw)
        if sha256(raw) not in (
            policy.document["cost_mapping"]["x1_sha256"],
            policy.document["cost_mapping"]["x2_sha256"],
        ):
            raise ValueError("fee_params_not_bound_to_conventions")
        p = json.loads(raw)
        assumptions += p["unverified"]
        metrics.update(calculate(request, p, policy, sha256(raw)))
    except json.JSONDecodeError:
        reasons.append("fee_file_invalid")
    except OSError:
        reasons.append("fee_file_missing")
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        reasons.append(
            str(exc) if isinstance(exc, ValueError) else "fee_input_invalid_or_missing"
        )
    return policy.bind(
        result(
            "fee_frontier",
            inputs,
            metrics=metrics,
            reasons=reasons,
            missing=[r for r in reasons if "missing" in r],
            assumptions=assumptions,
            availability={
                k: unavailable(
                    reasons[0]
                    if reasons
                    else "fee.actual_billing_unverified_or_metric_input_missing"
                )
                if metrics[k] is None
                else {"available": True, "reason": None}
                for k in ("net_edge_bps", "research_cost_usd", "actual_fee_usd")
            },
        )
    )

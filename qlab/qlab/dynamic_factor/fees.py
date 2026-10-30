"""Fee arithmetic from frozen parameter files; no account or quote access."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

from .contract import result, sha256, unavailable

FIXTURES = Path(__file__).parent / "fixtures"


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def iso_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("ISO date required")
    return value


def fee_frontier(
    request,
    params_path,
    schedule_path=FIXTURES / "fee_schedule.json",
    *,
    conventions=None,
):
    inputs = {"request": request, "params_sha256": None, "schedule_sha256": None}
    if conventions is not None:
        inputs.update(conventions.binding)
    assumptions = ["费用政策待 EVO-883 下一版"]
    metrics = {
        "net_edge_bps": None,
        "cash_net_edge_bps": None,
        "annual_drag_fraction": None,
    }

    def reject(reason, missing=()):
        report = result(
            "fee_frontier",
            inputs,
            metrics=metrics,
            reasons=[reason],
            assumptions=assumptions,
            missing=missing,
            availability={"net_edge_bps": unavailable(reason)},
        )
        return conventions.bind(report) if conventions else report

    for key, path in (
        ("params_sha256", params_path),
        ("schedule_sha256", schedule_path),
    ):
        try:
            raw = Path(path).read_bytes()
        except (OSError, TypeError):
            return reject("fee_file_missing", missing=[key])
        inputs[key] = sha256(raw)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            return reject("fee_file_invalid", missing=[key])
        if key == "params_sha256":
            p = value
        else:
            schedule = value
    if not all(isinstance(v, dict) for v in (request, p, schedule)):
        return reject("fee_input_invalid_or_missing")
    assumptions += list(p.get("unverified", []))
    if conventions is not None and inputs["params_sha256"] not in (
        conventions.document["cost_mapping"]["x1_sha256"],
        conventions.document["cost_mapping"]["x2_sha256"],
    ):
        return reject("fee_params_not_bound_to_conventions")
    try:
        price, budget, gross = (
            request[k] for k in ("price", "ticket_usd", "gross_edge_bps")
        )
        sell_date = iso_date(request["sell_date"])
        basis = request["pnl_basis"]
        rate_basis = request["rate_basis"]
        if basis not in {"reference", "cash_bid_ask"}:
            return reject("pnl_basis_unknown")
        if (
            not all(finite(x) for x in (price, budget, gross))
            or min(price, budget) <= 0
        ):
            return reject("invalid_notional_or_edge")
        if request.get("algo_order", False):
            return reject("algo_orders_not_allowed")
        required = (
            "commission_per_order",
            "platform_per_order",
            "settlement_per_share",
            "settlement_cap_fraction_of_value",
            "sec_fraction_of_sell_value",
            "sec_min_per_sell",
            "cat_per_share_each_side",
            "taf_min_per_sell",
            "taf_max_per_sell",
            "gst_rate",
            "spread_roundtrip_bps",
            "extra_slippage_roundtrip_bps",
            "gate_floor_roundtrip_bps",
            "cost_multiplier",
            "days_per_year",
        )
        if (
            not all(finite(p[k]) and p[k] >= 0 for k in required)
            or p["cost_multiplier"] < 1
        ):
            return reject("invalid_fee_parameters")
        if p["integer_shares"] is not True or p["gst_base"] not in {
            "all_fees",
            "broker_only",
        }:
            return reject("unsupported_fee_policy")
        if rate_basis == "effective_date":
            periods = [
                x
                for x in schedule["taf_periods"]
                if iso_date(x["start"]) <= sell_date
                and (
                    x["end_exclusive"] is None
                    or sell_date < iso_date(x["end_exclusive"])
                )
            ]
            if len(periods) != 1:
                return reject("fee_effective_date_uncovered_or_ambiguous")
            field = periods[0]["rate_field"]
        elif rate_basis == "research_restored":
            field = schedule["research_rate_field"]
            assumptions.append(schedule["historical_assumption"])
        else:
            return reject("rate_basis_unknown")
        rate = p[field]
        if not finite(rate) or rate < 0:
            return reject("invalid_taf_rate")
        qty = math.floor(budget / price)
        if qty < 1:
            return reject("integer_ticket_unaffordable")
        value = qty * price
        broker = 2 * (p["commission_per_order"] + p["platform_per_order"])
        settlement = 2 * min(
            p["settlement_per_share"] * qty,
            p["settlement_cap_fraction_of_value"] * value,
        )
        sec = max(p["sec_fraction_of_sell_value"] * value, p["sec_min_per_sell"])
        cat = 2 * p["cat_per_share_each_side"] * qty
        taf = (
            min(max(rate * qty, p["taf_min_per_sell"]), p["taf_max_per_sell"])
            if rate
            else 0.0
        )
        passthrough = settlement + sec + cat + taf
        gst = (broker + passthrough if p["gst_base"] == "all_fees" else broker) * p[
            "gst_rate"
        ]
        explicit = broker + passthrough + gst
        friction_bps = p["spread_roundtrip_bps"] + p["extra_slippage_roundtrip_bps"]
        mult = p["cost_multiplier"]
        # Executed bid/ask P&L already contains x1 friction. Stress adds ONLY its increment.
        friction_to_deduct = friction_bps * (mult if basis == "reference" else mult - 1)
        fee_bps = explicit * mult / value * 1e4 + friction_to_deduct
        floor_bps = p["gate_floor_roundtrip_bps"] * mult
        # The admission floor also includes baseline friction, already in cash P&L.
        gate_bps = max(
            fee_bps, floor_bps - (friction_bps if basis == "cash_bid_ask" else 0)
        )
        if conventions is not None:
            mapping = conventions.document["cost_mapping"]["legacy_floor_mapping"]
            match = re.search(
                r",([0-9.]+)\*order_notional\)$", mapping["per_order_cost_x1"]
            )
            if match is None:
                return reject("fee_order_mapping_unsupported")
            coefficient = float(match[1])
            broker_side, settlement_side, cat_side = broker / 2, settlement / 2, cat / 2
            explicit_sides = []
            for regulatory in (0, sec + taf):
                passthrough_side = settlement_side + cat_side + regulatory
                gst_side = (
                    broker_side + passthrough_side
                    if p["gst_base"] == "all_fees"
                    else broker_side
                ) * p["gst_rate"]
                explicit_sides.append(broker_side + passthrough_side + gst_side)
            gate_bps = (
                sum(
                    max(side + value * friction_bps / 2 / 1e4, coefficient * value)
                    for side in explicit_sides
                )
                * mult
                / value
                * 1e4
            )
            if basis == "cash_bid_ask":
                gate_bps -= friction_bps
            assumptions.append(
                "EVO-883 per-order floors are applied independently to the buy and sell scenario legs; business mapping receipt remains unverified."
            )
        tau = request.get("one_way_daily_turnover")
        if tau is not None and (not finite(tau) or not 0 <= tau <= 1):
            return reject("invalid_turnover")
        metrics.update(
            shares=qty,
            value_usd=value,
            unused_budget_usd=budget - value,
            taf_rate_field=field,
            taf_usd=taf,
            gst_usd=gst,
            explicit_usd=explicit,
            friction_deducted_bps=friction_to_deduct,
            cost_bps=fee_bps,
            gate_cost_bps=gate_bps,
            cash_net_edge_bps=gross - fee_bps,
            net_edge_bps=gross - gate_bps,
            positive_net_edge=gross > gate_bps,
            annual_drag_fraction=None
            if tau is None
            else p["days_per_year"] * tau * gate_bps / 1e4,
        )
        if any(type(v) in (int, float) and not finite(v) for v in metrics.values()):
            metrics = {k: None for k in metrics}
            return reject("fee_numeric_overflow")
        assumptions.extend(
            [
                "Equal-price whole-ticket buy/sell arithmetic, not observed fills.",
                "Admission floor is a threshold, not a cash ledger charge.",
                "TAF switches on sell_date; dates and fee rates come from versioned inputs.",
            ]
        )
        report = result(
            "fee_frontier",
            inputs,
            metrics=metrics,
            assumptions=assumptions,
            availability={"net_edge_bps": {"available": True, "reason": None}},
            artifacts={
                "fee_params_sha256": inputs["params_sha256"],
                "fee_schedule_sha256": inputs["schedule_sha256"],
            },
        )
        return conventions.bind(report) if conventions else report
    except (KeyError, TypeError, ValueError, OverflowError):
        return reject("fee_input_invalid_or_missing")

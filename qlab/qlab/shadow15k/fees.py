"""Decimal cumulative order charges from explicitly SHA-bound EVO-882 files."""

from __future__ import annotations

import json
from datetime import date
from decimal import Context, Decimal, InvalidOperation, localcontext
from functools import wraps
from pathlib import Path

from qlab.dynamic_factor.contract import sha256

from .contract import whole

ZERO = Decimal(0)


def decimal_arithmetic(function):
    """Do not inherit a caller's mutable decimal precision or rounding mode."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=50)):
            return function(*args, **kwargs)

    return wrapped


def money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("finite_money_required")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("finite_money_required") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("nonnegative_finite_money_required")
    return number


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("ISO_trading_date_required")
    return value


class FeeBook:
    """No default paths, rate basis, scenario or fee rates. No invoice rounding."""

    def __init__(self, params_path, schedule_path, *, params_sha256, schedule_sha256):
        p_raw, s_raw = Path(params_path).read_bytes(), Path(schedule_path).read_bytes()
        if (sha256(p_raw), sha256(s_raw)) != (params_sha256, schedule_sha256):
            raise ValueError("fee_file_sha_mismatch")
        self.params = json.loads(p_raw, parse_float=Decimal)
        self.schedule = json.loads(s_raw)
        self.binding = {
            "params_sha256": params_sha256,
            "schedule_sha256": schedule_sha256,
        }
        p = self.params
        self.scenario = p["name"]
        if (
            self.scenario not in {"x1", "x2"}
            or money(p["cost_multiplier"])
            != {"x1": Decimal(1), "x2": Decimal(2)}[self.scenario]
        ):
            raise ValueError("unsupported_cost_scenario")
        for key in (
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
        ):
            money(p[key])
        if p["integer_shares"] is not True or p["algo_orders_allowed"] is not False:
            raise ValueError("unsupported_order_policy")
        if p["gst_base"] not in {"all_fees", "broker_only"}:
            raise ValueError("unsupported_GST_base")
        for period in self.schedule["taf_periods"]:
            day(period["start"])
            if period["end_exclusive"] is not None:
                if day(period["end_exclusive"]) <= period["start"]:
                    raise ValueError("invalid_fee_period")
            money(p[period["rate_field"]])
        self.assumptions = list(p["unverified"]) + [
            "SEC/TAF minima and caps applied per order; actual broker invoice mapping unverified.",
            "Frozen Section 31 rate and open-ended future schedule are provisional, not live fee validation.",
            "TAF effective_date basis only, not the research_restored budget convention.",
            "No cent rounding; amounts retain Decimal precision until a rounding contract is frozen.",
        ]

    def rate_field(self, trade_date):
        trade_date = day(trade_date)
        periods = [
            p
            for p in self.schedule["taf_periods"]
            if p["start"] <= trade_date
            and (p["end_exclusive"] is None or trade_date < p["end_exclusive"])
        ]
        if len(periods) != 1:
            raise ValueError("fee_effective_date_uncovered_or_ambiguous")
        return periods[0]["rate_field"]

    @decimal_arithmetic
    def cumulative(self, *, qty, notional, side, trade_date, price_basis):
        """Compute full order-to-date cost; caller books only the cumulative delta."""
        whole(qty)
        value = money(notional)
        if side not in {"BUY", "SELL"} or price_basis not in {
            "reference",
            "cash_bid_ask",
        }:
            raise ValueError("unsupported_side_or_price_basis")
        field = self.rate_field(trade_date)
        if (qty == 0) != (value == 0):
            raise ValueError("quantity_notional_inconsistent")
        p = self.params
        if qty == 0:
            return dict(
                taf_rate_field=field,
                **{
                    k: "0"
                    for k in (
                        "broker",
                        "settlement",
                        "sec",
                        "cat",
                        "taf",
                        "gst",
                        "explicit",
                        "friction",
                        "charged",
                        "gate_floor_diagnostic",
                    )
                },
            )
        broker = money(p["commission_per_order"]) + money(p["platform_per_order"])
        settlement = min(
            money(p["settlement_per_share"]) * qty,
            money(p["settlement_cap_fraction_of_value"]) * value,
        )
        sec = (
            max(
                money(p["sec_fraction_of_sell_value"]) * value,
                money(p["sec_min_per_sell"]),
            )
            if side == "SELL"
            else ZERO
        )
        rate = money(p[field])
        taf = (
            min(
                max(rate * qty, money(p["taf_min_per_sell"])),
                money(p["taf_max_per_sell"]),
            )
            if side == "SELL" and rate
            else ZERO
        )
        cat = money(p["cat_per_share_each_side"]) * qty
        gst = (
            broker + settlement + sec + taf + cat
            if p["gst_base"] == "all_fees"
            else broker
        ) * money(p["gst_rate"])
        mult = money(p["cost_multiplier"])
        explicit = broker + settlement + sec + taf + cat + gst
        full_friction = (
            value
            * (
                money(p["spread_roundtrip_bps"])
                + money(p["extra_slippage_roundtrip_bps"])
            )
            / 20000
        )
        friction = full_friction * (mult if price_basis == "reference" else mult - 1)
        diagnostic = (
            max(
                explicit + full_friction,
                value * money(p["gate_floor_roundtrip_bps"]) / 20000,
            )
            * mult
        )
        lines = {
            k: v * mult
            for k, v in dict(
                broker=broker,
                settlement=settlement,
                sec=sec,
                cat=cat,
                taf=taf,
                gst=gst,
                explicit=explicit,
            ).items()
        }
        lines.update(
            friction=friction,
            charged=explicit * mult + friction,
            gate_floor_diagnostic=diagnostic,
        )
        return {"taf_rate_field": field, **{k: str(v) for k, v in lines.items()}}

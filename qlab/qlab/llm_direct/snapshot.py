"""Causal model input and one immutable execution object; no data fetching."""

from __future__ import annotations

from copy import deepcopy

from qlab.dynamic_factor.contract import is_sha
from qlab.shadow15k.ledger import timestamp
from qlab.shadow15k.fees import decimal_arithmetic

from .contract import (
    PROFILE_SHA,
    VERSION,
    bindings,
    canonical,
    decimal_string,
    digest,
    whole,
)


@decimal_arithmetic
def build_decision(payload):
    main = bindings()
    spec = main["input_snapshot"]
    fields = set(spec["required_top_level_fields"]) - {"snapshot_id", "input_sha256"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("input.exact_decision_fields_required")
    d = deepcopy(payload)
    canonical(d)
    assets = spec["asset_order"]
    if (
        d["arm_version"] != VERSION
        or d["profile_sha256"] != PROFILE_SHA
        or d["asset_order"] != assets
        or d["exchange_timezone"] != "America/New_York"
    ):
        raise ValueError("input.identity_mismatch")
    cutoff = timestamp(d["information_cutoff_utc"])
    manifest = d["source_manifest"]
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("input.source_manifest_required")
    for r in manifest:
        if (
            not is_sha(r.get("sha256"))
            or timestamp(r["published_at"]) > cutoff
            or timestamp(r["observed_at"]) > cutoff
        ):
            raise ValueError("input.future_or_unknown_source")
    if (
        not is_sha(d["calendar_sha256"])
        or not d["calendar_id"]
        or d["diagnostic_state_kind_or_authorized_forward_state_receipt"]
        != "SYNTHETIC_E0"
    ):
        raise ValueError("input.offline_synthetic_only")
    for key in ("bars252", "derived_TR", "raw_prices_close", "adv20_usd"):
        if set(d[key]) != set(assets):
            raise ValueError("input.panel_required:" + key)
    if set(d["eligibility"]) != set(assets[:-1]) or any(
        x == "UNKNOWN" or x not in spec["three_state_eligibility"]
        for x in d["eligibility"].values()
    ):
        raise ValueError("input.eligibility_unknown")
    if sum(x == "VERIFIED_ELIGIBLE" for x in d["eligibility"].values()) < 50:
        raise ValueError("input.eligible_count_below50")
    common_calendar = None
    source_shas = {r["sha256"] for r in manifest}
    for s in assets:
        decimal_string(d["raw_prices_close"][s], positive=True)
        decimal_string(d["adv20_usd"][s], positive=True)
        rows = d["bars252"][s]
        if len(rows) != 252 or any(set(r) != set(spec["row_fields"]) for r in rows):
            raise ValueError("input.history252_required")
        days = [r["session"] for r in rows]
        if (
            len(set(days)) != 252
            or days != sorted(days)
            or days[-1] != d["decision_session"]
            or (common_calendar is not None and days != common_calendar)
        ):
            raise ValueError("input.calendar_mismatch")
        common_calendar = days
        if digest(days) != d["calendar_sha256"]:
            raise ValueError("input.calendar_sha_mismatch")
        for r in rows:
            if (
                r["symbol"] != s
                or r["availability_reason"] is not None
                or r["source_sha256"] not in source_shas
                or timestamp(r["source_published_at_utc"]) > cutoff
                or timestamp(r["observed_at_utc"]) > cutoff
            ):
                raise ValueError("input.future_or_invalid_bar")
            prices = [
                decimal_string(r[k], positive=True)
                for k in (
                    "raw_open_usd",
                    "raw_high_usd",
                    "raw_low_usd",
                    "raw_close_usd",
                )
            ]
            if (
                not prices[2]
                <= min(prices[0], prices[3])
                <= max(prices[0], prices[3])
                <= prices[1]
            ):
                raise ValueError("input.ohlc_invalid")
            if type(r["raw_volume_shares"]) is not int or r["raw_volume_shares"] < 0:
                raise ValueError("input.volume_invalid")
        if rows[-1]["raw_close_usd"] != d["raw_prices_close"][s]:
            raise ValueError("input.close_mismatch")
        tr = d["derived_TR"][s]
        if len(tr) != 252:
            raise ValueError("input.TR252_required")
        for p in tr:
            decimal_string(p, positive=True)
        if (
            s != "QQQ"
            and d["eligibility"][s] == "VERIFIED_ELIGIBLE"
            and decimal_string(d["raw_prices_close"][s]) < 20
        ):
            raise ValueError("input.close_below20_eligible")
    if not isinstance(d["causal_events"], list):
        raise ValueError("input.causal_events_required")
    for r in d["causal_events"]:
        if (
            r.get("source_sha256") not in source_shas
            or timestamp(r["observed_at"]) > cutoff
            or timestamp(r["published_at"]) > cutoff
        ):
            raise ValueError("input.future_action")
    state = d["x2_control_state"]
    if (
        set(state) != set(spec["state_fields"])
        or state["unresolved_intents"]
        or type(state["risk_latch"]) is not bool
    ):
        raise ValueError("input.unreconciled_state")
    for k in (
        "inventory_qty",
        "holding_age_sessions",
        "cooldown_remaining_sessions",
        "lot_first_fill_session",
    ):
        if set(state[k]) != set(assets):
            raise ValueError("input.inventory_panel_required")
    for s in assets:
        for k in (
            "inventory_qty",
            "holding_age_sessions",
            "cooldown_remaining_sessions",
        ):
            whole(state[k][s])
    for k in ("nav_usd", "available_cash_usd", "receivable_dividends_usd"):
        decimal_string(state[k], positive=k == "nav_usd")
    nav = (
        sum(
            decimal_string(d["raw_prices_close"][s]) * state["inventory_qty"][s]
            for s in assets
        )
        + decimal_string(state["available_cash_usd"])
        + decimal_string(state["receivable_dividends_usd"])
    )
    if nav != decimal_string(state["nav_usd"]):
        raise ValueError("input.nav_mismatch")
    if set(d["required_action_plan_M"]) != set(assets):
        raise ValueError("input.required_M_panel")
    for s, q in d["required_action_plan_M"].items():
        if whole(q) > state["inventory_qty"][s]:
            raise ValueError("input.M_cannot_add_risk")
    if set(d["policy_state"]) != {
        "global_position",
        "drawdown_fraction",
        "integrity_exits",
    }:
        raise ValueError("input.policy_fields_required")
    whole(d["policy_state"]["global_position"])
    decimal_string(d["policy_state"]["drawdown_fraction"])
    if not isinstance(d["policy_state"]["integrity_exits"], list) or any(
        s not in assets[:-1] for s in d["policy_state"]["integrity_exits"]
    ):
        raise ValueError("input.integrity_state_invalid")
    h = digest(d)
    return dict(d, snapshot_id="snapshot:" + h, input_sha256=h)


def verify_decision(decision):
    raw = {
        k: v for k, v in decision.items() if k not in {"snapshot_id", "input_sha256"}
    }
    if build_decision(raw) != decision:
        raise ValueError("input.decision_hash_mismatch")


def execution_snapshot(decision, payload, fees):
    """Copy once; every repeat sees precisely these bytes and no live state."""
    verify_decision(decision)
    required = {
        "reference_open_session",
        "reference_open_utc",
        "raw_open_usd",
        "x2_control_state",
        "required_plan_M",
        "risk_age_cooldown_state",
        "fee_binding",
        "adv20_usd",
        "eligibility",
        "calendar_sha256",
        "corporate_action_and_cash_receipts",
        "input_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("execution.required_fields_missing")
    p = deepcopy(payload)
    canonical(p)
    if (
        p["input_sha256"] != decision["input_sha256"]
        or p["reference_open_session"] <= decision["decision_session"]
        or timestamp(p["reference_open_utc"]).date().isoformat()
        != p["reference_open_session"]
        or timestamp(p["reference_open_utc"])
        <= timestamp(decision["information_cutoff_utc"])
    ):
        raise ValueError("execution.session_or_input_mismatch")
    expected = {
        "x2_control_state": decision["x2_control_state"],
        "required_plan_M": decision["required_action_plan_M"],
        "risk_age_cooldown_state": decision["policy_state"],
        "adv20_usd": decision["adv20_usd"],
        "eligibility": decision["eligibility"],
        "calendar_sha256": decision["calendar_sha256"],
        "corporate_action_and_cash_receipts": decision["causal_events"],
        "fee_binding": fees.binding,
    }
    if (
        fees.scenario != "x2"
        or decision["cost_bindings"] != fees.binding
        or any(p[k] != v for k, v in expected.items())
    ):
        raise ValueError("execution.state_or_x2_binding_mismatch")
    if set(p["raw_open_usd"]) != set(decision["asset_order"]):
        raise ValueError("execution.prices_missing")
    for price in p["raw_open_usd"].values():
        decimal_string(price, positive=True)
    return p

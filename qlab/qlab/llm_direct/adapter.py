"""One deterministic target, monotone feasibility, full-plan x2 fees, strict G>K."""

from __future__ import annotations

from decimal import Decimal

from qlab.shadow15k.fees import decimal_arithmetic

from .contract import digest, validate_output
from .snapshot import execution_snapshot

ZERO = Decimal(0)


def net_orders(current, target, session, mandatory):
    return [
        dict(
            symbol=s,
            side="BUY" if target[s] > current[s] else "SELL",
            planned_qty=abs(target[s] - current[s]),
            exchange_trade_date=session,
            time_in_force="DAY",
            protective=target[s] < current[s]
            and mandatory[s] < current[s]
            and target[s] <= mandatory[s],
        )
        for s in sorted(current)
        if current[s] != target[s]
    ]


def full_cost(orders, prices, fees):
    return sum(
        (
            Decimal(
                fees.cumulative(
                    qty=o["planned_qty"],
                    notional=Decimal(prices[o["symbol"]]) * o["planned_qty"],
                    side=o["side"],
                    trade_date=o["exchange_trade_date"],
                    price_basis="reference",
                )["charged"]
            )
            for o in orders
        ),
        ZERO,
    )


@decimal_arithmetic
def required_plan(decision, ranks=None):
    """Independent protective M remains available when the model abstains."""
    assets = decision["asset_order"]
    state = decision["x2_control_state"]
    current = state["inventory_qty"]
    ages = state["holding_age_sessions"]
    policy = decision["policy_state"]
    risk = state["risk_latch"] or Decimal(policy["drawdown_fraction"]) >= Decimal(
        "0.15"
    )
    rank = {s: i + 1 for i, s in enumerate(ranks or [])}
    m = dict(current)
    for s in assets[:-1]:
        if current[s] and (
            risk
            or s in policy["integrity_exits"]
            or decision["eligibility"][s] != "VERIFIED_ELIGIBLE"
            or ages[s] >= 20
            or (ranks is not None and 5 <= ages[s] <= 9 and rank.get(s, 65) > 20)
            or (ranks is not None and 10 <= ages[s] <= 19 and rank.get(s, 65) > 5)
        ):
            m[s] = 0
    if m != decision["required_action_plan_M"]:
        raise ValueError("plan.required_M_mismatch")
    return m


@decimal_arithmetic
def raw_target(decision, ranks):
    """Age occupies slots first; never substitute an affordable lower rank."""
    assets = decision["asset_order"]
    state = decision["x2_control_state"]
    current = state["inventory_qty"]
    ages = state["holding_age_sessions"]
    policy = decision["policy_state"]
    risk = state["risk_latch"] or Decimal(policy["drawdown_fraction"]) >= Decimal(
        "0.15"
    )
    m = required_plan(decision, ranks)
    retained = [s for s in assets[:-1] if m[s]]
    retained.sort(key=lambda s: (-ages[s], s))
    if len(retained) > 5:
        raise ValueError("plan.existing_slots_invalid")
    chosen = list(retained)
    if not risk and policy["global_position"] >= 5:
        for s in ranks:
            if len(chosen) == 5:
                break
            if (
                s not in chosen
                and current[s] == 0
                and state["cooldown_remaining_sessions"][s] == 0
                and m[s] == current[s]
            ):
                chosen.append(s)
    nav = Decimal(state["nav_usd"])
    target = {s: 0 for s in assets}
    for s in chosen:
        q = int(Decimal("0.04") * nav / Decimal(decision["raw_prices_close"][s]))
        target[s] = current[s] if current[s] and ages[s] < 5 else q
    satellite = sum(
        Decimal(decision["raw_prices_close"][s]) * target[s] for s in assets[:-1]
    )
    if satellite > Decimal("0.20") * nav or any(
        Decimal(decision["raw_prices_close"][s]) * target[s] > Decimal("0.04") * nav
        for s in assets[:-1]
    ):
        raise ValueError("plan.satellite_cap")
    target["QQQ"] = max(
        0,
        int(
            (Decimal("0.98") * nav - satellite)
            / Decimal(decision["raw_prices_close"]["QQQ"])
        ),
    )
    if policy["global_position"] < 3:
        target = {s: 0 for s in assets}
        target["QQQ"] = min(
            int(Decimal("0.98") * nav / Decimal(decision["raw_prices_close"]["QQQ"])),
            current["QQQ"]
            + int(Decimal("0.40") * nav / Decimal(decision["raw_prices_close"]["QQQ"])),
        )
    elif policy["global_position"] < 5 or risk:
        target = dict(m)  # no opportunistic top-up between startup and first signal
    return m, target, chosen


@decimal_arithmetic
def adapt(raw, decision, execution, fees):
    x = execution_snapshot(decision, execution, fees)
    if decision["policy_state"]["global_position"] < 3:
        raise ValueError("plan.startup_has_no_LLM_decision_use_initialization_plan")
    output = validate_output(raw, decision)
    current = decision["x2_control_state"]["inventory_qty"]
    if output["status"] == "ABSTAIN":
        m = required_plan(decision)
        p = dict(m)
        chosen = []
    else:
        m, target, chosen = raw_target(decision, output["ranked_symbols"])
        if {r["symbol"]: r["target_qty"] for r in output["targets"]} != target:
            raise ValueError("plan.raw_target_policy_mismatch")
        p = dict(target)
    prices = x["raw_open_usd"]
    trace = ["VALIDATE", "REQUIRED_M", "OPTIONAL_TARGET", "PRICE_CANCEL"]
    cancelled = []
    for s in decision["asset_order"][:-1]:
        if p[s] > current[s] and Decimal(prices[s]) < 20:
            p[s] = current[s]
            cancelled.append(s)
        if m[s] < current[s]:
            p[s] = min(p[s], m[s])
    raw_plan = dict(p)
    nav = Decimal(decision["x2_control_state"]["nav_usd"])
    cash = Decimal(decision["x2_control_state"]["available_cash_usd"])
    session = x["reference_open_session"]
    m_orders = net_orders(current, m, session, m)
    cm = full_cost(m_orders, prices, fees)

    def feasible(q, *, mandatory=False):
        orders = net_orders(current, q, session, m)
        cost = full_cost(orders, prices, fees)
        buys = sum(
            Decimal(prices[o["symbol"]]) * o["planned_qty"]
            for o in orders
            if o["side"] == "BUY"
        )
        sells = sum(
            Decimal(prices[o["symbol"]]) * o["planned_qty"]
            for o in orders
            if o["side"] == "SELL"
        )
        open_nav = (
            cash
            + Decimal(decision["x2_control_state"]["receivable_dividends_usd"])
            + sum(Decimal(prices[s]) * current[s] for s in current)
        )
        remaining = cash + sells - buys - cost
        cap = Decimal("0.50") if mandatory and not buys else Decimal("0.20")
        if remaining < 0 or (buys + sells) / (2 * nav) > cap:
            return False
        if any(
            Decimal(prices[o["symbol"]]) * o["planned_qty"]
            > Decimal(x["adv20_usd"][o["symbol"]]) * Decimal("0.01")
            for o in orders
        ):
            return False
        if buys and remaining < Decimal("0.02") * (open_nav - cost):
            return False
        return True

    if not feasible(m, mandatory=True):
        raise ValueError("plan.required_M_unverifiable_or_infeasible")
    # One pass, fixed least-priority first. Never restore buys or search a second subset.
    trace.append("FEASIBILITY")
    priority = list(reversed(chosen)) + ["QQQ"]
    for s in priority:
        while p[s] > max(current[s], m[s]) and not feasible(p):
            p[s] -= 1
    if not feasible(p):
        p = dict(m)
    if any(p[s] > max(raw_plan[s], current[s]) for s in p):
        raise ValueError("plan.feasibility_increased_quantity")
    trace.append("FINAL_P")
    p_orders = net_orders(current, p, session, m)
    cp = full_cost(p_orders, prices, fees)
    trace.extend(["COSTS", "G_K"])
    forecasts = {
        r["symbol"]: r["gross_return_bps"] for r in output["forecasts_h10_bps"]
    }
    gain = ZERO
    forecast_missing = False
    for s in current:
        if p[s] != m[s]:
            if forecasts.get(s) is None:
                forecast_missing = True
            else:
                gain += (
                    Decimal(prices[s])
                    * (p[s] - m[s])
                    / nav
                    * Decimal(forecasts[s])
                    / 10000
                )
    threshold = max(ZERO, cp - cm) / nav
    approved = output["status"] == "READY" and not forecast_missing and gain > threshold
    # No mutation after this point. Mandatory M survives rejection independently.
    final = dict(p if approved else m)
    orders = net_orders(current, final, session, m)
    signature = dict(
        approval_bit=approved,
        final_holdings65=[final[s] for s in decision["asset_order"]],
        sorted_economic_net_orders=orders,
    )
    return dict(
        output=output,
        M=m,
        P=p,
        final=final,
        orders=orders,
        signature=signature,
        signature_sha256=digest(signature),
        execution_snapshot_sha256=digest(x),
        C2_M=str(cm),
        C2_P=str(cp),
        G=str(gain),
        K=str(threshold),
        rejection_reason="missing_forecast"
        if forecast_missing
        else (None if approved else "G_not_strictly_greater_than_K"),
        cancelled_buy_symbols=cancelled,
        trace=trace,
        execution_verified=False,
        runtime_consumable=False,
    )


@decimal_arithmetic
def initialization_plan(decision, execution, fees):
    """THREE_SESSION_QQQ_ONLY_V03: fixed orders, never a model G/K decision."""
    x = execution_snapshot(decision, execution, fees)
    position = decision["policy_state"]["global_position"]
    state = decision["x2_control_state"]
    current = state["inventory_qty"]
    if position not in {0, 1, 2} or any(
        current[s] for s in decision["asset_order"][:-1]
    ):
        raise ValueError("startup.phase_or_inventory_invalid")
    nav = Decimal(state["nav_usd"])
    price = Decimal(x["raw_open_usd"]["QQQ"])
    cap = min(
        int(Decimal("0.40") * nav / price),
        max(0, int(Decimal("0.98") * nav / price) - current["QQQ"]),
    )
    for add in range(cap, -1, -1):
        target = dict(current, QQQ=current["QQQ"] + add)
        orders = net_orders(current, target, x["reference_open_session"], current)
        cost = full_cost(orders, x["raw_open_usd"], fees)
        available = Decimal(state["available_cash_usd"]) - add * price - cost
        open_nav = (
            Decimal(state["available_cash_usd"])
            + current["QQQ"] * price
            + Decimal(state["receivable_dividends_usd"])
        )
        if (
            available >= 0
            and (not add or available >= Decimal("0.02") * (open_nav - cost))
            and add * price / (2 * nav) <= Decimal("0.20")
            and add * price <= Decimal(x["adv20_usd"]["QQQ"]) * Decimal("0.01")
        ):
            return dict(
                policy_id="THREE_SESSION_QQQ_ONLY_V03",
                phase=position,
                final=target,
                orders=orders,
                cost_x2=str(cost),
                available_cash=str(available),
                turnover=str(add * price / (2 * nav)),
                runtime_consumable=False,
                execution_verified=False,
            )
    raise ValueError("startup.cash_or_fees_unverifiable")

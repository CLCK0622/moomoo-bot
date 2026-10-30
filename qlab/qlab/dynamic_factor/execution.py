"""Offline startup and M -> P NAV arithmetic with the frozen v1 fee budget."""

from __future__ import annotations

import json
import math
import re

from .contract import digest, is_sha, result, sha256, unavailable
from .conventions import FIXTURES
from .fees import finite, iso_date
from .pipeline import price_basis_check
from .input_scope import reject_b2_inputs

FEE_PENDING = "Frozen v1 fee policy; actual billing and order-versus-fill minima remain unverified."


class OptionalRejected(ValueError):
    def __init__(self, reason, M):
        super().__init__(reason)
        self.metrics = {"allowed": False, "selected_plan": "M", "selected_holdings": M}


class OrderCosts:
    def __init__(self, policy, sell_date, rate_basis):
        self.policy = policy
        self.date = iso_date(sell_date)
        raw = (FIXTURES / "fee_params_x2.json").read_bytes()
        if sha256(raw) != policy.document["cost_mapping"]["x2_sha256"]:
            raise ValueError("fee_params_not_bound_to_conventions")
        self.params = json.loads(raw)
        raw_schedule = (FIXTURES / "fee_schedule.json").read_bytes()
        self.binding = {
            "fee_params_sha256": sha256(raw),
            "schedule_sha256": sha256(raw_schedule),
            "date": sell_date,
            "rate_basis": rate_basis,
        }
        schedule = json.loads(raw_schedule)
        if rate_basis not in ("effective_date", "research_restored"):
            raise ValueError("rate_basis_unknown")
        if policy.document["version"] == "v1.0.1":
            rate_basis = "research_restored"
        if rate_basis == "research_restored":
            field = schedule["research_rate_field"]
        elif rate_basis == "effective_date":
            periods = [
                p
                for p in schedule["taf_periods"]
                if p["start"] <= sell_date
                and (p["end_exclusive"] is None or sell_date < p["end_exclusive"])
            ]
            if len(periods) != 1:
                raise ValueError("fee_effective_date_uncovered_or_ambiguous")
            field = periods[0]["rate_field"]
        else:
            raise ValueError("rate_basis_unknown")
        if policy.document["version"] == "v1.0.1":
            field = "taf_per_share_sell_restored"
            self.binding["rate_basis"] = "research_restored"
        self.taf_rate = self.params[field]

    def quote(self, orders, prices):
        reject_b2_inputs({"orders": orders, "prices": prices}, "orders")
        from .fee_model import order_cost

        floor = float(
            re.search(
                r",([0-9.]+)\*filled_notional\)",
                self.policy.document["cost_mapping"]["floor_policy"]["x1"],
            )[1]
        )
        total = 0.0
        for symbol in sorted(orders):
            q = orders[symbol]
            if type(q) is not int:
                raise ValueError("trade.integer_quantity_required")
            if q:
                price = prices[symbol]
                if not finite(price) or price <= 0:
                    raise ValueError("data.raw_open_price_invalid")
                total += order_cost(
                    self.params,
                    "buy" if q > 0 else "sell",
                    abs(q),
                    abs(q) * price,
                    floor,
                    "reference",
                )["research_cost_usd"]
        return total


def startup_intent(position, previous_nav, inventory, previous_close, policy):
    """Lock the budget at the prior close; the next open only rounds/checks cash."""
    reject_b2_inputs(inventory, "orders")
    init = policy.document["initialization"]
    if (
        type(position) is not int
        or position < 0
        or not finite(previous_nav)
        or previous_nav <= 0
    ):
        raise ValueError("startup.invalid_position_or_nav")
    if not isinstance(inventory, dict) or any(
        type(q) is not int or q < 0 for q in inventory.values()
    ):
        raise ValueError("startup.inventory_invalid")
    if position == 0 and (
        previous_nav != init["initial_cash_usd"] or any(inventory.values())
    ):
        raise ValueError("startup.O0_requires_E0_and_zero_inventory")
    expression = init["max_buy_notional_each_startup_open"].split("*")[0]
    budget = (
        float(expression) * previous_nav
        if position in init["startup_open_positions"]
        else 0
    )
    payload = {
        "position": position,
        "previous_close": previous_close,
        "previous_nav": previous_nav,
        "inventory": inventory,
        "max_buy_notional": budget,
        **policy.binding,
    }
    return dict(payload, intent_sha256=digest(payload))


def lock_startup_intent(
    position,
    previous_nav,
    inventory,
    previous_close,
    *,
    policy,
    ledger,
    start_id,
    scope_id,
):
    """Caller records the preclose decision in the same durable accounting scope.

    A stitched test/forward account keeps one scope across folds. Each independent
    train probe/meta has its own explicitly identified scope. No implicit reset.
    """
    intent = startup_intent(position, previous_nav, inventory, previous_close, policy)
    if position == 0:
        ledger.record(
            "startup_scope/" + scope_id, {"start_id": start_id, **policy.binding}
        )
    elif ledger.recorded("startup_scope/" + scope_id) != {
        "start_id": start_id,
        **policy.binding,
    }:
        raise ValueError("startup.scope_not_carried")
    ledger.record(f"startup/{start_id}/intent/{position}", intent)
    return intent


def _tool(tool, request, policy, names, calculate):
    metrics = dict.fromkeys(names)
    reasons = []
    try:
        reject_b2_inputs(request, "orders")
        if policy.document["version"] != "v1.0.1":
            raise ValueError("prereg_pending_v0.2")
        metrics.update(calculate())
    except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else f"{tool}.input_invalid_or_missing"
        )
        if isinstance(exc, OptionalRejected):
            metrics.update(exc.metrics)
    return policy.bind(
        result(
            tool,
            {"request": request, **policy.binding},
            metrics=metrics,
            reasons=reasons,
            availability={
                k: unavailable(reasons[0])
                if metrics[k] is None
                else {"available": True, "reason": None}
                for k in names
            },
            assumptions=[
                FEE_PENDING,
                "Trusted, pinned evidence is required; computed plans are reference arithmetic, not executable orders.",
            ],
        )
    )


def initial_build_turnover_check(request, *, conventions, ledger=None):
    p = conventions.document

    def calculate():
        price_basis_check(request["context"])
        init, portfolio = p["initialization"], conventions.profile["portfolio"]
        intent = request["intent"]
        expected = startup_intent(
            intent["position"],
            intent["previous_nav"],
            intent["inventory"],
            intent["previous_close"],
            conventions,
        )
        if (
            intent != expected
            or request["previous_close"] != intent["previous_close"]
            or not intent["previous_close"] < request["open_timestamp"]
        ):
            raise ValueError("startup.intent_not_locked_at_previous_close")
        pos, inv, nav = intent["position"], intent["inventory"], intent["previous_nav"]
        if ledger is None:
            raise ValueError("startup.persistent_state_required")
        start_id = request["start_id"]
        key = f"startup/{start_id}/{pos}"
        if ledger.recorded(f"startup/{start_id}/intent/{pos}") != intent:
            raise ValueError("startup.preclose_intent_receipt_missing")
        sessions = request["reference_sessions"]
        if (
            sessions != sorted(set(sessions))
            or len(sessions) < pos + 2
            or intent["previous_close"][:10] != sessions[pos]
            or request["open_timestamp"][:10] != sessions[pos + 1]
        ):
            raise ValueError("startup.reference_session_mismatch")
        index = {d: i for i, d in enumerate(conventions.calendar)}
        if any(d not in index for d in sessions) or any(
            index[b] != index[a] + 1 for a, b in zip(sessions, sessions[1:])
        ):
            raise ValueError("startup.reference_session_mismatch")
        if request["sell_date"] != request["open_timestamp"][:10]:
            raise ValueError("startup.fee_date_mismatch")
        if ledger.recorded(key) is not None:
            raise ValueError("startup.position_already_consumed")
        if pos > 0:
            prev = ledger.recorded(f"startup/{start_id}/{pos - 1}")
            if (
                prev is None
                or prev["inventory"] != inv
                or prev["cash"] != request["cash"]
            ):
                raise ValueError("startup.state_not_carried_or_reset")
        cash = request["cash"]
        if (
            not finite(cash)
            or cash < 0
            or (pos == 0 and cash != init["initial_cash_usd"])
        ):
            raise ValueError("startup.cash_invalid")
        prices = request["raw_open_prices"]
        symbol = conventions.profile["portfolio"]["base_ticker"]
        price = prices[symbol]
        if (
            not finite(price)
            or price <= 0
            or any(
                q and (s not in prices or not finite(prices[s]) or prices[s] <= 0)
                for s, q in inv.items()
            )
        ):
            raise ValueError("data.raw_open_price_invalid")
        if any(q for s, q in inv.items() if s != symbol):
            raise ValueError("startup.non_QQQ_inventory")
        costs = OrderCosts(conventions, request["sell_date"], request["rate_basis"])
        invested = math.fsum(q * prices[s] for s, q in inv.items())
        pre_nav = cash + invested
        # No extension/topup after O2. No tilt before the first regular signal.
        budget = min(
            intent["max_buy_notional"],
            2 * init["normal_one_way_cap"] * nav,
            max(0, portfolio["max_invested_fraction"] * pre_nav - invested),
            cash,
        )
        quantity = math.floor(budget / price)
        while quantity > 0:
            fee = costs.quote({symbol: quantity}, prices)
            after_cash = cash - quantity * price - fee
            after_nav = pre_nav - fee
            if (
                after_cash >= 0
                and after_cash >= portfolio["cash_target_min"] * after_nav
                and invested + quantity * price
                <= portfolio["max_invested_fraction"] * after_nav
            ):
                break
            quantity -= 1
        fee = costs.quote({symbol: quantity}, prices)
        inventory = dict(inv)
        inventory[symbol] = inv.get(symbol, 0) + quantity
        output = {
            "allowed": quantity > 0,
            "quantity": quantity,
            "one_way_turnover": quantity * price / (2 * nav),
            "cash": cash - quantity * price - fee,
            "inventory": inventory,
            "fee_x2": fee,
            "position": pos,
            "intent_sha256": intent["intent_sha256"],
            "regular_signal_due": pos >= init["first_regular_signal_close_position"]
            and pos % init["first_regular_signal_close_position"] == 0,
            "fee_binding": costs.binding,
        }
        ledger.record(key, output)
        return output

    return _tool(
        "initial_build_turnover_check",
        request,
        conventions,
        ("allowed", "quantity", "one_way_turnover", "inventory", "cash", "fee_x2"),
        calculate,
    )


def calibrate_gain(rows, matured_dates, *, conventions, context):
    """Equal-date means of within-date bucket means, on common mature labels."""
    reject_b2_inputs({"rows": rows, "context": context}, "calibration")
    price_basis_check(context)
    p = conventions.profile["signal_params"]
    ids = conventions.document["variance_layers"]["family_definitions"][
        "candidate_members"
    ]
    import re

    buckets = int(
        re.search(
            r"floor\((\d+)\*u\)",
            conventions.document["gain_model"]["calibration"]["bucket"],
        )[1]
    )
    by_date = {}
    index = {d: i for i, d in enumerate(context["train_calendar"])}
    for row in rows:
        if (
            row["date"] not in matured_dates
            or row["label_end"] not in context["train_calendar"]
        ):
            raise ValueError("gain.label_outside_mature_train")
        signal = index[row["date"]]
        entry = signal + conventions.document["labels"]["entry_open_offset_from_signal"]
        exit_ = (
            signal
            + conventions.document["labels"]["primary_exit_open_offset_from_signal"]
        )
        if (
            exit_ >= len(index)
            or row["label_entry"] != context["train_calendar"][entry]
            or row["label_end"] != context["train_calendar"][exit_]
        ):
            raise ValueError("gain.label_interval_mismatch")
        by_date.setdefault(row["date"], []).append(row)
    if not by_date or set(by_date) != set(matured_dates):
        raise ValueError("gain.calibration_missing")
    samples = {k: {b: [] for b in range(buckets)} for k in ids}
    q_means = []
    for date_rows in by_date.values():
        if len(date_rows) < p["min_eligible_stocks"] or len(
            {r["symbol"] for r in date_rows}
        ) != len(date_rows):
            raise ValueError("gain.calibration_panel_incomplete")
        q = {r["qqq_h10"] for r in date_rows}
        if len(q) != 1 or not finite(next(iter(q))):
            raise ValueError("gain.benchmark_label_inconsistent")
        q_means.append(next(iter(q)))
        for k in ids:
            bins = {b: [] for b in range(buckets)}
            for r in date_rows:
                u = r["ranks"][k]
                if not finite(u) or not 0 <= u <= 1 or not finite(r["stock_h10"]):
                    raise ValueError("gain.label_or_rank_invalid")
                bins[min(buckets - 1, math.floor(buckets * u))].append(
                    r["stock_h10"] - r["qqq_h10"]
                )
            if not all(bins.values()):
                raise ValueError("gain.calibration_bucket_missing")
            for b in bins:
                samples[k][b].append(math.fsum(bins[b]) / len(bins[b]))
    table = {
        k: [math.fsum(samples[k][b]) / len(samples[k][b]) for b in range(buckets)]
        for k in ids
    }
    payload = {
        "m": table,
        "mu_Q": math.fsum(q_means) / len(q_means),
        "dates": sorted(by_date),
        "context_sha256": digest(context),
        **conventions.binding,
    }
    return dict(payload, calibration_sha256=digest(payload))


def forecast_stock(symbol, request, policy):
    calibration = request["calibration"]
    payload = {k: v for k, v in calibration.items() if k != "calibration_sha256"}
    if (
        digest(payload) != calibration["calibration_sha256"]
        or calibration["context_sha256"] != digest(request["context"])
        or calibration["conventions_sha256"] != policy.raw_sha256
    ):
        raise ValueError("gain.calibration_identity_mismatch")
    factors = request["factor_states"]
    if set(factors) != set(request["pool"]) or not factors:
        raise ValueError("gain.frozen_pool_missing")
    half = policy.profile["lifecycle"]["half_coefficient"]
    if any(v not in (1, half) or isinstance(v, bool) for v in factors.values()):
        raise ValueError("gain.factor_state_invalid")
    total = math.fsum(factors.values())
    alpha = 0.0
    for k, state in factors.items():
        u = request["ranks"][symbol][k]
        table = calibration["m"][k]
        if (
            not finite(u)
            or not 0 <= u <= 1
            or not table
            or not all(finite(x) for x in table)
        ):
            raise ValueError("gain.forecast_missing")
        alpha += state / total * table[min(len(table) - 1, math.floor(len(table) * u))]
    return alpha


def nav_increment(M, P, prices, alpha, mu_Q, E, c_M, c_P, mu_cash=0, qqq="QQQ"):
    """Pure unit arithmetic; quantities already include theta, never apply it twice."""
    if (
        not all(finite(x) for x in (E, mu_Q, mu_cash, c_M, c_P))
        or E <= 0
        or min(c_M, c_P) < 0
    ):
        raise ValueError("gain.invalid_NAV_or_cost")
    delta = {}
    for s in sorted(set(M) | set(P)):
        if (
            type(M.get(s, 0)) is not int
            or type(P.get(s, 0)) is not int
            or min(M.get(s, 0), P.get(s, 0)) < 0
            or not finite(prices[s])
            or prices[s] <= 0
        ):
            raise ValueError("gain.plan_or_price_invalid")
        delta[s] = (P.get(s, 0) - M.get(s, 0)) * prices[s] / E
    stocks = [s for s in sorted(delta) if s != qqq]
    if any(not finite(alpha.get(s)) for s in stocks):
        raise ValueError("gain.forecast_missing")
    cash_weight = -math.fsum(delta[s] for s in sorted(delta))
    G = (
        math.fsum(delta[s] * alpha[s] for s in stocks)
        + mu_Q * math.fsum(delta[s] for s in sorted(delta))
        + mu_cash * cash_weight
    )
    K = max(0, c_P - c_M) / E
    if not all(finite(x) for x in (G, K)):
        raise ValueError("gain.nonfinite_result")
    return {
        "allowed": G > K,
        "G_H10": G,
        "K": K,
        "expected_net_NAV_increment": G - K,
        "gain_nav_bps": G * 1e4,
        "net_edge_bps": (G - K) * 1e4,
        "delta_w": delta,
        "delta_w_cash_gross": cash_weight,
    }


def voluntary_trade_gate(request, *, conventions, ledger=None):
    # One predeclared signal in an accounting scope has one final optional plan.
    key = None
    if (
        isinstance(request, dict)
        and request.get("account_scope")
        and request.get("signal_close")
    ):
        key = f"gain/{request['account_scope']}/{request['signal_close']}"
    if key and ledger is not None:
        saved = ledger.recorded(key + "/outcome")
        if saved is not None and saved["request_sha256"] == digest(request):
            return saved["report"]

    def calculate():
        price_basis_check(request["context"])
        if ledger is None or key is None:
            raise ValueError("gain.persistent_signal_scope_required")
        index = {d: i for i, d in enumerate(conventions.calendar)}
        signal = request["signal_close"][:10]
        if (
            signal not in index
            or index[signal] + 1 >= len(index)
            or request["execution_date"] != conventions.calendar[index[signal] + 1]
            or request["sell_date"] != request["execution_date"]
        ):
            raise ValueError("gain.signal_execution_or_fee_date_mismatch")
        stage_key = f"v02/{request['run_id']}/{request['fold_id']}"
        s1, s2 = ledger.recorded(stage_key + "/S1"), ledger.recorded(stage_key + "/S2")
        if (
            s1 is None
            or s2 is None
            or s1.get("calibration") != request["calibration"]
            or s2["pool"] != request["pool"]
        ):
            raise ValueError("gain.frozen_calibration_or_pool_receipt_missing")
        M, P, original = request["M"], request["P"], request["original_inventory"]
        prices, cash = request["raw_open_prices"], request["cash"]
        if (
            not finite(cash)
            or cash < 0
            or any(type(v) is not int or v < 0 for v in original.values())
        ):
            raise ValueError("gain.original_inventory_or_cash_invalid")
        plan_binding = digest(
            {
                k: request[k]
                for k in ("M", "P", "original_inventory", "raw_open_prices", "cash")
            }
        )
        if (
            request["feasibility_receipt"].get("plans_sha256") != plan_binding
            or not is_sha(request["feasibility_receipt"].get("source_sha256"))
            or request["feasibility_receipt"].get("all_constraints_verified")
            is not True
        ):
            raise ValueError("gain.final_plan_feasibility_missing")
        ledger.record(
            key + "/plan", {"request_sha256": digest(request), **conventions.binding}
        )
        if any(P.get(s, 0) > M.get(s, 0) for s in request["required_exit_symbols"]):
            raise ValueError("gain.optional_plan_undoes_required_exit")
        E = cash + math.fsum(q * prices[s] for s, q in original.items())
        costs = OrderCosts(conventions, request["sell_date"], request["rate_basis"])
        c_M, c_P = [
            costs.quote(
                {
                    s: plan.get(s, 0) - original.get(s, 0)
                    for s in set(original) | set(plan)
                },
                prices,
            )
            for plan in (M, P)
        ]
        for plan, cost in ((M, c_M), (P, c_P)):
            if (
                any(type(q) is not int or q < 0 for q in plan.values())
                or cash
                + math.fsum(
                    (original.get(s, 0) - plan.get(s, 0)) * prices[s]
                    for s in set(original) | set(plan)
                )
                - cost
                < 0
            ):
                raise ValueError("gain.plan_not_cash_feasible")
        qqq = conventions.profile["portfolio"]["base_ticker"]
        stocks = (set(original) | set(M) | set(P)) - {qqq}
        try:
            alpha = {s: forecast_stock(s, request, conventions) for s in sorted(stocks)}
            cal = request["calibration"]
            if not finite(cal["mu_Q"]):
                raise ValueError("gain.benchmark_forecast_missing")
            # Validate calibration identity even for QQQ/cash-only plans.
            if (
                cal.get("calibration_sha256")
                != digest({k: v for k, v in cal.items() if k != "calibration_sha256"})
                or cal["context_sha256"] != digest(request["context"])
                or cal["conventions_sha256"] != conventions.raw_sha256
            ):
                raise ValueError("gain.calibration_identity_mismatch")
        except (ValueError, KeyError, TypeError) as exc:
            raise OptionalRejected(
                str(exc) if isinstance(exc, ValueError) else "gain.forecast_missing", M
            ) from exc
        output = nav_increment(
            M,
            P,
            prices,
            alpha,
            cal["mu_Q"],
            E,
            c_M,
            c_P,
            conventions.document["gain_model"]["calibration"]["mu_cash"],
            qqq,
        )
        if (
            cash
            + math.fsum(
                (original.get(s, 0) - P.get(s, 0)) * prices[s]
                for s in set(original) | set(P)
            )
            - c_P
            < 0
        ):
            raise ValueError("gain.plan_not_cash_feasible")
        output.update(
            selected_plan="P" if output["allowed"] else "M",
            selected_holdings=P if output["allowed"] else M,
            C2_M=c_M,
            C2_P=c_P,
            denominator_E=E,
            fee_binding=costs.binding,
        )
        return output

    report = _tool(
        "voluntary_trade_gate",
        request,
        conventions,
        ("allowed", "gain_nav_bps", "net_edge_bps", "G_H10", "K", "selected_plan"),
        calculate,
    )
    if (
        key
        and ledger is not None
        and ledger.recorded(key + "/plan")
        == {"request_sha256": digest(request), **conventions.binding}
    ):
        ledger.record(
            key + "/outcome", {"request_sha256": digest(request), "report": report}
        )
    return report

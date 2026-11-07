"""D12's one finite integer projection, over host-bound inputs and D2.

This module only quotes plans. It neither fills nor posts them, reads markets,
selects a second proposal after G/K, nor grants source/runtime permission. C09
owns provenance; C13 connects the candidate entry points to this same function.
"""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import json

from .contract import digest, sha256
from .execution_amounts import ExactOrderCosts as OrderCosts, amount, decimal_text
from .execution_closure import validate_execution_binding
from .execution_risk import RiskBook
from .isolation import rank_scores
from .input_scope import reject_b2_inputs
from .noncash_v3 import assert_consumer_symbols


TRACE = (
    "VALIDATE_AND_LOCK",
    "REQUIRED_M",
    "RAW_INTEGER_TARGET",
    "OTHER_REDUCTIONS",
    "SATELLITE_BUYS",
    "QQQ_BUY",
    "SEAL_SINGLE_P",
)
OUTPUT_KEYS = {"input_sha256", "NAV_anchor", "M", "P", "net_orders", "reasons", "trace"}


def _canonical(value):
    # Unlike the general reporting envelope, do not normalize NaN to null.
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def locked_targets(signal, *, snapshot, M, exits, eligible, risk_signal):
    """Shared frozen rank/age-slot target generation, before any open rounding.

    Meta supplies the source-bound per-recipe score and lifecycle objects from
    the original selection layer. Solo never consumes that pool or lifecycle.
    Caller weight claims are checked against generated weights, never used.
    """
    meta = snapshot["scope"]["execution_role"] == "current_META_POLICY_execution_layer"
    if signal["recipe_id"] != snapshot["scope"]["recipe_id"]:
        raise ValueError("projection.recipe_identity_mismatch")
    freeze = False
    if meta:
        if signal["scores"] != {}:
            raise ValueError("projection.meta_composite_must_be_generated")
        states, recipes = signal["factor_states"], signal["factor_scores"]
        permissions = risk_signal["origin_context"]["permissions"]
        if (
            type(states) is not dict
            or set(states) != set(recipes)
            or not set(states) <= set(permissions)
            or len(states) > 4
        ):
            raise ValueError("projection.frozen_meta_pool_mismatch")
        if any(type(a) is bool or a not in (1, 0.5) for a in states.values()):
            raise ValueError("projection.meta_lifecycle_state_unknown")
        normalized = {k: rank_scores(recipes[k], eligible) for k in sorted(recipes)}
        total = sum((amount(a) for a in states.values()), Fraction(0))
        if total == 0:
            proof = signal.get("empty_pool_proof")
            if proof != {
                "S2_complete": True,
                "pool": [],
                "source_sha256": risk_signal["origin_context"]["source_sha256"],
                "fold_id": snapshot["scope"]["fold_id"],
            }:
                raise ValueError(
                    "projection.empty_meta_pool_requires_original_S2_proof"
                )
        derived = {
            s: sum(
                (amount(states[k]) * amount(normalized[k][s]) for k in sorted(states)),
                Fraction(0),
            )
            / total
            for s in eligible
            if total
        }
        scores = derived
        theta = total / 20
        freeze = any(a == 0.5 or permissions[k] is not True for k, a in states.items())
    else:
        if any(
            k in signal for k in ("factor_states", "factor_scores", "pool", "lifecycle")
        ):
            raise ValueError("projection.solo_must_not_read_meta_pool")
        theta = Fraction(1, 5)
        scores = {s: amount(v) for s, v in signal["scores"].items()}
    if amount(signal["tilt_fraction"]) != theta:
        raise ValueError("projection.frozen_theta_mismatch")
    if set(scores) != set(eligible) and not (meta and theta == 0):
        raise ValueError("projection.score_or_eligibility_membership")
    ordered = sorted(scores, key=lambda s: (-scores[s], s))
    ranks, i = {}, 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and scores[ordered[j]] == scores[ordered[i]]:
            j += 1
        for s in ordered[i:j]:
            ranks[s] = Fraction(i + 1 + j, 2)
        i = j
    if (
        not (meta and theta == 0)
        and {s: amount(v) for s, v in risk_signal["ranks"].items()} != ranks
    ):
        raise ValueError("projection.D2_ranks_not_same_locked_signal")
    held = sorted(s for s, q in M.items() if q and s != "QQQ")
    if len(held) > 5:
        raise ValueError("projection.held_slots_exceed_frozen_capacity")
    ranked = sorted(
        (s for s in scores if s not in held and s not in exits),
        key=lambda s: (-scores[s], s),
    )
    selected = held + ranked[: 5 - len(held)]
    weights = {s: theta / 5 if s in selected else Fraction(0) for s in M}
    weights["QQQ"] = Fraction(49, 50) - theta
    if {s: amount(v) for s, v in signal["weights"].items()} != weights:
        raise ValueError("projection.caller_weights_not_frozen_targets")
    return scores, selected, weights, freeze


def _orders(original, plan, exits, scores):
    changes = {s: plan[s] - original[s] for s in original if plan[s] != original[s]}
    mandatory = sorted(s for s in exits if changes.get(s, 0) < 0)
    reductions = sorted(s for s, q in changes.items() if q < 0 and s not in exits)
    buys = sorted(
        (s for s, q in changes.items() if q > 0 and s != "QQQ"),
        key=lambda s: (-scores[s], s),
    )
    symbols = (
        mandatory + reductions + buys + (["QQQ"] if changes.get("QQQ", 0) > 0 else [])
    )
    return [
        dict(
            symbol=s,
            side="BUY" if changes[s] > 0 else "SELL",
            quantity=abs(changes[s]),
            priority=i + 1,
        )
        for i, s in enumerate(symbols)
    ]


def _quote(
    original,
    plan,
    prices,
    adv,
    exits,
    scores,
    cash,
    rights,
    nav,
    costs,
    guard,
    policy,
    binding,
    sale_cash,
    *,
    necessary,
):
    if set(plan) != set(original) or any(
        type(q) is not int or q < 0 for q in plan.values()
    ):
        raise ValueError("projection.integer_plan_required")
    orders = _orders(original, plan, exits, scores)
    running, available, total, gross, buys = cash, cash, Fraction(0), Fraction(0), False
    for order in orders:
        s, quantity = order["symbol"], order["quantity"]
        value = quantity * prices[s]
        if value > adv[s] / 100:
            return False, "ADV"
        # Original OrderCosts -> original order_cost, one net order per symbol.
        fee = costs.quote_exact(
            {s: quantity if order["side"] == "BUY" else -quantity},
            {s: Decimal(decimal_text(value))},
            guard=guard,
            execution_binding=binding,
        )
        total += fee
        gross += value
        buying = order["side"] == "BUY"
        buys |= buying
        running += -value - fee if buying else value - fee
        if not buying and sale_cash is not None and s not in sale_cash:
            raise ValueError("projection.actual_sale_cash_availability_unknown")
        available += (
            -value - fee
            if buying
            else (value if sale_cash is None else min(value, sale_cash[s])) - fee
        )
        if running < 0 or available < 0:
            return False, "cash"
    cap = (
        Fraction(1, 2)
        if necessary
        and orders
        and all(o["side"] == "SELL" and o["symbol"] in exits for o in orders)
        else Fraction(1, 5)
    )
    if gross > 2 * nav * cap:
        return False, "turnover"
    invested = sum((q * prices[s] for s, q in plan.items() if q), Fraction(0))
    after_nav = running + invested + rights
    if after_nav <= 0 or running < 0:
        return False, "cash"
    if buys and (available < after_nav / 50 or invested > after_nav * Fraction(49, 50)):
        return False, "buffer"
    return True, dict(
        fees=total, cash=running, available_cash=available, nav=after_nav, orders=orders
    )


def project(
    inputs,
    *,
    risk_book,
    risk_signal,
    execution_binding,
    expected_input_sha256,
    expected_snapshot_sha256,
    expected_signal_sha256,
):
    """Return the closed D1 payload, or reject while leaving original state intact.

    Hash arguments are host capabilities, never accepted from the input wire.
    ``risk_book`` must be the shared D2 object. Input component identities and
    actual reception remain C09's job; this function cannot certify them.
    """
    reject_b2_inputs(inputs, "orders")
    binding = validate_execution_binding(execution_binding)
    if type(risk_book) is not RiskBook:
        raise ValueError("projection.shared_D2_required")
    if type(inputs) is not dict or any(
        k in inputs for k in ("M", "P", "returns", "required_m")
    ):
        raise ValueError("projection.caller_plan_or_returns_forbidden")
    if set(inputs) != {
        "schema",
        "fixture_id",
        "economic_semantics_sha256",
        "close_state",
        "eligibility",
        "execution_open",
        "fee_parameters",
        "locked_signal",
        "source_component_sha256",
        "source_declaration",
    } or inputs["schema"] not in {
        "EVO883.D12.complete-synthetic-projector-input/v1",
        "EVO884.ProjectorInput/v1",
    }:
        raise ValueError("projection.closed_input_schema_required")
    if sha256(_canonical(inputs)) != expected_input_sha256:
        raise ValueError("projection.input_binding_mismatch")
    snapshot = risk_book.snapshot()
    if snapshot["snapshot_sha256"] != expected_snapshot_sha256 or snapshot[
        "execution_binding_sha256"
    ] != digest(binding):
        raise ValueError("projection.snapshot_or_adoption_mismatch")
    if not snapshot["complete"]:
        raise ValueError("projection.D2_incomplete:" + ";".join(snapshot["reasons"]))
    state, close = snapshot["state"], inputs["close_state"]
    signal, opened, eligibility = (
        inputs["locked_signal"],
        inputs["execution_open"],
        inputs["eligibility"],
    )
    original = state["inventory"]
    policy = risk_book._policy
    if inputs["schema"] == "EVO883.D12.complete-synthetic-projector-input/v1":
        if risk_book._guard["request"]["synthetic"] is not True:
            raise ValueError("projection.synthetic_input_not_runtime_source")
        sale_cash = None
    else:
        funding = opened["cash_availability"]
        if funding["mode"] == "research_immediate":
            if snapshot["scope"]["kind"] != "independent_training":
                raise ValueError("projection.ideal_cash_model_diagnostic_only")
            sale_cash = None
        elif funding["mode"] == "accepted_actual":
            sale_cash = {
                s: amount(v) for s, v in funding["available_sale_proceeds"].items()
            }
            if any(v < 0 for v in sale_cash.values()):
                raise ValueError("projection.actual_sale_cash_availability_unknown")
        else:
            raise ValueError("projection.cash_availability_evidence_required")
    # B checks precede numeric consumption, even for subsequently rejected buys.
    symbols = (
        set(opened["raw_open"])
        | set(opened["ADV20_usd_asof_close"])
        | set(signal["scores"])
    )
    if "factor_scores" in signal:
        for row in signal["factor_scores"].values():
            symbols.update(row)
    assert_consumer_symbols(risk_book._guard, "order", symbols, policy)
    if (
        close["inventory"] != original
        or amount(close["cash"]) != amount(state["cash"])
        or amount(close["NAV_anchor"]) != amount(state["nav"])
        or close["signal_close_session"] != snapshot["close_session"]
        or signal["signal_session"] != snapshot["close_session"]
        or opened["session"] != risk_signal["execution_session"]
        or close["execution_open_session"] != opened["session"]
        or close["age"] != state["age"]
        or close["origin"] != state["origin"]
        or close["rights"] != state["rights"]
        or close["receivables"] != state["receivables"]
        or close["unknown_components"] != []
    ):
        raise ValueError("projection.close_state_or_locked_date_mismatch")
    if (
        opened["ADV_unit"] != "USD_per_reference_session"
        or opened["trade_unit"] != "one_US_common_share"
    ):
        raise ValueError("projection.ADV_or_quantity_unit_unknown")
    if _canonical(inputs["fee_parameters"]) != _canonical(
        OrderCosts(policy, opened["session"], "research_restored").params
    ):
        raise ValueError("projection.frozen_fee_parameters_mismatch")
    quantity_state = eligibility["quantity_state"]
    facts = eligibility["states"]
    known = {"VERIFIED_USABLE", "COUNTERFACTUAL_ALL_REQUIRED_GATES_KNOWN"}
    if set(facts) != set(policy.profile["universe"]) or any(
        v not in known | {"UNKNOWN", "VERIFIED_INELIGIBLE", "B_GUARDED", "QUARANTINED"}
        for v in facts.values()
    ):
        raise ValueError("projection.eligibility_facts_required")
    names = sorted(s for s, v in facts.items() if v in known)
    lower = len(names)
    upper = lower + sum(v == "UNKNOWN" for v in facts.values())
    derived_quantity = (
        "VERIFIED_GE50" if lower >= 50 else "VERIFIED_LT50" if upper < 50 else "UNKNOWN"
    )
    if (
        quantity_state != derived_quantity
        or sorted(eligibility["E_t"]) != names
        or eligibility["named_count"] != lower
    ):
        raise ValueError("projection.eligibility_count_or_state_mismatch")
    if quantity_state not in {"VERIFIED_GE50", "VERIFIED_LT50"}:
        raise ValueError("projection.UNKNOWN_no_formal_plan")
    decision = risk_book.decision_due()
    if not decision["order_intent_due"]:
        raise ValueError("projection.no_locked_decision_for_this_open")
    required = risk_book.required_m(
        risk_signal,
        expected_book_id=snapshot["book_id"],
        expected_close_session=snapshot["close_session"],
        expected_snapshot_sha256=expected_snapshot_sha256,
        expected_original_state_sha256=snapshot["original_state_sha256"],
        expected_signal_sha256=expected_signal_sha256,
    )
    if not required["complete"]:
        raise ValueError("projection.M_unavailable:" + ";".join(required["reasons"]))
    M = required["M"]
    exits = {o["symbol"] for o in required["required_exits"]}
    eligible = eligibility["E_t"]
    if (
        type(eligible) is not list
        or len(eligible) != len(set(eligible))
        or not set(eligible) <= set(policy.profile["universe"])
    ):
        raise ValueError("projection.score_or_eligibility_membership")
    if quantity_state == "VERIFIED_GE50" and len(eligible) < 50:
        raise ValueError("projection.GE50_named_members_missing")
    if quantity_state == "VERIFIED_LT50":
        scores, selected, weights, freeze = {}, [], {}, True
    else:
        scores, selected, weights, freeze = locked_targets(
            signal,
            snapshot=snapshot,
            M=M,
            exits=exits,
            eligible=eligible,
            risk_signal=risk_signal,
        )
    prices = {s: amount(v) for s, v in opened["raw_open"].items()}
    adv = {s: amount(v) for s, v in opened["ADV20_usd_asof_close"].items()}
    used = {s for s, q in original.items() if q} | set(selected) | {"QQQ"}
    if (
        not used <= prices.keys()
        or not used <= adv.keys()
        or any(prices[s] <= 0 or adv[s] <= 0 for s in used)
    ):
        raise ValueError("projection.price_or_ADV_unknown")
    # Nonzero rights need C04's accepted valuation, never assumed spendable.
    rights_value = Fraction(0)
    if state["rights"]:
        raise ValueError("projection.accepted_rights_valuation_required")
    if state["receivables"]:
        proof = risk_book._cash_proof
        if proof is None:
            raise ValueError("projection.accepted_rights_valuation_required")
        rights_value = proof.check(state, risk_book._guard)
    cash, nav = amount(close["cash"]), amount(close["NAV_anchor"])
    costs = OrderCosts(policy, opened["session"], "research_restored")

    def feasible(plan, necessary=False):
        return _quote(
            original,
            plan,
            prices,
            adv,
            exits,
            scores,
            cash,
            rights_value,
            nav,
            costs,
            risk_book._guard,
            policy,
            binding,
            sale_cash,
            necessary=necessary,
        )

    ok, _ = feasible(M, True)
    if not ok:
        raise ValueError("projection.necessary_M_infeasible_preserve_state_and_intent")
    regular = decision["regular_decision"]
    if quantity_state == "VERIFIED_LT50" or regular is not True:
        return dict(
            input_sha256=expected_input_sha256,
            NAV_anchor=decimal_text(nav),
            M=M,
            P=deepcopy(M),
            net_orders=_orders(original, M, exits, scores),
            reasons=[
                "projection.LT50_no_new_tilt"
                if quantity_state == "VERIFIED_LT50"
                else "projection.not_regular_decision"
            ],
            trace=list(TRACE),
        )
    targets = {
        s: (weights[s] * nav // prices[s]) if weights[s] else 0 for s in original
    }
    for s in original:
        if s in exits:
            targets[s] = min(targets[s], M[s])
        elif s != "QQQ" and M[s] and state["age"][s] < 5:
            targets[s] = max(targets[s], M[s])
    P, reasons = deepcopy(M), []
    for s in sorted(original):
        if targets[s] < P[s] and s not in exits:
            trial = dict(P, **{s: targets[s]})
            ok, reason = feasible(trial)
            if ok:
                P = trial
            else:
                reasons.append("projection.cancel_reduction:" + s + ":" + reason)
    buys = sorted(
        (s for s in original if s != "QQQ" and targets[s] > P[s]),
        key=lambda s: (-scores[s], s),
    ) + (["QQQ"] if targets["QQQ"] > P["QQQ"] else [])
    for s in buys:
        if s != "QQQ":
            gate = risk_book.entry_allowed(
                s,
                expected_snapshot_sha256=expected_snapshot_sha256,
                expected_execution_session=opened["session"],
            )
            reason = (
                "LT50"
                if quantity_state == "VERIFIED_LT50"
                else "meta_additions_frozen"
                if freeze
                else "price_below20"
                if prices[s] < 20
                else "ineligible"
                if s not in eligible
                else ";".join(gate["reasons"])
                if not gate["allowed"]
                else None
            )
            if reason:
                reasons.append("projection.cancel_buy:" + s + ":" + reason)
                continue
        trial = dict(P, **{s: targets[s]})
        ok, reason = feasible(trial)
        if ok:
            P = trial
        else:
            reasons.append("projection.cancel_buy:" + s + ":" + reason)
    return dict(
        input_sha256=expected_input_sha256,
        NAV_anchor=decimal_text(nav),
        M=M,
        P=P,
        net_orders=_orders(original, P, exits, scores),
        reasons=reasons,
        trace=list(TRACE),
    )


def project_bytes(*args, **kwargs):
    """The same closed payload as exact canonical UTF-8 bytes, no final LF."""
    output = project(*args, **kwargs)
    assert set(output) == OUTPUT_KEYS
    return _canonical(output)

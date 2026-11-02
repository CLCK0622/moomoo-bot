"""C04 owned execution account: locked D1 orders, facts, exact cash and x1 replay.

This is an offline producer component, not a source/permission reader. All
expected hashes are capabilities supplied by C09's host after source acceptance.
No receipt here grants runtime permission. Only the named training model can
synthesize fills; accepted actual fills are retained even if a later fact fails.
"""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from functools import wraps
import json
from threading import RLock

from .contract import canonical, code_sha, digest, is_sha, sha256
from .execution_amounts import ExactOrderCosts
from .execution_cash import dividend_entitlement, issue_cash_proof, payment_amount
from .execution_closure import validate_execution_binding
from .execution_numbers import amount, decimal_text
from .execution_projection import project
from .execution_risk import RiskBook
from .fees import FIXTURES
from .input_scope import reject_b2_inputs
from .noncash_v3 import assert_consumer_symbols
from .reference_validation import utc_instant


MODEL = "reference_full_fill_at_verified_open"


def _r2(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            declaration = dict(
                operation=method.__name__,
                args=deepcopy(list(args)),
                kwargs=deepcopy(kwargs),
                status="pending",
            )
            self._declarations.append(declaration)
            try:
                result = method(self, *args, **kwargs)
                declaration["status"] = "verified"
                if (
                    isinstance(result, dict)
                    and result.get("schema") == "EVO884.ExecutionAccount/v1"
                ):
                    return self.snapshot()
                return result
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                reason = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "accounting.R2_necessary_evidence_unknown"
                )
                declaration.update(status="rejected", reason=reason)
                if reason not in self._reasons:
                    self._reasons.append(reason)
                raise ValueError(reason) from exc

    return call


class ExecutionAccount:
    """One separately bound canonical x2 account, with diagnostic x1 shadow fees.

    The x1 column replays exactly the same fills and order aggregation. It has
    no projector, risk book or alternative orders. A bad later actual fact
    quarantines the account without rolling back earlier occurred fills.
    """

    def __init__(
        self, *, risk_book, expected_snapshot_sha256, execution_binding, execution_mode
    ):
        binding = validate_execution_binding(execution_binding)
        if type(risk_book) is not RiskBook:
            raise ValueError("accounting.owned_D2_book_required")
        snap = risk_book.snapshot()
        if (
            not snap["complete"]
            or snap["snapshot_sha256"] != expected_snapshot_sha256
            or digest(binding) != snap["execution_binding_sha256"]
        ):
            raise ValueError("accounting.complete_bound_original_state_required")
        if execution_mode not in {"accepted_actual", "named_training_diagnostic"} or (
            execution_mode == "named_training_diagnostic"
            and snap["scope"]["kind"] != "independent_training"
        ):
            raise ValueError("accounting.explicit_execution_mode_required")
        self._mode = execution_mode
        self._book = risk_book
        self._policy, self._guard = risk_book._policy, risk_book._guard
        self._binding, self._book_id = binding, snap["book_id"]
        self._scope = snap["scope"]
        self._initial_snapshot_sha256 = expected_snapshot_sha256
        self._state = deepcopy(snap["state"])
        self._date, self._fees = snap["close_session"], amount(snap["fees_x2"])
        self._asof = self._state.get("asof", self._date + "T20:00:00Z")
        self._cash = amount(self._state["cash"])
        self._x1_fees = Fraction(0)
        self._x1_saving = Fraction(0)
        self._x1_cash_difference = Fraction(0)
        self._orders, self._active = {}, None
        self._seen, self._facts, self._fills = {}, [], []
        self._receipts, self._closes, self._reasons = [], [], []
        self._declarations = []
        self._lock = RLock()

    def lock_startup(self, startup_book, *, expected_source_sha256):
        """Consume C05's owned QQQ quantity; do not optimize or post C05's cash.

        C05 is a named diagnostic producer, so this ticket cannot become an
        actual fill receipt. Its incomplete account/risk slots stay incomplete.
        """
        from .execution_startup import StartupBook

        with self._lock:
            self._ready()
            if type(startup_book) is not StartupBook or self._active is not None:
                raise ValueError("accounting.owned_C05_startup_plan_required")
            source = startup_book.snapshot()
            event = startup_book._events[-1]
            intent = source["pending_intent"]
            if (
                digest(source) != expected_source_sha256
                or not is_sha(expected_source_sha256)
                or source["book_id"] != self._book_id
                or self._scope["kind"] != "independent_training"
                or self._mode != "named_training_diagnostic"
                or not source["pending_close"]
                or event["kind"] != "open"
                or source["identity"]["execution_binding"] != self._binding
                or amount(startup_book._previous_close_nav)
                != amount(self._state["nav"])
                or intent["inventory"]["QQQ"] != self._state["inventory"]["QQQ"]
                or intent["previous_close"] != self._state["asof"]
            ):
                raise ValueError("accounting.C05_state_or_source_binding_mismatch")
            quantity = event["output"]["planned_quantity"]
            if type(quantity) is not int or quantity < 0:
                raise ValueError("accounting.C05_integer_quantity_required")
            date = event["timestamp"][:10]
            if (
                date
                != self._policy.calendar[self._policy.calendar.index(self._date) + 1]
            ):
                raise ValueError("accounting.C05_session_mismatch")
            orders = [dict(symbol="QQQ", quantity=quantity)] if quantity else []
            ticket = dict(
                book_id=self._book_id,
                signal_session=self._date,
                execution_session=date,
                selected_plan="C05_STARTUP",
                orders=orders,
                source_input_sha256=expected_source_sha256,
                original_state_sha256=digest(self._state),
                execution_closure_sha256=self._binding["adoption_sha256"],
                startup_price=event["price"],
                model_only=True,
            )
            ticket["intent_sha256"] = digest(intent)
            ticket["ticket_sha256"] = digest(ticket)
            self._active, self._fills = ticket, []
            for index, row in enumerate(orders):
                key = digest([ticket["intent_sha256"], index])
                self._orders[key] = dict(
                    row,
                    filled=0,
                    notional="0",
                    fee_x2="0",
                    fee_x1="0",
                    session=date,
                    status="DAY_OPEN",
                )
            return self.intent()

    def lock_projection(
        self,
        inputs,
        *,
        risk_signal,
        expected_input_sha256,
        expected_snapshot_sha256,
        expected_signal_sha256,
        selected_plan,
        selection_receipt,
        expected_selection_sha256,
    ):
        """Consume the sole D1; selecting M never turns P-M into broker orders."""
        with self._lock:
            self._ready()
            if (
                self._book.snapshot()["close_session"] != self._date
                or self._book.snapshot()["original_state_sha256"] != digest(self._state)
                or self._active is not None
                or selected_plan not in {"M", "P"}
            ):
                raise ValueError("accounting.one_selected_locked_plan_required")
            plan = project(
                inputs,
                risk_book=self._book,
                risk_signal=risk_signal,
                execution_binding=self._binding,
                expected_input_sha256=expected_input_sha256,
                expected_snapshot_sha256=expected_snapshot_sha256,
                expected_signal_sha256=expected_signal_sha256,
            )
            expected_selection = dict(
                book_id=self._book_id,
                close_session=self._date,
                execution_session=inputs["execution_open"]["session"],
                input_sha256=expected_input_sha256,
                snapshot_sha256=expected_snapshot_sha256,
                selected_plan=selected_plan,
                execution_role=self._scope["execution_role"],
            )
            if (
                type(selection_receipt) is not dict
                or set(selection_receipt)
                != set(expected_selection) | {"decision_source_sha256"}
                or any(
                    selection_receipt.get(k) != v for k, v in expected_selection.items()
                )
                or not is_sha(selection_receipt.get("decision_source_sha256"))
                or not is_sha(expected_selection_sha256)
                or digest(selection_receipt) != expected_selection_sha256
            ):
                raise ValueError("accounting.host_bound_final_selection_required")
            target = plan[selected_plan]
            # Preserve the sole D1's frozen order, even when choosing necessary M.
            orders = []
            for row in plan["net_orders"]:
                symbol = row["symbol"]
                q = target[symbol] - self._state["inventory"][symbol]
                if q:
                    orders.append(dict(symbol=symbol, quantity=q))
            missing = {
                s for s, q in target.items() if q != self._state["inventory"][s]
            } - {r["symbol"] for r in orders}
            if missing:
                # P can have undone an M change; use the same D1 ordering helper.
                from .execution_projection import _orders

                required = self._book.required_m(
                    risk_signal,
                    expected_book_id=self._book_id,
                    expected_close_session=self._date,
                    expected_snapshot_sha256=expected_snapshot_sha256,
                    expected_original_state_sha256=digest(self._state),
                    expected_signal_sha256=expected_signal_sha256,
                )
                exits = {r["symbol"] for r in required["required_exits"]}
                orders = [
                    dict(
                        symbol=r["symbol"],
                        quantity=r["quantity"] * (1 if r["side"] == "BUY" else -1),
                    )
                    for r in _orders(
                        self._state["inventory"],
                        target,
                        exits,
                        {
                            s: amount(v)
                            for s, v in inputs["locked_signal"]["scores"].items()
                        },
                    )
                ]
            session = inputs["execution_open"]["session"]
            ticket = dict(
                book_id=self._book_id,
                signal_session=self._date,
                execution_session=session,
                selected_plan=selected_plan,
                source_input_sha256=expected_input_sha256,
                raw_open_sha256=digest(inputs["execution_open"]["raw_open"]),
                selection_sha256=expected_selection_sha256,
                original_state_sha256=digest(self._state),
                orders=deepcopy(orders),
                target=deepcopy(target),
                execution_closure_sha256=self._binding["adoption_sha256"],
            )
            ticket["intent_sha256"] = self._book.order_intent(
                risk_signal,
                expected_signal_sha256=expected_signal_sha256,
                expected_snapshot_sha256=expected_snapshot_sha256,
            )["intent_sha256"]
            ticket["origin_permissions"] = self._book.order_intent(
                risk_signal,
                expected_signal_sha256=expected_signal_sha256,
                expected_snapshot_sha256=expected_snapshot_sha256,
            )["origin_new_risk_enabled"]
            ticket["ticket_sha256"] = digest(ticket)
            self._active = ticket
            self._fills = []
            for index, row in enumerate(orders):
                key = digest([ticket["intent_sha256"], index])
                self._orders[key] = dict(
                    row,
                    filled=0,
                    notional="0",
                    fee_x2="0",
                    fee_x1="0",
                    session=session,
                    status="DAY_OPEN",
                )
            return self.intent()

    def intent(self):
        with self._lock:
            return dict(ticket=deepcopy(self._active), orders=deepcopy(self._orders))

    def _ready(self):
        validate_execution_binding(self._binding)
        if self._reasons:
            raise ValueError(self._reasons[0])

    def _fee(self, order, quantity, notional, scenario):
        costs = ExactOrderCosts(self._policy, order["session"], "research_restored")
        if scenario == "x1":
            raw = (FIXTURES / "fee_params_x1.json").read_bytes()
            if sha256(raw) != self._policy.document["cost_mapping"]["x1_sha256"]:
                raise ValueError("accounting.x1_frozen_parameters_mismatch")
            costs.params = json.loads(raw)
        return costs.quote_exact(
            {order["symbol"]: quantity},
            {order["symbol"]: Decimal(decimal_text(notional))},
            guard=self._guard,
            execution_binding=self._binding,
        )

    def _fill(self, fact, expected_sha256, *, model=False):
        reject_b2_inputs(fact, "orders")
        assert_consumer_symbols(
            self._guard, "order", [fact.get("symbol")], self._policy
        )
        if not is_sha(expected_sha256) or digest(fact) != expected_sha256:
            raise ValueError("accounting.fill_source_binding_mismatch")
        required = {
            "fill_id",
            "order_id",
            "book_id",
            "intent_sha256",
            "symbol",
            "execution_session",
            "quantity",
            "price",
            "source_sha256",
            "executed_at",
            "confirmed_at",
            "cash_available_at",
            "origin",
        }
        if set(fact) != required or not is_sha(fact["source_sha256"]):
            raise ValueError("accounting.closed_fill_fact_required")
        if fact["fill_id"] in self._seen:
            if self._seen[fact["fill_id"]] != fact:
                raise ValueError("accounting.conflicting_duplicate_fill")
            return
        if self._active is None or fact["order_id"] not in self._orders:
            raise ValueError("accounting.current_DAY_intent_required")
        order = self._orders[fact["order_id"]]
        if (
            fact["book_id"] != self._book_id
            or fact["intent_sha256"] != self._active["intent_sha256"]
            or fact["symbol"] != order["symbol"]
            or order["status"] != "DAY_OPEN"
            or fact["execution_session"] != order["session"]
            or utc_instant(fact["executed_at"]).date().isoformat() != order["session"]
            or utc_instant(fact["confirmed_at"]) < utc_instant(fact["executed_at"])
        ):
            raise ValueError("accounting.fill_date_scope_or_intent_mismatch")
        quantity = fact["quantity"]
        if (
            type(quantity) is not int
            or quantity == 0
            or quantity * order["quantity"] <= 0
            or abs(order["filled"] + quantity) > abs(order["quantity"])
        ):
            raise ValueError("accounting.integer_fill_or_remaining_quantity_invalid")
        price = amount(fact["price"])
        if price <= 0:
            raise ValueError("accounting.necessary_price_unknown")
        # Charge cumulative net order/day once; partial fills post only its delta.
        total_q = order["filled"] + quantity
        notional = amount(order["notional"]) + abs(quantity) * price
        x2 = self._fee(order, total_q, notional, "x2")
        x1 = self._fee(order, total_q, notional, "x1")
        delta, delta1 = x2 - amount(order["fee_x2"]), x1 - amount(order["fee_x1"])
        if delta < 0 or delta1 < 0:
            raise ValueError("accounting.cumulative_fee_not_monotonic")
        available = utc_instant(fact["cash_available_at"])
        executed = utc_instant(fact["executed_at"])
        if available < executed:
            raise ValueError("accounting.cash_available_before_actual_fill")
        net = abs(quantity) * price - delta
        cash_change = -quantity * price - delta
        receivable = None
        if quantity < 0 and available > utc_instant(fact["confirmed_at"]):
            if net < 0:
                raise ValueError("accounting.sale_net_cash_negative")
            cash_change = Fraction(0)
            receivable = dict(
                kind="sale_proceeds",
                symbol=fact["symbol"],
                amount=decimal_text(net),
                source_sha256=fact["source_sha256"],
                payment_state="UNPAID",
                available_at=fact["cash_available_at"],
            )
        if quantity < 0 and available > utc_instant(fact["confirmed_at"]):
            receivable["x1_amount"] = decimal_text(abs(quantity) * price - delta1)
        if quantity > 0 and available > utc_instant(fact["confirmed_at"]):
            raise ValueError("accounting.buy_cash_availability_unknown")
        if self._cash + cash_change < 0:
            raise ValueError("accounting.available_cash_infeasible_preserve_intent")
        symbol = fact["symbol"]
        if self._state["inventory"][symbol] + quantity < 0:
            raise ValueError("accounting.short_inventory_forbidden")
        # No mutation before a fully checked fact; no rollback of prior facts.
        self._cash += cash_change
        self._fees += delta
        self._x1_fees += delta1
        self._x1_saving += delta - delta1
        if receivable is None:
            self._x1_cash_difference += delta - delta1
        self._state["inventory"][symbol] += quantity
        if receivable:
            self._state["receivables"][fact["fill_id"]] = receivable
        order.update(
            filled=total_q,
            notional=decimal_text(notional),
            fee_x2=decimal_text(x2),
            fee_x1=decimal_text(x1),
        )
        self._seen[fact["fill_id"]] = deepcopy(fact)
        self._fills.append(
            dict(
                fill_id=fact["fill_id"],
                order_id=fact["order_id"],
                source_sha256=fact["source_sha256"],
                intent_sha256=self._active["intent_sha256"],
                intent_signal_session=self._active["signal_session"],
                execution_session=order["session"],
                symbol=symbol,
                quantity=quantity,
                origin=fact["origin"],
            )
        )
        self._facts.append(
            dict(
                fact=deepcopy(fact),
                source_sha256=expected_sha256,
                status="MODEL" if model else "ACCEPTED_ACTUAL",
            )
        )

    @_r2
    def record_actual(self, facts, *, expected_fact_sha256):
        """Previously accepted real facts survive a later rejected declaration."""
        with self._lock:
            self._ready()
            if (
                self._mode != "accepted_actual"
                or self._receipts
                or (self._active and self._active.get("model_only"))
            ):
                raise ValueError("accounting.model_receipt_cannot_be_actual_execution")
            if len(facts) != len(expected_fact_sha256):
                raise ValueError("accounting.fact_source_cardinality")
            for fact, identity in zip(facts, expected_fact_sha256):
                try:
                    self._fill(fact, identity)
                except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                    self._facts.append(
                        dict(
                            fact=deepcopy(fact),
                            source_sha256=identity,
                            status="REJECTED",
                            reason=str(exc),
                        )
                    )
                    self._reasons.append(str(exc))
                    raise ValueError(str(exc)) from exc
            return self.snapshot()

    @_r2
    def model_open(self, evidence, *, expected_evidence_sha256, model_name):
        """N2 named ideal model only; validate the entire batch before mutation."""
        with self._lock:
            self._ready()
            if (
                self._scope["kind"] != "independent_training"
                or self._mode != "named_training_diagnostic"
                or model_name != MODEL
                or self._active is None
            ):
                raise ValueError("accounting.named_training_model_only")
            reject_b2_inputs(evidence, "orders")
            assert_consumer_symbols(
                self._guard, "order", evidence.get("prices", {}), self._policy
            )
            if (
                digest(evidence) != expected_evidence_sha256
                or not is_sha(expected_evidence_sha256)
                or evidence.get("session") != self._active["execution_session"]
                or not is_sha(evidence.get("source_sha256"))
                or evidence.get("price_kind") != "verified_tradable_raw_open"
                or set(evidence)
                != {
                    "session",
                    "prices",
                    "source_sha256",
                    "price_kind",
                    "asof",
                    "origins",
                }
                or utc_instant(evidence["asof"]).date().isoformat()
                != evidence["session"]
            ):
                raise ValueError("accounting.verified_open_evidence_required")
            if self._active.get("model_only") and amount(
                evidence["prices"].get("QQQ")
            ) != amount(self._active["startup_price"]):
                raise ValueError("accounting.C05_raw_open_drift")
            if (
                not self._active.get("model_only")
                and digest(evidence["prices"]) != self._active["raw_open_sha256"]
            ):
                raise ValueError("accounting.model_raw_open_differs_from_sole_D1")
            facts = []
            for key, row in self._orders.items():
                if row["session"] != evidence["session"]:
                    continue
                if row["filled"]:
                    raise ValueError(
                        "accounting.model_cannot_replace_actual_or_prior_fills"
                    )
                s = row["symbol"]
                if s not in evidence["prices"] or amount(evidence["prices"][s]) <= 0:
                    raise ValueError("accounting.necessary_price_unknown")
                origin = evidence["origins"].get(s)
                if (
                    type(origin) is not str
                    or not origin
                    or (s == "QQQ" and origin != "QQQ_BASE")
                    or (
                        s != "QQQ"
                        and self._state["inventory"][s]
                        and origin != self._state["origin"][s]
                    )
                    or (
                        s != "QQQ"
                        and row["quantity"] > 0
                        and self._active.get("origin_permissions", {}).get(origin)
                        is not True
                    )
                ):
                    raise ValueError("accounting.source_bound_origin_required")
                facts.append(
                    dict(
                        fill_id=digest([key, "MODEL"]),
                        order_id=key,
                        book_id=self._book_id,
                        intent_sha256=self._active["intent_sha256"],
                        symbol=s,
                        execution_session=evidence["session"],
                        quantity=row["quantity"],
                        price=evidence["prices"][s],
                        source_sha256=evidence["source_sha256"],
                        executed_at=evidence["asof"],
                        confirmed_at=evidence["asof"],
                        cash_available_at=evidence["asof"],
                        origin=origin,
                    )
                )
            # Dry-run the identical accounting path on a private copy, no optimizer.
            saved = self._mutable()
            try:
                for fact in facts:
                    self._fill(fact, digest(fact), model=True)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                self._restore(saved)
                raise
            receipt = dict(
                model=model_name,
                execution_verified=False,
                orders_sha256=digest(self._active["orders"]),
                fills_sha256=digest(facts),
                book_id=self._book_id,
                execution_closure_sha256=self._binding["adoption_sha256"],
            )
            self._receipts.append(receipt)
            return deepcopy(receipt)

    def _mutable(self):
        return deepcopy(
            {
                k: getattr(self, k)
                for k in (
                    "_state",
                    "_cash",
                    "_fees",
                    "_x1_fees",
                    "_x1_saving",
                    "_x1_cash_difference",
                    "_orders",
                    "_seen",
                    "_facts",
                    "_fills",
                )
            }
        )

    def _restore(self, saved):
        for key, value in saved.items():
            setattr(self, key, value)

    @_r2
    def record_cash_events(self, events, *, session, expected_event_sha256):
        """Entitlement uses previous-close inventory, never ex-open purchases."""
        with self._lock:
            self._ready()
            if (
                self._fills
                or session
                != self._policy.calendar[self._policy.calendar.index(self._date) + 1]
            ):
                raise ValueError("accounting.cash_events_before_ex_open_fills_required")
            if len(events) != len(expected_event_sha256):
                raise ValueError("accounting.cash_source_cardinality")
            for event, identity in zip(events, expected_event_sha256):
                key = event["event_id"]
                if key in self._seen:
                    if self._seen[key] != event:
                        raise ValueError("accounting.conflicting_cash_event")
                    continue
                row = dividend_entitlement(
                    event,
                    book_id=self._book_id,
                    previous_inventory=self._state["inventory"],
                    session=session,
                    expected_event_sha256=identity,
                    guard=self._guard,
                    policy=self._policy,
                )
                self._state["receivables"][key] = row
                self._seen[key] = deepcopy(event)
                self._facts.append(
                    dict(
                        fact=deepcopy(event),
                        source_sha256=identity,
                        status="CASH_ENTITLEMENT",
                    )
                )
                if row["payment_state"] == "PAYDATE_UNKNOWN":
                    self._reasons.append("accounting.payment_date_unknown")
            return self.snapshot()

    def record_unknown_right(self, event, *, expected_event_sha256):
        """Retain a corporate-action fact; no invented split/FMV/disposal rule."""
        with self._lock:
            if digest(event) != expected_event_sha256 or not is_sha(
                expected_event_sha256
            ):
                raise ValueError("accounting.right_source_binding_mismatch")
            self._state["rights"][expected_event_sha256] = deepcopy(event)
            self._state["unknown_components"].append(
                "corporate_action_units_or_order_unknown"
            )
            self._facts.append(
                dict(
                    fact=deepcopy(event),
                    source_sha256=expected_event_sha256,
                    status="R2_UNRESOLVED_RIGHT",
                )
            )
            self._reasons.append("accounting.R2_rights_or_units_unknown")
            return self.snapshot()

    @_r2
    def settle_cash(self, event, *, expected_event_sha256, asof):
        with self._lock:
            self._ready()
            key = event["receivable_id"]
            row = self._state["receivables"][key]
            if (
                row["payment_state"] == "PAID"
                and row.get("payment_sha256") == expected_event_sha256
                and digest(event) == expected_event_sha256
            ):
                return self.snapshot()
            if utc_instant(asof) < utc_instant(self._asof):
                raise ValueError("accounting.cash_receipt_cannot_backdate_account")
            if row["kind"] == "sale_proceeds" and (
                utc_instant(asof) < utc_instant(row["available_at"])
                or utc_instant(event["available_at"]) < utc_instant(row["available_at"])
            ):
                raise ValueError("accounting.sale_proceeds_not_available")
            value = payment_amount(
                event,
                book_id=self._book_id,
                receivable=row,
                expected_event_sha256=expected_event_sha256,
                asof=asof,
            )
            # Keep the original entitlement/source lineage after payment.
            if row["kind"] == "sale_proceeds":
                self._x1_cash_difference += amount(row["x1_amount"]) - value
            row.update(
                amount="0", payment_state="PAID", payment_sha256=expected_event_sha256
            )
            self._cash += value
            self._facts.append(
                dict(
                    fact=deepcopy(event),
                    source_sha256=expected_event_sha256,
                    status="CASH_AVAILABLE",
                )
            )
            return self.snapshot()

    @_r2
    def close_session(self, evidence, *, expected_evidence_sha256):
        """Actual accounting precedes C06; no risk/lifecycle/selection here."""
        with self._lock:
            self._ready()
            reject_b2_inputs(evidence, "holdings_cash")
            assert_consumer_symbols(
                self._guard, "cash_valuation", evidence.get("prices", {}), self._policy
            )
            date = evidence.get("session")
            next_date = self._policy.calendar[
                self._policy.calendar.index(self._date) + 1
            ]
            if (
                digest(evidence) != expected_evidence_sha256
                or not is_sha(expected_evidence_sha256)
                or date != next_date
                or not is_sha(evidence.get("source_sha256"))
                or evidence.get("price_kind") != "verified_raw_close"
                or evidence.get("rights_complete") is not True
                or evidence.get("cash_events_complete") is not True
                or set(evidence)
                != {
                    "session",
                    "asof",
                    "prices",
                    "source_sha256",
                    "price_kind",
                    "rights_complete",
                    "cash_events_complete",
                    "execution_outcomes",
                }
                or utc_instant(evidence["asof"]).date().isoformat() != date
            ):
                raise ValueError(
                    "accounting.complete_raw_close_and_rights_evidence_required"
                )
            if any(
                utc_instant(row["fact"]["confirmed_at"]) > utc_instant(evidence["asof"])
                for row in self._facts
                if row["status"] == "ACCEPTED_ACTUAL"
                and row["fact"]["execution_session"] == date
            ):
                raise ValueError("accounting.actual_confirmation_after_close_asof")
            if self._state["rights"] or self._state["unknown_components"]:
                raise ValueError("accounting.R2_rights_or_units_unknown")
            nav = self._cash
            for s, q in self._state["inventory"].items():
                if q:
                    if (
                        s not in evidence["prices"]
                        or amount(evidence["prices"][s]) <= 0
                    ):
                        raise ValueError("accounting.necessary_close_price_unknown")
                    nav += q * amount(evidence["prices"][s])
            nav += sum(
                (amount(r["amount"]) for r in self._state["receivables"].values()),
                Fraction(0),
            )
            if nav <= 0:
                raise ValueError("accounting.nonpositive_NAV")
            outcomes = evidence["execution_outcomes"]
            today = {k: r for k, r in self._orders.items() if r["session"] == date}
            if set(outcomes) != set(today) or any(
                type(outcomes[k]) is not dict
                or set(outcomes[k]) != {"filled_quantity", "status", "source_sha256"}
                or type(outcomes[k]["filled_quantity"]) is not int
                or outcomes[k]["filled_quantity"] != row["filled"]
                or outcomes[k]["status"] != "verified_DAY_closed"
                or not is_sha(outcomes[k]["source_sha256"])
                for k, row in today.items()
            ):
                raise ValueError(
                    "accounting.actual_DAY_outcomes_required_no_assumed_zero_fill"
                )
            cancelled = []
            for key, row in self._orders.items():
                if row["session"] == date and row["status"] == "DAY_OPEN":
                    cancelled.append(
                        dict(order_id=key, remaining=row["quantity"] - row["filled"])
                    )
                    row["status"] = "DAY_CLOSED"
            previous_nav = amount(self._state["nav"])
            self._asof = evidence["asof"]
            self._state.update(
                asof=evidence["asof"],
                cash=decimal_text(self._cash),
                nav=decimal_text(nav),
                pending_orders=[],
            )
            accounting = {
                k: deepcopy(self._state[k])
                for k in (
                    "asof",
                    "inventory",
                    "cash",
                    "nav",
                    "rights",
                    "receivables",
                    "pending_orders",
                    "unknown_components",
                    "initialization_count",
                )
            }
            accounting["fees_x2"] = decimal_text(self._fees)
            payload = dict(
                schema="EVO884.AccountClose/v1",
                book_id=self._book_id,
                session=date,
                close_evidence_sha256=expected_evidence_sha256,
                ledger_facts_sha256=digest(self._facts),
                accounting=accounting,
                fills=deepcopy(self._fills),
                cancelled_DAY_orders=cancelled,
                previous_close_NAV=decimal_text(previous_nav),
                return_ratio=str(nav / previous_nav - 1),
                x1_replay=dict(
                    same_orders_and_quantities=True,
                    additional_orders=[],
                    fees_since_open=decimal_text(self._x1_fees),
                    cash_difference=decimal_text(self._x1_cash_difference),
                    net_equity_fee_difference=decimal_text(self._x1_saving),
                    NAV=decimal_text(nav + self._x1_saving),
                    canonical=False,
                ),
                execution_mode=self._mode,
                execution_verified=self._mode == "accepted_actual",
                execution_closure_sha256=self._binding["adoption_sha256"],
                runtime_consumable=False,
                certifiable=False,
            )
            self._closes.append(deepcopy(payload))
            self._active, self._date = None, date
            self._fills = []
            proof = issue_cash_proof(
                self._state,
                book_id=self._book_id,
                guard=self._guard,
                ledger_sha256=digest(self._facts),
            )
            return dict(
                receipt=payload, receipt_sha256=digest(payload), cash_proof=proof
            )

    def bind_next_risk(self, risk_book, *, expected_snapshot_sha256):
        """Accept only C06's resulting state of this account, never an x1 book."""
        with self._lock:
            snap = risk_book.snapshot() if type(risk_book) is RiskBook else {}
            if (
                self._active is not None
                or not snap.get("complete")
                or snap.get("book_id") != self._book_id
                or snap.get("close_session") != self._date
                or snap.get("snapshot_sha256") != expected_snapshot_sha256
                or snap.get("execution_binding_sha256") != digest(self._binding)
                or snap.get("fees_x2") != decimal_text(self._fees)
                or any(
                    snap["state"][k] != self._state[k]
                    for k in (
                        "asof",
                        "inventory",
                        "cash",
                        "nav",
                        "rights",
                        "receivables",
                    )
                )
            ):
                raise ValueError("accounting.C06_account_close_binding_mismatch")
            self._book = risk_book
            self._state = deepcopy(snap["state"])
            return self.snapshot()

    def close_receipts(self):
        with self._lock:
            return deepcopy(self._closes)

    def export_bytes(self):
        """Read-only reconciliation artifact, never an installed authority file.

        This does not grant a checkpoint restore capability or runtime receipt.
        C06 owns state/clock replay; its cash proofs must remain host owned.
        """
        with self._lock:
            return canonical(
                dict(
                    schema="EVO884.ExecutionAccountJournal/v1",
                    initial_snapshot_sha256=self._initial_snapshot_sha256,
                    accounting_source_sha256=code_sha(ExecutionAccount),
                    active_intent=self._active,
                    closes=self._closes,
                    snapshot=self.snapshot(),
                )
            )

    def snapshot(self):
        with self._lock:
            payload = dict(
                schema="EVO884.ExecutionAccount/v1",
                book_id=self._book_id,
                retained_state=deepcopy(self._state),
                cash=None if self._reasons else decimal_text(self._cash),
                NAV=None if self._reasons or self._active else self._state["nav"],
                fees_x2=decimal_text(self._fees),
                declarations=deepcopy(self._declarations),
                facts=deepcopy(self._facts),
                orders=deepcopy(self._orders),
                complete=not self._reasons and self._active is None,
                reasons=list(self._reasons)
                + (["accounting.close_pending"] if self._active else []),
                model_receipts=deepcopy(self._receipts),
                execution_mode=self._mode,
                execution_verified=self._mode == "accepted_actual"
                and self._active is None
                and not self._reasons,
                execution_closure_sha256=self._binding["adoption_sha256"],
                runtime_consumable=False,
                certifiable=False,
            )
            return dict(payload, account_sha256=digest(payload))

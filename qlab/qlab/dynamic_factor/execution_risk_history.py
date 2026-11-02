"""Owned D2 state from observed fills/closes; no price, strategy or order engine.

C04/C09 must supply accepted accounting and actual-fill sources. Their hashes
are host bindings, not self-reported wire credentials. C06 generates clocks,
risk and necessary-M provenance and conserves the observed account declaration.
"""

from copy import deepcopy
import json
from threading import RLock

from .contract import canonical, code_sha, digest, is_sha, sha256
from .conventions import load_conventions
from .execution_clock import ADOPTED_SHA256, validate_clock_binding
from .execution_risk import RiskBook
from .execution_startup import INITIAL_FIELDS, _locked
from .noncash_v3 import checked_guard, zero_exposure
from .reference_validation import utc_instant


ACCOUNTING = {
    "asof",
    "inventory",
    "cash",
    "nav",
    "fees_x2",
    "rights",
    "receivables",
    "pending_orders",
    "unknown_components",
    "initialization_count",
}
FILL = {
    "fill_id",
    "order_id",
    "source_sha256",
    "intent_sha256",
    "intent_signal_session",
    "execution_session",
    "symbol",
    "quantity",
    "origin",
}


class RiskHistory:
    """One book; only replay from its accepted current receipt can restore it."""

    def __init__(
        self,
        *,
        book_id,
        scope,
        genesis,
        expected_genesis_sha256,
        guard,
        clock_binding,
        expected_clock_binding_sha256,
        expected_ruling_sha256,
        policy=None,
    ):
        self._policy = policy or load_conventions()
        self._clock = validate_clock_binding(
            clock_binding, expected_clock_binding_sha256, expected_ruling_sha256
        )
        checked_guard(guard, self._policy)
        if (
            not is_sha(book_id)
            or digest(genesis) != expected_genesis_sha256
            or type(genesis) is not dict
            or set(genesis) != INITIAL_FIELDS
        ):
            raise ValueError("risk.genesis_binding_required")
        zero_exposure(genesis, guard, initial=True)
        if (
            any(
                type(genesis[k]) not in (int, float) or genesis[k] != 15000
                for k in ("cash", "nav", "peak")
            )
            or type(genesis["fees_x2"]) not in (int, float)
            or genesis["fees_x2"] != 0
            or genesis["risk_latch"] is not False
            or type(genesis["initialization_count"]) is not int
            or genesis["initialization_count"] != 1
            or any(
                genesis[k]
                for k in ("age", "origin", "pending_orders", "unknown_components")
            )
        ):
            raise ValueError("risk.proven_zero_E0_genesis_required")
        calendar = self._policy.calendar
        date = utc_instant(genesis["asof"]).date().isoformat()
        if (
            date not in calendar
            or calendar.index(date) == 0
            or calendar.index(date) + 1 == len(calendar)
        ):
            raise ValueError("risk.genesis_calendar_unknown")
        folds = self._policy.fold_manifest()["folds"]
        fold = next((f for f in folds if f["fold_id"] == scope.get("fold_id")), None)
        if scope.get("kind") == "independent_training":
            if (
                fold is None
                or calendar[calendar.index(date) + 1] != fold["train_start"]
            ):
                raise ValueError("risk.training_book_scope_mismatch")
        elif scope.get("kind") == "stitched_test":
            if (
                fold != folds[0]
                or calendar[calendar.index(date) + 1] != fold["test_start"]
            ):
                raise ValueError("risk.continuous_genesis_must_precede_first_fold")
        else:
            raise ValueError("risk.book_scope_required")
        self._initial = dict(
            book_id=book_id,
            scope=deepcopy(scope),
            genesis=deepcopy(genesis),
            expected_genesis_sha256=expected_genesis_sha256,
            guard=deepcopy(guard),
            clock_binding=deepcopy(clock_binding),
            expected_clock_binding_sha256=expected_clock_binding_sha256,
            expected_ruling_sha256=expected_ruling_sha256,
        )
        self._book_id, self._scope, self._guard = (
            book_id,
            deepcopy(scope),
            deepcopy(guard),
        )
        self._genesis = deepcopy(genesis)
        self._date = date
        self._start = calendar[calendar.index(date) + 1]
        self._state = deepcopy(genesis)
        for key in ("fees_x2", "peak", "risk_latch"):
            del self._state[key]
        self._fees = 0
        self._entries, self._cooldown, self._pending = {}, {}, {}
        self._active = None
        self._fills_seen = set()
        self._events, self._declarations = [], []
        self._halt = None
        self._lock = RLock()
        self._prior = dict(
            book_id=book_id,
            close_session=calendar[calendar.index(date) - 1],
            peak=15000,
            risk_latch=False,
        )
        self._refresh_clock(digest([]))
        self._book = self._make_book()
        if not self._book.snapshot()["complete"]:
            raise ValueError(self._book.snapshot()["reasons"][0])

    def _refresh_clock(self, fills_sha):
        self._state["_risk_clock"] = dict(
            book_id=self._book_id,
            scope_id=self._scope["scope_id"],
            ruling_sha256=ADOPTED_SHA256,
            close_session=self._date,
            global_start=self._start,
            entries=deepcopy(self._entries),
            cooldown_anchors=deepcopy(self._cooldown),
            pending_required_exits=deepcopy(self._pending),
            source_fills_sha256=fills_sha,
        )

    def _make_book(self):
        return RiskBook(
            book_id=self._book_id,
            scope=self._scope,
            close_session=self._date,
            state=self._state,
            prior_risk=self._prior,
            fees_x2=self._fees,
            canonical_scenario="x2",
            expected_original_state_sha256=digest(self._state),
            expected_prior_risk_sha256=digest(self._prior),
            guard=self._guard,
            clock_binding=self._clock,
            expected_clock_binding_sha256=digest(self._clock),
            expected_ruling_sha256=ADOPTED_SHA256,
            policy=self._policy,
        )

    @_locked
    def snapshot(self):
        snapshot = self._book.snapshot()
        if self._halt:
            snapshot.update(complete=False, risk=None, reasons=[self._halt])
            del snapshot["snapshot_sha256"]
            snapshot["snapshot_sha256"] = digest(snapshot)
        return snapshot

    @_locked
    def pending_intents(self):
        return dict(
            required_exits=deepcopy(self._pending),
            current_day_order_intent=deepcopy(self._active),
        )

    @_locked
    def prepare_open(self, signal, *, expected_signal_sha256, expected_snapshot_sha256):
        snapshot = self.snapshot()
        if self._halt:
            raise ValueError(self._halt)
        if snapshot["snapshot_sha256"] != expected_snapshot_sha256:
            raise ValueError("risk.snapshot_binding_mismatch")
        position = self._policy.calendar.index(
            self._date
        ) - self._policy.calendar.index(self._start)
        emergency = snapshot["risk"]["risk_latch"] or any(
            age >= 20
            for s, age in self._state["age"].items()
            if s != "QQQ" and self._state["inventory"].get(s)
        )
        if not emergency and not (position >= 5 and position % 5 == 0):
            raise ValueError("risk.not_regular_decision")
        result = self._book.required_m(
            signal,
            expected_book_id=self._book_id,
            expected_close_session=self._date,
            expected_snapshot_sha256=expected_snapshot_sha256,
            expected_original_state_sha256=snapshot["original_state_sha256"],
            expected_signal_sha256=expected_signal_sha256,
        )
        if not result["complete"]:
            raise ValueError(result["reasons"][0])
        intent = dict(
            book_id=self._book_id,
            signal_session=self._date,
            execution_session=signal["execution_session"],
            required_m_sha256=result["required_m_sha256"],
            required_exits=deepcopy(result["required_exits"]),
            origin_new_risk_enabled=deepcopy(result["origin_new_risk_enabled"]),
        )
        intent["intent_sha256"] = digest(intent)
        if self._active is not None and self._active != intent:
            raise ValueError("risk.one_locked_intent_per_open")
        for row in result["required_exits"]:
            old = self._pending.setdefault(
                row["symbol"],
                dict(
                    first_required_close=self._date,
                    reasons=[],
                    remaining_quantity=row["quantity"],
                ),
            )
            if row["reason"] not in old["reasons"]:
                old["reasons"].append(row["reason"])
        self._active = deepcopy(intent)
        output = dict(intent=intent, required_M=result)
        self._events.append(
            dict(
                op="prepare",
                inputs=dict(
                    signal=deepcopy(signal),
                    expected_signal_sha256=expected_signal_sha256,
                    expected_snapshot_sha256=expected_snapshot_sha256,
                ),
                output_sha256=digest(output),
            )
        )
        return output

    @_locked
    def observe_close(
        self,
        date,
        accounting,
        fills,
        *,
        expected_accounting_sha256,
        expected_fills_sha256,
    ):
        inputs = dict(
            date=date,
            accounting=deepcopy(accounting),
            fills=deepcopy(fills),
            expected_accounting_sha256=expected_accounting_sha256,
            expected_fills_sha256=expected_fills_sha256,
        )
        self._declarations.append(
            dict(
                input_index=len(self._declarations),
                status="pending",
                declaration=deepcopy(inputs),
            )
        )
        try:
            output = self._observe(
                date,
                accounting,
                fills,
                expected_accounting_sha256,
                expected_fills_sha256,
            )
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ArithmeticError,
        ) as exc:
            self._halt = (
                str(exc)
                if isinstance(exc, ValueError)
                else "risk.R2_close_state_unknown"
            )
            self._declarations[-1]["status"] = "rejected"
            self._events.append(dict(op="close", inputs=inputs, rejection=self._halt))
            raise ValueError(self._halt) from exc
        self._declarations[-1]["status"] = "verified"
        self._events.append(
            dict(op="close", inputs=inputs, output_sha256=digest(output))
        )
        return output

    def _observe(self, date, accounting, fills, accounting_sha, fills_sha):
        calendar = self._policy.calendar
        if (
            calendar.index(self._date) + 1 >= len(calendar)
            or date != calendar[calendar.index(self._date) + 1]
        ):
            raise ValueError("risk.missing_duplicate_or_nonadjacent_close")
        fold = next(
            (
                f
                for f in self._policy.fold_manifest()["folds"]
                if f["fold_id"] == self._scope["fold_id"]
            ),
            None,
        )
        if self._scope["kind"] == "independent_training" and date > fold["train_end"]:
            raise ValueError("risk.training_book_cannot_enter_other_fold")
        if (
            self._scope["kind"] == "stitched_test"
            and not fold["test_start"] <= date <= fold["test_end"]
        ):
            raise ValueError("risk.explicit_fold_handoff_required")
        if (
            not is_sha(accounting_sha)
            or digest(accounting) != accounting_sha
            or not is_sha(fills_sha)
            or digest(fills) != fills_sha
        ):
            raise ValueError("risk.close_source_binding_mismatch")
        if (
            type(accounting) is not dict
            or set(accounting) != ACCOUNTING
            or utc_instant(accounting["asof"]).date().isoformat() != date
        ):
            raise ValueError("risk.accounting_declaration_required")
        if (
            accounting["initialization_count"] != 1
            or type(accounting["initialization_count"]) is not int
            or accounting["pending_orders"]
        ):
            raise ValueError("risk.capital_reset_or_overnight_orders_forbidden")
        if type(fills) is not list:
            raise ValueError("risk.actual_fill_receipts_required")
        inventory = deepcopy(self._state["inventory"])
        entries, origins, cooldown, pending = (
            deepcopy(self._entries),
            deepcopy(self._state["origin"]),
            deepcopy(self._cooldown),
            deepcopy(self._pending),
        )
        seen = set(self._fills_seen)
        for fill in fills:
            if (
                type(fill) is not dict
                or set(fill) != FILL
                or any(
                    type(fill[k]) is not str or not fill[k] for k in FILL - {"quantity"}
                )
            ):
                raise ValueError("risk.actual_fill_receipts_required")
            if (
                not is_sha(fill["source_sha256"])
                or not is_sha(fill["intent_sha256"])
                or fill["execution_session"] != date
                or fill["intent_signal_session"] != self._date
            ):
                raise ValueError("risk.order_intent_cannot_roll_over")
            if (
                fill["fill_id"] in seen
                or type(fill["quantity"]) is not int
                or fill["quantity"] == 0
            ):
                raise ValueError("risk.duplicate_or_invalid_fill")
            seen.add(fill["fill_id"])
            symbol, quantity = fill["symbol"], fill["quantity"]
            if symbol not in inventory or inventory[symbol] + quantity < 0:
                raise ValueError("risk.fill_inventory_mismatch")
            old = inventory[symbol]
            if symbol != "QQQ":
                if quantity > 0:
                    if (
                        self._active is None
                        or self._active["execution_session"] != date
                        or fill["intent_sha256"] != self._active["intent_sha256"]
                    ):
                        raise ValueError("risk.buy_requires_current_locked_intent")
                    if self._active["origin_new_risk_enabled"].get(
                        fill["origin"]
                    ) is not True or any(
                        r["symbol"] == symbol for r in self._active["required_exits"]
                    ):
                        raise ValueError("risk.required_exit_or_origin_blocks_buy")
                    check = self._book.entry_allowed(
                        symbol,
                        expected_snapshot_sha256=self._book.snapshot()[
                            "snapshot_sha256"
                        ],
                        expected_execution_session=date,
                    )
                    if check["allowed"] is not True:
                        raise ValueError(check["reasons"][0])
                    if old == 0:
                        entries[symbol] = date
                        origins[symbol] = fill["origin"]
                    elif origins[symbol] != fill["origin"]:
                        raise ValueError("risk.addition_cannot_relabel_origin")
                if quantity < 0:
                    if (
                        self._active is None
                        or self._active["execution_session"] != date
                        or fill["intent_sha256"] != self._active["intent_sha256"]
                    ):
                        raise ValueError("risk.required_exit_order_must_be_reissued")
                    if self._state["age"][symbol] < 5 and not any(
                        r["symbol"] == symbol for r in self._active["required_exits"]
                    ):
                        raise ValueError("risk.minimum_age_blocks_voluntary_reduction")
                if old > 0 and old + quantity == 0:
                    if (
                        symbol in pending
                        and "maximum_age" in pending[symbol]["reasons"]
                    ):
                        cooldown[symbol] = date
                    entries.pop(symbol, None)
                    origins.pop(symbol, None)
                    pending.pop(symbol, None)
            else:
                if old + quantity:
                    origins[symbol] = "QQQ_BASE"
                else:
                    origins.pop(symbol, None)
            inventory[symbol] += quantity
            if symbol in pending:
                pending[symbol]["remaining_quantity"] = inventory[symbol]
        if accounting["inventory"] != inventory:
            raise ValueError("risk.inventory_change_without_actual_fills")
        candidate = deepcopy(self._state)
        candidate.update(
            {k: deepcopy(v) for k, v in accounting.items() if k != "fees_x2"}
        )
        candidate["age"] = {
            s: calendar.index(date) - calendar.index(entries[s]) + 1
            for s, q in inventory.items()
            if q and s != "QQQ"
        }
        if inventory.get("QQQ"):
            candidate["age"]["QQQ"] = 0
        candidate["origin"] = origins
        candidate["_risk_clock"] = dict(
            book_id=self._book_id,
            scope_id=self._scope["scope_id"],
            ruling_sha256=ADOPTED_SHA256,
            close_session=date,
            global_start=self._start,
            entries=entries,
            cooldown_anchors=cooldown,
            pending_required_exits=pending,
            source_fills_sha256=fills_sha,
        )
        prior = dict(
            book_id=self._book_id,
            close_session=self._date,
            peak=self._book.snapshot()["risk"]["peak"],
            risk_latch=self._book.snapshot()["risk"]["risk_latch"],
        )
        book = RiskBook(
            book_id=self._book_id,
            scope=self._scope,
            close_session=date,
            state=candidate,
            prior_risk=prior,
            fees_x2=accounting["fees_x2"],
            canonical_scenario="x2",
            expected_original_state_sha256=digest(candidate),
            expected_prior_risk_sha256=digest(prior),
            guard=self._guard,
            clock_binding=self._clock,
            expected_clock_binding_sha256=digest(self._clock),
            expected_ruling_sha256=ADOPTED_SHA256,
            policy=self._policy,
        )
        result = book.snapshot()
        if not result["complete"]:
            raise ValueError(result["reasons"][0])
        if accounting["fees_x2"] < self._fees:
            raise ValueError("risk.accrued_fees_cannot_reset")
        self._date, self._state, self._prior, self._fees = (
            date,
            candidate,
            prior,
            accounting["fees_x2"],
        )
        self._entries, self._cooldown, self._pending = entries, cooldown, pending
        self._fills_seen, self._book, self._active, self._halt = seen, book, None, None
        return result

    @_locked
    def advance_fold(self, fold_id, *, expected_snapshot_sha256):
        if self._halt:
            raise ValueError(self._halt)
        if self.snapshot()["snapshot_sha256"] != expected_snapshot_sha256:
            raise ValueError("risk.snapshot_binding_mismatch")
        if self._scope["kind"] != "stitched_test":
            raise ValueError("risk.independent_training_never_migrates")
        if self._active is not None:
            raise ValueError("risk.fold_handoff_before_new_order_lock")
        folds = self._policy.fold_manifest()["folds"]
        i = next(
            i for i, row in enumerate(folds) if row["fold_id"] == self._scope["fold_id"]
        )
        if (
            i + 1 >= len(folds)
            or folds[i + 1]["fold_id"] != fold_id
            or self._date != folds[i]["test_end"]
            or self._policy.calendar[self._policy.calendar.index(self._date) + 1]
            != folds[i + 1]["test_start"]
        ):
            raise ValueError("risk.fold_skip_or_boundary_unknown")
        self._scope["fold_id"] = fold_id
        self._book = self._make_book()
        result = self.snapshot()
        self._events.append(
            dict(
                op="fold",
                inputs=dict(
                    fold_id=fold_id, expected_snapshot_sha256=expected_snapshot_sha256
                ),
                output_sha256=digest(result),
            )
        )
        return result

    @_locked
    def continue_forward(self, *, expected_snapshot_sha256):
        """Carry the same book; this is no forward-run/calendar authorization."""
        if self._halt:
            raise ValueError(self._halt)
        snapshot = self.snapshot()
        last = self._policy.fold_manifest()["folds"][-1]
        if snapshot["snapshot_sha256"] != expected_snapshot_sha256:
            raise ValueError("risk.snapshot_binding_mismatch")
        if (
            self._scope["kind"] != "stitched_test"
            or self._scope["fold_id"] != last["fold_id"]
            or self._date != last["test_end"]
            or self._active is not None
        ):
            raise ValueError("risk.forward_requires_continuous_terminal_book")
        if self._policy.calendar.index(self._date) + 1 >= len(self._policy.calendar):
            raise ValueError("risk.verified_next_calendar_required")
        self._scope["kind"] = "forward"
        self._book = self._make_book()
        result = self.snapshot()
        self._events.append(
            dict(
                op="forward",
                inputs=dict(expected_snapshot_sha256=expected_snapshot_sha256),
                output_sha256=digest(result),
            )
        )
        return result

    @_locked
    def export_bytes(self):
        return canonical(
            dict(
                schema="EVO884.RiskHistory/v1",
                initial=self._initial,
                history_source_sha256=code_sha(RiskHistory),
                events=self._events,
                declarations=self._declarations,
                pending_required_exits=self._pending,
                active_order_intent=self._active,
                halt_reason=self._halt,
                snapshot=self.snapshot(),
            )
        )

    @classmethod
    def restore(
        cls, raw, *, expected_sha256, expected_book_id, expected_scope, policy=None
    ):
        if not is_sha(expected_sha256) or sha256(raw) != expected_sha256:
            raise ValueError("risk.current_history_bytes_mismatch")
        payload = json.loads(raw)
        if (
            payload.get("schema") != "EVO884.RiskHistory/v1"
            or payload["initial"]["book_id"] != expected_book_id
            or payload["initial"]["scope"] != expected_scope
        ):
            raise ValueError("risk.history_scope_mismatch")
        book = cls(**payload["initial"], policy=policy)
        for event in payload["events"]:
            try:
                if event["op"] == "prepare":
                    output = book.prepare_open(**event["inputs"])
                elif event["op"] == "close":
                    output = book.observe_close(**event["inputs"])
                elif event["op"] == "fold":
                    output = book.advance_fold(**event["inputs"])
                elif event["op"] == "forward":
                    output = book.continue_forward(**event["inputs"])
                else:
                    raise ValueError("risk.history_event_unknown")
            except ValueError as exc:
                if event.get("rejection") != str(exc):
                    raise ValueError("risk.history_replay_mismatch") from exc
            else:
                if event.get("rejection") or digest(output) != event["output_sha256"]:
                    raise ValueError("risk.history_replay_mismatch")
        if book.export_bytes() != raw:
            raise ValueError("risk.history_replay_mismatch")
        return book

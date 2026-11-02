"""Shared D2 predicates; clock parameters require an externally approved binding.

RiskHistory generates the clocks from actual fill/close declarations. This
immutable view consumes its host-bound close state and computes necessary M.
It does not execute orders, account fees or certify C09 source identity.
There is deliberately no clock default or installed authority path here.
"""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import re

from .contract import code_sha, digest, is_sha
from .conventions import authoritative, load_conventions
from .fees import finite
from .execution_clock import ADOPTED_SHA256, validate_clock_binding
from .execution_closure import validate_execution_binding
from .noncash_v3 import checked_guard, zero_exposure
from .reference_definition_v301 import FROZEN, frozen_documents, member_definition
from .state_v2 import necessary_state_known


SHARED_NAME = "EVO883-D12-shared-execution-contract-v3.0.1.json"
SNAPSHOT_KEYS = {
    "schema",
    "book_id",
    "scope",
    "close_session",
    "original_state_sha256",
    "state",
    "prior_risk",
    "prior_risk_sha256",
    "fees_x2",
    "risk",
    "clock_binding",
    "age_clock",
    "cooldown_boundary",
    "ruling_sha256",
    "canonical_scenario",
    "shared_contract_sha256",
    "execution_closure_sha256",
    "execution_binding_sha256",
    "risk_source_sha256",
    "complete",
    "reasons",
    "runtime_consumable",
    "certifiable",
    "snapshot_sha256",
}
M_KEYS = {
    "schema",
    "book_id",
    "close_session",
    "execution_session",
    "snapshot_sha256",
    "original_state_sha256",
    "signal_sha256",
    "shared_contract_sha256",
    "execution_closure_sha256",
    "execution_binding_sha256",
    "risk_source_sha256",
    "M",
    "age_clock",
    "cooldown_boundary",
    "ruling_sha256",
    "required_exits",
    "origin_new_risk_enabled",
    "complete",
    "reasons",
    "runtime_consumable",
    "certifiable",
    "required_m_sha256",
}


def _positive(value):
    return type(value) in (int, float) and finite(value) and value > 0


def position_clock_check(state, book_id, scope, date, policy):
    clock = state.get("_risk_clock")
    if (
        type(clock) is not dict
        or set(clock)
        != {
            "book_id",
            "scope_id",
            "ruling_sha256",
            "close_session",
            "entries",
            "cooldown_anchors",
            "pending_required_exits",
            "global_start",
            "source_fills_sha256",
        }
        or clock["book_id"] != book_id
        or clock["scope_id"] != scope["scope_id"]
        or clock["ruling_sha256"] != ADOPTED_SHA256
        or clock["close_session"] != date
        or not is_sha(clock["source_fills_sha256"])
        or any(
            type(clock[k]) is not dict
            for k in ("entries", "cooldown_anchors", "pending_required_exits")
        )
        or clock["global_start"] not in policy.calendar
    ):
        raise ValueError("risk.position_clock_unknown")
    index = policy.calendar.index(date)
    start = policy.calendar.index(clock["global_start"])
    folds = policy.fold_manifest()["folds"]
    fold = next((f for f in folds if f["fold_id"] == scope["fold_id"]), None)
    if scope["kind"] == "independent_training":
        if (
            fold is None
            or clock["global_start"] != fold["train_start"]
            or not start - 1 <= index <= policy.calendar.index(fold["train_end"])
        ):
            raise ValueError("risk.training_book_scope_mismatch")
    if scope["kind"] == "stitched_test":
        if (
            fold is None
            or clock["global_start"] != folds[0]["test_start"]
            or not policy.calendar.index(fold["test_start"]) - 1
            <= index
            <= policy.calendar.index(fold["test_end"])
        ):
            raise ValueError("risk.continuous_book_scope_mismatch")
    held = {s for s, q in state["inventory"].items() if q and s != "QQQ"}
    if set(clock["entries"]) != held:
        raise ValueError("risk.position_clock_inventory_mismatch")
    for symbol, entry in clock["entries"].items():
        if (
            entry not in policy.calendar
            or not start <= policy.calendar.index(entry) <= index
            or state["age"][symbol] != index - policy.calendar.index(entry) + 1
        ):
            raise ValueError("risk.position_age_not_generated_from_entry")
    for symbol, anchor in clock["cooldown_anchors"].items():
        if (
            symbol not in policy.profile["universe"]
            or anchor not in policy.calendar
            or not start <= policy.calendar.index(anchor) <= index
        ):
            raise ValueError("risk.cooldown_anchor_unknown")


def cooldown_remaining(clock, symbol, date, policy):
    anchor = clock["cooldown_anchors"].get(symbol)
    return (
        0
        if anchor is None
        else max(0, 5 - (policy.calendar.index(date) - policy.calendar.index(anchor)))
    )


def _close_risk(prior, nav, book_id, previous_session):
    if (
        type(prior) is not dict
        or set(prior) != {"book_id", "close_session", "peak", "risk_latch"}
        or prior["book_id"] != book_id
        or prior["close_session"] != previous_session
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(prior["peak"]))
        or Decimal(str(prior["peak"])) < 15000
        or type(prior["risk_latch"]) is not bool
        or not _positive(nav)
    ):
        raise ValueError("risk.prior_risk_or_close_NAV_unknown")
    peak = max(Decimal("15000"), Decimal(str(prior["peak"])), Decimal(str(nav)))
    # Exact ratios do not inherit a caller's mutable Decimal context. There
    # is no monetary rounding choice here; C04 owns the accounting amounts.
    ratio = Fraction(str(nav)) / Fraction(peak)
    latch = prior["risk_latch"] or ratio <= Fraction(85, 100)
    return dict(
        peak=format(peak, "f"),
        drawdown=str(1 - ratio),
        risk_latch=latch,
        warning=ratio <= Fraction(90, 100),
        satellite_additions_allowed=not latch,
    )


class RiskBook:
    """One immutable observed close, with no caller M/P/returns or numeric reader.

    Expected hashes are host capabilities, not claims accepted from a request
    wire. C09 must bind them to accepted sources. Merely rehashing a fabricated
    state/clock document does not certify it. Missing clock binding retains the
    state and generated account risk, but never returns a complete M.
    """

    def __init__(
        self,
        *,
        book_id,
        scope,
        close_session,
        state,
        prior_risk,
        fees_x2,
        canonical_scenario,
        expected_original_state_sha256,
        expected_prior_risk_sha256,
        guard,
        clock_binding,
        expected_clock_binding_sha256,
        expected_ruling_sha256,
        policy=None,
    ):
        self._policy = policy or load_conventions()
        if (
            not authoritative(self._policy)
            or self._policy.document["version"] != "v3.0.0"
        ):
            raise ValueError("risk.frozen_v3_required")
        self._shared = frozen_documents()[SHARED_NAME]
        if not is_sha(book_id):
            raise ValueError("risk.book_identity_required")
        if canonical_scenario != "x2":
            raise ValueError("risk.canonical_x2_required")
        if (
            type(scope) is not dict
            or set(scope)
            != {
                "kind",
                "scope_id",
                "member_id",
                "fold_id",
                "attempt_id",
                "execution_role",
                "recipe_id",
                "execution_binding",
            }
            or scope["kind"] not in {"independent_training", "stitched_test", "forward"}
            or any(
                type(v) is not str or not v.strip()
                for k, v in scope.items()
                if k != "execution_binding"
            )
            or scope["execution_role"] not in self._shared["applies_to"]
        ):
            raise ValueError("risk.book_scope_required")
        self._execution_binding = validate_execution_binding(scope["execution_binding"])
        self._book_id = book_id
        self._scope = deepcopy(scope)
        role = scope["execution_role"]
        if role in {
            "independent_candidate_reference",
            "independent_meta_reference_probe_component",
        }:
            if (
                member_definition(scope["member_id"], execution_role=role)["recipe_id"]
                != scope["recipe_id"]
            ):
                raise ValueError("risk.origin_context_role_mismatch")
        elif role == "candidate_solo_probe":
            if (
                scope["member_id"] != scope["recipe_id"]
                or scope["recipe_id"]
                not in self._policy.document["variance_layers"]["family_definitions"][
                    "candidate_members"
                ]
            ):
                raise ValueError("risk.origin_context_role_mismatch")
        elif (
            scope["member_id"] != "META_POLICY_V3"
            or scope["recipe_id"] != "META_POLICY_V3"
        ):
            raise ValueError("risk.origin_context_role_mismatch")
        self._date = close_session
        self._state = deepcopy(state)
        self._guard = deepcopy(guard)
        self._fees_x2 = fees_x2
        self._prior_risk = deepcopy(prior_risk)
        self._risk, self._clock = None, None
        self._reasons = []
        # Retain every state field on failure; never normalize unknowns away.
        try:
            if (
                not is_sha(expected_original_state_sha256)
                or digest(state) != expected_original_state_sha256
                or not is_sha(expected_prior_risk_sha256)
                or digest(prior_risk) != expected_prior_risk_sha256
            ):
                raise ValueError("risk.original_state_or_prior_binding_mismatch")
            calendar = self._policy.calendar
            if close_session not in calendar or calendar.index(close_session) == 0:
                raise ValueError("risk.calendar_not_adjacent")
            previous_session = calendar[calendar.index(close_session) - 1]
            checked_guard(guard, self._policy)
            necessary_state_known(state)
            zero_exposure(state, guard)
            if (
                type(fees_x2) not in (int, float)
                or not finite(fees_x2)
                or fees_x2 < 0
                or type(state.get("initialization_count")) is not int
                or state["initialization_count"] != 1
                or type(state["cash"]) not in (int, float)
                or not finite(state["cash"])
                or state["cash"] < 0
                or type(state["nav"]) not in (int, float)
            ):
                raise ValueError("risk.required_state_unknown")
            self._risk = _close_risk(
                prior_risk, state["nav"], book_id, previous_session
            )
            self._clock = self._bound_clock(
                clock_binding, expected_clock_binding_sha256, expected_ruling_sha256
            )
            position_clock_check(state, book_id, scope, close_session, self._policy)
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ArithmeticError,
        ) as exc:
            self._reasons.append(
                str(exc)
                if isinstance(exc, ValueError)
                else "risk.required_state_unknown"
            )

    @staticmethod
    def _bound_clock(binding, expected_binding_sha, expected_ruling_sha):
        return validate_clock_binding(
            binding, expected_binding_sha, expected_ruling_sha
        )

    def snapshot(self):
        validate_execution_binding(self._execution_binding)
        payload = dict(
            schema="EVO884.CloseRiskSnapshot/v1",
            book_id=self._book_id,
            scope=deepcopy(self._scope),
            close_session=self._date,
            original_state_sha256=digest(self._state),
            state=deepcopy(self._state),
            prior_risk=deepcopy(self._prior_risk),
            prior_risk_sha256=digest(self._prior_risk),
            fees_x2=self._fees_x2,
            risk=deepcopy(self._risk),
            clock_binding=deepcopy(self._clock),
            age_clock=deepcopy(self._clock["age_clock"]) if self._clock else None,
            cooldown_boundary=deepcopy(self._clock["cooldown_boundary"])
            if self._clock
            else None,
            ruling_sha256=self._clock["ruling_sha256"] if self._clock else None,
            canonical_scenario="x2",
            shared_contract_sha256=FROZEN[SHARED_NAME],
            execution_closure_sha256=self._execution_binding["adoption_sha256"],
            execution_binding_sha256=digest(self._execution_binding),
            risk_source_sha256=code_sha(RiskBook),
            complete=not self._reasons,
            reasons=list(self._reasons),
            runtime_consumable=False,
            certifiable=False,
        )
        return dict(payload, snapshot_sha256=digest(payload))

    def required_m(
        self,
        signal,
        *,
        expected_book_id,
        expected_close_session,
        expected_snapshot_sha256,
        expected_original_state_sha256,
        expected_signal_sha256,
    ):
        snapshot = self.snapshot()
        reasons = list(self._reasons)
        M, exits = None, []
        flags = None
        execution_session = (
            signal.get("execution_session") if type(signal) is dict else None
        )
        try:
            if (
                expected_book_id != self._book_id
                or expected_close_session != self._date
                or expected_snapshot_sha256 != snapshot["snapshot_sha256"]
                or expected_original_state_sha256 != snapshot["original_state_sha256"]
            ):
                raise ValueError("risk.snapshot_binding_mismatch")
            if reasons:
                raise ValueError(reasons[0])
            if (
                type(signal) is not dict
                or set(signal)
                != {
                    "book_id",
                    "signal_session",
                    "execution_session",
                    "ranks",
                    "origin_context",
                }
                or not is_sha(expected_signal_sha256)
                or digest(signal) != expected_signal_sha256
                or signal["book_id"] != self._book_id
                or signal["signal_session"] != self._date
            ):
                raise ValueError("risk.signal_binding_mismatch")
            calendar = self._policy.calendar
            if (
                calendar.index(self._date) + 1 >= len(calendar)
                or calendar[calendar.index(self._date) + 1] != execution_session
            ):
                raise ValueError("risk.calendar_not_adjacent")
            if self._scope["kind"] == "stitched_test":
                next_fold = next(
                    (
                        f
                        for f in self._policy.fold_manifest()["folds"]
                        if f["test_start"] <= execution_session <= f["test_end"]
                    ),
                    None,
                )
                if next_fold is None or next_fold["fold_id"] != self._scope["fold_id"]:
                    raise ValueError("risk.new_fold_context_required_no_old_pool")
            role = self._scope["execution_role"]
            meta = role == "current_META_POLICY_execution_layer"
            context = signal["origin_context"]
            if meta:
                if (
                    type(context) is not dict
                    or set(context)
                    != {
                        "source_sha256",
                        "signal_session",
                        "permissions",
                        "fold_id",
                        "execution_closure_sha256",
                    }
                    or not is_sha(context["source_sha256"])
                    or context["signal_session"] != self._date
                    or context["fold_id"] != self._scope["fold_id"]
                    or context["execution_closure_sha256"]
                    != self._execution_binding["adoption_sha256"]
                    or type(context["permissions"]) is not dict
                ):
                    raise ValueError("risk.origin_context_role_mismatch")
            elif context is not None:
                raise ValueError("risk.solo_must_not_read_current_pool")
            permissions = (
                context["permissions"] if meta else {self._scope["recipe_id"]: True}
            )
            candidates = self._policy.document["variance_layers"]["family_definitions"][
                "candidate_members"
            ]
            if any(
                name not in candidates or value is not None and type(value) is not bool
                for name, value in permissions.items()
            ):
                raise ValueError("risk.origin_state_unknown")
            flags = {
                name: False if self._risk["risk_latch"] else value
                for name, value in sorted(permissions.items())
            }
            if type(signal["ranks"]) is not dict:
                raise ValueError("risk.rank_state_unknown")
            candidate = dict(sorted(self._state["inventory"].items()))
            for symbol, quantity in candidate.items():
                if not quantity or symbol == "QQQ":
                    continue
                age = self._state["age"][symbol]
                origin = self._state["origin"][symbol]
                if type(origin) is not str or not origin:
                    raise ValueError("risk.origin_state_unknown")
                if not meta and origin != self._scope["recipe_id"]:
                    raise ValueError("risk.solo_origin_recipe_mismatch")
                rank = signal["ranks"].get(symbol)
                if rank is not None and (
                    not _positive(rank)
                    or rank < 1
                    or rank > len(self._policy.profile["universe"])
                ):
                    raise ValueError("risk.rank_state_unknown")
                flag = flags.get(origin)
                reason = None
                if self._risk["risk_latch"]:
                    reason = "account_drawdown_latch"
                elif age >= 20:
                    reason = "maximum_age"
                elif age >= 5:
                    threshold = 20 if age < 10 else 5
                    if flag is False or rank is not None and rank > threshold:
                        reason = "origin_disabled" if flag is False else "rank_exit"
                    elif flag is None or rank is None:
                        raise ValueError("risk.rank_or_origin_unknown")
                if reason is not None:
                    candidate[symbol] = 0
                    exits.append(dict(symbol=symbol, quantity=quantity, reason=reason))
            M = candidate
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ArithmeticError,
        ) as exc:
            reason = (
                str(exc)
                if isinstance(exc, ValueError)
                else "risk.required_state_unknown"
            )
            if reason not in reasons:
                reasons.append(reason)
            M, exits = None, []
            flags = None
        payload = dict(
            schema="EVO884.RequiredM/v1",
            book_id=self._book_id,
            close_session=self._date,
            execution_session=execution_session,
            snapshot_sha256=snapshot["snapshot_sha256"],
            original_state_sha256=snapshot["original_state_sha256"],
            signal_sha256=expected_signal_sha256,
            shared_contract_sha256=FROZEN[SHARED_NAME],
            execution_closure_sha256=self._execution_binding["adoption_sha256"],
            execution_binding_sha256=digest(self._execution_binding),
            risk_source_sha256=code_sha(RiskBook),
            M=M,
            age_clock=deepcopy(snapshot["age_clock"]),
            cooldown_boundary=deepcopy(snapshot["cooldown_boundary"]),
            ruling_sha256=snapshot["ruling_sha256"],
            required_exits=exits,
            origin_new_risk_enabled=flags,
            complete=not reasons,
            reasons=reasons,
            runtime_consumable=False,
            certifiable=False,
        )
        return dict(payload, required_m_sha256=digest(payload))

    def entry_allowed(
        self, symbol, *, expected_snapshot_sha256, expected_execution_session
    ):
        """Only a necessary gate; it neither selects a name nor authors an order."""
        from .noncash_v3 import assert_consumer_symbols

        snapshot = self.snapshot()
        allowed, remaining, regular = None, None, None
        reasons = list(self._reasons)
        try:
            if expected_snapshot_sha256 != snapshot["snapshot_sha256"]:
                raise ValueError("risk.snapshot_binding_mismatch")
            if reasons:
                raise ValueError(reasons[0])
            calendar = self._policy.calendar
            i = calendar.index(self._date)
            if i + 1 >= len(calendar) or calendar[i + 1] != expected_execution_session:
                raise ValueError("risk.calendar_not_adjacent")
            if symbol == "QQQ":
                raise ValueError("risk.QQQ_base_policy_separate")
            assert_consumer_symbols(self._guard, "order", [symbol], self._policy)
            clock = self._state["_risk_clock"]
            remaining = cooldown_remaining(clock, symbol, self._date, self._policy)
            position = i - calendar.index(clock["global_start"])
            regular = position >= 5 and position % 5 == 0
            allowed = not self._risk["risk_latch"] and remaining == 0 and regular
            if not allowed:
                reasons.append(
                    "risk.account_latched"
                    if self._risk["risk_latch"]
                    else "risk.cooldown_active"
                    if remaining
                    else "risk.not_regular_decision"
                )
        except (ValueError, KeyError, TypeError) as exc:
            reason = (
                str(exc)
                if isinstance(exc, ValueError)
                else "risk.required_state_unknown"
            )
            if reason not in reasons:
                reasons.append(reason)
        return dict(
            allowed=allowed,
            remaining=remaining,
            regular_decision=regular,
            reasons=reasons,
            snapshot_sha256=snapshot["snapshot_sha256"],
            ruling_sha256=ADOPTED_SHA256,
            runtime_consumable=False,
            certifiable=False,
        )

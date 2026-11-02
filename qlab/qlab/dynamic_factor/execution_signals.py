"""Frozen recipe arithmetic and the separately bound meta monitoring clock.

No market loading, pool selection, fit, performance run or account execution.
Only the original selection layer may select the pool. Independent solo books
never instantiate the meta lifecycle. C06 remains the sole position/risk clock.
"""

from copy import deepcopy
from fractions import Fraction
import math
from threading import RLock

from .contract import digest
from .execution_closure import validate_execution_binding
from .execution_amounts import amount
from .execution_risk import RiskBook
from .noncash_v3 import assert_consumer_symbols


def fixed_scores(
    recipe_id,
    histories,
    *,
    eligible,
    guard,
    policy,
    execution_binding,
    expected_histories_sha256,
    release_context=None,
    expected_release_identity_bytes=None,
):
    """Same fixed grammar for candidate and reference, including all four L20s.

    Host supplies the already accepted same-C histories ending at s. This pure
    function does not certify their source, interval or publication permissions.
    """
    validate_execution_binding(execution_binding)
    ids = policy.document["variance_layers"]["family_definitions"]["candidate_members"]
    if recipe_id not in ids or digest(histories) != expected_histories_sha256:
        raise ValueError("signal.recipe_or_history_binding_mismatch")
    if set(histories) != set(eligible):
        raise ValueError("signal.history_membership_mismatch")
    RiskBook.release_guard(
        guard, policy, release_context, expected_release_identity_bytes
    )
    assert_consumer_symbols(guard, "score", list(histories), policy)
    family, window = recipe_id.split("-L")
    window = int(window)
    scores = {}
    for symbol in sorted(histories):
        values = histories[symbol]
        if type(values) is not list or len(values) != window + 1:
            raise ValueError("signal.complete_asof_window_required")
        values = [amount(v) for v in values]
        if any(v <= 0 for v in values):
            raise ValueError("signal.positive_same_C_required")
        if family in {"F1", "F2"}:
            score = float(values[-1] / values[0] - 1)
            scores[symbol] = score if family == "F1" else -score
        else:
            returns = [float(b / a - 1) for a, b in zip(values, values[1:])]
            if family == "F3":
                mean = math.fsum(returns) / window
                scores[symbol] = -math.sqrt(
                    math.fsum((r - mean) ** 2 for r in returns) / (window - 1)
                )
            else:
                scores[symbol] = -math.sqrt(
                    math.fsum(min(r, 0) ** 2 for r in returns) / window
                )
        if not math.isfinite(scores[symbol]):
            raise ValueError("signal.nonfinite_score")
    if len(set(scores.values())) < 2:
        raise ValueError("signal.constant_recipe_date")
    return scores


class DecayHistory:
    """One meta book, contiguous closes; never a solo or a substitute D2."""

    def __init__(
        self, *, book_id, global_start, policy, execution_binding, execution_role
    ):
        self.binding = validate_execution_binding(execution_binding)
        if execution_role != "current_META_POLICY_execution_layer":
            raise ValueError("decay.solo_does_not_inherit_meta_lifecycle")
        if global_start not in policy.calendar:
            raise ValueError("decay.calendar_start_required")
        self.book_id, self.start, self.policy = book_id, global_start, policy
        self._lock = RLock()
        self._rows = []
        self._receipts = []
        self._states = {
            k: dict(
                state="active",
                half_at=None,
                previous_nonpositive_check=None,
                additions_frozen=False,
            )
            for k in policy.document["variance_layers"]["family_definitions"][
                "candidate_members"
            ]
        }

    @property
    def rows(self):
        with self._lock:
            return deepcopy(self._rows)

    @property
    def states(self):
        with self._lock:
            return deepcopy(self._states)

    def observe(self, risk_book, values, *, expected_snapshot_sha256):
        with self._lock:
            return self._observe(risk_book, deepcopy(values), expected_snapshot_sha256)

    def _observe(self, risk_book, values, expected_snapshot_sha256):
        validate_execution_binding(self.binding)
        if type(risk_book) is not RiskBook:
            raise ValueError("decay.shared_D2_required")
        snapshot = risk_book.snapshot()
        if not snapshot["complete"]:
            raise ValueError("decay.D2_close_unknown")
        date = snapshot["close_session"]
        if (
            snapshot["snapshot_sha256"] != expected_snapshot_sha256
            or snapshot["book_id"] != self.book_id
            or snapshot["execution_binding_sha256"] != digest(self.binding)
            or snapshot["scope"]["execution_role"]
            != "current_META_POLICY_execution_layer"
            or snapshot["state"]["_risk_clock"]["global_start"] != self.start
            or set(values) != set(self._states)
        ):
            raise ValueError("decay.book_or_close_continuity_mismatch")
        parsed = {k: None if v is None else amount(v) for k, v in values.items()}
        declaration = digest(values)
        if self._rows and self._rows[-1]["date"] == date:
            if (
                self._rows[-1]["input_sha256"] != declaration
                or self._rows[-1]["snapshot_sha256"] != expected_snapshot_sha256
            ):
                raise ValueError("decay.conflicting_close_replay")
            return deepcopy(self._receipts[-1])
        expected_index = self.policy.calendar.index(self.start) + len(self._rows)
        if (
            expected_index >= len(self.policy.calendar)
            or date != self.policy.calendar[expected_index]
        ):
            raise ValueError("decay.book_or_close_continuity_mismatch")
        values = parsed
        position = len(self._rows)
        # Mutate only after complete structural/value validation. Preserve every
        # unknown observation; it cannot be skipped into consecutive evidence.
        self._rows.append(
            dict(
                date=date,
                values=values,
                input_sha256=declaration,
                snapshot_sha256=expected_snapshot_sha256,
            )
        )
        checks = {}
        for k, state in self._states.items():
            recent = [r["values"][k] for r in self._rows[-20:]]
            missing = any(v is None for v in recent) or not snapshot["complete"]
            state["additions_frozen"] = missing or state["state"] != "active"
            if position % 5:
                continue
            valid = position >= 20 and len(recent) == 20 and not missing
            mean = sum(recent, Fraction(0)) / 20 if valid else None
            previous = state["previous_nonpositive_check"]
            if state["state"] == "active":
                if mean is not None and mean <= 0 and previous == position - 5:
                    state.update(state="half", half_at=position, additions_frozen=True)
                state["previous_nonpositive_check"] = (
                    position if mean is not None and mean <= 0 else None
                )
            elif (
                state["state"] == "half"
                and position - state["half_at"] >= 21
                and mean is not None
                and mean <= 0
            ):
                state.update(state="retired", additions_frozen=True)
            checks[k] = dict(
                valid=valid,
                mean_nonpositive=None if mean is None else mean <= 0,
                reason="unknown" if missing else "insufficient" if not valid else None,
            )
        receipt = dict(
            book_id=self.book_id,
            close_session=date,
            global_position=position,
            execution_closure_sha256=self.binding["adoption_sha256"],
            clock_ruling_sha256=snapshot["ruling_sha256"],
            states=deepcopy(self._states),
            checks=checks,
            complete=snapshot["complete"]
            and all(v is not None for v in values.values()),
            runtime_consumable=False,
            certifiable=False,
        )
        self._receipts.append(deepcopy(receipt))
        return receipt

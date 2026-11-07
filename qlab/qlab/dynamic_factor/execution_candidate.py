"""C13 candidate dispatch to the sole D1/D2 and original G/K arithmetic.

All expected hashes are host bindings after C09 source acceptance. These
capabilities do not certify source/permission, run a strategy, or open runtime.
No quantity, fee, risk, pool selection or decay algorithm is defined here.
"""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import json
from threading import RLock

from .contract import canonical, code_sha, digest, is_sha, sha256
from .execution_amounts import ExactOrderCosts
from .execution_closure import validate_execution_binding
from .execution_numbers import amount, decimal_text
from .execution_risk import RiskBook
from .execution_signals import DecayHistory
from .input_scope import reject_b2_inputs
from .reference_validation import utc_instant


_ISSUER = object()
ROLES = {"candidate_solo_probe", "current_META_POLICY_execution_layer"}


class SelectionLayer:
    """Immutable original S0/S1/S2 and explicit as-of availability; no reselect."""

    def __init__(self, issuer, document):
        if issuer is not _ISSUER:
            raise ValueError("candidate.original_selection_layer_required")
        self._bytes = canonical(document)

    def document(self):
        return json.loads(self._bytes)

    @property
    def sha256(self):
        return sha256(self._bytes)


def selection_from_stages(
    ledger,
    *,
    run_id,
    fold_id,
    expected_stage_sha256,
    availability,
    expected_availability_sha256,
    policy,
):
    """Read original selection records, never begin/finish/charge an attempt."""
    key = f"v02/{run_id}/{fold_id}"
    stages = {k: ledger.recorded(key + "/" + k) for k in ("S0", "S1", "S2")}
    if (
        set(expected_stage_sha256) != set(stages)
        or any(
            stages[k] is None or digest(stages[k]) != expected_stage_sha256[k]
            for k in stages
        )
        or type(availability) is not dict
        or set(availability)
        != {"source_sha256", "visible_at", "authorized_at", "fold_id"}
        or not is_sha(availability["source_sha256"])
        or digest(availability) != expected_availability_sha256
        or availability["fold_id"] != fold_id
    ):
        raise ValueError("candidate.original_stage_or_availability_binding_required")
    utc_instant(availability["visible_at"])
    utc_instant(availability["authorized_at"])
    context = stages["S0"]["context"]
    calibration = stages["S1"]["calibration"]
    pool = stages["S2"]["pool"]
    ids = policy.document["variance_layers"]["family_definitions"]["candidate_members"]
    if (
        context["fold_id"] != fold_id
        or type(pool) is not list
        or len(pool) != len(set(pool))
        or len(pool) > 4
        or not set(pool) <= set(ids)
        or type(calibration) is not dict
        or calibration.get("context_sha256") != digest(context)
        or calibration.get("conventions_sha256") != policy.raw_sha256
        or calibration.get("calibration_sha256")
        != digest({k: v for k, v in calibration.items() if k != "calibration_sha256"})
    ):
        raise ValueError("candidate.original_pool_or_calibration_required")
    return SelectionLayer(
        _ISSUER,
        dict(
            run_id=run_id,
            fold_id=fold_id,
            context=context,
            calibration=calibration,
            pool=pool,
            original_stage_sha256=deepcopy(expected_stage_sha256),
            availability=deepcopy(availability),
            conventions_sha256=policy.raw_sha256,
        ),
    )


class CandidateOpen:
    """One C09-host-bound next-open object; no signal or M/P/return fields."""

    def __init__(self, opened, *, expected_sha256):
        reject_b2_inputs(opened, "orders")
        if type(opened) is not dict or any(
            k in opened
            for k in ("M", "P", "returns", "locked_signal", "risk_signal", "selection")
        ):
            raise ValueError("candidate.open_cannot_replace_signal_or_plan")
        raw = json.dumps(
            opened, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if not is_sha(expected_sha256) or sha256(raw) != expected_sha256:
            raise ValueError("candidate.open_binding_required")
        self._bytes = raw

    def document(self):
        return json.loads(self._bytes)


class CandidateIntent:
    """Seal the s-close signal; T may only supply execution/feasibility inputs."""

    def __init__(
        self,
        template,
        *,
        risk_book,
        risk_signal,
        execution_binding,
        expected_template_sha256,
        expected_snapshot_sha256,
        expected_signal_sha256,
        selection=None,
        decay=None,
    ):
        reject_b2_inputs(template, "orders")
        self.binding = validate_execution_binding(execution_binding)
        if type(risk_book) is not RiskBook:
            raise ValueError("candidate.shared_D2_required")
        self.policy = risk_book._policy
        self._book = risk_book
        self._snapshot = risk_book.snapshot()
        scope = self._snapshot["scope"]
        self._role = scope["execution_role"]
        if self._role not in ROLES or not self._snapshot["complete"]:
            raise ValueError("candidate.complete_role_bound_D2_required")
        required = {
            "schema",
            "fixture_id",
            "economic_semantics_sha256",
            "close_state",
            "eligibility",
            "fee_parameters",
            "locked_signal",
            "source_component_sha256",
            "source_declaration",
        }
        if (
            type(template) is not dict
            or set(template) != required
            or digest(template) != expected_template_sha256
            or not is_sha(expected_template_sha256)
            or self._snapshot["snapshot_sha256"] != expected_snapshot_sha256
            or digest(self.binding) != self._snapshot["execution_binding_sha256"]
            or digest(risk_signal) != expected_signal_sha256
        ):
            raise ValueError("candidate.preclose_template_or_snapshot_binding_required")
        if (
            template["locked_signal"]["signal_session"]
            != self._snapshot["close_session"]
        ):
            raise ValueError("candidate.adjacent_preclose_required")
        self._template = deepcopy(template)
        self._signal = deepcopy(risk_signal)
        self._selection = selection
        self._decay = decay
        if self._role == "candidate_solo_probe":
            if (
                selection is not None
                or decay is not None
                or risk_signal["origin_context"] is not None
            ):
                raise ValueError("candidate.solo_must_not_read_meta_selection")
        else:
            if type(selection) is not SelectionLayer or type(decay) is not DecayHistory:
                raise ValueError(
                    "candidate.original_selection_and_owned_decay_required"
                )
            layer = selection.document()
            date = self._snapshot["close_session"]
            if (
                layer["fold_id"] != scope["fold_id"]
                or layer["conventions_sha256"] != self.policy.raw_sha256
                or any(
                    utc_instant(layer["availability"][k])
                    > utc_instant(self._snapshot["state"]["asof"])
                    for k in ("visible_at", "authorized_at")
                )
                or not decay._receipts
                or not decay._receipts[-1]["complete"]
                or decay._rows[-1]["snapshot_sha256"] != expected_snapshot_sha256
                or decay._receipts[-1]["book_id"] != self._snapshot["book_id"]
                or decay._receipts[-1]["close_session"] != date
                or digest(decay.binding) != digest(self.binding)
            ):
                raise ValueError(
                    "candidate.current_fold_visibility_or_decay_required_no_old_pool"
                )
            states = decay.states
            pool = layer["pool"]
            if any(states[k]["state"] == "retired" for k in pool):
                raise ValueError("candidate.original_pool_contains_retired_member")
            coefficients = {k: 0.5 if states[k]["state"] == "half" else 1 for k in pool}
            permissions = {
                k: k in pool
                and states[k]["state"] == "active"
                and not states[k]["additions_frozen"]
                for k in states
            }
            expected_context = dict(
                source_sha256=selection.sha256,
                signal_session=date,
                permissions=permissions,
                fold_id=scope["fold_id"],
                execution_closure_sha256=self.binding["adoption_sha256"],
            )
            if (
                risk_signal["origin_context"] != expected_context
                or template["locked_signal"].get("factor_states") != coefficients
                or set(template["locked_signal"].get("factor_scores", {})) != set(pool)
            ):
                raise ValueError("candidate.original_pool_or_inherited_decay_mismatch")
        required_M = risk_book.required_m(
            self._signal,
            expected_book_id=self._snapshot["book_id"],
            expected_close_session=self._snapshot["close_session"],
            expected_snapshot_sha256=expected_snapshot_sha256,
            expected_original_state_sha256=self._snapshot["original_state_sha256"],
            expected_signal_sha256=expected_signal_sha256,
        )
        if not required_M["complete"]:
            raise ValueError(
                "candidate.required_M_unavailable:" + ";".join(required_M["reasons"])
            )
        self._required = required_M
        self._result = None
        self._opened_sha = None
        self._failure = None
        self._lock = RLock()
        from .execution_projection import project

        self._identity = dict(
            book_id=self._snapshot["book_id"],
            snapshot_sha256=expected_snapshot_sha256,
            original_state_sha256=self._snapshot["original_state_sha256"],
            template_sha256=expected_template_sha256,
            signal_sha256=expected_signal_sha256,
            selection_layer_sha256=None if selection is None else selection.sha256,
            execution_role=self._role,
            execution_closure_sha256=self.binding["adoption_sha256"],
            clock_ruling_sha256=self._snapshot["ruling_sha256"],
            planner_source_sha256=code_sha(project),
            risk_source_sha256=code_sha(RiskBook),
        )

    def identity(self):
        self._book._check_release()
        return deepcopy(self._identity)

    def _gain(self, plan, inputs):
        # D1.7: solo keeps its fixed no-G/K override; meta uses the ORIGINAL
        # forecast and NAV increment functions after sealing exactly one P.
        from .execution import forecast_stock, nav_increment
        from .isolation import rank_scores

        state = self._snapshot["state"]
        original = state["inventory"]
        prices = {s: amount(v) for s, v in inputs["execution_open"]["raw_open"].items()}
        costs = ExactOrderCosts(
            self.policy, self._signal["execution_session"], "research_restored"
        )
        quotes = []
        for holdings in (plan["M"], plan["P"]):
            orders = {s: holdings[s] - original[s] for s in original}
            quotes.append(
                costs.quote_exact(
                    orders,
                    {
                        s: Decimal(decimal_text(abs(q) * prices[s]))
                        if q
                        else Decimal(0)
                        for s, q in orders.items()
                    },
                    guard=self._book._guard,
                    execution_binding=self.binding,
                    release_context=self._book._release_context,
                    expected_release_identity_bytes=self._book._release_identity_bytes,
                )
            )
        if self._role == "candidate_solo_probe":
            return dict(
                selected_plan="P",
                allowed=True,
                reason="candidate.fixed_solo_no_voluntary_GK",
                C2_M=decimal_text(quotes[0]),
                C2_P=decimal_text(quotes[1]),
                denominator_E=None,
            )
        if plan["P"] == plan["M"]:
            return dict(
                selected_plan="M",
                allowed=False,
                reason="candidate.no_optional_adjustment",
                C2_M=decimal_text(quotes[0]),
                C2_P=decimal_text(quotes[1]),
                denominator_E=None,
            )
        layer = self._selection.document()
        signal = inputs["locked_signal"]
        request = dict(
            calibration=layer["calibration"],
            context=layer["context"],
            pool=layer["pool"],
            factor_states=signal["factor_states"],
            ranks={},
        )
        ranks = {
            k: rank_scores(v, inputs["eligibility"]["E_t"])
            for k, v in signal["factor_scores"].items()
        }
        # D1 emits a complete inventory grid. G/K needs prices only for its
        # actual positions, not for the grid's unheld names outside E(t).
        active = {s for s in plan["M"] if plan["M"][s] or plan["P"][s]}
        stocks = active - {"QQQ"}
        request["ranks"] = {
            s: {k: r[s] for k, r in ranks.items() if s in r} for s in stocks
        }
        rights = (
            self._book._cash_proof.check(
                state,
                self._book._guard,
                release_context=self._book._release_context,
                expected_release_identity_bytes=self._book._release_identity_bytes,
                policy=self.policy,
            )
            if state["receivables"]
            else Fraction(0)
        )
        E = (
            amount(state["cash"])
            + sum((q * prices[s] for s, q in original.items() if q), Fraction(0))
            + rights
        )

        def numeric(value):
            number = float(value)
            if amount(number) != value:
                raise ValueError(
                    "candidate.original_ratio_interface_amount_unavailable"
                )
            return number

        try:
            # The shared arithmetic multiplies these by P-M. A zero delta
            # contributes exactly zero; it does not request an unavailable
            # forecast for a quarantined/zero-position name outside E(t).
            alpha = {
                s: 0.0
                if plan["M"][s] == plan["P"][s]
                else forecast_stock(s, request, self.policy)
                for s in sorted(stocks)
            }
            result = nav_increment(
                {s: plan["M"][s] for s in active},
                {s: plan["P"][s] for s in active},
                {s: numeric(v) for s, v in prices.items()},
                alpha,
                request["calibration"]["mu_Q"],
                numeric(E),
                numeric(quotes[0]),
                numeric(quotes[1]),
                self.policy.document["gain_model"]["calibration"]["mu_cash"],
            )
            return dict(
                result,
                selected_plan="P" if result["allowed"] else "M",
                C2_M=decimal_text(quotes[0]),
                C2_P=decimal_text(quotes[1]),
                denominator_E=decimal_text(E),
            )
        except (ValueError, KeyError, TypeError) as exc:
            return dict(
                selected_plan="M",
                allowed=False,
                reason=str(exc)
                if isinstance(exc, ValueError)
                else "gain.forecast_missing",
                C2_M=decimal_text(quotes[0]),
                C2_P=decimal_text(quotes[1]),
                denominator_E=decimal_text(E),
            )

    def next_open(self, opened):
        from .execution_projection import project

        if type(opened) is not CandidateOpen:
            raise ValueError("candidate.host_bound_open_required_no_caller_plans")
        with self._lock:
            self._book._check_release()
            opened_sha = sha256(opened._bytes)
            if self._opened_sha is not None and self._opened_sha != opened_sha:
                raise ValueError("candidate.one_open_binding_no_second_P")
            self._opened_sha = opened_sha
            if self._failure:
                raise ValueError(self._failure)
            if self._result is not None:
                return deepcopy(self._result)
            try:
                inputs = dict(
                    deepcopy(self._template), execution_open=opened.document()
                )
                plan = project(
                    inputs,
                    risk_book=self._book,
                    risk_signal=self._signal,
                    execution_binding=self.binding,
                    expected_input_sha256=digest(inputs),
                    expected_snapshot_sha256=self._snapshot["snapshot_sha256"],
                    expected_signal_sha256=digest(self._signal),
                )
                gain = self._gain(plan, inputs)
                selection = dict(
                    book_id=self._snapshot["book_id"],
                    close_session=self._snapshot["close_session"],
                    execution_session=self._signal["execution_session"],
                    input_sha256=digest(inputs),
                    snapshot_sha256=self._snapshot["snapshot_sha256"],
                    selected_plan=gain["selected_plan"],
                    execution_role=self._role,
                    decision_source_sha256=digest(
                        dict(identity=self._identity, plan=plan, gain=gain)
                    ),
                )
                self._inputs = inputs
                self._result = dict(
                    schema="EVO884.CandidateExecution/v1",
                    identity=self.identity(),
                    projection=plan,
                    gain=gain,
                    selection=selection,
                    selected_holdings=deepcopy(plan[gain["selected_plan"]]),
                    complete=True,
                    seal_status="seal_pending",
                    seal_reason="C13 source migration requires independent review and reseal",
                    runtime_consumable=False,
                    execution_verified=False,
                    certifiable=False,
                )
                self._result = RiskBook.release_payload(
                    self._result, self._book._release_identity_bytes
                )
                return deepcopy(self._result)
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                self._failure = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "candidate.required_projection_input_unknown"
                )
                raise ValueError(self._failure) from exc

    def bind_account(self, account, history):
        """Pass selected full holdings to C04, with the SAME C06 DAY intent."""
        from .execution_accounting import ExecutionAccount
        from .execution_risk_history import RiskHistory

        with self._lock:
            if (
                type(account) is not ExecutionAccount
                or type(history) is not RiskHistory
                or account._book is not self._book
                or history._book is not self._book
                or self._result is None
            ):
                raise ValueError("candidate.same_owned_account_and_D2_required")
            history.prepare_open(
                self._signal,
                expected_signal_sha256=digest(self._signal),
                expected_snapshot_sha256=self._snapshot["snapshot_sha256"],
            )
            return account.lock_projection(
                self._inputs,
                risk_signal=self._signal,
                expected_input_sha256=digest(self._inputs),
                expected_snapshot_sha256=self._snapshot["snapshot_sha256"],
                expected_signal_sha256=digest(self._signal),
                selected_plan=self._result["gain"]["selected_plan"],
                selection_receipt=self._result["selection"],
                expected_selection_sha256=digest(self._result["selection"]),
            )


class ExecutionObservation:
    """Only owned C04/C07 strategy returns may enter a v3 train callback."""

    def __init__(self, issuer, payload):
        if issuer is not _ISSUER:
            raise ValueError("candidate.owned_account_returns_required")
        self._bytes = canonical(payload)

    def document(self):
        return json.loads(self._bytes)

    @classmethod
    def from_account(
        cls,
        series,
        benchmark,
        *,
        expected_benchmark_sha256,
        scores,
        expected_scores_sha256,
        selection=None,
    ):
        from .execution_returns import TrainingReturns

        if (
            type(series) is not TrainingReturns
            or digest(scores) != expected_scores_sha256
        ):
            raise ValueError("candidate.owned_account_and_original_scores_required")
        account = series._account
        account._check_release()
        scope = account._scope
        if scope["execution_role"] not in ROLES:
            raise ValueError("candidate.reference_cannot_replace_candidate_attempt")
        if scope["execution_role"] == "candidate_solo_probe":
            if selection is not None:
                raise ValueError("candidate.solo_must_not_read_meta_selection")
        elif (
            type(selection) is not SelectionLayer
            or selection.document()["fold_id"] != scope["fold_id"]
        ):
            raise ValueError("candidate.original_selection_layer_required")
        reject_b2_inputs(scores, "features")
        from .noncash_v3 import assert_consumer_symbols

        for date, values in scores.items():
            if date not in series._dates:
                raise ValueError("candidate.scores_outside_original_train")
            assert_consumer_symbols(
                account._guard,
                "score",
                list(values),
                account._policy,
                release_context=account._release_context,
                expected_release_identity_bytes=account._release_identity_bytes,
            )
        result = series.evaluate(
            benchmark, expected_benchmark_sha256=expected_benchmark_sha256
        )
        if not result["complete"]:
            raise ValueError(
                "candidate.complete_owned_return_journal_required:"
                + ";".join(result["reasons"])
            )
        layer = None if selection is None else selection.document()
        return cls(
            _ISSUER,
            dict(
                returns=result["active_daily"],
                scores=deepcopy(scores),
                scope=deepcopy(scope),
                dates=result["dates"],
                execution_returns_sha256=result["returns_sha256"],
                account_sha256=account.snapshot()["account_sha256"],
                execution_closure_sha256=series._binding["adoption_sha256"],
                clock_ruling_sha256=series.plan()["clock_ruling_sha256"],
                pool=None if layer is None else layer["pool"],
                calibration_sha256=None
                if layer is None
                else layer["calibration"]["calibration_sha256"],
                runtime_consumable=False,
                execution_verified=False,
                certifiable=False,
                seal_status="seal_pending",
                seal_reason="C13 source migration requires independent review and reseal",
            ),
        )


def close_execution_day(
    account,
    history,
    evidence,
    *,
    expected_evidence_sha256,
    decay=None,
    monitoring=None,
    expected_monitoring_sha256=None,
    incoming_selection=None,
):
    """N5's common close sequence over existing C04/C06/N4; no runtime permission.

    Source/authorization acceptance of evidence and independent-template returns
    remains C09. This adapter does not manufacture monitoring returns from the
    current meta book or reset any state at a fold boundary.
    """
    from .execution_accounting import ExecutionAccount
    from .execution_risk_history import RiskHistory
    from .execution_signals import DecayHistory

    if (
        type(account) is not ExecutionAccount
        or type(history) is not RiskHistory
        or account._book is not history._book
    ):
        raise ValueError("pipeline.same_owned_account_and_D2_required")
    account._check_release()
    history._book._check_release()
    meta = account._scope["execution_role"] == "current_META_POLICY_execution_layer"
    if meta:
        if (
            type(decay) is not DecayHistory
            or monitoring is None
            or not is_sha(expected_monitoring_sha256)
            or digest(monitoring) != expected_monitoring_sha256
            or decay.book_id != account._book_id
        ):
            raise ValueError("pipeline.independent_template_monitoring_required")
    elif decay is not None or monitoring is not None or incoming_selection is not None:
        raise ValueError("pipeline.solo_must_not_read_meta_lifecycle")
    closed = account.close_session(
        evidence, expected_evidence_sha256=expected_evidence_sha256
    )
    row = closed["receipt"]
    snapshot = history.observe_close(
        row["session"],
        row["accounting"],
        row["fills"],
        expected_accounting_sha256=digest(row["accounting"]),
        expected_fills_sha256=digest(row["fills"]),
        cash_proof=closed["cash_proof"],
    )
    if not snapshot["complete"]:
        raise ValueError("pipeline.R2_close_risk_unknown")
    trace = ["ACCOUNTING_AND_NAV", "C06_RISK_ONCE"]
    decay_receipt = None
    if meta:
        decay_receipt = decay.observe(
            history._book,
            monitoring,
            expected_snapshot_sha256=snapshot["snapshot_sha256"],
        )
        trace.append("DECAY")
    policy = account._policy
    folds = policy.fold_manifest()["folds"]
    current = next(f for f in folds if f["fold_id"] == snapshot["scope"]["fold_id"])
    ready = True
    reason = None
    if (
        snapshot["scope"]["kind"] == "stitched_test"
        and row["session"] == current["test_end"]
        and current != folds[-1]
    ):
        next_fold = folds[folds.index(current) + 1]["fold_id"]
        if not meta:
            # Fixed solo recipes do not borrow the actual meta pool at a fold
            # boundary; C06 carries the same owned risk state into the fold.
            snapshot = history.advance_fold(
                next_fold, expected_snapshot_sha256=snapshot["snapshot_sha256"]
            )
            trace.append("FOLD")
        elif type(incoming_selection) is not SelectionLayer:
            ready, reason = False, "pipeline.new_fold_selection_missing_no_old_pool"
        else:
            layer = incoming_selection.document()
            if layer["fold_id"] != next_fold or any(
                utc_instant(layer["availability"][k])
                > utc_instant(row["accounting"]["asof"])
                for k in ("visible_at", "authorized_at")
            ):
                raise ValueError("pipeline.new_fold_selection_not_visible_no_old_pool")
            snapshot = history.advance_fold(
                next_fold, expected_snapshot_sha256=snapshot["snapshot_sha256"]
            )
            trace.append("FOLD")
    elif incoming_selection is not None:
        raise ValueError(
            "pipeline.selection_replacement_only_at_original_fold_boundary"
        )
    account.bind_next_risk(
        history._book, expected_snapshot_sha256=snapshot["snapshot_sha256"]
    )
    return dict(
        accounting=closed["receipt"],
        risk=snapshot,
        decay=decay_receipt,
        trace=trace,
        ready_to_lock=ready,
        reason=reason,
        seal_status="seal_pending",
        runtime_consumable=False,
        certifiable=False,
    )

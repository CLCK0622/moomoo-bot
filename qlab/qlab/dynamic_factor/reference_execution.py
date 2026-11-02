"""C10 reference orchestration over the sole C03/C04/C05/C06/C07 engines.

This named training diagnostic is deliberately separate from runtime reception.
Inputs are facts/locked signals, never strategy returns, M, P or a current
candidate/meta result. Source hashes bind inputs; they do not authenticate them.
"""

from copy import deepcopy

from .contract import digest, is_sha
from .execution_accounting import ExecutionAccount, MODEL
from .execution_candidate import close_execution_day
from .execution_returns import TrainingReturns
from .execution_risk_history import RiskHistory
from .execution_startup import StartupBook
from .reference_definition_v301 import member_definition
from .reference_profile_v301 import solo_profile
from .execution_receipts.reference_result import issue_observation


class ReferenceExecution:
    """One independently owned fixed reference book; no evaluator callback.

    The existing cores enforce quantity, price, B, fees, dates, origin, unknown
    state and 1260 closes. This class only orders their calls and records the
    actual DAG. The ideal-fill method cannot produce accepted actual fills.
    """

    def __init__(
        self,
        startup,
        history,
        *,
        run_id,
        expected_startup_sha256,
        expected_snapshot_sha256,
    ):
        if type(startup) is not StartupBook or type(history) is not RiskHistory:
            raise ValueError("reference.owned_startup_and_history_required")
        start, snap = startup.snapshot(), history.snapshot()
        identity, scope = start["identity"], snap["scope"]
        definition = member_definition(
            scope["member_id"], execution_role=scope["execution_role"]
        )
        if (
            type(run_id) is not str
            or not run_id
            or digest(start) != expected_startup_sha256
            or snap["snapshot_sha256"] != expected_snapshot_sha256
            or start["book_id"] != snap["book_id"]
            or scope["kind"] != "independent_training"
            or any(
                identity[k] != scope[k] for k in ("member_id", "fold_id", "attempt_id")
            )
            or start["position"] != 0
            or start["pending_intent"] is not None
            or digest(identity["execution_binding"]) != snap["execution_binding_sha256"]
        ):
            raise ValueError("reference.separate_preexecution_book_binding_required")
        self.startup, self.history = startup, history
        self.profile = solo_profile(definition)
        self.binding = deepcopy(identity["execution_binding"])
        self.run_id = run_id
        self._initial = dict(
            startup=dict(
                member_id=identity["member_id"],
                fold_id=identity["fold_id"],
                attempt_id=identity["attempt_id"],
                initial_state=deepcopy(start["genesis"]),
                context=deepcopy(startup._context),
                execution_binding=deepcopy(self.binding),
            ),
            history=deepcopy(history._initial),
            run_id=run_id,
        )
        self._program = []
        self.account = ExecutionAccount(
            risk_book=history._book,
            expected_snapshot_sha256=expected_snapshot_sha256,
            execution_binding=self.binding,
            execution_mode="named_training_diagnostic",
        )
        self.series = TrainingReturns(
            self.account,
            expected_account_sha256=self.account.snapshot()["account_sha256"],
            execution_binding=self.binding,
        )
        self._events = []

    def startup_open(
        self, timestamp, raw_open, *, source_sha256, expected_input_sha256
    ):
        facts = dict(
            timestamp=timestamp, raw_open=raw_open, source_sha256=source_sha256
        )
        if not is_sha(source_sha256) or digest(facts) != expected_input_sha256:
            raise ValueError("reference.open_fact_binding_required")
        # C05 owns the three-day quantity and the original numeric interface.
        self.startup.prepare_next_open()
        self.startup.execute_open(timestamp, lambda *_: raw_open)
        ticket = self.account.lock_startup(
            self.startup, expected_source_sha256=digest(self.startup.snapshot())
        )
        self._events.append(dict(operation="C05_STARTUP", input_sha256=digest(facts)))
        self._program.append(
            dict(
                operation="startup_open",
                arguments=dict(
                    timestamp=timestamp,
                    raw_open=raw_open,
                    source_sha256=source_sha256,
                    expected_input_sha256=expected_input_sha256,
                ),
            )
        )
        return ticket

    def lock_projection(
        self, inputs, signal, *, expected_input_sha256, expected_signal_sha256
    ):
        """Fixed solo selects P; C04 calls the sole D1 and C06 supplies M.

        There is no reference copy of quantity/risk arithmetic or G/K gate.
        C04 validates both the original state and the sealed s/T signal.
        """
        snap = self.history.snapshot()
        start = self.startup.snapshot()
        if (
            start["startup_complete"] is not True
            or snap["close_session"] < start["first_regular_signal_close"]
        ):
            raise ValueError("reference.startup_before_regular_projection")
        selection = dict(
            book_id=snap["book_id"],
            close_session=snap["close_session"],
            execution_session=signal["execution_session"],
            input_sha256=expected_input_sha256,
            snapshot_sha256=snap["snapshot_sha256"],
            selected_plan="P",
            execution_role=snap["scope"]["execution_role"],
            decision_source_sha256=self.profile["profile_sha256"],
        )
        if inputs["locked_signal"]["recipe_id"] != snap["scope"]["recipe_id"]:
            raise ValueError("reference.fixed_recipe_required")
        ticket = self.account.lock_projection(
            inputs,
            risk_signal=signal,
            expected_input_sha256=expected_input_sha256,
            expected_snapshot_sha256=snap["snapshot_sha256"],
            expected_signal_sha256=expected_signal_sha256,
            selected_plan="P",
            selection_receipt=selection,
            expected_selection_sha256=digest(selection),
        )
        self._events.append(
            dict(operation="C06_M_C03_P_C04_LOCK", input_sha256=digest(inputs))
        )
        self._program.append(
            dict(
                operation="lock_projection",
                arguments=dict(
                    inputs=deepcopy(inputs),
                    signal=deepcopy(signal),
                    expected_input_sha256=expected_input_sha256,
                    expected_signal_sha256=expected_signal_sha256,
                ),
            )
        )
        return ticket

    def model_open(self, evidence, *, expected_evidence_sha256):
        receipt = self.account.model_open(
            evidence,
            expected_evidence_sha256=expected_evidence_sha256,
            model_name=MODEL,
        )
        self._events.append(
            dict(operation="C04_NAMED_DIAGNOSTIC_FILL", input_sha256=digest(evidence))
        )
        self._program.append(
            dict(
                operation="model_open",
                arguments=dict(
                    evidence=deepcopy(evidence),
                    expected_evidence_sha256=expected_evidence_sha256,
                ),
            )
        )
        return receipt

    def close(self, evidence, *, expected_evidence_sha256, startup_valuation=None):
        if self.history._book.decision_due()["order_intent_due"]:
            ticket = self.account.intent()["ticket"]
            if (
                ticket is None
                or ticket["signal_session"] != self.history.snapshot()["close_session"]
                or ticket["execution_session"] != evidence.get("session")
            ):
                raise ValueError("reference.same_D1_plan_required_for_due_open")
        pending_startup = self.startup.snapshot()["pending_close"]
        # Validate C05's explicitly supplied valuation before mutating C04.
        if pending_startup and (
            type(startup_valuation) is not dict
            or set(startup_valuation) != {"raw_close", "valuation"}
        ):
            raise ValueError("reference.startup_close_valuation_required")
        if not pending_startup and startup_valuation is not None:
            raise ValueError("reference.no_startup_valuation_after_startup")
        out = close_execution_day(
            self.account,
            self.history,
            evidence,
            expected_evidence_sha256=expected_evidence_sha256,
        )
        self._events.append(
            dict(
                operation="C04_CLOSE_C06_ONCE",
                input_sha256=digest(evidence),
                trace=out["trace"],
                account_sha256=self.account.snapshot()["account_sha256"],
                snapshot_sha256=out["risk"]["snapshot_sha256"],
            )
        )
        if pending_startup:
            self.startup.close_session(
                evidence["asof"],
                startup_valuation["raw_close"],
                startup_valuation["valuation"],
            )
        self._program.append(
            dict(
                operation="close",
                arguments=dict(
                    evidence=deepcopy(evidence),
                    expected_evidence_sha256=expected_evidence_sha256,
                    startup_valuation=deepcopy(startup_valuation),
                ),
            )
        )
        return out

    def observe(self, benchmark, *, expected_benchmark_sha256):
        if not self.startup.snapshot()["startup_complete"]:
            raise ValueError("reference.complete_owned_startup_required")
        return issue_observation(
            self,
            benchmark=benchmark,
            expected_benchmark_sha256=expected_benchmark_sha256,
        )


def replay_execution(program, policy):
    """Recompute an owned fact program; no arbitrary callback or result input."""
    if (
        type(program) is not dict
        or set(program)
        != {"schema", "initial", "operations", "benchmark", "benchmark_sha256"}
        or program["schema"] != "EVO884.ReferenceExecutionProgram/v1"
    ):
        raise ValueError("reference.closed_execution_program_required")
    initial = program["initial"]
    if type(initial) is not dict or set(initial) != {"startup", "history", "run_id"}:
        raise ValueError("reference.closed_execution_genesis_required")
    source = StartupBook(**initial["startup"], policy=policy)
    history = RiskHistory(**initial["history"], policy=policy)
    execution = ReferenceExecution(
        source,
        history,
        run_id=initial["run_id"],
        expected_startup_sha256=digest(source.snapshot()),
        expected_snapshot_sha256=history.snapshot()["snapshot_sha256"],
    )
    for event in program["operations"]:
        if type(event) is not dict or set(event) != {"operation", "arguments"}:
            raise ValueError("reference.closed_execution_operation_required")
        operation, arguments = event["operation"], event["arguments"]
        if operation == "startup_open":
            execution.startup_open(**arguments)
        elif operation == "lock_projection":
            execution.lock_projection(**arguments)
        elif operation == "model_open":
            execution.model_open(**arguments)
        elif operation == "close":
            execution.close(**arguments)
        else:
            raise ValueError("reference.execution_operation_not_whitelisted")
    return execution.observe(
        program["benchmark"], expected_benchmark_sha256=program["benchmark_sha256"]
    )

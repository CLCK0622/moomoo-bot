"""Host-owned C07 output capability; serialized claims cannot issue one.

The worker recomputes an exact host-bound fact program with the same engines.
An owned diagnostic is still neither source acceptance nor a formal receipt.
"""

from copy import deepcopy
import json
from weakref import WeakKeyDictionary

from ..contract import canonical, code_sha, digest, sha256
from ..execution_accounting import ExecutionAccount
from ..execution_projection import project
from ..execution_returns import TrainingReturns
from ..execution_risk import RiskBook
from ..reference_profile_v301 import validate_solo_profile


_ISSUER = object()
_OWNED = WeakKeyDictionary()


class ReferenceObservation:
    def __init__(self, issuer):
        if issuer is not _ISSUER:
            raise ValueError("reference.owned_observation_required")


def issue_observation(execution, *, benchmark, expected_benchmark_sha256):
    from ..reference_execution import ReferenceExecution

    if (
        type(execution) is not ReferenceExecution
        or not execution.startup.snapshot()["startup_complete"]
    ):
        raise ValueError("reference.owned_execution_required")
    series, run_id, events = execution.series, execution.run_id, execution._events
    if type(series) is not TrainingReturns:
        raise ValueError("reference.owned_C07_required_no_caller_returns")
    profile = validate_solo_profile(execution.profile)
    account = series._account
    with account._lock:
        guard_sha = digest(execution._initial["history"]["guard"])
        if any(
            digest(guard) != guard_sha
            for guard in (
                account._guard,
                account._book._guard,
                execution.history._guard,
            )
        ):
            raise ValueError("reference.observation_guard_drift")
        snapshot, closes, _, _ = series._journal()
        result = series.evaluate(
            benchmark, expected_benchmark_sha256=expected_benchmark_sha256
        )
        if not result["complete"]:
            raise ValueError(
                "reference.owned_returns_incomplete:" + ";".join(result["reasons"])
            )
        scope = account._scope
        observed_closes = [e for e in events if e["operation"] == "C04_CLOSE_C06_ONCE"]
        if (
            scope["member_id"] != profile["definition"]["member_id"]
            or scope["execution_role"] != profile["definition"]["execution_role"]
            or scope["recipe_id"] != profile["definition"]["recipe_id"]
            or result["retained_account_sha256"] != snapshot["account_sha256"]
            or result["benchmark_sha256"] != expected_benchmark_sha256
            or result["journal_sha256"] != digest(closes)
            or len(observed_closes) != len(closes)
            or any(
                e["input_sha256"] != r["close_evidence_sha256"]
                for e, r in zip(observed_closes, closes)
            )
        ):
            raise ValueError("reference.observation_book_or_DAG_mismatch")
        # The issuer computes C07 itself; no caller strategy-return argument.
        program = dict(
            schema="EVO884.ReferenceExecutionProgram/v1",
            initial=deepcopy(execution._initial),
            operations=deepcopy(execution._program),
            benchmark=deepcopy(benchmark),
            benchmark_sha256=expected_benchmark_sha256,
        )
        document = dict(
            schema="EVO884.ReferenceExecutionObservation/v1",
            run_id=run_id,
            book_id=snapshot["book_id"],
            scope=deepcopy(scope),
            profile_sha256=profile["profile_sha256"],
            account_sha256=snapshot["account_sha256"],
            snapshot_sha256=account._book.snapshot()["snapshot_sha256"],
            execution_closure_sha256=account._binding["adoption_sha256"],
            clock_ruling_sha256=account._initial_snapshot["ruling_sha256"],
            benchmark_sha256=expected_benchmark_sha256,
            shared_guard_sha256=guard_sha,
            eligibility_by_close={
                event["arguments"]["inputs"]["close_state"][
                    "signal_close_session"
                ]: digest(event["arguments"]["inputs"]["eligibility"])
                for event in execution._program
                if event["operation"] == "lock_projection"
            },
            program_sha256=digest(program),
            dates=deepcopy(result["dates"]),
            returns=deepcopy(result["active_daily"]),
            return_receipt=deepcopy(result),
            events=deepcopy(events),
            DAG=dict(
                edges=[
                    "C05 -> C04",
                    "C06 -> C03 -> C04",
                    "C04 -> C06",
                    "C04 -> C07 -> REFERENCE_RESULT_WORKER",
                ],
                sources=dict(
                    orchestrator=code_sha(ReferenceExecution),
                    planner=code_sha(project),
                    risk=code_sha(RiskBook),
                    accounting=code_sha(ExecutionAccount),
                    returns=code_sha(TrainingReturns),
                ),
                execution_location="owned_host_and_isolated_replay",
                worker_role="reference_diagnostic_execution",
            ),
            source_acceptance="not_checked",
            formal_N=None,
            complete=True,
            execution_verified=False,
            seal_status="seal_pending",
            runtime_consumable=False,
            certifiable=False,
        )
        identity = account._check_release()
        if identity is not None:
            document.update(
                schema="EVO884.ReferenceExecutionObservation/v1-BR1",
                release_context_binding=json.loads(identity),
            )
        cap = ReferenceObservation(_ISSUER)
        _OWNED[cap] = (series, canonical(document), canonical(program))
        return cap


def read_observation(observation):
    if type(observation) is not ReferenceObservation or observation not in _OWNED:
        raise ValueError("reference.owned_observation_required_no_result_input")
    series, raw, _ = _OWNED[observation]
    document = json.loads(raw)
    with series._account._lock:
        if (
            digest(series._account._guard) != document["shared_guard_sha256"]
            or digest(series._account._book._guard) != document["shared_guard_sha256"]
        ):
            raise ValueError("reference.observation_guard_drift")
        if series._account.snapshot()["account_sha256"] != document["account_sha256"]:
            raise ValueError("reference.observation_account_drift")
        series._journal()
    return document, sha256(raw)


def read_program(observation):
    read_observation(observation)
    raw = _OWNED[observation][2]
    return json.loads(raw), sha256(raw)


def read_release(observation):
    document, _ = read_observation(observation)
    account = _OWNED[observation][0]._account
    identity = account._check_release()
    if identity is not None and document.get("release_context_binding") != json.loads(
        identity
    ):
        raise ValueError("B.release_context_persistent_identity_mismatch")
    return account._release_context, identity


def check_transport(document, expected_sha256, *, expected_release_identity_bytes=None):
    """Only the host-owned exact serialized result may cross this entry."""
    if sha256(canonical(document)) != expected_sha256:
        raise ValueError("reference.worker_observation_binding_mismatch")
    formal = expected_release_identity_bytes is not None
    if formal:
        from ..execution_cash import CashProof

        binding = CashProof.binding_value(expected_release_identity_bytes)
        if document.get("release_context_binding") != binding:
            raise ValueError("B.release_context_persistent_identity_mismatch")
    elif "release_context_binding" in document:
        raise ValueError("B.release_context_scope_mismatch")
    if (
        document.get("schema")
        != "EVO884.ReferenceExecutionObservation/v1" + ("-BR1" if formal else "")
        or document.get("complete") is not True
        or document.get("seal_status") != "seal_pending"
        or document.get("execution_verified") is not False
        or document.get("runtime_consumable") is not False
        or document.get("certifiable") is not False
        or document.get("source_acceptance") != "not_checked"
        or document.get("formal_N") is not None
        or len(document["returns"]) != len(document["dates"])
        or len(document["returns"]) != 1260
        or document["returns"] != document["return_receipt"]["active_daily"]
    ):
        raise ValueError("reference.diagnostic_result_schema_invalid")
    return document

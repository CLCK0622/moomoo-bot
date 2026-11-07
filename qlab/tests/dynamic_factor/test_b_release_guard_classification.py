"""Real bridge crossover refusals using B01's explicitly private host fixture.

No checker substitute, actual A, source permission or formal positive receipt.
"""

from copy import deepcopy
from decimal import Decimal
import json
import sys

import pytest

from qlab.dynamic_factor import b_release_context as b
from qlab.dynamic_factor.contract import canonical, digest, sha256
from qlab.dynamic_factor.execution_accounting import ExecutionAccount
from qlab.dynamic_factor.execution_amounts import ExactOrderCosts
from qlab.dynamic_factor.execution_candidate import CandidateIntent, CandidateOpen
from qlab.dynamic_factor.execution_cash import (
    CashProof,
    check_cash_state,
    dividend_entitlement,
    issue_cash_proof,
)
from qlab.dynamic_factor.execution_projection import project
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from qlab.dynamic_factor.execution_signals import fixed_scores
from projection_test_helpers import case
from test_b01_release_context import private_host_source as private_host_source, request
from test_execution_accounting import account
from test_execution_candidate import intent_case
from test_execution_risk_history import history


@pytest.fixture
def private_bridge_context(private_host_source):
    _, policy = private_host_source
    context = b.receive_release_context(policy=policy)
    raw = b.check_release_context(context, policy=policy, request=request(context))
    return context, raw


POINTS = [
    "cash_bridge",
    "risk_bridge",
    "cash_issue",
    "cash_check",
    "cash_state",
    "dividend",
    "exact_costs",
    "fixed_scores",
    "risk_constructor",
    "risk_snapshot",
    "history_constructor",
    "history_snapshot",
    "history_export",
    "history_restore",
    "account_constructor",
    "account_snapshot",
    "projection",
    "candidate_constructor",
    "candidate_cached",
]


def entry(point, context, expected, formal, binding):
    inputs, args, signal = case()
    policy = args["policy"]
    guard = deepcopy(args["guard"])
    if formal:
        guard["schema"] = "EVO883.BRuntimeGuard/v1"
    kwargs = dict(release_context=context, expected_release_identity_bytes=expected)
    watched = [args["state"], guard]

    def own(obj):
        obj._guard = deepcopy(guard)
        obj._release_context = context
        obj._release_identity_bytes = expected
        watched.append(obj._state)
        return obj

    if point in {"cash_bridge", "risk_bridge"}:
        cls = CashProof if point == "cash_bridge" else RiskBook

        def call():
            return cls.release_guard(guard, policy, **kwargs)
    elif point == "cash_issue":

        def call():
            return issue_cash_proof(
                args["state"],
                book_id=args["book_id"],
                guard=guard,
                ledger_sha256=digest("PRIVATE_TEST_ONLY"),
                policy=policy,
                **kwargs,
            )
    elif point == "cash_check":
        args["state"]["asof"] = args["close_session"] + "T20:00:00Z"
        proof = issue_cash_proof(
            args["state"],
            book_id=args["book_id"],
            guard=args["guard"],
            ledger_sha256=digest("PRIVATE_TEST_ONLY"),
            policy=policy,
        )
        # Reach the existing identity gate with matching private negative data.
        # This cannot create an accepted formal proof: context is absent.
        if formal:
            object.__setattr__(proof, "_guard_sha", digest(guard))

        def call():
            return proof.check(args["state"], guard, policy=policy, **kwargs)
    elif point == "cash_state":

        def call():
            return check_cash_state(args["state"], guard, None, policy=policy, **kwargs)
    elif point == "dividend":
        event = dict(
            event_id="PRIVATE_TEST_ONLY_DIV",
            book_id=args["book_id"],
            kind="cash_dividend",
            symbol="COP",
            ex_date=signal["execution_session"],
            ex_date_status="verified",
            exact_amount_status="verified_exact",
            cash_basis="integer_pre_tax_cash",
            declared_cash_amount="1",
            pay_date=signal["execution_session"],
            entitled_integer_shares=0,
            source_sha256=digest("PRIVATE_TEST_ONLY"),
        )
        watched.append(event)

        def call():
            return dividend_entitlement(
                event,
                book_id=args["book_id"],
                previous_inventory=args["state"]["inventory"],
                session=signal["execution_session"],
                expected_event_sha256=digest(event),
                guard=guard,
                policy=policy,
                **kwargs,
            )
    elif point == "exact_costs":
        costs = ExactOrderCosts(
            policy, signal["execution_session"], "research_restored"
        )

        def call():
            return costs.quote_exact(
                {"QQQ": 1},
                {"QQQ": Decimal("100")},
                guard=guard,
                execution_binding=args["scope"]["execution_binding"],
                **kwargs,
            )
    elif point == "fixed_scores":
        values = {"AAPL": ["100"] * 20 + ["101"], "COST": ["100"] * 20 + ["102"]}
        watched.append(values)

        def call():
            return fixed_scores(
                "F1-L020",
                values,
                eligible=list(values),
                guard=guard,
                policy=policy,
                execution_binding=args["scope"]["execution_binding"],
                expected_histories_sha256=digest(values),
                **kwargs,
            )
    elif point == "risk_constructor":

        def call():
            return RiskBook(**dict(args, guard=guard), **kwargs).snapshot()
    elif point == "risk_snapshot":
        book = own(RiskBook(**args))
        call = book.snapshot
    elif point.startswith("history_"):
        book, hargs = history()
        if point == "history_constructor":

            def call():
                return RiskHistory(**dict(hargs, guard=guard), **kwargs)
        elif point == "history_restore":
            payload = json.loads(book.export_bytes())
            if formal:
                payload = RiskBook.release_payload(payload, binding)
                payload["initial"]["guard"] = deepcopy(guard)
            raw = canonical(payload)
            # Formal restore retains the host/disk gates before missing context.
            restore_kwargs = (
                dict(kwargs, expected_release_identity_bytes=binding)
                if formal
                else kwargs
            )

            def call():
                return RiskHistory.restore(
                    raw,
                    expected_sha256=sha256(raw),
                    expected_book_id=book._book_id,
                    expected_scope=hargs["scope"],
                    policy=hargs["policy"],
                    **restore_kwargs,
                )
        else:
            own(book)
            call = book.snapshot if point == "history_snapshot" else book.export_bytes
    elif point in {"account_constructor", "projection"}:
        book = RiskBook(**args)
        snap = book.snapshot()
        own(book)
        if point == "account_constructor":

            def call():
                return ExecutionAccount(
                    risk_book=book,
                    expected_snapshot_sha256=snap["snapshot_sha256"],
                    execution_binding=args["scope"]["execution_binding"],
                    execution_mode="accepted_actual",
                )
        else:

            def call():
                return project(
                    inputs,
                    risk_book=book,
                    risk_signal=signal,
                    execution_binding=args["scope"]["execution_binding"],
                    expected_input_sha256=digest(inputs),
                    expected_snapshot_sha256=snap["snapshot_sha256"],
                    expected_signal_sha256=digest(signal),
                )
    elif point == "account_snapshot":
        book, *_ = account()
        own(book)
        watched.extend([book._orders, book._declarations])
        call = book.snapshot
    else:
        cinputs, _, template, cargs = intent_case()
        if point == "candidate_constructor":
            own(cargs["risk_book"])

            def call():
                return CandidateIntent(template, **cargs)
        else:
            intent = CandidateIntent(template, **cargs)
            opened = CandidateOpen(
                cinputs["execution_open"],
                expected_sha256=digest(cinputs["execution_open"]),
            )
            intent.next_open(opened)
            own(intent._book)
            watched.append(intent._result)

            def call():
                return intent.next_open(opened)

    return call, lambda: deepcopy(watched)


@pytest.mark.parametrize("point", POINTS)
@pytest.mark.parametrize(
    "mode",
    ["diagnostic_context", "diagnostic_expected", "diagnostic_both", "formal_none"],
)
def test_each_bridge_entry_refuses_crossed_mode_before_checker_reader_worker(
    private_bridge_context, point, mode, record_property
):
    context, binding = private_bridge_context
    formal = mode == "formal_none"
    capability = context if mode in {"diagnostic_context", "diagnostic_both"} else None
    expected = binding if mode in {"diagnostic_expected", "diagnostic_both"} else None
    call, watch = entry(point, capability, expected, formal, binding)
    before = watch()
    calls = dict(checker=0, reader=0, worker=0, fee=0)
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if event != "call":
            return
        module = frame.f_globals.get("__name__", "")
        name = frame.f_code.co_name
        if module == b.__name__ and name == "check_release_context":
            calls["checker"] += 1
        if module.startswith("qlab.") and name in {
            "read_inputs",
            "read_strategy_inputs",
            "numeric_read",
            "guarded_value",
            "economic_values",
            "economic_read_receipt",
        }:
            calls["reader"] += 1
        if (
            (module.startswith("qlab.") and name in {"_worker", "run_isolated"})
            or module == "subprocess"
            and name in {"__init__", "run"}
        ):
            calls["worker"] += 1
        if module.endswith("fee_model") and name == "order_cost":
            calls["fee"] += 1

    reason = (
        "B.release_context_required" if formal else "B.release_context_scope_mismatch"
    )
    try:
        sys.setprofile(observe)
        with pytest.raises(ValueError, match="^" + reason + "$"):
            call()
    finally:
        sys.setprofile(previous)
    assert watch() == before
    assert calls == dict(checker=0, reader=0, worker=0, fee=0)
    record_property(
        "crossed_mode",
        json.dumps(
            dict(entry=point, mode=mode, reason=reason, **calls), sort_keys=True
        ),
    )


@pytest.mark.parametrize(
    "marker",
    [
        "schema",
        "B_catalog_release_sha256",
        "B_release_acceptance_sha256",
        "accepted_catalog_sha256",
        "release_context_binding",
        "request_binding",
    ],
)
def test_guard_only_predicate_never_uses_context_or_expected_bytes(
    private_bridge_context, marker
):
    context, binding = private_bridge_context
    _, args, _ = case()
    guard = deepcopy(args["guard"])
    assert CashProof.release_requested(guard, None, None) is False
    assert CashProof.release_requested(guard, context, None) is False
    assert CashProof.release_requested(guard, None, binding) is False
    assert CashProof.release_requested(guard, context, binding) is False
    if marker == "schema":
        guard["schema"] = "EVO883.BRuntimeGuard/v1"
    elif marker == "request_binding":
        guard["request"]["release_binding"] = {}
    else:
        guard[marker] = "PRIVATE_TEST_ONLY"
    assert CashProof.release_requested(guard, None, None) is True


def test_diagnostic_none_none_keeps_original_bridge(private_bridge_context):
    _, args, _ = case()
    before = deepcopy(args)
    assert CashProof.release_guard(args["guard"], args["policy"], None, None) is None
    assert args == before

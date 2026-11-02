"""Publisher CF01's synthetic providers; never imported by product code."""

from copy import deepcopy
import json
from pathlib import Path

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_closure import (
    ADOPTED_SHA256 as CLOSURE,
    adopted_execution_binding,
)
from qlab.dynamic_factor.execution_clock import (
    ADOPTED_SHA256 as CLOCK,
    adopted_clock_binding,
)
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.execution_projection import project
from qlab.dynamic_factor.noncash_v3 import seal_guard
from v3_test_helpers import synthetic_guard, synthetic_zero_state

ORACLE = Path(__file__).parent / "fixtures/execution-projection-oracle"


def case(
    inputs=None, *, role="candidate_solo_probe", member="F1-L020", recipe="F1-L020"
):
    inputs = (
        deepcopy(inputs)
        if inputs is not None
        else json.loads((ORACLE / "CF01.input.canonical.json").read_bytes())
    )
    p = load_conventions()
    close = inputs["close_state"]
    date = close["signal_close_session"]
    i = p.calendar.index(date)
    request = synthetic_guard(p, blocked=inputs["eligibility"]["B"])["request"]
    # CF01 explicitly has no child securities. Do not manufacture children or
    # remove them from a product report to force a golden match.
    for row in request["catalog"]["entries"]:
        row["children"] = []
    guard = seal_guard(request, p)
    state = synthetic_zero_state(guard)
    state.update(
        inventory=deepcopy(close["inventory"]),
        cash=float(close["cash"]),
        nav=float(close["NAV_anchor"]),
        age=deepcopy(close["age"]),
        origin=deepcopy(close["origin"]),
    )
    binding = adopted_execution_binding(expected_adoption_sha256=CLOSURE)
    book_id = digest(close["book_id"])
    scope = dict(
        kind="forward",
        scope_id="CF01 COUNTERFACTUAL ONLY",
        member_id=member,
        fold_id="CF01",
        attempt_id="CF01",
        execution_role=role,
        recipe_id=recipe,
        execution_binding=binding,
    )
    clock = adopted_clock_binding(expected_ruling_sha256=CLOCK)
    state["_risk_clock"] = dict(
        book_id=book_id,
        scope_id=scope["scope_id"],
        ruling_sha256=CLOCK,
        close_session=date,
        global_start=p.calendar[i - 30],
        entries={
            s: p.calendar[i - close["age"][s] + 1]
            for s, q in state["inventory"].items()
            if q and s != "QQQ"
        },
        cooldown_anchors={},
        pending_required_exits={},
        source_fills_sha256=digest("COUNTERFACTUAL PUBLISHER AGE DECLARATIONS ONLY"),
    )
    prior = dict(
        book_id=book_id,
        close_session=p.calendar[i - 1],
        peak=float(close["verified_close_peak"]),
        risk_latch=close["prior_risk_latch"],
    )
    args = dict(
        book_id=book_id,
        scope=scope,
        close_session=date,
        state=state,
        prior_risk=prior,
        fees_x2=0,
        canonical_scenario="x2",
        expected_original_state_sha256=digest(state),
        expected_prior_risk_sha256=digest(prior),
        guard=guard,
        clock_binding=clock,
        expected_clock_binding_sha256=digest(clock),
        expected_ruling_sha256=CLOCK,
        policy=p,
    )
    signal = dict(
        book_id=book_id,
        signal_session=date,
        execution_session=inputs["execution_open"]["session"],
        ranks={
            s: float(v)
            for s, v in inputs["locked_signal"][
                "ranks_ordinal_higher_score_is_rank1_average_ties"
            ].items()
        },
        origin_context=None,
    )
    return inputs, args, signal


def plan(inputs, args, signal, **overrides):
    args = deepcopy(args)
    args["expected_original_state_sha256"] = digest(args["state"])
    args["expected_prior_risk_sha256"] = digest(args["prior_risk"])
    book = RiskBook(**args)
    kwargs = dict(
        risk_book=book,
        risk_signal=signal,
        execution_binding=args["scope"]["execution_binding"],
        expected_input_sha256=digest(inputs),
        expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
        expected_signal_sha256=digest(signal),
    )
    kwargs.update(overrides)
    return project(inputs, **kwargs)

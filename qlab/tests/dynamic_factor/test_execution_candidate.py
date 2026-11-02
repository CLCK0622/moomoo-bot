"""C13 wiring probes over CF01 synthetic inputs; no strategy performance run."""

from copy import deepcopy
from decimal import Decimal
import json

import pytest

from projection_test_helpers import case, plan
from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.execution import voluntary_trade_gate
from qlab.dynamic_factor.execution_candidate import (
    CandidateIntent,
    CandidateOpen,
    ExecutionObservation,
    selection_from_stages,
)
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.execution_signals import DecayHistory
from qlab.dynamic_factor.pipeline import execution_observation
from test_execution_signals import meta_case


def wire_hash(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def intent_case(*, recipe="F1-L020", meta=False, alpha=0.0):
    inputs, args, signal = meta_case() if meta else case()
    if not meta:
        args["scope"].update(member_id=recipe, recipe_id=recipe)
        inputs["locked_signal"]["recipe_id"] = recipe
        for symbol in ("COP", "CVS"):
            args["state"]["origin"][symbol] = recipe
            inputs["close_state"]["origin"][symbol] = recipe
    args["expected_original_state_sha256"] = digest(args["state"])
    book = RiskBook(**args)
    selection = decay = None
    if meta:
        # Explicit synthetic monitoring rows precede the CF01 snapshot. No
        # caller state/half-coefficient override is substituted for DecayHistory.
        args["state"]["asof"] = args["close_session"] + "T20:00:00Z"
        args["expected_original_state_sha256"] = digest(args["state"])
        book = RiskBook(**args)
        members = list(inputs["locked_signal"]["factor_states"])
        context = {"fold_id": args["scope"]["fold_id"]}
        calibration = dict(
            m={k: [alpha] * 10 for k in members},
            mu_Q=0.0,
            context_sha256=digest(context),
            conventions_sha256=args["policy"].raw_sha256,
        )
        calibration["calibration_sha256"] = digest(calibration)
        stages = {
            "S0": {"context": context},
            "S1": {"calibration": calibration},
            "S2": {"pool": members},
        }
        ledger = StageReader(stages)
        available = dict(
            source_sha256=digest("SYNTHETIC ORIGINAL STAGES"),
            visible_at=args["state"]["asof"],
            authorized_at=args["state"]["asof"],
            fold_id=context["fold_id"],
        )
        selection = selection_from_stages(
            ledger,
            run_id="SYNTHETIC",
            fold_id=context["fold_id"],
            expected_stage_sha256={k: digest(v) for k, v in stages.items()},
            availability=available,
            expected_availability_sha256=digest(available),
            policy=args["policy"],
        )
        assert ledger.reads == ["S0", "S1", "S2"] and ledger.writes == 0
        signal["origin_context"]["source_sha256"] = selection.sha256
        decay = DecayHistory(
            book_id=args["book_id"],
            global_start=args["state"]["_risk_clock"]["global_start"],
            execution_role=args["scope"]["execution_role"],
            policy=args["policy"],
            execution_binding=args["scope"]["execution_binding"],
        )
        start = args["policy"].calendar.index(decay.start)
        end = args["policy"].calendar.index(args["close_session"])
        for i in range(start, end):
            prior_args = deepcopy(args)
            date = args["policy"].calendar[i]
            state = prior_args["state"]
            state.update(
                inventory={k: 0 for k in state["inventory"]},
                age={},
                origin={},
                cash=15000,
                nav=15000,
            )
            state["_risk_clock"].update(entries={}, close_session=date)
            state["asof"] = date + "T20:00:00Z"
            prior_args["close_session"] = date
            prior_args["prior_risk"]["close_session"] = args["policy"].calendar[i - 1]
            prior_args["expected_original_state_sha256"] = digest(state)
            prior_args["expected_prior_risk_sha256"] = digest(prior_args["prior_risk"])
            prior_book = RiskBook(**prior_args)
            assert prior_book.snapshot()["complete"], prior_book.snapshot()["reasons"]
            decay.observe(
                prior_book,
                {k: "0.01" for k in decay.states},
                expected_snapshot_sha256=prior_book.snapshot()["snapshot_sha256"],
            )
        assert book.snapshot()["complete"], book.snapshot()["reasons"]
        decay.observe(
            book,
            {k: "0.01" for k in decay.states},
            expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
        )
        signal["origin_context"]["permissions"] = {
            k: k in members for k in decay.states
        }
    template = {k: deepcopy(v) for k, v in inputs.items() if k != "execution_open"}
    kwargs = dict(
        risk_book=book,
        risk_signal=signal,
        execution_binding=args["scope"]["execution_binding"],
        expected_template_sha256=digest(template),
        expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
        expected_signal_sha256=digest(signal),
        selection=selection,
        decay=decay,
    )
    return inputs, args, template, kwargs


class StageReader:
    def __init__(self, stages):
        self.stages, self.reads, self.writes = stages, [], 0

    def recorded(self, key):
        name = key.rsplit("/", 1)[-1]
        self.reads.append(name)
        return deepcopy(self.stages[name])


def open_object(inputs):
    opened = inputs["execution_open"]
    return CandidateOpen(opened, expected_sha256=wire_hash(opened))


@pytest.mark.parametrize("recipe", ["F1-L020", "F2-L020", "F3-L020", "F4-L020"])
def test_C13_solo_dispatches_one_shared_D1_D2_and_original_inventory_orders(recipe):
    inputs, args, template, kwargs = intent_case(recipe=recipe)
    intent = CandidateIntent(template, **kwargs)
    out = voluntary_trade_gate(
        open_object(inputs), conventions=args["policy"], execution=intent
    )
    assert out["projection"] == plan(inputs, args, kwargs["risk_signal"])
    assert out["gain"]["selected_plan"] == "P"
    assert out["gain"]["reason"] == "candidate.fixed_solo_no_voluntary_GK"
    original = args["state"]["inventory"]
    assert out["projection"]["net_orders"] == [
        dict(
            symbol=row["symbol"],
            side="BUY"
            if out["projection"]["P"][row["symbol"]] > original[row["symbol"]]
            else "SELL",
            quantity=abs(
                out["projection"]["P"][row["symbol"]] - original[row["symbol"]]
            ),
            priority=i + 1,
        )
        for i, row in enumerate(out["projection"]["net_orders"])
    ]
    assert out["projection"]["M"]["CVS"] == 0 and original["CVS"] == 3
    assert any(row["symbol"] == "CVS" for row in out["projection"]["net_orders"])
    assert out["seal_status"] == "seal_pending"
    assert (
        out["certifiable"]
        is out["runtime_consumable"]
        is out["execution_verified"]
        is False
    )
    assert intent.identity()["snapshot_sha256"] == kwargs["expected_snapshot_sha256"]


@pytest.mark.parametrize(
    "member,recipe,role",
    [
        ("CREF-F1-L020", "F1-L020", "independent_candidate_reference"),
        ("CREF-F3-L020", "F3-L020", "independent_candidate_reference"),
        ("MREF-F2-L020", "F2-L020", "independent_meta_reference_probe_component"),
        ("MREF-F4-L020", "F4-L020", "independent_meta_reference_probe_component"),
    ],
)
def test_C13_same_input_candidate_and_four_reference_quantity_agreement(
    member, recipe, role
):
    inputs, args, template, kwargs = intent_case(recipe=recipe)
    out = CandidateIntent(template, **kwargs).next_open(open_object(inputs))
    reference, ref_args, ref_signal = case(
        inputs, role=role, member=member, recipe=recipe
    )
    expected = plan(reference, ref_args, ref_signal)
    assert out["projection"]["M"] == expected["M"]
    assert out["projection"]["P"] == expected["P"]
    assert out["projection"]["net_orders"] == expected["net_orders"]


@pytest.mark.parametrize("alpha,selected", [(0.0, "M"), (0.1, "P")])
def test_C13_META_preserves_original_GK_after_single_plan(alpha, selected):
    inputs, args, template, kwargs = intent_case(meta=True, alpha=alpha)
    intent = CandidateIntent(template, **kwargs)
    out = intent.next_open(open_object(inputs))
    assert out["projection"] == plan(inputs, args, kwargs["risk_signal"])
    assert "G_H10" in out["gain"], out["gain"].get("reason")
    assert out["gain"]["selected_plan"] == selected, out["gain"]
    assert out["selected_holdings"] == out["projection"][selected]
    assert out["gain"]["allowed"] is (out["gain"]["G_H10"] > out["gain"]["K"])
    assert Decimal(out["gain"]["C2_P"]) == Decimal("17.4645981")
    assert intent.next_open(open_object(inputs)) == out
    assert kwargs["decay"].rows == intent._decay.rows  # no next-open lifecycle step


def test_C13_solo_never_reads_meta_pool_and_cannot_accept_reference_role():
    inputs, args, template, kwargs = intent_case()
    kwargs["selection"] = StageReader({})
    with pytest.raises(ValueError, match="solo_must_not_read_meta_selection"):
        CandidateIntent(template, **kwargs)
    inputs, args, signal = case(
        role="independent_candidate_reference", member="CREF-F1-L020"
    )
    book = RiskBook(**args)
    kwargs.update(
        risk_book=book,
        risk_signal=signal,
        expected_snapshot_sha256=book.snapshot()["snapshot_sha256"],
    )
    with pytest.raises(ValueError, match="complete_role_bound_D2_required"):
        CandidateIntent(template, **kwargs)


@pytest.mark.parametrize(
    "key",
    ["expected_template_sha256", "expected_snapshot_sha256", "expected_signal_sha256"],
)
def test_C13_preclose_binding_rejects_stale_objects_before_any_open(key):
    _, _, template, kwargs = intent_case()
    kwargs[key] = "0" * 64
    with pytest.raises(
        ValueError, match="preclose_template_or_snapshot_binding_required"
    ):
        CandidateIntent(template, **kwargs)


@pytest.mark.parametrize(
    "key", ["M", "P", "returns", "locked_signal", "risk_signal", "selection"]
)
def test_C13_next_open_cannot_replace_signal_or_report_own_plan(key):
    inputs, _, _, _ = intent_case()
    opened = dict(inputs["execution_open"], **{key: {}})
    with pytest.raises(ValueError, match="open_cannot_replace_signal_or_plan"):
        CandidateOpen(opened, expected_sha256=wire_hash(opened))


def test_C13_no_second_open_or_optimization_and_caller_vector_is_not_owned():
    inputs, _, template, kwargs = intent_case()
    intent = CandidateIntent(template, **kwargs)
    original = intent.next_open(open_object(inputs))
    inputs["execution_open"]["raw_open"]["QQQ"] = "101"
    with pytest.raises(ValueError, match="one_open_binding_no_second_P"):
        intent.next_open(open_object(inputs))
    assert intent._result == original
    with pytest.raises(ValueError, match="owned_execution_observation_required"):
        execution_observation(
            {"returns": [0.0] * 1260, "seal_status": "seal_pending"},
            context={},
            member_id="F1-L020",
            execution_role="candidate_solo_probe",
        )


def test_C13_pending_formal_receipt_rejected_without_consuming_fields():
    # Controlled internal envelope for the formal rejection itself. This is
    # deliberately NOT a C07 producer integration or a reseal positive.
    from qlab.dynamic_factor.execution_candidate import _ISSUER

    pending = ExecutionObservation(_ISSUER, {"seal_status": "seal_pending"})
    with pytest.raises(ValueError, match="execution_seal_pending"):
        execution_observation(
            pending,
            context={},
            member_id="F1-L020",
            execution_role="candidate_solo_probe",
        )


@pytest.mark.parametrize("field", ["ticker", "dependency", "source"])
def test_C13_B2_rejected_before_plan_and_any_reader(field):
    inputs, _, template, kwargs = intent_case()
    template[field] = "VTI"
    with pytest.raises(ValueError, match="scope.B2_dependency_forbidden"):
        CandidateIntent(template, **kwargs)
    opened = dict(inputs["execution_open"], **{field: "VTI"})
    with pytest.raises(ValueError, match="scope.B2_dependency_forbidden"):
        CandidateOpen(opened, expected_sha256=wire_hash(opened))

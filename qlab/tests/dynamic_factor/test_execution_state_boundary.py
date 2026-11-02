"""C04 repair: exact money is opt-in on the new C04/C06 paths only."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.continuity import historical_continuous_path_check
from qlab.dynamic_factor.execution import voluntary_trade_gate
from qlab.dynamic_factor.execution_cash import check_cash_state
from qlab.dynamic_factor.execution_risk import RiskBook
from qlab.dynamic_factor.isolation import seal_manifest
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.dynamic_factor.noncash_v3 import zero_exposure
from qlab.dynamic_factor.v1_harness import unit_context
from projection_test_helpers import case
from test_v2_isolation import synthetic_manifest
from test_v2_state import complete_grid
from v3_test_helpers import synthetic_guard, synthetic_zero_state


def gain_request(policy):
    state = synthetic_zero_state(synthetic_guard(policy))
    date = policy.calendar[600]
    return dict(
        context=unit_context(policy),
        account_scope="SYNTHETIC STATE BOUNDARY",
        signal_close=date,
        execution_date=policy.calendar[601],
        sell_date=policy.calendar[601],
        run_id="SYNTHETIC",
        fold_id="0",
        rate_basis="research_restored",
        M={},
        P={},
        original_inventory=deepcopy(state["inventory"]),
        raw_open_prices={},
        cash=15000,
        calibration={},
        pool=[],
        required_exit_symbols=[],
        required_state=state,
        isolation_manifest=seal_manifest(
            synthetic_manifest(policy, 50, 0, date=date), policy
        ),
    )


@pytest.mark.parametrize("field", ["cash", "nav", "both"])
@pytest.mark.parametrize("entry", ["execution", "noncash_v3", "continuity"])
def test_legacy_entry_keeps_original_R2_for_string_money(
    tmp_path, field, entry, record_property
):
    policy = load_conventions()

    def strings(state):
        for key in ["cash", "nav"] if field == "both" else [field]:
            state[key] = str(state[key])

    if entry == "execution":
        request = gain_request(policy)
        strings(request["required_state"])
        ledger = AttemptLedger(tmp_path / "synthetic.sqlite")
        ledger.record("v02/SYNTHETIC/0/S1", {"calibration": {}})
        ledger.record("v02/SYNTHETIC/0/S2", {"pool": []})
        out = voluntary_trade_gate(request, conventions=policy, ledger=ledger)
        assert not out["ok"]
        reasons = out["reasons"]
        assert reasons == ["state.R2_necessary_state_unknown"]
    elif entry == "noncash_v3":
        guard = synthetic_guard(policy)
        state = synthetic_zero_state(guard)
        strings(state)
        with pytest.raises(
            ValueError, match="^state.R2_necessary_state_unknown$"
        ) as exc:
            zero_exposure(state, guard)
        reasons = [str(exc.value)]
    else:
        request = complete_grid(policy)
        for row in request["folds"]:
            for key in ("input_state", "output_state"):
                strings(row[key])
                row[key + "_sha256"] = digest(row[key])
        out = historical_continuous_path_check(request, conventions=policy)
        assert not out["ok"] and out["metrics"]["R2_stop"]
        reasons = out["reasons"]
        assert "state.R2_necessary_state_unknown" in reasons
        assert out["metrics"]["A"] is None and out["metrics"]["IR"] is None
    import json

    record_property(
        "state_boundary_observation",
        json.dumps(dict(entry=entry, field=field, reasons=reasons)),
    )


def test_C06_scoped_exact_state_stays_bound_and_unmodified():
    from qlab.dynamic_factor.execution_state import necessary_execution_state_known

    _, args, _ = case()
    state = args["state"]
    state["cash"], state["nav"] = "1000", "15000"
    before = deepcopy(state)
    args["expected_original_state_sha256"] = digest(state)
    necessary_execution_state_known(state)
    check_cash_state(state, args["guard"], None)
    risk = RiskBook(**args).snapshot()
    assert risk["complete"], risk["reasons"]
    assert state == before and risk["state"] == before
    with pytest.raises(ValueError, match="R2_necessary_state_unknown"):
        zero_exposure(state, args["guard"])


@pytest.mark.parametrize(
    "value", ["1.0", "01", "-0", "-1", "NaN", "1e3", "", None, True]
)
def test_scoped_state_rejects_noncanonical_or_unknown_money(value):
    from qlab.dynamic_factor.execution_state import necessary_execution_state_known

    state = synthetic_zero_state(synthetic_guard())
    state["cash"] = value
    with pytest.raises(ValueError, match="R2_necessary_state_unknown"):
        necessary_execution_state_known(state)

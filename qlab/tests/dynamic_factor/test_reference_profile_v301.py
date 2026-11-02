"""C02 / A01 and A04: reject altered theta/gates before plan construction."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.reference_definition_v301 import (
    FROZEN,
    frozen_documents,
    reference_definitions,
)
from qlab.dynamic_factor.reference_profile_v301 import (
    solo_profile,
    validate_solo_profile,
)


def _rehash(packet):
    packet["profile_sha256"] = digest(
        {k: v for k, v in packet.items() if k != "profile_sha256"}
    )
    return packet


@pytest.mark.parametrize("index", range(4))
def test_A01_fixed_solo_profile_reuses_exact_shared_contract_and_constraints(index):
    packet = solo_profile(reference_definitions()[index])
    assert validate_solo_profile(packet) == packet
    assert packet["solo_overrides"] == dict(
        tilt_fraction=0.20,
        DSR_admission=False,
        decay_pool_selection=False,
        voluntary_gain_cost_gate=False,
    )
    assert (
        packet["common_profile"]
        == frozen_documents()["EVO883-D12-common-profile-v3.0.1.json"]
    )
    assert packet["shared_planner"] == dict(
        contract_sha256=FROZEN["EVO883-D12-shared-execution-contract-v3.0.1.json"],
        quantity_pointer="/D1",
        risk_pointer="/D2",
    )
    constraints = packet["execution_contract"]
    for key in (
        "B_guard_before_numeric_consumer",
        "same_E_t_for_all16_recipe_inputs",
        "same_global_B_release_and_effective_E_t_for_all16",
        "include_startup_and_terminal_costs",
        "masked_dates_are_not_dropped_from1260_return_calendar",
    ):
        assert constraints[key] is True
    assert constraints["startup_cash_usd"] == 15000
    assert packet["common_profile"]["portfolio"]["integer_shares"] is True
    assert packet["runtime_consumable"] is packet["certifiable"] is False


@pytest.mark.parametrize("section", ["solo_overrides", "execution_contract"])
@pytest.mark.parametrize("theta", [0.05, 0, 0.2001, "0.20", True])
def test_A04_quarter_budget_or_caller_theta_rejects_even_with_recomputed_digest(
    section, theta
):
    packet = solo_profile(reference_definitions()[0])
    packet[section]["tilt_fraction"] = theta
    with pytest.raises(ValueError, match="reference.solo_profile_mismatch"):
        validate_solo_profile(_rehash(packet))


@pytest.mark.parametrize("section", ["solo_overrides", "execution_contract"])
@pytest.mark.parametrize(
    "gate", ["DSR_admission", "decay_pool_selection", "voluntary_gain_cost_gate"]
)
@pytest.mark.parametrize("value", [True, 0, None])
def test_A04_all_three_overrides_are_explicit_false_not_truthy_defaults(
    section, gate, value
):
    packet = solo_profile(reference_definitions()[0])
    packet[section][gate] = value
    with pytest.raises(ValueError, match="reference.solo_profile_mismatch"):
        validate_solo_profile(_rehash(packet))


def test_A04_missing_override_and_changed_common_costs_reject():
    original = solo_profile(reference_definitions()[0])
    missing = deepcopy(original)
    del missing["solo_overrides"]["voluntary_gain_cost_gate"]
    changed = deepcopy(original)
    changed["common_profile"]["portfolio"]["integer_shares"] = False
    injected = deepcopy(original)
    injected["current_meta_pool"] = []
    for packet in (missing, changed, injected):
        with pytest.raises(ValueError, match="reference.solo_profile_mismatch"):
            validate_solo_profile(_rehash(packet))


def test_A04_four_members_share_one_planner_contract_and_no_pool_is_read():
    profiles = [solo_profile(d) for d in reference_definitions()]
    assert all(p["shared_planner"] == profiles[0]["shared_planner"] for p in profiles)
    assert all(p["solo_overrides"] == profiles[0]["solo_overrides"] for p in profiles)
    assert len({p["profile_sha256"] for p in profiles}) == 4
    assert all("current_meta_pool" not in p for p in profiles)

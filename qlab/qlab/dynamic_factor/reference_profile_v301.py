"""C02: fixed solo parameters over the unchanged, shared execution profile.

This is configuration, not a second quantity projector or risk engine. The
four reference members use theta 0.20 and the same three explicit overrides.
The current META pool's quarter-budget formula must not be used for a solo.
"""

from .contract import digest
from .reference_definition_v301 import (
    FROZEN,
    _same,
    frozen_documents,
    validate_member_definition,
)
from .reference_registry_v3 import member_spec


def solo_profile(definition):
    definition = validate_member_definition(definition)
    parameters = member_spec(definition["member_id"])["execution_contract"]
    common = frozen_documents()["EVO883-D12-common-profile-v3.0.1.json"]
    profile = dict(
        schema="EVO884.ReferenceSoloProfile/v1",
        definition=definition,
        common_profile=common,
        common_profile_sha256=FROZEN["EVO883-D12-common-profile-v3.0.1.json"],
        execution_contract=parameters,
        solo_overrides=dict(
            tilt_fraction=parameters["tilt_fraction"],
            DSR_admission=parameters["DSR_admission"],
            decay_pool_selection=parameters["decay_pool_selection"],
            voluntary_gain_cost_gate=parameters["voluntary_gain_cost_gate"],
        ),
        shared_planner=dict(
            contract_sha256=FROZEN["EVO883-D12-shared-execution-contract-v3.0.1.json"],
            quantity_pointer="/D1",
            risk_pointer="/D2",
        ),
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(profile, profile_sha256=digest(profile))


def validate_solo_profile(profile):
    if type(profile) is not dict:
        raise ValueError("reference.solo_profile_mismatch")
    expected = solo_profile(profile.get("definition"))
    if not _same(profile, expected):
        raise ValueError("reference.solo_profile_mismatch")
    return expected

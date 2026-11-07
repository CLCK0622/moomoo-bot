"""C06's one adopted clock. No caller-selected clock or runtime permission."""

from copy import deepcopy
import json

from .contract import digest, sha256
from .reference_definition_v301 import ROOT


NAME = "EVO883-C06-CLOCK-adopted-protocol-v1.0.0.json"
ADOPTED_SHA256 = "8cd32345adb5ebe16cb9020687091532c46f803f046d6c1527eeedee41407a5a"
DRAFT_SHA256 = (
    "ecbb377d64a8f4e2db6eeed7347aa9297460602eee7ccc0671038457a5e0c4c3",
    "7288912b853820fd63b75f82dfaf9373e0320588eee95549f935b147fad8a41e",
    "92f0565e4ad92ae4cb5f3d4db2f52c78e98e230d7b67f2064da0d50bfa4866d7",
)


def adopted_clock_binding(*, expected_ruling_sha256):
    if expected_ruling_sha256 != ADOPTED_SHA256:
        raise ValueError("risk.formal_clock_adoption_required")
    try:
        raw = (ROOT / NAME).read_bytes()
    except OSError as exc:
        raise ValueError("risk.formal_clock_adoption_missing") from exc
    if sha256(raw) != ADOPTED_SHA256:
        raise ValueError("risk.formal_clock_adoption_identity_mismatch")
    rules = json.loads(raw)["adopted_rules"]
    # This projection follows the exact adopted source, not an independent
    # set of defaults. Original adopted bytes and qualifications stay intact.
    return dict(
        ruling_sha256=ADOPTED_SHA256,
        age_clock=dict(
            entry_close_age=rules["C06_1"]["first_verified_held_close_age"],
            step_per_held_close=1,
        ),
        cooldown_boundary=dict(
            start_event="complete_exit_fill_open",
            first_blocked_execution_offset=rules["C06_2"]["blocked_close_open_offsets"][
                0
            ][1],
            blocked_sessions=rules["C06_2"]["remaining_at_C_e"],
        ),
    )


def validate_clock_binding(binding, expected_binding_sha, expected_ruling_sha):
    if binding is None:
        raise ValueError("risk.clock_binding_required")
    expected = adopted_clock_binding(expected_ruling_sha256=expected_ruling_sha)
    # Canonical bytes preserve bool/int distinctions. Digest self-consistency
    # alone never promotes a hypothetical or draft policy into adopted policy.
    if (
        type(binding) is not dict
        or digest(binding) != expected_binding_sha
        or json.dumps(binding, sort_keys=True, allow_nan=False)
        != json.dumps(expected, sort_keys=True, allow_nan=False)
    ):
        raise ValueError("risk.clock_binding_mismatch")
    return deepcopy(expected)

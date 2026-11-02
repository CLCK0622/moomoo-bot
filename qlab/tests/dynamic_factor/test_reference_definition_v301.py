"""C01 / A01 and A03: definitions only, no evaluation or runtime acceptance."""

from copy import deepcopy

import pytest

from qlab.dynamic_factor import reference_definition_v301 as definitions
from qlab.dynamic_factor.reference_registry_v3 import artifact


def test_A01_four_frozen_definitions_preserve_formula_H10_L20_seed_and_roles():
    values = definitions.reference_definitions()
    assert [v["member_id"] for v in values] == [
        "CREF-F1-L020",
        "CREF-F3-L020",
        "MREF-F2-L020",
        "MREF-F4-L020",
    ]
    originals = {}
    for role in ("candidate", "meta"):
        originals.update(
            {
                m["member_id"]: m
                for m in artifact(role + "_reference_manifest.json")["document"][
                    "members"
                ]
            }
        )
    for value in values:
        original = originals[value["member_id"]]
        assert definitions.validate_member_definition(value) == value
        assert value["fixed_rule"] == original["fixed_rule"]
        assert value["fixed_rule"]["horizon_sessions"] == 10
        assert value["fixed_rule"]["lookback_sessions"] == 20
        assert value["fixed_rule"]["seed"] is None
        assert value["recipe_id"] == original["recipe_id"]
        assert value["execution_profile_id"] == "CANDIDATE_PROBE_V3"
        assert value["runtime_consumable"] is value["certifiable"] is False


@pytest.mark.parametrize(
    "member_id", ["CREF-F1-L005", "MREF-F1-L020", "META_POLICY_V3", None, []]
)
def test_A03_unregistered_member_refuses(member_id):
    with pytest.raises(ValueError, match="reference.member_not_registered"):
        definitions.member_definition(
            member_id, execution_role="independent_candidate_reference"
        )


@pytest.mark.parametrize("member_id", ["MREF-F2-L020", "MREF-F4-L020"])
@pytest.mark.parametrize(
    "role",
    [
        "current_META_POLICY_execution_layer",
        "META_EVAL_V3",
        "independent_candidate_reference",
        None,
    ],
)
def test_A03_meta_reference_cannot_be_current_meta_or_another_role(member_id, role):
    with pytest.raises(ValueError, match="reference.execution_role_mismatch"):
        definitions.member_definition(member_id, execution_role=role)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expression", "C[t]/C[t-5]-1"),
        ("horizon_sessions", 5),
        ("lookback_sessions", 60),
        ("seed", 0),
        ("seed", float("nan")),
        ("horizon_sessions", 10.0),
    ],
)
def test_A03_changed_definition_cannot_be_rehashed_into_registration(field, value):
    packet = definitions.reference_definitions()[0]
    packet["fixed_rule"][field] = value
    raw = {k: v for k, v in packet.items() if k != "definition_sha256"}
    packet["definition_sha256"] = definitions.digest(raw)
    with pytest.raises(ValueError, match="reference.execution_definition_mismatch"):
        definitions.validate_member_definition(packet)


def test_definition_mutation_cannot_change_future_definitions():
    original = definitions.reference_definitions()
    changed = deepcopy(original[0])
    changed["bindings"]["common_profile_sha256"] = "0" * 64
    changed["current_pool"] = []
    with pytest.raises(ValueError, match="reference.execution_definition_mismatch"):
        definitions.validate_member_definition(changed)
    assert definitions.reference_definitions() == original


def test_A01_shared_contract_bytes_are_checked_before_definition(tmp_path, monkeypatch):
    for name in definitions.FROZEN:
        (tmp_path / name).write_bytes((definitions.ROOT / name).read_bytes())
    target = tmp_path / "EVO883-D12-shared-execution-contract-v3.0.1.json"
    target.write_bytes(target.read_bytes() + b" ")
    monkeypatch.setattr(definitions, "ROOT", tmp_path)
    with pytest.raises(
        ValueError, match="reference.execution_contract_identity_mismatch"
    ):
        definitions.reference_definitions()

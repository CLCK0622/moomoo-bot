"""C01: frozen four-member definitions, without execution or authority credit.

The registry remains 3.0.0. This separate envelope binds its unchanged member
definitions to the approved v3.0.1 shared execution supplement. An MREF member
is a solo probe component, never the current META_POLICY or its selected pool.
"""

import json
from pathlib import Path

from .contract import digest, sha256
from .reference_registry_v3 import DISPATCH, HASHES, artifact, member_spec

ROOT = Path(__file__).parent / "fixtures" / "execution-v3.0.1"
FROZEN = {
    "EVO883-D12-shared-execution-contract-v3.0.1.json": "f7a0623da88a7e2874ef5e372750ad04a1edca9796acc0c3fee02616f766a496",
    "EVO883-D12-common-profile-v3.0.1.json": "07b71b3fc59dc6dae1c96cadd3155622a18f4c4ad29b7c69b8f79c1455efc2d3",
    "EVO883-D12-addendum-v3.0.1.md": "f540dce44e00b7077a94d3155f55db5fdba700b7a48911ec03697724b8dfa8c9",
}
ROLES = {
    "candidate": "independent_candidate_reference",
    "meta": "independent_meta_reference_probe_component",
}


def frozen_documents():
    """Read exact approved bytes; this is no deployment or runtime receipt."""
    documents = {}
    for name, expected in FROZEN.items():
        raw = (ROOT / name).read_bytes()
        if sha256(raw) != expected:
            raise ValueError("reference.execution_contract_identity_mismatch")
        documents[name] = json.loads(raw) if name.endswith(".json") else raw.decode()
    return documents


def _same(actual, expected):
    """Do not equate bool/int, absent/null, float/int, or nonfinite/null."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same(a, b) for a, b in zip(actual, expected)
        )
    return actual == expected


def member_definition(member_id, *, execution_role):
    if type(member_id) is not str or member_id not in DISPATCH:
        raise ValueError("reference.member_not_registered_or_incomplete")
    family, _ = DISPATCH[member_id]
    if execution_role != ROLES[family]:
        raise ValueError("reference.execution_role_mismatch")
    documents = frozen_documents()
    shared = documents["EVO883-D12-shared-execution-contract-v3.0.1.json"]
    if execution_role not in shared["applies_to"]:
        raise ValueError("reference.execution_role_mismatch")
    artifact("predeclared_reference_registry.json")
    member = member_spec(member_id)
    definition = dict(
        schema="EVO884.ReferenceMemberDefinition/v1",
        execution_version="v3.0.1",
        registry_version="3.0.0",
        member_id=member_id,
        family=family,
        recipe_id=member["recipe_id"],
        fixed_rule=member["fixed_rule"],
        profile_id=member["profile_id"],
        execution_profile_id=member["execution_profile_id"],
        execution_role=execution_role,
        return_role=member["return_role"],
        role_membership=member["role_membership"],
        bindings=dict(
            registry_sha256=HASHES["predeclared_reference_registry.json"],
            definition_manifest_sha256=member["definition_manifest_sha256"],
            shared_contract_sha256=FROZEN[
                "EVO883-D12-shared-execution-contract-v3.0.1.json"
            ],
            common_profile_sha256=FROZEN["EVO883-D12-common-profile-v3.0.1.json"],
            addendum_sha256=FROZEN["EVO883-D12-addendum-v3.0.1.md"],
            parent_prereg_sha256=shared["parent_prereg_sha256"],
        ),
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(definition, definition_sha256=digest(definition))


def validate_member_definition(definition):
    if type(definition) is not dict:
        raise ValueError("reference.execution_definition_mismatch")
    expected = member_definition(
        definition.get("member_id"), execution_role=definition.get("execution_role")
    )
    if not _same(definition, expected):
        raise ValueError("reference.execution_definition_mismatch")
    return expected


def reference_definitions():
    """Closed ordered family; no caller-supplied recipe, seed, or subset."""
    return [
        member_definition(member_id, execution_role=ROLES[DISPATCH[member_id][0]])
        for member_id in sorted(DISPATCH)
    ]

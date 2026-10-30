"""Exact EVO-892 definitions; never edit registered bytes to add runtime results."""

import json
from pathlib import Path

from .contract import sha256

ROOT = Path(__file__).parent / "fixtures" / "evo892-v3"
HASHES = {
    "lineage-plan.json": "c977dfbcce2b666f85c54ee771c709b8485470948aeab5daa2bf0e57ec76ab2a",
    "noncash-consumer-contract.json": "216206a1c36fa61ad275692ee68d5247636ea94adb18cc127d2dfe170906802d",
    "candidate_reference_manifest.json": "bcce6f17f3515d66eb5b87569720740efb6eb70eca2d774a853be8e3cdecb4a4",
    "predeclared_reference_registry.json": "f531d65a5ad54fc68a8be40bc25cbb3987d0aeedd4c2c345ed334b1599445c48",
    "meta_reference_manifest.json": "964e9903e13bd618777f00652bad09272d7aa4ddbb3cec2c28371a8378002ae6",
    "runtime-evidence-contract.json": "f62481ad9e0d9913d29eae58de6b837c90a51c5d7dae6968a4fea0da35001964",
    "reference-isolation-contract.json": "d7cb2a57fd63ce6a1f57ecf1a9c3957de1314b31a64a133f1b560014544d5a97",
    "platform-anchor.json": "563a35795fc3d2ffa85f96cab0bb89e04bde9d4c948725ed85e5c2fe32c1421e",
    "fold-bindings.json": "f4ce91be042287d9e51f5117e0781f5c5e79cbf7d93d4808afe7ef391320d81b",
}
# No callback, search, eval, rule synthesis or current-pool-dependent dispatch.
DISPATCH = {
    "CREF-F1-L020": ("candidate", "F1-L020"),
    "CREF-F3-L020": ("candidate", "F3-L020"),
    "MREF-F2-L020": ("meta", "F2-L020"),
    "MREF-F4-L020": ("meta", "F4-L020"),
}


def artifact(name):
    raw = (ROOT / name).read_bytes()
    if sha256(raw) != HASHES[name]:
        raise ValueError("reference.registered_artifact_identity_mismatch")
    return {"raw": raw.decode(), "document": json.loads(raw), "sha256": sha256(raw)}


def registered_request():
    registry = artifact("predeclared_reference_registry.json")
    registry["platform_anchor"] = artifact("platform-anchor.json")["document"]
    return {
        "registry": registry,
        "manifests": {
            r: artifact(r + "_reference_manifest.json") for r in ("candidate", "meta")
        },
        "first_performance_at": None,
    }


def member_spec(member_id):
    if member_id not in DISPATCH:
        raise ValueError("reference.member_not_registered_or_incomplete")
    role, recipe = DISPATCH[member_id]
    manifest = artifact(role + "_reference_manifest.json")
    member = next(
        m for m in manifest["document"]["members"] if m["member_id"] == member_id
    )
    if (
        member["recipe_id"] != recipe
        or member["execution_profile_id"] != "CANDIDATE_PROBE_V3"
    ):
        raise ValueError("reference.execution_role_mismatch")
    return dict(
        member,
        definition_manifest_sha256=manifest["sha256"],
        execution_contract=manifest["document"]["common_contract"][
            "execution_contract"
        ],
    )

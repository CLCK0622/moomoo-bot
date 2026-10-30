"""Exact EVO-892 definitions; never edit registered bytes to add runtime results."""

import json
from pathlib import Path

from .contract import sha256

ROOT = Path(__file__).parent / "fixtures" / "evo892"
HASHES = {
    "predeclared_reference_registry.json": "83c9d47f375235faf0021342ff2e0a36b8cdc46a58975da8b31c50bd73aea3b2",
    "candidate_reference_manifest.json": "17c0080003bc984029dc8954486798d9b821eff79a369307e2fa8e8e39eabfc4",
    "meta_reference_manifest.json": "c6fa724aa501d346de2f6ace28afe971eabd4777cc8a0f3850bb849e37bba4f4",
    "lineage-plan.json": "20247efaa46ae945dd0dc7a94fb29683c5fa404e5039e79f92a223dc39e9182b",
    "runtime-evidence-contract.json": "98d1a2d49a054c1167e6744758d1dcdbfa65d3ca2474033b5102c0f2c812fec6",
    "fold-bindings.json": "8c40536cf6cc1780a61081548c5935256e2080e50e82c7c2953b051901ea0514",
    "platform-anchor.json": "7d09b4916178a7f9bb223133e778fdcbf830988c2c9990b7497d58fff6b4b3f8",
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
        or member["execution_profile_id"] != "CANDIDATE_PROBE_V03"
    ):
        raise ValueError("reference.execution_role_mismatch")
    return dict(
        member,
        definition_manifest_sha256=manifest["sha256"],
        execution_contract=manifest["document"]["common_contract"][
            "execution_contract"
        ],
    )

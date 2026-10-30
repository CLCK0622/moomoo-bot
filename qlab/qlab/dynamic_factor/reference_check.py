"""Registry/manifest guards and a static proof for the independent producer.

No real registry or new member rules are fabricated. The only positive registry
examples live in the offline unit harness. Runtime DSR/V stay null after checks.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

from .contract import digest, is_sha, result, sha256, unavailable
from .conventions import load_conventions

MODULES = {
    "reference_producer": {
        "argparse",
        "hashlib",
        "json",
        "fold_split",
        "reference_inputs",
    },
    "reference_inputs": {"hashlib", "json", "pathlib"},
    "fold_split": set(),
}


def static_proof():
    graph, sources, reads = {}, {}, []
    for name, allowed in MODULES.items():
        raw = (Path(__file__).parent / (name + ".py")).read_bytes()
        tree = ast.parse(raw)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            if isinstance(node, ast.Call):
                call = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                )
                if call in {
                    "eval",
                    "exec",
                    "__import__",
                    "compile",
                    "open",
                    "write_text",
                    "write_bytes",
                    "unlink",
                    "rename",
                }:
                    raise ValueError("reference.static_call_forbidden")
                if call == "read_bytes":
                    if name != "reference_inputs":
                        raise ValueError("reference.static_reader_forbidden")
                    reads.append(
                        {
                            "module": name,
                            "line": node.lineno,
                            "roles": ["panel", "benchmark", "profile"],
                        }
                    )
        if not imports.issubset(allowed):
            raise ValueError("reference.static_dependency_forbidden")
        graph[name] = sorted(imports)
        sources[name + ".py"] = sha256(raw)
    return {
        "import_graph": graph,
        "source_files": sources,
        "reader_sites": reads,
        "source_sha256": digest(sources),
        "read_whitelist": {
            "panel": "panel.json",
            "benchmark": "benchmark.json",
            "profile": "profile.json",
        },
        "forbidden_inputs": [
            "candidate_returns",
            "candidate_SR",
            "pool",
            "meta_returns",
            "meta_SR",
        ],
        "shared_splitter_sha256": sources["fold_split.py"],
        "scope": "static proof for pinned trusted source, not an arbitrary Python OS sandbox",
    }


def verify_registry(registry, manifests, policy, first_performance_at):
    if registry is None:
        raise ValueError("reference.registry_missing")
    if manifests is None or set(manifests) != {"candidate", "meta"}:
        raise ValueError("reference.manifest_missing")
    doc = registry["document"]
    if registry["sha256"] != sha256(registry["raw"].encode()) or digest(doc) != digest(
        json.loads(registry["raw"])
    ):
        raise ValueError("reference.registry_sha_mismatch")
    if (
        doc["interface_sha256"] != policy.raw_sha256
        or doc["prereg_sha256"] != policy.binding["prereg_sha256"]
        or doc["profile_sha256"] != policy.binding["common_profile_sha256"]
    ):
        raise ValueError("reference.profile_or_version_mismatch")
    if not is_sha(doc["platform_anchor_sha256"]) or not is_sha(
        doc["non_author_review_sha256"]
    ):
        raise ValueError("reference.authority_receipt_missing")
    if not isinstance(first_performance_at, str):
        raise ValueError("reference.performance_time_anchor_missing")
    if datetime.fromisoformat(
        doc["created_at"].replace("Z", "+00:00")
    ) >= datetime.fromisoformat(first_performance_at.replace("Z", "+00:00")):
        raise ValueError("reference.registration_not_preperformance")
    for layer in ("candidate", "meta"):
        manifest = manifests[layer]
        expected = doc["manifests"][layer]
        if (
            manifest["sha256"] != sha256(manifest["raw"].encode())
            or manifest["sha256"] != expected["sha256"]
        ):
            raise ValueError("reference.manifest_sha_mismatch")
        payload = json.loads(manifest["raw"])
        if (
            payload["profile_sha256"] != doc["profile_sha256"]
            or payload["role"] != layer
        ):
            raise ValueError("reference.profile_or_role_mismatch")
        members = payload["members"]
        minimum = policy.document["variance_layers"]["independent_reference"][
            "minimum_finite_SR_per_complete_reference_family"
        ]
        if (
            not isinstance(members, list)
            or len(members) < minimum
            or not all(isinstance(m, str) and m for m in members)
        ):
            raise ValueError("reference.complete_membership_required")
        if len(members) != len(set(members)) or set(members) != set(
            expected["members"]
        ):
            raise ValueError("reference.member_not_registered_or_incomplete")
    return doc


def reference_manifest_check(request, *, conventions=None):
    policy = conventions or load_conventions()
    reasons = []
    try:
        verify_registry(
            request.get("registry"),
            request.get("manifests"),
            policy,
            request.get("first_performance_at"),
        )
    except (ValueError, TypeError, KeyError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, ValueError)
            else "reference.input_invalid_or_missing"
        )
    return policy.bind(
        result(
            "reference_manifest_check",
            {"request": request, **policy.binding},
            metrics={
                "dsr": None,
                "trials_variance": None,
                "registry_valid": not reasons,
            },
            reasons=reasons,
            availability={
                k: unavailable(
                    reasons[0] if reasons else "dsr.runtime_bindings_pending"
                )
                for k in ("dsr", "trials_variance")
            },
            artifacts={"producer_static_proof": static_proof()},
        )
    )


def register_reference_attempts(
    registry, manifests, *, policy, ledger, fold_id, first_performance_at
):
    doc = verify_registry(registry, manifests, policy, first_performance_at)
    members = sorted(
        {m for layer in doc["manifests"].values() for m in layer["members"]}
    )
    run = f"reference/{registry['sha256']}/{fold_id}"
    attempts = [run + "/" + m for m in members]
    ledger.declare_family(
        run,
        attempts,
        basis=policy.document["N"]["DSR_SR_basis"],
        authority_source={
            "reference": doc["registry_id"],
            "sha256": registry["sha256"],
        },
    )
    for aid, member in zip(attempts, members):
        ledger.begin(
            aid,
            {"reference_member": member},
            kind="reference",
            context={"run_id": run},
            replay=False,
        )
    return attempts

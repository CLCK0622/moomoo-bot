"""Registry/manifest guards and a static proof for the independent producer.

No real registry or new member rules are fabricated. The only positive registry
examples live in the offline unit harness. Runtime DSR/V stay null after checks.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

from .contract import digest, result, sha256, unavailable
from .conventions import load_conventions

MODULES = {
    "reference_producer_v3": {
        "argparse",
        "hashlib",
        "json",
        "fold_split",
        "reference_inputs",
        "reference_guard",
        "reference_v3_scope",
    },
    "reference_v3_scope": {
        "hashlib",
        "json",
        "math",
        "catalog_members",
        "reference_validation",
    },
    "reference_validation": {"datetime", "hashlib", "json", "math"},
    "catalog_members": set(),
    "reference_producer": {
        "argparse",
        "hashlib",
        "json",
        "fold_split",
        "reference_inputs",
        "reference_guard",
    },
    "reference_inputs": {"hashlib", "json", "pathlib", "input_scope"},
    "input_scope": set(),
    "fold_split": {"dataclasses"},
    "reference_guard": {"os", "sys", "pathlib"},
}


def static_proof():
    graph, sources, reads = {}, {}, []
    for name, allowed in MODULES.items():
        raw = (Path(__file__).parent / (name + ".py")).read_bytes()
        tree = ast.parse(raw)
        for statement in tree.body:
            if isinstance(
                statement, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)
            ):
                continue
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                continue
            if isinstance(statement, ast.Assign):
                try:
                    ast.literal_eval(statement.value)
                    continue
                except (ValueError, TypeError):
                    pass
            if (
                name in {"reference_producer", "reference_producer_v3"}
                and isinstance(statement, ast.If)
                and ast.unparse(statement.test) == "__name__ == '__main__'"
            ):
                continue
            raise ValueError("reference.static_import_time_effect_forbidden")
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
        if name in {"reference_producer", "reference_producer_v3"}:
            main = next(
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main"
            )
            calls = {
                n.func.id: n.lineno
                for n in ast.walk(main)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            if calls.get("install", 10**9) >= calls.get("prepare", -1):
                raise ValueError("reference.audit_hook_must_precede_data_reads")
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
    from .reference_registry import artifact, HASHES, DISPATCH

    if policy.document["version"] == "v3.0.0":
        from .reference_registry_v3 import artifact, HASHES, DISPATCH

    if registry is None:
        raise ValueError("reference.registry_missing")
    if manifests is None or set(manifests) != {"candidate", "meta"}:
        raise ValueError("reference.manifest_missing")
    if (
        policy.document["version"] == "v3.0.0"
        and isinstance(registry, dict)
        and isinstance(registry.get("raw"), str)
        and registry.get("sha256") == sha256(registry["raw"].encode())
        and registry.get("document") == json.loads(registry["raw"])
        and registry["document"].get("version") in {"1.0.0", "2.0.0"}
    ):
        raise ValueError("reference.profile_or_version_mismatch")

    def checked(wrapper, name, reason):
        if (
            not isinstance(wrapper, dict)
            or wrapper.get("sha256") != sha256(wrapper["raw"].encode())
            or wrapper["sha256"] != HASHES[name]
            or wrapper["raw"] != artifact(name)["raw"]
            or wrapper.get("document") != json.loads(wrapper["raw"])
        ):
            raise ValueError(reason)
        return wrapper["document"]

    doc = checked(
        registry,
        "predeclared_reference_registry.json",
        "reference.registry_sha_mismatch",
    )
    anchor = registry.get("platform_anchor")
    if anchor != artifact("platform-anchor.json")["document"]:
        raise ValueError("reference.platform_anchor_missing_or_mismatch")
    if first_performance_at is not None:
        if datetime.fromisoformat(
            anchor["created_at"].replace("Z", "+00:00")
        ) >= datetime.fromisoformat(first_performance_at.replace("Z", "+00:00")):
            raise ValueError("reference.registration_not_preperformance")
    bindings = doc["bindings"]
    if (
        bindings["interface_to_consume_sha256"] != policy.raw_sha256
        or bindings["prereg_sha256"] != policy.binding["prereg_sha256"]
        or bindings["common_profile_sha256"] != policy.binding["common_profile_sha256"]
    ):
        raise ValueError("reference.profile_or_version_mismatch")
    for role in ("candidate", "meta"):
        wrapper = manifests[role]
        payload = json.loads(wrapper["raw"])
        expected_members = {m for m, (r, _) in DISPATCH.items() if r == role}
        if (
            {m["member_id"] for m in payload["members"]} != expected_members
            or len(payload["members"]) != len(expected_members)
            or payload["manifest_role"] != role + "_reference_manifest"
        ):
            raise ValueError("reference.member_not_registered_or_incomplete")
        checked(
            wrapper,
            role + "_reference_manifest.json",
            "reference.manifest_sha_mismatch",
        )
        if payload["common_contract"]["bindings"] != bindings:
            raise ValueError("reference.profile_or_version_mismatch")
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
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
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
        m for layer in doc["definition_manifests"] for m in layer["member_ids"]
    )
    run = f"reference/{registry['sha256']}/{fold_id}"
    attempts = [run + "/" + m for m in members]
    ledger.declare_family(
        run,
        attempts,
        basis=policy.document["N"]["DSR_SR_basis"],
        authority_source={
            "reference": doc["issue_id"],
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

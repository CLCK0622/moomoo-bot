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
        "execution_receipts.input_data",
        "execution_receipts.input_guard",
        "execution_receipts.input_reader",
        "execution_receipts.reference_result",
        "execution_receipts.replay_guard",
        "reference_execution",
        "conventions",
        "contract",
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
    "execution_receipts.input_data": {
        "hashlib",
        "json",
        "math",
        "reference_validation",
    },
    "execution_receipts.input_guard": {"os", "sys", "pathlib"},
    "execution_receipts.input_reader": {"hashlib", "json", "pathlib", "input_data"},
}


def static_proof():
    graph, sources, reads = {}, {}, []
    extension = {
        "execution_receipts.input_data",
        "execution_receipts.input_guard",
        "execution_receipts.input_reader",
        "execution_receipts.reference_result",
        "execution_receipts.replay_guard",
        "reference_execution",
        "conventions",
        "contract",
    }
    for name, allowed in MODULES.items():
        raw = (Path(__file__).parent / (name.replace(".", "/") + ".py")).read_bytes()
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
                    "read_text",
                    "write_text",
                    "write_bytes",
                    "unlink",
                    "rename",
                }:
                    raise ValueError("reference.static_call_forbidden")
                if call == "read_bytes":
                    if name not in {
                        "reference_inputs",
                        "execution_receipts.input_reader",
                    }:
                        raise ValueError("reference.static_reader_forbidden")
                    reads.append(
                        {
                            "module": name,
                            "line": node.lineno,
                            "roles": (
                                ["panel", "benchmark", "profile"]
                                if name == "reference_inputs"
                                else ["raw", "rights", "adv", "cash"]
                            ),
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
            if name == "reference_producer_v3":
                entry = next(
                    n
                    for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "execution_main"
                )
                result_entry = next(
                    n
                    for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "result_main"
                )
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module in extension:
                        if not any(
                            e.lineno < node.lineno <= e.end_lineno
                            for e in (entry, result_entry)
                        ):
                            raise ValueError("reference.execution_import_outside_entry")
                calls = {
                    n.func.id: n.lineno
                    for n in ast.walk(entry)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                }
                if calls.get("install_execution", 10**9) >= calls.get(
                    "read_execution", -1
                ):
                    raise ValueError("reference.audit_hook_must_precede_data_reads")
    return {
        # Keep the original preparation entry's graph separately named. The
        # complete module graph and the new dispatch graph are also published;
        # no source bytes or source identities are excluded from the proof.
        "import_graph": {
            name: [dep for dep in deps if dep not in extension]
            for name, deps in graph.items()
            if name not in extension
        },
        "module_import_graph": graph,
        "execution_preparation_import_graph": {
            name: [
                dep
                for dep in deps
                if dep
                not in {
                    "execution_receipts.reference_result",
                    "execution_receipts.replay_guard",
                    "reference_execution",
                    "conventions",
                    "contract",
                }
            ]
            for name, deps in graph.items()
            if name
            in {
                "execution_receipts.input_data",
                "execution_receipts.input_guard",
                "execution_receipts.input_reader",
                "reference_producer_v3",
            }
        },
        "execution_result_import_graph": {
            "reference_producer_v3": [
                dep
                for dep in graph["reference_producer_v3"]
                if dep
                in {
                    "execution_receipts.input_data",
                    "execution_receipts.reference_result",
                    "execution_receipts.replay_guard",
                    "reference_execution",
                    "conventions",
                    "contract",
                }
            ]
        },
        "source_files": sources,
        "reader_sites": [r for r in reads if r["module"] == "reference_inputs"],
        "execution_preparation_reader_sites": [
            r for r in reads if r["module"] == "execution_receipts.input_reader"
        ],
        "source_sha256": digest(sources),
        "read_whitelist": {
            "panel": "panel.json",
            "benchmark": "benchmark.json",
            "profile": "profile.json",
        },
        "execution_preparation_read_whitelist": {
            "raw": "raw.json",
            "rights": "rights.json",
            "adv": "adv.json",
            "cash": "cash.json",
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


# Separate C09/C10 segment: these names never become members of the old
# preparation import_graph/reader_sites. Exact tokens, no prefix matching.
EXECUTION_MODULES = {
    "execution_receipts.input_run": {
        "copy",
        "json",
        "weakref",
        "contract",
        "input_envelope",
    },
    "execution_receipts.input_envelope": {
        "copy",
        "datetime",
        "contract",
        "noncash_v3",
        "reference_profile_v301",
        "reference_v3_scope",
    },
    "execution_receipts.input_data": {
        "hashlib",
        "json",
        "math",
        "reference_validation",
    },
    "execution_receipts.input_reader": {"hashlib", "json", "pathlib", "input_data"},
    "execution_receipts.input_guard": {"os", "sys", "pathlib"},
    "execution_receipts.n_binding": {
        "copy",
        "gzip",
        "pathlib",
        "authority_host",
        "authority_ledger",
        "contract",
        "reception_schema",
        "reception_v2",
        "reference_definition_v301",
        "reference_profile_v301",
        "reference_registry_v3",
        "g14",
    },
    "execution_receipts.g14": {"pathlib", "contract", "reception_schema"},
    "reference_execution": {
        "copy",
        "contract",
        "execution_accounting",
        "execution_candidate",
        "execution_returns",
        "execution_risk_history",
        "execution_startup",
        "reference_definition_v301",
        "reference_profile_v301",
        "execution_receipts.reference_result",
    },
    "execution_receipts.reference_result": {
        "copy",
        "json",
        "weakref",
        "contract",
        "execution_accounting",
        "execution_projection",
        "execution_returns",
        "execution_risk",
        "reference_profile_v301",
        "reference_execution",
    },
    "execution_receipts.replay_guard": {
        "hashlib",
        "datetime",
        "os",
        "sys",
        "pathlib",
        "replay_files",
        "execution_state",
        "execution_exposure",
        "lineage_schema",
        "event_quarantine",
        "fee_model",
    },
    "execution_receipts.replay_files": set(),
}

EXECUTION_FIXED_READS = (
    (
        "execution_receipts.n_binding",
        "EVO883-EXECCL-v29-archive-acceptance-v1.json",
        "ffa8176e788b69bc4df60577d96afe6d8532d4ecf41633d39a53deb959495e01",
    ),
    (
        "execution_receipts.n_binding",
        "EVO891-B-ledger-v29.jsonl.gz",
        "0aa61627abde7693fd2ad9087b2d4a2b076438378620b987e14db7dfa3372ad8",
    ),
    (
        "execution_receipts.g14",
        "EVO883-G14-P1-adopted-protocol-v1.0.0.json",
        "68200926a94cc672e7f0e47c14cc6473b68920576a7ade1028c07fb5c168334d",
    ),
)


def execution_proof():
    """Inspect the new orchestration/result branch independently of old proof.

    Numeric and authority readers stay in the existing C13 proof, rather than
    silently expanding the old preparation's three-file guarantee.
    """
    graph, sources, readers, fixed_seen, trees = {}, {}, [], set(), {}
    forbidden = {
        "open",
        "read_text",
        "write_bytes",
        "write_text",
        "exec",
        "eval",
        "compile",
        "__import__",
        "unlink",
        "rename",
    }
    for name, allowed in EXECUTION_MODULES.items():
        raw = (Path(__file__).parent / (name.replace(".", "/") + ".py")).read_bytes()
        tree = ast.parse(raw)
        trees[name] = tree
        imports = set()
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
            if (
                name == "execution_receipts.reference_result"
                and isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                expected = {"_ISSUER": "object()", "_OWNED": "WeakKeyDictionary()"}
                if ast.unparse(statement.value) == expected.get(
                    statement.targets[0].id
                ):
                    continue
            if (
                name == "execution_receipts.input_run"
                and isinstance(statement, ast.Assign)
                and ast.unparse(statement) == "_RUNS = WeakKeyDictionary()"
            ):
                continue
            if isinstance(statement, ast.Assign):
                try:
                    ast.literal_eval(statement.value)
                    continue
                except (TypeError, ValueError):
                    pass
            raise ValueError("reference.execution_import_time_effect_forbidden")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    imports.update(n.name for n in node.names)
                else:
                    imports.add(node.module)
            elif isinstance(node, ast.Call):
                call = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if call in forbidden:
                    raise ValueError(
                        "reference.execution_reader_or_dynamic_call_forbidden"
                    )
                if call == "read_bytes":
                    expr = node.func.value
                    if (
                        name == "execution_receipts.replay_guard"
                        and ast.unparse(expr) == "path"
                    ):
                        readers.append(
                            dict(
                                module=name,
                                line=node.lineno,
                                identity="host static proof's exact source/protocol file map, before stdin; no economic file path",
                            )
                        )
                    elif (
                        name == "execution_receipts.input_reader"
                        and ast.unparse(expr) == "paths[role]"
                    ):
                        loops = [
                            n
                            for n in ast.walk(tree)
                            if isinstance(n, ast.For)
                            and isinstance(n.target, ast.Name)
                            and n.target.id == "role"
                        ]
                        if len(loops) != 2 or any(
                            ast.literal_eval(n.iter) != ("raw", "rights", "adv", "cash")
                            for n in loops
                        ):
                            raise ValueError(
                                "reference.execution_input_file_not_registered"
                            )
                        assigns = {
                            ast.unparse(n)
                            for n in ast.walk(tree)
                            if isinstance(n, ast.Assign)
                        }
                        if (
                            "path = root / (role + '.json')" not in assigns
                            or "paths[role] = path" not in assigns
                        ):
                            raise ValueError(
                                "reference.execution_input_file_not_registered"
                            )
                        readers.append(
                            dict(
                                module=name,
                                line=node.lineno,
                                files=[
                                    "raw.json",
                                    "rights.json",
                                    "adv.json",
                                    "cash.json",
                                ],
                                identity="original file SHA in immutable host preparation, before JSON/value parsing",
                            )
                        )
                    elif (
                        isinstance(expr, ast.BinOp)
                        and isinstance(expr.op, ast.Div)
                        and isinstance(expr.right, ast.Constant)
                    ):
                        match = next(
                            (
                                r
                                for r in EXECUTION_FIXED_READS
                                if r[:2] == (name, expr.right.value)
                            ),
                            None,
                        )
                        if match is None or match in fixed_seen:
                            raise ValueError(
                                "reference.execution_fixed_file_not_registered"
                            )
                        if (
                            name == "execution_receipts.n_binding"
                            and ast.unparse(expr.left) != "root"
                        ):
                            raise ValueError(
                                "reference.execution_fixed_file_not_registered"
                            )
                        if (
                            name == "execution_receipts.g14"
                            and ast.unparse(expr.left)
                            != "Path(__file__).parent / 'contracts'"
                        ):
                            raise ValueError(
                                "reference.execution_fixed_file_not_registered"
                            )
                        fixed_seen.add(match)
                        readers.append(
                            dict(
                                module=name,
                                line=node.lineno,
                                path="execution_receipts/contracts/" + match[1],
                                sha256=match[2],
                            )
                        )
                    else:
                        raise ValueError(
                            "reference.execution_reader_or_dynamic_call_forbidden"
                        )
        if not imports <= allowed:
            raise ValueError("reference.execution_static_import_not_whitelisted")
        graph[name] = sorted(imports)
        sources[name] = sha256(raw)
    if fixed_seen != set(EXECUTION_FIXED_READS) or len(readers) != 5:
        raise ValueError("reference.execution_registered_reader_set_changed")
    for _, filename, expected in EXECUTION_FIXED_READS:
        raw = (
            Path(__file__).parent / "execution_receipts" / "contracts" / filename
        ).read_bytes()
        if sha256(raw) != expected:
            raise ValueError("reference.execution_fixed_file_identity_mismatch")
    table = {
        n.targets[0].id: ast.literal_eval(n.value)
        for n in trees["execution_receipts.replay_files"].body
        if isinstance(n, ast.Assign)
    }
    replay_files = dict(table["REPLAY_FIXED_FILES"])
    root = Path(__file__).parent
    for name in table["REPLAY_SOURCE_FILES"]:
        if (
            type(name) is not str
            or "/" in name
            or not name.endswith(".py")
            or name in replay_files
        ):
            raise ValueError("reference.replay_source_file_not_registered")
        replay_files[name] = sha256((root / name).read_bytes())
    for name, expected in table["REPLAY_FIXED_FILES"].items():
        if sha256((root / name).read_bytes()) != expected:
            raise ValueError("reference.replay_fixed_file_identity_mismatch")
    # Entrypoint ordering is structural, not a claim inferred from test success.
    producer = ast.parse(
        (Path(__file__).parent / "reference_producer_v3.py").read_bytes()
    )
    entry = next(
        n
        for n in producer.body
        if isinstance(n, ast.FunctionDef) and n.name == "result_main"
    )
    calls = {
        n.func.id: n.lineno
        for n in ast.walk(entry)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    if calls.get("install_result", 10**9) >= calls.get("input", -1):
        raise ValueError("reference.result_guard_must_precede_input")
    return dict(
        schema="EVO884.ReferenceExecutionProof/v1",
        import_graph=graph,
        import_whitelist={k: sorted(v) for k, v in EXECUTION_MODULES.items()},
        source_files=sources,
        source_sha256=digest(sources),
        reader_sites=readers,
        replay_file_sha256=replay_files,
        worker_data_files=[],
        worker_economic_file_roles=[],
        worker_execution_role="reference_diagnostic_execution",
        replay_compile_sources=table["REPLAY_COMPILE_SOURCES"],
        guard_before_stdin=True,
        seal_status="seal_pending",
        scope="owned diagnostic orchestration and isolated same-engine replay; source authentication and formal runtime are separate",
    )


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

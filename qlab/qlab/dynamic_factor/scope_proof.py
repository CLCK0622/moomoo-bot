"""Static import/guard/read-scope receipt for owned trusted strategy interfaces."""

import ast
from pathlib import Path

from .contract import digest, sha256
from .input_scope import ROLES

# Role gates must dominate each inspected consumer's data work. Wrapped tools
# guard at the first statement of their try, before calculate() is invoked.
GATES = {
    "features": ("folds", "_features"),
    "qqq_labels": ("folds", "_run_walk_forward_unbound"),
    "calibration": ("execution", "calibrate_gain"),
    "admission": ("pipeline", "select_pool"),
    "reference": ("reference_inputs", "read_inputs"),
    "holdings_cash": ("valuation", "integer_cash_valuation"),
    "orders": ("execution", "_tool"),
}

IMPORTS = {
    "execution": {
        "__future__",
        "contract",
        "conventions",
        "fee_model",
        "fees",
        "input_scope",
        "isolation",
        "state_v2",
        "json",
        "math",
        "pipeline",
        "re",
    },
    "folds": {
        "__future__",
        "continuity",
        "contract",
        "conventions",
        "dataclasses",
        "fees",
        "fold_split",
        "input_scope",
        "json",
        "pipeline",
        "validation",
    },
    "pipeline": {
        "__future__",
        "contract",
        "conventions",
        "copy",
        "dsr_v0",
        "execution",
        "fees",
        "input_scope",
        "isolation",
        "json",
        "math",
        "pathlib",
        "re",
        "reference_registry",
        "statistics",
    },
    "reference_inputs": {"hashlib", "input_scope", "json", "pathlib"},
    "valuation": {
        "__future__",
        "contract",
        "conventions",
        "csv",
        "fees",
        "input_disposition",
        "input_scope",
        "io",
        "math",
    },
    "scope_reader": {"contract", "input_scope", "json", "pathlib"},
    "input_scope": set(),
    "pending": {"__future__", "contract", "execution", "input_scope", "pipeline"},
    "validation": {
        "__future__",
        "contract",
        "conventions",
        "datetime",
        "fees",
        "input_disposition",
        "scope_proof",
        "valuation",
    },
    "continuity": {
        "authority_ledger",
        "contract",
        "conventions",
        "copy",
        "fees",
        "input_scope",
        "input_disposition",
        "state_v2",
    },
    "isolation": {
        "copy",
        "datetime",
        "contract",
        "conventions",
        "fees",
        "math",
        "input_scope",
    },
    "state_v2": {"copy", "contract", "conventions", "fees", "input_scope"},
    "scope_proof": {
        "ast",
        "contract",
        "input_disposition",
        "input_scope",
        "json",
        "pathlib",
        "reference_check",
    },
}


def b2_isolation_proof(policy):
    from .reference_check import static_proof
    from .input_disposition import HASHES, sources as disposition_sources

    disposition_sources()

    graph, sources, gates, readers = {}, {}, {}, []
    file_reads = {}
    root = Path(__file__).parent
    for name in sorted(IMPORTS):
        raw = (root / (name + ".py")).read_bytes()
        sources[name + ".py"] = sha256(raw)
        tree = ast.parse(raw)
        graph[name] = sorted(
            {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            | {
                a.name
                for n in ast.walk(tree)
                if isinstance(n, ast.Import)
                for a in n.names
            }
        )
        if not set(graph[name]).issubset(IMPORTS[name]):
            raise ValueError("scope.static_import_not_whitelisted")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("open", "eval", "exec", "__import__", "compile")
            ):
                raise ValueError("scope.dynamic_reader_or_code_forbidden")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in (
                    "open",
                    "read_text",
                    "write_text",
                    "write_bytes",
                    "glob",
                    "rglob",
                ):
                    raise ValueError("scope.file_access_not_whitelisted")
                if node.func.attr == "read_bytes":
                    file_reads[name] = file_reads.get(name, 0) + 1
        for role, (module, function) in GATES.items():
            if module != name:
                continue
            fn = next(
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == function
            )
            body = (
                fn.body[1:]
                if isinstance(fn.body[0], ast.Expr)
                and isinstance(fn.body[0].value, ast.Constant)
                and isinstance(fn.body[0].value.value, str)
                else fn.body
            )
            if function in ("integer_cash_valuation", "_tool"):
                body = next(n.body for n in body if isinstance(n, ast.Try))
            first = body[0]
            if not (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Name)
                and first.value.func.id == "reject_b2_inputs"
                and isinstance(first.value.args[-1], ast.Constant)
                and first.value.args[-1].value == role
            ):
                raise ValueError("scope.guard_does_not_dominate_consumer")
            gates[role] = {
                "module": module,
                "function": function,
                "guard_line": first.lineno,
            }
        if name in ("reference_inputs", "scope_reader"):
            for n in ast.walk(tree):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "read_bytes"
                ):
                    readers.append({"module": name, "line": n.lineno})
    if set(gates) != set(ROLES) or len(readers) != 2:
        raise ValueError("scope.reader_or_role_set_changed")
    if file_reads != {
        "execution": 2,
        "pipeline": 1,
        "reference_inputs": 1,
        "scope_proof": 1,
        "scope_reader": 1,
        "valuation": 1,
    }:
        raise ValueError("scope.file_access_not_whitelisted")
    ref = static_proof()
    return {
        "schema": "EVO884.B2-isolation-proof/v1",
        "scope_ruling_sha256": HASHES["EVO883-EVO886-minimum-scope-ruling-v1.json"],
        **policy.binding,
        "source_files": sources,
        "source_sha256": digest(sources),
        "import_graph": graph,
        "import_whitelist": {k: sorted(v) for k, v in IMPORTS.items()},
        "guarded_consumers": gates,
        "market_reader_sites": readers,
        "strategy_market_symbol_whitelist": list(policy.profile["universe"])
        + [policy.profile["portfolio"]["base_ticker"]],
        "strategy_market_file_whitelist": "<frozen_symbol>.json, matching symbol header and SHA, exact supplied frozen date vector; no link/alias/path expansion",
        "reference_file_whitelist": ref["read_whitelist"],
        "reference_benchmark_symbol": "QQQ",
        "non_market_read_whitelist": {
            "execution": ["fee_params_x2.json", "fee_schedule.json"],
            "pipeline": [
                "predeclared_reference_registry.json",
                "candidate_reference_manifest.json",
                "meta_reference_manifest.json",
            ],
            "valuation": ["qqq-events-v1.csv"],
            "scope_proof": ["current pinned Python sources"],
        },
        "B2_series_capability_for_strategy_roles": False,
        "B2_only_readout_entry": "valuation.benchmark_valuation(symbol=VTI)",
        "scope": "Pinned owned Python entrypoints and declared source/header identities; caller adapters and independent market-source correctness require separate acceptance. No arbitrary native-code sandbox claim.",
        "runtime_consumable": False,
        "certifiable": False,
    }


def b2_manifest_check(manifest, policy):
    """An unavailable B2 entry is complete metadata, never available market data."""
    from .contract import is_sha
    from .input_disposition import sources
    import json

    ruling = json.loads(sources()["EVO883-EVO886-minimum-scope-ruling-v1.json"])
    expected_interface = (
        policy.document["interface_correction"]["previous_interface_sha256"]
        if policy.document["version"] == "v2.0.0"
        else policy.raw_sha256
    )
    if ruling["interface_sha256"] != expected_interface:
        raise ValueError("scope.ruling_identity_mismatch")
    proof = b2_isolation_proof(policy)
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "unavailable"
        or not isinstance(manifest.get("reason"), str)
        or not manifest["reason"]
        or not isinstance(manifest.get("missing_fields"), list)
        or not manifest["missing_fields"]
        or not is_sha(manifest.get("source_sha256"))
        or manifest.get("dates") != list(policy.calendar)
        or manifest.get("calendar_sha256") != digest(list(policy.calendar))
        or manifest.get("affected_scope") != ["B2"]
        or manifest.get("strategy_dependencies") != {r: [] for r in ROLES}
        or manifest.get("isolation_source_sha256") != proof["source_sha256"]
        or manifest.get("use_suffix")
        or manifest.get("fallback")
    ):
        raise ValueError("scope.B2_isolation_manifest_missing_or_invalid")
    return {
        "value": None,
        "available": False,
        "reason": manifest["reason"],
        "input_binding_present": True,
        "all_dates_retained": True,
        "source_sha256": manifest["source_sha256"],
        "isolation_source_sha256": proof["source_sha256"],
    }

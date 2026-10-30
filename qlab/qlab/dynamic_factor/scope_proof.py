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
        "noncash_v3",
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
        "reference_registry_v3",
        "statistics",
    },
    "reference_inputs": {"hashlib", "input_scope", "json", "pathlib"},
    "valuation": {
        "noncash_v3",
        "__future__",
        "contract",
        "conventions",
        "csv",
        "fees",
        "input_disposition",
        "input_scope",
        "io",
        "math",
        "k5",
    },
    "scope_reader": {"contract", "input_scope", "json", "pathlib"},
    "input_scope": set(),
    "noncash_v3": {
        "copy",
        "datetime",
        "contract",
        "conventions",
        "fees",
        "state_v2",
        "catalog_v21",
        "catalog_members",
    },
    "catalog_members": set(),
    "catalog_v21": {"csv", "io", "json", "contract", "conventions"},
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
        "k5",
    },
    "isolation": {
        "noncash_v3",
        "event_quarantine",
        "copy",
        "datetime",
        "contract",
        "conventions",
        "fees",
        "math",
        "input_scope",
    },
    "state_v2": {"copy", "contract", "conventions", "fees", "input_scope"},
    "k5": {
        "noncash_v3",
        "csv",
        "decimal",
        "io",
        "json",
        "contract",
        "conventions",
        "fees",
        "input_scope",
        "isolation",
    },
    "scope_proof": {
        "conventions",
        "noncash_v3",
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
        "catalog_v21": 1,
        "execution": 2,
        "pipeline": 1,
        "reference_inputs": 1,
        "scope_proof": 2,
        "scope_reader": 1,
        "valuation": 1,
        "k5": 2,
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
        "k5_scoped_quote_read_whitelist": [
            "k5/S2-field-receipt-v1.json",
            "k5/VSNT-open-close-none.csv",
        ],
        "reference_benchmark_symbol": "QQQ",
        "non_market_read_whitelist": {
            "catalog_v21": [
                "catalog-v21/EVO893-B-noncash-catalog-v21.csv",
                "catalog-v21/EVO893-B-CMI-guard-v21.json",
                "catalog-v21/EVO883-v21-final-receipt.json",
            ],
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


def noncash_isolation_proof(policy):
    """Inspect owned economic boundaries; this does not attest a real account."""
    from .noncash_v3 import (
        ROUTES,
        CONSUMERS,
        actor_ids,
        ACCEPTED_CATALOG_SHA256,
        CATALOG_REASON,
    )

    root = Path(__file__).parent
    names = (
        "noncash_v3",
        "catalog_v21",
        "catalog_members",
        "reference_noncash",
        "isolation",
        "execution",
        "valuation",
        "k5",
        "folds",
    )
    raw_sources = {name: (root / (name + ".py")).read_bytes() for name in names}
    trees = {name: ast.parse(raw) for name, raw in raw_sources.items()}

    def function(module, name):
        return next(
            n
            for n in trees[module].body
            if isinstance(n, ast.FunctionDef) and n.name == name
        )

    def calls(node, name):
        return sorted(
            n.lineno
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == name
        )

    numeric = function("noncash_v3", "guarded_value")
    guards = calls(numeric, "assert_consumer_symbols")
    readers = calls(numeric, "reader")
    if len(guards) != 1 or len(readers) != 1 or guards[0] >= readers[0]:
        raise ValueError("B.static_numeric_guard_not_dominant")
    economic = function("noncash_v3", "economic_values")
    if min(calls(economic, "assert_consumer_symbols"), default=10**9) >= min(
        calls(economic, "guarded_value"), default=-1
    ):
        raise ValueError("B.static_batch_guard_missing")
    # A pure injected reader is the only numeric boundary in this module.
    forbidden = {
        "open",
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "glob",
        "rglob",
        "eval",
        "exec",
        "__import__",
    }
    for n in ast.walk(trees["noncash_v3"]):
        if isinstance(n, ast.Call):
            name = (
                n.func.id
                if isinstance(n.func, ast.Name)
                else n.func.attr
                if isinstance(n.func, ast.Attribute)
                else ""
            )
            if name in forbidden:
                raise ValueError("B.static_unregistered_reader")
    acquisition = function("noncash_v3", "acquisition_check")
    if (
        len(calls(acquisition, "zero_exposure")) != 2
        or not calls(acquisition, "zero_origin")
        or not calls(acquisition, "checked_guard")
    ):
        raise ValueError("B.static_acquisition_induction_missing")
    calibration = function("execution", "_v2_calibration_rows")
    voluntary = function("execution", "voluntary_trade_gate")
    valuation = function("valuation", "integer_cash_valuation")
    for node in (calibration, voluntary, valuation):
        if not calls(node, "assert_consumer_symbols"):
            raise ValueError("B.static_consumer_connection_missing")
    factor_cash = function("valuation", "factor_cash_valuation")
    if not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "integer_cash_valuation"
        and any(
            k.arg == "factor_scope"
            and isinstance(k.value, ast.Constant)
            and k.value.value is True
            for k in n.keywords
        )
        for n in ast.walk(factor_cash)
    ):
        raise ValueError("B.static_factor_cash_scope_not_bound")
    marks = [
        n.lineno
        for n in ast.walk(valuation)
        if isinstance(n, ast.Subscript)
        and isinstance(n.slice, ast.Constant)
        and n.slice.value == "marks"
    ]
    if min(calls(valuation, "assert_consumer_symbols")) >= min(marks, default=-1):
        raise ValueError("B.static_valuation_read_precedes_guard")
    quote = function("k5", "vsnt_quote")
    raises = [n.lineno for n in ast.walk(quote) if isinstance(n, ast.Raise)]
    reads = [
        n.lineno
        for n in ast.walk(quote)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "read_bytes"
    ]
    if not raises or min(raises) >= min(reads, default=-1):
        raise ValueError("B.static_v3_legacy_reader_not_closed")
    files = {n + ".py": sha256(b) for n, b in raw_sources.items()}
    payload = dict(
        schema="EVO900.factor-arm-noncash-static-proof/v3",
        source_files=files,
        source_sha256=digest(files),
        actor_ids=list(actor_ids(policy)),
        acquisition_routes=sorted(ROUTES),
        economic_consumer_roles=sorted(CONSUMERS),
        numeric_guard_line=guards[0],
        injected_reader_line=readers[0],
        B_catalog_sha256=ACCEPTED_CATALOG_SHA256,
        B_catalog_reason=CATALOG_REASON,
        scope="Owned factor and virtual-monitor input boundaries, supplied complete source states, and trusted callbacks; not an arbitrary Python OS sandbox or real-account attestation.",
        reference_producer_proof_completed=False,
        reference_producer_separate_mechanism_proof_available=True,
        reference_producer_real_runtime_proven=False,
        factor_cash_entrypoint="factor_cash_valuation",
        generic_accounting_is_factor_proof=False,
        real_origin_proofs=None,
        runtime_consumable=False,
        certifiable=False,
        **policy.binding,
    )
    return dict(payload, static_proof_sha256=digest(payload))


def b2_manifest_check(manifest, policy):
    """An unavailable B2 entry is complete metadata, never available market data."""
    from .contract import is_sha
    from .conventions import FIXTURES, load_conventions
    from .input_disposition import sources
    import json

    ruling = json.loads(sources()["EVO883-EVO886-minimum-scope-ruling-v1.json"])
    expected_interface = (
        load_conventions(FIXTURES / "conventions-v1.0.1.json").raw_sha256
        if policy.document["version"] in ("v2.0.0", "v3.0.0")
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

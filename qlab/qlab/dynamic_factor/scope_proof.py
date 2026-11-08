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
        "execution_candidate",
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
        "execution_candidate",
        "arm_n",
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
        "b_release_context",
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
    "b_release_context": {
        "pathlib",
        "catalog_v21",
        "csv",
        "datetime",
        "io",
        "json",
        "weakref",
        "contract",
    },
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
        "authority_host",
        "historical_authority",
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
    "execution_accounting": {
        "contract",
        "copy",
        "decimal",
        "execution_amounts",
        "execution_cash",
        "execution_closure",
        "execution_numbers",
        "execution_projection",
        "execution_risk",
        "execution_startup",
        "fees",
        "fractions",
        "functools",
        "input_scope",
        "json",
        "noncash_v3",
        "reference_validation",
        "threading",
    },
    "execution_amounts": {
        "decimal",
        "execution",
        "execution_closure",
        "execution_numbers",
        "fee_model",
        "fees",
        "fractions",
        "input_scope",
        "noncash_v3",
        "re",
    },
    "execution_candidate": {
        "contract",
        "copy",
        "decimal",
        "execution",
        "execution_accounting",
        "execution_amounts",
        "execution_closure",
        "execution_numbers",
        "execution_projection",
        "execution_returns",
        "execution_risk",
        "execution_risk_history",
        "execution_signals",
        "fractions",
        "input_scope",
        "isolation",
        "json",
        "noncash_v3",
        "reference_validation",
        "threading",
    },
    "execution_cash": {
        "contract",
        "copy",
        "datetime",
        "event_quarantine",
        "execution_exposure",
        "execution_numbers",
        "execution_state",
        "input_disposition",
        "input_scope",
        "json",
        "lineage_schema",
        "noncash_v3",
        "reference_validation",
    },
    "execution_clock": {
        "contract",
        "copy",
        "json",
        "reference_definition_v301",
    },
    "execution_closure": {
        "contract",
        "copy",
        "decimal",
        "json",
        "reference_definition_v301",
    },
    "execution_exposure": set(),
    "execution_numbers": {
        "decimal",
        "fractions",
        "re",
    },
    "execution_projection": {
        "contract",
        "copy",
        "decimal",
        "execution_amounts",
        "execution_closure",
        "execution_risk",
        "fractions",
        "input_scope",
        "isolation",
        "json",
        "noncash_v3",
    },
    "execution_returns": {
        "contract",
        "copy",
        "execution_accounting",
        "execution_closure",
        "execution_numbers",
        "fees",
        "fold_split",
        "fractions",
        "math",
        "pipeline",
    },
    "execution_risk": {
        "contract",
        "conventions",
        "copy",
        "decimal",
        "execution_cash",
        "execution_clock",
        "execution_closure",
        "execution_numbers",
        "execution_state",
        "fractions",
        "noncash_v3",
        "re",
        "reference_definition_v301",
    },
    "execution_risk_history": {
        "contract",
        "conventions",
        "copy",
        "execution_cash",
        "execution_clock",
        "execution_closure",
        "execution_numbers",
        "execution_risk",
        "execution_startup",
        "json",
        "noncash_v3",
        "reference_validation",
        "threading",
    },
    "execution_signals": {
        "contract",
        "copy",
        "execution_amounts",
        "execution_closure",
        "execution_risk",
        "fractions",
        "math",
        "noncash_v3",
        "threading",
    },
    "execution_startup": {
        "contract",
        "conventions",
        "copy",
        "execution",
        "execution_closure",
        "fees",
        "functools",
        "json",
        "math",
        "pipeline",
        "reference_definition_v301",
        "reference_profile_v301",
        "reference_validation",
        "threading",
    },
    "execution_state": {
        "fees",
        "state_v2",
    },
    "reference_definition_v301": {
        "contract",
        "json",
        "pathlib",
        "reference_registry_v3",
    },
    "reference_profile_v301": {
        "contract",
        "reference_definition_v301",
        "reference_registry_v3",
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


# C13's registered additions only. Existing helper reads remain under their
# original mechanisms; this table does not attest complete transitive coverage.
FIXED_READS = (
    (
        "execution_closure",
        "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.json",
        "7677b123fa2fe573343fad3fe3f43887c5f5d2c0fd7c12d9a1de8bc625162e1b",
    ),
    (
        "execution_closure",
        "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.md",
        "34f25ce19dcf8687f7068b62f751c83573a858997ab11fa0096794157f3a373f",
    ),
    (
        "execution_clock",
        "fixtures/execution-v3.0.1/EVO883-C06-CLOCK-adopted-protocol-v1.0.0.json",
        "8cd32345adb5ebe16cb9020687091532c46f803f046d6c1527eeedee41407a5a",
    ),
    (
        "reference_definition_v301",
        "fixtures/execution-v3.0.1/EVO883-D12-shared-execution-contract-v3.0.1.json",
        "f7a0623da88a7e2874ef5e372750ad04a1edca9796acc0c3fee02616f766a496",
    ),
    (
        "reference_definition_v301",
        "fixtures/execution-v3.0.1/EVO883-D12-common-profile-v3.0.1.json",
        "07b71b3fc59dc6dae1c96cadd3155622a18f4c4ad29b7c69b8f79c1455efc2d3",
    ),
    (
        "reference_definition_v301",
        "fixtures/execution-v3.0.1/EVO883-D12-addendum-v3.0.1.md",
        "f540dce44e00b7077a94d3155f55db5fdba700b7a48911ec03697724b8dfa8c9",
    ),
    (
        "reference_registry_v3",
        "fixtures/evo892-v3/candidate_reference_manifest.json",
        "bcce6f17f3515d66eb5b87569720740efb6eb70eca2d774a853be8e3cdecb4a4",
    ),
    (
        "reference_registry_v3",
        "fixtures/evo892-v3/predeclared_reference_registry.json",
        "f531d65a5ad54fc68a8be40bc25cbb3987d0aeedd4c2c345ed334b1599445c48",
    ),
    (
        "reference_registry_v3",
        "fixtures/evo892-v3/meta_reference_manifest.json",
        "964e9903e13bd618777f00652bad09272d7aa4ddbb3cec2c28371a8378002ae6",
    ),
    (
        "execution_accounting",
        "fixtures/fee_params_x1.json",
        "7e24f9e9b25802a7d4b50bd4b089a60d288b8f8f448ea92aac9482816b7ffdb2",
    ),
)

# B02 exact originals; separate from the unchanged C13 registrations above.
B_RELEASE_FIXED_READS = (
    (
        "b_release_context",
        "fixtures/catalog-v21/EVO893-B-noncash-catalog-v21.csv",
        "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
    ),
    (
        "b_release_context",
        "fixtures/catalog-v21/EVO893-B-CMI-guard-v21.json",
        "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
    ),
    (
        "b_release_context",
        "fixtures/catalog-v21/EVO883-v21-final-receipt.json",
        "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
    ),
)


# C1 exact package originals; the old B02/C13 tables remain unchanged.
B_RELEASE_ADAPTER_READS = (
    (
        "b_release_context",
        "b_release_originals/EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json",
        "ff5da6ef748d5f1fca592559e73656d5283e28ec9d279b65b3ac0fd5943069ff",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-EVO893-v10-ruling.json",
        "834bf9546dda93c3fb613833b59ac87842c2825b71c11bc09edc13608f5d42e4",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-S1-BRKB-field-receipt.json",
        "ff8dee166c469310b915f903a32164351647e61dd8340437ffa09b45da9e0442",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-S2-v14-field-receipt.json",
        "9b5fd1e87a2cae26df8a0c1a8ee9fbd880c07234e05a9253ff9886d4dcb7711f",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-S3-v12-final-receipt.json",
        "1df425a328539f4cddfe3d574feabc1b753fc0abe2ff15d318634aee7dff3836",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-S4-v11-receipt.json",
        "d44ce4e0b13d68a129f6aca0ad2187f459ea978f117510cc48d910fb8b44b11f",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-v10-engineering-scope-receipt.json",
        "4da26596777a62595664ba9b9e17480113f96ccbd2c1d0226df083ac2e7ecc0f",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-v20.1-final-receipt.json",
        "cdd7954a20102e1053f932fe559153b26336475afdb41b772004795708bf3c4e",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO883-v21-final-receipt.json",
        "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO893-B-CMI-guard-v21.json",
        "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO893-B-noncash-catalog-v21.csv",
        "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO938-B-runtime-release-P-v1.0.0.json",
        "4a4b24b0a6ee2b6b561d285fa6f3f9233960959500b6e02fc137c83ca31deae1",
    ),
    (
        "b_release_context",
        "b_release_originals/EVO938-B-runtime-release-R-v1.0.0.json",
        "68f06b15ded4cb1ec5219a5456a2e0f0f376cab54a9e3ac33aee653dacfa877c",
    ),
    (
        "b_release_context",
        "b_release_originals/annotation-platform-readback.json",
        "d25ba025d42fea6ad908566384f97f6fd1ed567eb1f4474bba46105e9aa77c81",
    ),
    (
        "b_release_context",
        "b_release_originals/publication-platform-readback.json",
        "f847be9a107b9293e134bfc4d9a03a3c3cb1eeb823f40991d7b8d28d1533455e",
    ),
)

# Anti-cycle: the trust-root SHA cannot enter code; the module SHA cannot be
# embedded in itself or this audit gate. Exactly these TWO path-only entries
# are authorized. A third requires approval from the original authority line.
B_RELEASE_PATH_ONLY_READS = (
    ("b_release_context", "b_release_originals/trust-root-platform-readback.json"),
    ("b_release_context", "b_release_context.py"),
)


def _b_release_adapter_scope(tree, audit_tree):
    """Exact call ASTs, fixed original loop, and self-read SHA-only use."""
    try:
        if len(B_RELEASE_PATH_ONLY_READS) != 2 or set(B_RELEASE_PATH_ONLY_READS) != {
            (
                "b_release_context",
                "b_release_originals/trust-root-platform-readback.json",
            ),
            ("b_release_context", "b_release_context.py"),
        }:
            raise ValueError
        fn = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_read_trusted_release"
        )
        if fn.args.args or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg:
            raise ValueError
        expected = ast.literal_eval(
            next(
                n.value
                for n in ast.walk(fn)
                if isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "original_sha256"
            )
        )
        rows = tuple(
            ("b_release_context", "b_release_originals/" + name, value)
            for name, value in expected.items()
        )
        if (
            len(rows) != 15
            or rows != B_RELEASE_ADAPTER_READS
            or any(
                type(value) is not str
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
                for value in expected.values()
            )
        ):
            raise ValueError
        reads = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "read_bytes"
        ]
        expressions = {
            "root": '(Path(__file__).parent / "b_release_originals" / "trust-root-platform-readback.json").read_bytes()',
            "self": "Path.read_bytes(Path(__file__))",
            "original": '(Path(__file__).parent / "b_release_originals" / name).read_bytes()',
        }
        if len(reads) != 3 or {ast.dump(n) for n in reads} != {
            ast.dump(ast.parse(expr, mode="eval").body) for expr in expressions.values()
        }:
            raise ValueError
        # In particular the self-read argument AST must be EXACTLY Path(__file__)
        # (not a literal, alias, env/request expression or runtime path test).
        # Scan the WHOLE module, including bindings outside the reader body.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id in {"globals", "setattr"}:
                    raise ValueError
                if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in {
                    "__file__",
                    "Path",
                    "compile",
                    "_read_trusted_release",
                }:
                    raise ValueError
            if isinstance(node, ast.Attribute):
                if node.attr in {"globals", "setattr", "__setattr__"}:
                    raise ValueError
                if node.attr == "__file__" and isinstance(
                    node.ctx, (ast.Store, ast.Del)
                ):
                    raise ValueError
            if isinstance(node, ast.Subscript) and isinstance(
                node.ctx, (ast.Store, ast.Del)
            ):
                if (
                    isinstance(node.slice, ast.Constant)
                    and node.slice.value == "__file__"
                ):
                    raise ValueError
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) and node.name in {"__file__", "Path", "compile"}:
                raise ValueError
            if isinstance(node, ast.arg) and node.arg in {
                "__file__",
                "Path",
                "compile",
            }:
                raise ValueError
            if isinstance(node, ast.ExceptHandler) and node.name in {
                "__file__",
                "Path",
                "compile",
            }:
                raise ValueError
            if isinstance(node, ast.alias) and (
                node.asname or node.name.split(".")[0]
            ) in {"__file__", "compile"}:
                raise ValueError
        imports = [
            n for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        if len(imports) != 1 or ast.dump(imports[0]) != ast.dump(
            ast.parse("from pathlib import Path").body[0]
        ):
            raise ValueError
        if (
            sum(
                isinstance(n, ast.alias) and (n.asname or n.name) == "Path"
                for n in ast.walk(tree)
            )
            != 1
        ):
            raise ValueError
        prelude = ast.parse(
            'try:\n    live_code = _read_trusted_release.__code__\n    if type(__file__) is not str or __file__ != live_code.co_filename:\n        _fail("acceptance_mismatch")\nexcept (NameError, AttributeError, TypeError) as exc:\n    raise ValueError("B.release_context_acceptance_mismatch") from exc\n'
        ).body
        binding = ast.parse(
            '# Only compile this one fixed self-read; never execute the compiled module.\ntry:\n    self_raw = Path.read_bytes(Path(__file__))\n    compiled_module = compile.__call__(\n        self_raw, live_code.co_filename, "exec", dont_inherit=True, optimize=-1\n    )\nexcept (OSError, SyntaxError, ValueError, TypeError) as exc:\n    raise ValueError("B.release_context_acceptance_mismatch") from exc\ncode_type = type(live_code)\n\ndef same_constant(left, right):\n    if type(left) is not type(right):\n        return False\n    if type(left) is code_type:\n        return same_code(left, right)\n    if type(left) is tuple:\n        return len(left) == len(right) and all(\n            same_constant(a, b) for a, b in zip(left, right)\n        )\n    return left == right\n\ndef same_code(left, right):\n    attributes = (\n        "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",\n        "co_stacksize", "co_flags", "co_code", "co_names", "co_varnames",\n        "co_freevars", "co_cellvars", "co_filename", "co_name", "co_firstlineno",\n    )\n    optional = ("co_lnotab", "co_linetable", "co_exceptiontable", "co_qualname")\n    return (\n        type(left) is type(right) is code_type\n        and all(getattr(left, key) == getattr(right, key) for key in attributes)\n        and all(\n            hasattr(left, key) == hasattr(right, key)\n            and (not hasattr(left, key) or getattr(left, key) == getattr(right, key))\n            for key in optional\n        )\n        and same_constant(left.co_consts, right.co_consts)\n    )\n\ncandidates = [\n    value for value in compiled_module.co_consts\n    if type(value) is code_type and value.co_name == "_read_trusted_release"\n]\nif len(candidates) != 1 or not same_code(candidates[0], live_code):\n    _fail("acceptance_mismatch")\nimplementation_id = sha256(self_raw)\n'
        ).body

        def exact_sequence(statements, expected):
            wanted = [ast.dump(n) for n in expected]
            actual = [ast.dump(n) for n in statements]
            return (
                sum(actual[i : i + len(wanted)] == wanted for i in range(len(actual)))
                == 1
            )

        if not exact_sequence(fn.body, prelude):
            raise ValueError
        containers = [n.body for n in ast.walk(fn) if isinstance(n, ast.Try)]
        if sum(exact_sequence(body, binding) for body in containers) != 1:
            raise ValueError
        compile_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "__call__"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "compile"
        ]
        expected_compile = ast.parse(
            'compile.__call__(self_raw, live_code.co_filename, "exec", dont_inherit=True, optimize=-1)',
            mode="eval",
        ).body
        if len(compile_calls) != 1 or ast.dump(compile_calls[0]) != ast.dump(
            expected_compile
        ):
            raise ValueError
        if (
            sum(isinstance(n, ast.Name) and n.id == "compile" for n in ast.walk(tree))
            != 1
        ):
            raise ValueError
        if (
            sum(
                isinstance(n, ast.Name)
                and n.id == "self_raw"
                and isinstance(n.ctx, ast.Load)
                for n in ast.walk(fn)
            )
            != 2
        ):
            raise ValueError
        # This additive fixed metadata read has its own exact AST registration.
        # Legacy direct read_bytes/compile guard and counts above stay untouched.
        audit_reads = [
            n
            for n in ast.walk(audit_tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "__call__"
            and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "read_bytes"
        ]
        expected_read = ast.parse(
            "Path.read_bytes.__call__(root / relative)", mode="eval"
        ).body
        if len(audit_reads) != 1 or ast.dump(audit_reads[0]) != ast.dump(expected_read):
            raise ValueError
        audit_fn = next(
            n
            for n in audit_tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "b2_isolation_proof"
        )
        audit_loop = ast.parse(
            'for _, relative, expected in B_RELEASE_ADAPTER_READS:\n    raw = Path.read_bytes.__call__(root / relative)\n    if sha256(raw) != expected:\n        raise ValueError("scope.file_access_not_whitelisted")'
        ).body[0]
        if sum(ast.dump(n) == ast.dump(audit_loop) for n in audit_fn.body) != 1:
            raise ValueError
        loops = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.For)
            and ast.dump(n.iter)
            == ast.dump(ast.parse("original_sha256.items()", mode="eval").body)
        ]
        if len(loops) != 1 or ast.dump(loops[0].target) != ast.dump(
            ast.parse("for name, expected in original_sha256.items(): pass")
            .body[0]
            .target
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as exc:
        raise ValueError("scope.file_access_not_whitelisted") from exc
    return {
        "sha256_reads": [dict(module=m, path=p, sha256=s) for m, p, s in rows],
        "path_only_reads": [
            dict(module=m, path=p) for m, p in B_RELEASE_PATH_ONLY_READS
        ],
        "exact_adapter_read_sites": 3,
        "self_read_argument": "Path(__file__)",
        "self_read_use": "compile-only live-code comparison, then sha256 -> implementation_id",
        "live_code_binding": True,
        "additional_fixed_audit_read_sites": 1,
        "additional_fixed_compile_sites": 1,
        "root_sha_in_code": False,
    }


# Bind the inspected helper bodies/roots as well as their call-site domain.
# Accounting is re-pinned for B step 3 propagation; the other four stay unchanged.
# Any byte drift, including a comment, fails;
# no basename, prefix or source-identity exception is introduced.
FIXED_READER_SOURCES = {
    "execution_closure.py": "998ef21c68825ab9254489f29b12095c8dc0d4b3f6f14e507e8fbea6808615ae",
    "execution_clock.py": "c1f9563c645110335cdbf006328b3cee4d1d8952d8433ffd5306b91d07e8ecf6",
    "reference_definition_v301.py": "95a51f2f5c5d3473254e247ac8d1b408c4f89c9253b3622ee2fe4d7941ef1a55",
    "reference_registry_v3.py": "90ff033cb06bbedce4315ec04bb7c84b8a300fdd133015db58a23b1f7fee997a",
    "execution_accounting.py": "f8101633e86d2ee42e75dd66793ae0e153f1454e38ce008cc10bd2d6611a5a4a",
}


FILENAME_READS = {
    "conventions": ["provenance.json", "provenance-v2.json", "provenance-v3.json"],
    "input_disposition": ["qqq-events-v1.csv"],
    "historical_authority": ["EVO891-B-ledger-v4.tip.json"],
}
# Source identity, not a SHA requirement on these five filename-only artifacts.
# These helpers retain their original read mechanisms; they are not additional
# IMPORTS entries or a claim to cover every read in their whole modules.
FILENAME_SOURCE_IDENTITIES = {
    "conventions": "4b98838d3fca24664470c1e2fb65921eefc3d93a7bfb9331e857d65f0205064a",
    "input_disposition": "515945c2ee3de0d8e9a1ec0087f8087b5750258d013ada6ed08060f50e872d65",
    "historical_authority": "fb401e78c115876d73f9f5a6cece6d7d820927c9cd1222dad49eca983629fcce",
}


def _filename_read_scope(trees, sources):
    for name, expected in FILENAME_SOURCE_IDENTITIES.items():
        if sources[name + ".py"] != expected:
            raise ValueError("scope.file_access_not_whitelisted")
    for module in ("conventions", "input_disposition"):
        names = {
            node.func.value.right.value
            for node in ast.walk(trees[module])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_bytes"
            and isinstance(node.func.value, ast.BinOp)
            and isinstance(node.func.value.op, ast.Div)
            and isinstance(node.func.value.left, ast.Name)
            and node.func.value.left.id == "FIXTURES"
            and isinstance(node.func.value.right, ast.Constant)
        }
        if not set(FILENAME_READS[module]) <= names:
            raise ValueError("scope.file_access_not_whitelisted")
    tree = trees["historical_authority"]
    stores = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "HISTORICAL_V4_WITNESS_INPUT"
        and isinstance(node.ctx, ast.Store)
    ]
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "HISTORICAL_V4_WITNESS_INPUT"
            for t in node.targets
        )
    ]
    expected = ast.parse(
        "HISTORICAL_V4_FIXTURES / 'EVO891-B-ledger-v4.tip.json'", mode="eval"
    ).body
    if (
        len(stores) != 1
        or len(assignments) != 1
        or ast.dump(assignments[0].value) != ast.dump(expected)
    ):
        raise ValueError("scope.file_access_not_whitelisted")
    return dict(
        registrations=FILENAME_READS,
        historical_witness=dict(
            constant="HISTORICAL_V4_WITNESS_INPUT",
            assignments=len(stores),
            literal_filename="EVO891-B-ledger-v4.tip.json",
            source_identity_bound=True,
            scope="historical diagnostic only",
        ),
        unverified_not_in_table=["R056", "R057", "R058", "R059", "R060"],
        guarantee="Pinned owned source and static assignments; no arbitrary host mutation sandbox claim",
    )


def _candidate_registry_scope(trees, sources):
    """Bound the reached artifact calls, not the generic function's HASHES.

    The candidate path reaches member_definition and solo_profile, then
    member_spec for the four literal DISPATCH members. registered_request is
    not an entry: its platform anchor and five other HASHES are not allowed.
    """

    def assignment(tree, name):
        return next(
            n.value
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        )

    def function(module, name):
        return next(
            n
            for n in trees[module].body
            if isinstance(n, ast.FunctionDef) and n.name == name
        )

    def artifact_calls(node):
        return [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "artifact"
        ]

    allowed = {
        path.rsplit("/", 1)[-1]
        for module, path, _ in FIXED_READS
        if module == "reference_registry_v3"
    }
    try:
        dispatch = ast.literal_eval(
            assignment(trees["reference_registry_v3"], "DISPATCH")
        )
        if dispatch != {
            "CREF-F1-L020": ("candidate", "F1-L020"),
            "CREF-F3-L020": ("candidate", "F3-L020"),
            "MREF-F2-L020": ("meta", "F2-L020"),
            "MREF-F4-L020": ("meta", "F4-L020"),
        }:
            raise ValueError
        direct = artifact_calls(
            function("reference_definition_v301", "member_definition")
        )
        indirect = artifact_calls(function("reference_registry_v3", "member_spec"))
        if (
            len(direct) != 1
            or len(indirect) != 1
            or len(direct[0].args) != 1
            or len(indirect[0].args) != 1
        ):
            raise ValueError
        names = {ast.literal_eval(direct[0].args[0])}
        expression = indirect[0].args[0]
        if isinstance(expression, ast.Constant) and type(expression.value) is str:
            names.add(expression.value)
        elif ast.dump(expression) == ast.dump(
            ast.parse("role + '_reference_manifest.json'", mode="eval").body
        ):
            names.update(
                role + "_reference_manifest.json" for role, _ in dispatch.values()
            )
        else:
            raise ValueError
        if names != allowed:
            raise ValueError
        # The original functions' guards/root assignments remain byte-pinned.
        # In particular role comes from DISPATCH and callers cannot override it.
        if any(
            sources[name] != expected for name, expected in FIXED_READER_SOURCES.items()
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        raise ValueError("scope.file_access_not_whitelisted") from exc
    return {
        "entry_functions": [
            "reference_definition_v301.member_definition",
            "reference_profile_v301.solo_profile",
        ],
        "reached_reader": "reference_registry_v3.member_spec -> artifact",
        "literal_filenames": sorted(names),
        "DISPATCH_members": sorted(dispatch),
        "other_HASHES_granted": False,
        "registered_request_is_entry": False,
    }


def b2_isolation_proof(policy):
    from .reference_check import static_proof
    from .input_disposition import HASHES, sources as disposition_sources

    disposition_sources()

    graph, sources, gates, readers, trees = {}, {}, {}, [], {}
    file_reads = {}
    root = Path(__file__).parent
    targets = [
        (name, name + ".py", None)
        for name in sorted(
            set(IMPORTS)
            | {module for module, _, _ in FIXED_READS}
            | set(FILENAME_READS)
        )
    ]
    targets.extend(FIXED_READS)
    targets.extend(B_RELEASE_FIXED_READS)
    for name, relative, expected in targets:
        raw = (root / relative).read_bytes()
        if expected is not None:
            if sha256(raw) != expected:
                raise ValueError("scope.file_access_not_whitelisted")
            continue
        sources[name + ".py"] = sha256(raw)
        tree = ast.parse(raw)
        trees[name] = tree
        if name in FILENAME_READS:
            continue
        graph[name] = sorted(
            {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            | {
                a.name
                for n in ast.walk(tree)
                if isinstance(n, ast.Import)
                for a in n.names
            }
        )
        if name in IMPORTS and not set(graph[name]).issubset(IMPORTS[name]):
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
        "b_release_context": 4,
        "catalog_v21": 1,
        "execution": 2,
        "pipeline": 1,
        "reference_inputs": 1,
        "scope_proof": 2,
        "scope_reader": 1,
        "valuation": 1,
        "k5": 2,
        "execution_accounting": 1,
        "execution_clock": 1,
        "execution_closure": 2,
        "reference_definition_v301": 1,
        "reference_registry_v3": 1,
    }:
        raise ValueError("scope.file_access_not_whitelisted")
    registry_scope = _candidate_registry_scope(trees, sources)
    filename_scope = _filename_read_scope(trees, sources)
    ref = static_proof()
    # C1-R1 additive stage, after every original guard in its original order.
    adapter_scope = _b_release_adapter_scope(
        trees["b_release_context"], trees["scope_proof"]
    )
    for _, relative, expected in B_RELEASE_ADAPTER_READS:
        raw = Path.read_bytes.__call__(root / relative)
        if sha256(raw) != expected:
            raise ValueError("scope.file_access_not_whitelisted")
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
        "C13_registered_fixed_reads": [
            {"module": module, "path": path, "sha256": expected}
            for module, path, expected in FIXED_READS
        ],
        "B_release_adapter_scope": adapter_scope,
        "C13_registry_call_scope": registry_scope,
        "C13_filename_registration_scope": filename_scope,
        "C13_coverage_boundary": "Registered 3+7 fixed reads only; existing transitive helper reads retain original mechanisms and are not claimed fully covered by this table",
        "seal_status": "seal_pending",
        "non_market_read_whitelist": {
            **FILENAME_READS,
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


def reference_execution_proof(policy):
    """Independent C09/C10 segment; old B2 entries retain their own names."""
    from .reference_check import execution_proof

    inherited = b2_isolation_proof(policy)
    extension = execution_proof()
    return dict(
        schema="EVO884.ReferenceExecutionScope/v1",
        C09_C10=extension,
        C09_component_readers={
            name: [r for r in extension["reader_sites"] if r["module"] == name]
            for name in sorted(extension["source_files"])
        },
        C09_numeric_input_files=["raw.json", "rights.json", "adv.json", "cash.json"],
        C09_fixed_input_files=[
            {k: row[k] for k in ("module", "path", "sha256")}
            for row in extension["reader_sites"]
            if "path" in row
        ],
        shared_execution_source_sha256=inherited["source_sha256"],
        shared_fixed_reads=inherited["C13_registered_fixed_reads"],
        coverage_boundary="C09 four-file reader is separately registered before fact binding; the result worker consumes only the exact owned read facts and common-engine program, with individually registered metadata files; old component entries retain their original meanings",
        seal_status="seal_pending",
        runtime_consumable=False,
    )


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

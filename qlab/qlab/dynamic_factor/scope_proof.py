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


# V8: the complete reviewed specification includes docstrings, excludes locations.
# Digest markers expand from fixed original data; no candidate generates a template.
B_RELEASE_MODULE_TEMPLATE = '"""B01 metadata reception. No caller-mintable authority or runtime permission.\n\nThe deployment\'s original permission adapter is deliberately unconnected. Tests\nmay replace the private adapter to exercise reception; this does not certify a\nreal installation, source permission, A publication or a producer\'s proofs.\n"""\n\nimport csv\nfrom datetime import datetime\nimport io\nimport json\nfrom weakref import WeakKeyDictionary\n\nfrom .catalog_v21 import (\n    BINDINGS as _CATALOG_BINDINGS,\n    FIXTURES as _CATALOG_FIXTURES,\n    derive as _derive_catalog,\n)\nfrom .contract import code_sha, sha256\n\n\nADOPTION_SHA256 = "V8_FIXED_LITERAL_14"\nANNOTATION_COMMENT = "01a19e47-bff6-7dc8-9d06-0ca0b4369576"\nPUBLICATION_COMMENT = "01a19dda-830d-7b82-b549-b4d64129a6af"\nISSUE = "01a18a61-21a5-7763-8cd3-9c781f80499d"\n_CONTEXTS = WeakKeyDictionary()\n\n\ndef _fail(reason):\n    raise ValueError("B.release_context_" + reason)\n\n\ndef _pairs(pairs):\n    result = {}\n    for key, value in pairs:\n        if key in result:\n            _fail("encoding_invalid")\n        result[key] = value\n    return result\n\n\ndef _constant(value):\n    _fail("encoding_invalid")\n\n\ndef _canonical(value):\n    # Do not use contract.clean: NaN/Infinity must be rejected, never nullified.\n    try:\n        return json.dumps(\n            value,\n            ensure_ascii=False,\n            sort_keys=True,\n            separators=(",", ":"),\n            allow_nan=False,\n        ).encode("utf-8")\n    except (TypeError, ValueError, UnicodeError) as exc:\n        raise ValueError("B.release_context_encoding_invalid") from exc\n\n\ndef _json(raw, *, canonical=False):\n    if type(raw) is not bytes:\n        _fail("encoding_invalid")\n    try:\n        value = json.loads(\n            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant\n        )\n    except (ValueError, UnicodeError) as exc:\n        raise ValueError("B.release_context_encoding_invalid") from exc\n    encoded = _canonical(value)\n    if canonical and encoded != raw:\n        _fail("encoding_invalid")\n    return value\n\n\ndef _utc(value):\n    if type(value) is not str or len(value) != 20 or value[19:] != "Z":\n        _fail("encoding_invalid")\n    if any(\n        value[i] not in "0123456789"\n        for i in (0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18)\n    ):\n        _fail("encoding_invalid")\n    try:\n        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")\n    except ValueError as exc:\n        raise ValueError("B.release_context_encoding_invalid") from exc\n    return parsed\n\n\ndef _read_trusted_release():\n    """Fixed package originals and original-authority platform registration.\n\n    C1 deliberately omits the root file. C2 installs only the platform comment\n    readback after BR-A. Its content is the strict JSON registration below;\n    platform created_at supplies acceptance evidence; performance is a separate event.\n    No request, environment, cwd or caller parameter selects an input.\n    """\n    from pathlib import Path\n\n    try:\n        self_path = Path(_read_trusted_release.__code__.co_filename).resolve()\n        if type(__file__) is not str or self_path != Path(__file__).resolve():\n            _fail("acceptance_mismatch")\n    except (NameError, AttributeError, OSError, RuntimeError, TypeError) as exc:\n        raise ValueError("B.release_context_acceptance_mismatch") from exc\n    try:\n        root_raw = (\n            Path(__file__).parent\n            / "b_release_originals"\n            / "trust-root-platform-readback.json"\n        ).read_bytes()\n    except OSError as exc:\n        raise ValueError("B.release_context_trust_binding_missing") from exc\n    try:\n        root = _json(root_raw)\n        if (\n            type(root) is not dict\n            or root.get("type") != "comment"\n            or root.get("author_type") != "agent"\n            or root.get("author_id") != "cc562115-7ef6-4b8f-b4b6-a5b7584b1340"\n            or type(root.get("id")) is not str\n            or not root["id"]\n            or type(root.get("revision")) is not int\n            or root["revision"] < 1\n            or type(root.get("content")) is not str\n            or root.get("issue_id") != "01a19dab-15f2-7e58-96a0-cf92c87162c2"\n        ):\n            _fail("trust_binding_missing")\n        accepted_at = root["created_at"]\n        _utc(accepted_at)\n        registration = _json(root["content"].encode("utf-8"))\n        if type(registration) is not dict or set(registration) != {\n            "schema",\n            "context_version",\n            "receiver_id",\n            "implementation_id",\n            "r_sha256",\n            "p_sha256",\n            "adoption_sha256",\n            "policy_binding",\n            "run_time_binding",\n            "purpose",\n            "limitations",\n        }:\n            _fail("trust_binding_missing")\n        if (\n            registration["schema"] != "EVO884.BReleaseTrustRegistration/v1"\n            or registration["receiver_id"]\n            != "gongbu.original-host:5a307571-9534-4bbc-932c-93ffc9c94d73"\n            or any(\n                type(registration[k]) is not str or not registration[k]\n                for k in ("context_version", "purpose", "limitations")\n            )\n            or type(registration["policy_binding"]) is not dict\n        ):\n            _fail("trust_binding_missing")\n        # Anti-cycle: the root SHA is data-only, never embedded in any code.\n        # This sole self-read is used only for the module implementation_id.\n        try:\n            self_raw = Path.read_bytes(self_path)\n        except OSError as exc:\n            raise ValueError("B.release_context_acceptance_mismatch") from exc\n        implementation_id = sha256(self_raw)\n        if registration["implementation_id"] != implementation_id:\n            _fail("acceptance_mismatch")\n        original_sha256 = {\n            "EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json": "V8_FIXED_LITERAL_14",\n            "EVO883-EVO893-v10-ruling.json": "V8_FIXED_LITERAL_7",\n            "EVO883-S1-BRKB-field-receipt.json": "V8_FIXED_LITERAL_15",\n            "EVO883-S2-v14-field-receipt.json": "V8_FIXED_LITERAL_8",\n            "EVO883-S3-v12-final-receipt.json": "V8_FIXED_LITERAL_2",\n            "EVO883-S4-v11-receipt.json": "V8_FIXED_LITERAL_12",\n            "EVO883-v10-engineering-scope-receipt.json": "V8_FIXED_LITERAL_4",\n            "EVO883-v20.1-final-receipt.json": "V8_FIXED_LITERAL_10",\n            "EVO883-v21-final-receipt.json": "V8_FIXED_LITERAL_9",\n            "EVO893-B-CMI-guard-v21.json": "V8_FIXED_LITERAL_1",\n            "EVO893-B-noncash-catalog-v21.csv": "V8_FIXED_LITERAL_5",\n            "EVO938-B-runtime-release-P-v1.0.0.json": "V8_FIXED_LITERAL_3",\n            "EVO938-B-runtime-release-R-v1.0.0.json": "V8_FIXED_LITERAL_6",\n            "annotation-platform-readback.json": "V8_FIXED_LITERAL_11",\n            "publication-platform-readback.json": "V8_FIXED_LITERAL_13",\n        }\n        originals = {}\n        for name, expected in original_sha256.items():\n            try:\n                raw = (\n                    Path(__file__).parent / "b_release_originals" / name\n                ).read_bytes()\n            except OSError as exc:\n                raise ValueError("B.release_context_release_mismatch") from exc\n            if sha256(raw) != expected:\n                _fail("release_mismatch")\n            originals[name] = raw\n        r_raw = originals["EVO938-B-runtime-release-R-v1.0.0.json"]\n        p_raw = originals["EVO938-B-runtime-release-P-v1.0.0.json"]\n        adoption_raw = originals[\n            "EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json"\n        ]\n        if (\n            registration["r_sha256"] != sha256(r_raw)\n            or registration["p_sha256"] != sha256(p_raw)\n            or registration["adoption_sha256"] != sha256(adoption_raw)\n        ):\n            _fail("release_mismatch")\n        r, p = _json(r_raw, canonical=True), _json(p_raw, canonical=True)\n        readback = _json(originals["publication-platform-readback.json"])\n        publication = dict(\n            comment_id=readback["id"],\n            revision=readback["revision"],\n            created_at=readback["created_at"],\n            R=dict(sha256=sha256(r_raw), platform=p["actual_core_attachment"]),\n            P=dict(sha256=sha256(p_raw)),\n        )\n        readback = _json(originals["annotation-platform-readback.json"])\n        annotation = dict(\n            issue_id=ISSUE,\n            comment_id=readback["id"],\n            revision=readback["revision"],\n            content=readback["content"],\n        )\n        inputs = {}\n        for entry in r["accepted_input_manifest"]["entries"][:-1]:\n            name = entry["accepted_receipt"]["file"]\n            inputs[name] = originals[name]\n        for key in ("catalog_csv", "CMI_guard"):\n            name = r["accepted_input_manifest"]["entries"][0][key]["file"]\n            inputs[name] = originals[name]\n        time = dict(\n            context_version=registration["context_version"],\n            receiver_id=registration["receiver_id"],\n            accepted_at=accepted_at,\n        )\n        run = registration["run_time_binding"]\n        if type(run) is not dict or run.get("mode") not in {"history", "forward"}:\n            _fail("trust_binding_missing")\n        if run.get("first_performance_at") is None:\n            if set(run) != {\n                "mode", "first_performance_at", "signal_close", "performance_state"\n            } or run["performance_state"] != "pre_performance":\n                _fail("trust_binding_missing")\n        else:\n            if set(run) != {"mode", "first_performance_at", "signal_close"}:\n                _fail("trust_binding_missing")\n            if _utc(run["first_performance_at"]) <= _utc(accepted_at):\n                _fail("scope_mismatch")\n        if run["mode"] == "history":\n            if run["signal_close"] is not None:\n                _fail("scope_mismatch")\n        elif run["first_performance_at"] is not None and _utc(run["signal_close"]) < _utc(accepted_at):\n            _fail("scope_mismatch")\n        source = dict(\n            r_raw=r_raw,\n            p_raw=p_raw,\n            adoption_raw=adoption_raw,\n            original_inputs=inputs,\n            publication_raw=_canonical(publication),\n            annotation_raw=_canonical(annotation),\n            acceptance_time_evidence_raw=root_raw,\n            **time,\n            implementation_id=implementation_id,\n            expected_policy_binding_bytes=_canonical(registration["policy_binding"]),\n            expected_publication_bytes=_canonical(publication),\n            expected_annotation_bytes=_canonical(annotation),\n            expected_acceptance_time_bytes=_canonical(root),\n            run_time_binding_bytes=_canonical(run),\n        )\n        source["expected_sha256"] = {\n            k: sha256(source[k])\n            for k in (\n                "r_raw",\n                "p_raw",\n                "adoption_raw",\n                "publication_raw",\n                "annotation_raw",\n                "acceptance_time_evidence_raw",\n            )\n        }\n        source["expected_sha256"].update(\n            implementation_sha256=implementation_id,\n            original_inputs={name: sha256(raw) for name, raw in inputs.items()},\n        )\n        return source\n    except (KeyError, TypeError, AttributeError, IndexError, UnicodeError) as exc:\n        raise ValueError("B.release_context_encoding_invalid") from exc\n\n\nclass ReleaseContext:\n    """Immutable process-local capability. Persist bindings, never this object."""\n\n    __slots__ = ("__weakref__",)\n\n    def __new__(cls, *args, **kwargs):\n        raise TypeError("B.release_context_trust_binding_missing")\n\n    def __getattr__(self, name):\n        record = _CONTEXTS.get(self)\n        if record is None:\n            _fail("trust_binding_missing")\n        fields, _ = record\n        if name not in fields:\n            raise AttributeError(name)\n        return fields[name]\n\n    def __setattr__(self, name, value):\n        raise AttributeError("immutable ReleaseContext")\n\n    def __copy__(self):\n        return self\n\n    def __deepcopy__(self, memo):\n        return self\n\n    def __reduce_ex__(self, protocol):\n        raise TypeError("B.release_context_trust_binding_missing")\n\n\ndef _policy_binding(policy):\n    return dict(\n        policy.binding,\n        date_manifest_sha256=sha256(policy.raw_date_manifest),\n        common_calendar_sha256=policy.date_manifest["common_calendar_sha256"],\n        universe=list(policy.profile["universe"]),\n    )\n\n\ndef _source():\n    source = _read_trusted_release()\n    required = {\n        "r_raw",\n        "p_raw",\n        "adoption_raw",\n        "original_inputs",\n        "expected_sha256",\n        "publication_raw",\n        "annotation_raw",\n        "acceptance_time_evidence_raw",\n        "context_version",\n        "receiver_id",\n        "implementation_id",\n        "accepted_at",\n        "expected_policy_binding_bytes",\n        "expected_publication_bytes",\n        "expected_annotation_bytes",\n        "expected_acceptance_time_bytes",\n        "run_time_binding_bytes",\n    }\n    if type(source) is not dict or set(source) != required:\n        _fail("trust_binding_missing")\n    # Freeze the host response before any work; no shared caller-owned dicts.\n    expected = source["expected_sha256"]\n    inputs = source["original_inputs"]\n    if type(expected) is not dict or type(inputs) is not dict:\n        _fail("trust_binding_missing")\n    raw_keys = {\n        "r_raw",\n        "p_raw",\n        "adoption_raw",\n        "publication_raw",\n        "annotation_raw",\n        "acceptance_time_evidence_raw",\n    }\n    if set(expected) != raw_keys | {"implementation_sha256", "original_inputs"}:\n        _fail("trust_binding_missing")\n    if type(expected["original_inputs"]) is not dict or set(inputs) != set(\n        expected["original_inputs"]\n    ):\n        _fail("trust_binding_missing")\n    for value in [expected[k] for k in raw_keys | {"implementation_sha256"}] + list(\n        expected["original_inputs"].values()\n    ):\n        if (\n            type(value) is not str\n            or len(value) != 64\n            or any(c not in "0123456789abcdef" for c in value)\n        ):\n            _fail("encoding_invalid")\n    copied = dict(\n        source,\n        expected_sha256=dict(\n            expected, original_inputs=dict(expected["original_inputs"])\n        ),\n        original_inputs=dict(inputs),\n    )\n    for key in raw_keys:\n        _json(copied[key], canonical=key in {"r_raw", "p_raw"})\n    for raw in inputs.values():\n        if type(raw) is not bytes:\n            _fail("encoding_invalid")\n    _json(copied["expected_policy_binding_bytes"], canonical=True)\n    for key in (\n        "expected_publication_bytes",\n        "expected_annotation_bytes",\n        "expected_acceptance_time_bytes",\n    ):\n        _json(copied[key], canonical=True)\n    _json(copied["run_time_binding_bytes"], canonical=True)\n    return copied\n\n\ndef _verify_release(source, policy):\n    expected = source["expected_sha256"]\n    for key in ("r_raw", "p_raw", "adoption_raw", "publication_raw"):\n        if sha256(source[key]) != expected[key]:\n            _fail("release_mismatch")\n    if sha256(source["adoption_raw"]) != ADOPTION_SHA256:\n        _fail("release_mismatch")\n    r, p = (\n        _json(source["r_raw"], canonical=True),\n        _json(source["p_raw"], canonical=True),\n    )\n    publication = _json(source["publication_raw"])\n    if _canonical(publication) != source["expected_publication_bytes"]:\n        _fail("release_mismatch")\n    if (\n        publication["comment_id"] != PUBLICATION_COMMENT\n        or type(publication["revision"]) is not int\n        or publication["revision"] < 1\n        or publication["R"]["sha256"] != sha256(source["r_raw"])\n        or publication["P"]["sha256"] != sha256(source["p_raw"])\n        or p["actual_core_attachment"] != publication["R"]["platform"]\n        or p["core_raw_sha256"] != sha256(source["r_raw"])\n        or r["formal_clause_adoption_sha256"] != ADOPTION_SHA256\n        or p["core_version_and_formal_adoption_sha256"][\n            "formal_adoption_machine_sha256"\n        ]\n        != ADOPTION_SHA256\n        or r["schema"] != "EVO938.BRuntimeCatalogRelease/v1"\n        or p["schema"] != "EVO938.BRuntimeCatalogPublicationEnvelope/v1"\n        or p["release_id"] != r["release_id"]\n        or p["core_version"] != r["version"]\n    ):\n        _fail("release_mismatch")\n    entries = r["accepted_input_manifest"]["entries"]\n    if [e["input_id"] for e in entries] != [\n        "V21",\n        "CMI",\n        "S1",\n        "S2",\n        "S3",\n        "S4",\n        "S5a",\n        "S5b",\n        "QUARANTINE",\n    ]:\n        _fail("release_mismatch")\n    required = {}\n    for entry in entries[:-1]:\n        item = entry["accepted_receipt"]\n        required[item["file"]] = item["raw_sha256"]\n        raw = source["original_inputs"].get(item["file"])\n        if (\n            type(raw) is not bytes\n            or sha256(raw) != item["raw_sha256"]\n            or sha256(raw) != expected["original_inputs"].get(item["file"])\n        ):\n            _fail("release_mismatch")\n        receipt = _json(raw)\n        scope = entry["accepted_scope_verbatim"]\n        if {k: receipt[k] for k in scope["keys"]} != scope["value"]:\n            _fail("release_mismatch")\n    v21 = entries[0]\n    for key in ("catalog_csv", "CMI_guard"):\n        item = v21[key]\n        required[item["file"]] = item["raw_sha256"]\n    if required != expected["original_inputs"]:\n        _fail("release_mismatch")\n    for name, identity in required.items():\n        if sha256(source["original_inputs"][name]) != identity:\n            _fail("release_mismatch")\n    csv_raw = source["original_inputs"][v21["catalog_csv"]["file"]]\n    rows = list(csv.reader(io.StringIO(csv_raw.decode("utf-8"), newline="")))\n    catalog = r["catalog"]\n    if [catalog["v21_catalog"]["columns"]] + catalog["v21_catalog"][\n        "rows"\n    ] != rows or catalog["CMI_guard_mapping"]["value"] != _json(\n        source["original_inputs"][v21["CMI_guard"]["file"]]\n    ):\n        _fail("release_mismatch")\n    # Recompute every fact/protective row from the original v21 columns.\n    original = [dict(zip(rows[0], row)) for row in rows[1:]]\n    ordered = {row["symbol"]: row for row in original}\n    derived = r["derivation_payload"]\n    if [row["symbol"] for row in derived["per_symbol"]] != r[\n        "policy_profile_calendar_domain_bindings"\n    ]["U64"]["order_and_ids"]:\n        _fail("release_mismatch")\n    for row in derived["per_symbol"]:\n        old = ordered[row["symbol"]]\n        protected = old["candidate_guard"].startswith(\n            ("B 防护", "guard_pending_review=true")\n        )\n        if (\n            row["fact_state_v21"] != old["fact_state"]\n            or row["candidate_guard_v21"] != old["candidate_guard"]\n            or row["protective_membership"] is not protected\n            or row["guard_pending_review"]\n            is not old["candidate_guard"].startswith("guard_pending_review=true")\n            or row["fact_class"]\n            != (\n                "KNOWN_UNCLOSED"\n                if old["fact_state"].startswith("未闭合")\n                else "UNKNOWN"\n            )\n        ):\n            _fail("release_mismatch")\n    h_c, h_d = sha256(_canonical(catalog)), sha256(_canonical(derived))\n    if h_c != r["catalog_sha256"] or h_d != r["derivation_sha256"]:\n        _fail("release_mismatch")\n    binding = _json(source["expected_policy_binding_bytes"], canonical=True)\n    domain = r["policy_profile_calendar_domain_bindings"]\n    if (\n        domain["U64"]["order_and_ids"] != binding["universe"]\n        or domain["policy"]["raw_sha256"] != binding["prereg_sha256"]\n        or domain["common_profile"]["raw_sha256"]\n        != "V8_FIXED_LITERAL_0"\n        or domain["calendar"]["calendar_sha256"] != binding["common_calendar_sha256"]\n    ):\n        _fail("scope_mismatch")\n    return r, p, publication, h_c, h_d, binding\n\n\ndef _acceptance(source, policy, *, a_raw=None):\n    try:\n        r, p, publication, h_c, h_d, binding = _verify_release(source, policy)\n        if source["expected_sha256"]["implementation_sha256"] != code_sha(\n            receive_release_context\n        ) or any(\n            type(source[k]) is not str or not source[k]\n            for k in ("context_version", "receiver_id", "implementation_id")\n        ):\n            _fail("acceptance_mismatch")\n        time = _json(source["acceptance_time_evidence_raw"])\n        if (\n            sha256(source["acceptance_time_evidence_raw"])\n            != source["expected_sha256"]["acceptance_time_evidence_raw"]\n            or _canonical(time) != source["expected_acceptance_time_bytes"]\n            or type(time) is not dict\n            or time.get("type") != "comment"\n            or time.get("author_type") != "agent"\n            or time.get("author_id") != "cc562115-7ef6-4b8f-b4b6-a5b7584b1340"\n            or time.get("issue_id") != "01a19dab-15f2-7e58-96a0-cf92c87162c2"\n            or time.get("created_at") != source["accepted_at"]\n            or type(time.get("content")) is not str\n            or type(_json(time["content"].encode("utf-8"))) is not dict\n            or _json(time["content"].encode("utf-8")).get("context_version")\n            != source["context_version"]\n            or _json(time["content"].encode("utf-8")).get("receiver_id")\n            != source["receiver_id"]\n        ):\n            _fail("acceptance_mismatch")\n        if _utc(source["accepted_at"]) < _utc(publication["created_at"]):\n            _fail("acceptance_mismatch")\n        # Rebuild A from the independent host binding before checking the\n        # supplied annotation. C05 requires A mismatch to win a double fault.\n        annotation = _json(source["expected_annotation_bytes"], canonical=True)\n        annotation_binding = {\n            k: annotation[k] for k in ("issue_id", "comment_id", "revision")\n        }\n        annotation_binding["content_sha256"] = sha256(\n            annotation["content"].encode("utf-8")\n        )\n        a = dict(\n            schema="EVO884.BReleaseAcceptance/v1",\n            context_version=source["context_version"],\n            release_id=r["release_id"],\n            release_version=r["version"],\n            h_r=sha256(source["r_raw"]),\n            h_p=sha256(source["p_raw"]),\n            h_c=h_c,\n            h_d=h_d,\n            adoption_sha256=ADOPTION_SHA256,\n            publication=publication,\n            accepted_input_manifest=r["accepted_input_manifest"],\n            fact_scope=r["derivation_payload"],\n            unverified_runtime_obligations=r["proof_obligations_and_UNVERIFIED_status"],\n            receiver_id=source["receiver_id"],\n            implementation_id=source["implementation_id"],\n            implementation_sha256=code_sha(receive_release_context),\n            accepted_at=source["accepted_at"],\n            acceptance_time_evidence_sha256=sha256(\n                source["acceptance_time_evidence_raw"]\n            ),\n            policy_binding=binding,\n            annotation_binding=annotation_binding,\n            run_time_binding=_json(source["run_time_binding_bytes"], canonical=True),\n            runtime_consumable=False,\n            certifiable=False,\n            seal_status="seal_pending",\n        )\n        if a_raw is not None:\n            _json(a_raw, canonical=True)\n            if a_raw != _canonical(a):\n                _fail("acceptance_mismatch")\n        actual_annotation = _json(source["annotation_raw"])\n        if (\n            type(actual_annotation) is not dict\n            or sha256(source["annotation_raw"])\n            != source["expected_sha256"]["annotation_raw"]\n            or _canonical(actual_annotation) != source["expected_annotation_bytes"]\n            or actual_annotation.get("comment_id") != ANNOTATION_COMMENT\n            or actual_annotation.get("issue_id") != ISSUE\n            or type(actual_annotation.get("revision")) is not int\n            or actual_annotation["revision"] < 1\n            or type(actual_annotation.get("content")) is not str\n            or not actual_annotation["content"]\n        ):\n            _fail("annotation_missing_or_invalid")\n        return a\n    except (KeyError, TypeError, IndexError, UnicodeError) as exc:\n        raise ValueError("B.release_context_encoding_invalid") from exc\n\n\ndef receive_release_context(*, policy, a_raw=None):\n    """Host-only reception or reloading of the exact existing A. No re-signing."""\n    source = _source()\n    a = _acceptance(source, policy, a_raw=a_raw)\n    if source["expected_policy_binding_bytes"] != _canonical(_policy_binding(policy)):\n        _fail("scope_mismatch")\n    expected_a = _canonical(a)\n    if a_raw is not None:\n        _json(a_raw, canonical=True)\n        if a_raw != expected_a:\n            _fail("acceptance_mismatch")\n    fields = {\n        key: a[key]\n        for key in (\n            "context_version",\n            "release_id",\n            "release_version",\n            "receiver_id",\n            "implementation_id",\n            "implementation_sha256",\n            "accepted_at",\n            "adoption_sha256",\n            "acceptance_time_evidence_sha256",\n            "h_r",\n            "h_p",\n            "h_c",\n            "h_d",\n        )\n    }\n    fields.update(\n        a_raw=expected_a,\n        h_a=sha256(expected_a),\n        r_raw=source["r_raw"],\n        p_raw=source["p_raw"],\n        acceptance_time_evidence_raw=source["acceptance_time_evidence_raw"],\n        policy_binding_bytes=_canonical(a["policy_binding"]),\n        annotation_binding_bytes=_canonical(a["annotation_binding"]),\n    )\n    context = object.__new__(ReleaseContext)\n    _CONTEXTS[context] = (fields, source)\n    return context\n\n\ndef _consumer_catalog(source, release, policy):\n    """Use the original derivation only after all three local originals match R.\n\n    Gongbu 01a1b818-7cf9 permits R-bound receipt and frozen policy dependencies.\n    The original module retains its own SHA checks on the subsequent re-read.\n    """\n    binding = _json(source["expected_policy_binding_bytes"], canonical=True)\n    calendar_raw = "".join(day + "\\n" for day in policy.calendar).encode("utf-8")\n    if sha256(calendar_raw) != binding["common_calendar_sha256"]:\n        _fail("scope_mismatch")\n    v21 = release["accepted_input_manifest"]["entries"][0]\n    expected = {\n        v21[key]["file"]: v21[key]["raw_sha256"]\n        for key in ("catalog_csv", "CMI_guard", "accepted_receipt")\n    }\n    if expected != _CATALOG_BINDINGS:\n        _fail("release_mismatch")\n    for name in (\n        "EVO893-B-noncash-catalog-v21.csv",\n        "EVO893-B-CMI-guard-v21.json",\n        "EVO883-v21-final-receipt.json",\n    ):\n        try:\n            raw = (_CATALOG_FIXTURES / "catalog-v21" / name).read_bytes()\n        except OSError as exc:\n            raise ValueError("B.release_context_release_mismatch") from exc\n        if sha256(raw) != expected[name] or raw != source["original_inputs"][name]:\n            _fail("release_mismatch")\n    try:\n        return _derive_catalog(policy)["catalog"]\n    except (ValueError, OSError) as exc:\n        raise ValueError("B.release_context_release_mismatch") from exc\n\n\ndef check_release_context(\n    release_context, *, policy, request, expected_release_identity_bytes=None\n) -> bytes:\n    """Recompute from original host inputs on every call; never read economics."""\n    if release_context is None:\n        _fail("required")\n    if type(release_context) is not ReleaseContext:\n        _fail("type_mismatch")\n    record = _CONTEXTS.get(release_context)\n    if record is None:\n        _fail("trust_binding_missing")\n    fields, original = record\n    source = _source()\n    a = _acceptance(source, policy, a_raw=fields["a_raw"])\n    if source != original or _canonical(a) != fields["a_raw"]:\n        _fail("acceptance_mismatch")\n    identity = {\n        key: fields[key]\n        for key in (\n            "context_version",\n            "release_id",\n            "release_version",\n            "adoption_sha256",\n            "h_a",\n            "h_r",\n            "h_p",\n            "h_c",\n            "h_d",\n            "receiver_id",\n            "implementation_id",\n            "implementation_sha256",\n            "accepted_at",\n            "acceptance_time_evidence_sha256",\n        )\n    }\n    identity.update(\n        schema="EVO884.BReleaseContextIdentity/v1",\n        policy_binding=a["policy_binding"],\n        annotation_binding=a["annotation_binding"],\n    )\n    raw = _canonical(\n        dict(\n            schema="EVO884.BReleaseContextBinding/v1",\n            identity=identity,\n            identity_sha256=sha256(_canonical(identity)),\n        )\n    )\n    if expected_release_identity_bytes is not None:\n        _json(expected_release_identity_bytes, canonical=True)\n        if expected_release_identity_bytes != raw:\n            _fail("persistent_identity_mismatch")\n    if source["expected_policy_binding_bytes"] != _canonical(_policy_binding(policy)):\n        _fail("scope_mismatch")\n    try:\n        release = _json(fields["r_raw"], canonical=True)\n        catalog = _consumer_catalog(source, release, policy)\n        required = {"h_r": fields["h_r"], "h_a": fields["h_a"], "h_d": fields["h_d"]}\n        if (\n            type(request) is not dict\n            or request.get("synthetic") is not False\n            or request.get("release_binding") != required\n            or request.get("mode") not in {"history", "forward"}\n            or _canonical(request.get("catalog")) != _canonical(catalog)\n        ):\n            _fail("scope_mismatch")\n        sealed = _utc(request["sealed_at"])\n        accepted = _utc(a["accepted_at"])\n        if sealed < accepted:\n            _fail("scope_mismatch")\n        run = a["run_time_binding"]\n        if type(run) is not dict or run.get("mode") != request["mode"]:\n            _fail("scope_mismatch")\n        if run.get("first_performance_at") is None:\n            if set(run) != {\n                "mode", "first_performance_at", "signal_close", "performance_state"\n            } or run["performance_state"] != "pre_performance":\n                _fail("scope_mismatch")\n            first = _utc(request["first_performance_at"])\n            signal_close = request.get("signal_close")\n            if first <= accepted:\n                _fail("scope_mismatch")\n        else:\n            if (\n                set(run) != {"mode", "first_performance_at", "signal_close"}\n                or run["first_performance_at"] != request.get("first_performance_at")\n                or run["signal_close"] != request.get("signal_close")\n            ):\n                _fail("scope_mismatch")\n            first = _utc(run["first_performance_at"])\n            signal_close = run["signal_close"]\n        if request["mode"] == "history":\n            if sealed >= first or signal_close is not None:\n                _fail("scope_mismatch")\n        elif _utc(signal_close) < sealed or _utc(signal_close) < accepted:\n            _fail("scope_mismatch")\n    except (KeyError, TypeError) as exc:\n        raise ValueError("B.release_context_scope_mismatch") from exc\n    return raw\n'

B_RELEASE_FIXED_LITERALS = [
    "07b71b3fc59dc6dae1c96cadd3155622a18f4c4ad29b7c69b8f79c1455efc2d3",
    "08ed088405cbefa9bd24e8cb0756d5d10a62b105153b9cfba02af504d9371f77",
    "1df425a328539f4cddfe3d574feabc1b753fc0abe2ff15d318634aee7dff3836",
    "4a4b24b0a6ee2b6b561d285fa6f3f9233960959500b6e02fc137c83ca31deae1",
    "4da26596777a62595664ba9b9e17480113f96ccbd2c1d0226df083ac2e7ecc0f",
    "5040272302cf675b99e0b954669dde72bfc6431f47fb9d835f3acb6f408d1a13",
    "68f06b15ded4cb1ec5219a5456a2e0f0f376cab54a9e3ac33aee653dacfa877c",
    "834bf9546dda93c3fb613833b59ac87842c2825b71c11bc09edc13608f5d42e4",
    "9b5fd1e87a2cae26df8a0c1a8ee9fbd880c07234e05a9253ff9886d4dcb7711f",
    "b8b930396e7caf42ad8bde0f2f7ff190c40f36fd4c4686964a39154926f6644a",
    "cdd7954a20102e1053f932fe559153b26336475afdb41b772004795708bf3c4e",
    "d25ba025d42fea6ad908566384f97f6fd1ed567eb1f4474bba46105e9aa77c81",
    "d44ce4e0b13d68a129f6aca0ad2187f459ea978f117510cc48d910fb8b44b11f",
    "f847be9a107b9293e134bfc4d9a03a3c3cb1eeb823f40991d7b8d28d1533455e",
    "ff5da6ef748d5f1fca592559e73656d5283e28ec9d279b65b3ac0fd5943069ff",
    "ff8dee166c469310b915f903a32164351647e61dd8340437ffa09b45da9e0442",
]

B_RELEASE_CONTRACT_TEMPLATE = '"""Deterministic JSON envelopes and byte fingerprints shared by every tool."""\n\nfrom __future__ import annotations\n\nimport hashlib\nimport inspect\nimport json\nimport math\nfrom pathlib import Path\n\n\ndef clean(value):\n    """Retain nonfinite observations as null; never turn unknowns into zero."""\n    if isinstance(value, float) and not math.isfinite(value):\n        return None\n    if isinstance(value, dict):\n        return {str(k): clean(v) for k, v in value.items()}\n    if isinstance(value, (tuple, list)):\n        return [clean(v) for v in value]\n    return value\n\n\ndef canonical(value) -> bytes:\n    return json.dumps(\n        clean(value),\n        sort_keys=True,\n        separators=(",", ":"),\n        ensure_ascii=False,\n        allow_nan=False,\n    ).encode("utf-8")\n\n\ndef sha256(value: bytes) -> str:\n    return hashlib.sha256(value).hexdigest()\n\n\ndef digest(value) -> str:\n    return sha256(canonical(value))\n\n\ndef is_sha(value) -> bool:\n    return (\n        isinstance(value, str)\n        and len(value) == 64\n        and all(c in "0123456789abcdef" for c in value)\n    )\n\n\ndef source_manifest() -> dict:\n    root = Path(__file__).parent\n    return {p.name: sha256(p.read_bytes()) for p in sorted(root.glob("*.py"))}\n\n\ndef code_sha(value):\n    """Hash the whole adapter module, including helpers and constants."""\n    source = inspect.getsourcefile(value)\n    if source is None:\n        raise ValueError("adapter_source_unavailable")\n    return sha256(Path(source).read_bytes())\n\n\ndef result(\n    tool,\n    inputs,\n    *,\n    metrics=None,\n    reasons=(),\n    missing=(),\n    assumptions=(),\n    availability=None,\n    artifacts=None,\n    certifiable=False,\n    extra_sources=None,\n):\n    sources = source_manifest()\n    sources.update(extra_sources or {})\n    reasons = list(dict.fromkeys(reasons))\n    return clean(\n        {\n            "schema": "dynamic_factor.tool/v1",\n            "tool": tool,\n            "ok": not reasons,\n            "certifiable": bool(certifiable and not reasons),\n            "runtime_consumable": False,\n            "input_sha256": digest(inputs),\n            "source_sha256": digest(sources),\n            "source_files": sources,\n            "assumptions": list(assumptions),\n            "missing_inputs": list(missing),\n            "reasons": reasons,\n            "metrics": metrics or {},\n            "metric_availability": availability or {},\n            "artifacts": artifacts or {},\n        }\n    )\n\n\ndef unavailable(reason):\n    return {"available": False, "reason": reason}\n'

B_RELEASE_IMPORT_READS = (
    (
        "contract",
        "contract.py",
        "ff198c8d9ad05e7f2664af8120a9f6e3d21a242e3ef19e9f0b5cbb65a5beacbb",
    ),
    (
        "__init__",
        "__init__.py",
        "06af6993da8dcb49ff75936b7b5e327424b753802687d92dda74033c15efd797",
    ),
    (
        "../__init__",
        "../__init__.py",
        "304235cd17e4b3b6c3a0a921695d864d74e48cb1f7c5920b73af466ed07a72c2",
    ),
)

B_RELEASE_DEPENDENCY_SOURCES = {
    "catalog_members.py": "a4afc328161064689e24c85dfa1e3d946fd1c4fc7563701fd90e08864e82a82b",
    "catalog_v21.py": "12c3b0d33dcee4518ba39905d49f06fa55b62865f4ec041a5e0cf7f4a4189ab4",
    "continuity.py": "ee759682cd58c80195d5acf5e51ca2705f897f4144cd8c8eb99fb0ea5f658f95",
    "conventions.py": "4b98838d3fca24664470c1e2fb65921eefc3d93a7bfb9331e857d65f0205064a",
    "execution.py": "d15958dabe5c67d2e47033a62253a2fd19fd6667cf15ca5dac8b3b49c91d9cd8",
    "execution_accounting.py": "f8101633e86d2ee42e75dd66793ae0e153f1454e38ce008cc10bd2d6611a5a4a",
    "execution_amounts.py": "18b2cdf6edaa43c7fd489e63eb8bdac8e209f5a06b317ff2aa1d3f306a4e245d",
    "execution_candidate.py": "90d1a9dcbe46b9881450d1770003212e1daea0b14f3d8e15d90e5f4b1563d16e",
    "execution_cash.py": "a49653574a53ccab01552e18cdecf9f6d41481a7d63c49175904683651150348",
    "execution_clock.py": "c1f9563c645110335cdbf006328b3cee4d1d8952d8433ffd5306b91d07e8ecf6",
    "execution_closure.py": "998ef21c68825ab9254489f29b12095c8dc0d4b3f6f14e507e8fbea6808615ae",
    "execution_exposure.py": "8af9951b19fb454637440f98d74b4a4567cc4b8f8aebefbee647b18e1a4dbaed",
    "execution_numbers.py": "b31df6da61dbde3a864164e31bd8590debf2941040e301f8511914ccd4933aa2",
    "execution_projection.py": "d7a30669a8cfc019318c35e648ea3cd9bea7129e57b12bcd93da0751afa8f5cc",
    "execution_returns.py": "75d09e78605c6951cbaec3c914e7fdfc8090f646ddbd74078d8ceb4a0ec5f83c",
    "execution_risk.py": "b1b616126da4b831dba193f338ca9654c9de148bf1dc0b74d9723448faea8ab3",
    "execution_risk_history.py": "da55c683a2b281b1ece42850e0c4d49dbe81a921bfbb17c0a013a10330ba84d4",
    "execution_signals.py": "226c83a62f887ebf7720452c8ae045bceb699ab6cf7774446a5c72d28db5c0cb",
    "execution_startup.py": "4b675f45605e69869bab8135b77e1b82cca7d4a5a309f1549fc38ea10f0f1c72",
    "execution_state.py": "8e8129e63d084552ce308d84737d1b2851413e438ead3c247cfc3e69e32b4cf4",
    "folds.py": "d6f052976cc2bafacf3b7814a1fdf801e71c471ca4aca3b2813471e0666ccb02",
    "historical_authority.py": "fb401e78c115876d73f9f5a6cece6d7d820927c9cd1222dad49eca983629fcce",
    "input_disposition.py": "515945c2ee3de0d8e9a1ec0087f8087b5750258d013ada6ed08060f50e872d65",
    "input_scope.py": "3449f22061560251e19a21268da4c0cee911edc0864e19e08f1cf05b89a91bbe",
    "isolation.py": "910cccfd6fa0fa74405a393cba180ec5a65bceac99d5543722b68e87a7ec20a1",
    "k5.py": "96be5e8a8de9176b3cd24c766f08a4dc24a7d5db158a4bab2c0a468618d8bf97",
    "noncash_v3.py": "ce439592adc936c8715e7515dfb7f6dc8261847a15a737eadf281329cff47ccd",
    "pending.py": "3a1625313ea1d5491a8d0670a6698176ed80bdd98e7efd37a1447b2878349c06",
    "pipeline.py": "a7f4c35d0bb0c70507283fe525869d13b2d7cce6e6a53a5e2da6632e05cf8ffd",
    "reference_definition_v301.py": "95a51f2f5c5d3473254e247ac8d1b408c4f89c9253b3622ee2fe4d7941ef1a55",
    "reference_inputs.py": "0b9ce35ecdb6806f3469b8ce3e662c659743a6192fc0a80aba28038abb233099",
    "reference_profile_v301.py": "184f15302f003356a9d41027ab5fd84fa5917e796f96adee5374a714edc3ccd3",
    "reference_registry_v3.py": "90ff033cb06bbedce4315ec04bb7c84b8a300fdd133015db58a23b1f7fee997a",
    "scope_reader.py": "3bbb0be2fa7b80e63e2879e947d0268b0f3c93c667ca8815b660afac7dc41f38",
    "state_v2.py": "0c31a71defe68d23126ada28b15dbd3b6574b661508d53f0d1697a9ed1492e2c",
    "validation.py": "5d3d6d97ab350c14bf9e5d62f51b2d42244f4466f9ed7636d7eb77d7c4a2be8d",
    "valuation.py": "4b0a18ebb18b2706926e344a94fd5da32b0f06b969a34d9da294e91ffffb8a8d",
    "contract.py": "ff198c8d9ad05e7f2664af8120a9f6e3d21a242e3ef19e9f0b5cbb65a5beacbb",
    "__init__.py": "06af6993da8dcb49ff75936b7b5e327424b753802687d92dda74033c15efd797",
    "../__init__.py": "304235cd17e4b3b6c3a0a921695d864d74e48cb1f7c5920b73af466ed07a72c2",
}


B_RELEASE_AUDIT_FUNCTIONS = {
    "_b_release_audit_structure": '_b_release_audit_structure(tree):\n    """The audit source accepts only its reviewed functions and literal data."""\n    expected_bindings = {\n        "GATES": GATES,\n        "IMPORTS": IMPORTS,\n        "FIXED_READS": FIXED_READS,\n        "B_RELEASE_FIXED_READS": B_RELEASE_FIXED_READS,\n        "B_RELEASE_ADAPTER_READS": B_RELEASE_ADAPTER_READS,\n        "B_RELEASE_PATH_ONLY_READS": B_RELEASE_PATH_ONLY_READS,\n        "B_RELEASE_MODULE_TEMPLATE": B_RELEASE_MODULE_TEMPLATE,\n        "B_RELEASE_FIXED_LITERALS": B_RELEASE_FIXED_LITERALS,\n        "B_RELEASE_DEPENDENCY_SOURCES": B_RELEASE_DEPENDENCY_SOURCES,\n        "B_RELEASE_IMPORT_READS": B_RELEASE_IMPORT_READS,\n        "B_RELEASE_CONTRACT_TEMPLATE": B_RELEASE_CONTRACT_TEMPLATE,\n        "FIXED_READER_SOURCES": FIXED_READER_SOURCES,\n        "FILENAME_READS": FILENAME_READS,\n        "FILENAME_SOURCE_IDENTITIES": FILENAME_SOURCE_IDENTITIES,\n        "B_RELEASE_AUDIT_FUNCTIONS": B_RELEASE_AUDIT_FUNCTIONS,\n        "C1_ENTRY_TEMPLATE": C1_ENTRY_TEMPLATE,\n        "C1_ENTRY_REGISTRATION": C1_ENTRY_REGISTRATION,\n    }\n    assignments = [n for n in tree.body if isinstance(n, ast.Assign)]\n    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]\n    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]\n    if len(tree.body) != len(assignments) + len(functions) + len(imports) + 1:\n        raise ValueError\n    if not isinstance(tree.body[0], ast.Expr) or ast.dump(tree.body[0]) != ast.dump(\n        ast.parse(\n            "\'Static import/guard/read-scope receipt for owned trusted strategy interfaces.\'"\n        ).body[0]\n    ):\n        raise ValueError\n    if [ast.dump(n) for n in imports] != [\n        ast.dump(n)\n        for n in ast.parse(\n            "import ast\\nfrom pathlib import Path\\nfrom .contract import digest, sha256\\nfrom .input_scope import ROLES"\n        ).body\n    ]:\n        raise ValueError\n    seen = set()\n    for node in assignments:\n        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):\n            raise ValueError\n        name = node.targets[0].id\n        if (\n            name in seen\n            or name not in expected_bindings\n            or ast.literal_eval(node.value) != expected_bindings[name]\n        ):\n            raise ValueError\n        seen.add(name)\n    if seen != set(expected_bindings):\n        raise ValueError\n    if len(functions) != len(B_RELEASE_AUDIT_FUNCTIONS) or {\n        node.name: ast.dump(node, include_attributes=False) for node in functions\n    } != {\n        name: ast.dump(ast.parse("def " + source).body[0], include_attributes=False)\n        for name, source in B_RELEASE_AUDIT_FUNCTIONS.items()\n    }:\n        raise ValueError',
    "_b_release_dependency_scope": '_b_release_dependency_scope(trees, sources):\n    """Closed source identities plus namespace and method binding checks."""\n    protected = {\n        "_read_trusted_release",\n        "_fail",\n        "_json",\n        "_utc",\n        "_canonical",\n        "_pairs",\n        "_constant",\n        "sha256",\n        "ISSUE",\n        "json",\n        "datetime",\n        "Path",\n        "pathlib",\n        "__file__",\n        "__builtins__",\n        "type",\n        "str",\n        "dict",\n        "int",\n        "set",\n        "any",\n        "bytes",\n        "len",\n        "ValueError",\n        "TypeError",\n        "UnicodeError",\n        "KeyError",\n        "IndexError",\n        "NameError",\n        "AttributeError",\n        "OSError",\n        "RuntimeError",\n    }\n    methods = {\n        "resolve",\n        "read_bytes",\n        "parent",\n        "co_filename",\n        "__code__",\n        "loads",\n        "dumps",\n        "strptime",\n        "__dict__",\n        "__globals__",\n    }\n    if set(B_RELEASE_DEPENDENCY_SOURCES) != {\n        name + ".py"\n        for name in trees\n        if name not in {"scope_proof", "b_release_context"}\n    } or any(\n        sources.get(name) != expected\n        for name, expected in B_RELEASE_DEPENDENCY_SOURCES.items()\n    ):\n        raise ValueError("scope.file_access_not_whitelisted")\n    for module, tree in trees.items():\n        for node in ast.walk(tree):\n            if (\n                isinstance(node, ast.Name)\n                and isinstance(node.ctx, (ast.Store, ast.Del))\n                and node.id in protected\n            ):\n                # The reviewed literal ISSUE declaration is the single binding.\n                if not (\n                    module == "b_release_context"\n                    and node.id == "ISSUE"\n                    and isinstance(node.ctx, ast.Store)\n                ):\n                    raise ValueError("scope.file_access_not_whitelisted")\n            if isinstance(node, ast.Global) and set(node.names) & protected:\n                raise ValueError("scope.file_access_not_whitelisted")\n            if isinstance(node, ast.Attribute):\n                if node.attr in {"__dict__", "__globals__"} or (\n                    isinstance(node.ctx, (ast.Store, ast.Del))\n                    and node.attr in protected | methods\n                ):\n                    raise ValueError("scope.file_access_not_whitelisted")\n                if (\n                    node.attr == "modules"\n                    and isinstance(node.value, ast.Name)\n                    and node.value.id == "sys"\n                ):\n                    raise ValueError("scope.file_access_not_whitelisted")\n            if isinstance(node, ast.Call):\n                name = (\n                    node.func.id\n                    if isinstance(node.func, ast.Name)\n                    else node.func.attr\n                    if isinstance(node.func, ast.Attribute)\n                    else ""\n                )\n                if name in {\n                    "globals",\n                    "locals",\n                    "vars",\n                    "setattr",\n                    "delattr",\n                    "__setattr__",\n                    "__delattr__",\n                }:\n                    ordinary = (\n                        module in {"execution_accounting", "execution_cash"}\n                        and name in {"setattr", "__setattr__"}\n                        and len(node.args) == 3\n                        and isinstance(node.args[0], ast.Name)\n                        and node.args[0].id == "self"\n                    )\n                    # This existing ordinary-field operation is also byte-fixed.\n                    if not ordinary:\n                        raise ValueError("scope.file_access_not_whitelisted")\n            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):\n                value = node.value\n                if (\n                    isinstance(value, (ast.Name, ast.Attribute))\n                    and not (\n                        isinstance(value, ast.Attribute)\n                        and value.attr == "parent"\n                        and isinstance(value.value, ast.Call)\n                        and isinstance(value.value.func, ast.Name)\n                        and value.value.func.id == "Path"\n                    )\n                    and any(\n                        isinstance(n, ast.Name)\n                        and n.id\n                        in {\n                            "Path",\n                            "pathlib",\n                            "_read_trusted_release",\n                            "_fail",\n                            "_json",\n                            "_utc",\n                            "_canonical",\n                        }\n                        for n in ast.walk(value)\n                    )\n                ):\n                    raise ValueError("scope.file_access_not_whitelisted")\n    return dict(\n        module_count=len(trees),\n        fixed_source_count=len(B_RELEASE_DEPENDENCY_SOURCES),\n        hits=[],\n        unresolved_changes=[],\n        docstrings_compared=True,\n    )',
    "_b_release_adapter_scope": '_b_release_adapter_scope(tree, audit_tree):\n    """Exact call ASTs, fixed original loop, and self-read SHA-only use."""\n    try:\n        _b_release_audit_structure(audit_tree)\n        expected_source = B_RELEASE_MODULE_TEMPLATE\n        for index, value in reversed(list(enumerate(B_RELEASE_FIXED_LITERALS))):\n            expected_source = expected_source.replace(\n                "V8_FIXED_LITERAL_" + str(index), value\n            )\n        expected_tree = ast.parse(expected_source)\n        if ast.dump(tree, include_attributes=False) != ast.dump(\n            expected_tree, include_attributes=False\n        ):\n            raise ValueError\n        if len(B_RELEASE_PATH_ONLY_READS) != 2 or set(B_RELEASE_PATH_ONLY_READS) != {\n            (\n                "b_release_context",\n                "b_release_originals/trust-root-platform-readback.json",\n            ),\n            ("b_release_context", "b_release_context.py"),\n        }:\n            raise ValueError\n        fn = next(\n            n\n            for n in tree.body\n            if isinstance(n, ast.FunctionDef) and n.name == "_read_trusted_release"\n        )\n        if fn.args.args or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg:\n            raise ValueError\n        expected = ast.literal_eval(\n            next(\n                n.value\n                for n in ast.walk(fn)\n                if isinstance(n, ast.Assign)\n                and len(n.targets) == 1\n                and isinstance(n.targets[0], ast.Name)\n                and n.targets[0].id == "original_sha256"\n            )\n        )\n        rows = tuple(\n            ("b_release_context", "b_release_originals/" + name, value)\n            for name, value in expected.items()\n        )\n        if (\n            len(rows) != 15\n            or rows != B_RELEASE_ADAPTER_READS\n            or any(\n                type(value) is not str\n                or len(value) != 64\n                or any(c not in "0123456789abcdef" for c in value)\n                for value in expected.values()\n            )\n        ):\n            raise ValueError\n        reads = [\n            n\n            for n in ast.walk(fn)\n            if isinstance(n, ast.Call)\n            and isinstance(n.func, ast.Attribute)\n            and n.func.attr == "read_bytes"\n        ]\n        expressions = {\n            "root": \'(Path(__file__).parent / "b_release_originals" / "trust-root-platform-readback.json").read_bytes()\',\n            "self": "Path.read_bytes(self_path)",\n            "original": \'(Path(__file__).parent / "b_release_originals" / name).read_bytes()\',\n        }\n        if len(reads) != 3 or {ast.dump(n) for n in reads} != {\n            ast.dump(ast.parse(expr, mode="eval").body) for expr in expressions.values()\n        }:\n            raise ValueError\n        # V7: the self-read argument and its co_filename provenance are exact ASTs.\n        # No literal, caller/env path or descriptor-call alternative is allowed.\n        # Scan the WHOLE module, including bindings outside the reader body.\n        for node in ast.walk(tree):\n            if isinstance(node, ast.Name):\n                if node.id in {"globals", "setattr"}:\n                    raise ValueError\n                if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in {\n                    "__file__",\n                    "Path",\n                    "compile",\n                    "_read_trusted_release",\n                }:\n                    raise ValueError\n            if isinstance(node, ast.Attribute):\n                if node.attr in {"globals", "setattr", "__setattr__"}:\n                    raise ValueError\n                if node.attr == "__file__" and isinstance(\n                    node.ctx, (ast.Store, ast.Del)\n                ):\n                    raise ValueError\n            if isinstance(node, ast.Subscript) and isinstance(\n                node.ctx, (ast.Store, ast.Del)\n            ):\n                if (\n                    isinstance(node.slice, ast.Constant)\n                    and node.slice.value == "__file__"\n                ):\n                    raise ValueError\n            if isinstance(\n                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)\n            ) and node.name in {"__file__", "Path", "compile"}:\n                raise ValueError\n            if isinstance(node, ast.arg) and node.arg in {\n                "__file__",\n                "Path",\n                "compile",\n            }:\n                raise ValueError\n            if isinstance(node, ast.ExceptHandler) and node.name in {\n                "__file__",\n                "Path",\n                "compile",\n            }:\n                raise ValueError\n            if isinstance(node, ast.alias) and (\n                node.asname or node.name.split(".")[0]\n            ) in {"__file__", "compile"}:\n                raise ValueError\n        imports = [\n            n for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))\n        ]\n        if len(imports) != 1 or ast.dump(imports[0]) != ast.dump(\n            ast.parse("from pathlib import Path").body[0]\n        ):\n            raise ValueError\n        if (\n            sum(\n                isinstance(n, ast.alias) and (n.asname or n.name) == "Path"\n                for n in ast.walk(tree)\n            )\n            != 1\n        ):\n            raise ValueError\n        prelude = ast.parse(\n            \'try:\\n    self_path = Path(_read_trusted_release.__code__.co_filename).resolve()\\n    if type(__file__) is not str or self_path != Path(__file__).resolve():\\n        _fail("acceptance_mismatch")\\nexcept (NameError, AttributeError, OSError, RuntimeError, TypeError) as exc:\\n    raise ValueError("B.release_context_acceptance_mismatch") from exc\\n\'\n        ).body\n        binding = ast.parse(\n            \'try:\\n    self_raw = Path.read_bytes(self_path)\\nexcept OSError as exc:\\n    raise ValueError("B.release_context_acceptance_mismatch") from exc\\nimplementation_id = sha256(self_raw)\\n\'\n        ).body\n\n        def exact_sequence(statements, expected):\n            wanted = [ast.dump(n) for n in expected]\n            actual = [ast.dump(n) for n in statements]\n            return (\n                sum(actual[i : i + len(wanted)] == wanted for i in range(len(actual)))\n                == 1\n            )\n\n        if not exact_sequence(fn.body, prelude):\n            raise ValueError\n        containers = [n.body for n in ast.walk(fn) if isinstance(n, ast.Try)]\n        if sum(exact_sequence(body, binding) for body in containers) != 1:\n            raise ValueError\n        if (\n            sum(isinstance(n, ast.Name) and n.id == "compile" for n in ast.walk(tree))\n            != 0\n        ):\n            raise ValueError\n        if (\n            sum(\n                isinstance(n, ast.Name)\n                and n.id == "self_raw"\n                and isinstance(n.ctx, ast.Load)\n                for n in ast.walk(fn)\n            )\n            != 1\n        ):\n            raise ValueError\n        if (\n            sum(\n                isinstance(n, ast.Name)\n                and n.id == "self_path"\n                and isinstance(n.ctx, ast.Store)\n                for n in ast.walk(fn)\n            )\n            != 1\n        ):\n            raise ValueError\n        audit_fn = next(\n            n\n            for n in audit_tree.body\n            if isinstance(n, ast.FunctionDef) and n.name == "b2_isolation_proof"\n        )\n        audit_loop = ast.parse(\n            \'for name, relative, expected in B_RELEASE_ADAPTER_READS + B_RELEASE_IMPORT_READS:\\n    raw = Path.read_bytes(root / relative)\\n    if name == "contract" and raw != B_RELEASE_CONTRACT_TEMPLATE.encode("utf-8"):\\n        raise ValueError("scope.file_access_not_whitelisted")\\n    if sha256(raw) != expected:\\n        raise ValueError("scope.file_access_not_whitelisted")\\n    if (name, relative, expected) in B_RELEASE_IMPORT_READS:\\n        sources[name + ".py"] = sha256(raw)\\n        trees[name] = ast.parse(raw)\'\n        ).body[0]\n        if sum(ast.dump(n) == ast.dump(audit_loop) for n in audit_fn.body) != 1:\n            raise ValueError\n        loops = [\n            n\n            for n in ast.walk(fn)\n            if isinstance(n, ast.For)\n            and ast.dump(n.iter)\n            == ast.dump(ast.parse("original_sha256.items()", mode="eval").body)\n        ]\n        if len(loops) != 1 or ast.dump(loops[0].target) != ast.dump(\n            ast.parse("for name, expected in original_sha256.items(): pass")\n            .body[0]\n            .target\n        ):\n            raise ValueError\n    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as exc:\n        raise ValueError("scope.file_access_not_whitelisted") from exc\n    return {\n        "sha256_reads": [dict(module=m, path=p, sha256=s) for m, p, s in rows],\n        "path_only_reads": [\n            dict(module=m, path=p) for m, p in B_RELEASE_PATH_ONLY_READS\n        ],\n        "exact_adapter_read_sites": 3,\n        "self_read_argument": "self_path = Path(_read_trusted_release.__code__.co_filename).resolve()",\n        "self_read_use": "co_filename / resolved __file__ equality; fixed self bytes SHA -> implementation_id",\n        "import_filename_path_binding": True,\n        "post_import_process_tamper_defense": False,\n        "additional_fixed_audit_read_sites": 1,\n        "additional_fixed_compile_sites": 0,\n        "dynamic_code_exceptions": [],\n        "root_sha_in_code": False,\n    }',
    "_call_descriptor_forbidden": '_call_descriptor_forbidden(node):\n    forbidden = ("open", "eval", "exec", "__import__", "compile", "read_bytes")\n    if not isinstance(node, ast.Attribute) or node.attr != "__call__":\n        return False\n    value = node.value\n    return (\n        isinstance(value, ast.Name)\n        and value.id in forbidden\n        or isinstance(value, ast.Attribute)\n        and value.attr in forbidden\n    )',
    "_call_blindspot_scope": '_call_blindspot_scope(trees):\n    """V7: no exceptions for descriptor calls in any inspected module."""\n    for module, tree in sorted(trees.items()):\n        for node in ast.walk(tree):\n            if _call_descriptor_forbidden(node):\n                raise ValueError("scope.dynamic_reader_or_code_forbidden")\n    return {\n        "modules": sorted(trees),\n        "module_count": len(trees),\n        "hits": [],\n        "exceptions": [],\n    }',
    "_filename_read_scope": '_filename_read_scope(trees, sources):\n    for name, expected in FILENAME_SOURCE_IDENTITIES.items():\n        if sources[name + ".py"] != expected:\n            raise ValueError("scope.file_access_not_whitelisted")\n    for module in ("conventions", "input_disposition"):\n        names = {\n            node.func.value.right.value\n            for node in ast.walk(trees[module])\n            if isinstance(node, ast.Call)\n            and isinstance(node.func, ast.Attribute)\n            and node.func.attr == "read_bytes"\n            and isinstance(node.func.value, ast.BinOp)\n            and isinstance(node.func.value.op, ast.Div)\n            and isinstance(node.func.value.left, ast.Name)\n            and node.func.value.left.id == "FIXTURES"\n            and isinstance(node.func.value.right, ast.Constant)\n        }\n        if not set(FILENAME_READS[module]) <= names:\n            raise ValueError("scope.file_access_not_whitelisted")\n    tree = trees["historical_authority"]\n    stores = [\n        node\n        for node in ast.walk(tree)\n        if isinstance(node, ast.Name)\n        and node.id == "HISTORICAL_V4_WITNESS_INPUT"\n        and isinstance(node.ctx, ast.Store)\n    ]\n    assignments = [\n        node\n        for node in tree.body\n        if isinstance(node, ast.Assign)\n        and any(\n            isinstance(t, ast.Name) and t.id == "HISTORICAL_V4_WITNESS_INPUT"\n            for t in node.targets\n        )\n    ]\n    expected = ast.parse(\n        "HISTORICAL_V4_FIXTURES / \'EVO891-B-ledger-v4.tip.json\'", mode="eval"\n    ).body\n    if (\n        len(stores) != 1\n        or len(assignments) != 1\n        or ast.dump(assignments[0].value) != ast.dump(expected)\n    ):\n        raise ValueError("scope.file_access_not_whitelisted")\n    return dict(\n        registrations=FILENAME_READS,\n        historical_witness=dict(\n            constant="HISTORICAL_V4_WITNESS_INPUT",\n            assignments=len(stores),\n            literal_filename="EVO891-B-ledger-v4.tip.json",\n            source_identity_bound=True,\n            scope="historical diagnostic only",\n        ),\n        unverified_not_in_table=["R056", "R057", "R058", "R059", "R060"],\n        guarantee="Pinned owned source and static assignments; no arbitrary host mutation sandbox claim",\n    )',
    "_candidate_registry_scope": '_candidate_registry_scope(trees, sources):\n    """Bound the reached artifact calls, not the generic function\'s HASHES.\n\n    The candidate path reaches member_definition and solo_profile, then\n    member_spec for the four literal DISPATCH members. registered_request is\n    not an entry: its platform anchor and five other HASHES are not allowed.\n    """\n\n    def assignment(tree, name):\n        return next(\n            n.value\n            for n in tree.body\n            if isinstance(n, ast.Assign)\n            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)\n        )\n\n    def function(module, name):\n        return next(\n            n\n            for n in trees[module].body\n            if isinstance(n, ast.FunctionDef) and n.name == name\n        )\n\n    def artifact_calls(node):\n        return [\n            n\n            for n in ast.walk(node)\n            if isinstance(n, ast.Call)\n            and isinstance(n.func, ast.Name)\n            and n.func.id == "artifact"\n        ]\n\n    allowed = {\n        path.rsplit("/", 1)[-1]\n        for module, path, _ in FIXED_READS\n        if module == "reference_registry_v3"\n    }\n    try:\n        dispatch = ast.literal_eval(\n            assignment(trees["reference_registry_v3"], "DISPATCH")\n        )\n        if dispatch != {\n            "CREF-F1-L020": ("candidate", "F1-L020"),\n            "CREF-F3-L020": ("candidate", "F3-L020"),\n            "MREF-F2-L020": ("meta", "F2-L020"),\n            "MREF-F4-L020": ("meta", "F4-L020"),\n        }:\n            raise ValueError\n        direct = artifact_calls(\n            function("reference_definition_v301", "member_definition")\n        )\n        indirect = artifact_calls(function("reference_registry_v3", "member_spec"))\n        if (\n            len(direct) != 1\n            or len(indirect) != 1\n            or len(direct[0].args) != 1\n            or len(indirect[0].args) != 1\n        ):\n            raise ValueError\n        names = {ast.literal_eval(direct[0].args[0])}\n        expression = indirect[0].args[0]\n        if isinstance(expression, ast.Constant) and type(expression.value) is str:\n            names.add(expression.value)\n        elif ast.dump(expression) == ast.dump(\n            ast.parse("role + \'_reference_manifest.json\'", mode="eval").body\n        ):\n            names.update(\n                role + "_reference_manifest.json" for role, _ in dispatch.values()\n            )\n        else:\n            raise ValueError\n        if names != allowed:\n            raise ValueError\n        # The original functions\' guards/root assignments remain byte-pinned.\n        # In particular role comes from DISPATCH and callers cannot override it.\n        if any(\n            sources[name] != expected for name, expected in FIXED_READER_SOURCES.items()\n        ):\n            raise ValueError\n    except (ValueError, TypeError, KeyError, StopIteration) as exc:\n        raise ValueError("scope.file_access_not_whitelisted") from exc\n    return {\n        "entry_functions": [\n            "reference_definition_v301.member_definition",\n            "reference_profile_v301.solo_profile",\n        ],\n        "reached_reader": "reference_registry_v3.member_spec -> artifact",\n        "literal_filenames": sorted(names),\n        "DISPATCH_members": sorted(dispatch),\n        "other_HASHES_granted": False,\n        "registered_request_is_entry": False,\n    }',
    "b2_isolation_proof": 'b2_isolation_proof(policy):\n    from .reference_check import static_proof\n    from .input_disposition import HASHES, sources as disposition_sources\n\n    disposition_sources()\n\n    graph, sources, gates, readers, trees = {}, {}, {}, [], {}\n    file_reads = {}\n    root = Path(__file__).parent\n    targets = [\n        (name, name + ".py", None)\n        for name in sorted(\n            set(IMPORTS)\n            | {module for module, _, _ in FIXED_READS}\n            | set(FILENAME_READS)\n        )\n    ]\n    targets.extend(FIXED_READS)\n    targets.extend(B_RELEASE_FIXED_READS)\n    for name, relative, expected in targets:\n        raw = (root / relative).read_bytes()\n        if expected is not None:\n            if sha256(raw) != expected:\n                raise ValueError("scope.file_access_not_whitelisted")\n            continue\n        sources[name + ".py"] = sha256(raw)\n        tree = ast.parse(raw)\n        trees[name] = tree\n        if name in FILENAME_READS:\n            continue\n        graph[name] = sorted(\n            {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}\n            | {\n                a.name\n                for n in ast.walk(tree)\n                if isinstance(n, ast.Import)\n                for a in n.names\n            }\n        )\n        if name in IMPORTS and not set(graph[name]).issubset(IMPORTS[name]):\n            raise ValueError("scope.static_import_not_whitelisted")\n        for node in ast.walk(tree):\n            if (\n                isinstance(node, ast.Call)\n                and isinstance(node.func, ast.Name)\n                and node.func.id in ("open", "eval", "exec", "__import__", "compile")\n            ):\n                raise ValueError("scope.dynamic_reader_or_code_forbidden")\n            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):\n                if node.func.attr in (\n                    "open",\n                    "read_text",\n                    "write_text",\n                    "write_bytes",\n                    "glob",\n                    "rglob",\n                ):\n                    raise ValueError("scope.file_access_not_whitelisted")\n                if node.func.attr == "read_bytes":\n                    file_reads[name] = file_reads.get(name, 0) + 1\n        for role, (module, function) in GATES.items():\n            if module != name:\n                continue\n            fn = next(\n                n\n                for n in tree.body\n                if isinstance(n, ast.FunctionDef) and n.name == function\n            )\n            body = (\n                fn.body[1:]\n                if isinstance(fn.body[0], ast.Expr)\n                and isinstance(fn.body[0].value, ast.Constant)\n                and isinstance(fn.body[0].value.value, str)\n                else fn.body\n            )\n            if function in ("integer_cash_valuation", "_tool"):\n                body = next(n.body for n in body if isinstance(n, ast.Try))\n            first = body[0]\n            if not (\n                isinstance(first, ast.Expr)\n                and isinstance(first.value, ast.Call)\n                and isinstance(first.value.func, ast.Name)\n                and first.value.func.id == "reject_b2_inputs"\n                and isinstance(first.value.args[-1], ast.Constant)\n                and first.value.args[-1].value == role\n            ):\n                raise ValueError("scope.guard_does_not_dominate_consumer")\n            gates[role] = {\n                "module": module,\n                "function": function,\n                "guard_line": first.lineno,\n            }\n        if name in ("reference_inputs", "scope_reader"):\n            for n in ast.walk(tree):\n                if (\n                    isinstance(n, ast.Call)\n                    and isinstance(n.func, ast.Attribute)\n                    and n.func.attr == "read_bytes"\n                ):\n                    readers.append({"module": name, "line": n.lineno})\n    if set(gates) != set(ROLES) or len(readers) != 2:\n        raise ValueError("scope.reader_or_role_set_changed")\n    # V7: the direct registered metadata read is scope_proof site 3, counted honestly.\n    # V7: the legacy compile ban above stays unchanged; there is no exception.\n    if file_reads != {\n        "b_release_context": 4,\n        "catalog_v21": 1,\n        "execution": 2,\n        "pipeline": 1,\n        "reference_inputs": 1,\n        "scope_proof": 3,\n        "scope_reader": 1,\n        "valuation": 1,\n        "k5": 2,\n        "execution_accounting": 1,\n        "execution_clock": 1,\n        "execution_closure": 2,\n        "reference_definition_v301": 1,\n        "reference_registry_v3": 1,\n    }:\n        raise ValueError("scope.file_access_not_whitelisted")\n    registry_scope = _candidate_registry_scope(trees, sources)\n    filename_scope = _filename_read_scope(trees, sources)\n    ref = static_proof()\n    # V7: new checks follow every legacy guard in its original order.\n    blindspot_scope = _call_blindspot_scope(trees)\n    adapter_scope = _b_release_adapter_scope(\n        trees["b_release_context"], trees["scope_proof"]\n    )\n    for name, relative, expected in B_RELEASE_ADAPTER_READS + B_RELEASE_IMPORT_READS:\n        raw = Path.read_bytes(root / relative)\n        if name == "contract" and raw != B_RELEASE_CONTRACT_TEMPLATE.encode("utf-8"):\n            raise ValueError("scope.file_access_not_whitelisted")\n        if sha256(raw) != expected:\n            raise ValueError("scope.file_access_not_whitelisted")\n        if (name, relative, expected) in B_RELEASE_IMPORT_READS:\n            sources[name + ".py"] = sha256(raw)\n            trees[name] = ast.parse(raw)\n    _call_blindspot_scope({name: trees[name] for name, _, _ in B_RELEASE_IMPORT_READS})\n    dependency_scope = _b_release_dependency_scope(trees, sources)\n    return {\n        "schema": "EVO884.B2-isolation-proof/v1",\n        "scope_ruling_sha256": HASHES["EVO883-EVO886-minimum-scope-ruling-v1.json"],\n        **policy.binding,\n        "source_files": sources,\n        "source_sha256": digest(sources),\n        "import_graph": graph,\n        "import_whitelist": {k: sorted(v) for k, v in IMPORTS.items()},\n        "guarded_consumers": gates,\n        "market_reader_sites": readers,\n        "strategy_market_symbol_whitelist": list(policy.profile["universe"])\n        + [policy.profile["portfolio"]["base_ticker"]],\n        "strategy_market_file_whitelist": "<frozen_symbol>.json, matching symbol header and SHA, exact supplied frozen date vector; no link/alias/path expansion",\n        "reference_file_whitelist": ref["read_whitelist"],\n        "k5_scoped_quote_read_whitelist": [\n            "k5/S2-field-receipt-v1.json",\n            "k5/VSNT-open-close-none.csv",\n        ],\n        "reference_benchmark_symbol": "QQQ",\n        "C13_registered_fixed_reads": [\n            {"module": module, "path": path, "sha256": expected}\n            for module, path, expected in FIXED_READS\n        ],\n        "B_release_adapter_scope": adapter_scope,\n        "C1_dependency_scope": dependency_scope,\n        "C1_call_blindspot_scope": blindspot_scope,\n        "C13_registry_call_scope": registry_scope,\n        "C13_filename_registration_scope": filename_scope,\n        "C13_coverage_boundary": "Registered 3+7 fixed reads only; existing transitive helper reads retain original mechanisms and are not claimed fully covered by this table",\n        "seal_status": "seal_pending",\n        "non_market_read_whitelist": {\n            **FILENAME_READS,\n            "catalog_v21": [\n                "catalog-v21/EVO893-B-noncash-catalog-v21.csv",\n                "catalog-v21/EVO893-B-CMI-guard-v21.json",\n                "catalog-v21/EVO883-v21-final-receipt.json",\n            ],\n            "execution": ["fee_params_x2.json", "fee_schedule.json"],\n            "pipeline": [\n                "predeclared_reference_registry.json",\n                "candidate_reference_manifest.json",\n                "meta_reference_manifest.json",\n            ],\n            "valuation": ["qqq-events-v1.csv"],\n            "scope_proof": ["current pinned Python sources"],\n        },\n        "B2_series_capability_for_strategy_roles": False,\n        "B2_only_readout_entry": "valuation.benchmark_valuation(symbol=VTI)",\n        "scope": "Pinned owned Python entrypoints and declared source/header identities; caller adapters and independent market-source correctness require separate acceptance. No arbitrary native-code sandbox claim.",\n        "runtime_consumable": False,\n        "C1_source_preflight": {\n            "dependency_closed": False,\n            "reason": "scope.preflight_required",\n        },\n        "certifiable": False,\n    }',
    "reference_execution_proof": 'reference_execution_proof(policy):\n    """Independent C09/C10 segment; old B2 entries retain their own names."""\n    from .reference_check import execution_proof\n\n    inherited = b2_isolation_proof(policy)\n    extension = execution_proof()\n    return dict(\n        schema="EVO884.ReferenceExecutionScope/v1",\n        C09_C10=extension,\n        C09_component_readers={\n            name: [r for r in extension["reader_sites"] if r["module"] == name]\n            for name in sorted(extension["source_files"])\n        },\n        C09_numeric_input_files=["raw.json", "rights.json", "adv.json", "cash.json"],\n        C09_fixed_input_files=[\n            {k: row[k] for k in ("module", "path", "sha256")}\n            for row in extension["reader_sites"]\n            if "path" in row\n        ],\n        shared_execution_source_sha256=inherited["source_sha256"],\n        shared_fixed_reads=inherited["C13_registered_fixed_reads"],\n        coverage_boundary="C09 four-file reader is separately registered before fact binding; the result worker consumes only the exact owned read facts and common-engine program, with individually registered metadata files; old component entries retain their original meanings",\n        seal_status="seal_pending",\n        runtime_consumable=False,\n    )',
    "noncash_isolation_proof": 'noncash_isolation_proof(policy):\n    """Inspect owned economic boundaries; this does not attest a real account."""\n    from .noncash_v3 import (\n        ROUTES,\n        CONSUMERS,\n        actor_ids,\n        ACCEPTED_CATALOG_SHA256,\n        CATALOG_REASON,\n    )\n\n    root = Path(__file__).parent\n    names = (\n        "noncash_v3",\n        "catalog_v21",\n        "catalog_members",\n        "reference_noncash",\n        "isolation",\n        "execution",\n        "valuation",\n        "k5",\n        "folds",\n    )\n    raw_sources = {name: (root / (name + ".py")).read_bytes() for name in names}\n    trees = {name: ast.parse(raw) for name, raw in raw_sources.items()}\n\n    def function(module, name):\n        return next(\n            n\n            for n in trees[module].body\n            if isinstance(n, ast.FunctionDef) and n.name == name\n        )\n\n    def calls(node, name):\n        return sorted(\n            n.lineno\n            for n in ast.walk(node)\n            if isinstance(n, ast.Call)\n            and isinstance(n.func, ast.Name)\n            and n.func.id == name\n        )\n\n    numeric = function("noncash_v3", "guarded_value")\n    guards = calls(numeric, "assert_consumer_symbols")\n    readers = calls(numeric, "reader")\n    if len(guards) != 1 or len(readers) != 1 or guards[0] >= readers[0]:\n        raise ValueError("B.static_numeric_guard_not_dominant")\n    economic = function("noncash_v3", "economic_values")\n    if min(calls(economic, "assert_consumer_symbols"), default=10**9) >= min(\n        calls(economic, "guarded_value"), default=-1\n    ):\n        raise ValueError("B.static_batch_guard_missing")\n    # A pure injected reader is the only numeric boundary in this module.\n    forbidden = {\n        "open",\n        "read_bytes",\n        "read_text",\n        "write_bytes",\n        "write_text",\n        "glob",\n        "rglob",\n        "eval",\n        "exec",\n        "__import__",\n    }\n    for n in ast.walk(trees["noncash_v3"]):\n        if isinstance(n, ast.Call):\n            name = (\n                n.func.id\n                if isinstance(n.func, ast.Name)\n                else n.func.attr\n                if isinstance(n.func, ast.Attribute)\n                else ""\n            )\n            if name in forbidden:\n                raise ValueError("B.static_unregistered_reader")\n    acquisition = function("noncash_v3", "acquisition_check")\n    if (\n        len(calls(acquisition, "zero_exposure")) != 2\n        or not calls(acquisition, "zero_origin")\n        or not calls(acquisition, "checked_guard")\n    ):\n        raise ValueError("B.static_acquisition_induction_missing")\n    calibration = function("execution", "_v2_calibration_rows")\n    voluntary = function("execution", "voluntary_trade_gate")\n    valuation = function("valuation", "integer_cash_valuation")\n    for node in (calibration, voluntary, valuation):\n        if not calls(node, "assert_consumer_symbols"):\n            raise ValueError("B.static_consumer_connection_missing")\n    factor_cash = function("valuation", "factor_cash_valuation")\n    if not any(\n        isinstance(n, ast.Call)\n        and isinstance(n.func, ast.Name)\n        and n.func.id == "integer_cash_valuation"\n        and any(\n            k.arg == "factor_scope"\n            and isinstance(k.value, ast.Constant)\n            and k.value.value is True\n            for k in n.keywords\n        )\n        for n in ast.walk(factor_cash)\n    ):\n        raise ValueError("B.static_factor_cash_scope_not_bound")\n    marks = [\n        n.lineno\n        for n in ast.walk(valuation)\n        if isinstance(n, ast.Subscript)\n        and isinstance(n.slice, ast.Constant)\n        and n.slice.value == "marks"\n    ]\n    if min(calls(valuation, "assert_consumer_symbols")) >= min(marks, default=-1):\n        raise ValueError("B.static_valuation_read_precedes_guard")\n    quote = function("k5", "vsnt_quote")\n    raises = [n.lineno for n in ast.walk(quote) if isinstance(n, ast.Raise)]\n    reads = [\n        n.lineno\n        for n in ast.walk(quote)\n        if isinstance(n, ast.Call)\n        and isinstance(n.func, ast.Attribute)\n        and n.func.attr == "read_bytes"\n    ]\n    if not raises or min(raises) >= min(reads, default=-1):\n        raise ValueError("B.static_v3_legacy_reader_not_closed")\n    files = {n + ".py": sha256(b) for n, b in raw_sources.items()}\n    payload = dict(\n        schema="EVO900.factor-arm-noncash-static-proof/v3",\n        source_files=files,\n        source_sha256=digest(files),\n        actor_ids=list(actor_ids(policy)),\n        acquisition_routes=sorted(ROUTES),\n        economic_consumer_roles=sorted(CONSUMERS),\n        numeric_guard_line=guards[0],\n        injected_reader_line=readers[0],\n        B_catalog_sha256=ACCEPTED_CATALOG_SHA256,\n        B_catalog_reason=CATALOG_REASON,\n        scope="Owned factor and virtual-monitor input boundaries, supplied complete source states, and trusted callbacks; not an arbitrary Python OS sandbox or real-account attestation.",\n        reference_producer_proof_completed=False,\n        reference_producer_separate_mechanism_proof_available=True,\n        reference_producer_real_runtime_proven=False,\n        factor_cash_entrypoint="factor_cash_valuation",\n        generic_accounting_is_factor_proof=False,\n        real_origin_proofs=None,\n        runtime_consumable=False,\n        certifiable=False,\n        **policy.binding,\n    )\n    return dict(payload, static_proof_sha256=digest(payload))',
    "b2_manifest_check": 'b2_manifest_check(manifest, policy):\n    """An unavailable B2 entry is complete metadata, never available market data."""\n    from .contract import is_sha\n    from .conventions import FIXTURES, load_conventions\n    from .input_disposition import sources\n    import json\n\n    ruling = json.loads(sources()["EVO883-EVO886-minimum-scope-ruling-v1.json"])\n    expected_interface = (\n        load_conventions(FIXTURES / "conventions-v1.0.1.json").raw_sha256\n        if policy.document["version"] in ("v2.0.0", "v3.0.0")\n        else policy.raw_sha256\n    )\n    if ruling["interface_sha256"] != expected_interface:\n        raise ValueError("scope.ruling_identity_mismatch")\n    proof = b2_isolation_proof(policy)\n    if (\n        not isinstance(manifest, dict)\n        or manifest.get("status") != "unavailable"\n        or not isinstance(manifest.get("reason"), str)\n        or not manifest["reason"]\n        or not isinstance(manifest.get("missing_fields"), list)\n        or not manifest["missing_fields"]\n        or not is_sha(manifest.get("source_sha256"))\n        or manifest.get("dates") != list(policy.calendar)\n        or manifest.get("calendar_sha256") != digest(list(policy.calendar))\n        or manifest.get("affected_scope") != ["B2"]\n        or manifest.get("strategy_dependencies") != {r: [] for r in ROLES}\n        or manifest.get("isolation_source_sha256") != proof["source_sha256"]\n        or manifest.get("use_suffix")\n        or manifest.get("fallback")\n    ):\n        raise ValueError("scope.B2_isolation_manifest_missing_or_invalid")\n    return {\n        "value": None,\n        "available": False,\n        "reason": manifest["reason"],\n        "input_binding_present": True,\n        "all_dates_retained": True,\n        "source_sha256": manifest["source_sha256"],\n        "isolation_source_sha256": proof["source_sha256"],\n    }',
    "_c1_entry_structure": '_c1_entry_structure(raw, auditor_sha256):\n    """Complete reviewed literal template, including docstrings; no hash slot."""\n    if ast.dump(ast.parse(raw), include_attributes=False) != ast.dump(\n        ast.parse(C1_ENTRY_TEMPLATE), include_attributes=False\n    ):\n        raise ValueError("scope.preflight_entry_structure_mismatch")\n    return dict(\n        path=C1_ENTRY_REGISTRATION["path"],\n        kind="complete_AST",\n        placeholder_count=0,\n        auditor_sha256=auditor_sha256,\n        docstrings_compared=True,\n        execution_trust_added=False,\n        consistency="post_execution_only",\n    )',
    "_c1_snapshot_structure": '_c1_snapshot_structure(snapshot):\n    if (\n        type(snapshot).__name__ != "_Snapshot"\n        or type(snapshot).__module__ != "__main__"\n    ):\n        raise ValueError("scope.preflight_evidence_required")\n    if snapshot.entry_path() != snapshot.path(C1_ENTRY_REGISTRATION["path"]):\n        raise ValueError("scope.host_entry_path_mismatch")\n    if snapshot.validate.__func__.__code__.co_filename != snapshot.entry_path():\n        raise ValueError("scope.preflight_evidence_required")\n    if b2_isolation_proof_from_snapshot.__code__.co_filename != snapshot.path(\n        "scope_proof.py"\n    ):\n        raise ValueError("scope.preflight_loading_mismatch")\n    snapshot.validate()\n    entry = _c1_entry_structure(\n        snapshot.entry_source(), snapshot.identity("scope_proof.py")\n    )\n    _b_release_adapter_scope(\n        ast.parse(snapshot.raw("b_release_context.py")),\n        ast.parse(snapshot.raw("scope_proof.py")),\n    )\n    return entry',
    "_c1_reference_static": '_c1_reference_static(snapshot):\n    from .reference_check import MODULES\n\n    graph, sources, reads = {}, {}, []\n    extension = {\n        "execution_receipts.input_data",\n        "execution_receipts.input_guard",\n        "execution_receipts.input_reader",\n        "execution_receipts.reference_result",\n        "execution_receipts.replay_guard",\n        "execution_receipts.input_facts",\n        "reference_execution",\n        "conventions",\n        "contract",\n    }\n    for name, allowed in MODULES.items():\n        raw = snapshot.raw(name.replace(".", "/") + ".py")\n        tree = ast.parse(raw)\n        for statement in tree.body:\n            if isinstance(\n                statement, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)\n            ):\n                continue\n            if (\n                isinstance(statement, ast.Expr)\n                and isinstance(statement.value, ast.Constant)\n                and isinstance(statement.value.value, str)\n            ):\n                continue\n            if isinstance(statement, ast.Assign):\n                try:\n                    ast.literal_eval(statement.value)\n                    continue\n                except (ValueError, TypeError):\n                    pass\n            if (\n                name in {"reference_producer", "reference_producer_v3"}\n                and isinstance(statement, ast.If)\n                and ast.unparse(statement.test) == "__name__ == \'__main__\'"\n            ):\n                continue\n            raise ValueError("reference.static_import_time_effect_forbidden")\n        imports = set()\n        for node in ast.walk(tree):\n            if isinstance(node, ast.Import):\n                imports.update(n.name for n in node.names)\n            if isinstance(node, ast.ImportFrom):\n                imports.add(node.module)\n            if isinstance(node, ast.Call):\n                call = (\n                    node.func.id\n                    if isinstance(node.func, ast.Name)\n                    else (\n                        node.func.attr if isinstance(node.func, ast.Attribute) else ""\n                    )\n                )\n                if call in {\n                    "eval",\n                    "exec",\n                    "__import__",\n                    "compile",\n                    "open",\n                    "read_text",\n                    "write_text",\n                    "write_bytes",\n                    "unlink",\n                    "rename",\n                }:\n                    raise ValueError("reference.static_call_forbidden")\n                if call == "read_bytes":\n                    if name not in {\n                        "reference_inputs",\n                        "execution_receipts.input_reader",\n                    }:\n                        raise ValueError("reference.static_reader_forbidden")\n                    reads.append(\n                        {\n                            "module": name,\n                            "line": node.lineno,\n                            "roles": (\n                                ["panel", "benchmark", "profile"]\n                                if name == "reference_inputs"\n                                else ["raw", "rights", "adv", "cash"]\n                            ),\n                        }\n                    )\n        if not imports.issubset(allowed):\n            raise ValueError("reference.static_dependency_forbidden")\n        graph[name] = sorted(imports)\n        sources[name + ".py"] = snapshot.identity(name.replace(".", "/") + ".py")\n        if name in {"reference_producer", "reference_producer_v3"}:\n            main = next(\n                n\n                for n in tree.body\n                if isinstance(n, ast.FunctionDef) and n.name == "main"\n            )\n            calls = {\n                n.func.id: n.lineno\n                for n in ast.walk(main)\n                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)\n            }\n            if calls.get("install", 10**9) >= calls.get("prepare", -1):\n                raise ValueError("reference.audit_hook_must_precede_data_reads")\n            if name == "reference_producer_v3":\n                entry = next(\n                    n\n                    for n in tree.body\n                    if isinstance(n, ast.FunctionDef) and n.name == "execution_main"\n                )\n                result_entry = next(\n                    n\n                    for n in tree.body\n                    if isinstance(n, ast.FunctionDef) and n.name == "result_main"\n                )\n                release_entry = next(\n                    n\n                    for n in tree.body\n                    if isinstance(n, ast.FunctionDef) and n.name == "worker_release"\n                )\n                for node in ast.walk(tree):\n                    if isinstance(node, ast.ImportFrom) and node.module in extension:\n                        if not any(\n                            e.lineno < node.lineno <= e.end_lineno\n                            for e in (entry, result_entry, release_entry)\n                        ):\n                            raise ValueError("reference.execution_import_outside_entry")\n                calls = {\n                    n.func.id: n.lineno\n                    for n in ast.walk(entry)\n                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)\n                }\n                if calls.get("install_execution", 10**9) >= calls.get(\n                    "read_execution", -1\n                ):\n                    raise ValueError("reference.audit_hook_must_precede_data_reads")\n                for worker, installer in (\n                    (entry, "install_execution"),\n                    (result_entry, "install_result"),\n                ):\n                    sites = {\n                        n.func.id: n.lineno\n                        for n in ast.walk(worker)\n                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)\n                    }\n                    if sites.get("worker_release", 10**9) >= sites.get(installer, -1):\n                        raise ValueError("B.release_context_required")\n    return {\n        # Keep the original preparation entry\'s graph separately named. The\n        # complete module graph and the new dispatch graph are also published;\n        # no source bytes or source identities are excluded from the proof.\n        "import_graph": {\n            name: [dep for dep in deps if dep not in extension]\n            for name, deps in graph.items()\n            if name not in extension\n        },\n        "module_import_graph": graph,\n        "execution_preparation_import_graph": {\n            name: [\n                dep\n                for dep in deps\n                if dep\n                not in {\n                    "execution_receipts.reference_result",\n                    "execution_receipts.replay_guard",\n                    "execution_receipts.input_facts",\n                    "reference_execution",\n                    "conventions",\n                    "contract",\n                }\n            ]\n            for name, deps in graph.items()\n            if name\n            in {\n                "execution_receipts.input_data",\n                "execution_receipts.input_guard",\n                "execution_receipts.input_reader",\n                "reference_producer_v3",\n            }\n        },\n        "execution_result_import_graph": {\n            "reference_producer_v3": [\n                dep\n                for dep in graph["reference_producer_v3"]\n                if dep\n                in {\n                    "execution_receipts.input_data",\n                    "execution_receipts.reference_result",\n                    "execution_receipts.replay_guard",\n                    "execution_receipts.input_facts",\n                    "reference_execution",\n                    "conventions",\n                    "contract",\n                }\n            ]\n        },\n        "source_files": sources,\n        "reader_sites": [r for r in reads if r["module"] == "reference_inputs"],\n        "execution_preparation_reader_sites": [\n            r for r in reads if r["module"] == "execution_receipts.input_reader"\n        ],\n        "source_sha256": snapshot.digest(sources),\n        "read_whitelist": {\n            "panel": "panel.json",\n            "benchmark": "benchmark.json",\n            "profile": "profile.json",\n        },\n        "execution_preparation_read_whitelist": {\n            "raw": "raw.json",\n            "rights": "rights.json",\n            "adv": "adv.json",\n            "cash": "cash.json",\n        },\n        "forbidden_inputs": [\n            "candidate_returns",\n            "candidate_SR",\n            "pool",\n            "meta_returns",\n            "meta_SR",\n        ],\n        "shared_splitter_sha256": sources["fold_split.py"],\n        "scope": "static proof for pinned trusted source, not an arbitrary Python OS sandbox",\n    }',
    "b2_isolation_proof_from_snapshot": 'b2_isolation_proof_from_snapshot(policy, snapshot):\n    entry_consistency = _c1_snapshot_structure(snapshot)\n    from .input_disposition import HASHES\n\n    if any(\n        snapshot.identity("fixtures/disposition/" + name) != expected\n        for name, expected in HASHES.items()\n    ):\n        raise ValueError("data.disposition_identity_mismatch")\n\n    graph, sources, gates, readers, trees = {}, {}, {}, [], {}\n    file_reads = {}\n    targets = [\n        (name, name + ".py", None)\n        for name in sorted(\n            set(IMPORTS)\n            | {module for module, _, _ in FIXED_READS}\n            | set(FILENAME_READS)\n        )\n    ]\n    targets.extend(FIXED_READS)\n    targets.extend(B_RELEASE_FIXED_READS)\n    for name, relative, expected in targets:\n        raw = snapshot.raw(relative)\n        if expected is not None:\n            if snapshot.identity(relative) != expected:\n                raise ValueError("scope.file_access_not_whitelisted")\n            continue\n        sources[name + ".py"] = snapshot.identity(relative)\n        tree = ast.parse(raw)\n        trees[name] = tree\n        if name in FILENAME_READS:\n            continue\n        graph[name] = sorted(\n            {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}\n            | {\n                a.name\n                for n in ast.walk(tree)\n                if isinstance(n, ast.Import)\n                for a in n.names\n            }\n        )\n        if name in IMPORTS and not set(graph[name]).issubset(IMPORTS[name]):\n            raise ValueError("scope.static_import_not_whitelisted")\n        for node in ast.walk(tree):\n            if (\n                isinstance(node, ast.Call)\n                and isinstance(node.func, ast.Name)\n                and node.func.id in ("open", "eval", "exec", "__import__", "compile")\n            ):\n                raise ValueError("scope.dynamic_reader_or_code_forbidden")\n            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):\n                if node.func.attr in (\n                    "open",\n                    "read_text",\n                    "write_text",\n                    "write_bytes",\n                    "glob",\n                    "rglob",\n                ):\n                    raise ValueError("scope.file_access_not_whitelisted")\n                if node.func.attr == "read_bytes":\n                    file_reads[name] = file_reads.get(name, 0) + 1\n        for role, (module, function) in GATES.items():\n            if module != name:\n                continue\n            fn = next(\n                n\n                for n in tree.body\n                if isinstance(n, ast.FunctionDef) and n.name == function\n            )\n            body = (\n                fn.body[1:]\n                if isinstance(fn.body[0], ast.Expr)\n                and isinstance(fn.body[0].value, ast.Constant)\n                and isinstance(fn.body[0].value.value, str)\n                else fn.body\n            )\n            if function in ("integer_cash_valuation", "_tool"):\n                body = next(n.body for n in body if isinstance(n, ast.Try))\n            first = body[0]\n            if not (\n                isinstance(first, ast.Expr)\n                and isinstance(first.value, ast.Call)\n                and isinstance(first.value.func, ast.Name)\n                and first.value.func.id == "reject_b2_inputs"\n                and isinstance(first.value.args[-1], ast.Constant)\n                and first.value.args[-1].value == role\n            ):\n                raise ValueError("scope.guard_does_not_dominate_consumer")\n            gates[role] = {\n                "module": module,\n                "function": function,\n                "guard_line": first.lineno,\n            }\n        if name in ("reference_inputs", "scope_reader"):\n            for n in ast.walk(tree):\n                if (\n                    isinstance(n, ast.Call)\n                    and isinstance(n.func, ast.Attribute)\n                    and n.func.attr == "read_bytes"\n                ):\n                    readers.append({"module": name, "line": n.lineno})\n    if set(gates) != set(ROLES) or len(readers) != 2:\n        raise ValueError("scope.reader_or_role_set_changed")\n    # V7: the direct registered metadata read is scope_proof site 3, counted honestly.\n    # V7: the legacy compile ban above stays unchanged; there is no exception.\n    if file_reads != {\n        "b_release_context": 4,\n        "catalog_v21": 1,\n        "execution": 2,\n        "pipeline": 1,\n        "reference_inputs": 1,\n        "scope_proof": 3,\n        "scope_reader": 1,\n        "valuation": 1,\n        "k5": 2,\n        "execution_accounting": 1,\n        "execution_clock": 1,\n        "execution_closure": 2,\n        "reference_definition_v301": 1,\n        "reference_registry_v3": 1,\n    }:\n        raise ValueError("scope.file_access_not_whitelisted")\n    registry_scope = _candidate_registry_scope(trees, sources)\n    filename_scope = _filename_read_scope(trees, sources)\n    ref = _c1_reference_static(snapshot)\n    # V7: new checks follow every legacy guard in its original order.\n    blindspot_scope = _call_blindspot_scope(trees)\n    adapter_scope = _b_release_adapter_scope(\n        trees["b_release_context"], trees["scope_proof"]\n    )\n    for name, relative, expected in B_RELEASE_ADAPTER_READS + B_RELEASE_IMPORT_READS:\n        raw = snapshot.raw(relative)\n        if name == "contract" and raw != B_RELEASE_CONTRACT_TEMPLATE.encode("utf-8"):\n            raise ValueError("scope.file_access_not_whitelisted")\n        if snapshot.identity(relative) != expected:\n            raise ValueError("scope.file_access_not_whitelisted")\n        if (name, relative, expected) in B_RELEASE_IMPORT_READS:\n            sources[name + ".py"] = snapshot.identity(relative)\n            trees[name] = ast.parse(raw)\n    _call_blindspot_scope({name: trees[name] for name, _, _ in B_RELEASE_IMPORT_READS})\n    dependency_scope = _b_release_dependency_scope(trees, sources)\n    return {\n        "schema": "EVO884.B2-isolation-proof/v1",\n        "scope_ruling_sha256": HASHES["EVO883-EVO886-minimum-scope-ruling-v1.json"],\n        **snapshot.policy_binding(),\n        "source_files": sources,\n        "source_sha256": snapshot.digest(sources),\n        "import_graph": graph,\n        "import_whitelist": {k: sorted(v) for k, v in IMPORTS.items()},\n        "guarded_consumers": gates,\n        "market_reader_sites": readers,\n        "strategy_market_symbol_whitelist": list(snapshot.policy_profile()["universe"])\n        + [snapshot.policy_profile()["portfolio"]["base_ticker"]],\n        "strategy_market_file_whitelist": "<frozen_symbol>.json, matching symbol header and SHA, exact supplied frozen date vector; no link/alias/path expansion",\n        "reference_file_whitelist": ref["read_whitelist"],\n        "k5_scoped_quote_read_whitelist": [\n            "k5/S2-field-receipt-v1.json",\n            "k5/VSNT-open-close-none.csv",\n        ],\n        "reference_benchmark_symbol": "QQQ",\n        "C13_registered_fixed_reads": [\n            {"module": module, "path": path, "sha256": expected}\n            for module, path, expected in FIXED_READS\n        ],\n        "B_release_adapter_scope": adapter_scope,\n        "C1_dependency_scope": dependency_scope,\n        "C1_call_blindspot_scope": blindspot_scope,\n        "C13_registry_call_scope": registry_scope,\n        "C13_filename_registration_scope": filename_scope,\n        "C13_coverage_boundary": "Registered 3+7 fixed reads only; existing transitive helper reads retain original mechanisms and are not claimed fully covered by this table",\n        "seal_status": "seal_pending",\n        "non_market_read_whitelist": {\n            **FILENAME_READS,\n            "catalog_v21": [\n                "catalog-v21/EVO893-B-noncash-catalog-v21.csv",\n                "catalog-v21/EVO893-B-CMI-guard-v21.json",\n                "catalog-v21/EVO883-v21-final-receipt.json",\n            ],\n            "execution": ["fee_params_x2.json", "fee_schedule.json"],\n            "pipeline": [\n                "predeclared_reference_registry.json",\n                "candidate_reference_manifest.json",\n                "meta_reference_manifest.json",\n            ],\n            "valuation": ["qqq-events-v1.csv"],\n            "scope_proof": ["current pinned Python sources"],\n        },\n        "B2_series_capability_for_strategy_roles": False,\n        "B2_only_readout_entry": "valuation.benchmark_valuation(symbol=VTI)",\n        "scope": "Pinned owned Python entrypoints and declared source/header identities; caller adapters and independent market-source correctness require separate acceptance. No arbitrary native-code sandbox claim.",\n        "runtime_consumable": False,\n        "C1_source_preflight": {\n            "dependency_closed": False,\n            "reason": "scope.preflight_finalization_required",\n            "entry_consistency": entry_consistency,\n        },\n        "certifiable": False,\n    }',
}


def _b_release_audit_structure(tree):
    """The audit source accepts only its reviewed functions and literal data."""
    expected_bindings = {
        "GATES": GATES,
        "IMPORTS": IMPORTS,
        "FIXED_READS": FIXED_READS,
        "B_RELEASE_FIXED_READS": B_RELEASE_FIXED_READS,
        "B_RELEASE_ADAPTER_READS": B_RELEASE_ADAPTER_READS,
        "B_RELEASE_PATH_ONLY_READS": B_RELEASE_PATH_ONLY_READS,
        "B_RELEASE_MODULE_TEMPLATE": B_RELEASE_MODULE_TEMPLATE,
        "B_RELEASE_FIXED_LITERALS": B_RELEASE_FIXED_LITERALS,
        "B_RELEASE_DEPENDENCY_SOURCES": B_RELEASE_DEPENDENCY_SOURCES,
        "B_RELEASE_IMPORT_READS": B_RELEASE_IMPORT_READS,
        "B_RELEASE_CONTRACT_TEMPLATE": B_RELEASE_CONTRACT_TEMPLATE,
        "FIXED_READER_SOURCES": FIXED_READER_SOURCES,
        "FILENAME_READS": FILENAME_READS,
        "FILENAME_SOURCE_IDENTITIES": FILENAME_SOURCE_IDENTITIES,
        "B_RELEASE_AUDIT_FUNCTIONS": B_RELEASE_AUDIT_FUNCTIONS,
        "C1_ENTRY_TEMPLATE": C1_ENTRY_TEMPLATE,
        "C1_ENTRY_REGISTRATION": C1_ENTRY_REGISTRATION,
    }
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)]
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    if len(tree.body) != len(assignments) + len(functions) + len(imports) + 1:
        raise ValueError
    if not isinstance(tree.body[0], ast.Expr) or ast.dump(tree.body[0]) != ast.dump(
        ast.parse(
            "'Static import/guard/read-scope receipt for owned trusted strategy interfaces.'"
        ).body[0]
    ):
        raise ValueError
    if [ast.dump(n) for n in imports] != [
        ast.dump(n)
        for n in ast.parse(
            "import ast\nfrom pathlib import Path\nfrom .contract import digest, sha256\nfrom .input_scope import ROLES"
        ).body
    ]:
        raise ValueError
    seen = set()
    for node in assignments:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise ValueError
        name = node.targets[0].id
        if (
            name in seen
            or name not in expected_bindings
            or ast.literal_eval(node.value) != expected_bindings[name]
        ):
            raise ValueError
        seen.add(name)
    if seen != set(expected_bindings):
        raise ValueError
    if len(functions) != len(B_RELEASE_AUDIT_FUNCTIONS) or {
        node.name: ast.dump(node, include_attributes=False) for node in functions
    } != {
        name: ast.dump(ast.parse("def " + source).body[0], include_attributes=False)
        for name, source in B_RELEASE_AUDIT_FUNCTIONS.items()
    }:
        raise ValueError


def _b_release_dependency_scope(trees, sources):
    """Closed source identities plus namespace and method binding checks."""
    protected = {
        "_read_trusted_release",
        "_fail",
        "_json",
        "_utc",
        "_canonical",
        "_pairs",
        "_constant",
        "sha256",
        "ISSUE",
        "json",
        "datetime",
        "Path",
        "pathlib",
        "__file__",
        "__builtins__",
        "type",
        "str",
        "dict",
        "int",
        "set",
        "any",
        "bytes",
        "len",
        "ValueError",
        "TypeError",
        "UnicodeError",
        "KeyError",
        "IndexError",
        "NameError",
        "AttributeError",
        "OSError",
        "RuntimeError",
    }
    methods = {
        "resolve",
        "read_bytes",
        "parent",
        "co_filename",
        "__code__",
        "loads",
        "dumps",
        "strptime",
        "__dict__",
        "__globals__",
    }
    if set(B_RELEASE_DEPENDENCY_SOURCES) != {
        name + ".py"
        for name in trees
        if name not in {"scope_proof", "b_release_context"}
    } or any(
        sources.get(name) != expected
        for name, expected in B_RELEASE_DEPENDENCY_SOURCES.items()
    ):
        raise ValueError("scope.file_access_not_whitelisted")
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and node.id in protected
            ):
                # The reviewed literal ISSUE declaration is the single binding.
                if not (
                    module == "b_release_context"
                    and node.id == "ISSUE"
                    and isinstance(node.ctx, ast.Store)
                ):
                    raise ValueError("scope.file_access_not_whitelisted")
            if isinstance(node, ast.Global) and set(node.names) & protected:
                raise ValueError("scope.file_access_not_whitelisted")
            if isinstance(node, ast.Attribute):
                if node.attr in {"__dict__", "__globals__"} or (
                    isinstance(node.ctx, (ast.Store, ast.Del))
                    and node.attr in protected | methods
                ):
                    raise ValueError("scope.file_access_not_whitelisted")
                if (
                    node.attr == "modules"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "sys"
                ):
                    raise ValueError("scope.file_access_not_whitelisted")
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if name in {
                    "globals",
                    "locals",
                    "vars",
                    "setattr",
                    "delattr",
                    "__setattr__",
                    "__delattr__",
                }:
                    ordinary = (
                        module in {"execution_accounting", "execution_cash"}
                        and name in {"setattr", "__setattr__"}
                        and len(node.args) == 3
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == "self"
                    )
                    # This existing ordinary-field operation is also byte-fixed.
                    if not ordinary:
                        raise ValueError("scope.file_access_not_whitelisted")
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = node.value
                if (
                    isinstance(value, (ast.Name, ast.Attribute))
                    and not (
                        isinstance(value, ast.Attribute)
                        and value.attr == "parent"
                        and isinstance(value.value, ast.Call)
                        and isinstance(value.value.func, ast.Name)
                        and value.value.func.id == "Path"
                    )
                    and any(
                        isinstance(n, ast.Name)
                        and n.id
                        in {
                            "Path",
                            "pathlib",
                            "_read_trusted_release",
                            "_fail",
                            "_json",
                            "_utc",
                            "_canonical",
                        }
                        for n in ast.walk(value)
                    )
                ):
                    raise ValueError("scope.file_access_not_whitelisted")
    return dict(
        module_count=len(trees),
        fixed_source_count=len(B_RELEASE_DEPENDENCY_SOURCES),
        hits=[],
        unresolved_changes=[],
        docstrings_compared=True,
    )


def _b_release_adapter_scope(tree, audit_tree):
    """Exact call ASTs, fixed original loop, and self-read SHA-only use."""
    try:
        _b_release_audit_structure(audit_tree)
        expected_source = B_RELEASE_MODULE_TEMPLATE
        for index, value in reversed(list(enumerate(B_RELEASE_FIXED_LITERALS))):
            expected_source = expected_source.replace(
                "V8_FIXED_LITERAL_" + str(index), value
            )
        expected_tree = ast.parse(expected_source)
        if ast.dump(tree, include_attributes=False) != ast.dump(
            expected_tree, include_attributes=False
        ):
            raise ValueError
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
            "self": "Path.read_bytes(self_path)",
            "original": '(Path(__file__).parent / "b_release_originals" / name).read_bytes()',
        }
        if len(reads) != 3 or {ast.dump(n) for n in reads} != {
            ast.dump(ast.parse(expr, mode="eval").body) for expr in expressions.values()
        }:
            raise ValueError
        # V7: the self-read argument and its co_filename provenance are exact ASTs.
        # No literal, caller/env path or descriptor-call alternative is allowed.
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
            'try:\n    self_path = Path(_read_trusted_release.__code__.co_filename).resolve()\n    if type(__file__) is not str or self_path != Path(__file__).resolve():\n        _fail("acceptance_mismatch")\nexcept (NameError, AttributeError, OSError, RuntimeError, TypeError) as exc:\n    raise ValueError("B.release_context_acceptance_mismatch") from exc\n'
        ).body
        binding = ast.parse(
            'try:\n    self_raw = Path.read_bytes(self_path)\nexcept OSError as exc:\n    raise ValueError("B.release_context_acceptance_mismatch") from exc\nimplementation_id = sha256(self_raw)\n'
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
        if (
            sum(isinstance(n, ast.Name) and n.id == "compile" for n in ast.walk(tree))
            != 0
        ):
            raise ValueError
        if (
            sum(
                isinstance(n, ast.Name)
                and n.id == "self_raw"
                and isinstance(n.ctx, ast.Load)
                for n in ast.walk(fn)
            )
            != 1
        ):
            raise ValueError
        if (
            sum(
                isinstance(n, ast.Name)
                and n.id == "self_path"
                and isinstance(n.ctx, ast.Store)
                for n in ast.walk(fn)
            )
            != 1
        ):
            raise ValueError
        audit_fn = next(
            n
            for n in audit_tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "b2_isolation_proof"
        )
        audit_loop = ast.parse(
            'for name, relative, expected in B_RELEASE_ADAPTER_READS + B_RELEASE_IMPORT_READS:\n    raw = Path.read_bytes(root / relative)\n    if name == "contract" and raw != B_RELEASE_CONTRACT_TEMPLATE.encode("utf-8"):\n        raise ValueError("scope.file_access_not_whitelisted")\n    if sha256(raw) != expected:\n        raise ValueError("scope.file_access_not_whitelisted")\n    if (name, relative, expected) in B_RELEASE_IMPORT_READS:\n        sources[name + ".py"] = sha256(raw)\n        trees[name] = ast.parse(raw)'
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
        "self_read_argument": "self_path = Path(_read_trusted_release.__code__.co_filename).resolve()",
        "self_read_use": "co_filename / resolved __file__ equality; fixed self bytes SHA -> implementation_id",
        "import_filename_path_binding": True,
        "post_import_process_tamper_defense": False,
        "additional_fixed_audit_read_sites": 1,
        "additional_fixed_compile_sites": 0,
        "dynamic_code_exceptions": [],
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


def _call_descriptor_forbidden(node):
    forbidden = ("open", "eval", "exec", "__import__", "compile", "read_bytes")
    if not isinstance(node, ast.Attribute) or node.attr != "__call__":
        return False
    value = node.value
    return (
        isinstance(value, ast.Name)
        and value.id in forbidden
        or isinstance(value, ast.Attribute)
        and value.attr in forbidden
    )


def _call_blindspot_scope(trees):
    """V7: no exceptions for descriptor calls in any inspected module."""
    for module, tree in sorted(trees.items()):
        for node in ast.walk(tree):
            if _call_descriptor_forbidden(node):
                raise ValueError("scope.dynamic_reader_or_code_forbidden")
    return {
        "modules": sorted(trees),
        "module_count": len(trees),
        "hits": [],
        "exceptions": [],
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
    # V7: the direct registered metadata read is scope_proof site 3, counted honestly.
    # V7: the legacy compile ban above stays unchanged; there is no exception.
    if file_reads != {
        "b_release_context": 4,
        "catalog_v21": 1,
        "execution": 2,
        "pipeline": 1,
        "reference_inputs": 1,
        "scope_proof": 3,
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
    # V7: new checks follow every legacy guard in its original order.
    blindspot_scope = _call_blindspot_scope(trees)
    adapter_scope = _b_release_adapter_scope(
        trees["b_release_context"], trees["scope_proof"]
    )
    for name, relative, expected in B_RELEASE_ADAPTER_READS + B_RELEASE_IMPORT_READS:
        raw = Path.read_bytes(root / relative)
        if name == "contract" and raw != B_RELEASE_CONTRACT_TEMPLATE.encode("utf-8"):
            raise ValueError("scope.file_access_not_whitelisted")
        if sha256(raw) != expected:
            raise ValueError("scope.file_access_not_whitelisted")
        if (name, relative, expected) in B_RELEASE_IMPORT_READS:
            sources[name + ".py"] = sha256(raw)
            trees[name] = ast.parse(raw)
    _call_blindspot_scope({name: trees[name] for name, _, _ in B_RELEASE_IMPORT_READS})
    dependency_scope = _b_release_dependency_scope(trees, sources)
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
        "C1_dependency_scope": dependency_scope,
        "C1_call_blindspot_scope": blindspot_scope,
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
        "C1_source_preflight": {
            "dependency_closed": False,
            "reason": "scope.preflight_required",
        },
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


C1_ENTRY_TEMPLATE = '"""Controlled C1 source preflight; independent review binds this artifact."""\n\nimport sys\n\n_EVENTS = []\n_VERIFIED = False\n_PHASE = "startup"\n_ALLOWED_IMPORTS = set()\n\n\ndef _audit(event, args):\n    if event == "import":\n        name = args[0]\n        _EVENTS.append(\n            dict(sequence=len(_EVENTS), event=event, module=name, phase=_PHASE)\n        )\n        if name == "qlab" or name.startswith("qlab."):\n            if not _VERIFIED or name not in _ALLOWED_IMPORTS:\n                raise RuntimeError("scope.preflight_import_not_registered")\n    elif event == "open" and isinstance(args[0], str):\n        _EVENTS.append(\n            dict(sequence=len(_EVENTS), event=event, path=args[0], phase=_PHASE)\n        )\n\n\nsys.addaudithook(_audit)\nif any(name == "qlab" or name.startswith("qlab.") for name in sys.modules):\n    raise SystemExit("scope.preflight_candidate_already_loaded")\nif not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):\n    raise SystemExit("scope.preflight_isolation_required")\n\nimport base64  # noqa: E402\nimport hashlib  # noqa: E402 - isolation and audit checks precede other imports\nimport importlib.machinery  # noqa: E402\nimport json  # noqa: E402\nimport os  # noqa: E402\nimport stat  # noqa: E402\nimport tempfile  # noqa: E402\n\n\nSOURCE_FILES = (\n    "../../tools/c1_source_preflight.py",\n    "../__init__.py",\n    "__init__.py",\n    "b_release_context.py",\n    "catalog_members.py",\n    "catalog_v21.py",\n    "continuity.py",\n    "contract.py",\n    "conventions.py",\n    "event_quarantine.py",\n    "execution.py",\n    "execution_accounting.py",\n    "execution_amounts.py",\n    "execution_candidate.py",\n    "execution_cash.py",\n    "execution_clock.py",\n    "execution_closure.py",\n    "execution_exposure.py",\n    "execution_numbers.py",\n    "execution_projection.py",\n    "execution_receipts/input_data.py",\n    "execution_receipts/input_guard.py",\n    "execution_receipts/input_reader.py",\n    "execution_returns.py",\n    "execution_risk.py",\n    "execution_risk_history.py",\n    "execution_signals.py",\n    "execution_startup.py",\n    "execution_state.py",\n    "fees.py",\n    "fold_split.py",\n    "folds.py",\n    "historical_authority.py",\n    "input_disposition.py",\n    "input_scope.py",\n    "isolation.py",\n    "k5.py",\n    "noncash_v3.py",\n    "pending.py",\n    "pipeline.py",\n    "reference_check.py",\n    "reference_definition_v301.py",\n    "reference_guard.py",\n    "reference_inputs.py",\n    "reference_producer.py",\n    "reference_producer_v3.py",\n    "reference_profile_v301.py",\n    "reference_registry_v3.py",\n    "reference_v3_scope.py",\n    "reference_validation.py",\n    "scope_proof.py",\n    "scope_reader.py",\n    "state_v2.py",\n    "validation.py",\n    "valuation.py",\n)\nDATA_FILES = (\n    "b_release_originals/EVO883-B-RUNTIME-RELEASE-P1-adopted-protocol-v1.0.0.json",\n    "b_release_originals/EVO883-EVO893-v10-ruling.json",\n    "b_release_originals/EVO883-S1-BRKB-field-receipt.json",\n    "b_release_originals/EVO883-S2-v14-field-receipt.json",\n    "b_release_originals/EVO883-S3-v12-final-receipt.json",\n    "b_release_originals/EVO883-S4-v11-receipt.json",\n    "b_release_originals/EVO883-v10-engineering-scope-receipt.json",\n    "b_release_originals/EVO883-v20.1-final-receipt.json",\n    "b_release_originals/EVO883-v21-final-receipt.json",\n    "b_release_originals/EVO893-B-CMI-guard-v21.json",\n    "b_release_originals/EVO893-B-noncash-catalog-v21.csv",\n    "b_release_originals/EVO938-B-runtime-release-P-v1.0.0.json",\n    "b_release_originals/EVO938-B-runtime-release-R-v1.0.0.json",\n    "b_release_originals/annotation-platform-readback.json",\n    "b_release_originals/publication-platform-readback.json",\n    "fixtures/calendar-folds-v0.1.json",\n    "fixtures/catalog-v21/EVO883-v21-final-receipt.json",\n    "fixtures/catalog-v21/EVO893-B-CMI-guard-v21.json",\n    "fixtures/catalog-v21/EVO893-B-noncash-catalog-v21.csv",\n    "fixtures/common-calendar-v0.1.txt",\n    "fixtures/common-profile-v3.json",\n    "fixtures/conventions-v0.1.json",\n    "fixtures/conventions-v3.0.0.json",\n    "fixtures/disposition/EVO883-EVO886-minimum-scope-ruling-v1.json",\n    "fixtures/disposition/EVO883-EVO886-minimum-scope-ruling-v1.md",\n    "fixtures/disposition/EVO883-EVO891-disposition-draft-v1.json",\n    "fixtures/disposition/EVO883-EVO891-ruling-v1.md",\n    "fixtures/disposition/QQQ-source-row-bindings-v1.json",\n    "fixtures/evo892-v3/candidate_reference_manifest.json",\n    "fixtures/evo892-v3/meta_reference_manifest.json",\n    "fixtures/evo892-v3/predeclared_reference_registry.json",\n    "fixtures/execution-v3.0.1/EVO883-C06-CLOCK-adopted-protocol-v1.0.0.json",\n    "fixtures/execution-v3.0.1/EVO883-D12-addendum-v3.0.1.md",\n    "fixtures/execution-v3.0.1/EVO883-D12-common-profile-v3.0.1.json",\n    "fixtures/execution-v3.0.1/EVO883-D12-shared-execution-contract-v3.0.1.json",\n    "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.json",\n    "fixtures/execution-v3.0.1/EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.md",\n    "fixtures/fee_params_x1.json",\n    "fixtures/historical-seed-e51f8023.jsonl",\n    "fixtures/noncash-exposure-policy-v3.json",\n    "fixtures/prereg-v3.json",\n    "fixtures/provenance-v2.json",\n    "fixtures/provenance-v3.json",\n    "fixtures/provenance.json",\n)\nPOLICY_FILES = {\n    "raw_document": "fixtures/conventions-v3.0.0.json",\n    "raw_profile": "fixtures/prereg-v3.json",\n    "raw_date_manifest": "fixtures/calendar-folds-v0.1.json",\n    "seed_raw": "fixtures/historical-seed-e51f8023.jsonl",\n}\n\n_HASH = hashlib.sha256\n_DUMPS = json.dumps\n_LOADS = json.loads\n_OPEN = os.open\n_READ = os.read\n_FSTAT = os.fstat\n_CLOSE = os.close\n_STORE = {}\n_ENTRY = os.path.realpath(__file__)\n_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_ENTRY)))\n_DF = os.path.join(_ROOT, "qlab", "qlab", "dynamic_factor")\n\n\nclass _Refusal(Exception):\n    pass\n\n\ndef _digest(value):\n    return _HASH(\n        _DUMPS(\n            value,\n            sort_keys=True,\n            separators=(",", ":"),\n            ensure_ascii=False,\n            allow_nan=False,\n        ).encode("utf-8")\n    ).hexdigest()\n\n\ndef _path(relative):\n    path = os.path.normpath(os.path.join(_DF, relative))\n    if os.path.commonpath((_ROOT, path)) != _ROOT:\n        raise _Refusal("scope.preflight_path_not_registered")\n    return path\n\n\ndef _read_file(path):\n    fd = _OPEN(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n    try:\n        before = _FSTAT(fd)\n        if not stat.S_ISREG(before.st_mode):\n            raise _Refusal("scope.preflight_regular_file_required")\n        chunks = []\n        while True:\n            chunk = _READ(fd, 65536)\n            if not chunk:\n                break\n            chunks.append(chunk)\n        raw = b"".join(chunks)\n        after = _FSTAT(fd)\n        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (\n            after.st_dev,\n            after.st_ino,\n            after.st_size,\n            after.st_mtime_ns,\n        ) or len(raw) != before.st_size:\n            raise _Refusal("scope.preflight_file_changed")\n        return raw, dict(\n            path=path,\n            bytes=len(raw),\n            st_dev=before.st_dev,\n            st_ino=before.st_ino,\n            st_mtime_ns=before.st_mtime_ns,\n            observed_sha256=_HASH(raw).hexdigest(),\n        )\n    finally:\n        _CLOSE(fd)\n\n\nclass _Snapshot:\n    __slots__ = ()\n\n    def validate(self):\n        if type(self) is not _Snapshot or self not in _STORE:\n            raise ValueError("scope.preflight_evidence_required")\n        data = _STORE[self]\n        actual = {\n            name: dict(sha256=_HASH(raw).hexdigest(), bytes=len(raw))\n            for name, raw in data["raw"].items()\n        }\n        if _digest(actual) != data["anchor"]:\n            raise ValueError("scope.preflight_snapshot_mismatch")\n        for name, row in actual.items():\n            if (\n                row["sha256"] != data["metadata"][name]["observed_sha256"]\n                or row["bytes"] != data["metadata"][name]["bytes"]\n            ):\n                raise ValueError("scope.preflight_snapshot_mismatch")\n        return True\n\n    def raw(self, relative):\n        try:\n            return _STORE[self]["raw"][_path(relative)]\n        except (KeyError, TypeError) as exc:\n            raise ValueError("scope.preflight_snapshot_missing") from exc\n\n    def identity(self, relative):\n        try:\n            return _STORE[self]["metadata"][_path(relative)]["observed_sha256"]\n        except (KeyError, TypeError) as exc:\n            raise ValueError("scope.preflight_snapshot_missing") from exc\n\n    def entry_source(self):\n        return _STORE[self]["raw"][_ENTRY]\n\n    def entry_path(self):\n        return _ENTRY\n\n    def path(self, relative):\n        return _path(relative)\n\n    def digest(self, value):\n        return _digest(value)\n\n    def bind_policy(self, policy):\n        for field, relative in POLICY_FILES.items():\n            if getattr(policy, field) != self.raw(relative):\n                raise ValueError("scope.preflight_policy_mismatch")\n        document = _LOADS(self.raw(POLICY_FILES["raw_document"]))\n        profile = _LOADS(self.raw(POLICY_FILES["raw_profile"]))\n        _STORE[self]["profile"] = profile\n        _STORE[self]["binding"] = dict(\n            conventions_version=document["version"],\n            conventions_sha256=self.identity(POLICY_FILES["raw_document"]),\n            conventions_status=document["status"],\n            profile_sha256=self.identity(POLICY_FILES["raw_profile"]),\n            prereg_sha256=self.identity(POLICY_FILES["raw_profile"]),\n            prereg_version=profile["version"],\n            common_profile_sha256=document["variance_layers"]["probe_profile"][\n                "common_profile_sha256"\n            ],\n        )\n\n    def policy_binding(self):\n        return dict(_STORE[self]["binding"])\n\n    def policy_profile(self):\n        return _LOADS(_DUMPS(_STORE[self]["profile"]))\n\n    def bind_loaded(self):\n        self.validate()\n        rows = []\n        data = _STORE[self]\n        imported = {\n            e["module"]\n            for e in _EVENTS\n            if e["event"] == "import"\n            and (e["module"] == "qlab" or e["module"].startswith("qlab."))\n        }\n        for name, module in sorted(sys.modules.items()):\n            if name != "qlab" and not name.startswith("qlab."):\n                continue\n            if name not in imported:\n                raise ValueError("scope.preflight_import_event_missing")\n            spec = module.__spec__\n            if spec is None or spec.origin is None:\n                raise ValueError("scope.preflight_loading_mismatch")\n            path = os.path.normpath(os.path.abspath(spec.origin))\n            if path not in data["metadata"]:\n                raise ValueError("scope.preflight_loading_mismatch")\n            before = data["metadata"][path]\n            fd = _OPEN(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n            try:\n                current = _FSTAT(fd)\n            finally:\n                _CLOSE(fd)\n            if not stat.S_ISREG(current.st_mode) or (\n                current.st_dev,\n                current.st_ino,\n                current.st_size,\n                current.st_mtime_ns,\n            ) != (\n                before["st_dev"],\n                before["st_ino"],\n                before["bytes"],\n                before["st_mtime_ns"],\n            ):\n                raise ValueError("scope.preflight_loading_mismatch")\n            relative = os.path.relpath(path, _DF)\n            kind = (\n                "auditor_raw_SHA"\n                if relative == "scope_proof.py"\n                else "receiver_full_AST"\n                if relative == "b_release_context.py"\n                else "fixed_raw_SHA"\n            )\n            if kind == "fixed_raw_SHA" and relative not in SOURCE_FILES:\n                raise ValueError("scope.preflight_import_not_registered")\n            rows.append(\n                dict(\n                    module=name,\n                    path=path,\n                    observed_sha256=before["observed_sha256"],\n                    expected_sha256=data["metadata"][path]["expected_sha256"],\n                    binding=kind,\n                    st_dev=current.st_dev,\n                    st_ino=current.st_ino,\n                    bytes=current.st_size,\n                )\n            )\n        return rows\n\n\ndef _canonical(value):\n    return (\n        _DUMPS(\n            value,\n            sort_keys=True,\n            separators=(",", ":"),\n            ensure_ascii=False,\n            allow_nan=False,\n        )\n        + "\\n"\n    ).encode("utf-8")\n\n\ndef _parse(raw):\n    def types(item):\n        if type(item) not in (dict, list, str, int, bool, type(None)):\n            raise _Refusal("scope.host_manifest_encoding_invalid")\n        if type(item) is dict:\n            for child in item.values():\n                types(child)\n        elif type(item) is list:\n            for child in item:\n                types(child)\n\n    def pairs(items):\n        obj = {}\n        for key, value in items:\n            if key in obj:\n                raise _Refusal("scope.host_manifest_encoding_invalid")\n            obj[key] = value\n        return obj\n\n    try:\n        value = _LOADS(raw, object_pairs_hook=pairs)\n        types(value)\n        if _canonical(value) != raw:\n            raise _Refusal("scope.host_manifest_encoding_invalid")\n        return value\n    except (ValueError, UnicodeError, TypeError) as exc:\n        raise _Refusal("scope.host_manifest_encoding_invalid") from exc\n\n\ndef _collect(manifest_path, expected_sha256):\n    global _ROOT, _DF\n    manifest_raw, _ = _read_file(manifest_path)\n    if (\n        len(manifest_raw) > 16 * 1024 * 1024\n        or _HASH(manifest_raw).hexdigest() != expected_sha256\n    ):\n        raise _Refusal("scope.host_manifest_sha_mismatch")\n    manifest = _parse(manifest_raw)\n    if (\n        type(manifest) is not dict\n        or set(manifest)\n        != {\n            "schema",\n            "run_id",\n            "nonce",\n            "context_version",\n            "root",\n            "source_commit",\n            "registration_sha256",\n            "precheck_sha256",\n            "launcher_identity",\n            "interpreter",\n            "files",\n            "launch_intent",\n            "launch_intent_sha256",\n            "platform_evidence",\n            "host_clock",\n            "policy",\n        }\n        or manifest["schema"] != "EVO884.C1HostSourceManifest/v1"\n    ):\n        raise _Refusal("scope.host_manifest_scope_mismatch")\n    root = manifest["root"]\n    if not os.path.isabs(root) or root != os.path.realpath(root):\n        raise _Refusal("scope.host_manifest_scope_mismatch")\n    _ROOT = root\n    _DF = os.path.join(root, "qlab", "qlab", "dynamic_factor")\n    intent = manifest["launch_intent"]\n    if _HASH(_canonical(intent)).hexdigest() != manifest[\n        "launch_intent_sha256"\n    ] or intent != dict(\n        root=root,\n        entry="qlab/tools/c1_source_preflight.py",\n        interpreter=manifest["interpreter"],\n        flags=["-I", "-S", "-B"],\n        manifest_sha256_argument="sha256_of_final_manifest_bytes",\n    ):\n        raise _Refusal("scope.host_manifest_scope_mismatch")\n    fixed_entry = _path("../../tools/c1_source_preflight.py")\n    if _ENTRY != fixed_entry or os.path.abspath(__file__) != fixed_entry:\n        raise _Refusal("scope.host_entry_path_mismatch")\n    if os.path.realpath(sys.executable) != manifest["interpreter"]["path"]:\n        raise _Refusal("scope.host_manifest_scope_mismatch")\n    expected_paths = {_path(name) for name in SOURCE_FILES + DATA_FILES}\n    rows = manifest["files"]\n    if type(rows) is not list or len(rows) != len(expected_paths):\n        raise _Refusal("scope.host_manifest_scope_mismatch")\n    raw, metadata = {}, {}\n    for row in rows:\n        if type(row) is not dict or set(row) != {\n            "path",\n            "relative",\n            "bytes",\n            "st_dev",\n            "st_ino",\n            "st_mtime_ns",\n            "observed_sha256",\n            "expected_sha256",\n            "raw_base64",\n            "role",\n        }:\n            raise _Refusal("scope.host_manifest_scope_mismatch")\n        path = row["path"]\n        if (\n            type(path) is not str\n            or type(row["relative"]) is not str\n            or type(row["raw_base64"]) is not str\n            or any(\n                type(row[key]) is not int or row[key] < 0\n                for key in ("bytes", "st_dev", "st_ino", "st_mtime_ns")\n            )\n            or any(\n                type(row[key]) is not str\n                or len(row[key]) != 64\n                or set(row[key]) - set("0123456789abcdef")\n                for key in ("observed_sha256", "expected_sha256")\n            )\n            or row["role"] != ("source" if path.endswith(".py") else "data")\n            or os.path.normpath(os.path.join(root, row["relative"])) != path\n        ):\n            raise _Refusal("scope.host_manifest_scope_mismatch")\n        if path not in expected_paths or path in raw or os.path.realpath(path) != path:\n            raise _Refusal("scope.host_manifest_scope_mismatch")\n        try:\n            value = base64.b64decode(row["raw_base64"], validate=True)\n        except (ValueError, TypeError) as exc:\n            raise _Refusal("scope.host_manifest_encoding_invalid") from exc\n        digest = _HASH(value).hexdigest()\n        if (\n            digest != row["observed_sha256"]\n            or digest != row["expected_sha256"]\n            or len(value) != row["bytes"]\n        ):\n            raise _Refusal("scope.host_snapshot_mismatch")\n        raw[path] = value\n        metadata[path] = {k: v for k, v in row.items() if k != "raw_base64"}\n    actual_raw, actual = _read_file(_ENTRY)\n    own = metadata[_ENTRY]\n    if any(own[k] != actual[k] for k in ("path", "st_dev", "st_ino", "bytes")):\n        raise _Refusal("scope.host_entry_identity_mismatch")\n    if _HASH(actual_raw).hexdigest() != own["observed_sha256"]:\n        raise _Refusal("scope.host_entry_sha_mismatch")\n    snapshot = object.__new__(_Snapshot)\n    _STORE[snapshot] = dict(\n        raw=raw,\n        metadata=metadata,\n        manifest=manifest,\n        anchor=_digest(\n            {\n                name: dict(sha256=_HASH(value).hexdigest(), bytes=len(value))\n                for name, value in raw.items()\n            }\n        ),\n    )\n    return snapshot, list(metadata.values()), []\n\n\ndef main():\n    global _VERIFIED, _PHASE\n    observations = []\n    try:\n        if (\n            len(sys.argv) != 5\n            or sys.argv[1] != "--host-manifest"\n            or sys.argv[3] != "--host-manifest-sha256"\n        ):\n            raise _Refusal("scope.host_manifest_required")\n        if (\n            __name__ != "__main__"\n            or type(__loader__).__name__ != "SourceFileLoader"\n            or os.path.realpath(__loader__.get_filename("__main__")) != _ENTRY\n        ):\n            raise _Refusal("scope.preflight_startup_mismatch")\n        original = getattr(sys, "orig_argv", None)\n        if original is not None and (\n            len(original) != 9\n            or original[1:4] != ["-I", "-S", "-B"]\n            or os.path.realpath(original[4]) != _ENTRY\n        ):\n            raise _Refusal("scope.preflight_startup_mismatch")\n        _PHASE = "snapshot"\n        snapshot, observations, errors = _collect(sys.argv[2], sys.argv[4])\n        if os.path.realpath(os.getcwd()) != _ROOT:\n            raise _Refusal("scope.preflight_workdir_or_arguments_mismatch")\n        if errors:\n            raise _Refusal("scope.preflight_source_identity_mismatch")\n        for row in observations:\n            path = row["path"]\n            if path == _ENTRY or not path.endswith(".py"):\n                continue\n            relative = os.path.relpath(path, os.path.join(_ROOT, "qlab"))\n            name = relative[:-3].replace(os.sep, ".")\n            if name.endswith(".__init__"):\n                name = name[:-9]\n            _ALLOWED_IMPORTS.add(name)\n            search = (\n                os.path.dirname(os.path.dirname(path))\n                if os.path.basename(path) == "__init__.py"\n                else os.path.dirname(path)\n            )\n            spec = importlib.machinery.PathFinder.find_spec(name, [search])\n            _EVENTS.append(\n                dict(\n                    sequence=len(_EVENTS),\n                    event="module_spec",\n                    module=name,\n                    path=None if spec is None else spec.origin,\n                    expected_path=path,\n                    loader=None if spec is None else type(spec.loader).__name__,\n                    phase="snapshot",\n                )\n            )\n            if (\n                spec is None\n                or type(spec.loader) is not importlib.machinery.SourceFileLoader\n                or spec.origin != path\n            ):\n                raise _Refusal("scope.preflight_loading_mismatch")\n        _EVENTS.append(\n            dict(sequence=len(_EVENTS), event="preflight_conclusion", status="VERIFIED")\n        )\n        _VERIFIED = True\n        _PHASE = "candidate_import"\n        with tempfile.TemporaryDirectory(prefix="c1-preflight-bytecode-") as bytecode:\n            sys.pycache_prefix = bytecode\n            package_parent = os.path.join(_ROOT, "qlab")\n            sys.path.insert(0, package_parent)\n            try:\n                import qlab\n            finally:\n                sys.path.remove(package_parent)\n            if (\n                qlab.__spec__.origin != snapshot.path("../__init__.py")\n                or list(qlab.__path__)\n                != [os.path.dirname(snapshot.path("../__init__.py"))]\n                or any(\n                    p and os.path.commonpath((_ROOT, os.path.realpath(p))) == _ROOT\n                    for p in sys.path\n                )\n            ):\n                raise _Refusal("scope.preflight_loading_mismatch")\n            from qlab.dynamic_factor import scope_proof\n\n            scope_proof._c1_snapshot_structure(snapshot)\n            from qlab.dynamic_factor import b_release_context\n            from qlab.dynamic_factor.conventions import load_conventions\n\n            policy = load_conventions()\n            if b_release_context.__spec__.origin != snapshot.path(\n                "b_release_context.py"\n            ):\n                raise ValueError("scope.preflight_loading_mismatch")\n            snapshot.bind_policy(policy)\n            _PHASE = "snapshot_B2"\n            proof = scope_proof.b2_isolation_proof_from_snapshot(policy, snapshot)\n            _PHASE = "loaded_binding"\n            loaded = snapshot.bind_loaded()\n            stdlib_origins = {\n                name: os.path.realpath(sys.modules[name].__spec__.origin)\n                for name in ("ast", "pathlib")\n            }\n            if any(\n                os.path.commonpath((os.path.realpath(sys.base_prefix), path))\n                != os.path.realpath(sys.base_prefix)\n                for path in stdlib_origins.values()\n            ):\n                raise _Refusal("scope.preflight_loading_mismatch")\n            consistency = proof["C1_source_preflight"]["entry_consistency"]\n            proof["C1_source_preflight"] = dict(\n                dependency_closed=False,\n                source="controlled_entry_snapshot",\n                snapshot_sha256=_STORE[snapshot]["anchor"],\n                auditor_sha256=snapshot.identity("scope_proof.py"),\n                entry_consistency=consistency,\n                loaded_modules=loaded,\n            )\n            _EVENTS.append(\n                dict(sequence=len(_EVENTS), event="B2_complete", status="VERIFIED")\n            )\n        result = dict(\n            schema="EVO884.C1CandidateProof/v1",\n            status="VERIFIED",\n            C1_dependency_closed=False,\n            host_finalization_pending=True,\n            manifest_sha256=sys.argv[4],\n            run_id=_STORE[snapshot]["manifest"]["run_id"],\n            registration_sha256=_STORE[snapshot]["manifest"]["registration_sha256"],\n            precheck_sha256=_STORE[snapshot]["manifest"]["precheck_sha256"],\n            launcher_identity=_STORE[snapshot]["manifest"]["launcher_identity"],\n            launch_intent_sha256=_STORE[snapshot]["manifest"]["launch_intent_sha256"],\n            proof=proof,\n            observations=observations,\n            import_binding=loaded,\n            stdlib_origins=stdlib_origins,\n            authority="mechanism_only_pending_independent_review",\n            startup=dict(\n                executable=sys.executable,\n                argv=sys.argv,\n                original_argv=getattr(sys, "orig_argv", None),\n                isolated=sys.flags.isolated,\n                no_site=sys.flags.no_site,\n                dont_write_bytecode=sys.flags.dont_write_bytecode,\n                cwd=os.getcwd(),\n                entry=_ENTRY,\n            ),\n        )\n        rc = 0\n    except (_Refusal, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:\n        if isinstance(exc, (KeyError, TypeError)):\n            exc = _Refusal("scope.host_manifest_scope_mismatch")\n        _EVENTS.append(dict(sequence=len(_EVENTS), event="refusal", code=str(exc)))\n        result = dict(\n            schema="EVO884.C1SourcePreflight/v1",\n            status="REJECTED",\n            C1_dependency_closed=False,\n            reason=str(exc),\n            observations=observations,\n        )\n        rc = 2\n    result["events"] = _EVENTS\n    sys.stdout.buffer.write(_canonical(result))\n    return rc\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
C1_ENTRY_REGISTRATION = {
    "path": "../../tools/c1_source_preflight.py",
    "kind": "complete_AST_host_manifest_consumer",
    "path_only": False,
}


def _c1_entry_structure(raw, auditor_sha256):
    """Complete reviewed literal template, including docstrings; no hash slot."""
    if ast.dump(ast.parse(raw), include_attributes=False) != ast.dump(
        ast.parse(C1_ENTRY_TEMPLATE), include_attributes=False
    ):
        raise ValueError("scope.preflight_entry_structure_mismatch")
    return dict(
        path=C1_ENTRY_REGISTRATION["path"],
        kind="complete_AST",
        placeholder_count=0,
        auditor_sha256=auditor_sha256,
        docstrings_compared=True,
        execution_trust_added=False,
        consistency="post_execution_only",
    )


def _c1_snapshot_structure(snapshot):
    if (
        type(snapshot).__name__ != "_Snapshot"
        or type(snapshot).__module__ != "__main__"
    ):
        raise ValueError("scope.preflight_evidence_required")
    if snapshot.entry_path() != snapshot.path(C1_ENTRY_REGISTRATION["path"]):
        raise ValueError("scope.host_entry_path_mismatch")
    if snapshot.validate.__func__.__code__.co_filename != snapshot.entry_path():
        raise ValueError("scope.preflight_evidence_required")
    if b2_isolation_proof_from_snapshot.__code__.co_filename != snapshot.path(
        "scope_proof.py"
    ):
        raise ValueError("scope.preflight_loading_mismatch")
    snapshot.validate()
    entry = _c1_entry_structure(
        snapshot.entry_source(), snapshot.identity("scope_proof.py")
    )
    _b_release_adapter_scope(
        ast.parse(snapshot.raw("b_release_context.py")),
        ast.parse(snapshot.raw("scope_proof.py")),
    )
    return entry


def _c1_reference_static(snapshot):
    from .reference_check import MODULES

    graph, sources, reads = {}, {}, []
    extension = {
        "execution_receipts.input_data",
        "execution_receipts.input_guard",
        "execution_receipts.input_reader",
        "execution_receipts.reference_result",
        "execution_receipts.replay_guard",
        "execution_receipts.input_facts",
        "reference_execution",
        "conventions",
        "contract",
    }
    for name, allowed in MODULES.items():
        raw = snapshot.raw(name.replace(".", "/") + ".py")
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
        sources[name + ".py"] = snapshot.identity(name.replace(".", "/") + ".py")
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
                release_entry = next(
                    n
                    for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "worker_release"
                )
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module in extension:
                        if not any(
                            e.lineno < node.lineno <= e.end_lineno
                            for e in (entry, result_entry, release_entry)
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
                for worker, installer in (
                    (entry, "install_execution"),
                    (result_entry, "install_result"),
                ):
                    sites = {
                        n.func.id: n.lineno
                        for n in ast.walk(worker)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    }
                    if sites.get("worker_release", 10**9) >= sites.get(installer, -1):
                        raise ValueError("B.release_context_required")
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
                    "execution_receipts.input_facts",
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
                    "execution_receipts.input_facts",
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
        "source_sha256": snapshot.digest(sources),
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


def b2_isolation_proof_from_snapshot(policy, snapshot):
    entry_consistency = _c1_snapshot_structure(snapshot)
    from .input_disposition import HASHES

    if any(
        snapshot.identity("fixtures/disposition/" + name) != expected
        for name, expected in HASHES.items()
    ):
        raise ValueError("data.disposition_identity_mismatch")

    graph, sources, gates, readers, trees = {}, {}, {}, [], {}
    file_reads = {}
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
        raw = snapshot.raw(relative)
        if expected is not None:
            if snapshot.identity(relative) != expected:
                raise ValueError("scope.file_access_not_whitelisted")
            continue
        sources[name + ".py"] = snapshot.identity(relative)
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
    # V7: the direct registered metadata read is scope_proof site 3, counted honestly.
    # V7: the legacy compile ban above stays unchanged; there is no exception.
    if file_reads != {
        "b_release_context": 4,
        "catalog_v21": 1,
        "execution": 2,
        "pipeline": 1,
        "reference_inputs": 1,
        "scope_proof": 3,
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
    ref = _c1_reference_static(snapshot)
    # V7: new checks follow every legacy guard in its original order.
    blindspot_scope = _call_blindspot_scope(trees)
    adapter_scope = _b_release_adapter_scope(
        trees["b_release_context"], trees["scope_proof"]
    )
    for name, relative, expected in B_RELEASE_ADAPTER_READS + B_RELEASE_IMPORT_READS:
        raw = snapshot.raw(relative)
        if name == "contract" and raw != B_RELEASE_CONTRACT_TEMPLATE.encode("utf-8"):
            raise ValueError("scope.file_access_not_whitelisted")
        if snapshot.identity(relative) != expected:
            raise ValueError("scope.file_access_not_whitelisted")
        if (name, relative, expected) in B_RELEASE_IMPORT_READS:
            sources[name + ".py"] = snapshot.identity(relative)
            trees[name] = ast.parse(raw)
    _call_blindspot_scope({name: trees[name] for name, _, _ in B_RELEASE_IMPORT_READS})
    dependency_scope = _b_release_dependency_scope(trees, sources)
    return {
        "schema": "EVO884.B2-isolation-proof/v1",
        "scope_ruling_sha256": HASHES["EVO883-EVO886-minimum-scope-ruling-v1.json"],
        **snapshot.policy_binding(),
        "source_files": sources,
        "source_sha256": snapshot.digest(sources),
        "import_graph": graph,
        "import_whitelist": {k: sorted(v) for k, v in IMPORTS.items()},
        "guarded_consumers": gates,
        "market_reader_sites": readers,
        "strategy_market_symbol_whitelist": list(snapshot.policy_profile()["universe"])
        + [snapshot.policy_profile()["portfolio"]["base_ticker"]],
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
        "C1_dependency_scope": dependency_scope,
        "C1_call_blindspot_scope": blindspot_scope,
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
        "C1_source_preflight": {
            "dependency_closed": False,
            "reason": "scope.preflight_finalization_required",
            "entry_consistency": entry_consistency,
        },
        "certifiable": False,
    }

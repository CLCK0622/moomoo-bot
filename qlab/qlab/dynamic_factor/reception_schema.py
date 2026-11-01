"""Offline closed contracts. Schema shape never grants source authority."""

import json
from pathlib import Path


ROOT = Path(__file__).parent / "reception_contracts"


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("receipt.duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("receipt.nonfinite_json")

    if type(raw) is not bytes:
        raise ValueError("receipt.original_bytes_required")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (UnicodeError, TypeError) as exc:
        raise ValueError("receipt.json_invalid") from exc


def contract(name):
    return strict_json((ROOT / name).read_bytes())


def validate(document, name):
    from jsonschema import Draft202012Validator, validators
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    # JSON integer is lexical: 1.0 and true are not integer receipts.
    validator = validators.extend(
        Draft202012Validator,
        type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
            "integer",
            lambda checker, value: type(value) is int,
        ),
    )
    registry = Registry()
    for filename, alias in (
        ("T1.v21.schema.json", "urn:evo884:t1-replay:v2.1"),
        (
            "installation.schema.json",
            "urn:evo884:n03-install-receipt:proposed-v3-types-1",
        ),
        ("N-01.v3.schema.json", "urn:evo884:n-acceptance:v3"),
        ("N-02.v3.schema.json", "urn:evo884:formal-n-binding:v3"),
        ("N-03.v31.schema.json", "urn:evo884:installed-authority:v3.1"),
    ):
        if not (ROOT / filename).is_file():
            continue
        schema = contract(filename)
        registry = registry.with_resource(
            alias, Resource.from_contents(schema, default_specification=DRAFT202012)
        )
    errors = list(validator(contract(name), registry=registry).iter_errors(document))
    if errors:
        raise ValueError("receipt.schema_version_mismatch")
    return document


def empty_receipt(name, details):
    schema = contract(name)
    return dict(
        schema=schema["properties"]["schema"]["const"],
        item_id=schema["properties"]["item_id"]["const"],
        accepted=False,
        state="DEPENDENCY_REQUIRED",
        reasons=[],
        baseline_commit=schema["properties"]["baseline_commit"]["const"],
        input_identities=dict.fromkeys(
            schema["properties"]["input_identities"]["required"]
        ),
        binding_sha256=None,
        details=details,
        runtime_consumable=False,
        certifiable=False,
        performance_outputs=None,
        observations=dict.fromkeys(schema["properties"]["observations"]["required"], 0),
    )

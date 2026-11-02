"""Read-only collection of source identities and existing observation files.

This module never imports or executes the supplied entrypoints. A source record
observes a loaded Python object's location and the current bytes at that path;
it does not certify that a worker loaded those same bytes. Existing DAG, scope
and per-ledger B documents remain evidence payloads, never acceptance results.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from types import FunctionType, MethodType, ModuleType


SCHEMA = "EVO884.PrefreezeCollection/v1"


def _names(values, reason):
    if any(type(v) is not str or not v.strip() for v in values):
        raise ValueError(reason)


def _snapshot(path, root):
    record = dict(path=None, sha256=None, bytes=None, reasons=[])
    if path is None:
        record["reasons"] = ["collection.file_missing"]
        return record, None
    try:
        root = Path(root).resolve(strict=True)
        path = Path(path)
        candidate = path if path.is_absolute() else root / path
        relative = candidate.relative_to(root)
        if ".." in relative.parts:
            raise ValueError("collection.path_outside_root")
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("collection.symlink_not_collected")
        candidate.resolve(strict=True).relative_to(root)
        if not candidate.is_file():
            raise ValueError("collection.regular_file_required")
        raw = candidate.read_bytes()
        record.update(
            path=relative.as_posix(),
            sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),
        )
        return record, raw
    except FileNotFoundError:
        record["reasons"] = ["collection.file_missing"]
    except OSError:
        record["reasons"] = ["collection.file_unreadable"]
    except (TypeError, ValueError) as exc:
        reason = str(exc)
        record["reasons"] = [
            reason
            if reason.startswith("collection.")
            else "collection.path_outside_root"
        ]
    return record, None


def _constant(value):
    raise ValueError("collection.nonfinite_json:" + value)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("collection.duplicate_json_key")
        result[key] = value
    return result


def _source(path, root):
    if path is not None and Path(path).suffix != ".py":
        return dict(
            path=None,
            sha256=None,
            bytes=None,
            reasons=["collection.python_source_unavailable"],
        )
    return _snapshot(path, root)[0]


def _evidence(path, root):
    record, raw = _snapshot(path, root)
    record["document"] = None
    if raw is not None:
        try:
            record["document"] = json.loads(
                raw, parse_constant=_constant, object_pairs_hook=_pairs
            )
        except (ValueError, UnicodeError):
            record["reasons"] = ["collection.json_unreadable"]
    return record


def collect(
    *,
    source_root,
    evidence_root,
    entrypoints,
    shared_modules,
    read_dag=None,
    scope=None,
    ledger_ids=(),
    ledger_B_proofs=None,
):
    """Return a JSON-safe observation list, without a verdict or any writes.

    Entrypoints are already loaded Python functions/methods; shared_modules are
    already loaded modules. The caller supplies the expected ledger IDs, so a
    missing ledger proof is represented explicitly rather than dropped. Paths
    for DAG/scope/B refer only to existing files under evidence_root. No ledger,
    data reader, budget, planner or certification callback is accepted or called.
    """
    if not isinstance(entrypoints, Mapping) or not isinstance(shared_modules, Mapping):
        raise ValueError("collection.source_bindings_required")
    _names(entrypoints, "collection.entrypoint_id_invalid")
    _names(shared_modules, "collection.module_id_invalid")
    if type(ledger_ids) not in (list, tuple):
        raise ValueError("collection.ledger_ids_invalid")
    _names(ledger_ids, "collection.ledger_ids_invalid")
    if len(set(ledger_ids)) != len(ledger_ids):
        raise ValueError("collection.duplicate_ledger_id")
    proofs = {} if ledger_B_proofs is None else ledger_B_proofs
    if not isinstance(proofs, Mapping) or set(proofs) - set(ledger_ids):
        raise ValueError("collection.unlisted_ledger_proof")
    entries, modules = {}, {}
    for name, entry in sorted(entrypoints.items()):
        function = entry.__func__ if isinstance(entry, MethodType) else entry
        if not isinstance(function, FunctionType):
            raise ValueError("collection.loaded_python_function_required")
        code = function.__code__
        path = code.co_filename if not code.co_filename.startswith("<") else None
        record = _source(path, source_root)
        entries[name] = dict(
            record,
            module=function.__module__,
            qualname=function.__qualname__,
            first_line=code.co_firstlineno,
        )
    for name, module in sorted(shared_modules.items()):
        if not isinstance(module, ModuleType):
            raise ValueError("collection.loaded_python_module_required")
        record = _source(vars(module).get("__file__"), source_root)
        modules[name] = dict(record, module=vars(module).get("__name__"))
    gaps = []
    if not entries:
        gaps.append("collection.entrypoints_missing")
    if not modules:
        gaps.append("collection.shared_modules_missing")
    if not ledger_ids:
        gaps.append("collection.ledger_ids_missing")
    return dict(
        schema=SCHEMA,
        sources=dict(entrypoints=entries, shared_modules=modules),
        read_dag=_evidence(read_dag, evidence_root),
        scope=_evidence(scope, evidence_root),
        ledger_B_proofs={
            ledger: _evidence(proofs.get(ledger), evidence_root)
            for ledger in sorted(ledger_ids)
        },
        collection_gaps=gaps,
    )


def format_collection(observations):
    """Format deterministically; the caller chooses whether/where to save it."""
    return (
        json.dumps(
            observations,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

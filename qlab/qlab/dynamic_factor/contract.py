"""Deterministic JSON envelopes and byte fingerprints shared by every tool."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path


def clean(value):
    """Retain nonfinite observations as null; never turn unknowns into zero."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    return value


def canonical(value) -> bytes:
    return json.dumps(
        clean(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value) -> str:
    return sha256(canonical(value))


def is_sha(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def source_manifest() -> dict:
    root = Path(__file__).parent
    return {p.name: sha256(p.read_bytes()) for p in sorted(root.glob("*.py"))}


def code_sha(value):
    """Hash the whole adapter module, including helpers and constants."""
    source = inspect.getsourcefile(value)
    if source is None:
        raise ValueError("adapter_source_unavailable")
    return sha256(Path(source).read_bytes())


def result(
    tool,
    inputs,
    *,
    metrics=None,
    reasons=(),
    missing=(),
    assumptions=(),
    availability=None,
    artifacts=None,
    certifiable=False,
    extra_sources=None,
):
    sources = source_manifest()
    sources.update(extra_sources or {})
    reasons = list(dict.fromkeys(reasons))
    return clean(
        {
            "schema": "dynamic_factor.tool/v1",
            "tool": tool,
            "ok": not reasons,
            "certifiable": bool(certifiable and not reasons),
            "runtime_consumable": False,
            "input_sha256": digest(inputs),
            "source_sha256": digest(sources),
            "source_files": sources,
            "assumptions": list(assumptions),
            "missing_inputs": list(missing),
            "reasons": reasons,
            "metrics": metrics or {},
            "metric_availability": availability or {},
            "artifacts": artifacts or {},
        }
    )


def unavailable(reason):
    return {"available": False, "reason": reason}

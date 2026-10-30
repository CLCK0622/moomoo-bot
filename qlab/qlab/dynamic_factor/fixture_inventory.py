"""Explicit committed fixture identity; never hash tool caches or untracked files."""

import json
from pathlib import Path, PurePosixPath

from .contract import sha256
from .conventions import FIXTURES

MANIFEST = "frozen-fixtures-v3.json"


def frozen_fixture_hashes(root=FIXTURES):
    root = Path(root)
    raw = (root / MANIFEST).read_bytes()
    spec = json.loads(raw)
    if spec.get("schema") != "EVO884.frozen-fixture-inventory/v1" or not isinstance(
        spec.get("files"), dict
    ):
        raise ValueError("fixture.manifest_invalid")
    output = {MANIFEST: sha256(raw)}
    for name, expected in sorted(spec["files"].items()):
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or any(
                p in (".", "..", "__pycache__") or p.startswith(".") for p in path.parts
            )
            or str(path) != name
        ):
            raise ValueError("fixture.manifest_path_invalid")
        local = root / name
        if (
            local.is_symlink()
            or not local.is_file()
            or not local.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("fixture.declared_file_missing_or_aliased")
        actual = sha256(local.read_bytes())
        if actual != expected:
            raise ValueError("fixture.declared_file_sha_mismatch")
        output[name] = actual
    return output

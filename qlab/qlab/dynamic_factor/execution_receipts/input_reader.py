"""Four exact read-only files, pinned separately from untrusted stdin."""

import hashlib
import json
from pathlib import Path

from .input_data import validate_data


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def read_inputs(root, request, expected):
    if (
        type(request) is not dict
        or set(request) != {"schema", "manifest"}
        or request["schema"] != "EVO884.ExecutionInputReadRequest/v1"
        or digest(request) != expected["request_sha256"]
        or digest(request["manifest"]) != expected["manifest_sha256"]
    ):
        raise ValueError("execution_input.host_request_binding_mismatch")
    manifest = request["manifest"]
    if any(
        manifest[k] != expected[k]
        for k in ("book_id", "run_id", "member_id", "scope_sha256", "profile_sha256")
    ):
        raise ValueError("execution_input.host_request_binding_mismatch")
    root = Path(root).resolve()
    paths = {}
    # Preflight ALL four paths before opening the first file.
    for role in ("raw", "rights", "adv", "cash"):
        binding = manifest["inputs"][role]
        path = root / (role + ".json")
        if (
            binding["file"] != role + ".json"
            or path.is_symlink()
            or path.resolve().parent != root
            or not path.is_file()
            or path.stat().st_nlink != 1
        ):
            raise ValueError("execution_input.read_path_not_whitelisted")
        paths[role] = path
    result = {}
    for role in ("raw", "rights", "adv", "cash"):
        raw = paths[role].read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["inputs"][role]["sha256"]:
            raise ValueError("execution_input.original_file_sha_mismatch")
        result[role] = validate_data(raw, role, manifest)
    return result

"""The reference producer's sole data-file reader; three sealed train inputs."""

import hashlib
import json
from pathlib import Path
from .input_scope import reject_b2_inputs

ROLES = {
    "panel": "panel.json",
    "benchmark": "benchmark.json",
    "profile": "profile.json",
}
SCHEMAS = {
    "panel": "reference.train_panel/v1",
    "benchmark": "reference.train_benchmark/v1",
    "profile": "reference.profile/v1",
}


def read_inputs(root, manifest, dates):
    reject_b2_inputs(manifest, "reference")
    if set(manifest) != set(ROLES):
        raise ValueError("reference.read_role_not_whitelisted")
    root = Path(root).resolve()
    result = {}
    for role, name in sorted(ROLES.items()):
        binding = manifest[role]
        # Exact filenames prevent output/rename/path/seed tricks from expanding the reader.
        if binding["file"] != name:
            raise ValueError("reference.read_path_not_whitelisted")
        path = root / name
        if (
            path.is_symlink()
            or path.resolve().parent != root
            or path.stat().st_nlink != 1
        ):
            raise ValueError("reference.read_path_not_whitelisted")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding["sha256"]:
            raise ValueError("reference.input_sha_mismatch")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") != SCHEMAS[role]:
            raise ValueError("reference.input_schema_forbidden")
        allowed = (
            {
                "schema",
                "common_profile_sha256",
                "conventions_version",
                "conventions_sha256",
                "prereg_sha256",
                "fold_bindings_raw",
            }
            if role == "profile"
            else (
                {"schema", "rows", "symbol"}
                if role == "benchmark"
                else {"schema", "rows"}
            )
        )
        if set(data) != allowed:
            raise ValueError("reference.input_schema_forbidden")
        if role != "profile":
            reject_b2_inputs(data, "reference")
        if role == "benchmark" and data["symbol"] != "QQQ":
            raise ValueError("reference.primary_benchmark_must_be_QQQ")
        if role != "profile" and [r["date"] for r in data["rows"]] != list(dates):
            raise ValueError("reference.only_complete_train_visible")
        if role != "profile":
            expected = {"date", "prices"} if role == "panel" else {"date", "close"}
            if any(set(row) != expected for row in data["rows"]):
                raise ValueError("reference.input_schema_forbidden")
        result[role] = data
    return result

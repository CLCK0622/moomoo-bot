import json
import shutil

import pytest

from qlab.dynamic_factor.conventions import FIXTURES
from qlab.dynamic_factor.fixture_inventory import MANIFEST, frozen_fixture_hashes


def test_only_explicit_frozen_files_influence_identity(tmp_path):
    paths = json.loads((FIXTURES / MANIFEST).read_bytes())["files"]
    for n in [MANIFEST] + list(paths):
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / n, p)
    initial = frozen_fixture_hashes(tmp_path)
    for folder in ["evo891/.ruff_cache", "__pycache__", ".pytest_cache"]:
        p = tmp_path / folder
        p.mkdir(parents=True, exist_ok=True)
        (p / "CACHEDIR.TAG").write_text("arbitrary changing tool bytes")
    (tmp_path / "untracked.json").write_text("{}")
    assert frozen_fixture_hashes(tmp_path) == initial
    assert not any(".ruff_cache" in k or "__pycache__" in k for k in initial)
    changed = tmp_path / "fee_params_x1.json"
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="declared_file_sha_mismatch"):
        frozen_fixture_hashes(tmp_path)

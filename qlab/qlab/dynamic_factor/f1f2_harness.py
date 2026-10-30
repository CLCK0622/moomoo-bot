"""F1/F2 review reproductions on private fixtures, never author tool caches."""

import json
import shutil
import subprocess
import sys

from .contract import sha256
from .conventions import FIXTURES
from .fixture_inventory import MANIFEST, frozen_fixture_hashes
from .fees import _legacy_fee_frontier, fee_frontier
from .authority_ledger import (
    AuthorityLedger,
    CURRENT_FIXTURES,
    CURRENT_PUBLISHED,
    TOOL_SHA,
)


def cases(workdir, policy):
    local = workdir / "fixture-inventory-unit"
    local.mkdir()
    names = json.loads((FIXTURES / MANIFEST).read_bytes())["files"]
    for name in [MANIFEST] + list(names):
        target = local / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / name, target)
    original = frozen_fixture_hashes(local)
    for folder in ["evo891/.ruff_cache", "__pycache__", ".pytest_cache"]:
        cache = local / folder
        cache.mkdir(parents=True, exist_ok=True)
        (cache / ".gitignore").write_bytes(b"UNIT_CACHE_NOT_INPUT")
        (cache / "CACHEDIR.TAG").write_bytes(b"UNIT_CHANGED_CACHE")
    (local / "untracked-unit.json").write_bytes(b"{}")
    assert frozen_fixture_hashes(local) == original
    out = [
        dict(
            case_id="audit.fixture_identity_ignores_tool_caches",
            status="PASS",
            observed=dict(
                cache_and_untracked_files_excluded=True, declared_files=len(original)
            ),
        )
    ]
    observed = []
    for name in ["fee_params_x1.json", "fee_params_x2.json"]:
        for day in ["2026-09-30", "2026-10-01", "2026-12-31", "2027-01-01"]:
            request = dict(
                price=50,
                ticket_usd=5000,
                gross_edge_bps=10,
                sell_date=day,
                rate_basis="effective_date",
                pnl_basis="reference",
            )
            old = _legacy_fee_frontier(request, FIXTURES / name)
            assert old["reasons"] == ["fee.legacy_frontier_disabled"]
            assert old["metrics"]["taf_usd"] is old["metrics"]["net_edge_bps"] is None
            public = fee_frontier(request, FIXTURES / name)
            assert (
                public["ok"]
                and public["metrics"]["taf_usd"] == 0.0195
                and public["metrics"]["rate_basis_effective"] == "research_restored"
            )
            observed.append(
                dict(
                    file=name,
                    date=day,
                    legacy_TAF=None,
                    research_TAF=public["metrics"]["taf_usd"],
                )
            )
    out.append(
        dict(
            case_id="audit.legacy_TAF_date_path_disabled",
            status="PASS",
            observed=observed,
        )
    )
    ledger = CURRENT_FIXTURES / "EVO891-B-ledger-v4.jsonl"
    tip = CURRENT_FIXTURES / "EVO891-B-ledger-v4.tip.json"
    actual = AuthorityLedger(ledger, tip, external_anchor=CURRENT_PUBLISHED).verify()
    tool = FIXTURES / "evo891" / "EVO891-B-ledger-v2.py"
    assert sha256(tool.read_bytes()) == TOOL_SHA
    r = subprocess.run(
        [
            sys.executable,
            str(tool),
            "verify",
            str(ledger),
            str(tip),
            "--expect-tip",
            CURRENT_PUBLISHED["tip"],
            "--expect-sequence",
            str(CURRENT_PUBLISHED["sequence"]),
            "--expect-high-water",
            str(CURRENT_PUBLISHED["n_high_water"]),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 0 and json.loads(r.stdout) == actual
    out.append(
        dict(
            case_id="ledger.current_published_witness_parity",
            status="PASS",
            observed=actual,
        )
    )
    return out

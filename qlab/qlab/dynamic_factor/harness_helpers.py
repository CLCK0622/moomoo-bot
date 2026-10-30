"""Explicit synthetic bootstrap receipts for isolated offline harness DBs only."""

from pathlib import Path
from .contract import digest
from .ledger import AttemptLedger, bound_genesis


def fixture_ledger(path, policy):
    path = Path(path)
    receipt = {
        "action": "bootstrap",
        "target": str(path.resolve()),
        "genesis_sha256": digest(bound_genesis(policy)),
        "ledger_id": digest({"synthetic_unit_ledger": path.name}),
        "authority_source": {
            "reference": "SYNTHETIC_UNIT_ONLY_NOT_PRODUCTION_BOOTSTRAP",
            "sha256": digest("synthetic_bootstrap"),
        },
    }
    return AttemptLedger.from_conventions(
        path,
        policy,
        anchor_path=path.with_name(path.name + ".unit-tip.json"),
        bootstrap_receipt=receipt if not path.exists() else None,
    )

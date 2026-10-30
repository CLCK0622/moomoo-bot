"""Independently retained SQLite tail witness. No automatic rollback/rebase.

The witness must be backed up separately from the DB. Rewriting both the DB and
the witness is outside this local integrity boundary. A crash between DB commit
and witness fsync fails closed and needs an explicitly reviewed recovery.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .contract import canonical, digest, is_sha


def state(db, genesis):
    rows = db.execute("SELECT seq,body FROM events ORDER BY seq").fetchall()
    if [r[0] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("ledger.sequence_invalid")
    events = [json.loads(r[1]) for r in rows]
    previous = digest(genesis)
    for e in events:
        if e.get("previous_hash") != previous:
            raise ValueError("ledger_hash_chain_invalid")
        previous = digest(e)
    attempts = {e["attempt_id"] for e in events if e["event"] == "begin"}
    if genesis.get("attempt_counting_policy"):
        families = [e for e in events if e["event"] == "family"]
        runs = {e["run_id"] for e in families}
        attempts = {a for e in families for a in e["attempt_ids"]} | {
            e["attempt_id"]
            for e in events
            if e["event"] == "begin"
            and not (
                e.get("kind") == "fold_invocation"
                and e.get("context", {}).get("run_id") in runs
            )
        }
    reported = max(
        (e["value"] for e in events if e["event"] == "self_report_n"), default=0
    )
    return {
        "sequence": len(events),
        "tip": previous,
        "snapshot_sha256": digest({"genesis": genesis, "events": events}),
        "local_n": len(attempts),
        "self_report_n": reported,
        "n_high_water": max((genesis.get("prior_n") or 0) + len(attempts), reported),
    }


def validate_bootstrap(receipt, path, genesis):
    if (
        not isinstance(receipt, dict)
        or receipt.get("action") != "bootstrap"
        or receipt.get("target") != str(Path(path).resolve())
        or receipt.get("genesis_sha256") != digest(genesis)
        or not is_sha(receipt.get("ledger_id"))
        or not is_sha((receipt.get("authority_source") or {}).get("sha256"))
    ):
        raise ValueError("ledger.bootstrap_receipt_required")
    return receipt["ledger_id"]


def read(path):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        raise ValueError("ledger.independent_anchor_missing_or_invalid") from None


def verify(anchor, path, genesis, current):
    if anchor.get("migration_pending") or anchor.get("migrated_to"):
        raise ValueError("ledger.migration_pending_or_source_retired")
    if anchor.get("database") != str(Path(path).resolve()) or anchor.get(
        "genesis_sha256"
    ) != digest(genesis):
        raise ValueError("ledger.identity_or_migration_receipt_required")
    if any(anchor.get(k) != v for k, v in current.items()):
        raise ValueError("ledger.tail_or_high_water_mismatch")


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

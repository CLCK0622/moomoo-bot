"""Transactional, append-only attempt log, independent of the paused paper track.

SQLite transactions serialize writers. Attempts are inserted BEFORE execution;
an interrupted attempt survives as started. A new attempt ID counts even for an
identical proposal; replaying the same ID is transport idempotency, not a trial.
The hash covers logical content, not SQLite page layout or filesystem paths.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .contract import canonical, clean, digest, is_sha, result, unavailable

DEFAULT_GENESIS = {
    "namespace": "evo881.dynamic_factor",
    "prior_n": None,
    "authority_source": None,
}


class AttemptLedger:
    def __init__(self, path, genesis=None):
        self.path = Path(path)
        if str(path) == ":memory:":
            raise ValueError("persistent ledger path required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.genesis = clean(DEFAULT_GENESIS if genesis is None else genesis)
        if self.genesis.get("namespace") != DEFAULT_GENESIS["namespace"]:
            raise ValueError("isolated namespace must be evo881.dynamic_factor")
        prior = self.genesis.get("prior_n")
        if prior is not None and (type(prior) is not int or prior < 0):
            raise ValueError("prior_n must be a nonnegative integer or null")
        authority = self.genesis.get("authority_source")
        if authority is not None and (
            not isinstance(authority, dict)
            or not authority.get("reference")
            or not is_sha(authority.get("sha256"))
        ):
            raise ValueError("authority_source requires reference and sha256")
        with self._transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(seq INTEGER PRIMARY KEY, body TEXT NOT NULL)"
            )
            saved = db.execute("SELECT value FROM meta WHERE key='genesis'").fetchone()
            if saved is None:
                db.execute(
                    "INSERT INTO meta VALUES ('genesis', ?)",
                    (canonical(self.genesis).decode(),),
                )
            elif json.loads(saved[0]) != self.genesis:
                raise ValueError(
                    "genesis_mismatch: no silent history reset or rebasing"
                )

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _events(self, db):
        return [
            json.loads(row[0])
            for row in db.execute("SELECT body FROM events ORDER BY seq")
        ]

    def _append(self, db, event):
        events = self._events(db)
        event = clean(
            dict(
                event,
                previous_hash=digest(events[-1]) if events else digest(self.genesis),
            )
        )
        db.execute("INSERT INTO events(body) VALUES (?)", (canonical(event).decode(),))
        return event

    def begin(
        self, attempt_id, proposal, *, kind="candidate", context=None, replay=True
    ):
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("attempt_id required")
        payload = clean(
            {
                "event": "begin",
                "attempt_id": attempt_id,
                "proposal": proposal,
                "kind": kind,
                "context": context or {},
            }
        )
        with self._transaction() as db:
            for event in self._events(db):
                if event["event"] == "begin" and event["attempt_id"] == attempt_id:
                    if not replay:
                        raise ValueError("attempt_already_claimed")
                    if {
                        k: v for k, v in event.items() if k != "previous_hash"
                    } != payload:
                        raise ValueError("attempt_id_conflict")
                    return event
            return self._append(db, payload)

    def finish(self, attempt_id, status, *, sharpe=None, reason=None, details=None):
        if status not in {"success", "failed", "nan", "duplicate", "rejected"}:
            raise ValueError("invalid outcome")
        if sharpe is not None and (
            isinstance(sharpe, bool) or not isinstance(sharpe, (float, int))
        ):
            raise ValueError("sharpe must be numeric or null")
        if sharpe is not None and not math.isfinite(sharpe):
            sharpe, status, reason = None, "nan", reason or "nonfinite_sharpe"
        payload = clean(
            {
                "event": "finish",
                "attempt_id": attempt_id,
                "status": status,
                "sharpe_per_period": sharpe,
                "reason": reason,
                "details": details or {},
            }
        )
        with self._transaction() as db:
            events = self._events(db)
            if not any(
                e["event"] == "begin" and e["attempt_id"] == attempt_id for e in events
            ):
                raise ValueError("attempt_not_started")
            previous = [
                e
                for e in events
                if e["event"] == "finish" and e["attempt_id"] == attempt_id
            ]
            if previous:
                if {
                    k: v for k, v in previous[0].items() if k != "previous_hash"
                } != payload:
                    raise ValueError(
                        "outcome_conflict: previous observation is immutable"
                    )
                return previous[0]
            return self._append(db, payload)

    def snapshot(self):
        with self._transaction() as db:
            events = self._events(db)
            saved = json.loads(
                db.execute("SELECT value FROM meta WHERE key='genesis'").fetchone()[0]
            )
        if saved != self.genesis:
            raise ValueError("genesis_mismatch")
        previous = digest(saved)
        for event in events:
            if event["previous_hash"] != previous:
                raise ValueError("ledger_hash_chain_invalid")
            previous = digest(event)
        count = sum(e["event"] == "begin" for e in events)
        prior = saved.get("prior_n")
        reasons = []
        if saved.get("authority_source") is None:
            reasons.append("ledger_authority_unset")
        if prior is None:
            reasons.append("ledger_history_count_unknown")
        return {
            "genesis": saved,
            "events": events,
            "local_attempts_n": count,
            "cumulative_n": None if prior is None else prior + count,
            "n_ledger_hash": digest({"genesis": saved, "events": events}),
            "certifiable": not reasons,
            "reasons": reasons,
        }

    def readout(self):
        snapshot = self.safe_snapshot()
        return result(
            "ledger_readout",
            snapshot,
            metrics={
                k: snapshot[k]
                for k in ("cumulative_n", "local_attempts_n", "n_ledger_hash")
            }
            | {"trials_variance": None},
            reasons=snapshot["reasons"],
            availability={"trials_variance": unavailable("prereg_missing")},
            assumptions=[
                "All local begins count, including failures, repeats and interrupted attempts.",
                "This is a mechanism count; EVO-883 must define statistical N/V and history import.",
            ],
            artifacts={"ledger": snapshot},
        )

    def safe_snapshot(self):
        """Read-only tool boundary; corruption never becomes an empty new history."""
        try:
            return self.snapshot()
        except (ValueError, KeyError, TypeError, sqlite3.Error, OSError):
            return {
                "genesis": None,
                "events": None,
                "local_attempts_n": None,
                "cumulative_n": None,
                "n_ledger_hash": None,
                "certifiable": False,
                "reasons": ["ledger_unreadable_or_corrupt"],
            }

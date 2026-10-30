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
    @classmethod
    def from_conventions(cls, path, conventions):
        """Import the exact eight historical records as an incomplete N lower bound."""
        p = conventions.document
        return cls(
            path,
            dict(
                DEFAULT_GENESIS,
                prior_n=p["genesis"]["seed_min_N"],
                count_complete=p["genesis"]["complete_current_N_verified"],
                authority_source={
                    "reference": p["genesis"]["commit"]
                    + ":"
                    + p["genesis"]["repo_path"],
                    "sha256": p["genesis"]["sha256"],
                },
                historical_seed_rows=list(conventions.seed_rows),
                attempt_counting_policy=p["N_counting"],
                historical_sharpes_usable_as_active_V=p["N"][
                    "N_seed_historical_sharpes_usable_as_active_V"
                ],
                **conventions.binding,
            ),
        )

    def __init__(self, path, genesis=None):
        self.path = Path(path)
        if str(path) == ":memory:":
            raise ValueError("persistent ledger path required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.genesis = clean(DEFAULT_GENESIS if genesis is None else genesis)
        if self.genesis.get("namespace") != DEFAULT_GENESIS["namespace"]:
            raise ValueError("isolated namespace must be evo881.dynamic_factor")
        prior = self.genesis.get("prior_n")
        if (
            "count_complete" in self.genesis
            and type(self.genesis["count_complete"]) is not bool
        ):
            raise ValueError("count_complete must be boolean")
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
        if context is not None and not isinstance(context, dict):
            raise ValueError("attempt_context_invalid")
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
        if details is not None and not isinstance(details, dict):
            raise ValueError("attempt_details_invalid")
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

    def declare_family(self, run_id, attempt_ids, *, basis, authority_source=None):
        """Seal complete family membership before any of its performance attempts."""
        if (
            not run_id
            or not attempt_ids
            or len(set(attempt_ids)) != len(attempt_ids)
            or not all(isinstance(x, str) and x for x in attempt_ids)
        ):
            raise ValueError("family_membership_invalid")
        payload = {
            "event": "family",
            "run_id": run_id,
            "attempt_ids": list(attempt_ids),
            "basis": basis,
            "authority_source": authority_source,
        }
        with self._transaction() as db:
            events = self._events(db)
            previous = [
                e for e in events if e["event"] == "family" and e["run_id"] == run_id
            ]
            if previous:
                if {
                    k: v for k, v in previous[0].items() if k != "previous_hash"
                } != payload:
                    raise ValueError("family_membership_conflict")
                return previous[0]
            if any(
                e["event"] == "begin"
                and e.get("kind") == "candidate"
                and e.get("context", {}).get("run_id") == run_id
                for e in events
            ):
                raise ValueError("family_declared_after_attempts")
            return self._append(db, payload)

    def observe_self_report_n(self, value):
        if type(value) is not int or value < 1:
            raise ValueError("dsr.self_report_n_missing_or_invalid")
        with self._transaction() as db:
            prior = max(
                (e["value"] for e in self._events(db) if e["event"] == "self_report_n"),
                default=0,
            )
            if value > prior:
                self._append(db, {"event": "self_report_n", "value": value})
            return max(prior, value)

    def record(self, key, payload):
        """Seal a stage/receipt once; metadata adds no trial and cannot be revised."""
        event = clean({"event": "record", "key": key, "payload": payload})
        with self._transaction() as db:
            for previous in self._events(db):
                if previous["event"] == "record" and previous["key"] == key:
                    if {
                        k: v for k, v in previous.items() if k != "previous_hash"
                    } != event:
                        raise ValueError("ledger.record_conflict")
                    return previous
            return self._append(db, event)

    def recorded(self, key):
        return next(
            (
                e["payload"]
                for e in self.snapshot()["events"]
                if e["event"] == "record" and e["key"] == key
            ),
            None,
        )

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
        counted = count
        if saved.get("attempt_counting_policy"):
            families = [e for e in events if e["event"] == "family"]
            family_runs = {e["run_id"] for e in families}
            # Family membership is a pre-performance proposal record. Retain it
            # even if a child begin/outcome was interrupted. An invocation with
            # a declared family is metadata, not another optimizer trial.
            attempt_ids = {aid for family in families for aid in family["attempt_ids"]}
            attempt_ids.update(
                e["attempt_id"]
                for e in events
                if e["event"] == "begin"
                and not (
                    e.get("kind") == "fold_invocation"
                    and e.get("context", {}).get("run_id") in family_runs
                )
            )
            counted = len(attempt_ids)
        prior = saved.get("prior_n")
        complete = saved.get("count_complete", prior is not None)
        reasons = []
        if saved.get("authority_source") is None:
            reasons.append("ledger_authority_unset")
        if prior is None:
            reasons.append("ledger_history_count_unknown")
        elif not complete:
            reasons.append("ledger_history_incomplete")
        return {
            "genesis": saved,
            "events": events,
            "local_attempts_n": count,
            "local_counted_n": counted,
            "cumulative_n": prior + counted if prior is not None and complete else None,
            "cumulative_n_lower_bound": counted if prior is None else prior + counted,
            "n_complete": bool(prior is not None and complete),
            "n_ledger_hash": digest({"genesis": saved, "events": events}),
            "certifiable": not reasons,
            "reasons": reasons,
        }

    def readout(self):
        snapshot = self.safe_snapshot()
        report = result(
            "ledger_readout",
            snapshot,
            metrics={
                k: snapshot[k]
                for k in (
                    "cumulative_n",
                    "cumulative_n_lower_bound",
                    "local_attempts_n",
                    "local_counted_n",
                    "n_ledger_hash",
                )
            }
            | {"trials_variance": None},
            reasons=snapshot["reasons"],
            availability={
                "trials_variance": unavailable(
                    "dsr_run_context_required"
                    if (snapshot["genesis"] or {}).get("conventions_sha256")
                    else "prereg_missing"
                )
            },
            assumptions=[
                "All begins are retained; v0 counts declared proposals and structural rejections, with completed-family invocations as metadata.",
                "A historical snapshot is a lower bound until current-project reconciliation is complete.",
            ],
            artifacts={"ledger": snapshot},
        )
        genesis = snapshot["genesis"] or {}
        report.update(
            {
                k: genesis[k]
                for k in (
                    "conventions_version",
                    "conventions_sha256",
                    "conventions_status",
                    "profile_sha256",
                    "common_profile_sha256",
                )
                if k in genesis
            }
        )
        return report

    def safe_snapshot(self):
        """Read-only tool boundary; corruption never becomes an empty new history."""
        try:
            return self.snapshot()
        except (ValueError, KeyError, TypeError, sqlite3.Error, OSError):
            return {
                "genesis": None,
                "events": None,
                "local_attempts_n": None,
                "local_counted_n": None,
                "cumulative_n": None,
                "cumulative_n_lower_bound": None,
                "n_complete": False,
                "n_ledger_hash": None,
                "certifiable": False,
                "reasons": ["ledger_unreadable_or_corrupt"],
            }

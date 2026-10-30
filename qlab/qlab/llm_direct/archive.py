"""Private synthetic archive: durable raw bytes, transactional immutable events."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path

from qlab.shadow15k.ledger import FORBIDDEN, FORBIDDEN_LINE

from .contract import canonical, digest, sha

PHYSICAL_ROOT = (Path(__file__).resolve().parents[3] / ".llm-direct-offline").resolve()


class Archive:
    def __init__(self, root):
        self.anchor = PHYSICAL_ROOT
        self.root = Path(root).absolute()
        self._check()
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(exist_ok=True)
        self.path = self.root / "archive.sqlite3"
        with self._db() as db:
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if tables and tables != {"identity", "events"}:
                raise ValueError("archive.foreign_database")
            db.execute("CREATE TABLE IF NOT EXISTS identity (body TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL, event_hash TEXT NOT NULL)"
            )
            rows = db.execute("SELECT body FROM identity").fetchall()
            identity = '{"mode":"offline_synthetic","schema":"llm_direct.archive/v1"}'
            if rows and rows != [(identity,)]:
                raise ValueError("archive.identity_mismatch")
            if not rows:
                db.execute("INSERT INTO identity VALUES (?)", (identity,))
            self._events(db)

    def _check(self):
        path = self.root.resolve()
        if (
            self.anchor.resolve() != self.anchor
            or self.anchor not in path.parents
            or self.root != path
            or any(p.is_symlink() for p in [self.root, *self.root.parents])
            or FORBIDDEN.intersection(p.lower() for p in path.parts)
            or any(FORBIDDEN_LINE.search(p) for p in path.parts)
        ):
            raise ValueError("archive.private_physical_root_required")
        if path.exists():
            for p in path.iterdir():
                try:
                    st = p.lstat()
                except FileNotFoundError:
                    # Another transaction may have just removed its journal.
                    continue
                if p.name == "blobs" and stat.S_ISDIR(st.st_mode):
                    children = list(p.iterdir())
                    if any(
                        not c.is_file() or c.is_symlink() or c.stat().st_nlink != 1
                        for c in children
                    ):
                        raise ValueError("archive.foreign_blob")
                elif (
                    p.name not in {"archive.sqlite3", "archive.sqlite3-journal"}
                    or not stat.S_ISREG(st.st_mode)
                    or st.st_nlink != 1
                ):
                    raise ValueError("archive.foreign_file")

    def _db(self):
        from contextlib import contextmanager

        @contextmanager
        def connection():
            self._check()
            db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
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

        return connection()

    def put(self, raw):
        if not isinstance(raw, bytes):
            raise ValueError("archive.bytes_required")
        self._check()
        h = sha(raw)
        p = self.blobs / h
        try:
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if p.read_bytes() != raw:
                raise ValueError("archive.blob_conflict")
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            fd = os.open(str(self.blobs), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return h

    def get(self, h):
        from qlab.dynamic_factor.contract import is_sha

        self._check()
        if not is_sha(h):
            raise ValueError("archive.sha_required")
        raw = (self.blobs / h).read_bytes()
        if sha(raw) != h:
            raise ValueError("archive.blob_hash_mismatch")
        return raw

    def _events(self, db):
        stored = db.execute(
            "SELECT body, event_hash FROM events ORDER BY rowid"
        ).fetchall()
        if any(sha(raw.encode()) != h for raw, h in stored):
            raise ValueError("archive.event_hash_corrupt")
        events = [json.loads(raw) for raw, _ in stored]
        previous = digest(
            {"schema": "llm_direct.archive/v1", "mode": "offline_synthetic"}
        )
        for e in events:
            if e["previous_hash"] != previous:
                raise ValueError("archive.chain_corrupt")
            for h in e["body"].get("blob_sha256s", []):
                self.get(h)
            previous = digest(e)
        return events

    def events(self):
        with self._db() as db:
            return self._events(db)

    def append(self, event_id, body, *, validate=None):
        # BEGIN IMMEDIATE holds validation and insertion in the same transaction.
        body = json.loads(canonical(body))
        with self._db() as db:
            events = self._events(db)
            old = next((e for e in events if e["id"] == event_id), None)
            if old:
                if old["body"] != body:
                    raise ValueError("archive.event_identity_conflict")
                return old
            if validate:
                validate(events)
            for h in body.get("blob_sha256s", []):
                self.get(h)
            event = dict(
                id=event_id,
                body=body,
                previous_hash=digest(events[-1])
                if events
                else digest(
                    {"schema": "llm_direct.archive/v1", "mode": "offline_synthetic"}
                ),
            )
            db.execute(
                "INSERT INTO events VALUES (?, ?, ?)",
                (event_id, canonical(event).decode(), digest(event)),
            )
            return event

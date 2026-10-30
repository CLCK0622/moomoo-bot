"""Host-scoped version tombstones, independent of individual archive directories."""

from contextlib import contextmanager
import sqlite3

from .contract import VERSION


class Lifecycle:
    def __init__(self, archive):
        self.archive = archive
        self.path = archive.anchor / "version-registry.sqlite3"

    @contextmanager
    def transaction(self):
        self.archive._check()
        if self.path.exists() and (
            self.path.is_symlink()
            or not self.path.is_file()
            or self.path.stat().st_nlink != 1
        ):
            raise ValueError("runtime.registry_regular_file_required")
        db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS versions (version TEXT PRIMARY KEY, archive_root TEXT NOT NULL, configuration_id TEXT NOT NULL, clock_origin TEXT NOT NULL, termination_reason TEXT, termination_at TEXT)"
            )
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def bind(self, configuration_id, at):
        with self.transaction() as db:
            row = db.execute(
                "SELECT archive_root, configuration_id, clock_origin, termination_reason FROM versions WHERE version=?",
                (VERSION,),
            ).fetchone()
            if row:
                if row[3] is not None:
                    raise ValueError(
                        "runtime.version_terminated_new_version_registration_required"
                    )
                if row[:3] != (str(self.archive.root), configuration_id, at):
                    raise ValueError(
                        "runtime.version_archive_configuration_or_clock_change_requires_new_registration"
                    )
            else:
                db.execute(
                    "INSERT INTO versions VALUES (?, ?, ?, ?, NULL, NULL)",
                    (VERSION, str(self.archive.root), configuration_id, at),
                )

    def require_active(self):
        with self.transaction() as db:
            row = db.execute(
                "SELECT archive_root, termination_reason FROM versions WHERE version=?",
                (VERSION,),
            ).fetchone()
            if row is None:
                raise ValueError("runtime.version_not_registered")
            if row[1] is not None:
                raise ValueError(
                    "runtime.version_terminated_new_version_registration_required"
                )
            if row[0] != str(self.archive.root):
                raise ValueError("runtime.version_archive_changed_migration_required")

    def terminate(self, reason, at):
        with self.transaction() as db:
            row = db.execute(
                "SELECT termination_reason FROM versions WHERE version=?", (VERSION,)
            ).fetchone()
            if row is None:
                raise ValueError("runtime.version_not_registered")
            if row[0] is None:
                db.execute(
                    "UPDATE versions SET termination_reason=?, termination_at=? WHERE version=?",
                    (reason, at, VERSION),
                )

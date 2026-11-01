"""Only DELETE is supported; inspect the real connection before any transaction."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from qlab.shadow15k import ShadowLedger
from qlab.shadow15k import ledger as module
from qlab.shadow15k.harness import FIXTURE, fixture_fees

GENESIS = json.loads(FIXTURE.read_bytes())["genesis"]


def reopen(book, boundary):
    if boundary == "constructor":
        return ShadowLedger(book.root, GENESIS, fixture_fees("x1"))
    with book._connection(write=boundary == "write") as db:
        return db.execute("SELECT count(*) FROM metadata").fetchone()


@pytest.mark.parametrize("mode", ["wal", "memory", "off"])
@pytest.mark.parametrize("boundary", ["constructor", "read", "write"])
def test_non_delete_mode_refuses_before_transaction(
    tmp_path, monkeypatch, mode, boundary
):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    connect = sqlite3.connect
    statements, connections, prepared_hashes, mode_sources = [], [], [], []

    def prepared_connection(*args, **kwargs):
        db = connect(*args, **kwargs)
        # MEMORY/OFF are connection-local. Return a real SQLite connection in
        # that mode; do not pretend these settings persist across connections.
        observed_mode = db.execute("PRAGMA journal_mode=" + mode).fetchone()[0]
        if observed_mode != mode:
            # Apple's SQLite refuses OFF itself. Still exercise our OFF-result
            # rejection through the real connection boundary, explicitly tagged
            # as a query-result stub rather than claiming native OFF was set.
            assert mode == "off"
            mode_sources.append("query_result_stub_native_OFF_unavailable")
            db = OffResultConnection(db)
        else:
            mode_sources.append("native_sqlite")
        prepared_hashes.append(hashlib.sha256(book.path.read_bytes()).hexdigest())
        db.set_trace_callback(statements.append)
        connections.append(db)
        return db

    monkeypatch.setattr(module.sqlite3, "connect", prepared_connection)
    with pytest.raises(ValueError, match="journal_mode_delete_required:" + mode):
        reopen(book, boundary)
    assert statements == ["PRAGMA journal_mode"]
    assert hashlib.sha256(book.path.read_bytes()).hexdigest() == prepared_hashes[0]
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")
    with closing(connect(str(book.path))) as db:
        assert db.execute("SELECT count(*) FROM metadata").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM events").fetchone() == (0,)
        if mode == "wal":
            assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    print(
        json.dumps(
            dict(
                mode=mode,
                boundary=boundary,
                refused=True,
                statements=statements,
                new_rows=0,
                connection_closed=True,
                database_bytes_preserved=True,
                mode_source=mode_sources[0],
            )
        )
    )


class OffResultConnection:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql):
        cursor = self.connection.execute(sql)
        if sql == "PRAGMA journal_mode":
            return OffResultCursor()
        return cursor


class OffResultCursor:
    def fetchone(self):
        return ("off",)


def test_persisted_wal_refuses_before_schema_creation(tmp_path, monkeypatch):
    root = tmp_path / "shadow15k"
    root.mkdir()
    path = root / "ledger.sqlite3"
    connect = sqlite3.connect
    with closing(connect(str(path))) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    before = path.read_bytes()
    statements = []

    def observed(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(module.sqlite3, "connect", observed)
    with pytest.raises(ValueError, match="journal_mode_delete_required:wal"):
        ShadowLedger(root, GENESIS, fixture_fees("x1"))
    assert statements == ["PRAGMA journal_mode"]
    assert path.read_bytes() == before
    with closing(connect(str(path))) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            == []
        )
    print(
        json.dumps(
            dict(
                mode="persisted_wal",
                refused=True,
                tables=0,
                new_rows=0,
                database_bytes_preserved=True,
                mode_not_changed=True,
            )
        )
    )


def test_delete_mode_still_opens_and_reads(tmp_path):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    for boundary in ("constructor", "read", "write"):
        reopen(book, boundary)
    with book._connection(write=False) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert db.execute("SELECT count(*) FROM events").fetchone() == (0,)
    print(
        json.dumps(
            dict(mode="delete", constructor=True, read=True, write=True, accepted=True)
        )
    )

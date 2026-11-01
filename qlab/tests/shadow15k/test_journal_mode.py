"""Only DELETE is supported; inspect the real connection before any transaction."""

import hashlib
import json
import shutil
import sqlite3
import stat
import subprocess
import sys
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


def journal_files(root):
    """Capture the refusal scene without opening SQLite or changing sidecars."""
    files = {}
    for path in sorted(root.iterdir()):
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        files[path.name] = dict(
            size=info.st_size,
            nlink=info.st_nlink,
            uid=info.st_uid,
            gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return files


def copied_logical_view(root, destination, connect):
    # Even a read-only SQL query can create/checkpoint sidecars. Diagnose a
    # complete quiescent copy, never the original rejection scene.
    shutil.copytree(root, destination)
    with closing(connect(str(destination / "ledger.sqlite3"))) as db:
        return dict(
            integrity=db.execute("PRAGMA integrity_check").fetchall(),
            metadata=db.execute("SELECT * FROM metadata ORDER BY id").fetchall(),
            events=db.execute("SELECT * FROM events ORDER BY seq").fetchall(),
        )


def external_wal_boundary(book, boundary):
    if boundary == "read":
        return book.readout({})  # The object predates the external mode switch.
    return reopen(book, boundary)


@pytest.mark.parametrize("first_boundary", ["constructor", "read", "write"])
@pytest.mark.parametrize("retry_boundary", ["constructor", "read"])
def test_external_wal_repeated_open_contract(
    tmp_path, monkeypatch, first_boundary, retry_boundary
):
    # These are native regressions for the two audited macOS runtime builds,
    # not a claim that all SQLite builds behave like their Python version.
    audited_sqlite = {(3, 9): "3.51.0", (3, 12): "3.53.1"}
    version = sys.version_info[:2]
    if sys.platform != "darwin" or sqlite3.sqlite_version != audited_sqlite.get(
        version
    ):
        pytest.skip(
            "native sidecar contract requires an audited macOS Python/SQLite pair"
        )

    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    fixture = json.loads(FIXTURE.read_bytes())
    case = next(case for case in fixture["cases"] if "orders" in case)
    assert book.register_intent(
        dict(
            intent_id="wal-preservation",
            decision_ts=fixture["decision_ts"],
            input_hash="f" * 64,
            orders=case["orders"],
        )
    )["ok"]
    connect = sqlite3.connect
    expected = copied_logical_view(book.root, tmp_path / "before-copy", connect)
    assert expected["integrity"] == [("ok",)]
    assert len(expected["metadata"]) == 1 and len(expected["events"]) == 1
    child = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import sqlite3,sys; "
            "db=sqlite3.connect(sys.argv[1]); "
            "assert db.execute('PRAGMA journal_mode=WAL').fetchone()==('wal',); "
            "db.close(); print(sqlite3.sqlite_version)",
            str(book.path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert child.stdout.strip() == sqlite3.sqlite_version
    after_external = journal_files(book.root)
    assert set(after_external) == {"ledger.sqlite3"}
    main_bytes = book.path.read_bytes()
    main_sha = after_external["ledger.sqlite3"]["sha256"]
    connections, statements = [], []

    def observed_connect(*args, **kwargs):
        db = connect(*args, **kwargs)
        connections.append(db)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(module.sqlite3, "connect", observed_connect)
    with pytest.raises(ValueError, match="^journal_mode_delete_required:wal$"):
        external_wal_boundary(book, first_boundary)
    after_first = journal_files(book.root)  # Before any bare-SQLite diagnosis.
    assert len(connections) == 1
    assert statements == ["PRAGMA journal_mode"]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
    assert after_first["ledger.sqlite3"]["sha256"] == main_sha

    connections.clear()
    statements.clear()
    if version == (3, 9):
        assert set(after_first) == {
            "ledger.sqlite3",
            "ledger.sqlite3-wal",
            "ledger.sqlite3-shm",
        }
        assert after_first["ledger.sqlite3-wal"]["size"] == 0
        assert after_first["ledger.sqlite3-shm"]["size"] == 32768
        with pytest.raises(ValueError, match="^namespace_contains_foreign_files$"):
            external_wal_boundary(book, retry_boundary)
        assert connections == []  # Both re-construction and old-object reads.
        assert statements == []
        assert journal_files(book.root) == after_first
    else:
        assert version == (3, 12)
        assert set(after_first) == {"ledger.sqlite3"}
        with pytest.raises(ValueError, match="^journal_mode_delete_required:wal$"):
            external_wal_boundary(book, retry_boundary)
        assert len(connections) == 1
        assert statements == ["PRAGMA journal_mode"]
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
        assert set(journal_files(book.root)) == {"ledger.sqlite3"}
        assert journal_files(book.root)["ledger.sqlite3"]["sha256"] == main_sha

    before_diagnosis = journal_files(book.root)
    actual = copied_logical_view(book.root, tmp_path / "after-copy", connect)
    assert actual["integrity"] == expected["integrity"] == [("ok",)]
    assert actual["metadata"] == expected["metadata"]
    assert actual["events"] == expected["events"]
    content_sha = hashlib.sha256(
        json.dumps(actual, sort_keys=True).encode()
    ).hexdigest()
    assert journal_files(book.root) == before_diagnosis  # Copy queries left it intact.
    # The external switch changes the header; every product refusal preserves
    # the exact bytes captured AFTER that switch, not just the logical rows.
    assert book.path.read_bytes() == main_bytes
    assert hashlib.sha256(book.path.read_bytes()).hexdigest() == main_sha
    print(
        json.dumps(
            dict(
                python=sys.version.split()[0],
                sqlite=sqlite3.sqlite_version,
                first_boundary=first_boundary,
                retry_boundary=retry_boundary,
                child_exit_code=child.returncode,
                files_after_first=after_first,
                files_after_retry=before_diagnosis,
                retry_connect_calls=len(connections),
                retry_sql=statements,
                main_sha256=main_sha,
                integrity_before=expected["integrity"],
                integrity_after=actual["integrity"],
                metadata_rows=len(actual["metadata"]),
                event_rows=len(actual["events"]),
                content_sha256=content_sha,
                original_scene_unchanged=True,
            )
        )
    )

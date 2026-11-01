"""Deterministic journal unlink interleavings at both pre-open boundaries."""

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from qlab.shadow15k import ShadowLedger
from qlab.shadow15k import ledger as module
from qlab.shadow15k.harness import FIXTURE, fixture_fees

GENESIS = json.loads(FIXTURE.read_bytes())["genesis"]


def reopen(book, boundary):
    if boundary == "constructor":
        ShadowLedger(book.root, GENESIS, fixture_fees("x1"))
    else:
        with book._connection(write=False) as db:
            assert db.execute("SELECT count(*) FROM metadata").fetchone() == (1,)


def connect_spy(monkeypatch):
    calls = []
    connect = module.sqlite3.connect

    def observed(*args, **kwargs):
        calls.append(args)
        return connect(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", observed)
    return calls


@contextmanager
def unlinked_entry(monkeypatch, path, *, replace_with=None):
    """A real unlinked inode plus a stale directory entry, without scheduling."""
    fd = os.open(path, os.O_RDONLY)
    path.unlink()
    info = os.fstat(fd)
    assert info.st_nlink == 0
    iterdir, lstat = Path.iterdir, Path.lstat
    observations = []

    def entries(self):
        entries = list(iterdir(self))
        if self == path.parent and path not in entries:
            entries.append(path)
        return iter(entries)

    def observed(self):
        if self == path and not observations:
            if replace_with is not None:
                path.symlink_to(replace_with)
            observations.append(info.st_nlink)
            return info
        return lstat(self)

    monkeypatch.setattr(Path, "iterdir", entries)
    monkeypatch.setattr(Path, "lstat", observed)
    try:
        yield observations
    finally:
        os.close(fd)


@pytest.mark.parametrize("boundary", ["constructor", "connection"])
def test_unlinked_whitelisted_journal_is_a_disappearance(
    tmp_path, monkeypatch, boundary
):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    journal = book.root / "ledger.sqlite3-journal"
    journal.write_bytes(b"synthetic stale journal, never handed to SQLite")
    calls = connect_spy(monkeypatch)
    with unlinked_entry(monkeypatch, journal) as observed:
        reopen(book, boundary)
        assert observed == [0]
    assert len(calls) == 1


@pytest.mark.parametrize("boundary", ["constructor", "connection"])
@pytest.mark.parametrize("name", ["ledger.sqlite3", "foreign"])
def test_unlinked_main_or_foreign_file_is_refused_before_open(
    tmp_path, monkeypatch, boundary, name
):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    path = book.root / name
    if name == "foreign":
        path.write_bytes(b"foreign stale directory entry")
    calls = connect_spy(monkeypatch)
    with unlinked_entry(monkeypatch, path):
        with pytest.raises(ValueError, match="namespace_contains_foreign_files"):
            reopen(book, boundary)
    assert calls == []


@pytest.mark.parametrize("boundary", ["constructor", "connection"])
@pytest.mark.parametrize("kind", ["foreign", "symlink", "hardlink"])
def test_namespace_guardrails_refuse_before_sqlite_open(
    tmp_path, monkeypatch, boundary, kind
):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain untouched")
    journal = book.root / "ledger.sqlite3-journal"
    if kind == "foreign":
        (book.root / "foreign").write_bytes(b"foreign")
    elif kind == "symlink":
        journal.symlink_to(outside)
    else:
        os.link(outside, journal)
        assert journal.lstat().st_nlink == 2
    calls = connect_spy(monkeypatch)
    with pytest.raises(ValueError, match="namespace_contains_foreign_files"):
        reopen(book, boundary)
    assert calls == [] and outside.read_bytes() == b"must remain untouched"


@pytest.mark.parametrize("boundary", ["constructor", "connection"])
def test_unlinked_journal_replaced_by_symlink_during_check_is_refused(
    tmp_path, monkeypatch, boundary
):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    journal = book.root / "ledger.sqlite3-journal"
    journal.write_bytes(b"synthetic stale journal")
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain untouched")
    calls = connect_spy(monkeypatch)
    with unlinked_entry(monkeypatch, journal, replace_with=outside) as observed:
        with pytest.raises(ValueError, match="namespace_contains_foreign_files"):
            reopen(book, boundary)
        assert observed == [0]
    assert journal.is_symlink() and calls == []
    assert outside.read_bytes() == b"must remain untouched"

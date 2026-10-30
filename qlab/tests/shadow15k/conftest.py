import pytest

from qlab.shadow15k import ledger


@pytest.fixture(autouse=True)
def private_physical_root(tmp_path, monkeypatch):
    # Bind independently of each constructor's untrusted requested path.
    monkeypatch.setattr(ledger, "PHYSICAL_ROOT", tmp_path.resolve())

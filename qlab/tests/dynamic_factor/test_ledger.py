import json
from concurrent.futures import ProcessPoolExecutor

import pytest

from qlab.dynamic_factor.ledger import AttemptLedger, DEFAULT_GENESIS


def append_one(args):
    path, i = args
    ledger = AttemptLedger(path)
    ledger.begin(str(i), {"factor": "same"})
    ledger.finish(str(i), "failed", reason="fixture_failure")


def test_concurrent_writers_and_restart(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(append_one, [(path, i) for i in range(16)]))
    a = AttemptLedger(path).snapshot()
    assert a["local_attempts_n"] == 16
    assert len(a["events"]) == 32
    assert a == AttemptLedger(path).snapshot()
    assert a["cumulative_n"] is None
    assert not a["certifiable"]


def test_genesis_identity_and_raw_v_observations(tmp_path):
    genesis = dict(
        DEFAULT_GENESIS,
        prior_n=12,
        authority_source={
            "reference": "synthetic-authority-not-production",
            "sha256": "a" * 64,
        },
    )
    ledger = AttemptLedger(tmp_path / "ledger.sqlite", genesis)
    ledger.begin("nan", {"factor": "X"})
    ledger.finish("nan", "success", sharpe=float("nan"))
    ledger.begin("repeat", {"factor": "X"})
    ledger.finish("repeat", "duplicate", sharpe=0)
    ledger.begin("crash", {"factor": "X"})
    a = ledger.snapshot()
    assert a["cumulative_n"] == 15
    outcomes = [x for x in a["events"] if x["event"] == "finish"]
    assert outcomes[0]["sharpe_per_period"] is None
    assert outcomes[0]["status"] == "nan"
    assert outcomes[1]["sharpe_per_period"] == 0
    assert a == AttemptLedger(ledger.path, genesis).snapshot()
    with pytest.raises(ValueError, match="genesis_mismatch"):
        AttemptLedger(ledger.path)
    with pytest.raises(ValueError, match="genesis_mismatch"):
        AttemptLedger(ledger.path, dict(genesis, prior_n=0))


def test_idempotency_conflicts_and_count(tmp_path):
    ledger = AttemptLedger(tmp_path / "ledger.sqlite")
    ledger.begin("a", {"factor": "X"})
    a = ledger.snapshot()
    ledger.begin("a", {"factor": "X"})
    assert ledger.snapshot() == a
    with pytest.raises(ValueError, match="attempt_id_conflict"):
        ledger.begin("a", {"factor": "Y"})
    with pytest.raises(ValueError, match="already_claimed"):
        ledger.begin("a", {"factor": "X"}, replay=False)
    with pytest.raises(ValueError, match="not_started"):
        ledger.finish("absent", "failed")
    ledger.finish("a", "failed", reason="x")
    finished = ledger.snapshot()
    ledger.finish("a", "failed", reason="x")
    assert ledger.snapshot() == finished
    with pytest.raises(ValueError, match="outcome_conflict"):
        ledger.finish("a", "success")


def test_hash_independent_of_database_layout(tmp_path):
    a, b = [AttemptLedger(tmp_path / name) for name in ("a.sqlite", "b.sqlite")]
    for ledger in (a, b):
        ledger.begin("one", {"b": 1, "a": 2})
        ledger.finish("one", "success", sharpe=0)
    assert a.snapshot()["n_ledger_hash"] == b.snapshot()["n_ledger_hash"]
    json.dumps(a.readout(), allow_nan=False)


def test_log_corruption_is_rejected(tmp_path):
    import sqlite3

    ledger = AttemptLedger(tmp_path / "ledger.sqlite")
    ledger.begin("one", {"x": 1})
    ledger.finish("one", "success")
    db = sqlite3.connect(ledger.path)
    event = json.loads(db.execute("SELECT body FROM events WHERE seq=1").fetchone()[0])
    event["proposal"] = {"x": 2}
    db.execute("UPDATE events SET body=? WHERE seq=1", (json.dumps(event),))
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="hash_chain_invalid"):
        ledger.snapshot()

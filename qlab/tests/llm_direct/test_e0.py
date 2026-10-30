import json
import sqlite3
import shutil
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from qlab.llm_direct.arm_n import event, project
from qlab.dynamic_factor.ledger import AttemptLedger
from qlab.llm_direct import archive as archive_module
from qlab.llm_direct import contract as contract_module
from qlab.llm_direct.adapter import adapt, initialization_plan
from qlab.llm_direct.archive import Archive
from qlab.llm_direct.contract import canonical, digest
from qlab.llm_direct.harness import run
from qlab.llm_direct.reference import ReferenceBook
from qlab.llm_direct.runtime import Runtime
from qlab.llm_direct.snapshot import build_decision
from qlab.llm_direct.synthetic import (
    OPEN,
    decision,
    execution,
    frozen,
    group,
    output,
    payload,
)
from qlab.shadow15k.harness import fixture_fees


@pytest.fixture(autouse=True)
def private_archive_root(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_module, "PHYSICAL_ROOT", tmp_path.resolve())


def test_all_synthetic_adversarial_cases(tmp_path):
    report = run(tmp_path / "harness")
    assert report["cases_passed"] >= 50
    assert (
        report["network_attempts"]
        == report["model_calls"]
        == report["authority_writes"]
        == 0
    )
    assert not report["runtime_consumable"] and not report["certifiable"]


@pytest.mark.parametrize("name", sorted(contract_module.BINDINGS))
def test_each_of_seven_bound_objects_fails_closed_on_byte_change(
    tmp_path, monkeypatch, name
):
    fixture_root = tmp_path / "changed-inputs"
    shutil.copytree(contract_module.FIXTURES, fixture_root)
    p = fixture_root / name
    p.write_bytes(p.read_bytes() + b"changed")
    monkeypatch.setattr(contract_module, "FIXTURES", fixture_root)
    with pytest.raises(ValueError, match="binding.sha_mismatch:" + name):
        contract_module.bindings()


@pytest.mark.parametrize(
    "suffix",
    [
        "EVO-353",
        "evo_774",
        "workspace-EVO-844-run",
        "EVO-851",
        "llm_paper",
        "content",
        "out",
        "launchd",
        "opend_snapshot",
    ],
)
def test_archive_forbidden_lines_have_no_directory_or_DB(tmp_path, suffix):
    path = tmp_path / suffix / "archive"
    with pytest.raises(ValueError, match="private_physical_root"):
        Archive(path)
    assert not path.exists()


def test_archive_outside_anchor_and_symlink_refused_before_writing(tmp_path):
    path = tmp_path.parent / (tmp_path.name + "-escape")
    with pytest.raises(ValueError, match="private_physical_root"):
        Archive(path)
    assert not path.exists()
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="private_physical_root"):
        Archive(tmp_path / "link" / "archive")


def test_last_event_and_raw_blob_corruption_are_detected(tmp_path):
    ar = Archive(tmp_path / "archive")
    h = ar.put(b"original raw response")
    ar.append("test", dict(kind="synthetic", blob_sha256s=[h]))
    (ar.blobs / h).write_bytes(b"changed")
    with pytest.raises(ValueError, match="blob_hash_mismatch"):
        ar.events()
    (ar.blobs / h).write_bytes(b"original raw response")
    with sqlite3.connect(str(ar.path)) as db:
        row = json.loads(db.execute("SELECT body FROM events").fetchone()[0])
        row["body"]["kind"] = "changed"
        db.execute("UPDATE events SET body=?", (canonical(row).decode(),))
    with pytest.raises(ValueError, match="event_hash_corrupt"):
        ar.events()


def test_concurrent_conflicting_ID_has_only_one_winner(tmp_path):
    ar = Archive(tmp_path / "archive")

    def append(n):
        try:
            ar.append("same-ID", dict(kind="synthetic", value=n))
            return True
        except ValueError as exc:
            assert "event_identity_conflict" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, [1, 2])) == [False, True]
    assert len(Archive(tmp_path / "archive").events()) == 1


def test_forecast_difference_can_pass_when_actual_final_decisions_equal(tmp_path):
    fees = fixture_fees("x2")
    d = decision(fees)
    a = group(
        Archive(tmp_path / "archive"),
        d,
        [canonical(output(d, n)) for n in [1000, 2000, 3000, 4000, 5000]],
    )
    report = a.replay("synthetic-group", d, execution(d, fees), fees, at=OPEN)
    assert report["passed"] and len(set(r["G"] for r in report["results"])) == 5
    assert set(report["pairwise_mismatches"].values()) == {0}


def test_group_captures_execution_once_despite_caller_mutation(tmp_path, monkeypatch):
    import qlab.llm_direct.runtime as module

    fees = fixture_fees("x2")
    d = decision(fees)
    a = group(Archive(tmp_path / "archive"), d, [canonical(output(d))] * 5)
    x = execution(d, fees)
    frozen_sha = digest(x)
    original_adapt = module.adapt

    def mutate_external_after_adapt(*args):
        result = original_adapt(*args)
        x["raw_open_usd"]["AAPL"] = "19"
        return result

    monkeypatch.setattr(module, "adapt", mutate_external_after_adapt)
    report = a.replay("synthetic-group", d, x, fees, at=OPEN)
    assert report["passed"] and report["execution_snapshot_sha256"] == frozen_sha
    assert {r["execution_snapshot_sha256"] for r in report["results"]} == {frozen_sha}


def test_termination_survives_restart_and_forbids_configuration_switch(tmp_path):
    ar = Archive(tmp_path / "archive")
    rt = Runtime(ar)
    f = frozen(rt)
    rt.terminate("pinned_snapshot_unavailable", OPEN)
    reopened = Runtime(Archive(tmp_path / "archive"))
    with pytest.raises(ValueError, match="version_terminated"):
        frozen(reopened)
    changed = deepcopy(f["configuration"])
    changed["model_snapshot"] = "latest"
    with pytest.raises(ValueError, match="version_terminated"):
        reopened.freeze(at=OPEN, configuration=changed, aggregation=f["aggregation"])
    with pytest.raises(ValueError, match="version_terminated"):
        frozen(Runtime(Archive(tmp_path / "different-directory")))


def test_startup_is_QQQ_only_fee_feasible_and_does_not_consume_model_output():
    fees = fixture_fees("x2")
    p = payload(fees)
    p["policy_state"]["global_position"] = 0
    p["x2_control_state"]["inventory_qty"]["QQQ"] = 0
    p["x2_control_state"]["available_cash_usd"] = "15000"
    p["required_action_plan_M"]["QQQ"] = 0
    d = build_decision(p)
    x = execution(d, fees)
    r = initialization_plan(d, x, fees)
    assert r["final"]["QQQ"] == 6 and r["turnover"] == "0.2"
    assert all(o["symbol"] == "QQQ" and not o["protective"] for o in r["orders"])
    assert float(r["available_cash"]) >= 300
    with pytest.raises(ValueError, match="startup_has_no_LLM_decision"):
        adapt(b"not even JSON", d, x, fees)


def test_N_configuration_changes_count_once_and_fixture_projection_is_read_only(
    tmp_path,
):
    chain = AttemptLedger(tmp_path / "synthetic-chain.sqlite3")
    config = dict(
        prompt_version="p1", model_snapshot="snapshot1", parameters={}, ruleset="r1"
    )
    for i in range(2):
        c = dict(config, prompt_version="p%d" % i)
        chain.record(
            "reserve:%d" % i, event("configuration_reserved", "EVO883_FACTOR", c)
        )
        for j in range(2):
            chain.record(
                "evaluation:%d:%d" % (i, j),
                event(
                    "market_outcome_evaluated",
                    "EVO883_FACTOR",
                    c,
                    evaluation_id="outcome:%d:%d" % (i, j),
                    evidence_sha256=digest([i, j]),
                ),
            )
    before = chain.snapshot()["n_ledger_hash"]
    r = project(chain.safe_snapshot(), "EVO883_FACTOR")
    assert r["observed_N_config"] == 2
    assert r["rows"][1]["observed_N"] == 0
    assert r["cumulative_n"] is None and not r["certifiable"]
    assert chain.snapshot()["n_ledger_hash"] == before
    c = dict(config, prompt_version="p0")
    chain.record(
        "unknown-repair",
        event(
            "generation_request",
            "EVO883_FACTOR",
            c,
            actual_request_id="unknown-internal",
            request_count_known=False,
            evidence_sha256=digest("unknown"),
        ),
    )
    n = project(chain.safe_snapshot(), "EVO883_FACTOR")
    assert n["observed_N_generation_requests"] is None and not n["n_complete"]


def test_reference_missing_day_cannot_be_skipped_or_backfilled(tmp_path):
    import qlab.llm_direct.reference as module
    from qlab.llm_direct.contract import sha

    book = ReferenceBook(Archive(tmp_path / "archive"), "R1_MOM20")
    book.freeze(
        at="2026-10-29T21:00:00Z",
        sessions=["2026-10-30", "2026-11-02"],
        producer_source_sha256=sha(open(module.__file__, "rb").read()),
    )
    with pytest.raises(ValueError, match="missing_day_no_backfill_or_skip"):
        book.seal_day(
            session="2026-11-02",
            at="2026-11-02T21:00:00Z",
            source_bytes=b"synthetic-source",
            ledger_bytes=b"synthetic-ledger",
            return_bytes=b"synthetic-returns",
            source_run_id="synthetic-run",
        )

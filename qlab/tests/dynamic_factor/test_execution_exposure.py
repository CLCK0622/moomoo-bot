"""F-LEGACY-01 numeric equivalence, frozen cross-version receipts, S-CASH-01."""

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from qlab.dynamic_factor.contract import digest, sha256
from qlab.dynamic_factor.conventions import load_conventions
from qlab.dynamic_factor.execution_exposure import verify_execution_exposure
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from qlab.dynamic_factor.execution_state import necessary_execution_state_known
from qlab.dynamic_factor.noncash_v3 import zero_exposure
from test_execution_risk_history import history, next_date, accounting
from test_reference_day_cash import cash_close
from v3_test_helpers import synthetic_guard, synthetic_zero_state


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize(
    "variant",
    [
        "zero",
        "held-QQQ",
        "held-permitted",
        "B",
        "unknown",
        "child",
        "undeclared",
        "missing-inventory",
        "rights",
        "receivables",
        "pending-missing",
        "pending-nonlist",
        "pending-malformed",
        "pending-buy-B",
        "pending-buy-unknown",
        "pending-buy-child",
        "pending-buy-extra",
        "pending-buy-QQQ",
        "pending-sell-B",
        "pending-zero-B",
        "pending-bool",
        "pending-negative",
        "B-before-malformed",
        "rights-before-B",
        "malformed-before-B-buy",
        "B-buy-before-malformed",
        "unknown-before-B",
    ],
)
def test_F_LEGACY_01_separate_B_predicate_numeric_domain_equivalence(
    initial, variant, record_property
):
    guard = synthetic_guard(blocked=[load_conventions().profile["universe"][0]])
    state = synthetic_zero_state(guard)
    blocked = guard["B"][0]
    unknown = guard["unknown"][0] if guard["unknown"] else "SYNTHETIC_UNKNOWN"
    if not guard["unknown"]:
        guard["unknown"] = [unknown]
        state["inventory"][unknown] = 0
    child = next(iter(guard["children"]))
    allowed = next(
        s
        for s in guard["request"]["catalog"]["universe"]
        if s not in set(guard["B"]) | set(guard["unknown"])
    )

    def held(symbol):
        state["inventory"][symbol] = 1
        state["age"][symbol] = 1
        state["origin"][symbol] = "SYNTHETIC"

    def pending(symbol, side="BUY", quantity=1):
        return dict(symbol=symbol, side=side, quantity=quantity)

    if variant.startswith("held-"):
        held("QQQ" if variant == "held-QQQ" else allowed)
    if variant in ("B", "B-before-malformed", "rights-before-B", "unknown-before-B"):
        held(blocked)
    if variant == "unknown":
        held(unknown)
    if variant == "child":
        held(child)
    if variant == "undeclared":
        held("UNDECLARED_CHILD")
    if variant == "missing-inventory":
        state["inventory"].pop(child)
    if variant in ("rights", "rights-before-B"):
        state["rights"] = {"R": {"amount": 1}}
    if variant == "receivables":
        state["receivables"] = {"R": {"amount": 1}}
    if variant == "pending-missing":
        state.pop("pending_orders")
    if variant == "pending-nonlist":
        state["pending_orders"] = {}
    if variant in ("pending-malformed", "B-before-malformed"):
        state["pending_orders"] = [{}]
    targets = {
        "pending-buy-B": blocked,
        "pending-buy-unknown": unknown,
        "pending-buy-child": child,
        "pending-buy-extra": "EXTRA",
        "pending-buy-QQQ": "QQQ",
    }
    if variant in targets:
        state["pending_orders"] = [pending(targets[variant])]
    if variant == "pending-sell-B":
        state["pending_orders"] = [pending(blocked, "SELL")]
    if variant == "pending-zero-B":
        state["pending_orders"] = [pending(blocked, quantity=0)]
    if variant == "pending-bool":
        state["pending_orders"] = [pending(allowed, quantity=True)]
    if variant == "pending-negative":
        state["pending_orders"] = [pending(allowed, quantity=-1)]
    if variant == "malformed-before-B-buy":
        state["pending_orders"] = [{}, pending(blocked)]
    if variant == "B-buy-before-malformed":
        state["pending_orders"] = [pending(blocked), {}]
    if variant == "unknown-before-B":
        state["unknown_components"] = ["UNKNOWN"]
    before = deepcopy(state)

    def observed(call):
        try:
            return {"accepted": True, "value": call()}
        except ValueError as e:
            return {"accepted": False, "reason": str(e)}

    original = observed(lambda: zero_exposure(state, guard, initial=initial))

    def execution_only():
        necessary_execution_state_known(state)
        return verify_execution_exposure(state, guard, initial=initial)

    actual = observed(execution_only)
    assert actual == original, (variant, initial, original, actual)
    assert state == before
    record_property(
        "exposure_equivalence",
        json.dumps(
            dict(variant=variant, initial=initial, original=original, actual=actual)
        ),
    )


def _fixed_legacy_source(repo, destination):
    """Materialize the reviewed Git object; missing objects are a hard failure."""
    head = "f827776c7a4b3f270ad87367191b06314a7f3c28"
    archive = subprocess.run(
        ["git", "archive", "--format=tar", head],
        cwd=repo,
        capture_output=True,
    )
    assert archive.returncode == 0, archive.stderr.decode()
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tree:
        for member in tree.getmembers():
            target = (destination / member.name).resolve()
            assert destination.resolve() in target.parents
            assert member.isfile() or member.isdir(), member.name
        tree.extractall(destination)
    return destination


def test_F_LEGACY_01_frozen_review_34_actor_306_calls_original_bytes(
    tmp_path, record_property
):
    fixtures = Path(__file__).parent / "fixtures/legacy-origin-b25r"
    manifest = json.loads((fixtures / "manifest.json").read_bytes())
    for name, identity in manifest["files"].items():
        raw = (fixtures / name).read_bytes()
        assert len(raw) == identity["bytes"] and sha256(raw) == identity["sha256"]
    raw = (fixtures / "frozen-origin-inputs.json").read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "9d3d7c3d6b0271fcb1800129334c73bf024009225cbb449d6d4380b38465d612"
    )
    script = tmp_path / "independent_old_receipts.py"
    script.write_bytes((fixtures / "independent_old_receipts.py.fixture").read_bytes())
    repo = Path(__file__).resolve().parents[3]
    repo = _fixed_legacy_source(repo, tmp_path / "f827776")
    command = [
        sys.executable,
        "-B",
        str(script),
        str(repo),
        str(tmp_path / "replay"),
        str(fixtures / "frozen-origin-inputs.json"),
        "--expect-legacy-compatible",
    ]
    env = dict(
        os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1"
    )
    run = subprocess.run(command, cwd=repo / "qlab", env=env, capture_output=True)
    (tmp_path / "stdout").write_bytes(run.stdout)
    (tmp_path / "stderr").write_bytes(run.stderr)
    assert run.returncode == 0, run.stderr.decode()
    output = json.loads((tmp_path / "replay/observations.json").read_bytes())
    rows = output["rows"]
    assert len(rows) == 306 and output["old_receipts"] == 34
    assert sum(r["result"]["ok"] for r in rows) == 238
    assert sum(len(r["actual_reader_calls"]) for r in rows) == 34
    assert not json.loads((tmp_path / "replay/compatibility-errors.json").read_bytes())
    assert (fixtures / "frozen-origin-inputs.json").read_bytes() == raw
    record_property(
        "frozen_replay",
        json.dumps(
            dict(
                argv=command,
                exit_code=run.returncode,
                calls=306,
                accepted=238,
                reader_calls=34,
                input_sha256=sha256(raw),
            )
        ),
    )


def test_B01_new_source_old_receipts_all_refused_before_reader_or_worker(
    tmp_path, record_property
):
    fixtures = Path(__file__).parent / "fixtures/legacy-origin-b25r"
    frozen = fixtures / "frozen-origin-inputs.json"
    script = tmp_path / "independent_old_receipts.py"
    raw = (fixtures / "independent_old_receipts.py.fixture").read_bytes()
    script.write_bytes(raw)
    # Run the original script unchanged; observe child-worker launches around it.
    # This interpreter is the test driver, not a business worker.
    wrapper = tmp_path / "observe_workers.py"
    wrapper.write_text(
        "import json,runpy,sys\n"
        "script,audit_output=sys.argv[1:3]\n"
        "sys.argv=[script]+sys.argv[3:]\n"
        "workers=[]\n"
        "def audit(event,args):\n"
        "    if event.startswith(('subprocess.','os.exec','os.spawn')) or "
        "event in {'os.fork','os.system'}: workers.append(event)\n"
        "sys.addaudithook(audit)\n"
        "runpy.run_path(script,run_name='__main__')\n"
        "with open(audit_output,'w') as f: json.dump(workers,f)\n",
        encoding="utf-8",
    )
    repo = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "-B",
        str(wrapper),
        str(script),
        str(tmp_path / "workers.json"),
        str(repo),
        str(tmp_path / "replay"),
        str(frozen),
    ]
    env = dict(
        os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1"
    )
    run = subprocess.run(command, cwd=repo / "qlab", env=env, capture_output=True)
    assert run.returncode == 0, run.stderr.decode()
    output = json.loads((tmp_path / "replay/observations.json").read_bytes())
    rows = output["rows"]
    assert output["old_receipts"] == 34 and len(rows) == 306
    assert all(not row["result"]["ok"] for row in rows)
    assert {row["result"]["reason"] for row in rows} == {
        "B.zero_origin_or_actor_mismatch"
    }
    assert sum(len(row["actual_reader_calls"]) for row in rows) == 0
    assert json.loads((tmp_path / "workers.json").read_bytes()) == []
    assert script.read_bytes() == raw
    record_property(
        "new_source_old_receipts",
        json.dumps(dict(argv=command, calls=306, accepted=0, reader=0, worker=0)),
    )


def test_B01_missing_fixed_legacy_git_object_fails_instead_of_skip(
    monkeypatch, tmp_path
):
    def missing(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, b"", b"missing Git object")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(AssertionError, match="missing Git object"):
        _fixed_legacy_source(tmp_path, tmp_path / "absent")


@pytest.mark.parametrize("kind", ["dict", "bool", "None", "stale"])
def test_S_CASH_01_bad_proof_records_refusal_and_retains_prior_state(
    kind, record_property
):
    _, _, proof, hist = cash_close()
    before = hist.snapshot()
    journal_before = json.loads(hist.export_bytes())
    row = accounting(hist, next_date(hist))
    supplied = {
        "dict": {"sha256": proof.sha256, "verified": True},
        "bool": True,
        "None": None,
        "stale": proof,
    }[kind]
    with pytest.raises(ValueError) as rejected:
        hist.observe_close(
            next_date(hist),
            row,
            [],
            expected_accounting_sha256=digest(row),
            expected_fills_sha256=digest([]),
            cash_proof=supplied,
        )
    after = hist.snapshot()
    journal = json.loads(hist.export_bytes())
    assert len(journal["declarations"]) == len(journal_before["declarations"]) + 1
    assert journal["declarations"][-1]["status"] == "rejected"
    assert after["complete"] is False and after["risk"] is None
    assert (
        after["state"] == before["state"]
        and after["close_session"] == before["close_session"]
    )
    assert after["reasons"] == [str(rejected.value)]
    assert str(rejected.value) == (
        "accounting.cash_proof_state_or_scope_mismatch"
        if kind == "stale"
        else "accounting.owned_cash_proof_required"
    )
    record_property(
        "cash_proof_refusal",
        json.dumps(
            dict(
                kind=kind,
                reason=str(rejected.value),
                declarations_added=1,
                complete=after["complete"],
                state_preserved=True,
            )
        ),
    )


def test_invalid_proof_refusal_replays_even_without_receivables():
    hist, args = history()
    row = accounting(hist, next_date(hist))
    with pytest.raises(ValueError, match="owned_cash_proof_required"):
        hist.observe_close(
            next_date(hist),
            row,
            [],
            expected_accounting_sha256=digest(row),
            expected_fills_sha256=digest([]),
            cash_proof={},
        )
    raw = hist.export_bytes()
    restored = RiskHistory.restore(
        raw,
        expected_sha256=sha256(raw),
        expected_book_id=args["book_id"],
        expected_scope=args["scope"],
        policy=args["policy"],
    )
    assert restored.export_bytes() == raw

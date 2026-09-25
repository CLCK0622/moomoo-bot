"""End-to-end tests for the Qlib generator + RD-Agent budget skeleton.

Skipped automatically where Qlib is not installed (the lean qlab runtime venv),
so this never breaks the offline suite. Runs under the `qlab-py312` venv:

    ~/.venvs/qlab-py312/bin/python -m pytest tests/test_qlib_gen.py -q

Boundary under test: Qlib is a *generator* (factor engine + honest-N ledger);
it is never a verdict. The budget guard is a *hard* stop, not a hint.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]          # .../qlab
DAILY_FULL = REPO / "data" / "daily_full"

pytest.importorskip("qlib", reason="qlib not in this venv (lean runtime) — skip")


# ---------------------------------------------------------------------------
# Budget guard — no Qlib needed, but lives here with the rest of the plumbing.
# ---------------------------------------------------------------------------
def test_budget_guard_hard_stops(tmp_path):
    from tools.qlib_gen.rdagent_budget import BudgetGuard, guarded_call, BudgetExceeded

    ledger = tmp_path / "spend.jsonl"
    guard = BudgetGuard(cap_usd=0.01, ledger_path=ledger)

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok", 1000, 200

    # A cheap call within cap goes through and is recorded.
    guarded_call(guard, model="gpt-4o-mini", est_in_tokens=1000, est_out_tokens=200,
                 label="t1", fn=fn)
    assert guard.n_calls == 1
    assert ledger.exists() and ledger.read_text().strip()

    # A call that would exceed the cap must RAISE and must NOT invoke fn.
    before = calls["n"]
    with pytest.raises(BudgetExceeded):
        guarded_call(guard, model="claude-opus-4-8",
                     est_in_tokens=1_000_000, est_out_tokens=1_000_000,
                     label="t2-overspend", fn=fn)
    assert calls["n"] == before, "fn was called despite over-cap — cap is not a hard stop"


def test_budget_guard_resumes_spend_across_restart(tmp_path):
    from tools.qlib_gen.rdagent_budget import BudgetGuard, guarded_call

    ledger = tmp_path / "spend.jsonl"
    g1 = BudgetGuard(cap_usd=1.0, ledger_path=ledger)
    guarded_call(g1, model="gpt-4o", est_in_tokens=100_000, est_out_tokens=20_000,
                 label="r1", fn=lambda: ("x", 100_000, 20_000))
    spent = g1.spent_usd
    # New guard over the same ledger must resume, not reset to zero.
    g2 = BudgetGuard(cap_usd=1.0, ledger_path=ledger)
    assert abs(g2.spent_usd - spent) < 1e-9
    assert g2.n_calls == 1


def test_unknown_model_fails_closed():
    from tools.qlib_gen.rdagent_budget import estimate_usd, BudgetExceeded
    with pytest.raises(BudgetExceeded):
        estimate_usd("some-unpriced-model", 1000, 1000)


# ---------------------------------------------------------------------------
# Qlib generator — build store, compute factors, honest-N manifest.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mini_store(tmp_path_factory):
    if not DAILY_FULL.exists() or not any(DAILY_FULL.glob("*.parquet")):
        pytest.skip("committed data/daily_full parquets absent")
    from tools.qlib_gen.build_qlib_data import build
    out = tmp_path_factory.mktemp("qlib_store")
    man = build(DAILY_FULL, out, limit=3, max_workers=2)
    assert man["n_instruments"] == 3
    return out / "bin"


def test_factor_export_honest_n(mini_store, tmp_path):
    from tools.qlib_gen import factor_export as fx
    man = fx.export(
        mini_store, tmp_path / "factors",
        start="2023-01-01", end="2023-12-31", factor_set="core",
        # inject two guaranteed-discards to prove N counts failures:
        extra={"BROKEN": "Ref($close,)/NoSuchOp($x)",
               "future_nan": "$close/Ref($close,999999)-1"},
        repo_root=REPO,
    )
    # honest N == everything attempted, INCLUDING the two discards.
    assert man["n_expressions_attempted"] == man["n_exported"] + man["n_discarded"]
    assert man["n_discarded"] >= 2
    assert "BROKEN" in man["discarded"] and "future_nan" in man["discarded"]
    # verdict authority is never Qlib
    assert "qlab.events" in man["acceptance_authority"]
    # tidy parquet exists with the handoff schema
    df_path = tmp_path / "factors" / "factors.parquet"
    assert df_path.exists()
    import pandas as pd
    df = pd.read_parquet(df_path)
    assert list(df.columns) == ["datetime", "instrument", "factor", "value"]
    assert df["value"].notna().all()
    # manifest is on disk and self-describing
    disk = json.loads((tmp_path / "factors" / "manifest.json").read_text())
    assert disk["n_expressions_attempted"] == man["n_expressions_attempted"]


def test_rdagent_skeleton_accumulates_n_via_trial_ledger(mini_store, tmp_path):
    from tools.qlib_gen.rdagent_budget import BudgetGuard
    from tools.qlib_gen.rdagent_skeleton import run_trial, open_ledger

    # Seed the persisted台账 with prior human trials (the ~7 pre-existing),
    # then let the miner add rounds. N is read back from cumulative_n().
    ledger = open_ledger(tmp_path / "trial_ledger.json")
    ledger.register_run(run_id="human/prior", source="manual",
                        n_trials_total=7, n_evaluated=7)
    assert ledger.cumulative_n() == 7

    guard = BudgetGuard(cap_usd=1.0, ledger_path=tmp_path / "spend.jsonl")
    combined = run_trial(
        mini_store, tmp_path / "trial", guard=guard, ledger=ledger, rounds=2,
        start="2023-01-01", end="2023-12-31", repo_root=REPO,
    )
    assert combined["rounds_run"] == 2
    # mock proposes 4/round * 2 rounds = 8, plus prior 7 -> cumulative 15
    assert combined["miner_attempted_this_run"] == 8
    assert combined["cumulative_n_trials"] == 15
    assert ledger.cumulative_n() == 15           # persisted, authoritative
    assert combined["llm_spent_usd"] == 0.0      # mock model priced at 0
    # a fresh ledger over the same file must resume the count (no reset)
    assert open_ledger(tmp_path / "trial_ledger.json").cumulative_n() == 15


def test_run_trial_requires_ledger_no_fail_open(mini_store, tmp_path):
    """The exact seam 工部尚书 flagged: N must be fail-closed, never defaulted."""
    from tools.qlib_gen.rdagent_budget import BudgetGuard
    from tools.qlib_gen.rdagent_skeleton import run_trial
    guard = BudgetGuard(cap_usd=1.0, ledger_path=tmp_path / "s.jsonl")
    with pytest.raises((ValueError, TypeError)):
        run_trial(mini_store, tmp_path / "t", guard=guard, rounds=1,  # no ledger=
                  start="2023-01-01", end="2023-03-31", repo_root=REPO)


def test_factor_export_registers_into_ledger_fail_closed(mini_store, tmp_path):
    from tools.qlib_gen import factor_export as fx
    from tools.qlib_gen.rdagent_skeleton import open_ledger
    ledger = open_ledger(tmp_path / "led.json")
    man = fx.export(mini_store, tmp_path / "f", start="2023-01-01", end="2023-06-30",
                    factor_set="core", ledger=ledger, run_id="qlib/test", repo_root=REPO)
    # the run is registered; gate N is the cumulative, not the per-run attempted
    assert man["cumulative_n_trials"] == ledger.cumulative_n()
    assert man["cumulative_n_trials"] == man["n_expressions_attempted"]  # first & only run
    assert ledger.runs[0].n_trials_total == man["n_expressions_attempted"]


def test_rdagent_skeleton_stops_when_budget_exhausted(mini_store, tmp_path):
    from tools.qlib_gen.rdagent_budget import BudgetGuard
    from tools.qlib_gen.rdagent_skeleton import run_trial, open_ledger

    # Price the miner's calls above zero and set a cap that funds < 1 call.
    guard = BudgetGuard(cap_usd=0.0000001, ledger_path=tmp_path / "l.jsonl")
    ledger = open_ledger(tmp_path / "led2.json")

    def paid_llm(prompt):
        return ("mrev = Ref($close,2)/$close-1\n", 5000, 2000)

    combined = run_trial(
        mini_store, tmp_path / "trial2", guard=guard, ledger=ledger, llm_fn=paid_llm,
        model="gpt-4o", rounds=3, start="2023-01-01", end="2023-06-30",
        repo_root=REPO,
    )
    assert combined["rounds_run"] == 0 or combined["stopped_reason"].startswith("budget")
    assert guard.spent_usd <= guard.cap_usd + 1e-9
    # budget stopped before any round registered -> ledger stays empty (no phantom N)
    assert ledger.cumulative_n() == 0

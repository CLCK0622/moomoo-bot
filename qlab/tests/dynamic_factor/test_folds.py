from dataclasses import asdict

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.folds import (
    FeatureRow,
    FitReceipt,
    TrainRow,
    _run_walk_forward_unbound as run_walk_forward,
)
from qlab.dynamic_factor.ledger import AttemptLedger


def fixture():
    calendar = [f"2026-01-{d:02}" for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 20, 21)]
    bounds = [(0, 1, 3, 4), (3, 4, 6, 7), (6, 7, 9, 10)]
    folds = [
        dict(
            zip(
                ("train_start", "train_end", "test_start", "test_end"),
                (calendar[n] for n in bound),
            ),
            fold_id=str(i),
        )
        for i, bound in enumerate(bounds)
    ]
    manifest = dict(calendar=calendar, label_horizon=1, embargo=0, folds=folds)
    rows = [
        dict(
            date=d,
            features={"x": i},
            target=i / 10,
            label_end=calendar[min(i + 1, len(calendar) - 1)],
        )
        for i, d in enumerate(calendar)
    ]
    return manifest, rows


class Miner:
    def mine(self, train):
        assert all(isinstance(r, TrainRow) for r in train)
        return [{"expression": "same"}, {"expression": "same"}]


class Model:
    def __init__(self, training_value):
        self.training_value = training_value

    def predict(self, test):
        assert all(isinstance(r, FeatureRow) and not hasattr(r, "target") for r in test)
        return [self.training_value for _ in test]


class Fitter:
    def fit(self, train, proposals):
        train_hash = digest([asdict(r) for r in train])
        return FitReceipt(
            Model(sum(r.target for r in train)),
            tuple(r.date for r in train),
            train_hash,
            digest(proposals),
        )


def test_three_folds_really_remine_and_refit_and_predict(tmp_path):
    manifest, rows = fixture()
    contexts = []

    def new_miner(ctx):
        contexts.append(ctx)
        return Miner()

    ledger = AttemptLedger(tmp_path / "ledger.sqlite")
    result = run_walk_forward(
        manifest,
        rows,
        miner_factory=new_miner,
        fitter_factory=lambda ctx: Fitter(),
        ledger=ledger,
        run_id="three",
    )
    assert len(contexts) == 3
    outputs = result["metrics"]["folds"]
    assert len(outputs) == 3
    assert len({x["train_sha256"] for x in outputs}) == 3
    assert [x["predictions"][0] for x in outputs] == pytest.approx([0.1, 0.7, 1.3])
    assert (
        ledger.snapshot()["local_attempts_n"] == 9
    )  # 3 invocations + 6 proposals (duplicates kept)
    assert result["reasons"] == [
        "ledger_authority_unset",
        "ledger_history_count_unknown",
    ]
    # Same run is single-use; a restart cannot silently consume the holdout again.
    retried = run_walk_forward(
        manifest,
        rows,
        miner_factory=new_miner,
        fitter_factory=lambda ctx: Fitter(),
        ledger=ledger,
        run_id="three",
    )
    assert "attempt_already_claimed" in retried["reasons"]
    assert len(contexts) == 3


def test_test_targets_never_enter_fit_or_prediction(tmp_path):
    manifest, rows = fixture()
    manifest["folds"] = manifest["folds"][:1]
    for i in (3, 4):
        rows[i].pop("target")
        rows[i].pop("label_end")
    result = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: Miner(),
        fitter_factory=lambda ctx: Fitter(),
        ledger=AttemptLedger(tmp_path / "ledger.sqlite"),
        run_id="blind",
    )
    assert len(result["metrics"]["folds"]) == 1


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda m, r: m.update(embargo=1), "wf.embargo_violation"),
        (lambda m, r: m.update(label_horizon=2), "wf.future_label_rejected"),
        (
            lambda m, r: r[0].update(label_end=m["calendar"][3]),
            "wf.label_horizon_mismatch",
        ),
        (
            lambda m, r: m["folds"][1].update(test_start=m["calendar"][4]),
            "wf.nonforward_or_overlapping_fold",
        ),
        (lambda m, r: r.append(r[0]), "wf.input_dates_invalid"),
    ],
)
def test_leakage_rejected_before_discovery(tmp_path, mutation, reason):
    manifest, rows = fixture()
    mutation(manifest, rows)
    calls = []
    r = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: calls.append(ctx),
        fitter_factory=lambda ctx: Fitter(),
        ledger=AttemptLedger(tmp_path / "ledger.sqlite"),
        run_id="leak",
    )
    assert reason in r["reasons"]
    assert not calls


def test_prefit_receipt_and_reused_factory_rejected(tmp_path):
    manifest, rows = fixture()

    class FalseFitter:
        def fit(self, train, proposals):
            return FitReceipt(
                Model(0),
                tuple(r["date"] for r in rows),
                "full-history",
                digest(proposals),
            )

    ledger = AttemptLedger(tmp_path / "ledger.sqlite")
    r = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: Miner(),
        fitter_factory=lambda ctx: FalseFitter(),
        ledger=ledger,
        run_id="full-history",
    )
    assert "wf.full_history_or_mutated_fit_rejected" in r["reasons"]
    shared = Miner()
    r = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: shared,
        fitter_factory=lambda ctx: Fitter(),
        ledger=ledger,
        run_id="shared",
    )
    assert len(r["metrics"]["folds"]) == 3
    assert [f["status"] for f in r["metrics"]["folds"]] == [
        "success",
        "invalid",
        "blocked",
    ]
    assert "wf.reused_fold_instance" in r["reasons"]


def test_failed_discovery_attempt_survives_restart(tmp_path):
    manifest, rows = fixture()

    class BrokenMiner:
        def mine(self, train):
            raise RuntimeError("synthetic failure")

    path = tmp_path / "ledger.sqlite"
    r = run_walk_forward(
        manifest,
        rows,
        miner_factory=lambda ctx: BrokenMiner(),
        fitter_factory=lambda ctx: Fitter(),
        ledger=AttemptLedger(path),
        run_id="failed",
    )
    assert "wf.adapter_error:RuntimeError" in r["reasons"]
    restarted = AttemptLedger(path).snapshot()
    assert restarted["local_attempts_n"] == 1
    assert any(e.get("status") == "failed" for e in restarted["events"])
    ledger_readout = AttemptLedger(path).recorded("walk-forward-status/failed/0")
    assert ledger_readout
    assert ledger_readout["attempted"] and ledger_readout["status"] == "invalid"

"""Train-only discover/select/fit orchestration, with explicit fit receipts.

Trusted adapters are injected Python objects, never generated Python or a
serialized full-history model. This controls what is passed to adapters; it is
not an OS sandbox against a malicious adapter reading other files itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .contract import code_sha, digest, result
from .fees import finite
from .validation import calendar_index, fold_reasons


@dataclass(frozen=True)
class FeatureRow:
    date: str
    features: tuple


@dataclass(frozen=True)
class TrainRow:
    date: str
    features: tuple
    target: float
    label_end: str


@dataclass(frozen=True)
class FoldContext:
    fold_id: str
    train_sha256: str
    label_horizon: int
    embargo: int


@dataclass(frozen=True)
class FitReceipt:
    model: object
    fit_dates: tuple
    train_sha256: str
    proposals_sha256: str


def _features(row):
    features = row["features"]
    if not features or not all(
        isinstance(k, str) and finite(v) for k, v in features.items()
    ):
        raise ValueError("wf.invalid_features")
    return tuple(sorted(features.items()))


def run_walk_forward(manifest, rows, *, miner_factory, fitter_factory, ledger, run_id):
    """Create a new miner, fitter and model per fold. No strategy is bundled.

    miner.mine(train_tuple) -> ALL proposed JSON specs (including duplicates).
    fitter.fit(train_tuple, proposals_tuple) -> FitReceipt; selection/scaling and
    fitting must happen inside that call. predict receives feature rows only.
    Invocation begins also count locally, conservatively, until EVO-883 defines N.
    A consumed run/fold ID cannot execute again, even after an interrupted call.
    """
    reasons = fold_reasons(manifest)
    outputs, instances = [], []
    inputs = {"manifest": manifest, "rows": rows, "run_id": run_id}
    active = []
    adapter_sources = {}
    try:
        if "ledger_unreadable_or_corrupt" in ledger.safe_snapshot()["reasons"]:
            raise ValueError("ledger_unreadable_or_corrupt")
        if reasons:
            raise ValueError(reasons[0])
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("wf.run_id_missing")
        adapter_sources = {
            "adapter/miner_factory": code_sha(miner_factory),
            "adapter/fitter_factory": code_sha(fitter_factory),
        }
        index = calendar_index(manifest["calendar"])
        dates = [r["date"] for r in rows]
        if dates != sorted(set(dates)) or any(d not in index for d in dates):
            raise ValueError("wf.input_dates_invalid")
        by_date = {r["date"]: r for r in rows}
        for fold in manifest["folds"]:
            active = []
            calendar = manifest["calendar"]
            train_dates = calendar[
                index[fold["train_start"]] : index[fold["train_end"]] + 1
            ]
            test_dates = calendar[
                index[fold["test_start"]] : index[fold["test_end"]] + 1
            ]
            train = []
            for d in train_dates:
                row = by_date[d]
                endpoint = index[d] + manifest["label_horizon"]
                if endpoint + manifest["embargo"] >= index[fold["test_start"]]:
                    raise ValueError("wf.future_label_rejected")
                if row["label_end"] != calendar[endpoint]:
                    raise ValueError("wf.label_horizon_mismatch")
                if not finite(row["target"]):
                    raise ValueError("wf.invalid_training_label")
                train.append(
                    TrainRow(d, _features(row), row["target"], row["label_end"])
                )
            train = tuple(train)
            test = tuple(FeatureRow(d, _features(by_date[d])) for d in test_dates)
            train_hash = digest([asdict(r) for r in train])
            ctx = FoldContext(
                fold["fold_id"],
                train_hash,
                manifest["label_horizon"],
                manifest["embargo"],
            )
            invocation = f"{run_id}/{ctx.fold_id}/invocation"
            ledger.begin(
                invocation,
                {"train_sha256": train_hash},
                kind="fold_invocation",
                context=asdict(ctx),
                replay=False,
            )
            active.append(invocation)
            miner, fitter = miner_factory(ctx), fitter_factory(ctx)
            if any(miner is x or fitter is x for x in instances) or miner is fitter:
                raise ValueError("wf.reused_fold_instance")
            instances.extend([miner, fitter])
            adapter_sources[f"adapter/{ctx.fold_id}/miner"] = code_sha(type(miner))
            adapter_sources[f"adapter/{ctx.fold_id}/fitter"] = code_sha(type(fitter))
            proposals = miner.mine(train)
            if not isinstance(proposals, (list, tuple)) or not proposals:
                raise ValueError("wf.no_proposals")
            # Deep-copy via JSON before fitting; freeze identity prior to any selection.
            import json
            from .contract import canonical

            proposals = tuple(json.loads(canonical(proposals)))
            proposal_hash = digest(proposals)
            for number, proposal in enumerate(proposals):
                attempt = f"{run_id}/{ctx.fold_id}/proposal/{number}"
                ledger.begin(attempt, proposal, context=asdict(ctx), replay=False)
                active.append(attempt)
            receipt = fitter.fit(train, proposals)
            if not isinstance(receipt, FitReceipt):
                raise ValueError("wf.fit_receipt_missing")
            if (
                receipt.train_sha256 != train_hash
                or receipt.fit_dates != tuple(train_dates)
                or receipt.proposals_sha256 != proposal_hash
                or digest(proposals) != proposal_hash
            ):
                raise ValueError("wf.full_history_or_mutated_fit_rejected")
            if any(receipt.model is x for x in instances):
                raise ValueError("wf.reused_model")
            adapter_sources[f"adapter/{ctx.fold_id}/model"] = code_sha(
                type(receipt.model)
            )
            instances.append(receipt.model)
            predictions = list(receipt.model.predict(test))
            if len(predictions) != len(test) or not all(finite(x) for x in predictions):
                raise ValueError("wf.invalid_predictions")
            for attempt in list(active):
                ledger.finish(
                    attempt,
                    "success",
                    details={
                        "fit_dates": train_dates,
                        "test_dates": test_dates,
                        "train_sha256": train_hash,
                    },
                )
                active.remove(attempt)
            outputs.append(
                {
                    "fold_id": ctx.fold_id,
                    "train_sha256": train_hash,
                    "fit_dates": train_dates,
                    "prediction_dates": test_dates,
                    "predictions": predictions,
                }
            )
    except Exception as exc:
        reason = (
            str(exc)
            if isinstance(exc, ValueError)
            else f"wf.adapter_error:{type(exc).__name__}"
        )
        reasons.append(reason)
        for attempt in active:
            try:
                ledger.finish(attempt, "failed", reason=reason)
            except Exception:
                reasons.append("wf.ledger_outcome_write_failed")
    snapshot = ledger.safe_snapshot()
    inputs["ledger"] = snapshot
    reasons.extend(snapshot["reasons"])
    return result(
        "walk_forward",
        inputs,
        metrics={
            "folds": outputs,
            "cumulative_n": snapshot["cumulative_n"],
            "n_ledger_hash": snapshot["n_ledger_hash"],
        },
        reasons=reasons,
        artifacts={"ledger": snapshot},
        extra_sources=adapter_sources,
        assumptions=[
            "Trusted factories must discover/select/scale/refit using only supplied train rows.",
            "Fit receipts check declared dates and hashes; this is not a security sandbox.",
            "No backtest or profitability calculation is performed.",
        ],
    )

"""Offline receipt validation seams for the harness; no execution simulator.

Only confirmed fills establish inventory. Unknown fees/quantities stop new
intent registration. This is not the D6-8 shadow portfolio or its accounting.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .contract import canonical, digest, result, unavailable
from .fees import finite


def shadow_readout(receipt):
    reasons, residuals, actual, missing = [], {}, {}, []
    if (
        not isinstance(receipt, dict)
        or not isinstance(receipt.get("legs"), list)
        or any(
            not isinstance(leg, dict)
            or not isinstance(leg.get("symbol"), str)
            or not leg["symbol"]
            for leg in receipt.get("legs", [])
        )
    ):
        return result(
            "shadow_readout",
            receipt,
            reasons=["receipt.invalid_or_missing"],
            metrics={
                "sharpe": None,
                "execution_verified": False,
                "valuation_complete": False,
                "reconciliation_required": True,
            },
            availability={"sharpe": unavailable("receipt.invalid_or_missing")},
        )
    legs = receipt.get("legs", [])
    if not legs:
        reasons.append("receipt.legs_missing")
    names = set()
    for leg in legs:
        name = leg["symbol"]
        if name in names:
            reasons.append("receipt.duplicate_symbol")
        names.add(name)
        planned, filled = leg.get("planned_qty"), leg.get("confirmed_qty")
        if not finite(planned) or not finite(filled):
            actual[name], residuals[name] = None, None
            reasons.append("receipt.quantity_unknown")
        else:
            actual[name], residuals[name] = filled, planned - filled
            if planned != filled:
                reasons.append("receipt.partial_or_failed_leg")
        if not finite(leg.get("fee_usd")) or leg.get("fee_usd", -1) < 0:
            reasons.append("receipt.fee_unknown")
        if filled is None or (
            filled != 0 and (not finite(leg.get("mark")) or leg.get("mark", 0) <= 0)
        ):
            missing.append(name)
    if missing:
        reasons.append("receipt.missing_marks")
    complete = bool(legs) and not missing and "receipt.quantity_unknown" not in reasons
    execution = bool(legs) and not reasons
    hedge_legs = [leg for leg in legs if leg.get("protective") is True]
    hedged = bool(hedge_legs) and all(
        finite(leg.get("confirmed_qty"))
        and leg["confirmed_qty"] != 0
        and leg["confirmed_qty"] == leg.get("planned_qty")
        for leg in hedge_legs
    )
    return result(
        "shadow_readout",
        receipt,
        reasons=reasons,
        metrics={
            "actual_inventory": actual,
            "residual_qty": residuals,
            "execution_verified": execution,
            "valuation_complete": complete,
            "missing_marks": missing,
            "hedge_verified": hedged,
            "reconciliation_required": not execution,
            "sharpe": None,
        },
        availability={
            "sharpe": unavailable(
                "missing_marks" if not complete else "return_series_not_supplied"
            )
        },
        assumptions=[
            "Only confirmed quantities are actual inventory; plans never create fills.",
            "Marks and fees are caller-supplied receipts, not broker-verified observations.",
        ],
    )


class IntentJournal:
    """Offline dedup/reconciliation guard, transactional across processes."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def register(self, intent_id, receipt):
        if not isinstance(intent_id, str) or not intent_id:
            raise ValueError("intent_id required")
        readout = shadow_readout(receipt)
        body = canonical(receipt).decode()
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        reasons, added = [], False
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS intents "
                "(id TEXT PRIMARY KEY, body TEXT NOT NULL, unresolved INTEGER NOT NULL)"
            )
            old = db.execute(
                "SELECT body, unresolved FROM intents WHERE id=?", (intent_id,)
            ).fetchone()
            if old:
                if old[0] != body:
                    reasons.append("intent.receipt_conflict_requires_reconcile")
                if old[1]:
                    reasons.append("intent.reconciliation_required")
            elif db.execute(
                "SELECT 1 FROM intents WHERE unresolved=1 LIMIT 1"
            ).fetchone():
                reasons.append("intent.reconciliation_required")
            else:
                unresolved = readout["metrics"]["reconciliation_required"]
                db.execute(
                    "INSERT INTO intents VALUES (?, ?, ?)",
                    (intent_id, body, int(unresolved)),
                )
                added = True
                if unresolved:
                    reasons.append("intent.reconciliation_required")
            rows = [
                (row[0], json.loads(row[1]), bool(row[2]))
                for row in db.execute(
                    "SELECT id, body, unresolved FROM intents ORDER BY id"
                )
            ]
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return result(
            "intent_check",
            {"intent_id": intent_id, "receipt": receipt, "journal": rows},
            reasons=reasons,
            metrics={
                "registered": added,
                "intents_count": len(rows),
                "journal_sha256": digest(rows),
                "reconciliation_required": bool(reasons),
            },
            artifacts={"receipt_readout": readout},
            assumptions=[
                "Offline immutable receipts only; reconciliation needs a separate explicit workflow."
            ],
        )


def decay_check(request):
    return result(
        "decay_check",
        request,
        reasons=["prereg_missing"],
        missing=["decay_policy"],
        metrics={"decay": None},
        availability={"decay": unavailable("prereg_missing")},
    )

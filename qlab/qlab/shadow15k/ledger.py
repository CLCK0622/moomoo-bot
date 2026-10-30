"""Append-only, transactional synthetic receipts in a dedicated SQLite database.

Intent registration never creates inventory. Cumulative receipt snapshots can
resolve unknowns, but never erase known fills or revise a terminal order.
"""

from __future__ import annotations

import json
import re
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from qlab.dynamic_factor.contract import canonical, digest, is_sha

from .contract import report, text_id, whole
from .fees import ZERO, day, decimal_arithmetic, money
from .cash import cash_view, entitlement, payment_verified

NAMESPACE = "evo881.shadow15k.offline"
# Host-owned physical container, never taken from an intent/genesis/path request.
# The offline harness binds its own private sandbox before constructing ledgers.
PHYSICAL_ROOT = (Path(__file__).resolve().parents[3] / ".shadow15k-offline").resolve()
FORBIDDEN_LINE = re.compile(
    r"(?:^|[^a-z0-9])evo[-_]?0*(353|774|844|851)(?![0-9])", re.I
)
EXCHANGE_ZONE = ZoneInfo("America/New_York")
TERMINAL = {"filled", "failed", "cancelled"}
STATUSES = TERMINAL | {"partial", "pending", "unknown"}
FORBIDDEN = {
    "llm_paper",
    "opend_snapshot",
    "content",
    "out",
    "launchd",
    "evo353",
    "evo774",
    "evo844",
    "evo851",
}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("UTC_timestamp_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC_timestamp_required")
    return parsed.astimezone(timezone.utc)


def isolated_root(root, *, anchor=None):
    raw = Path(root).absolute()
    path = raw.resolve()
    anchor = PHYSICAL_ROOT if anchor is None else anchor
    # Resolve the caller path first, then compare to the independently pinned
    # physical container. A path prefix or a shadow15k basename is insufficient.
    if anchor.resolve() != anchor or anchor not in path.parents:
        raise ValueError("namespace_outside_physical_root")
    if any(p.is_symlink() for p in [raw, *raw.parents]):
        raise ValueError("namespace_symlink_forbidden")
    if (
        path.name != "shadow15k"
        or FORBIDDEN.intersection(p.lower() for p in path.parts)
        or any(FORBIDDEN_LINE.search(p) for p in path.parts)
    ):
        raise ValueError("dedicated_shadow15k_directory_required")
    if path.exists():
        allowed = {"ledger.sqlite3", "ledger.sqlite3-journal"}
        for p in path.iterdir():
            try:
                info = p.lstat()
            except FileNotFoundError:
                # A concurrent commit may already have removed its SQLite journal.
                continue
            if (
                p.name not in allowed
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise ValueError("namespace_contains_foreign_files")
    return path


def initial_state():
    return {
        "intents": {},
        "inventory": {},
        "cash_gross": "15000",
        "fees": "0",
        "postings": [],
        "dividends": {},
    }


def unresolved(intent):
    return any(
        o["status"] not in TERMINAL
        or not o["quantity_known"]
        or not o["fee_known"]
        or (o["spec"]["protective"] and o["qty"] != o["spec"]["planned_qty"])
        for o in intent["orders"].values()
    )


class ShadowLedger:
    """Mechanical accounting API only, not a signal-to-order or live execution path."""

    def __init__(self, root, genesis, fee_book):
        self._physical_root = PHYSICAL_ROOT
        self.root = isolated_root(root, anchor=self._physical_root)
        self.fees = fee_book
        # Explicit metadata, no defaults for strategy identity or prices.
        required = {
            "namespace",
            "mode",
            "initial_cash",
            "candidate_id",
            "version",
            "price_basis",
        }
        if not isinstance(genesis, dict) or set(genesis) != required:
            raise ValueError("explicit_genesis_fields_required")
        if genesis["namespace"] != NAMESPACE or genesis["mode"] != "offline_synthetic":
            raise ValueError("offline_namespace_only")
        if money(genesis["initial_cash"]) != Decimal(15000):
            raise ValueError("initial_cash_must_be_15000")
        text_id(genesis["candidate_id"])
        text_id(genesis["version"])
        if genesis["price_basis"] not in {"reference", "cash_bid_ask"}:
            raise ValueError("explicit_price_basis_required")
        self.genesis = dict(
            genesis, fee_binding=fee_book.binding, cost_scenario=fee_book.scenario
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "ledger.sqlite3"
        if self.path.exists() and (self.path.is_symlink() or not self.path.is_file()):
            raise ValueError("database_must_be_regular_file")
        with self._connection(write=True) as db:
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if tables and tables != {"metadata", "events"}:
                raise ValueError("foreign_database_refused")
            if not tables:
                db.execute(
                    "CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE events (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, "
                    "kind TEXT NOT NULL, body TEXT NOT NULL, previous_hash TEXT NOT NULL, "
                    "event_hash TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO metadata VALUES (1, ?)",
                    (canonical(self.genesis).decode(),),
                )
            self._load(db)

    @contextmanager
    def _connection(self, *, write):
        # Recheck namespace on every operation, not just construction.
        isolated_root(self.root, anchor=self._physical_root)
        db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _load(self, db):
        stored = db.execute("SELECT body FROM metadata WHERE id=1").fetchone()
        if stored is None or stored[0] != canonical(self.genesis).decode():
            raise ValueError("genesis_or_fee_binding_conflict")
        state, chain, count = initial_state(), digest(self.genesis), 0
        for seq, event_id, kind, body, prev, event_hash in db.execute(
            "SELECT * FROM events ORDER BY seq"
        ):
            value = json.loads(body)
            if (
                seq != count + 1
                or prev != chain
                or event_hash
                != digest(
                    {
                        "seq": seq,
                        "event_id": event_id,
                        "kind": kind,
                        "body": value,
                        "previous_hash": prev,
                    }
                )
            ):
                raise ValueError("ledger_hash_chain_invalid")
            self._apply(state, kind, value)
            chain, count = event_hash, seq
        return state, chain, count

    @decimal_arithmetic
    def _apply(self, state, kind, body):
        if kind == "dividend":
            if not isinstance(body, dict) or set(body) != {
                "receipt_id",
                "as_of",
                "event",
            }:
                raise ValueError("dividend.explicit_receipt_fields_required")
            text_id(body["receipt_id"])
            timestamp(body["as_of"])
            if any(
                i["last_receipt_ts"] and i["last_receipt_ts"] > body["as_of"]
                for i in state["intents"].values()
            ):
                raise ValueError("dividend.receipt_precedes_trade_receipt")
            event = body["event"]
            if not isinstance(event, dict) or event.get("symbol") != "QQQ":
                raise ValueError("dividend.QQQ_source_mapping_required")
            ex = day(event["ex_date"])
            if body["as_of"][:10] < ex:
                raise ValueError("dividend.receipt_precedes_ex_date")
            if (
                event.get("entitled_integer_shares") is not None
                and type(event.get("entitled_integer_shares")) is not int
            ) or event.get("entitled_integer_shares") != entitlement(state, ex):
                raise ValueError("dividend.entitlement_mismatch")
            previous = state["dividends"].get(ex)
            if previous:
                if body["as_of"] < previous["as_of"]:
                    raise ValueError("dividend.receipt_timestamp_out_of_order")
                prior = previous["event"]
                if payment_verified(prior, previous["as_of"]) and event != prior:
                    raise ValueError("dividend.paid_event_rewrite_forbidden")
            state["dividends"][ex] = body
            return
        if kind == "intent":
            request = body
            if not isinstance(request, dict) or set(request) != {
                "intent_id",
                "decision_ts",
                "input_hash",
                "orders",
            }:
                raise ValueError("explicit_intent_fields_required")
            intent_id = text_id(request["intent_id"])
            if intent_id in state["intents"] or any(
                unresolved(i) for i in state["intents"].values()
            ):
                raise ValueError("intent.reconciliation_required")
            decision = timestamp(request["decision_ts"])
            if any(
                p["as_of"] > request["decision_ts"] for p in state["dividends"].values()
            ):
                raise ValueError("intent.decision_precedes_dividend_receipt")
            if (
                state["dividends"]
                and cash_view(state, request["decision_ts"], {})["metrics"][
                    "available_cash"
                ]
                is None
            ):
                raise ValueError("dividend.cash_reconciliation_required")
            if not is_sha(request["input_hash"]):
                raise ValueError("input_hash_required")
            if not isinstance(request["orders"], list) or not request["orders"]:
                raise ValueError("orders_required")
            orders = {}
            prior_ids = {oid for i in state["intents"].values() for oid in i["orders"]}
            for spec in request["orders"]:
                if set(spec) != {
                    "order_id",
                    "symbol",
                    "side",
                    "planned_qty",
                    "trade_date",
                    "protective",
                }:
                    raise ValueError("explicit_order_fields_required")
                oid = text_id(spec["order_id"])
                text_id(spec["symbol"])
                if oid in orders or oid in prior_ids:
                    raise ValueError("order_id_already_registered")
                if (
                    spec["side"] not in {"BUY", "SELL"}
                    or type(spec["protective"]) is not bool
                ):
                    raise ValueError("invalid_order_side_or_protective_flag")
                if whole(spec["planned_qty"]) == 0:
                    raise ValueError("positive_planned_quantity_required")
                day(spec["trade_date"])
                if (
                    spec["trade_date"]
                    < decision.astimezone(EXCHANGE_ZONE).date().isoformat()
                ):
                    raise ValueError("intent.trade_date_precedes_decision")
                self.fees.rate_field(spec["trade_date"])
                orders[oid] = dict(
                    spec=spec,
                    qty=0,
                    notional="0",
                    fee="0",
                    fee_lines=None,
                    status="pending",
                    quantity_known=False,
                    fee_known=False,
                )
            state["intents"][intent_id] = dict(
                request=request, orders=orders, last_receipt_ts=None
            )
            return
        if kind != "receipt":
            raise ValueError("unknown_event_kind")
        intent = state["intents"][body["intent_id"]]
        receipt = body["receipt"]
        if not isinstance(receipt, dict) or set(receipt) != {
            "receipt_id",
            "receipt_ts",
            "orders",
        }:
            raise ValueError("explicit_receipt_header_required")
        text_id(receipt["receipt_id"])
        at = timestamp(receipt["receipt_ts"])
        if any(p["as_of"] > receipt["receipt_ts"] for p in state["dividends"].values()):
            raise ValueError("receipt.precedes_dividend_receipt")
        if at < timestamp(intent["request"]["decision_ts"]) or (
            intent["last_receipt_ts"] and at < timestamp(intent["last_receipt_ts"])
        ):
            raise ValueError("receipt_timestamp_out_of_order")
        snapshots = receipt["orders"]
        if not isinstance(snapshots, list) or len(snapshots) != len(intent["orders"]):
            raise ValueError("complete_cumulative_order_snapshots_required")
        seen = set()
        for snapshot in snapshots:
            if set(snapshot) != {
                "order_id",
                "confirmed_qty",
                "gross_usd",
                "fee_known",
                "status",
            }:
                raise ValueError("explicit_receipt_fields_required")
            oid = snapshot["order_id"]
            if oid not in intent["orders"] or oid in seen:
                raise ValueError("receipt_order_set_mismatch")
            seen.add(oid)
            order = intent["orders"][oid]
            spec = order["spec"]
            if (
                type(snapshot["fee_known"]) is not bool
                or snapshot["status"] not in STATUSES
            ):
                raise ValueError("invalid_receipt_status_or_fee_flag")
            if snapshot["confirmed_qty"] is not None:
                whole(snapshot["confirmed_qty"])
            if (
                order["status"] in TERMINAL
                and order["quantity_known"]
                and order["fee_known"]
            ):
                old = dict(
                    order_id=oid,
                    confirmed_qty=order["qty"],
                    gross_usd=money(order["notional"]),
                    fee_known=True,
                    status=order["status"],
                )
                normalized = dict(snapshot)
                if normalized["gross_usd"] is not None:
                    normalized["gross_usd"] = money(normalized["gross_usd"])
                if normalized != old:
                    raise ValueError("terminal_receipt_conflict")
                continue
            qty, value = snapshot["confirmed_qty"], snapshot["gross_usd"]
            if qty is None or value is None:
                if (
                    qty is not None
                    or value is not None
                    or snapshot["status"] != "unknown"
                    or snapshot["fee_known"]
                ):
                    raise ValueError("unknown_quantity_requires_unknown_receipt")
                # Known fills are retained; latest uncertainty is never zeroed.
                order.update(quantity_known=False, fee_known=False, status="unknown")
                continue
            whole(qty)
            if qty > order["qty"] and (
                at.astimezone(EXCHANGE_ZONE).date().isoformat() != spec["trade_date"]
            ):
                # This receipt schema has no independent actual-execution
                # timestamp/provenance. A late confirmation cannot prove a
                # pre-ex-date fill, nor can it confirm a future DAY order.
                raise ValueError("receipt.trade_date_confirmation_mismatch")
            notional = money(value)
            if (
                qty > spec["planned_qty"]
                or qty < order["qty"]
                or notional < money(order["notional"])
            ):
                raise ValueError("overfill_or_retrograde_cumulative_receipt")
            if (
                (qty == 0) != (notional == 0)
                or (qty == order["qty"] and notional != money(order["notional"]))
                or (qty > order["qty"] and notional <= money(order["notional"]))
            ):
                raise ValueError("quantity_notional_inconsistent")
            status = snapshot["status"]
            if (
                (status == "filled" and qty != spec["planned_qty"])
                or (status == "partial" and not 0 < qty < spec["planned_qty"])
                or (status == "pending" and qty != 0)
                or (status == "failed" and qty != 0)
            ):
                raise ValueError("receipt_status_quantity_conflict")
            lines = self.fees.cumulative(
                qty=qty,
                notional=notional,
                side=spec["side"],
                trade_date=spec["trade_date"],
                price_basis=self.genesis["price_basis"],
            )
            total_fee = (
                money(lines["charged"])
                if snapshot["fee_known"]
                else money(order["fee"])
            )
            fee_delta = total_fee - money(order["fee"])
            if fee_delta < 0:
                raise ValueError("retrograde_cumulative_fee")
            state["postings"].append(
                dict(
                    receipt_id=receipt["receipt_id"],
                    intent_id=body["intent_id"],
                    order_id=oid,
                    qty_delta=qty - order["qty"],
                    notional_delta=str(notional - money(order["notional"])),
                    fee_delta=str(fee_delta) if snapshot["fee_known"] else None,
                    cumulative_fee=str(total_fee) if snapshot["fee_known"] else None,
                )
            )
            sign = 1 if spec["side"] == "BUY" else -1
            symbol = spec["symbol"]
            state["inventory"][symbol] = state["inventory"].get(symbol, 0) + sign * (
                qty - order["qty"]
            )
            state["cash_gross"] = str(
                Decimal(state["cash_gross"])
                - sign * (notional - money(order["notional"]))
            )
            state["fees"] = str(Decimal(state["fees"]) + fee_delta)
            order.update(
                qty=qty,
                notional=str(notional),
                fee=str(total_fee),
                fee_lines=lines if snapshot["fee_known"] else None,
                status=status,
                quantity_known=True,
                fee_known=snapshot["fee_known"],
            )
        if any(q < 0 for q in state["inventory"].values()):
            raise ValueError("short_inventory_forbidden")
        known_cash = Decimal(state["cash_gross"]) - Decimal(state["fees"])
        if state["dividends"]:
            value = cash_view(state, receipt["receipt_ts"], {})["metrics"][
                "known_available_cash"
            ]
            if value is not None:
                known_cash = Decimal(str(value))
        if known_cash < ZERO:
            raise ValueError("cash_insufficient_including_fees")
        intent["last_receipt_ts"] = receipt["receipt_ts"]

    def _append(self, event_id, kind, body):
        inputs = {
            "genesis": self.genesis,
            "event_id": event_id,
            "kind": kind,
            "body": body,
            "ledger_before_sha256": None,
        }
        try:
            # Strict JSON: nonfinite values are rejected before imported canonical's null cleaning.
            json.dumps(body, allow_nan=False)
            with self._connection(write=True) as db:
                state, chain, count = self._load(db)
                inputs["ledger_before_sha256"] = chain
                old = db.execute(
                    "SELECT kind,body FROM events WHERE event_id=?", (event_id,)
                ).fetchone()
                if old is not None:
                    if old != (kind, canonical(body).decode()):
                        raise ValueError("intent_or_receipt_id_conflict")
                    added = False
                else:
                    self._apply(state, kind, body)
                    chain_next = digest(
                        dict(
                            seq=count + 1,
                            event_id=event_id,
                            kind=kind,
                            body=body,
                            previous_hash=chain,
                        )
                    )
                    db.execute(
                        "INSERT INTO events VALUES (?,?,?,?,?,?)",
                        (
                            count + 1,
                            event_id,
                            kind,
                            canonical(body).decode(),
                            chain,
                            chain_next,
                        ),
                    )
                    chain, count, added = chain_next, count + 1, True
                operation_time = (
                    body["decision_ts"]
                    if kind == "intent"
                    else body["receipt"]["receipt_ts"]
                    if kind == "receipt"
                    else body["as_of"]
                )
                cash_unknown = bool(
                    state["dividends"]
                    and cash_view(state, operation_time, {})["metrics"][
                        "available_cash"
                    ]
                    is None
                )
                metrics = dict(
                    registered=added,
                    event_count=count,
                    ledger_sha256=chain,
                    reconciliation_required=cash_unknown
                    or any(unresolved(i) for i in state["intents"].values()),
                )
            return report(
                "shadow_" + kind,
                inputs,
                metrics=metrics,
                assumptions=self.fees.assumptions,
            )
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "invalid_event_shape"
            return report(
                "shadow_" + kind,
                inputs,
                reasons=[reason],
                assumptions=self.fees.assumptions,
            )

    def register_intent(self, request):
        """Caller-supplied synthetic intent only; strategy gates are never bypassed implicitly."""
        iid = request.get("intent_id") if isinstance(request, dict) else None
        return self._append("intent:" + str(iid), "intent", request)

    def record_receipt(self, intent_id, receipt):
        rid = receipt.get("receipt_id") if isinstance(receipt, dict) else None
        return self._append(
            "receipt:" + str(rid),
            "receipt",
            {"intent_id": intent_id, "receipt": receipt},
        )

    def record_dividend(self, request):
        rid = request.get("receipt_id") if isinstance(request, dict) else None
        return self._append("dividend:" + str(rid), "dividend", request)

    @decimal_arithmetic
    def readout(self, marks):
        """Value known inventory at one explicit synthetic timestamp, with no price fallback."""
        with self._connection(write=False) as db:
            state, chain, count = self._load(db)
        orders = [o for i in state["intents"].values() for o in i["orders"].values()]
        quantity_known = all(o["quantity_known"] for o in orders)
        fee_known = all(o["fee_known"] for o in orders)
        reasons, missing, prices = [], [], {}
        try:
            as_of = timestamp(marks["as_of"])
            if any(timestamp(p["as_of"]) > as_of for p in state["dividends"].values()):
                raise ValueError("mark_precedes_dividend_receipt")
            if marks["price_basis"] != self.genesis["price_basis"]:
                raise ValueError("mark_price_basis_mismatch")
            if any(
                i["last_receipt_ts"] and timestamp(i["last_receipt_ts"]) > as_of
                for i in state["intents"].values()
            ):
                raise ValueError("mark_precedes_receipt")
            if not isinstance(marks["prices"], dict):
                raise ValueError("mark_prices_required")
            prices = marks["prices"]
        except (TypeError, KeyError, ValueError):
            reasons.append("nav.invalid_marks")
        value = ZERO
        for symbol, qty in sorted(state["inventory"].items()):
            if not qty:
                continue
            try:
                price = money(prices[symbol])
                if price == 0:
                    raise ValueError("nonpositive_mark")
                value += price * qty
            except (KeyError, ValueError):
                missing.append(symbol)
        if missing:
            reasons.append("nav.missing_marks")
        if not quantity_known:
            reasons.append("paper.quantity_unknown")
        if not fee_known:
            reasons.append("paper.fee_unknown")
        reconcile = any(unresolved(i) for i in state["intents"].values())
        valuation_complete = (
            quantity_known and not missing and "nav.invalid_marks" not in reasons
        )
        gross_cash, charged = Decimal(state["cash_gross"]), Decimal(state["fees"])
        cash_known = quantity_known and fee_known
        cash = gross_cash - charged if cash_known else None
        gross_pnl = gross_cash + value - 15000 if valuation_complete else None
        nav = cash + value if cash_known and valuation_complete else None
        dividend_readout = None
        receivable = ZERO
        known_available = str(gross_cash - charged)
        if state["dividends"]:
            try:
                dividend_readout = cash_view(state, marks["as_of"], prices)
                dm = dividend_readout["metrics"]
                if dm["known_available_cash"] is not None:
                    known_available = str(dm["known_available_cash"])
                reasons.extend(dividend_readout["reasons"])
                cash = (
                    None
                    if not cash_known or dm["available_cash"] is None
                    else money(dm["available_cash"])
                )
                receivable = (
                    None
                    if dm["receivable_amount"] is None
                    else money(dm["receivable_amount"])
                )
                cash_known = cash_known and cash is not None
                valuation_complete = (
                    valuation_complete
                    and cash_known
                    and receivable is not None
                    and dm["nav"] is not None
                )
                nav = cash + value + receivable if valuation_complete else None
                gross_pnl = nav + charged - 15000 if nav is not None else None
                reconcile = reconcile or not cash_known or receivable is None
            except (ValueError, TypeError, KeyError):
                reasons.append("dividend.cash_valuation_invalid")
                cash = nav = gross_pnl = receivable = None
                cash_known = valuation_complete = False
                reconcile = True
        execution_complete = bool(orders) and all(
            o["quantity_known"]
            and o["fee_known"]
            and o["qty"] == o["spec"]["planned_qty"]
            and o["status"] == "filled"
            for o in orders
        )
        per_intent, fee_ledger = [], []
        for iid, intent in state["intents"].items():
            fills, residuals = [], {}
            for oid, o in intent["orders"].items():
                residuals[oid] = (
                    o["spec"]["planned_qty"] - o["qty"] if o["quantity_known"] else None
                )
                fills.append(
                    dict(
                        order_id=oid,
                        symbol=o["spec"]["symbol"],
                        side=o["spec"]["side"],
                        confirmed_qty=o["qty"] if o["quantity_known"] else None,
                        last_known_qty=o["qty"],
                        gross_usd=o["notional"] if o["quantity_known"] else None,
                        status=o["status"],
                        fee_known=o["fee_known"],
                    )
                )
                fee_ledger.append(
                    dict(
                        intent_id=iid,
                        order_id=oid,
                        trade_date=o["spec"]["trade_date"],
                        cumulative_fee=o["fee"] if o["fee_known"] else None,
                        last_known_fee=o["fee"],
                        lines=o["fee_lines"],
                    )
                )
            per_intent.append(
                dict(
                    intent_id=iid,
                    decision_ts=intent["request"]["decision_ts"],
                    input_hash=intent["request"]["input_hash"],
                    fills=fills,
                    residual_qty=residuals,
                    reconciliation_required=unresolved(intent),
                )
            )
        if reconcile:
            reasons.append("intent.reconciliation_required")
        reason = (
            "invalid_marks"
            if "nav.invalid_marks" in reasons
            else (
                "missing_marks"
                if missing
                else (
                    "accounting_unknown"
                    if not cash_known
                    else "return_series_not_supplied"
                )
            )
        )
        metrics = dict(
            namespace=NAMESPACE,
            mode="offline_synthetic",
            candidate_id=self.genesis["candidate_id"],
            version=self.genesis["version"],
            decision_ts=[i["decision_ts"] for i in per_intent],
            input_hash=digest({"marks": marks, "ledger_sha256": chain}),
            price_basis=self.genesis["price_basis"],
            reading_kind="synthetic_" + self.genesis["price_basis"],
            cost_scenario=self.fees.scenario,
            gross_pnl=None if gross_pnl is None else str(gross_pnl),
            fees=state["fees"] if fee_known else None,
            known_fees=state["fees"],
            net_pnl=None if nav is None else str(nav - 15000),
            cash=None if cash is None else str(cash),
            available_cash=None if cash is None else str(cash),
            receivable_amount=None if receivable is None else str(receivable),
            cash_ledger_kind="simulation_pre_tax_integer",
            dividend_readout=dividend_readout,
            account_cash_credited_amount=None,
            account_cash_credited_at=None,
            last_known_cash=known_available,
            known_available_cash=known_available,
            inventory=state["inventory"],
            inventory_value=str(value) if valuation_complete else None,
            nav=None if nav is None else str(nav),
            valuation_complete=valuation_complete,
            missing_marks=missing,
            quantity_complete=quantity_known,
            fees_complete=fee_known,
            execution_verified=False,
            execution_complete=execution_complete,
            hedge_verified=False,
            sharpe=None,
            sharpe_available=False,
            metric_unavailable_reason=reason,
            cumulative_n=None,
            n_ledger_hash=None,
            intent_id=[i["intent_id"] for i in per_intent],
            fills=[f for i in per_intent for f in i["fills"]],
            residual_qty={i["intent_id"]: i["residual_qty"] for i in per_intent},
            reconciliation_required=reconcile,
            intents=per_intent,
            fee_ledger=fee_ledger,
            postings=state["postings"],
            ledger_sha256=chain,
            event_count=count,
        )
        value = report(
            "shadow_readout",
            {"genesis": self.genesis, "marks": marks, "ledger_sha256": chain},
            metrics=metrics,
            reasons=reasons,
            assumptions=self.fees.assumptions,
        )
        value["metric_availability"] = {
            "sharpe": {"available": False, "reason": reason},
            "nav": {
                "available": nav is not None,
                "reason": None
                if nav is not None
                else "valuation_or_accounting_incomplete",
            },
        }
        return value

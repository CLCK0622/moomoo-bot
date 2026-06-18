"""Execution engine: signals → risk-checked orders → broker, fully observable.

Reconciles current positions to the target weights in a :class:`SignalSet`, sizing
each order off current equity. Every order passes the :class:`RiskManager` before it
reaches the broker. Three modes (EXECUTION default-safe, EVO-13 §3):

- ``dry_run`` — compute intended orders + risk decisions, place nothing.
- ``paper``   — route to a :class:`PaperBroker` (simulated fills).
- ``live``    — route to a live broker adapter (moomoo); off unless explicitly built.

Returns a :class:`RunRecord` (orders, rejections + reasons, halt state, equity,
positions) so a paper session is auditable end-to-end.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .broker import Broker, OrderResult
from .risk import Quote, RiskManager
from .signals import SignalSet


@dataclass
class PlannedOrder:
    symbol: str
    side: str
    qty: float
    price: float
    increases_exposure: bool
    target_weight: float


@dataclass
class RunRecord:
    mode: str
    equity_before: float
    equity_after: float
    halted: bool = False
    halt_reason: str = ""
    filled: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    positions_after: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionEngine:
    def __init__(
        self,
        broker: Broker,
        risk: RiskManager,
        *,
        mode: str = "paper",
        lot: float = 1.0,
    ) -> None:
        if mode not in {"dry_run", "paper", "live"}:
            raise ValueError("mode must be dry_run | paper | live")
        self.broker = broker
        self.risk = risk
        self.mode = mode
        self.lot = lot  # min tradable unit (shares); orders are floored to this

    def run_cycle(
        self,
        sigset: SignalSet,
        marks: dict[str, float],
        *,
        prev_closes: dict[str, float] | None = None,
        quote_ages: dict[str, float] | None = None,
        intraday_pnl_pct: float = 0.0,
    ) -> RunRecord:
        prev_closes = prev_closes or {}
        quote_ages = quote_ages or {}
        equity_before = self.broker.equity(marks)
        record = RunRecord(mode=self.mode, equity_before=equity_before, equity_after=equity_before)

        # Portfolio-level breakers first.
        self.risk.register_equity(equity_before)

        positions = self.broker.positions()
        target = {s.symbol: s.target_weight for s in sigset.signals}

        # Projected book (symbol -> qty) carried across the whole cycle so gross
        # exposure and position count are validated *cumulatively* — each order is
        # checked against the book left by the orders already accepted this cycle,
        # not against a single pre-cycle snapshot. Holdings not in the signal set
        # stay in the book and keep contributing to gross / position count.
        book: dict[str, float] = {s: p.qty for s, p in positions.items()}

        def price_of(s: str) -> float | None:
            p = positions.get(s)
            return marks.get(s, p.avg_price if p else None)

        def gross_of(bk: dict[str, float]) -> float:
            if not equity_before:
                return 0.0
            total = 0.0
            for s, q in bk.items():
                px = price_of(s)
                if px:
                    total += abs(q * px)
            return total / equity_before

        def n_positions_of(bk: dict[str, float]) -> int:
            return len([s for s, q in bk.items() if abs(q) > 1e-9])

        for sig in sigset.signals:
            sym = sig.symbol
            price = marks.get(sym)
            if not price or price <= 0:
                record.skipped.append({"symbol": sym, "reason": "no mark price"})
                continue

            # Abnormal-market / staleness halt for this symbol's quote (latches).
            mkt = self.risk.check_market(
                Quote(sym, price, prev_closes.get(sym), quote_ages.get(sym, 0.0))
            )

            cur_qty = book.get(sym, 0.0)
            target_weight = self.risk_clamp(target.get(sym, 0.0))
            target_qty = self._round_lot((target_weight * equity_before) / price)
            if abs(target_qty - cur_qty) < self.lot:
                record.skipped.append({"symbol": sym, "reason": "within lot tolerance"})
                continue

            # A direction flip (long↔short) is split into two legs: first close to
            # flat (a de-risk leg, exempt), then open the full reverse position (an
            # increase leg that must clear every cap). Treating the net delta as one
            # order would mis-classify the flip as "not increasing exposure" (the
            # qty crosses zero) and let an arbitrarily large reverse position bypass
            # the position-weight / gross / intraday gates entirely.
            if cur_qty != 0.0 and target_qty != 0.0 and (cur_qty > 0) != (target_qty > 0):
                legs = [(cur_qty, 0.0), (0.0, target_qty)]
            else:
                legs = [(cur_qty, target_qty)]

            for from_qty, to_qty in legs:
                leg_delta = to_qty - from_qty
                if abs(leg_delta) < self.lot:
                    continue
                side = "BUY" if leg_delta > 0 else "SELL"
                increases = abs(to_qty) > abs(from_qty)
                weight_after = (to_qty * price) / equity_before if equity_before else 0.0
                projected = dict(book)
                if abs(to_qty) > 1e-9:
                    projected[sym] = to_qty
                else:
                    projected.pop(sym, None)
                gross_after = gross_of(projected)
                n_after = n_positions_of(projected)

                if not mkt.allowed and increases:
                    record.rejected.append(
                        {"symbol": sym, "side": side, "qty": abs(leg_delta), "reason": mkt.reason}
                    )
                    continue

                decision = self.risk.pretrade_check(
                    increases_exposure=increases,
                    symbol_weight_after=weight_after,
                    gross_after=gross_after,
                    n_positions_after=n_after,
                    intraday_pnl_pct=intraday_pnl_pct,
                )
                if not decision.allowed:
                    record.rejected.append(
                        {"symbol": sym, "side": side, "qty": abs(leg_delta),
                         "reason": decision.reason}
                    )
                    continue

                # Accepted: commit the projection so subsequent orders this cycle
                # accumulate against it.
                prev_book = book
                book = projected

                if self.mode == "dry_run":
                    record.filled.append(
                        {"symbol": sym, "side": side, "qty": abs(leg_delta), "price": price,
                         "status": "dry_run"}
                    )
                    continue

                result = self.broker.place_market_order(sym, side, abs(leg_delta), price)
                self._record_result(record, result)
                if result.status != "filled":
                    # Broker rejected the fill — roll the projection back so the
                    # cumulative book reflects only orders that actually filled.
                    book = prev_book

        record.equity_after = self.broker.equity(marks)
        record.halted = self.risk.halted
        record.halt_reason = self.risk.halt_reason
        record.positions_after = {
            s: {"qty": p.qty, "avg_price": p.avg_price} for s, p in self.broker.positions().items()
        }
        return record

    @staticmethod
    def risk_clamp(weight: float) -> float:
        return max(-1.0, min(1.0, weight))

    def _round_lot(self, qty: float) -> float:
        lots = int(qty / self.lot)
        return lots * self.lot

    @staticmethod
    def _record_result(record: RunRecord, result: OrderResult) -> None:
        row = {
            "symbol": result.symbol,
            "side": result.side,
            "qty": result.qty,
            "price": result.price,
            "order_id": result.order_id,
            "status": result.status,
            "reason": result.reason,
        }
        if result.status == "filled":
            record.filled.append(row)
        else:
            record.rejected.append(row)

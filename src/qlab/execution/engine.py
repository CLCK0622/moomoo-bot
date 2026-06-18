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
        # Build the desired order per signalled symbol.
        target = {s.symbol: s.target_weight for s in sigset.signals}
        gross_now = sum(
            abs(p.qty * marks.get(s, p.avg_price)) for s, p in positions.items()
        ) / equity_before if equity_before else 0.0

        for sig in sigset.signals:
            sym = sig.symbol
            price = marks.get(sym)
            if not price or price <= 0:
                record.skipped.append({"symbol": sym, "reason": "no mark price"})
                continue

            # Abnormal-market / staleness halt for this symbol's quote.
            mkt = self.risk.check_market(
                Quote(sym, price, prev_closes.get(sym), quote_ages.get(sym, 0.0))
            )

            cur_qty = positions.get(sym).qty if sym in positions else 0.0
            cur_weight = (cur_qty * price) / equity_before if equity_before else 0.0
            target_weight = self.risk_clamp(target.get(sym, 0.0))
            target_qty = self._round_lot((target_weight * equity_before) / price)
            delta = target_qty - cur_qty
            if abs(delta) < self.lot:
                record.skipped.append({"symbol": sym, "reason": "within lot tolerance"})
                continue

            side = "BUY" if delta > 0 else "SELL"
            increases = abs(target_qty) > abs(cur_qty) and (target_qty * cur_qty >= 0)
            weight_after = target_weight
            gross_after = gross_now - abs(cur_weight) + abs(weight_after)
            n_after = len([s for s, w in target.items() if abs(w) > 1e-9])

            if not mkt.allowed and increases:
                record.rejected.append(
                    {"symbol": sym, "side": side, "qty": abs(delta), "reason": mkt.reason}
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
                    {"symbol": sym, "side": side, "qty": abs(delta), "reason": decision.reason}
                )
                continue

            if self.mode == "dry_run":
                record.filled.append(
                    {"symbol": sym, "side": side, "qty": abs(delta), "price": price,
                     "status": "dry_run"}
                )
                continue

            result = self.broker.place_market_order(sym, side, abs(delta), price)
            self._record_result(record, result)

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

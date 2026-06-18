"""Broker abstraction for the execution layer.

A :class:`Broker` is the minimal surface the execution engine needs: read account
equity / positions, place a market order, cancel. :class:`PaperBroker` is the
default-safe simulated implementation (no SDK, deterministic) used for dry-run /
paper runs; the live moomoo gateway is adapted to this same surface separately.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0


@dataclass
class OrderResult:
    symbol: str
    side: str  # BUY | SELL
    qty: float
    price: float
    status: str  # filled | rejected | dry_run
    reason: str = ""
    order_id: str | None = None
    commission: float = 0.0


class Broker(abc.ABC):
    @abc.abstractmethod
    def positions(self) -> dict[str, Position]:
        ...

    @abc.abstractmethod
    def equity(self, marks: dict[str, float]) -> float:
        ...

    @abc.abstractmethod
    def place_market_order(self, symbol: str, side: str, qty: float, price: float) -> OrderResult:
        ...

    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> None:
        ...


class PaperBroker(Broker):
    """Simulated broker: deterministic fills at the mark ± slippage, flat commission.

    This is the explicit paper/dry-run venue (EVO-13 §3) — it is NOT a stand-in for
    verifying the live OpenD path. Tracks cash, positions and realised P&L so a paper
    session is fully observable.
    """

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        *,
        slippage_bps: float = 1.0,
        commission_per_trade: float = 1.0,
    ) -> None:
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.slippage = slippage_bps / 10_000.0
        self.commission_per_trade = commission_per_trade
        self._positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self.order_log: list[OrderResult] = []
        self._seq = 0

    def positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if abs(p.qty) > 1e-9}

    def equity(self, marks: dict[str, float]) -> float:
        mtm = sum(p.qty * marks.get(s, p.avg_price) for s, p in self._positions.items())
        return self.cash + mtm

    def place_market_order(self, symbol: str, side: str, qty: float, price: float) -> OrderResult:
        side = side.upper()
        if qty <= 0 or price <= 0:
            return OrderResult(symbol, side, qty, price, "rejected", "non-positive qty/price")
        fill = price * (1 + self.slippage) if side == "BUY" else price * (1 - self.slippage)
        self._seq += 1
        oid = f"PAPER-{self._seq}"
        pos = self._positions.get(symbol, Position(symbol))
        if side == "BUY":
            cost = fill * qty + self.commission_per_trade
            new_qty = pos.qty + qty
            pos.avg_price = (pos.avg_price * pos.qty + fill * qty) / new_qty if new_qty else 0.0
            pos.qty = new_qty
            self.cash -= cost
        else:  # SELL
            self.realized_pnl += (fill - pos.avg_price) * min(qty, pos.qty)
            pos.qty -= qty
            self.cash += fill * qty - self.commission_per_trade
            if abs(pos.qty) < 1e-9:
                pos.qty = 0.0
                pos.avg_price = 0.0
        self._positions[symbol] = pos
        result = OrderResult(
            symbol, side, qty, fill, "filled", order_id=oid, commission=self.commission_per_trade
        )
        self.order_log.append(result)
        return result

    def cancel_order(self, order_id: str) -> None:
        # Paper market orders fill instantly; nothing to cancel. No-op for parity.
        return None

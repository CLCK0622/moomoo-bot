"""In-memory paper broker — simulated fills, no external dependency.

Default execution backend. Lets the full signal -> risk -> order -> fill ->
position -> equity loop run deterministically with zero OpenD/account access,
which is exactly what is reproducible in CI and in this workspace.

Fill model: marketable orders fill immediately at the current mark with
configurable slippage; commission is charged per fill. The engine feeds the
current mark via :meth:`mark` before submitting (mirroring the snapshot the
live adapter would read).
"""
from __future__ import annotations

import math

import pandas as pd

from .base import (Account, BrokerError, Fill, Order, OrderStatus, OrderType,
                   Position, Side, Snapshot)


class PaperBroker:
    name = "paper"

    def __init__(self, initial_cash: float = 100_000.0,
                 commission_per_order: float = 1.0, slippage_pct: float = 0.0002):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission = commission_per_order
        self.slippage_pct = slippage_pct
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.orders: dict[str, Order] = {}
        self.realized_pnl = 0.0
        self._marks: dict[str, float] = {}
        self._now: pd.Timestamp | None = None
        self._seq = 0

    # --- lifecycle ---
    def connect(self) -> None:  # nothing to do
        pass

    def close(self) -> None:
        pass

    # --- simulator feed (engine pushes the latest price/time each tick) ---
    def mark(self, symbol: str, price: float, when: pd.Timestamp) -> None:
        self._marks[symbol] = price
        self._now = when
        if symbol in self.positions:
            self.positions[symbol].last_price = price

    # --- market data (paper broker has none of its own; engine supplies it) ---
    def get_snapshot(self, symbols: list[str]) -> dict[str, Snapshot]:
        out = {}
        for s in symbols:
            if s in self._marks:
                out[s] = Snapshot(s, self._marks[s], self._now)
        return out

    def get_history_kline(self, symbol, timeframe, start, end) -> pd.DataFrame:
        raise BrokerError("PaperBroker has no historical data; supply bars via a "
                          "DataSource / fixture replay instead.")

    # --- account / positions ---
    def get_account(self) -> Account:
        mv = sum(p.market_value for p in self.positions.values())
        return Account(cash=self.cash, total_assets=self.cash + mv,
                       market_value=mv, realized_pnl=self.realized_pnl)

    def get_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self.positions.items() if p.qty != 0}

    # --- orders ---
    def _next_id(self) -> str:
        self._seq += 1
        return f"PAPER-{self._seq:06d}"

    def place_order(self, order: Order) -> Order:
        if order.qty <= 0:
            order.status = OrderStatus.REJECTED
            raise BrokerError(f"non-positive qty for {order.symbol}")
        mark = self._marks.get(order.symbol)
        if mark is None:
            order.status = OrderStatus.REJECTED
            raise BrokerError(f"no mark for {order.symbol}; call mark() first")
        order.order_id = self._next_id()
        self.orders[order.order_id] = order

        # marketable fill with slippage against the taker
        if order.side == Side.BUY:
            fill_price = mark * (1 + self.slippage_pct)
        else:
            fill_price = mark * (1 - self.slippage_pct)
        if order.order_type == OrderType.LIMIT and order.limit_price is not None:
            # only fills if marketable
            if order.side == Side.BUY and fill_price > order.limit_price:
                order.status = OrderStatus.SUBMITTED
                return order
            if order.side == Side.SELL and fill_price < order.limit_price:
                order.status = OrderStatus.SUBMITTED
                return order
            fill_price = order.limit_price

        self._apply_fill(order, fill_price)
        return order

    def _apply_fill(self, order: Order, price: float) -> None:
        sym, qty = order.symbol, order.qty
        if order.side == Side.BUY:
            cost = qty * price + self.commission
            if cost > self.cash + 1e-9:
                order.status = OrderStatus.REJECTED
                raise BrokerError(f"insufficient cash for {sym}: need {cost:.2f}, "
                                  f"have {self.cash:.2f}")
            self.cash -= cost
            pos = self.positions.get(sym)
            if pos and pos.qty > 0:
                # commission-adjusted cost basis (avg_price carries the buy commission)
                new_qty = pos.qty + qty
                pos.avg_price = (pos.avg_price * pos.qty + price * qty + self.commission) / new_qty
                pos.qty = new_qty
            else:
                self.positions[sym] = Position(sym, qty, cost / qty, price)
        else:  # SELL (close/reduce long)
            pos = self.positions.get(sym)
            held = pos.qty if pos else 0
            sell_qty = min(qty, held)
            if sell_qty <= 0:
                order.status = OrderStatus.REJECTED
                raise BrokerError(f"no long position to sell for {sym}")
            self.cash += sell_qty * price - self.commission
            self.realized_pnl += (price - pos.avg_price) * sell_qty - self.commission
            pos.qty -= sell_qty
            qty = sell_qty
            if pos.qty == 0:
                del self.positions[sym]

        order.filled_qty = qty
        order.avg_fill_price = price
        order.status = OrderStatus.FILLED
        self.fills.append(Fill(order.order_id, sym, order.side, qty, price,
                               self.commission, self._now, order.reason))

    def cancel_order(self, order_id: str) -> None:
        o = self.orders.get(order_id)
        if o and o.status in (OrderStatus.NEW, OrderStatus.SUBMITTED):
            o.status = OrderStatus.CANCELLED

    def query_order(self, order_id: str) -> Order:
        if order_id not in self.orders:
            raise BrokerError(f"unknown order {order_id}")
        return self.orders[order_id]

    def query_open_orders(self) -> list[Order]:
        return [o for o in self.orders.values()
                if o.status in (OrderStatus.NEW, OrderStatus.SUBMITTED)]

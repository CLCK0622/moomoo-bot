"""Adapt the live :class:`MoomooTradeGateway` to the execution :class:`Broker`.

This lets ``mode="live"`` route the exact same engine through real OpenD orders —
behind every broker guardrail (enabled-flag, kill switch, allow_orders, REAL gating,
rate limit, masked logging) plus the execution-layer RiskManager. It is **never** the
default; the engine must be explicitly built in live mode AND the gateway explicitly
enabled. Until real credentials / OpenD access are provisioned this path is unverified
(see the blocker list on the issue) — paper mode is the validated venue.
"""

from __future__ import annotations

from ..brokers.moomoo import MoomooTradeGateway
from .broker import Broker, OrderResult, Position


class MoomooExecutionBroker(Broker):
    def __init__(self, gateway: MoomooTradeGateway) -> None:
        self.gateway = gateway

    def positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for row in self.gateway.positions():
            code = str(row.get("code", row.get("stock_code", "")))
            sym = code.split(".")[-1] if "." in code else code
            qty = float(row.get("qty", 0) or 0)
            out[sym] = Position(sym, qty, float(row.get("cost_price", 0) or 0))
        return out

    def equity(self, marks: dict[str, float]) -> float:
        info = self.gateway.account_info()
        # moomoo reports total_assets; fall back to cash if absent.
        return float(info.get("total_assets", info.get("cash", 0.0)) or 0.0)

    def place_market_order(self, symbol: str, side: str, qty: float, price: float) -> OrderResult:
        ack = self.gateway.place_market_order(symbol, side, qty)
        return OrderResult(
            symbol=symbol,
            side=side.upper(),
            qty=qty,
            price=price,
            status="filled",
            order_id=str(ack.get("order_id", "")),
        )

    def cancel_order(self, order_id: str) -> None:
        self.gateway.cancel_order(order_id)

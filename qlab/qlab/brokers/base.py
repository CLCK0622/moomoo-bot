"""Broker abstraction shared by the paper simulator and the live OpenD adapter.

The execution engine talks ONLY to this interface, so the same strategy +
risk + observability stack runs unchanged against an in-memory simulator
(``PaperBroker``) or a real moomoo OpenD gateway (``MoomooOpenDBroker``).
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Protocol

import pandas as pd


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TrdMode(str, enum.Enum):
    DRY_RUN = "dry_run"        # no broker; signals + intended orders logged only
    PAPER = "paper"            # in-memory PaperBroker simulated fills
    OPEND_PAPER = "opend_paper"  # real OpenD, TrdEnv.SIMULATE
    LIVE = "live"              # real OpenD, TrdEnv.REAL — hard-gated, off by default


@dataclass
class Bar:
    time: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Snapshot:
    symbol: str
    last_price: float
    time: pd.Timestamp


@dataclass
class Order:
    symbol: str
    side: Side
    qty: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    reason: str = ""
    strategy: str = ""
    create_ts: float = field(default_factory=time.time)
    # first-hand order-path latency instrumentation (set by the live adapter):
    # submit_ts = wall time just before the broker SDK call; ack_ts = wall time
    # when the gateway acknowledged; latency_ms = monotonic submit->ack round trip.
    submit_ts: Optional[float] = None
    ack_ts: Optional[float] = None
    latency_ms: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value
        d["order_type"] = self.order_type.value
        d["status"] = self.status.value
        return d


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: int
    price: float
    commission: float
    time: pd.Timestamp
    reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value
        d["time"] = str(self.time)
        return d


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float
    last_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.qty * (self.last_price or self.avg_price)

    @property
    def unrealized_pnl(self) -> float:
        return self.qty * ((self.last_price or self.avg_price) - self.avg_price)


@dataclass
class Account:
    cash: float
    total_assets: float
    market_value: float = 0.0
    realized_pnl: float = 0.0


class BrokerError(Exception):
    """Raised for non-retryable broker failures (rejects, auth, bad request)."""


class BrokerConnectionError(BrokerError):
    """Transport / gateway failure — connect lost, retries exhausted on an
    exception, or a disconnect. Distinct from a business reject: the engine
    routes this to ``RiskManager.on_connection_error`` -> global kill switch,
    whereas a plain ``BrokerError`` (e.g. an order reject) is handled locally."""


class Broker(Protocol):
    name: str

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def get_snapshot(self, symbols: list[str]) -> dict[str, Snapshot]: ...
    def get_history_kline(self, symbol: str, timeframe: str,
                          start: str, end: str) -> pd.DataFrame: ...
    def get_account(self) -> Account: ...
    def get_positions(self) -> dict[str, Position]: ...
    def place_order(self, order: Order) -> Order: ...
    def cancel_order(self, order_id: str) -> None: ...
    def query_order(self, order_id: str) -> Order: ...
    def query_open_orders(self) -> list[Order]: ...

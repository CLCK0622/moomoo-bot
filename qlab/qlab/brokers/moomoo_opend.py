"""Live moomoo OpenD adapter (defaults to the SIMULATE / paper account).

Wraps ``OpenSecTradeContext`` + ``OpenQuoteContext`` from the moomoo/futu SDK.
Patterns mirror the repo's legacy ``backend/trader.py`` (the OpenD wiring
reference) but harden them: env-only credentials, a token-bucket rate limiter,
bounded connection retry, structured error handling, and a hard gate on REAL
trading.

NOT runnable in this workspace: there is no OpenD gateway and the SDK is not
installed (see ``available()``). Construction/import never require the SDK; it
is imported lazily in :meth:`connect`.
"""
from __future__ import annotations

import importlib
import os
import time
from typing import Optional

import pandas as pd

from .base import (Account, BrokerError, Order, OrderStatus, OrderType,
                   Position, Side, Snapshot)


def _load_sdk():
    """Return the moomoo/futu SDK module, or None if unavailable."""
    for name in ("moomoo", "futu"):
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


class _RateLimiter:
    """Simple token bucket — OpenD throttles quote/trade calls (~10/30s typical)."""

    def __init__(self, max_calls: int, per_seconds: float):
        self.max_calls = max_calls
        self.per = per_seconds
        self._stamps: list[float] = []

    def acquire(self) -> None:
        now = time.monotonic()
        self._stamps = [t for t in self._stamps if now - t < self.per]
        if len(self._stamps) >= self.max_calls:
            sleep = self.per - (now - self._stamps[0])
            if sleep > 0:
                time.sleep(sleep)
        self._stamps.append(time.monotonic())


class MoomooOpenDBroker:
    name = "moomoo_opend"

    def __init__(self, *, host: str = "127.0.0.1", port: int = 11111,
                 trd_env: str = "SIMULATE", market: str = "US",
                 security_firm: str = "FUTUSG",
                 max_retries: int = 3, retry_backoff: float = 1.5,
                 quote_rate=(10, 30.0), trade_rate=(15, 30.0),
                 logger=None):
        self.host = host
        self.port = port
        self.trd_env_name = trd_env.upper()
        self.market = market
        self.security_firm = security_firm
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._log = logger
        self._sdk = None
        self._trade_ctx = None
        self._quote_ctx = None
        self._quote_rl = _RateLimiter(*quote_rate)
        self._trade_rl = _RateLimiter(*trade_rate)

    # --- availability / preconditions ---
    @staticmethod
    def available() -> bool:
        return _load_sdk() is not None

    def _emit(self, event: str, **kw):
        if self._log is not None:
            self._log.broker_event(self.name, event, **kw)

    # --- lifecycle ---
    def connect(self) -> None:
        sdk = _load_sdk()
        if sdk is None:
            raise BrokerError(
                "moomoo/futu SDK not installed. Install `moomoo-api` (or `futu-api`) "
                "AND run an authenticated OpenD gateway on "
                f"{self.host}:{self.port}. Neither is available in this workspace."
            )
        self._sdk = sdk
        trd_env = sdk.TrdEnv.REAL if self.trd_env_name == "REAL" else sdk.TrdEnv.SIMULATE
        self._trd_env = trd_env
        market = getattr(sdk.TrdMarket, self.market)
        firm = getattr(sdk.SecurityFirm, self.security_firm)

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self._trade_ctx = sdk.OpenSecTradeContext(
                    filter_trdmarket=market, host=self.host, port=self.port,
                    security_firm=firm)
                self._quote_ctx = sdk.OpenQuoteContext(host=self.host, port=self.port)
                self._emit("connected", attempt=attempt, trd_env=self.trd_env_name)
                break
            except Exception as e:  # pragma: no cover - needs gateway
                last_err = e
                self._emit("connect_retry", attempt=attempt, error=str(e))
                time.sleep(self.retry_backoff ** attempt)
        else:
            raise BrokerError(f"OpenD connect failed after {self.max_retries}: {last_err}")

        # REAL trading requires an explicit unlock with an env-only password.
        if self.trd_env_name == "REAL":
            pwd = os.environ.get("MOOMOO_TRADING_PASSWORD")
            if not pwd:
                raise BrokerError("REAL trading requires MOOMOO_TRADING_PASSWORD env var "
                                  "(never store it in the repo).")
            ret, data = self._trade_ctx.unlock_trade(pwd)
            if ret != self._sdk.RET_OK:
                raise BrokerError("unlock_trade failed (password redacted)")
            self._emit("unlocked")  # never log the password

    def close(self) -> None:
        for ctx in (self._trade_ctx, self._quote_ctx):
            try:
                if ctx is not None:
                    ctx.close()
            except Exception:
                pass

    # --- retry helper for transient SDK calls ---
    def _call(self, fn, rl, what: str):
        last = None
        for attempt in range(1, self.max_retries + 1):
            rl.acquire()
            try:
                ret, data = fn()
            except Exception as e:  # transport hiccup
                last = e
                self._emit("call_retry", what=what, attempt=attempt, error=str(e))
                time.sleep(self.retry_backoff ** attempt)
                continue
            if ret == self._sdk.RET_OK:
                return data
            last = data
            self._emit("call_error", what=what, attempt=attempt, ret=str(data))
            time.sleep(self.retry_backoff ** attempt)
        raise BrokerError(f"{what} failed after {self.max_retries}: {last}")

    def _timed_call(self, fn, rl, what: str):
        """Like _call, but returns first-hand submit->ack timing of the winning
        attempt: (data, submit_ts, ack_ts, latency_ms). submit_ts/ack_ts are wall
        clock; latency_ms is a monotonic round-trip (immune to clock skew)."""
        last = None
        for attempt in range(1, self.max_retries + 1):
            rl.acquire()
            submit_ts, submit_perf = time.time(), time.perf_counter()
            try:
                ret, data = fn()
            except Exception as e:
                last = e
                self._emit("call_retry", what=what, attempt=attempt, error=str(e))
                time.sleep(self.retry_backoff ** attempt)
                continue
            ack_perf, ack_ts = time.perf_counter(), time.time()
            latency_ms = (ack_perf - submit_perf) * 1000.0
            if ret == self._sdk.RET_OK:
                return data, submit_ts, ack_ts, latency_ms
            last = data
            self._emit("call_error", what=what, attempt=attempt, ret=str(data),
                       latency_ms=latency_ms)
            time.sleep(self.retry_backoff ** attempt)
        raise BrokerError(f"{what} failed after {self.max_retries}: {last}")

    # --- market data ---
    def get_snapshot(self, symbols: list[str]) -> dict[str, Snapshot]:
        codes = [f"{self.market}.{s}" for s in symbols]
        data = self._call(lambda: self._quote_ctx.get_market_snapshot(codes),
                          self._quote_rl, "get_market_snapshot")
        now = pd.Timestamp.utcnow()
        out = {}
        for _, row in data.iterrows():
            sym = str(row["code"]).split(".")[-1]
            out[sym] = Snapshot(sym, float(row["last_price"]), now)
        return out

    def get_history_kline(self, symbol, timeframe, start, end) -> pd.DataFrame:
        kl_map = {"1m": self._sdk.KLType.K_1M, "15m": self._sdk.KLType.K_15M}
        code = f"{self.market}.{symbol}"
        data = self._call(
            lambda: self._quote_ctx.request_history_kline(
                code, start=start, end=end, ktype=kl_map[timeframe], max_count=1000),
            self._quote_rl, "request_history_kline")
        if isinstance(data, tuple):  # (df, page_req_key)
            data = data[0]
        df = data.rename(columns={"time_key": "time"})
        return df[["time", "open", "high", "low", "close", "volume"]].copy()

    # --- account / positions ---
    def get_account(self) -> Account:
        data = self._call(lambda: self._trade_ctx.accinfo_query(trd_env=self._trd_env),
                          self._trade_rl, "accinfo_query")
        cash = float(data["cash"][0])
        total = float(data["total_assets"][0])
        return Account(cash=cash, total_assets=total, market_value=total - cash)

    def get_positions(self) -> dict[str, Position]:
        data = self._call(lambda: self._trade_ctx.position_list_query(trd_env=self._trd_env),
                          self._trade_rl, "position_list_query")
        out = {}
        for _, row in data.iterrows():
            sym = str(row["code"]).split(".")[-1]
            qty = int(float(row["qty"]))
            if qty == 0:
                continue
            out[sym] = Position(sym, qty, float(row["cost_price"]),
                                float(row.get("nominal_price", row["cost_price"])))
        return out

    # --- orders ---
    def place_order(self, order: Order) -> Order:
        sdk = self._sdk
        side = sdk.TrdSide.BUY if order.side == Side.BUY else sdk.TrdSide.SELL
        otype = sdk.OrderType.MARKET if order.order_type == OrderType.MARKET else sdk.OrderType.NORMAL
        price = 0 if order.order_type == OrderType.MARKET else (order.limit_price or 0)
        code = f"{self.market}.{order.symbol}"
        data, submit_ts, ack_ts, latency_ms = self._timed_call(
            lambda: self._trade_ctx.place_order(
                price=price, qty=order.qty, code=code, trd_side=side,
                trd_env=self._trd_env, order_type=otype),
            self._trade_rl, "place_order")
        order.order_id = str(data["order_id"][0]) if "order_id" in data else None
        order.status = OrderStatus.SUBMITTED
        order.submit_ts, order.ack_ts, order.latency_ms = submit_ts, ack_ts, latency_ms
        self._emit("order_submitted", order_id=order.order_id, symbol=order.symbol,
                   side=order.side.value, qty=order.qty, reason=order.reason,
                   submit_ts=submit_ts, ack_ts=ack_ts, latency_ms=latency_ms)
        return order

    def cancel_order(self, order_id: str) -> float:
        sdk = self._sdk
        _, submit_ts, ack_ts, latency_ms = self._timed_call(
            lambda: self._trade_ctx.modify_order(
                sdk.ModifyOrderOp.CANCEL, order_id, 0, 0, trd_env=self._trd_env),
            self._trade_rl, "cancel_order")
        self._emit("order_cancelled", order_id=order_id, submit_ts=submit_ts,
                   ack_ts=ack_ts, latency_ms=latency_ms)
        return latency_ms

    # --- position reconciliation (first-hand deviation source) ---
    def reconcile_positions(self, engine_positions: dict) -> dict:
        """Compare engine intent (symbol -> qty) against the broker's truth and
        emit a ``position_reconcile`` broker_event. This is the first-hand source
        for the 'position deviation' metric."""
        broker = self.get_positions()
        broker_qty = {s: p.qty for s, p in broker.items()}
        syms = set(engine_positions) | set(broker_qty)
        diffs = {}
        for s in sorted(syms):
            e = int(engine_positions.get(s, 0))
            b = int(broker_qty.get(s, 0))
            if e != b:
                diffs[s] = {"engine": e, "broker": b, "delta": b - e}
        result = {"in_sync": not diffs, "n_diffs": len(diffs), "diffs": diffs,
                  "engine_positions": engine_positions, "broker_positions": broker_qty}
        self._emit("position_reconcile", **result)
        return result

    def query_order(self, order_id: str) -> Order:
        data = self._call(
            lambda: self._trade_ctx.order_list_query(order_id=order_id, trd_env=self._trd_env),
            self._trade_rl, "order_list_query")
        if data is None or len(data) == 0:
            raise BrokerError(f"order {order_id} not found")
        row = data.iloc[0]
        o = Order(symbol=str(row["code"]).split(".")[-1],
                  side=Side.BUY if str(row["trd_side"]).upper().endswith("BUY") else Side.SELL,
                  qty=int(float(row["qty"])), order_id=order_id)
        o.filled_qty = int(float(row.get("dealt_qty", 0)))
        o.avg_fill_price = float(row.get("dealt_avg_price", 0) or 0)
        return o

    def query_open_orders(self) -> list[Order]:
        data = self._call(lambda: self._trade_ctx.order_list_query(trd_env=self._trd_env),
                          self._trade_rl, "order_list_query")
        out = []
        for _, row in data.iterrows():
            status = str(row.get("order_status", ""))
            if "FILLED_ALL" in status or "CANCELLED" in status or "FAILED" in status:
                continue
            out.append(Order(symbol=str(row["code"]).split(".")[-1],
                             side=Side.BUY if str(row["trd_side"]).upper().endswith("BUY") else Side.SELL,
                             qty=int(float(row["qty"])), order_id=str(row["order_id"])))
        return out

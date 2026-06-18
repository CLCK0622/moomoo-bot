"""moomoo US OpenD adapter — real implementation behind hard guardrails.

This advances the previous skeleton to actual OpenD wiring, reusing the connection
/ subscription / order patterns proven in the old ``moomoo-bot/backend`` (config via
env, ``OpenQuoteContext`` / ``OpenSecTradeContext``, ``unlock_trade``, ``place_order``
with ``trd_env``), but every old anti-pattern is removed:

- the old code hard-coded ``TRADING_PASSWORD`` / ``pwd_unlock`` and committed a
  ``.env`` — here credentials come ONLY from env (``qlab.config.MoomooConfig``) and
  are never logged in the clear (see :func:`mask_secret`);
- the old trader placed live orders by default — here **auto-trading is OFF by
  default** and every order passes through the EVO-13 §3 guardrails:
  enabled-flag, kill switch, allow_orders, SIMULATE/REAL isolation (+ allow_real +
  unlock), rate limit, masked logging, and connect retry/backoff with fail-safe.

The ``futu`` SDK is imported lazily, so importing qlab never requires it. For tests,
inject a ``context_factory`` returning a fake context — the guardrail + order-build
logic runs fully without the SDK or a live OpenD.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..config import MoomooConfig
from ..data.base import Bar, DataSource
from .guardrails import KillSwitch, RateLimiter, SafetyError, call_with_retry, mask_secret

_RET_OK = 0  # futu.RET_OK == 0


class MoomooConfigError(SafetyError):
    """Raised when a live moomoo operation is attempted without valid config/safety."""


def _load_futu():
    try:
        import futu  # type: ignore
    except ImportError as exc:  # pragma: no cover - requires the optional SDK
        raise MoomooConfigError(
            "futu SDK not installed. `pip install futu-api` to use moomoo OpenD."
        ) from exc
    return futu


def _trd_tokens(config: MoomooConfig, *, live: bool):
    """Resolve futu enums (live) or plain string stand-ins (tests/no-SDK).

    Returning strings when the SDK is absent lets injected fake contexts assert on
    readable values; the live path uses the real futu enums.
    """
    if not live:
        return {
            "env": config.trade_env,
            "buy": "BUY",
            "sell": "SELL",
            "market_order": "MARKET",
            "us": "US",
            "firm": config.security_firm,
            "cancel_op": "CANCEL",
        }
    futu = _load_futu()
    return {
        "env": futu.TrdEnv.REAL if config.trade_env == "REAL" else futu.TrdEnv.SIMULATE,
        "buy": futu.TrdSide.BUY,
        "sell": futu.TrdSide.SELL,
        "market_order": futu.OrderType.MARKET,
        "us": futu.TrdMarket.US,
        "firm": getattr(futu.SecurityFirm, config.security_firm, None),
        "cancel_op": futu.ModifyOrderOp.CANCEL,
    }


class MoomooQuoteSource(DataSource):
    """Historical-kline quote source backed by moomoo OpenD.

    Rate-limited and retry-wrapped; refuses to run unless explicitly enabled (so it
    never silently reaches a broker). Returns the same :class:`Bar` list every other
    qlab data source returns, so the backtest/report chain is unchanged.
    """

    def __init__(
        self,
        config: MoomooConfig,
        *,
        rate_limiter: RateLimiter | None = None,
        context_factory: Callable[[], object] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.rate = rate_limiter or RateLimiter(10, 1.0)  # OpenD history is ~10 req/s
        self._context_factory = context_factory
        self.log = logger or logging.getLogger("qlab.brokers.moomoo.quote")

    def _open_context(self):
        if self._context_factory is not None:
            return self._context_factory()
        futu = _load_futu()  # pragma: no cover - live path
        return futu.OpenQuoteContext(host=self.config.host, port=self.config.port)

    def _fetch(self, symbol: str, start: str | None, end: str | None) -> list[Bar]:
        if not self.config.enabled:
            raise MoomooConfigError(
                "moomoo source disabled. Set MOOMOO_ENABLED=true + MOOMOO_* env to use OpenD."
            )
        code = symbol if "." in symbol else f"US.{symbol}"
        ctx = call_with_retry(
            self._open_context,
            retries=self.config.connect_retries,
            backoff_seconds=self.config.connect_backoff_seconds,
        )
        try:
            self.rate.acquire()
            ret, payload = ctx.request_history_kline(code, start=start, end=end)
            if ret != _RET_OK:
                raise MoomooConfigError(f"history_kline failed for {code}: {payload}")
            return [_row_to_bar(r) for r in _iter_rows(payload)]
        finally:
            close = getattr(ctx, "close", None)
            if callable(close):
                close()


def _iter_rows(payload):
    # futu returns a pandas DataFrame; fall back to a plain iterable for fakes.
    itertuples = getattr(payload, "itertuples", None)
    return itertuples(index=False) if callable(itertuples) else payload


def _row_to_bar(row) -> Bar:
    def f(name):
        return getattr(row, name) if hasattr(row, name) else row[name]

    ts = str(f("time_key"))[:10]
    return Bar(
        ts=ts,
        open=float(f("open")),
        high=float(f("high")),
        low=float(f("low")),
        close=float(f("close")),
        volume=float(f("volume")),
    )


class MoomooTradeGateway:
    """Order-routing adapter against moomoo OpenD trade context — guarded.

    Auto-trading is OFF by default. Every order call runs the full guardrail chain
    before any SDK call; on connection failure it retries with backoff and otherwise
    fails safe (no order). ``context_factory`` is injectable for tests.
    """

    def __init__(
        self,
        config: MoomooConfig,
        *,
        kill_switch: KillSwitch | None = None,
        rate_limiter: RateLimiter | None = None,
        context_factory: Callable[[], object] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.kill = kill_switch or KillSwitch(config.kill_switch_file)
        self.rate = rate_limiter or RateLimiter(
            config.max_orders_per_window, config.order_window_seconds
        )
        self._context_factory = context_factory
        self.log = logger or logging.getLogger("qlab.brokers.moomoo.trade")
        self._ctx = None
        self._unlocked = False

    # --- safety ---------------------------------------------------------------
    def _preflight_order(self, qty: float) -> None:
        """Run every guardrail; raise before any SDK call if anything is off."""
        if not self.config.enabled:
            raise MoomooConfigError("moomoo gateway disabled (MOOMOO_ENABLED).")
        self.kill.require_clear()  # 全局急停
        if not self.config.allow_orders:  # 自动交易默认关闭
            raise SafetyError("auto-trading disabled (MOOMOO_ALLOW_ORDERS=false).")
        if not self.config.account_id:
            raise MoomooConfigError("MOOMOO_ACCOUNT_ID not set.")
        if qty is None or qty <= 0:
            raise ValueError("order qty must be positive")
        max_qty = self.config.max_order_qty  # 胖手指硬上限 (与限频正交; engine 风控之下再加一道)
        if max_qty is not None and qty > max_qty:
            raise SafetyError(
                f"order qty {qty} exceeds per-order cap {max_qty} (MOOMOO_MAX_ORDER_QTY)."
            )
        if self.config.trade_env == "REAL":  # 模式隔离
            if not self.config.allow_real:
                raise SafetyError("REAL trading not allowed (MOOMOO_ALLOW_REAL=false).")
            if not self.config.unlock_pwd:
                raise SafetyError("REAL env requires MOOMOO_UNLOCK_PWD.")
        self.rate.acquire()  # 限频

    # --- connection -----------------------------------------------------------
    def _open_context(self):
        if self._context_factory is not None:
            return self._context_factory()
        futu = _load_futu()  # pragma: no cover - live path
        tokens = _trd_tokens(self.config, live=True)
        return futu.OpenSecTradeContext(
            filter_trdmarket=tokens["us"],
            host=self.config.host,
            port=self.config.port,
            security_firm=tokens["firm"],
        )

    def connect(self):
        if self._ctx is None:
            self._ctx = call_with_retry(
                self._open_context,
                retries=self.config.connect_retries,
                backoff_seconds=self.config.connect_backoff_seconds,
            )
            self.log.info(
                "moomoo trade context connected env=%s firm=%s account=%s",
                self.config.trade_env,
                self.config.security_firm,
                mask_secret(self.config.account_id),  # 日志脱敏
            )
        return self._ctx

    def _ensure_unlocked(self) -> None:
        if self.config.trade_env != "REAL" or self._unlocked:
            return
        ctx = self.connect()
        ret, data = ctx.unlock_trade(self.config.unlock_pwd)
        if ret != _RET_OK:
            raise MoomooConfigError(f"unlock_trade failed: {data}")
        self._unlocked = True
        # unlock PIN is low-entropy (often 6 digits) — mask it fully, keep no tail.
        self.log.info(
            "trade account unlocked (pwd=%s)",
            mask_secret(self.config.unlock_pwd, keep=0),
        )

    # --- actions --------------------------------------------------------------
    def account_info(self) -> dict:
        if not self.config.enabled:
            raise MoomooConfigError("moomoo gateway disabled (MOOMOO_ENABLED).")
        ctx = self.connect()
        tokens = _trd_tokens(self.config, live=self._context_factory is None)
        ret, data = call_with_retry(
            lambda: ctx.accinfo_query(trd_env=tokens["env"]),
            retries=self.config.connect_retries,
            backoff_seconds=self.config.connect_backoff_seconds,
        )
        if ret != _RET_OK:
            raise MoomooConfigError(f"accinfo_query failed: {data}")
        return _first_row(data)

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        """Place a market order after the full guardrail chain. side ∈ {BUY, SELL}."""
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        self._preflight_order(qty)
        ctx = self.connect()
        self._ensure_unlocked()
        tokens = _trd_tokens(self.config, live=self._context_factory is None)
        code = symbol if "." in symbol else f"US.{symbol}"
        ret, data = ctx.place_order(
            price=0,
            qty=qty,
            code=code,
            trd_side=tokens["buy"] if side == "BUY" else tokens["sell"],
            trd_env=tokens["env"],
            order_type=tokens["market_order"],
        )
        if ret != _RET_OK:
            raise MoomooConfigError(f"place_order failed for {code}: {data}")
        ack = _first_row(data)
        self.log.info(
            "order ok env=%s %s %s x%s id=%s",
            self.config.trade_env,
            side,
            code,
            qty,
            mask_secret(str(ack.get("order_id", "")), keep=4),
        )
        return ack

    def positions(self) -> list[dict]:
        """Current holdings via position_list_query (read-only; no order guardrails)."""
        if not self.config.enabled:
            raise MoomooConfigError("moomoo gateway disabled (MOOMOO_ENABLED).")
        ctx = self.connect()
        tokens = _trd_tokens(self.config, live=self._context_factory is None)
        ret, data = call_with_retry(
            lambda: ctx.position_list_query(trd_env=tokens["env"]),
            retries=self.config.connect_retries,
            backoff_seconds=self.config.connect_backoff_seconds,
        )
        if ret != _RET_OK:
            raise MoomooConfigError(f"position_list_query failed: {data}")
        return _all_rows(data)

    def open_orders(self) -> list[dict]:
        """Open/working orders via order_list_query (read-only)."""
        if not self.config.enabled:
            raise MoomooConfigError("moomoo gateway disabled (MOOMOO_ENABLED).")
        ctx = self.connect()
        tokens = _trd_tokens(self.config, live=self._context_factory is None)
        ret, data = call_with_retry(
            lambda: ctx.order_list_query(trd_env=tokens["env"]),
            retries=self.config.connect_retries,
            backoff_seconds=self.config.connect_backoff_seconds,
        )
        if ret != _RET_OK:
            raise MoomooConfigError(f"order_list_query failed: {data}")
        return _all_rows(data)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a working order. Requires the same enable/kill guardrails as trading."""
        if not self.config.enabled:
            raise MoomooConfigError("moomoo gateway disabled (MOOMOO_ENABLED).")
        self.kill.require_clear()
        ctx = self.connect()
        self._ensure_unlocked()
        tokens = _trd_tokens(self.config, live=self._context_factory is None)
        ret, data = ctx.modify_order(
            modify_order_op=tokens.get("cancel_op", "CANCEL"),
            order_id=order_id,
            qty=0,
            price=0,
            trd_env=tokens["env"],
        )
        if ret != _RET_OK:
            raise MoomooConfigError(f"cancel_order failed for {order_id}: {data}")
        self.log.info("order cancelled id=%s", mask_secret(str(order_id), keep=4))
        return _first_row(data)

    def submit_target_position(
        self, symbol: str, target_shares: float, current_shares: float = 0.0
    ) -> dict | None:
        """Reconcile current → target by trading the delta. None if no trade needed."""
        delta = target_shares - current_shares
        if abs(delta) < 1e-9:
            return None
        return self.place_market_order(symbol, "BUY" if delta > 0 else "SELL", abs(delta))

    def emergency_stop(self, reason: str = "manual") -> None:
        """全局急停: trip the kill switch and best-effort cancel open orders."""
        self.kill.trip(reason)
        self.log.warning("EMERGENCY STOP tripped: %s", reason)
        if self._ctx is not None:
            cancel = getattr(self._ctx, "cancel_all_order", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:  # never let cleanup raise on the kill path
                    self.log.exception("cancel_all_order failed during emergency stop")

    def close(self) -> None:
        if self._ctx is not None:
            close = getattr(self._ctx, "close", None)
            if callable(close):
                close()
            self._ctx = None
            self._unlocked = False


def _first_row(data) -> dict:
    """Normalise a futu DataFrame (or fake dict/list) to the first row as a dict."""
    if isinstance(data, dict):
        return {k: (v[0] if isinstance(v, (list, tuple)) else v) for k, v in data.items()}
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):  # pragma: no cover - pandas path
        records = data.to_dict("records")
        return records[0] if records else {}
    return dict(data) if data else {}


def _all_rows(data) -> list[dict]:
    """Normalise a futu DataFrame (or fake list-of-dicts) to a list of row dicts."""
    to_dict = getattr(data, "to_dict", None)
    if callable(to_dict):  # pragma: no cover - pandas path
        return list(data.to_dict("records"))
    if isinstance(data, list):
        return [dict(r) for r in data]
    return []

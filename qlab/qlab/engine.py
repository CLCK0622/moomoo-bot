"""Execution engine — signal -> risk -> broker -> observability.

Two entry points share one core tick loop:

* ``run_replay(data)`` — deterministic offline paper-trading over a set of
  pre-fetched bars (fixtures / cached history). This is what runs in CI and in
  this workspace, since it needs no OpenD gateway.
* ``connect()`` + ``on_bar(...)`` — the same per-bar logic a live loop calls
  after each realtime bar/snapshot from the OpenD adapter.

Modes (``ExecConfig.mode``): ``dry_run`` logs signals + intended orders only;
``paper`` simulates fills via ``PaperBroker``; ``opend_paper`` / ``live`` use the
real OpenD adapter (``live`` is hard-gated, off by default).
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .config import ExecConfig
from .observability import Observability
from .params import default_params
from .risk import RiskManager
from .signals import SignalAdapter
from .brokers.base import (BrokerError, Order, OrderType, Side, TrdMode)
from .brokers.paper import PaperBroker


def build_broker(cfg: ExecConfig, obs: Observability):
    mode = cfg.mode
    if mode in (TrdMode.DRY_RUN.value, TrdMode.PAPER.value):
        return PaperBroker(cfg.initial_capital, cfg.commission_per_order, cfg.slippage_pct)
    if mode in (TrdMode.OPEND_PAPER.value, TrdMode.LIVE.value):
        if mode == TrdMode.LIVE.value and not cfg.allow_live:
            raise BrokerError("LIVE trading refused: set allow_live=True / "
                              "QLAB_ALLOW_LIVE=1 AND pass --i-understand-live.")
        from .brokers.moomoo_opend import MoomooOpenDBroker
        trd_env = "REAL" if mode == TrdMode.LIVE.value else "SIMULATE"
        return MoomooOpenDBroker(host=cfg.opend_host, port=cfg.opend_port,
                                 trd_env=trd_env, security_firm=cfg.security_firm,
                                 logger=obs)
    raise BrokerError(f"unknown mode {mode}")


class ExecutionEngine:
    def __init__(self, cfg: ExecConfig, run_dir: str | Path, params: dict | None = None,
                 also_stdout: bool = False):
        self.cfg = cfg
        self.params = params or default_params()
        self.obs = Observability(run_dir, also_stdout=also_stdout)
        self.adapter = SignalAdapter(self.params)
        self.risk = RiskManager(cfg.risk, cfg.initial_capital, logger=self.obs)
        self.broker = build_broker(cfg, self.obs)
        self.dry_run = cfg.mode == TrdMode.DRY_RUN.value
        self.state: dict[str, dict] = {}       # symbol -> vendored position state (exit logic)
        self.strategy_of: dict[str, str] = {}
        self._prev_price: dict[str, float] = {}
        self._day_realized = 0.0
        self.equity_curve: list[dict] = []
        self.obs.text(f"engine init mode={cfg.mode} broker={self.broker.name} "
                      f"symbols={len(cfg.symbols)}")

    # --- helpers ---
    def _equity(self) -> float:
        if self.dry_run:
            return self.cfg.initial_capital
        return self.broker.get_account().total_assets

    def _position_size(self, equity: float, price: float) -> int:
        budget = min(equity / self.cfg.risk.max_positions,
                     self.cfg.risk.per_symbol_max_notional)
        return int(budget // price) if price > 0 else 0

    def _strategy_notional(self, strategy: str) -> float:
        total = 0.0
        for sym, st in self.state.items():
            if self.strategy_of.get(sym) == strategy:
                total += st["shares"] * self._prev_price.get(sym, st["entry_price"])
        return total

    # --- per-bar core (shared by replay + live) ---
    def on_bar(self, rows: dict[str, pd.Series]) -> None:
        if not rows:
            return
        sample = next(iter(rows.values()))
        now = sample["time"]

        # mark + abnormal-move detection
        for sym, row in rows.items():
            price = float(row["close"])
            if not self.dry_run:
                self.broker.mark(sym, price, now)
            prev = self._prev_price.get(sym)
            if prev and prev > 0 and abs(price - prev) / prev >= self.cfg.risk.max_price_move_halt_pct:
                self.obs.broker_event("market", "abnormal_move", symbol=sym,
                                      prev=prev, price=price)

        equity = self._equity()
        self.risk.update_equity(equity)

        # --- EXIT scan (always; never blocked by risk) ---
        for sym in list(self.state.keys()):
            if sym not in rows:
                continue
            row = rows[sym]
            sig = self.adapter.exit_signal(self.state[sym], row)
            if sig is None:
                continue
            self.obs.signal(kind="exit", symbol=sym, time=str(now),
                            reason=sig.reason, price=sig.price, qty_pct=sig.quantity_pct)
            shares = self.state[sym]["shares"]
            qty = shares if sig.quantity_pct >= 1.0 else max(1, int(shares * sig.quantity_pct))
            self._submit(sym, Side.SELL, qty, sig.reason, self.strategy_of.get(sym, ""), row)
            if sig.quantity_pct >= 1.0:
                self.state.pop(sym, None)
                self.strategy_of.pop(sym, None)
            else:
                self.state[sym]["shares"] -= qty

        # --- ENTRY scan ---
        candidates = []
        for sym, row in rows.items():
            if sym in self.state:
                continue
            esig = self.adapter.entry_signal(_with_symbol(row, sym))
            if esig is not None:
                candidates.append(esig)
        candidates.sort(key=lambda e: e.score, reverse=True)

        for esig in candidates:
            sym = esig.symbol
            if sym in self.state:
                continue
            price = esig.price
            qty = self._position_size(equity, price)
            if qty < 1:
                continue
            notional = qty * price
            strat = esig.strategy
            decision = self.risk.check_entry(
                symbol=sym, strategy=strat, notional=notional, now=now,
                n_positions=len(self.state), equity=equity,
                strategy_notional=self._strategy_notional(strat),
                last_price=price, prev_price=self._prev_price.get(sym))
            self.obs.signal(kind="entry", symbol=sym, time=str(now), reason=esig.reason,
                            price=price, score=esig.score, qty=qty,
                            risk_ok=decision.allowed, risk_reason=decision.reason)
            if not decision.allowed:
                continue
            order = self._submit(sym, Side.BUY, qty, esig.reason, strat, rows[sym])
            if order is not None and not self.dry_run:
                fill_px = order.avg_fill_price or price
                self.state[sym] = self.adapter.new_position_state(fill_px, qty, esig.orb_low, now)
                self.strategy_of[sym] = strat

        # update prev prices (this bar's close is the latest mark)
        for sym, row in rows.items():
            self._prev_price[sym] = float(row["close"])

        # --- per-bar (1m) mark-to-market observability ---
        # Emit AFTER fills + marks so 户部 can recompute the 1m equity curve and
        # 1m max-drawdown independently. MTM = cash + positions marked at the
        # current bar close (PaperBroker.get_account / OpenD nominal price).
        mtm_equity = self._equity()
        self.risk.update_equity(mtm_equity)        # keep the DD breaker on the 1m mark
        intraday_pnl = mtm_equity - self.risk.day_start_equity
        self.obs.equity(time=str(now), equity=mtm_equity, mark_to_market=True,
                        intraday_pnl=intraday_pnl, open_positions=len(self.state),
                        kill_switch=self.risk.kill_switch, peak_equity=self.risk.peak_equity)
        self.snapshot_positions(now)               # per-bar open-position snapshot

    def emit_heartbeat(self, when, equity: float) -> None:
        """Periodic liveness signal — call from the live loop on a timer, or
        once per session in replay."""
        self.obs.heartbeat(time=str(when), equity=equity,
                           kill_switch=self.risk.kill_switch,
                           kill_reason=self.risk.kill_reason,
                           open_positions=len(self.state),
                           peak_equity=self.risk.peak_equity)

    def snapshot_positions(self, when) -> None:
        for sym, st in self.state.items():
            last = self._prev_price.get(sym, st["entry_price"])
            self.obs.position_snapshot(time=str(when), symbol=sym, qty=st["shares"],
                                       entry_price=st["entry_price"], last_price=last,
                                       strategy=self.strategy_of.get(sym, ""),
                                       unrealized=(last - st["entry_price"]) * st["shares"])

    def _submit(self, symbol, side, qty, reason, strategy, row) -> Order | None:
        order = Order(symbol=symbol, side=side, qty=qty, order_type=OrderType.MARKET,
                      reason=reason, strategy=strategy)
        if self.dry_run:
            order.status = order.status  # NEW
            self.obs.order(intended=True, **order.to_dict())
            return order
        try:
            order = self.broker.place_order(order)
        except BrokerError as e:
            self.obs.error("place_order", str(e), symbol=symbol, side=side.value, qty=qty)
            return None
        self.obs.order(intended=False, **order.to_dict())
        if order.filled_qty:
            self.obs.fill(order_id=order.order_id, symbol=symbol, side=side.value,
                          qty=order.filled_qty, price=order.avg_fill_price, reason=reason)
        return order

    # --- offline replay ---
    def run_replay(self, data: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> dict:
        prepared: dict[str, pd.DataFrame] = {}
        dates = set()
        for sym, (df1, df15) in data.items():
            df = self.adapter.prepare(df1, df15)
            df["symbol"] = sym
            prepared[sym] = df
            dates.update(df["date"].unique())
        all_dates = sorted(dates)

        for date in all_dates:
            day = {s: df[df["date"] == date].sort_values("time").reset_index(drop=True)
                   for s, df in prepared.items()}
            day = {s: d for s, d in day.items() if not d.empty}
            if not day:
                continue
            self.risk.start_new_day(self._equity())
            n_bars = max(len(d) for d in day.values())
            last_time = date
            for i in range(n_bars):
                rows = {s: d.iloc[i] for s, d in day.items() if i < len(d)}
                if rows:
                    last_time = next(iter(rows.values()))["time"]
                self.on_bar(rows)
            # per-bar equity/positions are written inside on_bar (1m MTM). Here we
            # only keep an in-memory daily marker for the summary + a session
            # heartbeat (a live loop would heartbeat on a wall-clock timer).
            eq = self._equity()
            self.equity_curve.append({"date": str(date), "equity": eq,
                                      "kill_switch": self.risk.kill_switch})
            self.emit_heartbeat(last_time, eq)

        return self.summary()

    def summary(self) -> dict:
        acct = None if self.dry_run else self.broker.get_account()
        fills = [] if self.dry_run else [f.to_dict() for f in self.broker.fills]
        return {
            "mode": self.cfg.mode,
            "broker": self.broker.name,
            "final_equity": (acct.total_assets if acct else self.cfg.initial_capital),
            "realized_pnl": (acct.realized_pnl if acct else 0.0),
            "num_fills": len(fills),
            "open_positions": len(self.state),
            "kill_switch": self.risk.kill_switch,
            "kill_reason": self.risk.kill_reason,
            "trading_days": len(self.equity_curve),
        }

    def close(self) -> None:
        try:
            self.broker.close()
        finally:
            self.obs.close()


def _with_symbol(row: pd.Series, sym: str) -> pd.Series:
    if row.get("symbol") == sym:
        return row
    row = row.copy()
    row["symbol"] = sym
    return row

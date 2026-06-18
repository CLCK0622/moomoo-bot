"""Mandatory risk controls — every entry passes through here.

Enforces: global kill switch, per-symbol & per-strategy notional caps, global
position cap, intraday loss limit (blocks new entries), 20% drawdown circuit
breaker (trips the kill switch), abnormal single-bar move halt (per symbol),
trading-session validation, and connection-failure halt.

Fail-closed: any unknown/ambiguous state denies new entries. Exits are never
blocked (you must always be able to flatten / reduce risk).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import RiskLimits


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, limits: RiskLimits, initial_equity: float, logger=None):
        self.limits = limits
        self.initial_equity = initial_equity
        self.peak_equity = initial_equity
        self.day_start_equity = initial_equity
        self.logger = logger
        self.kill_switch = False
        self.kill_reason = ""
        self._start = _parse_hhmm(limits.trading_start)
        self._end = _parse_hhmm(limits.trading_end)

    # --- global controls ---
    def trip_kill_switch(self, reason: str) -> None:
        if not self.kill_switch:
            self.kill_switch = True
            self.kill_reason = reason
            if self.logger:
                self.logger.broker_event("risk", "kill_switch", reason=reason)

    def on_connection_error(self, what: str) -> None:
        self.trip_kill_switch(f"connection_error:{what}")

    def on_market_halt(self, reason: str) -> None:
        self.trip_kill_switch(f"market_halt:{reason}")

    def start_new_day(self, equity: float) -> None:
        self.day_start_equity = equity

    def update_equity(self, equity: float) -> None:
        """Track peak + trip the drawdown breaker. Call every tick/bar."""
        self.peak_equity = max(self.peak_equity, equity)
        if self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity
            if dd >= self.limits.drawdown_breaker_pct:
                self.trip_kill_switch(f"drawdown_breaker dd={dd:.1%}")

    # --- session ---
    def session_open(self, now: pd.Timestamp) -> bool:
        mins = now.hour * 60 + now.minute
        return self._start <= mins < self._end

    # --- entry gate ---
    def check_entry(self, *, symbol: str, strategy: str, notional: float,
                    now: pd.Timestamp, n_positions: int, equity: float,
                    strategy_notional: float, last_price: float,
                    prev_price: float | None) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, f"kill_switch:{self.kill_reason}")
        if not self.session_open(now):
            return RiskDecision(False, "outside_trading_session")

        # intraday loss limit (blocks NEW entries; exits still allowed)
        intraday_pnl = equity - self.day_start_equity
        if self.day_start_equity > 0 and intraday_pnl <= -self.limits.intraday_loss_limit_pct * self.day_start_equity:
            return RiskDecision(False, f"intraday_loss_limit pnl={intraday_pnl:.0f}")

        if n_positions >= self.limits.max_positions:
            return RiskDecision(False, "max_positions")
        if notional > self.limits.per_symbol_max_notional:
            return RiskDecision(False, f"per_symbol_cap {notional:.0f}>"
                                       f"{self.limits.per_symbol_max_notional:.0f}")
        if strategy_notional + notional > self.limits.per_strategy_max_notional:
            return RiskDecision(False, "per_strategy_cap")

        # abnormal single-bar move -> skip this symbol (likely bad print / halt)
        if prev_price and prev_price > 0:
            move = abs(last_price - prev_price) / prev_price
            if move >= self.limits.max_price_move_halt_pct:
                return RiskDecision(False, f"abnormal_move {move:.1%}")

        return RiskDecision(True, "ok")


def _parse_hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)

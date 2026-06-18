"""Risk hard-guardrails for the execution layer (EVO-13 §4; 缺一视为未完成).

Guardrails enforced here, on top of the broker-level kill switch / rate limit /
masking in :mod:`qlab.brokers.guardrails`:

- 仓位上限       per-symbol weight cap + gross-exposure cap + max concurrent positions
- 日内损失阈值   halt new exposure once intraday P&L breaches the limit
- 20% 回撤熔断   peak-to-trough drawdown breaker (latches halted)
- 异常行情停机   single-bar move beyond threshold, or a stale quote, halts trading

Design: a halt blocks *increasing* exposure but still allows *reducing/closing*
(so the book can be de-risked). The manager is stateful (tracks the equity peak and
a latched halt) and pure-stdlib / deterministic via an injectable clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..brokers.guardrails import KillSwitch
from ..config import RiskConfig


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    prev_close: float | None = None
    age_seconds: float = 0.0


class RiskManager:
    def __init__(
        self,
        config: RiskConfig,
        *,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.config = config
        self.kill = kill_switch or KillSwitch()
        self._peak_equity: float | None = None
        self._halted = False
        self._halt_reason = ""

    # --- state ---------------------------------------------------------------
    @property
    def halted(self) -> bool:
        return self._halted or self.kill.is_tripped()

    @property
    def halt_reason(self) -> str:
        if self.kill.is_tripped():
            return f"kill switch ({self.kill.reason or 'external'})"
        return self._halt_reason

    def halt(self, reason: str) -> None:
        self._halted = True
        self._halt_reason = reason

    def register_equity(self, equity: float) -> RiskDecision:
        """Update the equity peak and trip the drawdown breaker if breached."""
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity and self._peak_equity > 0:
            dd = equity / self._peak_equity - 1.0
            if dd <= -self.config.drawdown_breaker:
                self.halt(f"drawdown breaker {dd:.1%} ≤ -{self.config.drawdown_breaker:.0%}")
                return RiskDecision(False, self._halt_reason)
        return RiskDecision(True)

    def check_market(self, quote: Quote) -> RiskDecision:
        """异常行情停机: extreme single-bar move or stale quote latches a halt."""
        if quote.age_seconds > self.config.stale_quote_seconds:
            self.halt(f"stale quote {quote.symbol} age={quote.age_seconds:.0f}s")
            return RiskDecision(False, self._halt_reason)
        if quote.prev_close and quote.prev_close > 0:
            move = abs(quote.price / quote.prev_close - 1.0)
            if move >= self.config.abnormal_move_pct:
                self.halt(f"abnormal move {quote.symbol} {move:.1%}")
                return RiskDecision(False, self._halt_reason)
        return RiskDecision(True)

    # --- pre-trade -----------------------------------------------------------
    def pretrade_check(
        self,
        *,
        increases_exposure: bool,
        symbol_weight_after: float,
        gross_after: float,
        n_positions_after: int,
        intraday_pnl_pct: float,
    ) -> RiskDecision:
        """Final gate before an order. Reducing exposure is allowed even when halted."""
        if self.kill.is_tripped():
            return RiskDecision(False, self.halt_reason)
        # Always allow de-risking trades through.
        if not increases_exposure:
            return RiskDecision(True)
        if self._halted:
            return RiskDecision(False, f"halted: {self._halt_reason}")
        if intraday_pnl_pct <= -self.config.intraday_loss_limit:
            return RiskDecision(
                False,
                f"intraday loss {intraday_pnl_pct:.1%} ≤ -{self.config.intraday_loss_limit:.0%}",
            )
        if abs(symbol_weight_after) > self.config.max_position_weight + 1e-9:
            cap = self.config.max_position_weight
            return RiskDecision(
                False, f"position cap {abs(symbol_weight_after):.0%} > {cap:.0%}"
            )
        if gross_after > self.config.max_gross_exposure + 1e-9:
            return RiskDecision(
                False, f"gross cap {gross_after:.0%} > {self.config.max_gross_exposure:.0%}"
            )
        if n_positions_after > self.config.max_positions:
            return RiskDecision(
                False, f"max positions {n_positions_after} > {self.config.max_positions}"
            )
        return RiskDecision(True)

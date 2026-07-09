"""Execution config — env-driven, no secrets in the repo.

Resolution order: explicit kwargs > environment (``QLAB_*``) > defaults.
Credentials (e.g. the REAL trading password) are NEVER part of this object;
the OpenD adapter reads ``MOOMOO_TRADING_PASSWORD`` from the environment only
at unlock time. See ``.env.example`` / ``config.example.yaml``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict


def _env_float(key, default):
    v = os.environ.get(key)
    return float(v) if v not in (None, "") else default


def _env_int(key, default):
    v = os.environ.get(key)
    return int(v) if v not in (None, "") else default


@dataclass
class RiskLimits:
    max_positions: int = 5                  # global concurrent positions cap
    per_symbol_max_notional: float = 25_000.0  # per-symbol position cap ($)
    per_strategy_max_notional: float = 100_000.0
    intraday_loss_limit_pct: float = 0.03   # halt new entries after this daily loss
    drawdown_breaker_pct: float = 0.20      # 20% equity DD -> full kill switch
    max_price_move_halt_pct: float = 0.25   # abnormal single-bar move -> skip symbol
    trading_start: str = "09:30"
    trading_end: str = "16:00"


@dataclass
class ExecConfig:
    mode: str = "paper"                     # dry_run | paper | opend_paper | live
    symbols: list[str] = field(default_factory=lambda: [
        "TSLA", "NVDA", "AMZN", "GOOGL", "META", "AAPL", "MSFT", "AMD", "AVGO", "PLTR"])
    initial_capital: float = 100_000.0
    commission_per_order: float = 1.0
    slippage_pct: float = 0.0002
    # OpenD connection (host/port only; no credentials here)
    opend_host: str = "127.0.0.1"
    opend_port: int = 11111
    trd_env: str = "SIMULATE"               # SIMULATE | REAL (REAL also needs --i-understand-live)
    security_firm: str = "FUTUSG"
    allow_live: bool = False                # hard gate; LIVE refused unless True
    reconcile_every_bars: int = 15          # engine.state vs broker positions (0=off)
    risk: RiskLimits = field(default_factory=RiskLimits)

    @classmethod
    def from_env(cls, **overrides) -> "ExecConfig":
        risk = RiskLimits(
            max_positions=_env_int("QLAB_MAX_POSITIONS", 5),
            per_symbol_max_notional=_env_float("QLAB_PER_SYMBOL_MAX_NOTIONAL", 25_000.0),
            per_strategy_max_notional=_env_float("QLAB_PER_STRATEGY_MAX_NOTIONAL", 100_000.0),
            intraday_loss_limit_pct=_env_float("QLAB_INTRADAY_LOSS_LIMIT_PCT", 0.03),
            drawdown_breaker_pct=_env_float("QLAB_DD_BREAKER_PCT", 0.20),
        )
        cfg = cls(
            mode=os.environ.get("QLAB_MODE", "paper"),
            initial_capital=_env_float("QLAB_INITIAL_CAPITAL", 100_000.0),
            opend_host=os.environ.get("QLAB_OPEND_HOST", "127.0.0.1"),
            opend_port=_env_int("QLAB_OPEND_PORT", 11111),
            trd_env=os.environ.get("QLAB_TRD_ENV", "SIMULATE"),
            allow_live=os.environ.get("QLAB_ALLOW_LIVE", "").lower() in ("1", "true", "yes"),
            risk=risk,
        )
        syms = os.environ.get("QLAB_SYMBOLS")
        if syms:
            cfg.symbols = [s.strip().upper() for s in syms.split(",") if s.strip()]
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

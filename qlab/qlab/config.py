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


# Sector/industry classification for the default universe (EVO-10 industry cap).
# Unmapped symbols fall back to their own bucket, so an unknown name is only
# bound by the per-symbol cap (never lumped with unrelated names).
DEFAULT_INDUSTRY_MAP: dict = {
    "NVDA": "semiconductors", "AMD": "semiconductors", "AVGO": "semiconductors",
    "MU": "semiconductors", "TSM": "semiconductors", "INTC": "semiconductors",
    "QCOM": "semiconductors", "MRVL": "semiconductors", "ASML": "semiconductors",
    "AMAT": "semiconductors", "LRCX": "semiconductors", "KLAC": "semiconductors",
    "ADI": "semiconductors", "MPWR": "semiconductors", "SMH": "semiconductors",
    "AAPL": "mega_tech", "MSFT": "mega_tech", "GOOGL": "mega_tech",
    "META": "mega_tech", "AMZN": "mega_tech", "PLTR": "software", "APP": "software",
    "SNPS": "software", "CDNS": "software", "PANW": "software",
    "TSLA": "autos_ev", "HOOD": "fintech", "CRCL": "fintech", "AXP": "fintech",
    "CVX": "energy", "XOM": "energy", "SCCO": "materials", "COST": "consumer",
    "WMT": "consumer", "UNH": "healthcare", "NVO": "healthcare", "LLY": "healthcare",
}


@dataclass
class RiskLimits:
    max_positions: int = 5                  # global concurrent positions cap
    # EVO-10 aligned exposure caps as % of equity (single 10 / industry 25 /
    # strategy 30). These are enforced ALONGSIDE the absolute notional backstops
    # below; the tighter of (pct*equity, notional) binds. See risk.check_entry.
    per_symbol_max_pct: float = 0.10
    per_industry_max_pct: float = 0.25
    per_strategy_max_pct: float = 0.30
    per_symbol_max_notional: float = 25_000.0  # absolute per-symbol backstop ($)
    per_strategy_max_notional: float = 100_000.0  # absolute per-strategy backstop ($)
    intraday_loss_limit_pct: float = 0.03   # halt new entries after this daily loss
    drawdown_breaker_pct: float = 0.20      # 20% equity DD -> full kill switch
    max_price_move_halt_pct: float = 0.25   # abnormal single-bar move threshold
    abnormal_move_global_halt: bool = True  # True: abnormal move -> GLOBAL halt
                                            # False: legacy per-symbol soft block
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
    industry_map: dict = field(default_factory=lambda: dict(DEFAULT_INDUSTRY_MAP))
    risk: RiskLimits = field(default_factory=RiskLimits)

    def industry_of(self, symbol: str) -> str:
        # unmapped -> own bucket, so it's only bound by the per-symbol cap
        return self.industry_map.get(symbol, f"_sym:{symbol}")

    @classmethod
    def from_env(cls, **overrides) -> "ExecConfig":
        risk = RiskLimits(
            max_positions=_env_int("QLAB_MAX_POSITIONS", 5),
            per_symbol_max_pct=_env_float("QLAB_PER_SYMBOL_MAX_PCT", 0.10),
            per_industry_max_pct=_env_float("QLAB_PER_INDUSTRY_MAX_PCT", 0.25),
            per_strategy_max_pct=_env_float("QLAB_PER_STRATEGY_MAX_PCT", 0.30),
            per_symbol_max_notional=_env_float("QLAB_PER_SYMBOL_MAX_NOTIONAL", 25_000.0),
            per_strategy_max_notional=_env_float("QLAB_PER_STRATEGY_MAX_NOTIONAL", 100_000.0),
            intraday_loss_limit_pct=_env_float("QLAB_INTRADAY_LOSS_LIMIT_PCT", 0.03),
            drawdown_breaker_pct=_env_float("QLAB_DD_BREAKER_PCT", 0.20),
            abnormal_move_global_halt=os.environ.get(
                "QLAB_ABNORMAL_MOVE_GLOBAL_HALT", "1").lower() in ("1", "true", "yes"),
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

"""Single-run driver around the vendored deterministic strategy core.

Responsibilities:
* Put ``qlab/vendor/qstrat`` on ``sys.path`` so the vendored modules import with
  their original absolute paths (``config``, ``backtest.*``, ``indicators.*`` …) —
  i.e. they run **verbatim**, unchanged.
* Load -> preprocess (param-independent) once, compute indicators per parameter
  set (cached), then run the backtest over any subset of trading days at a chosen
  cost multiplier.
* Annualise returns from the daily equity curve for comparison against the
  '~45% annualized' claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --- make the vendored core importable verbatim ---
_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "qstrat"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from config import Config  # noqa: E402  (vendored)
from data.preprocess import Preprocessor  # noqa: E402  (vendored)
from indicators.registry import IndicatorRegistry  # noqa: E402  (vendored)
from backtest.engine import BacktestEngine  # noqa: E402  (vendored)
from backtest.metrics import compute_metrics  # noqa: E402  (vendored)

TRADING_DAYS_PER_YEAR = 252


def make_config(initial_capital: float = 100_000.0, max_positions: int = 5,
                commission: float = 1.0, slippage_pct: float = 0.0002,
                cost_mult: float = 1.0) -> Config:
    """Vendored Config with the cost knob applied (commission + slippage scaled)."""
    return Config(
        initial_capital=initial_capital,
        max_positions=max_positions,
        commission_per_trade=commission * cost_mult,
        slippage_pct=slippage_pct * cost_mult,
    )


def annualized_return(daily_pnl: list[dict]) -> float:
    if len(daily_pnl) < 2:
        return 0.0
    eq0 = daily_pnl[0]["equity"]
    eq1 = daily_pnl[-1]["equity"]
    if eq0 <= 0:
        return 0.0
    total = eq1 / eq0
    n_days = len(daily_pnl)
    if total <= 0:
        return -1.0
    return float(total ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0)


class QlabRunner:
    def __init__(self, datasource):
        self.ds = datasource
        self._raw: dict[str, pd.DataFrame] = {}        # preprocessed, param-independent
        self._indicator_cache: dict[int, dict[str, pd.DataFrame]] = {}
        self._registry = IndicatorRegistry()
        self.all_dates: list = []
        self.skipped: list[str] = []

    def prepare(self) -> None:
        pre = Preprocessor(orb_minutes=15)
        dates = set()
        for symbol in self.ds.symbols():
            df_1m = self.ds.load(symbol, "1m")
            df_15m = self.ds.load(symbol, "15m")
            if df_1m is None or df_15m is None or df_1m.empty or df_15m.empty:
                self.skipped.append(symbol)
                continue
            merged = pre.process(df_1m, df_15m)
            self._raw[symbol] = merged
            dates.update(merged["date"].unique())
        self.all_dates = sorted(dates)
        if not self._raw:
            raise RuntimeError("No usable symbols after preprocessing — check data source.")

    def _indicators(self, params: dict) -> dict[str, pd.DataFrame]:
        key = int(params.get("orb_lock_minutes", 15))  # only orb depends on params here
        if key not in self._indicator_cache:
            data = {sym: self._registry.compute_all(df, params) for sym, df in self._raw.items()}
            self._indicator_cache[key] = data
        return self._indicator_cache[key]

    def run(self, params: dict, dates=None, cost_mult: float = 1.0) -> dict:
        """Run the backtest over ``dates`` (default: all) at ``cost_mult``."""
        indicator_data = self._indicators(params)
        if dates is not None:
            date_set = set(dates)
            indicator_data = {
                sym: df[df["date"].isin(date_set)].reset_index(drop=True)
                for sym, df in indicator_data.items()
            }
            indicator_data = {s: d for s, d in indicator_data.items() if not d.empty}
        cfg = make_config(cost_mult=cost_mult)
        engine = BacktestEngine(cfg)
        result = engine.run(indicator_data, params)
        m = dict(result["metrics"])
        m["annualized_return_pct"] = annualized_return(result["daily_pnl"])
        m["n_trading_days"] = len(result["daily_pnl"])
        m["cost_mult"] = cost_mult
        return {
            "metrics": m,
            "trade_log": result["trade_log"],
            "daily_pnl": result["daily_pnl"],
            "config": {
                "initial_capital": cfg.initial_capital,
                "max_positions": cfg.max_positions,
                "commission_per_trade": cfg.commission_per_trade,
                "slippage_pct": cfg.slippage_pct,
            },
        }

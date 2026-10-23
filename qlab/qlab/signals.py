"""Signal adapter — wires quant-strategies' author logic into the live skeleton.

This does NOT reimplement the strategy. It calls the *vendored* decision
functions verbatim:

* entries  -> ``strategy.combiner.build_entry_evaluator`` (+ ORB-lock / session
  gating identical to ``backtest.engine._run_day``)
* exits    -> ``strategy.exit_manager.ExitManager.evaluate``
* indicators -> ``indicators.registry.IndicatorRegistry`` on the vendored
  ``data.preprocess.Preprocessor`` output

so by construction the integrated signal/order behaviour matches the author's
backtest semantics. The lightweight consistency check (see tests) replays a
fixture through both this adapter and the vendored ``BacktestEngine`` and
asserts the entry decisions agree.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "qstrat"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from data.preprocess import Preprocessor          # noqa: E402 (vendored)
from indicators.registry import IndicatorRegistry  # noqa: E402 (vendored)
from strategy.combiner import build_entry_evaluator  # noqa: E402 (vendored)
from strategy.exit_manager import ExitManager       # noqa: E402 (vendored)


@dataclass
class EntrySignal:
    symbol: str
    time: pd.Timestamp
    price: float
    orb_low: float
    score: float
    reason: str = "orb_breakout"
    strategy: str = "orb_breakout"


@dataclass
class ExitSignalOut:
    symbol: str
    time: pd.Timestamp
    price: float
    quantity_pct: float
    reason: str


class SignalAdapter:
    def __init__(self, params: dict):
        self.params = params
        self._entry_eval = build_entry_evaluator(params)
        self._exit_mgr = ExitManager(params)
        self._registry = IndicatorRegistry()
        self.orb_lock = int(params.get("orb_lock_minutes", 15))
        self.max_entry_hour = int(params.get("max_entry_hour", 15))

    # --- data prep (fixture replay / warm-up buffer) ---
    def prepare(self, df_1m: pd.DataFrame, df_15m: pd.DataFrame) -> pd.DataFrame:
        merged = Preprocessor(orb_minutes=self.orb_lock).process(df_1m, df_15m)
        return self._registry.compute_all(merged, self.params)

    # --- entries ---
    def _within_session(self, t: pd.Timestamp) -> bool:
        minutes_since_open = t.hour * 60 + t.minute - (9 * 60 + 30)
        if minutes_since_open < self.orb_lock:
            return False
        return t.hour < self.max_entry_hour or (t.hour == self.max_entry_hour and t.minute == 0)

    def entry_signal(self, row: pd.Series) -> EntrySignal | None:
        """Return an entry signal if the vendored evaluator fires on this bar."""
        t = row["time"]
        if not self._within_session(t):
            return None
        if pd.isna(row.get("orb_high")) or pd.isna(row.get("orb_low")):
            return None
        if not self._entry_eval(row, self.params):
            return None
        breakout = (row["close"] - row["orb_high"]) / row["orb_high"]
        vol_ratio = 1.5 if row.get("volume_spike") else 1.0
        return EntrySignal(symbol=row.get("symbol", "?"), time=t, price=float(row["close"]),
                           orb_low=float(row["orb_low"]), score=float(breakout * vol_ratio))

    # --- per-open-position state (mirrors portfolio.open_position fields) ---
    @staticmethod
    def new_position_state(entry_price: float, shares: int, orb_low: float,
                           time: pd.Timestamp) -> dict:
        return {
            "entry_price": entry_price, "shares": shares, "orb_low": orb_low,
            "entry_time": time, "tp1_hit": False, "tp2_hit": False,
            "max_profit_price": entry_price, "current_stop": orb_low,
        }

    def exit_signal(self, state: dict, row: pd.Series) -> ExitSignalOut | None:
        sig = self._exit_mgr.evaluate(state, row)  # mutates state (tp1/trailing) — vendored
        if sig is None:
            return None
        return ExitSignalOut(symbol=row.get("symbol", "?"), time=row["time"],
                             price=float(row["close"]), quantity_pct=sig.quantity_pct,
                             reason=sig.reason)

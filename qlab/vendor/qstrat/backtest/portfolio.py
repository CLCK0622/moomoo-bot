from __future__ import annotations
import pandas as pd
import math


class Portfolio:
    def __init__(self, initial_capital: float, max_positions: int, commission: float, slippage_pct: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_positions = max_positions
        self.commission = commission
        self.slippage_pct = slippage_pct
        self.positions: dict[str, dict] = {}
        self.trade_log: list[dict] = []
        self.daily_pnl: list[dict] = []
        self._day_start_equity = initial_capital

    @property
    def available_slots(self) -> int:
        return self.max_positions - len(self.positions)

    @property
    def _current_equity(self) -> float:
        equity = self.cash
        for pos in self.positions.values():
            equity += pos["shares"] * pos["entry_price"]
        return equity

    def current_position_size(self, dd_scale_start: float = 0.05, dd_scale_min: float = 0.4) -> float:
        """Position size with compounding + drawdown scaling.
        When in drawdown > dd_scale_start, linearly reduce size down to dd_scale_min."""
        equity = self._current_equity
        base_size = equity / self.max_positions

        peak = self.initial_capital
        for d in self.daily_pnl:
            peak = max(peak, d["equity"])
        peak = max(peak, equity)

        dd_pct = (peak - equity) / peak if peak > 0 else 0

        if dd_pct <= dd_scale_start:
            return base_size

        # Linear scale: from 1.0 at dd_scale_start to dd_scale_min at 20% drawdown
        max_dd_for_scaling = 0.20
        scale = 1.0 - (1.0 - dd_scale_min) * min((dd_pct - dd_scale_start) / (max_dd_for_scaling - dd_scale_start), 1.0)
        return base_size * scale

    def open_position(self, symbol: str, price: float, size: float, orb_low: float, time: pd.Timestamp):
        fill_price = price * (1 + self.slippage_pct)
        shares = math.floor(size / fill_price)
        if shares <= 0:
            return
        cost = shares * fill_price + self.commission
        self.cash -= cost
        self.positions[symbol] = {
            "entry_price": fill_price, "shares": shares, "orb_low": orb_low,
            "entry_time": time, "tp1_hit": False, "tp2_hit": False,
            "max_profit_price": fill_price, "current_stop": orb_low,
        }

    def open_short_position(self, symbol: str, price: float, size: float, orb_high: float, time: pd.Timestamp):
        fill_price = price * (1 - self.slippage_pct)
        shares = math.floor(size / fill_price)
        if shares <= 0:
            return
        self.cash += shares * fill_price - self.commission
        self.positions[symbol] = {
            "entry_price": fill_price, "shares": shares, "orb_low": fill_price * 0.95,
            "orb_high": orb_high,
            "entry_time": time, "tp1_hit": False, "tp2_hit": False,
            "max_profit_price": fill_price, "current_stop": orb_high,
            "direction": "short",
        }

    def close_position(self, symbol: str, price: float, quantity_pct: float, reason: str, time: pd.Timestamp):
        pos = self.positions[symbol]
        is_short = pos.get("direction") == "short"
        shares_to_close = math.floor(pos["shares"] * quantity_pct)
        if shares_to_close <= 0:
            shares_to_close = pos["shares"]

        if is_short:
            fill_price = price * (1 + self.slippage_pct)
            self.cash -= shares_to_close * fill_price + self.commission
            pnl = (pos["entry_price"] - fill_price) * shares_to_close - 2 * self.commission
        else:
            fill_price = price * (1 - self.slippage_pct)
            proceeds = shares_to_close * fill_price - self.commission
            self.cash += proceeds
            pnl = (fill_price - pos["entry_price"]) * shares_to_close - 2 * self.commission

        self.trade_log.append({
            "symbol": symbol, "entry_price": pos["entry_price"], "exit_price": fill_price,
            "shares": shares_to_close, "entry_time": pos["entry_time"], "exit_time": time,
            "pnl": pnl, "reason": reason, "direction": pos.get("direction", "long"),
        })
        remaining = pos["shares"] - shares_to_close
        if remaining <= 0:
            del self.positions[symbol]
        else:
            pos["shares"] = remaining

    def record_daily_pnl(self, date):
        current_equity = self.cash
        for pos in self.positions.values():
            current_equity += pos["shares"] * pos["entry_price"]
        daily_return = current_equity - self._day_start_equity
        self.daily_pnl.append({"date": date, "equity": current_equity, "daily_return": daily_return})
        self._day_start_equity = current_equity

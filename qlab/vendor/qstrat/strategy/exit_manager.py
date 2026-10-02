from __future__ import annotations
import pandas as pd
from dataclasses import dataclass


@dataclass
class ExitSignal:
    quantity_pct: float
    reason: str


class ExitManager:
    def __init__(self, params: dict):
        self.tp1_rr = params.get("tp1_rr_ratio", 1.0)
        self.tp2_atr_mult = params.get("tp2_atr_mult", 3.0)
        self.tp2_sell_pct = params.get("tp2_sell_pct", 0.5)
        self.trailing_retain = params.get("trailing_retain_pct", 0.2)
        self.extreme_stop = params.get("extreme_stop_pct", 0.03)
        self.eod_minute = params.get("eod_close_minute", 55)
        self.trailing_activate_rr = params.get("trailing_activate_rr", 1.5)
        self.use_vwap_exit = params.get("use_vwap_exit", False)
        # R3: fixed percentage take profit
        self.use_fixed_tp = params.get("use_fixed_tp", False)
        self.fixed_tp_pct = params.get("fixed_tp_pct", 0.015)

    def evaluate(self, position: dict, bar: pd.Series) -> ExitSignal | None:
        entry = position["entry_price"]
        close = bar["close"]
        is_short = position.get("direction") == "short"

        if bar["time"].hour == 15 and bar["time"].minute >= self.eod_minute:
            return ExitSignal(quantity_pct=1.0, reason="eod_close")

        # PnL calculation respects direction
        if is_short:
            pnl_pct = (entry - close) / entry
        else:
            pnl_pct = (close - entry) / entry

        if pnl_pct <= -self.extreme_stop:
            return ExitSignal(quantity_pct=1.0, reason="extreme_stop")

        if is_short:
            if close > position["current_stop"]:
                reason = "breakeven_stop" if position["tp1_hit"] else "orb_stop_loss"
                return ExitSignal(quantity_pct=1.0, reason=reason)
        else:
            if close < position["current_stop"]:
                reason = "breakeven_stop" if position["tp1_hit"] else "orb_stop_loss"
                return ExitSignal(quantity_pct=1.0, reason=reason)

        # Fixed percentage take profit
        if self.use_fixed_tp and pnl_pct >= self.fixed_tp_pct:
            return ExitSignal(quantity_pct=1.0, reason="fixed_tp")

        # Trailing stop: works if TP2 hit OR if profit exceeds trailing_activate_rr
        if is_short:
            risk = position.get("orb_high", entry * 1.02) - entry
        else:
            risk = entry - position["orb_low"]

        trailing_active = position["tp2_hit"]
        if not trailing_active and risk > 0:
            if is_short:
                activate_level = entry - risk * self.trailing_activate_rr
                if close <= activate_level or position.get("trailing_active", False):
                    trailing_active = True
                    position["trailing_active"] = True
            else:
                activate_level = entry + risk * self.trailing_activate_rr
                if close >= activate_level or position.get("trailing_active", False):
                    trailing_active = True
                    position["trailing_active"] = True

        if trailing_active:
            if is_short:
                position["max_profit_price"] = min(position["max_profit_price"], close)
                max_profit = entry - position["max_profit_price"]
                if max_profit > 0:
                    current_profit = entry - close
                    if current_profit <= max_profit * self.trailing_retain:
                        return ExitSignal(quantity_pct=1.0, reason="trailing_stop")
            else:
                position["max_profit_price"] = max(position["max_profit_price"], close)
                max_profit = position["max_profit_price"] - entry
                if max_profit > 0:
                    current_profit = close - entry
                    if current_profit <= max_profit * self.trailing_retain:
                        return ExitSignal(quantity_pct=1.0, reason="trailing_stop")

        # VWAP exit: long exits below VWAP, short exits above VWAP
        if self.use_vwap_exit and position["tp1_hit"]:
            vwap = bar.get("vwap")
            if vwap is not None and not pd.isna(vwap):
                if (not is_short and close < vwap) or (is_short and close > vwap):
                    return ExitSignal(quantity_pct=1.0, reason="vwap_exit")

        # TP2 partial exit (long only for now)
        if not is_short and position["tp1_hit"] and not position["tp2_hit"]:
            kc_middle = bar.get("kc_middle")
            kc_atr = bar.get("kc_atr")
            if kc_middle is not None and kc_atr is not None and not pd.isna(kc_middle) and not pd.isna(kc_atr):
                tp2_level = kc_middle + self.tp2_atr_mult * kc_atr
                if close >= tp2_level:
                    position["tp2_hit"] = True
                    position["max_profit_price"] = close
                    return ExitSignal(quantity_pct=self.tp2_sell_pct, reason="tp2_extension")

        # TP1: move stop to breakeven
        if risk > 0 and not position["tp1_hit"]:
            if is_short:
                tp1_level = entry - risk * self.tp1_rr
                if close <= tp1_level:
                    position["tp1_hit"] = True
                    position["current_stop"] = entry
            else:
                tp1_level = entry + risk * self.tp1_rr
                if close >= tp1_level:
                    position["tp1_hit"] = True
                    position["current_stop"] = entry

        return None

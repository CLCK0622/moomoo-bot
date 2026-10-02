import pandas as pd
import numpy as np


def orb_breakout(row: pd.Series, params: dict) -> bool:
    return row["close"] > row["orb_high"]


def vwap_support(row: pd.Series, params: dict) -> bool:
    return row["close"] > row["vwap"]


def kc_trend(row: pd.Series, params: dict) -> bool:
    if pd.isna(row.get("kc_middle")):
        return False
    return row["close_15m"] > row["kc_middle"]


def anti_chase(row: pd.Series, params: dict) -> bool:
    if pd.isna(row.get("kc_upper")):
        return True
    return row["close_15m"] <= row["kc_upper"]


def rsi_not_overbought(row: pd.Series, params: dict) -> bool:
    if pd.isna(row.get("rsi")):
        return True
    return row["rsi"] < params.get("rsi_overbought", 70.0)


def macd_bullish(row: pd.Series, params: dict) -> bool:
    if pd.isna(row.get("macd_histogram")):
        return True
    return row["macd_histogram"] > 0


def volume_spike_confirm(row: pd.Series, params: dict) -> bool:
    return bool(row.get("volume_spike", False))


def ema_cross_bullish(row: pd.Series, params: dict) -> bool:
    return bool(row.get("ema_bullish", False))


def atr_high_vol(row: pd.Series, params: dict) -> bool:
    return bool(row.get("atr_high_vol", False))


ALL_CONDITIONS = {
    "orb_breakout": {"fn": orb_breakout, "always_on": True},
    "vwap_support": {"fn": vwap_support, "toggle_param": "use_vwap_filter"},
    "kc_trend": {"fn": kc_trend, "toggle_param": "use_kc_trend"},
    "anti_chase": {"fn": anti_chase, "toggle_param": "use_anti_chase"},
    "rsi_not_overbought": {"fn": rsi_not_overbought, "toggle_param": "use_rsi_filter"},
    "macd_bullish": {"fn": macd_bullish, "toggle_param": "use_macd_filter"},
    "volume_spike_confirm": {"fn": volume_spike_confirm, "toggle_param": "use_volume_spike"},
    "ema_cross_bullish": {"fn": ema_cross_bullish, "toggle_param": "use_ema_cross"},
    "atr_high_vol": {"fn": atr_high_vol, "toggle_param": "use_atr_pctl_filter"},
}

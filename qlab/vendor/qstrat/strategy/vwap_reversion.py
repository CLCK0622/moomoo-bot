from __future__ import annotations
import pandas as pd
import numpy as np


def vwap_reversion_entry(row: pd.Series, params: dict) -> bool:
    """Mean-reversion entry: price extended away from VWAP, expect snap-back.
    Used in low-volatility regimes where breakout strategies fail."""
    vwap = row.get("vwap")
    close = row.get("close")

    if vwap is None or pd.isna(vwap) or vwap <= 0:
        return False

    deviation_pct = (close - vwap) / vwap
    threshold = params.get("vwap_reversion_threshold", -0.008)

    # Buy when price is significantly BELOW VWAP (expect reversion up)
    if deviation_pct < threshold:
        # Additional filter: RSI showing oversold
        rsi = row.get("rsi")
        if rsi is not None and not pd.isna(rsi):
            rsi_threshold = params.get("vwap_reversion_rsi", 35.0)
            if rsi > rsi_threshold:
                return False
        return True

    return False


def vwap_reversion_exit(row: pd.Series, position: dict, params: dict) -> bool:
    """Exit when price reverts back to VWAP or slightly above."""
    vwap = row.get("vwap")
    close = row.get("close")

    if vwap is None or pd.isna(vwap):
        return False

    # Take profit when price crosses back above VWAP
    exit_offset = params.get("vwap_reversion_exit_offset", 0.001)
    if close >= vwap * (1 + exit_offset):
        return True

    return False

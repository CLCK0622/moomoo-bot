"""Deterministic swing-signal primitives (RSI, SMA).

Pure functions on a close series; no look-ahead (every value at index ``t`` uses
only closes up to and including ``t``). The strategies consume these to decide a
position *as of a bar's close*, and then execute on the NEXT bar — so a signal
computed on ``close[t]`` never trades at a price from ``t`` or earlier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def wilder_rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """Wilder's RSI (the Connors RSI-2 convention at ``period=2``).

    Uses Wilder smoothing (EMA with ``alpha = 1/period``). Where average loss is
    zero (an unbroken up-run) RSI is 100; where both are zero it is 50 (neutral).
    The first ``period`` values are NaN (insufficient history) and must not trade.
    """
    close = pd.Series(close, dtype=float).reset_index(drop=True)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.where(avg_loss > 0, 100.0)          # no losses -> fully overbought
    rsi = rsi.where((avg_gain > 0) | (avg_loss > 0), 50.0)  # flat -> neutral
    rsi[:period] = np.nan                          # not enough history to trade
    return rsi


def sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average; first ``window-1`` values are NaN (no look-ahead)."""
    return pd.Series(close, dtype=float).reset_index(drop=True).rolling(window).mean()

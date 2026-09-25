from __future__ import annotations
import pandas as pd


def gap_and_go_entry(row: pd.Series, params: dict, prev_close: float) -> bool:
    """Gap-and-Go: enter when a large gap holds direction after ORB period.
    Works best on high-catalyst names with 3%+ gaps."""
    if prev_close <= 0:
        return False

    gap_pct = (row["open"] - prev_close) / prev_close
    min_gap = params.get("gap_go_min_pct", 0.03)
    close = row["close"]
    orb_high = row.get("orb_high")
    orb_low = row.get("orb_low")

    if pd.isna(orb_high) or pd.isna(orb_low):
        return False

    # Gap up + price holding above ORB high = bullish continuation
    if gap_pct >= min_gap and close > orb_high:
        return True

    return False


def vwap_bounce_entry(row: pd.Series, params: dict) -> bool:
    """VWAP Bounce: buy pullback to VWAP in a trending day.
    Price was above VWAP, pulled back near it, and is bouncing."""
    vwap = row.get("vwap")
    close = row["close"]
    low = row["low"]

    if vwap is None or pd.isna(vwap) or vwap <= 0:
        return False

    # Price is near VWAP (within threshold) but still slightly above
    bounce_threshold = params.get("vwap_bounce_threshold", 0.003)
    deviation = (close - vwap) / vwap

    # Close is near VWAP (within threshold above) AND low touched/crossed VWAP (pullback happened)
    if 0 <= deviation <= bounce_threshold and low <= vwap * 1.001:
        # Confirm: ORB breakout already happened (trending day)
        orb_high = row.get("orb_high")
        if orb_high is not None and not pd.isna(orb_high) and close > orb_high * 0.995:
            return True

    return False

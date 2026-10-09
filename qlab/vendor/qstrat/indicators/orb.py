from __future__ import annotations
import pandas as pd


def compute(df: pd.DataFrame, orb_lock_minutes: int = 15, **kwargs) -> pd.DataFrame:
    df = df.copy()
    df["orb_high"] = float("nan")
    df["orb_low"] = float("nan")

    for date, group in df.groupby("date"):
        market_open_min = 9 * 60 + 30
        times_in_min = group["time"].dt.hour * 60 + group["time"].dt.minute
        orb_mask = times_in_min < (market_open_min + orb_lock_minutes)
        orb_bars = group[orb_mask]

        if orb_bars.empty:
            continue

        orb_high = orb_bars["high"].max()
        orb_low = orb_bars["low"].min()

        day_idx = group.index
        df.loc[day_idx, "orb_high"] = orb_high
        df.loc[day_idx, "orb_low"] = orb_low

    return df


def register_params(trial) -> dict:
    return {
        "orb_lock_minutes": trial.suggest_int("orb_lock_minutes", 5, 30),
    }

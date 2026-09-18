import pandas as pd


class Preprocessor:
    def __init__(self, orb_minutes: int = 15):
        self.orb_minutes = orb_minutes

    def filter_trading_hours(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["time"] = pd.to_datetime(df["time"])
        mask = (
            (df["time"].dt.hour > 9) | ((df["time"].dt.hour == 9) & (df["time"].dt.minute >= 30))
        ) & (df["time"].dt.hour < 16)
        return df[mask].reset_index(drop=True)

    def align_timeframes(self, df_1m: pd.DataFrame, df_15m: pd.DataFrame) -> pd.DataFrame:
        df_1m = df_1m.copy()
        df_15m = df_15m.copy()
        df_1m["time"] = pd.to_datetime(df_1m["time"])
        df_15m["time"] = pd.to_datetime(df_15m["time"])

        cols_15m = {c: f"{c}_15m" for c in ["open", "high", "low", "close", "volume"]}
        df_15m = df_15m.rename(columns=cols_15m)
        df_15m = df_15m.rename(columns={"time": "time_15m"})

        df_1m = df_1m.sort_values("time").reset_index(drop=True)
        df_15m = df_15m.sort_values("time_15m").reset_index(drop=True)

        merged = pd.merge_asof(
            df_1m, df_15m, left_on="time", right_on="time_15m", direction="backward"
        )
        return merged

    def mark_orb_period(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["time"] = pd.to_datetime(df["time"])
        df["date"] = df["time"].dt.date
        market_open = df["time"].dt.hour * 60 + df["time"].dt.minute
        orb_end = 9 * 60 + 30 + self.orb_minutes
        df["is_orb"] = (market_open >= 9 * 60 + 30) & (market_open < orb_end)
        return df

    def process(self, df_1m: pd.DataFrame, df_15m: pd.DataFrame) -> pd.DataFrame:
        df_1m = self.filter_trading_hours(df_1m)
        merged = self.align_timeframes(df_1m, df_15m)
        result = self.mark_orb_period(merged)
        return result

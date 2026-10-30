import pandas as pd
from pathlib import Path
from typing import Optional


class DataCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str, timeframe: str) -> Path:
        return self.cache_dir / f"{symbol}_{timeframe}.parquet"

    def save(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(symbol, timeframe), index=False)

    def load(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        path = self._path(symbol, timeframe)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def has_data(self, symbol: str, timeframe: str) -> bool:
        return self._path(symbol, timeframe).exists()

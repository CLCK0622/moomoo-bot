"""Pluggable bar sources for the reproduction harness.

A DataSource yields, per symbol, a 1-minute and a 15-minute OHLCV frame with
columns ``[time, open, high, low, close, volume]`` (``time`` parseable by
``pandas.to_datetime``). That is exactly the contract the vendored
``data.preprocess.Preprocessor`` expects.

Three implementations:

* ``ParquetDataSource`` — load real bars that someone has already fetched and
  committed/handed over (``<symbol>_<tf>.parquet``). This is the path to a real
  verdict; it requires real data on disk.
* ``SyntheticDataSource`` — deterministic, seeded synthetic bars. For HARNESS
  VALIDATION ONLY. Any returns produced on synthetic bars are meaningless and
  MUST NOT be reported as strategy performance.
* ``MoomooDataSource`` — the original repo's path: a live, authenticated moomoo
  OpenD gateway on 127.0.0.1:11111. Deliberately a thin wrapper around the
  vendored fetcher and gated behind an explicit opt-in, because it is NOT
  reproducible in this workspace (no gateway, no brokerage session). See
  ``available()``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd


BAR_COLUMNS = ["time", "open", "high", "low", "close", "volume"]


class DataSource(Protocol):
    name: str

    def symbols(self) -> list[str]: ...

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """Return an OHLCV frame for ``symbol``/``timeframe`` or None if absent."""
        ...

    def provenance(self) -> dict:
        """Audit trail describing exactly where the bars came from."""
        ...


class ParquetDataSource:
    """Load real bars from ``<dir>/<symbol>_<timeframe>.parquet``."""

    name = "parquet"

    def __init__(self, data_dir: str | Path, symbols: list[str]):
        self.data_dir = Path(data_dir)
        self._symbols = list(symbols)

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        path = self.data_dir / f"{symbol}_{timeframe}.parquet"
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        missing = [c for c in BAR_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path} missing columns {missing}")
        return df[BAR_COLUMNS].copy()

    def provenance(self) -> dict:
        return {
            "source": "parquet",
            "data_dir": str(self.data_dir),
            "performance_meaningful": True,
            "note": "real bars supplied out-of-band; verdict is only valid if "
                    "these bars are genuine market data with documented origin.",
        }


class MoomooDataSource:
    """The original repo's data path — a live moomoo OpenD gateway.

    NOT reproducible in this workspace. Construction is allowed (so the path is
    documented and testable), but ``load`` will surface the hard dependency
    instead of silently fabricating data.
    """

    name = "moomoo_opend"

    def __init__(self, symbols: list[str], host: str = "127.0.0.1", port: int = 11111,
                 history_months: int = 6):
        self._symbols = list(symbols)
        self.host = host
        self.port = port
        self.history_months = history_months

    @staticmethod
    def available() -> bool:
        try:
            import moomoo  # noqa: F401
        except Exception:
            return False
        return False  # even if the SDK is importable, no authenticated gateway here

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        raise RuntimeError(
            "MoomooDataSource requires a running, authenticated moomoo OpenD "
            "gateway (broker session) on "
            f"{self.host}:{self.port} plus ~{self.history_months} months of "
            "1m/15m history. This dependency is NOT available in this workspace, "
            "which is the core reason the original '~45% annualized' claim could "
            "not be independently reproduced. Use ParquetDataSource with bars "
            "fetched on a host that has the gateway."
        )

    def provenance(self) -> dict:
        return {
            "source": "moomoo_opend",
            "host": f"{self.host}:{self.port}",
            "history_months": self.history_months,
            "available": self.available(),
            "performance_meaningful": False,
            "note": "live broker gateway unavailable in this workspace — isolated, "
                    "non-reproducible data path.",
        }

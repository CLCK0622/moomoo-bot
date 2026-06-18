"""qlab — 理财方向探索 策略验证工程骨架.

A dependency-light, layered skeleton for taking candidate strategies through a
single pipeline: data ingest -> strategy -> backtest -> model train/persist ->
report. Every layer is an abstraction with a fixture implementation so the whole
chain runs without real market data.

Design notes:
- The core engine uses only the Python standard library, so `无真实行情也能跑通整条链路`
  and tests/lint run with zero third-party installs.
- pandas / numpy / futu (moomoo OpenD) are *optional* integration points, imported
  lazily inside the adapters that need them. Importing `qlab` never requires them.
"""

from .config import AppConfig, load_config

__all__ = ["AppConfig", "load_config", "__version__"]

__version__ = "0.1.0"

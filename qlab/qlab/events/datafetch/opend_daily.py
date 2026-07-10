"""moomoo OpenD daily-bar path — outer wrapper, vendored file left verbatim.

The vendored fetcher (``qlab/vendor/qstrat/data/fetcher.py``) ships a
``TIMEFRAME_MAP`` with only ``1m`` / ``15m``. The event-drift package needs
daily bars (``K_DAY``). Per the EVO-24 wiring constraint we **do not edit the
vendored file** — instead this wrapper adds ``"1d": KLType.K_DAY`` to the map
*from the outside* at import time, then reuses the vendored ``MoomooFetcher``
unchanged. If the vendored file is ever re-synced upstream, this override still
applies and nothing here conflicts.

Requires a live OpenD gateway plus the ``moomoo-api`` SDK (matching your OpenD
version). Neither exists in this workspace — importing this module raises a
clear ``OpenDUnavailable`` rather than failing obscurely, so ``fetch_all`` can
skip it and record the blocker. This is the production path for gap #2 on a
host that has an OpenD gateway (paper or live) reachable.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd


class OpenDUnavailable(RuntimeError):
    """Raised when the moomoo SDK / OpenD gateway is not importable here."""


def _install_daily_timeframe():
    """Add ``"1d": KLType.K_DAY`` to the vendored map without touching the file."""
    try:
        from moomoo import KLType  # noqa: F401
        from qlab.vendor.qstrat.data import fetcher as _vendor_fetcher
    except Exception as exc:  # noqa: BLE001
        raise OpenDUnavailable(
            "moomoo SDK / OpenD gateway not available in this workspace. "
            "Install moomoo-api matching your OpenD version and run this on a "
            "host with a reachable OpenD gateway (127.0.0.1:11111 by default)."
        ) from exc
    # outer override — the vendored source stays byte-for-byte unchanged
    _vendor_fetcher.TIMEFRAME_MAP.setdefault("1d", KLType.K_DAY)
    return _vendor_fetcher


def fetch_daily_parquet(symbols: List[str], start: str, end: str,
                        data_dir="data/daily", host: str = "127.0.0.1",
                        port: int = 11111) -> dict:
    """Fetch adjusted daily bars via OpenD and persist ``<symbol>_1d.parquet``.

    Returns ``{symbol: path}`` for every symbol that came back non-empty.
    Raises :class:`OpenDUnavailable` if the SDK/gateway is missing.
    """
    vendor_fetcher = _install_daily_timeframe()
    fetcher = vendor_fetcher.MoomooFetcher(host=host, port=port)
    frames = fetcher.fetch_all(symbols, "1d", start, end)  # uses the new "1d" key

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for symbol, df in frames.items():
        # vendored fetcher yields [time, open, high, low, close, volume];
        # ParquetDailyBarSource accepts "time" as an alias for "date".
        out = df.rename(columns={"time": "date"})
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        path = data_dir / f"{symbol.upper()}_1d.parquet"
        out.to_parquet(path, index=False)
        written[symbol.upper()] = str(path)
    return written

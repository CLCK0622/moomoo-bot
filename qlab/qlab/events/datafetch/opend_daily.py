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

import sys
import time
from pathlib import Path
from typing import List

import pandas as pd

# Vendored qstrat lives at <project>/vendor/qstrat and is imported by its
# in-tree names (``data.fetcher``, ``config`` …) with that dir on sys.path —
# the exact idiom qlab/runner.py and qlab/signals.py use to run it verbatim.
_VENDOR_QSTRAT = Path(__file__).resolve().parents[3] / "vendor" / "qstrat"


class OpenDUnavailable(RuntimeError):
    """Raised when the moomoo SDK / OpenD gateway is not importable here."""


def _install_daily_timeframe():
    """Add ``"1d": KLType.K_DAY`` to the vendored map without touching the file."""
    if str(_VENDOR_QSTRAT) not in sys.path:
        sys.path.insert(0, str(_VENDOR_QSTRAT))
    try:
        from moomoo import KLType  # noqa: F401
        import data.fetcher as _vendor_fetcher  # noqa: E402 (vendored, verbatim)
    except Exception as exc:  # noqa: BLE001
        raise OpenDUnavailable(
            "moomoo SDK / OpenD gateway not available. Install moomoo-api "
            "(provides `import moomoo`) matching your OpenD version and run on a "
            f"host with a reachable OpenD gateway. vendored path: {_VENDOR_QSTRAT} "
            f"(exists={_VENDOR_QSTRAT.exists()}). Underlying error: {exc!r}"
        ) from exc
    # outer override — the vendored source stays byte-for-byte unchanged
    _vendor_fetcher.TIMEFRAME_MAP.setdefault("1d", KLType.K_DAY)
    return _vendor_fetcher


def fetch_daily_parquet(symbols: List[str], start: str, end: str,
                        data_dir="data/daily", host: str = "127.0.0.1",
                        port: int = 11111, pause: float = 1.0) -> dict:
    """Fetch qfq-adjusted daily bars via OpenD and persist ``<symbol>_1d.parquet``.

    Pulls **one symbol at a time** and is resilient per symbol so a single bad
    ticker (no data / rate-limit / permission) does not abort the batch — the
    30-day historical-K quota is counted by distinct symbol, so this makes a
    single one-shot pass and never retries a symbol. The vendored ``fetch_kline``
    uses ``request_history_kline`` with the SDK default ``autype='qfq'``
    (forward-adjusted = split+dividend), and opens ONLY ``OpenQuoteContext`` —
    no trade context, no unlock, no order. Nothing here mutates the gateway.

    Returns ``{"written": {sym: {path, rows}}, "failed": {sym: reason}}``.
    Raises :class:`OpenDUnavailable` if the SDK/gateway is missing.
    """
    vendor_fetcher = _install_daily_timeframe()
    fetcher = vendor_fetcher.MoomooFetcher(host=host, port=port)

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    written, failed = {}, {}
    for symbol in symbols:
        sym = symbol.upper()
        try:
            df = fetcher.fetch_kline(symbol, "1d", start, end)  # "1d" -> K_DAY, qfq
        except Exception as exc:  # noqa: BLE001 — record, keep the batch going
            failed[sym] = f"fetch error: {exc}"
            time.sleep(pause)
            continue
        if df is None or df.empty:
            failed[sym] = "no bars returned (no data / rate-limit / permission)"
            time.sleep(pause)
            continue
        # vendored fetcher yields [time, open, high, low, close, volume];
        # ParquetDailyBarSource accepts "time" as an alias for "date".
        out = df.rename(columns={"time": "date"})
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        path = data_dir / f"{sym}_1d.parquet"
        out.to_parquet(path, index=False)
        written[sym] = {"path": str(path), "rows": int(len(out))}
        time.sleep(pause)
    return {"written": written, "failed": failed}

from __future__ import annotations

import pandas as pd
import time as _time
from moomoo import OpenQuoteContext, KLType, SubType


TIMEFRAME_MAP = {
    "1m": KLType.K_1M,
    "15m": KLType.K_15M,
}


class MoomooFetcher:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host = host
        self.port = port

    def fetch_kline(
        self, symbol: str, timeframe: str, start: str, end: str
    ) -> pd.DataFrame:
        kl_type = TIMEFRAME_MAP[timeframe]
        code = f"US.{symbol}"
        all_chunks = []

        ctx = OpenQuoteContext(host=self.host, port=self.port)
        try:
            page_req_key = None
            while True:
                if page_req_key is None:
                    ret, data, page_req_key = ctx.request_history_kline(
                        code, start=start, end=end, ktype=kl_type, max_count=1000
                    )
                else:
                    ret, data, page_req_key = ctx.request_history_kline(
                        code, start=start, end=end, ktype=kl_type, max_count=1000,
                        page_req_key=page_req_key
                    )

                if ret != 0 or data is None or data.empty:
                    break

                all_chunks.append(data)

                if page_req_key is None:
                    break

                _time.sleep(0.3)

            if not all_chunks:
                return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

            combined = pd.concat(all_chunks, ignore_index=True)
            combined = combined.rename(columns={"time_key": "time"})
            combined["time"] = pd.to_datetime(combined["time"])
            combined = combined.drop_duplicates(subset=["time"]).sort_values("time")
            return combined[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        finally:
            ctx.close()

    def fetch_all(
        self, symbols: list[str], timeframe: str, start: str, end: str
    ) -> dict[str, pd.DataFrame]:
        results = {}
        for symbol in symbols:
            df = self.fetch_kline(symbol, timeframe, start, end)
            if not df.empty:
                results[symbol] = df
            _time.sleep(1.0)
        return results

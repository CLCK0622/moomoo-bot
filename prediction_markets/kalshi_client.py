"""
Kalshi 只读 REST 客户端。

行情 GET 端点（markets / orderbook / trades / events / series）为公开端点，
无需鉴权 —— 已实测无凭证 HTTP 200。本客户端只暴露读取方法，不含任何写路径。

字段口径：新版 API 使用 *_dollars（字符串小数，如 "0.4500"）与 *_fp（定点字符串）；
旧版整数分字段（yes_bid 等）在部分品种返回 null，此处做双口径兼容解析。
"""
import time
import logging
import requests
from typing import List, Dict, Any, Optional

from . import config
from .models import Quote

log = logging.getLogger("pm.kalshi")


def _to_price(m: Dict[str, Any], dollars_key: str, cents_key: str) -> Optional[float]:
    """把 *_dollars（字符串美元）或旧版 *（整数分）解析为 0~1 美元价。"""
    v = m.get(dollars_key)
    if v not in (None, ""):
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    c = m.get(cents_key)
    if c not in (None, ""):
        try:
            return float(c) / 100.0
        except (TypeError, ValueError):
            pass
    return None


def _to_float(m: Dict[str, Any], *keys) -> Optional[float]:
    for k in keys:
        v = m.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _iso_to_ts(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


class KalshiClient:
    def __init__(self, base_url: str = None, session: requests.Session = None,
                 timeout: int = config.HTTP_TIMEOUT):
        self.base = (base_url or config.KALSHI_REST_PROD).rstrip("/")
        self.timeout = timeout
        self.s = session or requests.Session()
        self.s.headers.update({"Accept": "application/json",
                               "User-Agent": "moomoo-bot-pm-readonly/1.0"})

    def _get(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        r = self.s.get(url, params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---------- 原始只读端点 ----------
    def get_markets(self, limit: int = 100, status: str = "open",
                    series_ticker: str = None, event_ticker: str = None,
                    cursor: str = None) -> Dict[str, Any]:
        params = {"limit": limit}
        if status:
            params["status"] = status
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params)

    def iter_markets(self, status: str = "open", page: int = 200,
                     max_pages: int = 50, **kw) -> List[Dict[str, Any]]:
        """翻页拉取所有 markets（读取，带上限保护）。"""
        out, cursor, pages = [], None, 0
        while pages < max_pages:
            d = self.get_markets(limit=page, status=status, cursor=cursor, **kw)
            out.extend(d.get("markets", []))
            cursor = d.get("cursor")
            pages += 1
            if not cursor:
                break
        return out

    def get_market(self, ticker: str) -> Dict[str, Any]:
        return self._get(f"/markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker: str, depth: int = 10) -> Dict[str, Any]:
        return self._get(f"/markets/{ticker}/orderbook", {"depth": depth}).get("orderbook", {})

    def get_trades(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self._get("/markets/trades", {"ticker": ticker, "limit": limit}).get("trades", [])

    def get_events(self, limit: int = 100, status: str = "open",
                   cursor: str = None) -> Dict[str, Any]:
        params = {"limit": limit, "status": status}
        if cursor:
            params["cursor"] = cursor
        return self._get("/events", params)

    def exchange_status(self) -> Dict[str, Any]:
        return self._get("/exchange/status")

    # ---------- 归一化 ----------
    @staticmethod
    def to_quote(m: Dict[str, Any]) -> Quote:
        return Quote(
            venue="kalshi",
            market_id=m.get("ticker", ""),
            title=m.get("title", "") or m.get("yes_sub_title", ""),
            cost_yes=_to_price(m, "yes_ask_dollars", "yes_ask"),
            cost_no=_to_price(m, "no_ask_dollars", "no_ask"),
            yes_bid=_to_price(m, "yes_bid_dollars", "yes_bid"),
            no_bid=_to_price(m, "no_bid_dollars", "no_bid"),
            last=_to_price(m, "last_price_dollars", "last_price"),
            volume=_to_float(m, "volume_fp", "volume"),
            liquidity=_to_float(m, "liquidity_dollars", "liquidity"),
            expiration_ts=_iso_to_ts(m.get("expiration_time") or m.get("close_time")),
            event_key=m.get("event_ticker"),
            raw=m,
            ts=time.time(),
        )

    def quotes(self, status: str = "open", **kw) -> List[Quote]:
        return [self.to_quote(m) for m in self.iter_markets(status=status, **kw)]

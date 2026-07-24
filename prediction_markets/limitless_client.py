"""
Limitless Exchange 只读客户端（公开 REST）。

/markets/active -> {data: [ {id, slug, title, conditionId, expirationTimestamp,
  tokens{yes,no}, prices:[yes,no], tradeType(clob|amm), collateralToken(USDC), ...} ]}

注意口径：`prices` 为 AMM/参考概率价（0~1），不必然等于即时可成交 ask。
对 AMM 品种，买入会有价格冲击；对 CLOB 品种，精确 ask 需订单簿。
本客户端把 prices 作为参考价填入 cost_yes/cost_no，并在 raw 标注 price_is_reference，
回测/监控侧据此对可执行性打折或标注。仅读取，无写路径。
"""
import time
import logging
import requests
from typing import List, Dict, Any, Optional

from . import config
from .models import Quote

log = logging.getLogger("pm.limitless")


def _ts(v) -> Optional[int]:
    if v in (None, ""):
        return None
    try:
        n = float(v)
        return int(n / 1000) if n > 1e12 else int(n)   # 兼容毫秒/秒
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


class LimitlessClient:
    def __init__(self, base: str = None, session: requests.Session = None,
                 timeout: int = config.HTTP_TIMEOUT):
        self.base = (base or config.LIMITLESS_API).rstrip("/")
        self.timeout = timeout
        self.s = session or requests.Session()
        self.s.headers.update({"Accept": "application/json",
                               "User-Agent": "moomoo-bot-pm-readonly/1.0"})

    def _get(self, path: str, params: Dict[str, Any] = None) -> Any:
        r = self.s.get(f"{self.base}{path}", params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # Limitless 服务端限制 limit <= 25
    MAX_LIMIT = 25

    def get_active(self, limit: int = 25, page: int = 1) -> List[Dict[str, Any]]:
        limit = min(limit, self.MAX_LIMIT)
        d = self._get("/markets/active", {"limit": limit, "page": page})
        if isinstance(d, dict):
            return d.get("data", d.get("markets", []))
        return d if isinstance(d, list) else []

    def iter_active(self, page_size: int = 25, max_pages: int = 20) -> List[Dict[str, Any]]:
        out = []
        for p in range(1, max_pages + 1):
            batch = self.get_active(limit=page_size, page=p)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < page_size:
                break
        return out

    @staticmethod
    def to_quote(m: Dict[str, Any]) -> Quote:
        prices = m.get("prices") or []
        yes_p = _f(prices[0]) if len(prices) >= 1 else None
        no_p = _f(prices[1]) if len(prices) >= 2 else None
        # Limitless prices 有时以百分数（0~100）给出；>1 则归一到 0~1
        if yes_p is not None and yes_p > 1.5:
            yes_p = yes_p / 100.0
        if no_p is not None and no_p > 1.5:
            no_p = no_p / 100.0
        return Quote(
            venue="limitless",
            market_id=str(m.get("conditionId") or m.get("id") or m.get("slug") or ""),
            title=m.get("title", "") or m.get("proxyTitle", ""),
            cost_yes=yes_p,       # 参考价，可执行性见 raw.price_is_reference
            cost_no=no_p,
            yes_bid=yes_p,
            no_bid=no_p,
            last=yes_p,
            volume=_f(m.get("volumeFormatted") or m.get("volume")),
            liquidity=_f(m.get("liquidityFormatted") or m.get("liquidity")),
            expiration_ts=_ts(m.get("expirationTimestamp")),
            event_key=str(m.get("conditionId") or m.get("groupId") or ""),
            raw={"slug": m.get("slug"), "tradeType": m.get("tradeType"),
                 "price_is_reference": True},
            ts=time.time(),
        )

    def quotes(self, **kw) -> List[Quote]:
        return [self.to_quote(m) for m in self.iter_active(**kw)]

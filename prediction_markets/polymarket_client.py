"""
Polymarket 只读客户端（Gamma 元数据 + CLOB 订单簿，均公开无鉴权）。

- Gamma /markets：question / conditionId / outcomes / outcomePrices / clobTokenIds /
  bestBid / bestAsk / lastTradePrice / volume / liquidity / endDate。
- CLOB /book?token_id=：bids/asks（{price,size} 列表）。best_bid = 最高 bid，
  best_ask = 最低 ask（不依赖返回排序，取极值更稳）。

价格 0~1（USDC，$1 结算）。仅读取，无写路径。
"""
import json
import time
import logging
import requests
from typing import List, Dict, Any, Optional, Tuple

from . import config
from .models import Quote

log = logging.getLogger("pm.polymarket")


def _parse_json_list(v):
    """Gamma 把 outcomes / clobTokenIds 存成 JSON 字符串。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return []
    return []


def _iso_to_ts(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


class PolymarketClient:
    def __init__(self, gamma: str = None, clob: str = None,
                 session: requests.Session = None, timeout: int = config.HTTP_TIMEOUT):
        self.gamma = (gamma or config.POLY_GAMMA).rstrip("/")
        self.clob = (clob or config.POLY_CLOB).rstrip("/")
        self.timeout = timeout
        self.s = session or requests.Session()
        self.s.headers.update({"Accept": "application/json",
                               "User-Agent": "moomoo-bot-pm-readonly/1.0"})

    def _get(self, base: str, path: str, params: Dict[str, Any] = None) -> Any:
        r = self.s.get(f"{base}{path}", params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---------- 只读端点 ----------
    def get_markets(self, limit: int = 100, active: bool = True, closed: bool = False,
                    order: str = "volume", ascending: bool = False,
                    offset: int = 0) -> List[Dict[str, Any]]:
        params = {"limit": limit, "active": str(active).lower(),
                  "closed": str(closed).lower(), "order": order,
                  "ascending": str(ascending).lower(), "offset": offset}
        d = self._get(self.gamma, "/markets", params)
        return d if isinstance(d, list) else d.get("data", d.get("markets", []))

    def get_book(self, token_id: str) -> Dict[str, Any]:
        return self._get(self.clob, "/book", {"token_id": token_id})

    @staticmethod
    def best_of_book(book: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """返回 (best_bid, best_ask)。取极值，避免依赖返回排序。"""
        def px(levels, fn):
            vals = []
            for lv in levels or []:
                try:
                    vals.append(float(lv.get("price")))
                except (TypeError, ValueError):
                    continue
            return fn(vals) if vals else None
        best_bid = px(book.get("bids"), max)
        best_ask = px(book.get("asks"), min)
        return best_bid, best_ask

    # ---------- 归一化 ----------
    def to_quote(self, m: Dict[str, Any], fetch_book: bool = False) -> Quote:
        outcomes = _parse_json_list(m.get("outcomes"))
        prices = _parse_json_list(m.get("outcomePrices"))
        token_ids = _parse_json_list(m.get("clobTokenIds"))

        cost_yes = cost_no = yes_bid = no_bid = None
        # Gamma 顶层 bestBid/bestAsk 针对 YES token
        try:
            yes_bid = float(m["bestBid"]) if m.get("bestBid") is not None else None
        except (TypeError, ValueError):
            yes_bid = None
        try:
            cost_yes = float(m["bestAsk"]) if m.get("bestAsk") is not None else None
        except (TypeError, ValueError):
            cost_yes = None

        # NO 腿：优先取 NO token 订单簿；否则用 1 - yes_bid 近似（标注）
        note_no_derived = False
        if fetch_book and len(token_ids) >= 2:
            try:
                no_bid_v, no_ask_v = self.best_of_book(self.get_book(token_ids[1]))
                no_bid, cost_no = no_bid_v, no_ask_v
                if fetch_book and len(token_ids) >= 1:
                    yb, ya = self.best_of_book(self.get_book(token_ids[0]))
                    if yb is not None:
                        yes_bid = yb
                    if ya is not None:
                        cost_yes = ya
            except Exception as e:  # 订单簿抓取失败则退回近似
                log.debug("poly book fetch failed: %s", e)
        if cost_no is None and yes_bid is not None:
            cost_no = round(1.0 - yes_bid, 6)   # 近似：NO ask ≈ 1 - YES bid
            note_no_derived = True

        last = None
        try:
            last = float(m["lastTradePrice"]) if m.get("lastTradePrice") is not None else None
        except (TypeError, ValueError):
            last = None
        # 若 outcomePrices 存在且未取到 last，用 YES 概率兜底
        if last is None and prices:
            try:
                last = float(prices[0])
            except (TypeError, ValueError):
                pass

        q = Quote(
            venue="polymarket",
            market_id=m.get("conditionId") or m.get("slug") or "",
            title=m.get("question", "") or m.get("slug", ""),
            cost_yes=cost_yes,
            cost_no=cost_no,
            yes_bid=yes_bid,
            no_bid=no_bid,
            last=last,
            volume=_f(m.get("volume")),
            liquidity=_f(m.get("liquidity")),
            expiration_ts=_iso_to_ts(m.get("endDate")),
            event_key=m.get("conditionId"),
            raw={"outcomes": outcomes, "token_ids": token_ids, "slug": m.get("slug")},
            ts=time.time(),
        )
        if note_no_derived:
            q.raw["no_derived_from_yes_bid"] = True
        return q

    def quotes(self, limit: int = 100, fetch_book: bool = False, **kw) -> List[Quote]:
        return [self.to_quote(m, fetch_book=fetch_book)
                for m in self.get_markets(limit=limit, **kw)]


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None

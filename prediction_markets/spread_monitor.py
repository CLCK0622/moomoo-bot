"""
三家 venue 只读价差监测：拉取 -> 对齐 -> 计算跨 venue 套利净边。

pull_all() 用公开 REST 拉真实行情（Kalshi 生产/ Polymarket / Limitless 全公开，
无需任何账户或 KYC）。评估分两层：
  1) curated_pairs.json 中人工确认的同事件配对 -> 计算净边（可信）；
  2) 自动候选建议（event_matcher.suggest_pairs）-> 仅供发现，不作数。
"""
import time
import logging
from typing import Dict, List, Tuple, Optional, Any

from . import config
from .models import Quote, ArbEdge
from .kalshi_client import KalshiClient
from .polymarket_client import PolymarketClient
from .limitless_client import LimitlessClient
from . import event_matcher
from . import arb

log = logging.getLogger("pm.monitor")


def pull_all(kalshi_limit_pages: int = 3, poly_limit: int = 200,
             limitless_pages: int = 3, fetch_poly_books: bool = False) -> Dict[str, List[Quote]]:
    """从三家公开 REST 拉取行情快照。任一 venue 失败不影响其他（降级）。"""
    out: Dict[str, List[Quote]] = {"kalshi": [], "polymarket": [], "limitless": []}
    try:
        out["kalshi"] = KalshiClient().quotes(status="open") if kalshi_limit_pages else []
    except Exception as e:
        log.warning("Kalshi 拉取失败: %s", e)
    try:
        out["polymarket"] = PolymarketClient().quotes(limit=poly_limit, fetch_book=fetch_poly_books)
    except Exception as e:
        log.warning("Polymarket 拉取失败: %s", e)
    try:
        out["limitless"] = LimitlessClient().quotes(page_size=100, max_pages=limitless_pages)
    except Exception as e:
        log.warning("Limitless 拉取失败: %s", e)
    return out


def index_quotes(quotes_by_venue: Dict[str, List[Quote]]) -> Dict[Tuple[str, str], Quote]:
    idx = {}
    for venue, qs in quotes_by_venue.items():
        for q in qs:
            idx[(venue, str(q.market_id))] = q
    return idx


def evaluate_curated(quotes_by_venue: Dict[str, List[Quote]],
                     pairs: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """对人工确认配对计算净边。返回结构化结果（含缺失诊断）。"""
    pairs = pairs if pairs is not None else event_matcher.load_curated_pairs()
    idx = index_quotes(quotes_by_venue)
    results = []
    for p in pairs:
        qa = idx.get((p["venue_a"], str(p["market_a"])))
        qb = idx.get((p["venue_b"], str(p["market_b"])))
        if qa is None or qb is None:
            results.append({"label": p.get("label", ""), "status": "missing_quote",
                            "have_a": qa is not None, "have_b": qb is not None,
                            "pair": p})
            continue
        edge = arb.best_edge(qa, qb, label=p.get("label", ""))
        if edge is None:
            results.append({"label": p.get("label", ""), "status": "no_price", "pair": p})
            continue
        row = edge.to_dict()
        row["status"] = "ok"
        row["within_venue_a_sum"] = arb.within_venue_book_check(qa)
        row["within_venue_b_sum"] = arb.within_venue_book_check(qb)
        results.append(row)
    return results


def snapshot(quotes_by_venue: Dict[str, List[Quote]] = None) -> Dict[str, Any]:
    """生成一次完整快照（含 venue 计数 + curated 评估 + 自动候选建议）。"""
    if quotes_by_venue is None:
        quotes_by_venue = pull_all()
    counts = {v: len(qs) for v, qs in quotes_by_venue.items()}
    curated = evaluate_curated(quotes_by_venue)
    suggestions = event_matcher.suggest_pairs(quotes_by_venue)
    return {
        "ts": time.time(),
        "venue_counts": counts,
        "curated_edges": curated,
        "auto_suggestions": suggestions[:30],   # 仅取前 30 供人工审阅
        "quotes_by_venue": {v: [q.to_dict() for q in qs] for v, qs in quotes_by_venue.items()},
    }

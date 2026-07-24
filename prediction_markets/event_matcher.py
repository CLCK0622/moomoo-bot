"""
跨 venue「同事件」匹配。

现实警示：跨市场「同事件」极易因**结算标准/结算源/结算窗口**的细微差异而
名同实异（例：BTC 收盘价取 Chainlink vs 取 Coinbase、UTC 04:50 vs 05:00）。
名义价差多数是这种口径错位，而非真套利。因此：

  * 自动匹配（suggest_pairs）只产出**候选建议**，供人工审阅；
  * 真正进入回测的配对必须落到 mappings/curated_pairs.json（人工确认结算等价）。

匹配信号：标题 token Jaccard 相似度 + 结算时间接近度。
"""
import re
import json
import os
import logging
from typing import List, Dict, Any, Tuple, Optional

from . import config
from .models import Quote

log = logging.getLogger("pm.matcher")

_STOP = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "will", "be",
         "is", "are", "by", "and", "or", "vs", "win", "market", "resolve",
         "yes", "no", "than", "up", "down", "this", "that", "2026", "2027"}


def normalize_tokens(title: str) -> set:
    if not title:
        return set()
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in _STOP and len(w) > 1}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def suggest_pairs(quotes_by_venue: Dict[str, List[Quote]],
                  min_jaccard: float = None,
                  max_skew: int = None) -> List[Dict[str, Any]]:
    """跨 venue 两两生成候选同事件配对（仅建议，需人工确认）。"""
    min_jaccard = config.MATCH_TITLE_MIN_JACCARD if min_jaccard is None else min_jaccard
    max_skew = config.MATCH_MAX_RESOLUTION_SKEW_SEC if max_skew is None else max_skew

    venues = list(quotes_by_venue.keys())
    # 预计算 token
    toks = {v: [(q, normalize_tokens(q.title)) for q in quotes_by_venue[v]] for v in venues}

    out = []
    for i in range(len(venues)):
        for j in range(i + 1, len(venues)):
            va, vb = venues[i], venues[j]
            for qa, ta in toks[va]:
                if not ta:
                    continue
                for qb, tb in toks[vb]:
                    sim = jaccard(ta, tb)
                    if sim < min_jaccard:
                        continue
                    skew = None
                    if qa.expiration_ts and qb.expiration_ts:
                        skew = abs(qa.expiration_ts - qb.expiration_ts)
                        if skew > max_skew:
                            continue
                    out.append({
                        "venue_a": va, "market_a": qa.market_id, "title_a": qa.title,
                        "venue_b": vb, "market_b": qb.market_id, "title_b": qb.title,
                        "jaccard": round(sim, 3),
                        "resolution_skew_sec": skew,
                        "confirmed": False,   # 自动建议默认未确认
                    })
    out.sort(key=lambda d: -d["jaccard"])
    return out


def load_curated_pairs(path: str = None) -> List[Dict[str, Any]]:
    """加载人工确认的同事件映射（结算等价已核实）。"""
    path = path or os.path.join(config.MAPPINGS_DIR, "curated_pairs.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pairs", []) if isinstance(data, dict) else data

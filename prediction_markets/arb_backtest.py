"""
纸面套利回测：对采集到的快照时间序列，逐时刻计算各人工确认配对的扣费净边，
统计价差是否**真实可捕获**。

输入：collect_snapshots.py / run_spread_monitor.py --save 落到 data/ 的快照 JSON。
每个快照含 quotes_by_venue（各 venue 的归一化行情列表）。

输出（每个配对）：
  - n_obs               观测次数
  - frac_positive_net   扣费后净边 > 0 的时间占比（真正的机会频率）
  - mean_net / median_net / max_net   净边分布（美元/份）
  - mean_gross          未扣费毛边（对照，看费吃掉多少）
  - capture_est         机会期望捕获（frac_positive * mean_positive_net）
  - fee_sensitivity     Limitless 费率上调后的 frac_positive（稳健性）

同时给出「结算持有期年化」折算：净边是绝对收益，需除以到结算的持有期占比。
"""
import os
import glob
import json
import logging
import statistics
from typing import Dict, List, Any, Optional

from . import config
from .models import Quote
from . import arb, fees, event_matcher

log = logging.getLogger("pm.backtest")


def _quote_from_dict(d: Dict[str, Any]) -> Quote:
    q = Quote(venue=d.get("venue", ""), market_id=str(d.get("market_id", "")),
              title=d.get("title", ""))
    for k in ("cost_yes", "cost_no", "yes_bid", "no_bid", "last", "volume",
              "liquidity", "expiration_ts", "event_key", "ts"):
        setattr(q, k, d.get(k))
    return q


def load_snapshots(data_dir: str = None, pattern: str = "snapshot_*.json") -> List[Dict[str, Any]]:
    data_dir = data_dir or config.DATA_DIR
    files = sorted(glob.glob(os.path.join(data_dir, pattern)))
    snaps = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                snaps.append(json.load(fh))
        except Exception as e:
            log.warning("跳过损坏快照 %s: %s", f, e)
    return snaps


def _index(snap: Dict[str, Any]) -> Dict[str, Dict[str, Quote]]:
    idx: Dict[str, Dict[str, Quote]] = {}
    for venue, qs in snap.get("quotes_by_venue", {}).items():
        idx[venue] = {str(d.get("market_id")): _quote_from_dict(d) for d in qs}
    return idx


def backtest_pair(snaps: List[Dict[str, Any]], pair: Dict[str, Any],
                  limitless_fee_bump: float = 0.0) -> Dict[str, Any]:
    """对单个人工确认配对回测。limitless_fee_bump 用于费率敏感性。"""
    old = config.LIMITLESS_FEE_RATE
    if limitless_fee_bump:
        config.LIMITLESS_FEE_RATE = old + limitless_fee_bump
    try:
        nets, grosses, pos_nets = [], [], []
        for snap in snaps:
            idx = _index(snap)
            qa = idx.get(pair["venue_a"], {}).get(str(pair["market_a"]))
            qb = idx.get(pair["venue_b"], {}).get(str(pair["market_b"]))
            if qa is None or qb is None:
                continue
            edge = arb.best_edge(qa, qb, label=pair.get("label", ""))
            if edge is None:
                continue
            nets.append(edge.net_edge)
            grosses.append(edge.gross_edge)
            if edge.net_edge > 0:
                pos_nets.append(edge.net_edge)
    finally:
        config.LIMITLESS_FEE_RATE = old

    n = len(nets)
    if n == 0:
        return {"label": pair.get("label", ""), "n_obs": 0, "status": "no_data"}
    frac_pos = len(pos_nets) / n
    return {
        "label": pair.get("label", ""),
        "venue_a": pair["venue_a"], "venue_b": pair["venue_b"],
        "n_obs": n,
        "frac_positive_net": round(frac_pos, 4),
        "mean_net": round(statistics.mean(nets), 5),
        "median_net": round(statistics.median(nets), 5),
        "max_net": round(max(nets), 5),
        "mean_gross": round(statistics.mean(grosses), 5),
        "mean_positive_net": round(statistics.mean(pos_nets), 5) if pos_nets else 0.0,
        "capture_est_per_contract": round(frac_pos * (statistics.mean(pos_nets) if pos_nets else 0.0), 5),
        "status": "ok",
    }


def run(data_dir: str = None, pairs: List[Dict[str, Any]] = None,
        fee_sensitivity: List[float] = (0.0, 0.01, 0.02)) -> Dict[str, Any]:
    snaps = load_snapshots(data_dir)
    pairs = pairs if pairs is not None else event_matcher.load_curated_pairs()
    results = []
    for p in pairs:
        base = backtest_pair(snaps, p)
        base["fee_sensitivity"] = {
            f"limitless_+{b:.2f}": backtest_pair(snaps, p, limitless_fee_bump=b).get("frac_positive_net")
            for b in fee_sensitivity
        }
        results.append(base)
    return {"n_snapshots": len(snaps), "n_pairs": len(pairs), "pairs": results}

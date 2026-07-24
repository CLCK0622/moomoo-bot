#!/usr/bin/env python3
"""
CLI：拉取三家 venue 公开行情，打印跨 venue 价差/套利净边报告。

用法：
  python -m prediction_markets.run_spread_monitor            # 拉一次并打印
  python -m prediction_markets.run_spread_monitor --save     # 同时把快照落 data/
  python -m prediction_markets.run_spread_monitor --loop 60 --count 5   # 每 60s 采一次，共 5 次

零凭证、零真金：只走公开 REST，仅读取。
"""
import os
import sys
import json
import time
import argparse
import logging

from . import config, spread_monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pm.run")


def save_snapshot(snap: dict) -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    fn = os.path.join(config.DATA_DIR, f"snapshot_{int(snap['ts'])}.json")
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    return fn


def print_report(snap: dict):
    print("=" * 72)
    print(f"venue 行情计数: {snap['venue_counts']}")
    curated = snap.get("curated_edges", [])
    print(f"\n[人工确认配对净边] {len(curated)} 条")
    if not curated:
        print("  (curated_pairs.json 为空或当前无匹配行情；先用 auto_suggestions 人工确认配对)")
    for r in curated:
        if r.get("status") != "ok":
            print(f"  - {r.get('label','?')}: {r.get('status')}")
            continue
        flag = "★可捕获" if r["capturable"] else "×不可捕获"
        print(f"  - {r['event_label']}: net={r['net_edge']:+.4f} "
              f"(gross={r['gross_edge']:+.4f}, 买YES@{r['buy_yes_venue']}={r['cost_yes']:.3f}, "
              f"买NO@{r['buy_no_venue']}={r['cost_no']:.3f}, 费={r['fee_yes']+r['fee_no']:.4f}) {flag}"
              + (f"  [{r['notes']}]" if r.get("notes") else ""))

    sugg = snap.get("auto_suggestions", [])
    print(f"\n[自动候选建议] {len(sugg)} 条（仅供人工审阅结算等价，不作数）")
    for s in sugg[:10]:
        print(f"  ~ {s['jaccard']:.2f} | {s['venue_a']}:{s['title_a'][:38]}  ⟷  "
              f"{s['venue_b']}:{s['title_b'][:38]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="把快照落 data/（供回测）")
    ap.add_argument("--loop", type=int, default=0, help="循环间隔秒；0=只跑一次")
    ap.add_argument("--count", type=int, default=1, help="循环次数")
    ap.add_argument("--poly-books", action="store_true", help="抓 Polymarket NO 腿订单簿(更准，更慢)")
    args = ap.parse_args(argv)

    n = args.count if args.loop else 1
    for i in range(n):
        quotes = spread_monitor.pull_all(fetch_poly_books=args.poly_books)
        snap = spread_monitor.snapshot(quotes)
        print_report(snap)
        if args.save:
            path = save_snapshot(snap)
            print(f"\n快照已保存: {path}")
        if args.loop and i < n - 1:
            time.sleep(args.loop)
    return 0


if __name__ == "__main__":
    sys.exit(main())

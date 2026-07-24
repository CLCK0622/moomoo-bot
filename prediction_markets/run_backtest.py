#!/usr/bin/env python3
"""
CLI：对 data/ 下采集的快照做纸面套利回测。

用法：
  # 先采集若干快照（例如每 5 分钟一次，跑一段时间）：
  python -m prediction_markets.run_spread_monitor --save --loop 300 --count 288
  # 再回测：
  python -m prediction_markets.run_backtest
"""
import sys
import json
import argparse
import logging

from . import arb_backtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = ap.parse_args(argv)

    res = arb_backtest.run(data_dir=args.data_dir)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    print(f"快照数: {res['n_snapshots']}  配对数: {res['n_pairs']}")
    if res["n_snapshots"] == 0:
        print("无快照数据。先用 run_spread_monitor --save 采集时间序列。")
        return 0
    for p in res["pairs"]:
        if p.get("status") != "ok":
            print(f"- {p.get('label','?')}: {p.get('status')} (n={p.get('n_obs',0)})")
            continue
        print(f"- {p['label']} [{p['venue_a']}⟷{p['venue_b']}]  n={p['n_obs']}")
        print(f"    净边>0占比={p['frac_positive_net']:.1%}  均值净边={p['mean_net']:+.4f}  "
              f"中位={p['median_net']:+.4f}  最大={p['max_net']:+.4f}")
        print(f"    毛边均值={p['mean_gross']:+.4f}  机会期望捕获/份={p['capture_est_per_contract']:+.4f}")
        print(f"    费率敏感性(净边>0占比)={p['fee_sensitivity']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

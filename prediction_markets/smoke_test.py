#!/usr/bin/env python3
"""
在线冒烟测试：验证三家 venue 公开只读 REST 可拉到真实行情（零凭证、零真金）。
用法: python -m prediction_markets.smoke_test
"""
import sys
import logging
from . import config
from .kalshi_client import KalshiClient
from .polymarket_client import PolymarketClient
from .limitless_client import LimitlessClient

logging.basicConfig(level=logging.WARNING)


def main():
    ok = True

    # Kalshi 生产公开行情
    try:
        k = KalshiClient()
        st = k.exchange_status()
        d = k.get_markets(limit=50, status="open")
        ms = d.get("markets", [])
        priced = [m for m in ms if (m.get("yes_ask_dollars") not in (None, "", "0.0000"))]
        print(f"[Kalshi] exchange_active={st.get('exchange_active')} 拉到 {len(ms)} 市场, "
              f"其中有 YES ask 报价 {len(priced)}")
        if ms:
            q = k.to_quote(ms[0])
            print(f"         样例 {q.market_id}: cost_yes={q.cost_yes} cost_no={q.cost_no}")
        assert st.get("exchange_active") is not None and len(ms) > 0
    except Exception as e:
        ok = False
        print(f"[Kalshi] 失败: {e}")

    # Polymarket 公开行情
    try:
        p = PolymarketClient()
        qs = p.quotes(limit=20)
        print(f"[Polymarket] 拉到 {len(qs)} 市场; 样例 {qs[0].title[:40]!r} "
              f"cost_yes={qs[0].cost_yes} cost_no={qs[0].cost_no}")
        assert len(qs) > 0
    except Exception as e:
        ok = False
        print(f"[Polymarket] 失败: {e}")

    # Limitless 公开行情
    try:
        lm = LimitlessClient()
        qs = lm.quotes(page_size=50, max_pages=1)
        print(f"[Limitless] 拉到 {len(qs)} 市场; 样例 {qs[0].title[:40]!r} "
              f"cost_yes={qs[0].cost_yes} cost_no={qs[0].cost_no}")
        assert len(qs) > 0
    except Exception as e:
        ok = False
        print(f"[Limitless] 失败: {e}")

    print("\n冒烟结果:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""
prediction_markets —— 预测市场（Kalshi / Polymarket / Limitless）只读数据接入与
跨 venue 价差监测 / 纸面套利回测。

只读基线（对齐 quant SIMULATE-only）：本包不含任何下单 / 入金 / 提现 / 撤单路径；
Kalshi WS 的 RSA-PSS 鉴权会话仅用于订阅公开行情频道。
"""
__all__ = [
    "config", "models", "fees", "kalshi_auth", "kalshi_client", "kalshi_ws",
    "polymarket_client", "limitless_client", "event_matcher", "arb",
    "spread_monitor", "arb_backtest",
]

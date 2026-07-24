"""
各 venue 手续费 / 结算模型。

回测净额口径：赢方到期按 $1 结算，Kalshi/Polymarket 无单独结算费，
交易费在成交时一次性计入 —— 故「持有 YES+NO 到期得 $1」的组合，
每份净利 = 1 - cost_yes - cost_no - fee(cost_yes) - fee(cost_no)。
"""
import math
from . import config


def _ceil_cent(x: float) -> float:
    """向上取整到分（美元）。"""
    return math.ceil(round(x, 10) * 100) / 100.0


def kalshi_fee(price: float, contracts: int = 1, rate: float = None, taker: bool = True) -> float:
    """Kalshi 交易费（美元）。

    官方通用公式：fee = ceil_to_cent( rate * C * P * (1-P) )。
    maker 多数品种免费；此处默认按 taker 计（保守）。
    """
    if price is None:
        return 0.0
    p = max(0.0, min(1.0, float(price)))
    if not taker:
        r = config.KALSHI_MAKER_FEE_RATE
        if r <= 0:
            return 0.0
    else:
        r = config.KALSHI_FEE_RATE if rate is None else rate
    return _ceil_cent(r * contracts * p * (1.0 - p))


def polymarket_fee(price: float, contracts: int = 1, taker: bool = True) -> float:
    """Polymarket 交易费（美元）。当前 CLOB 零费；保留可配置。"""
    r = config.POLY_TAKER_FEE_RATE if taker else config.POLY_MAKER_FEE_RATE
    if r <= 0:
        return 0.0
    p = max(0.0, min(1.0, float(price)))
    return r * contracts * p


def limitless_fee(price: float, contracts: int = 1) -> float:
    """Limitless 交易费（美元）。费率未官方核实，占位可配置，回测时做敏感性分析。"""
    r = config.LIMITLESS_FEE_RATE
    if r <= 0:
        return 0.0
    p = max(0.0, min(1.0, float(price)))
    return r * contracts * p


# venue -> 费用函数（按买入价计一腿的费）
FEE_FN = {
    "kalshi": lambda price, contracts=1: kalshi_fee(price, contracts, taker=True),
    "polymarket": lambda price, contracts=1: polymarket_fee(price, contracts, taker=True),
    "limitless": lambda price, contracts=1: limitless_fee(price, contracts),
}


def leg_fee(venue: str, price: float, contracts: int = 1) -> float:
    fn = FEE_FN.get(venue)
    if fn is None:
        # 未知 venue 保守按 Kalshi 档估费
        return kalshi_fee(price, contracts)
    return fn(price, contracts)

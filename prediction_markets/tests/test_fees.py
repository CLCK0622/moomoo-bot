"""手续费模型：Kalshi 通用公式 ceil_to_cent(0.07*P*(1-P))；Polymarket 零费。"""
from prediction_markets import fees, config


def test_kalshi_fee_midprice():
    # P=0.5: 0.07*0.25=0.0175 -> 向上取整到分 = 0.02
    assert fees.kalshi_fee(0.50) == 0.02


def test_kalshi_fee_extremes():
    assert fees.kalshi_fee(0.0) == 0.0            # 0*(1-0)=0
    assert fees.kalshi_fee(1.0) == 0.0            # 1*(1-1)=0
    # P=0.9: 0.07*0.09=0.0063 -> ceil 0.01
    assert fees.kalshi_fee(0.90) == 0.01
    # P=0.99: 0.07*0.0099=0.000693 -> ceil 0.01（向上取整到分）
    assert fees.kalshi_fee(0.99) == 0.01


def test_kalshi_fee_scales_with_contracts():
    one = fees.kalshi_fee(0.50, contracts=1)
    many = fees.kalshi_fee(0.50, contracts=100)
    assert many > one


def test_polymarket_zero_fee_default():
    assert fees.polymarket_fee(0.5) == 0.0


def test_leg_fee_dispatch():
    assert fees.leg_fee("kalshi", 0.5) == fees.kalshi_fee(0.5)
    assert fees.leg_fee("polymarket", 0.5) == 0.0
    # 未知 venue 保守按 kalshi
    assert fees.leg_fee("unknown", 0.5) == fees.kalshi_fee(0.5)


def test_limitless_fee_configurable():
    old = config.LIMITLESS_FEE_RATE
    try:
        config.LIMITLESS_FEE_RATE = 0.02
        assert fees.limitless_fee(0.5) == 0.01   # 0.02*0.5
    finally:
        config.LIMITLESS_FEE_RATE = old


TESTS = [test_kalshi_fee_midprice, test_kalshi_fee_extremes, test_kalshi_fee_scales_with_contracts,
         test_polymarket_zero_fee_default, test_leg_fee_dispatch, test_limitless_fee_configurable]

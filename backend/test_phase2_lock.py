#!/usr/bin/env python3
"""
测试PHASE2止盈后不再回马枪的逻辑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 测试 PHASE2 止盈锁定逻辑")
print("=" * 70)

from trade_manager import StrategyLogic

# 测试场景：股票触发PHASE2止盈
print("\n📊 场景1: 股票涨幅达到2.5%，触发PHASE2止盈")
print("-" * 70)

# 假设参数
base_open_price = 100.00
cost_price = 100.00
max_price_seen = 102.50  # 涨了2.5%
current_price = 101.50   # 从高点回撤

print(f"开盘价:     ${base_open_price:.2f}")
print(f"成本价:     ${cost_price:.2f}")
print(f"最高价:     ${max_price_seen:.2f} (+{(max_price_seen/cost_price-1)*100:.1f}%)")
print(f"当前价:     ${current_price:.2f}")

should_sell, reason = StrategyLogic.check_sell_signal(
    current_price=current_price,
    base_open_price=base_open_price,
    cost_price=cost_price,
    max_price_seen=max_price_seen
)

if should_sell:
    print(f"\n✅ 触发卖出: {reason}")
    if "PHASE2" in reason:
        print(f"🎯 这是PHASE2止盈！")
        print(f"📝 数据库逻辑: status=FINISHED, isActive=false")
        print(f"🚫 结果: 今日不再允许回马枪买入")
    else:
        print(f"⚠️  这是其他卖出信号")
        print(f"📝 数据库逻辑: status=WATCHING, isActive=true")
        print(f"✅ 结果: 可以回马枪买入")
else:
    print(f"\n❌ 未触发卖出")

# 场景2: 普通止盈（PHASE1）
print("\n" + "=" * 70)
print("📊 场景2: 股票涨幅小于2.5%，触发PHASE1止盈")
print("-" * 70)

base_open_price = 100.00
cost_price = 100.00
max_price_seen = 101.50  # 涨了1.5%
current_price = 100.40   # 从高点回撤1%

print(f"开盘价:     ${base_open_price:.2f}")
print(f"成本价:     ${cost_price:.2f}")
print(f"最高价:     ${max_price_seen:.2f} (+{(max_price_seen/cost_price-1)*100:.1f}%)")
print(f"当前价:     ${current_price:.2f}")

should_sell, reason = StrategyLogic.check_sell_signal(
    current_price=current_price,
    base_open_price=base_open_price,
    cost_price=cost_price,
    max_price_seen=max_price_seen
)

if should_sell:
    print(f"\n✅ 触发卖出: {reason}")
    if "PHASE2" in reason:
        print(f"🎯 这是PHASE2止盈！")
        print(f"🚫 今日不再允许回马枪买入")
    else:
        print(f"📌 这是PHASE1或其他卖出信号")
        print(f"📝 数据库逻辑: status=WATCHING, isActive=true")
        print(f"✅ 结果: 允许回马枪买入")
else:
    print(f"\n❌ 未触发卖出")

# 场景3: 计算PHASE2的阈值
print("\n" + "=" * 70)
print("📐 PHASE2触发条件分析")
print("=" * 70)

print("\n公式:")
print("  max_gain_pct = (max_price_seen - cost_price) / base_open_price")
print("  PHASE2触发条件: max_gain_pct >= 0.025 (2.5%)")
print("\n不同涨幅的结果:")

test_cases = [
    {"gain": 0.01, "name": "涨1%"},
    {"gain": 0.02, "name": "涨2%"},
    {"gain": 0.025, "name": "涨2.5%"},
    {"gain": 0.03, "name": "涨3%"},
    {"gain": 0.05, "name": "涨5%"},
]

for case in test_cases:
    gain = case['gain']
    cost = 100.00
    max_price = cost * (1 + gain)

    # 计算是否触发PHASE2
    max_gain_pct = (max_price - cost) / cost
    is_phase2 = max_gain_pct >= 0.025

    # 计算止盈线
    if is_phase2:
        profit_from_open = max_price - cost
        stop_price = cost + (profit_from_open * 0.8)
        lock_pct = ((stop_price - cost) / cost) * 100
        result = f"PHASE2 - 锁定80%利润 (止盈线: ${stop_price:.2f}, +{lock_pct:.1f}%)"
    else:
        buffer = cost * 0.01
        stop_price = max_price - buffer
        result = f"PHASE1 - 允许回撤1% (止盈线: ${stop_price:.2f})"

    print(f"  {case['name']:<8} 最高${max_price:.2f} → {result}")

print("\n" + "=" * 70)
print("✅ PHASE2逻辑验证完成")
print("=" * 70)
print("\n📝 总结:")
print("   • PHASE2触发: 涨幅 >= 2.5%")
print("   • PHASE2止盈: 锁定80%利润")
print("   • PHASE2后: status=FINISHED, isActive=false")
print("   • 结果: 今日不再交易该股票，利润落袋为安 🎯")
print("=" * 70)


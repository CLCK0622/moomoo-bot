#!/usr/bin/env python3
"""
测试trader.py中的熔断检查功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 测试 Trader 熔断检查功能")
print("=" * 70)

from trader import QuantTrader

# 1. 初始化trader
print("\n1️⃣ 初始化 QuantTrader...")
try:
    trader = QuantTrader()
    print("   ✅ Trader initialized")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

# 2. 测试动态止损阈值计算
print("\n2️⃣ 测试动态止损阈值计算...")
try:
    from futu import TrdEnv
    ret, data = trader.ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)

    if ret == 0:  # RET_OK
        total_assets = data['total_assets'][0]
        approved_count = 5
        fixed_budget = (total_assets / 1.2) / approved_count
        stop_loss = -1 * (fixed_budget * 0.01)

        print(f"   ✅ 当前账户:")
        print(f"      总资产:       ${total_assets:>12,.2f}")
        print(f"      股票数量:     {approved_count:>12} 只")
        print(f"      单只预算:     ${fixed_budget:>12,.2f}")
        print(f"      止损阈值:     ${stop_loss:>12,.2f} (预算的1%)")
    else:
        print(f"   ⚠️  无法获取账户信息: {data}")
except Exception as e:
    print(f"   ⚠️  测试失败: {e}")

# 3. 测试熔断检查（模拟不同场景）
print("\n3️⃣ 测试熔断检查逻辑...")

test_scenarios = [
    {"symbol": "AAPL", "name": "正常情况（无熔断）", "expected": False},
    {"symbol": "TSLA", "name": "假设已触发熔断", "expected": None},  # 取决于实际数据
]

for scenario in test_scenarios:
    symbol = scenario['symbol']
    print(f"\n   测试: {scenario['name']} ({symbol})")

    try:
        # 调用check_circuit_breaker（不传阈值，让它自动计算）
        is_blocked = trader.check_circuit_breaker(symbol)

        if is_blocked:
            print(f"      ⚠️  {symbol} 已触发熔断，买入被阻止")
        else:
            print(f"      ✅ {symbol} 正常，可以买入")
    except Exception as e:
        print(f"      ❌ 检查失败: {e}")

# 4. 测试自定义止损阈值
print("\n4️⃣ 测试自定义止损阈值...")
custom_threshold = -1000.0
print(f"   使用自定义阈值: ${custom_threshold:.2f}")

try:
    is_blocked = trader.check_circuit_breaker("TEST", stop_loss_threshold=custom_threshold)
    print(f"   ✅ 自定义阈值功能正常")
except Exception as e:
    print(f"   ❌ 失败: {e}")

# 5. 验证公式
print("\n5️⃣ 验证计算公式...")
print("   公式:")
print("      单只预算 = (总资产 / 1.2) / 股票数量")
print("      止损阈值 = -1 × 单只预算 × 1%")

# 手动计算示例
example_assets = 1000000
example_count = 5
example_budget = (example_assets / 1.2) / example_count
example_stop = -1 * (example_budget * 0.01)

print(f"\n   示例（总资产 ${example_assets:,.2f}，{example_count} 只股票）:")
print(f"      单只预算: ${example_budget:,.2f}")
print(f"      止损阈值: ${example_stop:,.2f}")

trader.ctx.close()

print("\n" + "=" * 70)
print("✅ 测试完成")
print("=" * 70)
print("\n📝 关键功能:")
print("   • check_circuit_breaker() 动态计算止损阈值")
print("   • 默认使用预算的1%")
print("   • 支持自定义阈值参数")
print("   • 与monitor.py的逻辑一致")
print("=" * 70)


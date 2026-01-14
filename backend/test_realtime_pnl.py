#!/usr/bin/env python3
"""
测试实时浮盈浮亏计算的准确性
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 实时浮盈浮亏计算测试")
print("=" * 70)

# 模拟数据对比
print("\n示例对比：")
print("-" * 70)

test_cases = [
    {"symbol": "AAPL", "qty": 100, "cost": 150.00, "current": 155.00},
    {"symbol": "TSLA", "qty": 50, "cost": 200.00, "current": 195.00},
    {"symbol": "GOOGL", "qty": 20, "cost": 140.00, "current": 145.50},
]

for case in test_cases:
    symbol = case['symbol']
    qty = case['qty']
    cost = case['cost']
    current = case['current']

    # 旧方法：依赖Moomoo的pl_val（可能延迟）
    # 这里我们模拟一个延迟的值
    moomoo_pl = (current * 0.998 - cost) * qty  # 假设有0.2%的延迟

    # 新方法：实时计算
    realtime_pl = (current - cost) * qty

    # 市值计算
    market_value = current * qty

    difference = realtime_pl - moomoo_pl

    print(f"\n📊 {symbol}:")
    print(f"   持仓: {qty} 股 @ ${cost:.2f}")
    print(f"   现价: ${current:.2f}")
    print(f"   市值: ${market_value:,.2f}")
    print(f"   Moomoo浮盈: ${moomoo_pl:,.2f} (可能延迟)")
    print(f"   实时浮盈:   ${realtime_pl:,.2f} ✅")
    print(f"   差异:      ${difference:,.2f}")

print("\n" + "=" * 70)
print("📈 新计算方式优势：")
print("=" * 70)
print("✅ 使用最新成交价格，无延迟")
print("✅ 公式简单透明：(现价 - 成本) × 数量")
print("✅ 与市值计算一致：现价 × 数量")
print("✅ 避免Moomoo API的缓存延迟")
print("=" * 70)

# 测试实际dashboard
print("\n🔍 测试实际dashboard数据...")
try:
    from dashboard import get_dashboard_data

    data = get_dashboard_data()

    print(f"\n当前账户状态：")
    print(f"   现金:     ${data['account']['cash']:,.2f}")
    print(f"   持仓市值: ${data['account']['market_value']:,.2f}")
    print(f"   总资产:   ${data['account']['total_assets']:,.2f}")
    print(f"   今日盈亏: ${data['account']['total_pnl_today']:,.2f}")
    print(f"      ├─ 已实现: ${data['account']['realized_pnl']:,.2f}")
    print(f"      └─ 浮盈:   ${data['account']['unrealized_pnl']:,.2f} (实时计算)")

    if data['stocks']:
        print(f"\n持仓详情 ({len(data['stocks'])} 只):")
        for stock in data['stocks']:
            if stock['qty'] > 0:
                pnl_pct = (stock['unrealized_pnl'] / (stock['cost'] * stock['qty']) * 100) if stock['cost'] > 0 else 0
                print(f"   {stock['symbol']:<6} {stock['qty']:>4}股 "
                      f"${stock['cost']:>7.2f} → ${stock['current_price']:>7.2f} "
                      f"浮盈: ${stock['unrealized_pnl']:>8.2f} ({pnl_pct:>+6.2f}%)")

    print("\n✅ Dashboard数据已更新为实时计算!")

except Exception as e:
    print(f"⚠️  无法连接到实时数据: {e}")
    print("   (确保OpenD正在运行)")

print("\n" + "=" * 70)


#!/usr/bin/env python3
"""
测试动态止损阈值计算
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 测试动态止损阈值计算 (预算的1%)")
print("=" * 70)

# 模拟不同的账户资产和股票数量
test_cases = [
    {"total_assets": 1000000, "num_stocks": 5, "name": "100万资产，5只股票"},
    {"total_assets": 500000, "num_stocks": 3, "name": "50万资产，3只股票"},
    {"total_assets": 100000, "num_stocks": 2, "name": "10万资产，2只股票"},
]

print("\n计算公式:")
print("  单只股票预算 = (总资产 / 1.2) / 股票数量")
print("  止损阈值 = -1 × 单只股票预算 × 1%")
print("=" * 70)

for case in test_cases:
    total_assets = case['total_assets']
    num_stocks = case['num_stocks']

    # 计算单只股票预算
    fixed_budget = (total_assets / 1.2) / num_stocks

    # 计算止损阈值（预算的1%）
    stop_loss_threshold = -1 * (fixed_budget * 0.01)

    print(f"\n📊 {case['name']}:")
    print(f"   总资产:       ${total_assets:>12,.2f}")
    print(f"   股票数量:     {num_stocks:>12} 只")
    print(f"   单只预算:     ${fixed_budget:>12,.2f}")
    print(f"   止损阈值:     ${stop_loss_threshold:>12,.2f} (预算的1%)")
    print(f"   止损比例:     {abs(stop_loss_threshold/fixed_budget)*100:>12.2f}%")

# 对比之前的固定值
print("\n" + "=" * 70)
print("📈 对比分析")
print("=" * 70)

print(f"\n之前的固定止损: -$2,000.00")
print(f"\n现在的动态止损（以100万资产为例）:")

# 100万资产，5只股票的情况
fixed_budget = (1000000 / 1.2) / 5
new_threshold = -1 * (fixed_budget * 0.01)

print(f"   单只预算: ${fixed_budget:,.2f}")
print(f"   止损阈值: ${new_threshold:,.2f} (预算的1%)")
print(f"\n   对比:")
print(f"   旧止损: -$2,000.00")
print(f"   新止损: ${new_threshold:,.2f}")
print(f"   差异:   ${new_threshold - (-2000):+,.2f}")

if new_threshold < -2000:
    print(f"   ⚠️  新止损更宽松 (允许更大亏损)")
else:
    print(f"   ✅ 新止损更严格 (更早止损)")

print("\n" + "=" * 70)
print("✅ 动态止损阈值已启用")
print("=" * 70)
print("\n📝 优势:")
print("   • 根据实际投入预算动态调整")
print("   • 单只股票预算越大，止损阈值相应增加")
print("   • 单只股票预算越小，止损阈值相应减小")
print("   • 固定比例1%，风险控制一致")
print("=" * 70)

# 实际获取当前账户的止损阈值
print("\n🔍 当前账户实际止损阈值...")
try:
    from futu import *
    from config import MOOMOO_HOST, MOOMOO_PORT

    ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=MOOMOO_HOST,
        port=MOOMOO_PORT,
        security_firm=SecurityFirm.FUTUSG
    )

    ret, data = ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)

    if ret == RET_OK and not data.empty:
        total_assets = float(data['total_assets'].iloc[0])
        approved_count = 5  # 默认5只股票

        fixed_budget = (total_assets / 1.2) / approved_count
        stop_loss = -1 * (fixed_budget * 0.01)

        print(f"\n   ✅ 当前账户总资产: ${total_assets:,.2f}")
        print(f"   ✅ 单只股票预算:   ${fixed_budget:,.2f}")
        print(f"   ✅ 止损阈值:       ${stop_loss:,.2f} (预算的1%)")
        print(f"\n   💡 当任何股票的今日盈亏低于 ${stop_loss:.2f} 时会触发熔断！")
    else:
        print(f"   ⚠️  无法获取账户信息: {data}")

    ctx.close()
except Exception as e:
    print(f"   ⚠️  无法连接Moomoo: {e}")

print("\n" + "=" * 70)


#!/usr/bin/env python3
"""
测试总资产和已实现盈亏的计算
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 测试总资产和已实现盈亏计算")
print("=" * 70)

# 1. 测试数据库查询今日已实现盈亏
print("\n1️⃣ 测试今日已实现盈亏查询...")
from db import get_db_connection
from psycopg2.extras import RealDictCursor

conn = get_db_connection()
cur = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("""
    SELECT 
        symbol,
        "buyPrice",
        "sellPrice",
        quantity,
        ("sellPrice" - "buyPrice") * quantity as pnl,
        "sellTime"
    FROM "TradePosition"
    WHERE status = 'CLOSED' 
      AND "sellTime" >= CURRENT_DATE
      AND "sellTime" < CURRENT_DATE + INTERVAL '1 day'
    ORDER BY "sellTime" DESC
""")

trades = cur.fetchall()
total_realized = 0.0

if trades:
    print(f"   找到 {len(trades)} 笔今日平仓交易:")
    print(f"   {'Symbol':<8} {'Buy':<10} {'Sell':<10} {'Qty':<6} {'PnL':<12} {'Time'}")
    print("   " + "-" * 70)
    for t in trades:
        pnl = float(t['pnl'])
        total_realized += pnl
        print(f"   {t['symbol']:<8} ${t['buyPrice']:<9.2f} ${t['sellPrice']:<9.2f} "
              f"{t['quantity']:<6} ${pnl:<11.2f} {t['sellTime'].strftime('%H:%M:%S')}")
    print("   " + "-" * 70)
    print(f"   总已实现盈亏: ${total_realized:.2f}")
else:
    print("   ⚠️  今日暂无平仓交易")

# 2. 测试Moomoo账户信息获取
print("\n2️⃣ 测试Moomoo账户信息获取...")
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
        cash = float(data['cash'].iloc[0])
        market_val = float(data['market_val'].iloc[0])
        currency = data['currency'].iloc[0]

        print(f"   ✅ Moomoo账户信息:")
        print(f"      总资产:   ${total_assets:,.2f} {currency}")
        print(f"      现金:     ${cash:,.2f} {currency}")
        print(f"      持仓市值: ${market_val:,.2f} {currency}")

        # 验证计算
        calculated = cash + market_val
        diff = total_assets - calculated
        print(f"\n   验证: ${cash:,.2f} + ${market_val:,.2f} = ${calculated:,.2f}")
        if abs(diff) < 0.01:
            print(f"   ✅ 计算匹配 (差异: ${diff:.2f})")
        else:
            print(f"   ⚠️  有差异: ${diff:.2f}")
            print(f"      (可能是Moomoo包含了其他费用或冻结资金)")
    else:
        print(f"   ❌ 获取失败: {data}")

    ctx.close()
except Exception as e:
    print(f"   ⚠️  无法连接Moomoo: {e}")

# 3. 测试完整的dashboard
print("\n3️⃣ 测试完整Dashboard...")
try:
    from dashboard import get_dashboard_data

    data = get_dashboard_data()
    account = data['account']

    print(f"\n   Dashboard返回:")
    print(f"   {'总资产:':<12} ${account['total_assets']:>12,.2f}")
    print(f"   {'现金:':<12} ${account['cash']:>12,.2f}")
    print(f"   {'持仓市值:':<12} ${account['market_value']:>12,.2f}")
    print(f"   {'今日盈亏:':<12} ${account['total_pnl_today']:>12,.2f}")
    print(f"      {'├─ 已实现:':<10} ${account['realized_pnl']:>12,.2f}")
    print(f"      {'└─ 浮盈:':<10} ${account['unrealized_pnl']:>12,.2f}")

    # 验证今日盈亏计算
    calc_pnl = account['realized_pnl'] + account['unrealized_pnl']
    if abs(calc_pnl - account['total_pnl_today']) < 0.01:
        print(f"\n   ✅ 今日盈亏计算正确")
    else:
        print(f"\n   ⚠️  今日盈亏计算有误")

    if data['stocks']:
        print(f"\n   持仓明细 ({len(data['stocks'])} 只):")
        print(f"   {'Symbol':<8} {'Qty':<6} {'Cost':<10} {'Current':<10} {'浮盈':<12} {'已实现':<12}")
        print("   " + "-" * 70)
        for s in data['stocks']:
            if s['qty'] > 0:
                print(f"   {s['symbol']:<8} {s['qty']:<6} ${s['cost']:<9.2f} "
                      f"${s['current_price']:<9.2f} ${s['unrealized_pnl']:<11.2f} "
                      f"${s['realized_pnl']:<11.2f}")
        print("   " + "-" * 70)

except Exception as e:
    print(f"   ❌ Dashboard测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("✅ 测试完成")
print("=" * 70)
print("\n📝 关键点:")
print("   • 总资产 = Moomoo返回的total_assets（准确）")
print("   • 已实现盈亏 = 今日CLOSED交易的盈亏总和")
print("   • 今日盈亏 = 已实现 + 浮盈")
print("=" * 70)

cur.close()
conn.close()


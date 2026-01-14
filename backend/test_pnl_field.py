#!/usr/bin/env python3
"""
测试TradePosition的pnl字段是否正确填写
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 测试 TradePosition.pnl 字段填写")
print("=" * 70)

from db import get_db_connection
from psycopg2.extras import RealDictCursor

conn = get_db_connection()
cur = conn.cursor(cursor_factory=RealDictCursor)

# 1. 检查今日已平仓的交易
print("\n1️⃣ 检查今日已平仓交易的pnl字段...")
cur.execute("""
    SELECT 
        id,
        symbol,
        "buyPrice",
        "sellPrice",
        quantity,
        pnl,
        ("sellPrice" - "buyPrice") * quantity as calculated_pnl,
        "sellTime",
        "exitReason"
    FROM "TradePosition"
    WHERE status = 'CLOSED' 
      AND "sellTime" >= CURRENT_DATE
    ORDER BY "sellTime" DESC
    LIMIT 10
""")

trades = cur.fetchall()

if trades:
    print(f"\n   找到 {len(trades)} 笔今日平仓交易:")
    print(f"\n   {'ID':<6} {'Symbol':<8} {'Buy':<10} {'Sell':<10} {'Qty':<6} {'PnL(DB)':<12} {'PnL(计算)':<12} {'匹配':<6}")
    print("   " + "-" * 85)

    mismatches = 0
    nulls = 0

    for t in trades:
        pnl_db = float(t['pnl']) if t['pnl'] is not None else None
        pnl_calc = float(t['calculated_pnl'])

        if pnl_db is None:
            status = "❌ NULL"
            nulls += 1
        elif abs(pnl_db - pnl_calc) < 0.01:
            status = "✅"
        else:
            status = "⚠️  不匹配"
            mismatches += 1

        pnl_db_str = f"${pnl_db:.2f}" if pnl_db is not None else "NULL"

        print(f"   {t['id']:<6} {t['symbol']:<8} ${t['buyPrice']:<9.2f} ${t['sellPrice']:<9.2f} "
              f"{t['quantity']:<6} {pnl_db_str:<12} ${pnl_calc:<11.2f} {status}")

    print("   " + "-" * 85)
    print(f"\n   统计:")
    print(f"   ✅ 正确填写: {len(trades) - nulls - mismatches} 笔")
    if nulls > 0:
        print(f"   ❌ NULL: {nulls} 笔")
    if mismatches > 0:
        print(f"   ⚠️  不匹配: {mismatches} 笔")
else:
    print("   ℹ️  今日暂无平仓交易")

# 2. 测试 get_today_realized_pnl 函数
print("\n2️⃣ 测试 MonitorDB.get_today_realized_pnl()...")
from db_monitor import MonitorDB

# 获取所有今日交易过的symbol
cur.execute("""
    SELECT DISTINCT symbol 
    FROM "TradePosition" 
    WHERE "sellTime" >= CURRENT_DATE
""")
symbols = [row['symbol'] for row in cur.fetchall()]

if symbols:
    print(f"\n   今日交易过的股票 ({len(symbols)} 只):")
    print(f"\n   {'Symbol':<8} {'已实现盈亏':<15} {'来源'}")
    print("   " + "-" * 40)

    total_from_func = 0.0
    total_from_sql = 0.0

    for sym in symbols:
        # 使用函数
        pnl_func = MonitorDB.get_today_realized_pnl(sym)

        # 直接SQL
        cur.execute("""
            SELECT COALESCE(SUM(pnl), 0) 
            FROM "TradePosition" 
            WHERE symbol = %s AND "sellTime" >= CURRENT_DATE
        """, (sym,))
        pnl_sql = float(cur.fetchone()[0])

        total_from_func += pnl_func
        total_from_sql += pnl_sql

        match = "✅" if abs(pnl_func - pnl_sql) < 0.01 else "❌"

        print(f"   {sym:<8} ${pnl_func:<14.2f} {match}")

    print("   " + "-" * 40)
    print(f"   总计:    ${total_from_func:.2f}")

    if abs(total_from_func - total_from_sql) < 0.01:
        print(f"\n   ✅ get_today_realized_pnl() 函数工作正常！")
    else:
        print(f"\n   ❌ 函数返回 ${total_from_func:.2f}，但SQL计算是 ${total_from_sql:.2f}")
else:
    print("   ℹ️  今日暂无交易")

# 3. 检查是否有pnl为NULL的CLOSED交易
print("\n3️⃣ 检查是否有pnl为NULL的已平仓交易...")
cur.execute("""
    SELECT COUNT(*) as count
    FROM "TradePosition"
    WHERE status = 'CLOSED' AND pnl IS NULL
""")
null_count = cur.fetchone()['count']

if null_count > 0:
    print(f"   ⚠️  发现 {null_count} 笔已平仓但pnl为NULL的交易！")
    print(f"   这些交易可能是在修复之前产生的")

    # 显示这些交易
    cur.execute("""
        SELECT id, symbol, "buyPrice", "sellPrice", quantity, "sellTime"
        FROM "TradePosition"
        WHERE status = 'CLOSED' AND pnl IS NULL
        ORDER BY "sellTime" DESC
        LIMIT 5
    """)
    null_trades = cur.fetchall()

    print(f"\n   最近的NULL交易:")
    for t in null_trades:
        calc_pnl = (t['sellPrice'] - t['buyPrice']) * t['quantity'] if t['sellPrice'] and t['buyPrice'] else 0
        print(f"   ID={t['id']}, {t['symbol']}, 应该是: ${calc_pnl:.2f}")

    print(f"\n   💡 建议：运行修复脚本填充这些NULL值")
else:
    print(f"   ✅ 所有已平仓交易的pnl都已填写！")

print("\n" + "=" * 70)
print("✅ 测试完成")
print("=" * 70)

cur.close()
conn.close()


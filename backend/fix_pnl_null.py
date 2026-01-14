#!/usr/bin/env python3
"""
修复历史TradePosition中pnl为NULL的记录
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🔧 修复 TradePosition.pnl NULL值")
print("=" * 70)

from db import get_db_connection

conn = get_db_connection()
cur = conn.cursor()

# 1. 查找所有pnl为NULL的CLOSED交易
print("\n1️⃣ 查找pnl为NULL的已平仓交易...")
cur.execute("""
    SELECT 
        id, 
        symbol, 
        "buyPrice", 
        "sellPrice", 
        quantity,
        ("sellPrice" - "buyPrice") * quantity as calculated_pnl
    FROM "TradePosition"
    WHERE status = 'CLOSED' 
      AND pnl IS NULL
      AND "buyPrice" IS NOT NULL
      AND "sellPrice" IS NOT NULL
      AND quantity IS NOT NULL
    ORDER BY "sellTime" DESC
""")

null_trades = cur.fetchall()

if null_trades:
    print(f"   找到 {len(null_trades)} 笔需要修复的交易")

    # 2. 逐个修复
    print("\n2️⃣ 开始修复...")
    updated = 0

    for trade in null_trades:
        trade_id, symbol, buy_price, sell_price, quantity, calc_pnl = trade

        try:
            cur.execute("""
                UPDATE "TradePosition"
                SET pnl = %s
                WHERE id = %s
            """, (calc_pnl, trade_id))
            updated += 1
            print(f"   ✅ ID={trade_id:>4} {symbol:<6} pnl=${calc_pnl:>10.2f}")
        except Exception as e:
            print(f"   ❌ ID={trade_id:>4} {symbol:<6} 修复失败: {e}")

    conn.commit()
    print(f"\n   ✅ 成功修复 {updated}/{len(null_trades)} 笔交易")

    # 3. 验证
    print("\n3️⃣ 验证修复结果...")
    cur.execute("""
        SELECT COUNT(*) 
        FROM "TradePosition"
        WHERE status = 'CLOSED' AND pnl IS NULL
    """)
    remaining = cur.fetchone()[0]

    if remaining == 0:
        print(f"   ✅ 所有已平仓交易的pnl都已填写！")
    else:
        print(f"   ⚠️  还有 {remaining} 笔交易的pnl为NULL")
        print(f"   (可能是因为缺少buyPrice或sellPrice)")

    # 4. 显示修复后的统计
    print("\n4️⃣ 今日已实现盈亏统计...")
    cur.execute("""
        SELECT 
            symbol,
            COUNT(*) as trade_count,
            SUM(pnl) as total_pnl
        FROM "TradePosition"
        WHERE status = 'CLOSED' 
          AND "sellTime" >= CURRENT_DATE
        GROUP BY symbol
        ORDER BY total_pnl DESC
    """)

    stats = cur.fetchall()
    if stats:
        print(f"\n   {'Symbol':<8} {'交易次数':<10} {'总盈亏':<15}")
        print("   " + "-" * 40)
        grand_total = 0.0
        for row in stats:
            symbol, count, pnl = row
            pnl = float(pnl) if pnl else 0.0
            grand_total += pnl
            print(f"   {symbol:<8} {count:<10} ${pnl:>12.2f}")
        print("   " + "-" * 40)
        print(f"   {'总计':<8} {'':<10} ${grand_total:>12.2f}")

else:
    print("   ✅ 没有需要修复的交易！")

print("\n" + "=" * 70)
print("✅ 修复完成")
print("=" * 70)
print("\n📝 说明:")
print("   • pnl = (sellPrice - buyPrice) × quantity")
print("   • 所有历史NULL值已填充")
print("   • 新的交易会自动填写pnl")
print("=" * 70)

cur.close()
conn.close()


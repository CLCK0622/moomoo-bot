# backend/test_system.py
import time
import random
from datetime import datetime
from futu import *
from db import get_db_connection
from db_monitor import MonitorDB
from trader import QuantTrader
from dashboard import get_dashboard_data

# 确保测试用的 Symbol 不会干扰正常交易
TEST_SYMBOLS = [f"TEST{i}" for i in range(1, 11)]
REAL_TEST_SYMBOL = "F"  # 福特汽车，便宜，流动性好，用于测试真实下单连接


def setup_mock_data():
    print("\n🛠️ [1/5] Setting up Mock Data in DB...")
    conn = get_db_connection()
    cur = conn.cursor()

    # 清理旧的测试数据
    cur.execute("DELETE FROM \"DailyCandidate\" WHERE symbol LIKE 'TEST%' AND date = CURRENT_DATE")

    # 插入 10 个测试目标，分数随机
    for sym in TEST_SYMBOLS:
        score = random.randint(50, 100)
        cur.execute("""
            INSERT INTO "DailyCandidate" (symbol, "sentimentScore", status, date, "newsSummary")
            VALUES (%s, %s, 'PENDING', CURRENT_DATE, 'Mock News Summary for Testing')
        """, (sym, score))

    conn.commit()
    conn.close()
    print(f"   ✅ Inserted 10 mock targets ({TEST_SYMBOLS[0]} - {TEST_SYMBOLS[-1]})")


def test_auto_selection():
    print("\n🎲 [2/5] Testing Auto Selection Logic...")

    # 执行选股
    MonitorDB.auto_select_daily_targets()

    # 验证结果
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT symbol, status, \"sentimentScore\" FROM \"DailyCandidate\" WHERE symbol LIKE 'TEST%' AND date = CURRENT_DATE ORDER BY \"sentimentScore\" DESC")
    rows = cur.fetchall()
    conn.close()

    approved = [r for r in rows if r[1] == 'APPROVED']
    rejected = [r for r in rows if r[1] == 'REJECTED']

    print(f"   📊 Total: {len(rows)}, Approved: {len(approved)}, Rejected: {len(rejected)}")

    if len(approved) == 5 and len(rejected) == 5:
        print("   ✅ PASS: Exactly 5 stocks approved.")
        print(f"   🏆 Top 1 Score: {approved[0][2]} ({approved[0][0]})")
        print(f"   📉 Top Rejected Score: {rejected[0][2]} ({rejected[0][0]})")
    else:
        print("   ❌ FAIL: Selection logic incorrect!")
        exit(1)


def test_trader_connectivity():
    print("\n🤖 [3/5] Testing Trader Connectivity & Order System...")
    trader = QuantTrader()

    # 1. 解锁
    if not trader.unlock():
        print("   ❌ FAIL: Cannot unlock trader.")
        exit(1)
    print("   ✅ Trader unlocked.")

    # 2. 获取资产
    cash = trader.get_purchasing_power()
    print(f"   💰 Purchasing Power: ${cash:.2f}")
    if cash < 0:
        print("   ❌ FAIL: Invalid cash balance.")

    # 3. 测试下单 (模拟盘)
    # 注意：如果现在是盘后，市价单可能会失败或挂起。我们只测试函数调用是否成功。
    print(f"   🛒 Placing Test Order for {REAL_TEST_SYMBOL}...")

    # 这里我们手动调用 place_order 以获取 order_id 用于后续撤单
    ret, data = trader.ctx.place_order(
        price=10.0,  # 限价单，这就不会立刻成交
        qty=1,
        code=f"US.{REAL_TEST_SYMBOL}",
        trd_side=TrdSide.BUY,
        trd_env=TrdEnv.SIMULATE,  # 强制模拟盘
        order_type=OrderType.NORMAL  # 限价单
    )

    if ret == RET_OK:
        order_id = data['order_id'][0]
        print(f"   ✅ Order Placed Successfully! Order ID: {order_id}")

        # 🔥 暂停点 1：下单成功，等待用户检查
        print(f"   ⏸️  [PAUSE] Order {order_id} is ACTIVE. Check your App/Dashboard.")
        input("   ⌨️  Press ENTER to cancel the order and continue...")

        # 4. 撤单测试
        print("   🔙 Cancelling Order...")
        time.sleep(2)  # 等一下
        ret_c, data_c = trader.ctx.modify_order(
            ModifyOrderOp.CANCEL,
            order_id,
            0, 0,
            trd_env=TrdEnv.SIMULATE
        )
        if ret_c == RET_OK:
            print("   ✅ Order Cancelled Successfully.")
        else:
            print(f"   ⚠️ Cancel Failed (Maybe filled or rejected): {data_c}")
    else:
        print(f"   ❌ Order Placement Failed: {data}")
        # 不退出，继续测试看板

    trader.ctx.close()


def test_dashboard_stats():
    print("\n📊 [4/5] Testing Dashboard Data Aggregation...")

    # 1. 插入一个假的持仓记录到 DB
    conn = get_db_connection()
    cur = conn.cursor()
    fake_symbol = "TEST_DASH"
    watch_symbol = "TEST_WATCH"

    # 🔥 修复 FK 报错：必须先有 StockMonitor 和 DailyCandidate
    # 1. 插入 DailyCandidate (防止有约束)
    cur.execute("""
        INSERT INTO "DailyCandidate" (symbol, "sentimentScore", status, date, "newsSummary")
        VALUES (%s, 99, 'APPROVED', CURRENT_DATE, 'Mock News for Dashboard Test')
        ON CONFLICT (symbol, date) DO NOTHING
    """, (fake_symbol,))
    cur.execute("""
        INSERT INTO "DailyCandidate" (symbol, "sentimentScore", status, date, "newsSummary")
        VALUES (%s, 88, 'REJECTED', CURRENT_DATE, 'Mock News for Watch Test')
        ON CONFLICT (symbol, date) DO NOTHING
    """, (watch_symbol,))

    # 2. 插入 StockMonitor (解决 TradePosition 的外键依赖)
    cur.execute("""
        INSERT INTO "StockMonitor" (symbol, status, "baseOpenPrice", "isActive", "updatedAt")
        VALUES (%s, 'HOLDING', 100.0, true, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            status = EXCLUDED.status,
            "baseOpenPrice" = EXCLUDED."baseOpenPrice",
            "isActive" = true,
            "updatedAt" = NOW()
    """, (fake_symbol,))
    # 2b. 仅 WATCHING 的监控（无持仓），确保看板能显示
    cur.execute("""
        INSERT INTO "StockMonitor" (symbol, status, "baseOpenPrice", "isActive", "updatedAt")
        VALUES (%s, 'WATCHING', 50.0, true, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            status = 'WATCHING',
            "baseOpenPrice" = EXCLUDED."baseOpenPrice",
            "isActive" = true,
            "updatedAt" = NOW()
    """, (watch_symbol,))

    # 3. 插入 TradePosition 并更新 monitor 当前持仓
    cur.execute("""
        INSERT INTO "TradePosition" (symbol, "buyPrice", quantity, status, "buyTime")
        VALUES (%s, 100.0, 10, 'OPEN', NOW())
        RETURNING id
    """, (fake_symbol,))
    pos_id = cur.fetchone()[0]

    cur.execute("""
        UPDATE "StockMonitor"
        SET "currentPositionId" = %s, "updatedAt" = NOW()
        WHERE symbol = %s
    """, (pos_id, fake_symbol))

    # 4. 插入 TradeRecord + TradeLog 以便前端表格有数据
    cur.execute("""
        INSERT INTO "TradeRecord" (
            "candidateId", symbol, "createdAt", status,
            "entryPrice", quantity, "highestPrice", "currentStopLoss",
            "exitPrice", pnl, "pnlPercent", "isReEntry"
        ) VALUES (
            (SELECT id FROM "DailyCandidate" WHERE symbol = %s AND date = CURRENT_DATE LIMIT 1),
            %s, NOW(), 'HOLDING',
            100.0, 10, 101.0, 99.0,
            NULL, NULL, NULL, false
        )
        RETURNING id
    """, (fake_symbol, fake_symbol))
    trade_id = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO "TradeLog" ("tradeId", "timestamp", type, message, price)
        VALUES (%s, NOW(), 'INFO', '测试日志：建仓成功', 100.0)
    """, (trade_id,))

    conn.commit()
    conn.close()
    print(f"   ✅ Inserted fake position for {fake_symbol}")

    # 2. 调用 Dashboard 逻辑
    try:
        data = get_dashboard_data()
        stocks = data['stocks']
        monitors = data['monitors']
        found = False
        for s in stocks:
            if s['symbol'] == fake_symbol:
                print(f"   ✅ Found {fake_symbol} in dashboard data!")
                print(f"      Qty: {s['qty']}, Cost: {s['cost']}, Unrealized PnL: {s['unrealized_pnl']}")
                found = True
                break

        if not found:
            print("   ❌ FAIL: Fake position not showing in dashboard.")
        else:
            # 检查 WATCHING 监控是否存在
            watch_found = any(m['symbol'] == watch_symbol and m['status'] == 'WATCHING' for m in monitors)
            if watch_found:
                print(f"   ✅ WATCHING monitor {watch_symbol} present in dashboard monitors.")
            else:
                print(f"   ❌ FAIL: WATCHING monitor {watch_symbol} missing from dashboard monitors.")
    except Exception as e:
        print(f"   ❌ FAIL: Dashboard error: {e}")

    # 🔥 暂停点 2：假数据已上屏，等待用户检查
    print(f"   ⏸️  [PAUSE] Fake position {fake_symbol} is in DB. Check your Dashboard.")
    input("   ⌨️  Press ENTER to clean up and finish...")

    # 3. 清理假持仓
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM "TradeLog" WHERE "tradeId" = %s', (trade_id,))
    cur.execute('DELETE FROM "TradeRecord" WHERE id = %s', (trade_id,))
    cur.execute('DELETE FROM "TradePosition" WHERE id = %s', (pos_id,))
    cur.execute('DELETE FROM "StockMonitor" WHERE symbol IN (%s, %s)', (fake_symbol, watch_symbol))
    cur.execute('DELETE FROM "DailyCandidate" WHERE symbol IN (%s, %s)', (fake_symbol, watch_symbol))
    conn.commit()
    conn.close()
    print("   ✅ Cleaned up fake position.")


def cleanup():
    print("\n🧹 [5/5] Final Cleanup...")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM \"DailyCandidate\" WHERE symbol LIKE 'TEST%' AND date = CURRENT_DATE")
    conn.commit()
    conn.close()
    print("   ✅ All test data removed.")
    print("\n🎉 ALL SYSTEMS GO! READY FOR TOMORROW.")


if __name__ == "__main__":
    print("🚀 Starting System Health Check...")
    try:
        setup_mock_data()
        test_auto_selection()
        test_trader_connectivity()
        test_dashboard_stats()
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
    finally:
        cleanup()
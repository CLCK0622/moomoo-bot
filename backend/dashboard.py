# backend/dashboard.py
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT
from db import get_db_connection
from db_monitor import MonitorDB
from psycopg2.extras import RealDictCursor
from price_cache import PriceCache  # 🔥 实时价格缓存

# 🔥 确保这里和 trader.py 里的环境一致
CURRENT_ENV = TrdEnv.SIMULATE  # 如果是实盘，改为 TrdEnv.REAL


def _get_realtime_positions(ctx, acc_id=None):
    """
    🔑 关键函数：从 Moomoo 获取实时持仓（包含实时市价和浮盈浮亏）
    """
    try:
        if acc_id:
            ret, pos_data = ctx.position_list_query(trd_env=CURRENT_ENV, acc_id=acc_id)
        else:
            ret, pos_data = ctx.position_list_query(trd_env=CURRENT_ENV)

        if ret == RET_OK and not pos_data.empty:
            # 🔍 调试：打印第一行数据看字段名
            if len(pos_data) > 0:
                print(f"🔍 Position columns: {list(pos_data.columns)}")
                print(f"🔍 First row sample: {pos_data.iloc[0].to_dict()}")

            positions = {}
            for _, row in pos_data.iterrows():
                # 只统计有持仓的股票
                if row['qty'] > 0:
                    code = row['code'].split('.')[1]  # US.GOOGL -> GOOGL

                    # 🔧 修复：尝试多个可能的价格字段名
                    current_price = 0.0
                    if 'nominal_price' in row:
                        current_price = float(row['nominal_price'])
                    elif 'cur_price' in row:
                        current_price = float(row['cur_price'])
                    elif 'last_price' in row:
                        current_price = float(row['last_price'])
                    elif 'price' in row:
                        current_price = float(row['price'])
                    else:
                        # 如果都没有，用成本价
                        current_price = float(row.get('cost_price', 0))

                    # 成本价字段
                    cost = float(row.get('cost_price', 0))
                    if cost == 0 and 'cost_price_valid' in row:
                        cost = float(row.get('cost_price_valid', 0))

                    qty = float(row['qty'])
                    market_val = float(row.get('market_val', current_price * qty))

                    # 浮盈浮亏
                    pl_val = float(row.get('pl_val', market_val - cost * qty))

                    positions[code] = {
                        'qty': qty,
                        'cost': cost,
                        'current_price': current_price,
                        'market_value': market_val,
                        'pl_val': pl_val,
                        'pl_ratio': float(row.get('pl_ratio', 0.0)),
                    }
            return positions
        else:
            print(f"⚠️  position_list_query failed: {pos_data}")
    except Exception as e:
        print(f"⚠️  Exception in _get_realtime_positions: {e}")
        import traceback
        traceback.print_exc()

    return {}


def _get_account_info(ctx, acc_id=None):
    """
    🔥 获取账户信息（包括total_assets）
    """
    try:
        if acc_id:
            ret, data = ctx.accinfo_query(trd_env=CURRENT_ENV, acc_id=acc_id)
        else:
            ret, data = ctx.accinfo_query(trd_env=CURRENT_ENV)

        if ret == RET_OK and not data.empty:
            return {
                "total_assets": float(data['total_assets'].iloc[0]),  # 🔥 Moomoo返回的总资产
                "cash": float(data['cash'].iloc[0]),
                "market_val": float(data['market_val'].iloc[0]),  # Moomoo计算的持仓市值
                "power": float(data.get('power', [0.0]).iloc[0]),  # 购买力
            }
        else:
            print(f"⚠️  accinfo_query failed: {data}")
    except Exception as e:
        print(f"⚠️  Exception in _get_account_info: {e}")

    return {"total_assets": 0.0, "cash": 0.0, "market_val": 0.0, "power": 0.0}


def get_dashboard_data(acc_id=None):
    """
    🔥 核心改动：
    1. 总资产直接使用Moomoo返回的total_assets（准确）
    2. 浮盈使用PriceCache实时价格计算（无延迟）
    3. 已实现盈亏从数据库TradePosition查询今日已平仓的记录
    """

    # 1. 连接 Moomoo 获取持仓和账户信息
    realtime_positions = {}
    account_info = {"total_assets": 0.0, "cash": 0.0, "market_val": 0.0, "power": 0.0}

    try:
        ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=MOOMOO_HOST,
            port=MOOMOO_PORT,
            security_firm=SecurityFirm.FUTUSG  # 🔥 修正: 使用正确的 FUTUSG 账户
        )

        # 🔑 获取实时持仓（但不依赖其中的价格，因为可能有延迟）
        realtime_positions = _get_realtime_positions(ctx, acc_id)

        # 🔥 获取账户信息（包括Moomoo计算的total_assets）
        account_info = _get_account_info(ctx, acc_id)

        ctx.close()
    except Exception as e:
        print(f"⚠️  Failed to connect to Moomoo: {e}")

    # 🔥 2. 从PriceCache批量获取所有symbol的最新价格（无延迟！）
    symbols_to_price = list(realtime_positions.keys())
    cached_prices = PriceCache.get_prices(symbols_to_price) if symbols_to_price else {}

    print(f"🚀 Price Cache: Loaded {len(cached_prices)} prices from cache")

    # 3. 从数据库获取今日已实现盈亏
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 🔥 计算今日已实现盈亏：今日平仓的所有交易的盈亏总和
    cur.execute("""
        SELECT 
            COALESCE(SUM(("sellPrice" - "buyPrice") * quantity), 0) as realized_pnl
        FROM "TradePosition"
        WHERE status = 'CLOSED' 
          AND "sellTime" >= CURRENT_DATE
          AND "sellTime" < CURRENT_DATE + INTERVAL '1 day'
    """)
    realized_result = cur.fetchone()
    total_realized_pnl = float(realized_result['realized_pnl']) if realized_result else 0.0

    print(f"💰 Today's realized PnL: ${total_realized_pnl:.2f}")

    # 获取今日操作过的所有股票
    cur.execute(
        """
        SELECT DISTINCT symbol FROM "TradePosition" 
        WHERE "buyTime" >= CURRENT_DATE 
           OR "sellTime" >= CURRENT_DATE
           OR status = 'OPEN'
        """
    )
    active_symbols = [row['symbol'] for row in cur.fetchall()]

    # 3. 构建股票数据（合并 Moomoo 实时数据 + DB 已实现盈亏）
    stocks_data = []
    total_realized_db = 0.0
    total_unrealized = 0.0
    total_market_value = 0.0

    for sym in active_symbols:
        # 从 DB 获取今日已实现盈亏
        realized = MonitorDB.get_today_realized_pnl(sym)
        total_realized_db += realized

        # 🔑 优先使用 Moomoo 实时持仓数据
        if sym in realtime_positions:
            pos = realtime_positions[sym]
            qty = int(pos['qty'])
            cost = pos['cost']

            # 🔥 优先使用PriceCache的价格（Monitor线程实时更新，无延迟）
            if sym in cached_prices:
                current_price = cached_prices[sym]['price']
                price_age = cached_prices[sym]['age']
                if price_age < 10:  # 10秒内的价格认为是新鲜的
                    print(f"   ✅ {sym}: Using cached price ${current_price:.2f} (age: {price_age:.1f}s)")
                else:
                    print(f"   ⚠️  {sym}: Cache stale ({price_age:.1f}s), falling back to Moomoo")
                    current_price = pos['current_price']
            else:
                # 缓存未命中，使用Moomoo的价格
                current_price = pos['current_price']
                print(f"   ℹ️  {sym}: Cache miss, using Moomoo price ${current_price:.2f}")

            # 🔥 使用实时价格计算市值和浮盈浮亏（不依赖Moomoo的延迟数据）
            market_value = current_price * qty
            unrealized = (current_price - cost) * qty  # 实时计算: (现价 - 成本) * 数量

            total_unrealized += unrealized
            total_market_value += market_value

            stock_info = {
                "symbol": sym,
                "qty": qty,
                "cost": round(cost, 2),
                "current_price": round(current_price, 2),
                "market_value": round(market_value, 2),
                "realized_pnl": round(realized, 2),
                "unrealized_pnl": round(unrealized, 2),
                "total_pnl": round(realized + unrealized, 2),
                "status": "HOLDING",
            }
        else:
            # 如果 Moomoo 没有持仓，从 DB 查询（可能已平仓）
            cur.execute(
                """
                SELECT quantity, "buyPrice", status 
                FROM "TradePosition" 
                WHERE symbol = %s AND status = 'OPEN'
                ORDER BY "buyTime" DESC
                LIMIT 1
                """,
                (sym,)
            )
            db_pos = cur.fetchone()

            if db_pos and db_pos['quantity'] > 0:
                # DB 显示有持仓但 Moomoo 没有？可能数据不同步
                print(f"⚠️  {sym} has OPEN position in DB but not in Moomoo!")
                qty = int(db_pos['quantity'])
                cost = float(db_pos['buyPrice'])

                stock_info = {
                    "symbol": sym,
                    "qty": qty,
                    "cost": round(cost, 2),
                    "current_price": 0.0,  # 无法获取实时价
                    "market_value": 0.0,
                    "realized_pnl": round(realized, 2),
                    "unrealized_pnl": 0.0,
                    "total_pnl": round(realized, 2),
                    "status": "SYNC_ERROR",
                }
            else:
                # 今日操作过但已平仓
                stock_info = {
                    "symbol": sym,
                    "qty": 0,
                    "cost": 0.0,
                    "current_price": 0.0,
                    "market_value": 0.0,
                    "realized_pnl": round(realized, 2),
                    "unrealized_pnl": 0.0,
                    "total_pnl": round(realized, 2),
                    "status": "FLAT",
                }

        stocks_data.append(stock_info)

    # 4. TradeRecord 列表
    cur.execute(
        """
        SELECT id, symbol, "createdAt", status, "entryPrice", quantity, "highestPrice", "currentStopLoss",
               "exitPrice", pnl, "pnlPercent", "isReEntry"
        FROM "TradeRecord"
        ORDER BY "createdAt" DESC
        LIMIT 50
        """
    )
    trades = cur.fetchall()

    # 5. TradeLog 列表
    cur.execute(
        """
        SELECT id, "tradeId", "timestamp", type, message, price
        FROM "TradeLog"
        ORDER BY "timestamp" DESC
        LIMIT 100
        """
    )
    logs = cur.fetchall()

    # 6. StockMonitor 列表
    cur.execute(
        """
        SELECT id, symbol, "isActive", status, "baseOpenPrice", "currentPositionId", "entryCount",
               "lastBuyPrice", "lastSellPrice", "maxPriceSeen", "updatedAt"
        FROM "StockMonitor"
        WHERE status IN ('HOLDING', 'WATCHING')
        ORDER BY "updatedAt" DESC
        """
    )
    monitors = cur.fetchall()

    # 7. 今日 DailyCandidate 列表
    cur.execute(
        """
        SELECT id, symbol, date, "sentimentScore", status
        FROM "DailyCandidate"
        WHERE date = CURRENT_DATE
        ORDER BY "sentimentScore" DESC
        """
    )
    candidates = cur.fetchall()

    conn.close()

    # 8. 🔥 构建账户信息：使用Moomoo的total_assets（准确）
    total_pnl_today = total_realized_pnl + total_unrealized  # 已实现 + 浮盈

    account_summary = {
        "total_assets": round(account_info['total_assets'], 2),  # 🔥 使用Moomoo返回的准确值
        "cash": round(account_info['cash'], 2),
        "market_value": round(account_info['market_val'], 2),  # 🔥 使用Moomoo计算的持仓市值
        "power": round(account_info['power'], 2),
        "total_pnl_today": round(total_pnl_today, 2),
        "realized_pnl": round(total_realized_pnl, 2),  # 🔥 今日已实现盈亏
        "unrealized_pnl": round(total_unrealized, 2),  # 当前浮盈
    }

    return {
        "account": account_summary,
        "stocks": stocks_data,
        "trades": trades,
        "monitors": monitors,
        "logs": logs,
        "candidates": candidates,
    }


if __name__ == "__main__":
    # 🔧 测试时可以传入 acc_id
    import sys

    acc_id = None
    if len(sys.argv) > 1:
        acc_id = int(sys.argv[1])
        print(f"🔍 Using account ID: {acc_id}")

    # 测试打印
    data = get_dashboard_data(acc_id)

    print("=" * 70)
    print(f"💰 Total Assets:     ${data['account']['total_assets']:>12,.2f}")
    print(f"   ├─ 💵 Cash:        ${data['account']['cash']:>12,.2f}")
    print(f"   └─ 📊 Stock Value: ${data['account']['market_value']:>12,.2f}")
    print(f"⚡ Buying Power:     ${data['account']['power']:>12,.2f}")
    print("-" * 70)
    print(f"📈 Today PnL:        ${data['account']['total_pnl_today']:>12,.2f}")
    print(f"   ├─ ✅ Realized:    ${data['account']['realized_pnl']:>12,.2f}")
    print(f"   └─ 📊 Unrealized:  ${data['account']['unrealized_pnl']:>12,.2f}")
    print("=" * 70)

    if data['stocks']:
        print(f"\n📦 Stocks ({len(data['stocks'])}):")
        print(f"{'Symbol':<8} {'Status':<12} {'Qty':<8} {'Cost':<10} {'Current':<10} {'Value':<12} {'PnL':<12}")
        print("-" * 70)

        for s in data['stocks']:
            status_icon = {
                'HOLDING': '🟢',
                'FLAT': '⚪',
                'SYNC_ERROR': '🔴'
            }.get(s['status'], '❓')

            print(f"{s['symbol']:<8} {status_icon}{s['status']:<11} "
                  f"{s['qty']:<8} ${s['cost']:<9.2f} ${s['current_price']:<9.2f} "
                  f"${s['market_value']:<11,.2f} ${s['total_pnl']:<11,.2f}")
    else:
        print("\n📦 No active stocks today")

    print("-" * 70)
    print(f"📝 Trades: {len(data['trades'])} | "
          f"📋 Logs: {len(data['logs'])} | "
          f"👁️  Monitors: {len(data['monitors'])} | "
          f"🎯 Candidates: {len(data['candidates'])}")
    print("=" * 70)
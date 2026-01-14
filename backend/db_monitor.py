# backend/db_monitor.py
from db import get_db_connection, insert_trade_record, insert_trade_log, update_trade_record_on_sell


class MonitorDB:
    @staticmethod
    def get_active_monitors():
        conn = get_db_connection()
        cursor = conn.cursor()
        # 🔥 记得查 entryCount
        query = """
            SELECT 
                m.id, m.symbol, m.status, m."maxPriceSeen", m."lastSellPrice", m."currentPositionId",
                t."buyPrice", t."quantity", m."baseOpenPrice", m."entryCount"
            FROM "StockMonitor" m
            LEFT JOIN "TradePosition" t ON m."currentPositionId" = t.id
            WHERE m."isActive" = true 
            AND m.status IN ('HOLDING', 'WATCHING')
            """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append({
                "monitor_id": row[0],
                "symbol": row[1],
                "status": row[2],
                "max_price": row[3],
                "last_sell": row[4],
                "position_id": row[5],
                "buy_price": row[6],
                "quantity": row[7],
                "base_open": row[8],
                "entryCount": row[9] if row[9] is not None else 0
            })
        return results

    @staticmethod
    def get_today_realized_pnl(symbol):
        """获取某股票今日已结算盈亏"""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM("pnl") 
            FROM "TradePosition"
            WHERE symbol = %s AND "sellTime" >= CURRENT_DATE
        """, (symbol,))
        res = cur.fetchone()[0]
        conn.close()
        return float(res) if res else 0.0

    @staticmethod
    def get_stock_total_pnl(symbol, current_price, current_qty, current_cost):
        """获取当日总盈亏 (已实现 + 浮动)"""
        realized = MonitorDB.get_today_realized_pnl(symbol)
        unrealized = 0.0
        if current_qty > 0:
            unrealized = (current_price - current_cost) * current_qty
        return realized + unrealized

    @staticmethod
    def update_max_price(monitor_id, new_max):
        """更新最高价记忆"""
        conn = get_db_connection()
        cur = conn.cursor()

        # 🔥 Convert numpy types to Python native types
        new_max = float(new_max) if new_max is not None else None
        monitor_id = int(monitor_id) if monitor_id is not None else None

        # 🔥 增加 updatedAt
        cur.execute("""
            UPDATE "StockMonitor" 
            SET "maxPriceSeen" = %s, "updatedAt" = NOW() 
            WHERE id = %s
        """, (new_max, monitor_id))
        conn.commit()
        conn.close()

    @staticmethod
    def record_sell_action(monitor_id, position_id, sell_price, reason):
        """
        执行卖出后的数据库更新 (HOLDING -> WATCHING)
        🔥 同步更新 TradeRecord 和 TradeLog
        """
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            # 🔥 Convert numpy types to Python native types
            sell_price = float(sell_price) if sell_price is not None else None
            monitor_id = int(monitor_id) if monitor_id is not None else None
            position_id = int(position_id) if position_id is not None else None


            # 1. 获取 TradePosition 信息（用于计算 PnL 和查找关联的 TradeRecord）
            cur.execute("""
                SELECT symbol, "buyPrice", quantity FROM "TradePosition" WHERE id = %s
            """, (position_id,))
            pos_data = cur.fetchone()

            if pos_data:
                symbol, buy_price, quantity = pos_data
                pnl = (sell_price - buy_price) * quantity

                # 2. 🔥 立即更新 TradePosition，填写pnl（这是关键！）
                cur.execute("""
                    UPDATE "TradePosition" 
                    SET status = 'CLOSED', 
                        "sellPrice" = %s, 
                        "sellTime" = NOW(), 
                        "exitReason" = %s,
                        pnl = %s
                    WHERE id = %s
                """, (sell_price, reason, pnl, position_id))

                # 3. 查找对应的 TradeRecord（最新的 WATCHING 记录）
                # 🔥 Important: TradeLog.tradeId references TradeRecord.id (NOT candidateId!)
                cur.execute("""
                    SELECT id FROM "TradeRecord" 
                    WHERE symbol = %s AND status = 'WATCHING' 
                    ORDER BY "createdAt" DESC LIMIT 1
                """, (symbol,))
                trade_record = cur.fetchone()

                if trade_record:
                    trade_record_id = trade_record[0]
                    # 更新 TradeRecord (Optional)
                    try:
                        update_trade_record_on_sell(trade_record_id, sell_price, pnl, reason)
                    except Exception as e:
                        print(f"⚠️  [DB] TradeRecord update skipped: {e}")

                    # 插入 TradeLog (Optional)
                    try:
                        insert_trade_log(trade_record_id, 'SELL', f"Closed position: {quantity} shares @ ${sell_price:.2f}. Reason: {reason}", sell_price)
                    except Exception as e:
                        print(f"⚠️  [DB] TradeLog insertion skipped: {e}")
            else:
                # 如果找不到TradePosition，至少记录一下
                print(f"⚠️  [DB] TradePosition {position_id} not found!")

            # 4. 更新 StockMonitor 状态
            # 🔥 如果是PHASE2止盈，直接标记为FINISHED，不再允许回马枪买入
            if reason and "PHASE2" in reason:
                final_status = 'FINISHED'
                is_active = False
                print(f"🎯 [DB] {symbol} triggered PHASE2, marking as FINISHED (no re-entry today)")
            else:
                final_status = 'WATCHING'
                is_active = True

            cur.execute("""
                UPDATE "StockMonitor"
                SET status = %s, 
                    "currentPositionId" = NULL, 
                    "lastSellPrice" = %s,
                    "isActive" = %s,
                    "updatedAt" = NOW()
                WHERE id = %s
            """, (final_status, sell_price, is_active, monitor_id))

            conn.commit()
            print(f"✅ [DB] Sell action recorded: Sold @ ${sell_price:.2f}. Reason: {reason}")

        except Exception as e:
            conn.rollback()
            print(f"❌ DB Error in record_sell_action: {e}")
        finally:
            conn.close()

    @staticmethod
    def record_buy_action(monitor_id, symbol, price, qty, base_open_price=None):
        """
        记录买入
        🔥 修正顺序 + 增加 updatedAt + 同步写入 TradeRecord 和 TradeLog
        """
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            # 🔥 Convert numpy types to Python native types
            price = float(price) if price is not None else None
            qty = int(qty) if qty is not None else 0
            base_open_price = float(base_open_price) if base_open_price is not None else None

            # 1. 确保 StockMonitor 存在 (Upsert)
            cur.execute("""
                INSERT INTO "StockMonitor" (
                    symbol, status, "isActive", "baseOpenPrice", "entryCount", "maxPriceSeen", "updatedAt"
                )
                VALUES (%s, 'HOLDING', true, %s, 0, %s, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    "isActive" = true,
                    "updatedAt" = NOW(),
                    "baseOpenPrice" = COALESCE("StockMonitor"."baseOpenPrice", EXCLUDED."baseOpenPrice")
            """, (symbol, base_open_price, price))

            # 2. 插入 TradePosition
            cur.execute("""
                INSERT INTO "TradePosition" (symbol, "buyPrice", quantity, status, "buyTime")
                VALUES (%s, %s, %s, 'OPEN', NOW())
                RETURNING id
            """, (symbol, price, qty))
            new_pos_id = cur.fetchone()[0]

            # 3. 更新 StockMonitor 关联
            cur.execute("""
                UPDATE "StockMonitor"
                SET status = 'HOLDING',
                    "currentPositionId" = %s,
                    "maxPriceSeen" = %s,
                    "lastBuyPrice" = %s,
                    "entryCount" = COALESCE("entryCount", 0) + 1,
                    "updatedAt" = NOW()
                WHERE symbol = %s
            """, (new_pos_id, price, price, symbol))

            # 🔥 4. 创建 TradeRecord 记录 (Optional - for analytics)
            trade_id = None
            try:
                trade_id = insert_trade_record(symbol, price, qty, f"Bought at ${price:.2f}")
            except Exception as e:
                print(f"⚠️  [DB] TradeRecord insertion skipped (schema may not support it): {e}")

            # 🔥 5. 创建 TradeLog 日志 (Optional - for analytics)
            if trade_id:
                try:
                    insert_trade_log(trade_id, 'BUY', f"Opened position: {qty} shares @ ${price:.2f}", price)
                except Exception as e:
                    print(f"⚠️  [DB] TradeLog insertion skipped: {e}")

            conn.commit()
            print(f"✅ [DB] Buy action recorded: {symbol} x{qty} @ ${price:.2f} (TradeRecord #{trade_id})")

        except Exception as e:
            conn.rollback()
            print(f"❌ DB Error in record_buy_action: {e}")
            raise e
        finally:
            conn.close()

    @staticmethod
    def force_start_watching(symbol, trigger_price, base_open_price):
        """开盘跌破 -1% 或 9:35 没触发时，初始化为 WATCHING"""
        conn = get_db_connection()
        cur = conn.cursor()

        # 🔥 Convert numpy types to Python native types
        trigger_price = float(trigger_price) if trigger_price is not None else None
        base_open_price = float(base_open_price) if base_open_price is not None else None

        # 🔥 增加 updatedAt
        cur.execute("""
                INSERT INTO "StockMonitor" (
                    symbol, status, "lastSellPrice", "baseOpenPrice", "isActive", "updatedAt"
                )
                VALUES (%s, 'WATCHING', %s, %s, true, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    status = 'WATCHING',
                    "lastSellPrice" = %s,
                    "baseOpenPrice" = %s,
                    "isActive" = true,
                    "updatedAt" = NOW()
            """, (symbol, trigger_price, base_open_price, trigger_price, base_open_price))

        conn.commit()
        conn.close()

    @staticmethod
    def auto_select_daily_targets():
        """
        每天 9:29 自动执行：
        1. 重置今日所有目标为 REJECTED
        2. 按 sentimentScore 降序选出前 5 名设置为 APPROVED
        """
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. 重置今日状态
        cur.execute("""
            UPDATE "DailyCandidate" SET status = 'REJECTED' WHERE date = CURRENT_DATE
        """)

        # 2. 选出前5名 (PostgreSQL 语法)
        cur.execute("""
            UPDATE "DailyCandidate"
            SET status = 'APPROVED'
            WHERE id IN (
                SELECT id FROM "DailyCandidate" 
                WHERE date = CURRENT_DATE 
                ORDER BY "sentimentScore" DESC 
                LIMIT 5
            )
        """)

        conn.commit()
        conn.close()
        print("✅ Daily targets auto-selected: Top 5 APPROVED, others REJECTED.")

    @staticmethod
    def force_finish_all(symbol):
        """收盘强制结束"""
        conn = get_db_connection()
        cur = conn.cursor()
        # 🔥 增加 updatedAt
        cur.execute("""
            UPDATE "StockMonitor" 
            SET status = 'FINISHED', "isActive" = false, "updatedAt" = NOW() 
            WHERE symbol = %s
        """, (symbol,))
        conn.commit()
        conn.close()
import os
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# 获取 Docker 里的数据库连接串，或者直接在这里写死
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:mysecretpassword@localhost:5432/trading")

def get_db_connection():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn

def save_daily_analysis(symbol, sentiment_score, summary, news_links):
    """
    将 Senior Agent 的分析结果写入 DailyCandidate 表
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 使用 UPSERT 逻辑：如果当天该股票已有记录，则更新
        sql = """
            INSERT INTO "DailyCandidate" (date, symbol, "sentimentScore", "newsSummary", "sourceLinks", status)
            VALUES (CURRENT_DATE, %s, %s, %s, %s, 'PENDING')
            ON CONFLICT (date, symbol) 
            DO UPDATE SET 
                "sentimentScore" = EXCLUDED."sentimentScore",
                "newsSummary" = EXCLUDED."newsSummary",
                "sourceLinks" = EXCLUDED."sourceLinks",
                status = 'PENDING';
        """
        cur.execute(sql, (symbol, sentiment_score, summary, news_links))
        print(f"✅ [DB] Saved analysis for {symbol}")
    except Exception as e:
        print(f"❌ [DB Error] {e}")
    finally:
        cur.close()
        conn.close()

def get_approved_candidates():
    """
    获取所有状态为 APPROVED 的股票（供交易脚本使用）
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT * FROM "DailyCandidate" 
        WHERE date = CURRENT_DATE AND status = 'APPROVED'
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_active_watchlist():
    """
    从数据库获取 isActive = True 的自选股列表
    返回格式: [{'symbol': 'TSLA', 'name': 'Tesla', 'type': 'stock'}, ...]
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 注意表名加双引号，防止大小写问题
        cur.execute('SELECT symbol, name, type FROM "Watchlist" WHERE "isActive" = true')
        rows = cur.fetchall()
        return rows
    except Exception as e:
        print(f"❌ [DB Error] Failed to fetch watchlist: {e}")
        return []
    finally:
        cur.close()
        conn.close()


# backend/db.py

def get_approved_targets_for_today():
    """
    获取今日状态为 APPROVED 的股票列表 (PostgreSQL 适配版)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 修复点 1: 表名和字段名加双引号 "" 以匹配 Prisma 的大小写
    # 修复点 2: 使用 Postgres 的日期语法 ("date"::date = CURRENT_DATE)
    query = """
    SELECT "symbol", "sentimentScore", "newsSummary"
    FROM "DailyCandidate"
    WHERE "status" = 'APPROVED'
    AND "date"::date = CURRENT_DATE
    """

    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        targets = []
        for row in rows:
            targets.append({
                "symbol": row[0],
                "score": row[1],  # 对应 sentimentScore
                "reason": row[2]  # 对应 summary
            })
        return targets
    except Exception as e:
        print(f"❌ DB Error: {e}")
        # 调试提示: 如果还是报错，打印一下现在的表到底叫什么
        print("   (Tip: Check if your table name is 'DailyCandidate' or 'daily_candidate' in PgAdmin/TablePlus)")
        return []
    finally:
        conn.close()


def insert_trade_record(symbol, entry_price, quantity, strategy_note=""):
    """
    插入新的交易记录到 TradeRecord 表
    返回新创建的 TradeRecord.id (用于 TradeLog foreign key)

    Note: TradeRecord requires a candidateId (foreign key to DailyCandidate)
    This function will:
    1. Look for today's DailyCandidate for this symbol
    2. If found, create TradeRecord with that candidateId
    3. If not found, skip (return None) since TradeRecord is meant for analyzed candidates
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 🔥 Convert numpy types to Python native types
        entry_price = float(entry_price) if entry_price is not None else None
        quantity = int(quantity) if quantity is not None else 0

        # Step 1: Find today's DailyCandidate for this symbol
        cur.execute("""
            SELECT id FROM "DailyCandidate" 
            WHERE symbol = %s AND date = CURRENT_DATE
            LIMIT 1
        """, (symbol,))

        candidate = cur.fetchone()
        if not candidate:
            # No DailyCandidate found - this is OK, just skip TradeRecord
            # (Stocks might be traded outside of the daily analysis system)
            print(f"ℹ️  [DB] No DailyCandidate for {symbol} today - TradeRecord skipped")
            return None

        candidate_id = candidate[0]

        # Step 2: Insert TradeRecord with the candidateId, return the auto-generated id
        cur.execute("""
            INSERT INTO "TradeRecord" (
                "candidateId", symbol, "entryPrice", quantity, "highestPrice", 
                "currentStopLoss", "createdAt", "isReEntry", status
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), false, 'WATCHING')
            RETURNING id
        """, (candidate_id, symbol, entry_price, quantity, entry_price, entry_price * 0.99))

        trade_record_id = cur.fetchone()[0]
        conn.commit()
        print(f"✅ [DB] Created TradeRecord (id={trade_record_id}, candidateId={candidate_id}) for {symbol}")
        return trade_record_id

    except Exception as e:
        conn.rollback()
        print(f"❌ [DB Error] insert_trade_record: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def insert_trade_log(trade_id, log_type, message, price=None):
    """
    插入交易日志到 TradeLog 表
    log_type: 'BUY', 'SELL', 'STOP_UPDATE', 'INFO', 'ERROR'
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 🔥 Convert numpy types to Python native types
        trade_id = int(trade_id) if trade_id is not None else None
        price = float(price) if price is not None else None

        cur.execute("""
            INSERT INTO "TradeLog" ("tradeId", "timestamp", type, message, price)
            VALUES (%s, NOW(), %s, %s, %s)
        """, (trade_id, log_type, message, price))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"❌ [DB Error] insert_trade_log: {e}")
    finally:
        cur.close()
        conn.close()


def update_trade_record_on_sell(trade_record_id, exit_price, pnl, exit_reason):
    """
    卖出时更新 TradeRecord 状态
    使用 FINISHED status (MonitorStatus enum)

    Args:
        trade_record_id: TradeRecord.id (NOT candidateId!)
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 🔥 Convert numpy types to Python native types
        trade_record_id = int(trade_record_id) if trade_record_id is not None else None
        exit_price = float(exit_price) if exit_price is not None else None
        pnl = float(pnl) if pnl is not None else None

        # Calculate pnl percent
        cur.execute("""
            UPDATE "TradeRecord"
            SET status = 'FINISHED',
                "exitPrice" = %s,
                pnl = %s,
                "pnlPercent" = CASE 
                    WHEN "entryPrice" * quantity > 0 
                    THEN (%s / ("entryPrice" * quantity)) * 100 
                    ELSE 0 
                END
            WHERE id = %s
        """, (exit_price, pnl, pnl, trade_record_id))

        conn.commit()
        print(f"✅ [DB] Updated TradeRecord #{trade_record_id} with exit price ${exit_price:.2f}")
    except Exception as e:
        conn.rollback()
        print(f"❌ [DB Error] update_trade_record_on_sell: {e}")
    finally:
        cur.close()
        conn.close()


def log_trade_execution(symbol, action, price, quantity, status):
    """
    (Legacy function - 保持向后兼容)
    简单的交易日志打印
    """
    print(f"📝 DB Log: {action} {symbol} - {quantity} shares @ {price} ({status})")
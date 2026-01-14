#!/usr/bin/env python3
"""
实时价格缓存 - 用于消除Dashboard的延迟
Monitor线程将价格写入Redis/数据库，Dashboard直接读取
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db_connection
from datetime import datetime

class PriceCache:
    """
    实时价格缓存 - 使用数据库实现
    Monitor线程写入，Dashboard读取
    """

    @staticmethod
    def init_table():
        """创建价格缓存表（如果不存在）"""
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS "PriceCache" (
                    symbol TEXT PRIMARY KEY,
                    price DOUBLE PRECISION NOT NULL,
                    "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

            # 创建索引加速查询
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_cache_updated 
                ON "PriceCache"("updatedAt")
            """)

            conn.commit()
            print("✅ PriceCache table initialized")
        except Exception as e:
            print(f"⚠️  PriceCache table may already exist: {e}")
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def update_prices(price_dict):
        """
        批量更新价格
        Args:
            price_dict: {symbol: price, ...}
        """
        if not price_dict:
            return

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            for symbol, price in price_dict.items():
                # 🔥 Convert numpy types
                symbol = str(symbol)
                price = float(price) if price is not None else None

                if price is None or price <= 0:
                    continue

                # UPSERT: 插入或更新
                cur.execute("""
                    INSERT INTO "PriceCache" (symbol, price, "updatedAt")
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (symbol) 
                    DO UPDATE SET 
                        price = EXCLUDED.price,
                        "updatedAt" = NOW()
                """, (symbol, price))

            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"❌ PriceCache update error: {e}")
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_price(symbol):
        """
        获取单个股票价格
        Returns: (price, age_seconds) or (None, None)
        """
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT price, EXTRACT(EPOCH FROM (NOW() - "updatedAt")) as age
                FROM "PriceCache"
                WHERE symbol = %s
            """, (symbol,))

            result = cur.fetchone()
            if result:
                return float(result[0]), float(result[1])
            return None, None
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_prices(symbols):
        """
        批量获取价格
        Args:
            symbols: list of symbols
        Returns:
            {symbol: {'price': float, 'age': seconds}}
        """
        if not symbols:
            return {}

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            placeholders = ','.join(['%s'] * len(symbols))
            cur.execute(f"""
                SELECT symbol, price, EXTRACT(EPOCH FROM (NOW() - "updatedAt")) as age
                FROM "PriceCache"
                WHERE symbol IN ({placeholders})
            """, tuple(symbols))

            results = {}
            for row in cur.fetchall():
                results[row[0]] = {
                    'price': float(row[1]),
                    'age': float(row[2])
                }
            return results
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_all_prices():
        """获取所有缓存的价格"""
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT symbol, price, "updatedAt"
                FROM "PriceCache"
                ORDER BY symbol
            """)

            results = {}
            for row in cur.fetchall():
                results[row[0]] = {
                    'price': float(row[1]),
                    'updated_at': row[2]
                }
            return results
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def clean_old_prices(max_age_seconds=300):
        """清理超过N秒未更新的价格（市场关闭后）"""
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                DELETE FROM "PriceCache"
                WHERE EXTRACT(EPOCH FROM (NOW() - "updatedAt")) > %s
            """, (max_age_seconds,))

            deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            cur.close()
            conn.close()


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 Price Cache Test")
    print("=" * 70)

    # 1. 初始化表
    print("\n1️⃣ Initializing table...")
    PriceCache.init_table()

    # 2. 更新价格
    print("\n2️⃣ Updating prices...")
    test_prices = {
        'AAPL': 175.50,
        'GOOGL': 140.25,
        'TSLA': 245.80
    }
    PriceCache.update_prices(test_prices)
    print(f"   ✅ Updated {len(test_prices)} prices")

    # 3. 读取单个价格
    print("\n3️⃣ Reading single price...")
    price, age = PriceCache.get_price('AAPL')
    if price:
        print(f"   AAPL: ${price:.2f} (age: {age:.2f}s)")

    # 4. 批量读取
    print("\n4️⃣ Reading multiple prices...")
    prices = PriceCache.get_prices(['AAPL', 'GOOGL', 'TSLA', 'NOTFOUND'])
    for sym, data in prices.items():
        print(f"   {sym}: ${data['price']:.2f} (age: {data['age']:.2f}s)")

    # 5. 查看所有价格
    print("\n5️⃣ All cached prices...")
    all_prices = PriceCache.get_all_prices()
    print(f"   Total: {len(all_prices)} symbols cached")

    # 6. 清理测试数据
    print("\n6️⃣ Cleaning up test data...")
    from db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM \"PriceCache\" WHERE symbol IN ('AAPL', 'GOOGL', 'TSLA')")
    conn.commit()
    cur.close()
    conn.close()
    print("   ✅ Test data cleaned")

    print("\n" + "=" * 70)
    print("✅ Price Cache is ready!")
    print("=" * 70)
    print("\n📝 Usage:")
    print("   Monitor thread: PriceCache.update_prices(price_dict)")
    print("   Dashboard:      PriceCache.get_prices(symbols)")
    print("=" * 70)


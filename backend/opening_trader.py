# backend/opening_trader.py
import time
from datetime import datetime
import pytz
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT
from trader import QuantTrader
from db import get_db_connection
from db_monitor import MonitorDB

SNIPER_END_TIME = "09:35"
MAX_STOCKS = 5  # 最多买入5只股票
MIN_SENTIMENT_SCORE = 4  # 最低情绪分数


class OpeningSniper:
    def __init__(self):
        print("🔫 Initializing Opening Sniper (Dynamic Selection)...")
        self.trader = QuantTrader()
        self.ctx = self.trader.ctx  # 交易连接
        self.quote_ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)

        self.candidates = {}  # 所有候选股票
        self.bought = []  # 已买入的股票
        self.fixed_per_stock_budget = 0.0

    def get_ny_time(self):
        ny_tz = pytz.timezone('America/New_York')
        return datetime.now(ny_tz).strftime("%H:%M")

    def load_optimistic_candidates(self):
        """
        加载所有乐观股票 (sentimentScore >= 4)
        """
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT symbol, "sentimentScore", status
            FROM "DailyCandidate"
            WHERE date = CURRENT_DATE
              AND "sentimentScore" >= %s
            ORDER BY "sentimentScore" DESC, symbol
        """, (MIN_SENTIMENT_SCORE,))

        rows = cur.fetchall()
        conn.close()

        if not rows:
            print(f"❌ No candidates with sentimentScore >= {MIN_SENTIMENT_SCORE}")
            return False

        symbols = [row[0] for row in rows]
        scores = {row[0]: row[1] for row in rows}

        print(f"📊 Loaded {len(symbols)} optimistic candidates (score >= {MIN_SENTIMENT_SCORE}):")
        for sym in symbols[:10]:  # 显示前10个
            print(f"   {sym}: score={scores[sym]}")
        if len(symbols) > 10:
            print(f"   ... and {len(symbols) - 10} more")

        for sym in symbols:
            self.candidates[sym] = {
                'base_price': None,
                'score': scores[sym],
                'status': 'WATCHING'
            }

        return True

    def calculate_fixed_budget(self):
        """
        基于总资产和MAX_STOCKS计算固定预算
        """
        ret, data = self.ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            print(f"❌ Failed to get account info: {data}")
            return False

        total_assets = data['total_assets'][0]
        self.fixed_per_stock_budget = (total_assets / 1.2) / MAX_STOCKS

        print("=" * 60)
        print(f"💰 Account Total Assets:    ${total_assets:.2f}")
        print(f"🎯 Max Stocks:              {MAX_STOCKS}")
        print(f"💵 FIXED Budget/Stock:      ${self.fixed_per_stock_budget:.2f}")
        print("=" * 60)
        return True

    def run(self):
        if not self.trader.unlock():
            return

        # 等待到9:29加载候选股票
        while self.get_ny_time() < "09:29":
            print(f"⏳ Waiting for 09:29 to load candidates... (Current: {self.get_ny_time()})")
            time.sleep(10)

        print(f"🎲 Loading all optimistic stocks (sentimentScore >= {MIN_SENTIMENT_SCORE})...")

        if not self.load_optimistic_candidates():
            return

        # 🔥 等到9:30开盘后再设置base_price
        while self.get_ny_time() < "09:30":
            print(f"⏳ Waiting for market open (09:30)... (Current: {self.get_ny_time()})")
            time.sleep(5)

        # 🔥 9:30开盘后，获取实时价格作为base_price
        print("📊 Market opened! Setting base prices from first real-time quotes...")
        watching_syms = list(self.candidates.keys())
        ret, data = self.quote_ctx.get_market_snapshot([f"US.{s}" for s in watching_syms])

        if ret == RET_OK:
            for _, row in data.iterrows():
                sym = row['code'].split('.')[1]
                base_price = row['open_price'] if row['open_price'] > 0 else row['last_price']
                self.candidates[sym]['base_price'] = base_price
                print(f"   {sym}: base_price=${base_price:.2f}")
        else:
            print(f"❌ Failed to get base prices: {data}")
            return

        if not self.calculate_fixed_budget():
            return

        print(f"🚀 Dynamic Sniper started! Will buy first {MAX_STOCKS} stocks that surge...")
        print(f"⏰ Monitoring until {SNIPER_END_TIME}...")

        # 主循环：监控所有候选股票
        while True:
            current_time = self.get_ny_time()

            # 检查是否到达截止时间
            if current_time >= SNIPER_END_TIME:
                print(f"\n⏰ {SNIPER_END_TIME} reached. Finalizing selection...")
                self.finalize_selection()
                break

            # 如果已经买够了，提前结束
            if len(self.bought) >= MAX_STOCKS:
                print(f"\n✅ Already bought {MAX_STOCKS} stocks. Mission complete!")
                # 🔥 也需要调用finalize_selection来设置APPROVED/REJECTED
                self.finalize_selection()
                break

            # 获取所有还在监控的股票
            watching_syms = [s for s, info in self.candidates.items()
                             if info['status'] == 'WATCHING']

            if not watching_syms:
                print("ℹ️  No more stocks to watch.")
                break

            # 获取实时价格
            ret, data = self.quote_ctx.get_market_snapshot([f"US.{s}" for s in watching_syms])

            if ret == RET_OK:
                for _, row in data.iterrows():
                    sym = row['code'].split('.')[1]
                    curr_price = row['last_price']
                    base_price = self.candidates[sym]['base_price']
                    score = self.candidates[sym]['score']

                    pct = (curr_price - base_price) / base_price

                    # 🚀 涨幅 >= 0.5% -> 立即买入
                    if pct >= 0.005:
                        if len(self.bought) < MAX_STOCKS:
                            print(
                                f"   🚀 [{len(self.bought) + 1}/{MAX_STOCKS}] {sym} surged {pct * 100:.2f}% (score={score})! BUYING...")

                            success, qty, actual_price, order_id = self.trader.execute_buy(
                                sym, self.fixed_per_stock_budget
                            )

                            if success and qty > 0:
                                MonitorDB.record_buy_action(0, sym, actual_price, qty, base_price)
                                self.candidates[sym]['status'] = 'BOUGHT'
                                self.bought.append(sym)
                                print(f"      ✅ Bought {qty} shares @ ${actual_price:.2f}")
                        else:
                            # 已经买够了，停止监控这只
                            self.candidates[sym]['status'] = 'SKIPPED'

                    # 📉 跌幅 < -1% -> 标记为DROPPED
                    elif pct <= -0.01:
                        self.candidates[sym]['status'] = 'DROPPED'
                        print(f"   📉 {sym} dropped {pct * 100:.2f}% (score={score})")

            time.sleep(1)

        print("🏁 Opening Sniper finished.")
        self.quote_ctx.close()
        self.trader.ctx.close()

    def finalize_selection(self):
        """
        9:35时刻：
        1. 统计已买入的股票
        2. 从剩余WATCHING状态的股票中，按分数选择最高的几只（补齐到5只）
        3. 将这5只股票（已买入+剩余最高分）设置为APPROVED，其他所有设置为REJECTED
        4. 未买入的APPROVED股票设置为WATCHING，等待突破0.5%再买入
        """
        bought_count = len(self.bought)
        needed = MAX_STOCKS - bought_count

        print(f"\n{'=' * 60}")
        print(f"⏰ 9:35 Finalization - Lock in today's {MAX_STOCKS} trading targets")
        print(f"{'=' * 60}")
        print(f"📊 Already bought: {bought_count}/{MAX_STOCKS} stocks")

        # 已买入的股票
        approved_stocks = self.bought.copy()

        if needed > 0:
            print(f"🎯 Need to select {needed} more stocks to complete the lineup...")

            # 找出所有还在WATCHING状态的股票（未买入、未跌太多）
            remaining = [
                (sym, info['score'], info['base_price'])
                for sym, info in self.candidates.items()
                if info['status'] == 'WATCHING'
            ]

            # 按分数降序排序
            remaining.sort(key=lambda x: x[1], reverse=True)

            if remaining:
                # 选择分数最高的needed只
                selected = remaining[:needed]

                print(f"\n📈 Selecting top {len(selected)} by score:")
                for sym, score, base_price in selected:
                    approved_stocks.append(sym)
                    print(f"   ✅ {sym} (score={score:.1f}) - Will WATCH for 0.5% surge")

                    # 设置为WATCHING状态，等待突破0.5%
                    trigger_price = base_price * 1.005
                    virtual_sell = trigger_price / 1.002
                    MonitorDB.force_start_watching(sym, virtual_sell, base_price)
                    self.candidates[sym]['status'] = 'WATCHING_APPROVED'
            else:
                print(f"⚠️  No suitable stocks remaining to complete lineup")

        # 调用auto_select_daily_targets设置APPROVED/REJECTED
        print(f"\n🎯 Finalizing today's {len(approved_stocks)} APPROVED stocks...")
        MonitorDB.auto_select_daily_targets(approved_symbols=approved_stocks)

        print(f"\n✅ Today's trading lineup locked:")
        for i, sym in enumerate(approved_stocks, 1):
            status = "BOUGHT" if sym in self.bought else "WATCHING"
            print(f"   {i}. {sym} - {status}")

        # 将所有其他未处理的股票标记为DROPPED
        for sym, info in self.candidates.items():
            if info['status'] == 'WATCHING' and sym not in approved_stocks:
                self.candidates[sym]['status'] = 'DROPPED'
                print(f"   ❌ {sym} (score={info['score']:.1f}) - Not selected (REJECTED)")

        print(f"{'=' * 60}\n")

    def cleanup_remaining(self):
        """
        将所有还未处理的股票设置为WATCHING监控状态
        """
        for sym, info in self.candidates.items():
            if info['status'] == 'WATCHING':
                base_price = info['base_price']
                score = info['score']
                print(f"   👀 {sym} (score={score}) -> WATCHING")
                trigger_price = base_price * 1.005
                virtual_sell = trigger_price / 1.002
                MonitorDB.force_start_watching(sym, virtual_sell, base_price)
                self.candidates[sym]['status'] = 'WATCHING_SET'


if __name__ == "__main__":
    sniper = OpeningSniper()
    sniper.run()

# backend/opening_trader.py
import time
from datetime import datetime
import pytz
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT
from trader import QuantTrader
from db import get_approved_targets_for_today
from db_monitor import MonitorDB

SNIPER_END_TIME = "09:35"


class OpeningSniper:
    def __init__(self):
        print("🔫 Initializing Opening Sniper...")
        self.trader = QuantTrader()
        self.ctx = self.trader.ctx  # 交易连接 (查资产、下单)

        # 🔥 修复: 新增行情连接 (查股价)
        self.quote_ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)

        self.targets = {}
        self.fixed_per_stock_budget = 0.0

    def get_ny_time(self):
        ny_tz = pytz.timezone('America/New_York')
        return datetime.now(ny_tz).strftime("%H:%M")

    def calculate_fixed_budget(self):
        """
        🔥 基于总资产计算固定预算
        """
        # accinfo_query 属于交易接口，用 self.ctx 是对的
        ret, data = self.ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            print(f"❌ Failed to get account info: {data}")
            return False

        total_assets = data['total_assets'][0]

        target_count = len(self.targets)
        if target_count == 0: return False

        self.fixed_per_stock_budget = (total_assets / 1.2) / target_count

        print("=" * 40)
        print(f"💰 Account Total Assets: ${total_assets:.2f}")
        print(f"🎯 Target Count:        {target_count}")
        print(f"💵 FIXED Budget/Stock:   ${self.fixed_per_stock_budget:.2f} (Locked for today)")
        print("=" * 40)
        return True

    def prepare_targets(self):
        raw_targets = get_approved_targets_for_today()
        if not raw_targets: return False

        symbols = [t['symbol'] for t in raw_targets]

        # 🔥 修复: 使用 self.quote_ctx 获取快照
        ret, data = self.quote_ctx.get_market_snapshot([f"US.{s}" for s in symbols])
        if ret != RET_OK:
            print(f"❌ Market Snapshot Failed: {data}")
            return False

        for _, row in data.iterrows():
            sym = row['code'].split('.')[1]
            open_price = row['open_price']
            if open_price <= 0: open_price = row['last_price']

            self.targets[sym] = {
                'base_price': open_price,
                'status': 'PENDING'
            }
        return True

    def run(self):
        if not self.trader.unlock(): return

        # --- ⏳ 等待直到 09:29 进行选股 ---
        while self.get_ny_time() < "09:29":
            print(f"⏳ Waiting for 09:29 to select targets... (Current: {self.get_ny_time()})")
            time.sleep(10)

        print("🎲 Auto-selecting Top 5 Targets for today...")
        MonitorDB.auto_select_daily_targets()
        # -----------------------------------

        if not self.prepare_targets(): return

        # 1. 计算一次固定预算
        if not self.calculate_fixed_budget(): return

        print(f"🚀 Sniper started. Watching till {SNIPER_END_TIME}...")

        while True:
            current_time = self.get_ny_time()

            if current_time >= SNIPER_END_TIME:
                self.cleanup_remaining()
                break

            pending_syms = [s for s, info in self.targets.items() if info['status'] == 'PENDING']
            if not pending_syms: break

            # 🔥 修复: 使用 self.quote_ctx 获取快照
            ret, data = self.quote_ctx.get_market_snapshot([f"US.{s}" for s in pending_syms])

            if ret == RET_OK:
                for _, row in data.iterrows():
                    sym = row['code'].split('.')[1]
                    curr_price = row['last_price']
                    base_price = self.targets[sym]['base_price']

                    budget = self.fixed_per_stock_budget
                    pct = (curr_price - base_price) / base_price

                    # 📈 涨幅 > 0.5% (追涨)
                    if pct >= 0.005:
                        print(f"   🚀 {sym} surged! Buying with fixed budget ${budget:.2f}...")
                        success, qty, actual_price, order_id = self.trader.execute_buy(sym, budget)
                        if success and qty > 0:
                            # 🔥 立即同步数据库
                            MonitorDB.record_buy_action(0, sym, actual_price, qty, base_price)
                            self.targets[sym]['status'] = 'BOUGHT'

                    # 📉 跌幅 < -1% (放弃)
                    elif pct <= -0.01:
                        print(f"   ⚠️ {sym} dropped. Watching for reversal.")
                        virtual_sell = base_price * 0.99
                        MonitorDB.force_start_watching(sym, virtual_sell, base_price)
                        self.targets[sym]['status'] = 'SKIPPED'

            time.sleep(1)

        print("🏁 Opening Sniper finished.")
        # 🔥 记得关闭两个连接
        self.quote_ctx.close()
        self.trader.ctx.close()

    def cleanup_remaining(self):
        """9:35 还在震荡的，转为埋伏监控"""
        for sym, info in self.targets.items():
            if info['status'] == 'PENDING':
                base_price = info['base_price']
                print(f"   👀 {sym} Range Bound -> Switch to WATCHING (Ambush)")

                trigger_price = base_price * 1.005
                virtual_sell = trigger_price / 1.002

                MonitorDB.force_start_watching(sym, virtual_sell, base_price)
                self.targets[sym]['status'] = 'SKIPPED'


if __name__ == "__main__":
    sniper = OpeningSniper()
    sniper.run()
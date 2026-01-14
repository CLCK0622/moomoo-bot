# backend/backtest.py
import pandas as pd
from datetime import datetime, timedelta
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT
from trade_manager import StrategyLogic

# --- 回测配置 ---
# SYMBOLS = ['CSGP', 'TWLO', 'MDGL', 'MSTR', 'LVS'] # 猛跌股票
SYMBOLS = ['APLD', 'SNDK', 'BLDR', 'INTC', 'RGC'] # 猛涨股票
# SYMBOLS = ['COST', 'NVO', 'LLY', 'OKLO', 'FISV'] # 涨股票
# SYMBOLS = ['MU', 'PLTR', 'NVDA', 'GOOGL', 'INTC'] # 大股票
# SYMBOLS = ['MDGL', 'MSTR', 'LVS', 'APLD', 'SNDK'] # 综合股票 2涨 3跌
START_DATE = '2026-01-05'
END_DATE = '2026-01-06'
INITIAL_CASH = 100000.0

# 🔥 风控参数
MAX_LOSS_PER_STOCK = 200.0

class VirtualAccount:
    def __init__(self, cash):
        self.cash = cash
        self.initial_cash = cash
        self.positions = {}
        self.history = []
        self.daily_stock_realized_pnl = {}
        self.dead_symbols = set()

    def reset_daily_state(self):
        self.daily_stock_realized_pnl = {}
        self.dead_symbols = set()

    def mark_as_dead(self, symbol):
        self.dead_symbols.add(symbol)

    def is_dead(self, symbol):
        return symbol in self.dead_symbols

    def get_stock_daily_pnl(self, symbol, current_price):
        """计算当日总盈亏 (已实现 + 浮动)"""
        realized = self.daily_stock_realized_pnl.get(symbol, 0.0)
        unrealized = 0.0
        if symbol in self.positions:
            pos = self.positions[symbol]
            market_val = pos['qty'] * current_price
            cost_val = pos['qty'] * pos['cost']
            unrealized = market_val - cost_val
        return realized + unrealized

    def buy(self, time_str, symbol, price, qty):
        if symbol in self.dead_symbols: return False
        cost = price * qty
        if self.cash >= cost:
            self.cash -= cost
            if symbol not in self.positions:
                self.positions[symbol] = {'qty': 0, 'cost': 0, 'max_price': price, 'entry_count': 0}
            old_qty = self.positions[symbol]['qty']
            old_cost = self.positions[symbol]['cost']
            new_qty = old_qty + qty
            new_avg_cost = ((old_cost * old_qty) + cost) / new_qty
            self.positions[symbol]['qty'] = new_qty
            self.positions[symbol]['cost'] = new_avg_cost
            self.positions[symbol]['max_price'] = price
            self.positions[symbol]['entry_count'] += 1
            print(f"[{time_str}] 🔵 BUY  {symbol}: {qty} @ {price:.2f}")
            self.history.append({'time': time_str, 'action': 'BUY', 'symbol': symbol, 'price': price, 'qty': qty})
            return True
        return False

    def sell(self, time_str, symbol, price, reason):
        if symbol in self.positions:
            pos = self.positions[symbol]
            qty = pos['qty']
            revenue = price * qty
            profit = revenue - (pos['cost'] * qty)
            self.cash += revenue
            if symbol not in self.daily_stock_realized_pnl: self.daily_stock_realized_pnl[symbol] = 0.0
            self.daily_stock_realized_pnl[symbol] += profit
            print(f"[{time_str}] 🔴 SELL {symbol}: {qty} @ {price:.2f} (PnL: {profit:.2f}) [{reason}]")
            self.history.append(
                {'time': time_str, 'action': 'SELL', 'symbol': symbol, 'price': price, 'qty': qty, 'pnl': profit,
                 'reason': reason})
            del self.positions[symbol]
            return True
        return False


class BacktestEngine:
    def __init__(self):
        self.ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        self.account = VirtualAccount(INITIAL_CASH)
        self.daily_memory = {}

    def load_data(self, symbol):
        # 依然使用 K_1M，因为没有 Tick 接口
        ret, data, page_req_key = self.ctx.request_history_kline(
            f"US.{symbol}", start=START_DATE, end=END_DATE, ktype=KLType.K_1M, autype=AuType.QFQ
        )
        return data if ret == RET_OK else pd.DataFrame()

    def run(self):
        print(f"⏳ Loading data for {SYMBOLS}...")
        all_data = []
        for sym in SYMBOLS:
            df = self.load_data(sym)
            if not df.empty:
                df['symbol'] = sym
                all_data.append(df)
        if not all_data: return

        full_df = pd.concat(all_data)
        full_df['time_key'] = full_df['time_key'].astype(str)
        full_df = full_df.sort_values(by=['time_key', 'symbol'])
        grouped = full_df.groupby('time_key')

        print(f"🚀 Starting High-Fidelity Backtest (OHLC Logic)...")
        print(f"🛡️ Safety: Max Loss per Stock/Day = -${MAX_LOSS_PER_STOCK:.2f}")

        PER_STOCK_BUDGET = INITIAL_CASH / len(SYMBOLS)
        print(f"💰 Budget Allocation: ${PER_STOCK_BUDGET:.2f} per stock")

        current_date_str = ""
        last_prices = {}

        for time_str, group in grouped:
            date_str = time_str.split(' ')[0]
            hhmm = time_str.split(' ')[1][:5]

            # === 新的一天 ===
            if date_str != current_date_str:
                print(f"\n📅 === New Day: {date_str} ===")
                current_date_str = date_str
                self.daily_memory[date_str] = {}
                self.account.positions = {}
                self.account.reset_daily_state()

            for _, row in group.iterrows():
                sym = row['symbol']

                # 🔥 关键：获取 OHLC 四个价格
                open_p = row['open']
                close_p = row['close']
                high_p = row['high']
                low_p = row['low']

                # 在这一分钟内，我们假设顺序是 Open -> Low/High -> Close
                # 实际上我们同时检查 Low 和 High 触发的条件

                last_prices[sym] = close_p

                # --- 0. 熔断检查 ---
                # 使用 Low 来检查最坏情况的浮亏
                current_pnl_worst = self.account.get_stock_daily_pnl(sym, low_p)
                if not self.account.is_dead(sym) and current_pnl_worst < -MAX_LOSS_PER_STOCK:
                    print(f"🚨 [{sym}] MELT DOWN! Worst PnL ${current_pnl_worst:.2f}. STOP BUYING.")
                    self.account.mark_as_dead(sym)

                    if sym in self.account.positions:
                        pos = self.account.positions[sym]

                        # 🔥 核心修正：计算理论上的熔断价格
                        # 允许亏损额 = 预算 ($200) - 已实现盈亏 (可能是正的也可能是负的)
                        # 这里简单起见，假设主要亏损来自当前持仓
                        # 目标卖出价 = 成本 - (剩余允许亏损额 / 股数)
                        # 如果是第一笔就亏，就是 Cost - ($200 / Qty)

                        # 计算当前持仓在什么价格会触发 -$200
                        # PnL = (Price - Cost) * Qty = -MAX_LOSS
                        # Price = Cost - (MAX_LOSS / Qty)
                        limit_price = pos['cost'] - (MAX_LOSS_PER_STOCK / pos['qty'])

                        # 确定实际执行价格
                        # 情况 A: 开盘价就已经跌穿了 (Gap Down) -> 只能按 Open 卖
                        # 情况 B: 盘中跌穿的 (Open > Limit > Low) -> 按 Limit 卖 (模拟触价单)

                        if open_p < limit_price:
                            exec_price = open_p  # 跳空低开，惨案
                            note = "GAP_DOWN_CIRCUIT_BREAKER"
                        else:
                            exec_price = limit_price  # 盘中触达，按线执行
                            note = "CIRCUIT_BREAKER_LIMIT"

                        # 无论如何，执行价格不能优于 Open，也不能劣于 Low
                        # 加上一点点滑点 (比如 0.05%) 模拟真实世界的延迟
                        exec_price = max(low_p, min(open_p, exec_price * 0.9995))

                        actual_pnl = (exec_price - pos['cost']) * pos['qty']
                        print(
                            f"🚨 [{sym}] MELT DOWN! Triggered at ${limit_price:.2f}. Sold at ${exec_price:.2f}. PnL: ${actual_pnl:.2f}")

                        self.account.sell(time_str, sym, exec_price, note)

                        if sym in self.daily_memory[date_str]:
                            self.daily_memory[date_str][sym]['status'] = 'FINISHED'
                        continue

                # 初始化
                if sym not in self.daily_memory[date_str]:
                    self.daily_memory[date_str][sym] = {
                        'base_open': open_p, 'last_sell': 0, 'status': 'WATCHING' if hhmm < "09:30" else 'PENDING'
                    }
                memory = self.daily_memory[date_str][sym]
                base_open = memory['base_open']

                if hhmm < "09:30": continue

                # --- 1. 开盘狙击 (09:30-09:35) ---
                if sym not in self.account.dead_symbols and "09:30" <= hhmm <= "09:35":
                    if memory['status'] == 'PENDING':
                        # 检查 High 是否触发追涨
                        pct_high = (high_p - base_open) / base_open
                        # 检查 Low 是否触发放弃
                        pct_low = (low_p - base_open) / base_open

                        if pct_high > 0.005:
                            # 假设在 +1% 处成交
                            buy_price = base_open * 1.005
                            qty = int(PER_STOCK_BUDGET / buy_price)
                            if qty > 0 and self.account.buy(time_str, sym, buy_price, qty):
                                memory['status'] = 'HOLDING'
                        elif pct_low < -0.01:
                            memory['status'] = 'WATCHING'
                            memory['last_sell'] = base_open * 0.99
                            print(f"[{time_str}] ⚠️ {sym} Drop > 1% (Low hit {low_p}). Skip & Watch")

                    if hhmm == "09:35" and memory['status'] == 'PENDING':
                        trigger_price = base_open * 1.005
                        memory['status'] = 'WATCHING'
                        memory['last_sell'] = trigger_price / 1.002
                        print(f"[{time_str}] 👀 {sym} Range Bound -> Switch to WATCHING")

                # --- 2. 盘中监控 (卖出) ---
                if sym in self.account.positions:
                    pos = self.account.positions[sym]
                    if high_p > pos['max_price']: pos['max_price'] = high_p

                    if hhmm >= "15:55":
                        self.account.sell(time_str, sym, close_p, "EOD")
                        memory['status'] = 'FINISHED'
                        continue

                    # 🔥 核心修正：使用 Low 来检查止损
                    # 如果这一分钟的最低价触及了止损线，我们就认为止损触发了

                    # 为了复用 StrategyLogic，我们先用 Low 测一次
                    should_sell_hard, reason_hard = StrategyLogic.check_sell_signal(
                        current_price=low_p, base_open_price=base_open,
                        cost_price=pos['cost'], max_price_seen=pos['max_price']
                    )

                    if should_sell_hard:
                        # 计算理论卖出价
                        # 如果是硬止损，卖出价 = 成本 * 0.99
                        # 如果是移动止盈，卖出价 = 触发价
                        # 这里简化：如果是硬止损，就在硬止损线成交；否则在 Low 成交
                        exec_price = low_p
                        if "HARD_STOP" in reason_hard:
                            exec_price = pos['cost'] * 0.99
                        elif "PHASE1" in reason_hard:
                            # 估算触发价: max - buffer
                            buffer = base_open * 0.01
                            exec_price = pos['max_price'] - buffer

                        # 确保执行价格不优于 Low (保守估计)
                        exec_price = max(exec_price, low_p)

                        self.account.sell(time_str, sym, exec_price, reason_hard)
                        memory['status'] = 'WATCHING'
                        memory['last_sell'] = exec_price
                    else:
                        # 如果 Low 没触发，再检查 Close (常规检查)
                        # 这里其实不需要了，因为如果 Low 没触发，Close 肯定也没触发下跌类信号
                        # 但为了 Phase2 止盈 (可能 High 很高然后回落)，可以再检查一遍 Close
                        pass

                # --- 3. 盘中监控 (买入) ---
                elif not self.account.is_dead(sym) and memory['status'] == 'WATCHING' and hhmm < "15:50":
                    # 🔥 核心修正：使用 High 来检查突破
                    # 如果这一分钟的最高价 > 触发价，说明触发了买入

                    entry_count = len([x for x in self.account.history if
                                       x['symbol'] == sym and x['action'] == 'BUY' and x['time'].startswith(date_str)])

                    if 'max_price' not in memory: memory['max_price'] = base_open
                    if high_p > memory['max_price']: memory['max_price'] = high_p

                    # 用 High 去试探买入条件
                    should_buy, reason = StrategyLogic.check_buy_signal(
                        current_price=high_p, last_sell_price=memory['last_sell'],
                        last_sell_time=None, bid_vol=1000, ask_vol=500,
                        base_open_price=base_open, entry_count=entry_count,
                        max_price_seen=memory['max_price']
                    )

                    if should_buy:
                        # 计算成交价
                        # 突破买入通常是 Stop Buy，成交价 = 触发价
                        # 触发价 = last_sell * 1.002
                        trigger_price = memory['last_sell'] * 1.001
                        # 确保不超过这一分钟的 High
                        exec_price = min(trigger_price, high_p)

                        qty = int(PER_STOCK_BUDGET / exec_price)

                        if qty > 0 and self.account.buy(time_str, sym, exec_price, qty):
                            memory['status'] = 'HOLDING'

        print("\n" + "=" * 40)
        print("🛑 Backtest Finished. Calculating Equity...")
        total_equity = self.account.cash
        for sym, pos in self.account.positions.items():
            # 使用最后已知的价格来计算市值
            last_price = last_prices.get(sym, pos['cost'])
            market_val = pos['qty'] * last_price
            total_equity += market_val
            print(f"   💼 Holding {sym}: {pos['qty']} shares @ ${last_price:.2f} = ${market_val:.2f}")

        final_pnl = total_equity - self.account.initial_cash
        print("-" * 40)
        print(f"💰 Cash Balance:  ${self.account.cash:.2f}")
        print(f"📦 Stock Value:   ${(total_equity - self.account.cash):.2f}")
        print(f"💵 Total Equity:  ${total_equity:.2f}")
        print(f"📈 TRUE PnL:      ${final_pnl:.2f} ({final_pnl / self.account.initial_cash * 100:.2f}%)")
        print("=" * 40)

        self.ctx.close()

if __name__ == "__main__":
    eng = BacktestEngine()
    eng.run()
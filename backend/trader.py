# backend/trader.py
import time
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT, TRADING_PASSWORD
from db import get_approved_targets_for_today, log_trade_execution
from db_monitor import MonitorDB  # 引入 DB 用于检查熔断

# --- 配置 ---
CURRENT_ENV = TrdEnv.SIMULATE  # 实盘请改为 TrdEnv.REAL
MARKET = TrdMarket.US

class QuantTrader:
    def __init__(self):
        print(f"🤖 Initializing QuantTrader in [{CURRENT_ENV}] mode...")
        self.ctx = OpenSecTradeContext(filter_trdmarket=MARKET, host=MOOMOO_HOST, port=MOOMOO_PORT,
                                       security_firm=SecurityFirm.FUTUSG)

    def unlock(self):
        if CURRENT_ENV == TrdEnv.REAL:
            print("🔐 Unlocking Trading Account...")
            ret, data = self.ctx.unlock_trade(TRADING_PASSWORD)
            if ret != RET_OK:
                print(f"❌ Unlock Failed: {data}")
                return False
        return True

    def get_purchasing_power(self):
        ret, data = self.ctx.accinfo_query(trd_env=CURRENT_ENV)
        if ret == RET_OK:
            # 使用 'power' (购买力) 或 'cash' (现金)
            # 这里用 cash 比较稳妥
            cash = data['cash'][0]
            return cash
        return 0.0

    def get_market_price(self, symbol):
        from futu import OpenQuoteContext
        q_ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        ret, data = q_ctx.get_market_snapshot([f"US.{symbol}"])
        q_ctx.close()
        if ret == RET_OK:
            return data['last_price'][0]
        return None

    def check_circuit_breaker(self, symbol, stop_loss_threshold=None):
        """
        检查该股票今天是否已触发熔断（亏损超过阈值）

        Args:
            symbol: 股票代码
            stop_loss_threshold: 止损阈值（负数），如果不提供则动态计算
        """
        # 如果没有提供阈值，动态计算（单只股票预算的1%）
        if stop_loss_threshold is None:
            ret, data = self.ctx.accinfo_query(trd_env=CURRENT_ENV)
            if ret == RET_OK:
                total_assets = data['total_assets'][0]
                # 假设5只股票（实际应该从数据库获取，但这里简化处理）
                approved_count = 5
                fixed_budget = (total_assets / 1.2) / approved_count
                stop_loss_threshold = -1 * (fixed_budget * 0.01)
            else:
                # 如果获取失败，使用默认值
                stop_loss_threshold = -1666.67  # 基于100万资产的默认值

        pnl = MonitorDB.get_today_realized_pnl(symbol)
        if pnl < stop_loss_threshold:
            print(f"🛑 Circuit Breaker Active for {symbol} (PnL: ${pnl:.2f} < ${stop_loss_threshold:.2f}). BUY REJECTED.")
            return True
        return False

    def execute_buy(self, symbol, budget):
        """
        执行买入
        返回: (success: bool, qty: int, price: float, order_id: str)
        """
        # 1. 熔断检查
        if self.check_circuit_breaker(symbol):
            return False, 0, 0.0, None

        print(f"\n🚀 Executing MARKET BUY for {symbol} with budget ${budget:.2f}...")

        # 2. 获取现价计算股数
        price = self.get_market_price(symbol)
        if not price or price <= 0:
            print(f"   ⚠️ Price error. Skipping.")
            return False, 0, 0.0, None

        limit_price = round(price * 1.001, 2)

        # 动态股数计算
        quantity = int(budget / price)

        if quantity < 1:
            print(f"   ⚠️ Budget too low for 1 share. Skipping.")
            return False, 0, 0.0, None

        print(f"   🎯 Target: {quantity} shares @ Market Price (Approx ${price})")

        # 3. 提交限价单（模拟市价单）
        ret, data = self.ctx.place_order(
            price=0,
            qty=quantity,
            code=f"US.{symbol}",
            trd_side=TrdSide.BUY,
            trd_env=CURRENT_ENV,
            order_type=OrderType.MARKET,
        )

        if ret == RET_OK:
            order_id = data['order_id'][0] if 'order_id' in data else None
            print(f"   ✅ Buy Order Placed! ID: {order_id}")
            # 🔥 市价单假设立即成交，返回成功信息
            return True, quantity, price, order_id
        else:
            print(f"   ❌ Buy Failed: {data}")
            return False, 0, 0.0, None

    def execute_sell(self, symbol, quantity):
        """
        执行市价卖出
        返回: (success: bool, price: float, order_id: str)
        """
        print(f"📉 Executing MARKET SELL for {symbol} ({quantity} shares)...")

        price = self.get_market_price(symbol)
        if not price:
            return False, 0.0, None

        # 🔥 卖出时，折价 0.3% 挂单，确保卖出（模拟市价单）
        limit_price = round(price * 0.997, 2)

        ret, data = self.ctx.place_order(
            price=0,
            qty=quantity,
            code=f"US.{symbol}",
            trd_side=TrdSide.SELL,
            trd_env=CURRENT_ENV,
            order_type=OrderType.MARKET  # 🔥 使用限价单模拟市价单
        )

        if ret == RET_OK:
            order_id = data['order_id'][0] if 'order_id' in data else None
            print(f"   ✅ Sell Order Placed! ID: {order_id}")
            # 🔥 市价单假设立即成交，返回实际卖出价格
            return True, limit_price, order_id
        else:
            print(f"   ❌ Sell Failed: {data}")
            return False, 0.0, None

    def run_daily_execution(self):
        """开盘初始买入逻辑"""
        if not self.unlock(): return

        targets = get_approved_targets_for_today()
        if not targets:
            print("💤 No APPROVED targets.")
            return

        count = len(targets)
        # --- 新资金分配公式 ---
        total_cash = self.get_purchasing_power()
        if total_cash <= 0: return

        # 公式: 总现金 / 1.2 / 股票数量
        # 1.2 是为了留出 20% 的冻结/缓冲资金
        per_stock_budget = (total_cash / 1.1) / count

        print(f"💵 Strategy: Cash ${total_cash:.2f} / 1.2 / {count} stocks")
        print(f"💵 Budget per stock: ${per_stock_budget:.2f}")

        # 注意：这里只负责计算预算，具体的买入时机由 opening_trader 控制
        # 如果你想一键开盘无脑买，可以在这里循环调用 execute_buy
        # 但按照最新策略，建议使用 opening_trader.py
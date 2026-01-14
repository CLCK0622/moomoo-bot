# backend/monitor.py
import time
from datetime import datetime
import pytz
import threading
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT
from trader import QuantTrader
from db_monitor import MonitorDB
from trade_manager import StrategyLogic
import run_analysis
from opening_trader import OpeningSniper
from price_cache import PriceCache  # 🔥 实时价格缓存

# --- 配置 ---
EOD_TIME = "15:55"  # 收盘强平时间 (美东)
ANALYSIS_TIME = (6, 0)  # 06:00 美东 - DailyCandidate 分析时间
SNIPER_TIME = (9, 25)  # 09:25 美东


def start_analysis_scheduler():
    """后台线程每天 07:00(美东) 触发一次分析，不阻塞监控。"""
    ny_tz = pytz.timezone('America/New_York')

    def _worker():
        last_run_date = None
        while True:
            now = datetime.now(ny_tz)
            # 仅在 06:00 当天首次触发
            if (now.hour, now.minute) >= ANALYSIS_TIME and last_run_date != now.date():
                print("🧠 Auto analysis starting (NY 06:00)...")
                try:
                    run_analysis.main()
                    print("✅ Auto analysis finished.")
                except Exception as e:
                    print(f"❌ Auto analysis failed: {e}")
                last_run_date = now.date()
            time.sleep(30)

    threading.Thread(target=_worker, daemon=True).start()


def start_sniper_scheduler():
    """后台线程每天 09:25(美东) 启动开盘狙击，不阻塞监控。"""
    ny_tz = pytz.timezone('America/New_York')

    def _worker():
        last_run_date = None
        while True:
            now = datetime.now(ny_tz)
            if (now.hour, now.minute) >= SNIPER_TIME and last_run_date != now.date():
                print("🔫 Auto OpeningSniper starting (NY 09:25)...")
                try:
                    OpeningSniper().run()
                    print("✅ OpeningSniper finished.")
                except Exception as e:
                    print(f"❌ OpeningSniper failed: {e}")
                last_run_date = now.date()
            time.sleep(30)

    threading.Thread(target=_worker, daemon=True).start()


def get_market_data(quote_ctx, symbols):
    """批量获取报价和摆盘"""
    # 1. 实时报价
    ret_q, data_q = quote_ctx.get_market_snapshot([f"US.{s}" for s in symbols])
    quotes = {}
    if ret_q == RET_OK:
        for _, row in data_q.iterrows():
            # 提取代码 GOOGL (US.GOOGL -> GOOGL)
            sym = row['code'].split('.')[1]
            quotes[sym] = row['last_price']

        # 🔥 立即将价格写入缓存，供Dashboard无延迟读取
        PriceCache.update_prices(quotes)

    # 2. 摆盘数据 (为了计算买卖压力)
    # 注意：get_order_book 可能比较慢，如果关注股票多，建议多线程或减少频率
    books = {}
    for sym in symbols:
        ret_b, data_b = quote_ctx.get_order_book(f"US.{sym}", num=5)  # 取前5档
        if ret_b == RET_OK:
            # 计算前5档的总量
            bid_vol = data_b['Bid'].sum()['volume']
            ask_vol = data_b['Ask'].sum()['volume']
            books[sym] = (bid_vol, ask_vol)
        else:
            books[sym] = (0, 0)

    return quotes, books


def is_market_closing():
    """检查是否到了收盘时间 (美东 15:55)"""
    ny_tz = pytz.timezone('America/New_York')
    now_ny = datetime.now(ny_tz)
    current_time = now_ny.strftime("%H:%M")
    return current_time >= EOD_TIME


def run_monitor_loop():
    print("👀 Starting Monitor Daemon...")

    # 启动 07:00 分析调度
    start_analysis_scheduler()
    # 启动 09:25 开盘狙击调度
    start_sniper_scheduler()

    # 初始化交易员 (用于下单)
    trader = QuantTrader()

    approved_count = 5  # 默认值

    acc_ret, acc_data = trader.ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)  # 统一用模拟盘
    fixed_budget = 0.0
    if acc_ret == RET_OK:
        total_assets = acc_data['total_assets'][0]
        fixed_budget = (total_assets / 1.2) / approved_count
        print(f"💵 Monitor Fixed Budget per stock: ${fixed_budget:.2f}")
    else:
        print("⚠️ Failed to fetch assets, using fallback budget $10000")
        fixed_budget = 10000.0

    # 🔥 止损阈值 = 单只股票预算的1%
    stop_loss_threshold = -1 * (fixed_budget * 0.01)
    print(f"🛡️  Stop Loss Threshold per stock: ${stop_loss_threshold:.2f} (1% of budget)")

    # 初始化行情连接 (用于查价)
    quote_ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)

    try:
        while True:
            # 1. 获取所有活跃的监控任务
            monitors = MonitorDB.get_active_monitors()
            if not monitors:
                print("💤 No active monitors. Waiting...")
                time.sleep(5)
                continue

            symbols = [m['symbol'] for m in monitors]

            # 2. 获取实时数据
            realtime_prices, order_books = get_market_data(quote_ctx, symbols)

            # 检查是否收盘强平
            if is_market_closing():
                print("🚨 MARKET CLOSING! FORCE SELLING ALL POSITIONS!")
                for m in monitors:
                    if m['status'] == 'HOLDING':
                        success, sell_price, order_id = trader.execute_sell(m['symbol'], m['quantity'])
                        if success:
                            # 🔥 立即同步数据库
                            MonitorDB.record_sell_action(m['monitor_id'], m['position_id'], sell_price, "EOD")
                    MonitorDB.force_finish_all(m['symbol'])
                break  # 退出循环

            # 4. 遍历处理每个股票
            for m in monitors:
                sym = m['symbol']
                curr_price = realtime_prices.get(sym)

                # 🔥 修正 1: 获取买卖盘数据 (Bid/Ask Volume)
                # order_books 是 get_market_data 返回的字典 {sym: (bid, ask)}
                bid_vol, ask_vol = order_books.get(sym, (0, 0))

                if not curr_price: continue

                print(f"   🔎 Checking {sym}: ${curr_price} [{m['status']}]")

                # --- 0. 熔断检查 (Circuit Breaker) ---
                # 获取该股票今日已实现盈亏 + 当前浮动盈亏
                # 注意：这里需要传入当前持仓数量和成本，如果是 WATCHING 状态则为 0
                curr_qty = m['quantity'] if m['status'] == 'HOLDING' else 0
                curr_cost = m['buy_price'] if m['status'] == 'HOLDING' else 0

                today_pnl = MonitorDB.get_stock_total_pnl(sym, curr_price, curr_qty, curr_cost)

                # 🔥 熔断阈值 = 单只股票预算的1%
                if today_pnl < stop_loss_threshold:
                    print(f"🚨 [{sym}] MELT DOWN! PnL ${today_pnl:.2f} < ${stop_loss_threshold:.2f}. FORCE CLOSING.")
                    if m['status'] == 'HOLDING':
                        success, sell_price, order_id = trader.execute_sell(sym, m['quantity'])
                        if success:
                            MonitorDB.record_sell_action(m['monitor_id'], m['position_id'], sell_price, "CIRCUIT_BREAKER")
                    MonitorDB.force_finish_all(sym)  # 标记为 FINISHED
                    continue

                # =========================================
                # 场景 A: 持仓中 (HOLDING) -> 检查卖出
                # =========================================
                if m['status'] == 'HOLDING':
                    # A1. 实时更新最高价
                    if curr_price > m['max_price']:
                        MonitorDB.update_max_price(m['monitor_id'], curr_price)
                        m['max_price'] = curr_price

                        # A2. 调用卖出逻辑
                    should_sell, reason = StrategyLogic.check_sell_signal(
                        current_price=curr_price,
                        base_open_price=m['base_open'],
                        cost_price=m['buy_price'],
                        max_price_seen=m['max_price']
                    )

                    if should_sell:
                        print(f"   💥 SELL SIGNAL for {sym}: {reason}")
                        # 执行卖出
                        success, sell_price, order_id = trader.execute_sell(sym, m['quantity'])
                        if success:
                            # 🔥 立即同步数据库
                            MonitorDB.record_sell_action(m['monitor_id'], m['position_id'], sell_price, reason)

                # =========================================
                # 场景 B: 空仓监控 (WATCHING) -> 检查买回
                # 🔥 注意：FINISHED状态的股票不会进入这里，因为get_active_monitors只返回isActive=true的股票
                # 当PHASE2止盈后，股票会被标记为FINISHED，今日不再交易
                # =========================================
                elif m['status'] == 'WATCHING':
                    # 🔥 修正 2: 更新参数调用 (匹配最新的 StrategyLogic)
                    # 我们需要 entry_count 来判断是否需要逼近前高
                    # 这里的 entry_count 最好从 m['entryCount'] (数据库字段) 获取，
                    # 刚才的 SQL 查询里没查这个字段，建议在 get_active_monitors 里加上
                    # 这里先假设 SQL 已经加上了 entryCount (下标需确认)
                    entry_count = m.get('entryCount', 0)

                    should_buy, reason = StrategyLogic.check_buy_signal(
                        current_price=curr_price,
                        last_sell_price=m['last_sell'],
                        last_sell_time=None,  # 实盘暂不校验时间，或传入 datetime.now()
                        bid_vol=bid_vol,  # 🔥 传入刚才获取的 bid
                        ask_vol=ask_vol,  # 🔥 传入刚才获取的 ask
                        base_open_price=m['base_open'],
                        entry_count=entry_count,
                        max_price_seen=m['max_price']
                    )

                    if should_buy:
                        print(f"   🔥 RE-ENTRY SIGNAL for {sym}: {reason}")

                        # 重新计算固定预算 (复用 fixed_budget)
                        # 如果 fixed_budget 没定义，就在循环外定义好
                        current_cash = trader.get_purchasing_power()
                        actual_budget = min(fixed_budget, current_cash)  # fixed_budget 需要在循环外计算好

                        if actual_budget > 0:
                            success, qty, buy_price, order_id = trader.execute_buy(sym, actual_budget)
                            if success and qty > 0:
                                # 🔥 立即同步数据库
                                MonitorDB.record_buy_action(m['monitor_id'], sym, buy_price, qty, m['base_open'])

            # 5. 休息
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("🛑 Monitor stopped by user.")
    except Exception as e:
        print(f"❌ Monitor Error: {e}")
    finally:
        quote_ctx.close()
        # trader.ctx.close() # 在 trader 内部处理


if __name__ == "__main__":
    run_monitor_loop()
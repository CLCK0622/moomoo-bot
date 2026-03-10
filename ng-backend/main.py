"""
ORB + Keltner Channel 美股日内交易策略
主程序入口

策略说明：
- 交易时段：美东时间 09:30 - 16:00
- 开仓条件：09:45后，基于ORB突破、VWAP、Keltner Channel
- 风险控制：3%账户止损、多级止盈、趋势反转检测
- 资金管理：最多5只股票，每只1/5预算除以1.2（市价单冻结）
- 收盘清仓：15:55强制平仓
"""
import logging
import json
import time
from datetime import datetime, timedelta
from typing import List
import signal
import sys

import config
from trader import MoomooTrader
from state_manager import StateManager
from strategy import ORBKeltnerStrategy

# 配置日志
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def load_watchlist() -> List[str]:
    """
    从 watchlist.json 加载监控股票列表

    Returns:
        股票代码列表
    """
    try:
        with open(config.WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            symbols = data.get('symbols', [])
            logger.info(f"加载监控列表: {len(symbols)} 只股票 - {symbols}")
            return symbols
    except Exception as e:
        logger.error(f"加载 watchlist.json 失败: {e}")
        return []


def is_market_open(current_time: datetime) -> bool:
    """
    检查当前是否在交易时段

    Args:
        current_time: 当前时间（美东时间）

    Returns:
        是否在交易时段
    """
    current_time_only = current_time.time()
    return config.MARKET_OPEN_TIME <= current_time_only <= config.MARKET_CLOSE_TIME


def is_after_orb_period(current_time: datetime) -> bool:
    """
    检查是否已过 ORB 计算时间（09:45）

    Args:
        current_time: 当前时间（美东时间）

    Returns:
        是否已过09:45
    """
    return current_time.time() >= config.ORB_END_TIME


def is_force_close_time(current_time: datetime) -> bool:
    """
    检查是否到达强制平仓时间（15:55）

    Args:
        current_time: 当前时间（美东时间）

    Returns:
        是否需要强制平仓
    """
    return current_time.time() >= config.FORCE_CLOSE_TIME


def main():
    """主程序"""
    logger.info("="*60)
    logger.info("ORB + Keltner Channel 策略启动")
    logger.info("="*60)

    # 注册信号处理，捕获外部的 SIGTERM (kill) 以便排查无故退出
    def handle_sigterm(signum, frame):
        logger.warning(f"收到终止信号 ({signum})，准备安全退出并清理资源...")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # 加载监控列表
    watchlist = load_watchlist()
    if not watchlist:
        logger.error("监控列表为空，程序退出")
        return

    # 初始化组件
    trader = MoomooTrader()
    state_manager = StateManager()
    strategy = ORBKeltnerStrategy(trader, state_manager)

    # 连接到 Moomoo OpenD
    if not trader.connect():
        logger.error("无法连接到 Moomoo OpenD，程序退出")
        return

    # 添加股票到状态管理器
    for symbol in watchlist:
        state_manager.add_symbol(symbol)

    # 订阅K线数据
    formatted_symbols = [strategy.format_symbol(s) for s in watchlist]
    if not trader.subscribe_kline(formatted_symbols, [config.BAR_1M, config.BAR_15M]):
        logger.error("K线订阅失败，程序退出")
        trader.disconnect()
        return

    logger.info("初始化完成，开始监控...")

    # 标记变量
    orb_calculated = False      # ORB 是否已计算
    force_closed = False        # 是否已强制平仓
    daily_total_cash = None     # 当日初始可用资金

    # ===== 节流控制：避免触发 Moomoo OpenD API 频率限制 =====
    # watchlist 有 61 只股票，每次全量刷新 K 线 = 122 次 API 调用
    # K 线数据按 60 秒间隔更新（1m K 线本身就是 60 秒才变化一次）
    KLINE_UPDATE_INTERVAL = 60   # K 线更新间隔（秒）
    last_kline_update = 0.0      # 上次 K 线更新的时间戳

    try:
        while True:
            # 获取当前时间（美东时间）
            current_time = datetime.now(config.ET_TIMEZONE)
            now_ts = time.time()

            # 检查是否在交易时段
            if not is_market_open(current_time):
                logger.info(f"当前时间 {current_time.strftime('%H:%M:%S')} 不在交易时段，等待...")
                daily_total_cash = None  # 跨日重置
                orb_calculated = False   # 跨日重置
                force_closed = False     # 跨日重置
                last_kline_update = 0.0  # 跨日重置
                time.sleep(60)
                continue
                
            # 每天在交易时段首次执行时获取一次资金
            if daily_total_cash is None:
                daily_total_cash = trader.get_account_cash()
                if daily_total_cash <= 0:
                    logger.error("获取账户资金失败或资金为0，10秒后重试")
                    time.sleep(10)
                    continue
                logger.info(f"已获取当日可用本金: ${daily_total_cash:.2f}")

            # ===== K 线更新（每 60 秒一次）=====
            if now_ts - last_kline_update >= KLINE_UPDATE_INTERVAL:
                for symbol in watchlist:
                    strategy.update_kline_data(symbol)
                last_kline_update = now_ts
                logger.debug(f"K线数据已更新（{len(watchlist)} 只股票）")

            # 检查挂单状态
            for symbol in watchlist:
                strategy.check_pending_orders(symbol)

            # 09:45 计算并锁定 ORB
            if is_after_orb_period(current_time) and not orb_calculated:
                logger.info("09:45 开始计算 ORB...")
                for symbol in watchlist:
                    strategy.calculate_orb(symbol, current_time)
                orb_calculated = True

            # 15:55 强制平仓
            if is_force_close_time(current_time) and not force_closed:
                strategy.force_close_all()
                force_closed = True
                logger.info("收盘清仓完成，程序即将退出")
                break

            # 使用开盘初次获取的资金进行开仓计算
            total_cash = daily_total_cash

            # 检查开仓信号（只检查空仓的股票）
            if is_after_orb_period(current_time) and not force_closed:
                idle_symbols = state_manager.get_idle_symbols()

                for symbol in idle_symbols:
                    # 检查是否还能开新仓
                    if not state_manager.can_open_new_position():
                        break

                    # 检查开仓信号
                    if strategy.check_entry_signal(symbol):
                        strategy.execute_entry(symbol, total_cash)

            # 检查所有持仓的退出信号
            active_positions = state_manager.get_active_positions()
            for symbol in active_positions.keys():
                # 检查止损止盈
                strategy.check_exit_signals(symbol)

                # 检查风险控制
                strategy.check_risk_control(symbol)

            # 日志：当前状态
            active_count = len(state_manager.get_active_positions())
            logger.info(f"当前时间: {current_time.strftime('%H:%M:%S')}, 活跃持仓: {active_count}/{config.MAX_POSITIONS}")

            # 每3秒检查一次
            time.sleep(3)

    except KeyboardInterrupt:
        logger.info("接收到停止信号，程序退出...")

    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)

    finally:
        # 清理资源
        logger.info("断开连接...")
        trader.disconnect()
        logger.info("策略已停止")


if __name__ == '__main__':
    main()

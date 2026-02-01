"""
策略核心逻辑模块
整合指标计算、信号生成、状态管理和交易执行
"""
import logging
from datetime import datetime
from typing import Dict, Optional
import pandas as pd

import config
from indicators import TechnicalIndicators, SignalGenerator
from state_manager import StateManager, PositionState
from trader import MoomooTrader

logger = logging.getLogger(__name__)


class ORBKeltnerStrategy:
    """ORB + Keltner Channel 多头策略"""

    def __init__(self, trader: MoomooTrader, state_manager: StateManager):
        """
        初始化策略

        Args:
            trader: Moomoo 交易接口
            state_manager: 状态管理器
        """
        self.trader = trader
        self.state_manager = state_manager
        self.indicators = TechnicalIndicators()
        self.signal_gen = SignalGenerator()

        # 缓存数据
        self.kline_cache_1m: Dict[str, pd.DataFrame] = {}
        self.kline_cache_15m: Dict[str, pd.DataFrame] = {}

        logger.info("策略初始化完成")

    def format_symbol(self, symbol: str) -> str:
        """
        格式化股票代码为 Moomoo 格式

        Args:
            symbol: 原始代码 (如 'AAPL')

        Returns:
            格式化后的代码 (如 'US.AAPL')
        """
        if not symbol.startswith('US.'):
            return f'US.{symbol}'
        return symbol

    def update_kline_data(self, symbol: str):
        """
        更新股票的K线数据

        Args:
            symbol: 股票代码
        """
        formatted_symbol = self.format_symbol(symbol)

        # 获取1分钟K线
        df_1m = self.trader.get_kline(formatted_symbol, config.BAR_1M, num=200)
        if df_1m is not None and not df_1m.empty:
            df_1m.index = pd.to_datetime(df_1m['time_key'])
            self.kline_cache_1m[symbol] = df_1m

        # 获取15分钟K线
        df_15m = self.trader.get_kline(formatted_symbol, config.BAR_15M, num=100)
        if df_15m is not None and not df_15m.empty:
            df_15m.index = pd.to_datetime(df_15m['time_key'])
            self.kline_cache_15m[symbol] = df_15m

    def calculate_orb(self, symbol: str, current_time: datetime) -> bool:
        """
        计算并锁定 ORB 数据（09:45执行）

        Args:
            symbol: 股票代码
            current_time: 当前时间

        Returns:
            是否成功锁定 ORB
        """
        position = self.state_manager.get_position(symbol)
        if position is None or position.orb_locked:
            return False

        # 检查是否到达 09:45
        if current_time.time() < config.ORB_END_TIME:
            return False

        # 获取1分钟数据计算 ORB
        df_1m = self.kline_cache_1m.get(symbol)
        if df_1m is None or df_1m.empty:
            return False

        # 计算 ORB（09:30-09:45）
        orb_result = self.indicators.calculate_orb(df_1m, '09:30', '09:45')

        if orb_result:
            position.set_orb(
                orb_high=orb_result['high'],
                orb_low=orb_result['low'],
                orb_mid=orb_result['mid']
            )
            logger.info(f"{symbol} ORB 已锁定: High={orb_result['high']:.2f}, Low={orb_result['low']:.2f}, Mid={orb_result['mid']:.2f}")
            return True

        return False

    def check_entry_signal(self, symbol: str) -> bool:
        """
        检查开仓信号

        Args:
            symbol: 股票代码

        Returns:
            是否触发开仓信号
        """
        position = self.state_manager.get_position(symbol)

        # 前置条件检查
        if position is None or position.state != config.STATE_IDLE:
            return False

        if not position.orb_locked:
            return False

        if not self.state_manager.can_open_new_position():
            return False

        # 获取数据
        df_1m = self.kline_cache_1m.get(symbol)
        df_15m = self.kline_cache_15m.get(symbol)

        if df_1m is None or df_15m is None or df_1m.empty or df_15m.empty:
            return False

        # 获取当前价格
        current_price = self.trader.get_current_price(self.format_symbol(symbol))
        if current_price is None:
            return False

        # 计算指标
        vwap = self.indicators.calculate_vwap(df_1m).iloc[-1]

        kc_upper, kc_middle, kc_lower = self.indicators.calculate_keltner_channels(
            df_15m,
            ema_period=config.KC_EMA_PERIOD,
            atr_period=config.ATR_PERIOD,
            multiplier=config.KC_ATR_MULTIPLIER
        )

        if kc_upper.empty or kc_middle.empty:
            return False

        bar_15m_close = df_15m['close'].iloc[-1]

        # 检查开仓信号
        signal = self.signal_gen.check_long_entry(
            current_price=current_price,
            orb_high=position.orb_high,
            vwap=vwap,
            kc_upper=kc_upper.iloc[-1],
            kc_middle=kc_middle.iloc[-1],
            bar_15m_close=bar_15m_close
        )

        if signal:
            logger.info(f"{symbol} 触发开仓信号: 价格={current_price:.2f}, VWAP={vwap:.2f}, KC_Upper={kc_upper.iloc[-1]:.2f}, KC_Middle={kc_middle.iloc[-1]:.2f}")

        return signal

    def execute_entry(self, symbol: str, total_cash: float) -> bool:
        """
        执行开仓

        Args:
            symbol: 股票代码
            total_cash: 总资金

        Returns:
            是否成功开仓
        """
        position = self.state_manager.get_position(symbol)
        if position is None:
            return False

        # 计算买入金额：总资金 * (1/5) / 1.2
        buy_amount = (total_cash * config.POSITION_SIZE_RATIO) / config.MARGIN_FREEZE_RATIO

        logger.info(f"{symbol} 准备开仓，买入金额: ${buy_amount:.2f}")

        # 市价买入
        order_id = self.trader.market_buy(self.format_symbol(symbol), buy_amount)

        if order_id:
            # 获取当前价格作为开仓价
            current_price = self.trader.get_current_price(self.format_symbol(symbol))
            if current_price:
                quantity = int(buy_amount / current_price)
                position.open_position(
                    price=current_price,
                    quantity=quantity,
                    time=datetime.now()
                )
                self.state_manager.increment_opened_count()
                logger.info(f"{symbol} 开仓成功: 价格={current_price:.2f}, 数量={quantity}")
                return True

        return False

    def check_exit_signals(self, symbol: str):
        """
        检查所有退出信号（止损、止盈、趋势反转）

        Args:
            symbol: 股票代码
        """
        position = self.state_manager.get_position(symbol)

        # 只处理持仓状态
        if position is None or position.state not in [config.STATE_POSITION, config.STATE_HALF_PROFIT]:
            return

        if position.quantity <= 0:
            return

        # 获取数据
        df_15m = self.kline_cache_15m.get(symbol)
        if df_15m is None or df_15m.empty:
            return

        current_price = self.trader.get_current_price(self.format_symbol(symbol))
        if current_price is None:
            return

        # 更新浮亏
        position.update_drawdown(current_price)

        # 计算指标
        kc_upper, kc_middle, kc_lower = self.indicators.calculate_keltner_channels(
            df_15m,
            ema_period=config.KC_EMA_PERIOD,
            atr_period=config.ATR_PERIOD,
            multiplier=config.KC_ATR_MULTIPLIER
        )

        atr = self.indicators.calculate_atr(df_15m, config.ATR_PERIOD)

        if kc_middle.empty or atr.empty:
            return

        # 场景1：初始止损（跌破 ORB_Mid）
        if self.signal_gen.check_stop_loss(current_price, position.orb_mid):
            logger.warning(f"{symbol} 触发止损: 价格={current_price:.2f} < ORB_Mid={position.orb_mid:.2f}")
            self.execute_exit(symbol, position.quantity, "止损")
            return

        # 场景2：第一目标止盈（TP1）
        if position.state == config.STATE_POSITION and not position.tp1_triggered:
            if self.signal_gen.check_tp1(current_price, position.entry_price, position.orb_mid):
                logger.info(f"{symbol} 触发 TP1: 价格={current_price:.2f}")
                reduce_qty = int(position.quantity * config.TP1_REDUCE_RATIO)
                self.execute_exit(symbol, reduce_qty, "TP1减仓")
                position.tp1_triggered = True
                position.state = config.STATE_HALF_PROFIT
                return

        # 场景3：第二目标止盈（TP2）
        if position.state == config.STATE_HALF_PROFIT and not position.tp2_triggered:
            if self.signal_gen.check_tp2(current_price, kc_middle.iloc[-1], atr.iloc[-1], config.TP2_ATR_MULTIPLIER):
                logger.info(f"{symbol} 触发 TP2: 价格={current_price:.2f}")
                self.execute_exit(symbol, position.quantity, "TP2全平")
                position.tp2_triggered = True
                return

        # 场景4：趋势反转（连续2根15分钟K线跌破KC中轨）
        if self.signal_gen.check_trend_reversal(df_15m, kc_middle, config.TREND_REVERSAL_BARS):
            logger.warning(f"{symbol} 触发趋势反转信号")
            self.execute_exit(symbol, position.quantity, "趋势反转")
            return

    def execute_exit(self, symbol: str, quantity: int, reason: str):
        """
        执行平仓

        Args:
            symbol: 股票代码
            quantity: 平仓数量
            reason: 平仓原因
        """
        if quantity <= 0:
            return

        position = self.state_manager.get_position(symbol)
        if position is None:
            return

        logger.info(f"{symbol} 执行平仓: 数量={quantity}, 原因={reason}")

        # 市价卖出
        order_id = self.trader.market_sell(self.format_symbol(symbol), quantity)

        if order_id:
            position.reduce_position(quantity)
            logger.info(f"{symbol} 平仓成功，剩余持仓: {position.quantity}")

    def check_risk_control(self, symbol: str):
        """
        检查风险控制（账户止损3%）

        Args:
            symbol: 股票代码
        """
        position = self.state_manager.get_position(symbol)

        if position is None or position.quantity <= 0:
            return

        # 检查浮亏是否超过3%
        if abs(position.max_drawdown) >= config.STOP_LOSS_RATIO:
            logger.error(f"{symbol} 触发账户止损: 浮亏={position.max_drawdown*100:.2f}%")
            self.execute_exit(symbol, position.quantity, "账户止损")
            position.state = config.STATE_DONE

    def force_close_all(self):
        """强制平掉所有持仓（15:55收盘前）"""
        logger.warning("触发收盘清仓")
        active_positions = self.state_manager.get_active_positions()

        for symbol, position in active_positions.items():
            if position.quantity > 0:
                self.execute_exit(symbol, int(position.quantity), "收盘清仓")
                position.state = config.STATE_DONE


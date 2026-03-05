"""
技术指标计算模块
包含 VWAP, ATR, Keltner Channels, ORB 等指标计算
"""
import numpy as np
import pandas as pd
from typing import Tuple, Optional


class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """
        计算 VWAP (Volume Weighted Average Price)

        Args:
            df: 包含 'close', 'high', 'low', 'volume' 的 DataFrame

        Returns:
            VWAP 序列
        """
        typical_price = (df['close'] + df['high'] + df['low']) / 3
        return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        计算 ATR (Average True Range)

        Args:
            df: 包含 'high', 'low', 'close' 的 DataFrame
            period: ATR 周期

        Returns:
            ATR 序列
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # True Range 计算
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # ATR = TR 的移动平均
        atr = tr.rolling(window=period).mean()

        return atr

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """
        计算 EMA (Exponential Moving Average)

        Args:
            series: 价格序列
            period: EMA 周期

        Returns:
            EMA 序列
        """
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_keltner_channels(
        df: pd.DataFrame,
        ema_period: int = 20,
        atr_period: int = 14,
        multiplier: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算 Keltner Channels

        Args:
            df: 包含 'close', 'high', 'low' 的 DataFrame
            ema_period: EMA 周期
            atr_period: ATR 周期
            multiplier: 带宽倍数

        Returns:
            (KC上轨, KC中轨, KC下轨)
        """
        # 中轨 = EMA
        middle = TechnicalIndicators.calculate_ema(df['close'], ema_period)

        # 计算 ATR
        atr = TechnicalIndicators.calculate_atr(df, atr_period)

        # 上轨和下轨
        upper = middle + (multiplier * atr)
        lower = middle - (multiplier * atr)

        return upper, middle, lower

    @staticmethod
    def calculate_orb(
        df: pd.DataFrame,
        start_time: str,
        end_time: str
    ) -> Optional[dict]:
        """
        计算 ORB (Opening Range Breakout)
        统计开盘后前15分钟（09:30-09:45）的高低点和中轴

        Args:
            df: 包含时间索引和 'high', 'low' 的 DataFrame
            start_time: 开始时间 (如 '09:30')
            end_time: 结束时间 (如 '09:45')

        Returns:
            {'high': ORB_High, 'low': ORB_Low, 'mid': ORB_Mid} 或 None
        """
        if df.empty:
            return None

        # 筛选时间范围
        mask = (df.index.time >= pd.to_datetime(start_time).time()) & \
               (df.index.time < pd.to_datetime(end_time).time())

        orb_data = df[mask]

        if orb_data.empty:
            return None

        orb_high = orb_data['high'].max()
        orb_low = orb_data['low'].min()
        orb_mid = (orb_high + orb_low) / 2

        return {
            'high': orb_high,
            'low': orb_low,
            'mid': orb_mid
        }


class SignalGenerator:
    """交易信号生成器"""

    @staticmethod
    def check_long_entry(
        current_price: float,
        orb_high: float,
        vwap: float,
        kc_upper: float,
        kc_middle: float,
        bar_15m_close: float
    ) -> bool:
        """
        检查多头开仓信号

        条件：
        1. 当前价格 > ORB_High（突破开盘高点）
        2. 当前价格 > VWAP（位于均价之上）
        3. 15分钟K线收盘价 <= KC上轨（避免追高）
        4. 15分钟K线收盘价 > KC中轨（处于强势区）

        Args:
            current_price: 当前价格
            orb_high: ORB 高点
            vwap: VWAP 值
            kc_upper: KC 上轨
            kc_middle: KC 中轨
            bar_15m_close: 15分钟K线收盘价

        Returns:
            是否触发开仓信号
        """
        condition1 = current_price > orb_high
        condition2 = current_price > vwap
        condition3 = bar_15m_close <= kc_upper
        condition4 = bar_15m_close > kc_middle

        return all([condition1, condition2, condition3, condition4])

    @staticmethod
    def check_stop_loss(current_price: float, orb_mid: float) -> bool:
        """
        检查初始止损条件

        条件：当前价格跌破 ORB_Mid

        Args:
            current_price: 当前价格
            orb_mid: ORB 中轴

        Returns:
            是否触发止损
        """
        return current_price < orb_mid

    @staticmethod
    def check_tp1(current_price: float, entry_price: float, orb_mid: float) -> bool:
        """
        检查第一目标止盈（1:1 盈亏比）

        条件：价格达到 entry_price + (entry_price - orb_mid)

        Args:
            current_price: 当前价格
            entry_price: 开仓价格
            orb_mid: ORB 中轴

        Returns:
            是否触发TP1
        """
        target = entry_price + (entry_price - orb_mid)
        return current_price >= target

    @staticmethod
    def check_tp2(current_price: float, kc_middle: float, atr: float, multiplier: float = 3.0) -> bool:
        """
        检查第二目标止盈（极端延伸）

        条件：价格触及 KC中轨 + 3*ATR

        Args:
            current_price: 当前价格
            kc_middle: KC 中轨
            atr: ATR 值
            multiplier: ATR 倍数

        Returns:
            是否触发TP2
        """
        target = kc_middle + (multiplier * atr)
        return current_price >= target

    @staticmethod
    def check_trailing_profit_stop(
        current_price: float,
        entry_price: float,
        max_profit_price: float,
        keep_ratio: float = 0.2
    ) -> bool:
        """
        检查追踪止盈（TP2 后半仓使用）

        条件：利润从峰值回撤，仅剩 keep_ratio（20%）时平仓
        即 current_price <= entry_price + (max_profit_price - entry_price) * keep_ratio

        Args:
            current_price: 当前价格
            entry_price: 开仓价格
            max_profit_price: TP2 后记录的最高价
            keep_ratio: 保留利润比例（0.2 = 20%）

        Returns:
            是否触发追踪止盈
        """
        if max_profit_price <= entry_price:
            return False

        # 止盈线 = 入场价 + 峰值利润 * 保留比例
        trailing_stop_price = entry_price + (max_profit_price - entry_price) * keep_ratio
        return current_price <= trailing_stop_price

    @staticmethod
    def check_trend_reversal(
        df_15m: pd.DataFrame,
        kc_middle: pd.Series,
        bars: int = 2
    ) -> bool:
        """
        检查趋势反转（移动止盈）- 当前策略已弃用，保留备用

        条件：连续 N 根15分钟K线收盘价都低于 KC中轨

        Args:
            df_15m: 15分钟 DataFrame
            kc_middle: KC 中轨序列
            bars: 连续K线数量

        Returns:
            是否触发趋势反转
        """
        if len(df_15m) < bars:
            return False

        recent_closes = df_15m['close'].iloc[-bars:]
        recent_kc_middle = kc_middle.iloc[-bars:]

        # 检查所有收盘价是否都低于 KC 中轨
        return all(recent_closes < recent_kc_middle)



"""
交易状态管理模块
管理每个股票的持仓状态、开仓信息、止损止盈逻辑
"""
from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime
import config


@dataclass
class PositionState:
    """单个股票的持仓状态"""
    symbol: str                         # 股票代码
    state: int = config.STATE_IDLE      # 当前状态 (0/1/2/3)

    # 开仓信息
    entry_price: float = 0.0            # 开仓价格
    entry_time: Optional[datetime] = None  # 开仓时间
    quantity: float = 0.0               # 持仓数量
    initial_quantity: float = 0.0       # 初始持仓数量

    # ORB 数据
    orb_high: float = 0.0               # ORB 高点
    orb_low: float = 0.0                # ORB 低点
    orb_mid: float = 0.0                # ORB 中轴
    orb_locked: bool = False            # ORB 是否已锁定

    # 止盈标记
    tp1_triggered: bool = False         # TP1 是否已触发
    tp2_triggered: bool = False         # TP2 是否已触发
    
    # 挂单状态
    pending_buy_order_id: Optional[str] = None   # 待成交买单ID
    pending_sell_order_id: Optional[str] = None  # 待成交卖单ID

    # 风控
    max_drawdown: float = 0.0           # 最大浮亏比例
    max_profit_price: float = 0.0       # TP2 后追踪的最高价格

    def reset(self):
        """重置状态（用于次日重新开始）"""
        self.state = config.STATE_IDLE
        self.entry_price = 0.0
        self.entry_time = None
        self.quantity = 0.0
        self.initial_quantity = 0.0
        self.orb_high = 0.0
        self.orb_low = 0.0
        self.orb_mid = 0.0
        self.orb_locked = False
        self.tp1_triggered = False
        self.tp2_triggered = False
        self.pending_buy_order_id = None
        self.pending_sell_order_id = None
        self.max_drawdown = 0.0
        self.max_profit_price = 0.0

    def set_orb(self, orb_high: float, orb_low: float, orb_mid: float):
        """锁定 ORB 数据"""
        self.orb_high = orb_high
        self.orb_low = orb_low
        self.orb_mid = orb_mid
        self.orb_locked = True

    def open_position(self, price: float, quantity: float, time: datetime):
        """开仓"""
        self.entry_price = price
        self.entry_time = time
        self.quantity = quantity
        self.initial_quantity = quantity
        self.state = config.STATE_POSITION

    def reduce_position(self, reduce_qty: float):
        """减仓"""
        self.quantity -= reduce_qty
        if self.quantity <= 0:
            self.quantity = 0
            self.state = config.STATE_DONE

    def close_position(self):
        """平仓"""
        self.quantity = 0
        self.state = config.STATE_DONE

    def update_drawdown(self, current_price: float):
        """更新最大浮亏"""
        if self.entry_price > 0 and self.quantity > 0:
            drawdown = (current_price - self.entry_price) / self.entry_price
            if drawdown < self.max_drawdown:
                self.max_drawdown = drawdown

    def update_max_profit_price(self, current_price: float):
        """更新 TP2 后的最高价（用于追踪止盈）"""
        if current_price > self.max_profit_price:
            self.max_profit_price = current_price


class StateManager:
    """全局状态管理器"""

    def __init__(self):
        self.positions: Dict[str, PositionState] = {}
        self.opened_positions_count = 0  # 已开仓数量（最多5个）

    def add_symbol(self, symbol: str):
        """添加股票到监控列表"""
        if symbol not in self.positions:
            self.positions[symbol] = PositionState(symbol=symbol)

    def get_position(self, symbol: str) -> Optional[PositionState]:
        """获取股票持仓状态"""
        return self.positions.get(symbol)

    def can_open_new_position(self) -> bool:
        """检查是否还能开新仓（最多5个）"""
        return self.opened_positions_count < config.MAX_POSITIONS

    def increment_opened_count(self):
        """增加已开仓计数"""
        self.opened_positions_count += 1

    def get_active_positions(self) -> Dict[str, PositionState]:
        """获取所有活跃持仓（state=1或2）"""
        return {
            symbol: pos for symbol, pos in self.positions.items()
            if pos.state in [config.STATE_POSITION, config.STATE_HALF_PROFIT] and pos.quantity > 0
        }

    def get_idle_symbols(self) -> list:
        """获取所有空仓股票（state=0）"""
        return [
            symbol for symbol, pos in self.positions.items()
            if pos.state == config.STATE_IDLE
        ]

    def reset_all(self):
        """重置所有状态（用于新的交易日）"""
        for pos in self.positions.values():
            pos.reset()
        self.opened_positions_count = 0


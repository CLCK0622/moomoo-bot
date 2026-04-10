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

    # 交易日志需要的记录
    last_sell_reason: str = ""          # 等待成交的卖出原因
    sell_reason: str = ""               # 实际展示的卖出原因 (如 tp1, 止损等)
    sell_price_1: float = 0.0           # 第一笔卖出价 (如果是分批)
    sell_price_2: float = 0.0           # 第二笔卖出价 (如果是分批)
    sell_price: float = 0.0             # 单次卖出价
    realized_pnl: float = 0.0           # 已实现盈亏金额 (美元)

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
        self.last_sell_reason = ""
        self.sell_reason = ""
        self.sell_price_1 = 0.0
        self.sell_price_2 = 0.0
        self.sell_price = 0.0
        self.realized_pnl = 0.0

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

    def generate_trading_logs(self, daily_total_cash: float, current_prices: Dict[str, float]) -> None:
        """
        生成当前状态的交易日志并保存到 trading_logs.json
        """
        import json
        from datetime import datetime

        logs = []
        total_realized_pnl = 0.0
        total_floating_pnl = 0.0

        for symbol, pos in self.positions.items():
            if pos.state == config.STATE_IDLE and pos.initial_quantity == 0:
                continue # 未开仓过的股票

            # 计算 PNL
            cur_price = current_prices.get(symbol, pos.entry_price)
            # 当前浮动盈亏 = (当前价 - 入场价) * 剩余持仓
            floating_pnl = (cur_price - pos.entry_price) * pos.quantity
            total_floating_pnl += floating_pnl
            # 总盈亏 = 已实现盈亏 + 浮动盈亏
            total_trade_pnl = pos.realized_pnl + floating_pnl
            
            # 使用初始成本计算该笔交易的收益率
            initial_cost = pos.entry_price * pos.initial_quantity
            trade_return_rate = total_trade_pnl / initial_cost if initial_cost > 0 else 0.0

            # 累计总实盘盈亏
            total_realized_pnl += pos.realized_pnl

            # 构造日志记录
            item = {
                "股票代码": symbol.split('.')[-1], # US.AAPL -> AAPL
                "买入价格": round(pos.entry_price, 2),
                "卖出原因": pos.sell_reason,
                "收益率": f"{trade_return_rate * 100:.2f}%"
            }

            if pos.sell_reason == "tp1":
                if pos.sell_price_1 > 0:
                    item["卖出价格 1"] = round(pos.sell_price_1, 2)
                if pos.sell_price_2 > 0:
                    item["卖出价格 2"] = round(pos.sell_price_2, 2)
            elif pos.sell_reason:
                if pos.sell_price > 0:
                    item["卖出价格"] = round(pos.sell_price, 2)
                # 只有一笔卖出时，也可以显示两个卖出价格的空字段或者不显示，这里按照要求显示一个
            
            logs.append(item)

        # 当日总收益率
        if daily_total_cash and daily_total_cash > 0:
            today_realized_return = total_realized_pnl / daily_total_cash
            today_floating_return = (total_realized_pnl + total_floating_pnl) / daily_total_cash
        else:
            today_realized_return = 0.0
            today_floating_return = 0.0

        res = {
            "date": datetime.now(config.ET_TIMEZONE).strftime("%Y-%m-%d"),
            "今日已实现收益率": f"{today_realized_return * 100:.2f}%",
            "今日浮动总收益率": f"{today_floating_return * 100:.2f}%",
            "logs": logs
        }

        try:
            with open("trading_logs.json", "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"写入 trading_logs.json 失败: {e}")



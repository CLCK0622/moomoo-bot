# backend/trade_manager.py
from datetime import datetime, timedelta


class StrategyLogic:
    @staticmethod
    def check_sell_signal(current_price, base_open_price, cost_price, max_price_seen):
        """
        卖出逻辑 (进攻看开盘，防守看成本)
        """
        if base_open_price <= 0 or cost_price <= 0: return False, None

        # 1. 硬止损 (基于成本 -1%)
        hard_stop_price = cost_price * 0.99
        if current_price < hard_stop_price:
            return True, f"HARD_STOP: Price {current_price:.2f} < Cost Floor {hard_stop_price:.2f}"

        # 计算相对于开盘价的涨幅
        max_gain_pct = (max_price_seen - cost_price) / cost_price

        # 2. 阶段 2: 利润锁定 (开盘涨幅 >= 2.5%)
        # 规则: 锁住 80% 的利润
        if max_gain_pct >= 0.025:
            profit_from_open = max_price_seen - cost_price
            stop_price = cost_price + (profit_from_open * 0.8)
            stop_price = max(stop_price, hard_stop_price)  # 安全兜底，不能低于硬止损

            if current_price < stop_price:
                return True, f"PHASE2_LOCK: Retracing. Lock level: {stop_price:.2f}"

        # 3. 阶段 1: 震荡保护 (开盘涨幅 < 2%)
        # 规则: 允许回撤 1%
        else:
            buffer = cost_price * 0.01
            stop_price = max_price_seen - buffer

            # 只有当动态止盈线 > 硬止损线时才生效
            if stop_price > hard_stop_price and current_price < stop_price:
                return True, f"PHASE1_PROTECT: Dropped 1% from High {max_price_seen:.2f}"

        return False, None

    @staticmethod
    def check_buy_signal(current_price, last_sell_price, last_sell_time,
                         bid_vol, ask_vol, base_open_price, entry_count, max_price_seen):
        """
        买入逻辑 (回马枪/突破) - 已解除冷却和次数限制
        """
        if not last_sell_price or last_sell_price <= 0: return False, None

        # 1. 价格突破逻辑 (突破上次卖出价/埋伏价 0.2%)
        target_price = last_sell_price * 1.002
        is_breakout = current_price > target_price

        # 2. 动能确认 (实盘必须看盘口)
        is_pressure_buy = bid_vol >= ask_vol

        # 3. 逼近前高逻辑 (防止在深渊中买入)
        # 如果是当天第一次买，默认通过；如果是回马枪，必须在当日高点附近
        if entry_count > 0:
            near_high = current_price >= (max_price_seen * 0.99)
        else:
            near_high = True

        if is_breakout and is_pressure_buy and near_high:
            return True, f"ENTRY: Breakout {current_price:.2f} >= {target_price:.2f}"

        return False, None
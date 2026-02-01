"""
Moomoo OpenD 交易接口封装
处理行情订阅、下单、持仓查询等操作
"""
import logging
from typing import Optional, Dict, List
from futu import OpenQuoteContext, OpenSecTradeContext, TrdEnv, TrdMarket, OrderType, TrdSide, ModifyOrderOp, SecurityFirm, AuType
import config

logger = logging.getLogger(__name__)


class MoomooTrader:
    """Moomoo 交易接口封装"""

    def __init__(self, host: str = config.MOOMOO_HOST, port: int = config.MOOMOO_PORT):
        """
        初始化 Moomoo 连接

        Args:
            host: OpenD 服务地址
            port: OpenD 端口
        """
        self.host = host
        self.port = port

        # 行情上下文
        self.quote_ctx = None
        # 交易上下文
        self.trade_ctx = None

        # 交易环境：0=真实, 1=模拟
        self.trd_env = TrdEnv.SIMULATE if config.TRADE_ENV == 1 else TrdEnv.REAL

        # 交易市场
        self.trd_market = TrdMarket.US  # 美股

        logger.info(f"初始化 Moomoo 连接: {host}:{port}, 环境={'模拟' if self.trd_env == TrdEnv.SIMULATE else '真实'}")

    def connect(self) -> bool:
        """
        连接到 OpenD

        Returns:
            是否连接成功
        """
        try:
            # 行情连接
            self.quote_ctx = OpenQuoteContext(host=self.host, port=self.port)

            # 交易连接
            self.trade_ctx = OpenSecTradeContext(
                filter_trdmarket=self.trd_market,
                host=self.host,
                port=self.port,
                security_firm=SecurityFirm.FUTUSG  # Moomoo SG
            )

            logger.info("成功连接到 Moomoo OpenD")
            return True

        except Exception as e:
            logger.error(f"连接 OpenD 失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
        logger.info("已断开 Moomoo 连接")

    def subscribe_kline(self, symbols: List[str], ktype_list: List[str]) -> bool:
        """
        订阅K线数据

        Args:
            symbols: 股票代码列表
            ktype_list: K线类型列表 ['K_1M', 'K_15M']

        Returns:
            是否订阅成功
        """
        try:
            for ktype in ktype_list:
                ret_sub, err_msg = self.quote_ctx.subscribe(symbols, [ktype], subscribe_push=False)
                if ret_sub != 0:
                    logger.error(f"订阅K线失败 {ktype}: {err_msg}")
                    return False
            logger.info(f"成功订阅 {len(symbols)} 只股票的K线数据")
            return True
        except Exception as e:
            logger.error(f"订阅K线异常: {e}")
            return False

    def get_kline(self, symbol: str, ktype: str, num: int = 100) -> Optional[object]:
        """
        获取K线数据

        Args:
            symbol: 股票代码 (如 'US.AAPL')
            ktype: K线类型 ('K_1M', 'K_15M')
            num: 获取数量

        Returns:
            K线 DataFrame 或 None
        """
        try:
            ret, data = self.quote_ctx.get_cur_kline(
                symbol,
                num,
                ktype=ktype,
                autype=AuType.NONE
            )

            if ret == 0:
                return data
            else:
                logger.error(f"获取K线失败 {symbol} {ktype}: {data}")
                return None
        except Exception as e:
            logger.error(f"获取K线异常 {symbol}: {e}")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格

        Args:
            symbol: 股票代码

        Returns:
            当前价格或 None
        """
        try:
            ret, data = self.quote_ctx.get_market_snapshot([symbol])
            if ret == 0 and not data.empty:
                return data.iloc[0]['last_price']
            return None
        except Exception as e:
            logger.error(f"获取当前价格异常 {symbol}: {e}")
            return None

    def get_account_cash(self) -> float:
        """
        获取账户可用现金

        Returns:
            可用现金
        """
        try:
            ret, data = self.trade_ctx.accinfo_query(trd_env=self.trd_env)
            if ret == 0 and not data.empty:
                cash = data.iloc[0]['cash']
                logger.info(f"账户可用现金: ${cash:.2f}")
                return cash
            return 0.0
        except Exception as e:
            logger.error(f"查询账户现金异常: {e}")
            return 0.0

    def place_order(
        self,
        symbol: str,
        quantity: int,
        price: float = 0.0,
        order_type: str = 'MARKET',
        side: str = 'BUY'
    ) -> Optional[str]:
        """
        下单

        Args:
            symbol: 股票代码
            quantity: 数量
            price: 价格（市价单为0）
            order_type: 订单类型 'MARKET' 或 'LIMIT'
            side: 方向 'BUY' 或 'SELL'

        Returns:
            订单ID 或 None
        """
        try:
            trd_side = TrdSide.BUY if side == 'BUY' else TrdSide.SELL

            if order_type == 'MARKET':
                ret, data = self.trade_ctx.place_order(
                    price=0.0,  # 市价单
                    qty=quantity,
                    code=symbol,
                    trd_side=trd_side,
                    order_type=OrderType.MARKET,
                    trd_env=self.trd_env
                )
            else:
                ret, data = self.trade_ctx.place_order(
                    price=price,
                    qty=quantity,
                    code=symbol,
                    trd_side=trd_side,
                    order_type=OrderType.NORMAL,
                    trd_env=self.trd_env
                )

            if ret == 0:
                order_id = data.iloc[0]['order_id']
                logger.info(f"下单成功 {symbol} {side} {quantity}股 @ {price if price > 0 else '市价'}, 订单ID: {order_id}")
                return order_id
            else:
                logger.error(f"下单失败 {symbol}: {data}")
                return None

        except Exception as e:
            logger.error(f"下单异常 {symbol}: {e}")
            return None

    def get_positions(self) -> Dict[str, Dict]:
        """
        获取当前持仓

        Returns:
            持仓字典 {symbol: {'quantity': qty, 'cost': cost_price}}
        """
        positions = {}
        try:
            ret, data = self.trade_ctx.position_list_query(trd_env=self.trd_env)
            if ret == 0 and not data.empty:
                for _, row in data.iterrows():
                    symbol = row['code']
                    positions[symbol] = {
                        'quantity': row['qty'],
                        'cost': row['cost_price'],
                        'market_value': row['market_val']
                    }
            return positions
        except Exception as e:
            logger.error(f"查询持仓异常: {e}")
            return {}

    def market_buy(self, symbol: str, cash_amount: float) -> Optional[str]:
        """
        市价买入（按金额）

        Args:
            symbol: 股票代码
            cash_amount: 买入金额

        Returns:
            订单ID 或 None
        """
        current_price = self.get_current_price(symbol)
        if current_price is None or current_price <= 0:
            logger.error(f"无法获取 {symbol} 当前价格")
            return None

        # 计算股数（向下取整）
        quantity = int(cash_amount / current_price)

        if quantity <= 0:
            logger.warning(f"{symbol} 资金不足购买1股，需要 ${current_price:.2f}")
            return None

        return self.place_order(symbol, quantity, order_type='MARKET', side='BUY')

    def market_sell(self, symbol: str, quantity: int) -> Optional[str]:
        """
        市价卖出

        Args:
            symbol: 股票代码
            quantity: 卖出数量

        Returns:
            订单ID 或 None
        """
        return self.place_order(symbol, quantity, order_type='MARKET', side='SELL')

    def close_all_positions(self):
        """平掉所有持仓"""
        positions = self.get_positions()
        for symbol, pos_info in positions.items():
            qty = int(pos_info['quantity'])
            if qty > 0:
                logger.info(f"平仓 {symbol} {qty}股")
                self.market_sell(symbol, qty)


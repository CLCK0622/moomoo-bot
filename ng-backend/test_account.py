"""
测试账户资金查询 - 使用与 main.py 完全一致的方式连接并查询
用法: python test_account.py
"""
import logging
from futu import OpenSecTradeContext, TrdEnv, TrdMarket, SecurityFirm
import config

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_account_cash():
    """用与 MoomooTrader 完全一致的方式查询账户资金"""
    
    # 与 trader.py 中 MoomooTrader.__init__ + connect() 完全一致
    trd_env = TrdEnv.SIMULATE if config.TRADE_ENV == 1 else TrdEnv.REAL
    env_name = '模拟' if trd_env == TrdEnv.SIMULATE else '真实'
    
    print(f"\n{'='*60}")
    print(f"测试账户资金查询")
    print(f"  OpenD 地址: {config.MOOMOO_HOST}:{config.MOOMOO_PORT}")
    print(f"  交易环境: {env_name} (TRADE_ENV={config.TRADE_ENV})")
    print(f"{'='*60}\n")
    
    # 连接交易上下文
    print("[1/3] 正在连接 OpenD 交易上下文...")
    try:
        trade_ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=config.MOOMOO_HOST,
            port=config.MOOMOO_PORT,
            security_firm=SecurityFirm.FUTUSG
        )
        print("  ✅ 连接成功\n")
    except Exception as e:
        print(f"  ❌ 连接失败: {e}\n")
        return
    
    # 查询账户资金（与 trader.py get_account_cash 完全一致）
    print("[2/3] 正在查询账户资金 (accinfo_query)...")
    try:
        ret, data = trade_ctx.accinfo_query(trd_env=trd_env)
        print(f"  ret = {ret}")
        print(f"  data type = {type(data)}")
        print(f"  data =\n{data}\n")
        
        if ret == 0 and hasattr(data, 'empty') and not data.empty:
            row = data.iloc[0]
            if 'us_cash' in data.columns and getattr(config, 'MARKET', 'US') == 'US':
                cash = row['us_cash']
                print(f"  ✅ 可用现金 (us_cash 自动识别为美元): ${cash:.2f}")
            else:
                cash = row['cash']
                print(f"  ✅ 可用现金 (cash): ${cash:.2f}")
            
            # 打印更多字段帮助调试
            print(f"\n  所有字段:")
            for col in data.columns:
                val = data.iloc[0][col]
                print(f"    {col}: {val}")
        else:
            print(f"  ❌ 查询失败或返回空数据")
            print(f"     ret={ret}")
            print(f"     data={data}")
    except Exception as e:
        print(f"  ❌ 查询异常: {e}")
    
    # 模拟 execute_entry 的计算
    print(f"\n[3/3] 模拟开仓计算...")
    try:
        if ret == 0 and hasattr(data, 'empty') and not data.empty:
            row = data.iloc[0]
            if 'us_cash' in data.columns and getattr(config, 'MARKET', 'US') == 'US':
                cash = row['us_cash']
            else:
                cash = row['cash']
                
            buy_amount = (cash * config.POSITION_SIZE_RATIO) / config.MARGIN_FREEZE_RATIO
            print(f"  总资金: ${cash:.2f}")
            print(f"  POSITION_SIZE_RATIO: {config.POSITION_SIZE_RATIO}")
            print(f"  MARGIN_FREEZE_RATIO: {config.MARGIN_FREEZE_RATIO}")
            print(f"  买入金额 = ({cash:.2f} * {config.POSITION_SIZE_RATIO}) / {config.MARGIN_FREEZE_RATIO} = ${buy_amount:.2f}")
            
            if buy_amount <= 0:
                print(f"  ⚠️  买入金额为 $0！说明账户可用资金为 0 或计算有误")
            else:
                print(f"  ✅ 每只股票可用买入金额: ${buy_amount:.2f}")
        else:
            print(f"  ⚠️  无法计算，因为查询资金失败")
    except Exception as e:
        print(f"  ❌ 计算异常: {e}")
    
    # 关闭连接
    trade_ctx.close()
    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")


if __name__ == '__main__':
    test_account_cash()

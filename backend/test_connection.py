from futu import *
import time

# 1. 链接到本地 OpenD (默认端口 11111)
pwd_unlock = '123456'  # 如果你在OpenD设置了交易解锁密码，填在这里；如果没有，这行可能不需要或留空

try:
    # --- 测试行情连接 ---
    quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    
    # 订阅 AAPL 的即时报价
    ret, data = quote_ctx.subscribe(['HK.00700'], [SubType.QUOTE])
    if ret == RET_OK:
        print("✅ 行情连接成功！正在获取 Apple 当前价格...")
        ret, stock_data = quote_ctx.get_stock_quote(['HK.00700'])
        if ret == RET_OK:
            price = stock_data['last_price'][0]
            print(f"📈 AAPL 当前价格: ${price}")
        else:
            print("❌ 获取报价失败:", stock_data)
    else:
        print("❌ 订阅失败:", data)

    quote_ctx.close()

    # --- 测试交易连接 (这就决定了你能否下单) ---
    # 注意：trd_env=TrdEnv.REAL 是实盘，SIMULATE 是模拟盘
    # 建议先用 TrdEnv.SIMULATE 测试
    trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111, security_firm=SecurityFirm.FUTUINC)
    
    print("\n✅ 交易连接成功！正在查询资产...")
    ret, assets = trd_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE) # 改为 REAL 则是实盘
    if ret == RET_OK:
        power = assets['power'][0] # 购买力
        total = assets['total_assets'][0]
        print(f"💰 模拟盘总资产: ${total}")
        print(f"💵 购买力: ${power}")
    else:
        print("❌ 获取资产失败 (可能是未解锁交易密码):", assets)

    trd_ctx.close()

except Exception as e:
    print(f"❌ 发生错误: {e}")
    print("请检查 FutuOpenD 是否正在运行且端口为 11111")

# test_open_price.py
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT
from datetime import datetime
import pytz


def get_ny_time():
    ny_tz = pytz.timezone('America/New_York')
    return datetime.now(ny_tz).strftime("%H:%M:%S")


def test_open_price():
    print(f"🕐 Current NY Time: {get_ny_time()}")
    print("=" * 80)

    # 连接Moomoo
    quote_ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)

    # 测试几只股票
    test_symbols = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'NVDA']
    codes = [f"US.{s}" for s in test_symbols]

    # 获取市场快照
    ret, data = quote_ctx.get_market_snapshot(codes)

    if ret != RET_OK:
        print(f"❌ Failed to get data: {data}")
        quote_ctx.close()
        return

    print(f"{'Symbol':<10} {'Open Price':<12} {'Last Price':<12} {'Pre-Close':<12} {'Status'}")
    print("-" * 80)

    for _, row in data.iterrows():
        symbol = row['code'].split('.')[1]
        open_price = row['open_price']
        last_price = row['last_price']
        pre_close = row['prev_close_price']

        # 判断open_price是什么
        if open_price <= 0:
            status = "⚠️ ZERO (using last_price)"
        elif abs(open_price - pre_close) < 0.01:
            status = "⚠️ = Pre-Close (yesterday's close)"
        elif abs(open_price - last_price) < 0.01:
            status = "✅ = Last Price (real-time)"
        else:
            status = "✅ Real Open Price"

        print(f"{symbol:<10} ${open_price:<11.2f} ${last_price:<11.2f} ${pre_close:<11.2f} {status}")

    print("=" * 80)
    print("\n💡 Explanation:")
    print("  - Open Price: 今日开盘价 (should be today's first trade price)")
    print("  - Last Price: 最新成交价 (current real-time price)")
    print("  - Pre-Close:  昨日收盘价 (yesterday's closing price)")
    print("\n🎯 If Open Price = Pre-Close → API返回的是昨收价，不是今开价")
    print("   If Open Price = Last Price → 可能是开盘瞬间的价格")
    print("   If Open Price > 0 and different → 这才是真正的今日开盘价")

    quote_ctx.close()


if __name__ == "__main__":
    test_open_price()

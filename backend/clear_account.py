from futu import *
import time

# ================= 🔧 配置区 =================
HOST = '127.0.0.1'
PORT = 11111
PWD_UNLOCK = ''  # 如果有交易密码，请填入
FIRM = SecurityFirm.FUTUSG

# 目标账户信息
TARGET_ACC_ID = 3358341
TARGET_ENV = TrdEnv.SIMULATE  # 模拟盘
TARGET_MARKET = TrdMarket.US  # 美股市场


# ============================================


def close_all_positions():
    """市价单平掉所有持仓"""

    print("🚀 Starting close all positions process...")
    print(f"   Account: {TARGET_ACC_ID}")
    print(f"   Market: US")
    print(f"   Environment: SIMULATE")
    print("=" * 70)

    try:
        # 1. 建立交易连接
        trd_ctx = OpenSecTradeContext(
            filter_trdmarket=TARGET_MARKET,
            host=HOST,
            port=PORT,
            security_firm=FIRM
        )

        # 2. 解锁交易（如果需要）
        if PWD_UNLOCK:
            ret, data = trd_ctx.unlock_trade(PWD_UNLOCK)
            if ret != RET_OK:
                print(f"❌ Unlock failed: {data}")
                return

        # 3. 查询当前持仓
        print("\n📦 Fetching current positions...")
        ret, positions = trd_ctx.position_list_query(
            trd_env=TARGET_ENV,
            acc_id=TARGET_ACC_ID
        )

        if ret != RET_OK:
            print(f"❌ Failed to get positions: {positions}")
            trd_ctx.close()
            return

        if positions.empty:
            print("✅ No positions to close!")
            trd_ctx.close()
            return

        # 过滤出有持仓的股票（数量 > 0）
        active_positions = positions[positions['qty'] > 0].copy()

        if active_positions.empty:
            print("✅ No active positions to close!")
            trd_ctx.close()
            return

        print(f"\n📋 Found {len(active_positions)} position(s) to close:\n")

        # 显示持仓详情
        for idx, pos in active_positions.iterrows():
            print(f"   {pos['code']:<12} {pos['stock_name']:<20} Qty: {pos['qty']:.0f}")

        print("\n" + "=" * 70)

        # 4. 确认操作
        confirm = input("\n⚠️  Proceed to close ALL positions with MARKET orders? (yes/no): ")
        if confirm.lower() != 'yes':
            print("❌ Operation cancelled by user.")
            trd_ctx.close()
            return

        print("\n🔥 Starting to place sell orders...\n")

        # 5. 逐个下市价卖单
        order_results = []

        for idx, pos in active_positions.iterrows():
            code = pos['code']
            qty = int(pos['qty'])
            stock_name = pos['stock_name']

            print(f"📤 Selling {code} ({stock_name}) - Qty: {qty}")

            try:
                # 下市价卖单
                ret, order_data = trd_ctx.place_order(
                    price=0.0,  # 市价单价格设为0
                    qty=qty,
                    code=code,
                    trd_side=TrdSide.SELL,  # 卖出
                    order_type=OrderType.MARKET,  # 市价单
                    trd_env=TARGET_ENV,
                    acc_id=TARGET_ACC_ID
                )

                if ret == RET_OK:
                    order_id = order_data['order_id'].iloc[0]
                    print(f"   ✅ Order placed successfully! Order ID: {order_id}")
                    order_results.append({
                        'code': code,
                        'name': stock_name,
                        'qty': qty,
                        'status': 'SUCCESS',
                        'order_id': order_id
                    })
                else:
                    print(f"   ❌ Order failed: {order_data}")
                    order_results.append({
                        'code': code,
                        'name': stock_name,
                        'qty': qty,
                        'status': 'FAILED',
                        'error': str(order_data)
                    })

                # 避免频繁下单，稍微延迟
                time.sleep(0.5)

            except Exception as e:
                print(f"   ❌ Exception occurred: {e}")
                order_results.append({
                    'code': code,
                    'name': stock_name,
                    'qty': qty,
                    'status': 'ERROR',
                    'error': str(e)
                })

        # 6. 汇总结果
        print("\n" + "=" * 70)
        print("📊 ORDER SUMMARY:")
        print("=" * 70)

        success_count = sum(1 for r in order_results if r['status'] == 'SUCCESS')
        failed_count = len(order_results) - success_count

        print(f"\n✅ Successful: {success_count}")
        print(f"❌ Failed: {failed_count}\n")

        for result in order_results:
            status_icon = "✅" if result['status'] == 'SUCCESS' else "❌"
            print(f"{status_icon} {result['code']:<12} {result['name']:<20} Qty: {result['qty']}")
            if result['status'] != 'SUCCESS':
                print(f"   Error: {result.get('error', 'Unknown')}")

        print("\n" + "=" * 70)

        # 7. 等待几秒后查看最新持仓状态
        print("\n⏳ Waiting 3 seconds to check updated positions...\n")
        time.sleep(3)

        ret, new_positions = trd_ctx.position_list_query(
            trd_env=TARGET_ENV,
            acc_id=TARGET_ACC_ID
        )

        if ret == RET_OK:
            remaining = new_positions[new_positions['qty'] > 0]
            if remaining.empty:
                print("🎉 All positions closed successfully!")
            else:
                print(f"⚠️  {len(remaining)} position(s) still remaining:")
                for _, pos in remaining.iterrows():
                    print(f"   {pos['code']:<12} {pos['stock_name']:<20} Qty: {pos['qty']:.0f}")

        # 8. 关闭连接
        trd_ctx.close()
        print("\n✅ Done!")

    except Exception as e:
        print(f"\n💥 Critical Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    close_all_positions()
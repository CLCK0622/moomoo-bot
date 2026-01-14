# backend/cancel_orders.py
from futu import *
from config import MOOMOO_HOST, MOOMOO_PORT, TRADING_PASSWORD

CURRENT_ENV = TrdEnv.SIMULATE


def cancel_all_open_orders():
    print(f"🧹 Starting Order Cleanup in [{CURRENT_ENV}] mode...")

    try:
        ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=MOOMOO_HOST, port=MOOMOO_PORT,
                                  security_firm=SecurityFirm.FUTUSECURITIES)

        if CURRENT_ENV == TrdEnv.REAL:
            ctx.unlock_trade(TRADING_PASSWORD)

        # 查询未完成订单
        status_filter = [OrderStatus.WAITING_SUBMIT, OrderStatus.SUBMITTED, OrderStatus.FILLED_PART]
        ret, data = ctx.order_list_query(status_filter_list=status_filter, trd_env=CURRENT_ENV)

        if ret != RET_OK:
            print(f"❌ Query Failed: {data}")
            return

        order_ids = data['order_id'].tolist()
        if not order_ids:
            print("✅ No open orders found.")
            return

        print(f"🚨 Found {len(order_ids)} open orders. Cancelling...")

        for oid in order_ids:
            # 🔥 修复: 即使是撤单，也必须传 qty 和 price 占位 (传 0 即可)
            ret_c, data_c = ctx.modify_order(
                ModifyOrderOp.CANCEL,
                order_id=oid,
                qty=0,
                price=0,
                trd_env=CURRENT_ENV
            )

            if ret_c == RET_OK:
                print(f"   🗑️ Cancelled Order ID: {oid}")
            else:
                print(f"   ⚠️ Failed to cancel {oid}: {data_c}")

        print("✨ Cleanup Complete.")
        ctx.close()

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    cancel_all_open_orders()
from futu import *
import pandas as pd

# ================= 🔧 配置区 =================
HOST = '127.0.0.1'
PORT = 11111
PWD_UNLOCK = ''  # 如果有交易密码，请填入
FIRM = SecurityFirm.FUTUSG  # 新加坡 Moomoo


# ============================================

def check_all_accounts():
    """扫描所有账户（实盘+模拟盘）在所有市场的资产"""

    print(f"🇸🇬 Connecting to Moomoo SG (OpenD: {HOST}:{PORT})...\n")

    # 第一步：获取所有账户列表（不过滤市场）
    try:
        quote_ctx = OpenQuoteContext(host=HOST, port=PORT)

        # 尝试所有可能的交易环境
        environments = [
            (TrdEnv.REAL, "🟢 REAL (实盘)"),
            (TrdEnv.SIMULATE, "🔵 SIMULATE (模拟盘)")
        ]

        # 尝试所有可能的市场
        markets = [
            (TrdMarket.US, "🇺🇸 US"),
            (TrdMarket.HK, "🇭🇰 HK"),
            (TrdMarket.SG, "🇸🇬 SG")
        ]

        found_any = False

        for trd_env, env_name in environments:
            print("=" * 70)
            print(f"📍 Scanning: {env_name}")
            print("=" * 70)

            env_has_data = False

            for trd_market, market_name in markets:
                try:
                    # 🔑 关键：每次都要用正确的 trd_env 和 filter_trdmarket 初始化
                    trd_ctx = OpenSecTradeContext(
                        filter_trdmarket=trd_market,
                        host=HOST,
                        port=PORT,
                        security_firm=FIRM
                    )

                    # 解锁交易（如果需要）
                    if PWD_UNLOCK:
                        trd_ctx.unlock_trade(PWD_UNLOCK)

                    # 获取该环境下的账户列表
                    ret, acc_list = trd_ctx.get_acc_list()

                    if ret != RET_OK:
                        trd_ctx.close()
                        continue

                    # 遍历该市场下的所有账户
                    for _, acc_row in acc_list.iterrows():
                        acc_id = acc_row['acc_id']
                        acc_trd_env = acc_row['trd_env']

                        # 只处理当前环境的账户
                        if acc_trd_env != trd_env:
                            continue

                        # 查询资金
                        ret_fund, funds = trd_ctx.accinfo_query(
                            trd_env=trd_env,
                            acc_id=acc_id
                        )

                        if ret_fund == RET_OK and not funds.empty:
                            total_assets = funds['total_assets'].iloc[0]
                            cash = funds['cash'].iloc[0]
                            market_val = funds['market_val'].iloc[0]
                            currency = funds['currency'].iloc[0]

                            # 只显示有资产的账户
                            if total_assets > 0 or cash > 0 or market_val > 0:
                                found_any = True
                                env_has_data = True

                                print(f"\n👤 Account: {acc_id}")
                                print(f"   📊 Market: {market_name}")
                                print(f"   💰 Total Assets: {total_assets:,.2f} {currency}")
                                print(f"      - Cash: {cash:,.2f} {currency}")
                                print(f"      - Stock Value: {market_val:,.2f} {currency}")

                                # 查询持仓
                                ret_pos, positions = trd_ctx.position_list_query(
                                    trd_env=trd_env,
                                    acc_id=acc_id
                                )

                                if ret_pos == RET_OK and not positions.empty:
                                    # 过滤掉数量为0的持仓
                                    active_pos = positions[positions['qty'] > 0]

                                    if not active_pos.empty:
                                        print(f"   📦 Positions ({len(active_pos)}):")
                                        print(f"      {'Code':<12} {'Name':<20} {'Qty':<10} {'Value':<12}")
                                        print(f"      {'-' * 60}")

                                        for _, pos in active_pos.iterrows():
                                            stock_name = str(pos['stock_name'])[:19]
                                            print(
                                                f"      {pos['code']:<12} {stock_name:<20} {pos['qty']:<10.0f} {pos['market_val']:<12,.2f}")

                                        print(f"      {'-' * 60}")
                                    else:
                                        print(f"   📦 No active positions")
                                else:
                                    print(f"   📦 No positions")

                    trd_ctx.close()

                except Exception as e:
                    # 静默跳过不支持的市场
                    pass

            if not env_has_data:
                print(f"\n   ⚠️  No accounts or assets found in {env_name}")
                if trd_env == TrdEnv.SIMULATE:
                    print(f"   💡 Tip: Make sure you've activated the simulation account in the Moomoo app")

        quote_ctx.close()

        if not found_any:
            print("\n" + "=" * 70)
            print("❌ No accounts with assets found!")
            print("\n🔍 Troubleshooting:")
            print("   1. Check if OpenD is running (127.0.0.1:11111)")
            print("   2. Check if you're logged into the Moomoo app")
            print("   3. For simulation accounts: activate them in the app first")
            print("   4. Check if PWD_UNLOCK is needed (for real accounts)")
            print("=" * 70)
        else:
            print("\n" + "=" * 70)
            print("✅ Scan complete!")
            print("=" * 70)

    except Exception as e:
        print(f"💥 Critical Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    check_all_accounts()
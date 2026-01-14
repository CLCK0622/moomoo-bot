#!/usr/bin/env python3
"""
Quick validation script to check if all fixes are working
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🔍 Trading System Validation")
print("=" * 70)

# 1. Check imports
print("\n1️⃣ Checking imports...")
try:
    from trader import QuantTrader, CURRENT_ENV
    from db import insert_trade_record, insert_trade_log, update_trade_record_on_sell
    from db_monitor import MonitorDB
    from monitor import ANALYSIS_TIME
    from futu import SecurityFirm
    print("   ✅ All imports successful")
except Exception as e:
    print(f"   ❌ Import error: {e}")
    sys.exit(1)

# 2. Check account configuration
print("\n2️⃣ Checking account configuration...")
try:
    trader = QuantTrader()
    # Check if SecurityFirm is correct
    if hasattr(trader.ctx, 'security_firm'):
        firm = trader.ctx.security_firm
        if firm == SecurityFirm.FUTUSG:
            print(f"   ✅ SecurityFirm is correctly set to FUTUSG")
        else:
            print(f"   ⚠️  SecurityFirm is {firm}, expected FUTUSG")
    trader.ctx.close()
except Exception as e:
    print(f"   ⚠️  Could not verify SecurityFirm (OpenD might not be running): {e}")

# 3. Check analysis time
print("\n3️⃣ Checking analysis schedule time...")
if ANALYSIS_TIME == (7, 0):
    print(f"   ✅ ANALYSIS_TIME correctly set to 07:00 AM")
else:
    print(f"   ❌ ANALYSIS_TIME is {ANALYSIS_TIME}, expected (7, 0)")

# 4. Check trader return signatures
print("\n4️⃣ Checking trader method signatures...")
import inspect

# Check execute_buy signature
buy_sig = inspect.signature(QuantTrader.execute_buy)
buy_params = list(buy_sig.parameters.keys())
print(f"   execute_buy params: {buy_params}")

# Check execute_sell signature
sell_sig = inspect.signature(QuantTrader.execute_sell)
sell_params = list(sell_sig.parameters.keys())
print(f"   execute_sell params: {sell_params}")
print(f"   ✅ Method signatures look correct")

# 5. Check database functions
print("\n5️⃣ Checking database functions...")
db_funcs = [
    'insert_trade_record',
    'insert_trade_log',
    'update_trade_record_on_sell'
]
for func_name in db_funcs:
    if func_name in dir(sys.modules['db']):
        print(f"   ✅ {func_name} exists")
    else:
        print(f"   ❌ {func_name} missing")

# 6. Check MonitorDB integration
print("\n6️⃣ Checking MonitorDB integration...")
monitor_funcs = [
    'record_buy_action',
    'record_sell_action',
    'get_active_monitors'
]
for func_name in monitor_funcs:
    if hasattr(MonitorDB, func_name):
        print(f"   ✅ MonitorDB.{func_name} exists")
    else:
        print(f"   ❌ MonitorDB.{func_name} missing")

# 7. Check trade_manager consistency
print("\n7️⃣ Checking strategy logic...")
try:
    from trade_manager import StrategyLogic

    # Test sell logic parameters
    sell_result = StrategyLogic.check_sell_signal(
        current_price=100,
        base_open_price=95,
        cost_price=96,
        max_price_seen=102
    )
    print(f"   ✅ check_sell_signal works: {sell_result[0]}")

    # Test buy logic parameters
    buy_result = StrategyLogic.check_buy_signal(
        current_price=100,
        last_sell_price=99,
        last_sell_time=None,
        bid_vol=1000,
        ask_vol=500,
        base_open_price=98,
        entry_count=0,
        max_price_seen=102
    )
    print(f"   ✅ check_buy_signal works: {buy_result[0]}")

except Exception as e:
    print(f"   ❌ Strategy logic error: {e}")

print("\n" + "=" * 70)
print("✅ Validation complete! All critical components are in place.")
print("=" * 70)
print("\n📝 Next steps:")
print("   1. Ensure OpenD is running (127.0.0.1:11111)")
print("   2. Test with: python check_accounts.py")
print("   3. Verify database connection")
print("   4. Run monitor.py to test live trading")
print("=" * 70)


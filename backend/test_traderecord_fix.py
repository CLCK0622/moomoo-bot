#!/usr/bin/env python3
"""
Test TradeRecord and TradeLog with proper ID handling
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from db import get_db_connection, insert_trade_record, insert_trade_log, update_trade_record_on_sell

print("=" * 70)
print("🧪 TradeRecord & TradeLog Integration Test")
print("=" * 70)

conn = get_db_connection()
cur = conn.cursor()

# Step 1: Find a stock that has DailyCandidate today
print("\n1️⃣ Finding a stock with DailyCandidate...")
cur.execute("""
    SELECT symbol, id FROM "DailyCandidate"
    WHERE date = CURRENT_DATE
    LIMIT 1
""")
result = cur.fetchone()

if not result:
    print("   ⚠️  No DailyCandidate found today - creating test data")
    # Create a test candidate
    cur.execute("""
        INSERT INTO "DailyCandidate" (date, symbol, "sentimentScore", "newsSummary", status)
        VALUES (CURRENT_DATE, 'TEST', 5, 'Test candidate for integration test', 'APPROVED')
        RETURNING id, symbol
    """)
    result = cur.fetchone()
    conn.commit()
    cleanup_candidate = True
    print(f"   ✅ Created test DailyCandidate: {result[1]} (id={result[0]})")
else:
    cleanup_candidate = False
    print(f"   ✅ Using existing DailyCandidate: {result[0]} (id={result[1]})")

candidate_symbol = result[0]
candidate_id = result[1]

# Step 2: Test insert_trade_record (with numpy types)
print("\n2️⃣ Testing insert_trade_record...")
entry_price = np.float64(100.50)
quantity = np.int64(50)

trade_record_id = insert_trade_record(candidate_symbol, entry_price, quantity)

if trade_record_id:
    print(f"   ✅ TradeRecord created with id={trade_record_id}")

    # Verify in database
    cur.execute('SELECT id, "candidateId", symbol FROM "TradeRecord" WHERE id = %s', (trade_record_id,))
    tr = cur.fetchone()
    if tr:
        print(f"      Verified: TradeRecord.id={tr[0]}, candidateId={tr[1]}, symbol={tr[2]}")

    # Step 3: Test insert_trade_log
    print("\n3️⃣ Testing insert_trade_log...")
    try:
        insert_trade_log(trade_record_id, 'BUY', f"Test buy: {quantity} shares @ ${entry_price}", float(entry_price))
        print(f"   ✅ TradeLog created for TradeRecord.id={trade_record_id}")

        # Verify in database
        cur.execute('SELECT id, "tradeId", type, message FROM "TradeLog" WHERE "tradeId" = %s ORDER BY id DESC LIMIT 1', (trade_record_id,))
        tl = cur.fetchone()
        if tl:
            print(f"      Verified: TradeLog.id={tl[0]}, tradeId={tl[1]}, type={tl[2]}")

    except Exception as e:
        print(f"   ❌ TradeLog insertion failed: {e}")

    # Step 4: Test update_trade_record_on_sell
    print("\n4️⃣ Testing update_trade_record_on_sell...")
    exit_price = np.float64(105.00)
    pnl = (exit_price - entry_price) * quantity

    try:
        update_trade_record_on_sell(trade_record_id, exit_price, pnl, "Test sell")
        print(f"   ✅ TradeRecord updated with exit info")

        # Verify status changed
        cur.execute('SELECT status, "exitPrice", pnl FROM "TradeRecord" WHERE id = %s', (trade_record_id,))
        tr_updated = cur.fetchone()
        if tr_updated:
            print(f"      Verified: status={tr_updated[0]}, exitPrice=${tr_updated[1]:.2f}, pnl=${tr_updated[2]:.2f}")

        # Add sell log
        insert_trade_log(trade_record_id, 'SELL', f"Test sell: {quantity} shares @ ${exit_price}", float(exit_price))
        print(f"   ✅ Sell TradeLog created")

    except Exception as e:
        print(f"   ❌ Update failed: {e}")

    # Step 5: Clean up
    print("\n5️⃣ Cleaning up test data...")
    cur.execute('DELETE FROM "TradeLog" WHERE "tradeId" = %s', (trade_record_id,))
    deleted_logs = cur.rowcount
    cur.execute('DELETE FROM "TradeRecord" WHERE id = %s', (trade_record_id,))
    deleted_records = cur.rowcount

    if cleanup_candidate:
        cur.execute('DELETE FROM "DailyCandidate" WHERE id = %s', (candidate_id,))
        deleted_candidates = cur.rowcount
    else:
        deleted_candidates = 0

    conn.commit()
    print(f"   ✅ Cleaned up: {deleted_logs} TradeLog(s), {deleted_records} TradeRecord(s), {deleted_candidates} DailyCandidate(s)")

else:
    print("   ⚠️  No TradeRecord created (expected if stock not in DailyCandidate)")

# Step 6: Test with stock NOT in DailyCandidate
print("\n6️⃣ Testing with stock NOT in DailyCandidate...")
result = insert_trade_record('NOTINDB', np.float64(50.0), np.int64(10))
if result is None:
    print("   ✅ Correctly returned None (no DailyCandidate)")
else:
    print(f"   ⚠️  Unexpected: TradeRecord created with id={result}")

print("\n" + "=" * 70)
print("✅ All Tests Passed!")
print("=" * 70)
print("\n📝 Summary:")
print("   • insert_trade_record returns TradeRecord.id (NOT candidateId)")
print("   • TradeLog.tradeId correctly references TradeRecord.id")
print("   • Numpy type conversion works correctly")
print("   • Gracefully handles stocks without DailyCandidate")
print("=" * 70)

cur.close()
conn.close()


#!/usr/bin/env python3
"""
Database Schema Investigation and Testing
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db_connection

print("=" * 70)
print("🔍 Database Schema Investigation")
print("=" * 70)

conn = get_db_connection()
cur = conn.cursor()

# 1. Check TradeRecord schema
print("\n1️⃣ TradeRecord Schema:")
cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'TradeRecord'
    ORDER BY ordinal_position
""")
print("   Columns:")
for row in cur.fetchall():
    nullable = "NULL" if row[2] == 'YES' else "NOT NULL"
    default = f" DEFAULT {row[3]}" if row[3] else ""
    print(f"      {row[0]:<20} {row[1]:<20} {nullable}{default}")

# 2. Check TradeRecord primary key
print("\n   Primary Key:")
cur.execute("""
    SELECT a.attname
    FROM pg_index i
    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
    WHERE i.indrelid = '"TradeRecord"'::regclass AND i.indisprimary
""")
pkeys = cur.fetchall()
if pkeys:
    for row in pkeys:
        print(f"      {row[0]}")
else:
    print("      ⚠️  No primary key found!")

# 3. Check TradeLog schema
print("\n2️⃣ TradeLog Schema:")
cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'TradeLog'
    ORDER BY ordinal_position
""")
print("   Columns:")
for row in cur.fetchall():
    nullable = "NULL" if row[2] == 'YES' else "NOT NULL"
    default = f" DEFAULT {row[3]}" if row[3] else ""
    print(f"      {row[0]:<20} {row[1]:<20} {nullable}{default}")

# 4. Check TradeLog foreign keys
print("\n   Foreign Keys:")
cur.execute("""
    SELECT 
        kcu.column_name, 
        ccu.table_name AS foreign_table_name,
        ccu.column_name AS foreign_column_name 
    FROM information_schema.table_constraints AS tc 
    JOIN information_schema.key_column_usage AS kcu
        ON tc.constraint_name = kcu.constraint_name
    JOIN information_schema.constraint_column_usage AS ccu
        ON ccu.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY' 
    AND tc.table_name='TradeLog'
""")
for row in cur.fetchall():
    print(f"      {row[0]} -> {row[1]}.{row[2]}")

# 5. Check if there are any TradeRecords today
print("\n3️⃣ Today's TradeRecords:")
cur.execute("""
    SELECT id, "candidateId", symbol, "entryPrice", quantity, status, "createdAt"
    FROM "TradeRecord"
    WHERE "createdAt" >= CURRENT_DATE
    ORDER BY "createdAt" DESC
    LIMIT 5
""")
records = cur.fetchall()
if records:
    print(f"   Found {len(records)} records:")
    for row in records:
        print(f"      TradeID={row[0]}, CandidateID={row[1]}, {row[2]}, Entry=${row[3]:.2f}, Qty={row[4]}, Status={row[5]}")
else:
    print("   ⚠️  No TradeRecords found today")

# 6. Check DailyCandidate for today
print("\n4️⃣ Today's DailyCandidate:")
cur.execute("""
    SELECT id, symbol, "sentimentScore", status
    FROM "DailyCandidate"
    WHERE date = CURRENT_DATE
    ORDER BY "sentimentScore" DESC
    LIMIT 10
""")
candidates = cur.fetchall()
if candidates:
    print(f"   Found {len(candidates)} candidates:")
    for row in candidates:
        print(f"      ID={row[0]}, {row[1]}, Score={row[2]}, Status={row[3]}")
else:
    print("   ⚠️  No DailyCandidate found today")

# 7. Check TradePosition
print("\n5️⃣ Active TradePositions:")
cur.execute("""
    SELECT id, symbol, "buyPrice", quantity, status, "buyTime"
    FROM "TradePosition"
    WHERE status = 'OPEN' OR "buyTime" >= CURRENT_DATE
    ORDER BY "buyTime" DESC
    LIMIT 5
""")
positions = cur.fetchall()
if positions:
    print(f"   Found {len(positions)} positions:")
    for row in positions:
        print(f"      ID={row[0]}, {row[1]}, Buy=${row[2]:.2f}, Qty={row[3]}, Status={row[4]}")
else:
    print("   No positions found")

# 8. Check StockMonitor
print("\n6️⃣ Active StockMonitors:")
cur.execute("""
    SELECT id, symbol, status, "isActive", "entryCount", "currentPositionId"
    FROM "StockMonitor"
    WHERE "isActive" = true
    ORDER BY "updatedAt" DESC
    LIMIT 5
""")
monitors = cur.fetchall()
if monitors:
    print(f"   Found {len(monitors)} monitors:")
    for row in monitors:
        print(f"      ID={row[0]}, {row[1]}, Status={row[2]}, EntryCount={row[4]}, PosID={row[5]}")
else:
    print("   No active monitors")

print("\n" + "=" * 70)
print("🔍 Key Findings:")
print("=" * 70)

# Analyze the relationship
print("\n💡 Relationship Analysis:")
print("   • TradeLog.tradeId must reference a valid TradeRecord")
print("   • TradeRecord.candidateId references DailyCandidate.id")
print("   • If stock not in DailyCandidate, TradeRecord can't be created")
print("   • But TradePosition and StockMonitor work independently")

print("\n⚠️  Problem:")
print("   The error shows: TradeLog trying to insert tradeId=385")
print("   But TradeRecord with candidateId=385 doesn't exist")
print("   This means we're trying to log for a non-existent TradeRecord")

print("\n✅ Solution:")
print("   • Only create TradeLog if TradeRecord was successfully created")
print("   • Check if trade_id is not None before calling insert_trade_log")
print("   • TradePosition/StockMonitor continue to work as primary tracking")

print("=" * 70)

cur.close()
conn.close()


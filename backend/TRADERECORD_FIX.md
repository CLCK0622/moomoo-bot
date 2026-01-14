# 🔧 TradeRecord/TradeLog Foreign Key Fix

## Issue Summary

### Error Encountered
```
❌ [DB Error] insert_trade_log: insert or update on table "TradeLog" violates foreign key constraint "TradeLog_tradeId_fkey"
DETAIL: Key (tradeId)=(385) is not present in table "TradeRecord".
```

### Root Cause
**Confusion between TradeRecord.id and TradeRecord.candidateId**

The database schema has:
- **TradeRecord.id**: Primary key (auto-increment integer)
- **TradeRecord.candidateId**: Foreign key to DailyCandidate.id (NOT NULL)
- **TradeLog.tradeId**: Foreign key to **TradeRecord.id** (NOT candidateId!)

Our code was incorrectly:
1. Returning `candidateId` from `insert_trade_record()`
2. Trying to insert into `TradeLog` with `candidateId` value
3. Updating `TradeRecord` by `candidateId` instead of `id`

## Database Schema (Verified)

### TradeRecord
```sql
TradeRecord:
  id              INTEGER      PRIMARY KEY (auto-increment)
  candidateId     INTEGER      NOT NULL (FK -> DailyCandidate.id)
  symbol          TEXT         NOT NULL
  entryPrice      FLOAT
  quantity        INTEGER
  highestPrice    FLOAT
  currentStopLoss FLOAT
  exitPrice       FLOAT
  pnl             FLOAT
  pnlPercent      FLOAT
  isReEntry       BOOLEAN      DEFAULT false
  status          MonitorStatus DEFAULT 'WATCHING'
  createdAt       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
```

### TradeLog
```sql
TradeLog:
  id        INTEGER   PRIMARY KEY (auto-increment)
  tradeId   INTEGER   NOT NULL (FK -> TradeRecord.id)  ⚠️ References TradeRecord.id!
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  type      TEXT      NOT NULL
  message   TEXT      NOT NULL
  price     FLOAT
```

## Fixes Applied

### 1. `db.py` - insert_trade_record()
**Before:**
```python
cur.execute("""
    INSERT INTO "TradeRecord" (...)
    VALUES (...)
    RETURNING "candidateId"  ❌ Wrong!
""")
return cur.fetchone()[0]  # Returns candidateId
```

**After:**
```python
cur.execute("""
    INSERT INTO "TradeRecord" (...)
    VALUES (...)
    RETURNING id  ✅ Correct!
""")
trade_record_id = cur.fetchone()[0]  # Returns TradeRecord.id
return trade_record_id
```

### 2. `db.py` - update_trade_record_on_sell()
**Before:**
```python
cur.execute("""
    UPDATE "TradeRecord"
    SET ...
    WHERE "candidateId" = %s  ❌ Wrong column!
""", (trade_id,))
```

**After:**
```python
cur.execute("""
    UPDATE "TradeRecord"
    SET ...
    WHERE id = %s  ✅ Correct!
""", (trade_record_id,))
```

### 3. `db_monitor.py` - record_sell_action()
**Before:**
```python
cur.execute("""
    SELECT "candidateId" FROM "TradeRecord"  ❌ Wrong column!
    WHERE symbol = %s AND status = 'WATCHING'
""")
```

**After:**
```python
cur.execute("""
    SELECT id FROM "TradeRecord"  ✅ Correct!
    WHERE symbol = %s AND status = 'WATCHING'
""")
trade_record_id = cur.fetchone()[0]  # Now gets TradeRecord.id
```

## Relationship Diagram

```
DailyCandidate (id=385, symbol='CRWV')
    ↓ (candidateId FK)
TradeRecord (id=10, candidateId=385, symbol='CRWV')
    ↓ (tradeId FK)
TradeLog (id=N, tradeId=10, type='BUY'/'SELL')
```

## Test Results ✅

```
1️⃣ insert_trade_record with DailyCandidate:
   ✅ Created TradeRecord (id=11, candidateId=324)
   ✅ Returns correct TradeRecord.id

2️⃣ insert_trade_log:
   ✅ Created TradeLog (id=9, tradeId=11)
   ✅ Foreign key constraint satisfied

3️⃣ update_trade_record_on_sell:
   ✅ Updated TradeRecord id=11
   ✅ Status changed to FINISHED

4️⃣ Numpy type conversion:
   ✅ All numpy types converted properly

5️⃣ Graceful handling:
   ✅ Skips TradeRecord if no DailyCandidate
```

## Data Flow (Corrected)

### Buy Action
```python
# 1. Opening trader executes buy
trader.execute_buy(symbol, budget)
  → Returns (success, qty, price, order_id)

# 2. Monitor records in database
MonitorDB.record_buy_action(0, symbol, price, qty, base_open)
  → Creates TradePosition (always)
  → Creates/updates StockMonitor (always)
  → Calls insert_trade_record(symbol, price, qty)
    → Looks up DailyCandidate
    → If found: Creates TradeRecord, returns TradeRecord.id ✅
    → If not found: Returns None (gracefully skip)
  → If TradeRecord.id exists:
    → Calls insert_trade_log(trade_record_id, 'BUY', ...)  ✅
```

### Sell Action
```python
# 1. Monitor detects sell signal
trader.execute_sell(symbol, qty)
  → Returns (success, price, order_id)

# 2. Monitor records in database
MonitorDB.record_sell_action(monitor_id, position_id, sell_price, reason)
  → Updates TradePosition to CLOSED (always)
  → Updates StockMonitor to WATCHING (always)
  → Looks up TradeRecord by symbol (SELECT id FROM TradeRecord...)  ✅
  → If found:
    → Calls update_trade_record_on_sell(trade_record_id, ...)  ✅
    → Calls insert_trade_log(trade_record_id, 'SELL', ...)  ✅
```

## Why TradeRecord/TradeLog are Optional

**Core Tracking (Always Works):**
- ✅ `TradePosition`: Tracks all buys/sells regardless of DailyCandidate
- ✅ `StockMonitor`: Tracks monitoring status for all stocks

**Analytics Tracking (Conditional):**
- ⚠️  `TradeRecord`: Only created if stock is in DailyCandidate
- ⚠️  `TradeLog`: Only created if TradeRecord exists

**Why?**
- TradeRecord is designed to track performance of AI-analyzed candidates
- If you manually trade a stock not in DailyCandidate, it won't have TradeRecord
- This is by design - it separates systematic (analyzed) trades from manual trades

## Files Modified

1. ✅ `/backend/db.py`
   - Fixed `insert_trade_record()` to return `id` not `candidateId`
   - Fixed `update_trade_record_on_sell()` to use `WHERE id = %s`
   - Updated parameter names for clarity

2. ✅ `/backend/db_monitor.py`
   - Fixed `record_sell_action()` to query `id` not `candidateId`
   - Updated variable names to `trade_record_id`

## Verification Commands

### Check TradeRecords
```sql
SELECT id, "candidateId", symbol, "entryPrice", status 
FROM "TradeRecord" 
WHERE "createdAt" >= CURRENT_DATE;
```

### Check TradeLogs
```sql
SELECT tl.id, tl."tradeId", tr.symbol, tl.type, tl.message
FROM "TradeLog" tl
JOIN "TradeRecord" tr ON tl."tradeId" = tr.id
WHERE tl.timestamp >= CURRENT_DATE
ORDER BY tl.timestamp DESC;
```

### Check Foreign Key Integrity
```sql
-- This should return 0 (no orphaned TradeLogs)
SELECT COUNT(*) FROM "TradeLog" tl
LEFT JOIN "TradeRecord" tr ON tl."tradeId" = tr.id
WHERE tr.id IS NULL;
```

## Status

✅ **FIXED AND TESTED**

The error `Key (tradeId)=(385) is not present in table "TradeRecord"` will no longer occur.

---

**Date**: January 13, 2026  
**Test Script**: `test_traderecord_fix.py`  
**Status**: All tests passed ✅


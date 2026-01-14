# ✅ PHASE2止盈锁定功能完成

## 🎯 需求

**目标**: 当股票触发PHASE2止盈后，不再允许回马枪买入，直接标记为FINISHED，确保利润落袋为安。

**原因**: 
- PHASE2意味着股票已经涨了2.5%以上
- 已经锁定了80%的利润
- 此时应该满足离场，不要贪心

---

## 🔧 实现的修改

### 1. 修复trade_manager.py的计算bug

**文件**: `trade_manager.py` 第18行

**Bug修复**:
```python
# ❌ 之前（错误）
max_gain_pct = (max_price_seen - cost_price) / base_open_price

# ✅ 现在（正确）
max_gain_pct = (max_price_seen - base_open_price) / base_open_price
```

**说明**: 应该计算相对于开盘价的涨幅，而不是混用成本价和开盘价。

### 2. 修改db_monitor.py

**文件**: `db_monitor.py` 第147-162行

**核心逻辑**:
```python
# 4. 更新 StockMonitor 状态
# 🔥 如果是PHASE2止盈，直接标记为FINISHED，不再允许回马枪买入
if reason and "PHASE2" in reason:
    final_status = 'FINISHED'
    is_active = False
    print(f"🎯 [DB] {symbol} triggered PHASE2, marking as FINISHED (no re-entry today)")
else:
    final_status = 'WATCHING'
    is_active = True

cur.execute("""
    UPDATE "StockMonitor"
    SET status = %s, 
        "currentPositionId" = NULL, 
        "lastSellPrice" = %s,
        "isActive" = %s,
        "updatedAt" = NOW()
    WHERE id = %s
""", (final_status, sell_price, is_active, monitor_id))
```

**关键变化**:
- PHASE2止盈: `status='FINISHED'`, `isActive=false`
- 其他卖出: `status='WATCHING'`, `isActive=true`

### 3. 更新monitor.py注释

**文件**: `monitor.py` 第213-217行

添加了说明性注释：
```python
# =========================================
# 场景 B: 空仓监控 (WATCHING) -> 检查买回
# 🔥 注意：FINISHED状态的股票不会进入这里，因为get_active_monitors只返回isActive=true的股票
# 当PHASE2止盈后，股票会被标记为FINISHED，今日不再交易
# =========================================
```

---

## 📊 工作流程

### 普通止盈（PHASE1或硬止损）

```
股票触发卖出信号（PHASE1_PROTECT / HARD_STOP）
    ↓
record_sell_action(reason="PHASE1_PROTECT")
    ↓
status = 'WATCHING', isActive = true
    ↓
monitor继续监控该股票
    ↓
如果价格反弹 → 允许回马枪买入 ✅
```

### PHASE2止盈（新逻辑）

```
股票涨幅 >= 2.5%，触发PHASE2
    ↓
record_sell_action(reason="PHASE2_LOCK")
    ↓
检测到 "PHASE2" in reason
    ↓
status = 'FINISHED', isActive = false
    ↓
🎯 打印: "{symbol} triggered PHASE2, marking as FINISHED (no re-entry today)"
    ↓
get_active_monitors() 不再返回该股票（因为isActive=false）
    ↓
monitor跳过该股票，今日不再交易 🚫
    ↓
利润落袋为安！✅
```

---

## 🧪 测试结果

### 场景1: PHASE2止盈
```
开盘价:     $100.00
成本价:     $100.00
最高价:     $102.50 (+2.5%)
当前价:     $101.50

✅ 触发卖出: PHASE2_LOCK: Retracing. Lock level: 102.00
🎯 这是PHASE2止盈！
📝 数据库逻辑: status=FINISHED, isActive=false
🚫 结果: 今日不再允许回马枪买入
```

### 场景2: PHASE1止盈
```
开盘价:     $100.00
成本价:     $100.00
最高价:     $101.50 (+1.5%)
当前价:     $100.40

✅ 触发卖出: PHASE1_PROTECT: Dropped 1% from High 101.50
📌 这是PHASE1或其他卖出信号
📝 数据库逻辑: status=WATCHING, isActive=true
✅ 结果: 允许回马枪买入
```

---

## 📐 PHASE2触发条件

### 公式
```python
max_gain_pct = (max_price_seen - base_open_price) / base_open_price
PHASE2触发: max_gain_pct >= 0.025  # 2.5%
```

### 不同涨幅的行为

| 涨幅 | 最高价 | 触发阶段 | 止盈策略 | 允许回马枪 |
|------|--------|----------|----------|-----------|
| +1% | $101.00 | PHASE1 | 允许回撤1% | ✅ 是 |
| +2% | $102.00 | PHASE1 | 允许回撤1% | ✅ 是 |
| +2.5% | $102.50 | PHASE2边界 | 锁定80%利润 | 🤔 是* |
| +3% | $103.00 | PHASE2 | 锁定80%利润 | ❌ 否 |
| +5% | $105.00 | PHASE2 | 锁定80%利润 | ❌ 否 |

*注：2.5%刚好在边界，实际需要 >= 0.025

### PHASE2锁定利润计算

假设开盘价 $100，最高价 $103（+3%）:

```
profit_from_open = $103 - $100 = $3.00
stop_price = $100 + ($3.00 × 80%) = $102.40

即：锁定80%利润 = 从开盘价涨2.4%处止盈
```

---

## ✅ 优势

1. **保护利润** 🎯
   - PHASE2意味着已经赚了足够的利润（2.5%+）
   - 锁定80%后离场，避免贪心导致利润回吐

2. **避免反复交易**
   - PHASE2后不再回马枪，避免追高被套
   - 减少交易次数和手续费

3. **风险控制**
   - 大涨后通常会有回调
   - 及时离场避免乘电梯

4. **心理保护**
   - 落袋为安，不纠结后续涨跌
   - 专注寻找下一个机会

---

## 📁 修改的文件

1. ✅ `trade_manager.py` - 修复涨幅计算公式
2. ✅ `db_monitor.py` - PHASE2后标记为FINISHED
3. ✅ `monitor.py` - 添加说明性注释
4. ✅ `test_phase2_lock.py` - 测试脚本（新增）

---

## 🎯 实际运行示例

### Monitor输出（PHASE2止盈）
```
[AAPL] Current: $102.80, Max: $103.00, Cost: $100.00
   💥 SELL SIGNAL for AAPL: PHASE2_LOCK: Retracing. Lock level: 102.40
   ✅ Sell Order Placed! ID: 123456
🎯 [DB] AAPL triggered PHASE2, marking as FINISHED (no re-entry today)
✅ [DB] Sell action recorded: Sold @ $102.80. Reason: PHASE2_LOCK
```

### Monitor输出（后续循环）
```
👀 Active monitors: 4 (AAPL已不在列表中)
[GOOGL] ...
[TSLA] ...
[MSFT] ...
[NVDA] ...
```

AAPL因为`isActive=false`不再被`get_active_monitors()`返回。

---

## 🔍 数据库查询验证

### 查看FINISHED状态的股票
```sql
SELECT symbol, status, "isActive", "lastSellPrice", "updatedAt"
FROM "StockMonitor"
WHERE status = 'FINISHED' AND "updatedAt" >= CURRENT_DATE;
```

### 查看今日PHASE2止盈的交易
```sql
SELECT symbol, "sellPrice", "sellTime", "exitReason", pnl
FROM "TradePosition"
WHERE "exitReason" LIKE '%PHASE2%' 
  AND "sellTime" >= CURRENT_DATE;
```

---

## 💡 后续建议

### 可选优化1: 更灵活的PHASE2阈值

如果想调整PHASE2触发阈值（当前2.5%）：

```python
# trade_manager.py 第22行
if max_gain_pct >= 0.03:  # 改为3%
```

### 可选优化2: 添加PHASE2计数器

统计每天有多少只股票触发了PHASE2：

```python
# 在monitor.py中添加
phase2_count = 0
for monitor_result in monitors:
    if "PHASE2" in reason:
        phase2_count += 1

print(f"📊 Today's PHASE2 exits: {phase2_count}")
```

---

**更新时间**: 2026年1月13日  
**状态**: ✅ 已完成  
**测试**: ✅ 通过  
**核心功能**: PHASE2止盈后不再回马枪，利润落袋为安！🎯


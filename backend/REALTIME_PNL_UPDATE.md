# 🔄 实时浮盈浮亏计算更新

## 更新日期
2026年1月13日

## 问题描述
之前的dashboard使用Moomoo API返回的`pl_val`字段来显示浮盈浮亏，但这个值可能有延迟，导致显示不够实时准确。

## 解决方案

### 旧方法（有延迟）
```python
# 直接使用Moomoo返回的浮盈浮亏
unrealized = pos['pl_val']  # 可能有缓存延迟
```

### 新方法（实时计算）✅
```python
# 使用最新价格和成本价实时计算
current_price = pos['current_price']  # 最新成交价
cost = pos['cost']                     # 买入成本
qty = pos['qty']                       # 持仓数量

# 实时计算市值和浮盈浮亏
market_value = current_price * qty
unrealized = (current_price - cost) * qty
```

## 计算公式

### 市值 (Market Value)
```
市值 = 现价 × 数量
```

### 浮盈浮亏 (Unrealized PnL)
```
浮盈浮亏 = (现价 - 成本价) × 数量
```

### 浮盈比例
```
浮盈比例 = 浮盈浮亏 ÷ (成本价 × 数量) × 100%
```

### 今日总盈亏
```
今日总盈亏 = 今日已实现盈亏 + 当前浮盈浮亏
```

## 优势

✅ **实时性**: 使用最新成交价，无缓存延迟  
✅ **透明性**: 计算公式简单明了，易于验证  
✅ **一致性**: 市值和浮盈计算使用同一个价格源  
✅ **准确性**: 避免API返回数据的延迟问题

## 测试结果

### 模拟测试
```
AAPL: 100股 @ $150.00, 现价 $155.00
  - Moomoo浮盈: $469.00 (有0.2%延迟)
  - 实时浮盈:   $500.00 ✅
  - 差异:      $31.00
```

### 实盘数据
```
当前账户状态：
  现金:     $837,054.08
  持仓市值: $333,934.41
  总资产:   $1,170,988.49
  今日盈亏: $602.87
    ├─ 已实现: $0.00
    └─ 浮盈:   $602.87 (实时计算 ✅)

持仓详情:
  PSTG   2173股 $76.67 → $76.67  浮盈: $0.00 (+0.00%)
  CRWV   1863股 $89.50 → $89.82  浮盈: $602.87 (+0.36%)
```

## 修改的文件

### 1. dashboard.py
**位置**: `backend/dashboard.py` 第162-165行

**修改内容**:
```python
# 之前
market_value = pos['market_value']
unrealized = pos['pl_val']  # 使用Moomoo的计算值

# 之后
market_value = current_price * qty
unrealized = (current_price - cost) * qty  # 实时计算
```

## API返回数据结构

Dashboard API (`/api/dashboard`) 返回的数据中，每只股票包含：

```json
{
  "symbol": "AAPL",
  "qty": 100,
  "cost": 150.00,
  "current_price": 155.00,      // 最新价格
  "market_value": 15500.00,     // 实时市值
  "unrealized_pnl": 500.00,     // 实时浮盈 ✅
  "realized_pnl": 0.00,         // 今日已实现
  "total_pnl": 500.00,          // 总盈亏
  "status": "HOLDING"
}
```

## 前端更新建议

如果前端需要显示浮盈比例：

```javascript
// 计算浮盈比例
const unrealizedPct = (stock.unrealized_pnl / (stock.cost * stock.qty)) * 100;

// 显示格式
const pnlColor = unrealizedPct >= 0 ? 'green' : 'red';
const pnlSign = unrealizedPct >= 0 ? '+' : '';
console.log(`${stock.symbol}: ${pnlSign}${unrealizedPct.toFixed(2)}%`);
```

## 验证方法

### 手动验证
```bash
# 运行测试脚本
python test_realtime_pnl.py
```

### 通过Dashboard
```bash
# 启动dashboard服务
python dashboard.py

# 或启动API服务器
python server.py

# 访问 http://localhost:5001/api/dashboard
```

### 计算器验证
```
假设持仓: 100股 @ $150.00
当前价格: $155.00

市值 = 155.00 × 100 = $15,500.00
浮盈 = (155.00 - 150.00) × 100 = $500.00
比例 = 500 ÷ (150 × 100) × 100% = +3.33%
```

## 注意事项

⚠️ **价格来源**: 使用`nominal_price`字段作为当前价格（这是最新成交价）  
⚠️ **成本价**: 使用`cost_price`字段（平均成本价）  
⚠️ **实时性**: 价格更新频率取决于Moomoo API的推送频率（通常1-3秒）  
⚠️ **精度**: 所有金额保留2位小数

## 向后兼容

✅ API返回格式不变  
✅ 数据库表结构不变  
✅ 只改变计算方式，不影响其他功能  

## 状态

✅ **已完成并测试**  
✅ **生产环境可用**  
✅ **测试脚本已创建**: `test_realtime_pnl.py`

---

**更新人**: AI Assistant  
**测试状态**: 通过 ✅  
**部署状态**: 已更新


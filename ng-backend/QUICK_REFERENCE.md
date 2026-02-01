# ORB + Keltner Channel 策略 - 快速参考指南

## 🚀 一分钟快速启动

```bash
# 1. 初始化环境（首次运行）
./setup.sh

# 2. 启动 Moomoo OpenD
# 打开 Moomoo 桌面应用，确保 OpenD 服务运行在 127.0.0.1:11111

# 3. 运行策略
./run.sh
```

## 📋 策略核心逻辑速查

### 开仓条件（必须同时满足）
```
时间：09:45 后
1. 价格 > ORB_High（突破开盘高点）
2. 价格 > VWAP（位于均价之上）
3. 15分钟收盘价 ≤ KC上轨（避免追高）
4. 15分钟收盘价 > KC中轨（处于强势区）
```

### 平仓规则
| 触发条件 | 动作 | 优先级 |
|---------|------|-------|
| 价格跌破 ORB_Mid | 清仓 100% | 最高 |
| 浮亏达到 3% | 清仓 100% | 最高 |
| 价格达到 Entry + (Entry - ORB_Mid) | 减仓 50% (TP1) | 中 |
| 价格达到 KC_Mid + 3*ATR | 清仓 100% (TP2) | 中 |
| 连续2根15分钟K线跌破KC中轨 | 清仓 100% | 中 |
| 15:55 收盘前 | 清仓 100% | 强制 |

### 资金管理
```
总持仓：最多 5 只股票
每只股票预算：总资金 × (1/5) ÷ 1.2
市价单冻结：20% (1.2倍)
```

## 🔧 常用命令

### 环境管理
```bash
# 激活虚拟环境
source venv/bin/activate

# 退出虚拟环境
deactivate

# 重新安装依赖
pip install -r requirements.txt
```

### 运行与测试
```bash
# 测试所有模块
python test_modules.py

# 运行策略
python main.py

# 使用快速启动脚本
./run.sh
```

### 日志查看
```bash
# 实时查看日志
tail -f strategy.log

# 查看最近50行
tail -n 50 strategy.log

# 查看特定股票
grep "AAPL" strategy.log

# 查看开仓记录
grep "开仓成功" strategy.log

# 查看平仓记录
grep "平仓成功" strategy.log
```

## ⚙️ 关键参数速查

### config.py 常用参数
```python
# 交易环境
TRADE_ENV = 1              # 0=真实, 1=模拟

# 资金管理
MAX_POSITIONS = 5          # 最多持仓数量
POSITION_SIZE_RATIO = 0.2  # 每只股票占比 (1/5)

# 风控
STOP_LOSS_RATIO = 0.03     # 账户止损 3%
TP1_REDUCE_RATIO = 0.5     # TP1减仓比例 50%

# 技术指标
ATR_PERIOD = 14            # ATR周期
KC_EMA_PERIOD = 20         # KC的EMA周期
KC_ATR_MULTIPLIER = 2.0    # KC带宽倍数
```

### watchlist.json
```json
{
  "symbols": ["AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
}
```

## 🎯 状态机流转

```
State 0 (空仓)
    ↓ 触发开仓信号
State 1 (持仓中)
    ↓ 达到TP1
State 2 (半仓)
    ↓ 达到TP2/止损/反转
State 3 (结束)
```

## ⏰ 时间轴

```
09:30 ━━━━━━━━━━━━━━━━━ 开盘，开始记录ORB
09:45 ━━━━━━━━━━━━━━━━━ ORB锁定，开始监控入场
      ↓
      监控开仓信号
      管理持仓（止损止盈）
      ↓
15:55 ━━━━━━━━━━━━━━━━━ 强制平仓
16:00 ━━━━━━━━━━━━━━━━━ 收盘
```

## 📊 技术指标公式

### ORB (Opening Range Breakout)
```
时间范围：09:30 - 09:45
ORB_High = 15分钟内最高价
ORB_Low = 15分钟内最低价
ORB_Mid = (ORB_High + ORB_Low) / 2
```

### VWAP (Volume Weighted Average Price)
```
典型价格 = (High + Low + Close) / 3
VWAP = Σ(典型价格 × 成交量) / Σ(成交量)
```

### ATR (Average True Range)
```
TR = max(High - Low, |High - Close_prev|, |Low - Close_prev|)
ATR = TR的14周期移动平均
```

### Keltner Channel
```
KC_Middle = EMA(Close, 20)
KC_Upper = KC_Middle + 2 × ATR(14)
KC_Lower = KC_Middle - 2 × ATR(14)
```

### TP1 目标价
```
TP1 = Entry_Price + (Entry_Price - ORB_Mid)
即：1:1 盈亏比
```

### TP2 目标价
```
TP2 = KC_Middle + 3 × ATR
即：极端延伸位置
```

## 🐛 故障排查速查

| 问题 | 解决方案 |
|------|----------|
| 无法连接OpenD | 1. 确认OpenD已启动<br>2. 检查端口11111<br>3. 检查防火墙 |
| 订阅失败 | 1. 确认已登录Moomoo账户<br>2. 检查美股权限 |
| 资金不足 | 1. 检查模拟盘资金<br>2. 减少MAX_POSITIONS<br>3. 调小POSITION_SIZE_RATIO |
| 找不到模块 | `source venv/bin/activate` |
| 时区错误 | 检查config.ET_TIMEZONE |

## 📝 每日检查清单

### 启动前
- [ ] Moomoo OpenD 已启动
- [ ] 已登录模拟盘账户
- [ ] watchlist.json 已配置
- [ ] 虚拟环境已激活

### 运行中
- [ ] 09:45 确认 ORB 已锁定
- [ ] 监控活跃持仓数量
- [ ] 定期查看日志
- [ ] 关注异常报警

### 收盘后
- [ ] 确认 15:55 已平仓
- [ ] 查看交易记录
- [ ] 分析盈亏情况
- [ ] 备份日志文件

## 🔒 安全提醒

⚠️ **重要**
- 默认使用模拟盘（TRADE_ENV = 1）
- 切换真实交易需修改 config.py
- 真实交易前建议模拟盘测试至少2周
- 初次实盘建议降低仓位（MAX_POSITIONS = 2-3）
- 不要在重大新闻/财报时运行

## 📞 获取帮助

```bash
# 查看README
cat README.md

# 查看配置说明
cat CONFIG_GUIDE.md

# 查看实现总结
cat IMPLEMENTATION_SUMMARY.md

# 运行测试
python test_modules.py
```

## 🎓 学习资源

### 技术指标
- ORB: Opening Range Breakout 开盘区间突破
- VWAP: Volume Weighted Average Price 成交量加权均价
- ATR: Average True Range 平均真实波幅
- KC: Keltner Channel 凯尔特纳通道
- EMA: Exponential Moving Average 指数移动平均

### 策略类型
- 日内交易 (Intraday Trading)
- 突破策略 (Breakout Strategy)
- 动量交易 (Momentum Trading)
- 趋势跟踪 (Trend Following)

---

**提示**: 将此文件打印或保存到手机，交易时快速查阅。


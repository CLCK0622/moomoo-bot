# ORB + Keltner Channel 美股日内交易策略

基于 15 分钟开盘区间（ORB）和凯尔特纳通道（KC）的美股日内多头交易策略。

## 项目结构

```
ng-backend/
├── main.py              # 主程序入口
├── config.py            # 配置文件
├── trader.py            # Moomoo OpenD 交易接口
├── strategy.py          # 策略核心逻辑
├── indicators.py        # 技术指标计算
├── state_manager.py     # 交易状态管理
├── watchlist.json       # 监控股票列表
├── requirements.txt     # Python 依赖
├── setup.sh             # 环境初始化脚本
└── README.md            # 本文件
```

## 策略说明

### 交易时段
- 美东时间 09:30 - 16:00
- 09:45 锁定 ORB 数据
- 15:55 强制收盘清仓

### 技术指标
- **ORB**: 开盘后前 15 分钟（09:30-09:45）的高低点和中轴
- **VWAP**: 成交量加权平均价
- **ATR**: 14 周期平均真实波幅
- **Keltner Channel**: EMA(20) ± 2*ATR(14)

### 开仓条件（必须同时满足）
1. 当前价格 > ORB_High（突破开盘高点）
2. 当前价格 > VWAP（位于均价之上）
3. 15分钟K线收盘价 ≤ KC上轨（避免追高）
4. 15分钟K线收盘价 > KC中轨（处于强势区）

### 止损止盈规则
1. **初始止损**: 价格跌破 ORB_Mid → 清仓
2. **第一目标止盈（TP1）**: 价格达到 entry_price + (entry_price - ORB_Mid) → 减仓 50%
3. **第二目标止盈（TP2）**: 价格达到 KC_Middle + 3*ATR → 全部平仓
4. **趋势反转**: 连续 2 根 15 分钟 K 线收盘价低于 KC 中轨 → 清仓

### 风险控制
- 账户止损：单只股票浮亏达到 3% 强制清仓
- 收盘清仓：15:55 强制平掉所有仓位
- 资金管理：最多同时持有 5 只股票，每只占总资金的 1/5/1.2

## 安装与使用

### 1. 环境要求
- Python 3.8+
- Moomoo OpenD（需要运行在本地）
- Moomoo SG 美股模拟盘账户

### 2. 初始化环境

```bash
# 赋予执行权限
chmod +x setup.sh

# 运行初始化脚本
./setup.sh
```

或手动安装：

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置

编辑 `config.py` 调整参数：
- Moomoo OpenD 连接地址和端口
- 交易环境（模拟/真实）
- 策略参数（止损止盈比例、技术指标周期等）

编辑 `watchlist.json` 添加监控股票：
```json
{
  "symbols": ["AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
}
```

### 4. 启动 Moomoo OpenD

确保 Moomoo OpenD 已启动并运行在 `127.0.0.1:11111`（默认配置）。

### 5. 运行策略

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行主程序
python main.py
```

### 6. 停止策略

按 `Ctrl+C` 优雅停止程序。

## 日志

策略运行日志会同时输出到：
- 终端（实时显示）
- `strategy.log` 文件（持久化保存）

## 状态机说明

每只股票有 4 种状态：
- **State 0**: 空仓/等待买入
- **State 1**: 持仓中（初始仓位）
- **State 2**: 半仓止盈后持仓
- **State 3**: 当日交易结束（不再开仓）

## 模块说明

### `main.py`
主程序入口，负责：
- 加载监控列表
- 初始化各模块
- 主循环调度（信号检测、订单执行、风控检查）

### `config.py`
全局配置文件，包含：
- 交易环境参数
- 策略参数
- 时区和交易时段设置

### `trader.py`
Moomoo OpenD 接口封装，提供：
- 连接管理
- K线数据获取
- 下单功能（市价买卖）
- 持仓查询

### `strategy.py`
策略核心逻辑，整合：
- 数据更新
- ORB 计算
- 信号检测
- 订单执行
- 止损止盈

### `indicators.py`
技术指标计算，包含：
- VWAP
- ATR
- EMA
- Keltner Channels
- ORB
- 信号生成器

### `state_manager.py`
交易状态管理，维护：
- 每只股票的持仓状态
- 开仓信息
- ORB 数据
- 止盈标记

## 注意事项

1. **模拟盘优先**: 默认使用模拟盘环境，确保策略稳定后再切换到真实环境
2. **风险控制**: 严格遵守 3% 账户止损和收盘清仓规则
3. **网络连接**: 确保与 Moomoo OpenD 的连接稳定
4. **数据质量**: 策略依赖 1 分钟和 15 分钟 K 线数据，确保数据源正常
5. **时区设置**: 所有时间以美东时间为准，确保服务器时区配置正确

## 许可证

本项目仅供学习和研究使用，交易有风险，投资需谨慎。

## 联系方式

如有问题或建议，请通过 GitHub Issues 反馈。


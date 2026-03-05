"""
配置文件 - 策略参数与环境设置
"""
import pytz
from datetime import time

# ==================== 交易环境配置 ====================
# Moomoo 配置
MOOMOO_HOST = '127.0.0.1'  # OpenD 服务地址
MOOMOO_PORT = 11111        # OpenD 端口
MARKET = 'US'              # 美股市场
TRADE_ENV = 1              # 0=真实环境, 1=模拟环境（先用模拟盘）
SECURITY_FIRM = 2          # 2=Moomoo SG

# ==================== 时区与交易时段 ====================
ET_TIMEZONE = pytz.timezone('America/New_York')  # 美东时区

# 交易时段（美东时间）
MARKET_OPEN_TIME = time(9, 30)      # 09:30
MARKET_CLOSE_TIME = time(16, 0)     # 16:00
ORB_END_TIME = time(9, 45)          # 09:45 ORB 计算完成
FORCE_CLOSE_TIME = time(15, 55)     # 15:55 强制平仓

# ==================== 策略参数 ====================
# 资金管理
MAX_POSITIONS = 5           # 最多同时持有5只股票
POSITION_SIZE_RATIO = 0.2   # 每只股票占总资金的 1/5
MARGIN_FREEZE_RATIO = 1.2   # 市价单冻结20%，实际可用预算需除以1.2

# 技术指标参数
ATR_PERIOD = 14             # ATR 周期
KC_EMA_PERIOD = 20          # Keltner Channel EMA 周期
KC_ATR_MULTIPLIER = 2.0     # KC 带宽倍数

# 止损止盈参数
STOP_LOSS_RATIO = 0.03      # 账户止损 3%
TP1_REDUCE_RATIO = 0.5      # TP2 触发时减仓比例 50%
TP2_ATR_MULTIPLIER = 3.0    # 第二目标 = KC中轨 + 3*ATR
TRAILING_PROFIT_KEEP_RATIO = 0.2  # TP2 后半仓追踪止盈：利润回撤到峰值的 20% 时清仓

# 趋势反转确认
TREND_REVERSAL_BARS = 2     # 连续2根15分钟K线跌破KC中轨

# ==================== 数据频率 ====================
BAR_1M = 'K_1M'             # 1分钟K线
BAR_15M = 'K_15M'           # 15分钟K线

# ==================== 状态机定义 ====================
STATE_IDLE = 0              # 空仓/等待买入
STATE_POSITION = 1          # 持仓中（初始仓位）
STATE_HALF_PROFIT = 2       # 半仓止盈后持仓
STATE_DONE = 3              # 当日交易结束

# ==================== 日志配置 ====================
LOG_LEVEL = 'INFO'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_FILE = 'strategy.log'

# ==================== Watchlist 文件 ====================
WATCHLIST_FILE = 'watchlist.json'


# ==================== AI Monitor Configuration ====================
NITTER_INSTANCE = "https://nitter.poast.org"
MODEL_EXECUTIVE = "gpt-5.2-2025-12-11"

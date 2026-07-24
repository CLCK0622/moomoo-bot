"""
预测市场（Kalshi / Polymarket / Limitless）只读数据接入 —— 配置

只读基线（对齐 quant SIMULATE-only）：
  本模块只做行情读取与纸面回测，代码中不存在任何下单 / 入金 / 提现 / 撤单路径。
  Kalshi WS 的 RSA-PSS 鉴权会话仅用于订阅公开行情频道。

价格口径：所有 venue 统一归一到「每份合约以 $1 结算」的美元概率价（0.0 ~ 1.0）。
"""
import os

# ==================== 环境常量 ====================
# 只读硬开关：任何写路径都不应存在；此常量用于运行期自检与测试断言。
READ_ONLY = True
# 对齐 EVO SIMULATE-only 基线：禁止实盘 / 真金 / 下单。
SIMULATE_ONLY = True

# ==================== Kalshi ====================
# 生产 REST（行情 GET 端点公开，无需鉴权 —— 已实测 HTTP 200）
KALSHI_REST_PROD = "https://api.elections.kalshi.com/trade-api/v2"
# Demo（模拟盘，镜像生产，含 WS）
KALSHI_REST_DEMO = "https://demo-api.kalshi.co/trade-api/v2"

# WebSocket（连接需 RSA-PSS 鉴权，即使只订阅公开频道 —— 已实测无凭证 401）
KALSHI_WS_PROD = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
KALSHI_WS_DEMO = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
# 旧端点仍可用，作为兜底
KALSHI_WS_PROD_LEGACY = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# API key 凭证从环境变量读取（.env）；无凭证时 REST 只读照常工作，仅 WS 不可用。
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")
# 私钥 PEM 文件路径（不入库；.gitignore 已覆盖 *.pem / .env）
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

# ==================== Polymarket ====================
# 全部公开只读（已实测 HTTP 200）
POLY_GAMMA = "https://gamma-api.polymarket.com"
POLY_CLOB = "https://clob.polymarket.com"

# ==================== Limitless ====================
LIMITLESS_API = "https://api.limitless.exchange"

# ==================== 手续费 / 结算模型 ====================
# 说明：回测「净额」= 1 - 各腿买入成本 - 各腿手续费。赢方到期按 $1 结算，
# Kalshi/Polymarket 均无单独结算费，交易费已在成交时计入。
#
# Kalshi 通用交易费公式（官方 fee schedule）：
#   fee = ceil_to_cent( rate * C * P * (1 - P) )   —— rate 默认 0.07（部分指数类品种 0.035）
# 以美元计、按合约数 C，向上取整到分。P 为成交价（0~1）。
KALSHI_FEE_RATE = 0.07          # 通用档；标普/纳指区间类可传 0.035
KALSHI_MAKER_FEE_RATE = 0.0     # 多数品种 maker 免费；个别品种有 maker 费，按需覆盖

# Polymarket：当前 CLOB 交易零手续费（maker/taker=0）。链上 gas 由中继抽象，
# 对纸面套利近似 0；保留可配置项。
POLY_TAKER_FEE_RATE = 0.0
POLY_MAKER_FEE_RATE = 0.0

# Limitless：费率需以官方 fee 文档核实后再定；此处给保守占位默认，并在报告中标注「未核实」。
# 若无法核实，回测按最坏情形上调此值做敏感性分析。
LIMITLESS_FEE_RATE = 0.0        # TODO: 核实 Limitless 实际费率后覆盖（占位，勿直接采信）

# ==================== 事件匹配 ====================
# 跨 venue「同事件」匹配阈值（保守）；自动匹配仅用于「候选建议」，
# 进入回测的配对必须落到 mappings/curated_pairs.json 人工确认。
MATCH_TITLE_MIN_JACCARD = 0.55
MATCH_MAX_RESOLUTION_SKEW_SEC = 6 * 3600   # 结算窗口错位上限（秒）

# ==================== 运行 / 采集 ====================
HTTP_TIMEOUT = 20
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MAPPINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings")

# config.py
from pathlib import Path
from dotenv import load_dotenv

# 1. 获取当前文件的目录 (即 backend/)
current_dir = Path(__file__).resolve().parent

# 2. 获取项目根目录 (即 backend 的上一级)
root_dir = current_dir.parent

# 3. 指定 .env 路径
env_path = root_dir / '.env'

# 4. 加载环境变量
# override=True 表示如果系统环境有变量，优先用 .env 里的覆盖 (可选)
load_dotenv(dotenv_path=env_path)

# --- 模型配置 ---
# 便宜模型 (用于采集清洗)
MODEL_COLLECTOR = "gpt-5-mini-2025-08-07"

# 严谨模型 (用于市场数据)
MODEL_MARKET = "gpt-5-mini-2025-08-07"

# 聪明模型 (用于决策和急救)
MODEL_EXECUTIVE = "gpt-5.2-2025-12-11"  # 或者 gpt-5-mini

# --- Nitter ---
NITTER_INSTANCE = "https://nitter.dashy.a3x.dn.nyx.im"

# --- 周期配置 ---
COLLECTION_INTERVAL = 30 * 60  # 30分钟
ANALYSIS_INTERVAL = 4 * 60 * 60 # 4小时

# Moomoo
MOOMOO_HOST = '127.0.0.1'
MOOMOO_PORT = 11111
TRADING_PASSWORD = '762185' # ⚠️ 注意安全，不要提交到 GitHub
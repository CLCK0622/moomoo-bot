"""
Kalshi RSA-PSS 请求签名（仅用于 WebSocket 只读行情会话）。

签名规范（官方 docs.kalshi.com/getting_started/quick_start_authenticated_requests）：
  headers:
    KALSHI-ACCESS-KEY        = API Key ID
    KALSHI-ACCESS-TIMESTAMP  = 毫秒时间戳字符串
    KALSHI-ACCESS-SIGNATURE  = base64( RSA-PSS(SHA256, MGF1-SHA256, salt=DIGEST_LENGTH) )
  待签名串 = f"{timestamp}{METHOD}{path}"，path 含 /trade-api/... 且去掉 query。

cryptography 为惰性导入：REST 只读不依赖它，仅签名时才需要。
"""
import base64
import time
from typing import Tuple

# WS 鉴权固定签名路径（method 固定 GET）
WS_SIGN_PATH = "/trade-api/ws/v2"


def load_private_key(pem_path: str):
    """从 PEM 文件加载 RSA 私钥。"""
    from cryptography.hazmat.primitives import serialization  # 惰性导入
    with open(pem_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def sign_pss(private_key, message: str) -> str:
    """对 message 做 RSA-PSS 签名并 base64 编码。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("utf-8")


def now_ms() -> str:
    return str(int(time.time() * 1000))


def build_headers(key_id: str, private_key, method: str, path: str,
                  timestamp: str = None) -> dict:
    """构造 Kalshi 鉴权头。path 需含 /trade-api/... 前缀、不含 query。"""
    ts = timestamp or now_ms()
    path_no_query = path.split("?")[0]
    message = f"{ts}{method.upper()}{path_no_query}"
    signature = sign_pss(private_key, message)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def signed_message(timestamp: str, method: str, path: str) -> str:
    """返回将被签名的原文（便于单测比对，不触碰 cryptography）。"""
    return f"{timestamp}{method.upper()}{path.split('?')[0]}"


def load_from_config() -> Tuple[str, object]:
    """从 config（环境变量）加载 (key_id, private_key)。缺失则抛错，调用方按只读降级。"""
    from . import config
    if not config.KALSHI_API_KEY_ID or not config.KALSHI_PRIVATE_KEY_PATH:
        raise RuntimeError(
            "Kalshi API 凭证未配置（KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH）。"
            "REST 公开行情无需凭证；仅 WS 会话需要。"
        )
    return config.KALSHI_API_KEY_ID, load_private_key(config.KALSHI_PRIVATE_KEY_PATH)

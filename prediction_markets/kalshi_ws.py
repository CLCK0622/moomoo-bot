"""
Kalshi WebSocket 只读行情客户端。

约束：
  - WS 连接必须 RSA-PSS 鉴权（即使只订阅公开频道，无凭证实测 401）。
  - 仅允许订阅只读行情频道（见 READ_ONLY_CHANNELS）；不含任何下单/账户写命令。
  - 无凭证时抛错，调用方应降级到 REST 轮询（spread_monitor 已内置该降级）。

依赖 websockets（异步）。签名路径固定为 "/trade-api/ws/v2"，method="GET"。
"""
import json
import asyncio
import logging
from typing import Callable, List, Optional

from . import config
from . import kalshi_auth

log = logging.getLogger("pm.kalshi_ws")

# 只读白名单：任何不在其中的频道一律拒绝订阅（防止误连私有/写相关频道）
READ_ONLY_CHANNELS = {"ticker", "trade", "orderbook_delta", "market_lifecycle_v2"}

# 复用 auth 模块的固定签名路径
WS_SIGN_PATH = kalshi_auth.WS_SIGN_PATH


class KalshiReadOnlyWS:
    def __init__(self, market_tickers: List[str],
                 channels: List[str] = None,
                 on_message: Callable[[dict], None] = None,
                 ws_url: str = None,
                 key_id: str = None,
                 private_key=None):
        channels = channels or ["ticker"]
        bad = set(channels) - READ_ONLY_CHANNELS
        if bad:
            raise ValueError(f"只读客户端拒绝非行情频道: {sorted(bad)}")
        self.market_tickers = market_tickers
        self.channels = channels
        self.on_message = on_message or (lambda m: log.info("ws msg: %s", m))
        self.ws_url = ws_url or config.KALSHI_WS_PROD
        self._key_id = key_id
        self._private_key = private_key
        self._msg_id = 0

    def _ensure_creds(self):
        if self._key_id and self._private_key:
            return
        # 从 config 惰性加载；缺失会抛 RuntimeError
        self._key_id, self._private_key = kalshi_auth.load_from_config()

    def _auth_headers(self):
        return kalshi_auth.build_headers(self._key_id, self._private_key, "GET", WS_SIGN_PATH)

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def run(self, max_reconnects: int = 5):
        """连接 + 订阅 + 分发。断线指数退避重连。仅读取。"""
        import websockets  # 惰性导入
        self._ensure_creds()
        attempt = 0
        while attempt <= max_reconnects:
            try:
                headers = self._auth_headers()   # 每次连接重新签名（时间戳时效）
                async with websockets.connect(self.ws_url, additional_headers=headers,
                                              ping_interval=10, ping_timeout=20) as ws:
                    log.info("WS 已连接 %s", self.ws_url)
                    await self._subscribe(ws)
                    attempt = 0   # 连上即重置退避
                    async for raw in ws:
                        try:
                            self.on_message(json.loads(raw))
                        except json.JSONDecodeError:
                            log.warning("非 JSON 消息: %s", raw[:200])
            except Exception as e:
                attempt += 1
                backoff = min(30, 2 ** attempt)
                log.warning("WS 断开(%s)，%ss 后重连 (第 %d 次)", e, backoff, attempt)
                await asyncio.sleep(backoff)
        log.error("WS 超过最大重连次数，退出")

    async def _subscribe(self, ws):
        cmd = {
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": self.channels,
                "market_tickers": self.market_tickers,
            },
        }
        await ws.send(json.dumps(cmd))
        log.info("已发送订阅: channels=%s markets=%d", self.channels, len(self.market_tickers))


def stream(market_tickers: List[str], channels: List[str] = None,
           on_message: Callable[[dict], None] = None,
           demo: bool = False) -> None:
    """同步入口：阻塞运行 WS 只读流（需已配置 Kalshi 凭证）。"""
    ws_url = config.KALSHI_WS_DEMO if demo else config.KALSHI_WS_PROD
    client = KalshiReadOnlyWS(market_tickers, channels=channels,
                              on_message=on_message, ws_url=ws_url)
    asyncio.run(client.run())

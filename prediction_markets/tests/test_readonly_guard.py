"""
只读不变量守卫：扫描全包源码，确认不存在任何下单/入金/提现/撤单写路径。
这是硬约束（对齐 SIMULATE-only 基线）：新增代码若引入写路径，本测试必须失败。
"""
import os
import re

# 禁止出现的写相关标识（HTTP 写动词 + 交易/资金动作词）。用词边界避免误伤注释里的中文说明。
FORBIDDEN = [
    r"\.post\(", r"\.put\(", r"\.delete\(", r"\.patch\(",
    r"create_order", r"place_order", r"submit_order", r"cancel_order",
    r"createOrder", r"placeOrder", r"deposit", r"withdraw",
    r"TrdEnv\.REAL", r"trd_env\s*=\s*REAL",
]

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _iter_py():
    for root, _, files in os.walk(PKG_DIR):
        if os.path.basename(root) == "tests":
            continue
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def test_no_write_paths():
    hits = []
    for path in _iter_py():
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        for pat in FORBIDDEN:
            for m in re.finditer(pat, src):
                # 允许出现在字符串常量/注释里的英文说明？——从严：一律不允许出现可执行调用形态。
                hits.append((os.path.relpath(path, PKG_DIR), pat, m.group(0)))
    assert not hits, f"检测到疑似写路径，违反只读不变量: {hits}"


def test_config_read_only_flags():
    from prediction_markets import config
    assert config.READ_ONLY is True
    assert config.SIMULATE_ONLY is True


def test_ws_channels_are_read_only():
    from prediction_markets import kalshi_ws
    # 白名单只含行情频道，不含任何账户/成交私有写频道
    assert kalshi_ws.READ_ONLY_CHANNELS <= {
        "ticker", "trade", "orderbook_delta", "market_lifecycle_v2"
    }
    # 尝试订阅非白名单频道应被拒
    try:
        kalshi_ws.KalshiReadOnlyWS(["X"], channels=["fill"])
        raised = False
    except ValueError:
        raised = True
    assert raised


TESTS = [test_no_write_paths, test_config_read_only_flags, test_ws_channels_are_read_only]

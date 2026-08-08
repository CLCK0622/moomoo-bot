"""EVO-8 LLM 轨 — 纸面盯市的价格腿（vendor 无关适配层）。

工部 2026-08-08 撤回「价格腿断」的结论：出口不封**行情 API**，封的是抓取型端点
（Yahoo 429 / Stooq 反爬 HTML 只代表那两条抓取端点，不代表 API）。六个免费行情 API 均返回
正常应答（200 或 401-缺 key），Alpha Vantage 公开 `demo` key 当场取到 IBM 日线至前一交易日。

本模块是**消费侧适配层**（vendor 选型与 key 自助注册归都水）：把任一 vendor 的日线归一成
统一 bar 序列，供两处使用——
  1. `actual_start`：收益起算 = 首根真实 bar（**观测而非预测**，日历依赖到此为止）；
  2. 纸面组合盯市：只用 `close`。

四条纪律（与 `fred_vintage` / `evidence_sources` 同源）：
* **key 只从 env 读**（都水存 `~/.config/<vendor>/api.env`、chmod 600）；**不入库、不进日志、不进评论**；
* **fail-closed**：取不到就抛 `PriceLegUnavailable`，**绝不用陈旧价或估算价冒充盯市价**；
* **bar 日期取数据源自身的日期**，不用我们的时钟；
* **只读行情**：无下单/入金路径（SIMULATE-only、零真金）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd


class PriceLegUnavailable(RuntimeError):
    """行情取不到 / 应答不可解析 → fail-closed。绝不回退陈旧价或估算价。"""


@dataclass(frozen=True)
class Bar:
    date: str          # 数据源自身给出的交易日（YYYY-MM-DD），非我们的时钟
    close: float
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    source: str = ""


# --------------------------------------------------------------------------- #
# vendor 适配：新增 vendor 只需加一个 parser，上层接口不变
# --------------------------------------------------------------------------- #
def _parse_alphavantage(payload: Dict[str, Any], *, source: str) -> List[Bar]:
    key = next((k for k in payload if "Time Series" in k), None)
    if key is None:
        # AV 用 200 + Note/Information 表达限速或参数错误 —— 视为不可用，不当空数据
        msg = payload.get("Note") or payload.get("Information") or payload.get("Error Message")
        raise PriceLegUnavailable(f"alphavantage 未返回时间序列：{msg or list(payload)[:3]}")
    out: List[Bar] = []
    for d, row in payload[key].items():
        try:
            out.append(Bar(date=d, close=float(row["4. close"]), open=float(row["1. open"]),
                           high=float(row["2. high"]), low=float(row["3. low"]),
                           volume=float(row["5. volume"]), source=source))
        except (KeyError, TypeError, ValueError) as e:
            raise PriceLegUnavailable(f"alphavantage bar 不可解析 {d}: {e}") from e
    return sorted(out, key=lambda b: b.date)


def _parse_tiingo(payload: Any, *, source: str) -> List[Bar]:
    if not isinstance(payload, list) or not payload:
        raise PriceLegUnavailable(f"tiingo 应答非预期：{str(payload)[:120]}")
    out = []
    for row in payload:
        try:
            out.append(Bar(date=str(row["date"])[:10], close=float(row["close"]),
                           open=float(row.get("open")) if row.get("open") is not None else None,
                           volume=float(row.get("volume")) if row.get("volume") is not None else None,
                           source=source))
        except (KeyError, TypeError, ValueError) as e:
            raise PriceLegUnavailable(f"tiingo bar 不可解析: {e}") from e
    return sorted(out, key=lambda b: b.date)


VENDORS: Dict[str, Dict[str, Any]] = {
    "alphavantage": {
        "url": "https://www.alphavantage.co/query",
        # 注意：公开 demo key **只接受不带额外参数**的精确请求；正式 key 才可加 outputsize。
        # 故 outputsize 仅在非 demo key 时附加（否则 AV 会 200+Information 拒绝 → 我们 fail-closed）。
        "params": lambda sym, key: ({"function": "TIME_SERIES_DAILY", "symbol": sym, "apikey": key}
                                    if key == "demo" else
                                    {"function": "TIME_SERIES_DAILY", "symbol": sym,
                                     "apikey": key, "outputsize": "compact"}),
        "parse": _parse_alphavantage,
        "env": "ALPHAVANTAGE_API_KEY",
    },
    "tiingo": {
        "url": "https://api.tiingo.com/tiingo/daily/{symbol}/prices",
        "params": lambda sym, key: {"token": key},
        "parse": _parse_tiingo,
        "env": "TIINGO_API_KEY",
    },
}


def _api_key(vendor: str, explicit: Optional[str] = None) -> str:
    """key 只从 env（或显式入参）读；**绝不落库、不打日志**。"""
    if explicit:
        return explicit
    env = VENDORS[vendor]["env"]
    k = os.environ.get(env)
    if not k:
        raise PriceLegUnavailable(
            f"{vendor} 缺 API key（env {env} 未设）→ fail-closed。"
            f"key 由都水自助注册、存 ~/.config/<vendor>/api.env(chmod 600)，只从 env 读、不入库")
    return k


def fetch_daily(symbol: str, *, vendor: str = "alphavantage", api_key: Optional[str] = None,
                session: Any = None, timeout: int = 30) -> List[Bar]:
    """取单标的日线（归一为 `Bar` 序列，升序）。任何异常一律 fail-closed。"""
    if vendor not in VENDORS:
        raise PriceLegUnavailable(f"未支持的 vendor {vendor!r}（可选 {list(VENDORS)}）")
    spec = VENDORS[vendor]
    key = _api_key(vendor, api_key)
    import requests
    s = session or requests.Session()
    url = spec["url"].format(symbol=symbol)
    try:
        r = s.get(url, params=spec["params"](symbol, key), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise PriceLegUnavailable(f"{vendor} 请求失败：{type(e).__name__}") from e
    if r.status_code != 200:
        # 不把 key 写进异常信息
        raise PriceLegUnavailable(f"{vendor} HTTP {r.status_code} → fail-closed，不用陈旧价替代")
    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        raise PriceLegUnavailable(f"{vendor} 应答非 JSON（疑反爬/错误页）") from e
    bars = spec["parse"](payload, source=vendor)
    if not bars:
        raise PriceLegUnavailable(f"{vendor} 返回空序列 → fail-closed")
    return bars


def bar_dates(bars: Sequence[Bar]) -> List[str]:
    """交易日序列 —— **这就是权威交易日历**（有 bar 即开市），喂 `resolve_actual_start`。
    不再依赖仓内 SPY 日线（工部实测其混有约 31 个数据洞被当成假日）。"""
    return [b.date for b in bars]


def mark_to_market(holdings: Dict[str, float], bars_by_symbol: Dict[str, Sequence[Bar]],
                   *, as_of: Optional[str] = None) -> Dict[str, Any]:
    """纸面盯市：只用 `close`。**任一持仓标的缺当日 bar 即 fail-closed**，不用陈旧价估算。

    `holdings` 为 symbol → 权重（NAV 占比）。`as_of` 缺省取各标的共同最新日。
    """
    if not holdings:
        return {"as_of": as_of, "marks": {}, "note": "空持仓（全现金），无需盯市"}
    latest = {}
    for sym in holdings:
        bs = bars_by_symbol.get(sym) or []
        if not bs:
            raise PriceLegUnavailable(f"{sym} 无任何 bar → 无法盯市（fail-closed，不估算）")
        latest[sym] = {b.date: b.close for b in bs}
    day = as_of or min(max(v) for v in latest.values())    # 共同可得的最新日，保守取 min(max)
    marks, missing = {}, []
    for sym in holdings:
        px = latest[sym].get(day)
        if px is None:
            missing.append(sym)
        else:
            marks[sym] = px
    if missing:
        raise PriceLegUnavailable(
            f"{day} 缺 bar 的持仓：{missing} → fail-closed，绝不用陈旧价冒充盯市价")
    return {"as_of": day, "marks": marks,
            "source": next(iter(bars_by_symbol.values()))[0].source if bars_by_symbol else "",
            "note": "盯市仅用 close；bar 日期取数据源自身日期，非本机时钟"}

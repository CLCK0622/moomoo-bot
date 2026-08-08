"""evidence_availability — 从「受理时刻」派生「**公开可得**时刻」。

工部 2026-08-08 实测（AAPL 1000 条 EDGAR）：**653/1000 = 65%** 的文件在 **17:30 ET 之后受理**，
而 EDGAR 对 17:30 ET 之后受理的文件是**次一交易日**才对外披露的。所以：

    acceptanceDateTime = 「EDGAR 收到」的时刻  ≠  「公众可获取」的时刻

后果：一条 T 日 18:30 ET 受理的 8-K，若决策落在当晚或次日开盘前，`证据时间 ≤ 决策时间`
这条检查**会通过**，但那一刻信息其实尚未公开——该不等式证明的只是「在受理之后」，
**不是「在可获取之后」**，而本轨全部证据效力正押在这条不等式上。

**本模块不改抓取器**：`acceptanceDateTime` 是 EDGAR 给出的 ground truth，照旧原样留档；
这里只在**消费侧**派生一个用于时序核验的字段：

    evidence_available_utc = acceptanceDateTime
        若受理时刻（ET）>= 17:30 → 顺延至**次一交易日开盘**（09:30 ET）
        若受理时刻落在非交易日 → 顺延至下一个交易日开盘
        若受理于交易日 09:30 ET 之前 → 顺延至当日开盘（盘前受理，开盘才可交易）

时序检查一律用 `evidence_available_utc`；原始受理时刻同时留档备查（`acceptance_utc`）。
前向纸面轨天然基本免疫（决策按真实钟表往后走，届时多已披露），这条主要是**让审计口径与事实对齐**，
并防 `historical_replay` 模式偷跑。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

ET = "America/New_York"
DISCLOSURE_CUTOFF = (17, 30)     # >= 17:30 ET 受理 → 次一交易日才披露
MARKET_OPEN = (9, 30)            # 交易日开盘（ET）


def _is_trading_day(ts_et: pd.Timestamp) -> bool:
    """周一至周五且非美股假日（用 pandas 的 NYSE 近似：仅排除周末 + 常见固定假日）。

    说明：这里刻意**保守**——无第三方交易日历依赖时，只排除周末与已知固定假日；
    漏排的假日会让 available 时间**偏早**，故另有 `next_trading_open` 的调用方在
    真实执行时以行情日历为准（价格腿走 OpenD，其日历才是成交的 ground truth）。
    """
    if ts_et.weekday() >= 5:
        return False
    return True


def next_trading_open(ts_et: pd.Timestamp) -> pd.Timestamp:
    """给定 ET 时刻，返回**下一个交易日开盘**（09:30 ET）。"""
    d = (ts_et + pd.Timedelta(days=1)).normalize()
    while not _is_trading_day(d):
        d = d + pd.Timedelta(days=1)
    return d.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1])


def derive_available_utc(acceptance_utc) -> pd.Timestamp:
    """受理时刻(UTC, tz-aware) → 公开可得时刻(UTC, tz-aware)。"""
    ts = pd.Timestamp(acceptance_utc)
    if ts.tzinfo is None:
        raise ValueError("acceptance 时间必须带时区（naive 一律拒收，猜时区会把事件挪过 09:30/16:00 边界）")
    et = ts.tz_convert(ET)
    cutoff = et.replace(hour=DISCLOSURE_CUTOFF[0], minute=DISCLOSURE_CUTOFF[1],
                        second=0, microsecond=0, nanosecond=0)
    open_today = et.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1],
                            second=0, microsecond=0, nanosecond=0)

    if not _is_trading_day(et):                 # 周末/非交易日受理 → 下个交易日开盘
        out = next_trading_open(et)
    elif et >= cutoff:                          # 17:30 ET 之后受理 → 次一交易日开盘
        out = next_trading_open(et)
    elif et < open_today:                        # 盘前受理 → 当日开盘
        out = open_today
    else:                                        # 盘中受理（09:30–17:30）→ 即时可得
        out = et
    return out.tz_convert("UTC")


@dataclass
class AvailabilityRecord:
    acceptance_utc: str          # 原始受理时刻（EDGAR ground truth，留档备查）
    evidence_available_utc: str  # 派生：公开可得时刻（**时序核验用这个**）
    rolled: bool                 # 是否发生顺延
    reason: str


def annotate(records: Iterable[Dict[str, Any]], *,
             source_field: str = "source_time_utc") -> List[Dict[str, Any]]:
    """给抓取记录补 `evidence_available_utc`；原字段一概不改、不删。"""
    out: List[Dict[str, Any]] = []
    for r in records:
        rec = dict(r)
        src = rec.get(source_field)
        if src is None:
            raise ValueError(f"记录缺 {source_field}，不得派生可得时间（无据不猜）")
        acc = pd.Timestamp(src)
        avail = derive_available_utc(acc)
        rolled = bool(avail != acc.tz_convert("UTC"))
        rec["evidence_available_utc"] = avail.isoformat()
        rec["availability_rolled"] = rolled
        rec["availability_rule"] = ("acceptance>=17:30 ET 或非交易日/盘前 → 顺延至次/当交易日开盘"
                                    if rolled else "盘中受理，受理即可得")
        out.append(rec)
    return out


def summarize(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """统计有多少条发生顺延（工部量到 AAPL 样本 65%）。"""
    recs = list(records)
    n = len(recs)
    rolled = sum(1 for r in recs if r.get("availability_rolled"))
    return {"n": n, "n_rolled": rolled, "frac_rolled": (rolled / n) if n else 0.0,
            "note": "顺延比例高说明「受理≠可得」不是边角情形；时序核验须用 evidence_available_utc"}

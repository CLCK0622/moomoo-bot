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

**交易日历（工部 2026-08-08 补）**：不引第三方日历库、不硬编假日表——直接以仓内 `SPY_1d.parquet`
的日期集合为 NYSE 实际开市日（ground truth，自动含全部假日与半日市、随数据更新自维护、零新依赖）。
实测该日历 5018 天(2006→2026)，工作日中的非交易日 212 天 ≈ **10.6 天/年**；工部量到顺延目标正好落在
市场假日的样本占 **1.0%**（如受理 2025-08-29 18:30 ET 原判 09-01 劳动节、2023-04-06 17:48 ET 原判
04-07 耶稣受难日）——比例不高但**方向不保守**（available 判早 ⇒ 可用到当时还不可交易的信息），故必修。
**覆盖范围之外 fail-closed**（`CalendarCoverageError`），绝不回退「只排周末」。
证据可得性用本日历判定；**真实成交以 OpenD 行情日历为准**，两者冲突取更晚者（保守）。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

ET = "America/New_York"
DISCLOSURE_CUTOFF = (17, 30)     # >= 17:30 ET 受理 → 次一交易日才披露
MARKET_OPEN = (9, 30)            # 交易日开盘（ET）


class CalendarCoverageError(ValueError):
    """日期超出 SPY 派生交易日历的覆盖范围 → fail-closed，拒绝参与时序核验。

    绝不回退到「只排周末」：那会在覆盖边缘悄悄恢复不保守行为（把假日判成可交易日、
    available 时间偏早），正是本派生规则要防的东西（工部 2026-08-08）。
    """


_CAL_CACHE: Optional[Dict[str, Any]] = None
# SPY 日线即 NYSE 实际开市日 = ground truth：自动含全部假日与半日市，随数据更新自维护，零新依赖
_SPY_CANDIDATES = ("data/daily_full/SPY_1d.parquet", "data/gem/SPY_1d.parquet",
                   "qlab/data/daily_full/SPY_1d.parquet", "qlab/data/gem/SPY_1d.parquet")


def load_trading_calendar(path: Optional[str] = None) -> Dict[str, Any]:
    """从仓内 SPY 日线派生 NYSE 交易日历（缓存）。返回 {days:set, first, last, source, n}。"""
    global _CAL_CACHE
    if _CAL_CACHE is not None and path is None:
        return _CAL_CACHE
    from pathlib import Path as _P
    cands = [path] if path else list(_SPY_CANDIDATES)
    for c in cands:
        if c and _P(c).exists():
            df = pd.read_parquet(c)
            days = pd.to_datetime(df["date"]).dt.normalize()
            idx = pd.DatetimeIndex(sorted(days.unique()))
            cal = {"days": set(idx), "first": idx.min(), "last": idx.max(),
                   "source": str(c), "n": len(idx)}
            if path is None:
                _CAL_CACHE = cal
            return cal
    raise CalendarCoverageError(
        f"找不到 SPY 日线以派生交易日历（试过 {cands}）；不得回退到「只排周末」")


def _is_trading_day(ts_et: pd.Timestamp, cal: Optional[Dict[str, Any]] = None) -> bool:
    """该日是否为 NYSE 实际开市日 —— 以仓内 SPY 日线为 ground truth（含假日/半日市）。

    覆盖范围之外一律 `CalendarCoverageError`（fail-closed），**不回退周末规则**。
    另：证据可得性判定用本日历；**真实成交以 OpenD 行情日历为准**，两者冲突时取更晚者（保守）。
    """
    cal = cal or load_trading_calendar()
    day = ts_et.tz_localize(None).normalize() if ts_et.tzinfo else ts_et.normalize()
    if day < cal["first"] or day > cal["last"]:
        raise CalendarCoverageError(
            f"{day.date()} 超出交易日历覆盖 [{cal['first'].date()}, {cal['last'].date()}]"
            f"（源 {cal['source']}）→ fail-closed，标 availability_unverified、拒绝参与时序核验")
    return day in cal["days"]


def next_trading_open(ts_et: pd.Timestamp, cal: Optional[Dict[str, Any]] = None) -> pd.Timestamp:
    """给定 ET 时刻，返回**下一个真实开市日**的开盘（09:30 ET）——跳过周末**与假日**。"""
    cal = cal or load_trading_calendar()
    d = (ts_et + pd.Timedelta(days=1)).normalize()
    while not _is_trading_day(d, cal):          # 覆盖外会抛 CalendarCoverageError（fail-closed）
        d = d + pd.Timedelta(days=1)
    return d.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1])


def derive_available_utc(acceptance_utc) -> pd.Timestamp:
    """受理时刻(UTC, tz-aware) → 公开可得时刻(UTC, tz-aware)。"""
    ts = pd.Timestamp(acceptance_utc)
    if ts.tzinfo is None:
        raise ValueError("acceptance 时间必须带时区（naive 一律拒收，猜时区会把事件挪过 09:30/16:00 边界）")
    cal = load_trading_calendar()
    et = ts.tz_convert(ET)
    cutoff = et.replace(hour=DISCLOSURE_CUTOFF[0], minute=DISCLOSURE_CUTOFF[1],
                        second=0, microsecond=0, nanosecond=0)
    open_today = et.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1],
                            second=0, microsecond=0, nanosecond=0)

    if not _is_trading_day(et, cal):                 # 周末/非交易日受理 → 下个交易日开盘
        out = next_trading_open(et, cal)
    elif et >= cutoff:                          # 17:30 ET 之后受理 → 次一交易日开盘
        out = next_trading_open(et, cal)
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

"""AV `TIME_SERIES_DAILY` 到底是 as-traded 还是回溯复权？—— **1 次调用定性 + 定量**。

    python3 qlab/tools/check_av_adjustment.py            （仓根执行；花 1 次 AV EXPLORATION 额度）
    python3 qlab/tools/check_av_adjustment.py --dry-run  （不打网络，只打印将要做什么）

**为什么要问**（工部尚书 2026-08-27）：本轨对公司行为**零处理**——`qlab/llm_paper/` 零 parquet
引用，`quotes_api.py` 全文 `split|adjust|dividend` 命中 0，而 `quotes_api_provenance.json` 记了
endpoint / 覆盖 / 预算 / fail-closed / 日历 / 配额 / key 泄漏 / 配额分歧，**唯独一个字没提复权**。
后果分两种，方向都不好：

* 若 **as-traded**：持仓周内遇拆股 ⇒ 价格跳变而 `shares` 不变 ⇒ 该格当轮读数是假的，
  方向不定、量级可达数十个百分点；持仓期股息一律丢失（朝严）。
* 若 **回溯复权**：同一格跨轮的 round JSON 落在**不同价格标尺**上，拼出的净值序列在拆股处假跳。

**测法**：拿 AV 的 SPY 与仓内 `qlab/data/gem/SPY_1d.parquet`（OpenD K_DAY **qfq**，
`rate_carry_provenance.json:treasury_etf_bars.adjustment_basis` 断言为 split+dividend 复权）
在重叠区间逐日比 close。qfq 以该 parquet 自己的末日为锚，故：

* AV 若 **as-traded** ⇒ 比值 `av/pq` 在末日≈1，往前每遇一次除息**台阶式抬升**；
* AV 若 **回溯复权** ⇒ 比值全程≈1，无台阶。

比值是**乘性**的，拆股与分红都会在同一条曲线上现形，不需要事先知道除息日。

**边界**：本脚本**不改任何轮内代码**，不进符号并集、不进 08-31 的配额（按 UTC 日切，今日额度
与 08-31 无关），purpose 走 `EXPLORATION`（这是研究性核对，不是盯市，不该占盯市预留）。
只出结论与量级，动不动由吏部定。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QLAB_ROOT = _REPO_ROOT / "qlab"
for _p in (str(_QLAB_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

DATA_DIRS = ("gem", "daily_full")      # 两处都是 OpenD K_DAY qfq（split+dividend 复权）
STEP_BPS = 5.0        # 比值日变动超过这个门槛即视作一次「台阶」（普通日应为 0）


def _parquet_for(symbol: str) -> Path:
    for d in DATA_DIRS:
        p = _REPO_ROOT / "qlab" / "data" / d / f"{symbol}_1d.parquet"
        if p.exists():
            return p
    raise SystemExit(f"仓内找不到 {symbol} 的 qfq parquet（找过 {DATA_DIRS}）→ 换个标的。")


def _load_key() -> str:
    """key 只从环境读；没有则从 `~/.config/alphavantage/api.env`（chmod 600）载入。

    与 `quotes_api.get_api_key` 同一条纪律：**绝不回显、绝不写进任何产物**。
    """
    if os.environ.get("ALPHAVANTAGE_API_KEY"):
        return os.environ["ALPHAVANTAGE_API_KEY"]
    env = Path.home() / ".config" / "alphavantage" / "api.env"
    if not env.exists():
        raise SystemExit(f"缺 ALPHAVANTAGE_API_KEY，且 {env} 不存在 → 不猜、不降级。")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("export ").strip()
        if line.startswith("ALPHAVANTAGE_API_KEY="):
            key = line.split("=", 1)[1].strip().strip("'\"")
            os.environ["ALPHAVANTAGE_API_KEY"] = key
            return key
        if line and "=" not in line:                 # 裸 key 文件
            os.environ["ALPHAVANTAGE_API_KEY"] = line
            return line
    raise SystemExit(f"{env} 里没找到 ALPHAVANTAGE_API_KEY")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    symbol = argv[argv.index("--symbol") + 1] if "--symbol" in argv else "SPY"
    # compact ≈ 100 个交易日（够看除息）；full ≈ 全历史（够看拆股——拆股稀疏，compact 窗里通常没有）
    outputsize = argv[argv.index("--outputsize") + 1] if "--outputsize" in argv else "compact"

    parquet = _parquet_for(symbol)
    pq = pd.read_parquet(parquet)[["date", "close"]].copy()
    pq["date"] = pq["date"].astype(str)
    print(f"仓内 parquet  {parquet.relative_to(_REPO_ROOT)}  "
          f"{pq['date'].iloc[0]} → {pq['date'].iloc[-1]}  ({len(pq)} 行)")
    print("  复权基准    rate_carry_provenance.json:treasury_etf_bars.adjustment_basis "
          "= split + DIVIDEND adjusted (total return)，来源 OpenD K_DAY qfq")

    from qlab.events.datafetch.api_quota import EXPLORATION, guard_from_env
    guard = guard_from_env()
    snap = guard.status()
    print(f"配额（今日 UTC {snap['utc_day']}）used {snap['used_total']}/{snap['cap_per_day']}，"
          f"本脚本要花 1 次（purpose={EXPLORATION}）；标的 {symbol}，outputsize {outputsize}")
    if dry:
        print("\n--dry-run：未发出任何网络调用。")
        return 0

    _load_key()
    from qlab.events.datafetch.quotes_api import fetch_daily
    bars = fetch_daily(symbol, outputsize=outputsize, guard=guard, purpose=EXPLORATION)
    av = pd.DataFrame([{"date": b.date, "close": b.close} for b in bars])
    print(f"\nAV TIME_SERIES_DAILY({symbol}, {outputsize})  {av['date'].iloc[0]} → "
          f"{av['date'].iloc[-1]}  ({len(av)} 行)")

    m = av.merge(pq, on="date", suffixes=("_av", "_pq"))
    if m.empty:
        print("重叠为空 —— 无法判定（parquet 末日早于 AV compact 窗口起点）。")
        return 1
    m["ratio"] = m["close_av"] / m["close_pq"]
    m["step_bps"] = m["ratio"].pct_change() * 1e4
    print(f"重叠区间  {m['date'].iloc[0]} → {m['date'].iloc[-1]}  ({len(m)} 个交易日)")

    r0, r1 = m["ratio"].iloc[0], m["ratio"].iloc[-1]
    spread_bps = (m["ratio"].max() / m["ratio"].min() - 1) * 1e4
    steps = m[m["step_bps"].abs() > STEP_BPS]
    print(f"\n比值 av/pq   首 {r0:.6f}   末 {r1:.6f}   全窗极差 {spread_bps:.1f} bps")
    print(f"台阶（日变动 > {STEP_BPS:.0f} bps）：{len(steps)} 处")
    for _, row in steps.iterrows():
        print(f"    {row['date']}  ratio {row['ratio']:.6f}  跳 {row['step_bps']:+.1f} bps")

    # 定性：as-traded 的签名是「比值在除息日台阶式变化」；回溯复权是「比值全程恒定」
    as_traded = len(steps) > 0 or spread_bps > 20.0
    print("\n结论：AV TIME_SERIES_DAILY 相对仓内 qfq 总回报序列 —— "
          + ("**as-traded（未复权）**：比值出现台阶/显著漂移，"
             "说明 AV 未把分红或拆股回溯进历史价格。" if as_traded else
             "**与 qfq 一致（已复权）**：比值全程恒定、无台阶。"))
    print("量级：重叠窗内两条序列的累计收益差 = "
          f"{(m['close_av'].iloc[-1] / m['close_av'].iloc[0] - m['close_pq'].iloc[-1] / m['close_pq'].iloc[0]) * 100:+.3f} 个百分点"
          "（as-traded 时约等于窗内股息率，朝严方向：本轨会少记这部分收益）")
    print("\n本脚本只出结论，不改任何轮内代码；动不动由吏部定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

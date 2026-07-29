"""EVO-8 方向(b) — GEM 首轮回测 CLI：抓免费日线 → 建 verdict → 落 report.json + RESULTS.md。

用法（仓库根/qlab 下）：
  python -m qlab.swing.run_gem --out qlab/reports/gem --data-dir qlab/data/gem \
      --prereg-commit <GEM_EVAL_PREREGISTRATION.md 的冻结 commit>

数据：Yahoo v8 chart 复权日线（split+dividend adjusted），复用
`qlab.events.datafetch.prices.fetch_yahoo`。抓不到的符号如实记为缺口，不造数。
"""
from __future__ import annotations

import argparse
import json
import time
import datetime as dt
from pathlib import Path

import pandas as pd

from ..events.datafetch import prices as price_mod
from ..events.metrics import TRADING_DAYS_PER_YEAR
from .gem_signals import GemParams, load_daily
from .gem_evaluate import build_gem_report

_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _yahoo_one(symbol, start, end, session, host):
    """单次 Yahoo v8 复权日线抓取（host 可选 query1/query2）；复用 prices._normalize 归一。"""
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp(end).timestamp()) + 86400
    url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    r = session.get(url, timeout=30, headers={"User-Agent": _BROWSER_UA})
    if r.status_code != 200:
        return None, f"http {r.status_code}"
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    df = pd.DataFrame({"date": pd.to_datetime(ts, unit="s").normalize(),
                       "open": q["open"], "high": q["high"], "low": q["low"],
                       "close": q["close"], "volume": q["volume"]})
    if adj is not None:
        factor = pd.Series(adj).astype(float) / df["close"].astype(float)
        for c in ("open", "high", "low", "close"):
            df[c] = df[c].astype(float) * factor
    return price_mod._normalize(df), f"yahoo:{host} adjclose-rescaled"


def fetch_symbols(symbols, data_dir, start="1990-01-01", end=None, retries=4,
                  throttle_s=3.0):
    """用 Yahoo 复权日线抓取并落 parquet；节流 + host 轮换 + 429 退避。返回 (frames, provenance)。"""
    end = end or dt.date.today().isoformat()
    data_dir = Path(data_dir)
    frames, prov = {}, {}
    import requests
    sess = requests.Session()
    for si, s in enumerate(symbols):
        # 已有 parquet 则复用（避免重复打 API / 支持 rate-limit 冷却下复跑）
        cached = data_dir / f"{s.upper()}_1d.parquet"
        if cached.exists():
            try:
                fr = load_daily(cached)
                if len(fr):
                    frames[s] = fr
                    raw = pd.read_parquet(cached)
                    prov[s] = {"source": "cached_parquet(yahoo_v8_adjclose)",
                               "note": "reused existing parquet", "n_bars": int(len(raw)),
                               "first": str(pd.to_datetime(raw["date"]).min().date()),
                               "last": str(pd.to_datetime(raw["date"]).max().date())}
                    continue
            except Exception:  # noqa: BLE001
                pass
        if si > 0:
            time.sleep(throttle_s)                    # 节流：避免突发 429
        df, note = None, "not attempted"
        for attempt in range(retries):
            for host in ("query1", "query2"):
                try:
                    df, note = _yahoo_one(s, start, end, sess, host)
                except Exception as e:  # noqa: BLE001
                    df, note = None, f"yahoo:{host} error: {e}"
                if df is not None and len(df):
                    break
            if df is not None and len(df):
                break
            time.sleep(2.0 * (attempt + 1))           # 429/瞬时错误退避
        if df is not None and len(df):
            price_mod.write_parquet(df, data_dir, s)
            frames[s] = load_daily(data_dir / f"{s.upper()}_1d.parquet")
            prov[s] = {"source": "yahoo_v8_adjclose", "note": note,
                       "n_bars": int(len(df)),
                       "first": str(pd.to_datetime(df["date"]).min().date()),
                       "last": str(pd.to_datetime(df["date"]).max().date())}
        else:
            prov[s] = {"source": "yahoo_v8_adjclose", "note": note, "n_bars": 0, "blocked": True}
    return frames, prov


def write_results_md(report, path):
    v = report["overall_verdict"]
    g1 = report.get("primary_gate1_x2", {})
    lines = [
        f"# EVO-8 (b) GEM 首轮回测结果 — verdict: **{v}**", "",
        f"- candidate: {report['candidate']}",
        f"- preregistration_commit: `{report['preregistration_commit']}`",
        f"- 数据: {report.get('data_provenance','')}",
        f"- 决策成本口径: ×2；主格 lookback={report.get('primary_lookback_months','?')}m；"
        f"family={report.get('lookback_family_months','?')}",
        "",
        "## 主格 ×2 官方 50/20 门",
        f"- CAGR = **{g1.get('cagr',0):.2%}**（hurdle 50%）",
        f"- MDD  = **{g1.get('mdd',0):.2%}**（cap 20%）",
        f"- gate1 passed: {g1.get('passed', False)}",
        f"- 影子分层: {report.get('primary_shadow_tier_x2','n/a')}",
        "",
        "## 危机子窗（×2，MDD 破位即直接负向）",
    ]
    for name, w in report.get("crisis_windows_x2", {}).items():
        if isinstance(w, dict) and not w.get("insufficient"):
            lines.append(f"- {name}: 窗口收益 {w['window_return']:+.2%}, MDD {w['mdd']:.2%}, "
                         f"{'破20%' if w['mdd_breach_20pct'] else 'OK'}")
    lines += ["", "## 判读", f"{report['verdict_reason']}", "",
              "## 诚实试验计数",
              f"- within-candidate N = {report['honest_trial_count']['within_candidate_N']} "
              f"(family {report['honest_trial_count']['family_months']})",
              f"- {report['honest_trial_count']['note']}", "",
              "## 基准（仅上下文）"]
    for k, val in report.get("benchmarks", {}).items():
        if isinstance(val, dict) and "cagr" in val:
            lines.append(f"- {k}: CAGR {val['cagr']:.2%}, MDD {val['mdd']:.2%}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="qlab/reports/gem")
    ap.add_argument("--data-dir", default="data/gem")
    ap.add_argument("--prereg-commit", default="PENDING")
    ap.add_argument("--start", default="1990-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args(argv)

    params = GemParams()
    frames, prov = fetch_symbols(params.all_symbols, args.data_dir, start=args.start, end=args.end)
    provenance = ("Yahoo v8 chart 复权日线（split+dividend adj）; " +
                  "; ".join(f"{s}:{p.get('first','NA')}→{p.get('last','NA')}({p.get('n_bars',0)}bars)"
                            for s, p in prov.items()))
    report = build_gem_report(frames, P=TRADING_DAYS_PER_YEAR, n_boot=args.n_boot,
                              prereg_commit=args.prereg_commit, data_provenance=provenance)
    report["data_fetch_provenance"] = prov
    report["run_date"] = dt.date.today().isoformat()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_results_md(report, out / "GEM_RESULTS.md")
    print(f"verdict: {report['overall_verdict']}")
    print(f"primary x2: CAGR={report.get('primary_gate1_x2',{}).get('cagr',0):.2%} "
          f"MDD={report.get('primary_gate1_x2',{}).get('mdd',0):.2%} "
          f"shadow={report.get('primary_shadow_tier_x2')}")
    print(f"report → {out/'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

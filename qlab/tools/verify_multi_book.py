"""(b) 多 book 执行器 —— 等价性验证第 ① 段的**可复跑**留痕脚本。

    python3 qlab/tools/verify_multi_book.py          （仓根执行；不打网络、不花配额、不改台账）

做两件事，各自把结论打出来供口径备注引用：

1. **决策集逐位比对**：把第 1 轮 `round_20260810.json` 的 7 条决策原样喂给 (b)，逐条比
   symbol / target_weight / seed / prompt_variant / 三时间戳。`evidence_available_utc` 是
   **重新派生**出来的（不是抄回原值），故这一比对真的走了一遍派生逻辑。
2. **配额形态**：把第 1 轮 pv1/pv2 两份权重展开成冻结的足额 10 格跑一轮，数取行情的调用次数——
   这是 (b) 相对「10 次 run_round」的全部意义所在（≈8 次/轮 vs 80 次/轮）。

第 1 轮 `status=pending_entry_bar`、**没有 book 可比**，故 book 等价性不在此处，
留给与 (a) 并行的那一轮做对照（工部尚书 2026-08-27 派单第 2 条）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]        # moomoo-bot/      → research 包
_QLAB_ROOT = _REPO_ROOT / "qlab"                        # moomoo-bot/qlab/ → qlab 包
for _p in (str(_QLAB_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from qlab.events.datafetch.quotes_api import DailyBar          # noqa: E402
from qlab.llm_paper.multi_book import (cell_id, compare_decision_sets,  # noqa: E402
                                       expand_variants, run_round_multi)

ROUND1 = _REPO_ROOT / "qlab" / "reports" / "llm_paper" / "round_20260810.json"
PROBE = {"model": "verify-multi-book", "output": '{"probe":"fixed"}'}

# 第 1 轮口径备注 §2 留档的 pv2_riskaware 目标权重（pv1 从 round JSON 读）
PV2_WEIGHTS = {"EMR": 0.07, "MET": 0.06, "GD": 0.06, "CAT": 0.05,
               "COP": 0.05, "MRK": 0.05, "GILD": 0.03}


def _stub(monkey_target, days, price=100.0, calls=None):
    def fake(symbols, **kw):
        syms = sorted(symbols)
        if calls is not None:
            calls.append(syms)
        return ({s: [DailyBar(symbol=s, date=d, close=price, open=price * 0.99) for d in days]
                 for s in syms}, {})
    monkey_target.get_daily_closes = fake


def main() -> int:
    import qlab.llm_paper.multi_book as MB
    rec = json.loads(ROUND1.read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp())
    import os
    os.environ["QLAB_AV_QUOTA_LEDGER"] = str(tmp / "q.jsonl")
    os.environ["QLAB_LLM_DETERMINISM_BASELINE"] = str(tmp / "b.json")

    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-03-20", "2026-08-07")][-100:]
    _stub(MB, days)

    dts = pd.Timestamp(rec["round_decision_ts"])
    pv1 = [{"symbol": d["symbol"], "target_weight": d["target_weight"],
            "confidence": d["confidence"], "thesis": d["thesis"], "model": d["model"],
            "evidence_records": [{"source_time_utc": d["evidence_acceptance_utc"],
                                  "ref_id": d["evidence_refs"][0]}]}
           for d in rec["decisions"]]

    # ---- ① 决策集逐位比对 ----
    r = run_round_multi(cells=[{"seed": 11, "prompt_variant": "pv1_baseline", "proposals": pv1}],
                        decision_ts=dts, probe=PROBE, out_dir=str(tmp / "eq"),
                        register_trials=False)
    blk = r["cells"][cell_id(11, "pv1_baseline")]
    cmp = compare_decision_sets(blk["decisions"], rec["decisions"])
    print("① 决策集 vs 第 1 轮 f2f7729（round_20260810.json）")
    print(f"   比对字段    {', '.join(cmp['fields_compared'])}")
    print(f"   条数        {cmp['n_left']} vs {cmp['n_right']}")
    print(f"   逐位相同    {cmp['identical']}   差异 {cmp['diffs']}")
    print(f"   gross       {blk['portfolio_check']['gross']} "
          f"(第 1 轮 {rec['portfolio_check']['gross']})")
    print(f"   book 状态   {blk['book']['status']}（第 1 轮 {rec['book']['status']}，"
          "如期无 book ⇒ book 等价性留给并行对照轮）")

    # ---- ② 配额形态：足额 10 格一轮 ----
    calls = []
    _stub(MB, days, calls=calls)
    pv2 = [dict(p, target_weight=PV2_WEIGHTS[p["symbol"]]) for p in pv1]
    full = run_round_multi(cells=expand_variants({"pv1_baseline": pv1, "pv2_riskaware": pv2}),
                           decision_ts=dts, probe=PROBE, out_dir=str(tmp / "full"),
                           register_trials=False)
    print("\n② 冻结足额 10 格一轮")
    print(f"   取行情调用  {len(calls)} 次，符号 {full['symbols_fetched']}")
    print(f"   本轮配额    {full['quote_calls_this_round']} 次"
          f"（朴素按格各取一遍需 {full['quote_calls_if_naive_per_cell']} 次）")
    print(f"   格子        评估 {full['n_cells_evaluated']}/{full['n_cells_frozen_grid']}，"
          f"缺格 {full['cells_missing']}")
    grosses = {cid: c["portfolio_check"]["gross"] for cid, c in full["cells"].items()}
    print(f"   每格 gross  pv1={grosses[cell_id(11, 'pv1_baseline')]} / "
          f"pv2={grosses[cell_id(11, 'pv2_riskaware')]}（按格判，不跨格加总）")
    print(f"   verdict     {full['verdict']}（中途读数只作监控）")

    ok = cmp["identical"] and len(calls) == 1 and full["n_cells_evaluated"] == 10
    print(f"\n结论：{'PASS' if ok else 'FAIL'} —— 等价性第 ① 段"
          f"{'通过' if cmp['identical'] else '未通过'}；"
          "第 ② 段（book 等价性）待与 (a) 并行的那一轮对照。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

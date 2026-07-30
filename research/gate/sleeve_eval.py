"""
sleeve_eval.py —— sleeve（分散/回撤控制腿）组合级判据（户部 CERTIFY 用，都察院可复核）

工部/吏部口径：standalone 判负 ≠ sleeve 判负。一条候选够不够占组合位，看组合层：
  ① 净正（standalone CAGR > 0，扣成本后）；
  ② 与库存低/负相关（分散信号）；
  ③ 组合级边际贡献为正——按最优权重加入后，组合 MDD 下降、MAR/Sharpe 上升
     （加 A 改善组合 Sharpe 的充要近似：Sharpe_A > Sharpe_book × corr(A,book)）。
口径与冻结门一致：CAGR/MDD/Sharpe/MAR 全走 research.gate.metrics（每期净收益、ppy=252）。

复核用法（repo 根，需 qlab 库存曲线 csv 已落库）：
  python3 -m research.gate.sleeve_eval
"""
from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from .metrics import PERIODS_PER_YEAR, cagr, mar, max_drawdown, sharpe


def _stats(r: pd.Series) -> Dict[str, float]:
    return {"CAGR": round(cagr(r) * 100, 2), "MDD": round(max_drawdown(r) * 100, 2),
            "Sharpe": round(sharpe(r), 3), "MAR": round(mar(r), 3)}


def sharpe_improves(cand: pd.Series, book: pd.Series) -> bool:
    """加 cand 改善 book 的 Sharpe ⟺ Sharpe_cand > Sharpe_book × corr(cand,book)。"""
    return sharpe(cand) > sharpe(book) * float(cand.corr(book))


def blend_frontier(cand: pd.Series, book: pd.Series,
                   weights: Sequence[float] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)) -> List[dict]:
    """book+cand 按权重 w 的日频再平衡混合，返回各 w 的组合指标（找 MAR 最优 w）。"""
    out = []
    for w in weights:
        rp = (1.0 - w) * book + w * cand
        st = _stats(rp); st["w"] = w
        out.append(st)
    return out


def sleeve_verdict(cand: pd.Series, inventory: Dict[str, pd.Series]) -> dict:
    """
    组合级判据结论。inventory = {名字: 每期净收益}（候选要分散的库存腿）。
    返回：standalone、各库存相关性、Sharpe-improvement、对每个 book 的最优混合、三条判据是否满足。
    """
    aligned = pd.concat({**{"_cand": cand}, **inventory}, axis=1).dropna()
    c = aligned["_cand"]
    corrs = {k: round(float(c.corr(aligned[k])), 4) for k in inventory}
    improves = {k: sharpe_improves(c, aligned[k]) for k in inventory}
    books = {**{k: aligned[k] for k in inventory},
             "EW_all": aligned[list(inventory)].mean(axis=1)}
    frontiers = {}
    for bn, rb in books.items():
        fr = blend_frontier(c, rb)
        best = max(fr, key=lambda s: s["MAR"])
        frontiers[bn] = {"standalone": _stats(rb), "frontier": fr, "mar_opt": best}
    net_positive = cagr(c) > 0
    low_corr = all(v <= 0.10 for v in corrs.values())
    # 组合级贡献为正：至少一个 book 的最优混合 MDD 下降且 MAR 上升
    contributes = any(f["mar_opt"]["MDD"] < f["standalone"]["MDD"] and
                      f["mar_opt"]["MAR"] > f["standalone"]["MAR"] for f in frontiers.values())
    return {"standalone": _stats(c), "corr": corrs, "sharpe_improves": improves,
            "frontiers": frontiers,
            "criteria": {"net_positive": net_positive, "low_corr": low_corr,
                         "positive_contribution": contributes},
            "sleeve_pass": net_positive and low_corr and contributes}


def _load(path: str) -> pd.Series:
    return pd.read_csv(path, parse_dates=["date"]).set_index("date")["ret"].astype(float)


def main():
    D = "qlab/qlab/reports/inventory_curves/"
    cand = _load(D + "carry_rates_A_equity.csv")
    inv = {"GEM": _load(D + "gem_equity.csv"),
           "MF": _load(D + "multifactor_equity.csv"),
           "RM": _load(D + "residmom_equity.csv")}
    v = sleeve_verdict(cand, inv)
    print("A standalone:", v["standalone"])
    print("corr:", v["corr"], " sharpe_improves:", v["sharpe_improves"])
    for bn, f in v["frontiers"].items():
        print(f"  book={bn}: standalone {f['standalone']}  MAR-opt {f['mar_opt']}")
    print("criteria:", v["criteria"], " => sleeve_pass:", v["sleeve_pass"])


if __name__ == "__main__":
    main()

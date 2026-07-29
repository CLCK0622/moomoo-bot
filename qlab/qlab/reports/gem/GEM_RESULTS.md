# EVO-8 (b) GEM 首轮回测结果 — verdict: **基线未达标**

- candidate: GEM Global Equity Momentum (Antonacci 2014): dual momentum SPY/VEU rotate, AGG risk-off, T-bill(BIL) absolute-momentum hurdle
- preregistration_commit: `67b9ce74`
- 数据: Yahoo v8 chart 复权日线（split+dividend adj）; SPY:1993-01-29→2026-07-27(8429bars); VEU:2007-03-08→2026-07-27(4876bars); AGG:2003-09-29→2026-07-27(5741bars); BIL:2007-05-30→2026-07-27(4820bars)
- 决策成本口径: ×2；主格 lookback=12m；family=[6, 12]

## 主格 ×2 官方 50/20 门
- CAGR = **7.98%**（hurdle 50%）
- MDD  = **32.05%**（cap 20%）
- gate1 passed: False
- 影子分层: none(MDD≥20%)

## 危机子窗（×2，MDD 破位即直接负向）
- 2008_gfc: 窗口收益 +5.57%, MDD 11.05%, OK
- 2020_covid: 窗口收益 -25.12%, MDD 32.05%, 破20%
- 2022_ratehike_bear: 窗口收益 -16.75%, MDD 21.29%, 破20%
- 2025-2026_recent: 窗口收益 +27.90%, MDD 19.77%, OK

## 判读
未过官方 50/20，且未达影子兜底（官方门：CAGR=7.98% vs 50%，MDD=32.05% vs 20%; 危机窗破 MDD>20%：2020_covid, 2022_ratehike_bear; OOS 未显著高于 hurdle）；影子分层=none(MDD≥20%)（CAGR=7.98%, MDD=32.05%）。NEGATIVE。

## 诚实试验计数
- within-candidate N = 2 (family [6, 12])
- GEM 是单一文献配置（Antonacci 2014），无因子挖掘；within-candidate N=2 (6m,12m)。跨轮累计真 N（DSR）由户部组合级判据在拼装所有候选时累加，本候选只如实吐自己的 N，不预先折算。

## 基准（仅上下文）
- SPY_buy_and_hold: CAGR 10.63%, MDD 55.42%
- equal_weight_held_assets: CAGR 6.73%, MDD 40.90%
- 50_50_SPY_AGG_proxy_for_60_40: CAGR 7.29%, MDD 28.72%

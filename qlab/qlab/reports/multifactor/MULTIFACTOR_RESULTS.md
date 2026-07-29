# EVO-8 (b) 多因子长偏 首轮回测 — verdict: **REJECTED_dsr (NEGATIVE)**

判定经 `research/gate.certify()`（合树 27cecc4 版，N/V/成本/容量已修）。preregistration_commit `0642967`。

## 结论：双重负向
1. **`REJECTED_dsr`**：DSR = **0.000** < 0.95。策略 per-period Sharpe 0.042 远低于 **N=27 累计试验**下的
   期望最大 Sharpe 0.339——8% 的年化在这套多重检验负担下**与运气不可区分**，判为疑似伪 alpha。
2. **metrics 独立 FAIL**：CAGR **8.03%** / MDD **22.60%** / Sharpe_ann 0.67——离官方 50/20 远，
   也不进影子兜底带（需 CAGR≥15% 且 MDD≤20%，两条都不满足）。

## 门是怎么走到 DSR 的（都被你上轮加固的门逐道验过）
- 成本早筛：**过**（x1 净 Sharpe 0.046 > 0，有真实毛边——与残差动量的 ≈0 不同）。
- 容量：**过**，参与率 0.10%（单名部署 $455k vs 持仓名 20 分位 ADV $455M，AUM=$10M）——**ADV 如实填，门真跑了**。
- **DSR：拒**——这正是关键。用**真累计 N=27**（不是单轮 8）做 haircut，才把它拦下。

## 共享账本 = 真累计（你要修的那处）
`research/gate/state/trial_ledger.json` 单一账本，`cumulative_n()=27`：
GEM 2 + 残差反转 EVO-162 6 + 残差动量 4 + 人肉筛除死因 7 + 本轮 8 因子。账本 gitignore →
**全量登记明细 + 每因子试验 Sharpe（DSR 的 V）已写进 report.json** 供都察院复核。每因子 x2 Sharpe：
mom12_1 0.82 / mom6_1 0.90 / prox52w 0.52 / trend200 0.92 / rev21 0.49 / vol60 0.68 / vol120 0.72 / ltrev 0.88。

## 有价值的观察（不改结论）
- 200d 趋势闸**确实控住了急跌**：COVID 窗 MDD 14.1%、2022 窗 13.0%（GEM 同期 COVID 32%）——右侧闸有效。
- 但满仓多头十分位的 raw 收益太低（8% CAGR），且全样本 MDD 22.6% 仍破 20%；分散多因子没造出足够 alpha。
- 与 GEM / 残差动量同族命运：**大盘、免费价量因子、成本后，达不到 50/20，也不构成稳健 sleeve**。

## 纪律
- 不自建门；判据全在 `certify()`。预注册 `0642967` 先于结果。冻结后仅动**非策略**代码（ADV 读盘修复 +
  单因子 Sharpe 采集 + 序列化），**合成/因子/组合/趋势闸一行未改**，策略净收益与冻结一致。
- N 取共享 `cumulative_n()`、`n_trials_cumulative=None`、ADV 如实、cost x2、kernels=1——四条硬前提全落实。

## 复跑
```
python -m qlab.swing.run_multifactor --prereg-commit 0642967   # py312 venv; build→export→certify
```

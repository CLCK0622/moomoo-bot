# EVO-8 (b) 多因子长偏 — verdict: **REJECTED_dsr (NEGATIVE)**（canonical ledger 版）

rebase 到 `f024cdf`；判定经 `research/gate.certify()`；**共享 `project_ledger()` = `research/gate/state/trial_ledger.jsonl`（已入库）**。

## 结论：双重负向（与上轮一致，口径已对齐工部裁定）
- **`REJECTED_dsr`**：DSR=0.000 @ **cumulative_N=22**（canonical 14 + 本轮 8 因子）。per-period Sharpe 0.042 << 选择偏差下期望最大 → 疑似伪 alpha。
- metrics 独立 FAIL：**CAGR 8.03% / MDD 22.60%**，离 50/20 远、兜底带进不去（MDD>20%）。
- 门逐道过：成本**过**、容量**过**、DSR **拒**。200d 趋势闸把 COVID 窗 MDD 压到 14.1%、2022 到 13.0%。

## 工部四条接线，逐条（本轮修正点）
1. **`cost_per_turnover=0.001` 显式（10bps/单向）**，`cost_model` 用**注册表标签 `moomoo_retail_x1`**
   → 门 `resolve=max(floor 5bps, 自报 0.001)=10bps`，对齐 EVO-12 CostModel 与前三候选。上轮的自由文本
   标签在 f024cdf 新门下被 `REJECTED_prereg`（未登记成本标签），已改正。
2. **共享 `project_ledger()`**（非按候选分文件），登记后**把 `trial_ledger.jsonl` 提交入库**——N 真跨轮累计。
   本轮不再自行补登历史（canonical 已含权威 14：9 人肉证伪 + GEM 1 + 残差动量 4），只由 factor_export 登记 multifactor 8。
3. **adv/required_notional 如实**：单名 $455k vs 20 分位 ADV $455M，参与率 0.10%，容量门真跑、pass。
4. `ledger=` 传入、`n_trials_cumulative=None`、`kernels=1`、预注册先于结果。

## N 溯源（账本入库，report.json 亦全量记录）
canonical `trial_ledger.jsonl`：`pre_gate_manual_history` 9 + `gem_firstround` 1 + `residmom_evo162_r1` 4 +
`multifactor-longbias-438b578` 8 = **22**。每因子 x2 Sharpe（DSR 的 V）见 report.json。

## GEM 补跑 certify()（同一 canonical 账本）
`REJECTED_dsr`、metrics FAIL CAGR 7.98%/MDD 32.05%——与 EVO-149 原判一致；GEM 已作 `gem_firstround` 在册，未重登。

三候选：GEM 负、残差动量负、多因子长偏负。复跑：`python -m qlab.swing.run_multifactor --prereg-commit 438b578`。

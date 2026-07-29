# EVO-8 方向(b) — 多因子长偏 (multi-factor long-bias): FROZEN 预注册（待运行）

**状态**：预注册冻结、待运行。该腿依赖 Qlib 生成器基座（都水 (a) 的 `factor_export`）+
`research/gate` 已合到同一棵树（工部已派都水合分支 + 修 N-seam）。运行前不读结果。

## 0. 不自建门 / 判据零重实现（工部 2026-07-29 接线）

- 唯一新代码：因子合成 + 组合构建 adapter（`swing/multifactor_signals.py`）+ 接线（`run_multifactor.py`）。
- 因子来自都水 `qlab/tools/qlib_gen/factor_export` 出的 **tidy parquet**(`datetime,instrument,factor,value`)
  + manifest；`kernels=1`（macOS spawn 多进程死锁，都水踩过——硬规矩#2）。
- 判定 100% 交 `research/gate.certify()`；官方/影子/DSR/成本/容量门全在门里。

## 1. 数据 / 因子源

- Qlib Alpha158（价量派生技术因子）经 `dump_bin` 喂进二进制，CPU 即可；免费日线 + OpenD。
- 冻结宇宙 = 与 residual 同一大盘 `RESIDUAL_UNIVERSE_RESOLVED.txt`（跑中不换）。
- **N 只从 `TrialLedger.cumulative_n()` 取**（硬规矩#1）：Alpha158 全量因子（含被丢弃的）必须
  经 `TrialLedger.register_run(n_trials_total=全量, ...)` 登记，DSR 用累计真 N；绝不接受 manifest
  每轮 `n_expressions_attempted` 或默认 0（工部查出的 miner 侧 DSR 架空坑，都水已收口）。
- **调 `certify()` 时传 `ledger=`、`n_trials_cumulative` 留 `None`**（工部 2026-07-29 自律规矩）：
  门里 `gate.py:95-97` 现仍是「自报 N 优先于台账」的 fail-open——自报一个 `< cumulative_n()` 的小 N
  能把已驳回的伪 alpha 洗成 certified。故消费端硬自律：**绝不自算 N 传进门，一律让门去台账取**；
  代码加断言 `assert cand.n_trials_cumulative is None`。在户部把 `certify()` 取 N 处改成 fail-closed
  （自报 N < 台账 → HonestyError / 取 max）之前，**本腿即便出正向也先回工部、不自行当 DECISION_POINT 上报**。
- **分层判定一律走 `certify()` 的开区间 `≥25% 且 MDD≤20% → DECISION_POINT`**，不用本地 `_shadow_tier`
  的闭区间 `[25%,35%)`（会漏掉 35–50% 本该触发验收线的区间——工部查出的第二处接缝）。

## 2. 候选：多因子长偏 + 趋势

- **因子族（预注册冻结，literature-standard，no post-hoc grid）**：价值代理、质量代理、
  12-1 动量、低波（皆 Alpha158 技术口径）。等权合成 z-score 复合分。
- **长偏组合**：横截面按复合分排序，**做多 top 分位**（long-biased，可含小空腿或纯多），
  月度再平衡；**趋势 overlay**：组合级 200d SMA 之上满仓、之下降敞口（右侧/absolute-momentum 闸）。
- **杠杆 ≤2x 预注册**，不可事后加；long-biased（非市场中性），故承担市场 beta——用趋势闸控回撤。
- 执行 open(T+1)、成本 x1/x2（决策 ×2），与其它 sleeve 同一 CostModel。

## 3. family / OOS / 门槛（全在 certify()）

- family = 复合分权重 {等权 / 波动率倒数加权} × top 分位 {decile/quintile}，主格预先固定 = (等权, decile)。
- NO-FIT：因子定义与合成规则为文献惯例、冻结在前 ⇒ 全样本净收益即 OOS，单发 OOS 预算。
- 官方 50/20 / 影子 25/20 / 兜底 15/20；危机窗喂满日期索引（tail_incomplete 不背书）；
  DSR N=累计真 N；成本早筛；容量/ADV。

## 4. verdict 三值（同 residual momentum 口径）

- REPORT_5020→即刻上报；DECISION_POINT→带真实数字停等 Kevin；FAIL→先看 `shadow_floor_pass`
  （长偏组合更可能落影子/兜底带，作组合层贡献候选留档，别二值丢弃）。回报 → 工部尚书。

## 5. 运行前置（本腿卡点，透明记录）

1. 都水把 gate(PR#1 `c33332b0`) 与生成器(`evo-162`) 合到一棵树 + 修 `run_trial` 的 N-seam（工部已派）。
2. `build_qlib_data.py` 建 Alpha158 二进制；`factor_export` 出 tidy parquet + manifest。
3. 之上跑本 adapter → certify()。三步就位后本腿即可出 verdict（预注册已冻结于此）。

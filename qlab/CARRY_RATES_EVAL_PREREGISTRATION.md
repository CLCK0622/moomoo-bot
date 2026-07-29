# EVO-8 方向(b) 候选 A — 利率 CARRY（曲线陡度调久期）: FROZEN 预注册

**冻结于任何回测结果被读取之前**（工程 smoke 仅验证 adapter 可跑，未读 verdict）。基线
rebase 到 `agent/evo-162-residual-reversal @ 3250562`。**信号从零写，不接 VIX carry（EVO-25 已证伪）那套。**
本文件在结果 commit 之前提交，git 时序供户部/都察院核。

> ⚠️ **verdict 前置未满足**：户部门侧 DSR 单位契约修正未落地前，本候选**不出正式 verdict**（工部 2026-07-29）。
> 本轮只到「预注册冻结 + adapter 起草 + 相关性机制就位」；正式判定等 ①DSR 修正合入 + ②都水 FRED/ETF 数据落库。

## 0. 不自建门 / 判据零重实现

- 新代码：`swing/carry_rates_signals.py`（信号，从零）+ `run_carry_rates.py`（接线）。判定 100% 交
  `research/gate.certify()`（3250562 版，带 N/V/成本/容量修复）。复用 `carry_evaluate.py`/`run_carry.py`
  的评估-verdict **外壳结构** + `CARRY_EVAL_PREREGISTRATION.md` 作模板；**信号不复用**。

## 1. 数据来源（都水落地，本候选消费）

| 层 | 来源 | 角色 |
|--|--|--|
| 曲线信号 | **FRED `DGS2` / `DGS10`**（免费、无付费依赖），provenance 按仓内 `*_provenance.json` 惯例 | 陡度 = `DGS10 − DGS2` |
| 可交易久期 | **SHY(1-3y) / IEF(7-10y) / TLT(20y+)** 复权日线 parquet，入库可离线复跑 | 执行 |

- 数据窗须覆盖 **2022 利率冲击**（A 的杀手验证）；ETF 自 2002 起、FRED 更早 ⇒ 窗 ~2002→2026，含 2008/2020/2022。
- 反前视、日历对齐；缺窗直接标注不静默截断。FRED 从本 agent 运行时不可达（超时）——由都水落库；本 adapter
  消费 `date,slope`（或 `date,DGS2,DGS10`）序列，源可换不改机制。

## 2. 信号（no-fit，从零写）

- 陡度 `slope(t) = DGS10(t) − DGS2(t)`（%）。**曲线陡 ⇒ 期限溢价 + roll-down 大 ⇒ 上久期；平/倒挂 ⇒ 无 roll-down ⇒ 退短久期。**
- 规则（预注册冻结的曲线-regime 阈值，**非在收益上拟合**；round number，no-fit）：
  - `slope ≥ 0.50%`（明显陡）→ **TLT**（最长久期，收 carry+rolldown）
  - `0.00% ≤ slope < 0.50%`（温和正）→ **IEF**（中久期）
  - `slope < 0.00%`（平/倒挂）→ **SHY**（最短久期，避久期风险）
- 单资产 100% 权重、**long/flat 调久期，绝不做空债**（红线：无裸空）。
- 月度再平衡（月末 close 决定、次 open 执行、open-to-open）。杠杆 ≤2x 预注册（本候选 **1.0×，无杠杆**）。

## 3. 杀手验证（冻进口径，跑后不得改）— **A = 2022 利率冲击专测**

2022 曲线从年初 ~0.7% 陡度一路 bear-flatten 至年中倒挂、全曲线收益率飙升；buy&hold TLT 当年 ~−31%。
**A 的验收核心：随陡度转平/倒挂退到 SHY，把 2022 久期回撤压住。** 2022 子窗 MDD 与买入持有 TLT/IEF 对比
进 verdict，不得事后调阈值美化。另附 2008/2020 危机窗（gate 自带）。

## 4. 验收口径（**sleeve，不是 standalone**）—— 工部强调，别漏

A 是**分散 / 回撤控制 sleeve**：判据不是 standalone 50/20，而是 **净正 + 与库存低相关 + 组合级贡献**。
`standalone 判负 ≠ sleeve 判负`。故除净值口径外，**务必一并产出 A 与现有库存（GEM / 残差动量 / 多因子
三条曲线）的日频收益相关性矩阵** —— 否则组合层无法判。低/负相关（债 vs 股）即分散价值。

## 5. 接线（工部四条 + 门）

- rebase `3250562`；`project_ledger()` 读入库 `trial_ledger.jsonl`（N=29），`register_run` 后连 `.jsonl` 提交。
- `cost_per_turnover=0.001`（10bps/单向，×1/×2），`cost_model="moomoo_retail_x1"`（注册标签）。
- `adv_notional`/`required_notional` 如实（国债 ETF 流动性充裕，但不留 0 跳过容量门）。
- `ledger=` 传入、`n_trials_cumulative=None`、`kernels=1`。
- **DSR trial Sharpe 按每期口径**（已修 `*sqrt(252)`，commit `ac687cc`）——本候选沿用。
- family（haircut）：陡度阈值族 {(0.5,0.0) 主 / (0.75,0.25) / (1.0,0.0)} 稳健性，主格预先固定 (0.5,0.0)；诚实 N 全登记。
- 红线：SIMULATE-only、仅免费数据、本地算力、无裸空、≤2x 预注册、零真金。

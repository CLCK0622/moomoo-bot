# EVO-8 方向(b) 候选 A — 利率 CARRY（曲线陡度调久期）: FROZEN 预注册（重冻 v2）

**冻结于任何回测结果被读取之前。** 基线 rebase 到 `agent/evo-162-residual-reversal @ 818dded`（DSR 单位
修正含反方向洞已闭合、门齐、canonical 台账 N=29、`data/rate_carry` 三腿已归拢）。**信号从零写，不接 VIX carry（EVO-25 已证伪）那套。**
本文件在结果 commit 之前提交，git 时序供户部/都察院核。

> 硬前置**已闭合**（工部 2026-07-29/30，`818dded`）：DSR 产出侧去年化 + 门侧归一/软旗 + 反方向 ppy 洞全落地；
> 数据齐（`data/fred_yields.parquet` + `data/rate_carry/{BIL,IEF,TLT}` 含息复权，共同窗 2007-05-30→2026-07-17）。
> 故本候选**本轮出正式 verdict**。

## 0a. universe 替换：SHY → BIL（工部 2026-07-29 裁定，冻结前决定，供都察院复核）

原吏部 spec 短久期腿是 **SHY(1-3y)**，因 Stooq/Yahoo/OpenD 三源出口封锁**取不到真实 bar**（已实测、
provenance 如实记 missing）。改用 **BIL(1-3M)** 承担短久期/避险腿（GEM 现金腿同款）。三点交代：
① 替换**在预注册冻结之前**决定（重冻时尚无任何 verdict，合规，非跑后调参）；② 机制/杀手验证(2022)/红线**一律不变**；
③ **⚠️ 有利方向必须点明**：BIL(久期≈0) 在 2022 比 SHY(久期≈1.9) **更抗跌**（BIL≈+1.5% vs SHY≈−3.5%），
故 **A 的 2022 结果是「相对 SHY 原规格的上界」**，报告显式声明，不让替换悄悄美化候选。吏部/首辅若坚持必须 SHY，
预注册此刻方冻、现在提尚可。

**`rate_carry_provenance.json` 的 `substitution_bias_2022` 原文（都察院可直接核）：**
> IMPORTANT — the substitution is FAVORABLE to A's 2022 killer test and must be declared as such in the report:
> BIL (1-3mo, duration ~0) was materially more resilient in 2022 than SHY (1-3y, duration ~1.9): BIL ~+1.5% vs
> SHY ~-3.5% over the year. Because A's `slope<0 -> short leg` rule sends the book to the short leg exactly in the
> 2022 inversion, using BIL instead of SHY makes the 2022 result BETTER than the original SHY spec would have.
> So A's 2022 outcome must be read as an UPPER BOUND relative to the SHY spec, not a like-for-like — the report
> must state this so the substitution does not silently flatter the candidate.

## 0. 不自建门 / 判据零重实现

- 新代码：`swing/carry_rates_signals.py`（信号，从零）+ `run_carry_rates.py`（接线）。判定 100% 交
  `research/gate.certify()`（`818dded` 版，带 N/V/成本/容量/ppy 修复）。复用 `carry_evaluate`/`run_carry`
  的评估外壳 + `CARRY_EVAL_PREREGISTRATION.md` 作模板；**信号不复用**。

## 1. 数据来源

| 层 | 来源 | 角色 |
|--|--|--|
| 曲线信号 | **`data/fred_yields.parquet`**（都水已入库；DGS3MO/2/5/10/30，6145 行 0 NaN，2002→2026） | 陡度 = `DGS10 − DGS2` |
| 可交易久期 | **BIL(1-3M) / IEF(7-10y) / TLT(20y+)** 含息复权日线 parquet（IEF/TLT 自 evo-23-etf-momentum，BIL 自 gem） | 执行 |

- **共同窗 2007-05-30 → 2026-07-17**，2008 GFC / 2020 COVID / **2022 利率冲击全段在内**（A 杀手验证料齐）。
- 反前视、日历对齐；BIL/IEF/TLT 均总回报口径（含息复权，工部已验 CAGR 合理）。

## 2. 信号（no-fit，从零写）

- 陡度 `slope(t) = DGS10(t) − DGS2(t)`（%）。**曲线陡 ⇒ 期限溢价 + roll-down 大 ⇒ 上久期；平/倒挂 ⇒ 退短久期。**
- 规则（预注册冻结的曲线-regime 阈值，**非在收益上拟合**；round number，no-fit）：
  - `slope ≥ 0.50%`（明显陡）→ **TLT**（最长久期，收 carry+rolldown）
  - `0.00% ≤ slope < 0.50%`（温和正）→ **IEF**（中久期）
  - `slope < 0.00%`（平/倒挂）→ **BIL**（最短久期≈0，避久期风险）
- 单资产 100% 权重、**long/flat 调久期，绝不做空债**（红线：无裸空）。
- 月度再平衡（月末 close 决定、次 open 执行、open-to-open）。杠杆 ≤2x 预注册（本候选 **1.0×，无杠杆**）。

## 3. 杀手验证（冻进口径，跑后不得改）— **A = 2022 利率冲击专测**

2022 曲线从年初 ~0.7% 陡度一路 bear-flatten 至年中倒挂、全曲线收益率飙升；buy&hold TLT 当年 ~−31%。
**A 的验收核心：随陡度转平/倒挂退到 BIL，把 2022 久期回撤压住。** 2022 子窗 MDD 与买入持有 TLT/IEF 对比
进 verdict，不得事后调阈值美化。**且须声明 BIL vs SHY 的有利偏差（§0a③）——2022 结果为上界。** 另附 2008/2020 危机窗。

## 4. 验收口径（**sleeve，不是 standalone**）—— 工部强调，别漏

A 是**分散 / 回撤控制 sleeve**：判据不是 standalone 50/20，而是 **净正 + 与库存低相关 + 组合级贡献**。
`standalone 判负 ≠ sleeve 判负`。故除净值口径外，**务必一并产出 A 与现有库存（GEM / 残差动量 / 多因子
三条曲线）的日频收益相关性** —— 否则组合层无法判。低/负相关（债 vs 股）即分散价值。

## 5. 接线（工部四条 + 门）

- rebase `818dded`；`project_ledger()` 读入库 `trial_ledger.jsonl`（N=29），`register_run` 后连 `.jsonl` 提交。
- `cost_per_turnover=0.001`（10bps/单向，×1/×2），`cost_model="moomoo_retail_x1"`（注册标签）。
- `adv_notional`/`required_notional` 如实（国债 ETF 流动性充裕，但不留 0 跳过容量门）。
- `ledger=` 传入、`n_trials_cumulative=None`、`kernels=1`。
- **DSR trial Sharpe 按每期口径**（`r.mean()/r.std()`，无 `*sqrt(252)`）**且不声明 `trials_periods_per_year`**
  ——工部新加的反方向软旗会对「已是每期却又报 ppy」打「过松」旗，故绝不传 ppy。
- 红线：SIMULATE-only、仅免费数据、本地算力、无裸空、≤2x 预注册、零真金。

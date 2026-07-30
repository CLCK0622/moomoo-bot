# EVO-8 方向(b) 候选 C — 宏观-信用 regime: FROZEN 预注册 v3（数据到位，本轮出 verdict）

**冻结于任何回测结果被读取之前。** 基线 `agent/evo-162-residual-reversal @ 1960091`（并发锁 filelock + C vintage 数据已入库 +
canonical OOS + C 预注册在树、105 单测绿、台账 N=35）。信号从零写。本文件在结果 commit
之前提交，git 时序供户部/都察院核。

> **数据已到位**：都水经 FRED API（realtime_start/end）落库 `credit_baa10ym_vintages`（as_of 2019-12→2026-07，8 快照）
> + `credit_baa10ym_latest`（1990→2026），走的是真 point-in-time 接口（非工部实测的 `fredgraph vintage_date` 假 URL）。
> vintage-integrity 自检见 §3a：实测修订 ≤1bp ⇒ 序列基本不修订、latest 可用（证据化）。**本轮出正式 verdict。**

## 0. 判据零重实现 / 不自建门

- 新代码：`swing/credit_regime_signals.py`（信号，从零）+ `run_credit_regime.py`（接线）。判定 100% 交
  `research/gate.certify()`（`1960091` 版）。复用评估外壳，不重实现指标。

## 1. 数据来源（都水落地，本候选消费）

| 层 | 来源 | 角色 |
|--|--|--|
| 信用 regime 信号 | **FRED 信用利差 vintage（ALFRED point-in-time）**：HY OAS `BAMLH0A0HYM2` 或 `BAA10YM`（Baa−10y） | regime 判定 |
| 可交易 | SPY（风险腿）+ IEF/AGG（避险腿）+ BIL（现金）——已在仓（`data/daily_full`/`data/gem`/`data/rate_carry`） | 执行 |

- **vintage 取数硬约束**（工部 2026-07-30）：**禁用** `fredgraph.csv?...&vintage_date=`（静默返回 latest，md5 已证）；
  须走 FRED API `realtime_start/end`（免费 key）或 ALFRED 下载表单，provenance 写清端点+参数。**都水落库后须自检
  「vintage 与 latest 可区分」**——若完全相同：先排查端点是否生效；确认生效后若仍相同，则该序列不修订，**明确记为
  结论并附证据**（有证据的「无修订」≠ 无证据的假定，前者过都察院、后者不过）。
- 反前视、日历对齐；数据窗须覆盖 2008 GFC（信用利差最有信息量的一段）。

## 2. 信号（no-fit，从零写）

- **机制**：信用利差是权益压力的领先/同步指标。利差收窄/低位（risk-on regime）→ 持风险腿(SPY)；
  利差走阔/高位（risk-off/stress regime）→ 退避险腿(IEF/AGG) 或现金(BIL)。long/flat、无裸空、≤2x。
- **regime 判定（v3 re-freeze，固定 round-number 水平阈，no-fit）**：BAA10Y 利差 `s`（%）——
  `s < 1.8` = calm → **SPY**（风险腿）；`1.8 ≤ s < 2.6` = neutral → **IEF**（中久期避险）；`s ≥ 2.6` = stress → **BIL**（现金/短端）。
  阈值为 round number（BAA10Y 历史正常区间 ~1.5–2.5、压力期 >3，取 1.8/2.6 覆盖 calm/neutral/stress，**未在收益上拟合**）。
  改固定阈（原 §2 的 trailing 分位）是为复用已过门的 carry ETF-配置引擎（`carry_rates_curve`），信号源不变、无 verdict 前重冻合规。
- **family（冻结、决定 DSR 的 V，跑后不得增删）= 阈值对 {(1.8,2.6) 主, (1.5,2.5), (2.0,3.0)}**。
- 月度再平衡、close(T) 决定、次 open 执行、open-to-open。
- **发布滞后约定（冻结，工部 2026-07-30；对 C 可能比修订更致命）**：用 **T 日利差决定 → T+1 开盘执行**，
  **绝不同日决策同日成交**。即便序列不被修订，T 日 OAS 未必在 T 日收盘前可得，故信号相对执行至少滞后一日；
  报告须如实标注该滞后已生效（信号日 vs 首个可交易日）。这条口径冻结、跑后不得绕。

## 3. 杀手验证（冻进口径，跑后不得绕）— **C = FRED vintage 防前视**

两条前视都要防，冻进口径、跑后不得绕：

**(a) 修订偷看**：用 point-in-time vintage 跑、与 latest(revised) 对照；若 edge 只在 revised 下成立、vintage 下消失
⇒ 前视伪 alpha、判负。**口径校正（工部 2026-07-30）**：本候选选的 `BAMLH0A0HYM2`/`BAA10YM` 是**市场价格算出**的
（非 GDP/非农那类调查估计、也非 GZ 那类模型量），**市场价序列基本不回溯修订**，故 vintage 差异很可能≈0。**但不得因此跳过**——
须取一小段 vintage 样本，用**证据证明该序列修订可忽略（或不可忽略）**；证据化的「无修订」过门，假定的不过。
> **证据（营缮 2026-07-30 实测，都水 8 个 vintage 快照 as_of 2019-12→2026-07）**：latest − point-in-time 的修订
> **mean −0.0000、std 0.0007、max|rev| 0.0100（1bp）、median 0.0000**（438 obs 中仅 1 条 >1bp），约 0.00% of ~2.28 水平。
> ⇒ **BAA10YM 实测基本不回溯修订**（市场价格类，符合工部 §3a 假设）。故 (a) 修订偷看**证据化排除**，
> 本候选据此用 latest 序列跑 ETF 期（2007→）的策略；真正的绑定前视是 (b) 发布滞后，见下。

**(b) 发布滞后偷看（对 C 更致命）**：即便不修订，T 日 OAS 未必 T 日收盘前可得——已按 §2 冻结 **T→T+1** 滞后约定，
报告须实证信号日与首个可交易日的间隔。

另附 2008/2020/2022 危机窗。**vintage-integrity 自检**（vintage≠latest 可区分）是 run 的前置门，见 §1。

## 4. 契约（工部 2026-07-30 四条 + 门；C 尤其 ①）

1. **OOS 单发用 `project_oos_budget(path=_REPO_ROOT/DEFAULT_OOS_BUDGET_PATH)`**（canonical 落盘），consume 后
   **连 `oos_budget.json` 一起提交**（B 那次踩的坑：机制在、状态没入库=空转，已修）。
2. `register_run(candidate_id="macro_credit_regime", supersedes=<重冻旧 run_id>)`。
3. **family 预注册冻结**（regime 阈值那组，决定 DSR 的 V，跑后不得增删）；缺失即 `REJECTED_prereg`。
4. 每条台账带**每期** `trial_sharpes`（`r.mean()/r.std()`，无 `*√252`、不声明 `trials_periods_per_year`）。
- `cost_per_turnover=0.001`、`cost_model="moomoo_retail_x1"`、ADV 如实、`ledger=`、`n_trials_cumulative=None`、`kernels=1`。
- 红线：SIMULATE-only、仅免费数据、本地算力、无裸空、≤2x、零真金。

## 5. 验收口径

C 是**regime 择时/风险配置腿**：净正 + 组合级贡献 + 与库存相关性一并出（同 A sleeve 判据）。standalone 若不过
50/20/影子，按 sleeve 组件级判；若 vintage 检验下 edge 消失则直接负向。非 Kevin 上报事件，除非清官方 50/20。

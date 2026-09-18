# EVO-8 方向(b) 候选 C — 宏观-信用 regime: FROZEN 预注册（起草，run 待 vintage 数据）

**冻结于任何回测结果被读取之前。** 基线 `agent/evo-162-residual-reversal @ cd90eb3`（门齐、台账 N=35、
共享 OOS 落盘已修入库）。信号从零写。本文件在结果 commit 之前提交，git 时序供户部/都察院核。

> **run 前置未满足**：C 的信号是 FRED 信用利差/宏观序列，杀手验证=vintage 防前视（见 §3），**必须用
> point-in-time(ALFRED) 数据**。FRED 从本 agent 运行时超时不可达，且 vintage/ALFRED 是专门数据源——**待都水落库**。
> 本轮只到「预注册冻结 + 契约锁定 + 数据依赖点清」；正式 verdict 等 vintage 数据到位。

## 0. 判据零重实现 / 不自建门

- 新代码：`swing/credit_regime_signals.py`（信号，从零）+ `run_credit_regime.py`（接线）。判定 100% 交
  `research/gate.certify()`（`cd90eb3` 版）。复用评估外壳，不重实现指标。

## 1. 数据来源（都水落地，本候选消费）

| 层 | 来源 | 角色 |
|--|--|--|
| 信用 regime 信号 | **FRED 信用利差 vintage（ALFRED point-in-time）**：HY OAS `BAMLH0A0HYM2` 或 `BAA10YM`（Baa−10y） | regime 判定 |
| 可交易 | SPY（风险腿）+ IEF/AGG（避险腿）+ BIL（现金）——已在仓（`data/daily_full`/`data/gem`/`data/rate_carry`） | 执行 |

- **杀手验证要 vintage**：信用/宏观序列会被回溯修订，用最新版跑历史=偷看未来。故信号取值须用**发布当时的 vintage**
  （ALFRED），不许用 latest。都水落库时须带 vintage 时间轴 + provenance。
- 反前视、日历对齐；数据窗须覆盖 2008 GFC（信用利差最有信息量的一段）。

## 2. 信号（no-fit，从零写）

- **机制**：信用利差是权益压力的领先/同步指标。利差收窄/低位（risk-on regime）→ 持风险腿(SPY)；
  利差走阔/高位（risk-off/stress regime）→ 退避险腿(IEF/AGG) 或现金(BIL)。long/flat、无裸空、≤2x。
- **regime 判定**（预注册冻结阈值，round number，no-fit）：spread 相对其**trailing 中位数/分位**的偏离
  （如 > 上四分位 = stress → 避险；< 下四分位 = calm → 风险腿；中间 = 中性持 IEF）。具体阈值在 §-family 冻结。
- 月度再平衡、close(T) 决定、次 open 执行、open-to-open。

## 3. 杀手验证（冻进口径，跑后不得绕）— **C = FRED vintage 防前视**

**用 point-in-time(ALFRED) vintage 数据跑，与用 latest(revised) 数据跑对照。** 若 edge 只在 revised 下成立、
vintage 下消失 ⇒ 前视伪 alpha，判负。这是 C 的决定性检验：信用/宏观序列的修订幅度大，vintage 差异对
regime 择时是实打实的。冻结口径不许用 latest 数据美化。另附 2008/2020/2022 危机窗。

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

# EVO-8 方向(b) 候选 B — FOMC 季节性（pre-announcement drift）: FROZEN 预注册

**冻结于任何回测结果被读取之前。** 基线 `agent/evo-162-residual-reversal @ cd90eb3`（三口门齐、100 单测绿、
canonical 台账 N=32、`fomc_meetings.csv` 已在）。信号复用 EVO-130 S5 的 FOMC 原语（`s5_fomc_trades`/
`event_edge`/`load_fomc_calendar`），**不重写、不重抓数据**；B 是 EVO-8 独立预注册（2019+ 衰减口径 + 新门契约）。
本文件在结果 commit 之前提交，git 时序供户部/都察院核。

## 0. 判据零重实现 / 不自建门

- 新代码仅 `swing/run_fomc_seasonality.py`（接线）。判定 100% 交 `research/gate.certify()`（`cd90eb3` 版）。
- 复用 `swing/strategies.py`（`s5_fomc_trades`/`load_fomc_calendar`）+ `swing/evaluate.py`（`event_edge`）。

## 1. 数据

| 层 | 来源 | 角色 |
|--|--|--|
| 事件 | `data/fomc_meetings.csv`（164 场，2006→，含 scheduled 标记） | FOMC 决议日 |
| 价格/执行 | SPY 复权日线（`data/daily_full/SPY_1d.parquet`） | 标的 |

- 仅取 **scheduled** 会议（日程数月前公开 ⇒ close(T−offset) 入场非前视）。2020-03 计划外会议排除。
- 反前视：close(T−offset) 决定、执行至 close(T)；日频粒度无法隔离 2pm ET 那一刻，如实标注。

## 2. 信号（no-fit，文献惯例）

- **FOMC pre-announcement drift**（Lucca–Moench 2015）：会议决议日前若干交易日 SPY 系统性上行。
- 规则：每场 scheduled FOMC，close(T−offset) 买入 SPY、close(T) 平仓。**long/flat only、无裸空、无杠杆**。
- **主 offset = 1**（决议前 1 日入场）。**family（决定 DSR 的 V，冻结、跑后不得增删）= offsets {1, 2, 3}**。
- 成本：EVO-12 CostModel 10bps/side × cost_mult；决策口径 ×2。

## 3. 杀手验证（冻进口径，跑后不得改）— **B = 2019+ OOS 衰减复核**

FOMC 漂移在文献里被记录为 **~2015 后显著衰减**（Kurov et al. 2021）。B 的**决定口径**：
**`DECAY_SPLIT = 2019-01-01`；主 offset 在 2019+ 子样本上、扣 ×2 成本后 event edge 仍显著为正（p(mean≤0)<0.05）
且过 haircut ⇒ 未衰减/可用；否则 = 已衰减/不可用（负向）。** 默认假设 = 已衰减（负向），2019+ 不显著即坐实。
另报 full / pre-2019 / post-2019 三段 event edge 对照，跑后不得挑段。

## 4. 验收口径（sparse event sleeve）

B 是稀疏事件腿（每年 ~8 场），**满仓 50/20 由构造即不可能**（大部分时间现金）——full-capital `certify()` 的
CAGR 必然 FAIL，**如实记录、非 B 的判据**。B 的 PASS/FAIL 由 **2019+ 事件 edge 显著性 + haircut** 决定（§3）。
若最终为「未衰减」，仍须声明这是**低容量事件腿、非收益引擎、非 50/20 或影子门事件**（同 A：不构成 Kevin 上报事件）。

## 5. 接线（工部 2026-07-30 四条新契约 + 门）

1. **OOS 单发用 `project_oos_budget()`**（全项目共享落盘，`DEFAULT_OOS_BUDGET_PATH`）——不用进程内 `OOSBudget()`，
   否则每 run 一张新票、单发形同虚设；消费后 `.json` 入库。
2. **`register_run` 带 `candidate_id="fomc_seasonality"`**；重冻（换 prereg commit）用 `supersedes=<旧 run_id>`，
   否则 `RefreezeError`（防同候选重复计数）。
3. **预注册已冻 `family`**（§2 的 offsets{1,2,3}）——门要求 `family` 键，缺失/事后增删 → `REJECTED_prereg`。
4. **每条台账登记带每期口径 `trial_sharpes`**（`r.mean()/r.std()`，无 `*√252`、不声明 `trials_periods_per_year`）——
   pooled-V 地板靠这个做实（工部 e71201ec §3）。
- `cost_per_turnover=0.001`、`cost_model="moomoo_retail_x1"`、ADV 如实、`ledger=` 传入、`n_trials_cumulative=None`、`kernels=1`。
- 红线：SIMULATE-only、仅免费数据、本地算力、无裸空、≤2x、零真金。

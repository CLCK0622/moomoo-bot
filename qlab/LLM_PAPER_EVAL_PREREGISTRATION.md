# EVO-8 新范式 — LLM-agent 定性投资（前向纸面）: FROZEN 预注册

**冻结于任何纸面决策产生之前。** 基线 `agent/evo-162-residual-reversal @ 1748065`（门齐、ledger N=47、
`export` 透传修复在树上）+ 户部 `research/gate/llm_paradigm.py`（`5380a2e`）。
**本文件 push 后立即抓 GitHub 服务端 `PushEvent.created_at` 落 `freeze_anchor.json` 并提交；
此后本分支永不 rebase、永不 force-push。**

> **定位（钉死，不得漂移）**：**薄 alpha 探索、非收益腿，证据按年计。** 传统量化批次已证同宇宙内
> 50/20 不可达（全批最好 MAR 0.367 vs 官方门需 2.50）；本轨换的是**范式**（LLM 读公开信息做定性决策），
> 不是换一条更好的因子。**不许拿任何外部账号（含 @theaiportfolios）的战绩作背书或抄其持仓。**

## 0. 时序证明（本轨全部证据效力的来源 —— 工部 2026-08-08）

git 的 `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` **提交者可任意设定**，不能自证「预注册先于决策」。故用两条腿：
1. **绝对时间下界**：冻结 commit push 后立刻取 `gh api repos/CLCK0622/moomoo-bot/events` 中该 sha 的
   `PushEvent.created_at`（**服务端观测、提交者设不了**），写入仓内 `qlab/freeze_anchor.json`（`/events` 只留近期，
   不落库则证据期一到即查不到）。
2. **相对顺序**：**每一笔纸面决策的 commit 必须是本冻结 commit 的 DAG 后代**——无法给不存在的 commit 造子节点。
   因此本分支**永不 rebase / 永不 force-push**（改写历史 = DAG 证明当场作废）。
   两条合起来：冻结在服务端时间 T 已存在 + 决策皆其后代 ⇒ 决策必在冻结之后，**不依赖相信我们自己的时钟**。

## 1. 模式纪律（铁律，与三工具同源：生成器 ≠ 验收）

- **`forward_paper` 是唯一可作验收证据的模式**：决策在本预注册冻结之后实时做出
  （`llm_paradigm.admissibility_check(mode='forward_paper', eval_window_start, prereg_frozen_at=<锚点服务端时间>)`）。
- **`historical_replay` 仅作假设生成器、永不作验收证据**：LLM 预训练语料可能已含评测期，历史回放天然作弊。
- **模型训练 cutoff 不可核 ⇒ 一律按污染处理**（`INADMISSIBLE_CONTAMINATED`），不采信厂商自报。
- **中途读数只作监控、不出 verdict**；「3 个月漂亮数字当业绩」是明令违规形态。

## 2. 冻结的运行参数（跑后不得改）

| 项 | 冻结值 |
|--|--|
| **universe** | S&P 100 成分中、已在仓 `data/daily_full` 的大盘股（291 标的交集），**跑中不换**；不碰小微盘/OTC |
| **决策频率** | **每周一次**（美东周一开盘前决策 → 当日开盘执行）；不做日内、不做事件驱动加仓 |
| **单标的上限** | **10%** NAV |
| **总持仓上限** | **100%** NAV（**无杠杆、≤1x**） |
| **禁做空** | **long/flat only，绝不做空、无裸空** |
| **现金上限** | **100%**（允许全现金；现金即 BIL 口径） |
| **成本** | 10bps/side × cost_mult，**决策口径 ×2**（`cost_per_turnover=0.001`，`cost_model="moomoo_retail_x1"`） |
| **价格/执行** | **OpenD SIMULATE**；零真金 |

## 3. 决策链路（冻结之后方可开工）

公开信息 → 结构化论点 + 置信度 + 目标仓位 → **多 seed** → **决策与理由落盘不可改**。
每条决策记录**必须带三个时间**并满足 `evidence_max_ts ≤ decision_ts ≤ effective_from`
（由 `llm_paradigm.validate_decision_log` 逐条核，违规不静默）：
- **`evidence_max_ts` 取信息源自身的时间**——EDGAR `filing_date`/`acceptance_datetime`、RSS `pubDate`——
  **不是我们的时钟**（用自己的时钟＝自证，核不了）。
- `decision_ts` = LLM 产出决策的时刻；`effective_from` = 收益起算（次开盘）。

## 4. 验收口径

- 判定 100% 走 `certify()` + `llm_paradigm`；**中途不出 verdict**。
- **多 seed**：报 `seed_distribution` 的**下四分位**而非最好 seed（防挑 seed）；
- **风格/beta 归因**：报净额 + beta 归因（只报绝对收益 = 用 beta 冒充 alpha）；
- **台账**：`每个 seed × 每个 prompt 变体全额计一次试验`进共享台账（现 **N=47**），
  经 `export` 登记时**带 `candidate_id="llm_paper"`**（`1748065` 已把透传补上）；
- 证据按**年**计：`(t/IR)²` —— IR 0.5 需 ~16 年（t=2）/ ~36 年（t=3，多重检验后）。**故本轨不承诺短期结论。**

## 5. 红线

SIMULATE-only、零真金、仅免费/合规公开数据、无裸空、≤1x、本地算力；
**不许照抄任何外部账号持仓**（跟单风险 + 污染归因，只测我们自己的决策链路）；
不许拿外部账号战绩作背书。回流只在「起跑完成 / 异常违规 / Kevin 否决」三种情况。

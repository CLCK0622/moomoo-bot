# EVO-8 前向纸面轨 · 执行器变更与等价性口径备注（(a) 单 book → (b) 多 book）

**本文件是口径备注，不动冻结文本、不动决策逻辑、不动冻结参数。** 记录三件必须留痕的事：
(b) 多 book 执行器做了什么、等价性验证到哪一步、以及**哪一轮起换的执行器**。

裁定链：工部尚书 2026-08-10 提出分叉 → 吏部同日裁定走 (b)（带前置条件与兜底）→ 工部尚书 2026-08-10
修完前置 1 的两处 bug（`4da9493`）→ 轮次因宿主离线窗断了 17 天 → 工部尚书 2026-08-27 派单恢复实现。

---

## 1. 当前状态：**(b) 尚未接管，承载路径仍是 (a)**

| | 状态 |
|--|--|
| 承载路径（写入 §4 判据的那条） | **(a) `run_round.run_round()`** |
| (b) `multi_book.run_round_multi()` | 已在树上、有单测、可跑；**未接管** |
| 等价性第 ① 段（决策集 vs 第 1 轮） | ✅ **通过**（下方 §3） |
| 等价性第 ② 段（book 等价性） | ⏳ **2026-08-31 那轮跑并行对照**（下方 §4，工具已就位并彩排通过） |
| 换执行器的轮次 | **尚未发生**；**不在对照当轮切**，对照通过后的下一轮再切，届时回填本表 |

**08-31 那轮的默认路径仍是 (a)，(b) 不阻塞、不推迟轮次。** 证据连续性高于本次重构。
并行对照时 **(b) 必须传 `register_trials=False`**——对照不是承载路径，二次登记只会拿到幂等旧记录、
把 `n_evaluated` 记歪（`ledger_bridge` 会把这种情形标成 `ledger_reused_existing_record`，不静默）。

**违规处理口径（08-31 当轮不动）**：一格组合约束不过 ⇒ **整轮 fail-closed、零落盘**（现状）。
工部尚书 2026-08-27 裁定这一轮维持现状，理由是时序而非认同代价——对照轮要的是两条路径逐位可比，
此时引入新的违规处理语义等于同时换两个变量、比对结果不可归因。**规则须在首次违规发生之前预注册**，
已升吏部裁定（工部尚书推荐：违规格本轮不调仓、如实留档、仍计入 `n_evaluated`；理由是不 censor 分布——
被剔掉的系统性地是最激进的格，而 §4 下四分位正算在这个分布上）。裁定落地前本文件不改这条。

## 2. (b) 做了什么

`qlab/qlab/llm_paper/multi_book.py` —— **一次取符号并集、内部按格分账**，每格自带 book 与净值点：

* 配额形态实测（足额 10 格一轮，第 1 轮的 7 标的 + SPY）：**8 次/轮**；
  朴素「10 次 `run_round()` 各取一遍行情」需 **80 次/轮** ≫ 25/天硬预算。这正是吏部指出的正确形态。
* **组合约束按格逐一判**：每格是一个独立组合，不跨格加总（10 个 49% 是 10 个合规组合，不是 490% 超限）；
  任一格不过 ⇒ **整轮 fail-closed、零落盘**，与 (a) 同一条纪律（不产出半截证据）。
* 决策 / 约束 / 建仓 / 盯市 / 探针全部**复用既有实现**（`build_decision` / `check_portfolio` /
  `build_book` / `mark_to_market` / `determinism`），本模块只做编排，不复制其中任何一段逻辑——
  这是「两条路径不会静默分叉」的结构性保证，比对齐两份代码更可靠。
* 探针**按轮不按格**（它测的是模型有没有被换权重，与格子无关），仍无跳过开关。
* 缺格如实记进 `cells_missing`，不静默。

`qlab/qlab/llm_paper/nav_series.py` —— **每格净值序列**，从各轮**不可改的 round JSON** 机械拼出，
不维护第二份可变的累计文件。(a)/(b) 两种落盘格式都认，`coverage()` 直接给出
`executor_switch_rounds`（哪一轮起换的执行器，一眼可见）。未建仓的轮次没有净值点，序列里就不该有那一天——
**不补「持平」点**。`cumulative_returns()` 是监控读数，**不出 verdict**；判定一律走 `certify()` + `llm_paradigm`。

## 3. 等价性验证第 ① 段：决策集与第 1 轮 `f2f7729` 逐位相同 ✅

第 1 轮 `status=pending_entry_bar`、**没有 book 可比**（工部尚书 2026-08-10 §3 已更正吏部的前置 2），
故第 ① 段比的是**决策集**。可复跑：`python3 qlab/tools/verify_multi_book.py`（不打网络、不花配额、不改台账），
同一比对另有单测 `tests/test_multi_book.py::test_decision_set_matches_round1_bit_for_bit`。

```
① 决策集 vs 第 1 轮 f2f7729（round_20260810.json）
   比对字段    symbol, target_weight, seed, prompt_variant, evidence_available_utc, decision_ts, intended_start
   条数        7 vs 7
   逐位相同    True   差异 []
   gross       0.49 (第 1 轮 0.49)
   book 状态   pending_entry_bar（第 1 轮 pending_entry_bar，如期无 book）

② 冻结足额 10 格一轮
   取行情调用  1 次，符号 ['CAT', 'COP', 'EMR', 'GD', 'GILD', 'MET', 'MRK', 'SPY']
   本轮配额    8 次（朴素按格各取一遍需 80 次）
   格子        评估 10/10，缺格 []
   每格 gross  pv1=0.49 / pv2=0.37（按格判，不跨格加总）
   verdict     None
```

**这一比对不是抄答案**：喂给 (b) 的是 `evidence_acceptance_utc`（信息源自身受理时刻），
`evidence_available_utc` 由 `derive_available_utc` **重新派生**后才比对，故真的过了一遍派生逻辑。
（单条重建与原多条等价：`derive_available_utc` 对信息源时间单调不减 ⇒ max(可得) = 可得(max(受理))。）

比对器本身也上了单测（改一个字段必须报出来），不做橡皮图章。

## 4. 等价性验证第 ② 段：book 等价性 —— 并行对照工具已就位（2026-08-31 那轮跑）

`qlab/qlab/llm_paper/parallel_control.py` 的 `run_parallel_control()`：**一次取行情，同一份 bars
同时喂 (a) 与 (b)**，逐位比 `status/shares/entries/gross_notional/cash/entry_cost/nav_start`、
x2 影子腿的 `cash/entry_cost/gross_notional`、以及 `nav_point` 的 `as_of/nav/nav_x2_cost/nav_start`，
外加决策集比对。

**为什么必须共用同一份快照**——不是配额（本轨走 `purpose=MARKING`，可用全额 25，8+8 装得下），
是**对照有效性**：两次取数之间任何一根 bar 变动，都会让比对因与执行器无关的原因而失败或通过。
(a)/(b) 都是 `(decisions, bars)` 的确定性函数，同一快照喂两边是结构上唯一正确的做法。

三条安全性质（工具里各有单测钉住）：

1. **承载路径先跑、先落盘**；(b) 整段包在 try/except 里——对照侧无论怎么炸都**不许波及**已落盘的 (a)。
   用一次对照失败换掉一个补不回来的日历轮次是荒唐的。
2. **对照侧不登记台账**（`register_trials=False`）。
3. **两侧落盘目录必须不同**：两条路径都写 `round_<stamp>.json`，同目录会让对照记录**静默覆盖**承载记录。
   工具拒绝同目录启动；对照默认写进 `<out_dir>/control_multi_book/`（子目录不被 `round_*.json` 的
   非递归 glob 扫到，故不污染 `nav_series` 与台账并集）。

比对结果落 `CONTROL_<stamp>.json`（**刻意不叫 `round_*`**，同上）；不一致时另落
`ALERT_control_mismatch_<stamp>.json`——只以返回值形态存在的结论等于没留痕。
工具**不自动切换**承载路径，只给 `may_take_over` 这一个事实判断。

**彩排已通过**（`python3 qlab/tools/verify_multi_book.py` 第 ③ 节，人造建仓 bar 让 book 真的建起来）：

```
③ 并行对照彩排（人造建仓 bar；形态验证，非第 ② 段证据）
   取行情调用  1 次 —— (a)/(b) 共用同一份快照（对照侧自身 0 次）
   比对的格    seed11×pv1_baseline，book 状态 filled
   book 字段   status, shares, entries, gross_notional, cash, entry_cost, nav_start
   逐位相同    book=True / 决策集=True   差异 []
   可否接管    True（对照通过也不在当轮切，见裁定）
```

**这是彩排、不是第 ② 段的证据本身**——真证据必须是 08-31 用真实行情跑出来的那份 `CONTROL_<stamp>.json`。
彩排的价值只在于：08-31 那轮不是这条代码路径的首跑。

### 08-31 轮次怎么跑

```python
from qlab.llm_paper.parallel_control import run_parallel_control
rep = run_parallel_control(
    proposals=<(a) 的提案，每条带 seed/prompt_variant>,   # 承载路径，正常落盘 + 登记台账
    cells=<(b) 的格子，必须覆盖 (a) 所在的那一格>,          # 对照，自动 register_trials=False
    decision_ts=<决策时点>, probe=<金标准探针结果>)
# rep["bearing_payload"] 就是这一轮的真记录；rep["may_take_over"] 决定下一轮能不能切
```

`rep["may_take_over"] is False` ⇒ **停下回报工部尚书，不得切换**；本轮 (a) 的记录仍然有效。

**行情注入对 (a) 是零行为改动**：`run_round(bars=…)` 与自己取数的输出逐位相同、注入侧零调用零配额，
已由 `tests/test_run_round.py::test_injected_bars_produce_the_same_round_as_fetching` 钉住。
注入的快照必须覆盖本轮全部标的 ∪ 基准——缺一只即 fail-closed，因为部分快照会被记成
`missing_entry_open`，与「当天真的没开盘价」在记录里不可区分。

`tests/test_multi_book.py::test_single_cell_book_identical_to_path_a` 是这条对照的打桩版本，
两者并存：一个证明形态、一个是实盘证据。

## 5. 顺带修掉的一个会让**第 2 轮直接归零**的坑（(a)/(b) 同受影响）

实现时用真台账副本模拟第 2 轮，发现原先内联在 `run_round()` 里的台账登记**第 2 轮起必崩**：

```
RefreezeError: 候选 candidate_id='llm_paper' 已以 run_id=['llm_paper-2026-08-10'] 登记，
现又以新 run_id=llm_paper-2026-08-31 重登…须显式 supersedes=<旧 run_id> 覆盖计一次
```

抛错点最坏：**配额已花、决策已产生、round JSON 尚未落盘** ⇒ 该轮证据当场归零，
后果等同于「空一轮永久少一轮」。这与本次改点要抢救的第三轮是同一件事，故一并修掉。

`TrialLedger` 的重冻护栏（工部 2026-07-30）本身是对的——同 `candidate_id` 换 `run_id` 静默追加会把
同一批试验计两遍、N 虚高 ⇒ DSR haircut 变松。错的是调用方：本轨是**一个候选、一张冻结的 10 格网格、
按周前向推进**，每周不是新增 10 个试验，是同样那 10 格多走了一周。故正确形态是
**一个候选恒定一条台账记录**，`supersedes` 覆盖计一次：

* `n_trials_total` **恒为冻结的 10**，一格不少登（DSR 的 V 不变、不放松）；
* `n_evaluated` 取**跨轮已评估格子的并集**，从各轮 round JSON 机械读出——(a) 长期是 1 格，
  (b) 接管后是 10 格，「哪一轮起变成 10」在台账与 round JSON 两侧都对得上；
* `cumulative_n()` 里本候选恒定贡献 10，不会每周 +10。

实现在 `qlab/qlab/llm_paper/ledger_bridge.py`，**(a)/(b) 共用同一份**（这也顺手消掉了两条路径各写一份
登记逻辑的分叉风险）。回归单测把「原内联写法在第 2 轮必崩」这个失败形态本身钉死，防止有人改回去。

## 6. 取行情也收进了共用桥接

`qlab/qlab/llm_paper/quote_bridge.py` —— `fetch_round_quotes()` 现由 **(a) / (b) / 并行对照三处共用**。
理由与 `ledger_bridge` 相同：这段是 fail-closed 护栏（`require_full_batch` 整批不出、
`QUOTA_DIVERGENCE` 独立 ALERT、缺价即拒），**多一份拷贝就多一处会静默分叉的地方**。
并行对照引入第三个调用点时，与其抄第三遍，不如三处共用一份。护栏逻辑一字未改。

副产品：打桩点从三处收敛成一处，测试因此不再耦合「取数调用写在哪个模块里」。

## 7. 红线与边界（本次改动全程未动）

冻结文本 / 决策逻辑 / 冻结参数一律未动；`temperature` 未动、未重冻；`n_trials_total` 按冻结 10 格足额登记；
第 1 轮已落盘记录未回改。SIMULATE-only、零真金、仅免费数据、禁做空、单标的 ≤10%、总仓 ≤100%、≤1x。
**未 rebase、未 force-push**（集成分支 `agent/evo-162-residual-reversal` 快进推送）。

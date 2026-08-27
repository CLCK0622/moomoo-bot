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
| 等价性第 ② 段（book 等价性） | ⏳ 判据已改（§8.1）——原判据「轮内 `book.status == filled`」实测**结构性不可达**，改由**派生结算层**逐位比每格 book / NAV；工具与彩排已就位（§4） |
| 换执行器的轮次 | **尚未发生**；接管归批次 1（硬期限 **2026-10-31**，§8.3），届时回填本表 |
| 决策捕获 | 08-31 起每轮对照传**足额 10 格**，把未被承载路径执行的变体决策留档（§8.2）——决策易腐，事后补即造数 |

**08-31 那轮的默认路径仍是 (a)，(b) 不阻塞、不推迟轮次。** 证据连续性高于本次重构。
并行对照时 **(b) 必须传 `register_trials=False`**——对照不是承载路径，二次登记只会拿到幂等旧记录、
把 `n_evaluated` 记歪（`ledger_bridge` 会把这种情形标成 `ledger_reused_existing_record`，不静默）。

**违规处理口径（吏部 2026-08-27 裁定，08-31 当轮生效）**：某格 book 未过 `check_portfolio` ⇒
**该格本轮不调仓**、违规如实留档、**仍计入 `n_evaluated`**，本轮其余格与整轮落盘照常。
详见下方 §6；实现在 `qlab/qlab/llm_paper/rebalance_policy.py`。

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

### ⚠️ 08-31 那轮**大概率比不到 book**——空 book 上的「逐位相同」不算通过

实测（真代码，非推断）：本轨每轮的 book 只由**本轮**决策构成，而周一盘前决策的
`intended_start` 就是当天 09:30 ET 开盘：

```
decision_ts    2026-08-31T11:00:00Z = ET 2026-08-31 07:00（周一盘前）
intended_start 2026-08-31T13:30:00Z
最新可得 bar   2026-08-28（上周五；当日 bar 要收盘后才存在）
resolve_actual_start → actual_start=None, "价格腿尚无 >= intended 的 bar → pending，不猜"
⇒ book.status = pending_entry_bar，无 shares、无 nav_point
```

即 08-31 与第 1 轮同型。「08-31 是第一个真正产生 book 的轮次」只对**第 1 轮那 7 条决策**成立
（它们的 `intended_start = 2026-08-10T13:30Z`，对着现在的 bar 可解析），但执行器不会把上一轮的
决策带进本轮 book——两者之间没有 carry-forward。

后果与已上的护栏：两侧都没有持仓时，`shares`/`nav_point` 全为空，逐位比对**必然 identical**，
而「权重 → 股数按建仓日 open」那段算术**一行都没跑**。把它读成通过，切换就建立在从未检验过的
等价性上。故 `run_parallel_control()` 现在多给一个事实位 **`book_equivalence_exercised`**：
仅当 `book.status == "filled"` 才为真，`may_take_over` 必须同时满足它；空过时落
`ALERT_control_not_exercised_<stamp>.json`（与 `ALERT_control_mismatch` **刻意不同名**——
「什么都没比到」和「比出了问题」不该长成一样）。`no_rebalance`（违规不调仓）同样是空持仓，
一并按空过处理。

**这不改变 08-31 该不该跑对照**：跑，决策集比对与形态验证照旧有价值，轮次也照常落盘。
只是第 ② 段的真证据要等一个真正产生 `filled` book 的轮次。这条属工部/吏部的编排判断，
本文件只记事实与已上的护栏。

### 08-31 轮次怎么跑

⚠️ **`cells` 必须是冻结的足额 10 格，不是「够比对就行」的那一格。** 这不是洁癖：(a) 模式每轮
只产 1/10 网格的决策，而**决策是易腐的**——它需要当时那个信息截止下的 LLM 输出，事后补就是造数
（与拒绝回填丢失轮次同一条理由）。对照侧写出的 `control_multi_book/round_<stamp>.json` 是目前
**唯一**能把其余格子的决策留下来的地方，零额外配额（共用同一份 bars 快照）。
只传一格 ⇒ 那些决策**当轮永久损失**。详见 §8。

```python
from qlab.llm_paper.multi_book import expand_variants
from qlab.llm_paper.parallel_control import run_parallel_control

rep = run_parallel_control(
    proposals=<(a) 的提案，每条带 seed/prompt_variant>,      # 承载路径，正常落盘 + 登记台账
    cells=expand_variants({                                 # 对照：**足额 10 格**，自动不登台账
        "pv1_baseline":  <pv1 目标仓位>,                    # 须含 (a) 所在的那一格
        "pv2_riskaware": <pv2 目标仓位>,                    # ← 不传这个，pv2 的决策当轮就没了
    }),
    decision_ts=<决策时点>, probe=<金标准探针结果>)
# rep["bearing_payload"] 就是这一轮的真记录；rep["may_take_over"] 决定下一轮能不能切
```

`expand_variants` 按冻结口径把两份变体权重展开成 10 格（`temperature=0` ⇒ seed 名义化，
同一变体在 5 个 seed 上逐字同输出），缺变体会 fail-closed，不会静默少展。

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

## 6. 组合约束不过时取什么动作（吏部 2026-08-27 裁定，**08-31 当轮生效**）

旧行为：整轮 `raise`、零落盘。取代它的是——某格 book 未过 `check_portfolio` ⇒ **该格本轮不调仓**
（有前轮持仓则原样维持，无则全现金），违规如实落盘，**该格仍计入 `n_evaluated`**，
本轮其余格与整轮落盘照常。实现：`qlab/qlab/llm_paper/rebalance_policy.py`，(a)/(b) 共用。

**08-31 只上退化形态**（无前轮持仓 ⇒ 全现金）。退化形态成立有实测依据：本目录下只有
`round_20260810.json` 一份记录且 `book.status = pending_entry_bar`（无 shares、无 gross）
⇒ 每一格的「上一轮持仓」都是空的。全现金不是新语义——冻结 §2 明写现金上限 100%、允许全现金，
`check_portfolio([])` 实测 `ok=True / gross=0 / cash=1.0`，不需要豁免分支。
一般形态 carry-forward 归对照通过之后那批。

**退化形态被误用会把「不调仓」做成「清仓」**（方向相反且静默），故 `assert_no_prior_position()`
在动作前查一遍历史落盘：查到该格建过仓即 fail-closed，绝不用退化形态糊弄一般形态。
历史文件解析不了也拒——查不清就不许走。并行对照轮里 (b) 按**承载目录**查（对照子目录每轮新建、
历史恒为空，照它查会让两条路径在这一点上分歧，而那正是对照本身要发现的东西）。

边界（吏部原文，一条未扩散）：①只适用于 `check_portfolio` 对该格自身 book 的判定，其余失败
（缺价 / 探针 / 时序核验 / 台账 / 配额 / 决策链路）一律维持整轮 fail-closed；②空格子不适用，
`multi_book.py` 那句「空格子不是『持现金』，是漏了」原样保留；③格子永不从 `n_evaluated` 掉出；
④**禁止把违规权重投影 / 截断 / 缩放到合规**，动作取空动作；⑤留档够重建——格子 id、seed × 变体、
模型原始逐行权重、聚合权重、触发哪条约束、超出多少，`check_portfolio` 返回原样落盘不压成布尔。

**被点名要求的回归已落**：`tests/test_rebalance_policy.py::test_no_violation_output_is_bit_identical_to_the_pre_rule_path`
——无违规输入下，(a)/(b) 输出与加规则前逐位相同，payload 里不出现任何 `no_rebalance` 痕迹。

### 这条规则实际覆盖到的违规形态（比裁定书设想的窄，如实记）

`build_decision` 在**决策阶段**就拒掉两类，它们走不到 `check_portfolio`（实测）：

```
单行 target_weight = 0.11  → ValueError: EMR 目标仓位 0.11 超单标的上限 0.1
单行 target_weight = -0.05 → ValueError: 禁做空（long/flat only）
```

按边界①，决策链路失败**仍整轮 fail-closed**，故新规则实际只覆盖两种形态：
**同符号多行聚合后超单标的上限**（逐行合规、聚合超限）与**总仓 gross 超限**。
`violations_short` 在现有链路下不可达。这不是实现缺口——是边界①与决策阶段护栏叠加的结果，
记在这里以免后人误以为「贴着单标的上限」的那类风险已被这条规则兜住：
**单行报 0.11 仍然会丢整轮。**

**现金记零收益字面现金**（`nav - gross - cost`）。冻结散文「现金即 BIL 口径」与实现不一致是
既存偏离，吏部 2026-08-27 裁 (c)：口径钉死、实现放对照之后、**08-31 轮内一行不改**、
BIL 不进符号并集、不进配额、不进 universe、**永不因缺 BIL 死轮**；验收数取 `nav_bil_cash`、
`nav_literal_cash` 永久并存作保守下界，两条须同时上报并标明哪条是验收数。
一处更正需一并留档：**第 1 轮只有权重、没有现金读数**（`book.status = pending_entry_bar`、
`gross_notional`/`nav_point` 皆为 `None`），这条偏离首次真正咬人是产生 book 的那一轮，
不是从第 1 轮起就偏了。

## 7. 取行情也收进了共用桥接

`qlab/qlab/llm_paper/quote_bridge.py` —— `fetch_round_quotes()` 现由 **(a) / (b) / 并行对照三处共用**。
理由与 `ledger_bridge` 相同：这段是 fail-closed 护栏（`require_full_batch` 整批不出、
`QUOTA_DIVERGENCE` 独立 ALERT、缺价即拒），**多一份拷贝就多一处会静默分叉的地方**。
并行对照引入第三个调用点时，与其抄第三遍，不如三处共用一份。护栏逻辑一字未改。

副产品：打桩点从三处收敛成一处，测试因此不再耦合「取数调用写在哪个模块里」。

## 8. 接管判据变更 + 决策捕获 + 后续批次（工部尚书 / 吏部 2026-08-27）

### 8.1 接管判据改了 —— 因为**原判据被证明不可达**，不是因为达不成就放宽

原判据：并行对照的 `book_equivalence_exercised`（要求 `book.status == "filled"`）为真。
**它在现状下永远为假**：本轮 book 只由本轮决策构成，而周一盘前决策的 `intended_start` 就是当天
开盘，价格腿最新 bar 停在上周五 ⇒ 每一轮都是 `pending_entry_bar`（§4 那段实测）。于是
`may_take_over` **恒 False**，(b) 冻死在「未检验」——是**永远等**，不是暂时等。

把空过堵成 fail-closed 是对的（否则切换会建立在从未检验过的等价性上），但门后面没有路。
故判据改为：

1. **决策集逐位相同**（第 ① 段，已过，见 §3）；**外加**
2. **派生结算层**对 (a)/(b) 两侧 round JSON **各自产出**的每格 book / NAV 逐位相同。

这一段在派生层落地当天即可验——派生层从「不可改决策 + 归档 bars」重算 book/NAV，不依赖轮内
是否恰好有建仓 bar。

**必须写明的两件事**，免得日后被读成「达不成就放宽」：

* 改的是**判据落在哪一层**（轮内落盘 → 派生层），**不是**降低等价性要求。逐位相同这条一个字没松，
  比对字段也没减。
* 原判据不是「暂时难达成」，是**结构性不可达**：只要决策仍在开盘前做出、book 仍只由本轮决策构成，
  `filled` 就永远不会在决策当轮出现。这一点有实测（§4），不是推断。

**覆盖面要说清**：(a) 每轮只产 1 格，(b) 产 10 格 ⇒ book 等价性只在**两侧都有的那一格**上可比，
新判据不会、也不可能检验全部 10 格。这不是缺陷——执行器对每格走的是同一段代码；但报告里不得
把它说成「10 格全部验过」。

### 8.2 决策捕获：现在就起，零成本，且**它才是易腐的那一半**

派生层能从「不可改决策 + 归档 bars」把 book / NAV 全部回补出来，**但回补不出从未产生过的决策**。
所以每个以 (a) 模式跑的轮次，冻结网格里其余格子的决策**当轮即永久损失**，§4 的
`seed_distribution` 下四分位对该轮永远算不出来（下四分位结构性地等于**较差的那个变体**，
少了那个变体就无从算起）。

**止血**：08-31 起每轮照常跑并行对照，`cells` 传足额 10 格（§4 的 runbook 已改成这样）。
对照侧写出的 `control_multi_book/round_<stamp>.json` 与承载侧**同决策时点、同冻结、同 DAG 锚、
同一份 bars 快照**，零额外配额。能否升格为正式证据由吏部后裁——**先捕获、后定性**，反过来补不回来。

**一处量级更正（实测，与结论方向一致）**：10 格并非 10 份独立决策。冻结口径 `temperature=0`
⇒ seed 为名义值、不产生离散，5 个 seed 在同一变体上逐字同输出。实跑足额 10 格的对照轮：

```
对照侧 round JSON 落盘 ✓  格子数: 10   决策总数: 20
不同的决策集共 2 组:  pv1 → 5 格 / pv2 → 5 格
承载侧 (a)          格子数: 1
承载目录 n_evaluated 并集: {(11, 'pv1_baseline')}   coverage 轮数: 1（对照那份没被算进来）
```

⇒ 每轮真正易腐的是**一份**未被承载路径执行的 LLM 输出（`pv2_riskaware`），冻结网格把它计为 5 格。
量级比「9 份决策」小，**但结论一个字不变**：没有 pv2 就没有下四分位，§4 对该轮仍然算不出来。
另：第 1 轮的 pv2 目标权重其实**留过档**（`ROUND_CALIBER_NOTE_20260810.md` §2 的表，gross 0.37），
只是留成了人读的权重表，缺三时间戳 / `evidence_refs` / 论点，作为机器可核的决策证据比对照侧那份弱。

### 8.3 后续批次（08-31 跑完之后；本文件届时更新）

| 批次 | 内容 | 期限 |
|--|--|--|
| 1 | bar 归档（append-only + 内容哈希 + 取数时点）、派生结算层、第 1 轮回补结算、**(b) 接管** | **2026-10-31** |
| 2 | 四条冻结组合约束从 `build_decision` 整轮 fail-closed 移到每格同一道闸（后果统一为「该格本轮不调仓」） | 批次 1 之后 |
| 3 | carry-forward 一般形态、告警（连续 3 轮 / 单轮 ≥5 格）、`no_rebalance` 消费层、BIL 计息层 | 待裁 |

批次 1 的三个设计约束，设计时正面处理、不许等撞上：

* **bar 归档就是证据底座**，规矩照 BIL parquet 那套。附带收益：归档值与日后重取值一比，
  直接回答拆股那半的复权口径，不必再等「拆股日恰好落在 100 天窗口内」的标的（见
  `AV_ADJUSTMENT_FINDING.md` §2）。
* **`assert_no_prior_position` 在派生层下会结构性失明**：它认 `book.status == "filled" and shares`
  （`rebalance_policy.py`），而派生层之下 round JSON 永不 `filled` ⇒ 那道闸永远放行、永远走退化形态。
  闸抓得准、方向对，但站错了层。倾向的解法是**让轮内根本不需要知道前仓**：违规格的轮内动作改成
  「记录违规 + 本轮不提交新目标权重」，「维持上一轮持仓」的语义整个归派生层解释；并留一条测试
  钉死「不得再从 round JSON 推断前仓」。**派生层落地之前那道闸原样保留**——现在它是有效的。
* 批次 2 里 `build_decision` 保留的仍全部整轮 fail-closed：paradigm、锚点、网格、**无据不决策**、
  `decision_ts` 时区、三时间戳序——这些是证据完整性，一条不许跟着松。

## 9. 红线与边界（本次改动全程未动）

冻结文本 / 决策逻辑 / 冻结参数一律未动；`temperature` 未动、未重冻；`n_trials_total` 按冻结 10 格足额登记；
第 1 轮已落盘记录未回改。SIMULATE-only、零真金、仅免费数据、禁做空、单标的 ≤10%、总仓 ≤100%、≤1x。
**未 rebase、未 force-push**（集成分支 `agent/evo-162-residual-reversal` 快进推送）。

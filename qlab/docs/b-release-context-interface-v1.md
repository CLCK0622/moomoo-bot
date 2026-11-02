release_context 共同接口规格 v1.0.2（内部传参授权冲突与入口顺序澄清，待核）

作者：营缮主事。任务：EVO-881，工部派令 `01a19e47-e352-7af1-a330-9965c15ac876`。
本件定义接口，不提供 B01 类、接收器或 A 的实现。v1.0.0 已经工部核稿（01a19e53-9ee0）；v1.0.1 落实该评论两条约束。本版响应都水回读 01a19e8e-ed4e：保留已核接口与 12 码，明确内部传参在现有授权内不能闭合，交工部裁定；并补入口顺序及双缺陷矩阵，不把规格澄清称为实现通过。

本版只改此文档；产品基准固定本地头 `0cb4ba91fb5bcf6ea1854a14f51eb54487607599`。
其产品全量结果仍属于该固定头，本版没有重跑或升级为 B01/B02 正控。v1.0.1 原字节及逐字 diff 随交。

本地起点：`037e112ef1ab4919b1827e566b0387217ba0edc6`，取自本次 fetch 的远端
`evo884-exec-loop`。只在本地 `evo884-b-release-local` 分支保存本规格，不推送。
该起点不是尚未确定的 R 审查头；后续仅可重排未推送的本地提交，遇八文件冲突先停报工部。

## 1. 依据与适用边界

- 唯一机器采用件：`ff5da6ef748d5f1fca592559e73656d5283e28ec9d279b65b3ac0fd5943069ff`，
  BR.P5/P6/P10 与扩充后的 T11；原提案不能代替采用件。
- 首辅五项裁定：`01a19e46-3b74-7abd-8c5d-ba9a41e3ee8d`。第三块上限 17.25 AD、
  预警 13.8；营缮段高档 3.0；原两块上限不动。
- 首辅澄清：`01a19e47-89c5-7046-9faa-869126c04963`；外部附注登记评论：
  EVO-881 `01a19e47-bff6-7dc8-9d06-0ca0b4369576`。正式 A 必须引用该附注及登记 ID，
  缺引用即不完整。附注原文为：

  > 隔离清单 `quarantine_manifest_sha256=null` 不等于无隔离；CRH、COP、B、BA 的 UNKNOWN 冻结与隔离名单照既有裁定生效；若日后隔离清单单独核收，另版 R。

- 现有 R/P 不改字节。H_R 为
  `68f06b15ded4cb1ec5219a5456a2e0f0f376cab54a9e3ac33aee653dacfa877c`；H_P 为
  `4a4b24b0a6ee2b6b561d285fa6f3f9233960959500b6e02fc137c83ca31deae1`。
  当前 H_C 为 `0e5bf8afdbe2cd92ecc36b20c2cccb5a215a4bee8a3780ca71544fe2d88d0a64`；
  H_D 为 `a99e429cbd8335ecdd1321647768c3d663629ce7a1236106a356289fad11099c`。
  这些是已登记版本的核对锚，不是以常量代替共同接收核验，更不是本规格形成了 A。

此能力只代表 B 发布元数据与限定输入已经由原可信 host 接收；不代表市场来源/权限、
逐 producer 三证明、严格人数、完整 N、预算、SRC/AUTH、独审重封或 L0 已满足。
guard/scope 仍保持 `runtime_consumable=false`、`certifiable=false`，新读数仍 `seal_pending`。

## 2. 类型、公共入口与归属

规范类型名：`qlab.dynamic_factor.b_release_context.ReleaseContext`，由都水 B01 实现。
B02 的既有公共模块 `noncash_v3` 须导出同一个类对象，不能另定义包装类：
`noncash_v3.ReleaseContext is b_release_context.ReleaseContext`。
共同校验函数也经该既有模块导出，使营缮八件不必新增模块读取或扩大静态 import 能力。
这只是将来的接口要求；本件没有创建新 Python 模块或修改 noncash_v3。
工部附加约束：noncash_v3 的 main 差量只能是一行导入 b_release_context、上述两个名字的
再导出，以及 seal_guard/checked_guard 正式分支的签名和消费；不新增其他导出，不改其他
函数。scope_proof.IMPORTS["noncash_v3"] 只增 b_release_context 一个精确模块名并配反例。
这两件由都水在 B01/B02 实现，营缮先行头不动。八文件没有新增模块 import 或文件读取。
内部重核的授权冲突见 2.1，不能再以“待联调”当作有可行合同。本段仍保留这些原调用，
不得绕过、删掉或将其成功视为已经实现；B01/B02 未到时新正式路径仍拒绝，未宣称真实正向可达。

正式检查必须使用 `type(context) is ReleaseContext`。普通 dict、子类、代理、同名类、
仅有同名字段的对象和测试替身全部拒绝；不使用 `isinstance`、Protocol/duck typing、
类型名字符串或 `approved=true` 判断受信。

精确类型也不单独构成信任：B01 签发/重载入口仅归原可信 host；没有公开的
`ReleaseContext(**wire)`、`from_json`、pickle 或请求反序列化构造入口。
每次共同核验还须验证对象的签发来源以及独立受信绑定和原输入；私有 issuer 标记也不能
替代这些核验。此为受控 Python 调用边界，不宣称抵抗任意同进程代码篡改或构成 OS 隔离。

对象及其持有的原字节/期待绑定必须不可变，不得向消费者暴露可写的共享 dict。
复制可返回同一不可变能力；序列化/进程通信不得复制出新的受信能力。
host 在另一进程重载时，须用自己的受信输入重新核验同一份既存 A，取得当地同一规范类的实例。
仅反序列化旧身份记录不能生成实例，且不得因此重新签发 A。

### 2.1 内部重核：现行授权不能闭合，停止在合同裁定处

核对对象：main / 远端 2d45320 / 本地 0cb4ba9 的 noncash_v3 原字节相同，SHA256
`08301f9d7a5ad5bdcd2fcaae8422dec9896e18b59d197a9c183e81057e106744`。
都水回读包 SHA256 `ccf08c079548b7c4c7c9cbfda0b7ce145d13f11b39b7fdfd67df655090fe9ac2`
已下载重算核符；本地再次静态核对八件实际调用，不以回读结论代替源码。

现有传参链是 `assert_consumer_symbols:211 → allowed_symbols:202 → checked_guard:184 → seal_guard`，
前三条边均未携带 context / expected identity。`execution_amounts:75/88` 显式核验后，
`:94` 仍进入该链；`execution_cash:335` 复核后，`:345` 同样如此。
guard 是普通可持久化 dict；其中的 binding/hash 只有数据身份，不是 host 能力。
RiskHistory.restore 解码得到的也只是普通 dict，不能由其 JSON 反向生成能力。

只改 seal_guard/checked_guard 的签名和正式分支，无法让这些未改调用的默认 None
变成原 host 注入的能力及期待 bytes；先前外层成功不替代本次重核。
这结论限定于本规格已经核过的普通 guard / 显式能力接口，不声称否定另行设计新接口的可能。
本版不引入隐式线程/进程上下文、全局或按摘要查能力的注册表、guard 隐藏能力包装器、
函数装饰器、monkeypatch、从 policy/JSON 倒填能力或测试替身。这些均不是已核合同。
因此三处边界与每次原消费者重核的要求在当前接口下冲突，完整 B02 仍未闭合；
不以放宽 required、跳过消费者或仅比对自述摘要解决。

**交工部裁定的最小显式传参方案，未授权、未实现：**

| noncash_v3 原函数（原行号） | 建议仅增加的关键词及转递 |
| --- | --- |
| allowed_symbols:200 | 两关键词转 checked_guard |
| assert_consumer_symbols:208 | 两关键词转 allowed_symbols；原 consumer 检查仍先行 |
| guarded_value:215 | 两关键词转 assert_consumer_symbols；保留原 reader 位置 |
| economic_values:221 | 两关键词转 assert_consumer_symbols、每次 guarded_value |
| economic_read_receipt:228 | 两关键词转 zero_origin、economic_values；原 actor/origin 检查仍先行 |
| zero_origin:324 | 两关键词转 checked_guard；不改 zero_exposure、资本/初态检查 |
| acquisition_check:348 | 两关键词转 checked_guard、zero_origin；原 route/actor 顺序不动 |
| no_dependency_receipt:377 | 两关键词转 checked_guard、zero_origin、assert_consumer_symbols |
| forward_event:452 | 两关键词转 checked_guard、seal_guard；保留原前向门与状态保留逻辑 |

“两关键词”精确为 keyword-only `release_context=None, expected_release_identity_bytes=None`，
不改变已有位置参数/返回形态，不新增导出、import、读取、码或放行开关。
九函数共 15 处内部调用转递，预计约 45–80 行增加（排版相关），仅签名与实参；
这超出已授权的 seal_guard/checked_guard 两函数边界，未获裁定前不落产品 patch。
三个证明及 guarded_value 的源码身份会随实际差量变化，需迁移、重审与重封，不能复用旧 seal。

若获准，完整能力归属合同如下；在获准并联调以前仅是方案：

1. 原可信 host 从独立原输入核验/重载既存 A，将同一规范 ReleaseContext 实例及期待绑定
   注入拥有对象。首次构造可由共同 checker 得到绑定；一旦持有，此后固定传回同一 bytes。
2. 八件已有拥有对象/显式参数把自己持有的 context 与 bytes 传至表内入口；每条内部边
   原样转递，不从 guard 生成、不按 consumer 重签。每次到 checked_guard 仍进入共同重建，
   不把外层验证成功作为跳过令牌。
3. restore 先按第 6 节比较磁盘/host/context 身份，再构造拥有对象、传递同一能力；
   跨进程由当地 host 独立重载同一 A 得到当地规范实例，不传输或 pickle 能力。
4. forward_event 的新 request 也要用同一 context 重新核范围；若新 catalog/event 不属
   原接受范围，保持 scope 拒绝，不能借“转递”自动扩大许可或生成新 A。

八件中受影响的外部调用在 execution_amounts、execution_cash、execution_risk、
execution_accounting、execution_signals、execution_projection、execution_candidate；
execution_risk_history 负责能力拥有/恢复。它们仍需在获准后补实参与复核测试。
本地 0cb4ba9 上，八件之外另见 execution、valuation、k5、reference_day_inputs、
reference_compile_v3、reference_noncash、execution_receipts/input_envelope 调用上述函数。
它们只是影响清单，不是本版授权；逐调用行、源码 SHA 与 main 原件归属见随件静态 inventory。
正式调用须由各自原 host/拥有对象传入，诊断调用保留 None 的原范围；哪些调用进入正式
分支须由工部与原作者逐件划定，不能凭函数同名扩大到所有调用。R 固定头到件后重出清单。

请工部决定是否提请扩充这九函数的传参授权及对应调用方分工；本版不自行扩大边界，
不请求修改 zero_exposure/state、费用算法或旧 golden。两个既定再导出本身足够，
冲突在内部参数边，不在 B01 返回类型或增加公共出口。

## 3. 固定属性

属性均为只读。非空 str/bytes 必须按精确内置类型检查，SHA 为 64 位小写十六进制 str。
下面的 H_* 使用统一字段名；消费者不得自定义别名或互填。

| 属性 | 精确类型 | 含义及核对来源 |
| --- | --- | --- |
| `context_version` | str | 显式核收结果版本；不能用 PID、consumer 或调用时间生成 |
| `release_id`、`release_version` | str | R 中的版本身份；与 host 所接受版本相等 |
| `a_raw` | bytes | 固定 A 原字节，非重编码后的 JSON |
| `h_a` | str | SHA256(a_raw)，还须与 host 独立绑定核对，不能只验自摘要 |
| `r_raw`、`p_raw` | bytes | 固定 R/P 原字节；与平台实际公布身份及独立期待值核符 |
| `h_r`、`h_p` | str | 分别为 R/P 原字节 SHA，不是目录内容或 ZIP SHA |
| `h_c`、`h_d` | str | 从已核原输入及 R 的相应 payload 按采用件重算 |
| `receiver_id` | str | 实际接收方身份；不是本次 consumer、writer 或调用工程师的代称 |
| `implementation_id` | str | 形成该接收结果的实现版本标识，不随进程变化 |
| `implementation_sha256` | str | 该接收实现的受信源码身份，与 host 的接受绑定一致 |
| `accepted_at` | str | A 对应的真实接收核验时点，带 UTC 时区且与原证据逐值一致 |
| `acceptance_time_evidence_raw` | bytes | 固定真实时点的原证据；不能以当前时间或请求自报替代 |
| `acceptance_time_evidence_sha256` | str | 上述证据原字节 SHA，并与独立 host 绑定核符 |
| `adoption_sha256` | str | 正式条款采用件 SHA；本版固定为第 1 节机器 SHA |
| `policy_binding_bytes` | bytes | 已接受 policy/profile/U64 顺序/calendar 的规范身份对象 C 编码 |
| `annotation_binding_bytes` | bytes | 第 1 节外部附注的登记身份、revision 与原文绑定，详见下节 |

可信 host 还须私有持有 R/P 的真实平台公布证据、writer 发布评论
`01a19dda-830d-7b82-b549-b4d64129a6af`、限定原输入与各自已核范围，以及独立期待 SHA。
这些不能从 guard/request/A 的自述反向取得。路径和公开哈希不是信任根。
本规格不替 SRC/AUTH 创建受信源，也不把 N 的 authority_host 当来源许可。

`a_raw`、接收方/实现身份、真实核收时点及其证据在同一 context_version 内固定。
A 必须引用外部附注登记评论及其接受范围。若 A 后才形成某份真实读回证据，证据可绑定 H_A，
A 不得反向包含该后发证据的 SHA/ID；不制造自指，也不预填未来附件或发布 ID。
需要换 A 或接受范围时，须新显式版本、原线核验和传播，禁止原地替换旧 context。

## 4. 校验入口（签名合同，均未实现）

Python 3.9 与 3.12 使用同一签名；以下省略号只表示接口声明：

```python
def check_release_context(
    release_context, *, policy, request,
    expected_release_identity_bytes=None,
) -> bytes: ...

def seal_guard(
    request, policy=None, *, release_context=None,
    expected_release_identity_bytes=None,
) -> dict: ...

def checked_guard(
    guard, policy=None, *, release_context=None,
    expected_release_identity_bytes=None,
) -> dict: ...
```

`check_release_context` 由 B01 提供；`noncash_v3` 导出相同入口。
`seal_guard`/`checked_guard` 的正式分支由 B02 接入。其正式输入中 context 为精确规范类型；
expected identity 若传入必须为精确 bytes，且是第 5 节规范绑定的原字节。
`check_release_context` 返回该绑定的规范 bytes（可保存/比对，不能充当能力）。
`seal_guard` 从原输入生成具名正式 guard；`checked_guard` 从同一 context、policy、
guard.request 从头重建，逐字段/值比较 guard，不以 guard 自摘要为充分条件。

下述顺序只描述共同核验边界内部，不覆盖 seal/checked/restore 或八件入口已经在前面的旧检查：
检查实现可用及能力类型/来源；从独立 host 期待值和原件核正式采用件、
R/P/发布身份、限定输入、A/固定时点证据及外部附注；重算 H_C/H_D；核 expected identity
及当前 policy/request 的 mode、范围和时点；最后重建并比较 guard。
传 expected identity 是额外一致性要求，不是放宽独立核验的替代方案。
相同 context、相同 policy、相同 request 下，返回绑定及正式 guard 原字节应跨消费者、
时间和进程稳定；重建不产生新 A、不取当前时间、不混入本次 consumer/PID。
不同日期或 mode 的 request 仍按各自原规则校验，不要求不同 request 的 guard 字节相同。

正式 guard 仍按 BR.P4/P5 使用 H_C/H_R/H_A/H_D 的唯一语义；R/P/A 不成为运行权限。
`zero_exposure`、数值域检查和费用公式均不在本接口的修改范围内。

### 拒绝码与状态

所有以下失败均 `raise ValueError(code)`；上下文检查不得调用数值 reader/worker 或推进状态。
既有其他检查先失败时仍保留原码，不利用本表改写既有隔离/R2 拒绝顺序。

| code | 触发条件 |
| --- | --- |
| `B.release_context_implementation_unavailable` | B01/共同导出尚未实现；只拒绝，不接替身或静态回退 |
| `B.release_context_required` | 新正式分支缺少 context |
| `B.release_context_type_mismatch` | dict/子类/代理/测试替身等不等于规范精确类型 |
| `B.release_context_trust_binding_missing` | 无合法 host 签发/重载来源，或缺独立受信绑定/原输入 |
| `B.release_context_encoding_invalid` | 原件解析不符合严格编码，或 identity 不是规范 bytes |
| `B.release_context_release_mismatch` | R/P、公布身份、采用件或 H_R/H_P/H_C/H_D 与独立重算不符 |
| `B.release_context_acceptance_mismatch` | A 原字节/H_A/版本/接收方/实现身份/真实核收时点证据不符 |
| `B.release_context_annotation_missing_or_invalid` | A 缺外部附注登记引用，或引用/范围与受信登记不符 |
| `B.release_context_scope_mismatch` | policy/profile/U64/calendar/mode/范围或实际可用时点不符 |
| `B.release_context_persistent_identity_required` | 正式恢复缺持久绑定或缺 host 期待绑定 |
| `B.release_context_persistent_identity_mismatch` | 磁盘、host 期待绑定与重载 context 不同，含混用 A 版本 |
| `B.guard_identity_mismatch` | 上下文已核，但 guard 不等于同请求的共同重建结果；保留原码 |

本表不改 C09 的 B 发布门或 SRC/AUTH 外部门原码。旧静态/合成诊断只在原有明确诊断范围
继续存在；正式 schema 或含正式 release_binding 的请求不得删字段、改 synthetic 或回退
旧 guard。缺实现时也不能声称存在正式正控。

### 4.1 入口位置与拒绝顺序

12 行是码义集合，不是全局排序；persistent_identity 两码还涉及 restore 数据门，
guard_identity 则属于重建比较。以下是 B01/B02 到件时的接口合同澄清，仍待工部核稿；
不是这些尚不存在的正式分支已经执行通过。

| 入口 | 前置检查、共同核验及后置比较 |
| --- | --- |
| 直接 check_release_context | 入口已可用才可调用；缺实现由调用方解析出口时报 unavailable。依次缺能力/精确类型、host 来源与独立绑定存在性、原件/期待绑定严格编码、采用件及 R/P/发布身份和 H_C/H_D 重算、固定 A/接收时点证据、外部附注、可选 expected identity 的逐字节比较、当前 policy/request 范围。首次构造未传 expected 不报 persistent_identity_required。成功只返回完整 C 编码 bytes，不比较业务 guard。 |
| 直接 seal_guard | 先走该分支适用的原 request 结构/mode/synthetic、时间、prior、完整 U64/catalog/证据、可选注册派生检查；保留原先遇错即停的顺序。正式分支的共同 checker 位于原 runtime catalog 接受检查的位置、payload 重建之前。旧诊断分支原接受检查不动；正式分支由核过的 R/P/A 接受合同取代旧静态 ACCEPTED_CATALOG_SHA256 比较，不先让旧空常量永久挡住新分支。不得据此跳过 schema、时间或注册派生检查。 |
| 直接 checked_guard | 先保留原外形及取 request 行为：非 dict 报 guard_identity_mismatch，dict 缺 request 仍为原 KeyError('request')。之后以同一 context/expected bytes 调用 seal_guard 重建；seal 前置失败原样传播，其共同 checker 成功后才比较整份 guard，不等才报 guard_identity_mismatch。不把 checker 提到上述旧前置之前。 |
| 正式 RiskHistory.restore | 按当前 0cb4ba9：raw SHA → 严格 JSON 解码 → 原 schema/book/scope → history_source_sha256 → 正式根闭集 → BR1 根及 host 期待绑定存在性 → 磁盘绑定严格编码 → host 期待绑定严格编码 → 两份 bytes 相等 → 整份 raw 规范编码相等 → context 存在性 → release_guard（解析共同实现、精确类型、共同 checker、checked_guard）→ initial 闭集/构造 → 事件逐次重放 → 完整导出相等。来源不符在能力检查前拒绝。C04 Journal 没有 restore，本版不新增。 |

seal 的“原结构”是各分支定义允许的闭集；新正式键的允许范围由 B02 登记，不能拿旧
诊断闭集排除正式必填字段，也不能为正式键放松旧诊断闭集。原函数即时异常保持原语义：
例如坏时间文本可能是 datetime 的原 ValueError，缺 signal_close/request 可能是 KeyError；
本表不新造统一码来掩盖它们。

八件先行桥本来会在调用 checked_guard 前显式调用共同 checker，这仍是该外层入口自己的
调用位置，不等于“直接 checked_guard”的顺序。例：quote_exact 先检查 orders/notionals
成员，再解析 B01 出口、核 context、checked_guard，最后原消费者。CashProof.check 先核
原 state/book/guard 身份，再核拥有的 release 绑定和共同 checker，最后原 allowed_symbols。
本版不把所有入口改成同一顺序；2.1 的缺口未裁定前，桥后的原消费者链仍未闭合。

### 4.2 双缺陷矩阵（合同预期与当前实物分开）

下面 S/K/C 行描述 B01/B02 已实现时的合同预期，**本轮未实跑正式能力正控或这些未来分支**。
每行其余字段须有效且足以到达所列门；“缺 context”指已识别的新正式分支，不能回退诊断。
R 行是 0cb4ba9 已存在 restore 语句的静态顺序；不是本轮产品执行结果。

| ID / 入口 | 同时存在的两个缺陷 | 先失败的结果 / 尚未到达 |
| --- | --- | --- |
| S01 seal | request 结构不合法 + 缺 context | B.guard_schema_invalid；未进 checker |
| S02 seal | sealed_at 缺时区 + 缺 context | B.timezone_required；未进 checker |
| S03 seal | 历史 sealed_at 不早于 first_performance_at + 缺 context | B.not_sealed_before_performance；未进 checker |
| S04 seal | U64 catalog 不完整 + context 类型错 | B.full_U64_catalog_required；未进 checker |
| S05 seal | 原前置全有效，B01 出口缺件 + 缺 context | B.release_context_implementation_unavailable；不回退 |
| K01 checked | guard 非 dict + 缺 context | B.guard_identity_mismatch；不取 request |
| K02 checked | guard 缺 request + 缺 context | 原 KeyError('request')；未进 seal |
| K03 checked | request 时间无时区 + guard 摘要错 | B.timezone_required；未比较重建结果 |
| K04 checked | 原前置有效，缺 context + guard 内容错 | B.release_context_required；未比较 guard（B01 出口已可用） |
| C01 checker | 能力精确类型错 + R/P 身份错 | B.release_context_type_mismatch；未核 R/P |
| C02 checker | 无独立 host 绑定 + A 身份错 | B.release_context_trust_binding_missing；未核 A |
| C03 checker | 原件编码非法 + R/P 身份错 | B.release_context_encoding_invalid；未比 release |
| C04 checker | R/P 身份错 + A 身份错 | B.release_context_release_mismatch；未核 A |
| C05 checker | A 身份错 + 附注缺失 | B.release_context_acceptance_mismatch；未核附注 |
| C06 checker | expected bytes 合法但混版 + request 范围错 | B.release_context_persistent_identity_mismatch；未核当前范围 |
| R01 restore | raw SHA 错 + scope 错 | risk.current_history_bytes_mismatch；未解析 |
| R02 restore | scope 错 + history source 错 | risk.history_scope_mismatch；未核 source |
| R03 restore | history source 错 + 缺 context | risk.history_replay_mismatch；未核能力 |
| R04 restore | 正式根缺 release_context_binding 键 + host 期待缺失 | B.release_context_encoding_invalid；根闭集先失败 |
| R05 restore | 根键齐全但 host 期待缺失 + 磁盘绑定为另一合法版本 | B.release_context_persistent_identity_required；尚未作混版比较 |
| R06 restore | 磁盘绑定编码非法 + host 期待为另一合法版本 | B.release_context_encoding_invalid；先解析磁盘 |
| R07 restore | 磁盘/host 两份合法 bytes 混版 + 缺 context | B.release_context_persistent_identity_mismatch；未核能力 |
| R08 restore | 整份 raw 非规范编码（摘要取实际 bytes）+ 缺 context | B.release_context_encoding_invalid；未核能力，前面的根/绑定门均有效 |
| R09 restore | 缺 context + B01 出口缺件 | B.release_context_required；未解析 B01 出口 |
| E01 quote_exact | orders/notionals 成员错 + 缺 context | fee.exact_net_order_membership；未解析 B01 出口 |
| E02 CashProof.check | 原 state/book/guard 身份错 + context 混版 | accounting.cash_proof_state_or_scope_mismatch；未核 release |

R04 与 R05 刻意区分“磁盘根缺键”和“host 期待缺失”，不可统称缺绑定后随意选码。
S05 与 R09 也刻意不同：unavailable 不是覆盖所有入口的全局最高优先级。
表中拒绝均不得推进 reader/worker、事件或日期；这一不推进条件须在完整 B 头真实联调取证，
本次静态顺序核查不能替代 T10/T11/T19/T20 验收。

## 5. 持久身份：只记录绑定，不保存信任能力

本节 C 编码沿用 BR.P4：UTF-8、ensure_ascii=false、sort_keys=true、紧凑分隔、无尾换行，
拒绝重复 JSON 键、NaN/Infinity、缺键与多键。不能先用 `contract.clean` 把非法值变成 null，
不能将调用方路径或可变全局 pin 作为其中的期待值。

内部 identity 的闭集字段为：

```text
schema = EVO884.BReleaseContextIdentity/v1
context_version, release_id, release_version
adoption_sha256
h_a, h_r, h_p, h_c, h_d
receiver_id, implementation_id, implementation_sha256
accepted_at, acceptance_time_evidence_sha256
policy_binding
annotation_binding
```

`policy_binding` 为下列闭集：`conventions_version`、`conventions_sha256`、
`conventions_status`、`profile_sha256`、`prereg_sha256`、`prereg_version`、
`common_profile_sha256`、`date_manifest_sha256`、`common_calendar_sha256`、`universe`。
前七项逐值取当前已核冻结 policy.binding；date_manifest_sha256 取原日期 manifest 字节 SHA，
common_calendar_sha256 取该已核 manifest 的同名绑定并与 host 原日历/顺序复核。
`universe` 是原 policy.profile.universe 的 64 名有序 JSON list，逐值逐顺序相等。
其余九项均为精确非空 str，SHA 项依前述格式。不能按请求裁剪键、改版本或重排 U64，
不能用磁盘/请求里的同名子对象倒填期待值；不借本节新定义研究规则。

`annotation_binding` 闭集字段：`issue_id`、`comment_id`、`revision`、`content_sha256`。
ID 为精确非空 UUID str，revision 为精确正 int（拒 bool），content_sha256 为规范 SHA str。
本版 issue 为 EVO-881 `01a18a61-21a5-7763-8cd3-9c781f80499d`；comment_id 为
`01a19e47-bff6-7dc8-9d06-0ca0b4369576`。revision 及 content 须从真实平台读回、与独立
接受绑定核符；content_sha256 明确定义为该版本 CLI 返回 content 字符串 UTF-8 编码的 SHA，
不是声称平台提供了一份附件原字节。登记变更不得静默替换已接受的旧版本。

持久绑定的精确外层是：

```text
schema = EVO884.BReleaseContextBinding/v1
identity = 上述 identity 对象
identity_sha256 = SHA256(C(identity))
```

`expected_release_identity_bytes` 和校验返回值均为 C(上述完整外层)，不是 hash 字符串。
identity 不含自身摘要，故无自指；A 原字节不重新编码后塞入 identity，也不序列化 host
能力、issuer、loader、callback 或凭据。保存全部 raw bytes 的独立 host 档案可按原机制存在，
但该档案路径不是能力或权限证明。

新正式分支的业务对象以具名 `release_context_binding` 字段记录上述外层；新增字段必须
属于其明确登记的新正式 schema，不能往原闭集根偷加键：

| 对象 | 新正式根（旧诊断根仍按原范围） |
| --- | --- |
| RiskBook snapshot | `EVO884.CloseRiskSnapshot/v1-BR1` |
| required M | `EVO884.RequiredM/v1-BR1` |
| RiskHistory 导出 | `EVO884.RiskHistory/v1-BR1` |
| ExecutionAccount snapshot | `EVO884.ExecutionAccount/v1-BR1` |
| AccountClose | `EVO884.AccountClose/v1-BR1` |
| ExecutionAccountJournal 导出 | `EVO884.ExecutionAccountJournal/v1-BR1` |
| CandidateExecution 输出 | `EVO884.CandidateExecution/v1-BR1` |

这些是未来八文件传播的接口约定，并非本次已经生成的对象。
全部新增自摘要仍按原规则逐层计算，包含实际 release_context_binding；不得剔除
input_sha256 或先前层的真实派生身份。D1 的投影数值子对象、原 G/K 与费用 oracle 不改。
纯算术输出和 C07 不额外签发 A；C07 经拥有的 C04 账户/初始 snapshot 传递这些绑定。

## 6. restore 与调用方约定

RiskBook/RiskHistory 的新关键词：`release_context=None`、
`expected_release_identity_bytes=None`；保持现有位置/关键词参数次序不变。
正式分支 context 必填；首次由 host 构造时 expected identity 可省，仍须完成全部独立核验。
正式恢复则两项都必填：

```python
# RiskHistory 的 classmethod 接口声明，不是调用表达式。
@classmethod
def restore(
    cls, raw, *, expected_sha256, expected_book_id, expected_scope,
    policy=None, cash_proofs=None,
    release_context=None, expected_release_identity_bytes=None,
): ...
```

恢复必须先核原 raw/source/book/scope 身份，再核 host 注入的精确 context 与 host 期待绑定，
并逐字节比较磁盘 release_context_binding 的 C 编码。三者相等后，才从原事件依次重放；
每次生成 RiskBook、跨折或收盘均传同一能力/绑定，不能把 payload.initial 解码当注入来源。
旧 JSON 即使填齐全部字段并重哈希，也不能构造能力。仅提供 host identity bytes 而没有
host 能力也拒绝。缺键/多键、删绑定、混 A 版本、新源码配旧 seal 均不得进入事件或数值读取。

C04 沿原精确 RiskBook 类型取得上下文；CashProof 持有同一绑定，check 时与原账户的
guard/context 一致，不能由 wire 重建。当前 C04 Journal 是只读对账产物，没有 restore
能力，本合同不新增 C04 restore。C03 project/精确报价、fixed_scores、CandidateIntent 的
消费入口传同一上下文；只有共同 checker 重建防护，不另写消费者专用核验副本。

序列化或重载失败保留原库存、现金、权益、挂单、年龄、意图、latch、风险状态和日期。
失败不是新交易日，不重建本金，不修改 CashProof 金额或把未知转成零。

## 7. 不依赖 B01/B02 的先行传播与测试约束

规格核过后，营缮只改已报价八件：execution_risk、execution_risk_history、
execution_accounting、execution_cash、execution_projection、execution_amounts、
execution_signals、execution_candidate；同步已报三份文档。main 原件仍为 0 件。
本规格文件是本次明确要求的接口文档，不是新增产品模块或正式协议采用件。

先行代码可准备关键词、拥有对象的持有/转递、持久绑定及恢复拒绝，但共同实现未就绪时
新正式路径只能拒绝 implementation_unavailable；不自行实现 A/共同 verifier、不新增
import/read 能力或宽泛回退。日后从既有 noncash 公共出口接 B01/B02；任何额外静态边或
文件需求先回工部，不类推权限。B01/B02 到件前不作真实发布正向接收验收。

测试替身必须定义在测试代码中并显式命名 `ReleaseContextTestDouble`、
`ReleaseContextCheckerTestDouble`；不得成为规范类的别名/子类、注册为 host 能力，
或靠增加生产参数/环境开关进入正式入口。测试中可用单独的诊断调用探针观察传参和拒绝
顺序，但必须另断言同一替身经正式入口被拒，reader/worker 均为 0；探针不能充正式正控。

| 规格 | 先行取证与待办 |
| --- | --- |
| T10 | 准备 R/A 混版、自摘要伪造及不推进状态/日期反例；真实共同重建拒绝待 B01 到件 |
| T11 | 准备同一 A 跨消费者/时间/进程字节稳定与混版恢复反例；替身只验证传播，不能记正式通过 |
| T12 | 旧权益/未知敞口的原 R2 保留回归；不改 B 数值域、费用/期望或补零 |
| T13 | 准备候选/参考/META 同日 release/mask 不一致；正式共同派生联调待 B01/B02 |
| T19 | 原冻结脚本/输入/旧回执在旧源码 worktree 实跑，保留完整观察、argv、退出码 |
| T20 | 新传播源码配旧回执/旧 seal 在真实 reader 之前拒绝，实测 reader=0；不能以 collection/import 错误冒充业务门拒绝 |

T19/T20 先行新源码只证明本传播头的硬门，不外推尚未实现的 noncash 修改。
B01/B02 真正改动 noncash 后，完整 B 新头必须重跑新硬门及固定 main AST/zero_exposure
原函数体字节对照，不能复用先行结果代替。本版六项的实际执行状态以先行头交件的原始日志为准；替身观察、持久化数据控制不作为正式重建正控。
T19/T20 必须对同一份旧原件逐件作旧/新源码对照；不得旧端选 noncash 回执、新端改选
另一份 B2 manifest 后混称同件红绿。若先行头因 noncash 尚未改动而仍接受某份旧回执，
保留实跑结果及具体未闭合项回工部，不伪造拒绝、不扩大 main 范围或改旧夹具来造绿。
工部明确：先行头未改 noncash_v3，只绑定它的旧回执继续接受是预期，不是缺陷；交件逐件
标“因八文件传播改变被拒”或“待 B02 改 noncash 后才拒”，两版均记录实际输出，完整 B 头再统一重跑。

## 8. 核稿、版本与交付

v1.0.0 类型/出口等接口与 v1.0.1 附加约束已经核稿，八件先行传播及 pin 修复已另交。
本版请工部核第 4 节入口顺序，并裁定第 2.1 节九函数传参超出现有授权的冲突；
未获裁定不继续产品实现。12 码及规范签名不变，不把本稿或都水静态回读当作 B02 闭合。
显式保留 v1.0.1 原字节/diff；不等待回读后在本轮继续实现，也不设循环唤醒。

本地未推送提交须等 R 固定头确定后再 rebase 到该头，之后才可推到新
`evo884-b-release` 分支；不向 evo884-exec-loop 推送，不重写已推历史，八文件冲突即停报。
R 后单开 B 差量审；原 R/S 不等 A 或 B 门；B 晚于 S 则另作差量重封。
不运行真实策略/参考/前向、不取市场、不写权威链/预算/安装/生产路径，B 门和 L0 保持关闭。

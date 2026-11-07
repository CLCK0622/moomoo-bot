C09/C10：同源执行、隔离重放与剩余外部门

`reference_execution.ReferenceExecution` 只编排原 C03/C04/C05/C06/C07。
构造时必须是同一参考成员、fold、attempt、独立零账本的 `StartupBook` 和
`RiskHistory`；候选、实际 META 或其他账本不能替换。四个成员继续用原固定 solo
profile，选择 P，不读取实际 META 池、衰减或 G/K。数量、M、费用、现金、风险、日期、
末清算及收益都由原引擎生成，本模块没有这些算法的副本。

`startup_open`、`lock_projection`、`model_open`、`close` 接收绑定事实/信号及其 SHA。
M 和 P 不能作为调用方结果传入；`lock_projection` 直接调 C04 的 `lock_projection`，
由其调用唯一 D1 和 D2。`close` 直接调与候选相同的 `close_execution_day`，顺序为
ACCOUNTING_AND_NAV → C06_RISK_ONCE。C05 原接口与规范十进制的兼容边界保持原状。
首个常规决策时点消费 C05 已算的字段，不另选起点。

`observe` 只能由完整 C05 和 C07 所属账本签发 `ReferenceObservation`。
C07 重新从完整 1260 个原始收盘记录计算收益，调用方只能提供另行绑定的 QQQ B1 TR
基准，不能提供策略收益或 SR。返回对象在宿主私有 registry 中绑定原账本、原事实程序、
实际事件和 SHA；序列化字典、伪对象、其他成员及已经漂移的账本均不能取代它。

`reference_boundary.run_execution_result` 是旧空输出 preparation 之外的独立入口。
它先核自有对象和新的静态证明，然后以 `-I -S`、空环境、关闭继承 FD 启动子进程。
传入的不是收益，而是宿主自有事实程序。`reference_producer_v3.result_main` 在隔离进程
内重建独立账本，逐个执行同一四种具名操作，重新调用相同引擎产生 C07 输出，再与宿主
绑定的完整结果逐字段相等比较。未知操作、程序改写、非空结果替换和不同退出码均拒绝。

`run_execution_family` 要求原四成员一个不少；先核全批成员、独立 book/attempt、同一
run/fold/calendar、D1/D2 源码及两份采用件身份，再启动任一子进程。
同批还必须共用完全相同的 guard、QQQ 基准及逐决策资格集。每个 C06 `decision_due`
要求的开盘都必须消费同源 D1 的锁定计划，不能省略决策而仍签发完整收益。
成员的角色保留 `independent_candidate_reference` 或
`independent_meta_reference_probe_component`，没有改标候选或实际 META。

新 `scope_proof.reference_execution_proof` 独立命名，不改变旧 `IMPORTS`、`GATES`
或旧 preparation 的 `import_graph` / `reader_sites` 语义。它检查精确 import 令牌，
逐项登记四输入文件及原 C12/G14 的固定读取，继承 C13 十条原固定件绑定。
`execution_receipts/replay_files.py` 另逐文件列出隔离重放用的固定协议件及源码身份读取。
源码清单读取来自原 `contract.source_manifest()`；读取源码字节不等于执行其中的模块。
旧冻结配置和历史 seed 也不是安装态权威链或当前 N。
原 conventions / moments 的 AST 校验只准编译表中九个冻结表达式；任意其他表达式及所有 exec
仍被拒绝。这不是放开公式求值或提供用户代码入口。

隔离重放在接收事实程序前核对上述逐文件 SHA，然后安装只读 audit hook。
除原源码清单需要的固定源码根目录扫描以外，不允许目录遍历；每次文件打开仍须命中精确
清单。它不能打开经济输入文件、其他账户、安装态权威文件、网络或子进程，不能写文件。
`reader_calls/accessed_roles` 计经济文件读取，保持 0/[]；实际协议/源码读取另列
`protocol_read_paths`，实际执行操作数另列 `execution_steps`，不把它们藏在 reader=0 中。
此证明针对固定可信源码，不是任意恶意 Python 或有宿主写权限者的安全证明。

`reference_v3_evidence.execution_readiness` 是正式执行之前的只读元数据接收。
它复用原输入准备和 C12 的 `bind_execution_n`，校验实际 run/成员与全尝试映射，
完整本臂 N 只来自原 host reader；design archive reference、账面 1313、自报值不进该槽位。
缺失/漂移/N 未闭合会先拒绝，剩余外部门清单为空，不能冒充只有外部缺件。
对其他前置元数据齐备的受控正控，原短路拒绝码仍为
`reference.runtime_B_release_and_actual_proofs_missing`；`remaining_external_gates` 精确列出
`B_RUNTIME_RELEASE` 和 `SRC_AUTH_RECEPTION` 两项，后者的具名拒绝码为
`reference.SRC_AUTH_source_and_permission_reception_required`。两项均 `accepted=false`。
清单不把 N 的 authority_host 当来源许可，不接受请求自报或任何来源/权限替身。
收益为空、数值 reader 和 worker 启动次数均为 0。这是剩余外部义务的枚举，
不是已获准的来源或 P4/P7 正式运行回执。P4 的实际正式运行尚未发生，`P4_actual_run` 明确保持 null；诊断实际
DAG 不冒充正式运行回执。正控的私有完整 N 安装假设也不代表生产安装或完整 N 获准。

B 发布仍属外部门。原 `reference_v3_scope.py`、`execution_risk.py`、旧 guard/reader
一字不改，不造发布锚，不把真实输入重标 synthetic。一般真实来源、权限和预算核收仍沿
原权限线；源码/输入 SHA 自洽不是这些核收。旧 `runtime_check` 的正式门没有被此诊断
入口绕过。

所有诊断和新源码结果继续 `seal_pending`、`execution_verified=false`、
`runtime_consumable=false`、`certifiable=false`。带 pending 的对象不能进入正式回执。
这里只提交工程机制供 R 审查，没有独立认证、发布、安装、权威写入、预算消费或运行许可。

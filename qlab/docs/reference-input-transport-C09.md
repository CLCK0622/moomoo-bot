C09：四类原件的隔离传输（独立段，尚非完整 C09/C10）

本段承接 22c6638 的输入清单。宿主 `reference_boundary.prepare_execution_inputs`
先复用原 `prepare_input_envelope`，按原 B 谓词检查全部声明批次，再生成进程内
`InputPreparation` 对象。`run_isolated(..., input_preparation=...)` 核对原请求
与宿主保留对象，传输期望值在 bootstrap 中单独绑定，不从 stdin 取权威值。
wire dict 不能代替该对象。这个对象只授权本次诊断读取，不认证来源或权限。

隔离 worker 用 `-I -S`、空环境、关闭额外 FD；加载固定源码后、读取数据前安装
独立审计钩子。只允许 raw.json、rights.json、adv.json、cash.json 四个只读路径。
原 reference_inputs.py / reference_guard.py 继续只认原三文件，语义不变。
reference_check 分别列出两个 reader、读取角色及源码，守卫次序可做变异验证。
四个文件全部预检之后才打开第一件，任一 symlink、hardlink、缺件或别名拒绝。
每件先核清单原 SHA，再解析重复键/非有限 JSON，并核全部日期/标的头之后才碰值。

机读传输结构（这是本段 schema，不是经济完成性 schema）：

```text
EVO884.ExecutionInputReadRequest/v1 = {schema, manifest}
EVO884.RestrictedExecutionRows/v1 = {
  schema, role, book_id, run_id, member_id, scope_sha256, profile_sha256,
  records: [{date, symbol, available_at, values}]
}
role=raw    -> values={raw_open, raw_close}
role=adv    -> values={adv20_dollar}
role=rights -> values={rights_events}
role=cash   -> values={cash_events}
```

records 的有序 (date,symbol) 必须逐项等于该槽位声明的日期×标的批次；不删日、不
补日、不补零。raw/adv 传输原有限标量或显式 null，不转换为 float，不验证币种、
复权、规范十进制或经济时点。rights/cash 传输 null 或原件列表；每项只有原 raw
字符串及其 sha256，逐字节保留、严格解析为 object。事件内部的完整谱系、金额、
原价/账户到账语义留给原 C04 检查；本段不解释它，更不将发行支付日当到账日。
空事件列表也只是来源声明，不证明不存在权益或款项。

`EVO884.ExecutionInputTransport/v1` 明确分开 transport_complete 和经济状态：
economic_content_validated、accounting_executed、evidence_accepted、complete、
runtime_consumable、certifiable 全部 false；returns/sr 为 null；seal_status 固定
seal_pending。旧准备入口经新宿主读取后的报告也标 seal_pending；正式 runtime
逐原 SHA 解析 sidecar，显式拒绝其中任意层的 seal_pending。caller 自报 sealed
不能补齐 B/P4/P7。真实 read_roles / reader_calls 保留失败前已发生的读取，不抹成零。
原文件、原来源回执的 SHA 和本次进程边界单独记，不写已封存标志。
边界封套为 EVO884.ExecutionInputBoundary/v1，保留原声明清单及逐角色来源回执
引用；source_acceptance=not_checked。worker_source_sha256 只标 worker 图，不能
冒充尚未完成的 C10 全链 producer 身份或正式 P4 回执。

本段没有给 worker 接受收益或给正式 runtime 放行：只允许运输输入。后续 C10
必须在 C13 推送并过工部核收后接入实际共用 D1/D2、C04/C07 及结果归属，再完成
非空收益传输与实际 P4/P7/B/来源接收。`reference_v3_evidence.py` 的正式拒绝暂未
删除。缺真实来源/权限/预算/N/发布件时继续拒绝，不能据本段准备成功升级。
新组件在 scope_proof 的独立登记已获允许；按派单仍等 C13 核收后的 head，另段
精确登记，本段不改该文件。

同一份旧冻结回执在新源码失配时必须在 reader 前拒绝；旧源码原 worktree 与原
脚本/输入仍应成功。旧件不重造、不重签，费用/oracle、N/attempt 和正式采用件不动。

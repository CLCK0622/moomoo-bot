C06 追加绑定，原 `2b2483f` 保留。EXEC-CLOSURE 正式机器 SHA 为 `7677b123fa2fe573343fad3fe3f43887c5f5d2c0fd7c12d9a1de8bc625162e1b`。只认正式发布评论 `01a19a98-d18c`；后到同名 `e3646dc3…53ec` 已撤回，测试明确拒绝，不按附件时间取件。

| 组 | C06 盘点 | 本次差量及边界 |
| --- | --- | --- |
| EA.N1 | 未计算价格、成交名义额、现金或费用；接 C04 已记账金额，peak 与阈值比较已用规范词法及精确比值 | 共同参数随 scope 必填，原账户金额不重算、不删字段；完整金额域/报价硬门在 C03/C04 接线时继续验。 |
| EA.N2 | 未撮合，无全量模型填单；RiskHistory 只观察已接受逐笔成交 | 不新增模型，不把必要 M 当成交；C05 的模型账不变成此处实际 forward 来源。 |
| EA.N3 | 未推算卖出款可花时点；observe_close 只接已核会计状态 | 不把应收、权益或未知交收升级可花。实际来源接收仍由 C09，研究金额由 C04。 |
| EA.N4 | 未推进 meta 池生命周期；C06 的持有/冷却计龄和 adopted SHA 是独立合同 | solo 不读 meta 上下文；不从 C06 初龄反推 half。20/25/50 的实际生命周期回归随 C03 实现，当前只有共同参数与拒绝测试。 |
| EA.N5 | 涉及：observe_close 账务后推进风险；advance_fold 保留同账本状态；prepare_open 锁同收盘意图 | scope 必填完整 execution_binding；snapshot/M 显式输出采用件 SHA 和参数 SHA，保留独立 C06 ruling。跨折锁意图之前必须移交新折；meta 上下文必须匹配新 fold_id 和同一正式 SHA。缺件不得借旧池，solo 原 recipe 不读池。下一开盘只认锁定意图，原 DAY/零成交/部分成交测试保留。 |

共同状态参数不合并各账本。候选、四参考、meta 测试逐个证明采用同一 EXEC-CLOSURE SHA，原 `8cd32345…7a5a` C06 绑定照旧。当前 scope 的新必填字段为 `execution_binding`，值由 `adopted_execution_binding(expected_adoption_sha256=...)` 返回；不是权威链或来源授权。C08 产品文件不变，只调整其仓内宿主夹具，原 read 签名可原样接含绑定的 risk_scope。

meta origin_context 新增必填 `fold_id` 和 `execution_closure_sha256`，仍需原 source_sha256 / signal_session / permissions；hash 自洽不能覆盖过期 fold。它只是 C06 必要 M 的上下文拒绝边界，不认证 C03 产物可见性或 C09 来源。完整编排未落地前，不宣称第 3/4/5 步均已实现。

M-01 schema 描述已按机器裁定 `03809f4527ece1012b18bb214aa23a39a7d8d52da4e573cdd57c03dc3dd13914` 去掉待确认；保留最终非负整数持仓、不是上限/差量、净订单另表。引用 v1 中文169行、v3 /gain_model/plans、D12.D1.4-D1.5；`execution.py:498` 只作 G/K 权重差，不冒充订单生成。作者回读补件 SHA `6368ddb1be04a66ae6f432c9fcfaf45feb26222e8d29c875b67221f3aed7bac5`、机器回执 `e16e1adae7543fd4029ffe65dc5399af1c123189d273a95298e855765cfa5166`。

C03/C04/C07/C13 后续直接使用该正式绑定，不设置业务占位实现。本轮无策略/参考/前向实算，不写链、安装或预算，不修改 main；独审及正式接收沿原线。

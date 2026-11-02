C05 追加绑定，基于正式采用件，不改写 `9461724`。

正式机器件 SHA `7677b123fa2fe573343fad3fe3f43887c5f5d2c0fd7c12d9a1de8bc625162e1b`，中文件 `34f25ce19dcf8687f7068b62f751c83573a858997ab11fa0096794157f3a373f`。两件原字节均从 EVO-883 正式发布附件下载后重算。草案三 SHA、缺件、缺省值、内容漂移、任何参数漂移都不能通过。参数模块只承载共同合同，不是另一份 D1/D2。

| 组 | C05 盘点 | 本次作用及边界 |
| --- | --- | --- |
| EA.N1 | 涉及：`StartupBook.execute_open` 调原 `initial_build_turnover_check` / `OrderCosts`，记启动现金、费用与 NAV；`close_session` 估值 | 必填 binding；原费用调用固定独立 Decimal(28, HALF_EVEN, -999999, 999999)，不继承调用方上下文。原七笔 fee lexeme / oracle 原字节硬门先跑。此块仍是启动账局部：完整 Decimal 现金可行性与唯一数量投影在 C03/C04 改接，`complete_account_state` 保持 null；本次不认证完整金额域已实现。 |
| EA.N2 | 涉及：启动整批接受后按全量模型记账 | 回执显式具名 `reference_full_fill_at_verified_open`，独立 training book；计划接受、计划量、模型成交量分列，`execution_verified=false`。拒绝 forward/合账 scope，不能拿此模型作真实回执。 |
| EA.N3 | 未涉及卖出款可用相位：此块只从已证 E0 买 QQQ，不生成卖出，也不把权益/应收用于买入 | 绑定保留研究现金假设与 actual-forward 原来源边界，不在本块实现卖出现金规则。 |
| EA.N4 | 未涉及衰减相位：固定 solo 启动账，无 meta 池、half、retired | 共同参数明确 20/25，solo 不继承 meta 生命周期。这里只验参数漂移拒绝；生命周期业务相位用例随 C03，不冒充当前已实跑。 |
| EA.N5 | 涉及局部先后：前收锁意图→指定开盘→当日收盘→下一个意图 | C05 入口每次重验采用件，沿用原三日状态机。无换池/跨折激活，无新 signal 选择；完整同收盘编排在 C03/C06 层。 |

EA.N1 的字节门是停止条件。仓内保存从原冻结包复制的 worksheet、suite-manifest、CF01.expected 原字节，宿主测试绑定原 SHA；不让 DUT 生成或更新 golden。七笔费用仍调用原费用模块、参数、公式、地板和 x2，跨接口保留原 canonical float lexeme。该边界是费用兼容证明，不是共享规划器验收。

本次不运行策略/参考/前向，不写权威链、不调预算/安装，不改变权限或 runtime 门。

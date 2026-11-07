B02 对 release_context v1.0.3 第 2、4 节的补段（供 v1.0.4 合入）

依据工部 01a1b812-e60f 与 01a1b818-7cf9。正式 guard.request.catalog 唯一格式沿用现有 universe/calendar_sha256/entries 消费视图；R.catalog 保留发布 payload 原字节身份，不直接作为消费视图，也不添加旧字段。zero_exposure 和九函数原逻辑不变。

共同 checker 重核 R/P/A、host 期待值及冻结 policy 后，逐件核对 FIXTURES 中原 v21 CSV、CMI guard、v21 final receipt 的 SHA 与 R 的 accepted-input manifest，并逐字节比对同一 host 的已核原件；不符或缺件先报 B.release_context_release_mismatch，不调用 derive。三件读取均逐路径、逐完整 SHA 登记。回执为 R /accepted_input_manifest/entries/0/accepted_receipt 已接受的原件，不增加新的事实来源。U64 顺序、完整 calendar 来自同一冻结 policy，REGISTERED_AT 仍为原模块常量。

随后原样调用 catalog_v21.derive(policy)，原模块一字不改。其内部原有 SHA 校验保留。仅取其 catalog 与 request.catalog 作严格规范 JSON 字节比较；任何字段不符报 B.release_context_scope_mismatch。现有消费视图只由该单一派生函数产生，没有平行实现或隐藏包装。H_C 仍为 SHA256(C(R.catalog))，H_R/H_A/H_D 原语义不变，不能以消费视图摘要替代 H_C。

派生前还将实际 policy.calendar 按冻结 common-calendar 的逐日 LF 编码重算 SHA，与 host 的 common_calendar_sha256 比较。只保留原 raw/manifest 但改动内存中的日期元组，同样在 derive 前报 scope_mismatch；不增加读取或改动日历规则。

源代码变更依据为上述工部裁定；本段及私有机制测试不代表实际 A、来源许可、独审重封或运行放行。所有新源码读数仍 seal_pending。

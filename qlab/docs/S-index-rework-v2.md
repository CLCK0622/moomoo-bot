S 第一次返工按首辅乙口径，只修改数据索引并增加迁移清单 v2，不重签 source seal，不修改产品代码、原 v1 清单、发布封套或原包。

`historical[3]` 使用 `EVO884.HistoricalSealEntry/v1` 包装，外层只含 `schema`、`status`、`historical_superseded_by_S`、`attachments_retained`、`entry`。`entry` 是 `14ebe19` 索引原 `current` 的完整 JSON 对象原始字节，保留八个键和值；内部缩进也保留，所以不得对整个索引再做自动 JSON 格式化。`historical[0..2]` 保留原始对象字节。当前 S `current` 和 `previous_index_sha256` 原值不动，后者仍指向重封前 `14ebe19` 索引，而非此次返工父头。

`attachments_retained=true` 仅记录原 seal、回执、夹具及原包继续归档可取得，不授予来源、运行或完整 N 权限，不进入内层八键对象。

`evidence/evo884-exec-reseal-v1/migration-manifest-v2.json` 是独立升版件，回指原 `migration-manifest.json` 的 SHA `55ae24cd39271dfc633d9084b09596cb9f8c9191e869a4f01149a4573ca0556e`。`data_index_changes[0]` 登记重封前索引、原 S 索引和修正索引三份原字节 SHA、修改理由、包装合同，以及原 F3b 的规范 JSON SHA 与原始对象 SHA。规范编码为 UTF-8、键排序、紧凑分隔符 `,` / `:`、ensure_ascii=false、allow_nan=false。

哈希方向为 v2→新索引→原封套→原 v1 清单。索引与封套不反向引用 v2，也不包含新索引自身 SHA；新索引 SHA 只登记在 v2。原封套的11份绑定不变，不将新升版件暗塞回已签发封套。

仓内原消费者清单（基线 `4ef96c0`）：

|位置|实际行为|兼容验证|
|---|---|---|
|`qlab/tests/dynamic_factor/test_execution_reseal.py:61`|唯一显式读取索引的可执行点；只取 current，不读取 historical|原文件原函数不改，在新索引上原样执行；另比 current 原始片段和所有非 historical 元数据|
|`qlab/qlab/dynamic_factor/README.md:139`|文档指向索引及旧 F3b 归档，没有 JSON 解析行为|原文 SHA 不变，索引及归档文件仍可解析/定位；旧 F3b 不作当前 fallback|
|`qlab/qlab/dynamic_factor/evidence/evo884-exec-reseal-v1/README.md:3`|S 文档指向唯一当前索引，没有 historical 读取逻辑|原文 SHA 不变，current 仍定位同一 source seal、B2 与原发布封套|

基线 `git grep -n -I -e current-seal-index -e historical` 全仓结果随交件保留，其他 historical 命中分列为无关的权威历史账本/诊断、资料/夹具或文字。产品 Python AST 复查未发现显式索引引用或 historical 成员读取；新测试是审计消费者，直接按此包装合同取 entry，不是新增运行入口。仓外读取方不在这份仓内扫描结论内。

兼容与字节回归在 `tests/dynamic_factor/test_seal_index_rework.py`，同时原样执行旧 S 测试及两外部门接收测试。新测试夹具分别是 `14ebe19` 与 `4ef96c0` 的原始索引副本。消费者扫描和准确 argv/实例数以本次交件实际日志为准，不把原来的 7 新 S + 7 既有接收写作14个新增实例。

原 source seal 的52件身份、N1313、attempt661、设计 N6、C12 v31/seq1386、1747B、费用与正式采用件不变。S 仍待独立复审；B 分支冻结，B/SRC_AUTH/L0继续关闭，静态索引修复不代表真实运行许可。

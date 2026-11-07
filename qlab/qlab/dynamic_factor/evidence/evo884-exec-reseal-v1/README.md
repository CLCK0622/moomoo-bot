S 的单一源码绑定发布，以已独审 R-D 的 `14ebe19f1f2929b92379f4d3386a1a3c99cfe774` 为来源；待 EVO-887 独立 S 审查。

`binding-publication.json` 一次绑定本目录11份 JSON，`evidence/current-seal-index.json` 是唯一当前入口。`static-seal.json` 使用现有 `reference_evidence.seal_static/verify_seal` 合同，记录52项当前源身份并精确匹配静态证明。`source-inventory.json` 补充216个产品文件及C13文档的逐字节身份，包含共用执行模块及14ebe19的说明；清单不是完整读取覆盖证明。`collection.json` 使用原 C11 采集器，记录实际入口/共享模块、DAG、范围和已有合成 book 的 B 覆盖。47行既有读取及动态、未固定 SHA 的覆盖缺口照旧保留。

迁移清单以营缮原合稿 `056fae0f68e9d8abbdd2cebceb9450907b825ce758ef5a64c8b9d367008dff47` 为输入，9条要求行和原有2条 C13 补充行回填实际新 SHA、接收 artifact 与精确 JSON pointer。旧值、原观察与正式接受范围不倒写。B分支9行没有并入。

B2仍为不可用。本次 manifest 投影只引用既有采用件 `fixtures/disposition/EVO883-EVO891-disposition-draft-v1.json` 的 `/VTI_disposition/formal_readout_current`，绑定缺少已接受完整冻结历史读出的事实及当前隔离源码；没有将旧 `UNIT_EVENT_EVIDENCE_MISSING` 合成夹具升级为真实来源，也没有重算金额、TR、NAV或删减日期。具体来源及范围见 `B2-provenance.json`。

三类身份分别核验：旧源码 worktree 配原 noncash 回执仍为306调用/238接受/reader34；新源码配旧参考 seal/B2 源码绑定在 reader 前拒绝；新源码配本次新静态绑定正向通过。noncash模块仍为原字节，原noncash回执不因无关模块重封而失效，不将其与已改变源码的参考/B2封套混淆。

所有旧 seal、原回执和旧夹具保持原字节。当前索引的替换仅发生在仓内发布材料层，不部署、不安装权威件、不创建 D、不写链或外锚、不调用预算接口、不启动真实策略/参考/前向。`seal_pending` 诊断结果不被改标或接入正式回执；静态源字节绑定通过不等于真实输入、生产完整 N 或运行许可。

账面1313、attempt661、C12 v31/seq1386/设计归档引用6以及1747B正式 projection 原件均不动。B、SRC/AUTH、L0关闭。原两 B 副本、读取覆盖、私有x1及根cwd六旧CLI等限定不销项。

永久限定按首辅甲和R-D照录：

> C13 DUT 在 oracle 注入的反事实前收快照下，与 4049B oracle 逐字节一致；owned 前史与该 oracle 的同源接续无法证明，因为 oracle 按构造就没有前史。

4049B是完整 adapter 的原独立观察基准，不是一份新发布的完整 owned 前史 golden；正式1747B只对应 projection。另一book的 owned 夹具覆盖与该 oracle 的同源接续分列。

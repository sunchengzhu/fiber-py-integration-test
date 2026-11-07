# F2 SDK 负向校验快测方案（独立补充；实现完成）

范围：新增原 F2 五项负向检查的 **SDK 层快速补充**，整组执行上限 300 秒；保留原 `TestTlcRefundAdapter` 及其 skip，不替代或宣称完成原真实链/adapter 联合资格。设计复审已关闭 B1，用户已授权进入实现；按 G2 首例门禁确认 F2-02 后，已完成其余五条并执行整组快测。未启动节点或四小时长测；真实链/adapter 资格仍由旧 skip 类保留为缺口。

固定依据：集成 head `d45530e0cc5c194257ef48d437a9df1805b71d34`；工作区 `/Users/sunchengzhu/project/fiber-py-integration-test/tmp/lsp-p0-1` 的 HEAD 为 `0955f5bca08ad9d86298ffe67c054e8462d9d1eb`，两者代码树均为 `c92f0209b0eab6cb68075c77629754818b0e6ef1`。产品固定 `56c761c45c271c086b05c8d5ea3e033448f5fdf8`，本地源码为 `/Users/sunchengzhu/project/fiber-py-integration-test/download/fiber/source-pr-1623-56c761c4`。方案文件与反馈是本轮新增文档，不属于上述固定 tree。

源码入口：[原 F2 skip 类](/Users/sunchengzhu/project/fiber-py-integration-test/tmp/lsp-p0-1/test_cases/fiber/devnet/lsp_nightly/test_tlc_timeout_refund.py:813)、[退款评审](/Users/sunchengzhu/project/fiber-py-integration-test/tmp/lsp-p0-1/reviews/lsp/tlc-timeout-refund.md:209)、[公开 SDK 准备入口](/Users/sunchengzhu/project/fiber-py-integration-test/download/fiber/source-pr-1623-56c761c4/crates/fiber-lsp-sdk/src/signer.rs:1008)、[onchain 校验](/Users/sunchengzhu/project/fiber-py-integration-test/download/fiber/source-pr-1623-56c761c4/crates/fiber-lsp-sdk/src/onchain.rs:62)、[上游无等待 timeout 测试](/Users/sunchengzhu/project/fiber-py-integration-test/download/fiber/source-pr-1623-56c761c4/crates/fiber-lsp-sdk/src/commitment_tests.rs:2260)。外部 reviewer 应按上述固定 SHA 核对，不能用另一个工作区的最新文件替代。

## 先看结论

原 F2 同时包含真实链/SDK 联合准备和负向检查。本方案只补“退款签名材料有错误时，SDK 能否拒绝”这一层：使用预先设定的到期状态，直接调用真实 SDK，无需重新开通道并等待四小时。原真实链资格继续明确为未完成；保留旧 skip 类不会使它在本批运行。

采用 **Python 调度和断言 + 一个独立 Rust 辅助程序 + 固定的内存链状态**。辅助程序通过 SDK 公开接口构造经过 SDK 验证的本地历史；先证明有效请求可以通过，再逐项修改输入并验证拒绝。没有真实节点、RPC、VM 或墙钟修改。

- 五项负向是 `wrong_tlc_index/hash/amount/direction/residual`，每项仍单独报告结果。
- 20 字节与 32 字节 payment hash 两种 witness 格式各准备一次基线；共 10 次负向调用、4 次正向调用（每种格式组前、组后各一次）。
- 已有正确预编译产物时，正常执行目标为 60 秒内，**300 秒为包含启动、检查、收尾的硬上限**。60 秒是设计目标，尚无实测结果。
- 前置检查拟分配 15 秒预算；缺少产物、摘要不符或到时仍未完成检查均报环境失败，不悄悄延长。15 秒尚未实测，是本方案的待确认执行预算，不是已有产品/框架契约。运行入口不编译、不下载、不自动重试；首次构建是单独、显式的准备工作。
- SDK 快测通过只证明本地 SDK 校验。这不补齐独立 TLC 退款的真实链端到端覆盖，也不等于原含 TLC 链/SDK 联合资格已完成。
- 本文 `LSP-REFUND-F2-01～06` 是上一版已分配给 SDK 快测及快速入口的六个新稳定 ID，继续保留。旧 skip 类没有这些 ID 或映射，因此无需改名或新增一个“已测/待办”占位 ID；通过标题、入口和报告明确区分两种范围。

## Spec

### SPEC-01：先有有效正向基线，负向之后基线仍可用
Condition: 使用固定 SDK、无 UDT 的单笔 A→T 出站 1 CKB TLC、无 preimage；两种 witness 格式分别建立已验证的 remote recovery record 和已经成熟的内存链状态。
Expected: 真实 `prepare_onchain` 接受合法独立 TLC 退款候选；返回的待签内容与输入一致；负向组前后均成功，所有校验调用均不改变基线 signer store。
Observable: SDK 返回成功、待签交易及 key purpose；组前后 store 摘要、原始输入与 Python 独立解码结果。
Basis: 既有退款评审的正向准备要求；固定产品 `signer.rs:1008` 的公开入口、`commitment_tests.rs:2260` 的无等待 timeout 测试构造方式。
Source: explicit
Testing: required

### SPEC-02：TLC 签名使用创建时的密钥编号
Condition: 有效基线中的目标 TLC 创建索引为 k，witness 数组位置为 0；仅把请求的 `Tlc.commitment_number` 改为 k+1。
Expected: SDK 在 TLC 签名密钥校验处拒绝，store 不变；恢复原请求后仍可通过。
Observable: `prepare_onchain` 的错误类型、固定版本拒绝原因，以及输入差异和 store 前后摘要。
Basis: 退款评审的创建索引要求；固定产品 `onchain.rs:204–214`。
Source: explicit
Testing: required

### SPEC-03：已承诺的付款标识、金额和方向不可被篡改
Condition: 有效基线的原 record、live input、授权和内存链数据保持不变；分别仅修改输入 witness 中的 payment hash、金额或方向位。
Expected: 每个变体均被 SDK 的 witness 与 live input 承诺绑定校验拒绝，store 不变；不声称走到了更后的字段语义校验。
Observable: 三个具名变体各自的字节差异、SDK 错误及 store 前后摘要。
Basis: 退款评审的原 TLC 完整性要求；固定产品 `onchain.rs:126–128` 的最早拒绝点。
Source: explicit
Testing: required

### SPEC-04：退款后的剩余状态必须精确匹配
Condition: 有效基线的输入 witness、金额、费用、授权目的地址均不变；仅篡改后继输出 lock args 中的剩余状态 hash。
Expected: SDK 因该输出无法匹配合法后继且不属于批准目的地址而拒绝，store 不变；不把此结果扩写成所有残余金额错误均已验证。
Observable: 输出差异、SDK 输出授权/后继匹配层的拒绝及 store 前后摘要。
Basis: 退款评审的精确后继要求；固定产品 `onchain.rs:327–346`。
Source: explicit
Testing: required

### SPEC-05：五分钟入口不能隐式变成构建或长测
Condition: 执行快速入口，但所需预编译辅助程序缺失，或其版本、源码、锁文件、二进制摘要不匹配。
Expected: 15 秒内以非零退出报告环境失败；不执行 SDK 批次，不编译、下载、启动节点或转入原退款生命周期。
Observable: 入口退出码、失败原因、实际子命令清单和耗时。
Basis: 用户“整组控制在 5 分钟内，不要再启动四小时长测”；本方案采用准备与执行显式分离。
Source: inference
Testing: required

### SPEC-06：整组共享一个截止时间，超时也须收尾
Condition: 运行一次完整快速批次，或本批自有子进程卡住；从入口开始计时，不因参数、错误、重试或收尾重新计时。
Expected: 整组在 300 秒内结束；超时为非零退出且不计通过，停止并回收本批子进程，保留已经流式写出的结果；不影响无关进程。
Observable: 入口 monotonic 起止、每阶段耗时、退出码、被管理的 PID/进程组及收尾结果。
Basis: 用户本轮五分钟上限；仓库对有界等待和本批进程收尾的要求。
Source: explicit
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- F2 真实 SDK 快速校验（两种 witness 格式使用同一组行为）
  - 有效请求组前组后均通过且状态不变：LSP-REFUND-F2-01 [primary] -> SPEC-01
  - 五项负向
    - 错误 TLC 创建密钥编号：LSP-REFUND-F2-02 [primary] -> SPEC-02
    - hash、金额、方向三个独立变体均被承诺绑定拒绝：LSP-REFUND-F2-03 [primary] -> SPEC-03
    - 错误后继残余状态：LSP-REFUND-F2-04 [primary] -> SPEC-04
- 快速执行入口
  - 缺产物或版本摘要不符时快速失败：LSP-REFUND-F2-05 [primary] -> SPEC-05
  - 整批截止、超时留证与自有进程清理：LSP-REFUND-F2-06 [primary] -> SPEC-06
<!-- TEST-TREE-END -->

## 用例

以下六行是复审通过并获准实施的完整设计。本轮只为 F2-02 增加映射；复选框不表示整组通过，ID、预期和优先级未改变。hash/amount/direction 的操作与最早拒绝依据相同，合为一个参数化行为行，但三个具名结果均必须存在，不减少五项检查。F2-05 中的 15 秒是拟议入口预算，首次实现须给出测量结果后才能判断是否满足。

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-REFUND-F2-01` | - [x] 对两种 witness 格式分别建立 A→T 单笔 1 CKB、无 preimage、已到期的有效本地历史，在五项负向前后调用 SDK 准备合法 TLC 退款 | 组前组后均成功，待签交易和密钥用途与有效输入一致，校验不改变 signer store | 用无效基线造成全部负向错误通过，或变体污染后续检查 | P0 |
| `LSP-REFUND-F2-02` | - [x] 对已通过正向的退款候选，仅把 TLC 签名密钥创建编号改为另一编号，其余输入和链状态不变 | SDK 在 TLC 签名密钥校验处拒绝，signer store 不变 | 用当前承诺号或数组位置替代该 TLC 的创建编号 | P1 |
| `LSP-REFUND-F2-03` | - [x] 从同一已通过正向的退款候选分别仅篡改 witness 中的付款 hash、金额、方向位，每次恢复基线，原 live input 和授权不变 | 三个变体分别在 witness 与 live input 承诺绑定校验处被拒绝，signer store 不变 | 接受被篡改的已承诺付款信息，或漏跑其中一个变体 | P1 |
| `LSP-REFUND-F2-04` | - [x] 对已通过正向的退款候选，仅篡改后继输出 lock 的残余状态 hash，输入、费用、容量及授权目的地址不变 | SDK 在后继输出匹配及目的地址授权校验处拒绝，signer store 不变 | 退款后接受不符合原状态转换的剩余付款记录 | P1 |
| `LSP-REFUND-F2-05` | - [x] 启动快速批次时，预编译辅助程序缺失或版本、源码、锁文件、二进制摘要不匹配 | 15 秒内非零退出并说明环境原因，不执行 SDK 检查、编译、下载或长测 | 把准备工作或隐式长测藏进五分钟入口，或运行错误版本 | P1 |
| `LSP-REFUND-F2-06` | - [x] 执行整组快速检查，并用缩短测试截止的自有假子进程检验超时收尾；所有阶段共用入口截止 | 正常批次及超时收尾均受 300 秒总上限约束；超时非零退出、保留结果并回收本批进程，不终止无关进程 | 每项重新计时导致整组超时，或父进程退出后遗留任务 | P1 |
<!-- TEST-CASES-END -->

## 验证设计与实现建议

### 1. 保留 Python 用例，拆掉四小时准备依赖

新增的 Python 测试不继承 `FiberTest`、`_WatchtowerBase` 或 `_RefundBase`，不导入会要求节点 bundle 的 `_lsp_test`。它只读取快速 bundle manifest、启动一个本地辅助程序、校验结果。

Rust 辅助程序是独立可执行文件 `lsp-refund-f2-fast`，仅依赖固定产品 SDK 的公开接口；不调用 `_watchtower_chain::process`，不启动 Agent 的 RPC/WS 事件循环。选择独立文件可避免改变共享 `_sdk_driver.rs` 的源码摘要、影响已有自然时间 bundle。

完整实施涉及位置及处理方式（均在指定工作区；当前首例进度见文末）：

| 文件 | 变化 |
| --- | --- |
| `test_cases/fiber/devnet/lsp_nightly/test_tlc_refund_adapter_fast.py` | 新增 Python 快测；一个 SDK 批次覆盖 F2-01～04，逐项输出所有参数结果 |
| `test_cases/fiber/devnet/lsp_nightly/_tlc_refund_adapter_fast.rs` | 新增独立 SDK 辅助程序：构造基线、固定内存链、执行具名变体并导出原始结果 |
| `scripts/build_lsp_test_binaries.py` | 新增显式的 F2-only 构建分支，单独生成快速 bundle，不构建 FNN、不覆盖旧 bundle；其余构建路径保持原行为 |
| `scripts/run_lsp_refund_f2_fast.py` | 新增快速入口，固定选择器、单一 300 秒截止、流式日志及自有进程组清理 |
| `test_cases/framework/test_lsp_refund_f2_runner.py` | 入口的确定性检查，对应 F2-05/06；用临时文件和测试自有短命进程验证，无节点依赖 |
| `test_cases/fiber/devnet/lsp_nightly/test_tlc_timeout_refund.py` | 本批不修改；保留原 `TestTlcRefundAdapter` 和 skip，继续表示真实链/adapter 联合资格未完成；主退款生命周期及 LSP-REFUND-01～03 同样保留 |
| `test_cases/fiber/devnet/lsp_nightly/README.md`、退款评审的说明段落 | 增补快测入口及证明层级；旧 VM/长测历史保留为历史，不宣称已补齐真实链资格 |

新的 SDK 用例与入口自检均保留 `manual_nightly` 默认排除；不加入普通 Makefile、CI 或定时回归。本次“快速”只改变耗时和调用路径，不默默改变既有手动运行策略。

统一入口：`venv/bin/python scripts/run_lsp_refund_f2_fast.py --bundle <快速bundle>`。当前 G2 版本只选择 SDK 首例文件；尚未加入入口自检文件，不能计作整组完成。

完整实现时入口内部只调用两个精确文件选择器，不接受目录或任意 selector；为了沿用现有 deselect 机制，内部使用 `--run-lsp-refund-nightly`，但目标仅为新快测文件与入口自检文件。显式传入 `-o addopts=` 并清空子进程的 `PYTEST_ADDOPTS`，避免项目默认 HTML 输出覆盖 `report/report.html`，也避免环境追加选择器或重试参数；JUnit 写本批新建输出目录。不得调用旧 `test_hold_payment_timeout_refund`，不得使用整个 `lsp_nightly/` 目录作为选择器。单独运行底层 pytest/二进制属于诊断，不可当作“整组五分钟”验收结果。

### 2. 有效材料通过公开 SDK 生成

每个 feature 格式建立一份语义输入固定、可重新生成的基线。`create_channel()` 内部使用随机 channel ID，固定 root seed 不保证不同运行的交易字节/hash 相同；每次保存实际公开输入与结果以便核对，不承诺字节级历史回放。

1. 使用公开测试 seed 和 `MemoryStore` 创建 `RootSigner`、channel signer；通过 `approve_opening` 批准开通，通过 `authorize_payment` 批准 SHA-256、1 CKB、outbound 付款。
2. 参考固定产品 `commitment_tests.rs:26–298` 的公开接口调用方式，构造空 TLC 的开通承诺和下一版单 TLC 承诺；使用 `CommitmentContext`、`OwnedSettlementBinding`、`prepare_commitment`、`sign_commitment` 生成 SDK 验证过的历史，再读取 `recovery_records()`。不导入私有 `Fixture`，不直接伪造 signer store。
3. 固定 `for_remote=true`，匹配 A 付款、T 强关的视角。参考构造辅助函数的入参 version=0/1，内部先加 1，因此对应 nonce/链上承诺编号为 1/2。保存 TLC 创建时的身份、实际派生索引和公钥，再与公开 record 的 `local_key_commitment_number` 及 witness 数组位置交叉核对；请求的 k 取自这段实际创建历史。本组材料预期得到 k=1、数组位置=0、最新 record.version=2，常量只用于核对构造是否符合设计，不能代替历史推导，也不能用最新承诺号或数组下标生成 k。
4. 准备 unsigned 独立 TLC 退款候选：无 preimage，`key_purpose=Tlc{k}`，包含实际 expiry 的 absolute timestamp input、满足相对延迟的 commitment input、正确后继和批准目的地址。
5. 内存 `FixtureChain` 只提供列入基线的 cell/outpoint、ancestor 关系、输入成熟条件和 median；median 固定为严格晚于 E 的整秒。未知 outpoint/关系拒绝。各负向之间不修改这些可信输入，不更改系统时间。
6. 调用真实 `ChannelSigner::prepare_onchain`；成功后导出待签交易和公开 review 信息，再开始负向。每项从原内容的独立拷贝出发；每次前后比较 `MemoryStore::snapshot()`，组末再次准备原合法请求。

准备历史会执行**本地 commitment signing**。F2 校验阶段只调用 `prepare_onchain`，不调用 `sign_onchain`、签名提交或广播；不能笼统声称整个程序完全不签名。

采用合成有效历史而不是回放 `natural5` 的已花费 UTXO，可以消除旧 report、数据库、VM 和真实链状态依赖。固定产品已有无等待的 `TestChain` / `DescendantChain` 示例，但这些链响应不构成真实 CKB 合约或 canonical/live 证明。

### 3. 五项变异及真实拒绝层

这里的 index 特指 TLC 创建密钥编号，不是 witness 数组下标。每次只变更表内内容；原 record、授权和内存链状态全部保持不变。

| 具名检查 | 唯一变异 | 固定 56c 的预期拒绝依据 |
| --- | --- | --- |
| `wrong_tlc_index` | `key_purpose.Tlc.commitment_number: k → k+1` | `onchain.rs:210–214`：`wrong TLC signing key` |
| `wrong_tlc_hash` | 翻转 TLC entry 已编码 hash 区间内一个字节，两种格式均选实际编码区间 | `onchain.rs:126–128`：`settlement witness is not committed by live input` |
| `wrong_tlc_amount` | 将 entry 的 16 字节小端金额 Q 改为 Q+1，其他字节不变 | 同上，witness 承诺绑定拒绝 |
| `wrong_tlc_direction` | 仅翻转 entry 首字节的方向位，保留 hash 算法位 | 同上，witness 承诺绑定拒绝 |
| `wrong_tlc_residual` | 翻转后继输出 lock args 的 `[36:56]` 状态 hash 中一个字节 | `onchain.rs:341–346`：后继不匹配后报 `unapproved on-chain destination` |

hash/amount/direction 被较早的承诺绑定检查挡住是本方案真实覆盖的行为。不得为了进入更深分支而同步篡改可信 source lock、批准历史或放开链校验。residual 本次只覆盖剩余状态 hash，不能扩写为所有容量、重复 TLC 或后继关系的负向覆盖。

断言固定 SDK 错误类型与对应原因，panic、I/O 错误、超时、缺少正向材料均不能算负向通过。原因文字仅用于固定版本的拒绝层归因，不作为产品对外错误文案契约；升级 SDK 时重新核对，不能退化为“任意失败都通过”。

### 4. 独立判断依据与可观察结果

Rust 返回原始候选/变体、批准输入、公开 record、实际 SDK 结果、store 前后摘要和本次调用的链接口记录；Python 校验具名结果集合完整且无重复，并自行检查：

负向结果键固定为 `(feature, check_name)`，必须恰好等于两种格式与五个 `wrong_tlc_*` 名称的笛卡尔积，共 10 项；另有两种格式各自的 `positive_before/positive_after`，共 4 项。任何缺项、重复、正向调用未成功，或负向调用未得到指定拒绝结果，均使整组失败。尤其 hash、amount、direction 必须各有独立原始输入、错误与耗时，报告不得只显示一条 F2-03 汇总 passed。

- 两种格式的 entry 长度分别为 85/97，hash 长度为 20/32；原完整 H、Q=1 CKB、SHA-256、A outbound、E、k 与预设一致，record 视角为 remote。
- 逐项字节差异只落在本方案规定位置；拒绝结果不是 helper 自报的一个 `passed=true`。
- 正向 request 与返回待签内容一致；出站独立退款的容量关系由 Python 整数计算核对：`M_A+M_T+Q=C_fund`、`C0=C_fund−F_close`、`R=C0−Q`、`O=S+Q−F_spend`。Payout Q、sponsor S、授权 fee 与剩余容量分别核对。
- 每次校验前后 signer store 不变；组末基线仍可准备成功。保存摘要用于对比，不输出 seed 派生出的私钥、完整秘密 store 或 nonce 私有材料。
- chain 调用只来自固定内存实现；导出所查询的 outpoint、lineage 参数、median 和成熟条件，区分 SDK 错误与辅助程序错误。

独立 oracle 是 Python 对固定输入的金额计算、witness 字节解码、变异位置和结果集合检查；SDK 正反调用是真实被测入口。内存链只是明确受控的前提，不能拿其返回值当作真实链验证结果。

### 5. 300 秒预算、构建与退出方式

整组入口记录唯一 `t0=monotonic()`；case、feature 参数、子进程和诊断共用该截止。没有自动重试。

| 从 t0 起 | 上限与动作 |
| --- | --- |
| 0～15 秒 | 检查版本、manifest、辅助源码/锁/二进制摘要与资源；缺失或不符直接环境失败，不编译 |
| 15～270 秒 | pytest 收集、入口短自检、两份 SDK 基线及全部正负检查；子调用的 timeout 不超过剩余预算 |
| 第 270 秒 | 尚未结束则记录超时，向本批进程组发终止信号 |
| 第 275 秒 | 仍未退出则强制终止本批进程组并回收；不按端口或宽泛进程名清理 |
| 275～295 秒 | 核实自有进程退出，完成已流式写出的原始日志与结果摘要；不做大目录复制 |
| 不迟于第 300 秒 | 返回退出码；成功为 0，检查/环境失败为非零，超时使用 124；不能因部分检查完成而返回成功 |

F2-06 的监督器自检使用测试自有的“阻塞子进程及其子进程”，把同一监督函数的时间参数缩短到约 1 秒验证 TERM/KILL/回收。故障子进程及其子进程忽略 TERM，确保实际经过 KILL 分支，并检查退出码 124、已落盘日志及回收结果；它不等待真实 300 秒，不 patch 产品或系统时间。另以确定性的截止计算检查普通入口确实传入 270/275/300 秒阈值，且没有放大预算选项。自检另建一个不属于受测子进程组的对照进程，验证受测监督器不会误杀它，检查后主动回收。

自检所创建的进程组和对照进程也属于本批资源：创建后立即向外层登记 PID/PGID，内层 `finally` 正常清理，外层在总超时兜底回收登记的资源，避免 pytest 超时留下另一个 session 的孤儿进程。真正与本批无关的进程不登记、不操作。

构建单独使用现有脚本新增的 F2-only 分支，生成独立 crate/binary，仅链接固定 SDK 及构造材料所需依赖；例如直接 `musig2` 依赖采用与产品一致的版本。产品源码与 `Cargo.lock` 不改，辅助 crate 使用自己的冻结锁文件和摘要，不把新增依赖后的锁文件谎称为旧 driver 锁。

新 manifest 至少包含产品完整 SHA、产品锁摘要、辅助源码摘要、辅助锁摘要、二进制摘要与实际构建命令。运行前逐项匹配，构建输出放新目录。已有自然时间 bundle、历史 report 和源快照不覆盖、不清理。构建复用一份缓存，仍遵守仓库 8 GiB 可用空间和默认 2 GiB 新增空间约束；超出预算先停止，不隐式构建整套 FNN。

每批只保存一份小型输出：原始 stdout/stderr、实际输入与具名结果 JSON、JUnit（若 pytest 正常生成）、总退出码、monotonic 阶段耗时和清理结果。超时可能没有完整 JUnit，以父进程超时结果和已落盘日志为准；不能伪造完整成功报告。

实施后的验收报告须分别列出：正常完整批次实际耗时、manifest/各摘要检查耗时、14 个 SDK 具名结果、缩短截止的故障注入所用真实阈值与 TERM/KILL/退出 124/落盘/回收证据，以及普通入口 270/275/300 秒配置检查。缩短截止的进程实测证明收尾分支，配置检查证明生产阈值接线，**二者不等于已经真实等待到第 270/275 秒**。若 reviewer 仍要求后者，保留为独立监督器边界验证待办；不能声称 N3 的这部分已满足，也不在本批五分钟之外自动追加另一轮故障等待。当前方案和本轮文档修改均不启动这种运行。

## 覆盖边界与迁移顺序

快测覆盖：固定 SDK 的合法独立 TLC 请求准备、创建密钥编号、三个已承诺字段的防篡改、后继状态 hash，以及五分钟入口。

本批不覆盖：真实四小时成熟、真实 UTXO/祖先/合约执行、FNN watchtower 扫描、真实签名 Applied/广播、最终链资金及业务状态；也不验证 `_watchtower_chain::process` 的单 TLC 模式隔离或 `diagnose` 分支一致性。上述 F1 非阻塞项保留，不顺带修改。

现有自然时间证据仍只支持 `T-then-A-sweep`。这里合成的独立 Tlc 候选即使通过，也不能把真实独立退款分支标成已取得。原 `TestTlcRefundAdapter` 的真实链/SDK 联合准备资格继续由旧类及原评审保留为缺口，不因 SDK 快测通过而删除、解除 skip、改变口径或记为通过。本批没有授权运行原长测。

批准后的最小实施顺序：

1. 先实现有效基线及对应 Python 断言，确认通过的是上述真实 SDK 路径、无节点依赖且有可读证据。
2. 再加入五项变体和统一预算，执行一次有界快速批次；环境失败、断言失败、超时分别报告，不扩成四小时补跑。
3. 所有快速项实际通过后，只同步本文件映射、README 与 SDK 快测结果；保留旧 `TestTlcRefundAdapter` 及 skip，不改 LSP-REFUND-01～03 的预期或映射。将来若要重定义原 F2 或删除旧类，必须另有明确范围决定，不能把本方案批准当成该动作的授权。

## 外部 review 意见处理

依据：[f2-fast-plan-review-2026-11-07.md](/Users/sunchengzhu/project/fiber-py-integration-test/docs/analysis/f2-fast-plan-review-2026-11-07.md)。外部 review 文件保持原样；本节记录方案修订，不宣称外部 reviewer 已确认修订。

- **B1，采纳**：原方案虽写明 SDK 层边界，仍安排自动删除旧 skip 类，迁移决定不充分。现选择保留旧 F2、独立补充 SDK 快测的路径，取消所有删除/替代动作。旧类原本未执行，所以问题是保留范围与验收口径，不是丢失已经通过的结果。原类无上述六个新 ID 的映射，保留稳定 ID 即可区分，无需重命名或增加占位用例。
- **N1，采纳具名验收要求**：F2-03 仍合并同一拒绝依据的三个参数；每种格式的三个结果独立验收，任何一个缺失均失败，不以汇总 passed 代替。
- **N2，澄清**：15 秒仍是待评审的前置执行预算，不是已证明的耗时或产品契约。首次实施必须测量，超预算报告失败，不自行改成宽松预算。
- **N3，部分采纳并保留边界**：要求实际正常组耗时与真实缩短截止故障注入证据；不把配置值或短自检冒充真实 270/275 秒边界实测。后者未执行、也不自动追加，是否需专项验证仍交 reviewer 判断。
- **N4，采纳**：k 从实际 TLC 创建历史推导，并与 record、公钥和 witness 交叉核对；1/0/2 仅为该材料的预期值。
- **N5/N6，维持明确缺口**：F1 模式隔离与 diagnose 一致性不在本批；residual 仅覆盖后继状态 hash，不扩写为所有资金/残余错误覆盖。

## 设计评审问题（已复审）

1. 保留旧 F2 skip 类并新增独立 SDK 快测后，是否已解决 B1 的范围替代问题？
2. 五项变异是否只改变指定内容，正向基线和拒绝层是否能排除“材料本来就无效”的错误通过？
3. 两种格式、remote 视角、SHA-256 和 1 CKB 输入是否足以覆盖本批 F2，而没有悄悄扩大到 UDT/多 TLC？
4. 15 秒前置失败、270 秒开始收尾、300 秒总截止是否可执行？实际正常批次、缩短截止进程故障注入及阈值配置检查是否足够，还是必须另行验证真实 270/275 秒边界？
5. 是否需要调整上述六条待确认用例？请引用本文件稳定 ID，并区分 blocking 与 non-blocking。

## 设计阶段检查记录（历史）

当时仅核对文档、固定源码和设计/映射关系；未实现、编译或执行 F2，也未启动四小时测试。自动化运行时长仍未知。

- `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test/tmp/lsp-p0-1 --review reviews/lsp/tlc-refund-f2-fast-plan.md`：`cases: 6`，退出 0；提示 SPEC-05 的准备/执行分离方案需要人工确认，这也是本次方案评审内容。
- 在指定工作区执行 `python3 scripts/check_test_map.py`：`review cases: 144`、`automated cases: 132`，退出 1。六条 F2 行均未映射，无重复 ID；非零来自既有孤儿映射 `PMP-01～05、SETTLE-01`，没有跨范围修正。
- `git diff --check`：退出 0；新文档另检查 UTF-8、六行未勾选复选框与尾随空白。检查器不证明 SDK 行为或实际耗时。

首轮内部独立设计审阅由子代理 `/root/f2_plan_review` 以用户原始要求、本文及固定源码开展，未继承作者会话；当时结论为无 blocking，并落实随机材料、编号、报告隔离及进程收尾建议。该轮遗漏了旧 F2 删除决定的范围问题，不能用于否定外部 B1。此次按外部意见修订保留范围，并保留 N3 的真实边界未实测说明；当时修订不代表用户或外部 reviewer 已确认。随后外部复审关闭 B1，用户明确授权实施；下述首例证据不替代整组及真实链测试。

## G2/G3 实现与实测

本轮仅实现 `LSP-REFUND-F2-02`：两种 witness 格式各执行合法请求、错误创建密钥编号、恢复合法请求，共六次真实 SDK `prepare_onchain`。创建编号 k 从前一条真实 SDK recovery record 推导为 1，witness 位置为 0，最新 record.version 为 2。Python 独立解码 witness、核算退款容量、核对唯一输入差异、精确 SDK 拒绝原因和 signer store 不变。

- [Python 首例](../../test_cases/fiber/devnet/lsp_nightly/test_tlc_refund_adapter_fast.py)、[Rust SDK helper](../../test_cases/fiber/devnet/lsp_nightly/_tlc_refund_adapter_fast.rs)、[统一执行入口](../../scripts/run_lsp_refund_f2_fast.py)、[独立构建分支](../../scripts/build_lsp_test_binaries.py)。实际路径均位于指定工作区，旧 F2、共享 adapter 和自然退款测试未改。
- [最终构建 manifest](../../download/fiber/pr-1623-56c761c-f2-g2-r2/build.json)：首次离线构建 44.508 秒；修复 helper 的 SDK 错误原因前缀后，复用同一缓存重建 1.100 秒。两次构建退出 0，未下载或构建 FNN；[首次日志](../../report/lsp-refund-f2-g2-build/build.log)及[重建日志](../../report/lsp-refund-f2-g2-build/build-r2.log)保留。构建前后空闲约 14.42→14.04 GiB，新增约 386 MiB，未触及 8 GiB/2 GiB 限制。
- [原生执行凭据](../../reports/lsp-refund-f2-g2/execution.json)及[JUnit](../../reports/lsp-refund-f2-g2/native-results.xml)：`1 passed in 0.66s`，原生命令及 wrapper 均退出 0，声明输入未漂移。通过 skill 的 `run_with_evidence.py --junit --timeout 310` 调用下面的统一入口；310 秒仅是外围取证兜底，入口本身仍有 300 秒限制。完整实际 argv、固定产品身份和输入摘要见凭据。

```bash
# cwd: /Users/sunchengzhu/project/fiber-py-integration-test/tmp/lsp-p0-1
# 已执行；输出目录和 JUnit 必须不存在，复跑须换新路径。
venv/bin/python scripts/run_lsp_refund_f2_fast.py \
  --bundle download/fiber/pr-1623-56c761c-f2-g2-r2 \
  --output report/lsp-refund-f2-g2 \
  --junitxml reports/lsp-refund-f2-g2/native-results.xml
```

[入口结果](../../report/lsp-refund-f2-g2/result.json)：从入口 t0 到收尾 **0.896 秒**，前置检查 **0.023 秒**，正常退出 0，自有进程组无残留。[阶段日志](../../report/lsp-refund-f2-g2/supervisor.jsonl)逐项记录 Git/manifest 摘要校验耗时。[原始 SDK 结果](../../report/lsp-refund-f2-g2/sdk-results.jsonl)保存两份实际基线、六个具名调用及完成记录；两次错误均为 `InvalidContent("commitment validation: wrong TLC signing key")`，四次正向返回原候选，每次 store 前后相同。这里没有发生 TERM/KILL，不能用这次成功运行证明超时回收。

实现静态复核由 `/root/review_funds` 完成：发现 Python 公钥字段名和 Rust 错误原因前缀不一致，已修复并按最终源码及原始运行证据关闭；无其余 blocking。此复核与原外部设计复审分开，不宣称完成整组独立覆盖验收。

G2 首例阶段仅 F2-02 有映射；G3 已补齐 F2-01、F2-03、F2-04、F2-05、F2-06，当前六条均有映射。真实 270/275 秒边界仍未实测；旧 `TestTlcRefundAdapter` 保持 skip，真实链资格缺口不变。

最终静态检查：`check_test_design.py --root . --review reviews/lsp/tlc-refund-f2-fast-plan.md` 返回 `cases: 6`、退出 0，仍对 inference 类型的 SPEC-05 输出人工决策提示；15 秒预算已随本批设计获准实施。`python3 scripts/check_test_map.py` 返回 `review cases: 144 / automated cases: 133`、退出 1，非零仍来自既有孤儿 `PMP-01～05、SETTLE-01`，没有新增孤儿或重复 ID；该数值仅表示映射。默认 `pytest -o addopts= --collect-only -q <首例文件>` 被 deselect，退出 5（无选中用例），[原始日志](../../report/lsp-refund-f2-g2/default-collection.log)保留；未误入日常回归。`git diff --check`、Python AST、本文及 README 相对链接和新增文件空白检查均通过，固定产品工作区仍干净。

按 [ai-test-agent 的 G2 门禁](/Users/sunchengzhu/project/ai-test-agent/references/workflow-gates.md)，首例实现与实测完成后停在实现标准确认；确认后再补齐其余五条，无需逐条审批。

## G3 整组实现与实测（2026-11-08）

用户确认 F2-02 实现标准后，已在同一工作区补齐其余四项 SDK 变体和两项入口自检；未启动四小时退款、VM 或真实节点。旧 `TestTlcRefundAdapter` 仍保持 skip。

### 实现

- SDK helper 扩展为两种 witness 格式 × 七次调用：
  - `positive_before`
  - `wrong_tlc_index`
  - `wrong_tlc_hash`
  - `wrong_tlc_amount`
  - `wrong_tlc_direction`
  - `wrong_tlc_residual`
  - `positive_after`
- 共 14 个具名 `prepare_onchain` 结果；hash/amount/direction/residual 的输入、拒绝原因和 store 摘要分别输出。
- Python 新增一个 SDK 批次测试，映射 F2-01～F2-04；另新增入口确定性测试映射 F2-05～F2-06。
- 统一入口的精确选择器增加 `test_cases/framework/test_lsp_refund_f2_runner.py`，不扩大到整个 nightly 目录。

### 实测

构建：`download/fiber/pr-1623-56c761c-f2-g6/build.json`；helper 源码摘要 `a86205b9...`，binary 摘要 `6c7416ec...`；构建约 1.52 秒，未构建 FNN。

```bash
# cwd: /Users/sunchengzhu/project/fiber-py-integration-test/tmp/lsp-p0-1
venv/bin/python scripts/run_lsp_refund_f2_fast.py   --bundle download/fiber/pr-1623-56c761c-f2-g6   --output report/lsp-refund-f2-g7-run6   --junitxml reports/lsp-refund-f2-g7-run6/native-results.xml
```

结果：

```text
F2 exit=0 elapsed=1.983s
4 passed in 1.69s
```

- SDK 批次：`2 baselines + 14 calls + 1 complete`，共 17 行；
- 2 个正向前置、2 个恢复后正向、10 个负向全部通过；
- 具体拒绝原因：
  - `wrong_tlc_index`: `commitment validation: wrong TLC signing key`
  - `wrong_tlc_hash/amount/direction`: `commitment validation: settlement witness is not committed by live input`
  - `wrong_tlc_residual`: `commitment validation: unapproved on-chain destination`
- 每次调用前后 signer store 摘要不变；
- F2-05 同时验证真实入口对缺失 bundle 快速失败；
- F2-06 用缩短截止（0.3/0.6/2.0 秒）验证 TERM/KILL/退出 124、日志落盘和无关进程不被杀。

证据：

- `report/lsp-refund-f2-g7-run6/result.json`
- `report/lsp-refund-f2-g7-run6/sdk-results.jsonl`
- `report/lsp-refund-f2-g7-run6/supervisor.jsonl`
- `reports/lsp-refund-f2-g7-run6/native-results.xml`

### 映射与边界

`check_test_map.py`：`review cases: 144`、`automated cases: 138`，退出 1；新增 F2-01～F2-06 已映射，无新孤儿/重复 ID；非零仍来自既有 `PMP-01～05、SETTLE-01`。

仍未完成/未声明：

- 真实 270/275 秒边界未实测；缩短截止和阈值配置检查不等同于真实等到该时刻；
- 真实链/TLC adapter 联合资格仍由旧 skip 类保留为缺口；
- F1 的 `single_tlc`/`diagnose` 问题未修；
- 独立 TLC 真实退款分支仍未取得，不能把 SDK 快测通过外推为 `T-then-A-sweep` 之外的退款路径通过；
- 15 秒前置失败是实测入口耗时约 0.02 秒，不是 15 秒边界压力测试。

## 实现 review 修复（2026-11-08）

外部实现 review 发现并已修复：

- **B1 跨进程 PGID**：统一入口通过真实的 `LSP_REFUND_F2_OWNED_PIDS` 登记自检创建的子进程组；`supervise` 创建子进程时立即登记，外层 `main` 的 finally 和紧急超时都会读取并 KILL 登记组。F2-06 的登记测试不再覆盖真实 registry，而是读取真实 registry、保留测试自有组并调用实际 `_kill_registered` 兜底；登记写入失败也已纳入子进程清理。
- **B2 F2-05 摘要覆盖**：`test_preflight_rejects_missing_or_mismatched_bundle` 从有效 g6 bundle 复制独立样本，分别篡改固定版本、产品源码路径、产品锁、helper 源码/锁/manifest、二进制摘要，逐项断言对应错误来源，只接受 `ValueError` 且精确匹配 `SHA256 mismatch: <完整路径>`；缺目录/缺源码单独接受 `FileNotFoundError`，排除超时或缺文件冒充摘要拒绝；实际入口同时覆盖缺失和版本变异 bundle。
- **非阻塞**：README 命令改为 g6；F2-06 的 TERM/KILL 原始日志复制到 `runner-selftest-evidence/`；Python oracle 对方向位做 `after[18] == before[18]^1`、金额做 Q+1、residual 做长度不变的额外断言。

最新整组证据：`report/lsp-refund-f2-g7-run6/result.json`、`sdk-results.jsonl`、`reports/lsp-refund-f2-g7-run6/native-results.xml`。

仍未改变：真实 270/275 秒边界未实测；旧真实链/adapter F2 skip 保留；独立 TLC 真实退款分支未取得。

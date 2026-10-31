# Hosted LSP 新版主流程与进程重启恢复用例评审

评审范围：先验证新版 SDK 授权校验下的正常开通、单笔收款和协作关闭，再验证 SDK 或完整 FNN 在明确签名检查点退出后，用原数据恢复同一业务。对应区域图中“进程重启恢复”的 Gate1；不包含跨业务截止时间的强关、watchtower 结算或旧版存储迁移。

原始评审源码版本：[Fiber PR #1623](https://github.com/nervosnetwork/fiber/pull/1623)，目标为 `0f41d9a1f1d20bd5b1fe35e0f249c4340019a073`。测试仓库基线为 `852c97daeb41b9b3824dae184d4952ddad1069d1`。FNN、SDK 及测试驱动必须同源构建并通过摘要校验；执行结论不由场景勾选表示。本轮 Gate2 目标为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`，此前已执行 FNN/SDK 为 `4028884`；当前 `24b5c38` 的实际结果与历史构建说明见 [LSP 测试说明](../../test_cases/fiber/devnet/lsp/README.md)。本轮修改 02～07 的订阅恢复与冻结检查点，01 完整行保持原样；资金及原业务身份预期不放宽。现有勾选只表示原 TEST-MAP 存在，Gate3 自动化已同步新的 WS 恢复检查点，执行结果另行记录；总范围见 [签名订阅评审](signing-subscriptions.md)。

历史批次按 `0f41d9a` 的上游策略复测：nonce 跨消息复用仅保留警告，不再直接拒签；这不表示 nonce 问题已经修复。
其余 SDK 验证保留，用例场景及业务断言不变。新增的安全释放 preimage 入口不改变本表普通发票的覆盖边界。
发票显式设置 TLC 基础期限为 1 小时，付款端 `tlc_expiry_limit` 为 24 小时，满足已评审的恢复余量和 SDK 的 15 分钟下限、48 小时绝对期限上限。
节点会在基础期限上加入随机延长，因此不能只设置发票期限、却沿用付款端默认 14 天上限；dev 构建约 1.333 秒的 RPC 默认值也不是最终 TLC 期限。

## 接口说明

- T 是公共 LSP，A 是其中一个 Hosted 租户，P 是独立普通付款节点。A–T 使用私有 CKB 通道，收款路径为 P—T—A；本批只有一个租户、单笔支付，不使用 UDT 或 MPP。
- 签名端使用当前 SHA 的真实 SDK、文件存储和 A 的租户 token。WS channel_signing 订阅向 SDK 交付待签请求，`get_channel_signing_status` 仅供测试独立核对，`submit_channel_signature` 首次应用返回 `Applied`，最近一次完整相同的已应用结果返回 `AlreadyApplied`。原样包含请求 ID、部分签名和下一轮公开材料。
- 新 SDK 先检查本地开通约定、支付/发票及关闭授权，再检查待签内容和对端签名证据。驱动只能调用真实 SDK 的授权、准备和签名接口，不移除验证，不把节点要求签名的内容直接当成钱包批准值。
- SDK 重启保留 RootKey、会话、绑定、已验证历史和授权所在的原存储；FNN 重启保留公共节点与租户的原数据、配置和认证密钥。所有重启都在同一 SHA 内进行，不读取旧版运行遗留的数据来测试升级兼容。
- “进程重启”必须观察旧进程退出和新进程启动；仅重建 SDK 对象、重新连接 HTTP 或驱逐租户均不符合前提。FNN 可读存储不代表租户已经能继续协议，必须实际提交和完成业务。

本次新增范围（2026-10-30）：用户选择实测反馈候选18，直接展开下文[连续付款后的SDK恢复Gate2](#连续付款后的sdk恢复gate22026-10-30)，仅新增 `LSP-RECOVERY-08` 一行，固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`。01～07的历史行和结果不变；08等待完整行及预算确认，本轮未修改自动化或运行测试。

## Spec

### SPEC-01：正常授权与资金结果
Condition: 同 SHA 的真实 SDK 按本地意图开通、收款并协作关闭。
Expected: 签名验证保留，原支付只结算一次，关闭交易确认且资金按批准地址与费用返还。
Observable: 双方通道、支付/发票、TLC、四端余额和链上输出。
Basis: [Hosted 签名契约](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/docs/notes/hosted-lsp-remote-signer.md)。
Source: explicit
Testing: required

### SPEC-02：SDK 原存储恢复当前工作
Condition: SDK 在签名已保存或应用结果未知的明确检查点退出，以原存储启动新进程。
Expected: 新进程订阅获得当前请求，保留原身份、授权和已签历史，无需重新批准即可继续原业务。
Observable: 旧/新 PID、成功订阅及实际交付、原提交体、控制调用记录和业务结果。
Basis: [SDK agent](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/agent.rs)、[EventStream](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/events.rs)。
Source: explicit
Testing: required

### SPEC-03：FNN 原数据恢复请求与去重
Condition: 整个 FNN 正常停止后用原数据恢复，SDK 进程保持。
Expected: 待签及最近结果保留，原 SDK 自动重新订阅后继续原业务，签名和资金不重复应用。
Observable: FNN 进程与数据、同 SDK PID、新订阅交付、真实 RPC 结果及业务结果。
Basis: [Hosted 签名与运行时恢复](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/lsp/service.rs)、[通道持久化处理](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs)。
Source: explicit
Testing: required

### SPEC-04：已积累多笔付款历史的同一通道仍可恢复并继续支付
Condition: 同一P–T–A拓扑及同一SDK文件存储已连续完成8笔付款，第9笔的真实撤销签名已保存但尚未提交时强制退出SDK。
Expected: 原存储的新SDK进程恢复相同待签请求及提交体，无须重建通道或再次批准第9笔；第9笔及随后第10笔均成功，各付款只结算一次，逐笔及累计金额与实际路由费正确。
Observable: 十个唯一payment hash的实际付款/发票、四端余额和锁定、原channel/funding、旧新PID、原身份/token/存储、完整R/S及首次Applied；另记录整库snapshot.bin字节、恢复记录投影数量和付款耗时，不设未经确认的性能阈值。
Basis: 已获范围确认的[候选18与SPEC-06](field-feedback-scope.md#spec-06连续正常付款不能只验证第一笔可用)；固定843的 `crates/fiber-lsp-sdk/src/signer.rs:1257` 读写签名状态、`lifecycle.rs:234` 保留承诺恢复记录、`tests/fiber-lsp-sdk-agent/src/store.rs:30` 重新打开原快照及逐次持久化；已有06仅验证一笔付款时的同类恢复。
Source: inference
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 正常主流程
  - 开通收款关闭 LSP-RECOVERY-01 [primary] -> SPEC-01
- SDK 原存储重启
  - 开通签名已保存未送达 LSP-RECOVERY-02 [primary] -> SPEC-02
  - 开通已应用但结果未知 LSP-RECOVERY-03 [primary] -> SPEC-02
  - 支付撤销签名已保存 LSP-RECOVERY-06 [primary] -> SPEC-02
  - 关闭签名已保存 LSP-RECOVERY-07 [primary] -> SPEC-02
- FNN 原数据重启
  - 待签请求保留 LSP-RECOVERY-04 [primary] -> SPEC-03
  - 支付最近结果去重 LSP-RECOVERY-05 [primary] -> SPEC-03
- 同一通道累积付款历史
  - 前8笔逐笔完成，第9笔原SDK存储恢复，再完成第10笔及累计资金核对 LSP-RECOVERY-08 [primary] -> SPEC-04
  - 长期压力、性能增长阈值及单通道StoredSigningState字节导出 [pending] — 本次只记录现有接口可得数据，不新增性能验收或Rust导出入口。
<!-- TEST-TREE-END -->

## 待评审用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-RECOVERY-01` | - [x] 在同一新版 FNN/SDK 下，A 按本地批准的参数开通 A–T；A 创建并授权一笔普通发票，由 P 支付一次，在 SDK 记录该 TLC 的有效承诺后批准兑现；支付完成后保存关闭授权，由 T 协作关闭 A–T，全程不注入重启 | 原通道双方就绪；原支付为 `Success`、发票为 `Paid`，TLC 清空，四端余额只发生一次金额及实际路由费对应的变化；随后原通道关闭，关闭交易确认，双方收到约定余额扣除各自关闭费用后的输出 | 新版授权准备不足导致所有故障测试失去正常流程对照，或主流程看似完成但资金结果错误 | P0 |
| `LSP-RECOVERY-02` | - [x] A–T 开通中，SDK 已保存 S1但未送达 FNN；强制结束 SDK，以原存储启动新 PID，不重新绑定或批准开通，通过新进程的 WS 订阅恢复 R1 | 租户身份、token、绑定和完整 R1不变；新 SDK 成功订阅并实际收到 R1，生成与 S1相同的提交体，首次送达为 Applied；原通道双方就绪、对应原注资且无额外通道 | 重启丢失已签记录或授权，或仅查询正常却误判 SDK 已恢复 | P0 |
| `LSP-RECOVERY-03` | - [x] A–T 开通中，在转发 S1前阻断向 SDK 交付后续 WS 事件及新订阅；FNN Applied S1后扣住 HTTP 响应，确认 R2未交付旧 SDK、S2未应用即强制结束 SDK；原存储启动新 PID，通过新订阅恢复 R2并重交 S1 | 旧 SDK 没有获知 S1结果或 R2；新 SDK 订阅实际收到完整 R2且无需重新授权；真实 FNN 对 S1返回 AlreadyApplied，R2不变；放行后原通道双方就绪，通道及注资身份不变 | WS 提前泄露下一请求使未知结果检查点失真，或重启重复应用并吞掉下一请求 | P0 |
| `LSP-RECOVERY-04` | - [x] A–T 开通中冻结完整 R1及未送达的有效 S1；暂缓交付和提交，正常停止整个 FNN，以原数据重启并复核 R1；SDK 保持原 PID，自行重新订阅后恢复原签名 | 原 token 查询完整 R1不变；同一 SDK 的新订阅实际收到 R1，原签名首次应用为 Applied；原通道双方就绪且对应原注资，无重新注册或重开通道 | 节点仅能冷读存储却无法恢复订阅和执行，或恢复时丢失原待签 | P0 |
| `LSP-RECOVERY-05` | - [x] P 向 A 支付一次，关联承诺签名 S1已 Applied、R2尚未应用；暂缓 SDK 事件交付及后续提交，正常停止整个 FNN并用原数据重启；同一 SDK 重新订阅恢复 R2，重交 S1再放行 | FNN 保留最近已应用记录和完整 R2；原 SDK 同 PID 的新订阅实际收到 R2；S1返回 AlreadyApplied且 R2不变；P–T重连后原支付 Success、发票 Paid、TLC清空，四端余额只结算一次且路由费一致 | FNN 重启丢失去重或订阅恢复能力，造成重复扣款或原支付卡住 | P0 |
| `LSP-RECOVERY-06` | - [x] P 向 A 支付一次，SDK 已保存发票、兑现授权及该支付 SendRevokeAndAck 的签名，但未送达 FNN；强制结束 SDK，以原存储启动新 PID，经新订阅恢复原请求，不重新登记授权 | 新 SDK 成功订阅并实际收到原完整请求，从原历史及授权生成相同提交体，首次送达为 Applied；原支付 Success、发票 Paid、通道就绪、TLC清空，四端余额只结算一次，无须重新发起支付 | 恢复丢失撤销历史或授权，或未真正消费订阅却误判支付恢复 | P0 |
| `LSP-RECOVERY-07` | - [x] A–T 收款完成且无 TLC，A 已保存精确关闭费用授权；T 协作关闭，SDK 已保存 SendClosingSigned 签名但未提交时强制退出；以原存储启动新 PID，经新订阅恢复原请求，不重新批准关闭 | 新 SDK 实际收到原完整关闭请求并生成相同提交体，首次送达为 Applied；原注资被对应关闭交易花费一次且确认，两个输出的脚本与金额符合支付后余额和各自批准费用，原通道关闭 | 恢复丢失关闭授权或余额历史，或关闭资金少返、多返和付错地址 | P0 |
| `LSP-RECOVERY-08` | - [x] 同一P–T与T–A两条通道、同一SDK存储串行收款：前8笔各成功，第9笔SendRevokeAndAck签名已保存未提交时强制退出SDK，以原存储及身份新进程恢复第9笔，随后完成第10笔；每笔1,000,000 Shannon、唯一hash、只发送一次 | 第9笔新SDK收到原完整请求并生成相同提交体，首次实际提交Applied，无重新授权；十笔均Success/Paid且各只结算一次，原通道/注资不变，每笔及累计四端金额与实际路由费一致，无残留TLC/锁定；重启不改变前8笔结果，第10笔证明后续可用 | 单笔测试遗漏历史积累后的恢复错误、重复扣款/收款，或重启只能完成旧付款而无法继续新业务 | P1 |

<!-- TEST-CASES-END -->

原七行针对核心通道使用或资金安全；第一行是新版主流程对照，其余分别验证不同持久化事实和恢复位置。新增08仅补多笔历史积累后的恢复和继续付款，输入及预算按文末本次Gate2，不套用历史批次规模。
不把一切错误都归为重启缺陷：版本不符、授权入口缺失、指定检查点未出现，应报告准备失败，不能算用例通过。

## 共同前提：先让新版正常工作

每行建立独立环境，不依赖第一行或前一行遗留的节点、通道和余额。实现时先运行第一行，确认准备能力成立后再注入故障。

| 前提 | 固定的输入与准备方式 | 需要确认的证据 |
| --- | --- | --- |
| 版本和认证 | FNN 与 SDK 均来自上述 HEAD；使用匹配的 Biscuit 认证材料，在新数据目录中准备各行环境 | 构建清单、实际 FNN 版本、SDK 依赖 SHA 和产物摘要一致；重启前后保持同一套产物及密钥 |
| 开通 | 沿用 A、T 各提供 500 CKB 的私有通道；钱包注资与 remote signer 分开；`commitment_delay_epoch` 为 1 epoch。由 SDK 的 `open_tenant_channel` 保存原始钱包意图，调用生产开通 RPC，通过独立 CKB 查询校验完整注资交易并验证开通上下文，然后持久化绑定与授权 | 预先确定的双方金额、准备金、接收脚本、合约、手续费、epoch 时长和协商公钥，与批准的注资及通道约定一致；CKB 的 SDK 金额含准备金，不能把可支付余额直接当成这个值 |
| 签名准备 | 真实 SDK 完成对应 `prepare_*` 校验，再由测试策略确认并签名；测试转发器只控制传输，不代替签名或缓存 FNN 的幂等结果 | 收到合法签名提交体，完整待签请求包括 `session_evidence`、TLC 身份及密钥派生信息；授权成功必须等 SDK 存储操作完成，不能只看控制接口返回“请求已受理” |
| 单笔收款 | P–T 公共通道已就绪，P 已获得 T 的 trampoline 路由信息；A 创建金额 M=1,000,000 Shannon、有效期 1 小时、禁止 MPP 的普通发票；preimage 由测试预先生成。付款前调用 `authorize_invoice`；SDK 已保存包含该 TLC 的有效承诺后、签署兑现更新前，再以原 preimage 调用 `authorize_fulfillment`。P 仅调用一次 `send_payment`，路由费上限 10,000 Shannon | payment hash、金额、哈希算法和方向均与本地创建条件一致；SDK 不从节点待签快照推导“用户同意收款”；已知 preimage 的普通发票用于本批，不声称验证移动钱包的安全释放 preimage 流程 |
| 授权有效期 | 以本地创建时间 t0 为基准，`expires_at_ms=t0+1小时`、`min_tlc_expiry_delta_ms=15分钟`、`max_tlc_expiry_ms=t0+48小时`；沿用产品默认最终 TLC 有效期 24 小时，P 的支付 timeout 设为 1,200 秒 | 以实际 TLC expiry 复核授权范围和节点/SDK 恢复窗口；不复制上游内存测试中 120 秒授权、1 毫秒最小余量及无限最大 expiry 的宽松配置 |
| 协作关闭 | 支付已完成，双方没有未完成 TLC；A、T 的接收脚本可区分。T 以 `force=false`、费率 1,000 Shannon/KB 发起关闭，A 自动响应费率为 0；事先按关闭交易结构和双方费率计算费用，批准 `C_A=0`、`C_T=C` 并调用 `authorize_close` | 批准的总费用 C 等于两方费用之和；费用由预设费率、脚本和合约依赖决定，不先照抄节点发来的关闭交易扣款额再批准。实际协商费用若不符合前提，应报告差异，不能静默放宽授权 |

新 SDK 的 `authorize_invoice` 会检查 preimage，但不保存该秘密，也不等于批准释放；`authorize_fulfillment` 保存的是兑现意图。
本批由驱动预先掌握秘密并明确选择普通发票路径；重启后无需再次登记相同授权，更不能通过重新登记来掩盖存储恢复失败。
必须先接受 TLC，再批准兑现：若在首次接纳 TLC 前就把 SDK 中的授权标成已兑现，新 SDK 会拒绝这个新 TLC。
驱动通过 SDK 的有效承诺记录确认接受事实，不能只因 FNN 报告发票状态变化就跳过这一步。
agent 可能为未来开通分配未使用的签名材料，不能因此要求整个存储文件在启动前后字节完全不变；应检查身份、既有通道绑定和实际恢复行为。

### 本地测试驱动

`0f41d9a` 的命令行 agent 已补发票授权和安全释放 preimage 入口。本表继续用测试仓库 LSP 目录内的 `_sdk_driver.rs`
调用同 SHA 的 SDK/agent 库，为已评审的普通发票提供授权和恢复记录观察，保留真实文件存储、验证及签名流程；不改为另一种收款场景。
授权入口应返回 SDK 操作完成后的结果，重启行要记录控制调用，证明重启后没有再次登记旧授权。
这些是测试驱动的本地控制入口，不是 FNN RPC；不修改公共 Python 框架、`AGENTS.md` 或 `Makefile`。

开通使用 `412b254` 的真实 SDK 验证入口；受信合约、依赖数和 epoch 时长来自本地 devnet 配置。
驱动另以 RocksDB 只读模式读取本次公共 T 独立保存的协商状态，核对双方各 500 CKB、SDK 公钥、
A 的接收脚本、1 epoch 和费率，并按预定交易结构计算关闭费用。此读取用于独立核对和关闭预期，
不代替 SDK 的开通验证、不改节点数据，也不把待签响应当授权值。
首行主流程失败时须保留失败并停止故障执行，不能通过关闭 SDK 校验继续，也不能把后续映射当作通过。
每行使用新 SDK 存储；运行前准备仓库标准 devnet 依赖 `source/ckb-cli`。

## 异常时间与恢复窗口

所有等待上限都是测试发现卡死的预算，不是 PR 承诺的恢复时间。事件一旦成立就立即推进，不固定停机 5 秒或 12 秒。

| 阶段 | 触发点与上限 | 超限或前提不足时的处理 |
| --- | --- | --- |
| 取得故障检查点 | 正常流程发起后，最多 60 秒等待目标请求/真实 `Applied`；必须确认所属通道、转换和支付关联 | 未取得指定检查点即失败，不选择任意另一阶段代替 |
| SDK 停止与启动 | 捕获已保存但未送达的签名，或已应用但未回送的响应后，立即对本次 SDK 进程发出强制终止；10 秒内确认退出，使用原存储启动新进程，60 秒内出现新进程的成功 WS 订阅及目标事件实际交付 | 不复用旧状态文件冒充启动成功；不清理或补写授权存储；不重新注册、绑定或开通 |
| FNN 停止与启动 | 暂缓 SDK 提交，正常停止 FNN；退出与数据库锁释放分别最多 30 秒；新进程 RPC 就绪最多 300 秒，后续租户执行/目标签名最多 60 秒 | 保留原数据；不把正常停止超限后改用强杀算作同一行通过；RPC 可用后仍需验证 Hosted 通道可执行 |
| 开通与支付继续 | 直接 RPC 最多 10 秒；放行后最多 120 秒等待原通道或原支付终态，再连续观察 5 秒确认稳定 | 不新建通道、不重新发送支付；缺少终态、资金变化不符或出现第二次变化均失败 |
| 协作关闭 | 签名放行后最多 120 秒取得对应关闭交易；沿用 devnet 挖块方式，最多再等 180 秒确认交易和通道关闭 | 挖块只推进链上进度；不能仅见 `ShuttingDown`、交易进入池或注资 cell 不再 live 就判资金返还完成 |
| 业务截止前余量 | 开通故障开始时，适用 funding 窗口剩余至少 900 秒；支付故障开始时，安全截止及授权有效期剩余至少 900 秒；放行后续签名前再次确认至少 180 秒余量 | 900 秒覆盖 FNN 退出、启动、恢复和终态等待预算及调度余量；不足时报告前提失败。不得把超期拒绝或强关当成此批恢复成功 |

开通不缩短普通 funding timeout；沿用默认 24 小时并结合“是否仍可中止”判断适用性。等待外部注资交易的默认 5 分钟窗口
必须在进入本表故障检查点前完成，不能从签名暂停时把这 5 分钟重新计时。

支付同时考虑两端安全检查：节点按相关未确认移除 TLC 的实际 expiry 减去承诺延迟的 2/3；SDK 把 expiry 向下截到秒，
把安全预留向上取整后再校验。当前 1 epoch 的 debug 构建为 2,000 毫秒，节点预留 1,333 毫秒、SDK 预留 1,334 毫秒。
本批取两者更早的截止作为安全窗口；撤销签名还要纳入替代承诺中 TLC 的恢复截止，不能只检查当前 RPC 请求是否仍存在。
故障、退出、查询和提交时间用单调时钟记录；业务 expiry 及授权时间用与节点一致的墙上时间。不给宿主机改时钟。

## 场景展开与结果核对

### 所有行共用的结果核对

- **开通**：A、T 两侧同一个 channel ID 就绪、没有待签；双方注资 outpoint 一致，指向本次批准且已确认的注资交易。没有额外通道或第二笔注资。
- **支付**：保存 P–T 与 A–T 两条通道的支付前四端余额；最终原 payment hash 的支付为 `Success`、发票为 `Paid`，所有 pending TLC、发送/接收锁定额及 A 的待签清空。以实际路由费 F 验证 A 在 A–T 上增加 M、T 减少 M；P 在 P–T 上减少 M+F、T 增加 M+F；镜像余额一致，T 净增 F。通道仍就绪，稳定观察期内不再变动。
- **关闭**：取双方 `shutdown_transaction_hash` 并查询真实 CKB 交易，核对它花费原注资 outpoint、含约定的两个输出且已确认。若关闭前 RPC 可支付余额为 B_A、B_T，准备金为 R_A、R_T，批准的费用分摊为 C_A、C_T，则 CKB 输出应分别为 B_A+R_A−C_A、B_T+R_T−C_T；总输入容量减总输出容量等于 C_A+C_T，脚本对应正确接收方。双方原通道关闭并退出活动列表；相同交易的重新广播不算重复结算。
- **重启身份**：A 的 tenant ID、有效 token、既有 channel ID 和绑定保持一致；保留原注资 outpoint。记录旧进程退出、新进程来源和数据路径。SDK 恢复通过新进程实际订阅、目标事件交付、签名及后续业务证明，不能只比对日志或状态文件。

### LSP-RECOVERY-01：先跑通新版正常流程

完成共同开通与授权准备，检查通道就绪，再创建并支付唯一发票；完成四端余额核对后，批准关闭费用，T 发起协作关闭。
核对链上交易和两个输出。没有故障注入，也不暂时关闭 SDK 校验来获得成功；这行失败时先定位版本、准备或正常业务问题。

### LSP-RECOVERY-02：SDK 保存了，节点还没收到

保存首个待签 R1 及 SDK 实际提交 S1，确认上游转发次数为零；截获提交说明 SDK 签名存储调用已经返回。
强制终止 SDK 后再次向 FNN 查询完整 R1，启动新 SDK；确认新 PID 的订阅成功且实际收到完整 R1，取得它为 R1 产生的 S1'，逐字段比较业务提交体一致。
只放行新进程提交，确认首次 `Applied`，完成开通核对。只在测试中手工重发旧 S1 而新 SDK 没有继续签名，不能算通过。

### LSP-RECOVERY-03：节点已应用，SDK 在拿到答复前退出

在转发 S1之前冻结所有现有 WS 连接向旧 SDK 的后续通知交付，并阻止新订阅；再真实转发 S1，收到 `Applied` 后扣住整个 HTTP 响应。
从 WS 代理的实际交付记录确认 R2未进入旧 SDK 的网络缓冲，再终止旧进程；仅设置 pause_queries 或检查 repolled=false 不够。
测试直连 FNN 保存 R2，启动新 SDK，允许其新订阅实际交付 R2但暂不提交下一份结果；由测试直连真实 FNN 原样重交 S1，确认 `AlreadyApplied` 和完整 R2 不变。
放行新 SDK 的 R2 提交并完成开通；不要求 SDK 自己必然重发 S1，也不把测试直连重交当成 SDK 恢复证据。

### LSP-RECOVERY-04：整个 Hosted FNN 带着待签请求重启

保存完整 R1 和有效 S1，但不向 FNN 转发 S1。保持 SDK 进程运行，正常停止并启动 FNN，先用原 token 查询持久化 R1。
继续保留事件交付和提交限制直到复核完成；再放行原 SDK 的自动重连/订阅，保存同 PID 成功订阅及完整 R1交付证据，然后放行提交；记录实际首次应用结果并完成原通道开通。
重启前后的临时连接状态可变化，不要求整个通道 RPC 对象完全相同；待签内容、身份、注资和最终业务必须满足预期。

### LSP-RECOVERY-05：FNN 重启后仍记得支付签名已经应用

发起唯一支付，截住第一个与该 payment hash 关联的承诺签名，转换为 `SendCommitmentSigned` 或 `CompleteReceivedCommitment`，
结算内容必须包含对应 TLC。应用 S1，保存下一份尚未应用的完整 R2；暂停后续提交，正常重启 FNN，SDK 始终不退出。
复核 R2，放行同一 SDK 的新订阅并确认完整 R2实际交付，仍保持 S2不转发；原样重交 S1，确认真实 `AlreadyApplied` 且 R2 不变；随后恢复 SDK 签名和普通 P–T 连接，按原 payment hash 完成支付核对。
P2P 重连可使用原节点身份和地址，禁止以重新发起支付或换一条通道代替恢复。

### LSP-RECOVERY-06：SDK 恢复支付历史后才能继续撤销确认

在发起支付前完成发票授权；处理签名直到该支付加入承诺后的首个 `SendRevokeAndAck`，保存完整 R 和实际 S，暂不转发。
通过前一承诺的结算内容、版本及相同 payment hash 确认关联，不能截取开通或其他无关更新的撤销签名。
此时确认 SDK 已记录该 TLC；若尚未登记兑现意图，使用本地原 preimage 完成一次兑现授权并等待保存，再进入终止检查点。
终止 SDK 并使用原存储重启，不再次调用授权入口；新进程生成同一 S，首次提交 `Applied`，继续完成原支付及四端余额核对。

### LSP-RECOVERY-07：SDK 关闭阶段恢复后返还正确资金

先完成一次收款并核对余额；无待签和 TLC 后保存关闭授权，T 发起协作关闭，捕获 `SendClosingSigned` 的 R 和有效 S，确认 S 尚未送达。
终止 SDK 并用原存储重启，禁止再次批准费用；验证 R 未变及新 SDK 生成的 S 一致，放行签名。
检查关闭签名内容的原始交易哈希与实际关闭交易对应，完成链上输出和费用核对，不以关闭 RPC 成功代替余额返还。

## 预期依据与覆盖边界

- [SDK 本地授权及持久化](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/signer.rs#L521)、[签名返回前保存历史与恢复证明](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/signer.rs#L1072)、[agent 文件存储](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/tests/fiber-lsp-sdk-agent/src/store.rs#L52)支持 SDK 恢复预期；不等于证明写盘中途断电的原子性。
- [FNN 先保存最近已应用结果再回复和继续协议](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/channel.rs#L2216)、[恢复时重新交付待签请求](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/channel.rs#L4984)和[Hosted 运行时按需激活](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/lsp/service.rs#L418)对应完整 FNN 恢复。只保存最近一次结果，不扩展为永久保存历史重试。
- [SDK 收款恢复测试](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/commitment_tests.rs#L477)、[六种签名转换的节点恢复](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L923)和[签名端关闭恢复](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L1721)已有内存/对象级覆盖。本表补真实进程、文件存储、Hosted 内部通道及业务/链上结果，不重复展开全部签名转换组合。
- [SDK 安全预留算法](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/commitment.rs#L51)、[撤销前恢复窗口校验](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/commitment.rs#L692)和[节点截止检查](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/channel.rs#L6337)决定本批时间前提；[关闭金额校验](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/commitment.rs#L849)要求两个承诺方向余额一致、无 TLC，并精确匹配输出和费用。
- [首次接受 TLC 的授权状态校验](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/commitment.rs#L485)要求此时仍为未兑现状态，因此发票授权与兑现授权必须按共同前提的顺序进行；[协作关闭自动响应](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/channel.rs#L11547)使用 0 费率，明确了本表 A 不承担关闭费的输入条件。
- [4eb4f5e agent 文档](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/tests/fiber-lsp-sdk-agent/README.md)当时缺少命令行支付授权和链上验证接入；`412b254` 已替换旧绑定入口，`7f11564` 又补关闭、watchtower 授权和独立链上验证。支付/兑现控制及恢复记录观察仍由本地驱动调用真实 SDK；控制成功应表示 SDK 操作已完成。

本批不验证恶意签名内容的完整拒绝矩阵、FNN 强杀或断电、双进程同时退出、数据损坏/回滚、多租户驱逐、公共公告签名、业务超时及 watchtower 链上强关结算。
本表授权前提用于新版准备；已有 `LSP-SIGN-01～03` 和 `LSP-RETRY-01～06` 的业务预期及 ID 保留，旧版通过结果不能转记为新版通过。
后续新版适配若需要改变这些既有行的场景或结果，应先提交对应完整修改行评审，不在实现中静默改预期。

## 本轮需要确认

用户已确认 02～07 的完整修改行及以下 WS 冻结要求，Gate3 已同步自动化；01 的业务行不变。

- SDK 恢复辅助方法不再以 gate.queries 为恢复依据；必须按新 PID 记录成功订阅、目标事件交付和真实签名，恢复后没有重复授权控制调用。
- FNN 恢复辅助方法同时控制 WS 通知与 HTTP 提交；等待原进程自行重连，不能用 Python 查询代替它恢复。暂停操作必须有确认回执，避免仍在转发的事件越过冻结点。
- 03 的通知冻结在 S1转发之前完成，包括已有连接的帧和新订阅；结束旧 SDK 后清理旧连接缓冲，允许新 SDK 从 FNN 重新订阅，不能向它重放代理缓存冒充服务器补发。

- 先执行正常流程对照，再分别执行 SDK 已签未提交、SDK 未获知已应用、FNN 待签、FNN 支付去重、SDK 支付撤销、SDK 关闭恢复。
- SDK 故障采用存储操作返回后的强制进程退出；FNN 采用保留数据的正常停止重启。它们不代表断电或任意写入点崩溃恢复。
- 接受上文最小测试驱动作为必要准备；准备接口存在不等于新版完整链路成立，必须先验证第一行，再执行重启故障。

原01～07已对应 `test_cases/fiber/devnet/lsp/test_channel_signing_recovery.py` 中的 TEST-MAP；勾选只表示映射存在，不表示执行通过。新增08尚未映射。

## 连续付款后的SDK恢复：Gate2（2026-10-30）

本批是[实测反馈候选18](field-feedback-scope.md)的一条新行为序列，不重做旧订阅评审，也不把单笔RECOVERY-06再次执行当作新增覆盖。用户已选择该范围；本轮提交上表08及以下输入、断言、预算和适配供确认。产品固定843，GPT-6 Sol High只读复核，当前仅编辑文档。

### 固定规模与完整操作

只执行一个新方法，固定十笔串行付款；失败即停，不增加轮次或换hash补跑失败笔。A–T双方各500 CKB；P–T由P注资1,000 CKB，只开一次。四端顺序固定为A、T–A、P、T–P；准备就绪后保存两条channel ID、funding outpoint和四端余额基准。第2～10笔必须复用该拓扑，不重新注册A、不换SDK存储，不重建通道。

每笔金额均为1,000,000 Shannon，总金额10,000,000 Shannon（0.1 CKB），十个preimage/hash各不相同。沿用现有普通CKB发票、3600秒有效期、final_expiry_delta=3,600,000ms、允许trampoline且禁MPP；一次send_payment，max_fee_amount=10,000 Shannon、tlc_expiry_limit=86,400,000ms、timeout=1200秒。发票授权先保存，SDK记录含本笔TLC的真实有效承诺后才批准兑现。本行不是hold invoice安全释放测试，也不增加取消发票或链上结算。

1. **第1～8笔。** 每笔新建并授权唯一发票，真实发送一次；等Success/Paid、无待签、无TLC/锁定后核对逐笔与从初始基准累计的四端资金，连续5次、间隔1秒确认本笔状态/余额稳定，才发下一笔。SDK始终使用原PID和存储；仅在准备阶段创建P–T一次。
2. **第9笔冻结。** 沿现有06的真实检查点推进：本笔含目标hash的承诺已记录、发票及兑现授权已保存；到首个对应本笔的SendRevokeAndAck时保存完整R9/S9并暂扣提交。用commitment version、方向、complete标志及目标hash确认原恢复记录对应本笔，不截取开通或其他更新。HTTP审计确认S9从未实际转发；保留原R9、原身份、token、绑定、存储路径及控制调用记录。只在本笔活跃TLC/授权期限至少有900秒余量时开始故障。
3. **原存储恢复。** 强制退出SDK，确认旧进程退出；保存已落盘的snapshot.bin原字节/摘要。仅删除可重建status输出，原存储不写入、不修剪、不替换；以相同command/token/store启动新PID。新进程必须真实重新订阅并收到完整R9，产生与S9相同的提交；tenant/root signer/token/绑定保持，恢复期间没有新invoice/fulfill/bind授权调用，也不重新send第9笔。只要求在已保存签名之后杀进程，不声称覆盖任意写盘点断电。
4. **完成第9笔。** 放行真实SDK提交，原S9首次实际到FNN必须Applied；后续签名由真实SDK继续。第9笔Success/Paid，原通道/注资、逐笔及累计资金、零TLC/锁定和5秒稳定均通过；再次查询前8笔仍为Success/Paid且fee未改变。
5. **第10笔与收尾。** 由恢复后的同一新SDK进程按正常流程完成新hash付款，执行同样资金和稳定断言；最后重新查询十笔终态/fee并检查累计账本、原通道和零锁定。第10笔失败不能用“第9笔恢复了”代替本行通过。

### 金额、身份及证据断言

第i笔实际路由费为 `f_i=get_payment(hash_i).fee`，要求 `0≤f_i≤10,000`，不写死为零。相对上一笔稳定余额，四端local_balance增量依次为 `(a, -a, -(a+f_i), a+f_i)`，remote_balance增量相反；A/T–A与P/T–P均须local/remote互为镜像。完成k笔后相对首次基准，四端累计增量为 `(k*a, -k*a, -(k*a+Σf_i), k*a+Σf_i)`；T两条通道净收入合计等于Σf_i。

每笔四端保持ChannelReady、原channel/outpoint；offered/received锁定额均0、pending_tlcs清空、A为NoSignatureRequired。十次send的记录与十个唯一hash一一对应，旧付款终态/费用不变，逐笔和累计账本共同证明经济上没有重复结算；不声称完整验证所有内部session/attempt重试。第9笔恢复另要求同一R9/S9、原存储和新PID、新订阅的实际交付以及首次Applied，不能由Python代交S9冒充SDK恢复。

在0、1、4、8、9、10笔稳定点记录宿主单调时间、整库 `store/snapshot.bin` 的字节数、已有 `records` 投影条数/版本及各笔实际耗时；第9笔记录故障、重启、恢复的相应时间点。时间和大小是诊断数据，无增长斜率、CPU或性能通过阈值；付款耗时包含RPC与观察开销，不称SDK纯签名耗时。

当前 `records` 并不导出完整StoredSigningState，**单通道序列化状态字节在本批明确未测**；整库snapshot.bin不能换名冒充它。为本次功能验证不增加Rust导出接口或产品构建。原始请求/响应、签名审计、SDK/node日志、逐笔/累计账本、稳定样本、身份（摘要）、存储检查点和JUnit均保存在一个独立运行目录；对外汇报不展示token/私钥。

### 最小适配及一次验证

- 在现有 `test_channel_signing_recovery.py` 新增一个方法 `test_sequential_payments_survive_sdk_restart`，映射08；不新增通用框架。`_start_payment`仅增加可选已有public_channel输入：默认仍创建通道，旧01～07调用不变；08在首次付款后保留P–T ID，第2～10笔复用并核对同一四端。不能直接循环原方法而生成十条P–T通道。
- 复用 `_finish_payment` 的逐笔余额/镜像/费用/稳定断言，另保存初始基准、每笔终态和fee作累计核对；复用06的撤销检查点、`_kill_sdk/_restore_sdk/_check_first_forward`。十笔期间保留审计历史，不清空SDK记录来“重置”下一笔；第9笔用request ID和时间筛选自己的事件，避免把前8笔提交误判为重复。
- 现有局部循环之外增加仅对08生效的总截止；不修改旧方法默认等待。复用现有归档方式，将小型序列账本/度量随每笔落盘，故障/到期保留已完成笔数及当前原始证据。只新增一处TEST-MAP及08复选框同步。
- 显式使用 `LSP_TEST_REVISION=84333eea8488a8afc7e4474aa4bbd0e7e973cee9` 与已保留的 `report/lsp-invoice-cancel-84333ee-20261030T003644/bundle`。该清单driver/chain摘要与当前源码匹配；默认download下843 bundle的辅助源码摘要过期，不能误用。Gate3仍先核对全部文件摘要、产品干净HEAD、Python/端口和空间；匹配产物可复用，不为本批重建FNN/SDK或启动VM。
- 适配先经GPT-6 Sol High复核，静态语法与选择器收集检查后，仅跑旧06一次检查默认路径，再跑新增08一次。旧06在843既有JUnit耗时89.176秒，仅作本次3分钟聚焦预算参考；新十笔尚无实测时间，不将单笔时间机械乘十。两个方法均失败/到期即停，不加1+3、不跑全套旧订阅或退款。

### 时间、空间与停止规则

Gate3从首次准备开始共30分钟硬上限：实现/复核/产物与环境检查10分钟，旧06相关回归3分钟，新08正式执行12分钟，证据及清理5分钟。准备、修正或重启执行器都不重置起点；各阶段取自身截止与总截止前预留清理时间的较早者，未用完时间不扩大后续阶段上限。到期尚未完成十笔即记“预算停止/未完成”，不能压缩付款次数、5秒稳定期或资金断言来取得通过。

局部等待沿用RPC最多10秒、请求/撤销检查点和重连各最多60秒、每笔完成最多120秒，均受全局剩余截止限制；放行第9笔前保留现有至少180秒业务余量。入口/环境失败、产品断言失败或超时均停止；已完成前缀不等于08通过。运行前及运行中磁盘不得低于8 GiB，本批新证据目录增长到512 MiB即停止业务并保留现场收尾，不生成多轮全量存储拷贝。完成后清理本批自有进程及可重建临时文件，保留原始证据、现有bundle、源码改动与旧快照；本批不生成新的Rust编译缓存。

下一步等待用户确认08这一行、固定8+恢复第9+第10的规模、30分钟上限及上述度量边界，再在主会话进入Gate3；本次没有运行测试。

Gate2复核：GPT-6 Sol High结论为设计可通过、无阻塞；已将“同一P–T–A通道”精确化为两条原通道。设计检查识别8行、退出0，新增SPEC-04的推断预期仍按本轮提交用户确认，长期压力/单通道字节保持未覆盖。项目映射检查124评审/116映射、退出1，08未映射符合Gate2，9个既有孤儿映射保持且无重复ID；未宣称映射检查全绿。`git diff --check`退出0。仅新增评审行、测试树及表外方案，并在原候选范围添加入口；未改自动化、未收集pytest、未构建或启动节点。

## 连续付款后的SDK恢复：Gate3实测（2026-10-30）

用户明确确认上面的08行集与30分钟预算后，已实现`test_sequential_payments_survive_sdk_restart`并建立TEST-MAP，08复选框由未映射改为已映射；预期未变。GPT-6 Sol High先复核实现通过，再只读复核实测证据通过。

固定干净84333ee，匹配现有bundle，旧06、新08各运行一次：pytest分别103.82/207.16秒，均1 passed、exit0，整批exit0；准备至执行/自动清理约646.44秒，未重置预算或追加测试。08的固定8+恢复第9+第10完整执行，十笔Success/Paid，金额总计10,000,000 Shannon，费用总计50,000；四端逐笔及累计余额、原channel/outpoint、零锁定、5秒稳定与历史终态/fee保持均通过。新PID通过新WS恢复原请求，S9首次真实转发Applied。

完整证据和命令见本批RESULT（本地证据：`../../report/lsp-recovery08-84333ee-20261030T171222/RESULT.md`）。本批自有进程已退出、端口释放、可重建隔离临时目录清理；证据、原产物、历史快照保留。没有改产品、操作退款或扩成长压；整库snapshot/records的诊断边界仍按Gate2。映射检查124评审/117映射，exit1仍为9个既有孤儿，无新增孤儿或重复ID。

## 84333ee 收尾补证：RECOVERY-05 持久化 delivery（2026-10-30）

用户确认四项收尾工作后，复核现有05发现其已执行真实付款中的完整FNN正常停止、原数据重启、同SDK恢复及四端资金核对；不新增重复ID或第二套恢复环境。本次保留05既有输入与行预期，只增强原付款执行记录的观察：停前必须真实处于`in_flight`或`settling_upstream`，保存并匹配P—T的incoming channel/TLC、租户、private channel、hash、created_at和buffer_deadline；重启后这些身份和截止不变，attempt_count允许产品合法推进；最终同记录必须`succeeded`，原资金、零锁定与5秒稳定窗口断言仍执行。

源码依据：固定843的`crates/fiber-lib/src/lsp/service.rs`启动时扫描持久pending并Resume、`rpc/lsp.rs`公开原incoming执行键与时间字段。已有TEST-MAP继续使用LSP-RECOVERY-05；此次不声称覆盖Deferred冷租户的首次dispatch，也不验证断电/fsync或跨版本迁移。实现及复核不等于执行通过，实际结果追加至LSP README。

本次增强的单次实测结果：2026-10-30 `execution-211837`，pytest 1 failed in94.53s、exit1。真实delivery已取得`in_flight`，但新增观察代码在`before_restart`写未创建的证据父目录时失败；尚未调用FNN重启，不能计恢复、最终资金或稳定窗口通过，也不能归为产品失败。按用户fail-stop要求未重跑，后续九项TIMEOUT未启动。原TEST-MAP和用例预期不变，历史05通过不能代替增强后通过。证据、GPT-6 Sol High归因复核及已完成临时目录清理见实际结果（本地证据：`../../report/lsp-closeout-84333ee-20261030/execution-211837/RESULT.md`）。

用户批准修正后开新批`execution-214323`：父目录创建遗漏已修，GPT-6 Sol High复核及离线准备检查通过后，05单次**1 passed/150.86秒、exit0**。真实FNN新PID/原SDK同进程，同一incoming key、身份、时间字段在原数据重启前后保持，delivery由in_flight达到succeeded并五次稳定；原付款Success/Paid、金额1,000,000 Shannon、fee5,000、四端资金镜像和零锁定通过。归档校验及临时目录清理完成，旧211837仍保留原失败。证据和准确资金边界见新批结果（本地证据：`../../report/lsp-closeout-84333ee-20261030/execution-214323/RESULT.md`），仍不扩大为Deferred冷恢复、断电或跨版本保证；TEST-MAP和用例行不变。

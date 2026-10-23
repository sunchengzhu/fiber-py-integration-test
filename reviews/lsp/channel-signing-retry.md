# Hosted LSP 通道签名提交重试与短暂断线用例评审

评审范围：同一租户、同一通道在签名重复提交、提交内容冲突、旧请求重放，以及 HTTP 请求或响应丢失后，保持请求和业务结果一致。包含开通及单笔入站支付；进程重启、业务截止后保护、协作关闭和 watchtower 专项沿用区域图中的后续分组。

源码版本：[Fiber PR #1623](https://github.com/nervosnetwork/fiber/pull/1623)，HEAD `774e61bbe54b8ab335b235458d14df2f8feea23d`，base `271e13c2911247baf6f178be52cab98e23fb5fd4`。测试仓库基线为 `852c97daeb41b9b3824dae184d4952ddad1069d1`。

以上为历史评审依据。本轮 Gate2 固定目标为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；此前已执行的 FNN/SDK 为 `4028884`，不能转记为新版本通过；当前执行结果见 [LSP 测试说明](../../test_cases/fiber/devnet/lsp/README.md)。只修改 04/05 的事件恢复检查点，01/02/03/06 的完整行保持原样。全部现有 TEST-MAP 仍在，勾选仅表示映射存在，Gate3 自动化已同步新的 WS 恢复检查点。总迁移范围见 [签名订阅评审](signing-subscriptions.md)。

## 接口说明

当前 SDK 通过专用 WS listener 订阅 channel_signing，断线后重新订阅并获取当前待签状态；签名提交继续使用 HTTP RPC。HTTP 的自然 10 秒超时与 WS 恢复分别记录；测试直连查询只核对节点状态，不能当成 SDK 自动恢复证据。

- T 是公共 LSP，A 是 T 托管的一个租户，客户端使用真实 SDK 进程和 A 的有效 token。P 是支付场景中的独立普通节点，路径为 P—T—A；A–T 是私有通道。
- `get_channel_signing_status` 查询当前请求；`submit_channel_signature` 首次应用有效结果返回 `Applied`，完全相同的最近一次已应用结果再次提交返回 `AlreadyApplied`。
- “原样”包含相同的 `channel_id`、`request_id`、`partial_signature` 和 `next_material`；只复用请求 ID 不构成原样重试。请求中的 RPC `id` 只是传输关联号。
- 去重只保存最近一次已应用结果。下一份请求正在等待时，上一份原样重试仍有效；下一份应用后，更早的提交应被拒绝，不能期待永久返回 `AlreadyApplied`。
- agent 按订阅交付的当前状态决定提交什么。响应丢失后，重新订阅可能直接得到下一份请求；本批不要求它必然重发旧请求。旧提交的幂等结果由测试使用保存的原签名直接请求真实 FNN 验证。
- HTTP 请求预算为 10 秒；WS 连接/请求各有 10 秒预算，重连退避从 200 毫秒到 10 秒并加抖动。EventStream 串行等待事件处理确认，处理失败进入重连；这些是当前 agent 的实现参数，不是所有钱包必须采用的 SLA。
- 所有拒绝预期均指真实 FNN 的 JSON-RPC 错误；转发器错误、断线和等待超限只是故障注入或测试失败，不能冒充产品拒绝。

## Spec

### SPEC-01：最近已应用结果幂等
Condition: 所属租户重交最近结果、冲突内容或更旧结果。
Expected: 最近完整相同结果返回 AlreadyApplied；冲突及更旧结果拒绝；当前工作和业务资金不被重复推进。
Observable: 真实 RPC 结果、完整待签、原通道、支付余额及 TLC。
Basis: [签名上下文](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-types/src/channel_signer.rs)。
Source: explicit
Testing: required

### SPEC-02：传输失败后从当前状态恢复
Condition: 真实 SDK 的 HTTP 提交未送达或已应用但响应自然超时。
Expected: 原 SDK 重新建立 WS 订阅，未送达工作首次应用；已应用工作可幂等重交，后续原业务继续。
Observable: 原 SDK 的连接/订阅/交付记录、HTTP 转发及响应证据、签名结果和业务终态。
Basis: [事件恢复](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/events.rs)、[HTTP RPC](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/rpc.rs)。
Source: explicit
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 提交幂等
  - 最近结果重复 LSP-RETRY-01 [primary] -> SPEC-01
  - 相同 ID 内容冲突 LSP-RETRY-02 [primary] -> SPEC-01
  - 更旧结果 LSP-RETRY-03 [primary] -> SPEC-01
  - 支付只结算一次 LSP-RETRY-06 [primary] -> SPEC-01
- 传输故障恢复
  - 原请求未送达 LSP-RETRY-04 [primary] -> SPEC-02
  - 已应用但响应自然超时 LSP-RETRY-05 [primary] -> SPEC-02
<!-- TEST-TREE-END -->

## 待评审用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-RETRY-01` | - [x] A–T 开通过程中，上一份有效签名已首次应用，下一份签名请求正在等待且尚未提交；所属租户连续三次原样重交上一份结果，再完成后续签名 | 首次为 `Applied`，三次重交均为 `AlreadyApplied`；下一份完整待签请求保持不变，重交不导致额外状态推进；继续签名后原通道双方达到 `ChannelReady`，对应同一笔注资 | 正常重试被当成当前请求不匹配，或旧结果消耗下一份请求、重复推进通道 | P0 |
| `LSP-RETRY-02` | - [x] A–T 开通时，上一份结果已应用、下一份仍待签；使用上一份请求 ID，分别仅更换部分签名、仅更换后续公开材料中的一个有效编码值，再重交原始结果并继续签名 | 两种内容冲突均被 FNN 拒绝；下一份完整请求保持不变；原始结果仍返回 `AlreadyApplied`，后续有效签名能让原通道双方就绪 | 仅按请求 ID 去重而吞掉冲突，或拒绝冲突时污染已应用记录及下一轮材料 | P1 |
| `LSP-RETRY-03` | - [x] A–T 完成开通且没有待签请求；取开通过程中最后两份依次应用、ID 不同的结果，先重交较早一份，再重交最后一份 | 较早结果被 FNN 拒绝，不能返回 `Applied` 或 `AlreadyApplied`；最后一份返回 `AlreadyApplied`；原通道仍为双方就绪、无待签，注资对应关系、余额和最新承诺交易哈希不变 | 误把所有历史签名当成可重放，或拒绝旧请求时破坏最近已应用记录 | P1 |
| `LSP-RETRY-04` | - [x] A–T 开通时，SDK 已保存有效 S1但 FNN 未收到；不转发并断开该 HTTP 连接，继续拦住后续提交及重新订阅；观察同一 SDK 自行发起新的 WS 订阅请求，复核 R1后放行 | S1从未到达 FNN，冻结期间完整 R1不变；同一 SDK 成功重新订阅并收到 R1，生成与原 S1相同的提交体，首次上游结果为 Applied；原通道双方就绪，无重新注册或重开通道 | 未送达被误记已应用，或用测试查询冒充 SDK 自动恢复 | P1 |
| `LSP-RETRY-05` | - [x] A–T 开通时 FNN 已 Applied S1；不向 SDK 发送该 HTTP 响应头、正文或主动断线，让其自然经历 10 秒超时；观察原 SDK 自行重新建立 WS 订阅并收到 R2，保持 S2未提交，重交 S1后恢复签名 | 原 SDK 未收到 S1响应且自然超时后重新订阅；真实 FNN 对原样 S1返回 AlreadyApplied，完整 R2不变；原 SDK 完成原通道开通，双方就绪、同一注资且无重复应用 | 把超时误认为未处理，或换传输后恢复检查失效并掩盖重复应用 | P0 |
| `LSP-RETRY-06` | - [x] P 经 T 支付 A 的一张普通发票；A 为该支付生成的首份承诺签名已应用，下一份仍待签；原样重交已应用结果三次，然后恢复全部后续签名 | 三次均为 `AlreadyApplied`，下一份完整请求不变；原支付 `Success`、原发票 `Paid`，相关通道无遗留 TLC 和待签请求；A 仅增加发票金额，P 仅减少金额加实际手续费，T 的净变化等于该手续费，通道均保持就绪 | RPC 看似幂等但重复扣款、重复入账，或支付已显示成功却遗留锁定资金和签名请求 | P0 |

<!-- TEST-CASES-END -->

## 共同前提与时间控制

各场景使用独立环境。开通场景只需 A 一个租户，不重复首批双租户隔离矩阵。使用真实外部注资和 SDK 签名；进入被测通道签名阶段前，已完成外部注资交易的签名提交。

将两份依次产生的不同请求简称 R1、R2，对应 SDK 生成的完整提交为 S1、S2。测试只保存、比较和重交签名，不自行重写 MuSig2。所有者 token、通道 ID、SDK 密钥与存储始终不变。

| 控制项 | 本批具体约束 |
| --- | --- |
| 注入位置 | 先观察真实 `SignatureRequired` 并保存完整请求及签名体。R1 应用后，需要测试 R2 的场景必须先拦住 S2，并确认 FNN 仍在等待 R2，才开始比较；不能紧接 `Applied` 就把正常异步推进误判为重试副作用 |
| 开通有效期 | 沿用普通 funding timeout 的默认 24 小时；按通道 `created_at` 确认进入故障点时仍有至少 180 秒预算。外部注资提交已完成，不能用其原 5 分钟等待窗口给通道签名重新计时 |
| 请求未送达 | 截住 S1、确认其没有上游转发后直接断开连接；此后 SDK 请求也不转发。以同一 SDK 在新 WS 连接上再次发出真实 subscribe 请求为恢复触发事件，复核 R1 后放行，不固定断线秒数；不能把 HTTP 库内部再次发送 S1 当成已经重新订阅 |
| 已应用但响应未送达 | 转发器先取得真实 `Applied`，保持原 SDK 请求无响应且不主动关闭，直到客户端自然超时并自行重新建立 WS 订阅；原响应永不补发。新订阅允许收到真实 R2，但 S2 仍不转发，防止替换最近已应用记录；不固定扣留 12 秒 |
| 事件等待上限 | 两个故障场景复用 60 秒事件等待预算，从截住目标提交开始计时；发生所需事件就继续，不等满上限。它覆盖 agent 的 10 秒超时、WS 连接/订阅、退避及调度余量，只用于发现卡死，不是产品恢复时限；到点缺少事件即失败 |
| 其他有界等待 | 单次直接 RPC 上限 10 秒；等待目标签名请求上限 60 秒；故障解除后等待通道或支付终态上限 120 秒；稳定余额和清理结果再连续观察 5 秒。不满足即失败，不靠反复新建通道或重新发起支付获得通过 |
| 支付有效期 | 发票有效期 1 小时，TLC 基础期限显式为 1 小时，付款端 `tlc_expiry_limit` 为 24 小时，符合 SDK 的至少 15 分钟和最多 48 小时授权边界；支付请求设置 300 秒 timeout。节点还会加入随机延长，不能把基础期限当成实际 expiry。从 A 通道所有移除尚未确认的 TLC 实际 expiry 计算安全截止 D，开始重试前要求距离 D 至少 180 秒，恢复时再次检查余量。本批不跨过 D，也不缩短 TLC 有效期去触发强关 |

持续时间使用单调时钟，TLC 的 D 使用与节点一致的墙上时间。若因环境迟滞跨过业务截止点，该轮不能算短暂故障恢复成功；不把付款失败或强关当成本批允许的另一种结果。

HTTP 超时的观察依据是：真实上游已应用；代理未向 SDK 发送响应头、正文或主动关闭连接；原 SDK 随后重新连接 WS 并建立签名订阅。
结合 agent 串行等待本轮调用、请求具有 10 秒截止的实现，这些事件用来确认客户端结束了无响应等待并恢复工作。
记录提交、上游应用、客户端自然结束 HTTP 等待及 WS 重新订阅的实际时间，核对是否符合该超时路径，但不要求在第 10 秒的某一毫秒精确发生。
若代理提前断开、回送了错误，或 SDK 被外部停止，该轮不能算 HTTP 超时场景。现有 agent 日志可能只保留顶层错误上下文，日志只辅助诊断，不以包含 `timeout` 文案作为唯一证据。
事件按 SDK 来源、租户、通道、方法及签名 `request_id` 关联；测试自己的直连查询不能冒充 SDK 恢复，agent 固定使用的 JSON-RPC `id: 1` 也不能区分提交尝试。

## 场景展开

以下步骤解释同一组六行的操作顺序，不增加其他用例或映射。

### LSP-RETRY-01：上一份重交不能吞掉下一份

1. 在开通中取得 S1，首次提交得到真实 `Applied`；截住下一份 S2，保存完整 R2。
2. 直接向 FNN 原样提交 S1 三次，每次检查 `AlreadyApplied`，随后查询 R2，逐字段比较请求内容、转换、承诺信息及可选结算快照。
3. 放行 S2 与后续签名，检查原通道 ID 在 A、T 两侧就绪，两侧 `channel_outpoint` 相同且指向本次已确认的注资交易。

### LSP-RETRY-02：同一个请求 ID 不能对应另一份结果

1. 建立“R1 已应用、R2 待签”的检查点。保留原 S1，所有更改均作用于它的副本。
2. 分别构造只改 `partial_signature`、只改 `next_material.next_commitment_point` 的提交；使用可解析的标量/公钥编码，且与原值不同，避免 JSON 格式错误掩盖结果冲突。
3. 每次确认是 FNN 拒绝且 R2 完整内容未变，再重交原 S1 确认 `AlreadyApplied`。恢复后续签名并检查原通道双方就绪。

### LSP-RETRY-03：区分最近一次与更早的提交

1. 完成真实开通并保存各次签名的上游结果，确认最后两份不同请求都曾返回 `Applied`；取倒数第二份和最后一份。
2. 等双方就绪、无待签和 TLC、余额及最新承诺哈希稳定后记录基线。先提交倒数第二份，检查拒绝；再提交最后一份，检查 `AlreadyApplied`。
3. 对比基线，确认状态、注资 outpoint、双方余额、最新承诺哈希和无待签状态保持不变。不要求更早结果永远返回固定错误文案。

### LSP-RETRY-04：请求根本没有到节点

1. 截住 SDK 的 S1，确认 FNN 正在等待 R1；不转发 S1，直接断开这次连接，并继续阻断 SDK 到 FNN 的请求。以传输失败触发恢复流程，不伪造 FNN 的 JSON-RPC 错误。
2. 在 60 秒事件预算内观察到同一 SDK 在新 WS 连接发起 subscribe；该请求先不转发，后续 HTTP 提交也保持阻断。测试直连 FNN 复核完整 R1 不变、S1 上游转发次数为零，然后放行订阅。保存真实订阅成功及 R1交付记录，再放行提交；SDK 生成与 S1 相同的签名体并真实转发，第一份上游结果必须是 `Applied`。
3. 继续处理后续签名，检查原通道双方就绪及同一笔注资。无需退出 SDK 进程，不把该用例声称为重启恢复覆盖。

### LSP-RETRY-05：节点处理了，客户端却没收到

1. SDK 发出 S1 后真实转发，确认 FNN 返回 `Applied`；向 SDK 不发送响应头或正文，也不主动关闭该连接，让客户端自己的 10 秒截止结束本次等待。若未取得真实 `Applied`，该故障前提就不成立。
2. 在 60 秒事件预算内观察原 SDK 自行建立新的 WS 连接和订阅，按上述证据确认原 HTTP 无响应等待已自然结束；此时允许订阅交付真实 R2，但仍禁止 S2 到达 FNN。原 S1 响应保持丢弃，保存完整 R2，不把其生成当作第二次应用 S1。
3. 以所属租户身份将原 S1 直接提交 FNN，检查 `AlreadyApplied` 及 R2 不变；解除后续提交限制，由原 SDK 完成开通。测试转发器不得缓存并冒充 FNN 的幂等结果。

### LSP-RETRY-06：支付不能因签名重交多扣一次钱

1. 建立唯一的 P–T 公共通道与 A–T 私有通道，均已就绪且无 TLC；保存各端余额。A 创建普通发票，金额 M 为 1,000,000 Shannon，已知 preimage，允许经 T 的 trampoline 路由；P 仅调用一次 `send_payment`，手续费上限 10,000 Shannon，不使用 MPP。
2. 拦住 A 对这笔支付的首个承诺签名请求：转换为 `SendCommitmentSigned` 或 `CompleteReceivedCommitment`，结算快照必须包含该发票 payment hash。首次应用其签名后拦住下一份请求，三次原样重交已应用结果；记录实际转换并检查 `AlreadyApplied` 和下一份完整请求不变。
3. 恢复后续签名，按原 payment hash 等待 P 的支付 `Success`、A 的发票 `Paid`。两条通道各端仍为就绪，`pending_tlcs` 为空、发送/接收 TLC 锁定余额为零，A 无待签请求。
4. 用最终支付返回的实际手续费 F 对照支付前余额：A 在 A–T 上增加 M，T 在同一通道减少 M；P 在 P–T 上减少 M+F，T 在同一通道增加 M+F，T 两条通道的净增为 F。检查对端镜像余额一致，连续观察 5 秒不再变化。不能只检查 `Success` 或只检查两端金额总和。

本批支付终点是链下支付完成和通道余额一致，不涉及关闭提现；不将这条用例算作超时退款或 watchtower 链上结算覆盖。

## 预期依据与实现边界

- [签名上下文及最近结果判断](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-types/src/channel_signer.rs#L541)：完整结果相同则识别重试，同请求 ID 的不同结果拒绝，应用下一份后替换旧记录。对应前三行；[上游单元测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-types/src/channel_signer.rs#L765)验证了下一份待签时的重交及更旧结果拒绝。
- [节点提交处理](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L2216)：先判断重试，再验证并应用新签名；结果在协议继续前持久化。本批观察 RPC 和外部状态，不因读取不到内部 receipt 就臆造“查询最近结果”的 RPC 字段。
- 当前恢复依据为 [SDK EventStream](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/events.rs) 和 [HTTP 10 秒预算](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/rpc.rs)：事件处理错误触发重连，重新订阅补发当前工作；不得要求响应丢失后必然再发旧签名。
- [SDK 根据当前请求生成提交](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lsp-sdk/src/session.rs#L426)及[已签内容识别](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lsp-sdk/src/signer.rs#L510)：未送达时重新订阅仍得到 R1，SDK 可为相同内容再生成同一签名；已应用时补发可能变为 R2。这里验证的是当前状态驱动的恢复，不假设 SDK 有固定间隔盲重发旧提交的队列。
- [Hosted 上游幂等测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L697)已有 mock 注资下的直接重交；[Hosted 外部签名入站支付](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L842)及 [Bruno 真实支付入口](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/bruno/e2e/lsp-remote-signer-watchtower-revocation/15-node1-pay-hosted-tenant.bru)提供支付路径依据。本批补真实 FNN/SDK、传输故障及完整余额断言，不声称重新验证所有上游签名算法测试。
- 首批隔离测试保留 `_signer_gate.py` 的响应交接方式；本批使用 `_retry_signer_gate.py` 按请求暂停、记录真实上游提交、断开连接或保持无响应，重复提交直接请求真实 FNN。两批共用的开通准备逻辑位于 `_lsp_test.py`，不包含被测重试行为。
- FNN 与 SDK bundle 必须来自同一固定 SHA，启动前校验产物摘要。支付前等待付款节点看到 LSP 的路由公告；连续签名检查点、真实 HTTP 故障及 SDK 重新订阅都必须实际观察到。无法建立规定前提即失败，不能删除断言或改成允许支付失败。
- 复用现有框架及 LSP 测试准备能力；不为本批修改公共框架、`AGENTS.md`、`Makefile`。自动化实现前需恢复清理后缺失的 `source/ckb-cli`。六行各有一个 `TEST-MAP`，勾选仅表示映射存在，不表示运行通过。

进程重启和跨过业务截止的保护继续按区域图后两组单独展开；本批 HTTP 超时不等同于 TLC 签名安全截止。

## 自动化入口

六条用例位于 `test_cases/fiber/devnet/lsp/test_channel_signing_retry.py`，每条对应一个测试方法和唯一 `TEST-MAP`。
每个方法重新创建节点和单个租户；资金结果用原 payment hash、两条通道各端余额及 TLC 清理共同验证。

```bash
# 沿用仓库标准 devnet 准备步骤中的 CKB CLI 路径
cp download/0.202.0/ckb-cli source/ckb-cli
venv/bin/python -m pytest -vv -s test_cases/fiber/devnet/lsp/test_channel_signing_retry.py
python3 scripts/check_test_map.py
```

用户已确认 04/05 修改行；Gate3 已迁移 WS 故障观测及相关 TEST-MAP，并在当前固定 SHA 执行验证。历史源码链接仅作业务规则沿革，当前传输规则以上述固定 head 为准。

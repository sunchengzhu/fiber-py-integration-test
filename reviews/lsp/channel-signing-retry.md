# Hosted LSP 通道签名提交重试与短暂断线用例评审

评审范围：同一租户、同一通道在签名重复提交、提交内容冲突、旧请求重放，以及 HTTP 请求或响应丢失后，保持请求和业务结果一致。包含开通及单笔入站支付；进程重启、业务截止后保护、协作关闭和 watchtower 专项沿用区域图中的后续分组。

源码版本：[Fiber PR #1623](https://github.com/nervosnetwork/fiber/pull/1623)，HEAD `774e61bbe54b8ab335b235458d14df2f8feea23d`，base `271e13c2911247baf6f178be52cab98e23fb5fd4`。测试仓库基线为 `852c97daeb41b9b3824dae184d4952ddad1069d1`。

以上为原始评审依据；当前执行目标为 `8419c005e2d0e737c5abf7e0f881aaedbc6fd300`，FNN、SDK 和测试驱动同源构建。用例 ID 和业务预期不变；构建、运行及 nonce 跨消息复用仅警告的限制见 [LSP 测试说明](../../test_cases/fiber/devnet/lsp/README.md)。

## 接口说明

本轮维护目标为 `8419c005e2d0e737c5abf7e0f881aaedbc6fd300`。新版 agent 通过真实 SSE 事件流及重连快照获取待签状态；下文旧版的“轮询/再次查询”在本轮对应重新建立租户事件流、获取当前待签状态。HTTP 提交仍使用真实 10 秒超时，重试、隔离和业务结果预期不变。

- T 是公共 LSP，A 是 T 托管的一个租户，客户端使用真实 SDK 进程和 A 的有效 token。P 是支付场景中的独立普通节点，路径为 P—T—A；A–T 是私有通道。
- `get_channel_signing_status` 查询当前请求；`submit_channel_signature` 首次应用有效结果返回 `Applied`，完全相同的最近一次已应用结果再次提交返回 `AlreadyApplied`。
- “原样”包含相同的 `channel_id`、`request_id`、`partial_signature` 和 `next_material`；只复用请求 ID 不构成原样重试。请求中的 RPC `id` 只是传输关联号。
- 去重只保存最近一次已应用结果。下一份请求正在等待时，上一份原样重试仍有效；下一份应用后，更早的提交应被拒绝，不能期待永久返回 `AlreadyApplied`。
- agent 每轮先查询当前签名状态，再决定提交什么。响应丢失后，它可能直接处理下一份请求；本批不要求它必然重发旧请求。旧提交的幂等结果由测试使用保存的原签名直接请求真实 FNN 验证。
- HTTP 的 10 秒超时、默认 200 毫秒轮询间隔来自测试用 `fiber-lsp-sdk-agent`，不是 LSP 协议或 SDK 签名库要求所有移动客户端采用的固定值。每轮查询、签名、提交是依次等待的；200 毫秒是轮询间隔，不表示请求仍在等待时每 200 毫秒重发一次。
- 所有拒绝预期均指真实 FNN 的 JSON-RPC 错误；转发器错误、断线和等待超限只是故障注入或测试失败，不能冒充产品拒绝。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-RETRY-01` | - [x] A–T 开通过程中，上一份有效签名已首次应用，下一份签名请求正在等待且尚未提交；所属租户连续三次原样重交上一份结果，再完成后续签名 | 首次为 `Applied`，三次重交均为 `AlreadyApplied`；下一份完整待签请求保持不变，重交不导致额外状态推进；继续签名后原通道双方达到 `ChannelReady`，对应同一笔注资 | 正常重试被当成当前请求不匹配，或旧结果消耗下一份请求、重复推进通道 | P0 |
| `LSP-RETRY-02` | - [x] A–T 开通时，上一份结果已应用、下一份仍待签；使用上一份请求 ID，分别仅更换部分签名、仅更换后续公开材料中的一个有效编码值，再重交原始结果并继续签名 | 两种内容冲突均被 FNN 拒绝；下一份完整请求保持不变；原始结果仍返回 `AlreadyApplied`，后续有效签名能让原通道双方就绪 | 仅按请求 ID 去重而吞掉冲突，或拒绝冲突时污染已应用记录及下一轮材料 | P1 |
| `LSP-RETRY-03` | - [x] A–T 完成开通且没有待签请求；取开通过程中最后两份依次应用、ID 不同的结果，先重交较早一份，再重交最后一份 | 较早结果被 FNN 拒绝，不能返回 `Applied` 或 `AlreadyApplied`；最后一份返回 `AlreadyApplied`；原通道仍为双方就绪、无待签，注资对应关系、余额和最新承诺交易哈希不变 | 误把所有历史签名当成可重放，或拒绝旧请求时破坏最近已应用记录 | P1 |
| `LSP-RETRY-04` | - [x] A–T 开通时，SDK 已生成当前有效提交但 FNN 尚未收到；阻止其转发并断开该 HTTP 连接，继续阻断 SDK 请求；观察到同一 SDK 再次查询该通道签名状态，复核原请求后恢复连接 | 原提交未到达 FNN；SDK 在连接失败后主动开始下一轮查询，阻断期间完整待签请求不变；恢复后同一签名内容首次到达 FNN 返回 `Applied`，原通道双方就绪，没有重新注册租户或重开通道 | 将未送达误认为已应用，或连接失败后 SDK 不再查询、原请求丢失而无法恢复 | P1 |
| `LSP-RETRY-05` | - [x] A–T 开通时，FNN 已首次应用当前签名；不向 SDK 返回该次 HTTP 响应，也不主动断开连接，让其自然经历配置的 10 秒请求超时；观察到原 SDK 开始下一轮查询，保持下一份签名未提交，再原样重交旧结果并恢复后续签名 | 原提交在 FNN 已 `Applied`，SDK 在未收到响应的超时后继续查询；旧结果向真实 FNN 重交返回 `AlreadyApplied`，下一份请求不被消耗；原 SDK 能继续完成原通道开通，双方就绪且不重复注资 | 把响应超时误认为节点未处理，重复应用已完成操作，或客户端超时后停止工作 | P0 |
| `LSP-RETRY-06` | - [x] P 经 T 支付 A 的一张普通发票；A 为该支付生成的首份承诺签名已应用，下一份仍待签；原样重交已应用结果三次，然后恢复全部后续签名 | 三次均为 `AlreadyApplied`，下一份完整请求不变；原支付 `Success`、原发票 `Paid`，相关通道无遗留 TLC 和待签请求；A 仅增加发票金额，P 仅减少金额加实际手续费，T 的净变化等于该手续费，通道均保持就绪 | RPC 看似幂等但重复扣款、重复入账，或支付已显示成功却遗留锁定资金和签名请求 | P0 |

## 共同前提与时间控制

各场景使用独立环境。开通场景只需 A 一个租户，不重复首批双租户隔离矩阵。使用真实外部注资和 SDK 签名；进入被测通道签名阶段前，已完成外部注资交易的签名提交。

将两份依次产生的不同请求简称 R1、R2，对应 SDK 生成的完整提交为 S1、S2。测试只保存、比较和重交签名，不自行重写 MuSig2。所有者 token、通道 ID、SDK 密钥与存储始终不变。

| 控制项 | 本批具体约束 |
| --- | --- |
| 注入位置 | 先观察真实 `SignatureRequired` 并保存完整请求及签名体。R1 应用后，需要测试 R2 的场景必须先拦住 S2，并确认 FNN 仍在等待 R2，才开始比较；不能紧接 `Applied` 就把正常异步推进误判为重试副作用 |
| 开通有效期 | 沿用普通 funding timeout 的默认 24 小时；按通道 `created_at` 确认进入故障点时仍有至少 180 秒预算。外部注资提交已完成，不能用其原 5 分钟等待窗口给通道签名重新计时 |
| 请求未送达 | 截住 S1、确认其没有上游转发后直接断开连接；此后 SDK 请求也不转发。以同一 SDK 对该通道再次发出 `get_channel_signing_status` 为恢复触发事件，复核 R1 后放行，不固定断线秒数；不能把 HTTP 库内部再次发送 S1 当成已开始下一轮查询 |
| 已应用但响应未送达 | 转发器先取得真实 `Applied`，保持原 SDK 请求无响应且不主动关闭，直到客户端自然超时并开始下一轮签名状态查询；原响应永不补发。新查询允许看到真实 R2，但 S2 仍不转发，防止替换最近已应用记录；不固定扣留 12 秒 |
| 事件等待上限 | 两个故障场景复用 60 秒事件等待预算，从截住目标提交开始计时；发生所需事件就继续，不等满上限。它覆盖 agent 的 10 秒超时、下一轮间隔及调度余量，只用于发现卡死，不是产品恢复时限；到点缺少事件即失败 |
| 其他有界等待 | 单次直接 RPC 上限 10 秒；等待目标签名请求上限 60 秒；故障解除后等待通道或支付终态上限 120 秒；稳定余额和清理结果再连续观察 5 秒。不满足即失败，不靠反复新建通道或重新发起支付获得通过 |
| 支付有效期 | 发票有效期 1 小时，TLC 基础期限显式为 1 小时，付款端 `tlc_expiry_limit` 为 24 小时，符合 SDK 的至少 15 分钟和最多 48 小时授权边界；支付请求设置 300 秒 timeout。节点还会加入随机延长，不能把基础期限当成实际 expiry。从 A 通道所有移除尚未确认的 TLC 实际 expiry 计算安全截止 D，开始重试前要求距离 D 至少 180 秒，恢复时再次检查余量。本批不跨过 D，也不缩短 TLC 有效期去触发强关 |

持续时间使用单调时钟，TLC 的 D 使用与节点一致的墙上时间。若因环境迟滞跨过业务截止点，该轮不能算短暂故障恢复成功；不把付款失败或强关当成本批允许的另一种结果。

HTTP 超时的观察依据是：真实上游已应用；代理未向 SDK 发送响应头、正文或主动关闭连接；原 SDK 随后对同一通道发起下一轮签名状态查询。
结合 agent 串行等待本轮调用、请求具有 10 秒截止的实现，这些事件用来确认客户端结束了无响应等待并恢复工作。
记录提交、上游应用、客户端断开及下一轮查询的实际时间，核对是否符合该超时路径，但不要求在第 10 秒的某一毫秒精确发生。
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
2. 在 60 秒事件预算内观察到同一 SDK 再次查询该通道签名状态；这次查询在恢复前仍不转发。测试直连 FNN 复核完整 R1 不变、S1 上游转发次数为零，然后恢复连接。SDK 重新查询 R1、生成与 S1 相同的签名体并真实转发，第一份上游结果必须是 `Applied`。
3. 继续处理后续签名，检查原通道双方就绪及同一笔注资。无需退出 SDK 进程，不把该用例声称为重启恢复覆盖。

### LSP-RETRY-05：节点处理了，客户端却没收到

1. SDK 发出 S1 后真实转发，确认 FNN 返回 `Applied`；向 SDK 不发送响应头或正文，也不主动关闭该连接，让客户端自己的 10 秒截止结束本次等待。若未取得真实 `Applied`，该故障前提就不成立。
2. 在 60 秒事件预算内观察原 SDK 自行开始下一轮 `get_channel_signing_status`，按上述证据确认无响应等待已结束；此时允许查询真实 R2，但仍禁止 S2 到达 FNN。原 S1 响应保持丢弃，保存完整 R2，不把其生成当作第二次应用 S1。
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
- [SDK agent 轮询](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/fiber-lsp-sdk-agent/src/agent.rs#L177)、[主循环](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/fiber-lsp-sdk-agent/src/main.rs#L115)及 [10 秒 HTTP 超时](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/fiber-lsp-sdk-agent/src/rpc.rs#L67)：本轮调用结束后，主循环才等待默认 200 毫秒再查询；失败不会退出 agent。下一轮状态查询因此是比固定睡眠更直接的恢复观察点；不能要求响应丢失后必然再发旧签名。
- [SDK 根据当前请求生成提交](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lsp-sdk/src/session.rs#L426)及[已签内容识别](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lsp-sdk/src/signer.rs#L510)：未送达时重新查询仍得到 R1，SDK 可为相同内容再生成同一签名；已应用时查询可能变为 R2。这里验证的是当前状态驱动的恢复，不假设 SDK 有固定间隔盲重发旧提交的队列。
- [Hosted 上游幂等测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L697)已有 mock 注资下的直接重交；[Hosted 外部签名入站支付](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L842)及 [Bruno 真实支付入口](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/bruno/e2e/lsp-remote-signer-watchtower-revocation/15-node1-pay-hosted-tenant.bru)提供支付路径依据。本批补真实 FNN/SDK、传输故障及完整余额断言，不声称重新验证所有上游签名算法测试。
- 首批隔离测试保留 `_signer_gate.py` 的响应交接方式；本批使用 `_retry_signer_gate.py` 按请求暂停、记录真实上游提交、断开连接或保持无响应，重复提交直接请求真实 FNN。两批共用的开通准备逻辑位于 `_lsp_test.py`，不包含被测重试行为。
- FNN 与 SDK bundle 必须来自同一固定 SHA，启动前校验产物摘要。支付前等待付款节点看到 LSP 的路由公告；连续签名检查点、真实 HTTP 取消及下一轮查询都必须实际观察到。无法建立规定前提即失败，不能删除断言或改成允许支付失败。
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

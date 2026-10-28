# 真实付款的延迟签名恢复

范围：已通过 [Gate1](hosted-channel-guards-scope.md) 的在线延迟、SDK 完全离线、A 等签时 B 收款三个方向。用户已明确通过 Gate2 的三行、预算和共同断言，2026-10-24 进入 Gate3；Python 自动化与 TEST-MAP 已接入，执行结果另记于[运行记录](../../test_cases/fiber/devnet/lsp/README.md)。已有 RECOVERY、RETRY、SIGN、TIMEOUT 用例不变，不改产品代码；映射存在不表示执行通过。

固定 FNN/SDK：`24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；测试仓库基线 `cf937275618d8e51b35a7537788702cf4b67bc31`。新 PR HEAD 的观察保留在 Gate1，不把本批结果归给未运行的版本。

## 接口和共同前提

- T 为公共 LSP，A/B 为其不同 Hosted 租户，P 为独立付款节点。01/02 使用 P—T—A；03 预先建立 P—T、A—T、B—T，P—T 由两笔付款共用。每行新建 Fiber/SDK 数据与通道；不依赖前一行结果，不重置或消费无关链上资金。
- 各 A/B—T 通道沿用双方各 500 CKB 的私有通道、1 epoch 承诺延迟；P—T 为 P 提供 1,000 CKB 的公共通道。按本次 devnet 合约、协商参数和可信 epoch 时长验证开通；保存各 funding outpoint。开通结束时各通道 `ChannelReady`、无 TLC/锁定额，A/B 无待签，路由已就绪。
- 每个租户使用自己的真实 SDK、原文件存储、token、HTTP 签名 gate 和 WS 代理；本批使用现有 `--ack-held-events`，扣签后 SDK 仍在线且不会仅因测试暂停错误重连。保留全部真实签名校验；gate 只控制传输和记录，不生成签名、不伪造产品成功响应。
- A 金额 `a=1,000,000` Shannon；03 的 B 金额 `b=2,000,000` Shannon，使用不同 preimage/payment hash。分别创建普通 CKB 发票：有效期 3,600 秒，`final_expiry_delta=3,600,000ms`，允许 trampoline、禁止 MPP。SDK 授权：本地创建时间起 1 小时、最小 TLC delta 900,000ms、最大绝对 expiry 为创建起 48 小时；金额、方向和 hash 来自本地意图。
- 每张发票只发起一次真实 `send_payment`：`max_fee_amount=10,000`、`tlc_expiry_limit=86,400,000ms`、`timeout=1,200s`。路由须实际经过已保存的 P—T 与对应租户通道；按 payment hash 保存上游/下游 TLC 的金额、方向、expiry 和 ID，不把相同 channel ID 当作同一付款。SDK 只在已有有效承诺记录确实包含该 TLC 后批准兑现，不能提前标记授权已兑现。
- 普通发票路径的 preimage 已由 `new_invoice` 提供给 FNN；本批验证延迟通道签名与链下付款结果，不声称覆盖安全释放 preimage、hold invoice 或链上取回。

## Spec

### SPEC-01：跨 ACK 活动阈值仍保留原付款
Condition: A 停在含目标入站 TLC 的 CompleteReceivedCommitment，原签名未应用，T 正在等待该承诺的 ACK，业务截止仍有余量。
Expected: 连续跨过普通 30 秒活动阈值后，原通道、待签请求和付款保留；恢复原签名后原付款只结算一次。
Observable: 目标请求/签名、T 发送承诺的协议证据、原 funding、支付与发票终态、TLC 清理和余额。
Basis: [Hosted 等待契约](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/docs/notes/hosted-lsp-remote-signer.md#L109)、[30 秒阈值](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L156)、[活动超时豁免](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L6675)、[上游对应真实付款场景](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L1144)。
Source: explicit
Testing: required

### SPEC-02：离线等待不依赖租户请求
Condition: 已建立原付款检查点，SDK 退出、原 WS 两侧关闭，完整离线区间没有 A 的 HTTP、WS 或 SDK 控制请求。
Expected: T 不因客户端离线提前关闭；原存储启动的新 SDK 能恢复原完整请求及原签名，保持身份和授权，继续原付款。
Observable: 进程和 socket 状态、请求审计、公共侧及链观察、新订阅的真实补发、原业务和资金终态。
Basis: [不要求查询或探测的设计](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/docs/notes/hosted-lsp-remote-signer.md#L111)、[已确认的原存储恢复语义](channel-signing-recovery.md)。
Source: explicit
Testing: required

### SPEC-03：不同租户的付款独立推进
Condition: A 的目标签名持续扣留，B 已有独立可用通道和 SDK；P 经同一 T 向 B 付款。
Expected: B 在 A 未放行时完成；A 随后恢复，两个 payment hash 对应各自发票、金额和费用，共享通道不漏扣或重复扣款。
Observable: B 先成功、A 仍待签且未结算的同一观察点，以及两笔完成后的分通道增量和 T 净路由费。
Basis: [租户隔离契约](channel-signing-isolation.md)与 [每通道独立的 ACK 推进](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L6504)；付款并行是由 Gate1 选定、此轮具体化的组合验证。
Source: inference
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 原付款延迟签名恢复
  - 在线等待至少 35 秒并完成原付款：LSP-PAYMENT-01 [primary] -> SPEC-01
  - SDK 离线且不查询 A，恢复原存储：LSP-PAYMENT-02 [primary] -> SPEC-01、SPEC-02
  - A 等待期间 B 完成，再放行 A：LSP-PAYMENT-03 [primary] -> SPEC-01、SPEC-03
- 后续独立评审
  - 反向开通、watchtower 与链上资金取回 [unanalysed] — 本批不覆盖，完成此组后再选择下一范围。
<!-- TEST-TREE-END -->

## 完整用例

以下三行共享本文的检查点、时间预算及断言；复选框仅表示 TEST-MAP 是否存在。

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-PAYMENT-01` | - [x] P 真实支付 A 一次；A 的 SDK 在线，在目标 CompleteReceivedCommitment 签名未应用且 T 已等 ACK 后，持续扣留并观察至少 35 秒，再提交原 SDK 签名和放行后续签名 | 等待期间原请求和通道保留、原付款未完成、funding 未花费；恢复后原付款 Success、发票 Paid、TLC/锁定额/待签清空，四端余额与实际费用一致并稳定至少 5 秒 | 将用户正常延迟签名误判为通道失活，或恢复只返回 Applied 却丢付款、重复结算 | P1 |
| `LSP-PAYMENT-02` | - [x] P 真实支付 A 一次并到达同一检查点；结束 SDK，确认原 WS 两侧及在途请求均结束后，至少 35 秒完全不请求 A，再用原存储启动并核对原请求和签名后恢复 | 无租户查询的完整窗口内公共侧通道和原付款仍保留；新 PID 的订阅实际补发同一完整请求、首个签名体与原件一致且身份/授权未重建；原付款按共同资金断言完成并稳定 | 保护依赖持续查询或残留订阅保活，或重启靠重新授权、重发付款掩盖恢复丢失 | P1 |
| `LSP-PAYMENT-03` | - [x] A、B 通道先就绪；P 向 A 付款并扣住同一检查点，在 A 持续等签至少 35 秒期间向 B 支付另一张发票，确认 B 已完成且 A 仍未放行，再恢复 A | B 必须先 Success/Paid 且自身 TLC 清理，A 同时仍为原待签/未付款；共享 P–T 只结算 B 并保留 A 锁定额；A 随后成功，六端余额、两笔费用及 T 净收入分别准确且稳定 | 单租户签名等待阻塞其他租户付款，或共享余额/付款上下文串单、漏扣或重复扣款 | P1 |
<!-- TEST-CASES-END -->

## 共同检查点：证明 T 真正在等这笔付款的 ACK

1. 在任何付款之前保存所有通道的基线余额、funding、A 的 `NoSignatureRequired` 和 FNN 日志文件/偏移；03 同时保存 B 基线。确认准备期间签名请求已处理完，A gate 的既有请求完成，再将 A gate 设为扣留所有签名。A 的 SDK 与 Python 租户 RPC 都经同一审计 gate，后续不能走未记录的直连旁路。
2. 调用 A 的 `send_payment` 一次后，必须在 60 秒内得到该付款的 `SignatureRequired/CompleteReceivedCommitment`，保存完整请求 R 和真实 SDK 已保存的签名提交 S。R 的通道、方向、结算 TLC hash/金额/expiry 必须对应 A；`session_evidence.peer_partial_signature` 存在，SDK 验证通过并产出 S；同一 hash 在 T 的 A–T 通道是 offered、在 A 是 received，在 P–T 也存在正确上游 TLC。
3. 从付款前偏移起，要求该通道新出现 `set_waiting_ack(true)` 后发送 `CommitmentSigned` 的日志，时间早于捕获 R；从付款开始到建立检查点，A gate 没有把任何新的签名送到 FNN，也未手工直交或放过 A 的 `SendCommitmentSigned`。A 的唯一对端是 T，R 代表来自 T 的待完成承诺，结合真实 SDK 验证、方向及日志形成归属证据。若最先阻塞的签名不是目标转换，或不能排除 A 自己的发送，不应用它去换一个检查点，本轮报检查点未取得。
4. 这是一组协议与观测证据，**不是直接读取内部 `waiting_ack`**。源码发送路径 [先设置 ACK 并持久化，再发送承诺](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L2157)；A 的接收路径 [保存收到的对端签名并要求 CompleteReceivedCommitment](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L9772)。两侧日志可能继承同一 Network span，不能据此判断公共/租户侧；debug `Scalar(#...)` 是截断值，不能宣称与 RPC 的完整签名逐字相等。
5. 检查点成立后不得出现该 A–T 通道 ACK 被清除或新的承诺发送/版本推进；继续扣住 R，在线时每轮全量比较 R，离线时只被动检查日志并在恢复前全量核对 R。该通道的 `latest_commitment_transaction_hash` 保持检查点值，不能要求共享 P–T 在 B 付款时承诺不变化。

## 时间预算和安全期限

所有时长是测试预算，不是产品 SLA。使用单调时钟记阶段和总预算、墙钟核对业务 expiry；不修改宿主机时间、不停矿或减速节点。每个新等待取阶段、总预算和业务安全期限中最早的截止，不能因轮询或重试重置计时。

| 阶段 | 起点与硬上限 | 必须完成或停止的动作 |
| --- | --- | --- |
| 环境与通道准备 | 本条环境准备开始后 900 秒；不计入后面的付款总预算 | 同源检查、新节点/SDK、全部通道、路由、基线、发票和授权就绪；不足以满足后续期限则准备失败 |
| 付款业务总预算 | A 的唯一 `send_payment` 发出前记 `t_send`，到 `t_send+420s` | 包含检查点、故障、B 付款、SDK 恢复、全部终态和稳定观察；到期非零结束业务判断，不能再等完整子阶段 |
| A 检查点 | 从 `t_send` 起 60 秒，含发送 RPC | R/S、上下游 TLC、公共 T ACK 联合证据及初始安全余量全部成立，记 `t_checkpoint` |
| 02 离线准备 | 从 `t_checkpoint` 起共 20 秒；SDK kill 后退出最多 10 秒 | 旧 PID 退出、所有旧 WS 两端 CLOSED、relay/handler ended、HTTP 在途归零；条件齐全记 `t_offline`，不能把这 20 秒计入无请求的 35 秒 |
| 01/02 等待观察 | 01 从 `t_checkpoint`，02 从 `t_offline` 起连续至少 35 秒，最后完整样本须在 +35 至 +40 秒完成 | 每个完整样本满足等待断言；01 SDK 持续在线，02 零 A 请求；满足最短窗口后立即进入恢复，不额外睡满上限 |
| 03 B 付款与先完成证据 | `t_checkpoint+5s` 前发起 B 的唯一付款；到 `t_checkpoint+120s` 完成 B 全部终态、资金及 5 秒稳定观察 | A gate 全程关闭；B 完成时证明 A 仍 pending。A 总等待也要满 35 秒；两项都满足后的最终混合样本最迟 +125 秒完成，再进入 A 恢复 |
| 02 SDK 恢复 | 无请求观察结束、重新允许 A 请求后 60 秒 | 原存储新 PID、身份一致、新订阅真实补发 R、新进程首个签名体等于 S；gate 仍扣留。恢复开始前业务安全余量至少 240 秒，测试总预算还须至少够 60+15+120+10 秒 |
| 恢复复核与原签名首次送达 | 在线观察/03 混合样本完成或02恢复完成后，共 15 秒 | 核对 R、余量、无抢先应用；解除签名扣留并只手工发起一次原 S 的提交；保存真实响应，后续新请求正常由 SDK 签名 |
| 原付款完成 | 原 S 首次真实 Applied 后 120 秒 | 原 payment hash Success、对应发票 Paid、TLC/锁定额/待签清空及资金正确；不得再次调用 send_payment |
| 成功后稳定观察 | 首个完整成功样本后至少 5 秒，最多 10 秒取得最后完整成功样本 | 所有后续样本均保持成功、余额和 funding 不变；最终样本须仍在总截止内 |
| 清理 | 业务结论后另设 60 秒 | 有界停本条资源，保留失败和日志；清理不能追加成功断言、覆盖原始结果或修改无关进程/数据 |

01 的最大业务阶段和为 245 秒，02 为 325 秒，03 为 330 秒，均小于共同 420 秒总预算；阶段可重叠但不能借其他阶段未用完的时间放宽自身上限。

安全余量与 420 秒测试上限分别检查，**不能要求一个仅剩 420 秒的测试截止同时满足 900 秒业务余量**：

- 暂停前业务允许窗口至少还剩 900 秒。窗口取路径所有相关 TLC 的 FNN 截止、SDK 签名/替代承诺截止、SDK 首次接纳最小 delta 截止、发票/授权到期、以及测试按付款参数从 `t_send` 保守计算的 1,200 秒付款窗口的最小值；03 分别保存 A/B 的上下游数据。
- 1 epoch、可信 epoch 2,000ms 时，FNN 的截止是 `expiry−1333ms`，SDK 更早的签名截止是 `floor(expiry/1000)*1000−1334ms`；首次接纳还需满足 `floor(expiry/1000)*1000−900000ms`。按实际协商参数重新核对，不能把常量推广到其他构建；SDK 相关规则见 [安全预留](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lsp-sdk/src/commitment.rs#L51)、[首次接纳](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lsp-sdk/src/commitment.rs#L485)。即使原 S 已签好，也保守覆盖重启校验与后续签名所需的窗口。
- 放行前业务余量至少 180 秒，且测试总剩余预算足够 15+120+10 秒；02 的 240 秒门槛覆盖恢复启动，不把 180 秒同时拿来覆盖 60 秒启动和 120 秒付款。03 B 发起前先检查已知的发票/授权窗口；发起后从 B 的真实 TLC 快照、同 hash 节点消息日志及 SDK 记录取得实际期限，核对其首次出现时也满足 900 秒余量。不假装发送前已有真实 TLC，也不为取证额外暂停 B；缺少路径期限证据则本次不记为完整通过。
- 离线期间只用已保存 expiry、授权和时钟计算 A 的余量；不能调用会查询 A/SDK 的 `_check_payment_window`。恢复 A 请求权限后先核对原请求/实际期限，确认余量，再放行。
- `timeout=1200` 是请求参数和本地保守预算，不将其到时自动取消视作本批已验证契约；420 秒本地截止独立强制执行。

## 共同断言与采样

- 目标采样间隔 2 秒，每个 RPC 请求完整执行最多 2 秒，整轮采样最多 5 秒，相邻完整样本完成间隔不超过 7 秒；独立读取可以并发，均受剩余绝对预算限制，无隐藏自动 RPC 重试。超时、缺字段、解析失败、断连都不能当成“未关闭/无待签”；任何完整性缺口非零失败，不靠最后一帧补成连续通过。保存原始响应、轮次起止和阶段时间。
- 等待时：P 的 A 付款不是 Success/Failed，在线读取的 A 发票只能为 Open/Received；A–T 和 P–T 为 `ChannelReady`、原 funding 不变且独立 CKB 仍查为 live、无 shutdown hash。对应 TLC 身份/金额/expiry 不变，A–T 双方余额未结算，R 和未送达的 S 不变。03 另按混合观察点核对 B。离线窗口不读取 A，这些 A 侧字段在进入窗口前和恢复时检查，窗口内只使用公共 T/P、CKB、进程和被动日志；不得声称期间逐帧读了 A。
- 活性与故障控制：所需 FNN/SDK/矿工存活；02 只允许 A SDK 预定退出。每个滚动 30 秒内链高增长，公共 RPC 持续正常、日志持续可读，无 actor/节点重启；01/03 的 A 原 WS 会话持续 OPEN，无新的重订阅替代在线等待。自然关流/崩溃必须留证并定位，不能忽略。
- 02 零请求：A 的全部 SDK/Python 租户 HTTP 都经审计 gate，开始时 active=0；整个 `[t_offline, t_offline_end]` 的 HTTP 接收/转发计数、WS 请求数、SDK 控制调用记录不增加，无新 WS 连接，所有旧连接 ended 且上下游 CLOSED。不能用 host token 指定 A、临时打开只读订阅或直连查询绕过审计。公共 T/P 各自使用独立的公共 client。
- 恢复先核对后提交：gate 仍关闭时比较 R 全量字段和 S；02 还要求原 token/tenant ID/绑定/授权保留，新 PID、实际 subscribe 成功及本次新连接真实交付 R，不能使用代理缓存或重建授权。正常启动可能出现内部恢复读写，但不得调用新的注册、开通、invoice/fulfill 授权去补回旧状态。
- `--ack-held-events` 使被扣留的事件已处理，单独 `gate.release()` 不保证 S 再次发送。因此在安全复核后先允许后续签名正常转发，再经审计 gate 手工提交原 S 一次，避免 R 的应用产生下一请求时又被扣留而失去触发。第一笔真正送达的目标请求必须是原 S，真实结果 Applied；如 SDK 在放行时真实重试同一 S，手工请求可返回 AlreadyApplied，但必须有审计证据证明先前真实 Applied、完整体相同，不能仅凭 AlreadyApplied 判成功。不得伪造回执或循环重交直到成功。
- 后续由原 SDK 正常处理新请求，按真实有效承诺再调用兑现授权。A 在暂停检查点前只登记过发票授权，尚未登记兑现授权；恢复后的首次 fulfill 是正常继续步骤，不能重新登记已经存在的 invoice/fulfill 授权去补回丢失的存储。终态要求同一 payment hash Success、同一发票 Paid、A 的 NoSignatureRequired、相关所有通道仍就绪、无关闭交易/funding 消费、所有对应 TLC 及锁定额清空。03 最终包括两笔和三个通道，A/B 均须 NoSignatureRequired。成功后至少 5 秒全部采样不回退，余额没有第二次变化。

### 资金断言：区分余额与锁定额

`list_channels.local_balance` 是尚未扣除 pending TLC 的余额，`offered_tlc_balance` 独立表示发送锁定额；可发送额为 local 减 offered。只有成功兑现并完成 ACK 后才更新余额，见 [余额字段](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L7667)、[可发送额](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L9030)、[兑现记账](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L8247)。不能把 A 的 pending 金额从 local_balance 再扣一次。

以所有付款前的共同基线计算，`fA/fB` 为成功后的实际费用，各自 `0≤f≤10000`；`uA` 在 A pending 时直接取同 hash 的 P–T TLC 金额，最终须等于 `a+fA`，B 同理。

| 观察点 | A—T 的 A/T local 增量 | B—T 的 B/T local 增量 | P—T 的 P/T local 增量 | 锁定额 |
| --- | --- | --- | --- | --- |
| 01/02 A pending | `0 / 0` | 不适用 | `0 / 0` | T→A offered / A received = a；P→T offered / T received = uA |
| 01/02 A 完成 | `+a / −a` | 不适用 | `−(a+fA) / +(a+fA)` | 全部为 0 |
| 03 B 已完成、A 仍 pending | `0 / 0` | `+b / −b` | `−(b+fB) / +(b+fB)` | A—T 仍锁 a，P—T 仍锁 uA，B 的 TLC 和锁定额为 0 |
| 03 A/B 均完成 | `+a / −a` | `+b / −b` | `−(a+b+fA+fB) / +(a+b+fA+fB)` | 全部为 0 |

每腿 remote 增量与 local 相反，两端镜像余额一致；不相关方向锁定额为 0。03 中间 P 的可发送额为 `P基线local−(b+fB)−uA`，A 的原 TLC 不能因 B 完成而消失；最终 T 在三个通道的 local 净增等于 `fA+fB`。同一个 P–T 基线只保存一份，各租户的 payment hash、原始金额、费用、授权和 gate 上下文分开保存，禁止复用一个 `self.payment` 覆盖另一笔。

## 各用例操作顺序

### LSP-PAYMENT-01：在线延迟

1. 完成共同准备并保存基线，扣住 A 签名后发送唯一 A 付款；建立 R/S 和 T ACK 检查点及安全余量。
2. 保持 SDK、原 WS、FNN、矿工运行。从 `t_checkpoint` 连续采样至少 35 秒；全程无 A 签名上送，R、原付款、通道、funding 和锁定额满足共同断言。
3. 在最后完整等待样本后核对余量，按恢复提交规则送原 S 一次并开放后续签名；保留真实 Applied 证据，SDK 继续原流程，在已验证承诺后批准兑现。
4. 120 秒内取得原付款完整终态和四端资金断言，再稳定观察至少 5 秒；保存全部过程与结果。

### LSP-PAYMENT-02：无查询离线

1. 与01相同取得检查点，额外保存原身份、绑定、授权控制记录、R/S、各 WS 连接和审计计数。冻结的是签名转发，不先假装冻结事件等于离线。
2. kill A SDK 并确认旧 PID 退出，在共同 20 秒内完成所有旧 WS 双侧关闭、relay/handler ended、HTTP active=0；记录窗口起点及审计基数。
3. 至少 35 秒禁止 A 的任何 HTTP/WS/控制请求，仅采公共侧/CKB和被动记录；窗口末先完成公共侧样本，再检查审计计数未变，记窗口终点。离线期不检查 SDK records 或 A invoice/status。
4. 确认至少 240 秒业务余量和足够总预算后，结束无请求窗口。保持签名 gate 关闭，用原 store 启动新 PID；60 秒内证明新订阅真正交付完整 R、SDK 产生相同 S、原身份/授权和绑定保留。此阶段的 A 请求单独标为恢复期，不倒算进离线窗口。
5. 按恢复规则核对至少 180 秒业务余量、送原 S 并继续；按01完成原付款和资金稳定性。新发票、新支付、新通道或重建旧授权均不能替代恢复。

### LSP-PAYMENT-03：A 等签，B 先成功

1. 在任何付款前准备两个租户和公共通道，分别完成发票/授权并保存六端基线；各自 gate 和付款上下文独立，B 的 gate 正常转发。
2. 仅扣住 A，发起 A 唯一付款并建立原检查点；在其后 5 秒内向 B 发起唯一付款，A 的签名全程不得放行。B 使用真实 SDK 按正常授权顺序签名。
3. A 持续等待期间采样两笔；B 必须在 `t_checkpoint+120s` 前完成 Success/Paid、B TLC 清理、上述混合资金断言及至少 5 秒稳定观察。混合观察中 A 仍未成功、原 R 不变、S 未上送；共享 P–T 可更新承诺，但只能结算 B，保留 A 的原上游 TLC/锁定额。
4. 满足 B 完成证据和 A 等待至少 35 秒后，在 +125 秒前取得完整混合样本，再核对安全余量、恢复 A；禁止先放行 A 再把两笔最终成功解释为互不阻塞。
5. A 在恢复后 120 秒内完成；核对六端最终余额、每笔实际费用与 T 净收入，TLC/锁定额/待签全部清空，再稳定至少 5 秒。

## Gate3 所需最小夹具与结果边界

Gate3 在 LSP Python 范围复用/扩展：现有 RetrySignatureGate 的全 HTTP 请求与 active 审计、测试 A client 经同一 gate、WS 真实关闭状态、指定请求/日志联合检查点、绝对截止传递及多付款独立上下文。未新增 Rust 测试、扩展 Rust 驱动、直接读写 RocksDB、修改公共框架或产品。

运行记录将区分：检查点/期限/审计证据未成立的准备或证据失败；前提成立后提前关闭、付款失败、资金不符、跨租户阻塞等功能失败；以及依据明确原因定位的环境/夹具故障。不能把所有超时默认归给夹具；节点崩溃、付款未恢复等保留产品候选及原始证据。不能 skip、改成任一终态通过、静默换检查点或无限重跑；需实质改变检查点或预期时返回评审。

本批仅证明固定版本、正常授权有效期内、这三个受控签名等待场景。长时间离线、全部 ACK/重连竞态、业务超期强关、浏览器认证、watchtower、链上资金取回仍未覆盖。用户已明确确认三行、共同检查点、预算与资金断言，Gate3 按实际执行另记结果。

2026-10-23 设计复核：GPT 6.1 sol 独立只读检查固定源码、已有夹具和完整设计，最终无阻断项；未触发 Daybreak，未替代人工 Gate2 确认。`python3 scripts/check_test_map.py`：93 个评审 ID、86 个已映射，本批三行未映射，退出 1 仍为原有孤儿映射/历史 report 快照重复 ID。`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/delayed-payment-recovery.md`：识别 3 行，退出 1 仅报告历史重复 ID，无本批 Spec/树/用例结构错误；组合付款推断仍交人工确认。36 个相对文档路径存在，`git diff --check` 退出 0。未改自动化、产品或运行原始证据，未执行新增场景。

2026-10-24 Gate3：三行已确认并映射到 `test_delayed_payment_recovery.py`。首轮 3/3 通过后，独立复核补齐全部付款通道的 actor 重建检查；冻结后聚焦 1 轮和固定 3 轮共 12/12 通过。首轮及所有复跑的原始证据均保留，详见[本批运行记录](../../test_cases/fiber/devnet/lsp/README.md#24b5c38真实付款延迟签名恢复2026-10-24)。本段不改变已确认的用例、预算或资金断言。

GPT 6.1 sol 已独立复核最终代码与全部运行证据，无本范围剩余阻断项，未触发 Daybreak；受 gate 改动影响的既有 LSP-RETRY-04/05 另跑 2/2 通过。TEST-MAP 为本批 3/3；全仓映射检查因既有孤儿映射和历史重复 ID 返回 1，设计检查因历史重复 ID 返回 1，详见运行记录，不将其描述为检查通过。

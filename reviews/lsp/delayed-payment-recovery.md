# 真实付款的延迟签名恢复

2026-11-07 历史状态（56c）：`LSP-PAYMENT-05` 已实现并在 56c761c 执行一次，**1 passed / 95.22s**；测试补齐 SDK 出站 `authorize_payment`（金额 1,005,000）、P 发票 preimage 和本地 `fulfill`，P 发票 Paid，A payment Success。`LSP-PAYMENT-04` 的旧状态保留如下。最新192130批补入既有合约对齐调用，经GPT-6 Sol High复核后仅执行一次；pytest在setup_class的隔离路径断言报错（1 error in7.60s、exit1）即停。runner向预导入类设置路径，但pytest实际加载另一模块中的类，tmp_path_name仍为None；CKB已在默认tmp启动后才被断言拦下。未执行合约对齐、FNN初始化或任何付款/资金断言。属于本批执行准备错误，不能计产品业务失败或通过。详见最新RESULT（本地证据：`../../report/lsp-payment04-84333ee-20261030T192130/RESULT.md`）。旧批证据保留；固定产品仍为干净`84333eea8488a8afc7e4474aa4bbd0e7e973cee9`。

范围：已通过 [Gate1](hosted-channel-guards-scope.md) 的在线延迟、SDK 完全离线、A 等签时 B 收款三个方向；`LSP-PAYMENT-05` 的 763 正常单笔设计见 2026-11-08 段，不继承本节 `24b5c38`/843 的结论。用户已明确通过 Gate2 的三行、预算和共同断言，2026-10-24 进入 Gate3；Python 自动化与 TEST-MAP 已接入，执行结果另记于[运行记录](../../test_cases/fiber/devnet/lsp/README.md)。已有 RECOVERY、RETRY、SIGN、TIMEOUT 用例不变，不改产品代码；映射存在不表示执行通过。

历史 FNN/SDK：01～03 沿用 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`，04 按其下方 843 记录；当时测试仓库基线为 `cf937275618d8e51b35a7537788702cf4b67bc31`。`LSP-PAYMENT-05` 本批固定 763、测试起点为工程合并提交 `e79d540cda6d03ea8f591101c916f70329ab30b9`；设计和当前结果分别见 2026-11-08、2026-11-09 段。不把历史结果归给未运行版本。

2026-11-08 G1 设计记录（当时未执行；2026-11-09 已获用户确认，实现与执行见文末）：本批评审固定候选 `76307312e8de518c9a32074e6d16867c04de4f86`，只细化 `LSP-PAYMENT-05` 的正常单笔 A→T→P 出站付款、费用/资金守恒和一次经济结算判据。历史 56c 的 `1 passed / 95.22s` 只证明当时 A payment Success、P invoice Paid 以及 SDK 出站授权/本地 fulfill 的已有断言，不证明 763、新增费用/资金/重复执行断言或完整 external-signer outbound E2E。763 文档仍把“complete external-signer outbound payment E2E”列为 prototype 剩余项；本轮只评审正常单笔路径，不把 prototype 状态写成发布完成。

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

### SPEC-04：本地缺授权拒签后由显式批准恢复同一次付款
Condition: 固定843，P通过原P–T–A两条通道支付仅含hash的发票；A的真实SDK尚未保存该hash的付款授权，客户端持有preimage，SDK进程始终在线。
Expected: 无授权时拒绝目标签名且不释放preimage；用户明确补入匹配授权后，由同一SDK通过自然重连收到的原待签请求继续处理，先验证可执行承诺与真实链，再释放preimage使原付款完成；同通道下一笔付款也成功，逐笔及累计资金正确。
Observable: 无预授权的控制记录、含目标hash的完整R、实际WS交付/新连接、对应SDK拒签日志区间、提交及preimage相关HTTP审计、同PID/存储/身份、独立链验证控制结果、两笔付款/发票/四端余额/锁定和稳定样本。
Basis: 固定843 [缺授权拒绝](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/commitment.rs#L471)、[本地发票授权不释放preimage](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/signer.rs#L637)、[事件失败后重载](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/tests/fiber-lsp-sdk-agent/src/events.rs#L83)、[原Agent独立验证后释放](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/tests/fiber-lsp-sdk-agent/src/agent.rs#L557)；本地驱动`_sdk_driver.rs:347～351、538～542`仅调用上述真实授权/事件路径。
Source: inference
Testing: required

### SPEC-05：hosted external-signer outbound payment 正常单笔路径

Condition: T 为 public LSP，A 是 T 的 hosted tenant，A–T 是真实 external-signer 私有通道；P 是普通 Fiber 节点，P–T 为 ChannelReady 公共通道。P（不是 A）用它持有的 preimage `p` 创建普通 CKB 发票：`a=1,000,000` Shannon、`expiry=600s`、`allow_trampoline_routing=true`、`allow_mpp=false`，`H=ckb_hash(p)`。A 的 SDK 对 `H` 做 `inbound=false` 的 `authorize_payment`，金额取本实现的首跳 TLC 金额 `u=1,005,000`（`a + 5,000`），未过期；A 经 tenant token 只调用一次 `send_payment`（invoice、`trampoline_hops=[T]`、`max_fee_amount=10,000`、`tlc_expiry_limit=86,400,000`、`timeout=120s`）。A–T 接纳该 TLC 且 SDK records 确实包含 `H` 后，A 通过自己的 `get_payment(H).payment_preimage` 观察到 `p`、与 P 的 `p` 核对一致，再用该观察值做本地 fulfillment 授权；P 侧持有 preimage，不依赖 A 生成，也不把测试变量直接喂给 fulfill。

Expected: 付款经 A–T 和 T–P 到 P；A `get_payment` 到 `Success`，P `get_invoice` 到 `Paid`；A–T 的 TLC 实测金额为 `u`，T–P 为 `a`；763 直连 trampoline 路由源码期望 `u=a+effective_fee_budget`（本输入为 `1,005,000`），实际费用由 `f=u-a` 从 TLC/四端余额推导，并要求 `f=get_payment.fee`，5,000 是有效预算上限；本输入 exact-amount 路由下实际 f 也应为 5,000，仍以实测 u/四端余额和 `get_payment.fee` 交叉验证，不把授权值单独当 fee；四端结算满足 A 扣 `u`、P 收 `a`、T 在两个通道净收 `f`；终态后两段目标 hash 均无未终止 TLC、无待签、`offered/received` 归零、支持一次经济结算的派生判据（固定单笔输入、两段目标 TLC、四端精确净额、终态清理和稳定窗口共同支持，不按轮询直接计数），P 净增加 `a` 且稳定窗口无第二次变化（测试只创建一张发票，不以 `get_invoice` 证明唯一）；成功终态、余额、费用和支付历史在至少 5 秒稳定窗口内不变。内部合法 attempt/retry 不作为失败，也不把“恰好一个内部记录”作为唯一判据。

Observable: A 的 `get_payment`（含 `payment_preimage`）/SDK `records`、P 的 `get_invoice`、A/T/P 的 `list_channels`；A–T 与 T–P 的 TLC hash/amount/status/ID、四端 `local`/`remote`/`offered`/`received`、通道 outpoint、`send_payment` 调用次数与返回；`routers` 仅作辅助诊断。

Basis: 763 [tenant send_payment](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/docs/notes/hosted-lsp-remote-signer.md#L245-L270)、[PaymentAuthorization exact amount](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lsp-sdk/src/commitment.rs#L83-L98)、[fee cap](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/fiber/payment.rs#L450-L456)、[fee_paid](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-types/src/payment.rs#L994-L1004)、[trampoline balance tests](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/fiber/tests/trampoline.rs#L684-L768)、[hosted outbound/preimage test](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/lsp/tests/signer_isolation/payment_preimage.rs#L20-L110)、[trampoline first-hop amount](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/fiber/graph.rs#L1604-L1651)；[763 phase 5](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/docs/notes/hosted-lsp-remote-signer.md#L617) 仍把 complete external-signer outbound E2E 列为 prototype 剩余项，本 Spec 只覆盖正常单笔路径，不声称完整 E2E/生产 Auto policy。
依据分类：角色/入口与 tenant `send_payment`、费用路径与首跳金额来自 763 explicit 源码/文档；费用/四端资金公式由 763 通用 trampoline 实现/上游测试与本次设计推导；无重复/稳定终态判据是本设计 inference，需 G1 人工确认。
Source: inference
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 原付款延迟签名恢复
  - 在线等待至少 35 秒并完成原付款：LSP-PAYMENT-01 [primary] -> SPEC-01
  - SDK 离线且不查询 A，恢复原存储：LSP-PAYMENT-02 [primary] -> SPEC-01、SPEC-02
  - A 等待期间 B 完成，再放行 A：LSP-PAYMENT-03 [primary] -> SPEC-01、SPEC-03
- 缺授权后的显式批准恢复（固定843）
  - 无授权真实拒签、同PID自然恢复原付款及同通道下一笔资金：LSP-PAYMENT-04 [primary] -> SPEC-04
- Hosted external-signer 出站付款（763 正常路径）
  - P 用自身 preimage 签发普通发票，A 经真实 external signer 单笔出站到 P，并核对费用/资金/一次经济结算：LSP-PAYMENT-05 [primary] -> SPEC-05
- 后续独立评审
  - 反向开通、watchtower 与链上资金取回 [unanalysed] — 本批不覆盖，完成此组后再选择下一范围。
<!-- TEST-TREE-END -->

## 完整用例

01～03共享下文原检查点、时间预算及断言；04只采用SPEC-04及文末独立Gate2约束；05使用下文独立的出站资金/一次结算设计，不套用01～04的P→T→A反向公式。复选框仅表示TEST-MAP是否存在。

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-PAYMENT-01` | - [x] P 真实支付 A 一次；A 的 SDK 在线，在目标 CompleteReceivedCommitment 签名未应用且 T 已等 ACK 后，持续扣留并观察至少 35 秒，再提交原 SDK 签名和放行后续签名 | 等待期间原请求和通道保留、原付款未完成、funding 未花费；恢复后原付款 Success、发票 Paid、TLC/锁定额/待签清空，四端余额与实际费用一致并稳定至少 5 秒 | 将用户正常延迟签名误判为通道失活，或恢复只返回 Applied 却丢付款、重复结算 | P1 |
| `LSP-PAYMENT-02` | - [x] P 真实支付 A 一次并到达同一检查点；结束 SDK，确认原 WS 两侧及在途请求均结束后，至少 35 秒完全不请求 A，再用原存储启动并核对原请求和签名后恢复 | 无租户查询的完整窗口内公共侧通道和原付款仍保留；新 PID 的订阅实际补发同一完整请求、首个签名体与原件一致且身份/授权未重建；原付款按共同资金断言完成并稳定 | 保护依赖持续查询或残留订阅保活，或重启靠重新授权、重发付款掩盖恢复丢失 | P1 |
| `LSP-PAYMENT-03` | - [x] A、B 通道先就绪；P 向 A 付款并扣住同一检查点，在 A 持续等签至少 35 秒期间向 B 支付另一张发票，确认 B 已完成且 A 仍未放行，再恢复 A | B 必须先 Success/Paid 且自身 TLC 清理，A 同时仍为原待签/未付款；共享 P–T 只结算 B 并保留 A 锁定额；A 随后成功，六端余额、两笔费用及 T 净收入分别准确且稳定 | 单租户签名等待阻塞其他租户付款，或共享余额/付款上下文串单、漏扣或重复扣款 | P1 |
| `LSP-PAYMENT-04` | - [x] P向A的hash-only发票发送一次付款，A的SDK缺本地授权而真实拒签；在同一SDK进程补入同hash正确授权，经自然重连恢复原请求并安全释放preimage，原付款完成后在原两条通道再付一笔新hash | 补授权前无目标签名提交或preimage释放；同PID、新WS实际交付原R，补授权后SDK首次实际提交Applied；两笔均Success/Paid，逐笔及累计四端资金/实际费用守恒，原通道和funding保持、TLC/锁定/待签清空并各稳定至少5秒，原付款历史终态及费用不变 | 无授权状态被误签或提前泄露preimage，拒签后无法恢复、需要重启/重发掩盖问题，或后续付款串单及重复结算 | P0 |
| `LSP-PAYMENT-05` | - [x] P（普通节点）用自身 preimage 签发金额 `a=1,000,000` 的普通发票；A 的真实 external-signer 通道和 P–T 路由就绪；A 经 tenant token 只发起一次 `send_payment`，TLC 接纳后取得并核对 preimage 再完成本地 fulfillment 授权 | A payment `Success`、P invoice `Paid`；A 扣款、P 收款、T 净收入与实际费用一致，只发生一次经济结算；终态无未终止目标 TLC、无待签、锁定额归零，P 只结算一次、只增加发票额一次，状态/余额/费用稳定后不再变化 | 把 Inflight 当成功、把授权/首跳金额当实际费用、重复结算或重复 TLC、A 创建发票/方向写反，或只看 Success/Paid 不看资金 | P1 |
<!-- TEST-CASES-END -->

当前 `LSP-PAYMENT-05` 的 `[x]` 只表示已有 TEST-MAP；2026-11-09 已按用户确认的设计补齐费用、四端资金、一次经济结算派生判据、TLC trace 采集和稳定窗口，并改为 A 从自身 `get_payment.payment_preimage` 观察核对后再 fulfill。固定 763 的本次执行结果见文末；复选框本身仍不表示通过，也不代表其他版本或分支已验证。

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

## LSP-PAYMENT-05 评审设计：A→T→P 出站付款、费用与一次经济结算（2026-11-08）

本节只适用于 `LSP-PAYMENT-05`，不得套用 01～04 的 P→T→A 反向资金公式；01～04 的“等待签名”共同检查点也不要求本行复制。05 的输入与 01～04 不同：使用 600s 发票和 600s 授权窗口，而不是上文的 3600s；也不套用 01～03 的 900s 等待签名安全余量/180s 检查。本节保留已确认设计；2026-11-09 的自动化实现与执行结果见文末。

### 角色、输入和前置资格

- T 为 public LSP；A 是 T 的 hosted tenant，A–T 为真实 external-signer 私有通道；P 是普通 Fiber 节点，P–T 为真实的公共通道。**P 签发普通发票，A 发起付款**；不是 A 创建发票。
- P 用自己持有的 preimage `p` 创建普通 CKB 发票：`a=1,000,000` Shannon、`expiry=600s`、`allow_trampoline_routing=true`、`allow_mpp=false`，`H=ckb_hash(p)`；P 的 preimage 不依赖 A 或 T。
- A 的 SDK 在发送前完成 `inbound=false` 的 `authorize_payment`：`H`、`amount=a+effective_fee_budget`（本输入 `1,005,000`）、`hash_algorithm="ckb_hash"`、`expires_at_ms=now+600_000`、`min_tlc_expiry_delta_ms=300_000`、`max_tlc_expiry_ms=now+86_400_000`，且均满足；A 不调用 `authorize_invoice`。`effective_fee_budget=min(10,000, ceil(a*5/1000))=5,000`（763 `payment.rs` 的默认费率与上限；当前测试用 floor，本输入恰好整除）；这里的金额是 exact 首跳 TLC/授权金额（本输入 1,005,000），不单独等于实际费用；实际 `f=u-a`，本路由期望 5,000。`u` 必须从 A–T 实际 TLC 读取；SDK 授权额度只作 exact-amount 前置，不参与 `f` 计算。若 SDK 授权控制未保存或测试输入金额错误，是准备失败；若授权已正确保存且 exact amount 正确、但产品实际 TLC 金额/费用不同，是产品断言失败（exact-amount 契约）。763 `graph.rs` 的直连 trampoline 构造把 source-side amount 设为 `final_amount + max_fee_amount`，因此本输入期望 `u=1,005,000`；这仍是源码/路由依据，不是把授权值当 fee。
- A 经 tenant token 只发起一次 `send_payment`：invoice、`trampoline_hops=[T]`、`max_fee_amount=10,000`、`tlc_expiry_limit=86,400,000`、`timeout=120s`。不手工重发、不直接提交签名、不绕过 gate。
- A–T 接纳目标 TLC 且 SDK `records` 确实包含 `H` 后，A 必须先通过自己的 `get_payment(H).payment_preimage` 观察到 `p`，并与 P 创建发票时使用的 `p` 核对；然后才用这个**观察到的** preimage 做本地 `fulfill` 授权，不能把测试变量直接传给 driver。若 A 侧一直未观察到 preimage，不调用 fulfill、不得判成功。若测试未保存授权、未创建发票、未按设计等待，或本地 fulfill 的调用前置已经取得但测试漏调，按归因规则报准备/编排失败；因产品尚未提供 records/preimage 而按规则不调用 fulfill，不属于漏调。A–T 已接纳且 H 已知、在有效截止内持续等待后仍无 records/preimage，按归因规则归产品断言失败；只有可观察前置实际不可用才归观察/准备限制。前置有效、发送已被接受且观察源合格，但首跳 TLC 到截止仍未创建/接纳，按归因规则保留产品停滞候选，不因“未接纳”归观察失败。

### 四端资金关系

以 `L_A, L_TA, L_P, L_TP` 表示 A 侧、T 的 A 侧、P 侧、T 的 P 侧的 `local_balance`，基线加下标 0：

| 端点/视图 | 中段目标 TLC | 终态 `local_balance` 增量 | 对侧/镜像 |
| --- | --- | --- | --- |
| A（A–T） | offered `u`（`amount=u`） | `ΔL_A = -u` | `Δremote_A = +u` |
| T–A（T 的 A 侧） | received `u` | `ΔL_TA = +u` | `Δremote_TA = -u` |
| P（P–T） | received `a` | `ΔL_P = +a` | `Δremote_P = -a` |
| T–P（T 的 P 侧） | offered `a` | `ΔL_TP = -a` | `Δremote_TP = +a` |

- 实际费用 `f = u - a = ΔL_TA + ΔL_TP`，并由 A 的扣款 `-ΔL_A` 与 P 的收款 `ΔL_P` 交叉验证；`get_payment.fee` 必须等于 `f`，但它只是同一产品返回值，不能单独充当预期。
- 资金守恒：`A_debit = u = a + f`、`P_credit = a`、`T_net = f`；A–T 与 P–T 的 `local+remote` 在基线/终态保持常量，funding outpoint 不变。本输入 `effective_fee_budget=5,000`；763 直连路由源码期望 `u=1,005,000`，所以实际 `f=u-a` 应为 5,000，而不是任意 `0..5,000`。本输入 source/实测期望 `f=5,000`；5,000 由预算/路由推导，不是测试里单独写死的 fee。仍以实测 u、四端余额和 `get_payment.fee` 三者裁决；若实际 f 不是 5,000，先查路由/费用契约，不能靠放宽范围放行。
- 同通道 A/T-A、P/T-P 的 `local` 与 `remote` 必须镜像；不要只核对 P 或只核对 A。本行只能复用 `_views`/`_budget`；`_sample`/`_funds` 是 P→T→A 反向实现，**不得复用**，需写 05 专用采样和资金断言（A 查 `get_payment`，P 查 `get_invoice`）。
- 中段记录目标 hash 的未终止 TLC，不要求某个轮询瞬间两段同时可见（T–P 可能因 P 已持有 preimage 很快结算）；历史 `RemoveAckConfirmed` 记录允许保留，不能要求 `pending_tlcs` 字面为空。若同一段看到两个未终止目标 TLC，不自动判失败，但必须保存 attempt/TLC 历史并确认最终只有一次结算；无法解释则按重复执行失败。终态只要求目标 hash 无未终止 TLC 且 `offered/received` 归零。

### 归因规则（全节唯一口径）

- **准备/编排失败**：测试前置无效，或必要操作未执行（未保存授权、未创建发票、未按设计等待、fulfill 调用前置已经取得但测试漏调、未建立所需通道/基线），或测试自己的采样/输入/编排错误。不能把这种情况报成产品失败。
- **观察/准备限制**：前置有效且操作已执行，但 RPC/日志/字段实际不可用、采集资格不足，或准备消耗导致有效测试预算不足。这是“无法判断”，不是产品通过或失败。
- **产品停滞候选/待归因**：前置有效、`send_payment` 请求已被接受、观察源已确认可用，但到既定有效截止首跳 TLC 仍未创建/接纳，或业务不推进。保留原始 RPC/日志/请求/时间证据，标为候选、待归因；不得仅因“未接纳”归观察失败，也不得在证据不足时武断认定产品缺陷。正常异步等待或第一次未采到 TLC 不等于产品停滞；必须继续有界等待到有效截止，不延长或重置截止。763 `network.rs:5109–5134` 显示 AddTlc 发送与结果处理是异步的，`payment.rs:1217–1249` 显示非终态付款可能继续等待/停止 actor；因此截止无首跳时只能保留候选。
- **产品断言失败**：前置有效，A `Failed`/P `Cancelled|Expired`，或 A `Success`/P `Paid` 后费用、四端资金、TLC 清理、一次结算等关键断言不符；或 A–T 已接纳且 H 已知、在有效截止内持续等待后产品仍不提供本设计要求的 records/preimage 可观察前置。
- **成功**：以上条件全部满足，且 5s 稳定窗口内无变化。

### 采集资格与 TLC 补证边界

- 终态 `list_channels` 只读当前 `all_tlcs`（763 `rpc/channel.rs:518–565`）；成功移除会 `apply_remove_tlc`（763 `channel.rs:8407–8416`），不能保证补回已成功移除的历史 TLC。不能把“终态没有历史”当成“没有发生过”。
- 发送前必须选定并验证一个能保留 `H`、amount、channel ID、TLC ID、expiry 的观察源（trace 日志或其他），记录其级别、字段、路径和本次起始 offset/位置。当前 `_lsp_test.py:220,243` 默认 `fnn_log_level=debug`、`RUST_LOG=info,fnn=debug`；763 的完整 ChannelActor message 上下文来自 `channel.rs:5212–5218` 的 `trace!`，默认 debug 不能假设 trace 已产生。注意 T 侧发送 `AddTlcCommand` 的 Debug 不一定包含分配后的 `tlc_id`；T–P 补证优先使用接收侧 P 的 `PeerMessage(AddTlc)` trace 或另一个经字段校验的源；若源不能同时给出 H/amount/channel/TLC ID/expiry，按采集资格不足处理。
- 采集资格不足（级别/字段/起始位置/权限）→ 观察/准备限制；采集资格足够且完整观测后仍无第二段事件 → 产品停滞/路由候选或产品断言，按是否已有 A–T 首跳 TLC 判断。不得把日志/字段没采到直接当成第二段没有发生。
- 自动化先核对实际 trace 已启用并保存本次起始位置，再强制解析目标付款的完整接收侧 AddTlc；固定源码的格式说明不能替代本次目标事件。实际缺字段或日志不可用仍按上述观察限制处理。

### 观察顺序、路由和重复执行判据

1. **基线**：在 P 创建发票、A 授权之前保存 `self.baseline` 四端视图；两条通道均 `ChannelReady`、目标 hash 无 pending、`offered/received` 为 0、outpoint/funding 固定；A 的 signing status 为 `NoSignatureRequired`；此时 P 发票尚未创建。
2. **发送前授权**：P 创建发票后只确认 `get_invoice(H)` 状态为 `Open`、发票地址由该 `new_invoice` 返回；763 `get_invoice` 不返回 preimage，`p` 是测试/P 侧输入，不能声称从该 RPC 读取。记录测试只调用一次 `new_invoice`；确认 A SDK 已保存 outbound authorization；记录 `send_payment` 只调用一次及返回的 `payment_hash=H`。A 的付款 `get_payment` 在发送前不应被当作成功；本行不要求未创建时的查询结果。
3. **路径证据检查点（中段可选）**：优先在 A–T 已接纳、A 尚未本地 fulfill 时保存 A–T 目标 TLC（实测 u、id/expiry）。T–P 的 TLC 可能因 P 已持有 preimage 很快结算，不得因单段未同时观察到而直接判产品失败；补证只能使用发送前已确认采集资格的 trace/日志或其他源（见上节），并保存 H、a、channel/TLC ID、expiry 与起始位置；T–P 优先用接收侧 P 的 `PeerMessage(AddTlc)` trace 等能给出 tlc_id 的源，T 侧发送 `AddTlcCommand` 的 Debug 不保证 tlc_id；字段不足按采集资格不足处理。终态 `list_channels` 不足以补回已移除历史。`get_payment.routers` 仅 debug 构建可用，release 构建不存在，不能作为 release fallback。若 A–T 已有目标 TLC 而 T–P 在完整观测下始终没有，归产品停滞/路由候选；若 A–T 首跳在截止仍未创建/接纳，按归因规则保留产品停滞候选；只有采集资格/字段/预算不足才归观察/准备限制。正常异步等待或第一次未采到 TLC 不立即判产品失败；若事后仍无法建立两段对应，不能把 Inflight 或单段 TLC 当成功；中段看到同段两个未终止目标 TLC，按上节重试/重复规则保存证据。
4. **本地 fulfill（观察 preimage）**：只在 SDK `records` 已包含该 hash 的 TLC 后，读取 A 的 `get_payment(H).payment_preimage`，断言它等于 P 创建发票的 `p`，再把**观察到的** preimage 传给 `fulfill`；不能在 records 前 fulfill，也不能用测试变量直接代替 A 的观察。若 A 侧未观察到 preimage，不得调用 fulfill 或判成功。
5. **终态与稳定**：用有界 `_rpc` 轮询 A `get_payment(H)` 与 P `get_invoice(H)`，直到 A `Success`、P `Paid` 且目标 hash 无未终止 TLC，以该完整样本的 `finished` 记 `t_success`；随后至少 5 秒（末个完整样本的 `finished-t_success≥5s`，不计样本完成后的本地处理时间；采样间隔不超过 2s，至少 3 个样本，总截止遵循下节有效截止规则）重复采样 `get_payment`、`get_invoice`、A 的 `get_channel_signing_status`、四端视图，要求 status/fee/invoice/余额/outpoint/未终止 TLC 均不变、A 为 `NoSignatureRequired`（无目标待签）。成功轮询不得只返回一次响应就结束。若 A 在前提成立后为 `Failed`，或 P invoice 为 `Cancelled/Expired`，立即按产品断言失败停止，不等待 420s；若 A–T 已接纳且 H 已知、在有效截止内持续等待后 A 仍不暴露 records/preimage，按产品断言失败记录；若前置/发送/观察有效但到截止首跳仍未创建/接纳，按产品停滞候选保留；若观察源不可用/字段不足/预算不足，按观察/准备限制；若测试漏掉必要等待，或 fulfill 调用前置已经取得但测试漏调，按准备/编排失败；因产品未提供 records/preimage 而未调用 fulfill，沿用缺少可观察前置的归因。现有 fulfill 30s、终态 45s 等待上限不变，截止与到期归因统一遵循下节，不能因成功稳定窗口不足而提前降为观察/准备限制。
6. **资金裁决**：对终态四端套用上表公式，核对 `ΔL_A=-u`、`ΔL_TA=+u`、`ΔL_P=+a`、`ΔL_TP=-a`、`f=u-a`、`f=get_payment.fee`、`f=effective_fee_budget=5,000`（763 直连路由的源码期望，非授权值；实测不符即产品/路由断言失败）、P 终态净增加 `a` 且稳定窗口内未观察到第二次变化（派生判据，不是事件计数）、测试只调用一次 `new_invoice`/`send_payment`。不要把 `get_invoice(H)` 的当前状态当作“只有一张发票”的证明；若产品有 `list_invoices`，按 H 过滤记录数量。发送/终态查询走带 `business_until` 的 `_rpc`，不要用无界直接 `client.call`；现有 30s fulfill、45s 终态轮询都必须 cap 到 `business_until`，不能替代 420s 总截止。结果按上文“归因规则”唯一口径区分：准备/编排失败、观察/准备限制、产品停滞候选/待归因、产品断言失败、成功，不能互相替代。A–T 已接纳且 H 已知后产品不暴露 records/preimage，归产品断言失败（可观察前置缺失）；首跳未创建/接纳且前置/观察有效，保留产品停滞候选，不能因“未接纳”直接归观察失败。`get_payment.fee` 是 U128Hex，比较前先转整数。

- **一次经济结算（派生判据）**：每 2 秒读取余额/视图是离散状态快照，不能直接计数全部结算事件。本批固定单笔输入下，`H`、两段目标 TLC、四端精确净额、终态目标 TLC 清理，以及稳定窗口内未观察到第二次变化，共同支持“一次经济结算”的派生判据；不把“采样充分”写成“直接证明恰好一次”。若需要直接事件计数，必须另有能关联 H/channel/TLC 的完整结算事件，本批不新增此场景。内部合法 retry 仍与重复经济执行区分：不是“内部 attempt 恰好 1 个”，也不要求中段某一瞬间每段恰好一个；若 RPC 暴露 session/attempt 则记录但不计数。合法重试可造成瞬时多个/历史 TLC，但最终只能有一次结算；exact-amount 下改变首跳金额/授权会被 SDK 拒签，不能当合法 retry；无证据或出现第二次余额变化则按重复执行失败。不要求产品必须暴露 attempt 字段。`get_payment.routers`（debug 构建）只作辅助，不作为 attempt 数量或唯一判据。
- **路由归属**：优先用保存的 A–T、P–T channel ID/outpoint 与两段 TLC 的 hash/amount 证明 A→T→P；`routers` 只在调试构建可用，不能代替 TLC/通道证据。
- **P 结算一次（派生判据）**：测试只调用一次 `new_invoice`，`get_invoice(H)` 只核对该 hash 的当前发票为 `Paid`；不声称 `get_invoice` 能证明“只有一张发票”。若产品有 `list_invoices`，按 H 过滤记录创建数量。从付款前基线开始持续跟踪 P 的 `local_balance`，覆盖等待 records/preimage、本地 fulfill 和终态观察，不在 fulfill 后重置历史。每个完整样本只允许基线或基线 `+a`，且不允许从 `+a` 回退或出现第二次变化；fulfill 前的超额入账或回退同样失败。相邻完整采样完成间隔不超过 2s；这些离散快照只能检查观察到的变化，不能直接计数全部结算事件；观察到一次基线到 `+a` 的跃迁只是支持证据。最终以固定单笔输入、两段目标 TLC、四端精确净额、终态无活动目标 TLC、稳定窗口无第二次变化共同支持“只结算一次”的派生判据，不能宣称直接观测到恰好一次。不要求 A 的私有历史记录全部为空。

### 预算、版本和证明边界

**有效截止（本行唯一口径）：** 每个等待阶段沿用既定阶段上限，并与 `business_until`、付款 `timeout`、发票/授权到期，以及首跳 TLC 出现后的可用 expiry/安全余量取**当前可用且最早**的截止。新增期限证据只能收紧截止，不能延长或重置阶段计时。本地等待上限是测试预算，不是产品 SLA。

- **付款开始前的预算资格**：准备完成、尚未发送付款时，核对剩余有效预算能覆盖本设计必要观察和 5s 成功稳定窗口；若因准备消耗而不足，报观察/准备限制，不发起付款或扩大预算。
- **已进入合格等待后的到期归因**：前置和采集资格已成立后，时间自然接近截止，不因剩余时间不足成功后的 5s 稳定窗口而提前归为观察/准备限制。继续按原截止有界观察；到截止仍无首跳或业务不推进，依据已取得的证据保留产品停滞候选/待归因；已满足具体失败条件则按产品断言失败。若实际发生 RPC/日志不可用，单独记录观察限制。阶段上限先到但产品业务期限尚未到时，只能报告本测试预算内未完成的候选现象，不能宣称违反产品 SLA。
- **成功后的稳定证据**：只有取得成功终态后才要求至少 5s 稳定窗口。若剩余有效时间不足，记录已观察到的成功状态和“成功稳定证据不足”，不得记为通过，也不得覆盖此前已经成立的产品候选或断言失败。失败/停滞归因不需要预留成功后的稳定窗口。

- 沿用 `HostedTenantFixture` 的现有 `business_budget=420s`、`row_until=preparation_started+480s`；`business_until` 从 `preparation_started` 计算，不是从 `t_send` 重置。`t_send` 只作为观察起点，成功稳定窗口至少 5s。现有 fulfill 等待 30s、终态轮询 45s 均保留各自从阶段开始计算的上限，再受上文最早有效截止约束；成功稳定窗口也必须在有效截止内完成。准备造成的预算不足在付款开始前判断；合格等待中的自然到期按上文归因处理。本轮不重置或扩大任何预算。
- 固定候选 763 的预期需要同源 FNN/SDK/driver bundle、`Cargo.lock`/`build.json`、devnet 合约和目标 SHA 校验；56c 的历史 bundle/运行不能转记为 763。`TestHostedOutboundPayment.setup_class` 已固定允许 763，并保留显式 `LSP_RETEST_REVISION == REVISION` 复验通道；本次运行未设置 retest。继承的启动前门禁检查真实 FNN 版本、bundle revision、FNN/SDK/driver 二进制及本地驱动/chain 源摘要；构建记录保留 Cargo.lock/build.json/SHA。版本门禁的旧843固定通过/763固定拒绝预期已同步，其他套件版本门禁不变。本次使用新的业务证据根和 JUnit/observations，未覆盖 56c 的 `report/lsp-p0-1/d5fix9.xml`；docstring 与分段注释已对齐“P 创建发票，A 支付”。
- 763 文档 phase 5 仍明确写“complete external-signer outbound payment E2E remain”；本行只评审正常单笔路径，不覆盖生产 `Auto` policy、断线恢复、重启、MPP 或完整 outbound E2E。763 `payment_preimage.rs` 只证明 payer 侧 preimage-before-removal，不证明独立 P–T 拓扑；P–T 拓扑与资金由本 Python 用例的真实通道提供。
- **待确认：** 763 是否把“正常单笔 hosted outbound”作为发布契约，而不是 prototype 观察；本行的资金/一次结算断言以固定源码和通用 trampoline 实现为依据，产品范围决定仍需人工确认。

## Gate3 所需最小测试代码与结果边界

Gate3 在 LSP Python 范围复用/扩展：现有 RetrySignatureGate 的全 HTTP 请求与 active 审计、测试 A client 经同一 gate、WS 真实关闭状态、指定请求/日志联合检查点、绝对截止传递及多付款独立上下文。未新增 Rust 测试、扩展 Rust 驱动、直接读写 RocksDB、修改公共框架或产品。

运行记录将区分：检查点/期限/审计证据未成立的准备或证据失败；前提成立后提前关闭、付款失败、资金不符、跨租户阻塞等功能失败；以及依据明确原因定位的环境/测试代码故障。不能把所有超时默认归给测试代码；节点崩溃、付款未恢复等保留产品候选及原始证据。不能 skip、改成任一终态通过、静默换检查点或无限重跑；需实质改变检查点或预期时返回评审。

本批仅证明固定版本、正常授权有效期内、这三个受控签名等待场景。长时间离线、全部 ACK/重连竞态、业务超期强关、浏览器认证、watchtower、链上资金取回仍未覆盖。用户已明确确认三行、共同检查点、预算与资金断言，Gate3 按实际执行另记结果。

2026-10-23 设计复核：GPT 6.1 sol 独立只读检查固定源码、已有测试代码和完整设计，最终无阻断项；未触发 Daybreak，未替代人工 Gate2 确认。`python3 scripts/check_test_map.py`：93 个评审 ID、86 个已映射，本批三行未映射，退出 1 仍为原有孤儿映射/历史 report 快照重复 ID。`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/delayed-payment-recovery.md`：识别 3 行，退出 1 仅报告历史重复 ID，无本批 Spec/树/用例结构错误；组合付款推断仍交人工确认。36 个相对文档路径存在，`git diff --check` 退出 0。未改自动化、产品或运行原始证据，未执行新增场景。

2026-10-24 Gate3：三行已确认并映射到 `test_delayed_payment_recovery.py`。首轮 3/3 通过后，独立复核补齐全部付款通道的 actor 重建检查；冻结后聚焦 1 轮和固定 3 轮共 12/12 通过。首轮及所有复跑的原始证据均保留，详见[本批运行记录](../../test_cases/fiber/devnet/lsp/README.md#24b5c38真实付款延迟签名恢复2026-10-24)。本段不改变已确认的用例、预算或资金断言。

GPT 6.1 sol 已独立复核最终代码与全部运行证据，无本范围剩余阻断项，未触发 Daybreak；受 gate 改动影响的既有 LSP-RETRY-04/05 另跑 2/2 通过。TEST-MAP 为本批 3/3；全仓映射检查因既有孤儿映射和历史重复 ID 返回 1，设计检查因历史重复 ID 返回 1，详见运行记录，不将其描述为检查通过。

## LSP-PAYMENT-04 Gate2：缺授权后的同进程恢复（84333ee）

### 固定输入与去重边界

只新增一个方法、两个唯一付款hash：第一笔故意缺授权，第二笔正常授权后发送作为后续可用性对照。两笔各`a=1,000,000 Shannon`、独立preimage，不做参数矩阵或固定1+3。拓扑为P–T–A，A–T双方各500 CKB，P–T由P注资1,000 CKB，仅建立一次；四端顺序为A、T–A、P、T–P。准备后保存原channel ID/funding outpoint、完整余额基准、SDK PID/启动命令/存储路径和身份摘要。

两张发票均由A的真实tenant token创建：Fibd/CKB、`payment_hash`和`hash_algorithm=ckb_hash`、`expiry=3600s`、`final_expiry_delta=3,600,000ms`、允许trampoline、禁MPP；**没有`payment_preimage`参数**。preimage只留在测试客户端，直至本地授权及之后的安全释放。每hash只调用一次`send_payment`，`max_fee_amount=10,000`、`tlc_expiry_limit=86,400,000ms`、`timeout=1200s`；客户端RPC自动重试关闭。

第一笔先仅生成授权意图而不调用SDK授权：金额a、方向inbound、同hash/算法，`expires_at_ms=创建时+3,600,000`、`min_tlc_expiry_delta_ms=900,000`、`max_tlc_expiry_ms=创建时+172,800,000`。补授权使用这份原意图。第二笔在发送前保存自己的匹配授权。`invoice`控制验证preimage匹配后只保存付款授权；它不等于兑现批准或安全释放。

旧RETRY/PAYMENT/RECOVERY在付款前已有正确授权；SDK单测虽覆盖无授权拒绝，但没有本行真实付款/资金收尾。04不使用取消入口，不重跑已知`cancel_invoice`权限失败。错误金额/方向已保存授权的替换与永久拒绝收尾仍在范围外。

### 完整操作及证据顺序

1. **准备和审计边界。** 使用固定843的现有匹配bundle `report/lsp-invoice-cancel-84333ee-20261030T003644/bundle`。A–T、P–T及路由就绪，四端ChannelReady、无TLC/锁定/待签，funding为live。配置原Agent的独立ChainVerifier，保留`preimage-configure`请求/响应与固定合约目录。开通完成后签名HTTP gate始终passthrough，所有故障模式关闭；它只记录，不扣签、不伪造错误、不主动断线。A的Python RPC和SDK RPC都经过同一审计入口。保存开通后的审计/日志偏移，不清空历史；不留其他并发付款或待签工作。
2. **唯一发送与真实拒签。** 先核对新hash从未有`invoice/payment/fulfill/release-preimage`授权调用，创建hash-only发票并发送一次。60秒阶段内取得完整R：channel ID及结算TLC的hash/金额/方向/expiry对应第一笔，WS实际交给同一SDK；从发送前日志偏移起取得真实“无本地付款授权”错误。错误文本只用于确认故障来源，结合唯一待处理R、原始WS/HTTP和控制历史归属目标；单条日志或空`records`均不足以证明无授权。
3. **拒签观察及自然重连。** 自首个对应拒签证据起连续观察至少10秒，最后完整样本在10～15秒内；每约1秒取一个完整样本，每样本最多5秒，期间不得补授权。记录四端状态/余额/原hash TLC及锁定量；原付款仍非Success/Failed，发票Open或Received，原通道/funding保持，无已结算余额变化。补授权前目标签名**尝试与转发均为零**，没有`settle_invoice/create_preimage`，也没有携带该preimage的其他FNN写请求。需在同一60秒阶段内看到由真实拒签触发的另一个WS连接接受订阅并实际交付完整同R；不能只看到socket建立。缺证据、提前终止/强关或不再保留原R均保存实际状态并停批，不补发付款换分支。
4. **显式补授权和同进程处理。** 保存`t_auth_start`，只调用一次SDK `invoice`控制补入原意图并确认成功；SDK PID、命令、store/token/绑定不变，gate始终放行。60秒内同R由真实SDK产生有效签名，首次实际forward为Applied。自然重连的连接可以在补授权前已建立/交付R，不能强求补授权后再发生一次重连；提交必须属于首次拒签后新连接交付的同R，且补授权开始前没有提交。控制返回成功及单线程处理顺序证明授权保存；不以客户端收到ack的时间强制排序HTTP，因为回复接收存在传输竞争。禁止Python调用`_submit/_release_original`、手动重新订阅/断线、重启SDK或重发原付款。
5. **安全释放并完成第一笔。** 等SDK最新完整本地恢复记录（`complete=true, for_remote=false`）实际包含目标TLC，同时保存version/reference/金额/expiry。随后只调用一次原Agent `release-preimage`；它须经过独立ChainVerifier和`authorize_preimage_release`，在安全批准持久化后由原Agent以tenant token调用`settle_invoice`。要求成功控制响应和真实settle RPC审计；普通`fulfill`或Python直调settle不能替代。缺完整记录则有界等待，不先放preimage试探；安全校验/释放失败即停，不反复释放挑结果。原付款Success、发票Paid，完成下述资金/零占用和至少5秒稳定断言。
6. **同通道第二笔及历史复查。** 新建第二个hash-only发票，先保存它的匹配授权，再唯一发送；同PID自然处理，按相同完整记录/链验证/安全释放路径完成。核对本笔增量与从初始基准累计的资金，两笔各自终态和fee不变、原通道/funding、无待签/TLC/锁定及至少5秒稳定；第一笔恢复成功但第二笔失败不算04通过。

SDK授权拒签是预设故障；其他RPC/解析/审计/版本错误不得当作“拒签成功”。本批对“未泄露preimage”的证明限定为受控输入、SDK控制与完整FNN RPC审计：不向FNN提前提供它，也不声称执行了任意进程内存或全系统信息流证明。不得复用带preimage的普通发票。

### 资金、稳定和业务期限

每笔实际费用`f_i=get_payment(hash_i).fee`，要求`0≤f_i≤10,000`，不写死历史样本的5,000。相对该笔前的稳定快照，四端local增量应为`(a, -a, -(a+f_i), a+f_i)`，remote增量相反；A/T–A和P/T–P的local/remote互为镜像。两笔后相对原始基准为`(2a, -2a, -(2a+f_1+f_2), 2a+f_1+f_2)`，T两条通道净收入恰为`f_1+f_2`。

拒签期间local/remote余额保持初始未结算值；锁定额和目标TLC按实际协议阶段原样保存，不能预写为零或生搬旧“有效签名已保存”检查点的四端锁定形态。出现的TLC必须属于原hash、方向和金额正确，上游金额按真实TLC保存并在完成后核对`a+f_1`。每笔终态必须四端ChannelReady、原channel/outpoint、pending TLC清空、offered/received锁定为0、NoSignatureRequired；独立链查询原funding仍live。每笔成功后至少5秒、5个间隔约1秒的后续完整样本保持余额、终态与fee；最后完整样本最迟成功后10秒。末尾再查两笔历史，不能只依赖当前余额总和。

所有循环受单调绝对截止约束；RPC/控制单次最多10秒、无隐藏自动重试，负向观察样本取更小的5秒总上限。业务安全余量由实际上下游TLC expiry、SDK截断/安全预留、首次接纳最小delta、发票/授权到期以及`t_send+1200s`保守付款窗口共同取最早期限；首次观察拒签时至少900秒，补授权/安全释放前至少180秒。按实际1 epoch协商参数及devnet可信epoch时长核验安全预留，不将旧构建常量推广；原数据缺失或余量不足即停，不改变宿主时间/矿工参数。测试截止与业务余量分别判断，不能拿剩余测试秒数冒充TLC有效期。

### 30分钟总预算与固定执行数量

从Gate3首次实现/准备开始记唯一`t0`，绝对截止`t0+1800s`，不因修正、启动执行器或进入下一阶段重置。阶段均取自身上限与总截止预留清理时间的较早者：

| 阶段 | 硬上限 | 产出与停止条件 |
| --- | --- | --- |
| Python实现及GPT-6 Sol High复核 | 600秒 | 只实现本行；复核未通过或适配需超范围改动则停 |
| 静态/产物/环境检查 | 300秒 | 语法、唯一选择器收集、manifest及辅助源码摘要、干净843产品、端口和空间；不重新构建Rust |
| 新04单次正式执行 | 600秒，含类初始化、准备、两笔和进程收尾 | 仅一个方法一次；失败或超时立即停，不补跑、不追加旧套件或1+3 |
| 证据汇总及自有临时资源清理 | 300秒 | 保存日志、JSONL/JUnit、全部退出码及版本证据；确认自有进程退出、端口释放后清理可重建目录 |

600秒正式执行从pytest子进程启动计时，环境/通道/链验证配置最多180秒（含setup_class，setup_method不得重置起点）；从第一次send起的全部业务最多360秒；最后进程收尾预留60秒。内部阶段上限：拒签取得+10秒观察+自然新连接证据共60秒，显式补授权+原R首次Applied共60秒，第一笔完整记录/安全释放/终态/稳定共90秒，第二笔全流程共90秒，末尾历史和账本核对20秒；这些上限共享360秒且不累加延长它，剩余40秒只吸收观察开销。任一步不足以完整执行后续最小稳定期或安全余量即停止，不能删步骤凑通过。

执行前及过程中宿主可用空间至少8 GiB，本批证据增长不得超过512 MiB；超界停业务并收尾。保留新批原始证据与现有产物、旧快照，不开启VM/退款或清理无关文件。本批无重复试验概率/性能结论；通过只代表两笔固定功能序列。

### 最小适配与结果边界

计划新增`test_cases/fiber/devnet/lsp/test_payment_authorization_recovery.py`，一个`TestPaymentAuthorizationRecovery.test_missing_authorization_recovers_same_process_and_next_payment`方法，一处`TEST-MAP: LSP-PAYMENT-04`。Gate3才把本行复选框改为已映射；本轮不生成文件或收集pytest。

使用本文件专用的`_DelayedPaymentBase`子类复用真实拓扑、`_budget/_rpc/_control/_views`和归档；覆写原`_prepare_invoice`使准备阶段不创建普通发票/不预授权，覆写本类预算并在基类准备结束后立即`gate.release()`。正式发送前再次断言passthrough/无故障；不设会禁止自然重连的`holding=True`。新的hash-only创建、明确授权、安全释放及两笔账本在本文件线性展开；只复用取消测试中的创建输入和`preimage-configure/release-preimage`调用模式，不继承取消流程或其120秒付款超时。

不调用旧`_checkpoint/_sample/_funds/_release_original/_authorize/_finish_and_stabilize`，因为它们分别依赖有效签名检查点、禁止某些实际状态、旧单笔锁定模型、Python代交或普通fulfill。为本场景写少量专用观察/终态断言，保留原始失败数据，不把`_sample`异常一概归为测试环境。共享框架/原01～03/RECOVERY08默认行为保持；若实现发现必须实质修改它们，应先列出影响与必要聚焦回归，不能暗加到已确认600秒执行份额中。

保存：实际命令/版本与匹配产物证据、原始HTTP/WS帧和SDK/FNN/CKB日志、控制调用及其时间、拒签R/自然重送R/首次Applied关联、两个hash的唯一发送、各阶段四端快照、业务余量、完整记录及链验证/安全释放响应、逐笔/累计资金和稳定样本。证据可含开发网测试秘密，不在用户汇报展示token/preimage；归档无需重复复制大型链数据库。

失败分别记录：准备/观测能力不足、产品拒签未发生或提前错误终止、补授权后恢复/安全释放失败、资金/终态/稳定失败、预算或资源停止。只有整条04及第二笔都完成才通过；预设拒签本身不记产品失败，已有#1674/#1706归因不挪给新症状。Gate2交接时本行未映射、未执行；后续状态以本文件顶部及下方Gate3记录为准。

Gate2独立复核：GPT-6 Sol High只读核对完整04行、源码接口、自然重连时序、资金与安全释放、最小适配和30分钟预算，无阻断项。本批“可执行承诺”指SDK验证的最新完整、未撤销本地承诺及真实链funding可花费条件；不广播承诺交易，不据此宣称实际链上取回或退款通过。下一步等待用户确认04这一行、两笔规模、预算及适配边界，再进入Gate3。

Gate2静态检查：设计检查识别4行、退出0，SPEC-04推断预期仍交本轮人工确认；项目映射检查125评审/117映射、退出1，新增04未映射符合Gate2，9个既有孤儿映射保持、无重复评审ID；`git diff --check`退出0。只修改本评审、原Gate1入口及README进度说明，未修改测试/驱动/产品，未构建、收集或运行测试。

## LSP-PAYMENT-04 Gate3：实现已复核，预算与编排停止（2026-10-30）

新增`test_payment_authorization_recovery.py`中的一个方法，复用既有真实SDK控制、HTTP/WS审计和付款拓扑；04已有TEST-MAP，复选框仅表示映射。实现包含缺授权拒签、自然重连交付原请求、显式授权后同进程恢复、真实链验证后释放preimage、下一笔付款及逐笔/累计资金断言。未修改共享辅助代码、Rust驱动或产品，未操作退款。

GPT-6 Sol High指出并复核了完整请求的`payment_amount`字段、签名前实际可见TLC范围、拒签观察窗与自然重连等待的分离三项修正，最终无内容阻断项。但没有记录可证明600秒阶段内完成复核的时间；启动前阶段断言失败，执行者未正确依据退出码阻止下一工具调用，误启动了唯一pytest，发现后立即停止。该编排错误不归因产品，也不扩预算或补跑。

静态/版本适配自检退出0，精确收集1条退出0；pytest仅完成节点初始化的一部分，日志为`no tests ran in 25.93s`、JUnit为0条，观察记录只有`environment_start`及`incomplete`。拒签、补授权、两笔付款和资金断言均未执行；`batch.exit=1`，run.json中的payment04中断记录为125，因停止清理中的PermissionError未写出独立payment04.exit。原始final.json曾记录一个defunct进程，后续独立复查确认自有进程均退出、六端口释放，空临时目录已清除。保留全部原始记录，详见RESULT（本地证据：`../../report/lsp-payment04-84333ee-20261030T181026/RESULT.md`）。


## LSP-PAYMENT-04 Gate3新批：编排修正后单次准备失败（2026-10-30）

新批182922入口强制校验Sol批准、600秒内完成时间、唯一时钟和源文件摘要；离线13项自检通过，独立GPT-6 Sol High复核通过。实际适配/版本检查与精确收集退出0，唯一04运行85.24秒后退出1，batch.exit=1；所有命令结束时间、退出码、清理状态完整保存，未重复181026的编排错误。

失败在setUp的preimage-configure：普通测试环境从CURRENT_TEST及预置链恢复，auth等依赖位于部署交易；固定843原Agent验证器却校验创世第5/6/7输出，首项auth不符而拒绝。已建立通道和四端基准，但尚未创建付款发票或发送付款，因此缺授权拒签、恢复及资金断言均未运行。GPT-6 Sol High只读复核确认该测试环境适配归因，不能计产品业务失败、不能据此认定本地auth文件损坏，也不归入旧#1674/#1706。

本批失败即停，未改产品、驱动或04测试，未重跑或操作退款；自有进程、端口及临时目录已清理，所有新旧证据保留。后续适配须匹配真实合约部署位置而保留独立链/字节校验，不得绕过安全释放检查。完整实际命令、原始配置与控制错误见新批RESULT（本地证据：`../../report/lsp-payment04-84333ee-20261030T182922/RESULT.md`）。TEST-MAP存在，仅表示已映射。


## LSP-PAYMENT-04 Gate3实际部署适配新批：合约字节不匹配（2026-10-30）

按用户授权，新增本地驱动preimage-configure-deployed/release-preimage-deployed，04改用实际部署链配置；旧控制保持不变。Chain::new从可信配置通过Type ID查找真实合约并核对本地字节、确认和主链归属，保留独立ChainVerifier；新释放控制通过原Agent公开ChannelSigner真实执行authorize_preimage_release，持久批准后才使用原tenant token提交settle_invoice，顺序与原Agent私有方法一致。产品及旧链适配器未修改，Python不直接settle，业务与资金断言不变。

GPT-6 Sol High复核通过，13项离线编排自检通过，driver-only构建、静态检查和收集退出0；新批184212仅执行04一次，85.78秒后exit1，batch.exit1。FundingLock实际部署定位和字节/确认检查通过；CommitmentLock链上107784B、SHA256 ebf8614c…，本地80880B、SHA256 a7762721…，在字节检查即停止，后续auth/sighash未验证。尚未创建目标发票或发送付款，无拒签恢复或资金结果。

只读定位到既有Watchtower prepare_isolated_contract步骤：它在独立CKB启动后、FNN启动前将同一Type ID升级至受信字节并核对确认/主链/活输出。04复用了定位器但漏接该准备步骤；归为测试适配遗漏，不归因产品。下一批可以复用既有准备，本批不再修或跑。自有构建及运行目录已清理，匹配bundle和全部新旧证据保留；RESULT与原始字节比较（本地证据：`../../report/lsp-payment04-84333ee-20261030T184212/RESULT.md`）。TEST-MAP仍仅表示已映射。


## LSP-PAYMENT-04 Gate3合约对齐新批：实际pytest类未收到隔离路径（2026-10-30）

本批在源码中补入既有Watchtower合约对齐调用，计划在CKB初始化后、FNN初始化前调用，但本次未执行到；该操作保留Type ID、受信字节、主链和活输出校验。准备阶段共用pytest启动起点180秒，没有重置600秒单条或1800秒整批截止。GPT-6 Sol High代码复核通过，13项编排模拟、6项准备生命周期模拟和精确收集退出0；这些模拟未覆盖真实pytest模块加载，不能视为环境资格通过。

唯一真实pytest **1 error in7.60s**，payment04.exit=1、batch.exit=1，失败即停、未重跑。BOOTSTRAP设置的是完整包名导入的TestPaymentAuthorizationRecovery，pytest默认prepend实际加载basename模块中的另一类；实际cls.tmp_path_name为None。新setup_class先调用super后才检查隔离路径，因此已在默认tmp/contract/node启动CKB。断言在合约对齐之前失败，未启动FNN、未建目标发票、未付款或执行资金断言。执行者和Sol复核均漏掉这一实际加载差异，不归因产品。

**历史隔离表述勘误：**181026、182922、184212的runner使用同一BOOTSTRAP；182922和184212已完成类级初始化，实际也使用默认tmp，而非各批命名的运行目录。181026被中断，具体到达阶段仍以其原日志为准。CKB_CLI_HOME和报告目录分别独立不等于整条运行链隔离。此前“独立运行目录/隔离链”的表述不成立；仅删除命名空目录也不足以证明默认tmp未被使用。原报告与证据不覆盖，产品业务未执行的结论不变。

本批在class异常处理内保存CKB配置/日志，框架teardown已停止并清理本次实际node目录；后续只删除本批命名的空CKB CLI目录，保留默认tmp其他内容、历史证据与旧bundle。最终两组自有进程为空、六端口释放；产品仍固定843且clean，不改产品、不动退款。本批未构建，未产生新的Cargo target。完整结果、命令、JUnit、源码快照、复核与清理见RESULT（本地证据：`../../report/lsp-payment04-84333ee-20261030T192130/RESULT.md`）。04仍已映射、业务未验证；76ID口径保持48通过/2产品失败/26无该版本业务结果。

后续修正应在实际pytest类入口、任何节点启动之前读取并验证隔离路径，记录实际模块名与节点目录；必须用真实pytest收集对象验证设置确实生效。这里只记录下一次所需修正，本批没有修后重跑。

最终静态检查：设计4行exit0（SPEC-03/04为已确认的人工契约提示）；项目映射125评审/118映射，exit1为9个既有孤儿，无新增孤儿或重复ID；diff检查exit0。原始输出保存在本批document-checks.json。这些检查不替代04业务执行。

2026-11-07 `LSP-PAYMENT-05` 结果：真实 A→T→P 付款。A 的 SDK 出站授权和本地 `fulfill` 均成功，P 发票 `Paid`，A 付款 `Success`；`1 passed / 95.22s`。成功路径的费用、资金守恒和重复 TLC 细项仍是后续补强。


## LSP-PAYMENT-05 初版自动化补强与 763 历史结果（2026-11-09）

用户已明确确认本批评审，并授权只实现本条及聚焦验证、自审。本次未扩展其他业务用例；原 ID、P1、TEST-MAP 和用例表行保留。 下列为 PR #16 初版实现的历史正常路径结果；后续自审发现的两处采样漏判及修复验证见下一节，历史通过不能替代修复验证。

- 实现：`test_hosted_outbound_payment.py` 在独立 fixture 上核对四端基线、trace 资格与目标两段 AddTlc，A 通过 tenant RPC 观察前像后才批准 fulfill；断言实际费用、资金镜像、目标 TLC/锁定额/待签清理及稳定终态。内部重试和历史 TLC 不直接计为重复经济执行。
- 固定产品 `76307312e8de518c9a32074e6d16867c04de4f86`，FNN/SDK/driver 同源构建，清单及实际版本校验通过；未修改产品。唯一真实业务方法首轮 **1 passed，runner 106.737s，exit 0**；自审补齐相邻完整采样≤2s的显式断言后，只重跑同一方法，最终版本 **1 passed，runner 97.416s，exit 0**。两轮证据均保留，原始 JUnit 与输入摘要齐全，各轮执行期间输入未变。
- 实测 Shannon 增量：A `−1,005,000`、T-A `+1,005,000`、T-P `−1,000,000`、P `+1,000,000`；两段 TLC 金额为 `1,005,000`/`1,000,000`，实际费用与 `get_payment.fee` 均为 `5,000`。最终版本成功后6次采样，稳定窗口 `5.3080s`；相邻完整采样最大间隔 `1.0655s`，满足≤2s。这是本次固定单笔输入下的一次经济结算派生判据，不是直接事件计数。
- 支持检查：9项离线资金/日志判据检查（含错误方向、重复收款、错误费用、残留锁定、镜像/资金源错误及历史 TLC）和5项 PAYMENT-05 版本门禁检查，共 **14 passed、exit 0**。它们不新增业务用例或 Case ID。
- 本条节点进程由原 fixture 收束，任务运行目录已清理；新版本 bundle、构建及原始运行证据保留，旧56c证据未覆盖。
- 本轮按用户要求自审；未另派模型，不将自审称为独立覆盖审计。新范围仍不包括 MPP、重启、其他 Delivery 状态、Watchtower 或退款，也不将正常单笔通过扩大为完整生产 outbound gate。

完整构建、命令/退出码、原始业务观察、trace 和 JUnit 保存在执行机器的 `local-evidence/payment05-automation-20261109/`（不随 Git 提交）；PR 说明记录可复现的选择器、固定输入与验证摘要。本节仅保留人工可审阅的设计和结果，不提交节点数据、二进制或测试密钥。


## PR #16 两处 P1 采样漏判修复与验证（2026-11-09）

本轮只修复已确认 PAYMENT-05 判据的实现缺口，不改用例行、Case ID、P1、映射或其他业务用例；费用、资金公式、TLC 采集资格和时间预算保持原设计。

- **贯穿全程的 P 余额检查**：初版在本地 fulfill 后才建立 P 的余额变化历史，可能遗漏等待 records/preimage 期间的超额入账或回退。当前以付款前基线初始化同一份历史，每个完整样本立即检查，并延续到 fulfill 后和成功稳定期。只允许基线到基线 `+a` 的单向变化。
- **完整样本间的稳定时长**：初版用裁决时的本地时钟减稳定起点，末个样本之后的本地处理耗时可能凑足 5s。当前只用首末合格完整样本的 `finished` 差值，并在通过记录保存两个时间戳；仍要求至少 3 个样本、相邻完整样本间隔≤2s及原有效截止。
- **先红后绿的离线回归**：新增直接调用真实测试主方法的受控观察回归，覆盖 fulfill 前 `+a→+2a→+a`、`+a→0→+a`，以及成功样本仅跨 2s、末样本后本地处理延迟 3.5s 的场景；另保留正常流程对照。旧主方法配新回归得到 **3 failed / 1 passed、exit 1**，三项预期拒绝均未发生，证明回归能复现旧漏判；这不是 FNN 产品失败。修复后，13项资金/trace/编排检查与5项既有版本门禁合计 **18 passed、exit 0**。
- **修复版唯一真实业务重跑**：同一固定 763 同源 bundle、无 retest override，原唯一方法 **1 passed，runner 97.247s、exit 0**；本轮未重建或改产品。原始10个完整样本包括 fulfill 前3个，P 余额历史为 `100,000,000,000→100,001,000,000` Shannon。A/T-A/T-P/P 净增量依次 `−1,005,000/+1,005,000/−1,000,000/+1,000,000`，实际 TLC 差额与 RPC fee 均 `5,000`。6个成功稳定样本的首末 `finished` 跨 **5.241113s**，与通过记录一致；所有相邻完整样本最大间隔 **1.054705s**；原始 RPC 审计仍为1次发票创建、1次付款提交。
- **自审和证明边界**：检查两阶段使用同一余额历史、稳定时长只来自完整样本、原预算/资金/费用/日志断言未削弱、正常流程仍可通过。未发现这两处 P1 的残余漏判；结论仍是离散采样与精确资金共同支持一次经济结算，不声称直接计数全部内部事件。未另派模型，不称独立复核。

本轮原始回执、JUnit、失败输出、业务 JSONL、原始 FNN trace/SDK 数据、输入摘要和自审/静态检查保存在执行机器的 `local-evidence/payment05-pr16-fix-20261109/`，与初版 `payment05-automation-20261109/`、PR 准备及复核证据分开保留。节点由原 fixture 归档后清理；收尾检查自有进程和任务运行目录为空、六个套件端口释放。证据和节点数据均不随 Git 提交。

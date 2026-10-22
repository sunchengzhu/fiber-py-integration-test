# SSE 签名通知：Gate2 用例评审

范围：已通过的 [Gate1](sse-signing-events-scope.md) 五个方向；只测通道签名通知，不扩展 watchtower、token 刷新、连接容量或五分钟自然轮换。
依据：产品、FNN、SDK 和测试驱动固定为 `40288844157cac8dd7fb025304be276cb1ac1f0b`；测试仓库基于 `v0.10.0 / 6088115`。9 个评审行为已映射到 13 个独立测试方法；04 的五组拒绝输入分别运行，复选框仅表示映射存在，执行结果另记。
新版 ai-test-agent 要求 Spec → 测试树 → 用例；本对话仍称本步为 Gate2，用例通过后才进入 Gate3。

## 共同前提与观察口径

- 每条独立准备公共 LSP T、Hosted 租户 A；隔离和接管行另有 B。每个租户仅有一条私有 CKB 通道，双方各投入 500 CKB。钱包注资签名已提交，真实 SDK 的首份通道签名已保存但被 gate 扣住，未送达 FNN。
- `R1`、`R2` 是同一通道相邻的真实待签请求，`S1` 是 SDK 对 R1 产生的有效提交体；`C1/C2` 表示具体 HTTP 连接，`H1/H2` 表示服务端返回的会话 ID。换连接不一定换会话。
- 通知身份以真实租户 token 为准。记录连接编号、握手会话头、状态码、完整 SSE 帧和时间；不在报告输出 token。被比较的业务内容是 channel ID 与完整 status，不比较 JSON 字段顺序。
- 冻结签名提交后，先直连真实 FNN 保存当前待签集合 E。初始快照读到完整 `lsp.snapshot_complete` 才结束收集，标记前通道签名事件的集合须等于 E，不能仅比较第一条；同一冻结快照中不得重复同一完整请求。事件名与 JSON type 一致、version=1，收到通知不得推进签名状态。
- “新事件”必须由握手/错误请求/接管之后的一次真实签名应用产生。不能拿接管前缓存帧或心跳作为新连接可用、旧连接未受影响的证据。每次产生 R2 后冻结它，读取真实状态复核内容。
- 所有行收尾都关闭只读观察连接，确保同一存储只有一个 SDK 进程，按原身份、绑定与授权继续原通道。若 SDK 使用 `--ack-held-events` 已确认了暂停事件，单独 `gate.release()` 不会让已消费事件重新出现：应先允许后续提交，再把已保存的当前有效签名直连真实 FNN 应用一次，或明确重建 SDK 订阅让当前请求重放；不得由代理伪造 Applied。
- 收尾上限 120 秒：双方同一 channel ID 为 ChannelReady、注资 outpoint 一致且指向本次已确认交易、活动通道仅原来一条、待签清空；再稳定观察 5 秒，状态不二次推进。开通预算在操作前至少剩余 900 秒、放行前至少剩余 180 秒。

## Spec

### SPEC-01：初始快照包含当前未完成工作
Condition: 合法租户已有冻结的待签请求，建立新的 SSE 连接。
Expected: 返回本租户当前待签集合，再发送 snapshot_complete；读取通知不应用签名。
Observable: HTTP 200、text/event-stream、会话头，完整快照事件和签名状态。
Basis: [设计说明](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/docs/notes/hosted-lsp-remote-signer.md#L137)、[send_pending](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/crates/fiber-lib/src/rpc/events.rs#L377)。
Source: explicit
Testing: required

### SPEC-02：新请求沿当前连接推送
Condition: 初始快照结束，旧请求被有效签名推进为下一轮待签。
Expected: 无须重建连接或轮询签名状态，原 SSE 连接送达下一轮请求。
Observable: 同一连接编号上的新事件、无新握手记录、事件后的 RPC 状态比对。
Basis: [设计说明](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/docs/notes/hosted-lsp-remote-signer.md#L137)、[上游集成场景](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L478)。
Source: explicit
Testing: required

### SPEC-03：事件归属由认证租户决定
Condition: 两个租户分别订阅，各有真实待签工作。
Expected: 初始快照及后续事件只包含各自租户的请求；URL 参数不能更换租户。
Observable: 两条流的 channel ID、完整请求、参数请求的拒绝结果。
Basis: [认证及参数限制](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/crates/fiber-lib/src/rpc/events.rs#L166)、[设计说明](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/docs/notes/hosted-lsp-remote-signer.md#L122)。
Source: explicit
Testing: required

### SPEC-04：无效订阅在占用会话前被拒绝
Condition: 合法流已建立，同时出现缺少/无效 token、operator token、查询参数或格式错误会话头的请求。
Expected: 缺少 Bearer 返回 401；无效或 operator token 返回 403；合法 token 携带查询参数或非 32 位十六进制会话 ID 返回 400；不返回签名事件、不改变原会话。
Observable: 真实服务端 HTTP 状态、错误响应，以及原连接在拒绝后收到的新请求。
Basis: [serve 的拒绝顺序及上游测试](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/crates/fiber-lib/src/rpc/events.rs#L199)。精确状态码为当前实现观察，随本表提交人工确认，不绑定错误文案。
Source: observation
Testing: required

### SPEC-05：正常重连保留会话并补回当前待签
Condition: 有效请求尚未提交，连接断开；同租户以原会话重连。
Expected: 服务端接受原会话并补发相同请求；真实 SDK 在传输恢复后自动携带原会话重连，无须重启 SDK 或重新开通道。
Observable: 新连接、相同会话头、相同请求、同一 SDK PID、实际签名提交和原通道终态。
Basis: [重连规则](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/docs/notes/hosted-lsp-remote-signer.md#L137)、[SDK 重连实现](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/tests/fiber-lsp-sdk-agent/src/events.rs#L36)。
Source: explicit
Testing: required

### SPEC-06：补发当前状态，不重放已完成历史
Condition: R1 已应用，R2 仍待签，期间无其他签名提交，建立恢复连接。
Expected: 完整初始快照与当前 R2 一致，不含已完成 R1；未完成 R2 在多个连接出现不视为重复应用。
Observable: snapshot_complete 之前的完整事件集合、真实待签状态和签名应用结果。
Basis: [pending-state recovery 说明](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/docs/notes/hosted-lsp-remote-signer.md#L137)。
Source: explicit
Testing: required

### SPEC-07：主动接管只替换所属租户的通知会话
Condition: A 有会话 H1，新连接用 A token 且不带会话头；B 有自己的活动会话。
Expected: A 新连接获得 H2 并关闭旧流；带 H1 重连返回 409，不能挤掉 H2；B 不受影响。此结果不表示旧 token 被撤销或签名提交权限消失。
Observable: 新旧会话头、旧流结束、旧会话的拒绝状态、新 A 及原 B 连接的后续事件。
Basis: [会话接管及边界](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/docs/notes/hosted-lsp-remote-signer.md#L145)。
Source: explicit
Testing: required

### SPEC-08：旧 SDK 被接管后停止自动重试
Condition: 旧 SDK 已处理完当前事件并回到读取流程，服务端会话被同租户新连接接管。
Expected: 旧 SDK 在旧流结束后携带原会话重连，收到 409 即结束事件读取器；不去掉会话头重新接管，不影响新会话。
Observable: SDK 的真实握手及 409、读取器结束原因、驱动自行退出、没有后续订阅请求；新连接仍可推进事件。
Basis: [SDK 409 分支](https://github.com/nervosnetwork/fiber/blob/40288844157cac8dd7fb025304be276cb1ac1f0b/tests/fiber-lsp-sdk-agent/src/events.rs#L62)、[当前本地驱动](../../test_cases/fiber/devnet/lsp/_sdk_driver.rs)在读取器结束后退出。驱动退出是观察手段，不是所有钱包必须退出进程的契约。
Source: explicit
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 通道签名通知
  - 通知送达
    - R1 已存在，新订阅完整快照含 R1 且不推进签名：LSP-SSE-01 [primary] -> SPEC-01
    - 原连接快照结束，应用 S1 后收到 R2，无轮询或重连：LSP-SSE-02 [primary] -> SPEC-02
  - 身份隔离与拒绝
    - A/B 同时有待签，快照和新请求只进入所属连接：LSP-SSE-03 [primary] -> SPEC-03
    - 非法认证、参数或会话格式被拒，原连接仍能接收新请求：LSP-SSE-04 [primary] -> SPEC-03 SPEC-04
  - 断线恢复
    - HTTP 客户端带原会话重连，未提交 R1 原样补回：LSP-SSE-05 [primary] -> SPEC-05
    - SDK 传输断开后自行带原会话重连，并继续原签名：LSP-SSE-06 [primary] -> SPEC-05
    - R1 已完成且 R2 待签，恢复快照只含 R2：LSP-SSE-07 [primary] -> SPEC-06
  - 客户端接管
    - 新 A 替换旧 A，旧会话 409，新 A 与原 B 继续收事件：LSP-SSE-08 [primary] -> SPEC-07
    - 旧 SDK 收到真实 409 后停止读取和重连，新会话保持有效：LSP-SSE-09 [primary] -> SPEC-08 SPEC-07
  - 后续边界
    - watchtower 事件与链上结算 [pending] — 不在已批准首批范围，后续从 watchtower-settlement-scope.md 继续
    - token 到期/刷新、300 秒自然轮换、容量与慢消费者 [pending] — 留待后续凭证/传输边界批次，入口为 rpc/events.rs 与 SDK events.rs
    - FNN 重启后会话重建、冷租户、跨 listener 及快照并发窗口 [pending] — 本批不声称覆盖；后续分别核对会话内存生命周期和订阅/快照时序
<!-- TEST-TREE-END -->

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-SSE-01` | - [x] A 的 R1 已冻结且 SDK 已保存 S1；停止准备用 SDK，再以 A token 建立新订阅，读完初始快照，最后恢复真实签名完成原通道 | 返回 200、SSE 类型和有效会话 ID；快照恰含 R1 的完整内容，读取前后 R1 未改变；原通道最终就绪且注资一致 | 新连接漏掉已有待签工作，或收到通知被误当成签名完成 | P0 |
| `LSP-SSE-02` | - [x] A 的只读连接 C1 已读完含 R1 的快照；直连 FNN 提交真实 S1，期间不查询签名状态、不重连，等下一轮通知后再查状态 | S1 首次 Applied；C1 收到不同 request ID 的 R2，其完整内容与随后查询一致；没有新 SSE 握手，原通道最终就绪 | 看似推送正常，实际必须轮询或重连才能收到下一份请求 | P0 |
| `LSP-SSE-03` | - [x] A、B 各有冻结 R1 和独立订阅；读完双方快照，再分别应用各自真实 S1，持续读取双方连接 | 每个快照仅含所属请求；A/B 的新 R2 分别进入原连接，所有观察到的签名事件均属于本租户；两条通道最终各自就绪 | RPC 已隔离但 SSE 仍泄露其他租户请求，或一个租户的更新被推给另一个 | P0 |
| `LSP-SSE-04` | - [x] A 合法连接保持待签；独立环境分别发送缺少 token、无效 token、operator token、A token 加 tenant=B 参数、A token 加畸形会话头的请求；拒绝后应用 A 的 S1 | 依次按参数返回 401、403、403、400、400，无签名事件；A 的原请求及会话未被替换，原连接收到拒绝之后产生的 R2，原通道能就绪 | 无权订阅窃取请求，或错误请求挤掉合法客户端造成拒绝服务 | P0 |
| `LSP-SSE-05` | - [x] A 的 C1/H1 已读完 R1 快照且从未提交 S1；关闭 C1，确认传输结束，以同 token 和 H1 新建 C2 | C2 被接受且仍返回 H1；完整快照原样补回 R1，待签状态未推进；之后真实签名完成原通道 | 普通重连被当成旧设备拒绝，或未完成请求在断线后丢失 | P1 |
| `LSP-SSE-06` | - [x] A 的真实 SDK 已收到 R1 并保存但未转发 S1，暂停响应已确认处理；只切断它的 SSE 传输，保持进程和存储，恢复网络后观察其自动重连并放行 | 同一 SDK PID 自行携带 H1 重连并获得相同 R1；再次产生相同有效提交体，首次真实应用为 Applied，原通道完成；不靠测试手工订阅代替 SDK 恢复 | 服务端允许重连，但真实 SDK 丢会话、漏签或需要人工重启 | P1 |
| `LSP-SSE-07` | - [x] A 的 C1 收到 R1；真实 S1 已 Applied、R2 已产生并冻结后关闭 C1，以 H1 重连并读完新快照 | 新快照与当前 R2 完整内容一致且不含 R1；R2 未被通知读取应用，最后原通道完成 | 恢复时重放已完成任务、漏掉新任务，或把重复通知误当重复结算 | P1 |
| `LSP-SSE-08` | - [x] A、B 均有原始订阅和冻结请求；用 A token、不带会话头建立新 A 连接，旧 A 带 H1 尝试重连，随后分别应用 A/B 的 S1 | 新 A 获得不同的 H2 和原待签快照，旧流结束；H1 重连 409；新 A 和原 B 各收到之后产生的 R2，双方最终完成原通道 | 旧会话抢回连接、接管误伤其他租户，或旧流清理错误释放新会话 | P1 |
| `LSP-SSE-09` | - [x] A 真实 SDK 已处理完暂停事件，仍持有 H1；只读新客户端主动接管，等待旧 SDK 自己重连、被拒和退出，再推进新连接的事件 | 旧 SDK 的真实重连携带 H1 并收到 409，读取器以接管终止路径结束，驱动自行退出且无新订阅；新连接收到后续请求，随后单个 SDK 以原存储恢复完成原通道 | 服务端拒绝旧会话后 SDK 仍无限重试或省略会话头反复抢占 | P1 |
<!-- TEST-CASES-END -->

## 检查点和执行方式

### 两种客户端分工

01～05、07、08 主要验证服务端：准备 SDK 先生成并保存真实 S1，随后停止该进程并确认原流关闭；Python 只读流负责观察，不伪造签名。需要推进一轮时，直接提交保存的 S1；R2 出现后不提交，保持内容稳定供比较。完成观察后用原 SDK 存储继续，恢复订阅是明确的收尾接管。

06、09 验证真实 SDK：保留原进程，通过 LSP 局部转发器记录真实握手和事件。使用已有 `--ack-held-events`，暂停响应必须及时返回；观察驱动的“saved signature held; SSE stays connected”记录，确认处理确认已发送后才触发断线/接管。不得让 SDK 卡在当前 HTTP 提交或等待 processed 的阶段，再把不重连误判为停止。

09 由一个只读 HTTP 客户端接管，不启动第二个写相同存储的 SDK。旧 SDK 退出后才允许重启；不要求旧 SDK 退出码为 0，但必须同时有真实 409、读取器结束原因及无其他 panic/无关异常的证据。若日志不足以区分结束原因，回到设计补观察方式，不能只凭进程消失判通过。

### 各行重点

- 01：E 在连接前取得，直到 snapshot_complete 不放行任何签名；比较完整集合及原状态，防止只读到一条就提前成功。
- 02：S1 提交到收到 R2 期间不调用 `_pending()` 等带签名状态轮询的辅助方法；读到事件后才允许 RPC 交叉核对。C1 指同一次握手对应的 HTTP 流，不仅是相同 H1。
- 03：双方从初始快照开始持续收集。依次推进 A、B，使双方都确实产生新事件；读到预期新事件后各继续观察一个 25 秒心跳周期加 5 秒余量，检查全部已收事件的归属及流仍有效。有限观察不是“永远不泄露”的证明。
- 04：五组请求使用独立环境和相同判据；每组错误后仍由原 C1 收到新 R2。URL 参数请求带 A 的有效 token 和 B 的真实 tenant ID；B 是独立真实身份。不要让辅助客户端自动重试、自动接管或把 4xx 隐藏成通用连接失败。
- 05：关闭客户端及上游真实响应，不把读取超时当作断线；C2 必须明确携带 H1，不能省略头后把主动接管算成恢复。
- 06：只注入一次可确认 EOF 的传输中断，FNN/SDK 均不重启，不反复拒绝重连制造长退避；取得重连后再次捕获的 S1，比较原提交体，记录首次真实 Applied，再恢复后续签名。
- 07：关闭前先取得并冻结 R2；以重连完整快照为判据，不把 C1 中尚未读完的旧帧混入 C2；验证 R1 缺席不以“等几秒没看见”替代快照结束标记。
- 08：先确认新 A 的 H2 和快照，再观察旧流结束及 H1 的真实 409；旧连接可读到此前已交付的缓存帧，不把它们误算为新事件泄露。两次新事件均在接管/旧重连拒绝之后主动产生。新 A 暂时离线时旧 H1 是否仍被拒绝，留后续扩展，不暗示本行已覆盖。
- 09：需要同时记录握手序列、409 响应到 SDK、读取器结束原因和进程退出；在 409 后 65 秒窗口内不得出现任何后续订阅（含省略 session ID 的请求），同时验证新流可用。不得主动杀死旧 SDK 来满足停止断言。

## 有界等待及来源

| 阶段 | 上限和判据 | 原因 |
| --- | --- | --- |
| HTTP 握手/直连提交 | 10 秒；保留真实 HTTP/RPC 结果 | 沿用 SDK 连接预算与现有 RPC 预算 |
| 冻结待签准备、快照或新事件 | 各最多 60 秒；读到目标事件/标记立即推进 | 本地事件等待预算，容纳节点调度；不是产品 SLA |
| 旧 HTTP 流关闭 | 新会话握手成功后最多 10 秒 | 接管会取消旧流；不足时报告失败，不等 300 秒自然轮换冒充取消 |
| SDK 自动重连及 409 到达 | 断线/接管起最多 60 秒；以真实握手和响应为准 | 最大退避 30 秒，加 10 秒连接预算和调度余量；此批不注入 429/Retry-After |
| SDK 读取器结束及驱动退出 | 已收到 409 后最多 10 秒；不得有正在等待的测试提交 | 409 是停止分支，不再等待一次完整退避；结束原因须可归因 |
| 停止重试的补充观察 | 409 后观察满 65 秒，订阅计数不增加 | 大于最大 30 秒退避与 10 秒连接预算；仍须结合读取器结束证据，不以短时间静默单独判断 |
| 同一连接仍可用 | 所有同连接断言须在其 300 秒自然寿命内完成；观察前核对剩余预算 | 不能把自然换连接算成原连接推送；预算不足属于准备失败，不自动重连掩盖 |

300 秒寿命、25 秒心跳来自 FNN `EventLimits::default`；30 秒最大退避和 10 秒连接预算来自官方 SDK `events.rs`。客户端解析器持续读流、为每步设单调时钟截止，超时输出最后状态和事件，不无限阻塞或用长 sleep 代替判据。

## Gate3 实现

- [`test_sse_signing_events.py`](../../test_cases/fiber/devnet/lsp/test_sse_signing_events.py) 实现 9 个行为、13 个独立方法；04 的五组输入各自准备环境。
- [`_sse_observer.py`](../../test_cases/fiber/devnet/lsp/_sse_observer.py) 按帧读取真实 SSE，保留握手及会话信息，支持切断指定连接和回收读取线程；不合成事件、session ID 或 409。
- 复用 `RetrySignatureGate` 扣住真实提交，仅为它增加可覆盖的 SSE 转发入口，默认行为不变。03/08 使用独立租户上下文；已 ACK 的暂停事件由本文件的局部恢复步骤收尾。公共 framework、Makefile、AGENTS.md、Rust 驱动及产品源码未改。
- 2026-10-22 在 `4028884` 上运行整个 SSE 文件及原有 `test_identical_retry_preserves_next_request`：`14 passed in 1314.14s`，退出码 0；其中新增 SSE 13 个方法、旧回归 1 个，无失败、错误或跳过。命令见 [LSP README](../../test_cases/fiber/devnet/lsp/README.md#sse-通道签名通知)，原始报告位于 `report/lsp-sse-4028884-20261022/regression.{log,xml,html,exit}`。
- GPT 6.1 sol 已对照本表完成只读代码复核，并核对最终日志和 JUnit，未发现需要修改的问题。映射勾选与运行结果分别核实，不代表整个 PR 验收。
- 设计与映射检查均已运行，退出码均为 1：既有历史报告副本造成重复评审 ID，原有 `PMP-01～05`、`SETTLE-01` 仍为孤儿映射；本批 9 个 ID 无重复评审行、无漏映射，04 对应五个方法，其余各一个。未跨范围修改历史资料。

本表精确状态码含当前源码观察（SPEC-04），随用例整体提交确认。其余未选边界见测试树和 Gate1，不通过降低断言扩大覆盖口径。

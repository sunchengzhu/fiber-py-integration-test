# LSP WebSocket 签名订阅用例评审

订阅过滤 Gate3 已完成：用户确认20～28九行、28数组兼容及150分钟预算后，进一步明确授权改用LSP分支最新代码。本批固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，十二个方法已映射，正式1+3共48/48、相关3/3通过；实际构建、自检、预算及证据见[运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-订阅过滤-gate3完成2026-10-29)。此前04产物准备失败保留历史，不转记通过。已完成的浏览器鉴权 Gate3：`LSP-SUBSCRIPTION-14～19`，固定 `04c206465b48da85b99aa58e80afe9801a2cb2db`，Gate1/Gate2 已获用户确认；新六行已接入映射，正式1+3共44/44通过，相关既有14方法回归14/14通过，见 [浏览器鉴权运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-浏览器鉴权-gate32026-10-26)。01～07、10～13 保留已批准行为；2026-10-26 在 04 上的 14 方法回归通过见 [运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-websocket-既有订阅回归与下一步2026-10-26)。以下迁移经过和24版结果保留历史依据，不替代本次843过滤批次的实际结果。

历史迁移批次沿用已通过的 [Gate1 范围](signing-subscriptions-scope.md)，将现有事件与恢复用例迁移到 WebSocket 签名订阅。固定目标为 [PR #1623](https://github.com/nervosnetwork/fiber/pull/1623) 的 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；用户已明确通过 Gate2；FNN/SDK/测试驱动已在该提交同源构建，本批核心与订阅 30 个方法已在该版本通过；完整 40 条回归为 38 通过、2 失败，残余问题见测试目录 README，历史结果不转记为本版本通过。

用户先要求同时迁移 ID 与映射，随后选择完整前缀 `LSP-SUBSCRIPTION-*`：原 01～07 对应迁移为 `LSP-SUBSCRIPTION-01～07`；原 08/09 退休，不复用；新行为从 10 开始。Gate3 已将 Python 文件和测试名称迁移为签名订阅，并同步 TEST-MAP；本表勾选只表示映射存在，执行结果见测试目录 README。

## 既有行为的共同前提与观察口径

- T 是启用认证的公共 FNN，A/B 是两个不同的 Hosted 租户，P 是独立普通节点。各行使用独立环境，A–T/B–T 为私有 CKB 通道，真实 SDK 完成批准、注资验证、绑定及签名。只读观察器不生成签名。
- 专用 `rpc.ws_listening_addr` 从 WS 握手的 `Authorization: Bearer <token>` 保存凭证，认证在随后 RPC 调用时执行；不能把携带凭证等同于握手阶段拒绝。通过 `subscribe` 订阅 `channel_signing`。凭证须允许 `write("subscriptions")` 及对应 topic 读取，身份来自凭证。常规环境重新签发当前 token，不拿旧版缺少订阅权限的 token 冒充当前协议故障。
- C 表示连接，U 表示该连接返回的订阅 ID；保留其字符串/数字类型，以 `params.subscription == U` 关联 `subscribe` 通知。比较 `params.result.type` 与完整 `data`，不能只检查 channel ID 或日志。
- R1/R2 是同通道先后产生的完整 `SignatureRequired` 请求，S1/S2 是真实 SDK 已保存的完整提交。转发器冻结提交，独立 RPC 保存当前请求作为比较基准。签名 body 包含 `channel_id`、`request_id`、`partial_signature`、`next_material`。
- 建立订阅只补发当前待签请求，没有 `snapshot_complete`、历史游标或 session ID。每行预先冻结待签集合，收到预期内容后继续有界观察；需要证明“不投递”的场景，在观察窗口之后用同一订阅收到主动产生的正向事件证明它仍有效。ping、socket 未断开不够。
- 负向观察窗口为 5 秒，之后的正向事件最多等待 60 秒；持续收集并检查到正向事件到达为止。它只证明本次窗口内的行为，不宣称证明无限历史、严格 exactly-once 或同一毫秒的订阅/写入竞态。取消后旧缓冲帧不算违规，判断使用取消成功后才产生的新请求。

用户已明确确认调整后的 [过滤参数 Gate1](signing-subscriptions-scope.md#2026-10-28过滤参数补充-gate1)，本轮进入 Gate2：固定 04 每租户仅一条私有通道，覆盖默认/显式全集、空集及异常边界；多通道严格子集保留缺口。新行 20～28 的共同前提、输入与预算仅见文末新节，不套用前文浏览器批次的执行数量和预算；旧行不变。

## Spec

### SPEC-01：建立订阅补发当前待签，状态变化持续推送
Condition: 已认证的所属租户订阅通道签名主题，存在冻结的待签请求，随后真实应用该请求。
Expected: 新订阅收到当前完整待签；同一订阅随后收到新状态。重连只恢复当前待签，不回放已应用的历史；读订阅本身不推进业务。
Observable: 订阅 ID、完整 typed notification、直连查询、真实提交结果和原通道终态。
Basis: [订阅与恢复规则](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/subscription.rs)、[状态补发与去重](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/subscription/service.rs)。
Source: explicit
Testing: required

### SPEC-02：凭证决定权限与节点范围
Condition: 客户端通过 WS 握手头提供凭证后调用订阅或取消；凭证属于 A、B 或 operator。
Expected: 缺失/无效凭证及缺少必要权限的请求拒绝；有效租户只收到本租户状态，operator 获得 host 范围而非租户私有待签内容；失败请求不破坏已有合法订阅。
Observable: subscribe 的 JSON-RPC 拒绝、各订阅的完整状态内容，以及错误操作后合法订阅的正向事件。
Basis: [RPC 调用时认证](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/middleware.rs)、[认证、topic 权限及 scope](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/subscription.rs)、[租户 token 能力](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/lsp/token.rs)。
Source: explicit
Testing: required

### SPEC-03：真实 SDK 从断线恢复当前工作
Condition: SDK 已完成暂停事件的处理确认，连接明确断开，SDK 进程与存储保持。
Expected: SDK 自行重连和重新订阅，从仍待签的原请求生成相同提交并首次应用，业务完成；不需要测试手工订阅代替它恢复。
Observable: 同 PID 的新连接和成功订阅、补发内容、真实 SDK 提交及原注资对应的就绪通道。
Basis: [EventStream 连接、处理确认和退避](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/events.rs)。
Source: explicit
Testing: required

### SPEC-04：并存订阅独立，取消受连接所有权约束
Condition: 同一租户在同连接或不同连接建立多个订阅，随后请求取消。
Expected: 各订阅独立接收状态；取消本连接所属订阅返回 true，其他连接的 ID 和未知 ID 返回 false，其他订阅继续工作。
Observable: 各连接的 ID 与通知、unsubscribe 布尔结果、取消后才产生的新状态的投递去向。
Basis: [订阅注册与按连接取消](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/subscription.rs)。
Source: explicit
Testing: required

### SPEC-05：浏览器子协议接入及编码兼容
Condition: 固定 04 的专用 WS listener 开启认证；连接提供 fiber-rpc 与凭证子协议，或使用普通 Bearer header。
Expected: 当前注册 token 是未填充 base64url，可原样用作凭证子协议后缀；旧格式去除尾部填充后可用于该后缀；Bearer 接受带/不带填充的同一 token。浏览器握手成功仅选择 fiber-rpc，不回显凭证协议。
Observable: 实际 HTTP 101、Sec-WebSocket-Protocol 响应值、相同 token 字节及完整当前/实时签名状态，最终原通道就绪。
Basis: [固定 04 浏览器鉴权契约](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L44)、[注册 token 编码](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/lsp/token.rs#L59)。
Source: explicit
Testing: required

### SPEC-06：歧义和编码错误在握手阶段拒绝
Condition: 携带凭证子协议但缺 fiber-rpc、多个凭证、同时携带 Authorization header 与凭证子协议，或凭证后缀为空/非法 base64url。
Expected: 服务端返回 HTTP 400，不升级为有效 WS 连接；已有合法订阅继续接收新工作。普通 Bearer 不要求 fiber-rpc。
Observable: 真实服务端握手响应、未获得订阅 ID、原连接的完整新 R2 与最终原通道状态。
Basis: [凭证归一化拒绝条件](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/middleware.rs#L25)、[握手拒绝响应](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/mod.rs#L254)。
Source: observation
Testing: required

### SPEC-07：浏览器入口保留 RPC 权限和租户范围
Condition: 编码及协议组合合法，浏览器凭证已通过握手归一化；随后订阅 channel_signing。
Expected: 无效 Biscuit、缺订阅写权限或缺 topic 读取权限仍在 RPC 阶段拒绝；有效 A/B 凭证只收到各自私有状态，拒绝请求不影响合法订阅。
Observable: HTTP 101 后的真实 JSON-RPC 拒绝及无事件、权限正向对照、A/B 完整 R1/R2 归属和原通道终态。
Basis: [同一 Biscuit 权限规则](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L54)、[RPC 授权及范围](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L249)。
Source: explicit
Testing: required

### SPEC-08：过滤对象选择当前及后续工作
Condition: 固定 04 的有效 A 凭证在 channel_signing 上指定默认、显式或空过滤集合，A 有唯一私有通道及冻结 R1。
Expected: 省略 options、null、{}、channel_ids:null 均选择授权全集；[A] 与重复 A 只表示同一通道；空 channel_ids 数组可成功注册但不接收该通道的初始或后续事件。
Observable: 原类型订阅 ID、完整 R1/R2、冻结窗口内相同工作无重复、空订阅取消 true、原 SDK 完成原通道。
Basis: [04 RPC 过滤定义](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L114)、[初始化与实时过滤](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L84)、[重复 ID 合并](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L208)。null 和去重按固定实现提出兼容预期。
Source: observation
Testing: required

### SPEC-09：参数解析与过滤数组长度分层拒绝
Condition: 有效凭证在已建立 WS 上提交不合法的 topic/options/Hash，或超过 256 项的 channel_ids。
Expected: 类型/格式解码失败返回 -32602；256 个重复有效 A 可接受，原数组 257 项在去重前返回 -32001；错误请求不建立订阅且不破坏原合法订阅。
Observable: 实际请求与同 request ID 的 RPC error、无 result/残留通知、原合法订阅仍收到真实 R2，以及最终原通道就绪。
Basis: [长度检查](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L69)、[业务错误 -32001](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L353)、锁定 jsonrpsee 0.25.1 的 render_server.rs/params.rs（完整静态路径见文末）。具体 code 为固定实现观察，不绑定易变错误文本。
Source: observation
Testing: required

### SPEC-10：指定不可见通道使整次订阅拒绝
Condition: A 的有效凭证指定不存在的 X、真实 B 私有通道，或与 A 通道混合。
Expected: 单个不可见 ID 和两种顺序的混合列表都返回 -32001，无成功订阅或部分工作；不能借过滤改变身份、暴露 B 工作或破坏 A 原订阅。
Observable: X 不存在、B 自身 R1/R2 的正向对照；A 连接所有帧的订阅归属及完整内容；原 A/B 通道完成。
Basis: [租户 store 选择](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L288)、[任一通道缺失即失败](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L208)、[初始化后才接受](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L343)。
Source: observation
Testing: required

### SPEC-11：options 数组的固定版本兼容
Condition: 完整 RPC 参数解析最终将 options 交给 Option<SubscriptionOptions>；结构体只有一个 channel_ids 字段。
Expected: 用户已确认将固定 04 接受 [null]、[[]]、[[A]] 的实现兼容纳入回归，分别等价于默认全集、空集、单 A；[]、[null,null]、[A] 仍应解析拒绝。不把该兼容声明为未来 API 保证。
Observable: 前三者的真实订阅及与对象形式一致的事件集合；后三者 -32602，原合法订阅仍工作；全部原通道完成。
Basis: [单字段结构体](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-json-types/src/subscription.rs#L20)、固定 Cargo.lock 的 serde/serde_derive 1.0.228、serde_json 1.0.151；完整静态推导见文末，不是运行证据。
Source: inference
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 当前工作与实时状态
  - 初始完整待签 LSP-SUBSCRIPTION-01 [primary] -> SPEC-01
  - 同订阅下一请求 LSP-SUBSCRIPTION-02 [primary] -> SPEC-01
  - 未提交请求重连补发 LSP-SUBSCRIPTION-05 [primary] -> SPEC-01
  - 已应用历史不补发 LSP-SUBSCRIPTION-07 [primary] -> SPEC-01
- 认证及隔离
  - 双租户初始与后续事件 LSP-SUBSCRIPTION-03 [primary] -> SPEC-02
  - 无效凭证和缺少权限 LSP-SUBSCRIPTION-04 [primary] -> SPEC-02
  - operator 的 host 范围 LSP-SUBSCRIPTION-10 [primary] -> SPEC-02
- SDK 自动恢复
  - 同进程真实重订阅 LSP-SUBSCRIPTION-06 [primary] -> SPEC-03
- 独立订阅与取消
  - 同租户不同连接并存 LSP-SUBSCRIPTION-11 [primary] -> SPEC-04
  - 本连接取消一个订阅 LSP-SUBSCRIPTION-12 [primary] -> SPEC-04
  - 外连接和未知 ID 不可取消 LSP-SUBSCRIPTION-13 [primary] -> SPEC-04
- 浏览器凭证接入（04 新批次）
  - 当前注册 token 原样接入及协商响应 LSP-SUBSCRIPTION-14 [primary] -> SPEC-05
  - 同一 token 的三种编码/入口兼容 LSP-SUBSCRIPTION-15 [primary] -> SPEC-05
  - 五种握手拒绝输入及原连接存活 LSP-SUBSCRIPTION-16 [primary] -> SPEC-06
  - 合法编码但无效 Biscuit 的 RPC 拒绝 LSP-SUBSCRIPTION-17 [primary] -> SPEC-07
  - 缺写/缺读分别拒绝且互补权限可用 LSP-SUBSCRIPTION-18 [primary] -> SPEC-07
  - 两个有效浏览器租户的初始及实时隔离 LSP-SUBSCRIPTION-19 [primary] -> SPEC-07
- 过滤参数（04 Gate2 新批次）
  - 对象形式的选择集合
    - 四种默认值均恢复并推进工作 LSP-SUBSCRIPTION-20 [primary] -> SPEC-08
    - 显式 A 与重复 A 不扩增工作 LSP-SUBSCRIPTION-21 [primary] -> SPEC-08
    - 空集成功注册且保持无事件 LSP-SUBSCRIPTION-22 [primary] -> SPEC-08
  - 请求拒绝与授权原子性
    - 16 个格式输入分四个独立实例拒绝 LSP-SUBSCRIPTION-23 [primary] -> SPEC-09
    - 未知 ID 及有效/未知混合整拒 LSP-SUBSCRIPTION-24 [primary] -> SPEC-10
    - 真实 B ID 及有效/B 混合整拒且无泄露 LSP-SUBSCRIPTION-25 [primary] -> SPEC-10
  - 原数组长度边界
    - 256 个重复 A 接受并去重 LSP-SUBSCRIPTION-26 [primary] -> SPEC-09
    - 257 个重复 A 在去重前拒绝 LSP-SUBSCRIPTION-27 [primary] -> SPEC-09
  - options 顺序字段形式
    - 三种数组形式与对应对象的选择集合一致 LSP-SUBSCRIPTION-28 [primary] -> SPEC-11
    - 空/过长/错误字段数组拒绝 LSP-SUBSCRIPTION-23 [ref] -> SPEC-11
- 后续范围
  - watchtower 事件及链上结算 [unanalysed] — 已有独立范围草稿；本批完成后回到 watchtower Gate1。
  - 同一授权范围内多条真实待签通道的严格子集 [pending] — 固定 04 Hosted 单通道约束；后续支持多通道或独立 host 外部签名拓扑须另评，不用 A/B 隔离替代。
  - 命名 params 的运行覆盖 [pending] — 数组兼容的命名参数路径已静态核同源；本批线级用例仅用位置参数，不宣称命名入口执行通过。
  - 订阅容量及 token 运行中到期 [pending] — 另批确认，不计入过滤参数覆盖。
<!-- TEST-TREE-END -->

## 待评审用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-SUBSCRIPTION-01` | - [x] A–T 开通中冻结 R1，SDK 已保存 S1 但从未提交并退出；A 新建通道签名订阅，收到当前工作后复核 R1，再用原存储继续签名 | 返回订阅 ID U；U 收到与预存 R1 完全一致的待签内容；只读期间 R1 不变；恢复签名后原通道双方就绪，注资身份一致 | 初始工作遗漏、内容被截断，或订阅本身推进签名状态 | P0 |
| `LSP-SUBSCRIPTION-02` | - [x] A 订阅 U 已收到冻结 R1；应用真实 S1，冻结后续 S2；期间不重连、不查询，收到后再直连核对 R2，最后恢复签名 | S1 首次返回 Applied；原 U 主动收到不同请求 ID 的完整 R2，与随后查询一致；原通道最终双方就绪 | 实时通知漏发或发送旧内容，客户端只能靠查询继续 | P0 |
| `LSP-SUBSCRIPTION-03` | - [x] A/B 各有冻结 R1 并分别订阅；核对初始工作，依次应用各自 S1 并冻结各自 R2，在完整观察窗口及后续正向事件中检查归属，再完成两条原通道 | 各订阅只收到所属租户的完整 R1/R2，不含另一租户私有请求；两条原订阅均实际收到各自新 R2，最终两条原通道就绪 | 初始补发或实时通知跨租户泄露，或用失效连接的静默掩盖隔离错误 | P0 |
| `LSP-SUBSCRIPTION-04` | - [x] A 已有合法订阅及冻结 R1；分别使用缺失 token、无效 token、有效但缺 subscriptions 写权限、有效但缺 channel_signing 读取权限的凭证尝试订阅，每种失败后推进 A 到新的 R2 | 四种输入的 subscribe 均返回 JSON-RPC 错误、不建立有效订阅且不交付签名事件；不以 WS 握手失败为判据；原 A 订阅在各自独立场景中仍收到完整 R2，原通道可完成 | 未授权读取签名数据，或无效请求破坏已有合法订阅 | P1 |
| `LSP-SUBSCRIPTION-05` | - [x] A 的 C1/U1 已收到 R1，S1 从未应用；关闭 C1，用相同 token 新建 C2 并重新订阅，复核当前工作后完成签名 | C2 获得自己的有效订阅 U2，补发完整 R1；观察期间请求不推进；随后 U2 收到应用 S1 后的新 R2，原通道双方就绪 | 普通重连丢失未完成工作，或仍依赖已移除的会话参数恢复 | P0 |
| `LSP-SUBSCRIPTION-06` | - [x] 真实 SDK 已保存 S1，FNN 仍待 R1；确认 SDK 已处理完暂停事件后切断其真实 WS 连接，保持 PID、token 和存储，允许它自动恢复 | 原 SDK 自行建立新连接并成功订阅，收到完整 R1；它生成的提交体与原 S1 相同，首次到 FNN 返回 Applied；原通道就绪且注资不变 | 仅观察器能重连而真实 SDK 卡住、丢失已签记录或重新注册才能继续 | P0 |
| `LSP-SUBSCRIPTION-07` | - [x] S1 已 Applied、R2 冻结且未提交，关闭旧连接并重新订阅；收到 R2 后有界观察，再放行 S2 及后续签名并在同一订阅观察新状态 | 新订阅补发的完整当前请求是 R2，直到后续正向状态到达均不重放 R1；R2 未被订阅消耗；原通道最终就绪 | 重连误回放已完成请求，或用空连接静默掩盖恢复失败 | P0 |
| `LSP-SUBSCRIPTION-10` | - [x] A 的租户订阅已收到 R1；operator 建立 host 通道签名订阅，应用 A 的 S1 产生租户 R2 并有界观察，随后新建普通 T–P 通道产生 host 状态 | operator 订阅成功，收到新 T–P 通道的完整 host 状态；它不收到 A 的私有 R1/R2；A 原订阅收到自己的 R2 并可完成原通道。同一 A–T channel ID 的合法 host 状态不误判为泄露 | 沿用旧 operator 一律拒绝，或 operator 意外读取租户私有签名内容 | P0 |
| `LSP-SUBSCRIPTION-11` | - [x] A 有冻结 R1；用同一 token 在 C1、C2 各建立一个订阅，待两者收到 R1 后应用 S1 并冻结 R2，再完成原通道 | 两个连接各自的订阅都收到完整 R1 及新 R2；新订阅不替换旧订阅、不导致旧连接退出；原通道完成且只有一次签名推进 | 错把并存客户端当成旧式接管，导致原客户端失去工作 | P1 |
| `LSP-SUBSCRIPTION-12` | - [x] A 在同一连接建立 U1/U2，另一个连接建立 U3，三者已收到冻结 R1；取消 U1 并取得成功响应后才应用 S1 产生 R2，继续收集事件并完成原通道 | 取消 U1 返回 true；该连接仍可使用，U2/U3 均收到完整新 R2；U1 在观察期内不收到取消后产生的 R2；原通道正常完成 | 取消一个订阅误断整个连接或其他客户端，或已取消订阅继续接收新工作 | P1 |
| `LSP-SUBSCRIPTION-13` | - [x] A 在 C1/U1 与 C2/U2（两个 ID 不同）均收到冻结 R1；从 C2 尝试取消 C1 的 U1 及一个确定未知的 ID，然后应用 S1 产生 R2 并完成原通道 | 两次取消均返回 false；C1/U1 和 C2/U2 仍各自收到完整新 R2，原通道正常完成 | 仅凭订阅 ID 跨连接取消工作，或无效取消误伤合法订阅 | P1 |
| `LSP-SUBSCRIPTION-14` | - [x] A–T 冻结 R1，使用当前注册返回的原始 token，经浏览器凭证子协议建立订阅，应用真实 S1 后在原订阅等待 R2，再恢复原 SDK | token 为未填充 base64url；握手返回 101 且只协商 fiber-rpc、不回显凭证；订阅收到完整 R1/R2，R2 到达前不靠查询推进，原通道最终双方就绪且注资不变 | 新浏览器入口无法接入、泄露凭证或只有握手成功而不能收到工作 | P0 |
| `LSP-SUBSCRIPTION-15` | - [x] A–T 冻结 R1，取确有尾部填充的有效 A token，以去填充的浏览器子协议、带填充 Bearer、去填充 Bearer 在三连接订阅，再应用一次 S1 并完成原通道 | 三种输入解码为同一 token 字节；三连接各收到完整 R1/R2；浏览器仅协商 fiber-rpc 且不回显凭证，两个 Bearer 均无需提供该协议；原通道双方就绪、注资不变 | 旧编码输入不兼容、重复编码 token，或仅测没有实际填充的伪边界 | P1 |
| `LSP-SUBSCRIPTION-16` | - [x] A 的合法订阅已收到冻结 R1；分别以带凭证但缺 fiber-rpc、重复凭证、同时带 Bearer 和凭证子协议、空后缀、非法 base64url 后缀请求新握手，每种独立场景随后推进 A 到 R2 并恢复签名 | 五种请求实际送达服务端并返回 HTTP 400，不建立订阅；原合法订阅仍收到完整 R2，原通道双方就绪且注资不变；客户端本地拒绝不算通过 | 歧义凭证被接受、错误输入绕过握手检查，或误伤合法订阅 | P1 |
| `LSP-SUBSCRIPTION-17` | - [x] A 的合法订阅已有冻结 R1；另一连接使用 fiber-rpc 和编码合法但内容不是有效 Biscuit 的凭证子协议完成握手后订阅，再推进 A 的 R2 并完成原通道 | 错误凭证连接握手为 101 且仅协商 fiber-rpc；subscribe 返回 JSON-RPC 错误、无订阅 ID、无签名事件；A 原订阅收到完整 R2，原通道就绪且注资不变 | 把编码校验误当 token 认证，或错误地要求此输入在握手失败 | P1 |
| `LSP-SUBSCRIPTION-18` | - [x] A 的合法订阅已有冻结 R1；分别用签名有效且身份正确、仅缺订阅写权限或仅缺通道读取权限的浏览器凭证握手，证明互补权限可用后订阅，再各自推进 A 的 R2 并完成通道 | 两种输入均握手 101 且仅协商 fiber-rpc；缺写者签名查询成功、缺读者未知 ID 取消返回 false 而签名查询拒绝；subscribe 均 RPC 拒绝且无事件；原订阅收到 R2、原通道就绪且注资不变 | 浏览器入口绕过任一权限，或用全无权限 token 掩盖未执行另一项检查 | P1 |
| `LSP-SUBSCRIPTION-19` | - [x] A/B 各有冻结 R1，分别用各自有效浏览器凭证订阅；核对初始工作后依次应用各自 S1，在同一订阅收取各自 R2，再恢复两方原 SDK | 两连接握手 101 且仅协商 fiber-rpc；初始及实时事件只含所属租户完整 R1/R2，不出现对方私有状态；两个原订阅均收到正向 R2，两条原通道就绪且各自注资不变 | 凭证归一化丢失身份导致跨租户泄露，或用空连接静默掩盖隔离失败 | P0 |
| `LSP-SUBSCRIPTION-20` | - [x] A 唯一私有通道冻结 R1；同一连接分别省略 options、传 null、{}、channel_ids:null 建立订阅，再应用真实 S1 并完成原通道 | 四个订阅各收到完整 R1 和新 R2，订阅期间 R1 不被消耗；原通道双方就绪、原注资不变 | 默认参数被误当空集或不同默认形式行为不一致 | P1 |
| `LSP-SUBSCRIPTION-21` | - [x] A 冻结 R1；同连接用 channel_ids:[A] 和 [A,A] 订阅，应用 S1 后冻结 R2，再完成原通道 | 两订阅各收到完整 R1/R2，冻结观察期每份工作各一条；原通道就绪、原注资不变；仅证明单通道显式全集 | 显式选择漏事件或重复 ID 放大同一工作 | P1 |
| `LSP-SUBSCRIPTION-22` | - [x] A 冻结 R1；同连接建立默认对照与 channel_ids:[] 订阅，推进 R2 后取消空订阅并完成原通道 | 空订阅获得有效 ID，初始及 R2 后完整窗口均无该 ID 通知，取消返回 true；对照收到完整 R1/R2，原通道就绪 | 空数组被当默认全集，或失效订阅静默造成假通过 | P1 |
| `LSP-SUBSCRIPTION-23` | - [x] A 合法订阅已有 R1；按本节四个独立组逐项提交共 16 个 topic/options/channel_ids 格式错误，每组随后产生 R2 并完成原通道 | 每项均由服务端返回 -32602、无订阅 ID 或遗留事件；每组原合法订阅收到完整 R2，原通道就绪且注资不变 | 参数校验缺失、把客户端拒绝当成功，或错误请求损坏原订阅 | P1 |
| `LSP-SUBSCRIPTION-24` | - [x] A 合法订阅已有 R1，确认 X 为不存在的合法 Hash；同连接依次订阅 [X]、[A,X]、[X,A]，再推进 R2 并完成原通道 | 三次均 -32001 且整次拒绝，无部分订阅或孤立通知；原合法订阅收到完整 R2，原通道就绪且注资不变 | 静默跳过未知 ID 或仅因列表顺序不同建立部分订阅 | P1 |
| `LSP-SUBSCRIPTION-25` | - [x] A/B 各冻结 R1 且各自合法订阅可读；A 连接依次订阅 [B]、[A,B]、[B,A]，再依次推进两方 R2 并完成两条原通道 | 三次均 -32001 且整次拒绝，A 全连接无 B 私有工作或孤立通知；原 A/B 订阅均收到自己的完整 R2，两通道就绪且各自注资不变 | 过滤绕过租户隔离，或混合列表部分接受导致泄露 | P0 |
| `LSP-SUBSCRIPTION-26` | - [x] A 冻结 R1；以 256 个重复 A 组成 channel_ids 建立订阅，推进并冻结 R2，再完成原通道 | 订阅成功，冻结观察期 R1/R2 各一条完整工作，原通道就绪且注资不变；不代表 256 条不同通道覆盖 | 上限边界错误或去重不当放大通知 | P1 |
| `LSP-SUBSCRIPTION-27` | - [x] A 合法订阅已有 R1；以 257 个重复 A 请求订阅，随后推进 R2 并完成原通道 | 请求返回 -32001、无订阅 ID 或遗留通知；原合法订阅仍收到完整 R2，原通道就绪且注资不变 | 先去重后校验使超长原数组被接受 | P1 |
| `LSP-SUBSCRIPTION-28` | - [x] A 冻结 R1；同连接建立默认对照及 options 为 [null]、[[]]、[[A]] 的三个订阅，推进 R2、取消空订阅并完成原通道 | 保留已确认的固定 04 数组兼容；三者分别等价于全集、空集、单 A，非空者收到完整 R1/R2、空者无事件且取消 true；原通道就绪且注资不变 | 把可接受的顺序字段形式误测为非法，或不同形式选择错集合 | P1 |
<!-- TEST-CASES-END -->

## 已移除的旧行为

原 LSP-SSE-08/09 的单租户会话接管、H1/H2、409/session_replaced 及旧 SDK 接管退出用例和映射已删除；其原行可从 Git 历史追溯。原 04 的 tenant URL 参数、畸形会话头、operator 必须拒绝三条输入也已移除。仍成立的恢复价值由 05/06 与核心恢复行保留；operator 新预期独立为 10，并存行为使用新 ID 11。

## Gate3 实施清单及判断边界

| 位置 | 本批同步的内容 |
| --- | --- |
| `test_sse_signing_events.py` → `test_signing_subscriptions.py` | 保留 01～07 的业务价值，迁移 TEST-MAP 到 LSP-SUBSCRIPTION 前缀；清除原 08/09 和 04 的三条废弃输入；实现 10～13 及 04 两种权限输入。去掉类名、方法名、日志中的旧传输/会话语义 |
| `_sse_observer.py` → `_subscription_observer.py` | 握手认证、真实 subscribe/unsubscribe、按连接及原类型 ID 收集通知；精确断线；保留上游事件与向 SDK 实际交付事件的独立记录 |
| `_sdk_driver.rs`、本地配置/构建入口 | 固定 FNN/SDK 同 SHA；使用官方 EventStream::connect 和专用 WS URL；保留真实 SDK 验证、存储及 processed 确认机制；只改 Python 测试的本地驱动，不改产品代码 |
| `_retry_signer_gate.py`、`_lsp_test.py` | HTTP 提交故障仍由 HTTP gate 控制；将 gate.repolled、queries、pause_queries 的恢复判断替换为真实 WS 连接、订阅和交付检查点；避免自动重试掩盖被测操作 |
| 核心重试/恢复文件 | 同步下面链接中 8 条修改行的全部映射；其余 8 条核心业务行不改预期，但通过共用驱动迁移后也须重新执行 |

核心完整修改行另见 [重试 04/05](channel-signing-retry.md)、[恢复 02～07](channel-signing-recovery.md)。两份表对应自动化已同步 WS 恢复检查点；勾选仍只表示映射存在。

- 01/05/07：先冻结完整当前集合，不等待不存在的结束标记；05 用 R2，07 用后续请求或 NoSignatureRequired 正向证明同一订阅仍工作。跨连接 ID 只用于关联，不承诺全局唯一或不复用。
- 03：收齐双方初始 R1 后观察 5 秒，再推进两方各自 R2；持续检查归属到两边均收到正向新状态。
- 04：四种输入独立执行。缺写权限的凭证保留 topic 读权限，缺读权限的凭证保留 subscriptions 写权限，确保分别验证两道检查；不能用同一个全无权限 token 冒充两条证据。拒绝之后在原 U 推进新工作证明未被破坏。
- 06：暂停事件处理必须向 EventStream 返回 processed 成功后才断线，否则 SDK 可能仍等待处理确认、没有进入读取/重连。失败事件不能由无限自动重试掩盖。恢复证据来自 SDK 连接，不能由 Python 自建订阅代替。
- 10：operator 正向样本采用订阅后新建的普通 T–P 通道，观测其本地签名的 NoSignatureRequired 状态；初始 host 无待签时的静默不够。A–T 两侧可能使用同一 channel ID，须比较 host/tenant 的完整状态内容，不能仅按 ID 判泄露；A 的真实待签 R1/R2 为负向样本。
- 12：取消响应前已排队的旧 R1 不算错误；取消响应成功后才应用 S1，使 R2 成为明确的新事件。U2/U3 收到 R2 后仍收集 5 秒，任何 U1/R2 通知均失败。13 同样用新 R2 证明两条原订阅有效；先确认 U1 不属于 C2 的活动 ID 集合，未知 ID 也必须避开本测试实际分配集合，避免跨连接 ID 偶合把 C2 自己的订阅当成取消目标。
- 建立/事件恢复最多 60 秒，业务完成最多 120 秒，直接 RPC 最多 10 秒。SDK 当前连接/请求各 10 秒预算，重连退避从 200 毫秒到 10 秒并加抖动；上述测试预算不是产品 SLA。进入开通签名检查点前完成外部注资，开通适用截止剩余至少 300 秒，并在放行前复核。
- 执行顺序：先正常开通→收款→关闭，再聚焦订阅行为及受影响重试/恢复，最后完成 16 条核心回归及映射检查。新增 Python 方法总数以 Gate3 发现结果为准，11 个行为 ID 不等于 11 个参数化/独立方法。

## 本轮交接

用户已确认本表 11 条、原 08/09 删除及原 04 三个废弃输入，以及重试表 04/05、恢复表 02～07。Gate3 已按该行集同步自动化、文件/类/方法名称、TEST-MAP 及勾选。超时强关、watchtower 与链上资金取回仍按后续独立 Gate1 推进，未因本次迁移被计为覆盖。


## 浏览器鉴权 Gate2：共同断言、输入与预算（04c2064）

本节适用于已获用户明确确认的14～19及共同断言、预算。本批Gate3已实现并完成正式1+3及相关旧回归，实际证据见测试目录README；复选框本身只表示映射存在；前文旧迁移记录独立保留。

### 准备与可观察证据

复用已有私有 CKB 通道和真实 SDK 冻结 R1/S1 的夹具。C/U、R1/R2、S1/S2 沿用前文定义。浏览器连接不设置 Authorization header，协议列表是 `fiber-rpc` 与 `base64url.bearer.authorization.fiber.<token>`；16 的冲突输入除外。14 必须直接使用真实注册原文；15 是固定 04 上同一有效 token 的编码兼容，不代表历史版本/身份存储迁移。

15 的 padded 字符串必须实际含 1 或 2 个尾部 `=`，去填充后必须不同且解码字节一致；不能盲目追加无效填充。如当前注册 token 长度恰好不需要填充，Gate3 可最小扩展已有测试专用 token 夹具：保留从真实 token 验证得到的 A tenant/node，签发 subscriptions 写与 channels 读权限，加入不参与授权的长度控制 fact，以至多三种连续长度取得有效且需要填充的序列化 token。中性 fact 名称和值避开所有授权规则，仅用于控制编码长度。只使用本地公开 devnet 测试私钥，不改产品签发逻辑；未取得有效夹具则报告夹具失败，不跳过或伪称兼容通过。该 token 仅供只读观察器；真实签名仍由原 SDK 身份/存储完成。

16 的五个输入各自使用独立准备和收尾，不在同一冻结窗口内循环累积：缺 fiber-rpc 时其余凭证有效；重复相同凭证两次；同一有效 token 同时放 header 和子协议；后缀为空；后缀为 HTTP/subprotocol 合法但 base64url 非法的 `!`。HTTP 400 是固定 04 源码观察，随本行提交人工确认，不绑定错误响应正文。必须取得真实服务器 HTTP 400；Python 参数校验异常、连接失败、超时或其他状态码均不能代替。17 使用对 `not a Biscuit` 字节的一次无填充 base64url 编码，编码合法但认证无效，必须先取得 101 再断言 RPC 错误。

18 的两种输入各自独立；复用已有 token 权限夹具，保留有效签名及唯一 A tenant/node。缺写者先在同连接查询完整 R1 成功；缺读者先以避开所有活动 ID 的未知取消请求证明写权限，再证明签名查询失败，最后验证 subscribe 拒绝。不能因为握手成功就宣称身份或权限正确。

### 共同断言

- 成功浏览器握手记录真实 101 与响应协议头，协商值恰为 `fiber-rpc`，不包含凭证子协议或 token；禁止只依赖客户端构造成功。Bearer 不传该协议。RPC 拒绝检查 error/整数 code、无 result 订阅 ID，不绑定非契约错误文案。
- 对全部成功订阅保留 ID 的 JSON 类型并比较完整 typed notification。先收 R1 并核对独立保存的当前状态；应用真实 S1 只得到一次 Applied，再先收新 request ID 的 R2、后直连查询交叉核对。消息由真实 FNN 产生，不由观察器伪造；读订阅本身不提交签名或推进 R1。
- 负向输入不得获得签名事件；保留原合法订阅，错误发生后主动产生 R2 并在原连接收到，以证明故障隔离。19 收齐双方 R1 后观察 5 秒，再依次产生各自 R2；持续检查所有事件归属，直到双方 R2 到达后再观察 5 秒，不能仅依赖静默窗口。
- 所有行恢复原 SDK 存储完成原通道，验证双方 ChannelReady、NoSignatureRequired、同一原始 channel ID/注资 outpoint、注资交易 committed。无额外通道、无 pending TLC，双方 local/remote 余额互相对应；最终连续 5 秒状态、注资、余额及 TLC 不再变化。不把“余额等于开通前”作为断言，因为正常开通有费用。
- 证据包括版本和构建校验、请求输入类别、真实握手响应、RPC/WS 帧、R1/S1/R2、原 SDK 与节点日志和终态。新测试使用 `test_browser_*`/`TestBrowserSigningSubscriptions` 等清晰名称及完整 `LSP-SUBSCRIPTION-*` 映射；不恢复旧事件传输名称。

### 时间预算与 Gate3 执行顺序

| 阶段 | 上限与判据 |
| --- | --- |
| 环境及 R1 准备 | 单租户 180 秒、双租户 240 秒；独立节点/SDK 就绪且真实 R1/S1 已冻结后才进入行为阶段；超时记环境/夹具证据，不算产品行为通过 |
| 连接及请求 | 每次 WS 握手最多 10 秒、每次 RPC 最多 10 秒；共享外层截止，禁止自动重试替换拒绝、超时或失败 |
| 当前/新事件 | 每个阶段共享最多 60 秒，15 的三连接和19 的双租户均共用阶段截止，不能按连接倍增；检查 SDK 实际已保存 S2，不用轮询触发推送 |
| 负向及终态稳定 | 负向观察 5 秒并继续收集到正向 R2 后 5 秒；最终状态稳定 5 秒，期间 0.1～0.2 秒轮询；这是有限观察结论 |
| 完成原通道 | 所有涉及通道共用最多 120 秒，不按租户累加；超时完整留证 |
| 行为阶段与总预算 | 行为阶段共用 300 秒，子阶段取自身上限和剩余预算的较小值；进入阶段时每条通道业务截止余量至少 360 秒，提交 S1 及恢复 SDK 两处放行前均复核至少 180 秒。不延长产品配置或借重建环境刷新失败。含准备及最多30秒清理，单租户单输入总上限540秒、双租户600秒 |

Gate3 拟实现 6 个行为行、11 个独立执行实例：14/15/17/19 各1，16 五种输入，18 两种输入。15 的三种入口在一个实例内使用同一 token 字节及同一真实状态推进，不是三次成功计数。先静态收集/映射检查，再聚焦一轮11实例；冻结实现后固定复跑3轮11实例，共44个预定实例，不通过补跑凑成功数。修复夹具须保留原失败、单独记录修正后新批次；产品失败留证交用户处理。共用观察器/凭证夹具若被修改，另对既有14条回归一次并单列，不计入新44个实例。全批理论串行上限每轮100分钟、四轮400分钟，实际耗时按原始结果记录；超时是执行失败，不是产品 SLA。

Python 仅验证服务器对浏览器线协议的行为，不宣称真实浏览器页面、TLS/代理、全局压力或 watchtower 链上取回通过。watchtower 字节预检仍独立保留，不在本批升级合约。用户已明确通过14～19完整行集、共同断言及预算，Gate3已完成；运行结果单独记入测试目录README。


Gate2 复核与检查：GPT 6.1 sol 已只读复核六行、源码、输入夹具和预算，未发现阻断项，未触发 Daybreak。实现时新批次需明确传递共享截止及两处180秒放行余量，不盲目复用旧 `_submit_saved/_finish_channels` 的固定300秒判断，也不改变旧用例默认行为。

映射检查 `python3 scripts/check_test_map.py`：103个评审ID/93个有映射，退出1；新增14～19未映射符合当前Gate2阶段，报错仍为既有6个孤儿映射与历史报告overlay的16个重复ID。设计检查使用 skill 的 `scripts/check_test_design.py --root <仓库> --review reviews/lsp/signing-subscriptions.md`：识别17行，退出1，报告相同历史重复ID、保留的后续分支及SPEC-06源码观察待人工确认；不代表本批新增了结构错误或功能已通过。`git diff --check` 通过。仅文档/命名及一条注释调整，本轮未启动节点或执行功能测试。

Gate3最终交接：14～19的11个方法及全部TEST-MAP已同步；聚焦和固定三轮44/44通过，既有14方法回归14/14通过，GPT6.1 sol代码/结果复核无阻断。初版探索轮因补outpoint索引断言被人工中断（5通过、退出2），全部证据保留，不计入正式结果。无产品代码或合约改动，watchtower验证边界不变。


## 过滤参数 Gate2：输入、断言、预算与最小适配（04c2064）

2026-10-28 用户明确确认调整后的 Gate1，本节仅交付新行 20～28，等待完整行集、数组兼容选择与预算确认。固定 `04c206465b48da85b99aa58e80afe9801a2cb2db`，源码干净，现有 FNN 报告 `Fiber v0.10.0-rc1 (04c2064 2026-10-23)`。本轮只读 GitHub 查询 head 仍为 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，不自动切换。不触碰退款夜跑；没有新增自动化或运行产品样本。

### 完整输入及分组

本节 A/B 在 channel_ids 中表示其真实 32 字节 channel ID 字符串，T 为公共节点；X 为预先确认不在本次 A/B/T 通道集合中的合法 32 字节 ID，且 A 查询 X 返回不存在。统一使用 Bearer、当前有效且有完整权限的真实 A 凭证和位置参数 `params:[topic, options]`。只改变待测字段，其他前提必须有效。

| 用例 | 传输输入与执行安排 |
| --- | --- |
| 20 | `params:["channel_signing"]`、`["channel_signing",null]`、`["channel_signing",{}]`、`["channel_signing",{"channel_ids":null}]`；一个实例、四个 U，均收到 R1 后只应用一次 S1，再等待全部 R2 |
| 21 | options 为 `{"channel_ids":[A]}`、`{"channel_ids":[A,A]}`；一个实例、两个 U，共享同一次真实推进 |
| 22 | 默认对照 U0 加 `{"channel_ids":[]}` 的 Uempty；一个实例，空订阅的取消发生在 R2 后观察完成之后 |
| 23 | 下表四组，各组独立环境/R1/合法 U0/R2/收尾，合计四个执行实例；每组内四个请求依次发出、逐个检查，任一异常立即失败，不继续取样 |
| 24 | 默认 U0 加 `{"channel_ids":[X]}`、`{"channel_ids":[A,X]}`、`{"channel_ids":[X,A]}` 三个拒绝请求；一个实例 |
| 25 | 两租户各自默认 U0，A 连接依次发 `{"channel_ids":[B]}`、`{"channel_ids":[A,B]}`、`{"channel_ids":[B,A]}`；一个双租户实例 |
| 26 | channel_ids 为长度恰为 256 的重复 A 数组；一个实例，保留原数组和长度，不能先在 Python 去重 |
| 27 | 默认 U0 加长度恰为 257 的重复 A 数组；一个实例 |
| 28 | 默认 U0 加 options `[null]`、`[[]]`、`[[A]]`；一个实例，四个成功订阅；三个数组不是 channel_ids 字段本身 |

23 的完整错误输入如下，除 topic 变化外均为 topic=`channel_signing`；Hash 字符串使用精确构造，不能误把合法的无 `0x`、`0X` 或大写十六进制列为非法。

| 独立组 | 四个请求的唯一变更 | 共同预期 |
| --- | --- | --- |
| topic/字段 | topic=`"not_a_topic"`；topic=`0`；options=`{"tenant_id":"B"}`；options=`0` | 服务端 -32602，无 result 或新订阅；随后原 U0 收到 R2 |
| 参数类型 | options=`true`；options=`"invalid"`；options=`{"channel_ids":{}}`；options=`{"channel_ids":[0]}` | 同上；不扩大为所有非对象或所有 null 均非法 |
| Hash/元素 | channel_ids=`[null]`；`["0x" + "00"*31]`；`["0x" + "00"*33]`；`["0x0"]` | 分别覆盖 null 元素、短、长、奇数十六进制；同上 |
| 字符/序列 | channel_ids=`["0x" + "gg"*32]`；options=`[]`；options=`[null,null]`；options=`[A]` | 分别覆盖非十六进制、缺字段、额外字段、字段类型错误；同上 |

这是九个行为 ID、十二个独立执行实例；16 个非法输入不是16个完整环境，也不能仅因同组最后一个请求通过就忽略前面的 RPC 结果。每组最多四个待测请求，通常另最多一个合法对照请求；25例外为三个拒绝请求加A/B各一个对照，合计仍为五次subscribe。所有请求共享本组40秒截止；有界分组共享最后一次主动 R2 屏障，不能宣称逐输入各有独立业务推进或独立环境。

### options 数组：完整静态路径及产品边界

固定产品 `Cargo.lock` 锁定 jsonrpsee/proc-macros/types 0.25.1、serde/serde_derive 1.0.228、serde_json 1.0.151。本轮读取本机 Cargo registry 对应版本源码，没有编译、运行 serde 小程序或发送 RPC 试探。

1. 产品 `subscription.rs:225～229` 声明 `options: Option<SubscriptionOptions>`。jsonrpsee `render_server.rs:374～394` 对位置参数生成 `optional_next()`，`params.rs:190～200,249～255` 用 serde_json 读取 `Option<T>`；解析失败由宏拒绝为 -32602，尚未进入产品 subscribe。
2. serde_json `de.rs:1673～1684` 把外层 null 读为 None；产品 `subscription.rs:350～351` 再用默认 options。对象缺 channel_ids 与字段 null 同样得到 None。
3. `SubscriptionOptions` 只有一个 `Option<Vec<Hash256>>` 字段。serde_derive `de/struct_.rs:70～94,143～146` 生成结构体 `visit_seq`；serde_json `de.rs:1836～1845` 允许数组进入此路径。因此 `[null]` 是唯一字段值 None，`[[]]` 是 Some(empty)，`[[A]]` 是 Some([A])。
4. Rust `derive(Default)` 不等于 `#[serde(default)]`。serde_derive `de.rs:805～834` 在序列缺字段时返回 invalid_length，所以 `[]` 拒绝；serde_json `de.rs:1072～1085` 的 end_seq 拒绝额外元素，因此 `[null,null]` 拒绝；`[A]` 以字符串填 Vec 字段，也拒绝。
5. 命名参数经 `render_server.rs:397～455` 生成 ParamsObject，再经 `params.rs:121～127` 的 from_str，options 最终类型相同，上述静态结果一致；本批不增加命名入口的运行实例，不把静态结论当执行覆盖。
6. 解码成功后才到产品 stream：超过 256 项或未知/不可见通道由 `subscription.rs:353～363` 包装 -32001。合法数组接受仍以认证、topic 可用、容量和所选通道存在为前提。

依赖源码位置为本机 `.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/<上述包名-版本>/src/`，产品来源为固定 04 checkout。**28 的待确认点是采用该固定实现兼容作为本批回归预期**：接口文档只公开对象形式，当前接收数组并不自动成为跨版本稳定 API。若用户希望产品只接受对象，应另提出契约决策，不能在本批暗改测试或产品来强制拒绝。

### 共同断言及资金边界

- 冻结真实 SDK 的 R1/S1，确认 gate 尚未转发，A（以及25的B）唯一原通道及原注资已记录；读取订阅不能消耗 R1。各成功 U 按 JSON 原类型区分，同连接 ID 必须互不混淆，所有 R1 与独立预存完整 typed data 相等。
- 建立所有成功订阅或收到本组所有拒绝后，完整观察5秒并再核当前 R1 未推进；应用一次真实 S1 必须返回 Applied。随后等待原 U 的新 request ID R2，不重连、不重订阅、不先调用查询触发它；事件到达后才直连核对完整 R2，并确认真实 SDK 已保存 S2 而 gate 仍未放行。
- 多个 U 共享 R1 阶段60秒和 R2 阶段60秒，不按 U 累加。25 的两租户共享同一阶段截止：依次真正应用各自 S1，各原 U 都必须收到所属 R2。之后继续观察5秒，始终检查全连接帧，不能只检查已知 U 子集。
- 每条连接维护全部成功 U 集合；通知的 ID 类型和值必须属于该集合，消息内容必须属于该 U 的预期集合。先处理并登记subscribe响应再核对应历史帧，允许首通知与响应相邻到达；最终每帧必须有合法归属，不能在成功ID尚未登记时误报孤立。拒绝请求需保存确实发出的原始 JSON 及同 request ID error，code 精确为预期整数，不能含 result。无新 ID、无孤立通知、无被错误挂到合法 U 的 B 数据；每个原合法 U 必须在本组错误之后收到 R2。客户端异常、断连、超时或鉴权失败不能替代参数拒绝。
- 21/26 在冻结的 R1、R2 完整窗口内分别计数，目标 typed 工作各恰一份；允许合法的中间 NoSignatureRequired 状态，不能把所有通知数等于一当成规则。去重判据只覆盖本连接有限窗口，不声称跨重连 exactly-once。
- 22/28 的空 U 从注册到 R2 后5秒均为零通知，同连接默认 U0 真实收到 R1/R2。随后该空 U 取消必须 true。对照 U0 证明事件源推进，取消证明空 U 自身注册仍在，两者不能混写为“空 U 收到正向事件”。无 snapshot_complete，以冻结集合及上述窗口作为有限证据。
- 每条通道恢复原 SDK 身份/存储和后续签名，双方 ChannelReady、NoSignatureRequired，channel ID、原 funding tx hash 及输出索引一致，精确 outpoint 的交易 committed。双方 local/remote 余额互为镜像，无 pending TLC、无额外通道；最终状态、余额及 outpoint 连续5秒不变。仅证明本次观察/错误请求未破坏正常开通与资金归属，不做 TLC 退款或强关守恒宣称，也不要求余额等于含费用的开通前值。
- 未预期事件/RPC 结果即失败，不重新订阅、刷新凭证、重开通道或重试被测 subscribe 来掩盖；保留失败输入、全部通知、真实签名、链/SDK/节点日志。此处 subscribe 不触发任何付款、TLC 或强关。

### 时间预算

全部等待由单调时钟绝对截止约束，取操作、阶段、实例、当前轮和整批剩余时间的最小值；完成后还要检查时间，晚到成功只作诊断。准备超时和行为断言失败分别归因，任何上限都不是产品 SLA。保持既有开通窗口86400秒及共享 helper 的300秒余量守卫，不为本批延长或缩短产品计时器。

| 阶段 | 上限、起点与判据 |
| --- | --- |
| 单实例准备 | 从 setup_method 入口计时，单租户180秒、双租户240秒，涵盖该实例节点/SDK及R1/S1准备；类级链初始化另计入当前轮30分钟上限 |
| 行为入口余量 | 每条通道距现有开通截止至少720秒；真实S1提交前至少480秒；恢复SDK前至少300秒。剩余不足即测试准备失败，不通过重新开通刷新预算 |
| WS 与请求组 | 每次握手10秒；每个RPC10秒。本组所有subscribe（通常四个输入加一个对照；25为三个拒绝加两个对照）共享40秒请求截止；不允许五次各耗满10秒后仍声称满足40秒 |
| 完整R1 / 实时R2 | 各阶段最多60秒，所有U/租户共享；等待真实S2也使用R2剩余时间。真实S1提交各≤10秒，受共同阶段/实例截止约束 |
| 负向观察与取消 | R1冻结后5秒、全部R2后5秒；空订阅取消≤10秒；观察间隔0.1～0.2秒，期间持续检查全量通知 |
| 恢复与终态 | 所有原通道完成共享120秒，随后共同稳定观察5秒；双租户不能简单调用两次120秒而叠加，需外层绝对截止包住旧helper |
| 行为 / 清理 / 实例 | 行为共420秒；清理最多30秒，含保存观察证据及结束本实例进程。单租户实例总630秒、双租户690秒，从最早setup_method入口算；阶段不重置总截止，清理用预留时间，不被已到期的行为截止跳过 |
| 每轮 / Gate3执行阶段 | 每轮12实例共用30分钟墙钟上限，包含类初始化和归档；首批正式固定1+3轮最多48实例。Gate3执行阶段整体150分钟，自环境准备开始计时（不含编码及人工评审等待）：环境准备/适配自检15分钟，相关聚焦10分钟，四轮各30分钟，最终归档5分钟；任一先到即停止后续，未运行项如实记录 |

准备/行为的绝对截止还须不晚于当前轮截止减30秒、整批截止减最终归档5分钟再减30秒；清理独立使用已预留的30秒，不能被到期的行为定时器立即打断。剩余时间不足以保留清理时不启动下一实例，标记未运行；轮30分钟到期后不能另加30秒清理。任一归档或清理超时须保留原始目录，不调用会删除证据的clean；停止本实例自有进程后报告尚存目录和未完成归档，不能把超时记为成功。

不能把单实例最坏上限简单累加当作已批准总时长：12实例的单独上限相加为127分钟，但**本方案每轮先受30分钟上限截断**。如果环境变慢导致无法在当前轮完成，报告预算失败和未运行项，不能延长到127分钟或当作通过。

耗时仅作排期参考：同基线既有浏览器11实例每轮911.64～923.40秒，约83～84秒/实例；本批12实例估计每轮17～25分钟，正式四轮约70～100分钟，非实测保证。Gate3加准备与相关聚焦预计约1.5～2小时，硬上限150分钟。固定1+3只用于本次资格验证，日常建议单轮；本批无需链上成熟等待，不混入退款夜间目录或启动夜间任务。

### 最小适配及环境差异

1. 新增普通目录 `test_cases/fiber/devnet/lsp/test_signing_subscription_filters.py`，继承现有 SubscriptionTestBase；11个单租户实例、1个双租户实例。23用四个明确方法调用同一组请求/断言辅助逻辑；其余每行一个方法。不依赖 unittest 不支持的pytest参数化，不把所有输入串成一个巨型场景。
2. 原始 `SubscriptionObserver.request()` 已能发送任意JSON并保留服务端envelope；用它明确区分省略与null/数组。沿用 frames/messages 和R1/S1/R2测试准备逻辑，仅在新文件加入请求记录、全连接ID检查、集合/计数断言、有界分组及证据归档。局部覆写收尾时须注意现有 `_lsp_test.py::teardown_method` 在finally中clean：只有成功归档后才允许清理数据目录，归档异常时保留原目录并仅停止自有进程。无需新增Rust功能、扩展SDK签名能力或改公共framework。
3. 截止控制参考已实现的 `_BrowserSubscriptionBase._budget`，在新文件内保持小型、可恢复已有signal状态的有界包装；为全部U/R2、双通道完成和清理传同一个绝对截止，不改旧helper的300秒守卫。Gate3若发现共享代码必须修改，先把影响范围说清并扩大相关回归，不能静默重写旧行为。
4. **当前worktree尚不可直接执行**：原仓库04构建清单的driver/chain源码摘要分别为 `ce6c6f49…` / `f8339ff5…`，匹配原工作区；当前普通用例worktree为 `b71a4969…` / `dbc7deef…`，且没有本地download bundle。FNN提交相同不代表测试适配产物匹配，不能软链原bundle后跳过源码哈希校验。
5. Gate3环境准备方案是在当前隔离worktree补齐既有Python/CKB/ckb-cli依赖，按现有 `build_lsp_test_binaries.py` 对干净固定04源码和隔离Cargo缓存生成本worktree匹配bundle；缓存可从已有产物复制，原bundle、原源码和夜跑产物保留。该步骤不改产品源码或构建脚本；它仍占前述15分钟环境预算，不能自动扩成冷构建长任务。本轮未复制、构建或启动；版本/哈希不满足就停止在环境阶段。
6. 新用例在本目录依现有发现规则接入，不改日常目录、nightly标记或公共conftest。实现后才为20～28加入对应TEST-MAP并勾选；23的四处映射都需检查。当前所有新增行未映射。

### Gate3 验证顺序与停止条件（尚未授权执行）

- 先实现本批并由GPT 6.1 sol复核，再做语法/设计/映射及收集自检；这些不算功能通过。核对固定04来源、SDK/driver/合约与源码哈希、Python环境、独立端口和目录，设置独立输出路径，避免默认report.html覆盖原证据。
- 相关聚焦只选既有订阅02（真实R2）、12（本连接取消）及03对应的双租户隔离方法，各一次，单列结果；保留现有版本归因，不先跑全量普通LSP或退款。共用代码有实质变化时须重新评估此最小集合。
- 冻结实现后，首轮12实例通过才执行固定三轮12实例；全轮使用停止于首失败的执行方式，固定方法顺序，按每轮剩余截止启动。产品失败停止后续批次，环境/预算失败同样停止并记录层次；不为了取得某分支补跑失败。只有全部预定48实例执行并通过，才报告该固定批次完成。
- 每批独立保留命令、版本、源码/构建清单、起止及截止、JUnit、原始日志和退出码；每方法另存输入组、请求/响应、全部带时间WS消息、成功U集合及R1/S1/R2/资金终态。失败或清理超时也先保留证据，不覆盖原快照；既有#1674/#1706等仍沿原归因。本轮只改评审文档，不新增运行记录中的通过条目。


Gate2复核与静态检查（2026-10-28）：GPT 6.1 sol 已独立复核完整行集、Serde路径、预算及最小适配，未发现剩余阻塞；预算复核提出的25双对照数量及截止前清理预留已补齐，归档失败保留原目录的边界也已复核。未触发Daybreak，没有切换复核模型。

- `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root . --review reviews/lsp/signing-subscriptions.md`：26行，退出0；08～11的源码观察/推导和28数组兼容仍需本次人工确认，检查器不证明行为通过。
- `python3 scripts/check_test_map.py`：112条评审/99条映射，退出1；新20～28九行未映射符合Gate2，仍只有既有PMP-01～05、SETTLE-01六个孤立映射，无重复ID。比例不是功能覆盖率。
- `git diff --check` 退出0；只修改三个评审Markdown文件，保留上一轮Gate1编辑；未修改测试、产品、构建产物或时间，未执行pytest、节点、VM或退款批次。

下一门禁：用户确认20～28完整行集、28数组兼容采用、有限观察及执行预算、独立匹配构建产物的最小准备方案后，才进入Gate3实现与执行。


2026-10-28 Gate3实施开始：用户已明确批准20～28行集、28固定04数组兼容及150分钟执行预算。新文件 `test_signing_subscription_filters.py` 实现12方法，23有四处映射；本次勾选仅表示映射存在。先GPT 6.1 sol复核，再独立产物、自检、相关聚焦和固定1+3；执行时钟从独立环境准备开始，退款夜跑不动。结果另见测试目录README。


Gate3本轮停止（2026-10-28）：独立产物准备约29.41秒后版本断言失败，构建脚本退出1；未进行适配自检/收集、相关3条或正式48实例。原04源码、bundle及退款夜跑未变，失败产物和源码快照已完整保留，GPT 6.1 sol复核归因为构建缓存产物不匹配；不证明仅版本metadata过期。现有20～28勾选仅表示12个方法已实现，详见[本轮运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-订阅过滤-gate3准备失败2026-10-28)。依用户失败即停指令，不自动修复重跑。


## 2026-10-28：用户授权更新到 LSP 分支最新提交

用户明确要求更新到LSP分支最新代码测试。GitHub PR #1623 的 head 分支为 `chenyukang/fiber:lsp-support`，查询及独立fetch均得到 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；新源码位于当前worktree `download/fiber/source-pr-1623-84333ee`，原04源码及夜间环境保留。该明确指令取代本批必须运行04的约束；不将已有04/3ce结果转记为843通过。

GPT 6.1 sol已只读复核04→843差异：subscription RPC/types/鉴权/SDK核心和根Cargo.lock未变，20～28的过滤、-32602/-32001、数组兼容预期继续适用。新增revocation nonce watchdog只作用于已就绪且非internal的特定失衡状态，本批冻结开通R1/R2不满足；SDK新增付款/履约授权分支不改变本地驱动接口；sync store默认false；watchtower prune不属于本批正常开通路径。因此不新增或放宽用例行，沿用已有12方法和预算。以上为静态影响结论，不是产品测试通过。

构建/测试通过现有完整SHA参数 `--revision` / `LSP_TEST_REVISION` 选择843，独立输出 `pr-1623-84333ee`。在新的APFS缓存副本中清理 `fiber-bin`、`fnn`、`fiber-store`、`fiber-types`、`fiber-json-types`、`fiber-lsp-sdk`、`fiber-lsp-sdk-agent` 七个相关本地包，保留第三方依赖缓存；让产品实现与版本嵌入一起重新编译，而非伪造版本字符串。原缓存、04 bundle及上次失败产物不覆盖。新执行阶段仍从产物准备计时，环境15分钟/整体150分钟、相关3条及固定1+3、失败即停；本次新批次的真实结果记录在测试目录README。


2026-10-29 Gate3执行完成：843匹配产物、自检与收集完成，相关3方法以及首轮/固定三轮各12方法全部通过（正式48/48，退出码均0），总执行4789.563秒。20～28九个ID的12处TEST-MAP与勾选保持一致；勾选仍只代表映射，运行结论限定于本次843样本。同身份多通道严格子集、命名参数入口及无限窗口/跨重连exactly-once未被本批覆盖；未运行退款、watchtower或全量LSP。完整证据、预算及复核边界见测试目录最新记录。

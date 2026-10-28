# LSP WebSocket 签名订阅用例评审

当前实施的是文末浏览器鉴权 Gate3：`LSP-SUBSCRIPTION-14～19`，固定 `04c206465b48da85b99aa58e80afe9801a2cb2db`，Gate1/Gate2 已获用户确认；新六行已接入映射，正式1+3共44/44通过，相关既有14方法回归14/14通过，见 [浏览器鉴权运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-浏览器鉴权-gate32026-10-26)。01～07、10～13 保留已批准行为；2026-10-26 在 04 上的 14 方法回归通过见 [运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-websocket-既有订阅回归与下一步2026-10-26)。以下迁移经过和24版结果保留历史依据，不替代本次固定04的实际结果。

历史迁移批次沿用已通过的 [Gate1 范围](signing-subscriptions-scope.md)，将现有事件与恢复用例迁移到 WebSocket 签名订阅。固定目标为 [PR #1623](https://github.com/nervosnetwork/fiber/pull/1623) 的 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；用户已明确通过 Gate2；FNN/SDK/测试驱动已在该提交同源构建，本批核心与订阅 30 个方法已在该版本通过；完整 40 条回归为 38 通过、2 失败，残余问题见测试目录 README，历史结果不转记为本版本通过。

用户先要求同时迁移 ID 与映射，随后选择完整前缀 `LSP-SUBSCRIPTION-*`：原 01～07 对应迁移为 `LSP-SUBSCRIPTION-01～07`；原 08/09 退休，不复用；新行为从 10 开始。Gate3 已将 Python 文件和测试名称迁移为签名订阅，并同步 TEST-MAP；本表勾选只表示映射存在，执行结果见测试目录 README。

## 既有行为的共同前提与观察口径

- T 是启用认证的公共 FNN，A/B 是两个不同的 Hosted 租户，P 是独立普通节点。各行使用独立环境，A–T/B–T 为私有 CKB 通道，真实 SDK 完成批准、注资验证、绑定及签名。只读观察器不生成签名。
- 专用 `rpc.ws_listening_addr` 从 WS 握手的 `Authorization: Bearer <token>` 保存凭证，认证在随后 RPC 调用时执行；不能把携带凭证等同于握手阶段拒绝。通过 `subscribe` 订阅 `channel_signing`。凭证须允许 `write("subscriptions")` 及对应 topic 读取，身份来自凭证。常规环境重新签发当前 token，不拿旧版缺少订阅权限的 token 冒充当前协议故障。
- C 表示连接，U 表示该连接返回的订阅 ID；保留其字符串/数字类型，以 `params.subscription == U` 关联 `subscribe` 通知。比较 `params.result.type` 与完整 `data`，不能只检查 channel ID 或日志。
- R1/R2 是同通道先后产生的完整 `SignatureRequired` 请求，S1/S2 是真实 SDK 已保存的完整提交。转发器冻结提交，独立 RPC 保存当前请求作为比较基准。签名 body 包含 `channel_id`、`request_id`、`partial_signature`、`next_material`。
- 建立订阅只补发当前待签请求，没有 `snapshot_complete`、历史游标或 session ID。每行预先冻结待签集合，收到预期内容后继续有界观察；需要证明“不投递”的场景，在观察窗口之后用同一订阅收到主动产生的正向事件证明它仍有效。ping、socket 未断开不够。
- 负向观察窗口为 5 秒，之后的正向事件最多等待 60 秒；持续收集并检查到正向事件到达为止。它只证明本次窗口内的行为，不宣称证明无限历史、严格 exactly-once 或同一毫秒的订阅/写入竞态。取消后旧缓冲帧不算违规，判断使用取消成功后才产生的新请求。

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
- 后续范围
  - watchtower 事件及链上结算 [unanalysed] — 已有独立范围草稿；本批完成后回到 watchtower Gate1。
  - topic 参数、过滤组合、容量及 token 运行中到期 [pending] — 当前批次聚焦迁移；后续单独确认范围，不将其算作本批覆盖。
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

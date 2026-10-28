# Gate1：将现有 LSP 签名用例迁移到 WebSocket 订阅

本文前半部分保留 `24b5c38` 的已批准迁移记录；最新推进范围见文末「2026-10-26：浏览器鉴权补充 Gate1」。新增范围已获用户明确确认，进入 [浏览器鉴权 Gate2](signing-subscriptions.md#浏览器鉴权-gate2共同断言输入与预算04c2064)；新增完整行集也已获用户明确通过，Gate3已完成新44/44及旧14/14验证，结果见测试目录运行记录。

建议下一批先改造现有用例，恢复当前 PR 版本的 Python 验证基础；删除已被产品移除的 SSE 专属行为。随后优先补无 pending TLC 的 watchtower 强关结算，再处理带 TLC 的超时取回。

沿用本对话的阶段：Gate1 评审范围及取舍，Gate2 评审完整用例行，Gate3 实现及执行。本文记录已获用户明确通过的 Gate1 范围；[Gate2 完整行集](signing-subscriptions.md)也已获用户明确通过，Gate3 已完成本批自动化迁移与验证，实际执行及完整回归中的残余问题见测试目录 README。用户进一步要求迁移 ID，并最终选择完整前缀 LSP-SUBSCRIPTION-*；以下历史旧 ID 仅用于定位迁移来源。

## 已核实的版本和本地内容

2026-10-23 通过 GitHub API 查询 [PR #1623](https://github.com/nervosnetwork/fiber/pull/1623)，并 fetch 对应提交后检查源码差异：

- PR 为 open，head 为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；base 分支为 `develop`，base tip 与 merge-base 均为 `2620b5b3fdca082092ce57797d0c22b65c33af59`。
- 相对已验证的 `40288844157cac8dd7fb025304be276cb1ac1f0b`，增加 14 个提交、变更 57 个文件。`bd5d7523` 移除 SSE，`ba4ef2c9` 引入 WS 签名订阅，后续提交调整权限、专用 listener 和业务事件发布。这是迁移范围的 diff，不是整个 PR 的验收。
- 测试分支为 `codex/lsp-core-regressions`，HEAD `7a3e750`；本地 FNN 实际输出 `fnn Fiber v0.10.0-rc1 (4028884 2026-10-21)`，构建清单中的 SDK/驱动也仍是该 SHA。产品 checkout 保持在干净的 `4028884`，仅获取新提交，未切换或构建。
- 已有 `reviews/review-feedback.md` 修改，以及未跟踪的 deadline 评审、10 条 deadline 测试、watchtower/hosted guards 草稿、`reviews/README.md`、`docs/analysis/`、`report/`、`source/ckb-cli` 和 `.DS_Store`。这些均保留；本次没有把未提交内容当成已批准或已通过。

Gate1 当时核对原始 JUnit 和 `.exit`：`4028884` 的核心回归为 `1 + 15` 条通过；SSE 批次为 13 条加 1 条旧 retry 回归通过，退出码均为 0。Gate1 时 `24b5c38` 尚未构建或运行；后续 Gate3 的实际构建及执行结果见 [LSP 测试说明](../../test_cases/fiber/devnet/lsp/README.md)，不使用历史通过数替代。

## 为什么先迁移，再补资金路径

| 方向 | 已有覆盖及实际缺口 | 建议顺序 |
| --- | --- | --- |
| 现有签名业务及事件用例 | 16 条核心业务仍有价值，但共用驱动调用的 `subscribe_events` 已移除；HTTP gate 的“再次查询”观测点也不能捕获新 WS 恢复；SSE 测试另依赖旧会话及快照标记 | 本批：适配订阅和故障检查点、保留业务判断，再执行回归，不能只升级 SHA 或改名 |
| 无 pending TLC 的 watchtower 强关结算 | 旧 [Gate1 草稿](watchtower-settlement-scope.md)尚未进入本批确认；本地驱动没有 watchtower 授权和独立链验证入口 | 紧接迁移之后单独评审；优先打通最短完整资金路径 |
| TLC 截止保护与最终取回 | 10 条本地 deadline 测试已有映射；旧 `8419c00` 仅有部分执行证据。TIMEOUT-10/11 到承诺确认、发票未误记 Paid，未证明退款、付款终态和资金解锁 | 当前版本先复核旧语义与归因，再补链上结算；不重复新增同义用例 |
| Hosted 延迟签名等候选 | 已有 [范围草稿](hosted-channel-guards-scope.md)，不是当前版本通过记录 | 本批不扩展，保持后续入口 |

特别保留两个问题：TIMEOUT-04 在 `8419c00` 有普通开通超时失败，05 的前提因此受阻；`4028884` 已让公共 T 对 Hosted 通道豁免普通 ACK 超时，同时保留 TLC 截止强关。旧 deadline 文档的“公共 T 30 秒后强关”不能继续作为归因依据。这些均不能由本轮源码阅读宣布已修复或仍执行失败。

## Spec

以下规则来自固定 head 的文档；只作为 Gate2 迁移依据，未运行验证。

### SPEC-01：通过 WS 订阅恢复待签状态

Condition: 在专用 `rpc.ws_listening_addr` 上，以租户凭证订阅 `channel_signing`。
Expected: 建立订阅时补发当前待签请求；随后发送状态变化，包括无待签状态；重连重新订阅恢复当前工作，没有独立快照结束标记或历史游标。
Observable: `subscribe` 返回的 ID 及 `params.subscription`、完整 typed `data`、真实签名 RPC 结果与原通道终态。
Basis: [subscription.rs：接口与恢复规则](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/subscription.rs#L115)。
Source: explicit
Testing: required

### SPEC-02：授权来自凭证，订阅相互独立

Condition: RPC 开启认证，客户端请求建立或取消订阅。
Expected: 要求 `write("subscriptions")`，建立时另需 topic 查询权限；租户/node 范围由认证确定。同租户可有多个独立订阅，取消只作用于同一连接所属的订阅；operator 按 host 权限处理，不能照搬 SSE 的一律拒绝规则。
Observable: 拒绝或接受结果、完整事件归属、取消结果，以及错误请求之后合法订阅收到新工作。
Basis: [subscription.rs：权限、身份与取消](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/subscription.rs#L16)、[tenant token 能力](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/lsp/token.rs#L15)。
Source: explicit
Testing: required

### SPEC-03：真实 SDK 自动重连并保持业务结果

Condition: 当前 SDK 进程已经处理完暂停事件，WS 传输被明确断开，进程、凭证和本地签名存储保持。
Expected: SDK 重连并重新订阅，处理仍待签的原工作；提交仍走真实 RPC，原通道继续完成，幂等与余额预期沿用已有业务用例。
Observable: 同 PID 的新握手/订阅、恢复事件及真实提交；原 channel ID、注资、付款/发票与余额结果。
Basis: [SDK EventStream](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/events.rs#L28)、[远程签名与幂等](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/docs/notes/hosted-lsp-remote-signer.md#L89)。自动恢复为 agent 行为；业务期望不因更换传输而放宽。
Source: explicit
Testing: required

## 测试树

- 现有 16 条核心业务（SPEC-03）
  - 正常开通/收款/关闭、RPC 隔离、幂等与原业务终态 [pending] — 复用，不因改传输增设重复业务用例。
  - RETRY-04/05 的故障后恢复 [pending] — 保留 ID；Gate2 修改“再次查询”的步骤，观测同 SDK 的真实 WS 重新订阅，保留 HTTP 未送达/响应自然超时的故障与判断。
  - SDK/FNN 恢复的冻结与原请求证据 [pending] — 核对所有 `_restore_sdk`、`_restart_fnn` 调用；Gate2 明列受影响行，不把 `pause_queries` 当成 WS 已暂停。
- 现有事件行为迁移（SPEC-01、SPEC-02、SPEC-03）
  - 初始待签、实时下一请求、A/B 隔离 [pending] — 对应原 01/02/03，Gate2 沿用编号并改为完整 SUBSCRIPTION 前缀。
  - 无权订阅及错误请求不干扰原连接 [pending] — 对应原 04，按新权限契约重写；删除无效的会话参数分支。operator 允许订阅但限 host 的判断另分新 ID，不混进拒绝行。
  - 原待签恢复、真实 SDK 自动恢复、重连后只恢复当前请求 [pending] — 对应原 05/06/07，沿用编号并改为完整 SUBSCRIPTION 前缀，去掉 session/快照标记。
  - SSE 会话接管与旧 SDK 收到 409 后退出 [pending] — 原 08/09 列入 Gate2 删除行集及对应自动化清理。
  - 同租户独立订阅与按连接取消 [pending] — 新契约，若接受此范围，在 Gate2 分配新 ID；不复用 08/09 代表新行为。
- watchtower 请求与资金结算 [unanalysed] — 本轮仅核对依赖及旧草稿；WS 基础恢复后回到独立 Gate1，不合并进本批用例表。

## 用例：本轮只评审迁移取舍

Gate1 不修改正式五列表。用户后续明确选择完整 LSP-SUBSCRIPTION-* 前缀：Gate2 将原 01～07 迁移到新前缀，08/09 退休不复用，新增从 10 起；[完整修改及删除行](signing-subscriptions.md)已获人工确认，Gate3 同步全部映射。

| 处理 | 现有条目 | 保留的判断与必须变化的部分 |
| --- | --- | --- |
| 改造 | LSP-SSE-01 | 保留已有 R1 的完整内容、请求未推进和原通道完成；用订阅 ID 与预先冻结的待签集合取代 HTTP 200、SSE 类型、会话 ID 和 `snapshot_complete` |
| 改造 | LSP-SSE-02 | 保留原连接收到真实 R2、期间不查询或重连、内容交叉核对；改读 WS notification，并明确订阅 ID |
| 改造 | LSP-SSE-03 | 保留 A/B 初始和后续事件隔离及两条通道完成；去掉 25 秒心跳观察依据，用明确推进后的正向事件证明仍连通 |
| 部分保留、部分删除 | LSP-SSE-04（现 5 个方法） | 保留缺 token、无效 token 的拒绝方向，按新权限细化；删除 `tenant=B` URL 参数、畸形 session header 及 operator 必须拒绝的旧分支。operator 允许订阅但限 host 是独立新行为，Gate2 另分新 ID，须有正向 host 事件并证明租户事件不投递，不能以空 host 范围的静默通过 |
| 改造 | LSP-SSE-05 | 保留未提交 R1 的完整补发及状态不推进；重新订阅不再携带或比较 H1 |
| 改造 | LSP-SSE-06 | 保留同 PID、原存储、真实签名和自动恢复；精确断开真实 WS，再证明 SDK 自行建立新订阅，不能由 Python 手工订阅代替 |
| 改造 | LSP-SSE-07 | 保留重连恢复 R2 而不是已应用 R1；没有快照结束标记，Gate2 需按冻结集合和有界观察写清判据 |
| 删除 | LSP-SSE-08 | 产品已移除单租户会话接管、H2/H1 与 409，删除该行及对应测试；新的并存订阅行为另起 ID |
| 删除 | LSP-SSE-09 | 产品已移除 `session_replaced` 导致旧 SDK 退出的流程，删除该行及对应测试；原存储恢复仍由 05/06 及核心恢复用例证明 |

删除依据是当前契约已移除相应行为；迁移中发现仍成立的断言失败时保留失败，不以“无效”为由删除。此表是 Gate1 取舍建议，不表示已改造后的数量或执行结果。

## Gate2 需写实的实现边界

- 复用 `_lsp_test.py`、真实签名 gate、已有业务断言和构建脚本。FNN/SDK/驱动固定同一 SHA；本地加专用 WS listener 和独立端口，不占用已有节点端口或修改公共 framework。
- 本地 `_sdk_driver.rs` 需要从已移除的 `rpc.subscribe_events` 改调官方 `EventStream::connect`，传入专用 WS URL；只适配 Python 控制驱动，不修改 FNN/SDK 产品代码、不新增 Rust 测试。Gate2 明列最小改动后再进入实现。
- 用 WS 观察/断线工具替换 `_sse_observer.py`；HTTP 签名提交 gate 仍保留。旧 `forward_events` 等仅在确认没有剩余调用后清理，不影响无关 HTTP 重试。
- 核心测试也要迁移故障控制：`_wait_for_fault_repoll` 依赖的 `gate.repolled` 目前只由 SSE GET 或签名状态查询置位，新 SDK 失败后重新 WS 订阅不会触发它。RETRY-04/05 必须在真实 WS 侧捕获恢复尝试；04 保留“原提交未送达”，05 保留“FNN 已 Applied、原 HTTP 响应没有发送且由客户端自然超时”。不能提前关闭 05 的 HTTP 请求来制造恢复。
- 恢复辅助方法中的 `gate.queries` 与 `pause_queries` 同样依赖旧入口。Gate2 须逐一核对调用：SDK 重启仍证明新 PID、原身份/存储、未重新授权及原工作；FNN 重启保留原数据及同 SDK PID；RECOVERY-03 必须在退出前阻止 SDK 经 WS 学到 R2，而非仅检查已失效的 `repolled`。相关行和观察步骤列入 Gate2，业务终态及一次结算判断保留。
- 旧凭证未必有 `write("subscriptions")`；常规用例重新注册取得当前 token，保留的 SDK/FNN 原存储恢复发生在本条用例内。跨版本旧 token 的迁移另行评审，不通过扩大权限掩盖拒绝。
- 不能用 `--once` 轮询模式冒充实时推送。初始补发无结束标记，Gate2 需定义冻结集合及有界负向窗口；窗口之后须在同一订阅 ID 收到主动产生的新事件，只有 WS socket 存活或 ping 成功不足以证明订阅仍有效。不承诺集成测试证明同一毫秒的订阅/写入竞态。
- 当前 SDK 的连接/请求预算各 10 秒、退避从 200 毫秒增长至最多 10 秒并加抖动；与旧 SSE 不同。Gate2 单独规定事件和重连等待上限，且检查开通/TLC 剩余业务窗口；测试等待预算不是产品 SLA。
- 先执行真实开通→收款→关闭，再运行改造后的事件用例和受影响的核心恢复/重试范围；最终维护 TEST-MAP 与复选框。改/删正式评审行及测试在同一实现批次对齐，映射不等于通过。

## 资金路径的后续边界

watchtower 仍优先选私有 CKB、无 pending TLC、公共 T 强关：跟踪“原注资输出 → 承诺输出 → 最终结算输出”，同时证明所属 SDK 授权/签名被接受、交易确认、地址及 sponsor 输入/找零与实际费用相符。只看到 `Closed` 不算取回成功。

在当前 head，[上游场景](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/bruno/e2e/lsp-remote-signer-watchtower/README.md)仍显式批准结算到公共 T 的 sponsor 钱包；这不证明租户独立钱包取回。当前 [独立 chain verifier](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/tests/fiber-lsp-sdk-agent/src/chain.rs#L89)仍假设 genesis 合约输出 5/6/7，本地 Python devnet 的部署来源需适配核对；本地驱动也尚未暴露 Watchtower 授权。这些前提没有因改 WS 自动解决。

带 TLC 的超时退款须进一步证明目标 TLC 确实进入广播承诺、未释放 preimage、链上到期花费确认、付款终态及金额解锁；真实路由支付的长期 expiry 与 debug 注入场景必须分清。成熟条件按实际 `since`/epoch 验证，不能靠固定挖块数或固定 sleep。上述内容留待独立范围与用例确认，不计入本批完成条件。

## 核验与下一门禁

- GPT 6.1 sol 独立复核发现核心重试/恢复观测迁移及 operator 行为拆分两项问题；已按意见修订并复核，未发现尚存 Gate1 阻塞。复核仅涉及本文范围和源码依据，不代表用例已获人工确认或测试执行通过。
- 已只读比较固定提交，核对原始 JUnit、构建版本及本地改动；本轮没有启动节点或执行 pytest。
- 项目 `check_test_map.py` 在本轮修改前已退出 1：既有 `PMP-01～05`、`SETTLE-01` 孤立映射，以及 `report/.../test-overlay/reviews` 历史副本导致 16 个核心 ID 重复。本批不删除本地报告或跨范围修检查器。
- 仓库当前没有 `scripts/check_test_design.py`，映射检查器也没有 `--review` 选项。Gate1 尚无正式用例行，设计结构检查留到 Gate2，届时使用 skill 提供的检查器核对适配方式。

已获用户确认的 Gate1 范围：**迁移现有 16 条核心业务及事件 01～07（包括重试/恢复检查点）；删除事件 08/09 和 04 的旧 URL、会话头、operator 拒绝分支；另列最小的 operator host 隔离及独立订阅/取消行为。** 该完整改/删/新增行集也已获用户明确确认，后续实施与当前版本结果见签名订阅评审及测试目录 README。

## 2026-10-26：浏览器鉴权补充 Gate1

用户收到开发者“方案稳定”的反馈后要求优先推进 WebSocket。当天只读查询 PR #1623：仍为 open，head 为 `04c206465b48da85b99aa58e80afe9801a2cb2db`；本地产品 checkout 与构建清单同源，无需再次切换版本。开发者反馈作为优先级依据，不代替源码契约或运行结果。

### 环境阻断的适用范围

watchtower 适配自检发现当前 devnet 中 CommitmentLock Type ID 所指向的 live 合约字节与固定 04 可信模板不一致（107,784 对 80,880 字节），因此在 `watchtower-configure` 阶段拒绝。完整原始证据和摘要见 [运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-watchtower-gate3合约预检阻断2026-10-25)。这属于尚未满足的验证环境前提，未确定链上二进制的源码版本，也未据此认定 Fiber 产品 bug。

现有 `test_signing_subscriptions.py` 不调用该链验证配置；已有 14 个方法覆盖 11 个签名订阅行为。本轮先运行这些已批准方法，当前版本结果单独记入 [LSP 测试说明](../../test_cases/fiber/devnet/lsp/README.md)，不将 24 版结果转记。普通签名订阅通过也不能证明强关结算合约兼容。

watchtower 的恢复方案另行处理：仅在隔离的临时 devnet 中准备与固定模板一致的合约，再执行原适配自检和正式 1+3 批次。原 Gate2 明确禁止字节不符时自动部署/升级，本轮不改变该边界，不通过换信任源或跳过校验消除错误。它不作为下面浏览器鉴权范围的前置条件。

### 本批建议：只补浏览器鉴权入口

Gate1核对时观察器仅支持Bearer header；Gate3已增加可选浏览器子协议参数。普通订阅的初始工作、实时下一请求、租户/host 隔离、SDK 重连和独立取消已有批准用例；复用这些行为判据，不重新迁移 ID，也不把 SSE 语义带回来。

固定源码依据：[浏览器入口及权限说明](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L44)、[握手凭证归一化](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/middleware.rs#L25)。以下是范围拆分，尚未创建正式用例行或新增 TEST-MAP。

- 正常浏览器凭证接入 [pending]：使用真实注册返回的未填充 base64url token，同时提供 `fiber-rpc` 和 `base64url.bearer.authorization.fiber.<token>`；核对协商结果仅为 `fiber-rpc`，不回显凭证协议；建立订阅后接收真实完整 R1/R2，再由原 SDK 完成原通道。兼容输入包括旧格式 token 去掉尾部填充后用于子协议、Bearer header 对带/不带填充的接受；不能对 token 再做一次 base64 编码。
- 握手拒绝及故障隔离 [pending]：提供凭证子协议却缺少 `fiber-rpc`、多个凭证、同时提供 Authorization header 与凭证子协议、空或非法 base64url 编码，均在服务端握手阶段拒绝。普通 Bearer 连接不要求 `fiber-rpc`，不误判为拒绝输入。必须证明请求实际送到服务器，不能把 Python 客户端本地参数校验异常算通过；错误连接之后合法原订阅仍收到主动产生的新事件。
- 同一鉴权与租户边界 [pending]：子协议归一化后仍须通过 Biscuit 与 `write("subscriptions")`、topic 读取权限检查。编码合法但签名/内容无效的 Biscuit，以及缺写/缺读权限，区分为 subscribe 的真实 JSON-RPC 拒绝，不能混写为握手失败。合法 A/B 浏览器凭证各收到所属初始与新事件；不能只检查没有事件的静默窗口。

### 验证方式与边界

仍是 Python 功能测试：通过真实 WS 握手头和消息测试服务器提供给浏览器的入口，保留握手响应、订阅响应、事件及最终通道证据；不生成假事件或模拟 FNN 成功响应。必要时仅为现有本地观察器增加子协议参数及握手证据获取，不修改 FNN/SDK 产品代码。此方式不声称已覆盖某一浏览器引擎、页面集成、TLS 或反向代理配置。

Gate2 再展开完整行集、各失败层次、有限等待与共同断言，展示后仍须用户明确确认该行集，才可进入 Gate3 实现；本轮范围确认不授权新增自动化。新独立行为使用 `LSP-SUBSCRIPTION-14` 起的 ID，不复用已退休的 08/09。已批准且预期不变的 01～07、10～13 保持原 ID 和映射。首次聚焦通过后再按 Gate2 的固定次数复跑，不能通过重试筛掉失败。

后续候选依次为 `channel_ids` 过滤/非法参数、凭证过期与换证重连、每连接 32 个订阅的功能边界。凭证到期不终止既有流，但新的 subscribe/unsubscribe 必须重新鉴权，不能预设到期自动断流。全局容量压测、慢消费者压力、真实 watchtower 待签事件和链上结算不混入本批；watchtower 的空订阅也不能当成真实事件链通过。

以上三个方向及 Python 线级验证边界已获用户确认；当前 [Gate2 完整行集、共同断言及预算](signing-subscriptions.md#浏览器鉴权-gate2共同断言输入与预算04c2064)已获用户明确通过，新增方向Gate3已完成，正式44/44及相关旧14/14通过，GPT6.1 sol已复核代码和结果。

GPT 6.1 sol 已只读复核固定源码、现有覆盖与本节范围，未触发 Daybreak；未发现方向性阻塞。已按反馈限定“带凭证子协议时缺少 fiber-rpc”，并明确完整 Gate2 行集仍须再次确认。服务端握手拒绝有真实 HTTP 400 依据；后续 Python 输入应使用 HTTP 合法但 base64url 非法的值并保存服务器响应，避免客户端先拒绝。旧 padding 仅验证固定 04 版本的输入兼容，不宣称跨版本迁移通过。此复核不代表新增用例或浏览器入口已执行。

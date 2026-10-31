# Gate1：将现有 LSP 签名用例迁移到 WebSocket 订阅

## 2026-10-30 普通订阅版本验证 Gate1（主会话，已确认）

后续纠正：用户指出这些订阅用例原本已存在，要求先整体盘点遗漏。本批是旧场景的版本回归，不是新增覆盖；Gate2草稿保留但暂缓，不据此前确认自动实施或执行。当前实际状态以LSP README顶部整体盘点为准。

用户要求补充测试回到主会话，按 Gate1 → Gate2 → Gate3 逐阶段确认；此前自动推进授权不用于跳过本批确认。当前只评审普通订阅的版本验证范围，不改自动化、不运行节点，不把 TIMEOUT 或 Watchtower 合并进本批。退款已由用户接受两轮独立通过收尾，不再补原计划第3/4轮。

### 已核实的基线与缺口

- 固定产品 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；本地 `download/fiber/source-pr-1623-84333ee` 的 HEAD 匹配且工作区干净。本次不声称这是重新联网查询的最新 PR head。
- 候选产物 `report/lsp-invoice-cancel-84333ee-20261030T003644/bundle/fnn --version` 返回 `fnn Fiber v0.10.0-rc1 (84333ee 2026-10-28)`。这只核对自报版本；完整 manifest、FNN/SDK/driver/源码摘要和环境资格须在 Gate3 启动前重新核验。
- 本批八个 ID 有现成自动化及旧版本执行记录，缺的是固定843的完整执行结果。此前 `report/lsp-long-regression-84333ee-20261030T022936/` 在准备中被停止，不能记为这些场景已经完成843验证。
- 对固定源码的局部比较：`24b5c38..84333ee` 的 `rpc/subscription.rs` 仅新增35行浏览器鉴权说明，`rpc/subscription/service.rs` 与 SDK agent `events.rs` 无差异。这是本次局部契约复用的依据，不等于整个鉴权链或整个PR无变化。

### Spec 与测试树

沿用[主评审的 SPEC-01～04 及既有行集](signing-subscriptions.md)，本批不改变预期或重编号：

- 当前工作与恢复（SPEC-01、SPEC-03）：初始完整待签补发 → `LSP-SUBSCRIPTION-01`；未提交请求重连补发 → `05`；同一真实 SDK 进程断线后恢复原签名 → `06`；重连只恢复当前请求、不重放已应用请求 → `07`。
- 权限与身份范围（SPEC-02）：缺token、无效token、缺订阅写权限、缺通道读权限分别拒绝且合法订阅继续推进 → `04`；operator收到真实host正向事件且不泄露租户私有请求 → `10`。
- 并存连接与取消（SPEC-04）：同租户两个连接均收到完整新状态、不互相接管 → `11`；跨连接及未知ID取消返回false，两个原订阅仍可继续 → `13`。

固定843的源码依据为 `crates/fiber-lib/src/rpc/subscription.rs` 的认证/身份选择与 subscribe 实现、`crates/fiber-lib/src/rpc/subscription/service.rs` 的初始及实时状态流，以及 `tests/fiber-lsp-sdk-agent/src/events.rs` 的真实SDK重连/重新订阅。取消的连接所有权沿用已确认 SPEC-04，不在本批将行为扩展为全局ID唯一或跨重连exactly-once保证。

### 用例范围与验证边界

| 范围 | 保留的独立判断 | 方法数 |
| --- | --- | --- |
| 初始补发（01） | 初始补发完整R1，不推进原待签；原通道完成 | 1 |
| 凭证与权限（04） | 四种凭证/权限分别在RPC拒绝；每次原合法订阅仍收到新R2 | 4 |
| 断线恢复（05/06/07） | 普通重连、真实SDK同进程自动恢复、只恢复当前工作 | 3 |
| host范围（10） | operator有真实host正向事件且不泄露租户私有R1/R2 | 1 |
| 并存与取消（11/13） | 独立并存订阅与取消所有权，不破坏原通道 | 2 |

共8个既有ID、11个方法，保留所有既有TEST-MAP；正式五列表不变，复选框只表示已映射。Gate2展开本批的完整输入、观察顺序、资金/终态边界、全部选择器及最小适配；Gate3才按确认方案执行，每个方法一次，不再套用1+3重复。

- 共同成功条件保留真实SDK/FNN、完整R1/R2内容、正向事件对照、原channel/funding身份、双方就绪与既有余额稳定检查。现有共同断言不含双方余额互为镜像，不宣称已经覆盖；若Gate2拟增加此断言须明确列出。06必须保留同PID、原token/存储、真实重新订阅及原签名首次Applied证据，不能由Python手工恢复代替。
- 负向只证明实际观察窗口：不以socket存活/无消息替代业务正向对照；04不把WS握手失败当RPC权限拒绝；10允许同channel合法host状态，不能将它误判为租户泄露；13不假定跨连接ID全局唯一。
- 本批不验证付款/TLC/强关退款、不启动VM或调时，也不宣称全PR验收。已有843结果的02/03/12、浏览器14～19、过滤20～28不重复；新能力如多通道严格子集、凭证到期、订阅配额仍不在本批。
- 初步预算建议45分钟硬上限：产物/环境与必要适配核验15分钟、11方法单次串行25分钟、证据及清理5分钟。此为Gate1建议，Gate2须结合方法历史耗时和实际输入确认；不因预算不足削减断言。候选产物不匹配时先报告必要适配，不能隐式切产品或发起大型重建。
- 执行遇失败或超时停止本批，保留已经完成、失败及未运行项，区分环境与产品，不挑结果反复重跑。独立复核沿用GPT-6 Sol High；主会话负责阶段决策、适配和执行，不再交给夜间分支持续执行。

用户已明确确认本节8个场景、11个方法的Gate1范围；主会话已展开[Gate2完整输入、断言、预算与最小适配](signing-subscriptions.md#2026-10-30-普通订阅版本验证-gate2固定84333ee)，等待本批Gate2评审。本次没有修改自动化或运行测试；下文均为历史阶段记录，保持原样。

本节静态复核：GPT-6 Sol High核对8ID/11方法、局部源码变化及版本边界；指出“余额镜像”并非现有断言，已按代码修正为余额稳定。设计检查退出0，映射检查退出1仍为9个既有孤儿映射、无重复ID，diff空白检查退出0。普通分支取消记录确认22个方法均未执行，未启动构建或测试，后续仅由主会话推进。

调整后的[过滤参数Gate1](#2026-10-28过滤参数补充-gate1)及[Gate2行集、数组兼容和预算](signing-subscriptions.md#过滤参数-gate2输入断言预算与最小适配04c2064)均已获用户确认。Gate3实现后04产物准备因缓存版本不匹配停止；用户随后明确授权更新LSP分支，本批固定 `84333ee` 独立重编并完成相关3/3及正式1+3共48/48，见[最新运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-订阅过滤-gate3完成2026-10-29)。历史24迁移及04浏览器结果保留，不合并为843全量通过；同身份多通道严格子集仍是覆盖缺口。

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


## 2026-10-28：过滤参数补充 Gate1

本轮只评审普通 `channel_signing` 的过滤与非法参数范围。继续遵守本会话的 **Gate1 范围 → Gate2 完整行集、预算与适配方案 → Gate3 实现及验证**；本节不新增正式用例 ID、复选框或 TEST-MAP，已有 01～07、10～19 不变。退款夜间专项仍由用户手动运行，本轮没有启动测试、VM 或其他批次。

### 基线、现有覆盖与前提修正

2026-10-28 只读核对 PR #1623 仍为 open，最新 head 为 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`。实际分析与后续建议验证继续固定 `04c206465b48da85b99aa58e80afe9801a2cb2db`：原仓库 `download/fiber/source-pr-1623` 为该提交且干净，现有 `pr-1623-04c2064/fnn --version` 输出 `Fiber v0.10.0-rc1 (04c2064 2026-10-23)`。没有切换源码或重新构建，也没有把其他版本通过算入本批。

评审编辑位置为干净起始的 `codex/lsp-reviewed-regressions` worktree（起点 `c85da0b`）；原 `codex/lsp-core-regressions` 工作区的未提交内容、快照及全部运行证据保留。两处 checkout 不同步或重置。

**更正此前建议：不能在固定 04 上准备“同一 Hosted 租户两条私有待签通道”。** [SDK session](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/session.rs#L279) 在已有 binding 时只允许原开通请求重入；[registry](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/lsp/registry.rs#L245) 也限制租户绑定唯一私有通道。不能通过复制 SDK 存储、换身份、改产品或重复尝试绕过。A/B 各一条可证明隔离，不能证明同一授权集合内排除另一条通道。

已有 Python 订阅用例覆盖默认订阅、A/B 隔离、host 范围、重连和独立取消，没有显式过滤参数行。上游固定 04 的 `rpc/subscription/service/tests.rs` 已有内存源的过滤/去重测试，`rpc/subscription/tests.rs` 已有部分非法选项/未知 ID 测试；这些是既有源码证据，本轮未执行，也不替代 Python 真实 SDK/节点集成。现有 operator 用例仅以普通 host 通道的 `NoSignatureRequired` 验证正向事件，不能声称已有两个 SDK 待签通道的初始与实时过滤夹具。

### Spec：本批依据

#### SPEC-04：过滤集合与默认值

Condition: 有效租户凭证订阅 `channel_signing`，可选参数为 `channel_ids`。
Expected: 省略过滤选择全部授权通道，空数组选择零通道；指定 ID 约束初始待签与后续状态。省略 options、`{}`、options 为 `null`、`channel_ids` 为 `null` 在固定 04 均走默认全集；重复 ID 不扩增同一待签工作。
Observable: 订阅 ID、按该 ID 归属的完整 R1/R2 与空集窗口；最终原通道双方就绪、注资不变。
Basis: [RPC 文档](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L114)、[Options 类型](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-json-types/src/subscription.rs#L20)、[初始及实时过滤](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L84)。null 和重复 ID 为固定实现的兼容性观察，Gate2 单列输入，不扩大为跨版本保证。
Source: explicit / observation
Testing: required

#### SPEC-05：输入格式与长度限制

Condition: 有效凭证通过 WS 调用 subscribe，变更 topic、options 或 channel_ids。
Expected: 未知 topic/字段、明确非法的参数类型（例如 options 数字/布尔/字符串）和不能解码为 32 字节的 Hash256 被 RPC 拒绝；已列 null 兼容形式不属于非法输入。原始 ID 数组最多 256 项，去重前的 257 项也拒绝。
Observable: 请求确实发出，服务端 JSON-RPC 错误且无订阅 ID；同连接原合法订阅仍能收到真实新请求。256 个重复合法 ID 可建立订阅但只表示一条通道的工作。
Basis: [JSON 类型约束](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-json-types/src/subscription.rs#L11)、[长度检查在去重之前](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L69)、[Hash 解码](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-json-types/src/serde_utils.rs#L11)。不把可接受的无前缀、`0X` 或大写十六进制误列为非法。
Source: explicit / observation
Testing: required

#### SPEC-06：过滤不扩大授权，列表整体建立或拒绝

Condition: A 凭证指定未知 ID、B 的真实私有 channel ID，或与 A 自有 ID 混合。
Expected: 身份由凭证决定；不能读取的 ID 使整个 subscribe 失败，不能静默跳过、建立部分订阅或泄露 B 的待签状态。
Observable: B 的通道和 R1 确实存在；A 的非法请求无订阅 ID，完整连接记录中无孤立或越权通知；随后 A 原合法订阅仍收到新 R2。
Basis: [租户 store 来源](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L288)、[逐项读取失败即返回](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription/service.rs#L208)、[完整初始化后才接受订阅](https://github.com/nervosnetwork/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/subscription.rs#L343)。整体拒绝按固定实现提出；不将错误文案或耗时相同提升为防探测保证。
Source: explicit / observation
Testing: required

### 测试树：范围分解

- 合法选择（SPEC-04）
  - 默认全集 [pending]：A 唯一私有通道冻结 R1，分别省略 options、传 `{}`、options `null`、`channel_ids: null`，各订阅收到 R1 及主动推进的 R2。
  - 显式全集 [pending]：`[A]` 与 `[A, A]` 可订阅，完整 R1/R2 属于 A；同一冻结工作不因重复 ID 增发。只证明唯一通道的显式选择，不称多通道子集。
  - 空集合 [pending]：`[]` 获得有效订阅 ID，初始窗口和真实 R1→R2 推进后均无该 ID 的通知；同连接默认订阅收到 R2，空订阅随后取消返回 true。
- 非法输入（SPEC-05）
  - 解析拒绝 [pending]：未知 topic、非字符串 topic、未知 options 字段、options 为数字/布尔/字符串、channel_ids 为既非数组也非 null 的值、数组项非字符串、错误长度/奇数长度/非十六进制 Hash，逐个独立请求被拒绝且不破坏原合法订阅。
  - 数组上限 [pending]：256 个重复 A 接受并只发一份冻结工作；257 个重复 A 拒绝，证明限制作用于原数组。接受与拒绝是两个判据，Gate2 分开展开。
- 授权与原子性（SPEC-06）
  - 单个不可见 ID [pending]：未知 ID、真实 B ID 分别拒绝；B 自己能收到该待签状态作为存在性对照。
  - 有效/不可见 ID 混合 [pending]：`[A, unknown]`、`[unknown, A]`、`[A, B]`、`[B, A]` 均整体拒绝，无部分工作泄露，A 原合法订阅仍推进。
- 明确保留的缺口
  - options 数组形态 [pending]：文档约定对象，但 serde 的结构体顺序反序列化可能接受某些数组；本批不笼统承诺所有数组均拒绝。Gate2 先沿完整 RPC 参数反序列化路径核实，再决定兼容行为或待确认预期，不修改产品来满足测试。
  - 同一授权范围内多条真实待签通道的严格子集/全集过滤 [pending]：Hosted 固定 04 单通道限制；以后单独核对支持多通道的产品版本，或另提 host 外部签名拓扑与契约。不能用 A/B 或 host 无待签事件替代。
  - 凭证到期/换证、每连接 32/33 限制 [pending]：另批范围；本批 256/257 是 channel_ids 项数，不是订阅配额。
  - watchtower topic 过滤、慢消费者/全局压力、订阅和写入的瞬时竞态 [pending]：需要各自源、负载或并发判据，不在本批作覆盖承诺。

### 用例：Gate1 取舍与验证边界

本轮不改正式五列表；Gate2 在范围获确认后为上述独立行为分配 `LSP-SUBSCRIPTION-20` 起的新 ID（不复用 08/09），展开完整输入、优先级、共同断言、逐阶段及绝对总预算。仅增加未映射行，不把源码观察写成执行通过。

- **真实业务对照**：复用已确认夹具，冻结真实 SDK 的 R1/S1，建立观察订阅，再应用真实 S1 产生不同 request ID 的 R2；收到事件后才查询交叉核对，最后恢复原 SDK 完成原通道。需 A/B 的分支各自核对其原通道完成及注资；不为负向输入制造假事件。
- **有限负向证据**：无快照结束标记，以冻结的已知待签集合和有界观察判定；按每个订阅 ID 保存全量通知，不能只检查 socket 活着。空订阅不可能收到正向事件，因此用同连接对照订阅的 R2 加空订阅自身取消 true，证明业务源推进和注册存活；仍只证明观察窗口内为空。
- **拒绝必须来自服务端**：客户端送出原始 JSON 后检查实际 RPC 错误；本地参数异常、握手失败、过期凭证均不能算本批参数拒绝通过。非法请求前后保留整条连接的响应与通知，检查没有失败请求残留的孤立事件；不以“没有拿到订阅 ID”代替泄露检查。
- **最小适配**：现有 `_subscription_observer.py` 已支持 options 和原始 `request`；显式 `null` 用原始请求避免被 helper 变为省略。优先新增普通 LSP 测试文件，复用现有单租户及 A/B 夹具、签名 gate 和通道终态断言。Gate2 再核对局部 helper，暂不承诺修改 SDK driver 或公共框架；不绕过单通道限制。
- **普通任务边界**：本批不发起付款、TLC 或强关，不需要 VM、时间跳变或等待链上成熟。256/257 用重复真实 A 测请求长度，不准备 256 条通道，也不称吞吐或容量压测；不加入夜间专项。实际测试时长和固定复跑数留 Gate2 依据既有开通窗口确定，不能由本次源码阅读宣称快速通过。
- **失败与证据**：以后执行时，前提未成立、环境失败、服务端拒绝与断言失败分别记录；固定批次遇产品失败即停，沿用已知归因，不更换版本或反复取样。现有运行记录和 TEST-MAP 保持事实含义，本轮没有新映射或测试结果。

本次下一门禁是确认上述收窄后的 Gate1 范围，尤其接受多通道严格子集仍未覆盖，再进入 Gate2 完整用例评审；不是批准现在写自动化或执行。


### 本轮静态核验

GPT 6.1 sol 的独立复核已纠正两个前提：单租户两私有通道不可构造；不能将 null 或所有 options 数组一概视为非法。已纳入上述范围和待确认项；修订后复核未发现剩余 Gate1 阻塞，可交用户确认。复核是文档/源码检查，不代表行为运行通过。

- `git diff --check`：退出 0，仅三个评审 Markdown 文件变更。
- `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root . --review reviews/lsp/signing-subscriptions.md`：17 条既有用例，退出 0；只验证原正式行与树的结构，不替代本节 Gate1 或未来 Gate2 的语义评审。
- `python3 scripts/check_test_map.py`：103 条评审、99 条映射，退出 1；仅既有 `PMP-01～05`、`SETTLE-01` 六个孤立映射，无重复评审 ID。本批没有映射变化，数量不是功能覆盖率。
- 未运行 pytest、节点、VM 或夜间批次；未修改产品、版本或宿主时间。


2026-10-28 后续：用户明确确认本节调整后的Gate1，并要求展开Gate2。现已在[主评审文档](signing-subscriptions.md#过滤参数-gate2输入断言预算与最小适配04c2064)新增20～28九行及完整预算；options数组静态核实为[null]/[[]]/[[A]]兼容，[]/[null,null]/[A]拒绝，兼容回归选择随28交人工确认。保留本节历史待核记录，不把静态核实当运行通过。

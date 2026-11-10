# Hosted 租户边界：查询与运维 RPC

历史范围（SPEC-01～05）：候选 `56c761c45c271c086b05c8d5ea3e033448f5fdf8` 上的一批黑盒租户边界：默认命名空间查询、显式 tenant_id 查询、tenant token 对 operator RPC 的越权，以及 operator-only 方法分类。A/B 均使用真实注册、真实 external funding 和真实 ChannelReady 通道；当时不额外制造付款，付款 own-namespace 读取和 eviction 门禁留作后续。当前付款查询评审见下方固定763的新增范围。

56c 历史依据：[Hosted LSP 文档](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)（租户数据面、admin 权限与 eviction 语义）、[tenant RPC 查询解析](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs)、[invoice RPC](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/invoice.rs)、[Biscuit 权限规则](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/biscuit.rs)。A/B 是不同 Hosted 租户，P 是付款方，T 是 LSP；A/B 使用各自真实 tenant Biscuit，不能用 operator token 代替。

本次新增评审（2026-11-09）：只分析 **native `get_payment` 的真实付款查询隔离**，固定产品 `76307312e8de518c9a32074e6d16867c04de4f86`，测试基线为已合并 PR #16 的 `fa4a3b7c7853b926f79108e3a6b86c54bc4d397f`。下方原 SPEC-01～05、QUERY-01/02 和 ADMIN-AUTH-01～03 保留 56c 的历史范围及用例行；本批新增 SPEC-06～08、QUERY-04～06，不把历史执行转记为 763。QUERY-03 曾在旧评审撤回，本次不复用这个编号。

用户已明确确认 QUERY-04～06 三条用例，并在 QUERY-04 首例修复、自审后授权继续实现 QUERY-05/06。当前三条均有独立自动化入口；最新验证见本文末，首例及修复记录保留为历史。复选框只表示 TEST-MAP 是否存在；本文的自审不称独立 B 复核。`list_payments`、发票/付款修改、eviction、重启及其他付款失败场景均不在本批。

## Spec

### SPEC-01：默认查询只落在调用者自己的命名空间

Condition: A 和 B 均已注册并持有有效 tenant token；A 创建一张真实 Open hold invoice；B 创建自己的 Open 发票。
Expected: B 用普通 `get_invoice`（不带 tenant_id）查 A 的 payment hash 时返回发票不存在，不返回 A 的内容；B 查自己的发票成功，A 查自己的发票成功且状态不变。
Observable: B 查 A hash 的 JSON-RPC 错误、B 查自己发票的完整结果、A 查自己发票的完整结果。
Basis: [tenant token 选择租户命名空间；无目标时只查自身](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)；[resolve_tenant_query_rpc_context 的默认分支](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs)；[get_invoice 在自身 store 查不到才报 not found](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/invoice.rs)。
Source: explicit
Testing: required

### SPEC-02：显式 tenant_id 不能越权

Condition: A/B 均已注册；A 有一张真实 Open invoice；operator token 具备 `read("lsp")` 与 `read("invoices")`。
Expected: B 带 `tenant_id=A` 查询 A 的发票被拒绝；operator 带 `tenant_id=A` 查询同一发票成功，证明目标路由本身有效；A 的发票和状态不变。
Observable: B 显式目标的错误、operator 对 A 的正向查询结果、A 发票与通道状态。
Basis: [显式 tenant_id 只作单独授权目标；tenant token 不能查询其他租户](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)；[显式不相等在解析 store 前报错](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs)。
Source: explicit
Testing: required

### SPEC-03：tenant token 不能调用 operator 的 LSP 读 RPC

Condition: A/B 持有有效 tenant token；A 能正常调用 allowlist 内的租户方法；operator token 可用。
Expected: A 调 `lsp_list_tenants` 被拒绝；A 调一个允许的租户方法成功，证明 token 有效；operator 调 `lsp_list_tenants` 成功并包含 A/B。
Observable: A 的拒绝错误、A 的正向 allowlist 调用、operator 列表结果。
Basis: [admin 读要求 read("lsp")](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)；[Biscuit 的 lsp_list_tenants 规则](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/biscuit.rs)；[tenant 方法分类](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs)。
Source: explicit
Testing: required

### SPEC-04：tenant token 不能调用 operator 的 eviction RPC

Condition: A/B 均为 Active runtime；A 能正常调用 allowlist 内的租户方法；operator token 可用。
Expected: A 用 tenant token 驱逐 B、再驱逐自己均被拒绝；调用前后 A/B 的 `runtime_status` 仍为 Active，`channels[]` 的 channel_id 集合不变，`lsp_get_status.active_tenants` 与 `registered_tenants` 不变；operator 的 `lsp_list_tenants` 仍成功。
Observable: 两次 evict 的错误、`lsp_get_status` 的两个计数、`lsp_list_tenants` 的 runtime_status/channels、operator 列表。
Basis: [eviction 只停止 runtime、保留注册状态；active 与 registered 分开](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)；[lsp_evict_tenant 需要 write("lsp")](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/biscuit.rs)；[ListTenants/status 字段来自 registry 与 ready 集合](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/lsp/service.rs)。
Source: explicit
Testing: required

### SPEC-05：operator-only 分类不能被 tenant token 绕过

Condition: A 持有有效 tenant token，且拥有 `read("invoices")`；A 已有一张可解析的 invoice address。
Expected: A 调 `parse_invoice` 被 middleware 拒绝；A 调 `get_invoice` 读取自己的发票仍成功，证明 token 和能力本身有效。若 operator-only 分类被误改为 tenant-scoped，`parse_invoice` 会返回解析结果而不是拒绝。
Observable: `parse_invoice` 的错误、A 的 `get_invoice` 正结果。
Basis: [parse_invoice 为 operator-only，而 tenant 有 read("invoices")](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/biscuit.rs)；[TENANT_SCOPED/OPERATOR_ONLY 分类](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs)。
Source: explicit
Testing: required


### SPEC-06：已有真实付款时，tenant 默认查询只读自身 payment namespace

Condition: 同一 T 上注册 A/B，两者均有真实 external-signer ChannelReady 通道、有效 tenant token 和已成功的出站付款；A 只发起 `H_A`，B 只发起不同的 `H_B`，资金及历史已稳定。
Expected: A/B 不带 `tenant_id` 查询自己的 hash 均返回各自成功记录；交叉查询另一方 hash 均返回 payment session 不存在，不返回另一方付款记录，也不回退到 public T 或其他租户。查询后原付款历史、资金、原通道和零锁定状态不变。
Observable: 同一 T RPC 网关上 A/B token 的原始 JSON-RPC 请求与响应、付款 hash/preimage/status/fee、查询前后历史及六端余额/锁定快照。
Basis: [763 namespace 契约](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/docs/notes/hosted-lsp.md#L265-L268)、[默认 tenant 解析](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc/tenant.rs#L310-L338)、[actor/store 随 tenant 绑定](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc_scope.rs#L149-L187)、[按 actor store 查付款，缺记录报错](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/fiber/network.rs#L5620-L5638)。
Source: explicit
Testing: required

### SPEC-07：tenant 显式目标允许自身、拒绝其他租户

Condition: SPEC-06 的 A/B 真实付款已存在；调用使用各自有效 tenant token、正确 hash 和格式有效的 tenant ID。
Expected: 显式指定自己的 tenant ID 可读自己的成功付款；显式指定另一方 tenant ID 查询其真实付款时，在租户目标授权处拒绝，不能当成默认查询后返回 not found，更不能返回记录。合法读取在拒绝后仍成功，原历史和资金不变。
Observable: A/B 对自身目标的成功响应、对另一方目标的租户授权拒绝及拒绝后合法读取、资金/锁定快照。
Basis: [参数的显式自身/其他目标契约](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-json-types/src/payment.rs#L31-L38)、[跨租户在解析 context 前拒绝](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc/tenant.rs#L324-L333)、[native handler 先解析 tenant 再调用对应 payment backend](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc/payment.rs#L169-L181)。
Source: explicit
Testing: required

### SPEC-08：有合法权限的 operator 必须按显式 tenant 目标读取真实付款

Condition: A/B 付款及稳定快照成立；operator token 具有 `read("payments")` 和 `read("lsp")`，不是带 tenant 身份的 token。
Expected: operator 指定 A 查 `H_A`、指定 B 查 `H_B`，分别返回与该所有者一致的成功记录；同一个 `H_A` 改为指定 B，以及 `H_B` 改为指定 A，均返回 payment session 不存在。该同 hash、不同目标对照证明目标参数被采用，不能仅凭一次 operator 查询成功判通过。原历史与资金不变。
Observable: operator 四组显式目标响应、与所有者快照的字段比对、查询后历史/资金快照。
Basis: [operator 显式 tenant 的权限与命名空间契约](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/docs/notes/hosted-lsp.md#L265-L268)、[显式 operator 授权与 context 解析](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc/tenant.rs#L335-L379)、[查询 handler 使用已选 backend](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc/payment.rs#L169-L181)。
Source: explicit
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- Hosted 租户边界
  - 默认查询命名空间
    - B 查 A hash 返回不存在，B/A 查自己成功：LSP-TENANT-QUERY-01 [primary] -> SPEC-01
  - 显式 tenant_id
    - B 显式查 A invoice 被拒，operator 显式查 A 成功：LSP-TENANT-QUERY-02 [primary] -> SPEC-02
    - tenant 显式自身读取成功、显式另一租户授权拒绝：LSP-TENANT-QUERY-05 [primary] -> SPEC-07
  - 运维读权限
    - tenant token 调 lsp_list_tenants 被拒，operator 正向列表：LSP-ADMIN-AUTH-01 [primary] -> SPEC-03
  - 运维写权限
    - tenant token 驱逐 B/自己均被拒，Active/计数不变：LSP-ADMIN-AUTH-02 [primary] -> SPEC-04
  - operator-only 分类
    - tenant token 调 parse_invoice 被拒，get_invoice 仍成功：LSP-ADMIN-AUTH-03 [primary] -> SPEC-05
  - 真实付款默认查询隔离（固定763）
    - A/B 各有真实付款，自己可读、交叉查无记录：LSP-TENANT-QUERY-04 [primary] -> SPEC-06
  - operator 显式付款查询目标（固定763）
    - 所有者目标成功，同一 hash 换成另一目标无记录：LSP-TENANT-QUERY-06 [primary] -> SPEC-08
  - 有 pending 签名/delivery 时的 eviction 门禁 [unanalysed] — 需要先构造 pending 工作，作为后续独立分支。
<!-- TEST-TREE-END -->

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-TENANT-QUERY-01` | - [x] A/B 各有真实 Open 发票；B 不带 tenant_id 查 A 的 payment hash，再查自己的发票，A 查自己的发票 | B 查 A 返回发票不存在；B、A 查自己均成功；A 发票内容和状态不变 | 默认查询回退到 public/A 命名空间，读取其他租户发票 | P0 |
| `LSP-TENANT-QUERY-02` | - [x] B 带 `tenant_id=A` 查 A 的发票；operator 带 `tenant_id=A` 查同一发票；A 再查自己 | B 被拒绝且不返回 A 内容；operator 正向读到 A；A 发票状态不变 | tenant_id 被静默忽略/回退自身，导致显式越权或无法区分正确拒绝 | P0 |
| `LSP-ADMIN-AUTH-01` | - [x] A 用 tenant token 调 `lsp_list_tenants`，随后调一个允许的租户方法；operator 调 `lsp_list_tenants` | A 的列表调用被拒绝，正向租户方法成功；operator 列表成功且包含 A/B | tenant token 获得 operator 列表权限，或 token 失效导致假拒绝 | P0 |
| `LSP-ADMIN-AUTH-02` | - [x] A 用 tenant token 分别调用 `lsp_evict_tenant` 驱逐 B 和 A 自己；两次调用后只由 operator 读取状态，不再调用任何 A/B tenant client | 两次 evict 均被拒绝；A/B 仍为 Active，channels 的 channel_id 集合不变，active_tenants/registered_tenants 不变；operator 列表仍成功 | 越权 evict 成功，或后置 tenant 读取把 runtime 重新拉起而漏掉越权 | P0 |
| `LSP-ADMIN-AUTH-03` | - [x] A 用 tenant token 调 `parse_invoice` 解析自己的 invoice address，再调 `get_invoice` | `parse_invoice` 被拒绝；`get_invoice` 成功；不会因 tenant 有 read("invoices") 而放行 operator-only 方法 | operator-only 分类回归，tenant token 误用 parse_invoice | P1 |
| `LSP-TENANT-QUERY-04` | - [x] A/B 各完成一笔不同 hash 的真实出站付款；各用自身 tenant token、不带 tenant_id 查询自己的及另一方的 hash | 自己的付款为原 Success 记录，交叉查询返回 payment session 不存在且不泄露记录；查询后原历史、资金及零锁定状态不变 | 默认查询错误落到 public/其他租户，或 token/数据无效造成假隔离 | P0 |
| `LSP-TENANT-QUERY-05` | - [x] A/B 各有真实成功付款；各自显式指定自身 ID 查自己，再指定另一方 ID 查对方，最后重读自身 | 显式自身查询成功；跨租户明确因目标授权被拒，不以 not found 代替；合法读取继续成功，原历史、资金及零锁定状态不变 | 忽略 tenant_id、跨租户读取，或所有请求都失败掩盖授权错误 | P0 |
| `LSP-TENANT-QUERY-06` | - [x] A/B 各有真实成功付款；具备 payments/lsp 读取权限的 operator 分别指定所有者查询，再将同一 hash 的目标改为另一租户 | 所有者目标返回与 A/B 各自快照一致的记录，另一目标返回 payment session 不存在；原历史、资金及零锁定状态不变 | operator 目标被忽略或回退 public，只有成功响应却读错 namespace | P1 |
<!-- TEST-CASES-END -->

## 56c 历史用例验证设计（QUERY-01/02、ADMIN-AUTH-01～03）

- 独立预期：默认查询的不存在、显式目标拒绝、operator 目标成功、runtime Active/计数不变，分别来自 tenant 查询解析、Biscuit capability 和 registry/ready 语义；不使用被测调用自身的返回值自证。
- 实际入口与观察：A/B 的真实 tenant HTTP 客户端和 operator 客户端；先做每个 Case 的正向控制，再改变目标参数观察拒绝。QUERY-01/02 可在拒绝后重读 A 的 `get_invoice`；ADMIN-01/03 可重读 A 的 `get_invoice`；ADMIN-02 在两次 evict 后只读取 operator 的 `lsp_get_status`/`lsp_list_tenants`，绝不再调用 A/B tenant client，避免被驱逐 runtime 被重新拉起。
- 环境与成本：使用候选 bundle `download/fiber/pr-1623-56c761c-cancel`，`LSP_TEST_REVISION`/`LSP_RETEST_REVISION` 固定 56c761c；复用 `_CancellationBase` 的真实 A/B 注册、external funding、SDK 签名和 `ChannelReady` 通道，不等待付款。每个方法独立建立 A/B 真实通道并创建自己的发票，不依赖执行顺序；第一条实测 102.78 秒，五个 Case 的预算按真实开通道成本估算，不能用轻量 unsigned fixture 代替黑盒用户流程。
- 证明边界：真实 FNN、真实 tenant Biscuit、真实 Store 命名空间和 operator token；不覆盖 own-namespace 的 A payment 读取、Received/结算隔离、eviction 门禁或跨租户并发。这些保留在树中未分析分支，后续独立设计。

## 56c 历史 B review 与处理

第一轮 B review 结论为 **G1 not ready**，提出的问题及处理：

| Finding | 处理 |
| --- | --- |
| B-F1：显式 tenant_id 与默认查询不可判别 | 拆为 QUERY-01/02；显式目标增加 operator 正向对照 |
| B-F2：不能只看“仍在列表”；evict 目标未定 | ADMIN-02 改为检查 runtime_status、channel_id 集合、active/registered 计数，并明确驱逐 B 与 A 自己 |
| B-F3：负向用例缺正向控制，admin 拒绝有两层 | 每个负向 Case 先做 token 有效的正向控制；ADMIN-03 用 `parse_invoice` 专门判别 operator-only 分类 |
| B-F4：843 cancellation 类不可直接复用，成本低估 | 使用候选 bundle + `LSP_RETEST_REVISION` 和真实 A/B funded channels；第一条实测 102.78 秒，按真实黑盒成本排期 |
| B-F5：显式目标检查无需 payment，未分析分支过宽 | 删除不可判别的 QUERY-03；显式 payment 和 own-namespace payment 都标为 unanalysed |

第二轮 bounded revision 指出的 R1～R3：

| Finding | 处理 |
| --- | --- |
| R1：QUERY-03 仍不可判别 | 删除 QUERY-03 用例；显式 payment 分支标为 unanalysed，待真实 A payment 再设计 |
| R2：ADMIN-02 后置 tenant 读取会重新拉起被驱逐 runtime | 规定 evict 后只做 operator 状态读取，不再调用 A/B tenant client；已验证顺序写入本文件 |
| R3：共享类级 A/B 缺机制、成本低估 | 改为每方法独立真实 A/B 通道；不假设类级共享，成本按实测 102.78 秒/条估算 |


## 763 本批的共同准备、判断依据与边界

### 接口、身份和正常付款前提

- 只调用 native HTTP JSON-RPC `get_payment([{payment_hash, tenant_id?}])`。A/B/operator 都访问同一公共 T 的网关，分别使用真实 tenant Biscuit 或 operator token；不能改用 P 的 RPC、SDK 本地 records、`lsp_get_payment_delivery` 或 operator 冒充 tenant。`payment_hash` 为32字节 hex，`tenant_id` 使用真实注册返回的 ID。
- 每行采用独立的新 Fiber/SDK 数据和真实 A–T、B–T 私有 external-signer 通道，以及 T–P 公共通道。共享准备逻辑可复用，但不能依赖另一条用例先执行、直接调用另一个测试方法或以未注资通道代替。P 是普通收款节点。
- A、B 依次向 P 支付两张不同发票；`H_A != H_B`，两个 preimage 由 P 独立生成并持有，每张发票只创建一次、只发送一次。沿用已确认 PAYMENT-05 的正常 CKB 输入：每笔 `a=1,000,000` Shannon、600s普通发票、禁止MPP、经 T trampoline、`max_fee_amount=10,000`；各 SDK 的出站 exact 授权额为1,005,000，先观察自身 RPC preimage并核对，再做本地 fulfillment。A 只发起 H_A，B 只发起 H_B；不借用重复 hash、故障付款或数据库注入来制造可区分性。
- 进入查询操作前，两笔必须都 Success、P 的对应发票都 Paid；单笔资金及累计资金正确、原通道存续、无活动目标 TLC/锁定/待签，并完成至少5s的稳定观察。这是准备资格，不把查别人的请求先跑一遍再当作准备成功条件。准备失败则报告本行未取得有效隔离结果，不能把后续 not found 或拒绝算通过。
- 独立资金依据：实测两笔首跳 TLC 各为 u_i、收款额各为 a，f_i=u_i-a，并与各自 RPC fee 交叉核验；本输入期望 u_i=1,005,000、f_i=5,000。相对两笔之前的基线，A/T-A 为 `−u_A/+u_A`，B/T-B 为 `−u_B/+u_B`，共享 P/T-P 为 `+2a/−2a`，T 总净收入为 `f_A+f_B`；remote 增量相反且同通道两侧镜像。第二笔前后的增量也分别核验，不能用累计净额掩盖第一笔异常。复用已确认 PAYMENT-05 的完整样本时长/全程余额判据，按每笔开始时的新稳定基线计算；这些只是查询数据的真实资格，不新增付款行为 Case。

### 读取与拒绝的裁决

1. 保存所有者的稳定付款快照 Q_A/Q_B，再执行本行查询矩阵。每次正式查询都保存新返回的HTTP/JSON-RPC响应，不能用准备快照代替调用结果；每个成功响应必须核对输入对应的 hash、Success、预期 preimage、实测 fee，以及 created_at/last_updated_at、failed_error、custom_records 与对应所有者快照一致。整数 hex 先规范化；时间戳只用于绑定同一历史和检查只读稳定，不单独证明 namespace 正确。`get_payment` 不返回 amount，不编造金额字段；金额由准备的 TLC/余额证明。debug-only routers 仅作诊断，不成为 release 的必要字段。
2. QUERY-04 的交叉查询必须得到正常 JSON-RPC 的 payment session 不存在错误；HTTP认证失败、权限拒绝、超时、断连、解析错误、缺字段或空结果均不能算隔离通过。固定763的 `on_get_payment` 对当前 actor store 无 session 报 `Payment session not found`，核对这个错误类别/原因，不绑定包含具体 hash 的整句文本。
3. QUERY-05 对方记录确实存在，但请求必须在 tenant 目标授权处分支拒绝；固定源码原因是 `tenant token cannot query another tenant's state`。必须区分这一原因与 payment not found，不能让“忽略参数后查自身失败”冒充正确授权拒绝。自身显式查询和拒绝后合法查询均须成功。
4. QUERY-06 用同一个 H_A 分别指定 A/B，再用 H_B 分别指定 B/A；相同凭据、相同 hash、只改目标。A/B 的合法记录应分别与 Q_A/Q_B 一致，另一目标必须无记录。两个目标若总返回 public 记录或固定租户数据，会在成功/不存在对照中失败。T 作为 trampoline 可能也有同 hash 的 public payment session，因此**不能预设 operator 不带 tenant_id 查 H_A 必须不存在**；本批不把默认 public 查询当隔离 oracle。
5. 查询矩阵之后重新读取 Q_A/Q_B、两张发票及六端通道；原成功历史、fee/preimage、funding/outpoint、余额和零活动锁定/待签必须保持。继续至少5s、至少3组完整后续样本，相邻完整样本完成间隔≤2s；首末完整样本的 finished 差值用于时长。不能重发付款、重做授权或重建数据来修复查询导致的状态变化。

### 预算、证据与失败分层

- 保留中性 HostedTenantFixture 的既有绝对 business 420s / row 480s；两笔付款分别沿用已确认的30s preimage等待和45s终态上限，并受发票/授权/TLC安全期限及总截止约束。查询阶段（含后续5s观察）最多30s，每次RPC最多2s、无隐藏重试；一轮后续完整采样最多5s且相邻完成间隔≤2s。上述时长是测试预算与观察约束；阶段不得重置总截止，发送前余量不足或准备不成立就停止，不扩预算凑通过。
- 后续自动化阶段才核验实际 FNN/SDK/driver 同源 bundle、源码摘要、合约、端口及资源并运行；本次仅固定源码 SHA，不把已有 PAYMENT-05 单租户运行或构建目录名当成这组三个 Case 的执行证据。
- 保存请求角色/tenant绑定、原始请求/响应、每个 H 的唯一 invoice/send 审计、准备和查询前后历史/资金快照、阶段时间及实际版本/JUnit。传输或观察失败归无法判定；真实付款准备失败单列；合格前提下 namespace 错误、错误拒绝层或查询副作用才是本批断言失败。

### 已有覆盖与本批差异

- 原 QUERY-01/02 只调用 get_invoice：共享 query resolver 不能证明 get_payment handler 实际把 tenant 目标传给了正确 payment actor。原五条评审行和全部映射保持不动，不为发票或 admin 新建重复用例。
- PAYMENT-05 已覆盖 A 自己的正常 get_payment/preimage/资金；它没有第二租户和显式查询矩阵。本批只复用其正常付款资格，不重新登记一条“正常出站成功”。PAYMENT-03 的 A/B 隔离是入站付款并行，付款查询来自 P，不证明本批的租户出站 payment namespace。
- 固定源码 `rpc/tenant.rs` 的 query-context 单元测试覆盖自身/跨租户、operator附加能力、非法目标及服务不可用；`signer_isolation.rs` 的 list_payments 只检查空列表，new_invoice 测试检查 tenant backend 路由。这些已有原生测试不等于有真实成功 payment 的三角色查询证据；本轮未执行这些 Rust 测试，也不重复其通用能力/非法参数矩阵。
- 本批不增加 operator 缺 read("lsp")、未认证/feature-off/WASM、list_payments 分页、未注册/evicted租户、进行中或失败付款查询、写操作及数据故障场景。这里只确认所选的“已成功真实付款 + 有效身份”的 get_payment 隔离范围，不声称整个 RPC 权限矩阵已由 Python 覆盖。

## 763 本批自审与待确认

按用户要求自审，没有另派模型或宣称独立 B 复核。核对点：旧 QUERY-03 不复用；原五行不变；新用例各有稳定ID和Spec/测试树主映射；真实资金前提、有效 token 正向控制及两种拒绝层明确；operator 同 hash/不同目标对照能识别忽略参数；未把 public 同 hash session 当作“不应存在”；错误响应、历史/余额只读性和采样时长均有明确裁决。

本批 QUERY-04～06 的设计已获用户确认。首例阶段只实现 QUERY-04，经修复和自审交接；随后用户授权继续完成 QUERY-05/06 并合并到一个独立 PR。三个 Case 均沿用固定763和已确认判据；未修改 SDK driver 或产品源码。结构检查不等于业务执行或独立覆盖审计。


## QUERY-04 首例实现（2026-11-09，历史阶段）

- 首例阶段唯一新业务方法为 `test_tenant_payment_queries.py::TestTenantPaymentQueries::test_default_payment_namespace_is_isolated`，当时 QUERY-04 对应一处 TEST-MAP、QUERY-05/06 尚未实现；后续扩展见文末。
- 两笔正常出站准备共用 `_hosted_outbound.py::HostedOutboundFixture`：从原 PAYMENT-05 提取原有 trace/前像/资金/费用/稳定裁决，保留 PAYMENT-05 原 nodeid 与版本门禁。该共用类没有 test 方法，QUERY-04 不继承业务测试类；A 角色的四端资金视图表示当前付款人，物理 A/B 由 preparation/passed 事件的 payer_label 及各 hash/channel 绑定。每笔审计和采样历史分别开始，第二笔前资金基线包含第一笔的实际结算。
- 新方法中直接展开 A/B 自身成功、交叉 not-found、再读自身的矩阵；每次使用新 HTTP 请求，记录 caller、请求ID、hash、原始响应和时间，不传 tenant_id。权限拒绝、传输/字段异常均不能作为 not-found 通过。
- 准备阶段同时核对未付款租户保持原余额，以及每笔和累计六端资金。查询后持续核对原成功历史、发票、六端资金/锁定/通道和待签；稳定期由首末完整样本 finished 差值计算。
- 固定763门禁和8GiB磁盘资格在新用例启动节点前检查。提取未改变原 SDK/driver/合约输入；既有二进制须在当前工作树内通过实际摘要校验后复用。

首例交接时，原三条已确认用例行除 QUERY-04 映射复选框外未变化，当时等待用户确认；用户后续授权的 QUERY-05/06 实现见文末。

### 首次实现验证（历史记录；本轮修复验证见下）

- 固定763、复用已核验同源 FNN/SDK/driver bundle，未使用 retest override、未重建或修改产品。唯一 QUERY-04 正式执行 **1 passed，runner 123.654s，exit 0**；因提取共用准备影响原 PAYMENT-05，再单独执行一次该既有方法作对照，**1 passed，runner 97.141s，exit 0**。两轮均有新 JUnit 和执行前后输入未变化的原生回执。
- 离线 **31 passed、exit 0**：13项新增 QUERY-04 编排/请求/视图检查，另18项原 PAYMENT-05资金/trace/采样及版本门禁。新检查直接驱动真实 QUERY-04 主方法，覆盖正常对照、跨租户记录泄露、权限拒绝冒充不存在、错误响应携带前像、错误正向记录、查询后资金或历史变化、本地处理延迟凑稳定期、缺字段、准备时空闲租户余额变化；另检查真实请求构造拒绝HTTP认证错误/错响应ID及B视图正确投影。离线模拟不计真实付款通过。
- 原始 QUERY-04 观察中，两张发票和两次发送分别绑定 H_A/H_B。A/T-A、B/T-B 各为 `−1,005,000/+1,005,000`，共享P/T-P为 `+2,000,000/−2,000,000` Shannon；每笔fee=5,000，T合计净收10,000。查询后6个完整稳定样本跨 **5.297894s**，最大间隔 **1.066904s**；全部样本的历史、资金、镜像、零锁定、Paid和无待签一致。
- 20次正式查询都有新原始HTTP请求/响应，并与A/B各自gate中实际转发的payload、reply及真实tenant token的Authorization摘要匹配；两个tenant凭据不同。两次交叉请求均HTTP200、JSON-RPC `-32000`，原因是 `Payment session not found`，没有用权限/传输失败替代；所有自身读取均为对应成功记录。四条目标TLC原始trace在归档日志的记录偏移处逐字匹配，channel/金额与对应物理A/B通道一致。
- 提取自审对照确认资金、trace解析、活动TLC过滤、P余额历史等纯函数AST保持原样；trace采集/读取方法保持原样；采样器只改为选当前付款人的四角色视图。必要变化是显式选择A/B、每笔独立审计/采样起点，以及将成功判定交回外围业务方法。未降低原费用、资金、前像或稳定断言；新模块没有可被继承收集的业务测试，两个相关业务模块完整收集仍只有原PAYMENT-05与新QUERY-04两个方法。
- 原始回执、JUnit、HTTP/SDK/trace与节点资料、逐文件证据摘要、复算脚本及自审记录保存在本机 `local-evidence/query04-automation-20261109/`。此前所有批次证据保留，不提交本地产物。自有进程、两类任务运行目录为空，六个套件端口释放。
- 初始4.8GiB空闲未达到8GiB资格，未启动节点；经用户明确授权，仅删除Git报告为垃圾且无占用的四个10月30～31日临时文件，实际释放约9.35GiB，Git引用不变。随后只复制一份已验证bundle到当前工作树，执行收尾空闲约13.70GiB。跨工作树bundle符号链接被启动前门禁拒绝的收集记录也独立保留，没有放宽产物边界。

以上首例阶段按用户要求自审，不称独立实现复核；当时结论限于默认get_payment隔离，QUERY-05/06仅有设计。文末另列后续三条用例的完整验证。


### QUERY-04 两项复核问题修复与重新验证（2026-11-09）

首次实现的正常路径执行记录仍保留；该批31项离线检查遗漏了“错误响应只泄露部分付款字段”和“已知自有付款返回合法业务错误”的反例，不能据此认定这两个判据已经充分验证。本轮只修正QUERY-04的裁决及其离线回归，八条用例行、业务预期和映射均未变。

- 部分信息泄露：not-found错误中出现任何付款结果私有字段（例如单独的status、fee、created_at，或嵌套/JSON序列化的部分记录）均不能通过，不再要求泄露完整记录才失败；已知前像的值也按大小写不敏感检查。请求中已有payment_hash的正常回显允许通过，不将其误判为新增付款信息。
- 自有付款错误归因：查询前快照、矩阵中的自身读取、交叉查询后重读及稳定期复查统一使用`_read_owned_payment`。完整合法的JSON-RPC业务错误明确归为`assertion_failure`，保存caller、payment_hash及原始response；不再因读取缺失result抛KeyError而被外层归为`observation_limit`。错误schema不完整、字段不足或传输失败仍归观察不足，不能作为隔离成功。
- 新增12项工程回归：6种部分泄露、4个自有付款错误位置，另有请求hash回显和错误schema不足两个对照；全部驱动实际QUERY-04主方法。相同回归先在旧判据上得到**10 failed / 2 passed、exit 1**，修复后与原QUERY-04及PAYMENT-05相关检查一起得到**43 passed、exit 0**。原复核脚本原样重跑为**3 passed、exit 0**；这些都是自审离线证据，不称独立复核或真实付款执行。
- 固定`76307312e8de518c9a32074e6d16867c04de4f86`、核验同源bundle后，仅重新执行同一条真实QUERY-04：**1 passed，runner 118.261s，exit 0**，无重试；执行前后声明输入摘要一致。20次原始查询与各自gate实际转发及真实tenant凭据摘要一致；两次交叉错误均为HTTP200 / JSON-RPC -32000 / Payment session not found，错误只含code和message；自身读取仍对应各自原成功付款。
- 本次真实证据重新复算：A/T-A、B/T-B各`−1,005,000/+1,005,000`，P/T-P累计`+2,000,000/−2,000,000` Shannon；每笔费用5,000，T净收10,000。查询后6个完整稳定样本跨**5.250204s**，最大间隔**1.056945s**；历史、Paid发票、六端资金/通道、零锁定及无待签一致。四条目标TLC与归档节点日志对应字节偏移匹配。
- 共用付款helper、PAYMENT-05入口及其离线判据文件与首次验证摘要完全一致，本轮未改动；43项离线检查保留其相关回归。首次PAYMENT-05的真实1 passed / 97.141s是历史同源验证，本轮未再次执行该业务方法。
- 修复前源码、旧判据失败回执、修复后源码、43项及原反例3项的JUnit/日志/运行资料、真实节点/SDK/HTTP/trace原始资料、复算脚本、摘要和交接保存在本机`local-evidence/query04-fix-20261109/`，与前两批归档并存。任务自身运行目录及进程为空，六个端口释放，未进行额外手动删除。

该修复阶段自审结论：两个复核问题已由旧实现上的失败复现、修复后的聚焦回归和固定763的真实重跑闭环验证，未发现阻断QUERY-04首例实现确认的问题。当时尚未实现QUERY-05/06、未提交或推送；后续实现与PR验证另列于下。


### QUERY-04～06 完整实现与验证（2026-11-09，PR初始提交历史记录）

用户在QUERY-04首例修复与自审后，明确要求一起实现已确认的QUERY-05/06再提交PR。本批不改变三行用例预期，只同步QUERY-05/06的TEST-MAP复选框。三个独立方法均在`test_tenant_payment_queries.py::TestTenantPaymentQueries`：

| 执行场景 | 原生方法 | 本次JUnit耗时 | 原始查询 / 显式目标查询 | 完整稳定样本跨度 / 最大间隔 |
| --- | --- | --- | --- | --- |
| 默认命名空间 | `test_default_payment_namespace_is_isolated` | 116.130s | 20 / 0 | 5.488479s / 1.106660s |
| tenant显式目标 | `test_explicit_payment_target_rejects_other_tenant` | 106.275s | 20 / 6 | 5.212999s / 1.045274s |
| operator显式目标 | `test_operator_payment_query_selects_explicit_tenant` | 104.480s | 20 / 6 | 5.511998s / 1.113711s |

- 每个方法独立建立A/B真实通道和两笔真实付款，三行合计六个不同hash；不调用其他测试方法，也不依赖执行顺序。三个方法复用正常付款准备、完整六端快照及有界稳定采样；自身/交叉/operator矩阵及核心断言在各方法直接展开。QUERY-04的准备和稳定段抽为共用方法，原有错误归因、私有字段检查、预算和完整样本时长判据保持。
- QUERY-05的六次显式请求为A自身成功→A指定B查H_B被拒→A自身重读，及B的对称顺序。两次拒绝均为HTTP200 / JSON-RPC -32000，原因为`tenant token cannot query another tenant's state`，不接受not-found或泛化权限错误；拒绝后同token显式自身读取仍为原记录。
- QUERY-06使用已核验bundle中的真实operator token，其凭据与两个tenant均不同。对H_A和H_B各执行所有者目标成功→同hash改另一目标not-found→所有者重读成功。六次显式请求保持同operator；不增加operator默认public查询，也不预设public是否有同hash。每次原始请求额外记录实际RPC地址和Authorization摘要，不记录明文token。
- 聚焦离线**69 passed，exit 0**：保留原43项并增加26项，覆盖两行真实主方法的正常矩阵、忽略/固定目标、错误拒绝层、全拒绝、错误正记录、部分信息泄露、合法业务错误、重读失败、资金/历史副作用、处理耗时凑稳定期以及真实请求构造的身份/目标/原始响应。离线模拟不记为真实付款通过。
- 固定产品`76307312e8de518c9a32074e6d16867c04de4f86`，同源FNN/SDK/driver bundle经实际摘要核验。只执行这三个原生业务方法，单轮**3 passed / 0 failed / 0 errors / 0 skipped，runner 327.362s，exit 0**；每条JUnit时间见表，执行前后声明输入一致，无重试或产品源码修改。
- 原始HTTP复算：每行20次正式请求，tenant请求与各自真实gate转发payload/reply及归档SDK凭据摘要匹配，operator请求与bundle凭据及归档T的真实RPC地址匹配。每行6个完整稳定样本、发票和发送各2次、4条目标TLC原始日志均匹配归档字节偏移。两条显式用例的六请求序列逐项核对caller/hash/tenant_id，不只统计成功/失败次数。
- 三行逐一核对资金：A/T-A、B/T-B各`−1,005,000/+1,005,000`，P/T-P合计`+2,000,000/−2,000,000` Shannon；每笔费用5,000，T净收10,000。原Success历史、Paid发票、通道/outpoint、镜像、零锁定及无待签在全部后续样本保持一致。
- 本轮没有改共用付款helper、原PAYMENT-05入口或其离线判据，相关69项中的18项回归已通过；该入口此前同源真实**1 passed / 97.141s**仍作为历史对照，本轮未再次执行PAYMENT-05。自审不称独立实现复核。
- 本批原生回执、JUnit、离线运行资料、全部HTTP/SDK/节点/trace原始证据和复算脚本保存在本机`local-evidence/payment-query-040506-20261109/`；此前两批QUERY-04归档继续保留。本地产物、凭据、节点数据和下载bundle不进入PR。

静态验证：评审设计检查8行、五个Python文件Black及diff空白检查通过；相关两个模块仅收集到原PAYMENT-05和QUERY-04/05/06四个业务方法。项目映射检查为147条评审、141条映射；退出码1来自既有`PMP-01～05`和`SETTLE-01`六个孤儿映射，无新增孤儿或重复ID。运行记录表使用场景名称，避免简写ID被检查器误识别为新的评审行。

独立PR沿用已合并PR #16的目标分支`codex/lsp-core-regressions`，基线为`fa4a3b7c7853b926f79108e3a6b86c54bc4d397f`，范围只含本组评审、三个查询用例、共用付款准备提取及相关离线回归。没有扩展其他业务用例或修改产品实现；不自动合并。


### PR #17：P2 响应外壳归因修复与重新验证（2026-11-09）

再次复核发现，HTTP200且jsonrpc/id匹配时，同时包含result和error、或两者都缺失的响应，会因直接assert保留为assertion_failure，与本文“观察不足”的分层约定不一致。本轮只将互斥外壳检查改为显式observation_limit，保存caller、request、response及HTTP状态；校验可通过的响应集合未变。合法业务错误仍交给业务判据，HTTP故障仍优先判观察不足。正式八行用例、三条映射、资金/历史及授权判据均未变。

- 新增同一实际QUERY-04主方法/HTTP解析路径的四项工程回归：result/error同时存在、同时缺失、HTTP200合法业务错误、HTTP401对照。注入前两笔付款准备和查询矩阵均成立；均核对原始响应、归因及不产生passed事件。相同回归先在旧实现取得**2 failed / 2 passed，exit 1**，修复后随全组取得**73 passed / 0 failed / 0 errors，exit 0**。原复核探针原样重跑**3 passed，exit 0**，不把离线结果记成真实付款通过。
- 固定`76307312e8de518c9a32074e6d16867c04de4f86`并核验同源bundle后，单轮重新执行QUERY-04～06：**3 passed / 0 failed / 0 errors / 0 skipped，runner 324.340s，exit 0**，无重试，声明输入前后摘要一致。

| 执行场景 | 本轮JUnit耗时 | 原始查询 / 显式查询 | 完整稳定跨度 / 最大间隔 |
| --- | --- | --- | --- |
| 默认命名空间 | 114.230s | 20 / 0 | 5.232656s / 1.049449s |
| tenant显式目标 | 106.244s | 20 / 6 | 5.241591s / 1.049322s |
| operator显式目标 | 103.547s | 20 / 6 | 5.308617s / 1.066260s |

- 原始证据逐条复算：真实凭据、目标参数和拒绝原因吻合，QUERY-05仍为目标授权拒绝、QUERY-06仍为同hash切换目标成功/不存在；每行6个完整稳定样本、发票/发送各2次及4条目标TLC原始日志均核对。A/T-A及B/T-B各−1,005,000/+1,005,000，P/T-P累计+2,000,000/−2,000,000 Shannon；每笔费用5,000，T净收10,000，原历史、Paid发票、六端镜像、通道/outpoint、零锁定和无待签保持一致。
- 本轮未修改共用付款helper、PAYMENT-05入口或其离线判据；相关回归包含在73项中，历史真实PAYMENT-05证据仍对应同源文件。本轮未重跑该业务方法，也未扩展其他业务用例。自审不称独立B复核。
- 修复前源码、正式红灯/绿灯回执和运行资料、原复核探针、本轮真实节点/HTTP/SDK/trace、复算脚本及交接保存在`local-evidence/pr17-envelope-fix-20261109/`。此前完整实现的261个证据文件和复核阶段的71个文件摘要均校验一致，未覆盖原始归档。仅更新PR #17，不自动合并。

### QUERY-04～06 可选共享环境试点（2026-11-10）

用例行、资金/费用、历史、隔离和错误归因判据保持不变。默认仍走独立环境路径；`LSP_QUERY_ENV_MODE=shared` 仅为这三个方法复用类内环境，每个方法仍新建两笔真实付款，另加跨方法资金、历史及环境身份检查。原生独立/共享对照、失败证据及使用边界见[共享环境试点记录](../../docs/analysis/lsp-query-shared-environment-pilot.md)。本轮不扩展其他业务场景。

### QUERY-01/02、ADMIN-AUTH-01/03 可选共享环境（2026-11-10）

原用例行与 TEST-MAP 保持，ADMIN-AUTH-01 补齐拒绝后的合法查询。`LSP_INVOICE_QUERY_ENV_MODE=shared` 只允许这四条，默认独立，ADMIN-AUTH-02 继续独立并保持 evict 后无 tenant 读取。默认独立的归档/证据初始化失败会失效并保留现场，不依赖 keep-runtime。

固定 763 的最终真实对照为独立 4/4（418.812 秒）、共享 4/4（148.824 秒），本机单轮耗时减少 64.5%；QUERY-04～06 共享影响回归另有 3/3，不计入提速比较。仓库离线 146 项通过，另有本地探针形成的 150/153 项验证记录；本地产物不随代码提交。入口、状态边界、耗时口径及证据范围见[发票查询与权限共享环境说明](../../docs/analysis/lsp-next-shared-environment-review.md)。

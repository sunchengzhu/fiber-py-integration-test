# Hosted 租户边界：查询与运维 RPC

范围：候选 `56c761c45c271c086b05c8d5ea3e033448f5fdf8` 上的一批黑盒租户边界：默认命名空间查询、显式 tenant_id 查询、tenant token 对 operator RPC 的越权，以及 operator-only 方法分类。A/B 均使用真实注册、真实 external funding 和真实 ChannelReady 通道；本批不额外制造付款。付款 own-namespace 读取和 eviction 门禁留作后续分支。

依据：[Hosted LSP 文档](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)（租户数据面、admin 权限与 eviction 语义）、[tenant RPC 查询解析](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs)、[invoice RPC](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/invoice.rs)、[Biscuit 权限规则](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/biscuit.rs)。A/B 是不同 Hosted 租户，P 是付款方，T 是 LSP；A/B 使用各自真实 tenant Biscuit，不能用 operator token 代替。

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

## 测试树

<!-- TEST-TREE-BEGIN -->
- Hosted 租户边界
  - 默认查询命名空间
    - B 查 A hash 返回不存在，B/A 查自己成功：LSP-TENANT-QUERY-01 [primary] -> SPEC-01
  - 显式 tenant_id
    - B 显式查 A invoice 被拒，operator 显式查 A 成功：LSP-TENANT-QUERY-02 [primary] -> SPEC-02
    - B 显式查 A 已存在 payment [unanalysed] — 需要 A 的真实 payment 才能区分“正确拒绝”和“忽略 tenant_id 后查自身 not found”。
  - 运维读权限
    - tenant token 调 lsp_list_tenants 被拒，operator 正向列表：LSP-ADMIN-AUTH-01 [primary] -> SPEC-03
  - 运维写权限
    - tenant token 驱逐 B/自己均被拒，Active/计数不变：LSP-ADMIN-AUTH-02 [primary] -> SPEC-04
  - operator-only 分类
    - tenant token 调 parse_invoice 被拒，get_invoice 仍成功：LSP-ADMIN-AUTH-03 [primary] -> SPEC-05
  - B 在自己命名空间查 A 已存在 payment [unanalysed] — 需要 A 的真实 payment；本批不引入付款 setup。
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
<!-- TEST-CASES-END -->

## 验证设计

- 独立预期：默认查询的不存在、显式目标拒绝、operator 目标成功、runtime Active/计数不变，分别来自 tenant 查询解析、Biscuit capability 和 registry/ready 语义；不使用被测调用自身的返回值自证。
- 实际入口与观察：A/B 的真实 tenant HTTP 客户端和 operator 客户端；先做每个 Case 的正向控制，再改变目标参数观察拒绝。QUERY-01/02 可在拒绝后重读 A 的 `get_invoice`；ADMIN-01/03 可重读 A 的 `get_invoice`；ADMIN-02 在两次 evict 后只读取 operator 的 `lsp_get_status`/`lsp_list_tenants`，绝不再调用 A/B tenant client，避免被驱逐 runtime 被重新拉起。
- 环境与成本：使用候选 bundle `download/fiber/pr-1623-56c761c-cancel`，`LSP_TEST_REVISION`/`LSP_RETEST_REVISION` 固定 56c761c；复用 `_CancellationBase` 的真实 A/B 注册、external funding、SDK 签名和 `ChannelReady` 通道，不等待付款。每个方法独立建立 A/B 真实通道并创建自己的发票，不依赖执行顺序；第一条实测 102.78 秒，五个 Case 的预算按真实开通道成本估算，不能用轻量 unsigned fixture 代替黑盒用户流程。
- 证明边界：真实 FNN、真实 tenant Biscuit、真实 Store 命名空间和 operator token；不覆盖 own-namespace 的 A payment 读取、Received/结算隔离、eviction 门禁或跨租户并发。这些保留在树中未分析分支，后续独立设计。

## B review 与处理

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

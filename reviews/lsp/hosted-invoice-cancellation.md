# Hosted 租户发票取消：Gate2 用例评审

范围：LusoCryptoLabs 在 [PR #1623 的三项实测反馈](https://github.com/nervosnetwork/fiber/pull/1623#issuecomment-6418454010)中报告的第三项，以及已确认 [Gate1 方向 9～11](field-feedback-scope.md#用例gate1-候选场景)。固定分析版本为 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`。2026-10-30 用户授权按顺序持续推进，无需再逐项等待 Gate1/Gate2；01/02已实施并建立TEST-MAP，固定843只执行01单次诊断。03的Received取消契约仍待产品明确，保留未映射、未运行。映射不代表通过。

这里的 A、B 是不同 Hosted 租户，P 是付款方，T 是 LSP；A/B 使用各自真实 tenant Biscuit，不能用 operator token 代替。`Open` 为尚未收到款，`Received` 为已收到但未结算的 hold invoice。金额 M 固定 1,000,000 Shannon，费用上限 10,000 Shannon；成功时用实际付款费 f 核账，不把上限当实收费用。

## Spec

### SPEC-01：租户能取消自己的 Open 发票

Condition: A 以有效 tenant token 创建未过期、未付款的 hold invoice；A 的测试客户端保留 preimage，FNN 仅收到 payment hash，SDK 只保存经 `authorize_invoice` 验证的付款授权。
Expected: A 的 `cancel_invoice` 请求可到达自己的发票后端并返回 `Cancelled`；该发票随后不能被付款或结算，新的独立发票仍可正常使用。
Observable: 真实 RPC 请求与返回、A `get_invoice`、P 付款终态、各通道余额与锁定额、原 Agent 安全预像释放调用审计和后续新付款。
Basis: [租户 allowlist 缺方法](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/tenant.rs#L22-L49)；[RPC 已有 tenant context 分派](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/invoice.rs#L249-L264)；[取消后的状态变更](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L4978-L5014)。
Source: inference
Testing: required

### SPEC-02：租户身份不能跨越发票归属

Condition: A/B 是各自注册、持有有效凭证的租户，各有独立 Open 发票。
Expected: B 可取消自己的发票，但用同一凭证不能取消 A 的发票；拒绝不会修改 A 的状态、资金或后续收款能力。
Observable: B 自己的正向取消、B 对 A hash 的拒绝、A 发票及付款/通道终态。
Basis: [租户身份从 token 权威事实提取](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/tenant.rs#L13-L19)；[按 tenant context 选后端](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/invoice.rs#L249-L264)。
Source: inference
Testing: not_tested — 843 的统一 allowlist 拒绝不能冒充跨租户隔离通过。

### SPEC-03：取消有待处理 TLC 的 hold invoice 后安全收尾

Condition: A 创建 payment-hash-only hold invoice，客户端保留 preimage，SDK 有本地付款授权但尚未调用 `authorize_fulfillment`/`settle_invoice`；P→T→A 的付款已使发票进入 `Received`，尚未向 FNN 提交 preimage。
Expected: 待确认：`Received` 且 FNN 无 preimage 时应允许 A 取消。若确认允许，取消返回 `Cancelled`，原付款安全失败、全部 TLC 锁解除、无下游有效支出；后台自然恢复及后续正常付款不能使旧发票复活。
Observable: 取消前后发票/RPC、P 付款、A/T/P 双段通道余额与锁定额、SDK 预像提交审计、后续独立付款和稳定采样。
Basis: [当前底层允许无 preimage 的 Received 取消并安排异步 TLC 处理](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L4978-L5014)，但 [RPC 文档仍写仅 Open](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/README.md#L878-L894)；需人工确定契约。
Source: inference
Testing: not_tested — 当前入口先被 allowlist 阻断，且 `Received` 契约待确认。

## 测试树

<!-- TEST-TREE-BEGIN -->
- Hosted 发票取消入口与资金收尾
  - A 自己的 Open hold invoice 取消后拒绝旧付款，新发票仍可用：LSP-INVOICE-CANCEL-01 [primary] -> SPEC-01
  - B 自己的取消可用，但不能取消 A 的发票：LSP-INVOICE-CANCEL-02 [primary] -> SPEC-02
  - Received 且无节点 preimage 时取消并自然清理待处理付款：LSP-INVOICE-CANCEL-03 [primary] -> SPEC-03
  - Paid、已 Cancelled、Expired、有已保存 preimage 的 Received 状态边界 [pending] — RPC 注释与实现不一致；先确认产品契约，不从 843 行为直接推为预期。
  - 取消期间 FNN/SDK 原数据重启 [pending] — 先用本批自然恢复证明终态，重启作为独立风险评审，不把未运行项算进 03。
<!-- TEST-TREE-END -->

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-INVOICE-CANCEL-01` | - [x] A 用真实 tenant token 创建未过期的 Open hold invoice，客户端保留 preimage、SDK 仅保存付款授权；A 调用 `cancel_invoice`，再由 P 尝试付款旧发票并完成一笔新发票付款 | A 的取消返回 `Cancelled` 且查询保持；旧付款终态时 P/T/A 余额回基线、费用与 TLC 锁定额为零，旧 preimage 无提交记录；新付款按实际费用 f 正常结算 | 租户入口被 allowlist 挡住，或取消只改状态却仍能收款 | P0 |
| `LSP-INVOICE-CANCEL-02` | - [x] A/B 各有真实身份和 Open 发票；B 先用自己的 tenant token 取消 B 发票，再用同一 token 取消 A 发票，随后 P 支付 A 原发票 | B 自己的取消成功，跨租户请求被拒且 A 发票/余额/锁定额不变；A 原付款成功一次、A 收 M、P 支出 M+实际 f、T 净收入 f，最终无 TLC 锁定 | 统一入口拒绝伪装成隔离，或跨租户取消污染 A | P0 |
| `LSP-INVOICE-CANCEL-03` | - [ ] A 的 payment-hash-only hold invoice 已在真实 P→T→A 付款中进入 `Received`，客户端保留 preimage、未向 FNN 提交；A 用 tenant token 取消并让后台自然恢复，之后发送新付款 | 待确认：无节点 preimage 的 `Received` 应允许取消；若确认，返回 `Cancelled`、原付款失败且无有效下游支出，原付款终态时各方余额回基线、费用和 TLC 锁定额为零，30 秒内不复活，新付款可正常结算 | 待处理付款继续支付已取消发票，或取消后通道被永久占用 | P0 |
<!-- TEST-CASES-END -->

## 触发、资金断言与时间预算

- 只用普通匹配 FNN、真实 SDK、现有 Python LSP 生命周期/签名授权/通道余额辅助；`payment_hash` 用 CKB Blake2b 生成，`new_invoice` 只传 hash、不传 preimage。测试客户端保留 preimage；SDK 的 `authorize_invoice` 只验证持有并保存付款授权，不能把 preimage 说成已存于 SDK。对旧/待取消 hash 不调用 `authorize_fulfillment`、`settle_invoice` 或 `create_preimage`，并保留调用审计。03 等 `get_invoice=Received` 与真实待处理 TLC 同时成立再取消；若状态点未取得，报测试准备失败，不拿 Open 分支顶替。无需接纳一致性的 Rust 薄包装，也不修改产品或宿主机时间。
- 对 01 的新发票、02 的 A 原发票和 03 的新发票，先确认真实目标 TLC 和 SDK recovery record，再复用固定843原 Agent 的 `FixtureAuthorization::ReleasePreimage { target: Invoice }`。该路径通过独立 `ChainVerifier` 调 SDK `authorize_preimage_release` 检查真实 funding 与可执行承诺，并在授权持久化后由原 Agent 立即以 tenant token 调 `settle_invoice`。不能把仅记录兑现意图的 `authorize_fulfillment` 或直接 RPC `settle_invoice` 当成安全释放门禁。已取消的旧 hash 绝不走这条正向路径。旧 hash 失败且余额回基线的检查点先完成，再开启独立新 hash 的正常付款，分别核账。
- 每行新建独立 P–T–A 环境；02 另建 B 的真实租户和通道。失败付款要求所有端点相对基线余额为零变化、payer fee=0、无 pending TLC/锁定额；成功付款要求 A `+M`、T–A `−M`、P `−(M+f)`、T–P `+(M+f)`，且 T 净收入 `f`、`0≤f≤10,000`。所有检查以真实 RPC 和链上活通道为依据，取消 RPC 返回本身不证明异步清理完成。
- 843 只安排 01 的**一次**入口诊断：若 tenant token 在 allowlist 被拒，保留产品失败证据即停，不运行 02/03，也不以 operator token 绕过。修复版本需先固定 SHA、审查 diff、构建匹配产物和验证 A 自己的入口可达，再执行 01→02→03，各行单次，任一产品/资格失败即停。
- 修复版预算：版本/构建与自检≤35 分钟；每行准备≤240 秒、业务及有界终态到行起点+420 秒、归档清理≤60 秒，单行硬上限8分钟；三行最多24分钟，收尾/映射复核≤10分钟，总硬上限70分钟。03 的30秒稳定期在业务预算内。843 单行诊断若授权则≤15分钟。超时、未达到 `Received` 或环境失败单列，不重跑挑竞态。

## 最小适配与验证边界

沿用 `_DelayedPaymentBase` 的真实拓扑、SDK本地 `invoice` 授权、`get_invoice/get_payment/list_channels/get_live_cell` 与资金守恒辅助；新增本组专用的 hash-only 发票准备和取消 RPC 调用。测试侧 `_sdk_driver.rs` 只需薄增两个控制入口：配置原 Agent 的独立 dev-chain/合约源，以及把正向付款交给原 `FixtureAuthorization::ReleasePreimage`；先自检链源和该安全路径，再运行正向对照，不复制节点启动或绕过原 SDK 校验。01/03 的后续新付款使用独立 hash，逐笔核账；02 的 A 原发票正向付款也需经原 Agent 安全释放。03 不依赖内部 delivery key，可通过唯一原 hash、真实通道、付款/发票终态与30秒稳定采样判定取消安全性。保存每次请求和响应、凭证身份、发票状态、安全释放与节点提交调用、付款与 TLC/余额序列及原始节点日志。现有非 Hosted `test_cases/fiber/devnet/cancel_invoice/` 用例可作接口参考，不能算 tenant token 权限覆盖。

2026-10-30 用户授权后已实现01/02；执行顺序仍为843一次01诊断，若租户入口被拒则停止，02不运行。03未实施；后续执行结果另记于LSP运行说明。01/02 需要产品开放正确的租户入口，03 另需确认 `Received` 无 preimage 的取消契约；不能把当前843的 allowlist 拒绝写成业务安全通过。


2026-10-30 执行结果：01在固定843的真实租户入口收到 `-32999 Unauthorized`，节点明确报告tenant token不能调用cancel_invoice，产品入口缺口已复现；独立构建和收集通过，01非超时失败即停。付款与资金后半步骤、02/03未运行，旧证据完整保留。详见[LSP运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-hosted租户发票取消真实入口拒绝2026-10-30)。01/02复选框仅表示代码已映射，不表示通过；03仍待产品契约明确。

2026-10-30 相关普通兼容回归：固定843同一新driver-only bundle顺序执行核心16、延迟付款3、浏览器11，共30方法/25独立ID，三阶段及整批均退出0，JUnit零失败/错误/跳过；60分钟预算内实际2828.229秒，收尾无本批残留进程。原始证据保存在分离测试工作树的 `report/lsp-invoice-cancel-regression-84333ee-20261030T005117/`，不随本PR提交。此结果只验证新增SDK控制入口未破坏这些普通LSP路径，不代表取消功能通过：01仍在真实tenant入口被`-32999 Unauthorized`阻断，后续旧付款资金与新付款未运行；02未运行，03待契约、未映射。

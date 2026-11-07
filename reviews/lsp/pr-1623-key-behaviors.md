# PR #1623 关键行为清单（56c761c）

范围：`nervosnetwork/fiber#1623` 的 hosted LSP 关键行为。基线 `84333ee`，当前候选 `56c761c`。本文是**行为覆盖清单**，不是 Case 表；Case ID 只用于指向现有证据，不在这里新增或改动用例预期。

勾选语义：

- `[x]`：当前候选版本有**通过**的真实执行证据，且断言覆盖该行为；
- `[ ]`：未完成、未覆盖、产品失败、契约未确认或仅有设计稿；状态在行内说明；
- “已覆盖-失败”不算完成，不能用产品失败换勾；
- 产品未实现的行为可以先有设计，但不能标通过。

进度：**37/44 个关键行为通过（约 84%）**。核心缺口中 D2、H6 已通过；D5 是正式 xfail，产品未通过；F3/F4/H4 仍产品阻塞；G4 受控 A/T 双分支已通过但自然竞态未判定。Rust 单元/集成测试与 Python 黑盒用例分开注明层级。

## A. 租户生命周期、查询与权限（6）

- [x] **A1 租户注册、身份与 token scope**
  A/B 真实注册、tenant token、身份绑定。证据：SIGN-01～03、SUBSCRIPTION-01～28、WATCHTOWER-02～05。
- [x] **A2 默认命名空间查询隔离**
  B 不带 `tenant_id` 查 A 的 invoice，不得到 A 数据。证据：`LSP-TENANT-QUERY-01`，真实 A/B 通道，99.28s。
- [x] **A3 显式 `tenant_id` 授权**
  B 不能显式指向 A；operator 可正向读取 A。证据：`LSP-TENANT-QUERY-02`，真实 A/B 通道，95.40s。
- [x] **A4 operator-only admin 权限**
  tenant token 不能调 `lsp_list_tenants` / `lsp_evict_tenant`；operator 正向可用。证据：`LSP-ADMIN-AUTH-01/02`，89.95s / 88.90s。
- [x] **A5 operator-only 方法分类**
  tenant token 不能调 `parse_invoice` 等 operator-only 方法。证据：`LSP-ADMIN-AUTH-03`，87.84s。
- [x] **A6 eviction 门禁与 runtime 状态**
  有 pending 签名、delivery 或 active TLC 时不能驱逐；驱逐后状态字段正确。证据（Rust 单元/集成）：`tenant_supervisor_rejects_eviction_while_runtime_is_busy`、`tenant_with_pending_delivery_cannot_be_evicted`、`pending_signature_survives_cold_queries_and_resumes_after_eviction`、`hosted_private_channel_registers_host_watch_and_survives_evict`。

## B. 外部签名、重试与恢复（7）

- [x] **B1 external signer 开通与 funding**
  `open_channel_with_external_funding`、真实 SDK 签名、通道就绪。证据：SIGN、RECOVERY-01。
- [x] **B2 跨租户签名查询/提交隔离**
  A 不能读/提交 B 的签名请求。证据：SIGN-02/03。
- [x] **B3 相同/冲突/旧签名重试**
  Applied/AlreadyApplied、冲突拒绝、旧请求不消耗。证据：RETRY-01～06。
- [x] **B4 SDK 重启恢复已保存签名**
  未提交 S1、原存储、新 subscription、首次 Applied。证据：RECOVERY-02/03/06/07。
- [x] **B5 SDK 重启恢复未知结果**
  已知已应用、未知结果、R2 恢复。证据：RECOVERY-03/06/07。
- [x] **B6 FNN 重启恢复 pending 签名/支付**
  原数据重启、subscription 恢复、receipt/next request。证据：RECOVERY-04/05。
- [x] **B7 撤销、关闭授权与连续付款**
  撤销签名、关闭授权、十笔连续付款及第 9 笔重启。证据：RECOVERY-06/07/08。

## C. 订阅（5）

- [x] **C1 当前工作补发与下一请求**
  初始 R1、应用 S1 后原订阅收到 R2。证据：SUBSCRIPTION-01/02。
- [x] **C2 重连/重放/按连接取消**
  未提交请求重连补发、只重放当前请求、独立订阅/取消。证据：SUBSCRIPTION-05/06/07/11/12/13。
- [x] **C3 订阅租户隔离**
  A/B 只收到各自事件，host 不读私有工作。证据：SUBSCRIPTION-03/10。
- [x] **C4 浏览器鉴权与子协议**
  注册 token、padded/Bearer、缺失/多凭证/非法编码。证据：SUBSCRIPTION-14～19。
- [x] **C5 订阅过滤、参数与上限**
  默认/显式/空过滤、非法参数、256/257、固定数组兼容。证据：SUBSCRIPTION-20～28。

## D. 发票、取消与付款（5）

- [x] **D1 Open 发票取消与跨租户隔离**
  A 取消自己的 Open 发票；B 不能取消 A。证据：INVOICE-CANCEL-01/02。
- [x] **D2 Received 状态取消**
  Received、无节点 preimage 时取消并安全清理。证据：`LSP-INVOICE-CANCEL-03`，补 SDK `authorize_cancellation` 后 1 passed / 100.80s。
- [x] **D3 入站付款、延迟签名、SDK 离线**
  P→T→A 正常付款、在线延迟、SDK 完全离线。证据：PAYMENT-01/02。
- [x] **D4 缺授权后的同进程恢复**
  真实拒签、补授权、原请求恢复、下一笔付款。证据：PAYMENT-04。
- [ ] **D5 external-signer outbound payment**
  hosted 租户主动 `send_payment` 的完整 E2E。状态：Fiber 文档明确仍缺；2026-11-05 干净 passthrough 探针：补 SDK outbound authorization、gate 全放行后，P 发票已 Received，但 A 付款 90 秒仍 Inflight；T 日志 `Failed to settle upstream trampoline payment ... non-final status Inflight`。测试 gate 已排除，D5 仍未闭环。

## E. Delivery（6）

- [ ] **E1 接纳后丢回复的最终一致性**
  原 K 已持久化、丢 reply、最终资金/30 秒稳定。状态：DELIVERY-02 产品失败；不能勾。
- [x] **E2 同 key 重投/幂等/冲突**
  InFlight/Succeeded replay、金额冲突、另一租户目标。证据：DELIVERY-01/03/04/05/06。
- [x] **E3 多通道选择与 reselect**
  同租户多通道、离线/关闭通道、dispatch 前重选、dispatch 后固定。证据（Rust 集成）：`buffered_delivery_reselects_online_same_asset_channel`、`buffered_delivery_does_not_reselect_another_asset`、`buffered_delivery_keeps_channel_after_dispatch_starts`、`buffered_delivery_skips_closed_and_shutting_down_channels`、`cold_tenant_delivery_dispatches_only_after_channel_online`。
- [x] **E4a Delivery service 重启恢复**
  Deferred/InFlight 持久化恢复、不重复 dispatch。证据（Rust 集成）：`buffered_delivery_reselection_survives_service_restart`、`settling_delivery_resumes_upstream_failure_after_restart_marker`、`restart_fails_deferred_delivery_after_upstream_tlc_removal`。
- [x] **E4b Delivery 完整 FNN 重启恢复**
  FNN 进程重启后 delivery 持久化与 LSP replay 恢复；原 key/attempt/TLC/session 不变，不新建执行。证据：`LSP-DELIVERY-07`，真实 P→T→A + 整个 Public T 重启，1 passed / 118.69s。held 签名结算、Dispatching/SettlingUpstream/Deferred 重启仍未覆盖。
- [x] **E5 Delivery downstream MPP**
  `max_parts > 1`、部分失败/全部失败/最终成功。证据（Rust）：`payment_delivery_accepts_downstream_mpp_and_rejects_invalid_state_transition`。
- [x] **E6 Delivery 限额和 pending 清理**
  `max_pending_deliveries`、per-tenant、buffer 期限。证据（Rust）：`payment_delivery_enforces_per_tenant_pending_limit`、`cold_tenant_delivery_fails_at_buffer_deadline`、`in_flight_delivery_is_not_reverted_by_buffer_deadline`。

## F. Watchtower（4）

- [x] **F1 缺批准拒签与显式批准后适配结算**
  130 秒无结算、批准后真实提交。证据：WATCHTOWER-02。
- [x] **F2 跨租户读取/提交隔离**
  B 不能读/提交 A 的 watchtower 工作。证据：WATCHTOWER-03/04。
- [ ] **F3 独立收款正向到账与 sponsor 分离**
  D_A ≠ operator sponsor，A 份额完整进入 D_A。状态：产品新要求未完成；无 Case。
- [ ] **F4 payout lock 替换拒绝与陈旧请求**
  check-only 拒绝替换、旧请求/新请求排序。状态：WATCHTOWER-06 未自动化；陈旧请求只有部分证据。

## G. 期限、强关与竞争（4）

- [x] **G1 外部注资超时中止与晚到提交**
  注资超时、输入未花费、晚到钱包签名拒绝。证据：TIMEOUT-01/02/03/06。
- [x] **G2 签名期限、强关承诺与 loser 恢复**
  受控强关、承诺哈希、恢复窗口。证据：TIMEOUT-07/08/10/11/12。
- [ ] **G3 #1674 普通开通超时/晚到通道签名**
  TIMEOUT-04/05 仍失败；不能勾完成。
- [ ] **G4 自然双方强关竞争/race 覆盖**
  受控 T-win 和 A-win **双向分支均已通过**：T-win/A-loser 有 `LSP-TIMEOUT-12`；A-win/T-loser 有 `LSP-TIMEOUT-13`（1 passed / 5:40）。自然竞争/多轮概率仍未判定，因此本行不勾“自然 race 完成”。

## H. 系统边界与安全（6）

- [x] **H1 同一租户多通道生命周期**
  多通道开户、状态 `channels[]`、通道关闭后仍可继续其他通道。证据（Rust 集成）：`hosted_tenant_can_open_multiple_channels`、`tenant_registry_binds_multiple_channels_with_assets`。
- [x] **H2 资源上限与拒绝**
  `max_active_tenants`、pending delivery、buffer 上限的边界行为。证据（Rust）：`tenant_supervisor_hydrates_evicts_and_enforces_capacity`、`payment_delivery_enforces_per_tenant_pending_limit`、`hosted_invoice_buffer_duration_is_capped_at_seven_days`。
- [x] **H3 跨租户并发/竞争**
  同时开通道、签名、订阅、取消的隔离。证据（Rust 集成）：`hosted_signer_requests_are_isolated_across_concurrent_tenants`、`offline_tenant_does_not_block_an_online_tenant`。
- [ ] **H4 严格 nonce-reuse / fail-closed**
  nonce 重用和缺失 material 的 fail-closed。状态：文档列为 release gate，产品未完成。
- [x] **H5 `lsp` feature 关闭的构建/启动回归**
  不带 lsp feature 的 FNN 正常启动；`lsp:`/services 配置被明确拒绝。证据：`LSP-FEATURE-01/02`，无 lsp 构建 56c761c，2 passed / 80.62s。
- [x] **H6 当前 head 退款链路**
  REFUND-01～03 在 56c761c 自然时间重跑：`1 passed / 4:12:20`，实际分支 `T-then-A-sweep`。独立 TLC 退款分支未观察到；辅助 TLC 自检 F2 仍明确 skip。

## 未完成项优先级

| 优先级 | 关键行为 | 状态/成本 |
| --- | --- | --- |
| P0 | E1 Delivery-02 最终一致性 | 等产品修复，修复后复验 |
| P0 | E4b Delivery 完整 FNN 重启恢复 | 需要 delivery + FNN 重启 fixture；Service restart 已有 Rust 覆盖 |
| P0 | D2 Received 取消 | 已通过（`LSP-INVOICE-CANCEL-03`，100.80s） |
| P0 | F3 独立收款正向 | 等产品新要求 |
| P0 | G3 TIMEOUT-04/05 | 等 #1674 |
| P0 | A2～A5 租户查询/admin 边界 | 已设计 G1，低成本，待实现 |
| P1 | D5 external-signer outbound、F4 watchtower06、G4 自然竞争、H4 nonce | 产品/契约或非确定性专项 |
| P1 | H4 nonce、H5 feature-off | 产品/构建级门禁 |


## 剩余九项最终归类（2026-11-05）

九项之间没有严格前置依赖；它们共享同一 devnet/端口，所以只能串行。当前没有一项能在这台宿主机上新增“通过”结果，不能把产品失败或契约未定写成完成。

| 项目 | 最终状态 | 依据/原因 | 下一步 |
| --- | --- | --- | --- |
| E1 `DELIVERY-02` | **产品失败** | 56c761c 已复验失败：接纳后丢回复，最终一致性不成立 | 等产品修复后复验，不重写预期 |
| D2 Received 取消 | **已通过** | 补 SDK `authorize_cancellation` 后 `LSP-INVOICE-CANCEL-03` 1 passed / 100.80s；文档 issue #1723 单独处理 | 保留文档同步项 |
| D5 external-signer outbound | **产品未完成（干净探针仍失败）** | 文档仍列为剩余；补 outbound authorization、gate 全放行后 P 发票 Received，但 A 付款 90 秒仍 Inflight，T 报 upstream 非终态 | 等完整 outbound E2E，不用内部 runtime 测试冒充 |
| F3 Watchtower 独立收款正向 | **产品未完成** | 当前结算仍把 unlock 金额付给 sponsor fee-provider；独立 D_A 正向未实现 | 等双地址/独立收款实现 |
| F4 WATCHTOWER-06 | **产品阻塞** | 当前 `build_settlement_transaction` 的 settlement output 直接 lock 到 fee provider S，没有可替换的 A payout output；无法做单变量 check-only | 等产品产生独立 D_A 候选后再补 |
| G3 TIMEOUT-04/05 | **产品失败** | #1674 未修复；普通开通超时/晚到通道签名仍失败 | 等 #1674 |
| G4 自然强关竞争 | **受控双分支通过** | T-win `LSP-TIMEOUT-12`；A-win `LSP-TIMEOUT-13` 1 passed / 5:40；自然竞争未判定 | 可选压力/混沌专项，不是普通门禁 |
| H4 nonce fail-closed | **产品 gate 未完成** | 文档列为 release gate；严格 nonce-reuse/fail-closed 未完成 | 等产品安全门禁 |
| H6 当前 head 退款 | **已通过（单分支）** | 56c761c 自然时间：`1 passed / 4:12:20`，实际分支 `T-then-A-sweep`；独立 TLC 退款分支未取得；辅助自检 F2 仍 skip | 保留分支边界，不扩写为所有退款路径通过 |

因此关键行为进度为 **37/44（约 84%）**；剩余 7 项：D5、E1、F3、F4、G3、G4 自然竞态、H4。未把“无法测试”折算成通过。


## 核心缺口场景覆盖计划（2026-11-05）

这里记录的是**执行入口/阻塞原因**，不是正式测试覆盖。正式覆盖必须满足：有测试代码、在当前 head 执行、有原始结果；设计、诊断日志和“等产品”都不算。

| 核心场景 | 覆盖入口 | 当前结果 | 已知问题 |
| --- | --- | --- | --- |
| D5 external-signer outbound payment | **正式用例** `LSP-PAYMENT-05`（xfail） | 1 xfailed / 139.97s；A 付款未 Success | 产品 outbound 上游收口未完成 |
| D2 Received 取消 | **正式用例** `LSP-INVOICE-CANCEL-03` | `1 passed / 100.80s`；补本地取消授权后通过 | 文档 #1723 仍待同步；主路径已验证 |
| F3 Watchtower 独立收款正向 | `LSP-WATCHTOWER-01` 设计入口 + 当前源码前置检查 | 前置不成立 | 产品仍把 unlock 付给 sponsor |
| F4 WATCHTOWER-06 | `LSP-WATCHTOWER-06` 设计入口 + 当前 builder 检查 | 前置不成立 | 无独立 A payout output 可变异 |
| H4 nonce fail-closed | 产品 release gate/源码入口 | 未执行 | 严格 nonce fail-closed 未实现 |
| H6 当前 head 退款 | **正式自然时间用例** `test_tlc_timeout_refund.py` | `1 passed / 4:12:20`，实际分支 `T-then-A-sweep` | 独立 TLC 退款分支未取得；辅助自检 F2 仍 skip |
| G4 自然强关竞争 | `LSP-TIMEOUT-12`（T-win）+ `LSP-TIMEOUT-13`（A-win） | 受控双分支均通过；自然竞态未判定 | 非确定性，需专项预算 |

结论：**D2、H6 已有正式通过；D5 已有正式 xfail；G4 受控双分支已通过；F3/F4/H4 仍是产品阻塞，G4 自然竞态仍未判定。不能报 7/7 或 100%**。产品失败不写成通过，也不再把入口冒充测试。

### D5 正式覆盖

用例：`test_cases/fiber/devnet/lsp/test_hosted_outbound_payment.py::TestHostedOutboundPayment::test_hosted_tenant_pays_ordinary_node`
结果：`1 xfailed in 139.97s`（`# TEST-MAP: LSP-PAYMENT-05`）。

## 维护规则

1. 只有当前 head 有真实通过证据才勾选；产品失败、契约未确认、只设计不实现都不勾。
2. 新行为先进入本清单，再按需要创建/更新 Case；Case ID 不在这里重复定义。
3. 每次测试完成后更新本文件和 `COMPLETION.md`，不维护第二份通过率台账。
4. 清单是**行为覆盖**，不能替代 Case 表、Spec 和 B review；Case 仍走 ai-test-agent 的 G1/G2。

## Rust 覆盖证据（2026-11-05）

命令：`cargo test --locked --offline -p fnn --lib lsp::tests --features rocksdb`

结果：**76 passed / 0 failed / 0 ignored**（测试运行 13.47s）。覆盖包括：多通道 reselect、delivery service restart、MPP、per-tenant 限额、buffer deadline、eviction 门禁、多通道开户、并发租户、outbound 付款等。

层级说明：这些是 Rust 单元/集成测试，不等于 Python 黑盒 E2E；关键行为只按“有真实测试证据”勾选，并在行内注明层级。D5 仍不勾：现有 outbound 测试使用 hosted 内部 runtime；Fiber 文档仍把完整 external-signer outbound E2E 列为剩余项。

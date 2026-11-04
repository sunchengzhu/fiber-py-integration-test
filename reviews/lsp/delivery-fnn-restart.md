# Delivery 完整 FNN 重启恢复

范围：候选 `56c761c45c271c086b05c8d5ea3e033448f5fdf8` 上的一条完整进程级恢复：真实 P→T→A delivery 在 `InFlight` 时，重启整个 Public T 进程（不是只重启 LSP service）。重启后既检查 store 投影仍为原 key/attempt/TLC/session，也通过测试 wrapper 把原 `TrampolineForwardingRequest` 重投给 LSP service，确认 service 返回同一 delivery、不新建记录。held settlement 签名跨重启后的结算、Dispatching/SettlingUpstream/Deferred 重启留作后续分支，不能由本 Case 冒充。

依据：[hosted LSP delivery 状态机与重启恢复说明](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)；[delivery manager 的持久化与重放 key](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/lsp/delivery.rs)；Rust service restart 覆盖：`buffered_delivery_reselection_survives_service_restart`、`settling_delivery_resumes_upstream_failure_after_restart_marker`、`restart_fails_deferred_delivery_after_upstream_tlc_removal`。这里补的是完整 FNN 进程重启，不是 service restart。

## Spec

### SPEC-01：InFlight delivery 的原执行在完整 FNN 重启后仍可识别

Condition: A 已通过真实 P→T→A 付款进入 `InFlight`；Public T 的 delivery 记录已持久化为非终态；测试记录原 key、request、attempt_count、上游 TLC、下游 session。
Expected: 停掉并重启整个 Public T 进程（同一 config/Store），重启后从 Store 投影仍能找到**同一个** delivery key；request、attempt_count、上游 TLC、下游 session 与重启前一致；随后通过 wrapper 的 `replay_request` 控制把原 request 交给 LSP service，返回同一 key/记录且 attempt_count 不变，不生成第二条 delivery 记录。该 Case 不声称“重启后一定结算成功”，也不覆盖 Dispatching 的重复窗口。
Observable: 重启前后 wrapper `snapshot` 的 `deliveries`（store 投影）、key、request、attempt_count、上游 TLC（按 incoming channel/TLC 从 `channels` 取）、下游 session（按 payment_hash/created_at/previous_keys 从 `sessions` 取）；重启后 `replay_request` 的返回、control ready、P/T 与 A/T 通道 ready。
Basis: [非终态 delivery 从 Store reload，按原 incoming channel/TLC 恢复](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp.md)；[delivery manager 持久化/key/attempt 字段](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/lsp/delivery.rs)。
Source: explicit
Testing: required

### SPEC-02：held settlement 签名跨完整 FNN 重启后的行为（不测试）

Condition: InFlight 时 A 的 settlement 签名已由 SDK 生成并被测试扣住。
Expected: 待确认：完整 FNN 重启后，原 SDK 是否能通过新的 WS subscription 恢复该 pending 请求并接受原签名；文档只说明依赖 WS subscription，显式把 persisted signature receipt / channel continuation 的 crash/race 列为未完成 readiness。
Observable: 重启后 SDK subscription replay、pending signing request、原签名 Applied、付款终态。
Basis: [remote signer pending-state recovery 依赖 WS subscriptions，crash/race 仍是未完成项](../../download/fiber/source-pr-1623-56c761c4/docs/notes/hosted-lsp-remote-signer.md)。
Source: inference
Testing: not_tested — 需要产品/独立证据确认 held 签名跨完整 FNN 重启的恢复契约。

## 测试树

<!-- TEST-TREE-BEGIN -->
- Delivery 完整 FNN 重启
  - InFlight 记录/key/attempt/TLC/session 在完整 FNN 重启后保持：LSP-DELIVERY-07 [primary] -> SPEC-01
  - 重启后原 request 经 LSP replay 返回同一 delivery、不新建记录：LSP-DELIVERY-07 [ref] -> SPEC-01
  - held settlement 签名跨重启恢复 [pending] — 文档未给出显式保证；需产品确认后再设计，不能用本 Case 冒充。
  - Dispatching（已持久化、下发窗口）重启 [unanalysed] — 需要在下游 session 创建前后注入崩溃；下一分支。
  - SettlingUpstream 重启 [unanalysed] — 需要上游结算中的故障注入；下一分支。
  - Deferred/离线通道完整 FNN 重启 [unanalysed] — 需要尚未 dispatch 的 delivery。
<!-- TEST-TREE-END -->

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-DELIVERY-07` | - [x] A 的 P→T→A delivery 真实 InFlight；记录原 key/request/attempt/上游 TLC/下游 session；停掉整个 Public T，确认旧 PID/端口消失且同一 config 能重新启动后用同一 Store 重启；换新 events 文件并重接 control；观察 store 投影和通道 readiness；最后用 wrapper 的 `replay_request` 把原 request 交给 LSP service | 重启后 store 投影仍有同一 delivery key，request/attempt_count/上游 TLC/下游 session 与重启前一致；`replay_request` 返回同一 key/记录、attempt_count 不变，没有第二条 delivery 记录；不提交 held 签名，不声称结算成功；P/T 与 A/T 通道恢复 ready | 完整 FNN 重启只有 RocksDB 记录、LSP 恢复逻辑却返回新执行或丢掉原执行，或重投生成第二份执行 | P0 |
<!-- TEST-CASES-END -->

## 验证设计

- 独立预期：原 key/request/attempt/上游 TLC/下游 session 来自重启前的 store 快照；重启后逐项比较。`captures` 是 wrapper 进程内状态，重启后为空，**不用于**本 Case 的 no-dispatch 或终态证据。
- 实际入口与观察：`_DeliveryBase` 的真实 P→T→A；产生 InFlight 后记录 wrapper snapshot 的 `deliveries`、付款/invoice/TLC/session；停掉 `lsp-delivery-node` 整个进程，等待进程退出、RPC 端口关闭和 Store 锁释放。
- 重启 recipe：更新 `LSP_DELIVERY_EVENTS` 到新的唯一 events 文件（wrapper 使用 `create_new`，不能复用旧路径）；旧进程 `wait()`、确认旧 PID/RPC 端口消失；删除旧 Unix control socket；用同一 `host_binary`、config、`-d`、operator token 环境重新 Popen；等待 RPC `node_info`、control `status.ready`；再用 operator 的 `lsp_get_status`/`lsp_get_payment_delivery` 和 P/T、A/T 的 `list_channels` 等待 ChannelReady。若 P/T 未自然重连，允许一次标准 `connect_peer` 并记为环境前置，不静默超时。
- 证明边界：完整 FNN 进程重启、store 投影和 LSP replay 恢复；不证明 held 签名结算、Dispatching/SettlingUpstream/Deferred 重启、自然并发或资金守恒。held 签名分支标为 pending，失败不能算本 Case 通过或环境失败。

## B review 与处理

第一轮 B review 结论为 **G1 not ready**，阻断项已处理：

| Finding | 处理 |
| --- | --- |
| B-01：同一 events 路径会因 `create_new` 启动失败 | 重启使用新的唯一 events 文件、重置 snapshot offset、归档旧日志；旧 socket 在旧进程退出后删除 |
| B-02：captures 不能证明重启后 no-dispatch/只结算一次 | 删除 captures 证据；只用 store 投影 key/request/attempt/TLC/session 比较；不声称 no-dispatch 或终态结算 |
| B-03：held 签名跨完整 FNN 重启成功不可推导 | SPEC-02 标 `not_tested`，树中标 pending；本 Case 不提交签名 |
| B-04：重启控制面/readiness 缺口、A/B 引用错误 | 写明 terminate→wait→端口/Store 锁→socket unlink→新 events→Popen 同一 config/store→control ready→operator/通道 ready；只用 A，不再写 B |
| B-05：InFlight 不覆盖真实 Dispatching 重复窗口 | 收窄 SPEC-01，不声称“不重复 dispatch”；Dispatching/SettlingUpstream 明确标 unanalysed |
| R1：只读 store 不是 recovery | 增加重启后 `replay_request` 原 request，要求同一 key/记录且不新建；仍不声称结算成功 |
| R2：字段比较过宽/措辞不一致 | 明确从 channels 取上游 TLC、从 sessions 取下游 session；改为“不新建 delivery 记录”，不再写“不重复 dispatch” |
| R3：Store 锁没有直接探针 | 以旧 PID/端口消失 + 同一 config 成功启动为探针；P/T 未自然重连时允许一次 connect_peer 并记录为环境前置 |

# Hosted LSP 签名超时退出与资金处理用例评审

评审范围：区域图第三组“超时保护与结果一致性”。同一租户 A 与公共 LSP T 的私有通道在两种计时下越过截止：开通阶段（外部钱包注资期限、普通开通期限）和通道就绪后的支付签名安全截止 D。包含晚到提交、无人提交时自动保护，以及不交出 preimage 时可观察到的结果。

本批不做：Hosted 侧链上取回与付款最终余额、费用核对；SDK 对过期请求的拒签（见“本批不覆盖的缺口”）。

原始评审源码版本：[Fiber PR #1623](https://github.com/nervosnetwork/fiber/pull/1623)，当时 HEAD `0f41d9a1f1d20bd5b1fe35e0f249c4340019a073`；测试仓库基线 `852c97daeb41b9b3824dae184d4952ddad1069d1`。范围与依据见 [Gate1 范围分析](channel-signing-deadline-scope.md)；历史 `8419c00` 维护与执行结果见[评审入口](../README.md)。

已知问题（2026-10-23 核实）：`LSP-TIMEOUT-04/05` 在 `24b5c38` 的两轮失败归入
[Fiber #1674](https://github.com/nervosnetwork/fiber/issues/1674)（当日为 Open）：钱包签名提交后未安排普通开通期限检查。
05 同样停在等待开通中止，尚未执行晚到通道签名提交。后续接续优先查阅
[既有诊断、复现与原始日志](../../test_cases/fiber/devnet/lsp/README.md#已知问题关联1674)，无需按未知问题重新定位。
此关联不改变以下用例预期、映射或执行结果；08/10 的强关竞争另见该运行记录，不归入 #1674。

2026-10-23：用户已确认 [08/10 稳定性改造 Gate1](channel-signing-deadline-scope.md#0810-稳定性改造范围)及以下 Gate2 完整行和共同断言，本轮 **Gate3 实现、聚焦验证与固定 3 轮复跑已完成，GPT 6.1 sol 独立复核无阻断项**。
依据固定为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；只实质修改 08/10，保留其 ID、P0 和现有 TEST-MAP，其他行仅补充结构索引，未重新批准或验证。
`[x]` 仍只表示已有代码映射；08/10 的 Python 已接入下述广播隔离，实际执行结果另见[运行记录](../../test_cases/fiber/devnet/lsp/README.md)，不能用旧结果代替本轮验证。
自然竞争后败方识别赢家的恢复问题单独保留评审；后续独立诊断已在检查点 A 的自然 T 胜出样本、检查点 B 的受控查询时序 T 胜出样本中观察到 Hosted A 自动收敛，证据见下方 SPEC-09。结论仅适用于已取得的路径；本轮只改 Python 测试与相关文档，不改产品代码。

当前批次：用户已通过 SPEC-09 的 [Gate1](channel-signing-deadline-scope.md#spec-09-独立败方恢复回归gate1-范围) 与下方 Gate2 完整行、预算和断言，**Gate3：`LSP-TIMEOUT-12` 检查点 B 的独立败方恢复已实现并验证**。在固定 `24b5c38` 上，修复后聚焦加固定 3 次复跑 **4/4 通过**，相关 08/10 **2/2 通过**。初始两次夹具失败、修复、全部原始证据及独立复核见 [SPEC-09 运行记录](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-spec-09lsp-timeout-12-独立败方恢复2026-10-23)。`[x]` 只表示映射存在；历史诊断及 08/10 通过不转记为 12 通过。产品及驱动保持不变。

## Spec

SPEC-01～08 保留既有行的来源与结构，不改变其预期；新增行 12 使用 SPEC-09。

### SPEC-01：外部注资期限及晚到钱包提交（原有行为）
Condition: 通道等待外部钱包注资，或钱包已在外部期限内提交。
Expected: 未提交时到期中止且原输入未花费，晚到钱包提交不能复活；已及时提交时旧检查不提前中止，放行通道签名后正常就绪。
Observable: 开通失败记录、真实提交结果、CKB 输入及原通道就绪状态。
Basis: [原 Gate1 的开通分支](channel-signing-deadline-scope.md#两条业务分支不能使用同一种超时预期)及本文件原 01～03 行。
Source: explicit
Testing: required

### SPEC-02：普通开通期限及晚到通道签名（原有行为）
Condition: 钱包已提交，开通仍可安全中止，后续通道签名一直扣留。
Expected: 普通期限到达后中止且注资未上链；中止后的通道签名不能首次应用或复活通道。
Observable: 双方 FUNDING_ABORTED、链上输入、真实 RPC 拒绝与通道数量；当前已知失败归入 #1674。
Basis: [#1674](https://github.com/nervosnetwork/fiber/issues/1674)及本文件原 04/05 行。
Source: explicit
Testing: required

### SPEC-03：支付签名检查点对照（原有行为）
Condition: hold 发票、短期限 TLC 与真实 SDK 授权就绪，依次放行承诺和撤销签名。
Expected: 检查点 A 为待签且 Open，B 已有含 TLC 的完整承诺但仍 Open；ACK 往返完成后为 Received 且无需签名。
Observable: TLC、SDK 已签记录、请求状态与发票状态。
Basis: [原 Gate1 发票状态依据](channel-signing-deadline-scope.md#已经查清的一项预期不交-preimage-时的发票状态)及本文件原 06 行。
Source: explicit
Testing: required

### SPEC-04：截止后的新签名不能继续更新（原有行为）
Condition: 检查点 B 的未应用撤销签名在 D 之后提交。
Expected: 不首次应用、承诺不推进，节点进入保护；不要求一定由此次提交触发。
Observable: 提交结果、承诺版本与关闭行为；原 07 的竞争归因假设不在本轮修复范围。
Basis: [截止提交检查](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L2276)及本文件原 07 行。
Source: explicit
Testing: required

### SPEC-05：无人提交时 A 自动保护并阻止旧请求复活
Condition: 检查点 A 的真实通道签名一直扣留，A 的旧完整承诺不含目标 TLC，T 竞争广播按 SPEC-08 隔离。
Expected: A 在 D 后自行启动保护并广播旧完整承诺，真实链确认；请求清理，确认后提交原签名不能应用或产生新承诺。
Observable: A 的状态及实际发送、CKB 接受/确认和注资花费、规范化签名消息、NoSignatureRequired、晚到 RPC 错误及稳定观察。
Basis: [维护触发](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L4339)、[本地保护与请求清理](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L3411)及已确认 Gate1。
Source: explicit
Testing: required

### SPEC-06：A 强关采用含目标 TLC 的完整承诺
Condition: 检查点 B 已完整签署含目标 TLC 的 A 承诺，下一撤销签名扣留；T 竞争广播按 SPEC-08 隔离。
Expected: A 自动保护，真实确认交易与该 SDK 记录的签名内容一致，准确包含目标 payment_hash 和 expiry；在发票有效期内检查仍为 Open。
Observable: 保存与确认时的 SDK 记录、实际交易和 funding outpoint、A 的本地强关状态、发票状态。
Basis: [使用已有承诺强关](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L2697)、[规范化交易消息](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-types/src/channel_signer.rs#L650)及已确认 Gate1。
Source: explicit
Testing: required

### SPEC-07：未交 preimage 的 Received 发票不能被关闭误改（原有行为）
Condition: 目标发票已 Received，其 TLC 在完整承诺中；另一 TLC 卡在签名截止并触发保护。
Expected: 原发票在关闭确认及自身有效期之后仍为 Received，不为 Paid，不把锁定金额计为成功收入或重复结算。
Observable: 发票、已签承诺、余额与锁定额；不据此证明 watchtower 取回。
Basis: [原 Gate1 发票状态依据](channel-signing-deadline-scope.md#已经查清的一项预期不交-preimage-时的发票状态)及本文件原 11 行。
Source: explicit
Testing: required

### SPEC-08：竞争广播隔离必须有真实发生的证据
Condition: 在 D 前唯一绑定目标 funding outpoint 与 A/T 两份不同规范化签名消息；仅本条测试环境启用 CKB RPC 拦截器。
Expected: A 的匹配交易原样送真实 CKB并确认，T 的匹配交易至少实际被拦一次、所有重播同样处理；未知目标交易或隔离前提缺失均使本次失败。
Observable: FNN 实际发送、拦截器分类/原始响应与时间、独立 CKB 查询；不伪造成功，不由测试代发承诺，不以重跑取得通过。
Basis: 已确认 [Gate1 广播隔离方案](channel-signing-deadline-scope.md#推荐方案仅在两条用例中隔离竞争交易广播)；[共享链 actor 的发送行为](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/ckb/actor.rs#L310)。
Source: explicit
Testing: required

### SPEC-09：双方真实竞争后的独立败方恢复与回归边界
Condition: 检查点 B 保留双方真实广播；一次固定 250 ms 的 A 查询响应窗口内 T 的真实发送被接受，A 随后得到真实 RBFRejected；T 确认且同一 funding 花费已被索引器查到，FNN/SDK/链持续运行。
Expected: A 在链观察就绪后 330 秒内自动转为 Closed，含 UNCOOPERATIVE_REMOTE、关闭哈希等于 T 的真实确认交易、NoSignatureRequired；完整观察 330 秒且首次恢复后至少观察 10 秒，全部后续样本不回退，总观察上限 340 秒。这是固定版本回归预算，不是产品 SLA。
Observable: 唯一 A/T 内容绑定、双方真实请求/响应、精确 funding 花费、单调时间与连续状态样本，以及同一 channel 的 Hosted A 远端关闭识别与状态转换日志。
Basis: 已批准 [SPEC-09 Gate1](channel-signing-deadline-scope.md#spec-09-独立败方恢复回归gate1-范围)；固定版本 [失败处理](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs)、300 秒 Hosted 扫描及远端识别（同文件 2514～2520、256、9125～9131、4860～4906 行）；[链索引查询](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/ckb/client.rs) 139～152、187～215、321～338 行。
Source: explicit
Testing: required

历史证据：[A 自然诊断](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-自然竞争后的恢复诊断2026-10-23)与 [B 受控诊断](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-检查点-b-的竞争与恢复诊断续查2026-10-23)分别观察到恢复。B 的前三次无额外时序控制尝试均 A 获胜；新行 12 的 Gate3 实际结果单独记录，不沿用诊断通过。250 ms 控制不用于推断无干预竞态概率，关闭识别不证明链上结算或资金取回。

## 测试树

<!-- TEST-TREE-BEGIN -->
- 开通阶段（本轮不改行为）
  - 未交钱包签名到期中止：LSP-TIMEOUT-01 [primary] -> SPEC-01
  - 中止后晚到钱包提交不复活：LSP-TIMEOUT-02 [primary] -> SPEC-01
  - 及时钱包提交后的旧检查不误中止：LSP-TIMEOUT-03 [primary] -> SPEC-01
  - 普通开通期限中止且输入未花费：LSP-TIMEOUT-04 [primary] -> SPEC-02
  - 中止后晚到通道签名不应用：LSP-TIMEOUT-05 [primary] -> SPEC-02
- 通道就绪后的签名保护
  - 原检查点/晚到提交/发票行为（本轮不改）
    - A、B 到 Received 的真实对照：LSP-TIMEOUT-06 [primary] -> SPEC-03
    - D 后的新签名不应用：LSP-TIMEOUT-07 [primary] -> SPEC-04
    - Received 发票不因关闭误结算：LSP-TIMEOUT-11 [primary] -> SPEC-07
  - 已有隔离 T 广播后的 A 侧保护
    - 检查点 A 无新提交，旧无 TLC 承诺确认且旧请求不复活：LSP-TIMEOUT-08 [primary] -> SPEC-05
    - 检查点 B 扣留撤销签名，含目标 TLC 承诺确认：LSP-TIMEOUT-10 [primary] -> SPEC-06
    - 两侧内容唯一绑定、T 真正被拦、A 真正上链、未知即失败：LSP-TIMEOUT-08 LSP-TIMEOUT-10 [ref] -> SPEC-08
  - 双方真实竞争后的败方识别（本批仅 B）
    - B 的含 TLC 完整承诺就绪，T 胜出且 A 真实 RBF 后自动识别远端关闭：LSP-TIMEOUT-12 [primary] -> SPEC-09
    - 一次固定查询窗口、唯一交易归属及真实确认，缺任一前提均不能记恢复通过：LSP-TIMEOUT-12 [ref] -> SPEC-09
    - 索引可见后完整观察，关闭方向/hash/无待签恢复后不回退，并有 Hosted A 归因证据：LSP-TIMEOUT-12 [ref] -> SPEC-09
<!-- TEST-TREE-END -->

## 接口说明

- T 是承载租户的公共 LSP 节点，A 是 T 托管的租户（真实 SDK 进程、真实 token），P 只用于钱包注资签名辅助，本批不作为付款方。
- 开通走外部注资：SDK 的 `open_tenant_channel` 保存钱包意图并校验注资输入后返回未签交易；测试用钱包私钥签名，再由租户客户端 `submit_signed_funding_tx` 提交。钱包注资提交与通道承诺签名提交是两个不同接口。
- 中止开通后原通道状态对象会被删除：该版本要在 `list_channels(only_pending=true)` 里读由开通记录合成的失败条目，状态为 `Closed` 且带 `FUNDING_ABORTED` 标志，可带中止详情。此时没有承诺哈希、也没有承诺号可查。
- 支付侧的 TLC 由操作员客户端调用 dev 模块的 `dev_add_tlc` 注入，可指定 `expiry`。该 debug 构建启用 `debug-add-tlc` 并在 `rpc.enabled_modules` 中启用 `dev`，源码里也明确支持无 onion 的 TLC 走结算判断。注入只替代“TLC 如何进入通道”；hold 发票、SDK 发票授权、真实签名、截止保护、强关和链上确认都是真的。
- 真实路由支付的最终 TLC 期限无法压短：付款方会给每笔支付加至少一个 4 小时的隐私随机延长，发行二进制没有开关，T 转发到 A 的钳制也不会让它更早，因此真实路由支付的 D 至少在 4 小时后。本批不使用真实路由支付做截止用例。
- **承诺已签不等于 ACK 已完成**：承载 TLC 的承诺可以先完整签署（此时它已包含目标 TLC），随后仍有一份撤销签名待提交；只有这份撤销签名应用、对端的撤销与 ACK 往返完成之后，接收 TLC 才会进入结算判断，仍为 `Open` 的发票才被置为 `Received`。所以“承诺含 TLC”和“发票 `Received`”是两个不同检查点，不能同时要求。
- 观察点：`list_channels`（含 `only_pending=true`）的 `state_name`、`state_flags`、`failure_detail`、`latest_commitment_transaction_hash`、`pending_tlcs`；`get_channel_signing_status`；`get_invoice`；SDK 控制面 `records`（含每个已签承诺的 TLC 与 expiry）；CKB 交易与 live cell 查询。
- 所有拒绝预期均指真实 FNN 或真实 SDK 的拒绝。转发器暂停、断线或等待超限只是故障注入或测试失败，不能冒充产品拒绝。晚到提交的错误文字可以随通道状态不同，因此只断言“没有被应用、没有副作用”。

## 三个支付侧检查点

支付侧用例共用同一夹具，只有“停在哪个检查点、扣住哪一份请求、提交什么”不同。

| 检查点 | 已经完成 | 此时必须成立 | 后续动作 |
| --- | --- | --- | --- |
| A（签名前） | 发票与 SDK 授权已就绪，T 已注入目标 TLC | 目标 TLC 出现在 A 的 TLC 列表；A 出现承载 TLC 的待签请求并保存完整内容；发票仍为 `Open`；尚未应用任何签名 | 不再提交任何签名（`LSP-TIMEOUT-08`），或放行这份签名以进入检查点 B |
| B（承诺已完整签署，撤销签名待提交） | 已应用承载 TLC 的承诺签名 | 最新已签承诺含目标 TLC（`latest_commitment_transaction_hash` 与注入前不同，SDK 记录中该版本完整签署且含目标 `payment_hash` 与实际 expiry）；随后出现的下一份待签请求已被扣住；**发票仍为 `Open`**，因为撤销与 ACK 往返尚未完成 | 越过 D 后提交（`LSP-TIMEOUT-07`），或始终不提交（`LSP-TIMEOUT-10`） |
| C（目标发票已 `Received`，另有一份待签请求） | 目标 TLC（记为 TLC-A）的承诺签名与撤销签名都已应用，ACK 往返完成 | 发票 A 变为 `Received`，TLC-A 在最新已签承诺中，且此时没有待签请求；随后注入另一笔 TLC-B（独立发票与独立授权）并停在它的检查点 B，由 TLC-B 提供待签请求 | 让保护在 D 触发（D 取两笔 TLC 中较早的 expiry 减 1333 毫秒），核对发票 A 的终态（`LSP-TIMEOUT-11`） |

- 检查点 A 上 A 可用的已完整签署承诺是**注入前**那份，不含目标 TLC；检查点 B 上才是含目标 TLC 的那份。因此“强关承诺含 TLC”只在检查点 B 起断言。
- 检查点 B 的发票仍是 `Open`；只有检查点 C 才有 `Received`。`LSP-TIMEOUT-11` 因此不能复用 07、10 的检查点，必须另建 C。
- 08/10 以“目标注资输入 + SDK 规范化签名消息 + 实际广播 + 真实确认”归因；不再用 30 秒内关闭、原始哈希相等或两侧关闭哈希不同排除 T。刷新依赖可以改变原始哈希，两侧也可最终记录同一确认交易。
- 原 07/11 的行与步骤本轮保留，相关旧归因假设未因此修复；它们不适用 08/10 新增的隔离条件，也不能把原通过结果解释为已排除自然竞争恢复缺陷。

## 用例

本批只新增 12（P1，独立失败恢复行为）；原有 10 行保持原文。12 的检查点 B、`t_ready` 和全部预算详见其专节；本行已在 Gate3 接入 TEST-MAP，复选框不代表运行通过。

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-TIMEOUT-01` | - [x] A–T 进入外部注资等待后一直不提交钱包签名，直到越过配置的外部注资期限；随后用 `list_channels(only_pending=true)` 查询双方开通失败记录，并核对链上输入 | 双方都出现该通道的失败条目，状态为 `Closed` 且带 `FUNDING_ABORTED` 标志；没有任何注资交易上链；原未签注资交易的每个输入仍是可用 live cell | 超期不中止、只在单侧生效，或中止时钱包资金已经被带上链 | P0 |
| `LSP-TIMEOUT-02` | - [x] 在 01 的中止终态上，用保存的原未签注资交易补签并提交，再查询开通记录、通道数量与链上 | 提交被拒绝；失败条目保持同一条 `Closed` 与 `FUNDING_ABORTED`，不出现新的待开记录或新通道；原输入仍未被花费 | 晚到钱包提交把已放弃的通道重新激活，或让同一笔资金对应两个通道 | P0 |
| `LSP-TIMEOUT-03` | - [x] 钱包在外部注资期限内提交有效注资交易，之后的通道签名一直暂缓到越过原外部注资期限、但未越过普通开通期限；再放行签名并等待开通完成 | 原通道没有被中止，仍在合法开通过程中；放行后双方达到 `ChannelReady`，`channel_outpoint` 指向本次那笔已确认注资，没有重新注资或重开通道 | 旧的外部注资计时器误杀已完成钱包提交的流程，或“没有中止但流程其实已坏”被当成通过 | P1 |
| `LSP-TIMEOUT-04` | - [x] 钱包提交已完成、通道停在允许安全中止的开通阶段，扣住后续通道签名直到越过配置的普通开通期限 | 用 `list_channels(only_pending=true)` 在双方都查到该通道的失败条目，状态为 `Closed` 且带 `FUNDING_ABORTED` 标志；该注资交易从未广播到链上（链上查不到、原输入仍是可用 live cell） | 把“注资已签名”当成可以随时中止，或中止后资金已经锁在链上无人处理 | P0 |
| `LSP-TIMEOUT-05` | - [x] 在 04 的中止终态上提交此前保存的真实通道签名，再查询提交结果、开通记录、通道数量与链上输入 | 提交不被首次应用，不返回 `Applied`，不产生新的承诺交易；失败条目与通道数量不变；原输入仍未被花费 | 晚到通道签名复活已放弃的开通，或用已删除的状态对象拼凑不可靠证据 | P1 |
| `LSP-TIMEOUT-06` | - [x] 夹具对照：hold 发票与真实 SDK 授权就绪，T 注入 expiry 为注入时刻加 22～25 秒的 TLC 并到达检查点 A；放行承载 TLC 的承诺签名到达检查点 B；再放行被扣住的撤销签名直到 ACK 往返完成 | 检查点 A：发票为 `Open`、待签请求出现、目标 TLC 在 A 的 TLC 列表中。检查点 B：最新已签承诺含目标 TLC 且 SDK 记录该版本完整签署，**发票仍为 `Open`**。继续放行后：发票变为 `Received`，且不再有待签请求。短期限夹具与三段状态转移都真实可达 | 夹具不可用导致后续失败行假通过，或把“承诺已签”误当成“发票已 `Received`” | P1 |
| `LSP-TIMEOUT-07` | - [x] 从检查点 B 扣住撤销签名，等到超过 D 加 1 秒再直连 FNN 提交这份签名 | 提交发生在 T 发出承诺签名后 30 秒以内；该签名不被首次应用，不返回 `Applied`，承诺号不推进、不产生新的承诺交易；A 最终进入截止保护并等待承诺确认，允许周期维护先于这次提交触发；链上关闭交易与 A 侧保存的承诺哈希一致 | 晚到签名仍能首次应用并继续原更新、节点不启动保护，或把对端无响应强关算成签名截止保护；也防止把“必须由本次提交触发”写成断言 | P0 |
| `LSP-TIMEOUT-08` | - [x] A–T 就绪后暂停本条矿工，停在检查点 A 并扣住新通道签名；在 D 前绑定双方承诺并启用广播隔离，待 A 被真实 CKB 接受且 T 的竞争广播实际被拦后恢复挖块；确认关闭后提交原扣留签名 | A 在 D 后 15 秒内无新提交、无手动关闭地启动保护并广播不含目标 TLC 的旧完整承诺；首次真实转发起 60 秒内确认并花费原注资，A 记录本地强关；待签清除，晚到提交被真实 FNN 拒绝，随后 5 秒无请求复活、承诺推进或新承诺广播；未知交易或隔离前提不成立均失败 | 自动保护依赖客户端再提交、确认错误承诺、把对端关闭冒充 A 保护，或请求清理后仍能复活更新 | P0 |
| `LSP-TIMEOUT-10` | - [x] A–T 就绪后暂停本条矿工，到达检查点 B：A 已完整签署含目标 TLC 的承诺，下一撤销签名始终扣留；在 D 前绑定双方承诺并启用广播隔离，待 A 被真实 CKB 接受且 T 的竞争广播实际被拦后恢复挖块 | A 在 D 后 15 秒内自动保护并广播该承诺；首次真实转发起 60 秒内由真实 CKB 确认并花费原注资，A 记录本地强关；确认交易规范化签名消息匹配 SDK 完整记录，目标 payment_hash 与 expiry 准确且区别于注入前承诺；未交 preimage，发票在有效期内仍为 Open；未知交易或隔离前提不成立均失败 | 用旧的无 TLC 承诺或 T 的交易冒充 A 的含 TLC 强关，或把广播成功当确认、把隔离成功当产品恢复无缺陷 | P0 |
| `LSP-TIMEOUT-11` | - [x] 建立检查点 C：先让 TLC-A 的承诺签名与撤销签名都应用、ACK 往返完成，等发票 A 变为 `Received`；再注入独立的 TLC-B 并停在它的检查点 B；让保护在 D 触发、关闭交易确认。全程不交出任何 preimage、不批准兑现；发票 A 自身有效期设为 90 秒，确认后等到越过它再查询 | 关闭交易含 TLC-A（其版本已完整签署）；发票 A 全程不是 `Paid`，确认时与越过其自身有效期之后都保持 `Received`，不变成 `Open` 或 `Expired`；收款方没有成功收入，锁定额不被当成已结算，不产生第二次结算 | 把关闭当结算完成、发票被误判已支付、锁定额被记成收入，或用“扣住 ACK 未完成”的检查点冒充 `Received` 场景 | P0 |
| `LSP-TIMEOUT-12` | - [x] A–T 就绪后到达检查点 B：A 已完整签署含目标 TLC 的承诺，下一撤销签名始终扣留；仅对 A 发送前的真实 unknown 交易查询使用一次固定 250 ms 响应窗口，保留双方真实广播，取得 T 确认及 A 真实 RBFRejected 后持续观察 | T 精确花费原 funding 且索引可查后，A 在 330 秒内自动进入 Closed/UNCOOPERATIVE_REMOTE，关闭 hash 指向 T 且为 NoSignatureRequired；观察满 330 秒并覆盖恢复后至少 10 秒（总上限 340 秒），全部后续样本不回退且有同通道 Hosted A 恢复日志；场景或证据不成立均非零退出 | A 广播失败后不能自动识别赢家、只凭无待签或最后一帧误判恢复，或把场景未取得当恢复通过 | P1 |
<!-- TEST-CASES-END -->

## LSP-TIMEOUT-12：检查点 B 独立败方恢复

固定源码、FNN、SDK 与驱动依据均为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`、dev profile；执行前重新检查构建清单、实际二进制摘要及版本。下列步骤与断言同属一条端到端用例，不把准备、日志采集另拆成“已覆盖”的产品行为。本条保持挖块、索引、FNN 和 SDK 运行，不复用 08/10 的停矿或广播 `arm()` 准备入口。

### 完整步骤

1. 建立本条独立 FNN/SDK 状态及 A–T 私有通道（双方各 500 CKB），真实注资已确认，双方 `ChannelReady`。保存目标 channel、A/T 公钥、funding outpoint（hash 与 index）、funding lock 与初始 live cell；观察代理就绪，独立断言直连真实 CKB。CKB 按现有基类生命周期管理，不假设每个方法都会重置整条链。
2. 开具金额 1,000,000 Shannon、有效期 600 秒的 hold 发票，SDK 真实授权；记录实际创建时间与到期时间，不交 preimage。注入寿命 22 秒 TLC，读回准确 `payment_hash/expiry`，固定 `D = expiry - 1333ms`（本版本 debug、2 秒/epoch、承诺延迟 1 epoch）。放行承载 TLC 的承诺签名一次，到检查点 B 后保存并始终扣留下一份 `SendRevokeAndAck`。必须是 `SignatureRequired`、发票 `Open`，A 最新完整承诺已不同于注入前且含目标 TLC。
3. 在 D 前至少 5 秒完成准备：按 A/T 最新承诺 hash 各找到唯一 SDK 记录，A 为 `complete && !for_remote` 且 TLC hash/expiry 准确，T 为 `for_remote`（不要求此记录在 A 的 SDK 中完整聚签）；计算两份不同的规范化签名消息，前后读回版本不变。此时通道仍 Ready、同一撤销请求仍待签、funding 仍 live，代理未记录目标关闭广播。保存签名提交计数基线；实际发票到期必须晚于 `D + 450s`。任一准备失败即结束本次，不重新注入 TLC 或延长发票。
4. 根据既有 `Spawning InFlightCkbTxActor ... Closing(Pubkey(T), channel, true)` 日志唯一绑定 A 的实际关闭 hash；同时保留 Hosted A 身份及动态 actor 关联。只对 D 后该 hash 的真实 `get_transaction` unknown 响应设置一次 250 ms 窗口；取到上游原文后记录 `window_start`，固定 `release_at = window_start + 0.250s`。该 hash 在窗口内并发 unknown 响应共用这一释放点，不滚动延长；至少一次命中真实发送前查询 `[hash, "0x0", true]`，只命中 tracer `[hash]` 不够。
5. 窗口等待不持共享代理锁，原始响应在固定释放点之后原样发出；T 的查询、双方 `send_transaction` 和其他请求全部真实转发。要求 T 的真实转发与 CKB 接受响应完成均落在 `[window_start, release_at)`，A 在其发送前查询已释放后真实转发。A 必须收到原始 `error.code=-1111` **且** `error.data` 含 `RBFRejected`；保存双方原始交易、响应、单调时间和规范化消息，确认分别匹配步骤 3 的 A/T 内容及同一 funding 输入。不能用错误 message、`already in pool` 日志或“非 A 即 T”判断归属。
6. 从独立 CKB 读取 T 的实际交易首次为 `committed`，记 `t_commit`，保存区块号/hash、实际交易及精确 funding 输入。所有查询延迟此时都已结束；A 的实际关闭交易不得已确认。随后直接按同一 funding lock 进行 exact、lock、非分组的 `get_transactions` 查询（desc、每页 100，最多 3 页且共用当前轮预算），必须找到 T 的 `io_type=input` 项，并用该项的 `io_index` 定位 T 完整交易中的输入、核对原 funding outpoint 的 hash/index；同时确认 T 仍 committed、索引器高度已达其区块，三项同轮成立时记 `t_ready`。不能用 `get_cells`、高度追平或最后一帧索引高度替代花费证据。
7. 从 `t_ready` 起继续挖块、索引和所有进程，代理仅记录/原样转发。按下表采样；第一次完整满足恢复谓词的样本完成时记 `t_recover`。即使提前恢复也观察满 330 秒；后续每个完整样本都必须保持恢复谓词，并至少取得相距 10 秒的恢复成功样本。首次恢复不得晚于 `t_ready+330s`，最后观察不得越过 `t_ready+340s`；扣留签名始终不提交，禁止手动关闭、重启、调费、停矿、代发交易或新的时序干预。
8. 在窗口内持续落盘证据，记录最终判断后有界清理本条资源。保存同通道 Hosted A 的 `is shutdown by remote` 与随后的状态转换，结合链/RPC 样本证明恢复来源；不写死 actor ID，不用 watchtower 的 `PeriodicCheck` 代替 Hosted A 证据。失败也保留原始日志、最后完整样本和未完成步骤，不能在清理阶段追加读取而将超期结果补成通过。

### 时间预算与采样

wall clock 仅用于 TLC/发票协议时间；在读取实际 expiry 时记录成对的 wall/monotonic 时间并一次性换算 D，后续所有 deadline 用单调时钟，重试或重播不得重新起算。若时钟明显跳变影响协议截止，保留为环境证据失败，不调整 D。环境启动与开通沿用现有有界框架等待并单独记录耗时（例如节点端口等待上限 300 秒）；下面的 `D+445s` 是业务上限，不冒称含环境启动的 pytest 总时长。

| 阶段 | 固定起点与预算 | 到期处理 |
| --- | --- | --- |
| 发票与 B 准备 | 发票实际创建起有效 600 秒；全部准备完成 `<=D-5s`，实际到期 `>D+450s` | 准备过晚、发票余量不足或记录不唯一：准备失败；不补开新发票/新通道替代 |
| 查询时序控制 | 一次 `window_start+250ms`；实际响应写出不早于 release_at，最迟 release_at+100ms（仅调度容差） | 超容差为夹具失败；T 的发送与接受仍须在原 250 ms 窗口内，不能用容差延长竞争窗口 |
| 双方真实竞争 | D 到 D+15 秒，捕获 T 接受和 A 真实 RBF；阶段轮询间隔最多 0.5 秒 | 保存实际结果；按下方分类处理，不自动调参重跑 |
| T 真实确认 | 从 T 首次匹配交易真实转发起 60 秒 | 不能以接受代替 committed；到期按真实链、广播及进程证据定位 |
| 链观察就绪 | 首次 `t_commit` 起 30 秒 | 精确 input 索引不可见时本次不能作为有效恢复验证，不启用一个新的 330 秒重试周期 |
| A 首次恢复与完整窗口 | 从 `t_ready` 起 330 秒；330 秒不是“首次恢复后再等 330 秒” | 场景/链/运行前提成立但到期不收敛：恢复回归失败；没有扫描日志也不能改判场景未取得 |
| 恢复后稳定观察 | 所有后续完整样本均成功，至少两个成功样本相隔 10 秒；观察覆盖到 `max(t_ready+330s, t_recover+10s)`，硬上限 t_ready+340 秒 | 任何状态回退为恢复失败；若边界采样不足以证明满窗/满 10 秒，即使业务状态正确也为非零证据失败，不能延长首次恢复期限 |
| 业务总上限 | D+445 秒，即最坏 15+60+30+340；同时受各阶段更早截止限制 | 预算包含 RPC、解析、状态采样与日志读取；禁止到期后再开完整等待 |
| 收尾清理 | 业务判断后单独最多 60 秒，不计入恢复时延；优先停本条 FNN/SDK，再停观察代理 | 清理故障另记并保留业务判断；不改变同机无关进程、数据或旧日志 |

恢复观察的目标采样间隔为 2 秒，每个 RPC 最多 1 秒、整轮最多 3 秒，相邻完整样本间隔不得超过 5 秒。请求（含连接、读取、解析）、整轮和阶段三层都受更早绝对截止限制；必要时并发独立查询，不能让多个串行 1 秒调用突破整轮预算，也不能靠 `requests timeout` 的分段超时宣称总耗时已受限。不启用自动 RPC 重试；超时、断连或缺字段不是 `NoSignatureRequired`。每轮保存起止时间，只有整轮完成且在期限内的结果可作断言，迟到响应只作诊断。

每轮包含 A 的真实通道状态与签名状态、T committed 及精确 funding 输入、CKB tip、indexer tip 和同 funding 的 input 可见性；同时核对 FNN/SDK/矿工存活、代理异常和签名提交计数。准备结束到 t_ready 也持续收集状态，不以“先证明 A 未恢复”作为取得场景的必要条件。恢复阶段每个滚动 30 秒段链高应增长，索引高度不倒退且持续可见目标 input；进度异常保存因果证据，FNN 崩溃不得笼统归为环境问题。

完整窗与稳定期以完成的样本时间判定：至少有一个完整成功样本在 `t_ready+330s` 或之后完成，且与首次恢复样本相距至少 10 秒，所有响应均在 `t_ready+340s` 及业务总截止前完成。须预留最终轮的剩余时间；若首次恢复临近 330 秒边界且边界采样不足以证明稳定性，按证据不足失败，不能越界读取或把 340 秒改成首次恢复期限。

### 必须同时成立的断言

- **确实是 B：** A 的当前完整签署版本含准确目标 TLC hash/expiry，区别于注入前版本；保存的下一撤销请求从未提交，基线后的真实签名提交计数不增加，全程未交 preimage。初始发票为 Open、其创建时有效期覆盖整段预算；后续发票/余额只作诊断，不在本条新增付款或资金结算终态预期。
- **真实败方场景：** D 前无目标关闭广播；唯一 A/T 消息绑定与固定窗口成立；双方都是 FNN 自发真实广播；T 接受、A 真实 RBF（code 与 data 双条件）及 T committed 缺一不可。目标 funding 的无法归属交易、代理注入错误、未命中 preflight 或 A 获胜均不能通过。
- **赢家及链就绪：** T 原始成功响应 hash、独立 committed hash、规范化消息与 SDK 的 T 记录一致；确认交易精确花费原 funding（hash/index），原 cell 已不再 live（dead/unknown 且 cell=null，仅作交叉证据）。同 funding lock 索引返回 T input，索引高度达其确认区块。不能要求 T 的承诺也含本条 TLC；本例不是 10 的 A 含 TLC 承诺上链断言。
- **恢复谓词：** A 的通道存在，`state_name=Closed`，flags 含 `UNCOOPERATIVE_REMOTE` 且不含 `UNCOOPERATIVE_LOCAL`，`shutdown_transaction_hash` 等于 T 实际确认 hash，真实签名状态为 `NoSignatureRequired`。允许仍有 `WAITING_ONCHAIN_SETTLEMENT`；无待签、单个 hash、关闭日志或 RPC 错误均不能独立证明恢复。首次完整满足后不得回退或改指其他交易；不要求观察到中间状态，以免漏采短暂状态造成假失败。
- **持续性与归因：** 满足全部时间/连续采样条件，所有恢复后样本保持上述谓词；T 在每轮仍 committed、链及索引健康，无额外干预；同 channel、同 Hosted A 的远端关闭识别日志及随后状态转换齐全。即使状态已正确，缺日志或采样缺口也不能记为本批完整证据通过。

### 非零结果分类与后续验证计划

| 观测结果 | 结果与归因边界 |
| --- | --- |
| 准备迟到、绑定歧义、未知目标内容、窗口未命中/越界、代理异常、缺采样，或业务终态正确但缺 Hosted A 归因日志 | 准备/夹具/证据失败，保留原因与原始数据；状态正确但证据缺失不直接判产品 bug |
| A 获胜，或 T 确认但 A 没有真实 RBF | `scenario_not_acquired`，非零退出，不 skip/xfail，不算恢复通过或产品恢复失败 |
| T 不确认、索引未就绪、运行或链异常 | 本次不能形成完整恢复通过；根据原始链/FNN/进程证据区分环境、夹具或产品故障，不能默认排除产品 bug |
| 场景、精确索引就绪和运行健康已成立，330 秒内没有完整恢复，或恢复后任何样本回退 | 恢复回归失败，区分扫描未触发、查询/识别失败和状态转换错误；保留产品问题候选，不能以“没有扫描成功证据”改成夹具失败 |
| 业务条件及全部证据/完整窗口/稳定期均满足 | 仅本次受控 B 败方关闭识别通过；不宣称无干预竞态概率、A 受控场景、结算取回或整个 PR 已验证 |

归类优先级：场景、精确索引与运行健康已成立后，窗口内未恢复或实测状态回退优先判恢复回归失败，不能因缺少恢复日志改写为证据失败；“缺 Hosted A 日志”单独归证据失败仅适用于业务终态正确的情况。

Gate3 按已确认范围实现 12 的单条 Python 测试与映射（本行改为 `[x]`），保持原 08/10 行及契约。现有手动诊断只复用已核实的低层准备、规范化内容计算与观察方式；其“从 committed 起算、RPC 独立长等待、仅首次与末次成功”的判断不能直接转为正式断言。共享 setup 增加仅用于 12 的分支，因此针对性回归 08/10 各一次；不扩展产品、Rust 驱动或公共框架。

固定验证批次：新用例先聚焦 1 次，再按同一参数串行复跑 3 次，共 4 次，每次使用独立 FNN/SDK/通道状态并保留所有结果；4/4 完整通过才报告本批稳定性验证通过，不推断竞态概率。夹具问题修复后从头重跑固定 4 次并保留旧失败；产品候选失败保存证据交用户，不擅自改产品或反复改时序。当前执行与失败修复记录见 [SPEC-09 Gate3 运行记录](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-spec-09lsp-timeout-12-独立败方恢复2026-10-23)。

2026-10-23 Gate2 文档复核：按用户最新要求由 **GPT 6.1 sol** 独立只读复核，未触发 Daybreak。已修正“缺恢复日志”与“未恢复”归类的优先级歧义，并明确索引 `io_index` 的精确输入核对；最终无阻断项，与已批准 Gate1 无实质冲突。该结论仅针对设计，不是运行结果。

Gate2 当轮检查（历史记录）：`python3 scripts/check_test_map.py` 退出 1，仍报既有 PMP/SETTLE 孤儿映射和历史 report overlay 重复 ID，新增 12 当时保持未映射；`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/channel-signing-deadline.md` 识别 11 条、退出 1，仅报既有重复 ID，SPEC-09 已链接到新行。`git diff --check`、三份文档的新增链接/锚点与空白检查、原 10 行逐字不变检查均退出 0。固定源码 HEAD 为上述 SHA 且工作区干净；当轮未启动节点或执行用例，未修改自动化、产品、驱动或 TEST-MAP。用户随后已通过 Gate2，当前 Gate3 结果另记，不覆盖此历史检查。

## 08/10 的隔离条件、预算与共同断言

仅这两条按本节执行；A/T 仍在同一真实 FNN 中，独立 CKB devnet、真实 SDK、token 与承诺签名不变。不开新通道替换失败，不修改产品/数据库/宿主机时钟，不调用手动强关，不由测试代发承诺。

### 准备与交易识别

1. 注资已确认且通道为 `ChannelReady`、链查询已可读后，暂停本条环境的后台矿工；确认矿工退出且链高连续 1 秒稳定（最多等 5 秒），CKB/FNN/SDK 进程继续运行。暂停期间不调用其他挖块辅助方法。链高稳定不能替代进程退出检查。
2. 正常创建 hold 发票及 SDK 授权，再注入一笔寿命 22 秒、金额 1,000,000 Shannon 的 TLC；读回实际 expiry，固定 `D = expiry - 1333ms`。08 发票保留 90 秒；10 在创建时设 180 秒，从发票返回的实际创建 timestamp 起算，不能从授权完成时间起算或临时延寿。
3. 08 保存检查点 A 的原请求与完整提交；A 当前承诺仍为注入前版本，由该哈希唯一选中的 SDK `complete && !for_remote` 记录不含目标 TLC。SDK 可以另有已签但尚未提交给 FNN 的新记录，不把全部 SDK 记录都要求为“不含目标 hash”。10 先应用承载 TLC 的签名到检查点 B，保存下一份 `SendRevokeAndAck` 请求并扣留；A 当前承诺不同于注入前，对应 SDK 完整记录包含准确目标 hash/expiry，发票为 `Open`。
4. 保存同一目标 funding outpoint。A 当前承诺哈希必须唯一匹配 SDK 的 `complete && !for_remote` 记录；T 当前承诺哈希必须唯一匹配 `for_remote` 记录（不要求 T 记录 `complete=true`）。保存各自规范化签名消息，要求不同；前后读回承诺哈希一致。缺失、歧义、变化或解析失败均为本次准备失败，不降级成“非 A 就是 T”。
5. 启用规则时必须仍有 `armed_at <= D - 5s`，A 仍 `ChannelReady` 且是保存的 `SignatureRequired`，原注资 cell 仍 live，尚无目标关闭广播；否则失败并清理，不调整 expiry 重新等待。10 还须满足 `D + 95s < 实际发票到期时刻`，保证整个观察预算在有效期内。

### CKB RPC 拦截与证据

- 范围只限本条环境中消耗目标 funding outpoint 的 `send_transaction`。A 匹配消息原样转发真实 CKB；T 匹配消息立即返回 JSON-RPC `error.code = -32099`、`error.message = LSP_TEST_COMPETING_COMMITMENT_BLOCKED`，不返回成功 hash、不挂住请求。
- 目标交易若不是已绑定的 A 或 T 内容，或无法解析，记录原始请求并令测试失败，不能按 T 静默过滤。其他交易与读取请求透明转发；测试的链查询和矿工直接使用真实 CKB URL。
- 规则从 armed 持续到本条 FNN 停止；T 的所有匹配重播都立即返回同一个注入错误，每次记录，不要求恰好一次，不因重播重置等待预算。清理时先停止本条 FNN，再关闭拦截器；在失败路径也恢复/清理本条矿工，避免污染下一条。
- **恢复挖块前必须同时取得两项真实证据：** 至少一笔 FNN 自行发出的 A 匹配交易获得真实 CKB 成功响应（返回实际交易 hash），以及至少一次 FNN 自行发出的 T 匹配交易被拦截且未发往真实 CKB；两项均须在 `[D, D + 15s]` 内出现。缺任一项都是本次失败，不能靠测试自发探针、日志声明或重跑替代。
- 保存每次目标发送的原始交易、funding outpoint、规范化消息、分类、接收/转发时间及真实响应；A 转发记录中的实际 hash 用于独立链查询，所有 T 拦截 hash 均不得为实际确认赢家。注入错误与真实 CKB 错误分开记录。

### 有界等待和共同结果

| 阶段 | 起算点与上限 | 必须观察到的结果 |
| --- | --- | --- |
| 截止保护与广播 | 从 D 到 D+15 秒，轮询间隔不超过 0.5 秒 | 截止前无目标强关广播；A 为 `ShuttingDown` 且带 `WAITING_COMMITMENT_CONFIRMATION`，SDK/FNN 仍运行，A 真实接受和 T 实际拦截两项证据齐全；整个阶段无新签名提交或手动关闭 |
| 真实确认 | 从首次 A 匹配交易真正转发到 CKB 起 60 秒，包含等待 T 证据及恢复矿工的耗时 | 两项证据齐全后立即恢复挖块；独立 CKB 查询为 `committed`，交易输入花费保存的 funding outpoint、该 cell 已不再 live；实际确认交易的规范化消息等于 A 完整 SDK 记录，不能是 T 内容 |
| 本地关闭记录 | 从首次独立查询观察到 committed 起最多 15 秒，继续正常挖块供 FNN 确认深度使用 | A 为 `Closed` 且含 `UNCOOPERATIVE_LOCAL`，`shutdown_transaction_hash` 等于实际确认 A hash，当前承诺仍对应保存版本；不要求 T 的关闭 hash 与 A 不同，也不等待 T 收敛 |
| 08 请求清理及晚到提交 | 至迟在上述本地关闭窗口末尾为 `NoSignatureRequired`；保存提交前快照后仅提交一次原签名，单次 RPC 上限 10 秒，收到响应后连续观察 5 秒 | FNN 返回真实 JSON-RPC 错误且没有 Applied；相对提交前快照，请求始终不复活，A 的关闭 hash 与可查询承诺 hash/counter 不变，SDK 完整承诺版本不增加，无另一规范化消息的目标广播；原 A/T 内容的重播不算新承诺 |
| 10 最终发票核对 | 在 A 本地关闭后 5 秒内，且早于实际发票到期 | SDK 完整记录仍包含同一目标 hash/expiry，发票仍 `Open`，全程未释放 preimage、未放行扣留撤销签名 |
| 总上限 | 08 到 D+110 秒；10 到 D+95 秒 | 任一阶段或总预算超时即失败并清理；阶段预算不因重试、重播、重新查询或已出现部分结果而重新起算 |

确认交易内容按已有驱动 `commitment-message` 与 SDK `signing_message` 比对；签名有效性由真实 CKB 接受并确认来证明。原始 hash 仅用于唯一定位一笔实际交易，不要求它等于刷新依赖前保存的 hash。
Gate3 修正了 CKB RPC 的状态表达：固定 0.202.0 随包官方文档（本地材料：`download/0.202.0/docs/rpc.md#type-cellwithstatus`）明确 `dead` 已弃用，`unknown` 包含已不再 live 的 cell。因此后置检查为 `status in (dead, unknown)` 且 `cell=null`；必须同时有准备阶段同一输入为 live、A 的真实交易 committed、确认交易包含该输入及规范化承诺匹配的证据，绝不以 unknown 单独证明花费。五列表中“由 A 指定承诺真实花费原注资”的业务预期未改变。
请求清理允许发生在本地保护成功后、链确认之前；RPC 报错、请求超时或查不到通道都不能冒充 `NoSignatureRequired`。未公开的内部缓冲区不凭日志宣称清空，以晚到提交后的状态与无新承诺副作用验证边界。
快照查询、解析、恢复矿工等操作也计入总预算；每次调用取自身上限与剩余预算的较小值，不能在总截止后另开完整等待。到期立即保留失败并进入有界清理，不因业务预算耗尽跳过环境清理。
本节隔离/时间预算已获人工确认；准备失败、隔离失败、产品断言失败均保留失败证据，不使用 skip/xfail 或“重跑到绿”。

## 共同前提与时间控制

各场景使用独立环境：一条 A–T 私有通道（双方各 500 CKB），真实 SDK 进程与真实 token 始终不变。不引入 MPP、UDT、并发支付、租户驱逐、重启和存储损坏。
下表保留其余原用例的准备依据；08/10 的停矿、广播隔离、22 秒 TLC 和全部等待按上方专节，10 的发票在创建时为 180 秒，其余原行的参数不变。12 独立采用其专节的持续挖块、250 ms 查询响应窗口、600 秒发票和完整恢复预算，不继承这里的 90 秒参数或 08/10 的广播隔离。

| 控制项 | 本批具体约束 |
| --- | --- |
| 开通计时 | 只在承载租户的 FNN 配置里加 `funding_timeout_seconds = 180`、`external_funding_timeout_seconds = 60`，与现有套件改写 `lsp:` 段的做法一致；不改公共模板、`framework/`、`AGENTS.md` 或 `Makefile` |
| 外部注资注入 | 一直不调用 `submit_signed_funding_tx`，或只在中止之后再补签提交；原未签交易、输入与钱包私钥全部保存，用于中止后核对输入仍可用 |
| 通道签名注入 | 转发器按请求暂停 `submit_channel_signature`；需要“晚到提交”时把捕获到的真实提交直连 FNN 提交，不伪造签名、不用缓存响应冒充幂等回执 |
| 开具发票 | 托管租户的 hold 发票用 `payment_hash` 创建（不给 FNN preimage），并把发票自身 `expiry` 设为 90 秒，供 `LSP-TIMEOUT-11` 跨过它再查询；SDK 授权用真实接口登记，`min_tlc_expiry_delta_ms` 取 5000，`expires_at_ms` 覆盖注入时刻，`max_tlc_expiry_ms` 大于 `expires_at_ms` 且不小于注入 expiry；金额 1,000,000 Shannon |
| 单笔 TLC 注入（检查点 A、B） | 原准备使用操作员客户端调用 `dev_add_tlc`，`expiry` 取注入时刻加 22～25 秒，使 D 约为加 21～24 秒；实际 expiry 必须从 A 的 TLC 列表读回并保存。08/10 固定为 22 秒，不再用“少于 30 秒”排除 T 的截止保护 |
| 两笔 TLC（检查点 C） | TLC-A 用较长 expiry（例如注入 A 时刻加 60 秒）留足完成其 ACK 往返的时间，TLC-B 用 22～25 秒决定 D；两笔各有独立 hold 发票与独立授权、互不相同的 payment hash；全程不释放任何 preimage。D 取两笔中较早的 expiry 减 1333 毫秒 |
| 准备检查（检查点 A） | 注入后必须同时满足：目标 TLC 出现在 A 的 TLC 列表、A 出现承载 TLC 的待签请求（保存请求 ID 与完整内容）、距 D 仍有足够余量。此时不要求发票为 `Received` |
| 准备检查（检查点 B） | 必须同时满足：承诺哈希已变化、SDK 记录中该版本承诺完整签署且含目标 TLC、下一份待签请求已出现并被扣住、发票仍为 `Open`。任一不满足算准备失败，不算用例结果 |
| 准备检查（检查点 C） | 必须同时满足：发票 A 为 `Received`、TLC-A 在最新已签承诺中、此时没有任何待签请求；随后 TLC-B 到达检查点 B。任一不满足算准备失败 |
| D 与归因 | D 等于相关 TLC 中最早的 expiry 减 1333 毫秒（debug 构建 2 秒每 epoch、2/3 承诺延迟预留）。08/10 按上方广播隔离与规范化内容核对归因；其他原行中的 30 秒与原始哈希要求本轮未修订，不据此证明当前版本已排除对端竞争 |
| 有界等待 | 等待 D 用墙上时间；越过 D 后最多再等 15 秒观察保护启动；链上确认按挖块推进并逐阶段检查，不超过 60 秒；`LSP-TIMEOUT-11` 另等到发票 90 秒有效期之后，再加 5 秒稳定观察。到点未出现目标事件即失败 |
| 不做的事 | 不修改宿主机时钟，不篡改数据库或 SDK 存储，不重开通道或重放支付换取通过，不放宽既有 16 条的参数与断言 |

`LSP-TIMEOUT-07`、`10` 共用检查点 B；`LSP-TIMEOUT-08` 停在检查点 A；`LSP-TIMEOUT-11` 使用检查点 C；`LSP-TIMEOUT-06` 是夹具对照，负责证明 A 到 B 到 `Received` 的三段转移都能真实到达。

## 场景展开

以下保留原有十行的操作顺序；本批新增 12 的完整步骤及断言已在上方专节展开，Gate3 已接入映射。

### LSP-TIMEOUT-01：外部注资超期必须中止

1. 走 SDK 开通，确认双方进入外部注资等待、拿到未签注资交易并保存其输入。
2. 不提交任何钱包签名，等到越过 `external_funding_timeout_seconds`。
3. 用 `list_channels(only_pending=true)` 在 A 与 T 两侧查询失败条目与标志；查询该注资交易与每个输入，确认链上没有注资交易、输入仍可用。

### LSP-TIMEOUT-02：中止后晚到提交不能复活

1. 在 01 的终态上，用保存的钱包私钥补签原未签交易。
2. 调用 `submit_signed_funding_tx`，确认被拒绝且没有新的注资交易或通道。
3. 再查一次双方失败条目、通道数量与输入，确认没有变化、输入仍未被花费。

### LSP-TIMEOUT-03：旧计时器不能误中止

1. 在外部注资期限内提交有效注资交易，然后在第一个待签通道签名处暂停提交。
2. 等到越过原外部注资期限（配置 60 秒）、但仍在普通开通期限（配置 180 秒）内，确认通道没有被中止。
3. 放行签名与后续转换，等待双方 `ChannelReady`，核对 `channel_outpoint` 与本次注资交易一致。

### LSP-TIMEOUT-04：普通开通期限中止，且注资未上链

1. 在钱包提交完成、通道停在允许安全中止的开通阶段时，扣住后续通道签名。
2. 等到越过普通开通期限，用 `list_channels(only_pending=true)` 在双方确认失败条目与 `FUNDING_ABORTED` 标志。
3. 查询注资交易哈希与输入，确认从未广播、输入仍可用。

### LSP-TIMEOUT-05：开途中止后的晚到通道签名

1. 在 04 的终态上，提交此前保存的真实通道签名。
2. 确认不返回 `Applied`、没有新的承诺交易。
3. 再查失败条目、通道数量与输入，确认没有复活、也没有注资；原状态对象已删除，因此不以承诺号或承诺哈希作为证据。

### LSP-TIMEOUT-06：夹具对照，证明三段转移都可达

1. 在租户侧用 `payment_hash` 创建 90 秒有效期的 hold 发票，并用真实 SDK 接口登记发票授权与 preimage（preimage 只留在 SDK）。
2. 由公共节点注入 TLC，完成检查点 A 的准备检查：目标 TLC 出现、待签请求出现、距 D 有余量；记录此时发票为 `Open`。
3. 放行这份签名，等下一份待签请求出现并扣住，完成检查点 B 的准备检查：承诺哈希变化、SDK 记录含目标 TLC、发票仍为 `Open`。
4. 放行被扣住的撤销签名，等到 ACK 往返完成：确认发票变为 `Received` 且不再有待签请求。
5. 本行到此为止；之后 TLC 在活跃通道上到期失败的处理属于另一条路径，不在本批断言。

### LSP-TIMEOUT-07：窗口内签名、越过 D 再提交

1. 在检查点 B 保存被扣住的撤销签名、完整内容、承诺哈希与 T 发出承诺签名的时间。
2. 等到实际时间超过 D 加 1 秒，直连 FNN 提交这份签名；确认提交时刻仍在 T 发出承诺签名后 30 秒以内。
3. 确认没有被应用、承诺号与承诺哈希不变，A 进入等待承诺确认的关闭状态。若周期维护已经先触发关闭，同样记为通过，只要求最终进入截止保护而不是由这次提交触发。
4. 比对链上关闭交易与保存的承诺哈希，确认是 A 侧强关；确认待签请求在强关成功后被清理。

### LSP-TIMEOUT-08：无人提交时维护自行保护

1. 通道就绪及注资确认后停本条矿工，完成上方准备检查；保存注入前 A 的完整承诺。注入 22 秒 TLC 并停在检查点 A，原通道签名只保存在测试侧，尚未交给 FNN；由 A 当前承诺哈希选中的 SDK 完整本地记录不得含目标 hash，其他尚未提交的 SDK 记录不受此断言约束。
2. 唯一绑定双方承诺及注资输入，至少 D 前 5 秒启用规则；确认 A 仍就绪、原请求仍为待签。之后直到关闭确认前，不提交任何签名、不手动强关、不重启，不代发 A/T 交易。
3. 在 D 后 15 秒内同时取得 A 的保护状态、A 匹配旧承诺被真实 CKB 接受、T 匹配承诺实际被拦截的证据；截止前目标关闭广播、未知交易、缺少任一项均失败。
4. 两项广播证据齐全后恢复挖块；从 A 首次真实转发起 60 秒内确认 A 交易，核对规范化消息等于保存的完整旧承诺、原 funding 被它花费且 cell 已不再 live。再在 committed 被观察到后 15 秒内核对 A 的 `Closed/UNCOOPERATIVE_LOCAL`、实际关闭 hash 和保存承诺版本。
5. 明确读到 `NoSignatureRequired` 后，保存 FNN 状态与 SDK 记录快照，只直连真实 FNN 提交一次原扣留签名（RPC 上限 10 秒）；必须得到真实 JSON-RPC 错误，不出现 `Applied`，不能以连接失败或超时冒充拒绝。
6. 收到响应后连续 5 秒观察，相对提交前快照：仍无待签请求，A 本地关闭状态、承诺版本及 hash、实际关闭 hash 不变，SDK 完整承诺版本不增加；无新的目标承诺内容被广播。原 A/T 交易重播沿用转发/拦截规则，不当作新承诺。总观察截止为 D+110 秒。

### LSP-TIMEOUT-10：强关承诺确实带目标 TLC

1. 通道就绪及注资确认后停本条矿工，创建 180 秒 hold 发票；完成上方准备检查并注入 22 秒 TLC。记录注入前承诺，放行承载 TLC 的签名进入检查点 B，扣住下一份 `SendRevokeAndAck` 提交且全程不再放行。
2. 确认 A 当前承诺不同于注入前，唯一完整 SDK 记录包含准确目标 `payment_hash` 与读回 expiry，发票为 `Open`；至少 D 前 5 秒绑定双方规范化消息并启用规则，验证实际发票期限覆盖 D+95 秒。
3. 在 D 后 15 秒内取得 A 保护状态、A 的含 TLC 承诺真实被 CKB 接受，以及 T 的已识别竞争承诺实际被拦的证据；无人工强关、代发交易或 preimage 释放。
4. 恢复挖块，在 A 首次真实转发后 60 秒内确认同一 A 交易，验证 funding 输入及该 cell 已不再 live，规范化消息匹配检查点 B 的完整 SDK 记录且区别于旧承诺。保留全部真实 CKB 响应，不能只凭广播成功断言通过。
5. committed 被观察到后 15 秒内，A 应为 `Closed/UNCOOPERATIVE_LOCAL` 且关闭 hash 指向实际确认交易；在本地关闭后 5 秒内、实际发票到期前再次查询为 `Open`，SDK 保存记录仍准确含目标 hash/expiry，扣留撤销签名从未放行。总观察截止为 D+95 秒，不断言链上取回或真实付款终态。

### LSP-TIMEOUT-11：不交 preimage 且发票已 Received 的终态

1. 先完成 TLC-A：注入后按出现顺序放行它的承诺签名与撤销签名，等到 ACK 往返完成，确认发票 A 为 `Received`、TLC-A 在最新已签承诺中、没有待签请求。
2. 再注入 TLC-B（独立发票与授权），停在它的检查点 B，扣住撤销签名不再提交；此时 D 由 TLC-B 的 expiry 决定。
3. 让保护在 D 触发，取得广播的关闭交易并确认：交易含 TLC-A 的版本已完整签署，原注资输出被它花费。
4. 确认时查询发票 A，确认不是 `Paid`、为 `Received`；等到越过发票 A 自身 90 秒有效期后再查一次，确认仍为 `Received`。
5. 查询双方余额与锁定额，确认没有成功收入、锁定额未被当成已结算、没有第二次结算。

## 本批不覆盖的缺口

- **自然竞争的剩余边界**：原 60 秒失败及 08/10 的广播隔离通过均不能单独排除产品恢复缺陷。A 自然样本与 B 受控样本已有恢复证据，本批 B 受控恢复 12 已取得独立的固定 4/4 通过，实际运行另记；B 无额外时序控制的 T 胜出样本、竞态概率以及 A 受控方案仍不在本批。不能把关闭识别误写为链上结算、资金取回或所有竞态均已验证。
- **SDK 对过期请求的拒签**：到 D 之后节点可能已经强关并清掉待签请求，此时扣住状态查询再放行，SDK 看不到请求，自然不会提交；即使 SDK 没有期限校验，这样的用例也会通过。要真正验证，必须证明 SDK 收到了目标过期请求并因期限拒绝签名，而 SDK 的最后可签时刻只比 D 早不足 1 秒、节点最多再 3 秒就清理请求，集成层无法稳定命中这个窗口。该行为继续由 SDK 的 Rust 测试证明，本批不写这一行（原 `LSP-TIMEOUT-09`）。
- **链上取回与付款最终失败、金额解锁、链上费用承担方核对**：需要 Hosted watchtower 或链上花费授权，而本地驱动只接入 `open`、`invoice`、`fulfill`、`close`、`records`、`opening`，SDK 会按无授权拒绝签名。上游 agent 在同 SHA 已有相应入口，接入后需重新构建同 SHA 驱动并更新清单摘要。
- **付款方 P 一侧的资金解锁**因此不在本批断言；`LSP-TIMEOUT-11` 只断言收款侧可观察到的发票与记账结果。
- 精确到期那一毫秒、维护与提交的严格执行顺序、全部签名转换组合、撤销惩罚与恶意 watchtower 授权，仍由可控的 Rust 测试证明。

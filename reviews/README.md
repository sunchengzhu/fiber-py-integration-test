# Fiber 网络集成测试区域图

当前84333ee专项已带已知问题收尾。新会话先读[LSP收尾结论与有限后续](../test_cases/fiber/devnet/lsp/README.md#84333ee-收尾结论与新会话入口2026-10-31)，下方历史计划不作为当前启动授权。

2026-10-30整体盘点已核原始JUnit及退款最终证据：固定843为47通过、2个产品失败、25个无该版本结果（74个既有LSP ID口径）。DELIVERY当前5/6通过，退款按用户接受的两轮方案完成；下文40/74、DELIVERY 1/6等为早期批次历史。无843结果不等于从未执行：19个是旧版本回归，2个沿#1674待修，取消02被已知入口缺陷阻断，另3个待产品能力/契约且未实现。见[当前运行汇总](../test_cases/fiber/devnet/lsp/README.md)。普通订阅8ID/11方法重新评审的草稿暂缓，下一步应选真正未覆盖行为，不新增同义用例或重复夜跑。

本文标为“本地证据”的路径均相对仓库根目录；原始报告保留在本机 `report/`，不随 Git 提交或推送。其他会话可先读已提交的 [LSP 运行说明](../test_cases/fiber/devnet/lsp/README.md)，需要原始日志时再到本机按路径核对。

第二批接纳一致性的[Gate2六行、触发方案、资金断言与预算](lsp/delivery-acceptance-consistency.md)已获用户明确确认，固定84333ee；`LSP-DELIVERY-01～06` 均有 Python TEST-MAP。第七批01取得原调用超时后接纳的安全失败样本但未过终态，第八批正常对照因逐K采样缺口停止，均保留历史失败。第九批正常资格及正式01通过；正式02在同进程actor薄包装受控丢弃接纳回复后，出现原K上游失败而同K下游成功的产品一致性失败，于早期断言停止，正式最终资金与30秒稳定未运行；03～06未运行，正式通过 **1/6**。见[第七批](../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第七批01终态判据未过2026-10-30)、[第八批](../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第八批逐k完成采样缺口停批2026-10-30)和[第九批运行记录](../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第九批01通过02产品一致性失败2026-10-30)。固定843独立通过 **40/74**、有映射 **71/74**；映射不等于通过。新02失败不归入旧#1674/#1706，退款夜跑结论不变。

LusoCryptoLabs 报告的第三项“租户不能取消自己的发票”已补为[Hosted 发票取消 Gate2 三行](lsp/hosted-invoice-cancellation.md)：自己 Open 发票取消、跨租户隔离、Received hold invoice 取消后的资金收尾。01/02 已建立 TEST-MAP；固定843的01单次诊断以真实A tenant token创建hash-only Open发票后，`cancel_invoice` 返回 `-32999 Unauthorized`，节点明确指出租户白名单缺该方法。旧付款资金与新付款后半步骤未执行，02未运行；03的Received契约待产品明确，未映射。见[取消运行记录](../test_cases/fiber/devnet/lsp/README.md#84333ee-hosted租户发票取消真实入口拒绝2026-10-30)。

2026-10-29 新增[实测反馈与相邻风险 Gate1](lsp/field-feedback-scope.md)：二十个候选方向，涵盖独立收款归属、actor 接纳超时、租户取消发票、缺授权 TLC 收尾、注册规模及 SDK 长期状态。Gate1已获确认；方向1/2已展开为[watchtower Gate2](lsp/watchtower-settlement.md#独立收款与目的地替换gate22026-10-29)：补强01、新增05/06，02澄清历史引用；行集/费用/预算已确认，Gate3当前实现05；旧01过时映射移除，01/06等待修复版。前次Gate3因05证据schema缺陷主动停批的证据保留；修正后经用户重新授权，843独立构建、自检、旧02一次与05单次均通过，总耗时570.293秒。05仅证明SDK sponsor约束拒绝，独立到账仍未验证，见[最新LSP运行记录](../test_cases/fiber/devnet/lsp/README.md#84333ee-独立收款诊断-gate3修正后单次批次完成2026-10-29)。旧 watchtower 批次预先批准 T/sponsor 钱包，因此证明已批准交易的签名和守恒，不能证明资金回到独立用户钱包；新范围优先补这个判据缺口，不抹去 #1706 的有效修复证据。

上一轮完整已执行基线：FNN/SDK `4028884`，测试仓库基于 `v0.10.0 / 6088115`；已有 16 条核心用例已全部回归通过，见 [运行说明](../test_cases/fiber/devnet/lsp/README.md)。
`24b5c38` 签名订阅迁移批次：[已通过的 Gate1 范围](lsp/signing-subscriptions-scope.md)、[已确认的 Spec、测试树与用例表](lsp/signing-subscriptions.md)。原事件 01～07改造为 LSP-SUBSCRIPTION 前缀，旧 08/09 已删除；该版本已同源构建并完成 Gate3 实现：核心 16 条与订阅 14 条全部通过；当轮完整 LSP 40 条为 38 通过、2 失败。普通开通计时器缺口及旧强关夹具竞争风险见 [运行记录](../test_cases/fiber/devnet/lsp/README.md)，历史通过不转记。

当前新增范围为固定 `04c2064` 的 [浏览器鉴权 Gate2](lsp/signing-subscriptions.md#浏览器鉴权-gate2共同断言输入与预算04c2064)，14～19六行及预算已获用户确认，Gate3已实现并完成正式1+3共44/44、相关旧14/14回归，GPT6.1 sol复核通过，见 [浏览器鉴权记录](../test_cases/fiber/devnet/lsp/README.md#04c2064-浏览器鉴权-gate32026-10-26)。现有 Bearer 14方法已在04通过，见 [运行记录](../test_cases/fiber/devnet/lsp/README.md#04c2064-websocket-既有订阅回归与下一步2026-10-26)。旧事件传输仅保留为 [4028884历史范围](lsp/legacy-signing-events-scope.md)，不代表当前协议。

订阅过滤20～28的[Gate1](lsp/signing-subscriptions-scope.md#2026-10-28过滤参数补充-gate1)及[Gate2行集/数组兼容/预算](lsp/signing-subscriptions.md#过滤参数-gate2输入断言预算与最小适配04c2064)已获确认，12方法与TEST-MAP已实现。用户进一步授权更新LSP分支后，固定 `84333ee` 独立构建并完成相关3/3及正式1+3共48/48；04缓存准备失败保留历史，详见[最新运行记录](../test_cases/fiber/devnet/lsp/README.md#84333ee-订阅过滤-gate3完成2026-10-29)。同身份多通道严格子集仍是覆盖缺口。

**已知问题入口：** `LSP-TIMEOUT-04/05` 的普通开通计时器缺口已由
[Fiber #1674](https://github.com/nervosnetwork/fiber/issues/1674) 跟踪，2026-10-23 核实时为 Open；
`24b5c38` 的两轮回归仍可复现。新会话先读 [既有归因与日志](../test_cases/fiber/devnet/lsp/README.md#已知问题关联1674)，
相同版本和失败特征沿用该 issue；目标版本或现象变化时先核对修复与差异，再决定针对性验证，避免重复建 issue 或从头定位。

[真实付款的延迟签名恢复](lsp/delayed-payment-recovery.md)展开 `LSP-PAYMENT-01～03` 的完整用例、时间预算和共同断言；[Gate1](lsp/hosted-channel-guards-scope.md)的在线延迟、SDK 完全离线、A 等签时 B 收款三个方向已获用户确认。固定 `24b5c38`，跨普通 ACK 的 30 秒阈值并保留业务安全余量；用户已明确通过三行、预算与共同断言，2026-10-24 进入 Gate3；Python 自动化及 TEST-MAP 已接入，冻结后聚焦一轮与固定三轮合计 12/12 通过，首轮断言补齐与全部执行、复核记录见[运行记录](../test_cases/fiber/devnet/lsp/README.md#24b5c38真实付款延迟签名恢复2026-10-24)。2026-10-23 核实 PR HEAD 为 `04c2064`，相对固定基线新增浏览器 WS 认证及 token 编码调整，未把旧结果转记为新 HEAD 通过。反向开通仍为候选；下文旧版本分析保留历史依据。

上一批 [SPEC-09：LSP-TIMEOUT-12 完整用例、预算与断言](lsp/channel-signing-deadline.md#lsp-timeout-12检查点-b-独立败方恢复)：[Gate1 范围](lsp/channel-signing-deadline-scope.md#spec-09-独立败方恢复回归gate1-范围)及 Gate2 均获用户确认，基于 `24b5c38`，仅 B 的受控查询时序恢复，保留真实 T 获胜/A RBF、精确索引就绪及完整扫描窗口。Gate3 的 Python 测试及 TEST-MAP 已接入，修复后聚焦与固定 3 次复跑 **4/4 通过**，相关 08/10 回归 **2/2 通过**；初始夹具失败、全部运行结果及独立复核见 [SPEC-09 记录](../test_cases/fiber/devnet/lsp/README.md#24b5c38-spec-09lsp-timeout-12-独立败方恢复2026-10-23)，历史诊断不转记为本条通过。

`LSP-TIMEOUT-08/10` 的 [稳定性改造 Gate1](lsp/channel-signing-deadline-scope.md#0810-稳定性改造范围)与 [Gate2 完整用例及断言](lsp/channel-signing-deadline.md)均已获用户确认，本轮 Gate3 已完成。Python CKB RPC 门禁隔离 T 的竞争广播，仍要求 A 指定承诺真实确认；聚焦加固定 3 轮复跑共 8/8 通过，GPT 6.1 sol 独立复核无阻断项，原始失败与修正见[运行记录](../test_cases/fiber/devnet/lsp/README.md)。后续[自然竞争独立诊断](../test_cases/fiber/devnet/lsp/README.md#24b5c38-自然竞争后的恢复诊断2026-10-23)已证实检查点 A：T 真实确认、A 真实 RBF 后约 264.6 秒通过 Hosted 扫描恢复，完整观察 331.8 秒；B 三次无额外时序控制的尝试均由 A 获胜。[B 的受控查询时序续查](../test_cases/fiber/devnet/lsp/README.md#24b5c38-检查点-b-的竞争与恢复诊断续查2026-10-23)取得 T 真实胜出、A 真实 RBF，并在确认后约 261.8 秒观察到 Hosted A 恢复，完整观察 330.7 秒。这个结果证明所取得的 B 路径能收敛；250 ms 时序控制不证明无干预竞态的概率，也不覆盖链上结算及资金取回。

Hosted LSP 区域依据 `nervosnetwork/fiber#1623`；上方超时诊断与当前签名订阅回归使用固定 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`。
下述历史维护分析的目标版本是 `8419c005e2d0e737c5abf7e0f881aaedbc6fd300`（2026-10-19），当时测试仓库基线为
`852c97daeb41b9b3824dae184d4952ddad1069d1`。
本批构建使用干净源码 `download/fiber/source-pr-1623`，FNN、SDK agent 和测试驱动同 SHA；不代表完成整个 PR 的逐行审查。
上轮实际验证版本为 `0f41d9a`。下文与子文档的旧 SHA、当时的环境和范围分析保留原评审依据，不代表新版执行通过；本轮维护说明和实际结果见 8419c00 验证记录（本地证据：`report/lsp-8419c00/result.md`）。
已有隔离、提交重试评审依据仍对应 `774e61bbe54b8ab335b235458d14df2f8feea23d`；新版主流程初始分析对应 `4eb4f5e`。
以下旧 SHA 链接保留原依据；`412b254` 的开通入口适配见“当前版本变化与既有测试的关系”。

本文档用于确定测试范围和评审入口，不记录批准状态或自动化状态。

当前 Python 通过项、未解决问题、待回归及未覆盖项见
2026-10-20 功能测试汇总（本地证据：`report/lsp-python-status-20261020/summary.md`）。
2026-10-24 用户批准切至 `04c2064`；最小兼容回归 `LSP-RECOVERY-01` / `LSP-SUBSCRIPTION-02` 共 2/2 通过，原 `24b5c38` 产物与历史结果保留，详见[新版运行记录](../test_cases/fiber/devnet/lsp/README.md#04c2064-最小兼容回归2026-10-24)。[Hosted watchtower Gate1](lsp/watchtower-settlement-scope.md) 三个方向已获用户确认，[Gate2 四条完整用例、预算与资金断言](lsp/watchtower-settlement.md) 及 02 分段边界已获确认，现已进入 Gate3 并建立四条映射。原合约字节阻断已于 2026-10-27 在用户批准的隔离链中修复。修正后自检及聚焦 4/4 通过，首轮固定复跑 3 通过/02 失败，后两轮未运行；后续独立诊断已确认 FNN 产品 bug：旧首项遮蔽已通过 SDK 校验的新请求，显式批准后完整 240.356s 仍未恢复，详见 [最新归因与证据](../test_cases/fiber/devnet/lsp/README.md#04c2064-watchtower-02-陈旧请求遮蔽与批准后恢复诊断2026-10-27)。02 不计原 Agent 自动恢复覆盖；单租户暂停和 SDK 掉线另批保留。

2026-10-28 修复定点验证：固定 `3ce369e5c4b224638817ab99aec8c3e0fcb85d3a` 的适配自检及普通 watchtower 四条单轮共 **5/5 通过**，02 已取得 `R0<R1` 的原遮蔽条件并完成结算。详见 [修复版本记录](../test_cases/fiber/devnet/lsp/README.md#3ce369e1706-修复定点验证2026-10-28)；不转记为 04、当前 PR head 或完整 1+3 通过。


| 区域 | 职责 | 边界 | 入口 | 可观察结果 | 评审文档 |
| --- | --- | --- | --- | --- | --- |
| 通道签名请求的租户隔离 | 隔离租户的签名查询和提交 | 两个租户各开通一条私有通道；沿用首批范围 | 租户 Biscuit、签名查询/提交、通道查询 | 本租户能签名；跨租户操作失败；原请求保持不变；双方通道就绪 | [通道签名请求的租户隔离](lsp/channel-signing-isolation.md) |
| 通道签名的重试与恢复 | 在重复请求、连接中断、进程重启和超时后保持签名及业务状态一致 | 覆盖私有通道开通、单笔支付更新、协作关闭的相关签名阶段；超时涉及的安全强关纳入分析；完整 watchtower 专项另行分析 | 所属租户的签名 RPC、SDK 存储、FNN 生命周期、通道及支付/发票查询、CKB 交易 | 能恢复时继续原流程，不能恢复时明确拒绝并进入正确终态；不重复应用、不丢请求、不重复扣款或结算 | [提交重试与短暂断线](lsp/channel-signing-retry.md)；其余两组见下文 |
| Hosted watchtower 签名与结算 | 强关后由所属租户 SDK 批准签名并完成结算 | 首批限无 pending TLC、A 非零份额的私有 CKB 通道；结算到事先批准的 LSP 费用钱包，尚不证明租户自托管取回 | watchtower 事件、租户查询/提交、SDK 本地授权与独立链验证、CKB 交易 | 正常授权结算；原 Agent 拒签及批准后适配结算（仅分段证据）；跨租户读取和提交被拒绝 | [Gate1 范围](lsp/watchtower-settlement-scope.md)、[Gate2 用例](lsp/watchtower-settlement.md) |

## 通道签名的重试与恢复：Gate1 范围分析

这轮整体分析一个流程：**节点要求签名后，遇到重复发送、掉线、重启或等待过久，
能否继续完成原来的开通、支付或关闭；如果已经不能继续，是否正确终止并处理资金。**
重复提交只是其中一部分。本节梳理范围、已有覆盖、测试条件和分批方式；具体用例从下文 Gate2 入口评审。

### 先区分“在哪一步出问题”

正常流程是：节点保存待签请求 → SDK 生成并保存签名 → 节点应用签名 → 继续通道协议。
故障发生的位置决定恢复方式，不能把所有中断都当成同一种“重试”：

| 中断位置 | 需要回答的问题 |
| --- | --- |
| 节点已经要求签名，客户端尚未完成签名 | 恢复连接或进程后，是否仍能取到同一个请求和完整内容？ |
| SDK 已签好，但节点还没收到 | 使用原 SDK 存储恢复后，能否继续提交这份签名，而非重新创建租户或通道？ |
| 节点已经应用，但客户端没收到结果 | 客户端能否确认处理进度或安全重试，避免重复应用？ |
| 节点已等待下一份签名，却收到上一份提交 | 是否保留当前请求，正确处理原样重试、冲突内容和过旧请求？ |
| 等待签名已跨过适用的业务截止时间 | 晚到签名是否被正确处理，通道及相关支付是否进入一致的终态？ |

### 四类风险统一纳入分析

| 分析方向 | 本轮考虑的范围 | 观察重点 |
| --- | --- | --- |
| 提交与重试 | 最近已应用签名原样重试；同请求 ID 的内容冲突；结果已被下一次应用替换；请求未送达与结果未送达 | 区分首次应用、已应用和明确拒绝；当前待签内容及稳定业务状态不被错误推进 |
| 签名端断线与重启 | SDK 到 LSP 的 HTTP 连接中断再恢复；SDK 进程在待签或已签未提交时退出，用同一存储重启 | 租户身份、token、通道绑定及签名材料保留；原流程继续，不能靠重建通道掩盖恢复失败 |
| FNN 重启与通道恢复 | 整个 Hosted LSP 所在 FNN 退出并使用原数据重启；分别观察待签状态和已应用结果的恢复 | 原请求及提交结果记录恢复，租户运行时能重新激活，协议继续；签名恢复之后仍检查业务终态 |
| 超时与晚到签名 | 区分 HTTP 请求超时、开通阶段注资超时、支付 TLC 的签名安全截止时间；比较截止前恢复与截止后处理 | HTTP 超时后查明实际应用结果；仍可中止的注资超期后中止；TLC 安全截止后拒绝新签名并尝试强关，成功才清理请求；具体时间控制及预期见下文 |

“断线”首先指移动签名端与 LSP 的 HTTP 连接。租户与公共 LSP T 使用
[进程内传输](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/runtime.rs#L116)，
不能用普通 `disconnect_peer` 冒充签名端掉线。对外普通 Fiber 节点的 P2P 重连是另一个观察点。
租户驱逐也不等于整个 FNN 重启；本轮将其作为已有覆盖的参照，不展开容量、调度和多租户驱逐矩阵。

### 看整个签名流程，不穷举所有故障组合

| 业务阶段 | 涉及的签名步骤 | 恢复成功不能只检查什么；还需要检查什么 |
| --- | --- | --- |
| 私有通道开通 | 发送承诺、完成对端承诺：`SendCommitmentSigned`、`CompleteReceivedCommitment` | 不只看一次提交成功；还要看原通道在双方就绪，通道身份和注资对应关系保持一致 |
| 单笔支付进行中 | 上述承诺步骤，以及发送/完成撤销确认：`SendRevokeAndAck`、`CompleteReceivedRevokeAndAck` | `ChannelReady` 在支付前后都可能存在；还要看原支付/发票终态、TLC 清理、双方余额变化与一次业务结果相符 |
| 协作关闭 | 关闭签名：`SendClosingSigned` | 不只看关闭 RPC 返回；还要看原通道关闭、关闭交易确认，以及对应的资金结果 |
| 触发安全强关 | 有未处理完的 TLC，签名等待超过其安全截止时间 | 不只看 `ShuttingDown`；还要看使用哪份可用承诺、交易是否确认、TLC/支付如何结束；最终结算需要联合链上处理验证 |

Gate2 按差异选择代表性检查点，不机械地把每种故障乘以每个签名步骤。
支付用于验证签名恢复后的结果，只建立必要的普通节点—公共 LSP—租户路径，不扩展路由、MPP 或离线投递的完整矩阵。
公共通道公告签名、移动端 Auto/Manual 审批策略、存储损坏或丢失、断电时的文件落盘原子性、
多进程争用签名存储，以及高并发压力不在当前范围。
完整 watchtower 授权、撤销惩罚和 preimage 专项仍单独评审；本范围不能仅凭通道关闭就声称它们已覆盖。

### 已核实的实现边界

- **去重不是永久保存所有历史结果。** [签名上下文](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-types/src/channel_signer.rs#L541)
  只保存最近一次已应用结果。它比较请求 ID、部分签名和下一轮公开材料；完全相同返回已应用，
  同请求 ID 但结果不同则拒绝。下一条请求待签时仍能识别上一条重试，但下一条应用后会替换旧记录。
  对更早提交，应根据当前待签状态核对拒绝语义，不能一律期待 `AlreadyApplied`。
- **节点和 SDK 各自有需要恢复的状态。** [节点应用流程](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L2266)
  在继续协议前持久化已应用结果；[通道恢复](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L4984)
  会重新交付原待签请求。Hosted 租户的只读签名查询可直接读存储，
  [提交使用的租户运行时按需激活](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/service.rs#L418)，
  所以“能查到请求”还不等于“恢复后能继续执行”。
- **签名端应使用原存储恢复。** [SDK 签名实现](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lsp-sdk/src/signer.rs#L489)
  记录已签内容；[agent 文件存储](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/fiber-lsp-sdk-agent/src/store.rs#L13)
  保存每次变更，[agent 启动](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/fiber-lsp-sdk-agent/src/agent.rs#L312)
  恢复 RootKey、租户 token 和通道绑定。需要在真实进程退出后验证这些能力，不能只新建一个 SDK 对象。
- **三种超时不能混为一谈。** agent 的 HTTP 请求超时为 10 秒，只表示客户端没有得到结果；
  开通阶段受 [funding timeout](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L11433)
  和“是否仍可中止注资”的条件约束；有未完成 TLC 时，[签名安全截止时间](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L6337)
  为相关 TLC 到期时间减去承诺延迟的安全预留，适用于就绪/关闭中的特定状态。
  不是给所有签名请求统一设置一个几秒钟的倒计时。
- **晚到签名与维护任务都可能触发保护。** [提交入口检查截止时间](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L2232)，
  [周期维护也检查](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L4239)。
  [超期处理](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L3328)
  先尝试安全强关，成功后才清除待签请求。拒绝晚到签名和清理状态都需要观察，不能只等待一个错误字符串。

### 异常在什么时候注入、持续多久

PR 新增的[设计文档：等待签名时的 TLC 安全截止时间](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/docs/notes/hosted-lsp-remote-signer.md#L549)
明确规定了截止算法、晚到提交、强关和请求清理行为。下面把产品时间规则与测试控制参数分开；
故障持续几秒由测试选择，不能把它当成产品统一的“签名超时”。

| 时间规则 | 从哪里起算、何时到期 | 对测试控制的约束 |
| --- | --- | --- |
| agent HTTP 请求超时 | 每次 HTTP 调用开始后 10 秒；见 [agent RPC](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/fiber-lsp-sdk-agent/src/rpc.rs#L67)；这是测试 agent 的配置，不是所有 SDK 使用方的统一要求 | 短暂断线与真正 HTTP 超时分开；后者保持响应不可见、不主动关闭连接，观察客户端自然超时后的下一轮查询，并查明节点是否已应用。具体场景以事件推进，等待上限用于发现卡死 |
| 开通注资超时 | 普通路径从通道创建起算，默认 24 小时；等待外部签名注资交易时从该等待阶段开始，默认 5 分钟。见 [配置](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/config.rs#L94)及[适用条件](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/channel.rs#L11433) | 测试通过已有配置缩短适用超时，并保存起算点；普通 funding timeout 不是从断线或签名请求产生时重新计时。已发出注资签名、不能安全中止时不能期待超期即撤销 |
| 有未完成 TLC 的签名安全截止时间 D | 对所有移除尚未确认的 TLC，取 `expiry - 安全预留` 的最早值，减法最低为 0；安全预留为承诺延迟对应时间的 2/3。`now >= D` 即到期 | 读取实际 TLC expiry，保留实际通道承诺延迟配置，计算 D；包含尚未签入承诺的更新。当前 debug 构建每 epoch 按 2 秒换算，不能套用 release 的 4 小时；也不能从“断线已持续几秒”推断到期 |

故障注入点先用状态锁定：待签/未送达场景先取得并保存原 `SignatureRequired`；响应丢失场景则先确认
上游已应用，再扣住响应。SDK/FNN 重启同样在明确检查点发生，并保留原数据。记录实际注入、恢复、提交时间及 D。

- **截止前恢复**：先确保 D 前的剩余时间覆盖故障事件等待、恢复提交及后续协议；观察到预定故障和恢复事件后立即推进，不固定断线秒数。
  重启场景要为实际启动、RPC 可用、租户激活和支付继续处理配置更长有效期；
  如果恢复时已越界，该轮不能算“截止前恢复成功”。支付成功场景还必须满足正常的剩余有效期校验。
- **截止后保护**：保持签名阻塞直到实际 `now >= D + 1 秒`，再观察保护或提交原签名；1 秒是测试避开边界抖动的余量，
  产品在 D 当刻就拒绝。自动保护场景保持 FNN/通道运行，以有界轮询等待维护处理；当前 dev 维护周期为 3 秒，
  拟用越过 D 后 15 秒作为保护启动的观察上限，超限即失败，不无限重试。该上限不代表链上结算也须在 15 秒内完成。
- **提交和维护的先后**：Python 不承诺精确控制同一毫秒的竞态；晚到签名在维护前到达时必须自行触发检查，
  维护先处理时也不能再恢复已放弃的流程。精确相等及两种严格顺序已有 Rust 可控时间测试，集成层检查实际可观察结果。
  FNN 停止期间维护不会执行；只读存储查询也不会触发保护，不能因仍显示待签就判定晚到提交可以被接受。

以上是整体 Gate1 的时间控制方案；进程重启已在 `0f41d9a` 上实际执行通过（见
主流程结果（本地证据：`report/lsp-0f41d9a/result.md`）与回归结果（本地证据：`report/lsp-0f41d9a-regression/result.md`）），业务超时保护仍未本地执行；
各批 Gate2 需把所选配置、恢复余量和链上等待上限写入具体场景前提。
采用合法 expiry 和有界等待，不修改宿主机时间；挖块只用于相应链上进度，不能代替墙上时间的 D。

### 超时保护已有明确预期

| 条件 | 必须观察到的结果 |
| --- | --- |
| HTTP 超时，节点尚未收到提交 | 原待签请求仍可恢复；在业务截止前提交同一份有效结果，可以首次应用，不能因 HTTP 超时就重建通道 |
| HTTP 超时，但节点已应用该提交 | 查明已应用结果；原样重试最近一次已应用提交返回 `AlreadyApplied`，不再次应用签名或造成第二次业务扣款 |
| 开通仍满足可中止条件，且适用 funding timeout 已到 | 中止注资，进入 `Closed(FUNDING_ABORTED)`；不能继续把原通道开成就绪。未广播注资的场景不得出现通道锁资；已发出注资签名的分支不适用这一预期 |
| 当前待签请求尚未应用，已到 TLC 安全截止时间 | 拒绝晚到签名，不应用新签名材料、不因该提交推进承诺号或继续原链下流程；尝试使用最新已保存、已签名的承诺强关，不能假定永远是上一承诺号 |
| 上述强关成功启动 | 进入等待承诺交易确认的关闭状态；清除待签请求及被阻塞的协议消息，并在返回过期错误前持久化；检查实际关闭交易与所用承诺相符，再跟踪确认及结算 |
| 上述强关尝试失败 | 晚到新签名仍不能被应用，待签请求必须保留，不能清空后伪装成已经安全处理或已结算 |

截止检查只针对适用通道状态下、尚未应用的当前请求；最近已应用结果的原样重试先走幂等判断，
不能笼统断言“截止后的所有提交都必须报过期”。维护已先清理请求时，晚到提交的错误形式也可能不同，
测试应核对拒绝和状态副作用，而不是只匹配一个错误字符串。没有未完成 TLC 时，不能凭空期待这条 TLC 保护定时强关。

**强关启动不等于支付已失败、退款已完成。** PR 明确要求在途支付继续按支付核对和链上结果结算，
不能仅因签名等待或 Hosted 缓冲到期就提前向上游判失败。Gate2 必须固定该签名检查点下 TLC 是否进入广播承诺、
preimage 是否已知，进而写明唯一的支付/发票及收付款余额预期；不能写“成功或失败均可”，也不能统一期待立即全额退款。
“无有效收款凭据的超时退款”与“已兑现支付不重复结算”应分别判断，并扣除对应实际链上费用；
所需链上执行能力尚未验证时应明确标出，不能用 `ShuttingDown` 或 `Closed` 代替资金断言。

### 已有覆盖与真正需要补的部分

以下是已阅读测试代码所表达的覆盖，不代表本轮运行过这些上游测试。

| 证据 | 已有覆盖 | 集成验证仍需补充的部分 |
| --- | --- | --- |
| [签名上下文单元测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-types/src/channel_signer.rs#L713)；[Hosted 提交测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L697) | 重复、冲突和旧结果判断；Hosted HTTP 调用的 `Applied → AlreadyApplied` | 后者使用 mock 注资，重试后未继续验证完整业务终态；需补真实进程和链上注资后的状态一致性 |
| [SDK 恢复测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lsp-sdk/src/signer.rs#L1095)；[Bruno remote signer](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/tests/bruno/e2e/lsp-remote-signer/README.md) | SDK 快照恢复后保留签名结果；真实 agent 在通道就绪后重启并协作关闭 | 需补待签/已签未提交等中途退出位置，以及 HTTP 请求未送达、结果未送达的区别 |
| [external_signer_restart](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L442) | 节点侧、签名侧在六种签名转换恢复；恢复辅助断言包含支付成功、TLC 清空、ACK 和待签结束 | 这里的节点 restart 是 Rust 测试内 NetworkNode 停启，签名端 restart 是内存快照恢复；不能等同于完整 Hosted FNN 和独立 SDK 进程重启 |
| [Hosted 冷查询/驱逐恢复](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L638)；[双租户 signer 恢复](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/integration.rs#L657) | 待签请求经过冷查询或租户驱逐后仍可用；SDK 快照恢复后继续开通 | 需补整个 FNN 进程停止、公共节点和租户一起恢复时的实际生命周期，不能用驱逐代替 |
| [签名截止时间测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L1306) | 精确截止边界、提交与维护先后顺序、强关使用已有承诺、不继续推进承诺号 | 使用手动驱动 actor 和时间参数；需补真实运行时超期后的 RPC、链上确认及业务终态，不能把发出交易事件当成结算完成 |
| 本仓库首批 LSP 与普通节点测试 | `LSP-SIGN-01～03` 已覆盖隔离；普通节点重启、funding timeout、watchtower 测试提供基础工具 | 首批转发器缓存重复请求，不验证真实重复提交；普通节点测试缺少 Hosted 身份和 remote signer，不能直接算作本范围覆盖 |

### 进程重启恢复：本批 Gate1

**本批要回答：签名端或整个 LSP 节点退出后，使用原数据重新启动，能否接着处理原通道，
保留已经授权和已经应用的事实，最终只开通、支付或关闭一次？**
每次补充先确认本批范围、已有覆盖和环境能力，再进入具体场景表；上述整体分组不代替本批范围确认。
本节不创建用例 ID、评审行或自动化。

#### 当前版本变化与既有测试的关系

`4eb4f5e` 相比已有隔离、重试测试版本新增：
[verify hosted signing state before authorization](https://github.com/nervosnetwork/fiber/commit/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10)。
它不是单纯的测试重构：[SDK 现在要求本地批准的开通参数、支付/发票授权、关闭授权等，先验证状态，再签名](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/README.md#L54)。
签名状态 RPC 还增加了对端 nonce/部分签名证据，以及 TLC 身份和密钥派生索引。
因此重启不仅要恢复身份和 nonce，也要保留本地授权及已验证的通道历史。

`412b254` 新增经过验证的租户开通入口。测试驱动改为调用同 SHA agent 的 `open_tenant_channel`：
先保存钱包意图，独立查询 CKB 校验注资交易，再验证开通上下文并保存绑定。受信合约来自本地 devnet 配置。
受控公共节点的只读协商状态仅用于独立核对及关闭费用预期，不代替 SDK 的开通验证。
发票、兑现及关闭授权继续调用真实 SDK 接口；FNN、SDK、认证材料和驱动的摘要在测试启动前核对。
`7f11564` 补充关闭、watchtower 本地授权入口和独立链上验证；通道签名核心及 SDK nonce 策略未改。
`0f41d9a` 将 nonce 跨消息复用从策略直接拒签改为保留警告，未改变 nonce 分配和派生；
本轮按该上游策略验证功能，不能据此认定 nonce 问题已修复。此版本另补 agent 收款授权、安全释放 preimage 和租户 `settle_invoice` 入口。
已评审主流程仍使用普通发票及真实 SDK 授权；不把它转写成安全释放 preimage 专项，也不修改业务断言。
本批仍按既有开通、支付、关闭行为复测，不据此扩展 watchtower 场景。
已有九条用例的业务预期保持不变；映射及版本对齐不等于新版执行通过。

#### 本批范围与可观察结果

| 方向 | 边界和入口 | 必须观察的结果 |
| --- | --- | --- |
| 恢复主流程 | 原租户、原通道、同一版本及原数据目录；分别重启独立 SDK 和完整 Hosted FNN | 身份、token、通道绑定和本地授权仍有效；能查询并继续处理原通道，不能重新注册或另开通道来掩盖恢复失败 |
| SDK 已签但未提交 | 截住实际签名提交，确认没有送达 FNN，再退出 SDK；该位置也意味着本次 SDK 签名的存储操作已返回 | 重启后能继续原待签请求；首次到达节点的有效结果只应用一次，已签记录和合法签名材料不丢失 |
| 已应用但 SDK 未获知 | 确认真实节点返回 `Applied`，阻止响应交给 SDK，并保留下一份待签请求，再选择 SDK 或 FNN 重启 | 当前请求不被旧结果吞掉；最近已应用结果仍可安全原样重试；允许 SDK 按当前状态继续，不要求它必然重发上一份 |
| FNN 尚有待签请求 | 停止整个承载公共节点和租户的 FNN，保留数据库；恢复 RPC 后再验证租户运行时和内部通道 | 原待签内容可恢复、有效签名能实际推动协议；只读查询成功不等于运行时已经恢复，不用租户驱逐冒充 FNN 重启 |
| 单笔支付恢复 | 选择与该支付关联的承诺或撤销签名检查点；保留原 payment hash、SDK 授权和有效期 | 原支付/发票完成，TLC 清理，双方余额与金额及实际手续费相符；不能只用 `ChannelReady` 判断成功 |
| 协作关闭恢复 | 无未完成 TLC，已有本地关闭授权，在关闭签名阶段重启 | 原通道完成关闭，原注资只被对应关闭交易花费一次；交易确认，输出接收脚本及金额与关闭前余额和实际费用一致 |

开通检查双方就绪、同一通道和同一笔注资；支付检查一次资金变化；关闭检查实际链上输出。
Gate2 按这三种结果选择代表检查点，不穷举“所有进程 × 所有签名转换 × 所有业务阶段”。
正常退出和强制终止要分清：现有 FNN `stop()` 发送终止信号并等待数据库锁释放；
SDK 的 `terminate()` 不能自动称为完成了应用级优雅退出。强制终止只能在可观察的存储完成检查点注入。
磁盘写入中断、断电落盘、存储损坏、丢失数据恢复、旧版到新版的存储迁移不属于本批。

#### 已有覆盖与环境缺口

| 依据或能力 | 能证明或复用什么 | 本批仍需补什么 |
| --- | --- | --- |
| 本仓库 `LSP-SIGN-01～03`、`LSP-RETRY-01～06` | 旧版真实 FNN/SDK 开通、隔离、重复提交、HTTP 故障和单笔支付；已有按请求暂停与真实响应丢失能力 | 新版授权前提适配及回归；现有 HTTP 故障没有停止进程，不能算重启覆盖 |
| [当前 Rust 重启测试](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L923)及 [SDK 快照恢复](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/crates/fiber-lsp-sdk/src/commitment_tests.rs#L477) | 六种签名转换的节点停启/内存 SDK 恢复，以及恢复后的授权、余额校验 | 独立 SDK 的真实文件和进程生命周期、完整 Hosted FNN 重启、最后业务及资金结果 |
| [agent 文件存储](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/tests/fiber-lsp-sdk-agent/src/store.rs#L52)及[启动恢复](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/tests/fiber-lsp-sdk-agent/src/agent.rs#L365) | 每次变更写快照并替换文件；启动读取 RootKey、会话和签名存储 | 确认旧进程确实退出、新进程读取同一路径；不能把对象重建或仅存在状态文件当成进程恢复证据 |
| [4eb4f5e agent `/bind`](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/tests/fiber-lsp-sdk-agent/src/main.rs#L49) | 当时支持提供开通参数，再进入校验后的签名流程；`412b254` 已改为验证租户开通 | 当前驱动调用真实 `open_tenant_channel`，不能沿用已移除的手工绑定入口，或把待签响应里的余额、费用直接当成本地批准值 |
| [新版 agent 的明确限制](https://github.com/nervosnetwork/fiber/blob/4eb4f5e9800d383c81e8c1b0fb10881fa1a8af10/tests/fiber-lsp-sdk-agent/README.md#L6) | Rust 调用方可登记支付/发票、兑现和关闭授权；SDK 会保存这些数据 | `4eb4f5e` 命令行控制面未接入支付及关闭授权；`7f11564` 补关闭授权，`0f41d9a` 再补发票及安全释放 preimage。本表继续由本地驱动接入真实 SDK 的普通发票授权及恢复记录观察，不手工篡改私有存储 |

上游 Bruno 文档仍描述“通道就绪后重启再关闭”，但新版 agent 已明确要求补齐驱动授权能力；
不能仅凭旧流程文件仍存在，就判定当前 HEAD 的支付、关闭可直接执行。
完整 watchtower 还需要独立链上验证接口，本批不扩展其授权、撤销惩罚及强关结算矩阵。

#### 时间控制与建议推进顺序

故障由明确事件触发：看到待签请求、截住 SDK 提交、或收到真实 `Applied`，然后才停止目标进程。
恢复以旧进程退出、新进程 RPC 可用、租户可执行及后续签名出现为条件，不固定停机 5 秒或 12 秒。
本批验证业务截止前恢复；开通的 funding 窗口和支付 TLC 的实际安全截止 D 都要覆盖退出、启动、
租户激活和协议推进，恢复时再次核对余量。越过 D 应转入超时保护批次，不能把失败或强关算作恢复成功。
具体有界等待预算在 Gate2 结合目标路径写明，不能因旧版单次启动耗时就宣称新版保证该恢复时间。

建议先确认上述“SDK/FNN 进程恢复 + 开通/支付/关闭结果”的范围；进入 Gate2 时，先把新版独立授权
作为共同前提说清楚，再选择相关场景。实现阶段先让同一 SHA 的 FNN/SDK 正常开通和必要业务流程成立，
再注入重启。支付与关闭保留在本批分析范围内，但在驱动能力补齐之前不能声称可执行或已覆盖。
若补齐授权需要改变已有评审行的前提或预期，应回到对应行评审后再改自动化；不修改公共框架、
`AGENTS.md` 或 `Makefile`，也不为赶进度回退到不校验的 SDK 签名路径。

### Gate2 场景分组与入口

下面是场景组和评审入口，不是用例表。每组共同评审多个相关场景，数量由实现证据决定；
不为每个小测试点单独重复 Gate1，也不要求本轮一次写完全部用例。

| 建议推进顺序 | 一起评审的内容 | 评审文档 |
| --- | --- | --- |
| 提交重试与短暂断线 | 原样重试、冲突/过旧提交、请求未送达、应用后响应丢失；恢复正常签名后核对开通或支付及余额 | [提交重试与短暂断线](lsp/channel-signing-retry.md) |
| 进程重启恢复 | 新版正常开通、支付、关闭作为对照；SDK/FNN 在待签或已应用检查点重启，核对恢复后的业务及资金结果 | [新版主流程与进程重启恢复](lsp/channel-signing-recovery.md) |
| 超时保护与结果一致性 | 开通安全中止、SDK/节点的晚到处理、无人提交时自动保护，以及不交出 preimage 时可观察到的发票与记账结果；支付侧 TLC 由 dev 模块注入短期限，链上取回与付款方解锁留作能力缺口 | [Gate1 范围分析](lsp/channel-signing-deadline-scope.md)、[Gate2 用例](lsp/channel-signing-deadline.md) |

### 环境能力、限制与判断标准

- 版本：目标提交为 `0f41d9a`；FNN、SDK 与测试驱动同源构建，产物及认证材料的 SHA-256 必须匹配当前清单；本地驱动源码摘要也在启动前校验。
  隔离与提交重试用例使用当前测试仓库基线 `852c97d`；覆盖边界以各自评审表为准，不代表整个 PR 已完成代码审查。
- 基础环境：Python、CKB 0.202.0、devnet 快照和下载目录中的 ckb-cli 在；运行前确保 `source/ckb-cli` 已准备。
  可设置 `CKB_CLI_HOME` 为测试专用目录，避免使用个人 keystore。LSP 环境适配保留在测试目录内，公共框架、`AGENTS.md` 和 `Makefile` 沿用仓库基线。
- 故障注入：LSP 局部 HTTP 转发器已支持按请求暂停、请求不转发、真实上游应用后丢响应等控制。
  必须从真实 FNN 读取处理进度；不允许用转发器缓存响应证明幂等。
- 重启：复用同一 FNN 数据目录和 SDK 存储；区分正常退出与强制终止，避免清理目录后“重开成功”。
  Hosted 场景的租户运行时重新激活、内部通道恢复和整台 FNN 重启已在 `0f41d9a` 上实际执行通过
  （见回归结果（本地证据：`report/lsp-0f41d9a-regression/result.md`））；仍未验证的是断电、存储损坏与存储迁移。
- 时间：当前 dev 构建采用较短的 epoch 换算和 3 秒维护周期，具备有限等待的基础；恢复成功场景的有效期要覆盖实际进程启动耗时。
  TLC 截止检查使用墙上时间，挖块不等于推进它。优先用合法 expiry 配置和有界等待，不修改宿主机系统时间；
  精确“截止那一毫秒”以及维护和提交的严格竞态顺序仍由可控的 Rust 测试证明，Python 集成测试只承诺可稳定观察的边界。
- 通过标准：先保存明确检查点，再比较 RPC、完整签名请求、通道状态、支付/发票终态、TLC、余额和必要的链上交易。
  首次签名应用后的正常异步推进需与重复/故障造成的变化分开；不把超时、连接失败或日志当作正确拒绝。
  若某条链上结算依赖尚未验证的 watchtower 执行能力，在 Gate2 写明前提及未解决项，不把 `Closed` 单独当成资金结算通过。

Gate1 对应上述完整范围与分组；Gate2 首组具体场景见[提交重试与短暂断线](lsp/channel-signing-retry.md)。
各组评审行确认后，再实现对应自动化和 TEST-MAP，不自动扩展到其余组。

评审表使用“用例、场景、预期结果、防止的问题、优先级”五列。已有首批入口：

```bash
venv/bin/python -m pytest -vv -s test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py
python3 scripts/check_test_map.py
```

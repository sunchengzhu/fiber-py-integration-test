# 签名超时后的退出与资金处理：Gate1 范围分析

## SPEC-09 独立败方恢复回归：Gate1 范围

本批目标：把检查点 B 的“**T 真实关闭确认、A 的竞争交易被真实 RBF 拒绝后，A 自动识别远端关闭**”纳入独立 Python 功能回归。
固定依据为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；本次核对源码 checkout 干净，现有 FNN/SDK/驱动构建清单同 SHA、dev profile。后续执行仍须核验构建清单、实际二进制摘要及版本，不能沿用历史通过。
2026-10-23 用户已明确通过本节 Gate1；范围、时序控制和判断边界保留如下。[Gate2 完整行、步骤与预算](channel-signing-deadline.md#lsp-timeout-12检查点-b-独立败方恢复)仅新增 `LSP-TIMEOUT-12`，用户已确认并授权进入 Gate3；12 的 Python 实现与 TEST-MAP 已接入，修复后聚焦及固定 3 次复跑 **4/4 通过**，相关 08/10 回归 **2/2 通过**。全部尝试与独立复核见 [SPEC-09 运行记录](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-spec-09lsp-timeout-12-独立败方恢复2026-10-23)。已批准的 08/10 及其 TEST-MAP 保持原契约；本批只改 12 的 Python 自动化与相关文档，不改产品或驱动。

### 范围与现有证据

| 范围 | 本批方案 | 验证边界 |
| --- | --- | --- |
| 检查点 B 败方恢复 | A 已完整签署含目标 TLC 的承诺，扣留下一份 `SendRevokeAndAck`；由截止保护触发双方真实广播，取得 T 胜出与 A 真实 RBF 后观察 A 收敛 | 独立于 10 的“A 含 TLC 承诺确认”；本例最终上链的是 T 的已绑定承诺，不要求 T 的承诺也含该 TLC |
| 检查点 A | 已有无额外时序控制的自然 T 胜出诊断作为背景，本批不新增 A 正式恢复用例 | A 的受控查询时序适配尚未实测；不把 B 的结果转记为 A 已受控验证，也不为补自然样本反复碰运气 |
| 受控方式 | 在 A 发送前的真实交易状态查询上施加一次固定 250 ms 响应延迟，保留双方真实竞争 | 明确标为受控查询时序；不推断无干预竞态发生率或所有自然顺序均已验证 |
| 业务终点 | A 的远端强关状态、真实 T 关闭哈希及无待签状态，在完整窗口内收敛且恢复后不回退 | `WAITING_ONCHAIN_SETTLEMENT` 可以仍在；不以 `Closed` 代表资金结算完成 |
| 本批排除 | 04/05 的 #1674、08/10 已批准的 A 指定承诺断言、07/11、签名订阅、重启/断网、真实路由付款、watchtower 结算与资金取回 | 保留各自已有结果或待覆盖入口，不借本批通过宣布整个 LSP PR 无缺陷 |

[A 自然诊断](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-自然竞争后的恢复诊断2026-10-23)在确认后约 264.6 秒恢复、观察 331.8 秒；[B 受控诊断](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-检查点-b-的竞争与恢复诊断续查2026-10-23)约 261.8 秒恢复、观察 330.7 秒，已由用户指定的 GPT 6 sol 终审。
B 的三次无额外时序控制尝试均由 A 获胜，只说明目标分支未取得。本批是在既有诊断基础上增加可重复的回归约束，历史单次受控通过不等于新用例已实现或稳定。

### 行为依据（SPEC-09，Gate1 已确认）

在本条独立 devnet 中，T 的精确 funding 花费已确认且索引可查询、A 的匹配交易被真实 RBF 拒绝、FNN/SDK/链持续健康后，A 应在一个 300 秒关闭扫描周期加 30 秒余量内，自动进入 `Closed`、包含 `UNCOOPERATIVE_REMOTE`、关闭哈希等于 T 的真实确认交易，并为 `NoSignatureRequired`；恢复后所有采样保持这些条件。

这是基于当前实现和已保存观察提出的**固定版本回归预算**，不是已有产品 SLA，也不要求恰好在确认后第 300 秒恢复。`NoSignatureRequired` 可以在本地保护时已出现，不能单独作为恢复证明。

源码依据（均为上述固定 SHA，链接指向对应上游源码）：

- [in_flight_ckb_tx_actor.rs](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/in_flight_ckb_tx_actor.rs) 第 239～263 行在投递 `SendTx` 前异步查询交易状态；第 358～373 行对真实拒绝发送 `ClosingTransactionFailed` 并结束跟踪。
- [network.rs](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs) 第 2514～2520 行仅清理失败交易跟踪；第 256、9125～9131 行为 HostedTenant 注册 300 秒关闭扫描；第 3123～3145 行包含 `ShuttingDown`；第 4642～4656、4860～4906 行查询 funding 花费并识别远端已确认承诺。
- [channel.rs](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs) 第 11716～11747 行将其记录为 `Closed(UNCOOPERATIVE_REMOTE | WAITING_ONCHAIN_SETTLEMENT)` 并保存实际关闭哈希。
- [ckb/actor.rs](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/ckb/actor.rs) 第 303～330 行在共享 chain actor 内串行等待真实发送，还会把 `-1111` 打印为 `already in pool`；因此接受、拒绝和确认须检查原始 CKB 响应，不能凭该日志判定。

### 受控时序方案

1. 复用独立 `FiberTest` 环境、真实 Hosted A—公共 LSP T 通道、SDK hold 发票和 22 秒 TLC，发票有效期预留 600 秒；不交 preimage。到达 B 后保留撤销签名，确认 `SendRevokeAndAck`、A 的完整承诺包含准确 `payment_hash/expiry`，并在 D 前至少 5 秒完成准备。准备预算不得消耗掉观察窗口，Gate2 将把各起点和总上限写入用例。
2. D 前保存 funding outpoint、A/T 最新承诺对应的唯一 SDK 记录及两份不同规范化签名消息。A 记录须 `complete && !for_remote`；T 记录须 `for_remote`，不要求 A 的 SDK 持有 T 的完整聚合签名。真实发送之后再用现有驱动独立计算规范化消息核对归属，不能通过赢家顺序猜 A/T。
3. 仅本条环境的 FNN 链 RPC 经过观察代理；独立断言直连真实 CKB。按目标 channel、T 公钥和既有 `Spawning InFlightCkbTxActor ... Closing` 日志唯一绑定 A 的实际关闭哈希。只对 D 之后该哈希的真实 `get_transaction` **unknown** 响应开启一次固定 250 ms 窗口，保存上游原文后等待；同哈希并发查询共用一个释放点，不滚动延长。必须证明包含发送前查询（固定版本参数为 `[hash, "0x0", true]`），不能只延迟 tracer 而宣称控制了发送。
4. 等待发生在共享 `SendTx` 之前，不持代理共享锁。T 的查询、双方 `send_transaction` 及所有其他响应原样转发；不调用广播 `arm()`，不注入 RPC 错误、不代发交易、不调费、不停矿、不重启或手动强关。固定时间到即释放，释放条件不依赖 T 接受或确认。
5. 取得场景须同时证明：窗口确实激活；T 在该固定窗口内真实发送并由 CKB 接受；A 在匹配查询释放后真实发送；A 的原始错误同时为 `code=-1111` 且 `data` 含 `RBFRejected`；T 的真实 `committed` 交易精确花费目标 funding。保存双方原始请求/响应、交易归属和单调时间，所有延迟须在首次独立观察到 T `committed` 前结束。缺任一项均不能记为恢复通过。
6. 恢复阶段代理只记录并原样转发；保持 FNN/SDK、挖块和索引器运行，不再提交扣留签名。250 ms 是待固定复跑验证的夹具参数，不能宣称保证 T 必胜；若仍由 A 获胜，保存该次非零结果后定位，不动态加长延迟、不自动重跑到通过。

方案以现有 [diagnose_competing_close.py](../../test_cases/fiber/devnet/lsp/diagnose_competing_close.py) 的 B 机制为依据；正式实现由 Gate3 单独接入。该脚本仅有手动诊断入口，不为它新增 TEST-MAP，不把历史诊断计为正式回归通过。

### 观察窗口与证据边界

- **确认起点 `t_commit`：** 独立查询首次读到 T 为 `committed` 的单调时间，保存区块号、hash、精确 funding 输入。它是观察时间，不冒称精确出块时刻。
- **链观察就绪 `t_ready`：** T 仍已确认，索引器高度达到其区块，且直接按同一 funding lock 查询已能返回该 T 的 input 花费；高度追平本身不足以证明可见。就绪最多等到 `t_commit + 30 秒`，超期为链/索引环境未就绪，保留非零结果。恢复阶段完整窗口从 `t_ready` 起算 330 秒，两个起点均留档，禁止反复重置预算。该前提比旧诊断只检查最终索引高度更严格，须 Gate2/3 实现并验证。
- **成功及稳定性：** A 在 `t_ready + 330 秒` 内满足全部恢复条件；即使提前恢复也观察至完整窗口结束。首次恢复后至少连续观察 10 秒，全部后续样本均保持完整条件；若临近截止才恢复，可补足这 10 秒，总上限为 `t_ready + 340 秒`。不得只检查第一次成功和最终一帧、忽略中途回退。Gate2 固定有界 RPC 超时与采样间隔，避免阻塞读调用隐性延长预算。
- **持续健康：** 记录签名提交计数不变、进程存活、代理无异常、真实链和索引器进度；链读取直接验证 T 仍为目标 funding 的确认花费。发票有效期覆盖从创建到观察结束的预算，禁止运行中延期。余额、发票和 TLC 记录可作为诊断上下文，不在本批推出资金解锁或付款终态结论。
- **恢复来源：** 联合 A 的 RPC 状态、T 的链交易、固定源码和同一 channel 的 HostedTenant 身份日志定位；actor ID 动态获取，不写死 `0.12`。须留存 Hosted A 的 `is shutdown by remote` 及随后状态转换；watchtower 的 `PeriodicCheck` 或相同 funding 查询不能替代该证据。无需新增产品日志。业务终态正确但缺失这些日志时，归证据采集/夹具不完整并非零退出，不记为本批完整证据的回归通过，也不凭缺日志判产品 bug。
- **缺扫描也不能逃过判断：** 当真实 T 胜出/A RBF、链观察就绪及运行健康都已成立，330 秒内不收敛应判恢复回归失败，保留扫描调度或识别路径的产品问题可能；不能要求“先证明扫描成功”才把它算失败，也不能改写成目标场景未取得。

### 测试树与异常结果如何处理

- 独立败方恢复 → SPEC-09（Gate2 展开为 `LSP-TIMEOUT-12`、P1，Gate3 已接入映射；执行结果另记）
  - B 的准确检查点、唯一 A/T 交易绑定与真实竞争条件成立。
  - T 已确认且链观察就绪后，A 在完整扫描预算内识别 T 的关闭。
  - A 的关闭方向、真实 hash、无待签条件恢复后持续成立。
- A 受控时序、无干预竞态概率、重启/断网与资金结算 → 本批不展开；后续有明确需求时另走范围评审。

| 实际结果 | 归类与下一步 |
| --- | --- |
| 记录歧义、查询未命中、代理异常、准备过晚，或正确业务终态缺少 Hosted A 恢复归因日志 | 测试准备、夹具或证据采集失败，非零退出并保存已有证据；修复对应问题后重跑，不把未执行或证据不完整的恢复分支记为通过 |
| A 获胜，或 T 确认但 A 没有真实 RBF | 目标场景未取得，非零退出；只说明本次没有检验恢复，调查时序或前提，禁止自动择优保留 |
| T 已确认，但索引在有界等待内不可见；或观察中链/运行环境异常 | 按证据定位环境、夹具或 FNN 故障，不能用“环境”标签掩盖产品崩溃；本次不形成有效恢复通过 |
| 场景、链就绪和运行条件成立，窗口内 A 未恢复，或恢复后回退 | 恢复回归失败；区分扫描未运行、链查询/识别失败、状态转移错误，保留为产品问题候选并给出日志，不仅凭 60 秒等待定性 |
| 场景、全部恢复及持续观察条件成立，且有同一 channel 的 Hosted A 恢复日志 | 本次受控 B 关闭识别回归通过；不扩写为无干预竞态、链上结算或整个 PR 通过 |

### Gate1 交接与当前入口

已确认范围：**首批只纳入 B；采用一次固定 250 ms 查询响应窗口；以真实 T 确认/A RBF 为前提；链观察就绪后完整 330 秒、恢复后至少 10 秒稳定；终点限定为远端关闭识别。**
Gate2 已获用户明确通过，完整用例、预算、断言及固定复跑次数见上方入口；Gate3 的实现和实际验证结果见本节顶部。固定复跑用于检验夹具能重复取得场景，每次结果都保留；历史诊断不替代本条实际执行。

Gate1 当轮记录：GPT 6 sol 已独立复核本节及主评审入口；补齐 Hosted A 日志缺失时的非零结果分类后，最终无阻断项。当轮仅改三份评审文档，未运行节点：`git diff --check` 与链接/空白检查退出 0；`python3 scripts/check_test_map.py` 退出 1，仍为既有 PMP/SETTLE 孤儿映射及历史 report overlay 重复 ID；`check_test_design.py --review reviews/lsp/channel-signing-deadline.md` 识别原有 10 条、退出 1，当时另保留 SPEC-09 待确认及 pending 分支。Gate2 当前检查结果见完整用例文档，不覆盖或冒用这份历史记录。

## 08/10 稳定性改造范围

2026-10-23 用户已明确通过本节 Gate1 及 [08/10 完整用例与共同断言 Gate2](channel-signing-deadline.md)，本轮 Gate3 实现、聚焦与固定 3 轮复跑已完成，GPT 6.1 sol 独立复核无阻断项。
本节保留 `LSP-TIMEOUT-08/10` 的改造范围与控制方式，固定依据为
[`24b5c38bc098aeb29de5f6af7ac28dc667f218e3`](https://github.com/nervosnetwork/fiber/commit/24b5c38bc098aeb29de5f6af7ac28dc667f218e3)。
本地源码干净，未切换版本；这是已执行版本的分析，不表示重新核实了上游最新 HEAD。
对应 Python 自动化已按确认行接入广播隔离；实际结果与首次实现问题见[Gate3 运行记录](../../test_cases/fiber/devnet/lsp/README.md)，不以历史运行代替本次验证。
以下保留已确认的范围与控制方式；隔离用例结果不证明自然竞争恢复。后续独立诊断已证实检查点 A 在真实 T 获胜/RBF 后恢复；B 三次无额外时序控制的尝试均由 A 获胜，随后一次受控查询时序复现取得 B 的 T 胜出/A 真实 RBF 并在完整扫描窗口内恢复，详见下方诊断入口。

### 产品问题判断

**已定位失败的直接原因，但不能确认 Fiber 没有产品缺陷。**
[原始日志与源码归因](../../test_cases/fiber/devnet/lsp/README.md#0810-为什么首轮失败最终轮通过)显示：A/T 同时触发保护，T 的交易确认，A 的交易被 `RBFRejected`，旧测试只等 A 的交易而失败。
“30 秒以内”不能排除 T 同一截止的主动保护；双方最终记录同一关闭哈希也可能是正常收敛，不应据此认定发起方。

该轮尚未验证的产品问题是：**A 的关闭交易被拒绝后，能否自动识别已确认的 T 承诺并正确收敛。** 后续实测结果见本节末的“产品恢复诊断入口”。
[`ClosingTransactionFailed`](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs#L2514)只移除交易跟踪并记录错误；
Hosted 网络另有 [300 秒关闭扫描](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs#L9129)与
[识别对端已确认承诺的路径](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs#L4860)。
现有失败只观察 60 秒，既没有证明该路径完成，也没有证明永久卡住。04/05 的 [#1674](https://github.com/nervosnetwork/fiber/issues/1674)不覆盖这里的竞争或恢复问题。

### 行为依据（Spec）

- **自动截止保护：** [维护入口](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L4339)在 D 到达后触发保护；
  [适用条件](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L6582)同时覆盖待签的 A 与 internal channel 的 T。
  [现有上游测试](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L12373)明确覆盖 T 的 `LocalAnnounced` TLC；本轮只阅读该测试，不运行或扩展 Rust 测试。
- **使用正确承诺：** [强关入口](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L2697)取得已有完整签署的承诺后投递广播并进入等待确认。
  对照真实 SDK 的已签记录与 CKB 确认交易；现有 `commitment-message` 驱动可生成规范化签名消息，避开刷新 `cell_deps` 导致原始交易哈希变化的问题。
- **请求清理边界：** [取消请求和清空缓存](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L3411)发生在本地保护转移成功后，并不等待链上确认。
  用例仍要分别证明真实上链与晚到签名不能应用，不能把“请求消失”当作链上成功，也不能把提前于确认的清理单独判为 bug。

### 测试树与本轮范围

- A 的截止保护及指定承诺确认（本轮改造）
  - 检查点 A：不再提交签名，A 自动使用不含目标 TLC 的旧承诺关闭，并拒绝晚到签名 → `LSP-TIMEOUT-08`；依据：自动截止保护、使用正确承诺、请求清理边界。
  - 检查点 B：扣住撤销签名，A 使用已完整签署且包含目标 TLC 的承诺关闭 → `LSP-TIMEOUT-10`；依据：自动截止保护、使用正确承诺。
- 双方自然竞争后败方识别赢家（待后续独立评审）
  - T 获胜且 A 收到真实 `RBFRejected` 后，A 能否在完整扫描窗口内识别 T 的关闭并收敛；不并入 08/10，不分配新 ID，不将隔离后的通过当作该分支通过。
- 真实付款终态、watchtower 结算及资金取回（不在本轮范围）；当前 `dev_add_tlc` 没有完整真实付款会话，关闭确认不能替代这些结果。

### 推荐方案：仅在两条用例中隔离竞争交易广播

A 与 T 共用 FNN 进程和 [chain actor](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/lsp/runtime.rs#L203)，
且 Hosted 开通[要求对端为所属公共 LSP](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/channel.rs#L1114)。
因此暂停 T 进程会一起暂停 A，换一个普通节点作对端也不符合当前接口。推荐在测试侧增加一个仅 08/10 启用的 Python CKB RPC 门禁：

1. 仅在这两条的独立环境中将 FNN 的链 RPC 指向门禁；测试自身的 CKB 查询、挖块及最终断言直接访问真实 CKB。准备阶段正常转发，通道开通和真实 SDK 签名均保持原流程；其他测试继续使用原 URL。
2. 在 D 之前保存目标 funding outpoint，并分别绑定 A/T 当前承诺：A 的最新承诺哈希匹配 SDK 唯一 `complete && !for_remote` 记录；T 的最新承诺哈希匹配 SDK 唯一 `for_remote` 记录，取各自规范化签名消息并确认不同。T 记录无需 `complete=true`，因为 A 的 SDK 未必持有 T 聚合后的签名；[记录来源](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lsp-sdk/src/lifecycle.rs#L239)与现有驱动已提供所需字段。匹配缺失、歧义或剩余准备时间不足均判准备失败，不降级成所有非 A 交易都算 T；该匹配方案尚待 Gate3 实测。
3. A 的预期承诺原样送真实 CKB，使用其实际响应并跟踪实际确认；T 的已识别竞争承诺立即返回明确的测试注入 RPC 错误，其他通道和读取请求照常转发。门禁只控制竞争交易可否提交，不生成签名、不提交预存交易替代 A、不伪造 CKB 接受或确认。
4. 不挂起 T 的请求：共享 [chain actor 会等待 send_transaction 返回](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/ckb/actor.rs#L310)，挂起会阻塞 A。使用普通、可明确识别的注入错误；不能使用该路径当作成功处理的 `-1107/-1111`，也不能把注入错误误记为真实 RBF。具体错误与有界窗口在 Gate2 固定。
5. 独立记录门禁实际拦截/转发的交易、规范化消息、时间与真实响应；解析失败、未知目标交易、门禁未及时就绪或 A 未按期限发起保护都应使该次测试失败，不能重跑到绿。门禁随该条环境清理，不影响其余 LSP 用例。

这是为了验证 A 侧指定承诺的隔离条件，不证明自然竞争下的系统恢复。若实现时不能可靠识别两侧承诺或影响 A 的广播，先报告夹具准备问题并回到评审，不能悄悄改成接受任一侧关闭。

### Gate1 确认的改造项（完整行已展开到 Gate2）

| 范围 | 拟改造方式 | 必须保留的结果 |
| --- | --- | --- |
| 08：无人提交时自动保护 | 增加竞争广播隔离前提；以 A 的状态、实际广播及已签承诺证明自主保护，删除“早于 30 秒即可排除 T”和“双方关闭哈希必须不同”的归因依据 | D 到达后 A 无需新的签名提交或手动关闭就发起保护；A 的旧承诺由真实 CKB 确认并花费目标注资；待签清理，晚到原签名不被应用；该承诺不含目标 TLC |
| 10：确认承诺包含目标 TLC | 同样隔离竞争；沿用现有测试的 SDK 完整签署记录与规范化签名消息比对，纠正文档直接比较更新依赖前后原始哈希的描述；保留检查点 B | A 的含 TLC 承诺真实确认并花费目标注资，包含准确的目标 `payment_hash` 与 expiry；区别于注入前承诺；检查时发票仍为 `Open`，不交出 preimage |
| 共用辅助方法 | 增加仅 08/10 显式启用的门禁和证据输出；分开准备、保护启动、确认阶段的有界等待；保留现有 ID 与 TEST-MAP | 保护启动暂沿用 D 后 15 秒、链确认 60 秒上限；10 的发票有效期单独建议设为 180 秒以容纳完整观察预算，TLC 仍为 22 秒；11 原有 90 秒发票过期设计保留。Gate2 固定准备裕量与各等待起算点；未知交易不能被过滤为通过；不改 07/11 的语义或默认行为 |

Gate2 已在[现有评审文档](channel-signing-deadline.md)内补齐本批 Spec → 测试树 → 两条完整变更行，并明确门禁识别与预算；用户已确认此行集及共同断言。
Gate2 必须明确门禁生效证据（T 的匹配交易被拦截、A 的匹配交易真实转发）、T 重播沿用同一规则、D 前就绪余量，以及从发票创建起计算的完整观察预算；不临时延寿已过期发票。
Gate3 才修改 Python 自动化，先验证隔离确实生效，再验证两条真实业务结果及受影响辅助方法；固定次数的重复运行用于检验稳定性，每次结果都保留，不重试掩盖失败。
本轮不修改 FNN/SDK/Rust 驱动或公共框架，不跳过或放宽用例，不将 08/10 标为已修复。

### 产品恢复诊断入口（2026-10-23 更新）

用户已另行批准诊断：保留自然竞争并记录真实的 T 确认/A 拒绝，从赢家确认起观察完整 300 秒扫描周期加 30 秒余量；
核对 A 是否自动进入 `Closed/UNCOOPERATIVE_REMOTE` 并指向 T 的确认交易，保存扫描触发、链查询及匹配证据。
这个窗口用于检查产品收敛，不能替代 08/10 的 A 承诺确认要求；超时后需据日志定位产品问题，成功也只证明这次关闭识别，不代表结算与资金取回通过。

[首批独立诊断原始结果](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-自然竞争后的恢复诊断2026-10-23)：检查点 A 取得真实 T 获胜/A RBF，确认后约 264.6 秒恢复，观察满 331.8 秒且无回退；HostedTenant A 的扫描识别日志与实际 T 关闭哈希吻合。检查点 B 的前三次无额外时序控制的竞争均 A 获胜，未取得目标分支。随后[检查点 B 的受控查询时序诊断](../../test_cases/fiber/devnet/lsp/README.md#24b5c38-检查点-b-的竞争与恢复诊断续查2026-10-23)保留双方真实广播，T 确认、A 收到真实 RBF，确认后约 261.8 秒由 HostedTenant A 自动收敛，持续观察满 330.7 秒。该次固定 250 ms 查询延迟不用于推断无干预竞态发生率，也不代表链上结算、资金取回或正式恢复用例已通过。诊断未改产品代码及原 08/10 契约，未新增 TEST-MAP。

## 历史 Gate1 分析（0f41d9a）

以下保留原阶段依据；其中“30 秒排除对端”“SDK 轮询”等旧版本描述不作为 `24b5c38` 的新方案或已验证结果。

本批要回答：**钱包一直没把签名交回来，什么时候还能继续，什么时候必须停止？停止后，这笔钱最终归谁？**

这是[整体区域图](../README.md)中已规划的第三组“超时保护与结果一致性”。本文件先评审范围、预期方向和测试条件；具体用例行在 Gate2 编写。
依据为 PR #1623 当前提交 [`0f41d9a`](https://github.com/nervosnetwork/fiber/commit/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073)，仅针对本行为阅读相关实现和测试，不代表整个 PR 已完成代码审查。

## 为什么补这一批

已有隔离、重试、进程恢复三份评审表，共 16 个 TEST-MAP。它们在 `0f41d9a` 上分三批实际执行并通过
（主流程 `1 passed in 187.78s`；其余 15 条为 `3 passed`、`6 passed`、`6 passed, 1 deselected`，各批退出码 0，见
主流程结果（本地证据：`report/lsp-0f41d9a/result.md`） 与 回归结果（本地证据：`report/lsp-0f41d9a-regression/result.md`））。
这些结果覆盖正常业务和在仍有余量时的恢复；**没有任何一条超时截止场景被执行过**，有映射也不代表本批已经验证。

本轮交接时重新核对了上游 PR HEAD：`refs/pull/1623/head` 仍为 `0f41d9a`，与本批构建、SDK、驱动和已执行批次一致，
因此不需要重新构建或版本适配；本地 `download/fiber/pr-1623/build.json` 与安装目录版本也一致。
构建清单与安装目录版本（build.json（本地材料：`download/fiber/pr-1623/build.json`）、FNN `fnn Fiber v0.9.1 (0f41d9a 2026-09-24)`）未变化。

## 两条业务分支，不能使用同一种超时预期

| 分支 | 谁负责判断、从哪里观察 | 预期方向 |
| --- | --- | --- |
| 通道还在开通，等待钱包注资或后续通道签名 | FNN 的开通计时和状态机；钱包提交接口、双方通道查询、CKB 输入和交易查询 | 只有仍能安全撤销注资时才中止。对于尚未广播注资的场景，钱应仍在原钱包输入中，并没有发生“链上退款”；晚到签名不能让已中止的原通道重新开通 |
| 通道已就绪，支付更新卡在签名步骤 | SDK 决定还能否签名；FNN 决定还能否应用签名、是否启动强关；支付/发票查询和链上结算证明资金结果 | 越过安全截止后，不能靠晚到签名继续原支付更新；节点尝试用已有有效承诺强关。强关开始、交易确认和资金结算完成是不同阶段，不能看到关闭就算完成 |

角色沿用已有场景：A 是 Hosted 租户，T 是公共 LSP，P 是普通付款节点（本批只用作钱包注资签名的辅助节点，不再作为付款方）。
不引入 MPP、UDT 或并发付款。超时期间 FNN 和 A 的通道运行时保持运行；本批不混入重启、驱逐和冷运行时重新激活。

支付侧的 TLC 由 `dev_add_tlc` 注入，而不是走完 P—T—A 路由：该 debug 构建启用了 `debug-add-tlc` 和 dev 模块，
可以指定精确 `expiry`。原因是真实路由支付的最终 TLC 期限无法压短——付款方会给每笔支付加
[至少一个 4 小时的隐私随机延长](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/graph.rs#L2189)
（编译期常量，发行二进制没有开关），T 转发到 A 时的钳制也不会让它更早，因此真实路由支付的 D 至少在 4 小时后，无法在有限等待内触发。
注入只替代“这笔 TLC 怎么进入通道”；hold 发票、SDK 授权与真实签名、截止保护、强关和链上确认仍然全部真实。

## 准备一起评审的行为

以下是分析方向，不是已批准用例，也不为每一行立即分配用例 ID。
“可行性”指当前本地套件在**不新增驱动控制**的前提下能否注入该条件；已核对的控制入口见下文“环境条件”。

| 方向 | 故障或对照条件 | 必须能够判断的结果 | 当前可行性 |
| --- | --- | --- | --- |
| 钱包没有及时完成注资 | 已取得未签注资交易，一直不提交钱包签名，越过外部注资期限，再尝试提交 | 原开通中止（`Closed(FUNDING_ABORTED)`，`list_channels` 带有中止详情）；晚到提交被拒绝且不能复活原通道；没有注资交易确认，选定且没有其他消费的原钱包输入仍然可用 | 可做：钱包提交由测试直接控制 |
| 钱包及时提交后，旧计时器到期 | 钱包在外部注资期限内提交有效交易，但后续通道签名暂缓；普通开通期限仍有余量 | 旧的外部注资计时器不能误中止已完成钱包提交的流程；在后续合法窗口内恢复，应完成同一通道 | 可做：缩短外部注资计时后提交，观察不中止 |
| 后续开通签名一直不回来 | 钱包提交已完成，仍停在允许安全中止的开通阶段（`SigningCommitment`），等待超过普通开通期限 | 原开通中止（`FUNDING_ABORTED`）；此时**尚未广播注资交易**（节点只在注资签名交换完成时才广播），钱仍在原钱包输入中；晚到通道签名不能复活通道 | 可做：缩短普通开通期限并扣住通道签名 |
| 钱包回来得太晚，SDK 还没签 | 带未完成支付的请求直到 SDK 安全窗口耗尽后才交给 SDK | SDK 应拒绝生成新的有效签名，不能记录一次成功签名或推进节点 | **归因受限**：见下文“不能稳定隔离的一项” |
| SDK 及时签了，但交给节点时太晚 | 在合法窗口内取得真实有效签名，截住提交；越过节点安全截止后交给 FNN | 该份尚未应用的签名不能首次应用，不能增加承诺版本或恢复支付更新；节点进入超时保护。维护可能先发生，因此不绑定某一条错误文字或精确调用先后 | 可做：gate 扣住真实提交，越过 D 后直连 FNN 提交 |
| 钱包一直不提交，节点自行保护 | 保持待签请求和未完成 TLC，过期后不发送任何签名提交 | 活跃节点应由周期维护启动强关，不能必须等客户端回来才处理。使用已有有效承诺；成功启动后清理待签及相关缓存更新，晚到签名不能恢复原更新 | 可做：不提交任何签名，等待维护触发 |
| 保护启动后，钱最终怎样处理 | 选定已有有效承诺确实包含目标 TLC 的检查点；收款方始终未向 FNN 交出 preimage，也未批准兑现；随后恢复必要的链上签名能力 | 承诺交易确认后，按链上期限完成超时处理；原付款最终失败，不能长期停在处理中，发票不能成为已支付。付款金额解除锁定，不产生成功支付收入；链上支出按实际费用及承担方核对，不能重复退款或结算 | **部分不可做**：链上取回需要 Hosted watchtower/链上授权，本地驱动未接入 |

最后一项需要明确“承诺中包含该 TLC”。如果广播承诺根本没有这笔 TLC，其失败和解锁路径不同，不能拿来替代链上超时取回场景。
本批先分析“不交出 preimage”的资金结果；已经允许兑现或 preimage 已公开的情况，不能一概预期退款，另批展开。

## 时间怎么控制（按 `0f41d9a` 复核）

| 时间 | `0f41d9a` 的实际含义 | 测试控制原则 |
| --- | --- | --- |
| HTTP 请求超时 | agent 一次 RPC 的等待预算（10 秒），不是业务截止时间 | 已有重试批次覆盖；不能因为请求等了 10 秒就期待中止或强关 |
| 外部钱包注资期限 | 默认 5 分钟（`DEFAULT_EXTERNAL_FUNDING_TIMEOUT_SECONDS`）；在存入未签注资交易、进入 `AWAITING_EXTERNAL_FUNDING` 时记录 `started_at`，缺该时间才退回通道创建时间 | 通过节点配置缩短；先确认进入外部注资等待，再决定提交时机 |
| 普通开通期限 | 默认 24 小时（`DEFAULT_FUNDING_TIMEOUT_SECONDS`），从通道创建时间计时，且只在 `can_abort_funding_on_timeout()` 为真时生效 | 通过节点配置缩短；过期事件到达时会重新判定，已不适用就忽略 |
| 节点支付安全截止 D | 对移除尚未确认的 TLC，取 `expiry − tlc_expiry_delay(commitment_delay_epoch)` 的最早值；`tlc_expiry_delay` 为 2/3 承诺延迟。debug 构建 `MILLI_SECONDS_PER_EPOCH = 2 秒`，本环境 `commitment_delay_epoch = 0x10000000001`，故预留约 **1333 毫秒**（浮点截断） | 读取实际 TLC expiry 后按 `(expiry − 1333)` 计算；不修改宿主机时钟，不把挖块当作推进这项时间。已有恢复用例里的 `- 1334` 写法即出于同一换算 |
| SDK 签名安全窗口 | SDK 把 TLC expiry 向下截到整秒，安全预留按 `ceil(2/3 epoch)` 向上取整（同环境下为 **1334 毫秒**），撤销确认还检查替代承诺的恢复窗口 | SDK 的最后可签时刻通常**早于** FNN 的 D（截秒最多再早 1 秒）。不能直接用 FNN 的 D 当作 SDK 最后可签时刻 |
| 对端无响应保护 | 发送承诺签名后若 30 秒内没有对端 ACK，会走“对端无响应”强关（debug 构建也是 30 秒） | 这是**另一个强关来源**，会与本批目标截止保护竞争；见下文归因要求 |
| 维护周期 | debug 构建每 3 秒检查一次全部通道 | 截止到达后给数个维护周期作为观察上限，不承诺 3 秒内完成 |

已有恢复用例的 15 分钟 TLC 授权下限和较长有效期是为进程恢复留时间，不能直接复制成快速超时场景。
本环境的 TLC 最短寿命由收货侧校验决定：到达时要求 `expiry > now + MIN_TLC_EXPIRY_DELTA`（同环境 1333 毫秒），
发票 `final_expiry_delta` 也只受 `[MIN_TLC_EXPIRY_DELTA, 14 天]` 约束，因此 1～2 分钟量级的合法 TLC 可以构造；
但付款端还要在发票要求的最终期限与自身 `tlc_expiry_limit` 之间取随机延长，Gate2 必须实测保存实际 expiry，
并让 SDK 授权区间（`min_tlc_expiry_delta_ms`、`max_tlc_expiry_ms`、`expires_at_ms`）与所选短期限自洽——
这是为本批选定的短窗口参数，不是放宽既有 16 条的授权边界。

链上结算另按实际交易确认、TLC 到期、相对锁定期及索引同步确定有界等待，并逐阶段检查；不能用同一个短等待覆盖全部结果。

## 已有覆盖与真正需要补的部分

以下为阅读 `0f41d9a` 测试代码得到的覆盖边界；本轮没有运行这些 Rust 或 Python 测试。

| 已有依据 | 已覆盖的内容 | 本批要补的差距 |
| --- | --- | --- |
| FNN Rust `external_signer_restart.rs`：`check_signature_deadline` 及其六个用例 | 截止当刻与过期后提交、维护先发生、强关使用最新已存已签承诺、承诺号不推进、请求在强关失败时保留、清理后投递被丢弃 | 这些测试手动驱动 actor 与时间；不能代替真实 Hosted/SDK 进程、CKB 确认及支付资金终态 |
| FNN Rust 开通测试 | 外部钱包超时中止、及时提交后旧定时器不误中止，以及普通开通超时 | 补真实 Hosted 钱包与通道签名配合、晚到提交、原输入和注资核对 |
| SDK Rust `commitment_tests.rs`（如 `rejects_expired_existing_tlc_and_uncommitted_millisecond_grace`） | 已过期 TLC、毫秒截断边界及过期签名确认的拒绝 | 精确边界继续由 Rust 证明；Python 侧只承诺可稳定观察的边界与业务结果 |
| Python 普通通道超时和 watchtower 测试 | 普通开通超时，以及部分带 TLC 的强关、兑现与链上等待 | 未覆盖真实 Hosted SDK 签名截止自动触发强关后，同一笔支付的完整资金结果 |

## 环境条件：能控制什么，缺什么

### 已经确认可用的控制入口

- **钱包注资提交由测试直接控制。** 当前流程是：SDK 的 `open_tenant_channel` 保存钱包意图、独立校验注资输入后返回未签交易；
  测试随后调用 `sign_external_funding_tx` 取得钱包签名，再由租户客户端 `submit_signed_funding_tx` 提交
  （见 [_lsp_test.py](../../test_cases/fiber/devnet/lsp/_lsp_test.py) 中的开通段）。
  因此“一直不提交”和“超时后再提交”都不需要新控制面，也**不绕过 SDK 已验证的开通前提**；
  钱包注资提交与通道承诺签名提交是两个不同接口，不能拿签名拦截器冒充注资拦截。
- **通道签名提交可以按请求暂停/放行**（`RetrySignatureGate` 对 `submit_channel_signature` 的暂停、断线、丢响应），
  且测试可以把捕获到的真实提交直连 FNN 提交，用于“晚到提交”。
- **SDK 获取请求的时刻可以推迟**：agent 只通过 `get_channel_signing_status` 轮询发现待签请求
  （`tests/fiber-lsp-sdk-agent/src/agent.rs` 的 `poll_channel`），转发器已有 `pause_queries` 开关。
- **时间参数可缩短**：通道的 `funding_timeout_seconds` / `external_funding_timeout_seconds` 来自节点配置
  （`fiber/network.rs` 生成通道 `ChannelEphemeralConfig`），租户通道同样适用。
  最小改动是在 LSP 套件内给承载租户的 FNN 配置文件补这两个键，与现有套件改写 `lsp:`/`rpc:` 段的做法一致；
  不改公共模板、`framework/`、`AGENTS.md` 或 `Makefile`。
- **链上与业务观察**：CKB 交易/输入查询与挖块、`list_channels`（含 `failure_detail`、`latest_commitment_transaction_hash`、
  `pending_tlcs`）、`get_channel_signing_status`、支付/发票查询、SDK 控制面的 `records`（可读到已签承诺及其 TLC 与 expiry）。

### 不能稳定隔离的一项

“SDK 在窗口关闭后才看到请求、因而自己拒签”与节点的截止保护共用同一个 D：SDK 的最后可签时刻通常只比 D 早不足 1 秒，
而节点在下一次维护（最多再 3 秒）就会清理请求并强关。若释放时机稍晚，SDK 看到的已经是“无需签名”，
它的拒绝就与节点的保护混在一起，无法归因。Gate2 只能三选一：把该行写成“不产生新的提交且节点进入保护”的合并观察、
用 SDK 日志/状态作为辅助证据并声明归因限制、或把该行留给 Rust 边界证明。本文件不预先决定。

### 明确的缺口：Hosted 侧链上取回

- 付款从“锁住”走到“最终失败并解除锁定”依赖链上 TLC 输出被真正花费并被 watchtower 记录：
  结算记录只由 [watchtower actor](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/watchtower/actor.rs#L1084) 写入，
  没有记录时判定为未知，超时集合也只收“已结算但无 preimage”的 TLC
  （[解析](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/onchain_tlc_reconcile.rs#L331)、[超时集合](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/onchain_tlc_reconcile.rs#L547)）。
- 上游 agent 在同一 SHA 已有独立链查询、preimage 释放与 watchtower 授权入口
  （`tests/fiber-lsp-sdk-agent/README.md`），但本地 `_sdk_driver.rs` 只接入 `open/invoice/fulfill/close/records/opening`，
  没有链上/watchtower 授权控制，SDK 会按“无授权”拒绝签名。因此本批**不能承诺**“钱包永久离线时 Hosted 一侧也会自动完成链上结算”。
- 结论：方向“保护启动后，钱最终怎样处理”在本批只能做到可观察的一半——
  截止保护启动、承诺交易上链确认、未交出 preimage、发票不为 `Paid`、付款不会因此变成成功；
  真正的链上取回与最终余额/费用核对，要么扩展本地驱动（用干净源码目录按同一 SHA 重新构建并更新清单摘要），
  要么另行评审 watchtower 专项。

### 归因要求（避免假通过）

- 公共节点在等待 ACK 30 秒后会以“对端无响应”强关，这与本批的 TLC 截止保护是两个来源。
  用例必须让 D 明显早于“承诺签名发出 + 30 秒”，并断言关闭发生在该 30 秒之前，才能把结果归给截止保护；
  同时检查待签请求被清理、承诺号未推进、使用的承诺与 `latest_commitment_transaction_hash` 相符。
- 强关启动失败时，现有实现保留待签请求和缓存更新；本批不通过篡改数据库制造失败，稳定外部故障入口明确前不承诺自动化此分支。
- 最近一次已应用签名的原样重试先走去重判断，不能一概归为“过期必拒绝”；通道关闭后的接口可达性另取决于状态。

### 已经查清的一项预期：不交 preimage 时的发票状态

托管租户的 hold 发票用 `payment_hash`（不带 preimage）创建，目标 TLC 完成承诺并处理完 ACK、进入结算判断时才置 `Received`
（[发票创建](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/rpc/invoice.rs#L315)、
[置 Received](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/settle_tlc_set_command.rs#L348)）。
失败或超时路径没有把状态写回 `Open`，而 `get_invoice` 只在存储状态仍为 `Open` 且发票自身已过期时才显示 `Expired`
（[状态映射](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/rpc/invoice.rs#L446)）。
所以“TLC 超时、发票自身未过期”的预期是 **`Received`**，且即使随后越过发票自身有效期也仍是 `Received`，绝不能是 `Paid`。
Gate2 必须写死这一条，不能沿用“Open/Expired 都可以”的写法；结算成功场景仍应写出 `Paid` 对照。

## 本批边界

- 没有未完成 TLC 时，不会仅凭等待签名的时长触发这里的 TLC 安全强关。
- 精确到期那一毫秒、维护与提交的严格执行顺序、全部签名转换组合、撤销惩罚及恶意 watchtower 授权不在本批 Python 范围。
- 不引入 MPP、UDT、并发支付、租户驱逐、重启与存储损坏；不使用修改宿主机时钟或篡改数据库的手段。
- 不放宽任何既有断言，不修改公共框架、模板、`AGENTS.md` 或 `Makefile`。

## 源码依据（固定到 `0f41d9a`）

- [开通是否允许中止](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L11507)、[当前适用的开通期限是否已到](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L11531) 及[过期事件重新判定](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L4295)。
- [两个开通计时窗口的默认值与 debug epoch 换算](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/config.rs#L94)。
- [存入未签注资交易时记录外部注资起点并排定计时](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L4081)、[钱包提交后清除起点](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L3940)。
- [节点支付截止计算](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L6375)、[生效条件](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L6386)、[提交路径检查](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L2232) 及[周期维护检查](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L4241)。
- [强关成功启动后才清理请求](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L3328)、[2/3 承诺延迟换算](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L5767) 及[到货 TLC 的最短期限校验](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L8578)。
- [对端无响应 30 秒保护](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/channel.rs#L155) 与[维护周期](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/network.rs#L251)。
- [SDK 安全预留](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lsp-sdk/src/commitment.rs#L51)、[承诺 TLC 时间检查](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lsp-sdk/src/commitment.rs#L346)、[授权区间校验](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lsp-sdk/src/commitment.rs#L486) 及[替代承诺恢复窗口](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lsp-sdk/src/commitment.rs#L690)。
- [设计文档：等待签名时的 TLC 安全截止时间](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/docs/notes/hosted-lsp-remote-signer.md#L549)。
- [Rust 截止场景的可控驱动](https://github.com/nervosnetwork/fiber/blob/0f41d9a1f1d20bd5b1fe35e0f249c4340019a073/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L1959)。

## 本批范围（已定）

| 决定项 | 本批采用 |
| --- | --- |
| 方向 | 按上表五条继续，不新增方向 |
| “保护启动后，钱最终怎样处理” | 只做到“截止保护启动 + 承诺交易上链确认 + 未交出 preimage 时发票不为 `Paid`”；链上取回、付款最终失败与最终余额/费用核对标注为能力缺口，不在本批断言 |
| 时间控制 | 使用短 TLC 期限与自洽缩小的 SDK 授权窗口；既有 16 条的期限与授权边界不变 |
| 支付侧 TLC 来源 | 由公共节点 T 通过 `dev_add_tlc` 注入指定 `expiry` 的 TLC；发票、SDK 授权与签名、截止保护、强关和上链保持真实。准备检查分三段：签名前只要求目标 TLC 与待签请求出现；“承诺含 TLC”在承载 TLC 的承诺已签、撤销签名待提交时检查，此时发票仍为 `Open`；发票 `Received` 要等撤销签名与 ACK 往返完成之后，并需要另一笔 TLC 提供待签请求。不满足算准备失败 |
| “钱包回来得太晚，SDK 还没签” | 合并观察：该请求不产生新的有效提交且节点进入保护，同时记录 SDK 侧证据；行内声明单独归因受限 |
| 不变项 | 不放宽任何断言；不改公共框架、模板、`AGENTS.md`、`Makefile` |

Gate2 在 `reviews/lsp/channel-signing-deadline.md` 给出逐项中文用例、具体时间控制和完整预期；本轮不新增或修改自动化和 TEST-MAP。

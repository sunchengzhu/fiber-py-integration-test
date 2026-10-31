# Gate2：Hosted watchtower 授权与无 TLC 结算

2026-10-29：用户已确认[实测反馈 Gate1](field-feedback-scope.md)。本次仅展开其方向 1/2 的 **Gate2：独立收款归属与目的地替换**，完整设计见[本次补充](#独立收款与目的地替换gate22026-10-29)。就地补强 `LSP-WATCHTOWER-01`，新增 05/06；02 只澄清其历史资金判据引用，02～04 的行为不扩展。用户已明确确认01/02/05/06行集、费用分配和预算，进入Gate3；当前只实现/验证843的05及旧02相关回归，01/06等待修复版。

旧共同前提将 D 定义为 T/sponsor 钱包，既有通过只证明已批准交易的签名、结算及守恒，**不证明 A 的资金回到独立用户控制的钱包**。旧01方法保留历史D=S断言，已移除它对新版01的过时TEST-MAP；新版01仍未实现，04/3ce 的历史结果及 #1706 陈旧请求修复证据保留原范围，不转记新 01 通过。当前只读分析固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；其独立收款正向有产品能力阻塞，不能用本地适配绕过。

2026-10-25 用户已通过 Gate2 并接受 02 分段验证边界。2026-10-27 用户批准隔离链合约修复后，预检阻断已解决；修正后适配自检通过，正式聚焦 4/4，通过后的首轮固定复跑 3 通过/02 失败，后两轮未运行。02 观察到服务端持续返回已死输入的陈旧待签请求，产品侧证据及恢复结论边界见 [最新运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-watchtower-隔离环境恢复与正式验证2026-10-27)。随后按用户要求独立诊断，已确认有效后继请求被旧首项遮蔽，显式批准后完整 240.356s 仍未恢复，属于 FNN 产品 bug，见 [02 最新归因](../../test_cases/fiber/devnet/lsp/README.md#04c2064-watchtower-02-陈旧请求遮蔽与批准后恢复诊断2026-10-27)。Gate3 稳定性验收未完成，02 仍不能标为原 Agent 自动恢复覆盖。历史 Gate2 分析保留。

历史批次范围（下文 04 的依据、预算、旧 01 步骤及适配说明保留；02～04 仍沿用）：用户已通过 [Gate1 三个方向](watchtower-settlement-scope.md)，本轮展开正常结算、未授权拒签后恢复、跨租户隔离。固定 FNN/SDK `04c206465b48da85b99aa58e80afe9801a2cb2db`；源码 checkout 干净，测试仓库基线 `cf937275618d8e51b35a7537788702cf4b67bc31`。保留已有改动与历史证据。本轮仅文档，不改自动化、驱动或产品，不启动节点。

**用户已接受、实现必须保留的边界：现有 devnet 无法直接安装进官方 agent 的固定 genesis 验证器。建议保留现有链，用局部驱动适配公开的 verified 签名入口；02 的负向是原 agent 真实拒签，正向是显式批准后经适配入口完成，不能声称原 agent 自动事件链的完整恢复。** 若要求同一原事件路径只改变批准状态，本方案的 02 尚不可执行，应另评兼容 genesis 环境或上游可配置 verifier 接口，不能在 Gate3 静默替换。

产品缺陷跟踪：`LSP-WATCHTOWER-02` 的陈旧请求遮蔽已由用户提交 [Fiber #1706](https://github.com/nervosnetwork/fiber/issues/1706)。2026-10-28 在明确修复提交 `3ce369e` 上重编并运行原 02，已自然命中旧 ID 小于新 ID、旧输入被 T 花费的条件，取得有效后继请求并完成真实结算；`1 passed in 363.48s`，GPT 6.1 sol 独立复核通过。见 [运行记录末尾的修复定点验证](../../test_cases/fiber/devnet/lsp/README.md)。这不覆盖原 Agent 自动恢复或全套 1+3 稳定性；04 的历史失败和诊断结果保留。

## 历史共同前提与接口（02～04 沿用）

- A 是 Hosted 租户，T 是公共 LSP，B 仅用于隔离对照。各用例使用新 Fiber 状态及独立 SDK 身份/存储；沿用现有 CKB 快照，不要求整个链按方法重置。A–T 为私有 plain CKB 通道，正常外部注资和开通，不制造付款或注入 TLC。
- 初始注资沿用 A/T 各 500 CKB 的夹具参数；以实际 funding 输出、双方余额与 SDK 已验证完整 recovery record 核对，A/T 的待结算金额均非零，零 pending TLC。强关前不重启/驱逐 FNN 或 SDK。
- 在开通前给 T 钱包准备额外、未被占用的 plain CKB sponsor cells，总容量至少 1,000 CKB；两个通道按需预留独立资金，不能在待签后让充值/其他测试消耗已引用输入。实际输入、找零和费用仍独立核算。
- 目的地址 D 是测试从本地 T 钱包配置/公钥推导的完整 secp lock，事先保存。批准的 `max_fee=10_000` Shannon 是**每笔待签交易全部输入输出之差**的上限，不是全通道累计限额或从 A 余额扣款的上限。实际费用超过时失败，不自动提高授权；不是产品固定费率契约。
- 通道延迟沿用 `commitment_delay_epoch=0x10000000001`（一个 epoch）；watchtower 保持模板的 60 秒扫描。独立读取真实 CKB epoch 分数与输入 `since`；SDK 开通使用的 2,000ms epoch 配置不能代替链上 maturity 判断。
- 真实 RPC 为 `get_watchtower_signing_status({channel_id})`、`submit_watchtower_signature({channel_id,request_id,signature})`；实际事件为 `watchtower_signing`。正常提交要求 FNN 首次接受为 `Applied`；若是相同实际重传导致 `AlreadyApplied`，必须已有该签名的真实首次 Applied 证据，不能只拿重复回执通过。
- 所有签名必须来自 A/B 自身真实 SDK。取得完整请求 R 时核对 `key_purpose=Settlement`、request ID 与完整 packed 交易字节的哈希、所属 node/channel、SDK 本地 source record 及独立链上输入。不得从 FNN 待签内容反推目的地址或提高费用批准。

## Spec

### SPEC-01：历史 D=S 判据下的授权结算与守恒（02～04）
Condition: 上述正常通道，T 的强关交易已确认、commitment 已成熟，A 已事先批准 D 与费用预算。
Expected: A 的真实 SDK 验证独立链证据后签署 Settlement；FNN 接受，A 对应份额上链，沿合法后继输出最终完成两方结算；逐笔资金与累计资金遵守下文公式。
Observable: 原 funding、SDK 完整已验证记录、关闭及结算交易、请求/签名/回执、独立 CKB 输入输出和 maturity、最终稳定窗口。
Basis: 用户通过 Gate1 的正常结算方向；[actor 构造与 sponsor 合并](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1612)、[SDK onchain 验证](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L63)。
Source: explicit
Testing: required

### SPEC-02：原 agent 拒签与适配入口批准后结算分别举证
Condition: A 的真实有效 Settlement 请求已到达，尚无本地 watchtower 批准；独立适配器的链/dep/输入前置检查正常，但原 agent 的私有 chain 未安装。
Expected: 原 Agent.handle_event 确实因缺本地批准拒签；完整负向窗口没有 A 签名或提交且 A 份额未结算。之后用原 Agent.authorize 写入批准，适配器读取该批准并调用真实 SDK verified 入口完成原通道。
Observable: 原函数的拒签记录、零提交审计、未结算份额、原授权 API 的持久化内容、适配签名与真实确认。原链未安装这一限制不能隐藏。
Basis: [原批准检查先于 chain 检查](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/agent.rs#L692)、[公开 verified 入口](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/agent.rs#L792)；Gate1 的恢复方向在本环境下拟采用分段证明。
Source: inference
Testing: required

### SPEC-03：跨租户读取与提交不能越权
Condition: A/B 均有真实注册身份和足够自身权限，A 的当前有效 SDK Settlement 签名已捕获且未提交；B 身份访问 A 的资源。
Expected: B 不能读 A 的待签内容，也不能应用 A 的真实签名；A 的正向处理可成功。B 的自身读/写正向对照证明拒绝并非无效 token、权限不足或错误签名。
Observable: 同一版本的 R/S、B 自身正向结果、B→A 原始错误、操作前后 A 工作及链状态、A 真正 Applied 与资金结果。
Basis: 用户通过 Gate1 的隔离方向；[RPC 按授权 node_id/channel_id 取记录并验签](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L395)、[Biscuit 方法权限](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/biscuit.rs#L196)。
Source: explicit
Testing: required

### SPEC-04：独立收款正向必须同时证明金额与所有权
Condition: A–T 私有 plain CKB 通道、双方非零份额且无 TLC；D_A 是开通已绑定且由 A 控制的 shutdown lock，S 是 T 的费用钱包，D_A≠S；产品已具备分别表达和验证二者的能力。
Expected: A 只批准 D_A 作为自身收款地址；真实 SDK 签名被 Applied 并用于链上 A 支出，A 合法应得份额进入 D_A，T 份额及 sponsor 费用按独立账本核对；两方各结算一次并稳定至少 65 秒。采用用户已确认的本补充费用分配——沿用合法先后顺序分摊强关费，T 以 sponsor 资金承担结算费，不从 A 已确定份额扣除结算费。
Observable: 原开通意图、完整 recovery record、独立 D_A/S 归属、预先批准、真实 R/S/Applied、committed 输入输出/witness、逐方应得值与 outpoint 账本、稳定观察。
Basis: 已确认的实测反馈 Gate1 方向 1；[当前 actor 使用 fee-provider 输出](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/watchtower/actor.rs#L1786)暴露旧判据缺口；本补充的费用承担是待确认验收提案，不宣称当前产品已经支持。
Source: inference
Testing: required

### SPEC-05：独立批准不能为真实错付候选产生签名
Condition: A 的固定批准为 D_A，真实 843 工作却把 A 份额并入 S 输出；请求、祖先、maturity、record、deps、费限和输入 live 均可独立验证，额外输入确属预先确定的 S。
Expected: 原 SDK 拒绝该真实候选，不产生或提交 A 的 Settlement，至少 65 秒观察中 A 份额未解锁；记录最先拒绝层级。sponsor 与 destination 不兼容的拒绝仅证明该候选未通过，不算输出目的地校验或独立收款正向通过。
Observable: 未改写的真实请求、D_A 批准、S 输入/输出、原 SDK prepare 拒绝、SDK 状态与提交审计、A 未解锁及 T 合法后继证据。
Basis: [SDK sponsor 限制](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L256)先于[输出目的地校验](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L345)；当前本地适配也先检查 sponsor，必须区分适配拒绝与原 SDK 拒绝。
Source: observation
Testing: required

### SPEC-06：金额与费用守恒不能掩盖 payout 被替换
Condition: 已有原 SDK 在固定 D_A/S 授权下 prepare 成功的自然候选；固定授权及所有控制量，只将一个支付 A 的输出 lock 替换成 S 或独立第三方 D_X，逐个 check-only。
Expected: 两个变体均被原 SDK 在收款归属约束处拒绝，原样对照仍可 prepare；不调用任何签名或提交入口，SDK 签名历史、revision/nonce 和存储不变。原样对照失败或先被其他约束拒绝时不计本行为通过。
Observable: 原请求来源、原样/变异 content 与 SDK 重算摘要、完整不变的授权、字段差异、原 SDK 拒绝层级、状态前后摘要、零 sign/submit 审计。
Basis: 已确认的 Gate1 方向 2；[prepare_onchain](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/signer.rs#L1007)是只验证入口；原本地 wrong_destination 修改的是授权，不满足本行的单变量要求。
Source: inference
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 真实结算与资金
  - A 只批准独立 D_A，真实到账且 sponsor 与费用分开核算：LSP-WATCHTOWER-01 [primary] -> SPEC-04
- 独立批准的拒签边界
  - 真实候选付往 S，原 SDK 拒签且不产生 A 支出：LSP-WATCHTOWER-05 [primary] -> SPEC-05
  - 固定原授权，仅替换合法候选的 A payout lock，check-only 拒绝：LSP-WATCHTOWER-06 [primary] -> SPEC-06
- 本地批准
  - 原 agent 无批准拒签，明确批准后经独立验证适配入口完成：LSP-WATCHTOWER-02 [primary] -> SPEC-01、SPEC-02
- 租户隔离
  - B 自身读取成功但读取 A 工作失败，A 正向完成：LSP-WATCHTOWER-03 [primary] -> SPEC-01、SPEC-03
  - B 自身真实提交成功但提交 A 有效签名失败，A 应用原有效签名并完成：LSP-WATCHTOWER-04 [primary] -> SPEC-01、SPEC-03
<!-- TEST-TREE-END -->

独立钱包取回现纳入新 01，但尚未实现或验证；A/B 共享 sponsor 并行结算、原存储恢复、含 TLC 兑现/退款和撤销惩罚仍在本批范围外，入口保留在 Gate1。

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-WATCHTOWER-01` | - [ ] A/T 双方非零份额、无 TLC 的私有 CKB 通道中，A 只批准自己开通时绑定的 D_A，D_A≠T 的 sponsor 钱包 S；T 强关，真实成熟后由 SDK 经独立链验证签名 | 按已确认的本补充费用分配，A 的合法应得份额全部进入 D_A，sponsor 输入、T 份额及费用独立守恒；A 签名真实 Applied 并用于该支出，两方各结算一次且终态稳定至少 65 秒 | 钱仍守恒但 A 份额进入运营方钱包，或把 sponsor 总余额当用户所得 | P0 |
| `LSP-WATCHTOWER-02` | - [x] 沿用历史 D=S 判据的 A/T 非零份额、无 TLC 私有 CKB 通道中，不授予 A 本地 watchtower 批准；取得有效请求及原 Agent.handle_event 的缺批准拒签后观察至少 130 秒，再调用原批准 API 并经适配入口完成原通道 | 已确认分段验证边界；批准前 SDK 不产生/提交 A 的 Settlement，A 份额未结算；明确批准后真实 SDK 验链、签名及资金终态满足历史 D=S 共同判据，不扩展为独立收款，也不宣称原 agent 自动事件链仅补批准即可恢复 | 测试驱动自行拦截被误算成 SDK 拒签，或绕过本地批准直接调用 verified 入口却宣称完整授权恢复 | P0 |
| `LSP-WATCHTOWER-03` | - [x] A/B 自身 watchtower 查询均成功；T 强关 A 后，捕获并扣住 A 对当前有效 Settlement 的真实签名，用 B token 读取 A 的同一 channel，再用 A 处理该工作 | B 读取失败且未返回 A 请求内容；操作前后 A 当前工作及可用输入未被 B 改变；A 的真实提交、结算与共同资金断言通过 | 跨租户泄露签名上下文，或因 B token 无效/无权限而取得假阳性 | P0 |
| `LSP-WATCHTOWER-04` | - [x] 先让 B 在自己的通道上真实提交有效 Settlement 并完成结算作为写权限对照；再取得 A 通道当前有效请求和扣留的真实 SDK 签名，用 B token 原样提交 A 的 channel/request/signature，随后由 A 提交 | B→A 提交失败，A 原工作不被应用或替换；A 提交同一仍有效签名真实 Applied 且结算守恒；不能用错误签名、过期请求或 AlreadyApplied 代替身份隔离 | 租户身份未参与签名提交路由，或缺少合法写权限/有效签名对照而错误判定隔离成功 | P0 |
| `LSP-WATCHTOWER-05` | - [x] A 只批准独立 D_A，在当前 843 的真实有效 Settlement 工作把 A 份额付往 S 时，以原授权和真实链证据调用原 SDK 验证并观察至少 65 秒 | SDK 拒签且无 A Settlement 签名或提交，A 份额未解锁；明确最先拒绝层级，sponsor 限制拒绝不算输出目的地校验或正向取回通过 | 为凑结算成功批准运营方收款，或把夹具提前拦截冒充 SDK 目的地防护 | P0 |
| `LSP-WATCHTOWER-06` | - [ ] 独立 D_A/S 授权下的自然候选先通过原 SDK prepare；保持原授权、输入、金额、费用等不变，仅将 A payout lock 分别换成 S、独立 D_X，逐个 check-only | 两个变体均因收款归属约束拒绝，原样对照仍可 prepare；全过程不签名、不提交，SDK 状态不变；无有效原样对照或更早拒绝均不得记通过 | 金额守恒掩盖错付，或用修改批准、陈旧摘要及其他校验拒绝取得假阳性 | P1 |
<!-- TEST-CASES-END -->

02～05存在TEST-MAP；新版01/06未映射，旧01方法仅保留历史D=S验证。复选框只表示映射存在，所有旧通过仍只对应历史D=S判据。02 的引用调整仅固定其原意，03/04 不变；四项历史执行与本次未运行须分开。

## 历史分阶段时间预算（02～04 沿用；新 01/05/06 见补充）

所有阶段使用单调时钟绝对截止；单次 HTTP/CKB RPC 不超过 10 秒且不得超过阶段剩余预算。查询常规间隔 1 秒，负向/稳定采样间隔至多 2 秒，记录实际最大间隔；异常阻塞不能只延长 sleep 掩盖。所有请求、SDK 控制和挖块也受总截止限制。

| 阶段 | 上限/下限 | 计时与超时归因 |
| --- | --- | --- |
| 独立链/合约预检 | 最多 60 秒 | 已有测试链可访问起核对；需要启动链的时间计入准备阶段。可信配置、字节或链证据不符是环境/适配失败，不算用例通过 |
| 节点、身份、资金和通道准备 | 最多 300 秒 | 含类级 CKB 启动和每条新 Fiber/SDK 启动、A/B 开通、完整记录及 sponsor 资金检查；串行消耗同一截止 |
| 每个通道 T 强关并确认 | 最多 120 秒 | 单次 force shutdown 起，独立核对真实 committed、唯一 funding 输入、原 commitment 输出和 canonical block；不广播自制替代交易 |
| 成熟与索引就绪 | 最多 180 秒 | 上一步确认起；挖真实块/epoch 并重读头与精确 outpoint 花费索引，直到实际相对 epoch/since 满足，不修改时钟或链参数 |
| 取得当前有效工作 | 最多 180 秒 | 成熟且索引就绪起，覆盖两个 60 秒扫描周期加余量；收到真实 watchtower 事件并核对 SDK/链证据，03/04 还需拿到扣留的有效签名 |
| 02 未批准观察 | 至少 130 秒，采样收尾最多 10 秒 | 有效工作、原 agent 缺批准错误、A 零提交及链前提齐全后起算；覆盖两个完整扫描间隔加余量。140 秒内不能完成则失败，不缩短观察 |
| 02 明确批准 | 最多 30 秒 | 原授权 API 与持久化核对；不更换身份、通道、金额、目的地址或费率上限 |
| 03/04 跨租户操作窗口 | 最多 30 秒 | 操作前再核 R/S 与输入 live；记录 B 请求/响应和 A 前后状态。竞争造成输入失效不能算身份拒绝通过 |
| 已批准工作至两方结算确认 | 最多 240 秒 | 01 从首次有效工作起；02 从批准完成起；03/04 从跨租户窗口结束放行起。包括重新取当前工作、真实提交、后续扫描/广播和两方确认 |
| 终态稳定 | 至少 65 秒，收尾最多 10 秒 | 两方结算确认且 indexer 追平后起；跨一轮 60 秒扫描观察，无新的 A 份额重复支出或资金变化；不声称证明无限未来稳定 |
| 证据保存和清理 | 最多 60 秒 | 成功、失败均保存原始证据并清理本批节点，不删除历史报告 |

保守总上限（包括清理）：01 **1,260 秒**，02 **1,440 秒**，03 **1,320 秒**，04 **2,100 秒**。01 基本阶段含收尾合计 1,215 秒；02 再加 140+30 秒为 1,385 秒；03 加 30 秒为 1,245 秒；04 在 03 上再加 B 独立正向流程的 795 秒为 2,040 秒。剩余仅用于阶段交接，不授权阶段超时自动续期。这是本地功能测试上限，不是产品性能 SLA。

首次原始请求若被 T 的合法份额结算抢先消耗，允许在“取得工作/已批准结算”的原截止内至多三轮重新取当前工作、独立验链和重新生成授权/签名；不重新开通、不改变资金预期、不增加成功次数。每轮保存 R、输入 live 状态、SDK 拒绝、T 支出及新请求证据。03/04 的 B 操作必须落在有效且未应用的同一 R/S 上；若窗口内失效，该次不能计隔离成功，有限重建检查点仍无法取得时报告“场景未取得”，不是产品恢复通过。

RPC 持续只返回已死输入的旧工作时，不跳过它从数据库挑新请求、不删除节点 signer 状态；到期保留为产品/接口候选问题。Hosted 关闭识别的 300 秒扫描不作为本批 Settlement 判据，也不手动调用 `check_channel_shutdown` 加速。

## 历史 D=S 共同资金与签名断言（02～04 沿用）

### 1. 锁定原通道与强关承诺

强关前保存 funding outpoint、双方余额/保留容量、SDK 已独立验证的 recovery records（A 的本地承诺含本地聚合签名；T 将广播的远端承诺不要求 A 存有聚合签名）。T 广播的真实 committed 承诺必须唯一消费该 funding，按 `compute_tx_message`（清空广播时 deps 后的签名消息）匹配 A 的对应本地 record，并独立核对广播 FundingDeps；不能凭相同 channel ID 或同钱包认定祖先。

记实际 funding 输出容量为 `C_fund`、原承诺输出容量为 `C0`。本批要求原强关交易只有该 funding 输入和一个 plain CKB commitment 输出，故 `F_close = C_fund - C0 >= 0`，单列记录并按已批准 commitment fee rate/实际序列化大小核对。签名记录中的 `M_A/M_T` 必须与强关前余额加各自 reserved 一致，且 `M_A + M_T = C_fund`、两者非零；方向由 record.for_remote、settlement 公钥及 witness 侧位共同决定。

**`M_A/M_T` 已包含 reserved，不能再加一次。** 依据 [channel.rs:11580](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/channel.rs#L11580)。最后一方得到当前剩余 capacity；强关费已经从 `C0` 扣除，不能要求双方都恰好取回开通时的 500 CKB，也不能重复扣强关费。

### 2. 逐笔账本和后继状态

对原 commitment 及每笔合法后继结算建立有序链 `C_i → C_(i+1)`，每笔独立解析：

- `C_i`：被花费的当前 commitment 容量；`S_i`：所有额外 sponsor 输入容量之和（输入由独立 CKB 解析，type 为空、data 为空、lock 必须是批准的 D）。
- `R_i`：唯一合法后继 commitment 容量，最后一次必须为 0 且没有后继；`D_i`：本笔所有批准地址输出容量之和，含合并的 sponsor 找零，不等同 A 的收入。
- `F_i = C_i + S_i - R_i - D_i`：真实总交易费，非负。A 签名的每笔均要求 `F_i <= 10_000` 且等于本地 exact authorization 的 fee；T 本地签名交易也记录总费用，并按本批相同的测试预算及实际结构检查，不能偷偷归到 A 的批准里。
- `P_i = D_i - S_i + F_i = C_i - R_i`：从 commitment 转出的份额。不是最后一方时 `P_i = M_party`；另一方已经清零时 `P_i = C_i`。根据 live input 的已验证 settlement witness 识别实际一方，不能凭输出地址区分 A/T（两者可能同为 D）。
- 对非最终支出，后继 lock 的 code_hash/hash_type、前 36 字节、feature bitmap 不变；结算 witness 只清零已解锁一方并相应更新 body hash/settled 标志，另一方公钥和金额保持，TLC 数始终 0。容量正好为 `R_i`，type/data 正确，不能接受任意相似地址的“后继”。
- 最终两方各解锁一次、无剩余 commitment：`sum(P_i) = C0`，`sum(D_i-S_i) + sum(F_i) = C0`，再加 `F_close` 得 `C_fund`。sponsor 输入即使复用前一笔输出，也按该笔实际输入计入，不能用共享钱包总余额替代。

完整 SDK 断言依据 [onchain.rs](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L125)。Python 需自行核对实际输入输出、整数资金公式、解锁顺序和非零份额；不能只读取 SDK 的“成功”布尔值。SDK 可导出自己已验证的公共 record/witness 解码材料，不能泄露或使用私钥重签来制造成功。

### 3. 证明 A 的签名真正被用于该笔支出

保存原 R、SDK 生成的 65 字节 S、真实 FNN Applied、最终 committed 交易。最终 raw transaction 的输入/输出/deps/since 与实际被使用的 R 一致；结算 witness 中 A 的解锁签名与 S 对应（FNN 填写该签名和 sponsor witness 的位置可以变化，不能要求 unsigned/full signed 交易字节相同）。核对恢复的公钥为 A 该 record 的 Settlement 公钥，解锁一方确为 A；原 commitment 仅被 T 花费不够。

允许有旧 R 被链状态替代，但至少有一份属于 A、被真实接受且实际用于最终已确认 A 支出的签名。终态沿祖先链确认 A/T 各已解锁、索引追平并稳定 65 秒；pending 状态完整保存，不把 `NoSignatureRequired` 或 `Closed` 单独当资金成功。过期 pending 残留另记观察项，若阻塞当前有效工作则按预算失败，不宣称已排除产品问题。

## 历史四条执行步骤（02～04 沿用；01 由本次补充替代）

### LSP-WATCHTOWER-01：正常授权结算

1. 完成独立链/dep 预检，正常开通 A–T，保存完整记录、资金基线与 D/10,000 的预先意图；调用原 `Agent.authorize(Watchtower)`，核对持久化批准。A 的 watchtower 提交门禁为透明转发。
2. T 调用一次强关，独立确认原 funding 支出；推进到实际 maturity 和索引就绪，等真实 watchtower 事件。适配器只处理真实事件/查询工作，按原批准构造 exact authorization，再调用真实 SDK verified 入口。
3. 不强制 A/T 谁先结算；当前工作因 T 先花费失效时，按有限轮次重新核对实际后继。记录 A 的 Applied 与对应链上签名。
4. 跟踪至两方全部结算，执行逐笔/累计资金与 witness 断言，再完整观察稳定窗口。

### LSP-WATCHTOWER-02：真实拒签与显式批准后适配结算

1. 正常开通但不授予 watchtower 批准；证明本地批准文件中没有 A 记录，签名 gate 透明转发、不以门禁阻止越权提交。适配链预检通过，冻结 D/10,000 的待批准意图。
2. T 强关、成熟后，真实 watchtower 事件交给未修改的 `Agent.handle_event`；保存其缺本地批准错误、请求、零签名提交审计。若只是缺 ChainVerifier/输入无效错误，不算取得拒签检查点。
3. 从检查点连续观察 130 秒以上：A SDK 未产生/提交 Settlement，A 对应份额尚未解锁；允许 T 合法结算自身份额并转为后继。起止均核对当前有效工作和份额，期间记录原 agent 的处理结果；若旧请求阻塞且无法证明有效工作，不能用空等通过。
4. 原 `Agent.authorize(Watchtower)` 持久化同一意图；显式调用适配的“处理当前 watchtower 工作”控制入口。重新读真实状态，验证当前输入、祖先和费用，再走公开 verified 签名接口；不要求自动重连或无控制调用恢复。
5. 原通道两方结算并满足全部资金/稳定断言。结论分别写“原 agent 前置批准检查拒签”和“批准后适配 SDK 结算通过”。原 agent 私有链未安装，因此**不是只缺批准的同路径单变量恢复试验**，这是本次待确认的证明边界。

### LSP-WATCHTOWER-03：跨租户读取

1. A/B 各自正常开通，B 用自身 token 读取自身 watchtower 状态成功；A 预先批准，T 强关 A，取得 A 的真实 Settlement R/S，gate 扣住 A 的提交并记录未转发。
2. 等当前 R 输入仍 live，核对 SDK 签名/所属公钥；记录 A 状态和链输入，用 B token 查询 A channel。要求实际 RPC 错误且没有 A 的请求内容，不绑定非契约错误措辞。
3. 查询前后 A 的同一 R 未被该操作应用或替换，原签名仍可用。若 T 竞争使输入失效，此次不算身份隔离成功；在原阶段预算与最多三轮内重新建立有效检查点。
4. 由 A 原身份提交仍有效签名并放行后续工作；核对 Applied、真实 A 支出及两方资金终态。B 自身资源仍可读，B 通道无需强关。

### LSP-WATCHTOWER-04：跨租户提交

1. A/B 正常开通后，**先**完成 B 通道自己的授权、强关、有效 SDK Settlement 提交 Applied、两方结算和稳定观察，证明 B token 能执行同一写 RPC。此时尚未强关/扣签 A，不据此验收并发隔离。
2. T 再强关 A，取得当前 live 请求 R 和 A SDK 真实 S，A 提交被 gate 扣住且没有首次 Applied。保存 A 前态与 SDK 签名校验材料。
3. 用 B 的原 token，完整不变地提交 A 的 channel/request/signature；要求 RPC 失败，A 的 R/S/输入和应用状态不被该请求改变，不使用随机或截断签名。
4. 立即用 A token 提交同一仍有效 S，要求首次 Applied 并跟踪其实际链上使用；若发生自然失效则保存该次并按有限轮次重建检查点，不能把“签名已过期”当跨租户拒绝通过。
5. A 两方结算、资金及稳定窗口通过，B 已完成的链上结果不变；两个通道资金台账分开，不用共享 sponsor 钱包总余额判断。

## 独立链验证适配方案（仅设计）

### 现有入口为什么不能直接换用

官方 [Agent.configure_chain](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/agent.rs#L429)只能构造具体 DevChain，私有 chain、watchtower_authorization 和 sign_watchtower_status 没有通用注入接口。[DevChain.settlement_deps](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/chain.rs#L96)要求 genesis 5/6/7 的 auth/funding/commitment 字节与本地合约一致。

当前 `FiberTest` 使用 `CkbNodeConfigPath.CURRENT_TEST` 和既有快照，配置来自 [v118 dev spec](../../source/template/ckb/v118/specs/dev.toml)；其标准 system cells 不包含上述三份 Fiber 合约。[FNN 模板](../../source/fiber/dev_config_3.yml.j2)使用 FundingLock/CommitmentLock Type ID 部署项和独立 auth outpoint。不能照搬另一份 `CURRENT_FIBER` genesis 模板、伪造 RPC genesis 或悄悄重建链；运行时预检仍须核对实际 snapshot，不能仅信模板。

### 最小本地改动边界

Gate3 拟仅扩展 LSP 目录的 Python 用例/gate、`_sdk_driver.rs` 及同目录一个独立链适配模块，并让现有构建脚本纳入该驱动源码和必要依赖/摘要。修改前另存当前 04 版驱动产物与清单，旧运行结果仍绑定原摘要；FNN/SDK/合约 checkout 不改。这个 Rust 适配用于让 Python 调用真实 SDK，既不是新增 Rust 压力测试，也不是修改 SDK 实现。

- 增加显式 `watchtower-authorize` 控制，调用**原** `Agent.authorize(FixtureAuthorization::Watchtower)`；从其实际持久化 `watchtower-approvals.json` 读取同通道 D/max_fee。不同身份的 policy/存储不复用，未批准时不得启动 generic 签名路径。
- 增加当前工作处理入口及只读 record 导出：来源为真实 RPC/WS 和真实 SDK 存储；导出完整已验证 public settlement 数据/交易/reference/公钥，支持 Python 独立资金判断。精确 OnchainSpendAuthorization 不由 Python 随意传入，而由适配器读取固定批准和可信链数据构造。
- 正向使用公开 `Agent.poll_watchtower_verified(channel_id, authorization, chain)`，保留真正的 SDK prepare/confirm、独立验证和真实 RPC 提交。该函数会再查询当前 status；若与构造授权时的 R 不同，不放宽授权，记录拒绝并在既定次数/截止内重新核对。
- watchtower 事件路由：未批准时交给原 `Agent.handle_event` 取得真实拒签；已批准时调用上述适配流程。普通 channel_signing 仍走原处理。该路由和 policy 读取属于测试夹具，**不证明原 agent configure_chain + 自动事件链的正向兼容**。02 必须明确分段证据；不以驱动自身 `if` 的错误字符串冒充原函数错误。
- gate 增加 watchtower 查询/提交审计与按 node/channel/request 扣留真实签名。01/02 不扣提交，03/04 只扣 A；真实上游返回错误/回执原样记录，不伪造产品 Applied。SDK 日志、control、HTTP/WS、CKB 查询和交易都落入每轮独立证据目录。

### 可信合约与 deps 从哪里来

1. 强关/签名前，从仓库本地受信模板取得 Funding/Commitment Type ID 完整脚本与 auth outpoint，从现有本地 `source/contract/fiber/{auth,funding-lock,commitment-lock}` 取得预期合约字节；记录原文件摘要。不能使用 FNN `node_info` 或待签交易的 deps 作为信任来源。
2. 通过直接连接的独立 CKB RPC/indexer 对 Type ID 做 exact 查询，要求唯一 live cell；核对 cell 的 type script hash 与预设 code_hash、数据字节与本地合约一致、部署交易真实 committed 且位于 canonical block。auth 的固定 outpoint 同样独立核对。没有匹配/多个匹配/字节不符/索引落后到超时均失败，不选择“看起来像”的 cell、不自动部署或升级合约。
3. secp dep-group 来自独立 CKB genesis 的标准 sighash dep-group，解析其成员并核对本地可信 chain spec 的标准脚本/数据依赖，不能取待签交易给的 group。冻结有序 `FundingDeps=[funding,auth]`、`SettlementDeps=[commitment,auth,secp dep-group]`，与该版本构造顺序核对；SDK 要求 exact deps，不靠集合近似匹配。
4. 本批不升级 Type ID cells；签名前确认依赖仍有效，变化即停止。原始 CKB 响应、部署/包含区块、预期字节摘要和最终有序 outpoint 列表全部留证。snapshot 与本地合约若不一致，归为环境前置未满足并交用户处理，不能批准节点当前返回的任意字节。

### ChainVerifier 的实现与不能省略的检查

使用 `DevChain::new(独立 CKB URL)` 委托其公开 trait 的 `live_cell`、`verify_maturity`、`median_time_ms`，保留真实 RPC 的 live/data、block/epoch/absolute timestamp since、epoch 分数和 median-time 规则；relative timestamp 按原实现拒绝，不宣称支持所有 since 类型。不调用其硬编码 genesis deps 入口，也不能委托未配置 funding_deps 的旧 lineage（模板签名 hash 不一定等于广播 tx hash）。

本地适配实现 `verify_commitment_lineage`，保留原 [DevChain 祖先与 canonical 验证](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/chain.rs#L54)：

- 每笔祖先须 committed，原始交易重算 hash 等于 RPC hash；对应 header 仍为该高度 canonical block。输入/输出 0 的连续链、同 commitment code_hash/hash_type/type、前 36 字节及 feature bitmap 连续，后继 settled 标志合法，最多 128 层且受阶段总截止限制。
- 终止于本租户 SDK 已验证完整 recovery record 的 source；接受实际 tx hash 或匹配其 `compute_tx_message` 的广播交易时，都核对预先独立解析的 FundingDeps 及原 funding outpoint，不接受仅 hash 相似的不同通道。
- SDK 原 `onchain::validate` 仍二次检查 live input、maturity、依赖、witness body hash、原 signed snapshot、解锁归属、后继输出、准确金额和费用。适配器不自己生成签名或提供永真 ChainVerifier。
- 从批准的 D/max_fee 与独立 live inputs 生成 exact authorization：遍历本租户已验证 recovery records 找唯一合法 ancestor；不以本地 `complete_signature` 过滤远端承诺，完整广播签名的有效性由真实 canonical 链确认佐证；所有额外 input 必须是 D 的无 type/无 data plain CKB，去重并保持交易顺序；独立累加输入/输出得实际 fee 并检查 cap；deps 只用冻结的可信列表。不得把 LSP 提供的 source、fee 或输出地址直接作为批准。

Gate3 在进入产品场景前必须验证适配器会拒绝：非 live 输入、非 canonical/错误 hash 祖先、无关 channel/非法后继、未成熟 since、错误 deps/字节、不批准的 sponsor/destination 和超 cap。优先复用上游校验，通过 Python 驱动只读调用验证接口做确定性负向检查，不广播攻击交易、不另建 Rust 测试套件；这些是适配自检，单独记录，不能当四条产品用例已通过。适配失败时不运行或不计产品场景成功。

## 证据、失败分类与门禁

每轮保留固定源码/产物/驱动摘要、实际命令退出码/JUnit、预检、完整 RPC/WS/SDK control、批准前后文件、R/S/回执、签名和交易关联、祖先/成熟/indexer 原始响应、逐笔账本和连续观察日志；成功与失败均独立目录，不覆盖历史。

区分环境/适配前置失败、未取得有效 R/S 场景、预算内产品行为失败及成功。测试问题可修复后重新运行并保留之前结果；产品问题不改产品，保存具体 request/transaction/block 与源码路径交用户。不能通过删除资金断言、无限重试、重发业务、放宽 fee 或换地址消除失败。

Gate2 交接时四行均未映射、未运行。以下为当时评审要求：请评审四行、上述预算与资金公式，以及 **02 分段证据边界、局部 Rust ChainVerifier/驱动适配、独立合约预检**；这些一并明确通过后才进入 Gate3。若不接受 02 分段证明，先保留其未解决范围并另评环境/API路线，不把它标成完整恢复已覆盖。

2026-10-24 GPT 6.1 sol 已独立复核实际四行、步骤、预算和适配方案，并逐项对照固定源码的 deps 顺序、reserved 金额、for_remote 解锁方向及最终份额计算，未发现阻断项，未触发 Daybreak。已采纳其建议，明确 relative timestamp 不受现有 DevChain 支持；02 的分段边界仍需人工确认，复核不代替用户批准或执行结果。

本轮文档检查：`python3 scripts/check_test_map.py` 输出 `review cases: 97`、`automated cases: 89`，四条新用例均未映射，退出 1，原因仍为既有 `PMP-01～05` / `SETTLE-01` 孤儿映射及历史 report overlay 的 16 个重复 ID。`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/watchtower-settlement.md` 输出 `cases: 4`，退出 1，报告相同历史重复 ID及 02/SPEC-02 的明确待确认边界，无本批新增结构错误。`git diff --check` 退出 0。未运行 watchtower 测试，不把旧版或最小兼容回归计入四条结果。

2026-10-27 执行修正：用户批准仅在本批隔离 devnet 工作副本中更新 CommitmentLock 至固定 04 字节，原快照不变。自检发现原说明把已验证 recovery record 与本地聚合签名混淆：固定 SDK `lifecycle.rs::complete` 仅在持有 peer partial 时保存聚合签名，`signer.rs::prepare_onchain` 不要求此字段。修正 Python/Rust 本地过滤，保留 T 真实强关、唯一已验证记录、规范化消息、原 funding、可信 deps、canonical 确认与全部资金断言；不伪造或补写 SDK 记录。四条行为行及 02 分段边界不变，GPT 6.1 sol 已核对这一修正依据。实际执行结果见运行记录。


## 独立收款与目的地替换：Gate2（2026-10-29）

### 本次输入、版本与验收边界

只展开已批准 Gate1 的方向 1/2。复用原 ID 01 补强独立所有权，新增 05（真实错付候选拒签）与 06（固定授权下单变量替换）；本轮02～04及退款夜跑不重写、不执行；未来获批Gate3在当前843拟仅跑旧02一次作相关回归，03/04和退款不纳入。Gate2交接时01仍为旧映射；Gate3将其移除并为05建立真实映射。01/06尚不实现，执行结果另记本轮记录。

当前 PR head、源码与已有 FNN 均为 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，FNN 自报 `fnn Fiber v0.10.0-rc1 (84333ee 2026-10-28)`。源码/同源 SDK 及合约字节仍须在未来执行前重新核对，产物准备写新目录，不覆盖订阅过滤或旧 watchtower 证据。当前 actor 将份额与 sponsor 资金合并到 S；SDK 要求辅助输入和非后继输出都属于唯一 destination，因此 **843 只能安排 05 的一次有限诊断，不能承诺 01 或 06 通过**。未来实际修复 SHA、API 和合约须重新核对 diff 并获明确版本批准；本设计不授权切换版本、实现产品修复或自动启动未来批次。

- 复用 `_lsp_test.py` 中真实租户 A 的 `shutdown_script` 作为 D_A；它已用于 open/funding 绑定。S 从 T 本地钱包公钥推导。完整 lock 与 key 归属独立核对，要求 D_A≠S；D_X 为另外一个独立 secp lock，三者两两不同。私钥不写报告，不能从待签输出反推批准。
- A/T 各 500 CKB 开通参数、双方非零份额、无付款/TLC；完整 verified record 与资金基线必须匹配。T 额外准备至少 1,000 CKB plain sponsor cells。禁止 D_A 资金充作辅助输入，禁止无关业务同时使用 S 输入。
- A 原 `Agent.authorize` 保存 D_A 与每笔 `max_fee=10_000` Shannon。另从独立本地配置冻结 sponsor S、plain CKB 限制及费用承担意图；**这份夹具意图不等于产品已支持双地址授权**。843 的诊断只送原 SDK prepare，绝不据此启动签名；未来须映射到修复版真实授权接口，不能擅自扩展原单 destination 的含义。
- 仍用一个 epoch 的原通道延迟、真实 CKB maturity、60 秒 watchtower 扫描和可信 deps；不加 VM、不改时间、不改产品或快照，不广播自制交易。强关祖先、签名真实使用及后继状态沿用上文独立验证规则。

### 费用分配提案与独立资金断言

**用户已确认的验收费用分配（不代表产品已支持）：** 本批沿用现有强关分配规则：非最终解锁方领取已验证 record 的 `M_party`，最终方领取剩余 commitment capacity，故强关费由最终方的份额承担；`M_A/M_T` 已含 reserved，不再追加。T 的 sponsor 资金承担后续结算交易费，A 已按此规则确定的应得份额不得再扣结算费。不要求 A 无条件收回整笔初始 500 CKB，不用隐藏补款补足差额。如产品选用其他费用契约，先修改本行及公式并重新确认，不能在执行中适配掉差异。

设 `C_fund` 为原 funding 容量，`C0` 为真实强关 commitment 容量，`F_close=C_fund-C0`。冻结 `M_A+M_T=C_fund`，按真实 witness 解锁顺序从 record **预先推导**两方合法应得值：先解锁方为 `M_party`，最终方为 `C0-M_first`；须为正、两方和为 C0。不得仅把实际输出命名为应得值，否则少付也可“守恒”。两种合法先后顺序都按同一规则核算，不为凑某顺序重复开通或重跑。

每笔 i 从独立链取得：当前 commitment `C_i`、合法后继 `R_i`（最终为 0）、S 的辅助输入合计 `I_i`、支付 D_A 的输出合计 `U_i`、支付 S 的输出合计 `W_i`。只允许合法后继、D_A 和 S 三类输出，type/data 均按 plain CKB 规则校验；不接受第三方或额外业务输入/输出。定义 `P_i=C_i-R_i`，`A_i=P_i` 当且仅当 witness 证明本笔解锁 A，否则为 0，并独立要求 P_i 等于该方上述合法应得值。实际费用 `F_i` 按全部输入输出之差计算：

```text
C_i + I_i = R_i + U_i + W_i + F_i
U_i = A_i
W_i - I_i = P_i - A_i - F_i
0 <= F_i <= 10_000 Shannon
```

A 解锁时 `W_i=I_i-F_i`；T 解锁时 `W_i=I_i+P_i-F_i`，因此 S 的输出可能兼有 T 份额和找零，不能全叫找零或全算收入。A 签名交易的实际 fee 还须等于 exact authorization；T 自签交易按同一测试费限核对，但不冒充 A 的授权。输出容量必须满足实际 occupied capacity，sponsor 不足、费限超出或无法分离不扩大批准。

最终要求两方各解锁一次、没有剩余 commitment，并按实际 outpoint 消除 S 输出再次作为下一笔输入的影响：

```text
sum(P_i) = C0 = P_A + P_T
sum(U_i) = P_A
sum(W_i - I_i) = P_T - sum(F_i)
sum(U_i) + sum(W_i-I_i) + sum(F_i) + F_close = C_fund
```

P_A/P_T 是独立推导的合法应得值。末尾跨过至少一轮扫描、连续观察 ≥65 秒：A 份额不重复解锁，D_A 的本批输出及两方账本不再变化。既有总守恒、真实 Applied/签名进入 witness 仍保留；不以钱包余额、`Closed`、`NoSignatureRequired` 或仅有 SDK prepare 成功代替链上证明。

### 05：当前 843 的一次有限拒签诊断

1. 整批54分钟计时从首个产物预检前开始；05的17分钟计时从该阶段开始，实际截止取该阶段截止与整批剩余截止的较早者，业务截止至少提前60秒用于清理。核对843同源 FNN/SDK、新驱动清单、原快照/可信合约及空闲资源。只准备一条 A–T 通道，记录 D_A≠S、开通绑定、原批准、费用意图、完整 record 和资金基线。关闭后台 watchtower 自动签署路径，channel signing 保持原行为。
2. T 仅强关一次；独立确认、推进真实 maturity/indexer 并取得当前 live Settlement R。检查 source、key purpose、祖先、deps、原始交易和真实 S inputs/outputs，证明该候选把 A 应得份额送到 S。若 T 合法先结算，只在原截止内沿已验证后继重新读取，最多 3 个不同真实工作；不删除陈旧请求、不重新开通。未取得有效工作只记场景未取得。
3. 原授权仍为 D_A。专用诊断入口从真实链构造 source、fee、additional_inputs 与可信 deps，直接调用未修改的 `prepare_onchain`；不先用现有 `lock==destination` 的夹具检查代替产品判断。所有 S 输入仍须匹配事先独立冻结的 S、plain/type/data/去重与 live 规则，不能让任意输入通过。保留原 SDK 返回；预计先命中 sponsor/destination 不兼容，按实际最先拒绝层级报告。
4. 从有效真实请求及原 SDK 拒绝齐备时观察 ≥65 秒（阶段最多75秒，完成采样间隔≤2秒）。比较每次prepare调用前后的SDK signing state、revision/nonce/签名历史，证明验证调用没有写入；65秒全窗口另核提交审计及无A Settlement签名/submit/Applied，不把普通事件接收的观察记录变化当成prepare写状态。沿真实祖先与 witness 确认 A 份额仍未解锁。允许 T 合法解锁自身份额，但必须保存前后继与未结算 A 份额，不能仅凭原 outpoint 已死判 A 结算。
5. 保存证据并清理本批进程。报告“05 的有限拒签结果及拒绝层级；01 独立到账、06 单变量目的地验证未运行”。适配器提前拒绝、缺链配置、无效 token、旧输入或无 SDK 调用均不能算05通过；若 SDK 意外 prepare 成功也不签名，停止并报告授权安全问题。

05 是当前错误候选的安全负向，证明原SDK prepare验证拒绝；零签名/提交是专用只验证流程的边界检查，不证明原Agent自动事件链的拒签或恢复。它不要求先通过D_A正向，也不证明SDK已正确区分payout与sponsor。缺少自然合法 D_A 候选时，不能拿变异拒绝代替06，更不能批准 S 来填补01。

### 01/06：实际修复版的正向与单变量对照

1. 先核对并固定获批修复 SHA、同源产物、产品的真实双地址/费用授权接口及可信合约，证明符合本次费用分配；不符则回到评审。准备一条新 A–T 通道及固定 D_A/S 意图，T 真实强关并取得合法自然候选。
2. 在 A 尚未签名/提交时，以只验证模式执行06：原样 prepare 成功后冻结 content、authorization、SDK state 和链输入。仅改变一个应支付 A 的 output.lock，依次替为 S 与 D_X；完整 input/outpoint/since、output capacity/data/type、deps、witness、授权 source/destination/fee/additional_inputs 均保持不变，脚本长度相同以保持交易体积控制。由 SDK 从变异 content 重算 canonical 摘要/消息，不复用旧摘要。
3. 对照与两个变体必须在同一仍有效输入/状态下完成；每个变体拒绝后再验证原样仍能 prepare。必须证明拒绝落在归属约束；若因输入竞争、record、nonce、deps、摘要或 sponsor 先拒绝，则06未验收，停止，不为取得分支复跑。全组 check-only 上限30秒，只有适配证据和本地计数允许写入；签名存储摘要/历史/revision/nonce 不变，不调用 `sign_onchain`、`sign_verified`、poll/submit 或广播。
4. 06结束后，仅对原始自然候选放行01的真实 verified 签名路径。再次核对其当前输入与授权；自然合法后继变化只按既定三工作/原截止规则处理，不把变异内容回送产品。取得 A 首次 Applied 与链上实际签名，完成两方资金及稳定观察。
5. 报告两个行为各自结果。06 是本地原 SDK 验证器负向，原 RPC request_id 只用于来源关联；`prepare_onchain` 不接收 RPC request_id，因此此处不证明服务端 request_id 校验或抗重放。05 的旧错误候选不强行移植成修复版真实工作，保留843结果；禁止为重现05而手改产品输出。

### 最小本地适配与回归边界

- 保留01在现有 `test_watchtower_settlement.py` 的稳定 ID，Gate3 获批后只同步该行全部映射；新增05/06使用同文件的明确方法/参数。02～04继续旧 D=S 预期，不改公共默认目的地造成静默扩展。新增范围仍属普通 LSP 功能测试，不搬入退款夜跑、不增加默认日常执行命令。
- `_sdk_driver.rs` / `_watchtower_chain.rs` 增加单一用途只验证入口：接受明确的真实来源和本地冻结意图，导出原 SDK prepare 结果与摘要；诊断与变异路径永远不能转入签名/提交。原 `wrong_destination` 改的是 auth.destination，不替代06，也不删除旧自检。
- 05的专用输入检查区分 D_A payout 与 S sponsor，但**不改产品 SDK**；SDK 自身仍看到真实 S 输入并执行原拒绝。不得复制/修改 validator、伪造 ChainVerifier 返回值、把输入 lock 改成 D_A、删输入、放宽费用或修改批准来凑成功。未来01/06仅按实际修复 API 构造授权，不能凭测试适配创造产品尚无的能力。
- 资金辅助只增加 D_A/S 分账与独立应得值，不替换可信链、祖先、maturity、witness、金额和真实签名验证。现有 helper 中会延长 cleanup 截止的路径不适用于本批；本批所有路径（包括旧02相关回归）必须由外层执行器服从首个动作开始的绝对总截止；旧02的24分钟包含准备、业务和清理，业务截止提前60秒。不能因teardown或旧helper延长截止而续期。
- 驱动变更以新产物清单绑定原843 FNN/SDK，旧 bundle、所有19项 helper及历史快照保留；需要原版二进制重建时当前短诊断停止、另列预算。本地适配自检先验证真实 prepare 调用可到达、无 sign/submit、状态不变和输入差异范围。当前843先跑旧02一次作为共享授权/处理入口相关回归，通过后才进入05；它只证明历史D=S的分段授权恢复，失败则停止05。未来修复版必须先读diff：旧D=S契约仍有效才可复用完整02；若输出已合法改为D_A，需另批实质修订02并确认，不能把其旧预期失败当产品回归或静默替换。只验证“无批准拒签”的片段不计完整02通过。

### 时间预算与停止规则

当前843不跑固定1+3、不等待无法实现的独立到账。实现与代码复核属于 Gate3 的前置工作；下列是之后的执行预算，从首个检查/构建动作前开始，以单调时钟计时。05预计6～11分钟，连同产物、自检和旧02相关回归预计15～30分钟，**整批硬上限54分钟**；这些是历史耗时辅助的估算，独立D_A尚无实测：

| 当前843阶段 | 硬上限 | 范围 |
| --- | --- | --- |
| 版本、现有产物及资源预检 | 3分钟 | 已匹配843 FNN/SDK，不自动重建或切版本 |
| 新本地诊断驱动构建/清单 | 5分钟 | 仅本地驱动、独立输出；需重编产品或依赖不齐则停 |
| 适配入口自检 | 3分钟 | 输入意图、只验证边界及审计；真实链拒绝在下阶段取得 |
| 旧02相关回归一次，含清理 | 24分钟 | 在843验证新驱动保留历史D=S的分段授权行为；失败停止05，业务截止提前60秒 |
| 05一次有限诊断，含清理 | 17分钟 | 准备≤300秒，强关≤120秒，maturity≤180秒，有效工作≤180秒（包括SDK prepare、独立核验及最多三工作），拒签观察65～75秒，清理预留60秒；所有子阶段受同一总截止限制 |
| 最终证据及残留核验 | 2分钟 | 不用于追加业务或重跑 |

未来修复版仅供本次预算评审，**不能因05完成自动启动**：预计55～85分钟，整批硬上限135分钟，分配为版本/环境预检3分钟、同源产物准备25分钟、适配自检5分钟、经修复diff确认仍适用的相关回归最多24分钟、01+06聚焦一轮18分钟、固定三轮各18分钟、最终证据核验5分钟，合计134分钟，余1分钟仅作交接。相关回归不能默认使用旧02：若D=S契约失效，先将02的实质修订另交评审；本次不授权改变02或用新预期吞掉旧失败。无法确定仍适用的相关回归时，未来批次停在版本影响评审，不先启动1+3。每轮18分钟含环境准备、真实强关/成熟/结算、06的30秒、终态65～75秒及清理60秒；原各阶段较小上限仍有效，但不保证能同时耗尽所有阶段上限，剩余时间不足即失败清理。未用预算不兑换额外轮次。启动观察前若剩余不足完整65秒窗口、收尾及清理，即停止业务并保存未完成原因，不截短观察。

所有RPC≤10秒并受剩余截止约束；采样间隔≤2秒。新来源只允许原截止内至多3个自然有效工作，不重开、不重置预算；取得特定先后顺序不是目标。环境/适配失败、场景未取得、业务断言失败、预算到期均停止后续批次；产品失败不重跑。#1674/#1706相同症状沿旧归因；新的收款阻塞单独描述，不归到旧问题。保留全部失败记录，不把05安全拒签标成PR资金问题已修复。

### 证据与下一门禁

每批/轮独立目录保留版本和产物清单、原授权与 D_A/S 公共归属材料、开通/record基线、原请求及链证据、逐笔输入输出与应得值计算、SDK拒绝层级、prepare/control/HTTP审计、状态前后摘要、真实签名与Applied/交易关联（仅01）、采样时间、阶段起止/退出码和清理结果；不保存私钥。旧运行记录原样保留。实施后才同步TEST-MAP及复选框，并分别记“已实现、未取得、失败、通过”，不只汇总通过数量。

用户已明确确认本次01/02/05/06行集、费用分配和预算，并授权当前843的Gate3实现、GPT6.1sol复核、自检、旧02相关回归及05单次诊断。执行硬上限54分钟，失败或到期停止；01/06等待实际修复版，不自动切换、不动退款。其他Gate1方向不扩展。


2026-10-29 Gate2文档核验：GPT 6.1 sol 分别复核资金公式/ID历史边界、真实SDK适配/单变量对照、预算与停止规则，未触发Daybreak。已采纳反馈：prepare副作用按调用前后比较，观察窗口另核零签名；整批与诊断阶段分别计时且不延长总额；当前843先做旧02相关回归，未来按修复契约重新判断02适用性。复核不代替用户对新行集、费用提案及预算的确认。

静态检查（不是产品执行）：`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root . --review reviews/lsp/watchtower-settlement.md` → `cases: 6`、退出0；提示01费用提案及SPEC-02/04/05/06需要人工决定，02的历史分段边界已有原批准，新01/05/06仍待本次确认。`python3 scripts/check_test_map.py` → `review cases: 114`、`automated cases: 108`、`duplicate review IDs: none`，退出1仍仅因既有PMP-01～05、SETTLE-01六个孤立映射；新增05/06未映射为预期，01旧映射不代表新预期已实现。`git diff --check`退出0。本轮未构建、未运行自动化或产品测试，未改产品、原快照、退款环境及已有TEST-MAP。

2026-10-29 Gate3实现：05已映射；原01仅保留历史方法并移除过时映射，新01/06未实现。新增本地SDK只验证入口、显式独立bundle和driver-only构建路径；GPT6.1sol已独立复核Python/Rust/构建边界，另核对54分钟有界执行器。旧02行为保持，所有真实运行与失败分类见LSP运行说明，代码评审不算执行通过。

2026-10-29 Gate3执行停批：独立driver构建、参数/只验证入口自检及两方法收集通过；随后发现05授权导出的EntityHex与Python Script对象比较不匹配，主动中断旧02准备阶段（exit2，JUnit tests=0），05未启动，整批exit1/stopped。此为测试实现及前次复核遗漏，不归产品；约90秒即停、无重跑。已保留原授权证据并补实际auth目的地的RPC导出和纯内存schema自检，修正后仅静态复核、未重建/执行。详见[LSP运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-独立收款诊断-gate3因测试适配缺陷停批2026-10-29)。05有映射但尚无行为通过，01/06仍待修复版。

停批后修正复核：GPT6.1sol只读确认实际auth的RPC导出、SDK EntityHex往返、Python完整目的地断言和纯内存schema自检一致，未重建/运行。最终静态检查：设计6行退出0；映射114条/108条，01/06未映射、05已映射，无重复ID，退出1只剩既有PMP-01～05及SETTLE-01六个孤立映射；Python AST和git diff --check均通过。冻结的21份原始源字节与run.json摘要一致。

2026-10-29 修正后获用户重新执行授权：固定843，新批次`report/lsp-watchtower-05-84333ee-20261029T195244/`在570.293秒内完成独立driver构建、扩展schema自检、旧02一次相关回归和05单次诊断，整批exit0；GPT6.1sol独立证据复核通过。05原SDK真实拒绝层级为`sdk_sponsor`（fee input is not approved plain CKB），65.546秒连续观察零提交、SDK快照不变且A未解锁；只证明有限拒绝，不证明输出目的地校验、产品修复或独立到账。旧02仍限历史D=S分段路径，01/06未运行。前次停止证据保留，详见[修正后运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-独立收款诊断-gate3修正后单次批次完成2026-10-29)。

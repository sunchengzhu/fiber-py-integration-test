# Gate2：Hosted watchtower 授权与无 TLC 结算

2026-10-25 用户已通过 Gate2 并接受 02 分段验证边界。2026-10-27 用户批准隔离链合约修复后，预检阻断已解决；修正后适配自检通过，正式聚焦 4/4，通过后的首轮固定复跑 3 通过/02 失败，后两轮未运行。02 观察到服务端持续返回已死输入的陈旧待签请求，产品侧证据及恢复结论边界见 [最新运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-watchtower-隔离环境恢复与正式验证2026-10-27)。随后按用户要求独立诊断，已确认有效后继请求被旧首项遮蔽，显式批准后完整 240.356s 仍未恢复，属于 FNN 产品 bug，见 [02 最新归因](../../test_cases/fiber/devnet/lsp/README.md#04c2064-watchtower-02-陈旧请求遮蔽与批准后恢复诊断2026-10-27)。Gate3 稳定性验收未完成，02 仍不能标为原 Agent 自动恢复覆盖。历史 Gate2 分析保留。

范围：用户已通过 [Gate1 三个方向](watchtower-settlement-scope.md)，本轮展开正常结算、未授权拒签后恢复、跨租户隔离。固定 FNN/SDK `04c206465b48da85b99aa58e80afe9801a2cb2db`；源码 checkout 干净，测试仓库基线 `cf937275618d8e51b35a7537788702cf4b67bc31`。保留已有改动与历史证据。本轮仅文档，不改自动化、驱动或产品，不启动节点。

**用户已接受、实现必须保留的边界：现有 devnet 无法直接安装进官方 agent 的固定 genesis 验证器。建议保留现有链，用局部驱动适配公开的 verified 签名入口；02 的负向是原 agent 真实拒签，正向是显式批准后经适配入口完成，不能声称原 agent 自动事件链的完整恢复。** 若要求同一原事件路径只改变批准状态，本方案的 02 尚不可执行，应另评兼容 genesis 环境或上游可配置 verifier 接口，不能在 Gate3 静默替换。

产品缺陷跟踪：`LSP-WATCHTOWER-02` 的陈旧请求遮蔽已由用户提交 [Fiber #1706](https://github.com/nervosnetwork/fiber/issues/1706)。2026-10-28 在明确修复提交 `3ce369e` 上重编并运行原 02，已自然命中旧 ID 小于新 ID、旧输入被 T 花费的条件，取得有效后继请求并完成真实结算；`1 passed in 363.48s`，GPT 6.1 sol 独立复核通过。见 [运行记录末尾的修复定点验证](../../test_cases/fiber/devnet/lsp/README.md)。这不覆盖原 Agent 自动恢复或全套 1+3 稳定性；04 的历史失败和诊断结果保留。

## 共同前提与接口

- A 是 Hosted 租户，T 是公共 LSP，B 仅用于隔离对照。各用例使用新 Fiber 状态及独立 SDK 身份/存储；沿用现有 CKB 快照，不要求整个链按方法重置。A–T 为私有 plain CKB 通道，正常外部注资和开通，不制造付款或注入 TLC。
- 初始注资沿用 A/T 各 500 CKB 的夹具参数；以实际 funding 输出、双方余额与 SDK 已验证完整 recovery record 核对，A/T 的待结算金额均非零，零 pending TLC。强关前不重启/驱逐 FNN 或 SDK。
- 在开通前给 T 钱包准备额外、未被占用的 plain CKB sponsor cells，总容量至少 1,000 CKB；两个通道按需预留独立资金，不能在待签后让充值/其他测试消耗已引用输入。实际输入、找零和费用仍独立核算。
- 目的地址 D 是测试从本地 T 钱包配置/公钥推导的完整 secp lock，事先保存。批准的 `max_fee=10_000` Shannon 是**每笔待签交易全部输入输出之差**的上限，不是全通道累计限额或从 A 余额扣款的上限。实际费用超过时失败，不自动提高授权；不是产品固定费率契约。
- 通道延迟沿用 `commitment_delay_epoch=0x10000000001`（一个 epoch）；watchtower 保持模板的 60 秒扫描。独立读取真实 CKB epoch 分数与输入 `since`；SDK 开通使用的 2,000ms epoch 配置不能代替链上 maturity 判断。
- 真实 RPC 为 `get_watchtower_signing_status({channel_id})`、`submit_watchtower_signature({channel_id,request_id,signature})`；实际事件为 `watchtower_signing`。正常提交要求 FNN 首次接受为 `Applied`；若是相同实际重传导致 `AlreadyApplied`，必须已有该签名的真实首次 Applied 证据，不能只拿重复回执通过。
- 所有签名必须来自 A/B 自身真实 SDK。取得完整请求 R 时核对 `key_purpose=Settlement`、request ID 与完整 packed 交易字节的哈希、所属 node/channel、SDK 本地 source record 及独立链上输入。不得从 FNN 待签内容反推目的地址或提高费用批准。

## Spec

### SPEC-01：所属租户授权的无 TLC 结算必须真实确认并守恒
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

## 测试树

<!-- TEST-TREE-BEGIN -->
- 真实结算与资金
  - A 已批准，T 强关，SDK 签名接受后两方结算守恒：LSP-WATCHTOWER-01 [primary] -> SPEC-01
- 本地批准
  - 原 agent 无批准拒签，明确批准后经独立验证适配入口完成：LSP-WATCHTOWER-02 [primary] -> SPEC-01、SPEC-02
- 租户隔离
  - B 自身读取成功但读取 A 工作失败，A 正向完成：LSP-WATCHTOWER-03 [primary] -> SPEC-01、SPEC-03
  - B 自身真实提交成功但提交 A 有效签名失败，A 应用原有效签名并完成：LSP-WATCHTOWER-04 [primary] -> SPEC-01、SPEC-03
<!-- TEST-TREE-END -->

A 暂停时 B 并行结算、SDK 原存储掉线恢复、含 TLC 兑现/退款、撤销惩罚和租户独立钱包取回仍在本批范围外，入口保留在 Gate1，不拿本批正向对照替代这些用例。

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-WATCHTOWER-01` | - [x] A/T 非零份额、无 pending TLC 的私有 CKB 通道中，A 事先批准本地 D 和每笔 10,000 Shannon 费用上限；T 强关，推进真实成熟条件并由 SDK 经独立链验证适配入口签名 | A 的 Settlement 签名真实 Applied，其份额支出确认；沿后继输出完成两方结算，逐笔及累计资金满足共同公式，终态连续稳定至少 65 秒 | 将原承诺被 T 花费、SDK 回执或钱包总余额变化误当成 A 已结算，漏掉费用或 sponsor 资金 | P0 |
| `LSP-WATCHTOWER-02` | - [x] 同样的真实通道中不授予 A 本地 watchtower 批准；取得有效请求及原 Agent.handle_event 的缺批准拒签后观察至少 130 秒，再调用原批准 API 并经适配入口完成原通道 | 已确认分段验证边界；批准前 SDK 不产生/提交 A 的 Settlement，A 份额未结算；明确批准后真实 SDK 验链、签名及资金终态满足 01，不宣称原 agent 自动事件链仅补批准即可恢复 | 测试驱动自行拦截被误算成 SDK 拒签，或绕过本地批准直接调用 verified 入口却宣称完整授权恢复 | P0 |
| `LSP-WATCHTOWER-03` | - [x] A/B 自身 watchtower 查询均成功；T 强关 A 后，捕获并扣住 A 对当前有效 Settlement 的真实签名，用 B token 读取 A 的同一 channel，再用 A 处理该工作 | B 读取失败且未返回 A 请求内容；操作前后 A 当前工作及可用输入未被 B 改变；A 的真实提交、结算与共同资金断言通过 | 跨租户泄露签名上下文，或因 B token 无效/无权限而取得假阳性 | P0 |
| `LSP-WATCHTOWER-04` | - [x] 先让 B 在自己的通道上真实提交有效 Settlement 并完成结算作为写权限对照；再取得 A 通道当前有效请求和扣留的真实 SDK 签名，用 B token 原样提交 A 的 channel/request/signature，随后由 A 提交 | B→A 提交失败，A 原工作不被应用或替换；A 提交同一仍有效签名真实 Applied 且结算守恒；不能用错误签名、过期请求或 AlreadyApplied 代替身份隔离 | 租户身份未参与签名提交路由，或缺少合法写权限/有效签名对照而错误判定隔离成功 | P0 |
<!-- TEST-CASES-END -->

03/04 是同一方向的两个独立可失败行为，分别映射；四项已存在 TEST-MAP，执行结果另见运行记录；复选框不代表已验证。02 的分段边界和下文驱动适配是本次 Gate2 的明确评审项。

## 分阶段时间预算

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

## 共同资金与签名断言

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

## 四条具体执行步骤

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

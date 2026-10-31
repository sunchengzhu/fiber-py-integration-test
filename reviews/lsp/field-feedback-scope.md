# LSP 实测反馈与相邻风险：Gate1 场景范围

## 2026-10-30 三项缺口契约核查：最小 Gate1（待确认）

本节只回答“是否属于PR核心交付、有没有对应测试、最少还需补什么”，不统计执行比例。产品源码固定且干净 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；仅核对该提交的设计说明、源码、上游Rust/Bruno断言与现有Python测试。未更新远端版本、写自动化或运行产品测试。下文历史二十候选保留，但不代表本轮获准并行实施。

### Spec：必须支持与尚未决定的契约

- **对应 SPEC-01：批准的收款归属必须守住；独立payout/sponsor是另一个问题。** SDK的`OnchainSpendAuthorization`明确包含钱包批准的destination、fee及输入，输出与批准不符必须拒签，这是核心安全规则。当前单一destination同时约束费用输入与非后继输出，watchtower将结算款付到fee-provider地址。固定说明定位为订阅原型，未明确承诺用户D_A与运营方赞助S不同的正向退出能力，也没有两地址费用/找零契约；不能因实现缺失就认定无需支持，也不能把测试评审自定的费用分配当作产品需求。**待产品确认：本PR是否承诺D_A≠S、A的应得份额实际进入D_A；如果承诺，如何表达批准及费用归属。**依据：[SDK授权](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L42)、[输入限制](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L244)、[输出限制](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L345)、[实际结算输出](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/watchtower/actor.rs#L1786)、[原型范围与non-goals](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/docs/notes/hosted-lsp-remote-signer.md#goals)。
- **对应 SPEC-03：取消生效后的失败一致性是核心；Hosted Received取消入口仍有契约冲突。** 普通节点允许Received且没有preimage时取消，设置Cancelled并安排TLC收尾；RPC注释却写仅Open，Hosted tenant allowlist又未开放cancel_invoice。普通取消逻辑相对PR base不是新语义，不能直接移植为Hosted接口承诺。Hosted文档明确Cancelled等永久下游失败应持久化并结算上游、不再重投。**待产品确认：Hosted hold invoice已Received且节点无preimage时，租户是否允许取消；若允许，就必须验证原付款安全终结。**依据：[RPC注释及租户分派](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/invoice.rs#L249)、[实际取消条件](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L4996)、[Hosted永久失败契约](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/docs/notes/hosted-lsp.md#buffer-deadline-and-durable-state)。
- **对应 SPEC-04：未授权不签、等待不能越过TLC安全期限，属于核心；“无限拒绝仍自动退款并保持原通道可用”不是既定契约。** SDK拒绝缺授权或条款不匹配；Agent处理失败只要求重载pending，不等于调用取消。产品说明规定InFlight不由buffer计时器取消，TLC期限可触发强关，后续付款协调/链上结果负责收尾。永久不补该笔commitment授权，不等于拒绝之后合法链上支出的独立批准；强关后不能要求原通道继续付款。依据：[授权检查](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/commitment.rs#L471)、[失败重载](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/tests/fiber-lsp-sdk-agent/src/events.rs#L83)、[TLC安全期限及结算责任](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/docs/notes/hosted-lsp-remote-signer.md#tlc-safety-deadline-while-awaiting-a-signature)。

上述安全规则来自固定版本的明示说明或具体校验；双地址正向、Hosted Received取消范围是未定契约，不能只用实现观察替代产品决定。本轮不对整个PR作生产非托管能力承诺。

### 测试树：排除重复后的观察边界

- 收款归属 → SPEC-01
  - **已有：固定授权仅替换输出地址。** 上游`onchain_claim_checks_live_input_witness_destination_fee_and_maturity`先prepare合法原样；bad=0只改outputs[1].lock、保留terms，断言prepare拒绝与store快照不变，最后原样仍能prepare/sign；JSON路径还覆盖Auto/Manual。见[精确断言](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/commitment_tests.rs#L1623)。先前将通用错地址防护说成缺测试不准确，本轮纠正，不新增同义测试。
  - **仍无端到端实现：D_A≠S自然候选的真实到账及该模型的变体。** 复用WATCHTOWER-01/06；上游合成TestChain没有sponsor辅助输入，现有05先被sponsor检查拒绝，均不能替代双地址正向。
- 发票取消 → SPEC-03
  - **已有普通节点测试：** Rust`test_delayed_final_hold_invoice_cancel_failure_is_decodable_by_payer`相关路径等待Received后取消并验证RemoveTlcFail，但取消helper直接写状态、绕过RPC；Bruno`hold-invoice-cancel-failure`真实调用RPC并验证Cancelled/Failed。两者都不是Hosted租户双段资金验证。见[普通付款测试](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/tests/payment.rs#L10265)、[helper](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/tests/test_utils.rs#L929)。
  - **已有Hosted状态机测试：** `permanent_payment_outcomes_settle_upstream_without_redispatch`包括InvoiceCancelled，检查持久失败决定、不重投；FakeRuntime与人工outcome/settled消息不等于真实取消和资金闭环。见[上游测试](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/tests/mod.rs#L2576)。
  - **仍无：** INVOICE-CANCEL-03的真实Hosted Received取消到资金收尾；01/02已有代码，入口失败是产品问题，不能重复算缺用例。
- 长期不补授权 → SPEC-04
  - **已有分层验证：** SDK未知hash/金额/方向拒绝及状态不变（[commitment_tests.rs](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/commitment_tests.rs#L440)）；上游不同签名检查点的截止保护、最新承诺和清pending（[external_signer_restart.rs](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/tests/external_signer_restart.rs#L2223)）；现有TIMEOUT-08/10/11/12及已获授权的REFUND-01～03。PAYMENT-04已经实现的是“后来补授权”，不是永久拒绝。
  - **明确残余：** 尚无真实SDK永久缺该笔授权到原付款/全部资金最终收尾的端到端组合。分层通过不能冒充组合通过；本轮建议保留此风险，不因它另建长时退款环境。若另定为必验，最小候选只到“真实拒签→安全截止→保护结果”，链上取回必须另外明确合法授权和成熟条件。

### 用例范围：本轮Gate1建议

| 核查对象 | 最小补充方案 | 当前不做的扩展 |
| --- | --- | --- |
| 独立D_A/S收款 | 不新增ID或通用错地址测试。先确定是否属于本PR交付；若是，仅复用已有WATCHTOWER-01正向、06固定授权变体，产品具备合法候选后再进入Gate2 | 双租户共享sponsor、重启、UDT、更多攻击矩阵 |
| Hosted Received取消 | INVOICE-CANCEL-03保持“契约待确认”。若产品确认允许，只复用该行：真实tenant入口、原付款失败/逐方资金与零锁、下一笔正常付款；先解决01已知入口问题 | MPP、重启竞争、Expired及所有状态组合 |
| 永久不补授权 | 不新增或运行长时用例；复用现有拒签及截止保护测试，明确端到端组合尚未覆盖。若用户另将组合列为本PR必验，再单独评审窄范围的截止保护场景 | 将拒签当取消、无需后续链上批准的自动退款、强关后要求原通道继续付款 |

**本轮建议为零新增正式用例、零自动化修改、零执行；两个产品契约决定，加一个明确保留的组合风险。** 这不是把风险认定为范围外：在作者/维护者作出明确裁定前，独立到账与Hosted Received取消仍未关闭。用户确认本Gate1仅确认测试范围与取舍，不自动代表产品已承诺这些能力；若后续契约改变已确认行的预期，Gate2必须展示改后行集。

本轮不改现有WATCHTOWER-01/06、INVOICE-CANCEL-03、PAYMENT-04正式行、复选框或TEST-MAP，不启动Gate2/3，不触及已完成退款。GPT-6 Sol High完成源码与上游断言的独立核对。仅执行文档静态检查：`git diff --check`退出0；项目映射125评审/118映射，exit1仍为9个既有孤儿、无重复ID；设计检查为0正式行、exit1提示`no case definitions`及历史未定契约，符合本文件只交Gate1范围、未展开Gate2正式行的边界，不声称完整行集检查通过。没有执行pytest、Cargo测试或节点。

---

2026-10-30当前主会话：候选18的有界功能部分已由`LSP-RECOVERY-08`完成Gate3，固定843、旧06及新08各单次通过；十笔付款、第9笔原存储重启及第10笔继续付款均有资金与稳定证据，见完整结果（本地证据：`../../report/lsp-recovery08-84333ee-20261030T171222/RESULT.md`）。长期压力和单通道序列化大小仍未测。用户已确认候选12对应PAYMENT-04的Gate2/Gate3及准备修正。最新192130批补入既有合约对齐调用，经GPT-6 Sol High复核后仅执行一次；pytest在setup_class的隔离路径断言报错（1 error in7.60s、exit1）即停。runner向预导入类设置路径，但pytest实际加载另一模块中的类，tmp_path_name仍为None；CKB已在默认tmp启动后才被断言拦下。未执行合约对齐、FNN初始化或任何付款/资金断言。属于本批执行准备错误，不能计产品业务失败或通过。旧批证据保留，见最新RESULT（本地证据：`../../report/lsp-payment04-84333ee-20261030T192130/RESULT.md`）。

## 2026-10-30 去重核对与下一批Gate1

本次沿用`ai-test-agent`评审流程，检查现有Python方法及全部相关TEST-MAP、固定843本地源码、上游SDK/Agent单测、LSP README及对应原始运行证据。产品HEAD仍为干净`84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，本轮没有查询或切换最新远端提交。下方原二十候选及Spec/树保留提出时的范围；其中历史`pending/not_tested`不覆盖本节引用的后续实测。

### 已排除重复及需要分开的事项

| 判断 | 核对结果与证据 | 下一步性质 |
| --- | --- | --- |
| 已有当前版本通过 | 连续付款恢复08见上方结果；DELIVERY夜批（本地证据：`../../report/lsp-night-new-84333ee-20261030T030349/RESULT.md`）的03～06各一份通过JUnit，连同之前01共5/6；退款最终结果（本地证据：`../../report/lsp-refund-84333ee-20261030T1300/RESULT.md`）两轮正式结果均通过，已按用户决定验收 | 不再作为新覆盖缺口或待补轮次 |
| 当前版本已有产品失败 | DELIVERY-02的JUnit为`original K failed but downstream paid`，尚未完成最终资金稳定断言；INVOICE-CANCEL-01在真实tenant入口`-32999 Unauthorized`，后半资金步骤未执行 | 等修复SHA定点验证；不从零重复定位，也不算“没写场景” |
| 已写未执行或只缺当前版本结果 | INVOICE-CANCEL-02已有映射但被同一取消入口阻断；普通订阅8 ID、TIMEOUT 9 ID、WATCHTOWER-03/04已有旧版代码与结果，843长回归`timeout-9.xml tests=0`且环境权限停批，后续阶段未启动 | 合计19个旧场景属于最终版本回归，不包装为新增用例 |
| 真实尚缺的独立行为 | 本地付款授权缺失/不匹配后的业务收尾；持久化接纳后原数据重启FNN、Failed终态重投及同hash新incoming key政策；重复RootSigner、凭证刷新、协议key冲突后的身份隔离和重启保持 | 分组评审，当前只选下述缺授权路径 |
| 仍受能力或契约限制 | 独立收款WATCHTOWER-01/06及共享sponsor/目的地重启扩展；Received取消03；同身份多通道严格子集过滤；长期规模/状态增长及未来缓存、修剪 | 独立收款/取消先等契约或修复；843每租户仅一私有通道，严格子集不能用A/B隔离代替；性能和未来实现另定版本/阈值 |

19个已有场景具体为SUBSCRIPTION-01/04/05/06/07/10/11/13、TIMEOUT-01/02/03/06/07/08/10/11/12、WATCHTOWER-03/04。TIMEOUT-04/05沿旧#1674归因另留修复验证；#1706已有指定修复版证据，不重新包装为当前未知缺陷。当前ID和版本结果汇总仅维护在[现有README](../../test_cases/fiber/devnet/lsp/README.md)，不另建覆盖率台账。

### 本批范围：缺少授权后的显式补授权恢复（原候选12）

**范围提案：只测一个连贯业务路径。** 先让真实SDK因缺少本地付款授权拒签，再由用户显式补入同hash的正确授权，依赖同一SDK进程已有的错误重连/待签重送完成原付款；随后在原两条通道上完成一笔新hash正常付款。选择“显式批准后恢复”作为本批收尾，不要求永久拒绝时自动取消或自动释放资金。这里的合法补授权是被测操作，不是绕过拒签。

**Spec依据与观察边界。** 固定843的SDK `commitment.rs:471～482`拒绝无授权和金额/方向不符的TLC；`signer.rs:637～653`允许显式保存匹配的入站发票授权。现有驱动对真实处理失败回报`processed=false`，上游Agent `events.rs:84～87`触发重新订阅/重载待签；这是自然恢复路径的源码依据，尚不是本场景的运行证明。安全释放必须经过原Agent `release_preimage_verified`调用独立ChainVerifier和`authorize_preimage_release`，持久授权后才以tenant token `settle_invoice`；不调用`cancel_invoice`，不受已知取消入口阻断影响。

测试树与拟交Gate2的行为边界：

| 行为阶段 | 必须取得的可观察证据 | 与已有用例的差别 |
| --- | --- | --- |
| 无授权时拒签 | 使用客户端持有preimage的hash-only发票，真实发送一次；SDK实际收到含目标hash的待签请求并拒绝，FNN未预先得到preimage，无该请求的有效提交/结算，保留四端余额与占用快照 | 上游单测只证明拒签；旧RETRY/PAYMENT/RECOVERY在发送前已写正确授权，扣住的是有效签名 |
| 显式补授权后恢复原付款 | 补同hash正确本地授权；同SDK PID、原存储/token/通道，以实际新WS交付证明同一完整待签请求恢复，不重发付款、不由Python代签/代交；含目标TLC的真实可执行承诺及独立链验证满足后，由原Agent安全释放preimage | 08从已保存的有效签名重启；本批从尚未获准签名的状态恢复，保持SDK进程运行 |
| 原付款收尾并继续业务 | 原hash Success/Paid、原四端资金按实际费用守恒、无活跃TLC/锁定/待签；原两条通道上下一笔新hash正常付款也成功，各自稳定窗口及累计账本通过 | 拒签日志、订阅重连或仅原付款成功均不足以证明后续可用性 |

Gate2再确定完整行、稳定ID、固定金额/次数、拒签观察时长、业务安全余量、逐方资金公式、实际选择器与预算。建议只含一笔故意缺授权的付款和一笔后续正常付款，Gate3以30分钟为初步上限（含实现、Sol复核、单次执行及清理）；不默认加1+3或全量回归。正式预算以Gate2可复用接口核验后提交的行集为准。

**最小适配方向。** 复用现有真实付款拓扑、hash-only发票、SDK `invoice/records/release-preimage`控制入口、订阅/提交审计及四端资金断言；本轮没有证明新组合已可运行。优先在Python层组合，不新增Rust薄包装、产品钩子或构建任务。Gate2必须核对“无授权时没有签名提交”的可观测性和安全释放前提；缺证据不能降为只查错误日志。

**本批排除。** 候选13错误金额/方向的既有授权不能照搬此路径：`commitment.rs:255～276`禁止将同hash已保存授权替换为不同条款，其永久拒绝收尾须另定。也不加入拒签后自动退款/强关、VM调时、FNN/SDK强制重启、注册规模、长期压力或修改产品。失败/到期停批、保留证据和清理自有临时文件等约束留到Gate2具体化。

本轮只更新范围说明及08后的已有汇总，不增删正式用例行或TEST-MAP，不改自动化，不启动节点、VM或任何产品测试。上述**候选12的三阶段单路径**已获用户确认，已进入[PAYMENT-04 Gate2](delayed-payment-recovery.md#lsp-payment-04-gate2缺授权后的同进程恢复84333ee)；候选13及其他方向没有隐含获得实施许可。

本节经GPT-6 Sol High只读去重复核，无阻断项。静态检查：`git diff --check`退出0；项目映射检查124评审/117映射、退出1仍为9个既有孤儿，无重复ID；设计检查识别0正式行、退出1为`no case definitions`，符合本文件只交Gate1范围、Gate2再展开正式行的既有约定，不能称完整用例设计检查通过。

范围：针对 LusoCryptoLabs 报告暴露的资金归属、投递接纳、租户 RPC、授权拒签及持续使用问题，补充候选场景和相邻风险。沿用本会话的 **Gate1 范围 → Gate2 完整行集、预算和适配 → Gate3 实现与执行**；本文件保留原范围，不分配正式用例 ID。2026-10-29 用户已确认 Gate1，方向1/2已进入[watchtower Gate2及后续记录](watchtower-settlement.md#独立收款与目的地替换gate22026-10-29)；方向5/6/7已展开为[接纳一致性 Gate2及Gate3记录](delivery-acceptance-consistency.md)；方向9/10/11已形成[发票取消 Gate2 三行及单次诊断](hosted-invoice-cancellation.md)。用户已授权按顺序持续推进这三批，其他方向仍按下列候选范围保留。表中的序号只是阅读顺序，不是 Test Point ID。

分析固定产品 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；2026-10-29 再次查询 PR #1623 head 仍为该提交。旧 04、3ce 和本次 843 的结果各自保留，原工作区、退款夜跑、原快照和运行证据不动。后续修复验证须另固定实际修复 SHA，不能把评论者分支或建议当成已合入产品。

来源：[三项功能问题](https://github.com/nervosnetwork/fiber/pull/1623#issuecomment-6418454010)、[租户规模与 SDK 状态增长](https://github.com/nervosnetwork/fiber/pull/1623#issuecomment-6477923077)、[状态修剪、缓存及未授权 TLC 跟进](https://github.com/nervosnetwork/fiber/pull/1623#issuecomment-6485213291)。评论者使用过 PR #1623 与 #1677 的组合环境；本地只读核对能确认下列 843 代码模式，不能把对方性能数字、资金损失或 mock-chain 实验写成本地复现结果。[索引修复 PR](https://github.com/chenyukang/fiber/pull/9) 当前未合并，pruning/cache 也不是 843 的既有能力。

## Spec

### SPEC-01：结算必须验证收款所有权，并与费用赞助分开
Condition: A 为 Hosted 租户，D_A 是 A 独立控制并事先批准的退出钱包；S 是 T 的 sponsor 钱包，要求 D_A 与 S 不同；双租户时另有独立 D_B。
Expected: 未批准的目的地不得签名或提交；拟纳入验收的正向要求是 A 的净份额进入 D_A，S 只按明确的费用/找零契约使用，金额守恒之外还必须证明归属正确。待确认：产品如何分别表达、持久化和验证 payout、sponsor 输入、sponsor 找零及费用承担；不要求用当前单一 destination 字段假装实现独立收款。
Observable: 开通时的 shutdown script、独立钱包 lock/密钥归属、原 SDK 批准、候选交易、真实输出及逐方账本、拒签和零提交、重启后的原批准。
Basis: [结算输出使用 fee-provider lock](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/watchtower/actor.rs#L1786)；[SDK 辅助输入限制](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L256)及[输出限制](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/onchain.rs#L345)。旧评审明确把 D 设为 T 钱包，不能当作独立用户收款的产品要求。
Source: inference
Testing: not_tested — Gate1 候选，独立收款正向及费用契约待确认，Gate2 分配正式行。

### SPEC-02：接纳调用超时不能造成上游失败、下游独立成功
Condition: 一笔真实 incoming TLC 通过 T 投递给租户；接纳调用在服务处理前或持久化后遭遇超时/丢回复，随后恢复或重启。
Expected: 对同一次 incoming 执行，上下游与 delivery 状态必须一致；上游已不可逆失败后不能再单方面完成下游支出。完全相同执行重投不得多付款，冲突内容不得修改原记录。待确认：超时后的查证/撤销机制、终态和恢复时限；传输超时本身不等于业务失败。
Observable: 原 incoming_channel_id + incoming_tlc_id、tenant/payment hash 关联、delivery 持久状态、上下游 TLC、付款/发票终态、双方余额与费用、真实接纳/回复先后证据。
Basis: [5 秒 actor 调用及超时错误](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L5312)；[服务接纳、安排恢复后才回复](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/service.rs#L519)；[执行 key](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L23)及[重复/冲突规则](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L415)。key 不含 tenant；相同 hash 的多个 active incoming 也不能假设均可接受。
Source: inference
Testing: not_tested — Gate1 候选，精确 actor 屏障及 incoming key 重投能力尚未具备。

### SPEC-03：租户取消发票必须同时满足入口权限、归属及终态一致性
Condition: 有完整合法凭证的 A 对自己的发票调用 cancel_invoice；另有 B 的隔离请求和取消期间的待处理投递。
Expected: A 的合法取消入口可达，B 无权改变 A；成功取消后旧投递/重启不能再次使该发票收款成功。已付款、已取消、已有 preimage 的拒绝及 Received/Expired 的允许范围，按明确状态契约区分。待确认：Received 无 preimage、Expired 是否允许取消及取消与结算竞争的胜出判据。
Observable: 服务端 RPC 响应、发票状态、preimage 是否存在、持久 delivery、原付款终态、锁定解除和后续支付可用性。
Basis: [tenant allowlist 缺 cancel_invoice](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/tenant.rs#L22)；[已有租户分派及仅 Open 的接口注释](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/invoice.rs#L249)；[实际状态限制及取消后异步处理](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L4978)。注释与实现范围并不完全一致，不能只据注释或实现决定新契约。
Source: inference
Testing: not_tested — Gate1 候选，当前 allowlist 阻断不得算取消业务验证通过。

### SPEC-04：拒绝未授权 TLC 后仍须有明确业务收尾
Condition: 发票有效，但 SDK 缺少相应本地授权，或授权与收到的 TLC 金额/方向不匹配。
Expected: 不得为未批准状态签名或泄露 preimage；待确认：安全失败原付款并释放占用，还是允许明确补授权恢复。选定方案必须验证原付款终态和同一通道下一笔合法付款，不能以一条拒签日志代替收尾。不给“签取消”方案预先作安全承诺。
Observable: 原始授权存储、真实 SDK 拒签、签名提交审计、原 TLC/付款/发票、余额、下一笔独立正常支付。
Basis: [缺本地授权直接拒签](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/commitment.rs#L471)；既有 PAYMENT/RECOVERY/TIMEOUT 夹具在发款前已写入本地授权，扣住的是有效签名。
Source: inference
Testing: not_tested — Gate1 候选，安全取消/补授权的目标终态须先确认。

### SPEC-05：租户查找优化不能破坏注册、刷新及身份隔离
Condition: 首次注册、重复 RootSigner、协议 key 冲突、凭证刷新、原数据重启，以及有界租户规模增长。
Expected: 首次注册唯一身份；重复已注册 RootSigner 按认证入口拒绝，凭证刷新仍定位原身份；key 冲突不能污染原记录，重启不改变绑定。规模下先保持同一功能不变量，性能门槛另定；不把所有重复注册都写成幂等成功。
Observable: tenant ID、RootSigner/协议 key、凭证作用域、原通道绑定、记录数量、分项操作耗时；失败注册 nonce 的消耗规则待确认。
Basis: [认证注册重复拒绝及凭证刷新](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/registry.rs#L200)；[全量查找](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/registry.rs#L267)；未合并的索引 PR #9 仅作为未来回归线索。
Source: observation
Testing: not_tested — Gate1 候选，规模阶梯和测量阈值留 Gate2，不把对方一万租户结果设为门槛。

### SPEC-06：连续正常付款不能只验证第一笔可用
Condition: 同一真实通道在原 SDK 存储上持续完成有界支付；后段停在真实待签检查点并重启 SDK。
Expected: 每笔只结算一次，余额正确；重启恢复原请求且后续业务仍能完成。记录随支付数变化的状态大小与耗时；待确认允许增长及性能阈值，不能凭单次功能通过排除历史累积成本。
Observable: 逐笔付款/发票/余额、原 request ID/签名、单通道 StoredSigningState 大小、整库快照大小分别记录、后段签名/支付耗时和恢复结果。
Basis: [整块加载与保存](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/signer.rs#L1257)；[追加历史 commitments](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/lifecycle.rs#L244)；[追加与扫描 revocations](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lsp-sdk/src/commitment.rs#L738)。14KB/笔、96笔1.31MB、95% CPU 都是评论者测量，不是本批标准。
Source: inference
Testing: not_tested — Gate1 候选，需确认规模、状态导出和环境测量方法。

### SPEC-07：未来缓存/历史修剪不能改变授权和惩罚能力
Condition: 在实际合入的修复版本上，签名状态字节改变，或历史被产品按已确认规则修剪。
Expected: 缓存不能返回旧授权/旧 nonce 状态；修剪不能丢失待签恢复所需资料或让已撤销承诺失去合法惩罚能力，也不能让当前承诺被错误惩罚。待确认实际修复、保留契约、缓存失效规则和合约字节；不手工删除 SDK 历史伪造产品修剪。
Observable: 授权前后真实拒签/可签结果、原请求恢复、合法旧承诺与当前承诺的差异、错误签名拒绝、固定合约的真实验证及资金结果。
Basis: 评论者的 pruning/cache 提议及 mock-chain 结果；本轮没有已合入实现供核验，也没有证明“只留最新撤销”在所有状态都安全。
Source: inference
Testing: not_tested — 明确保留为未来修复范围，先读实际 diff/契约再进入 Gate2。

## 测试树

<!-- TEST-TREE-BEGIN -->
- 收款归属与费用赞助 → SPEC-01
  - A 独立退出钱包与 sponsor 分开 [pending] — 确认正向能力；当前可观察拒签，不可放宽授权凑成功。
  - 金额不变而 payout 被替换 [pending] — 复用自检，须分辨目的地校验与更早的请求完整性拒绝。
  - A/B 共享 sponsor、各自退出钱包 [pending] — 分别核对真实归属，不能用共享余额抵消错付。
  - 原存储重启保留原目的地 [pending] — 明确 SDK/FNN 分别承担的持久化与显式处理边界。
- 投递接纳与执行一致性 → SPEC-02
  - 服务处理前越过 5 秒后再处理 [pending] — 需要证明实际接纳前后顺序的屏障。
  - 已持久化接纳但丢回复 [pending] — 与未接纳超时分开，不能由传输错误决定付款终态。
  - 同 incoming key 原样/冲突重投 [pending] — 现有 Python 尚无原 key 重投入口。
  - 已接纳后原数据重启 [pending] — 需要可观察持久化点，防重付也防已承诺工作丢失。
- 发票入口与取消终态 → SPEC-03
  - A 取消自己的 Open 发票 [pending] — 修复前只会暴露 allowlist 阻断。
  - B 不能取消 A 的发票 [pending] — 拒绝后以 A 原发票仍可正确处理作对照。
  - 取消与后台恢复/结算竞争 [pending] — 明确 Received/Expired 和 preimage 边界，成功取消不得复活。
- SDK 本地授权 → SPEC-04
  - 完全缺授权及后续正常支付 [pending] — 先决定安全失败还是显式补授权恢复。
  - 金额/方向不匹配授权 [pending] — 选择一个有判别力的代表输入，避免全字段组合矩阵。
- 租户注册、刷新与规模 → SPEC-05
  - 首次注册、重复 RootSigner 和合法刷新 [pending] — 重复注册拒绝，不混同内部 register 幂等。
  - 协议 key 冲突及之后的合法注册 [pending] — 确认冲突后的 nonce 规则，验证没有污染 A。
  - 原数据重启后身份查找和通道继续 [pending] — 修复迁移另读真实数据格式，不删除索引模拟。
  - 有界租户阶梯 [pending] — 注册身份不等于每租户启动独立 agent/通道；先定测量口径。
- 长期使用与后续优化
  - 同通道连续支付、后段 SDK 重启 → SPEC-06 [pending] — 逐笔结果与状态/耗时分开判断。
  - 未来缓存的授权/状态变化 → SPEC-07 [unanalysed] — 等实际修复 diff，确认缓存键、对象可变性和失效规则。
  - 未来修剪后的旧承诺惩罚与拒绝对照 → SPEC-07 [unanalysed] — 等保留契约与固定合约字节，不能沿用评论结论替代验证。
<!-- TEST-TREE-END -->

## 用例：Gate1 候选场景

以下二十个方向全部提交范围评审；“待产品/夹具”不表示忽略问题。Gate2 会按独立可观察结果拆分正式行，并复用已有 ID，不把本表一行机械等同一个执行实例。

| 序号与候选场景 | 前提与操作 | 要验证的结果或待确认点 | 建议优先级 |
| --- | --- | --- | --- |
| 1. 用户收款与 sponsor 分离 | A 只批准自己的 D_A，D_A≠S；T 强关生成真实工作 | 错付 S 必须拒签；正向必须把 A 净份额付给 D_A、S 找零单列；当前产品结构阻塞，先确认契约 | P0 |
| 2. 金额守恒但目的地被换 | 固定原批准，仅把合法候选 payout 换成 S/D_B，check-only | 仍须拒签且零提交，不因金额/费用正确放过错付；不广播变异交易 | P1 |
| 3. 两租户共享 sponsor | D_A、D_B、S 各异，两条通道分别结算 | 各自净份额只能进入自己的批准地址，批准不能跨租户沿用，逐通道守恒 | P1 |
| 4. 重启不改变退出钱包 | 已保存 D_A 批准/待签工作，以原存储重启 SDK/FNN 的选定一侧 | 恢复原目的地与费限，不回落 S、不自动扩大批准；显式处理和自动事件恢复分开 | P1 |
| 5. 接纳前调用超时 | incoming 已排队但尚未处理，调用方越过 5 秒后再放行 | 不出现上游最终失败、下游成功；真实接纳顺序和资金结果必须可证 | P0 |
| 6. 接纳成功但回复丢失 | delivery 已持久化，再丢 actor 回复并恢复 | 查清已接纳事实，同一次 incoming 至多一次有效付款，上下游终态一致 | P0 |
| 7. 同一次 incoming 重投 | 相同 channel+TLC ID 先原样重放，再提交金额/目标冲突内容 | 原样幂等、冲突拒绝，原记录不变；不能换新 key 冒充重试 | P0 |
| 8. 接纳后重启恢复 | 取得已持久化且未完成的 delivery，原数据重启 FNN | 已承诺工作不丢失、不重复下游付款或上游结算，最终余额一致 | P0 |
| 9. 租户取消自己的发票 | A 合法凭证取消自己的 Open 发票，再尝试支付它 | 入口可达并正确取消，已取消发票不能完成收款；权限错误不算通过 | P1 |
| 10. 不能取消其他租户发票 | B 用有效凭证取消 A 发票，之后 A 正常处理原发票 | B 被拒，A 状态与资金不变；A 的正向操作仍有效 | P0 |
| 11. 取消后不被恢复复活 | 在真实未完成投递中取消，再触发恢复/原数据重启；选择一处与结算竞争的边界 | 若取消成功则不能再 Paid；不可取消时明确拒绝并保持真实终态；Received/Expired/preimage 规则待确认 | P0 |
| 12. 无本地授权的 TLC | 有效 invoice 但 SDK 没有授权，随后按选定策略收尾，再发送正常付款 | 不签未批准状态、不泄露 preimage；原付款有明确结果，同一通道能继续；取消或补授权策略待确认 | P0 |
| 13. 授权存在但内容不匹配 | 使用错误金额或方向的代表授权，再作合法支付对照 | 拒绝不匹配承诺，不误用另一份批准；不能把“授权存在”当匹配 | P0 |
| 14. 注册与刷新身份稳定 | 首次合法注册、相同 RootSigner 再注册、合法 challenge 刷新凭证 | 唯一身份；重复注册拒绝且原记录不变；刷新保留原 key/通道绑定 | P1 |
| 15. key 冲突不污染原租户 | B 独立 RootSigner 尝试用 A 协议 key 注册，拒绝后用独立 key 注册 | 不覆盖 A、不产生错误 key 归属；A/B 凭证隔离；失败 nonce 规则待确认 | P0 |
| 16. 注册数据重启后仍正确 | A/B 注册、A 开通后以原数据重启，刷新凭证并继续 A 业务 | 仍定位原身份/通道，计数与绑定不丢；索引修复的旧数据迁移另定版本 | P1 |
| 17. 注册规模阶梯 | 固定环境下随 tenant 数增长测首次注册、刷新、冲突拒绝 | 每阶段功能仍正确；记录分项时延/样本，阶梯与上限待 Gate2 确认 | P1 |
| 18. 连续付款后的状态和恢复 | 同一通道有界连续付款，后段待签时用原存储重启 SDK | 逐笔仅结算一次、恢复原请求；分别采集单通道状态/整库大小及耗时；不套用评论数字作阈值 | P1 |
| 19. 未来缓存不能使用旧授权/nonce | 在已固定的缓存修复版改变真实存储状态，并访问两个独立租户 | 不沿用旧拒签/旧批准、不串租户；具体失效场景须先读修复 diff | P0，修复后 |
| 20. 未来修剪不能丢失惩罚/恢复能力 | 产品自行积累并修剪历史后，验证合法旧撤销承诺及当前承诺/错误签名对照 | 合法惩罚有效，当前承诺/坏签名拒绝，保留必要待签恢复材料；先固定保留规则与合约 | P0，修复后 |

<!-- TEST-CASES-BEGIN -->
本轮无新增正式用例行。Gate1 确认选定范围后，Gate2 才为独立行为分配稳定 ID、写精确五列表、时间预算、资金公式和适配方案；所有新增行初始未映射。正式行检查器因此不能把本范围文件判为完整用例设计。
<!-- TEST-CASES-END -->

## 执行可行性、复用和分批建议

原定顺序为 **第一批收款归属 1/2 → 第二批接纳一致性 5/6/7 → 第三批发票取消 9/10/11**；三批已按此顺序进入各自 Gate2/Gate3，结果见各评审和运行记录。**12/13**仍须先明确安全收尾契约，**3/4/8/14～18**按对应修复及预算另行分批，**19/20**只保留为修复准入条件，不把未来实现混入 843 验收。已执行的三批不代表其余候选方向获准实施。

- 目的地：当前 actor、SDK `OnchainSpendAuthorization` 和上游 agent 均把 sponsor 与 destination 耦合。可用独立 D_A 做真实拒签负向，但不能只改 Python expected 值就得到正向；不得将 S 额外批准后声称独立退出通过。首批 plain CKB、无 pending TLC，退款和 UDT 不顺带运行。
- 接纳时序：现有签名 HTTP gate 不能阻塞服务 actor 邮箱，CPU 压力/随机 sleep 也不能证明发生在哪个持久化点。Gate2 先核查产品已有可复用测试入口或指定测试分支能力；没有入口就保留夹具缺口，不自行添加产品钩子或 Rust 压力测试。同 key 重投、接纳后崩溃也需各自可证明的触发点。
- 发票/授权：公开 RPC 与真实 SDK 授权存储可作入口；当前 allowlist 拒绝是待修复结果，不把它吞掉当业务通过。取消先核状态和 preimage，再看异步 delivery 与下一笔支付；只检查 `Cancelled` 或拒签日志不够。
- 注册规模：须能只注册身份而不为每个 tenant 启动 agent/通道，才能区分服务查询成本与夹具开销；需要合法 challenge 签名和分项时延。不能凭 RPC 成功证明索引实际使用，也不直接规定必须支持一万租户。
- 长期状态：复用原支付/恢复逻辑，但逐笔核对并以同一通道/同一存储累积；固定轮次数、样本和资源预算，不无限加负载。单通道状态与 `snapshot.bin` 整库大小分别命名；没有导出能力就注明，不能把整库尺寸伪称 StoredSigningState。
- 修剪/缓存：只验证真实产品行为，不手删历史或伪造裁剪。最新 revocation 可覆盖哪些旧承诺、pending 记录和 nonce 必须保留多久，均以实际协议/修复审查为前提。评论者 mock-chain 成功不替代本地真实链证明；CKB/UDT 和不同合约字节分开确认。

本次 Gate2 就地补强 `LSP-WATCHTOWER-01`，保留 ID 和原结果；02先固定历史D=S的分段验证边界，独立收款恢复另批再评，03/04继续证明RPC身份隔离，不复制为新用例。已有 `wrong_destination` 自检可复用，但要区分修改授权对象与固定批准下修改交易。RETRY-05、PAYMENT-01～03、RECOVERY 的旧断言保留；新的服务接纳竞态不能冒充已有 HTTP/签名恢复。所有实质行集变更仍须 Gate2 明确确认，之后才同步全部映射。

本轮没有展开全组合故障、UDT/MPP、跨进程共享 signer、任意断电点、全部数据迁移和长期资源压测；也不声称这些已被整个 PR 覆盖。遇到 #1674/#1706 相同症状继续沿既有归因，不把上述新缺口归入旧 issue。

第一批交接：方向1/2的[完整Gate2行集、资金提案与预算](watchtower-settlement.md#独立收款与目的地替换gate22026-10-29)已获用户明确确认。Gate3首批因测试证据序列化缺陷停批的记录保留；修正后经用户重新授权，固定843完成独立构建、适配自检、旧02一次及05单次，整批570.293秒、exit0，GPT6.1sol复核通过。05只验证SDK sponsor约束拒绝，01/06仍待产品修复版。

第二批交接：方向5/6/7的[完整Gate2](delivery-acceptance-consistency.md)已获用户确认，`LSP-DELIVERY-01～06` 已建立Python TEST-MAP，固定843；两种actor超时、active/成功终态原样重投、金额前置拒绝及真实B目标冲突保留原资金判据。测试薄包装复用原 `run_node`，通过同进程registry接入代理。第七批01取得原调用超时后接纳的无下游支出样本但未过终态；第八批正常对照因逐K完成原因采样不足而停。第九批正常资格和正式01通过；02在薄包装受控丢弃接纳回复、产品真实5秒调用超时的故障注入下，原K失败而同K下游session/attempt成功，早期产品一致性断言失败，最终资金与30秒稳定未执行，不能声称最终持久损失；03～06未运行。正式通过 **1/6**，此新失败不归入旧#1674/#1706。见[第七批](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第七批01终态判据未过2026-10-30)、[第八批](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第八批逐k完成采样缺口停批2026-10-30)及[第九批运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第九批01通过02产品一致性失败2026-10-30)。其余方向和退款夜跑结论不变。

第三批交接：方向9/10/11已形成[Hosted 发票取消 Gate2 三行](hosted-invoice-cancellation.md)，01/02已实施并建立TEST-MAP，03的`Received`取消契约待产品明确、未映射。固定843对01的单次诊断证明真实A tenant token可创建hash-only Open发票，但调用`cancel_invoice`收到`-32999 Unauthorized`，节点指出tenant allowlist缺该方法；旧付款资金及新付款后半步骤未执行，02/03未运行。此为产品入口缺口，不把operator token绕过或统一拒绝算作租户功能通过，见[取消运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-hosted租户发票取消真实入口拒绝2026-10-30)。

GPT 6.1 sol 已分别复核资金归属、接纳/取消/授权、注册/长期状态，并复核本范围全文；已按反馈把跨模块同时推进改为上述三批顺序。未触发 Daybreak。正式行设计检查识别 0 行、退出 1，唯一结构错误为 `no case definitions`：本文件有意停在 Gate1 范围，不能据此宣称 Gate2 完整设计检查通过，也不为消除提示提前生成行集。

`git diff --check` 退出 0；项目映射检查为 112 条评审、108 条映射，退出 1 仍仅有既有 PMP-01～05、SETTLE-01 六个孤立映射，无重复 ID。这是Gate1交接当时的结果，彼时没有增加/修改正式行或映射；本次Gate2静态检查见watchtower评审，不把检查当作产品行为验证。


### 2026-10-30 独立夜间批结果

固定843的独立新批中，LSP-DELIVERY-03～06各执行一次并通过，逐K、四端资金及30秒稳定窗口均完成；总488.48秒、batch.exit=0。仅复用代码和产物摘要匹配的已有正常资格，没有重跑01/02。六行正式通过从1/6增至5/6，02的原产品一致性失败保留；不由本批通过冲销。映射行和用例预期不变。原始命令/源码/事件/JUnit及收尾见本夜结果（本地证据：`../../report/lsp-night-new-84333ee-20261030T030349/RESULT.md`）。

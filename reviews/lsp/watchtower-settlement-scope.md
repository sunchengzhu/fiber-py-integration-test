# Gate1：Hosted 租户强关后的 watchtower 签名与结算

**这批要回答：通道被强制关闭后，LSP 能否等到所属租户的 SDK 授权签名，再把这条通道的钱按批准的地址和费用完成链上结算；一个租户暂停或掉线，会不会影响另一个租户？**

沿用本对话的阶段名称：Gate1 先确定范围和环境能力，Gate2 展开中文场景表，Gate3 实现 Python 自动化。本文件只是范围草案，不创建用例 ID 或 TEST-MAP，也不代替完整设计评审。当前 ai-test-agent 规范（本机规范：`/Users/sunchengzhu/project/ai-test-agent/SKILL.md`）已采用 v2 的 G1/G2 命名；不能把这份范围草案当成其要求的完整 Spec、用例和独立评审已经完成。

## 分析基线

以下本地证据路径相对仓库根目录，原始材料仅保留在本机，不随 Git 提交或推送。

- 产品 head：`8419c005e2d0e737c5abf7e0f881aaedbc6fd300`。
- base / merge-base：`2ba4b2559aa885458d9c60469a1e190d71473c15`。
- FNN、官方 SDK agent 与本地测试驱动版本、产物摘要已核对一致；原材料见 版本快照（本地证据：`report/lsp-python-status-20261020/inputs.json`）、PR 原始信息（本地证据：`report/lsp-python-status-20261020/pr-status.json`）。
- 当前已有覆盖和执行结果见 Python 进度汇总（本地证据：`report/lsp-python-status-20261020/summary.md`）。本轮不构建、不运行测试，不修改产品代码。

## 为什么选这一批

已有 Python 用例证明了正常开通、收款、协作关闭，以及部分签名异常恢复。截止保护用例也证明了有效承诺能上链，但**承诺上链只是把通道关掉，尚未证明后续结算能完成**。

因此先补“无未完成 TLC 的强关结算”。它包含真实资金、外部签名和租户身份，又避开 TLC 成功兑现、超时退款、撤销惩罚等不同资金路径，便于先把基础流程测清楚。普通开通超时的已知问题不影响按正常签名流程开通本批通道。

上游已有 [Hosted watchtower E2E 场景](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/tests/bruno/e2e/lsp-remote-signer-watchtower/README.md)：公共 LSP 强关，SDK 收到 watchtower 事件并提交签名，等待承诺延时后结算。本轮只把它作为设计依据，没有运行该套件。

## 必须先说清楚的钱款去向

**当前实现的结算输出使用 LSP 的费用钱包地址。上游场景也是事先批准把资金结算到公共 LSP T 的 sponsor wallet。不能把这个流程描述为“钱已回到租户自己的钱包”。**

依据：[watchtower 构造结算输出](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/crates/fiber-lib/src/watchtower/actor.rs#L1717)、[上游显式授权](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/tests/bruno/e2e/lsp-remote-signer-watchtower/09b-authorize-settlement.bru#L24)。

本批建议沿用这个明确授权的地址，仅验证**授权、签名、链上结算的一致性**，不据此验收用户自托管取回能力。若本批要求“回到租户独立钱包”，应先确认产品能力，不能在测试里偷偷换成 LSP 钱包。

目的地址和费用上限必须来自测试事先给 SDK 的本地授权；不能收到服务端待签交易后，照抄其中的地址和费用作为“独立批准”。上游 10,000 Shannon 是场景授权预算，尚不能直接当作本环境的实际手续费或正式产品限额。

## 候选范围

只用私有 CKB 通道、真实 SDK、已确认注资和零 pending TLC；以公共 LSP T 发起强关作为统一入口。正常流程先可达，再增加异常。

| 方向 | 场景边界 | Gate2 需要落实的可观察结果 |
| --- | --- | --- |
| 正常结算（优先） | 事先批准所属通道、目的地址和费用预算；T 强关，SDK 正常签名 | 存在真实 Settlement 待签请求、SDK 签名及节点接受记录；结算交易确认并花费对应承诺输出；按事先授权核对地址和实际费用，核清该通道资金 |
| 租户隔离 | 两个租户各有自己的通道；B 尝试读取 A 的 watchtower 请求，并用 B 身份提交 A 的真实有效签名 | 跨租户读取与提交不能成功；A 的请求及资金路径不被推进或替换；恢复由所属租户处理后，各自完成正确结算 |
| A 暂停不影响 B | 截住 A 的真实 watchtower 签名提交，保持节点运行；让 B 正常结算，再放行 A | B 不必等 A 就能完成；A 没有在未得到自己的有效签名时被算作已完成；放行后 A 完成自己的结算，不串用签名或资金 |
| 签名端短暂掉线恢复 | 已捕获真实待签工作后中断 SDK 与 LSP 的连接，随后用原身份、存储及授权恢复；本批不重启 FNN | 恢复后处理仍然有效的待签工作，最终完成原通道结算；确认资金没有重复支出或重复计入。请求因交易输入合法变化而换 ID 时，不能强行要求 ID 永远不变 |

四个方向属于同一个 watchtower Settlement 流程；不是完整 watchtower 功能矩阵。是否需要拆成多行用例、具体暂停点及等待上限，放在 Gate2 写清楚后再评审。

## 源码支持与待核实边界

| 依据 | 对本批设计的约束 |
| --- | --- |
| [watchtower RPC](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/crates/fiber-lib/src/rpc/watchtower.rs#L379)按授权节点身份及通道查询记录 | 跨租户测试必须使用真实租户认证和目标通道，不能仅用错误签名代替身份隔离 |
| [watchtower 扫描](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/crates/fiber-lib/src/watchtower/actor.rs#L294)逐项处理待签工作 | 支持分析“A 等签名、B 继续”的预期；是否实际互不阻塞仍须 Python 执行证明 |
| [SDK agent 事件处理](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/tests/fiber-lsp-sdk-agent/src/agent.rs#L580)及[验证后签名](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/tests/fiber-lsp-sdk-agent/src/agent.rs#L695) | 使用真实 SDK 及链验证，不在 Python 中伪造签名或跳过本地授权 |
| [请求 ID](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/crates/fiber-lib/src/watchtower/signer.rs#L95)与待签交易内容关联 | 恢复测试比较同一有效工作和资金结果；若要断言同 ID，必须先证明输入及待签交易未变 |
| [PR remote signer 设计说明](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/docs/notes/hosted-lsp-remote-signer.md) | Hosted 租户身份、外部签名及 watchtower 授权是本批产品背景；不把原型实现细节自动升级成整个 PR 的验收承诺 |

## 环境已有能力与缺口

| 项目 | 现状和下一步 |
| --- | --- |
| Python 节点、租户、真实通道、SDK 存储、CKB 查询和挖块 | 已有，可复用本目录 LSP 夹具和框架；不需要新增 PR 专用公共配置 |
| SDK watchtower 事件分派 | 官方 agent 已支持；本地驱动走真实 agent 的 `handle_event`，可复用 |
| watchtower 本地授权入口 | 现有测试驱动尚未暴露本批需要的通道、地址和费用批准；Gate2 明确最小接入方式 |
| 独立链验证与合约依赖 | 官方 agent 的 devnet 实现硬编码 genesis 输出 5/6/7；Python 环境使用自己的链快照和部署合约，不能直接假定兼容 |
| watchtower 暂停、捕获及直连提交 | 现有 gate 主要处理通道签名 RPC；尚未实现本批 watchtower 查询/提交拦截，必须保留真实 SDK 生成与 FNN 验签 |
| 最终资金核对 | 现有截止测试只到承诺确认；需增加结算交易追踪、成熟条件和 sponsor 输入/找零的核对能力 |

链验证差异依据：[官方 chain verifier](https://github.com/nervosnetwork/fiber/blob/8419c005e2d0e737c5abf7e0f881aaedbc6fd300/tests/fiber-lsp-sdk-agent/src/chain.rs#L89)、本地 [FiberTest 部署](../../framework/basic_fiber.py)、[开发链合约模板](../../source/fiber/dev_config_3.yml.j2)。现有签名 gate 见 [_retry_signer_gate.py](../../test_cases/fiber/devnet/lsp/_retry_signer_gate.py)。

**建议实现边界：Python 用例负责操作和断言，局部驱动只补调用真实 SDK 所需的适配。** 若需修改 `_sdk_driver.rs`，其目的只是让 Python 调用官方 watchtower 授权和链验证接口，须在 Gate2 列明；不会新增 Rust 压力测试，也不修改 FNN/SDK 产品实现。优先适配现有 Python devnet；若只能另建链环境，先回到评审，不默认扩建框架。

目前不能说环境已经具备可直接执行全部场景的能力。Gate2 必须先把链验证适配和独立资金核对方案写实；若无法做到，保留缺口，不能删掉验证让测试通过。

## 时间控制与资金判据

- 通过真实 RPC、SDK 记录和链上状态建立检查点。暂停必须发生在实际 Settlement 请求/签名出现之后，不能靠固定睡几秒猜状态。
- 使用本地挖块工具推进到承诺输出的实际 `since` / epoch 成熟条件；不改宿主机时间，不以“挖了若干块”替代成熟校验。
- Gate2 按实际扫描周期、链成熟条件及本地运行余量制定有界轮询。该等待预算用于判定测试结束，不是产品性能 SLA。
- 正常结算必须同时证明 SDK 签名被接受和对应链上支出确认。仅看到 `Closed`、仅看到某笔交易或 SDK 返回成功，都不够。
- 沿“原注资输出 → 强关承诺输出 → 结算输出”追踪本通道；核对授权地址、sponsor 投入/找零和实际手续费。公共费用钱包可能被两个租户共用，不能用它的总余额增加冒充某一个租户已结算。
- 恢复时重新核对输入仍可用、请求仍适用；没有新的业务授权时，不应借重连放宽目的地址或费用预算。

## 本批明确不覆盖

- 含未完成 TLC 的 preimage 兑现、到期退款、付款方解锁和撤销惩罚。本批通过也不能关闭 TIMEOUT-10/11 的完整资金取回缺口。
- 把结算钱款转到租户独立钱包的产品能力，以及授权地址/费用篡改的完整对抗矩阵。
- FNN 重启、租户驱逐、存储损坏、多设备、并发压力与性能基准。
- UDT、MPP、多跳支付及 Hosted 租户主动付款。
- 整个 PR 的逐行代码审查或合入验收。

## 本轮需要确认的范围

建议先按上述四个方向推进，并接受“结算到事先批准的 LSP 费用钱包”作为这批测试的明确前提。批准范围后，下一步是 Gate2 的中文用例表及环境适配方案；仍不直接修改自动化。

已有 16 条当前版本待回归、普通开通超时失败和既有断言缺口继续保留，不用本批新增覆盖替代。范围确认也不表示这些旧问题已经解决。

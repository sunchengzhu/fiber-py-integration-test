# Gate1：Hosted 租户强关后的 watchtower 签名与结算

用户已通过本 Gate1，当前评审入口为 [Gate2 四条用例、时间预算、资金断言和独立链适配](watchtower-settlement.md)。Gate2 核实固定 genesis 验证器与当前快照不兼容，因此未授权恢复采用分段证据；用户于 2026-10-25 明确接受并授权 Gate3，2026-10-27 经用户授权修复隔离链合约后自检及聚焦四条通过；首轮固定复跑 02 出现陈旧待签工作失败、后两轮停止；后续独立诊断已确认旧项遮蔽有效后继请求、显式批准后完整 240s 不恢复的产品 bug，见 Gate2 文档的最新归因入口；本文件保留当时范围与已知前提，不将其直接记成自动化通过。

本批先回答：**无未完成 TLC 的 Hosted 通道强关后，所属 SDK 能否按事先批准的地址和费用完成真实链上结算；没有本地批准或使用其他租户身份时，能否阻止越权签名与提交。**

沿用本对话的 Gate1 → Gate2 → Gate3：本文件评审范围、依据和环境边界；确认后才展开完整用例、稳定 ID、预算和断言，再次确认后才实现自动化。本轮没有新增 watchtower 用例行、TEST-MAP 或测试实现。原草案的单租户暂停和 SDK 掉线恢复保留为下一批，先把基础结算与授权判断做实。

## 版本与已有证据

- 用户已批准执行基线切换至 **`04c206465b48da85b99aa58e80afe9801a2cb2db`**。2026-10-24 重新获取固定提交，`download/fiber/source-pr-1623` 干净；FNN、官方 SDK agent、本地集成驱动同源构建，产物为 `download/fiber/pr-1623-04c2064/`，构建时未改产品代码。当前 Python 夹具与构建脚本均锁定此 SHA。
- [相对 24b5c38 的差异](https://github.com/chenyukang/fiber/compare/24b5c38bc098aeb29de5f6af7ac28dc667f218e3...04c206465b48da85b99aa58e80afe9801a2cb2db)只有浏览器 WS 鉴权、无填充 base64url token 及相关测试/文档/依赖，没有修改 watchtower、SDK 链验证、通道或合约逻辑。以下源码依据均已对照此固定版本。
- 新版最小兼容回归为 **2 passed in 201.45s，退出 0**：`LSP-RECOVERY-01` 与 `LSP-SUBSCRIPTION-02`。覆盖新注册 token、HTTP Bearer、现有 SDK 的 WS 签名事件送达、开通、真实付款和协作关闭，详见 [运行记录](../../test_cases/fiber/devnet/lsp/README.md#04c2064-最小兼容回归2026-10-24)。**这两条不证明 watchtower 结算、浏览器 subprotocol 或其余 42 条方法通过。**
- 原 `download/fiber/pr-1623/` 的 `24b5c38` 构建及全部历史结果保留；旧版已通过的付款恢复、超时强关和败方识别不转记为新版结果。`LSP-TIMEOUT-04/05` 继续关联 [#1674](https://github.com/nervosnetwork/fiber/issues/1674)，本批未重跑或宣称解决。

## 已有覆盖核对

| 已有资料/测试 | 能借鉴什么 | 仍缺什么 |
| --- | --- | --- |
| [LSP 截止保护与败方恢复](channel-signing-deadline.md)、[Python 实现](../../test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py) | 真实承诺广播、确认、原通道关联、300 秒 Hosted 关闭扫描的恢复证据 | 没有证明后续 Settlement 签名、资金结算或自托管取回 |
| [普通 watchtower 用例](../../test_cases/fiber/devnet/watch_tower/test_watch_tower.py) | 成熟推进、真实链上支出与普通节点结算 | 使用普通节点本地密钥，不验证 Hosted SDK 本地授权或租户身份；本轮没有重跑这些旧用例 |
| [扫描 RPC 错误](../../test_cases/fiber/devnet/watch_tower/test_pr1528_abort_scan_on_rpc_error.py)、[禁止移除存活通道](../../test_cases/fiber/devnet/watch_tower/test_pr1463_remove_watch_channel.py)、[独立 tower 兼容测试](../../test_cases/fiber/devnet/compatibility/test_full_hash_standalone_watchtower.py) | 扫描、记录生命周期和合约版本兼容的已有判断依据 | 不能替代 Hosted 外部签名与授权端到端结果；保留现有映射，不批量改造 |
| [上游 Hosted watchtower Bruno 场景](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/bruno/e2e/lsp-remote-signer-watchtower/README.md) | T 强关、SDK 事先授权、签名和真实 CKB 扫描的设计参考 | 含手动关闭检查；其“原承诺已花费”和“存在提交”检查不能独立证明 A 的份额已完成结算；本轮未执行此套件 |
| [上游 external signing 测试](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/external_signing_tests.rs#L537) | 无 TLC 的 for_remote/后继结算组合、正确密钥、RPC 接受与拒绝 | 使用 fixture/模拟输入，不能转记为 Python Hosted 真实资金回归 |

已检索当前 `test_cases/fiber/devnet/lsp/`：尚无调用 `get_watchtower_signing_status` / `submit_watchtower_signature` 的 Python 用例。已有 channel_signing 订阅覆盖也不能算作 watchtower_signing 覆盖。

## Spec

### SPEC-01：本地批准后才完成所属租户的真实结算
Condition: 私有 CKB 通道已正常注资和就绪，零 pending TLC，Hosted A 有非零可结算份额且能构成有效 CKB 输出；公共 LSP T 强关；A 的 SDK 事先批准通道、目的地址、总费用上限，并具备独立链验证能力。
Expected: SDK 验证待签内容与真实链上输入后，为 A 的 Settlement 请求生成真实签名；FNN 接受并最终形成已确认的对应支出，资金遵守本地批准。
Observable: A 的 node/channel 身份、SDK 签名和接受回执、实际链上交易及其祖先、目的地址、独立取得的输入容量与实际费用。
Basis: [SDK 本地授权和链验证](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/agent.rs#L692)、[Settlement 构造](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1612)、[SDK 授权说明](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/README.md)。
Source: observation
Testing: not_tested — 本轮仅做范围分析，Gate2 固定资金公式和交易关联断言。

当前实现及上游场景支持此拟验证行为，不把原型实现自动视为完整资金取回契约。

### SPEC-02：没有本地批准时拒签，显式批准后可继续
Condition: 已产生 A 的真实 Settlement 工作；身份、密钥、链验证、成熟条件和连接均正常，但 A 尚未授予本地 watchtower 批准。
Expected: SDK 不产生/提交 A 的有效 Settlement 签名，A 的份额不能被算作结算完成；补入独立、明确的本地批准后，对当前仍有效工作重新验证并完成原通道结算。
Observable: 缺少本地批准的拒签证据、A 的提交记录及份额路径；批准后的真实签名、节点接受和资金结果。T 自己的合法结算不构成失败。
Basis: [先检查本地批准，再进行链验证与签名](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/agent.rs#L692)、[官方授权入口](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/main.rs#L45)。
Source: observation
Testing: not_tested — Gate2 明确补授权后的处理入口与预算，不默认 SDK 自动重试策略。

拒签由源码明确支持；补授权后的完整恢复是本批要执行证明的组合行为。

### SPEC-03：其他租户不能读取或应用 A 的 watchtower 签名
Condition: A、B 均为合法注册租户且自身权限足够；存在 A 的真实待签工作，已取得但暂未提交 A 的有效 SDK 签名。
Expected: B 身份读取 A 的状态或提交 A 的真实有效签名均被拒绝；不能推进或替换 A 的工作。所属 A 可处理当前有效工作并完成正确结算。
Observable: 真实租户凭据、目标通道和请求、跨租户失败、所属 A 的正向对照与最终资金路径；不以错误签名或缺少模块权限冒充身份隔离。
Basis: [按授权 node_id/channel_id 读取和提交](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L395)。
Source: observation
Testing: not_tested — Gate2 可按独立可观察结果拆分读取与提交，Gate1 不预先锁死最终方法数量。

## 测试树

<!-- TEST-TREE-BEGIN -->
- 无 pending TLC 的 Hosted Settlement
  - 本地批准 → 真实签名 → A 份额对应支出确认 [pending] — SPEC-01；Gate2 分配 ID。
  - 未批准 → 拒签且 A 份额未结算 → 显式批准后完成 [pending] — SPEC-01、SPEC-02。
  - B 读取 A 请求被拒绝 [pending] — SPEC-03。
  - B 提交 A 有效签名被拒绝，A 正向对照成功 [pending] — SPEC-01、SPEC-03。
- 下一批保留
  - A 扣签时 B 独立结算、SDK 原存储掉线恢复 [unanalysed] — 待基础授权与资金判断成立后，再展开各自检查点、预算和映射。
- 范围外
  - TLC 兑现/超时退款、撤销惩罚、租户独立钱包取回 [unanalysed] — 需要单独契约和资金路径分析。
<!-- TEST-TREE-END -->

## 用例范围（Gate2 入口）

<!-- TEST-CASES-BEGIN -->
本轮不建立正式用例行或 ID。下列三项范围确认后，Gate2 展开完整五列表、时间预算和共同断言，再交人工评审。
<!-- TEST-CASES-END -->

| 本批方向 | 优先级 | 场景边界 | 必须证明的结果 |
| --- | --- | --- | --- |
| 正常授权结算 | P0 | A 有非零份额、零 pending TLC；事先独立批准目的地址和总费用；T 强关 | A 的真实 Settlement 签名被接受，沿原 funding/commitment 及合法后继输出追踪到 A 份额的已确认结算；地址、sponsor 投入和总费用可核清 |
| 未授权拒签后恢复 | P0 | 其他签名与链验证前提正常，仅缺少 A 本地 watchtower 批准；观察后显式批准 | 批准前 SDK 不签、不提交 A 的 Settlement，A 份额未结算；批准后重新验证当前工作并完成原通道结算，不依靠放宽地址或费用 |
| 跨租户隔离 | P0 | B 有正常自身权限；读取 A 工作，并用 B 身份提交 A 的真实有效签名 | 读取和提交均被拒绝，A 工作不被 B 推进或替换；A 的正向对照及资金结果正确，失败原因不能只是签名错误或权限不足 |

## 资金与时序的共同边界

1. **结算目的地址目前是事先批准的 LSP 费用钱包，不是租户独立钱包。** [actor.rs 的输出构造](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1710)及上游场景一致。本批验证授权与链上结果一致，不能据此验收自托管取回；目的地址和 `max_fee` 必须来自本地意图，不能照抄待签交易。
2. **允许 T 先结算自己的份额。** [本地结算公钥判断及后继输出](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1359)决定当前侧能解锁的份额。原承诺变 dead 可能只是 T 的合法支出，必须继续追踪后继 commitment，并证明 A 的 SDK 签名对应 A 份额的最终确认。未授权阶段不能要求整条链或所有承诺输出完全不变。
3. 资金核对以独立 CKB 输入为准：逐笔核对 `sum(inputs.capacity) - sum(outputs.capacity)` 为实际总费用且不超批准；区分 commitment 剩余容量、sponsor 投入及批准地址输出。sponsor 资金可能合并进结算输出，不能把整个输出容量当成 A 的收入。最后一方结算还包含剩余保留容量，不能用开通余额或固定 500 CKB 代替精确账本；Gate2 需给出分步公式。
4. A 份额必须非零，sponsor 资金与输出占用容量条件充足，避免 T 单方结算或零余额造成假阳性。签名被接受和真实链上确认缺一不可；`Closed`、原输出已花费或出现任意交易都不够。
5. [请求 ID 是完整待签交易字节的哈希](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/signer.rs#L95)。合法后继输出或 sponsor 输入变化可能换 ID；使用原通道、资金祖先和当前可用工作关联。只有确认待签交易未变时才要求 ID 不变。
6. 使用真实 epoch/`since` 成熟条件和有上限轮询，不靠固定睡眠或若干块猜测。当前 LSP 模板的 watchtower 扫描为 **60 秒**，与 Hosted 关闭识别的 **300 秒** 是两条不同定时任务；普通 watchtower 旧测试还覆盖配置为 5 秒，不能移用其时限。本批预算应容纳成熟、首次扫描、签名后的后续扫描、确认及余量，Gate2 单独列阶段预算，不把候选等待值当产品 SLA。
7. 不用手动 `check_channel_shutdown` 冒充自然扫描通过；若 Gate2 需要主动触发辅助动作，必须明确其作用和证明边界。暂停/恢复检查点建立在实际请求上，不通过改数据或伪造成功响应取得。

## 环境能力与 Gate2 前置工作

| 项目 | 已有能力和必须补齐的边界 |
| --- | --- |
| FNN、SDK、Python、CKB | 新版兼容入口已通过；沿用 `FiberTest`、现有 devnet 快照和 Hosted 开通，构建仍为 dev/debug-add-tlc，本批不用 TLC 注入接口 |
| 本地 watchtower 授权 | 官方 agent 已有 HTTP `POST /authorize`、`--ckb-rpc`、`--contracts-dir`；当前 Python `_sdk_driver.rs` 没有 watchtower 授权操作，也未调用 `configure_chain`，不能直接复用就宣称能签 Settlement |
| 独立链验证 | [官方 DevChain](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/chain.rs#L96)要求 genesis 输出 5/6/7 为 auth/funding/commitment 并与本地二进制一致；当前 Python 使用既有链快照，兼容性尚未证明。Gate2 必须核清可信合约/dep 来源、live input、祖先与 maturity 的验证办法 |
| 签名捕获和身份对照 | 当前 HTTP gate 只控制 `submit_channel_signature`；watchtower 捕获/放行需局部接入，仍由真实 SDK 生成签名和 FNN 验签，不生成 Python 假签名 |
| 链上账本 | 已有关闭交易查询可借用，但还需后继 commitment 跟踪、独立输入解析和 sponsor/保留容量核算；不能只增加“原输出 dead”断言 |

先评估复用官方 agent 的现成授权入口；如需扩展本地 Rust 驱动，仅限让 Python 调用真实 SDK 授权/链验证的最小适配，Gate2 写明后再评审。本轮不实现适配、不新建 devnet、不绕过 ChainVerifier、不修改 FNN/SDK/合约产品代码，也不扩展 Rust 压力测试。若无法在现有链上完成独立验证，应保留环境缺口并返回评审，不能删断言换通过。

## 验证边界与下一门禁

这批不覆盖含 TLC 的 preimage 兑现/超时退款、撤销惩罚、完整授权篡改矩阵、浏览器 WS 新鉴权、FNN 重启、租户驱逐、存储损坏、多设备、UDT、MPP 或压力。先前受控败方恢复只证明关闭识别，不证明本批资金结算；未经干预的竞态获取概率也没有因本轮兼容通过而补齐。

请评审上述三个方向，以及“结算到事先批准的 LSP 费用钱包”和“独立链验证适配必须在 Gate2 写实”的边界。下一步仅展开这些方向的完整用例与预算，尚不进入 watchtower 自动化。

2026-10-24 GPT 6.1 sol 已独立复核本轮代码、构建清单及实际摘要、2/2 的 JUnit/退出码和 HTTP/WS 原始证据，并核对上述 Gate1 与固定源码一致，无阻断项，未触发 Daybreak。独立复核不替代本批范围的人工确认。

检查记录：`python3 scripts/check_test_map.py` 识别 93 个评审 ID、89 个有映射，退出 1，仍报告既有 PMP-01～05/SETTLE-01 孤儿映射及历史 report overlay 的 16 个重复评审 ID；本轮未增删映射。`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/watchtower-settlement-scope.md` 最终退出 1：相同历史重复 ID，且 Gate1 尚无正式用例定义，三个 observation 预期和 pending 分支待人工确认；不把它写成完整用例设计检查通过。初次 Source 行格式问题已修正，初次和最终输出均保存在本地证据目录 `report/lsp-compat-04c2064-20261024.hkbapv/`，分别为 `test-design.log`、`test-design-final.log` 及同名 `.exit`。映射检查见 `test-map.log/.exit`；静态编译及 `git diff --check` 退出 0。

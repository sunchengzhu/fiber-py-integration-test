# Gate1：真实付款的延迟签名恢复

用户已明确通过本文件的三个方向及 `24b5c38` 基线，也已确认 [Gate2 的三条完整用例、时间预算与共同断言](delayed-payment-recovery.md)。2026-10-24 进入 Gate3，实现与执行见该文档和运行记录。以下保留 Gate1 当时的范围与分析依据。

本轮只评审三个方向的范围、证据要求和环境能力：在线延迟、SDK 完全离线、一个租户等签时另一个租户收款。沿用 Gate1 → Gate2 → Gate3：范围确认后才展开完整用例和稳定 ID，完整用例确认后才改 Python 自动化。本轮没有新增 TEST-MAP、执行新增场景或修改产品代码。

本文件原来混合的“反向开通被拒绝”继续留作后续候选；此前 `4028884`/SSE 的分析由本轮重新核对的固定源码取代。旧运行记录仍见 [LSP 运行说明](../../test_cases/fiber/devnet/lsp/README.md)，不转记为本批通过。

## 版本与选择依据

- 建议本批固定 FNN/SDK **`24b5c38bc098aeb29de5f6af7ac28dc667f218e3`**，沿用已经构建和验证过的环境。当前源码 checkout 干净，`download/fiber/pr-1623/build.json` 标明同一版本、`dev` 构建及 `fiber-bin/debug-add-tlc`，未启用 `bench`；本批不使用 TLC 注入接口。Gate3 仍须重新校验实际二进制、驱动摘要和 devnet 合约配置，不能仅信清单。
- 测试仓库基线为 `codex/lsp-core-regressions` 的 `cf937275618d8e51b35a7537788702cf4b67bc31`，保留所有无关本地内容及历史原始证据。
- 2026-10-23 经 GitHub API 核实，[PR #1623](https://github.com/nervosnetwork/fiber/pull/1623) 为 Open，HEAD 是 `04c206465b48da85b99aa58e80afe9801a2cb2db`。[相对 24b5c38 的两笔变更](https://github.com/nervosnetwork/fiber/compare/24b5c38bc098aeb29de5f6af7ac28dc667f218e3...04c206465b48da85b99aa58e80afe9801a2cb2db)为浏览器 WebSocket 认证和无填充 base64url token；涉及 RPC、token、测试和依赖，未改通道付款/ACK 逻辑或 SDK 签名实现。这是源码差异结论，**不是 04c2064 已运行通过**。
- 先把较稳定的业务语义补齐；浏览器认证、token 编码和新版构建适配单独处理。若 Gate2/3 要换目标 SHA，先重核上述差异与检查点，不无声切到最新版本。

## 已有覆盖与本批缺口

| 已有用例及全部映射 | 已覆盖 | 本批新增的判断依据 |
| --- | --- | --- |
| `LSP-RECOVERY-05/06`：[付款恢复](../../test_cases/fiber/devnet/lsp/test_channel_signing_recovery.py)；各一个映射 | FNN 重启去重、SDK 原存储恢复撤销签名，原支付终态与四端余额 | 没有要求在 `CompleteReceivedCommitment`、T 等 ACK 的同一检查点持续超过普通 30 秒阈值；撤销检查点不能替代本批 |
| `LSP-RETRY-06`：[付款重试](../../test_cases/fiber/devnet/lsp/test_channel_signing_retry.py)；一个映射 | 同一次付款的重复签名不重复结算 | 没有强制跨 ACK 等待阈值，也没有无租户查询的离线窗口 |
| `LSP-SIGN-01`：[租户隔离](../../test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py)；一个映射 | A 开通等签时 B 能开通 | 尚未证明 A 真实付款等签时 B 的独立付款能完成 |
| `LSP-TIMEOUT` 现有 11 个映射：[截止保护](../../test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py) | 外部注资/开通期限、短期限 TLC 强关、受控败方恢复 | 支付部分使用短期限注入；本批使用真实 `send_payment`、正常授权及充足有效期，验证到期前等待和恢复 |

现有映射保留，不删除、不改名，也不只延长某次旧测试的运行耗时就宣称补齐覆盖。原 `LSP-TIMEOUT-04/05` 仍由 [#1674](https://github.com/nervosnetwork/fiber/issues/1674) 跟踪；本批不重做该问题的定位。

## Spec

### SPEC-01：Hosted 通道等待签名时保持原付款
Condition: 公共 LSP T 正向其已注册租户 A 转发真实付款，A 停在关联目标 TLC 的 `CompleteReceivedCommitment`，T 已等待 ACK，TLC 与授权都未到安全截止。
Expected: 跨过普通 ACK 活动超时后，原通道和不可变待签请求仍保留；恢复正常签名后原付款只结算一次。
Observable: 同通道/请求/payment hash、T 的 ACK 证据、通道及 funding 存活、原支付 Success/发票 Paid、TLC 清理及金额和路由费。
Basis: [等待 Hosted 签名的设计](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/docs/notes/hosted-lsp-remote-signer.md#L109)、[活动超时豁免与 ACK 调度](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L6675)、[上游真实收款检查点](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L1206)。
Source: explicit
Testing: not_tested — 本轮只做 Gate1，完整用例、ID 和执行留到后续人工确认阶段。

### SPEC-02：等待保护不依赖客户端在线或查询
Condition: 已取得上述付款检查点，A 的 SDK 进程和已有 WS 会话均结束，观察窗口内不向 A 查询、提交签名或进行保活探测。
Expected: T 仍保留原 ACK 等待和通道；用原 SDK 存储恢复后继续原请求和付款，无需重新注册、开通或重发付款。
Observable: 旧进程退出、WS 两侧关闭、窗口内零租户请求记录、公共侧状态、恢复后的原请求及正常资金结果。
Basis: [设计明确不要求查询、探测或运行时激活](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/docs/notes/hosted-lsp-remote-signer.md#L111)；已有 [SDK 原存储恢复契约](channel-signing-recovery.md)。
Source: explicit
Testing: not_tested — Gate2 固定无查询窗口、会话关闭证据及恢复预算。

### SPEC-03：一个租户等签时其他租户付款仍可完成
Condition: A、B 的独立通道已就绪；A 的上述付款签名持续扣留，P 经同一 T 向 B 发起另一笔真实付款。
Expected: B 在 A 仍暂停时成功且金额/费用正确；A 此时尚未结算，随后放行 A，原 A 付款成功且两笔分别只结算一次。
Observable: 两组 payment hash、发票、租户请求与余额；共享 P–T 通道区分 A 的锁定 TLC 和 B 已完成的增量。
Basis: [租户隔离目标](channel-signing-isolation.md)、已有开通隔离映射及各租户独立付款/签名路径；付款并行结果是本批拟验证的组合推断。
Source: inference
Testing: not_tested — 需要 Gate1 确认范围，再在 Gate2 固定双付款的独立观察与金额断言。

## 测试树

<!-- TEST-TREE-BEGIN -->
- 真实付款跨普通 ACK 阈值后恢复
  - 在线扣留目标承诺签名 [pending] — 对应 SPEC-01；Gate2 分配 ID 并展开完整步骤和断言。
  - SDK 完全离线且不查询租户 [pending] — 对应 SPEC-01、SPEC-02；Gate2 固定关闭证据和计时起点。
  - A 等签时 B 收款，再恢复 A [pending] — 对应 SPEC-01、SPEC-03；Gate2 固定共享通道增量核对。
- 后续范围
  - 反向开通、watchtower 和链上资金取回 [unanalysed] — 本轮不展开，完成本批后再单独评审。
<!-- TEST-TREE-END -->

## 用例范围（Gate2 入口）

<!-- TEST-CASES-BEGIN -->
本轮不建立正式用例行和 ID。下列三项是待确认的范围；确认后在独立 Gate2 文档中给出完整五列表、时间预算及共同断言，再交人工评审。
<!-- TEST-CASES-END -->

| 本批方向 | 场景边界 | 必须证明的结果 |
| --- | --- | --- |
| 在线延迟后恢复 | A 的 SDK 保持在线，真实签名提交被 gate 扣留；取得目标 `CompleteReceivedCommitment` 和公共 T 等 ACK 证据后，持续观察至少 35 秒 | 原请求未应用、付款未完成，原通道未关闭且 funding 未花费；放行后原付款/发票成功，TLC 及锁定额清空，四端余额和实际费用只结算一次 |
| SDK 完全离线后恢复 | 先取得同一检查点，再结束 A 的 SDK；确认已有 WS 上下游都关闭且无在途租户请求后，至少 35 秒不查询或提交 A；以原存储启动 | 等待保护不靠查询或订阅保活；恢复仍为原完整请求和原付款，原身份/通道/授权保留，成功后资金及状态与在线方向一致 |
| A 等签时 B 正常收款 | A 持续停在同一检查点，期间对 B 发起另一笔真实付款；A 的等待至少 35 秒且持续到 B 完成 | B 必须在 A 未放行时完成；此时 A 仍未支付。保存独立上下文和共享通道增量，之后 A 完成，两笔金额/费用不串单、不重复；不要求 B 完成时共享 P–T 上 A 的 TLC 消失 |

## 时间控制与观察边界

1. 固定版本的普通非 `test/bench` [ACK 阈值为 30 秒](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L156)。本批 **35 秒是跨阈值的测试下限，不是产品恢复 SLA**。从目标 TLC、原请求、T 等 ACK 和对应故障条件全部成立后计时；离线方向从进程退出、会话关闭、在途请求结束后计时。不能从开始付款或准备节点计时。
2. 优先复用已存在的 `CompleteReceivedCommitment` 检查点，核对通道、方向、目标 payment hash 与 expiry，并保存完整原请求。公共 T 的 `waiting_ack=true` 必须属于本次付款后的同通道、同公共侧 actor；T 与 Hosted A 共享 FNN 日志和 channel ID，仅按 channel ID 搜日志不足。Gate2 固定 actor/namespace 关联证据，并核对暂停期间无清除 ACK 或推进承诺的证据；单条旧日志不能证明当前检查点。
3. 只用真实 `send_payment` 和真实 SDK 授权/签名，不调用 `dev_add_tlc`，不改时钟、挖块速度、节点数据或产品代码。P–T 正常协议保持，不人为扣住其 ACK；不使用强关测试的停矿、广播门禁或 250 ms 查询时序。
4. 付款沿用普通单笔 CKB 发票、单路径、非 MPP；已有配置为金额 1,000,000 Shannon、发票/授权 1 小时、最终 TLC 基础期限 1 小时、付款端 expiry 上限 24 小时和 timeout 1,200 秒。SDK 的有效承诺接受与兑现授权仍按原先顺序，不从节点请求推导用户意图。
5. 暂停前核对路径相关 TLC 的实际最早安全截止（含 T、A 及上游付款腿）、SDK 更早的签名/替代承诺窗口、授权和付款剩余预算。拟沿用故障前至少 900 秒、恢复放行前至少 180 秒余量；不能只看发票 expiry 或把客户端等待 35 秒当作业务到期。离线区间用暂停前保存的期限和时钟判断余量，不调用会读取 A/SDK 的检查 helper；恢复后先核对原请求和余量再允许提交。
6. 在线方向有界采样；离线区间只从 P、公共 T、独立 CKB 和被动日志/代理记录观察，不读 A 通道/发票/签名状态、不调用 A 的 SDK 控制接口，也不通过 host 凭据切换查询 A。SDK 进程退出本身不等于 WS 后端已关闭；暂停事件交付也不等于离线。
7. 不无限等 B 或恢复。Gate2 需明确准备、目标检查点、暂停最大时长、B 完成、SDK 启动、原付款完成及清理的阶段预算；35 秒是最短观察，所有阶段还受实际安全余量和总截止限制。候选恢复预算沿用新 SDK 启动/订阅 60 秒、原付款终态 120 秒、成功后连续稳定观察 5 秒；需在 Gate2 统一计算，不能串联超出余量。
8. 待签保留/支付未完成期间，通道仍在原可用状态、无关闭交易，原 funding 仍 live；恢复最终核对同 payment hash Success、发票 Paid、待签/TLC/锁定额清理、镜像余额和实际路由费。只见订阅恢复、`Applied` 或 `ChannelReady` 均不算付款恢复通过。

## 环境能力与 Gate2 必须落实的部分

| 已有能力 | 最小补充与边界 |
| --- | --- |
| 同源 FNN/SDK、独立 devnet、普通 P—T—A 收款、真实 SDK 签名 gate | 只复用已有准备和结果断言；新增准确的承诺/公共侧 ACK 检查点及持续观察，不改公共框架或产品 |
| 真实 SDK 停止/原存储恢复、WS 代理连接记录 | 补齐连接两端关闭和在途请求归零的本地证据；离线区间禁止调用 `_check_payment_window`、`_finish_payment` 等会查询 A/SDK 的 helper |
| 两个租户的独立 SDK 与签名 gate | 现有收款 helper 只保存 `self.payment`，需要局部保存 A/B 两组上下文；共享 P–T 的总余额、已完成 B 与仍锁定 A 分开核对，不机械复用“所有 TLC 清空”的单付款断言 |
| 现有 debug ACK 日志 | 需在 Gate2 明确公共侧 actor 身份、日志时间和同一付款关联；若被动证据不足，不以查询激活 A 的方式补证明，不静默改用撤销检查点 |

这些是源码与现有夹具的可行性分析，不表示新方向已经实测可达。如果 Gate3 不能取得已确认检查点，保存失败，定位夹具或产品原因；需要实质改变检查点/预期时返回评审，不能改成“随便暂停后最终成功”。

## 验证边界与后续门禁

本批不验证反向开通、FNN 重启/租户驱逐、5 分钟重连超时、普通非租户超时对照、超过 TLC 截止后的保护、浏览器 WS 认证、watchtower、链上资金取回、UDT、MPP 或压力。新旧源码相同的业务逻辑也不等于最新 PR 已运行通过；本批结果只能归于实际验证的固定 SHA。

上述三个方向、固定 `24b5c38` 基线、35 秒下限和安全余量原则已获 Gate1 确认。当前评审对象为独立 Gate2 文档的三行及共同断言；Gate3 再实现与执行，维护 TEST-MAP 并保留全部结果。独立复核沿用用户要求的 GPT 6.1 sol，只有实际触发 Daybreak 限制才换 GPT 6 sol。

2026-10-23 本轮检查：GPT 6.1 sol 已独立只读复核范围、源码和已有映射，无阻断项，未触发 Daybreak；这不代替人工 Gate1 确认。相对文档路径检查 31 项通过，`git diff --check` 退出 0。`python3 scripts/check_test_map.py` 退出 1，仍为既有孤儿映射和本地历史 report 快照引起的重复 ID；本轮未增删映射。skill 的 `check_test_design.py --review reviews/lsp/hosted-channel-guards-scope.md` 退出 1：同样存在历史重复 ID，且当前 Gate1 按阶段尚无正式用例定义（`no case definitions`）；不将此结果称为用例设计检查通过，Gate2 完整展开后再检查。没有运行节点或新增付款场景。

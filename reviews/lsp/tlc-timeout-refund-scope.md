# Gate1：Hosted 付款方带 TLC 强关后的超时退款与资金守恒

用户已明确确认本 Gate1；原 Gate2 已进入 Gate3 并因短期限与四小时路由 reserve 不兼容停止。随后 [专用 VM 受控时间 Gate1](tlc-timeout-refund-vm-scope.md) 也已确认，当前评审入口为 [VM Gate2 完整用例、隔离预检、预算、资金断言与最小适配](tlc-timeout-refund.md)。本文件保留原范围依据，不将原执行授权转用于尚待确认的 VM 方案。

范围：建议首批选择 **Hosted A → 公共 T 的单笔真实 CKB hold 付款，T 强关，无 preimage，A 完成链上 TLC 超时退款及后继份额结算**。本轮只评审范围和证明边界；沿用 Gate1 → Gate2 → Gate3，确认本范围后才写完整用例、稳定 ID、预算和断言，再次确认后才实现与执行。

依据：[2026-10-27 交接](../../docs/analysis/pr-1623-handoff-2026-10-27.md)、固定 `04c2064` 源码及现有评审/测试。以下实现观察与组合预期均交人工确认，不把当前实现自动作为产品契约；不新增正式用例行或 TEST-MAP。

## 基线和既有结论

- 2026-10-27 只读 GitHub API：PR #1623 为 open，head 仍是 `04c206465b48da85b99aa58e80afe9801a2cb2db`；base `develop` 为 `2620b5b3fdca082092ce57797d0c22b65c33af59`，本地实际 merge-base 也是该 SHA。本轮只读选定资金路径及相关 diff，不作整个 PR 验收。
- 测试分支 `codex/lsp-core-regressions`，HEAD `cf937275618d8e51b35a7537788702cf4b67bc31`，保留全部原有改动。产品 `download/fiber/source-pr-1623` 干净且 HEAD 为上述 04；实际 `fnn --version` 为 `fnn Fiber v0.10.0-rc1 (04c2064 2026-10-23)`。FNN、官方 SDK agent、本地驱动、Cargo.lock 及驱动/链适配源码摘要与 `download/fiber/pr-1623-04c2064/build.json` 一致；未切换、重建或更新版本。
- 原快照与两份可信 commitment-lock 对照已有 `original-inputs.sha256` 全部 OK。此前已解决的隔离链合约预检问题不再记为当前阻断；将来运行仍需新建隔离工作副本，核对实际部署字节。原快照、24 产物及所有运行证据保持不变。
- TIMEOUT-04/05 沿用 [#1674](https://github.com/nervosnetwork/fiber/issues/1674) 归因；WATCHTOWER-02 沿用 [#1706](https://github.com/nervosnetwork/fiber/issues/1706) 归因。08/10 的竞争假设、TIMEOUT-12 的 330 秒败方识别与夹具修正按交接最终结论处理，均不重新调查。24 的通过不记作 04 通过。

## 剩余缺口核对

| 已有范围 | 已证明的边界 | 仍缺的证据与本轮处置 |
| --- | --- | --- |
| [TIMEOUT-10/11/12](channel-signing-deadline.md) | 含目标 TLC 的承诺确认、未交 preimage 的发票状态、受控竞争败方关闭识别；主要通过证据在 24 | 没有跟踪 TLC 退款、后继结算或真实付款方资金；本批优先补资金路径，不重写原用例 |
| [PAYMENT-01～03](delayed-payment-recovery.md) | 24 上真实付款延迟签名后在安全期限内恢复成功 | 未覆盖业务到期后的失败付款与链上退款；不能用 Success/Paid 的恢复结果替代 |
| [WATCHTOWER-01～04](watchtower-settlement.md) | 04 上无 pending TLC 的授权与资金验证；聚焦 4/4，首轮复跑 02 因 #1706 失败，验收未完成 | 没有 TLC key 签名或含 TLC 的账本；#1706 修复回归、SDK 原存储离线恢复、A 等签时 B 独立结算另批保留 |
| [现有 WS/浏览器订阅](signing-subscriptions.md) | 04 上既有订阅和浏览器鉴权已有各自运行证据 | 不等于链上资金覆盖；本批复用传输与证据捕获，不新增鉴权矩阵 |
| 旧版核心/截止/付款恢复，以及 UDT、MPP、撤销惩罚、反向开通、独立钱包取回、更多自然竞争时序 | 前者有旧版证据，后者仍需按支持范围与已有测试去重 | 分开保留“当前版本回归证据缺口”和“新增行为缺口”；本轮不展开 |

“剩余 30%”仅是粗略估计；没有完整需求分母，不给精确覆盖率。TEST-MAP 表示映射存在，不表示实现充分或执行通过。

普通通道 [test_watch_tower.py](../../test_cases/fiber/devnet/watch_tower/test_watch_tower.py) 和 [test_hash_algorithm.py](../../test_cases/fiber/devnet/watch_tower/test_hash_algorithm.py) 可参考挖块、交易确认、费用读取；本地密钥、5 秒扫描和钱包余额差不能替代 Hosted SDK 授权、60 秒扫描和逐 outpoint 账本。[test_pending_tlc.py](../../test_cases/fiber/devnet/shutdown_channel/test_pending_tlc.py) 的候选场景均已注释，[test_htlc_mutil.py](../../test_cases/fiber/devnet/watch_tower/test_htlc_mutil.py) 为空，不能记为自动化覆盖。上游 [timeout 签名测试](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/external_signing_tests.rs#L335) 和 [SDK timeout→后继结算测试](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/commitment_tests.rs#L2260) 证明设计参考存在，但其模拟链输入不能转记为 Python 真实链通过。

## Spec

### SPEC-01：先取得可证明的未兑现付款和含目标 TLC 的强关承诺
Condition: A/T 的私有 plain CKB 通道正常就绪；T 创建仅含 payment_hash 的单笔 hold 发票，preimage 只留在测试端；A 事先保存精确 outgoing 授权，再以租户身份调用一次 send_payment；双方完成该 TLC 的承诺和撤销 ACK。
Expected: 取得同一 hash 的真实付款会话、T 的 Received 发票及双方已验证含 TLC 记录；T 在到期前主动强关，确认的交易精确花费原 funding，包含该 TLC 的金额、方向、hash/算法和 expiry。未取得此前提即场景失败，不改用旧无 TLC 承诺或另一笔付款。
Observable: A 的租户 RPC、SDK 持久化授权与 recovery record、T 的发票、双方 TLC、原 funding、真实 committed/canonical 强关交易；全程无 settle_invoice/create_preimage 或兑现授权。
Basis: [Hosted send_payment 路由](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/payment.rs#L127)、[SDK authorize_payment](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/signer.rs#L619)、[付款校验](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/commitment.rs#L471)。
Source: inference
Testing: not_tested — Gate1 选择真实单跳付款；Gate2 固定输入与检查点，不沿用 debug 注入充当付款会话。

### SPEC-02：真实成熟后按实际解锁路径证明 A 的退款
Condition: SPEC-01 的含 TLC 承诺已确认，A 已预先批准 watchtower 目的脚本与每笔费用上限；全程不释放 preimage，独立链验证正常。
Expected: 待确认：成熟前不发生该 TLC 的退款或兑现；成熟后允许自然产生两种路径。独立 TLC 退款须由 A 的真实 Tlc 派生签名 Applied 并用于确认交易，后继仅移除目标 TLC、保留双方份额；若 T 先结算，A 可由真实 Settlement 签名最终 sweep 剩余资金，但须证明其中包含归 A 的目标 TLC、没有后继 commitment 且没有重复退款。后者不计作 Tlc 密钥签名覆盖，也不因合法顺序判产品失败。
Observable: 真实链 median time、输入的相对 epoch/绝对 timestamp since、当前 live outpoint、完整签名请求及 key_purpose、SDK 签名/回执、实际 witness 和后继状态；独立 TLC 路径还核对创建时派生索引。
Basis: [actor 成熟与退款选择](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1555)、[Tlc key 与费用输入 since](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1655)、[SDK 方向/派生/成熟校验](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L199)、[合法最终 sweep 的 TLC 处理](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L3408)。
Source: observation
Testing: not_tested — Gate2 分开写到期保护及两种解锁路径的判断；只报告实际取得分支，未取得分支仍保留缺口，不为强求 Tlc 签名操控 T 的合法结算。

### SPEC-03：退款与后继份额结算均可归属，资金及业务结果不误记成功
Condition: 上述原通道的退款及后继结算持续自然推进，A 的事先批准保持不变，所有真实链交易可独立追踪。
Expected: 待确认：目标 TLC 的金额归入 A 的退款，不成为 T 的收款收入；后继双方份额结算完成且逐笔/累计资金守恒、无重复解锁。原付款最终 Failed，发票不为 Paid；若强关前已 Received，按当前实现观察保留 Received。付款 Failed、通道 Closed、请求清空均不能单独证明资金取回。
Observable: 目标付款和发票查询、链上全路径输入输出/费用/witness、A 在实际路径使用的 Tlc/Settlement 签名分别绑定对应支出、原目标 TLC 的最终处理和连续稳定窗口。
Basis: [SDK 输出/残余校验](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L266)、[付款方超时回传](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/channel.rs#L3588)、[收款侧超时清理但保留发票](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/network.rs#L4360)。
Source: inference
Testing: not_tested — Gate2 核清 Failed 的触发来源、付款重试和实际清理字段；不把客户端 timeout 或旧通道余额回填当链上退款。

## 测试树

<!-- TEST-TREE-BEGIN -->
- A→T 单笔无 preimage 付款，T 强关
  - 真实付款已进入双方承诺、发票 Received，确认交易包含同一 TLC [pending] — SPEC-01；Gate2 固定检查点及 ID，失败不降级为注入场景。
  - 到期保护与退款
    - 未成熟的连续窗口不发生目标 TLC 支出 [pending] — SPEC-02；Gate2 固定可观测窗口和采样，不仅取一帧。
    - 独立 TLC 路径：成熟后 A 的 Tlc 派生签名被应用并用于真实退款 [pending] — SPEC-02；Gate2 固定归属判断，未取得不计该分支覆盖。
    - T 先结算路径：A 最终 Settlement sweep 包含原 TLC 退款且无后继 [pending] — SPEC-02；Gate2 单独核清残余资金和目标 TLC，不冒充独立 Tlc 签名。
  - 最终结果
    - 后继双方份额结算、TLC 退款归属与逐笔/累计资金守恒 [pending] — SPEC-03；Gate2 展开账本及 SDK 签名关联。
    - 原付款失败、发票未支付、目标 TLC 清理与稳定 [pending] — SPEC-03；Gate2 拆开业务终态与链上结果的证据，不以其一替代另一项。
- 后续范围
  - 持有 preimage 的链上兑现、相反付款/强关方向 [unanalysed] — 从 SDK preimage release、actor 1/3 delay 及其他 for_remote 分支继续，单独评审。
  - SDK 离线恢复、双租户结算隔离、#1706 修复回归 [pending] — 沿用 watchtower scope 的保留分支及已知缺陷，等待各自批次/修复版本。
  - UDT、MPP、多 TLC、撤销惩罚、独立钱包、更多自然竞争时序 [unanalysed] — 本批仅单笔 CKB，仍需各自支持范围与既有测试去重。
<!-- TEST-TREE-END -->

## 用例范围（Gate2 入口）

<!-- TEST-CASES-BEGIN -->
本轮无正式用例行或新 ID。请确认 SPEC-01～03 及下列验证边界；下一阶段再建立完整五列表，保持现有 TIMEOUT/PAYMENT/WATCHTOWER 用例和全部 TEST-MAP 不变。
<!-- TEST-CASES-END -->

## 资金、成熟和故障边界

1. **退款归属与去向分开。** A 是该 TLC 的付款方；T 先建立 hold 发票，preimage 不交给任何 FNN 或 watchtower。目的 D 仍是事先从本地配置推导并批准的 LSP sponsor 钱包；证明 A 份额按授权结算到 D，不声称租户独立钱包取回或端到端自托管。实际使用的 Tlc/Settlement 签名及含 TLC 的残余资金不能混作无 TLC 结算。
2. **不直接套用无 TLC 的两笔账本。** 初始 funding 应拆成 `M_A + M_T + Q`（Q 为目标 TLC，双方金额含各自 reserved），强关费为 `F_close=C_fund-C0`。每笔记录当前 commitment 容量 C、sponsor 输入 S、后继 commitment 容量 R、D 地址全部输出 O、费用 `F=C+S-R-O`，净取出份额 `P=C-R=O-S+F`。独立 TLC 退款要求 `P=Q` 且 witness 指向 A 的目标 TLC；非最终普通份额按签署金额，最终 sweep 按真实残余容量。若 T 先领取 `M_T`、TLC 仍在后继中，A 最终取出的应为 `C0-M_T=M_A+Q-F_close`，再独立核对 sponsor 和本笔费用，不能漏掉 Q 或重复记一笔退款。不能重复加 reserved 或把 sponsor 找零计作退款。最终无剩余 commitment，`sum(P)=C0`，`sum(O-S)+sum(F)+F_close=C_fund`，再按 witness/签名确认每项归属。顺序影响最终费用归属，Gate2 逐步列出，不要求固定两笔或固定余额差。
3. **成熟采用真实链证据。** 首个 commitment 的 TLC timeout 相对 delay 为 2/3；普通份额为完整 delay；合法后继的首输入 since 为 0，但独立 TLC timeout 解锁仍需绝对 timestamp 输入。最终 Settlement sweep 不要求该绝对 timestamp 费用输入，SDK 仍校验残留 TLC 均已过期。SDK 要求 `median_time_ms/1000 > expiry/1000`，不能用墙钟过期、固定挖块数或 SDK 的 2 秒 epoch 估算替代。[onchain.rs:175–241](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L175) 与 [actor 的链 median time](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L627) 为判断依据。未成熟负向限自然链观察，本批不新增篡改交易矩阵。
4. **时间和付款生命周期须在 Gate2 写实。** 当前 dev 构建 `MIN_TLC_EXPIRY_DELTA=1333ms`，release 常量对应 160 分钟；默认 final expiry 为长窗口，不能直接沿用。建议显式选择约 300 秒的合法 final expiry，强关确认后仍需覆盖至少一轮 60 秒 watchtower 扫描的未成熟窗口；以实际 TLC expiry 复核余量，不满足即场景未取得。T 发票须先 Received，此状态忽略普通 hold timeout；发票自身 expiry、付款 session timeout、TLC expiry、链 median time 是不同计时。Gate2 固定金额、expiry、单路径/禁 MPP、重试边界、所有阶段绝对截止与总上限；不预先授权运行次数或加速链时钟。watchtower 60 秒扫描和 Hosted 300 秒关闭识别分别预算，不沿用 deadline 的 22 秒或旧 240 秒结算上限。
5. **#1706 是本路径的已知依赖风险，不是已复现结论。** T 合法先结算或 TLC 支出形成后继后，A 未及时提交的旧请求可能变成死输入；现有按 ID 取首项机制仍可能挡住新工作。提前批准并正常及时处理，允许双方自然顺序，但不保证避开缺陷。出现匹配旧项遮蔽症状，复用 #1706 并保存原始证据，判本批受阻；不删 DB、不挑隐藏后继代签、不隔离 T 广播、不反复重跑挑成功。只有新症状/新证据才追加调查，预算到期不能假设一定是 #1706。
6. **链上和业务终态独立证明。** Failed 可能受通道关闭、付款自身 timeout 或重试策略影响，不能仅据它归因链上退款；保留完整时序并要求目标 TLC 的链支出证据。Received 是未完成发票的当前实现观察，不将其写成 Paid/Expired；Closed 通道不要求余额重新变为可支付余额。Gate2 明确 RPC 可见的 TLC/锁定额与清理状态；必要证据不可见时公开缺口，不能靠改存储制造终态。

## 已有能力与需评审的最小扩展

| 项目 | 现有能力及 Gate2 要写明的增量 |
| --- | --- |
| Hosted 真实付款 | 产品有租户 send_payment 和公开 authorize_payment；[官方测试 agent](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/README.md#L54) 明确未实现 outgoing 控制。需在本仓局部驱动暴露真实 SDK outgoing 授权，不能从待签快照反推用户意图；dev add_tlc 不带 tenant 路由，不用它冒充 Hosted 付款入口 |
| SDK 链验证与签名 | 复用已通过 selfcheck-6 的独立 CKB 适配与真实 SDK verified 入口；当前 [_watchtower_chain.rs](../../test_cases/fiber/devnet/lsp/_watchtower_chain.rs) 拒绝 Tlc key 且过滤含 TLC record，必须明确扩展两处并验证方向、创建索引、成熟和前后继状态；不简单删保护条件 |
| 记录与资金判断 | [_sdk_driver.rs](../../test_cases/fiber/devnet/lsp/_sdk_driver.rs) 的 watchtower-records 要求零 TLC；[现有 ledger](../../test_cases/fiber/devnet/lsp/test_watchtower_settlement.py) 固定 TLC 数零、最多两笔，不能直接继承为新判据。需导出公开 TLC 证据并增加单 TLC 的独立解析/账本，保留旧四条判断 |
| 环境和授权 | 复用已核清的隔离快照部署流程、固定可信合约、sponsor 资金及持久化目的/每笔费用上限。Gate2 明确本批隔离链准备与局部 Rust 驱动适配；Gate3 前仍需独立复核和用户批准，不改产品、原快照或公共框架 |

原 Agent 的固定 genesis 验证器边界仍存在。新路径拟证明“Python 驱动真实 FNN + SDK verified 签名 + 独立 CKB 适配”的资金行为，不能称为官方 Agent 原事件路径全自动恢复，也不扩展 Rust 压力测试。

## 核验和下一门禁

2026-10-27，GPT 6.1 sol 已只读复核范围、固定源码、两种自然解锁路径及资金公式，无剩余 Gate1 阻断；两处非阻断措辞已按建议限定绝对 timestamp 的适用分支并统一签名表述。未触发 Daybreak。复核不是执行通过，也不替代人工确认。

检查记录：`python3 scripts/check_test_map.py` 输出 `review cases: 103`、`automated cases: 99`，退出 1；仍为既有 PMP-01～05/SETTLE-01 孤儿及历史 report overlay 的 16 个重复 ID，本次未增删映射。`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/tlc-timeout-refund-scope.md` 输出 `cases: 0`，退出 1：相同历史重复 ID，以及本 Gate1 尚无正式用例定义；三个 Spec 与 pending 分支等待人工决定，不宣称完整用例设计检查通过。`git diff --check` 退出 0；本文件 12 个相对文件链接均存在。源码/构建核对见本文基线，全部为只读检查。

本轮不运行节点、pytest、自检、构建或全量回归；不改既有用例行、自动化或 TEST-MAP。待完成人工 Gate1 评审后，下一步仅编写本范围的 Gate2 完整行集、预算、资金公式展开和最小适配方案。Gate2 再次明确批准后才进入 Gate3。

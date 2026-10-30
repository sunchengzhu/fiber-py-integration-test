# Hosted 付款方的 TLC 超时退款与资金守恒

2026-10-28：用户确认VM Gate1后，已对下列完整Gate2方案要求继续并希望当晚启动、次晨查看结果，进入Gate3。用户新增持久约束：本专项只手动夜跑，不纳入日常测试；`AGENTS.md`与pytest默认deselect/显式nightly开关同步维护。以下保留已评审的行集、预检、资金断言、预算及最小适配依据；只有专用guest可单次推进墙钟，宿主时间与产品代码不变。实际实现、准备、失败与未运行项另见LSP运行记录，不因获得执行授权而记为通过。

保留 [原 Gate1](tlc-timeout-refund-scope.md) 的 **A→T 单笔真实 CKB hold 付款、无 preimage、T 主动强关**。允许自然独立 TLC 退款或最终 Settlement sweep；只报告实际分支，不隔离 T、不重复取景。TLC 是通道内尚未完成的条件付款；sweep 指最后一方领取剩余 commitment 容量。受控时间结果不代表四小时自然等待或 macOS 产物通过。

固定源码 `04c206465b48da85b99aa58e80afe9801a2cb2db`；本轮只读 GitHub head、本地干净产品源码和实际 FNN 版本均相符。测试分支 `codex/lsp-core-regressions`，保留全部已有改动。2026-10-28 同04的Linux FNN/SDK/driver已构建并冻结，VM适配已实现；首个clock实例启动后的准备命令超时，已由独立诊断定位为隔离初始化误丢已有SSH回包；固定批次退出1，预检主体与全部产品样本未运行。三条 TEST-MAP 已存在但不表示行为通过，详见运行记录02:08交接；旧自检的路由 reserve 参数失败及未运行的后续批次见文末与 [运行记录](../../test_cases/fiber/devnet/lsp/README.md)。文末长等待方案仅保留历史，不是当前执行计划。原快照、24 产物与全部证据不动；#1674、#1706、08/10/12 沿用 [交接](../../docs/analysis/pr-1623-handoff-2026-10-27.md)。

## 共同输入与观察方式

2026-10-28 用户要求修复编排并自行于晚间运行：退款生命周期、含 TLC 自检和局部 helper 已迁至 `test_cases/fiber/devnet/lsp_nightly/`，普通 LSP 留在 `lsp/`。当前手动入口及隔离短检记录见 [夜跑说明](../../test_cases/fiber/devnet/lsp_nightly/README.md)。本次目录与控制修复不改变下列三行预期、断言或时间预算，原失败证据保留；短隔离验证不能代替纯时钟/真实链资格或退款通过。

| 项目 | 固定输入或检查 |
| --- | --- |
| VM 与资格 | 专用 Lima VZ/plain Linux ARM64；**正式产品样本**要求下文两类隔离预检均通过且与冻结配置/产物一致，每轮由无业务基础镜像新建实例。合并预检只要求匹配基础构建、纯时钟及旧适配成功，经受限preflight入口生成第二类资格，不要求已有自身证据。CKB/miner、FNN、SDK、Python 和观察器同处guest；宿主只做控制/截止/证据收集，每个实例最多一次正向跳变 |
| 拓扑和资金 | A 为 Hosted 租户，T 为公共 LSP；仅一条 A–T 私有 plain CKB 通道，A/T 各按现有夹具注资 500 CKB。双方真实就绪，无旧 TLC/付款；T sponsor 钱包另有至少 1,000 CKB 可用 plain cells。沿用一 epoch 承诺延迟 `0x10000000001`、60 秒 watchtower 扫描及原 Hosted 300 秒关闭识别，不改这些周期 |
| 发票 | 测试生成 preimage 并仅在测试端保留，以 SHA-256 得到 H；T 调用一次 `new_invoice`，金额 `Q=100,000,000 Shannon`（1 CKB），`currency="Fibd"`、`payment_hash=H`、`hash_algorithm="sha256"`、`allow_mpp=false`、`expiry=21600` 秒、`final_expiry_delta=300000` 毫秒。数值按 RPC 用 `hex()`；不传 `payment_preimage`。读取/解析返回发票，核对收款公钥、H、金额、资产、算法、到期与非 MPP 属性 |
| A 的独立付款批准 | 发起付款前紧邻记录 guest 墙钟 `t_auth`（毫秒），调用真实 SDK `authorize_payment`：`inbound=false`、H、SHA-256、精确 Q；`expires_at_ms=t_auth+120000`、`min_tlc_expiry_delta_ms=14580000`、`max_tlc_expiry_ms=t_auth+14820000`。这些是 SDK 原生整数，不能照搬 RPC hex。等待保存成功；不从后来的待签内容反推授权、不放宽金额或时间范围 |
| 唯一付款调用 | 从 `t_auth` 起 10 秒内完成批准持久化并开始发送，以 A 的原租户 token 调用一次 `send_payment`：返回的 `invoice`、`final_tlc_expiry_delta=hex(300000)`、`tlc_expiry_limit=hex(14700000)`、`timeout=hex(21600)`、`max_fee_amount=hex(0)`、`max_parts=hex(1)`、`keysend=false`、`allow_self_payment=false`；不指定 trampoline、UDT、dry_run 或另一条路线。要求实际直达 T、金额 Q、路由费 0；不使用会重发业务的框架付款 helper |
| 重试边界 | `max_parts=1` 不禁内部重试；固定源码没有可设为 1 的 max_attempt RPC，非 MPP 仍有内部尝试上限。本批只保证一次外部 `send_payment`，并核实实际仅有一个已建立的目标 TLC。失败的找路尝试可记录；出现第二个已建立 TLC/替代通道则本次不满足场景，不重开付款凑成功。最终空 `routers` 不能证明没有历史重试 |
| watchtower 批准 | 付款前保存完整目的脚本 D（由 T 本地钱包配置/公钥推导）和每笔总费用上限 `10,000 Shannon`，经原 `Agent.authorize(Watchtower)` 持久化。沿用独立 CKB 适配 + 真实 SDK verified 入口；不批准任意地址/费用、不释放 preimage。D 是已批准的 LSP sponsor 钱包，不是 A 的独立钱包 |
| 真实承诺检查点 | 原 payment H 已 `Inflight`，T 发票 `Received`；A/T 对应条目分别为 Outbound/Inbound `Committed`、Q/H/expiry E 一致且无 forwarding；双方已完成承诺与撤销 ACK，无待签请求，SDK 两方向已验证记录都含唯一目标 TLC。T 即将广播的远端 record 不要求 A 存有聚合签名；真实 CKB 确认须证明广播签名有效 |
| 查询与身份 | A 的 RPC 经其真实 tenant token，T 用自身公共客户端；`get_payment`、`get_invoice`、`list_channels({include_closed:true})`、签名状态与 HTTP/WS 原始证据共同观察。`include_closed` 不与 `only_pending` 混用；始终绑定原 node/channel、funding outpoint、H 和双方各自 TLC ID |
| 一次时间推进 | 完整 ACK、真实强关和 65 秒未成熟扫描窗口全部取得后，读取双方一致的实际 `E_ms`，只在该 guest 将 CLOCK_REALTIME 设置为绝对值 `E_ms+5000`；跳前目标必须严格大于当前墙钟，未满足即停止。不按发送时刻猜 E、不重复相对加四小时；命令/读回最多 30 秒，不增加目标值 |

源码依据：[RPC 付款参数](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-json-types/src/payment.rs#L166)、[付款期限校验](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/payment.rs#L239)、[SDK 授权字段](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/commitment.rs#L81)、[固定 reserve 与随机范围](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/graph.rs#L2177)。14700000ms 扣掉 final 300000ms 后只允许一倍 14400000ms reserve，不靠抽样重跑；仍回读实际 E 验证批准区间。`timeout=21600` 只防止六小时逻辑期限先于本轮结束，不把它当自动取消契约。初始 `expires_at_ms` 是新 TLC 入场批准期限，跳变前已完成 ACK；之后沿用原持久化链上批准，不延长该字段。

## Spec

### SPEC-01：真实含 TLC 强关后，未成熟窗口不能提前处理目标付款
Condition: 专用 VM 的隔离资格成立；上述单笔付款和完整 ACK 检查点成立；T 主动强关交易在 E 前确认，目标 TLC 位于实际承诺；链、SDK、查询和 watchtower 均正常，尚未推进 guest 时间。
Expected: 观察至少 65 秒真实链 median time 尚未达到目标 TLC 到期的窗口；目标 TLC 未被退款、兑现或最终 sweep，原付款不为 Success、发票保持 Received，preimage 不外传。强关交易/窗口前提不成立不能算保护通过。
Observable: funding→实际承诺的 canonical 关联，真实 epoch/median time、精确 TLC/witness、完整连续样本与支出索引、付款/发票及请求审计。
Basis: 用户确认的 Gate1 SPEC-01/02；[actor 使用真实链 median time](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L627)、[SDK 到期与 since 验证](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L175)。
Source: explicit
Testing: required

### SPEC-02：成熟后按自然支出路径确认退款、签名归属及资金守恒
Condition: SPEC-01 窗口完整取得；原通道、H 和本地批准不变，只推进一次 guest 墙钟至 E+5 秒后正常挖块，真实链到期与当前路径输入 since 均成熟；SDK 持续正常处理公开工作。
Expected: 成熟及索引就绪后 480 秒内，A 的目标 TLC 资金按独立退款或合法最终 sweep 路径取回，双方份额结算完成；实际使用的 SDK 签名已 Applied 且出现在确认交易中，逐笔/累计资金及 witness 转换正确、无剩余 commitment。自然顺序不当作失败；未取得的密钥/支出分支不计覆盖。
Observable: 真实 R/S/Applied/committed 交易、派生公钥或 Settlement 公钥、每笔输入/输出/费用、所有后继 outpoint、最终无后继及实际分支。
Basis: 用户确认的 Gate1 SPEC-02/03；[退款、后继与最终领取构造](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L1359)、[SDK 金额及残余校验](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L266)。
Source: explicit
Testing: required

### SPEC-03：原付款失败，发票不误记已支付，关闭状态完成链上处理
Condition: 已独立证明 SPEC-02 的原通道资金路径；guest 不再调时，原 token/批准不变，继续自然观察同一付款、发票及双方持久化通道状态。
Expected: 资金终态后 360 秒内原 H 的付款为 Failed 且无 preimage，T 发票仍 Received；A/T 分别为远端/本地强关且关闭 hash 正确，公开 WAITING_ONCHAIN_SETTLEMENT 清除，目标 TLC 已不在列表或处于对应移除状态；随后至少 65 秒稳定。不把历史条目保留或旧锁定额显示等同于资金仍锁定。
Observable: 同一 H、原通道/funding/关闭 hash、明确的 TLC 状态与公开关闭 flags、实际链账本、连续稳定样本；余额与历史列表保留原值供解释。
Basis: 用户确认的 Gate1 SPEC-03；[付款方链上超时处理](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/channel.rs#L3584)、[收款侧移除但不更新发票](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/network.rs#L4360)、[完成后清等待 flags](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/network.rs#L4434)。
Source: observation
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- A→T 单笔 hold 付款，T 强关，全程无 preimage
  - 真实业务与未成熟保护
    - 原付款完整 ACK、唯一 TLC 进入确认的 T 承诺，连续未成熟窗口不提前支出：LSP-REFUND-01 [primary] -> SPEC-01
  - 成熟后的自然退款与完整账本
    - 仅 guest 一次推进 E+5秒，正常挖块证明成熟，按实际支出确认 A 退款及双方份额、SDK 签名和守恒：LSP-REFUND-02 [primary] -> SPEC-02
      - 独立 TLC 退款后 A/T 按任一顺序结算，核对 TLC 创建索引、公钥和 Q：LSP-REFUND-02 [ref] -> SPEC-02
      - T 先结算，A 最终 sweep 包含 Q 且无后继，不计 TLC 派生签名覆盖：LSP-REFUND-02 [ref] -> SPEC-02
  - 原业务与关闭终态
    - 原付款 Failed、发票 Received、公开等待 flags 清除、目标 TLC 移除状态及稳定：LSP-REFUND-03 [primary] -> SPEC-03
- 保留边界
  - 未自然取得的退款分支 [pending] — 只按每轮实际链交易说明，不能用同一用例映射或整体通过代替分支证据。
  - preimage 兑现、相反付款/强关方向、UDT/MPP/多 TLC、撤销惩罚、独立钱包及离线恢复 [unanalysed] — 仍按 Gate1 后续入口单独评审，本批不扩展。
<!-- TEST-TREE-END -->

## 完整用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-REFUND-01` | - [x] 在隔离预检通过且尚未调时的专用 VM 内，A 向 T 真实支付唯一 1 CKB hold 发票并完成 TLC 承诺与撤销 ACK，T 发票 Received；不交 preimage，由 T 在到期前强关确认，连续自然观察至少 65 秒未成熟窗口及真实 watchtower 扫描 | 确认承诺精确花费原 funding 且包含唯一目标 TLC；整个窗口目标 TLC 未退款、兑现或被最终 sweep，付款非 Success、发票 Received；窗口、扫描或链证据不完整不能通过 | 用旧无 TLC 承诺或空等冒充保护证据，未到期释放资金，或用调时跳过保护窗口 | P0 |
| `LSP-REFUND-02` | - [x] 原 A→T 唯一 1 CKB TLC 已随 T 强关上链并取得完整未成熟窗口，全程无 preimage，A 已批准 D 与每笔 10,000 Shannon 费限；仅在专用 guest 单次推进至实际 E+5 秒，正常挖块满足真实 median、epoch、since 和索引后让双方自然处理 | 成熟及索引就绪后 480 秒内，独立 TLC 退款或合法最终 sweep 将目标资金归入 A 的授权支出；真实 SDK 签名 Applied 并用于确认交易，双方份额结清、无剩余 commitment，逐笔及累计金额/费用精确守恒；只记实际分支 | 用墙钟代替链成熟，将 T 支出、回执或 sponsor 找零误算退款，漏返、重返或归属错误 | P0 |
| `LSP-REFUND-03` | - [x] 在同一专用 VM 中，原无 preimage 付款已由真实链证明退款与双方结算，不再调时或重授权，继续观察原 H、原 Received 发票与双方通道 | 资金终态后 360 秒内付款 Failed 且无 preimage、发票仍 Received；双方强关方向/hash 正确、公开等待链结算标志清除、目标 TLC 缺席或处于对应移除状态；再自然稳定至少 65 秒，不要求历史条目或锁定额归零 | 退款后业务挂起或误记成功、关闭不收敛、重复记账，或用额外调时与重授权掩盖失败 | P0 |
<!-- TEST-CASES-END -->

三个 ID 仍由同一完整生命周期方法映射；`[x]` 仅表示已有 TEST-MAP。2026-10-28 用户要求继续后已实现 VM 模式并进入准备，尚未验收。一次通过不是三次独立执行；任一阶段失败整条非零，不把局部证据转记为后续行通过。产品金额与终态预期不变，本批确认对象包括隔离前提、逻辑期限和一次受控时间推进。

## 冻结环境与隔离预检设计

本节是后续获批阶段的设计，不是已执行命令。Gate1 核查到宿主 macOS ARM64、12 逻辑 CPU、32 GiB RAM、约 43 GiB 可用内置盘，尚无可用专用 VM；Docker daemon 不可达，不复用 Docker 的共享 VM。每个实例限制 4 vCPU/8 GiB/32 GiB 动态磁盘，构建并行≤2；每 5 秒及下载/复制/构建边界检查宿主剩余≥8 GiB、guest≥4 GiB。计入基础镜像、活动盘、失败盘、缓存与证据副本；OOM、停线、超时即停，不扩盘、不清理旧证据或改用外置盘。

| 固定对象 | 本 Gate2 候选与验证方法 |
| --- | --- |
| VM 软件 | Lima **v2.2.1 Darwin-arm64**；[官方发行资产](https://github.com/lima-vm/lima/releases/expanded_assets/v2.2.1) 的 `lima-2.2.1-Darwin-arm64.tar.gz` SHA256 为 `9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e`。只在获批准备时取得并校验，实际 `limactl --version` 必须匹配，不因 `minimumLimaVersion` 允许新版就自行升级 |
| guest 镜像 | Ubuntu 24.04 ARM64，固定 [release-20260926 镜像](https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-arm64.img)，SHA256 `1d6bffe64b848468ac97f821d369a4846d983de1800ccf6b5ec8853e85cefc55`；与 [官方校验文件](https://cloud-images.ubuntu.com/releases/noble/release-20260926/SHA256SUMS) 及 [Lima 固定模板](https://raw.githubusercontent.com/lima-vm/lima/v2.2.1/templates/_images/ubuntu-24.04.yaml) 一致；镜像消失或不匹配即停，无 latest/fallback |
| VM 配置 | [v2.2.1 keys](https://raw.githubusercontent.com/lima-vm/lima/v2.2.1/templates/default.yaml)：`vmType=vz`、`arch=aarch64`、`os=Linux`、`plain=true`、上述 CPU/内存/磁盘与唯一镜像/digest；无挂载、guest agent、containerd、Rosetta、动态端口/SSH agent 转发。plain [明确关闭宿主时钟同步](https://raw.githubusercontent.com/lima-vm/lima/v2.2.1/website/content/en/docs/config/plain.md)，仍须验证 guest 自身校时与虚拟硬件行为 |
| 产品与测试构建 | 产品完整 04 SHA、Cargo.lock、Rust 1.95.0、dev、`fiber-bin/debug-add-tlc`、`CARGO_PROFILE_DEV_DEBUG=0`；不启用 `cfg(test)`，不改四小时 reserve。只在独立 guest 仓库副本运行现有构建流程，宿主 bundle 不可写。局部 driver 使用原已解析 driver Cargo.lock，冻结依赖和源码；若跨平台依赖解析需要实质变更先停评审，不静默换版本 |
| CKB/CLI/Python/合约 | CKB 0.202.0 [官方发行](https://github.com/nervosnetwork/ckb/releases/tag/v0.202.0) 有 Linux aarch64 包；ckb-cli 固定 1.15.0，但其 ARM64 资产/是否随 CKB 打包尚未确认。准备阶段先核官方打包/校验与实际版本，无法取得即环境阻断，不自动改版本或另开源码编译方案。Linux 新 venv 按项目依赖建立并记录实际版本；原快照与可信合约字节按既有流程校验，只部署到副本 |

基础镜像仅保存系统、工具链、已构建产物、依赖和只读输入，无 FNN store、SDK 租户、活动链业务或已跳变状态。每个试验从它新建独立盘与实例，记录 Lima 名称/UUID、guest `/proc/sys/kernel/random/boot_id`、本轮唯一标记、SSH 身份、实际进程和镜像/配置/构建摘要。测试根位于 guest 本地文件系统，源码通过复制输入，不挂载宿主项目；所有 CKB/FNN/SDK/Python、透明 RPC 审计均在 guest。运行前封闭 guest 外联，仅保留所需 SSH 控制/证据通道和 guest 本地网络；不得接公网链或宿主上的旧节点。

guest 内逐项枚举并关闭/禁用实际存在的 timesyncd、chrony、ntpd、cloud-init/guest-tools 校时及自动恢复钩子，保存配置/服务状态；只看 `timedatectl` 的单个布尔值不足。宿主的 date/NTP/系统配置完全不动。调时权限只交给 guest 中本轮唯一受限控制入口：先核 guest 为 Linux、实例标记/boot ID 与宿主选定实例相符、当前阶段/唯一事件额度匹配；任一不符在调用 CLOCK_REALTIME 设置之前拒绝。不得调用公共 `framework.util.change_time` 或在宿主执行调时命令。

### 两类预检与资格判据

**纯时钟预检（9 分钟，独立无业务实例）**：60s 内启动/核身份与隔离，60s 自然基线，30s 内唯一正向设置为该实例基线末墙钟+14700s并读回，360s 自然保持，最后30s导出/停止。各阶段各自有界且合计540s；启动慢不压缩60/360s窗口。全程宿主和 guest 各每1s采样本机 wall/monotonic，间隔≤5s、非事件偏移变化<2s；guest 调时入口在 syscall 前登记并启动相对10s和60s等待，证据必须显示两个等待均跨越唯一事件，实际单调耗时不得提前、迟到≤2s，不满足不能重设计时器补证据。证明设置只影响 guest 墙钟，单调与相对截止继续运行；360s内无校回、第二跳、boot变化、挂起/恢复或控制通道失联。该实例终止后不回拨复用。

**真实链/SDK 预检与新含 TLC 适配自检合并（36 分钟，另一个全新实例）**：复用适配后的 `TestTlcRefundAdapter::test_single_tlc_adapter`，原唯一真实付款、ACK、强关、65s实际扫描、单次 E+5s、180s真实成熟/索引均执行；跳后至少360s偏移保持与成熟/请求等待并行，即使请求提前就绪也不能提前结束窗口。用**跳前持久化的原批准和原 token**查询当前有效请求，真实 SDK `prepare_onchain` 必须正向成功，然后原索引/hash/金额/方向/residual 五类局部负向必须以对应原因拒绝。只收到 SignatureRequired、仅五项拒绝或环境错误都不够。A 的测试SDK/适配入口始终 check-only，不提交 watchtower 签名、不广播其候选或变异交易；T 的合法强关及本地份额自签广播保持自然。不要求退款资金或03终态，不计正式产品样本；自然只取得 Settlement 时不制造 Tlc 请求或换分支。

合并实例同时产出“环境资格”和“适配校验”两类结论，但只执行、计时一次；纯9+合并36=**45分钟能力预检**。任一缺项/超时停止，不另起未计时的SDK预检。现有 `watchtower-check` 返回的正向/负向证据须能关联当前 live/canonical R、原 record/批准与身份；若现有输出不足，仅在后续获批 Gate3 补必要导出，不能以自检返回布尔值替代。两个预检与正式四轮均不同实例/boot/业务数据，不恢复运行中快照。资格绑定本批冻结内容；镜像、VM配置、工具链/依赖、时间控制、产物或相关适配变化后不得引用旧资格。

### 一次跳变的证据与连续采样

- 宿主和 guest 分别记 `wall-monotonic` 偏移，不能跨系统比较 monotonic 绝对值。开始前保存各自基线；宿主全程非预期偏移变化≥2s、采样/心跳间隔>5s，guest 非事件漂移≥2s，或 boot/进程身份变化均使该轮无效并停批；不关闭宿主正常校时来凑通过。宿主挂起后恢复也不能继续算有效样本。
- 跳变控制与 `_sample` 并行。唯一事件先登记实例/H/E/目标值和旧偏移，消费一次额度，再由 guest 记录 syscall 前后 wall/mono、调用结果、读回与新偏移；不把30s执行预算加到目标上。设置调用的本地单调包围区间≤2s，读回应位于目标值至目标值加该区间耗时及2s采样余量之间；全过程仍受30s及总限约束。控制结果未知也不能重发命令，直接封存失败。
- 跨事件样本保留完整链/资金/RPC内容、起止wall/mono及事件包围区间；按端点落在事件前/后分别验证旧/新偏移。恰落在包围区间的时间读数单独标记并由 syscall 与邻接样本约束，不能丢弃整个样本、清空历史、跳过资金断言或关掉漂移检测。原2s单RPC、3s整样本、5s间隔仍适用，事件前最后完整样本和事件后首个完整样本连续覆盖。
- guest monotonic/SIGALRM相对预算只允许自然消耗；宿主独立截止不接受 guest 延期。事件后链 median 可能尚未过期，仍正常挖块；每笔解锁须核实际 since，CKB 自己验证 canonical 交易。relative epoch 满足不能仅用墙钟/固定块数推断，不构造未来区块或假 median。
- 固定源码 tenant issuer `lsp/token.rs` 发行的基础 token 无时间 check；固定 operator fixture 的权限块也无时间 check，但 RPC 验证器确实支持时间事实，不能推广到其他 Biscuit。只用这两个固定身份，跳前后实际 RPC/SDK成功证据配对，不打印 token 原文或换发 token。`expires_at=t_auth+120s` 只限制首次新TLC批准（`commitment.rs` 的 `other.is_none()` 分支），不是已建TLC的全流程授权期限；watchtower 原 D/fee 批准不变。未来实际 token 若不同或包含不能覆盖本轮的时间条件，付款前停止。

## 阶段顺序与时间预算

预算是本地功能测试停止上限，未经实测，不是预计耗时或产品 SLA。宿主以单调时钟记录每轮启动点 `h0`；整轮截止为 `h0+2160s`。guest `t_send` 为唯一付款 RPC 起点的单调时钟，同时保存 guest 墙钟；宿主收到发送阶段事件后只收紧、不能延后原绝对截止。guest 各阶段和总截止连续计时，宿主独立监控进展、失联和总上限；两侧 monotonic 原点不直接相减。

准备最多 **600 秒**（含新实例启动与配置检查），从 `t_send` 起业务最多 **1500 秒**，清理/导出最多 **60 秒**。guest 业务截止取自身总截止与 `t_send+1500s` 的较早者，宿主在总限前 60 秒结束业务并开始有界收尾；任何子阶段超时均失败，不借剩余总余量补时。36 分钟入场要求为：基础VM、Linux产物、venv、可信快照已就绪；合并预检另需纯时钟及旧适配成功，正式四轮还需合并资格成功且摘要匹配，不临时安装依赖、不让预检依赖自身尚未产生的资格。

| 阶段 | 截止/窗口 | 必须取得的证据与失败边界 |
| --- | --- | --- |
| 独立环境、可信合约、身份、funding 与批准 | 600 秒总准备；前 300 秒包含新 VM 启动、身份/隔离检查、CKB/合约，后续节点/开通/准备最多 300 秒 | 原快照只读来源，工作副本按既有流程部署固定合约；canonical/字节/唯一 live dep、SDK绑定、双方余额/sponsor 充分。原类级计时也受宿主准备截止约束，不能另外加 300 秒 |
| 发票、outgoing 授权与唯一发送 | 计入准备；从 `t_auth` 起 10 秒内完成批准持久化并开始发送 | 发票参数来自本地意图；SDK 授权 `t_auth` 仅在环境就绪后创建。实际 E 回读后核对本地允许区间及剩余安全时间；不重新批准掩盖迟到 |
| 取得完整 ACK/Received 检查点 | `t_send+60s` | 同一 H/Q，两侧唯一 Committed TLC，无 forwarding、额外 TLC 或待签；双方向 SDK 记录对应，真实直达单跳。场景未取得非零结束 |
| T 主动强关及确认 | 检查点后最多 60 秒，且不晚于 `t_send+120s`；确认时距实际 E 的墙钟余量至少 120 秒 | T 仅调用一次 force shutdown；真实 committed/canonical 交易精确花费原 funding，匹配已验证 T 方向承诺及唯一目标 TLC。不是等待 08/10 的自动保护，也不隔离 A/T 广播 |
| 连续未成熟观察 | 强关确认后至少 65 秒，最多 75 秒完成最后完整样本 | 全部样本链 median 秒值尚未越过 E 的秒值，目标 TLC 未被移除；覆盖一轮 60 秒扫描。若实际提前成熟导致窗口不足，判准备/证据失败，不缩窗、不重开另一个场景 |
| 唯一 guest 时间推进 | 未成熟完整窗口及扫描成立后最多 30 秒，包括命令、读回与确认 | 目标是绝对 `E_ms+5000`，仅 guest 调时一次；观察器并行运行，不能停采样。结果不明确、额外跳变或宿主/guest 监控缺口均停止，不能重试调时 |
| 等待真实成熟及索引 | 从成功读回的 guest 单调事件点 `t_jump` 起最多 180 秒，受所有总限约束 | 正常挖块读取真实 median/epoch、canonical header、原 lineage 的 outpoint/indexer。原 commitment 完整相对 delay、TLC 绝对到期及相关索引齐全；不改矿工、区块字段或 RPC，不将墙钟目标当成熟证据；成熟阶段不能补做时间控制 |
| 正常工作、签名与两方资金完成 | 上述成熟/索引齐全起最多 480 秒 | 包含 60 秒扫描、SDK处理、签名后扫描/广播、最多三笔自然支出及确认；每次 RPC 最多 10 秒。旧工作失效只从正常 RPC/WS 重新读取，不挑隐藏请求；#1706 相同症状按既有归因受阻 |
| 付款和关闭终态收敛 | 最后资金交易确认且索引可查起最多 360 秒 | 包含一个 Hosted 300 秒关闭识别周期及余量；与资金阶段并行保存业务样本，已完成者无需重复等待。只以原 H 终态和实际通道状态判定，不等付款 timeout 参数来兜底 |
| 稳定窗口 | 所有资金/业务断言同时成立后至少 65 秒，最多 75 秒收尾 | 跨一轮 watchtower 扫描；每个后续样本均满足终态，无重复目标支出、付款/发票回退或额外通道/TLC |
| 保存与清理 | 60 秒，已含在 2160 秒内 | 从开始就持续写 guest 证据并流式导出宿主；终止本轮进程、完成导出与摘要核验。超时/无法确认停止或证据不全则整批停止，保留该 VM/磁盘待处理，不自动删除；清理不追加成功断言 |

业务串行上限为 **60+60+75+30+180+480+360+75=1320 秒 < 1500 秒**，未用余量不续已超时阶段。E 不再按跳前墙钟映射成四小时后的单调截止；按前述跳变事件划分墙钟偏移，成熟仍只能用真实链判断。发票 expiry、付款 timeout 的 21600 秒须覆盖**虚拟墙钟**而不只是 2160 秒真实耗时：创建时即核对 `t_auth+14820000+5000+1500000` 毫秒的保守结束墙钟小于原发票/付款有效期限，token 有时间限制时也须覆盖此界；不满足则付款前停止，不改批准或续 token。

### 连续观察与链成熟

- 阶段观察目标间隔 1 秒；独立 RPC 可并发，单次观察请求完整耗时最多 2 秒，整轮最多 3 秒，相邻完整样本结束间隔最多 5 秒。观察采样优先采用这里更严格的 2 秒上限；其他控制/提交操作采用最多 10 秒上限，二者都受更早绝对截止限制。记录起止/最大间隔；超时、解析错误、断连和缺字段都不是“无事件”。负向与稳定窗口内任何连续性缺口非零失败，不用最后一帧补齐。
- 每轮保存链高、canonical tip、median time、相关 outpoint 的 live/spend 查询、A/T 状态、原付款/发票、SDK/节点进程与请求审计；观察期内每个滚动 30 秒链高须增长。用独立标记的 FNN→CKB 透明审计取得目标 commitment lock 前缀/区块范围的实际扫描请求及成功响应，和同轮 median/header 查询关联；不能拿 Python 自己的轮询、SDK 的 ChainVerifier 请求或配置值冒充 watchtower 扫描。若没有一次可归因扫描，不能声明扫描下的保护已通过。
- 未成熟只禁止**目标 TLC 的退款/兑现/最终移除**；如有其他合法份额支出必须逐笔解释，不能将 T 合法活动自动判错。给定单 TLC/无 preimage 前提下若出现不符预期的早期普通支出，保存实际 witness/成熟证据再分类，不放宽 SDK 校验。
- 独立 TLC timeout：首 commitment 输入至少满足真实相对 `2/3×delay`，还要有绝对 timestamp since 输入（当前构造在 sponsor 输入）不小于该 TLC 的 expiry 秒值；SDK 要求 `median_ms/1000 > E/1000`。普通份额首输入需完整 delay；合法后继首输入 since=0。最终 sweep 不需要 TLC timeout 专用绝对 timestamp 输入，但 SDK 仍检查残留 TLC 均过期。每笔签名前、确认后分别核对实际路径约束，不能把一轮成熟证明套给后来的新输入。

## 资金与真实签名断言

### 1. 原承诺和金额初值

保存原 funding outpoint、开通意图及批准费率、注资交易/双方余额、选定强关交易、SDK 两方向公开 recovery records。T 广播交易必须唯一消费原 funding，只有一个 plain CKB commitment 输出，FundingDeps 与可信配置顺序一致；规范化 `compute_tx_message` 匹配 A 的唯一已验证 `for_remote=true` record，而不将含广播 deps 的 tx hash 与签名模板 hash 直接相等。

`C_fund` 为真实 funding 容量，`C0` 为首 commitment 容量，`F_close=C_fund-C0>=0`，按原批准 commitment fee rate 与真实序列化大小核对。`M_A/M_T` 是**该强关 snapshot** 的两方 settlement 金额，已扣 pending TLC 并含 reserved；不是直接用强关前 RPC balance 加 reserve。无此前支付时必须独立与开通基线对应：`M_A=A 的可用通道初值+reserve_A-Q`，`M_T=T 的可用通道初值+reserve_T`，并证明 `M_A+M_T+Q=C_fund`。两份额非零、均足够承担最终强关费，链输出占用容量及 sponsor 前提满足。

实际 witness 中唯一目标 TLC 绑定原 H、Q、SHA-256、E、方向与创建索引；使用真实 feature bitmap 决定 20/32 字节链上 hash 形式，再与 SDK 的完整 H 对应，不只比较截断 hash。记录该 snapshot 的其他 TLC 数为零，不能将“已消失/未入承诺”的 TLC 当成超时退款。

### 2. 每笔账本与合法顺序

沿首 commitment 的精确 outpoint 追踪所有合法后继，最多三笔结算支出。每笔独立从 CKB 读取并重算交易 hash、canonical 包含块和输入前序交易：

- C：被花费的当前 commitment 容量；S：额外 sponsor 输入容量之和；R：合法后继 commitment 容量（最终为零、无后继）；O：本笔所有 D 输出之和，含 sponsor 找零。
- 所有输入 outpoint 去重；额外输入必须为事先批准 D 的无 type/无 data plain CKB。非 commitment 输出全部归 D 且类型/数据符合预期；禁止漏算任一输入/输出或隐藏其他去向。
- 实际手续费 `F=C+S-R-O`，要求 `0<=F<=10,000`。A 签名的 F 必须等于真实 exact authorization 的 fee；T 自签的费用独立核对同一测试上限，不冒称经过 A 批准。
- 从 commitment 取出的份额 `P=C-R=O-S+F`。O 不是 A 的退款额；D 对两方可能相同，归属只能由 TLC 方向、解锁 witness 与签名公钥证明。前一笔 D 输出若成为后一笔 sponsor，按实际 outpoint 正常计 S，累计公式自然抵消，不按钱包总余额猜测。

| 自然路径 | 每一步必须符合的金额与状态 |
| --- | --- |
| 独立 TLC → A 份额 → T 最终领取 | 第一笔 `P=Q`，仅删目标 TLC；第二笔 `P=M_A`，只清 A 份额；第三笔 `P=M_T-F_close`，无后继 |
| 独立 TLC → T 份额 → A 最终领取 | 第一笔 `P=Q`，仅删目标 TLC；第二笔 `P=M_T`，只清 T 份额；第三笔 `P=M_A-F_close`，无后继 |
| T 份额 → A 最终 sweep | 第一笔 `P=M_T`，目标 TLC 完整留在后继；第二笔 `P=C0-M_T=M_A+Q-F_close`，目标 TLC 与 A 份额一并终结、无后继。不能再加一笔 Q 或记成独立 Tlc 签名退款 |

最终双方份额各解锁一次，目标 TLC 恰好由独立退款或最终 sweep 处理一次；`ΣP=C0`，`Σ(O-S)+ΣF+F_close=C_fund`。不要求最终领取者恰好得到开通时 500 CKB，不重复扣强关费/加 reserved，不用容差掩盖整数差额。费用变化、异常第四笔、分叉后继或无法唯一解释的支出均失败。

### 3. witness、派生公钥与 SDK 签名必须对应实际支出

从真实 commitment feature 解码 TLC entry，长度为 `65+payment_hash_len`（85 或 97），body 长度 `1+n×entry_len+72`；保留格式前缀并验证 body hash 与 live input lock args 匹配。无 preimage unlock 必须 67 字节、`with_preimage=0`；不接受 99 字节兑现路径。非最终 TLC 支出仅删除目标 entry/减少 count，双方各 36 字节份额保持；普通份额仅清解锁一方，TLC与另一份额保持；后继 code_hash/hash_type、前36字节、feature不变，body hash/settled位及容量精确更新。

对每笔使用 A 签名的支出保存完整 R、request_id、SDK S、真实 Applied 与最终 committed 交易。request_id 对应完整待签交易；最终 raw transaction 的 inputs/outputs/deps/since 与 R 一致，签名放进实际 unlock 的 S 相同，恢复公钥符合原 record：

- 独立退款为 `key_purpose=Tlc{commitment_number}`，数值必须是目标 TLC 的 **local_key_commitment_number 创建索引**；当前 witness 数组下标、当前最新承诺号都不能替代。以 SDK 公开派生公钥及原 witness key hash/for_remote 方向交叉核对，不导出私钥或自行代签。
- 普通/最终领取使用 A 的 Settlement 公钥；最终 sweep 必须仍包含原目标 TLC 的完整残余证据，再证明实际消耗后无 commitment。只出现 Settlement 签名时，不声称 Tlc 派生密钥路径已执行。
- 如果旧 R 曾 Applied 但未被链采用，不能拿它替代最终有效签名证据；必须存在实际用于确认支出的 A 签名。`AlreadyApplied` 只在有同一提交体先前真实 Applied 时解释，不单独计通过。

相关固定源码：[金额构造](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/fiber/channel.rs#L11560)、[witness 编码](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-types/src/watchtower.rs#L240)、[派生索引/方向](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lsp-sdk/src/onchain.rs#L197)。

## 付款、发票及通道终态

1. 原 `get_payment(H)` 为 Failed、无 `payment_preimage`，保存 `failed_error`、fee、created/updated 时间与全过程；不精确匹配非契约错误文本。最终 fee=0 与直达无路由费一致，但不能由此反推链上退款。Failed 可以早于链资金终态；本条必须已有独立链资金证据，不能把关闭/找路失败或客户端截止解释成退款成功。
2. T 的原发票始终不是 Paid，强关前 Received，最终仍 Received；全流程不调用 fulfill、settle_invoice、create_preimage、cancel_invoice 或人工 remove_tlc。退款不等于支付成功，T 不取得 Q 收款收入；T 自身份额和 sponsor 找零与 Q 分开核算。
3. `list_channels({include_closed:true})` 必须返回原通道及正确 funding、关闭 hash；A 为 `Closed/UNCOOPERATIVE_REMOTE`，T 为 `Closed/UNCOOPERATIVE_LOCAL`，两侧公开 `WAITING_ONCHAIN_SETTLEMENT` 消失。不能查询 `only_pending` 的开通合成项替代真实通道。内部 `ONCHAIN_SETTLEMENT_CONFIRMED` 未在公开 JSON flags 中命名输出，本批不把它当作可直接断言的 RPC 字段。
4. 对初始保存的双方 TLC ID/H：条目已删除，或 A 为 `Outbound.RemoteRemoved`（也允许已进一步移除确认的状态），T 为 `Inbound.LocalRemoved`（也允许已进一步移除确认的状态）；不得仍是 Committed/Announced。`pending_tlcs` 实际遍历历史列表，不能要求必为空。`get_inflight_*` 只排除特定失败移除确认状态，链上移除不一定完成 ACK，因此**不要求关闭后 offered/received_tlc_balance 必为零**，也不要求 local/remote_balance 回填到可支付余额；完整保留其值并与链账本分开解释。移除状态本身不证明内部 hold 记录物理删除，本批不宣称检查了隐藏存储。
5. 状态收敛时必须已有至少一份同通道链上结算完成日志作为辅助归因；决定性证据仍为原交易路径、原付款/发票和真实 RPC 状态。随后连续 65 秒所有样本稳定；无新业务调用、第二个目标 TLC、请求推进产生的第二次退款或账本变化。陈旧 pending 若不阻塞任何实际工作，仅保留观察，不要求本批证明 signer store 全面清理；若阻塞当前工作，按 #1706 边界失败。

上述区别来自 [真实通道列表与 only_pending 补齐分支](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/channel.rs#L530)、[链上移除状态](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-types/src/channel.rs#L758)、[锁定额过滤](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-types/src/channel.rs#L581)。这是本轮静态核对出的观测边界，不是新复现的资金缺陷。

## 最小适配方案（VM 增量只评审，尚未实现）

| 位置 | 必要增量及保留的保护 |
| --- | --- |
| 专用宿主入口（拟 `scripts/lsp_refund_vm.py`）与固定 VM 配置 | 只管理本批明确标记的实例，拒绝复用 Docker/已有业务VM；冻结软件/镜像与配置、建立独立guest副本、资源与时钟监控、宿主绝对截止、流式证据导出和有界停止。安装/下载/构建/运行分别受下表上限控制。宿主入口不调用任何宿主调时接口；命令超时或结果未知时停止，不自动重试调时/付款或扩大资源 |
| guest 时间控制与观察（局部 `_vm_time.py`） | 核对实例/boot/阶段/唯一事件，执行一次 guest CLOCK_REALTIME 设置，保存 syscall/墙钟/单调证据，按前后偏移验证跨事件样本；保留相对timer及完整采样。控制/观察和产品业务分开，无全局patch、libfaketime或冻结时钟，不修改公共 framework |
| `test_tlc_timeout_refund.py` | 现有一个生命周期/三个映射保留；将原短期限改为本文固定输入，正式VM入口要求两类资格，受限preflight入口仅要求纯时钟/旧适配并产出第二类资格，二者不能互充通过。protect_immature 后加入一次跳变，mature用跳后180s截止、真实链判断不变；_sample只接受唯一登记事件，其他时钟断言继续生效。适配自检增加正向证据与跳后360s观察，仍check-only，不变成第二份产品退款测试 |
| `_sdk_driver.rs` / `_watchtower_chain.rs` | 先复用已实现的 outgoing 授权、单 TLC record 导出、真实 SDK verified 与五项负向。只在正向证据输出不足时补导出当前R、原批准关联和prepare成功，不改产品SDK；无TLC模式继续拒绝TLC。原唯一ancestor、canonical/live/maturity/lineage、有序deps、D/sponsor/fee和签名保护全部保留；不能为了跳时删保护或重新authorize |
| 适配中的请求上限 | 现有每通道最多 3 个不同有效请求只为无 TLC 场景。新模式最多 3 个实际 commitment outpoint，每个 outpoint 最多 3 个不同、经独立链和 SDK 验证的候选请求，全流程最多 9 个；相同 R 的重复观察不消耗新名额。仍共用 480 秒截止；新 outpoint 必须由真实确认前驱推出，不能靠换 ID 重置预算。只处理公开 RPC/WS 首项，不删除/绕过旧项 |
| `_refund_ledger.py` | 沿用现有最多三笔、单TLC独立账本及上文全部整数/签名断言；时间变化不改变金额算法，不共用放松后的无TLC ledger，不把预检结果冒充退款 |
| FNN 扫描观察 | 复用 `_watchtower_rpc.py` 的转发审计能力，为本条 FNN→CKB 设置独立标记的透明入口，固定 `fault=None`；SDK 独立验链和 Python 查询仍用各自入口以区分来源。仅记录原请求/响应和时刻，不改响应、不扣留、不人为延时，不调用手动 check_channel_shutdown；原四条配置不变。该入口不能用于适配负向故障注入 |
| 现有 Python helper / 构建脚本 | 复用隔离准备/可信deps/有界RPC，必要时仅传入更早的外层截止，不能扩大原1260s/2160s上限或默认关闭时钟保护；原watchtower四条及非VM入口不改变语义。构建脚本只在guest仓库副本操作同相对bundle路径，保留宿主Mac产物；原快照、产品/合约源码、公共framework和Makefile不改 |

适配器不把节点提供的 source/fee/目的地址当作本地批准。唯一祖先匹配使用已验证 record 与真实链，不要求 A 持有 T 方向的聚合签名；SDK 自己核对剩余条目是原 signed snapshot 的未变子集、方向、派生索引和金额。既有 DevChain 对固定 genesis 的限制沿用已批准分段边界：本批是 Python 调度真实 SDK verified 入口与独立链适配，**不是官方 Agent 原事件路径自动恢复**，也不是新增 Rust 压力测试。

### Gate3 的适配核验边界

如果本 Gate2 获明确批准，先验证新增的局部授权/导出/账本能力，再进入正式产品场景；这是后续步骤，本轮不运行。

- 复用既有适配预检：可信字节/deps、非 live 或无关祖先、非法后继/输出、未成熟 since、未经批准 sponsor/目的地址和费用上限均须拒绝；零 TLC 模式的保护继续生效。
- 新增能力的最小核验围绕本批变化：SDK outgoing 授权持久化与方向正确；真实含 TLC record 导出与 Python 编码交叉一致；85/97 格式按实际 feature选择，不错误偏移签名；实际取得的 Tlc 或 sweep 路径走真实 SDK。对派生索引不符、目标 hash/金额/方向不符和含 TLC 残余不符的局部负向，只允许不广播、不提交签名的校验调用，分开记录适配结果，不能当产品场景通过。
- 如果没有自然取得可用 Tlc 请求，不能拿模拟链/自行构造签名算 Tlc 正向已验证。实际 sweep 的资金和业务仍可按三行验收，Tlc 正向分支明确未取得；若以后必须确定性取得该分支，另交场景控制方案，不在本批增加 T 隔离或重复取景。
- 本批调整共享适配后，后续验证需包含原无 TLC 正常结算的聚焦回归及已有适配自检；#1706 的 02 不为本批再次盲目复跑。正式建议先一次完整生命周期，再由同一冻结实现固定复跑三次；任何非零立即停止后续批次，保留所有失败，不为某分支改变时序。此为 Gate2 原计划；2026-10-28 用户要求继续夜间运行，实际结果另记。

### 固定后续顺序、选择器与整批预算

先实现局部适配并交 GPT 6.1 sol 复核，再按下表准备/预检/执行；本表为已确认的设计。每个实例仅在上一项成功、证据完整后启动，不能并行跑四个样本改变资源/时序。无TLC两项不调时，含TLC合并项及正式每轮各只有一次。所有时间上限均包含该项实例启动、pytest类/方法、导出和停止，不能在表外追加teardown时间。

| 顺序 | 项目与执行入口（路径相对 `test_cases/fiber/devnet/`） | 宿主单调硬限 |
| --- | --- | --- |
| 1 | 固定 Lima/镜像、Linux CKB/CLI、系统依赖；先核CLI取得与校验来源再开始重构建 | 60分钟 |
| 2 | 固定04的Linux FNN/SDK/driver、Rust依赖与Python venv；冻结实际产物/依赖、基础镜像及输入 | 120分钟 |
| 3 | 独立纯时钟预检，尚无产品/业务 | 9分钟 |
| 4 | `lsp/test_watchtower_settlement.py::TestWatchtowerAdapter::test_adapter_rejects_invalid_authorization`，旧无TLC保护自检 | 21分钟（1260s） |
| 5 | `lsp_nightly/test_tlc_timeout_refund.py::TestTlcRefundAdapter::test_single_tlc_adapter`，合并真实链/SDK资格与新TLC适配自检 | 36分钟（2160s） |
| 6 | `lsp/test_watchtower_settlement.py::TestWatchtowerSettlement::test_authorized_settlement`，原正常结算聚焦回归 | 21分钟（1260s） |
| 7 | `lsp_nightly/test_tlc_timeout_refund.py::TestTlcTimeoutRefund::test_hold_payment_timeout_refund`，首次完整生命周期+固定复跑3次，每轮独立实例/业务 | 4×36=144分钟 |

原1260s自检/回归已含类级CKB准备，宿主还须把VM启动/证据/清理包在这1260s内；不能读到历史114.69s通过就把Linux预算估成两分钟，也不在内部上限后另加60s清理。两个短项由宿主在总限前60s开始收尾；内部准备/业务只能使用更早截止。合并项的360s偏移旁证与成熟/请求等待并行，正向检查即使早完成也观察满360s；36分钟硬限不因此延长。

时间账只计每项一次：首次准备/能力预算 `60+120+(9+36)=225分钟`，其中36分钟同时完成新适配自检；再加旧自检21、正常回归21和正式144，**从零全批411分钟（6小时51分）**。已有匹配基础镜像及纯时钟资格时，后续旧/新自检、聚焦回归与正式批次为 **222分钟（3小时42分）**；若纯时钟也需重做则 **231分钟（3小时51分）**，不含重建。正式单独1+3仍144分钟，不把前面的5类工作省略后宣称全批只36分钟。

以上均为失败停止限额，不代表实际需要满额运行或首次准备一定成功。冻结实现下当前批旧/新自检各一次，合并预检不另跑一次相同TLC场景；任一非零不替换样本、不继续剩余批次。配置/适配变更导致资格失效时，先明确受影响项与预算，再重做相应预检；不以无限自检消耗或重跑来获取特定退款分支。

## 证据、失败分类与交接

每轮使用由宿主真实日期命名的新证据目录，保存VM/boot/配置/软件/镜像/构建摘要、运行命令与退出码、双方wall/mono/阶段截止/唯一跳变事件、资源检查、原发票/付款/批准、完整SDK records、HTTP/WS/R/S/Applied、真实链成熟响应、所有canonical交易及逐笔账本、样本起止/最大间隔、节点/SDK日志和实际分支。按单调时序关联事件，guest未来墙钟单独标注，不当作真实执行日期。启动时即持续归档，导出核摘要后才标为完整；失败VM/磁盘保留，不覆盖旧失败或只保成功。Tlc/sweep分支分别说明，不新增覆盖率台账。

- **环境/适配失败**：版本/资产/可信字节/deps、时钟隔离/采样、VM或监控、资源、SDK预检/输出解析或导出不满足；不算产品通过。额外跳变/回拨、宿主挂起、token失效、未知控制结果均先停止，保存证据再区分产品与环境，不能一律归#1706。
- **场景未取得**：付款未直达、额外已建立 TLC、完整 ACK/含 TLC 承诺/65 秒未成熟窗口缺失；非零结束，不用空场景、skip、重新付款或 sweep 冒充独立 Tlc 分支。
- **产品行为失败**：充分前提下提前支出、资金/签名归属错误、超时未完成或业务终态不符；保存准确阶段和证据。若症状匹配旧死输入请求遮蔽有效后继，沿用 #1706，不从零定位，不删 DB、不挑隐藏请求。仅预算到期不足以自动归因 #1706。
- **本批完整通过**：三行所有要求、实际自然分支的完整账本及稳定窗口均成立；没有取得的另一分支仍未覆盖。付款 Failed、Closed、TEST-MAP 或适配自检各自都不等于完整通过。

本轮交接对象是 **VM 前提下 LSP-REFUND-01～03 三行、两类隔离预检、真实链/资金/业务断言、2160s单轮及411/222/231分钟整批边界、最小适配与停止规则**。此为 Gate2 交接范围；2026-10-28 已依据用户后续明确要求进入 VM Gate3。TEST-MAP 的存在不替代下文实际运行结果。

## VM Gate2 只读复核与静态检查（2026-10-28）

GPT 6.1 sol 分别复核隔离/时钟/授权与资金/预算，另只读核对固定 VM 软件和镜像官方元数据；未触发 Daybreak，未使用替代模型。终审发现的“合并预检依赖自身资格”与“禁止广播未限定A入口”歧义已修正，复核确认无剩余Gate2文档阻断。环境仍未实测，Linux CLI资产取得/版本、磁盘足够、VZ时钟隔离与真实出块追赶须在后续获批预检中证明；不能把静态评审当运行通过。

- `gh api repos/nervosnetwork/fiber/pulls/1623 --jq '{state,head:.head.sha,base:.base.sha}'` 返回 open、head `04c206465b48da85b99aa58e80afe9801a2cb2db`、base `2620b5b3fdca082092ce57797d0c22b65c33af59`，退出0。本地产品 `status --short --branch` 干净 detached HEAD，`rev-parse HEAD`同04；实际 `fnn --version` 为 `fnn Fiber v0.10.0-rc1 (04c2064 2026-10-23)`，退出0，未启动节点。
- `python3 scripts/check_test_map.py` → `review cases: 106`、`automated cases: 102`，退出1；仍为既有PMP-01～05/SETTLE-01六个孤儿及历史report overlay十六个重复ID。本批只改三条评审行及文档，三条映射原样保留，无新增孤儿/重复；102/106不是通过率。
- `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/tlc-timeout-refund.md` → `cases: 3`，退出1，仅上述历史重复ID为结构错误；SPEC-03观察与保留分支仍提示人工决定。本批Spec/树/三行无新增结构错误，不宣称全仓静态检查通过。
- `git diff --check` 退出0；未运行pytest、适配自检、节点、VM、构建或调时，未修改产品代码和自动化，原快照/产物/失败证据均保留。

## 原 Gate2 只读复核与静态检查（2026-10-27，历史）

2026-10-27，GPT 6.1 sol 分别复核完整设计及资金/适配细节，最终无剩余 Gate2 阻断，未触发 Daybreak。已核清真实 actor 查询与 only_pending 合成项的区别、历史 TLC/锁定额、公开 flags 的实际输出、内部付款重试及两种退款路径；最后统一 `t_auth` 发送起点、观察 RPC 上限，并补足 FNN 扫描的透明审计归因。复核仅为静态设计意见，不代表实现可执行或场景已通过。

- `git -C download/fiber/source-pr-1623 status --short --branch` / `rev-parse HEAD`：干净 detached HEAD、完整 SHA 为固定 04；`download/fiber/pr-1623-04c2064/fnn --version` 输出 `fnn Fiber v0.10.0-rc1 (04c2064 2026-10-23)`，退出 0。`shasum -a 256` 核对 FNN/SDK agent/驱动及驱动和链适配源码，与现有 build.json 一致；`shasum -a 256 -c report/lsp-watchtower-isolated-04c2064-20261027/original-inputs.sha256` 三项全部 `OK`，退出 0。
- `python3 scripts/check_test_map.py`：`review cases: 106`、`automated cases: 99`，新增三条均未映射，退出 1；仍为既有 `PMP-01～05/SETTLE-01` 孤儿和历史 report overlay 的 16 个重复 ID。本批没有新增孤儿/重复或改动既有映射；总计不是 LSP 通过率。
- `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/tlc-timeout-refund.md`：`cases: 3`，退出 1，仅历史重复 ID 为结构错误；另提示 SPEC-03 的实现观察待人工决定、未取得分支及范围外前沿。三条 Spec/树/用例连接没有本批新增结构错误，不称为全仓检查通过。
- `git diff --check` 退出 0；新文档三条行均为未映射复选框，相对文件链接全部存在，空白检查通过。未运行 pytest、适配自检、节点、构建或回归；原有代码、快照和运行证据均保留。

## 原 Gate3 执行结果与自然等待预算提案（2026-10-27，历史未采纳）

本节保留原始失败与当时的自然等待提案，**未授权执行，不作为当前门禁**。原Gate2短期限不能建立付款；当前自动化仍保留原输入以对应失败证据，上文现已改为待评审VM方案但尚未同步代码。三条行为仍未验收，原始运行证据完整保留。

### 已执行与停止位置

- 固定 `04c2064`，产品源码干净；PR head 相同，FNN/官方 SDK agent 摘要与本轮改动前一致。已实现真实 outgoing 授权、显式单 TLC record/适配模式、独立 FNN 扫描审计和完整生命周期/逐笔账本，GPT 6.1 sol 先完成静态复核；未触发 Daybreak。
- 旧无 TLC 适配自检：`1 passed in 114.69s`，exit 0。新单 TLC 自检：`1 failed in 82.92s`，exit 1，在唯一 `send_payment` 返回 `tlc_expiry_limit 300000 is too small for random expiry reserve 14400000`。
- outgoing 授权已真实写盘，开通交易已发生；付款被路由构造拒绝，未取得含 TLC 检查点、未强关、无 watchtower 签名提交。本次是**场景前置/评审参数错误**，不是已证明的退款产品缺陷，也不复用 #1674/#1706 的归因。
- 已停止后续批次：原正常结算聚焦回归与正式 1+3 **均未运行**。LSP-REFUND-01～03 只有映射，尚未取得行为通过证据。全部原始证据和失败版本在 `report/lsp-refund-04c2064-gate3-20261027/`，详见 [运行记录](../../test_cases/fiber/devnet/lsp/README.md)。

### 更正的源码约束

固定源码 `fiber/config.rs:42` 的 `DEFAULT_TLC_EXPIRY_DELTA` 为 14,400,000ms（4小时）；debug 只降低 MIN，不降低该 DEFAULT。`fiber/graph.rs:2177–2185` 找路前先从 limit 扣除这项固定 reserve，`:2189–2202` 实际选择至少一倍 4 小时的随机值，`:2084–2119` 同时加到首跳及最终 hop 的绝对 expiry。`fixed_rand_expiry_delta` 仅在 `#[cfg(test)]` 单元测试中存在；原 Gate2 与首轮静态复核漏看了这一层，不能只依据 MIN/请求参数校验认定 300 秒真实付款可行。

`send_payment_with_router` 同样经过显式路由校验和共同的 expiry 构造（`graph.rs:1386–1394,1445,1362`），不是短窗口替代；它还引入不同默认参数。不换接口、不注入 add_tlc、不改产品或时钟、不重复抽取随机值。

### 保留真实付款的最小修订

仍用同一条 A→T、Q、H、无 preimage 发票、一次 `send_payment`、T 自然强关；`final_tlc_expiry_delta=300000`、60 秒/300 秒扫描、未成熟保护、SDK/链/资金/业务全部断言保持。拟仅调整明确受 expiry 影响的输入与时间边界：

| 项目 | 原获批值 | 待批准修订 |
| --- | --- | --- |
| `tlc_expiry_limit`（RPC） | `hex(300000)` ms | `hex(14700000)` ms，即 4小时5分钟；扣掉 300000 基础期限后随机预算恰为 14400000，`random_range(1..2)` 仅可能选一倍4小时，不靠重跑筛值 |
| SDK `min_tlc_expiry_delta_ms` | 180000 | 14580000（4小时3分钟），保持原两分钟安全余量关系 |
| SDK `max_tlc_expiry_ms` | `t_auth+420000` | `t_auth+14820000`（4小时7分钟），仍是发送前本地批准，不按事后 E 反推 |
| SDK `expires_at_ms` 与发送起点 | `t_auth+120000`；10秒内开始唯一发送 | 不变，授权新 TLC 的有效期不随链上等待延长 |
| 发票 expiry / 付款 timeout | 各3600秒 | 各21600秒（6小时），长于业务硬限；仍不依赖付款 timeout 自动取消 |
| 真实成熟及索引截止 | `min(t_send+480s, E对应单调时刻+180s)` | `min(t_send+14880s, E对应单调时刻+180s)`，仅等待真实时间和正常挖块 |
| 业务总硬限 | 1500秒 | 15900秒（4小时25分钟） |
| 整轮总上限 | 准备600+业务1500+清理60=2160秒 | 准备600+业务15900+清理60=16560秒（4小时36分钟） |

其他阶段不变：完整 ACK 60秒；主动强关最多60秒且不晚于发送后120秒；确认时距 E 至少120秒；未成熟完整样本跨度至少65秒、75秒封顶；成熟/索引后资金480秒；资金终态后业务收敛360秒；稳定完整样本跨度至少65秒、75秒封顶。最坏 `14880+480+360+75=15795<15900`，不重复计算前面的强关/保护窗口。采样仍目标1秒、单 RPC 最多2秒、整样本3秒、完成间隔最多5秒、每滚动30秒链高增长；长等待不降采样精度、不删证据。

若批准，后续先同步这些参数和截止并交 GPT 6.1 sol 复核，然后重新执行新增适配自检、原正常结算聚焦回归及固定1+3。本轮旧适配自检只保留其已取得的保护证据；若共享适配再次变更，先重做受影响自检。新自检加正式四轮共有五次长场景，预算合计最多 **23小时**；其中正式1+3最多 **18小时24分钟**，另加短聚焦回归。任何非零立即停止后续，产品失败沿既有归因规则处理，不替换失败轮。

历史结论：当时在“任何系统时钟都不改”的边界下，未确认2160s内可行的替代；本提案未获批准、未执行。用户随后确认仅专用VM受控时间的Gate1，当前待评审对象为本文前半部分VM Gate2，不是本节16560s自然等待计划。


### 2026-10-30 固定843夜间资格结果

用户已授权843版本的独立夜跑。Linux构建/时钟/旧适配成功；修复1轮TLC辅助driver接口后，真实TLC资格在固定180秒成熟窗口超时：真实epoch仅推进27/200，虽然median已过到期且indexer追平。产品退款结论未定，SDK完整资格、正常对照及正式1+3均未完成/未运行，三条TEST-MAP不计通过。原04脚本/产物/快照保留，未放宽资金或时间断言；完整证据和下一步边界见本夜结果（本地证据：`/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/report/lsp-night-new-84333ee-20261030T030349/RESULT.md`）。


## 2026-10-30 退款成熟预算修正与获准新批

最终重复次数调整：用户明确采纳两轮独立通过收尾，本批已按两轮方案完成；原启动时1+3预算/计划作为历史保留，实际2/4，后两轮未运行且不再待补。以下预算调整不倒改已执行的deadline或行为预期。

用户已授权预算修正经 GPT-6 Sol High 独立复核后直接验证。本节只替代固定843新批的时间预算，三行行为/资金预期、一次调时、真实正常出块、失败即停与实例独立性均不变；上文原04与已结束夜批的180秒/1500秒/2160秒/411分钟属于保留历史，失败记录不改写。新批保守从北京时间13:00计修正准备，绝对截止21:00（8小时），修复/复核/导出均连续计入，最多2轮有记录的辅助代码修复；正式结果与执行进展以本批证据为准；预算本身不表示产品通过。

原始链样本逐条单调核算：确认后首完整样本98.168844963→末342.967144496，共244.7983秒、243块、0.135epoch；跳前65.2196秒/65块，跳后163.503589036→342.967144496共179.4636秒/178块（0.0988889epoch）。所以不能按180秒/0.135估算。实际矿工默认Dummy Constant1000ms、poll1000ms；冻结dev参数`epoch_duration_target=14400`、`permanent_difficulty_in_dummy=true`。CKB v0.202.0 `spec/src/consensus.rs` 的permanent分支以`ceil(14400/8)=1800`决定下一epoch长度，当前epoch也实见1800；跳墙钟不缩短该长度。完整1epoch按实测约1813秒；跳前已自然消耗约65秒，跳后预计约1748秒。新资格必须再次读回真实矿工/参数和跨epoch样本，预测不替代真实成熟断言。

| 边界 | 固定843新批 | 保持的验证 |
| --- | --- | --- |
| 真实成熟/索引 | `t_jump+2100s`（35分钟），仍取更早业务总截止 | 真实canonical epoch、median、indexer；每笔真实输入的since；不改矿工/epoch/区块/RPC或追加调时 |
| 唯一发送后业务总限 | 3300秒（55分钟） | 串行上限`60+60+75+30+2100+480+360+75=3240s`，留60秒余量；单阶段到期不能借余量续期 |
| 每实例总限 | 3960秒（66分钟）=准备600+业务3300+清理60 | 宿主/guest独立单调计时；guest marker记录完整实例截止，双方都在最后60秒只收尾，避免旧入口重复预扣60秒 |
| 资金/终态/稳定 | 480秒 / 360秒 / 至少65秒且75秒封顶 | 原完整SDK Applied、两方份额/费用、唯一退款、付款Failed/发票Received/通道Closed和逐样本稳定断言不减 |
| 发票expiry、付款timeout | 仍各21600秒 | 付款前保守核`授权墙钟+14820+5+3300秒 < 原发票创建+21600秒`；对本固定token维持无time-check证据，不续token/批准 |
| 已匹配产物后全序列 | 时钟9+旧适配21+真实链/SDK资格66+正常对照21+正式4×66=381分钟硬限 | 全部独立实例；资格须一次完整成功才运行正常对照和正式固定1+3；任一步失败停批，不重跑挑分支 |

运行前原843业务空白repairbase可作为只读来源：完整核FNN/SDK/driver/锁/工具/输入摘要后，克隆新base，仅同步预算/配置读回和新实例名前缀对应的网络身份校验（三个辅助输入）并重新冻结；不重编、不改产品字节，不复用消费资格。宿主始终≥8GiB、guest≥4GiB，不删旧证据腾空间。旧8VM保留Stopped；本批只清理本批创建的实例。全序列通常预计约3～4小时（真实资格约30分钟、正式每轮约32～40分钟，加时钟/对照），这是短样本推测，未完整实测；66分钟/实例和21:00绝对截止是停止守卫，均不是产品SLA。

新的唯一证据目录为 `/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/report/lsp-refund-84333ee-20261030T1300`；旧夜证据、样本与退出码完整保留。三条TEST-MAP及复选框不变，只有实际正式生命周期与全部断言通过后才更新执行结论。

本批正常对照边界核实：原已批准的`TestWatchtowerSettlement.test_authorized_settlement`保留既有`generate_block`主动出块，属于无TLC正常结算兼容回归；它不改矿工配置/区块字段/RPC实现，但不是自然出块速度证据。新TLC资格及正式退款始终只用原矿工自然出块，不调用该加速路径。此区别经GPT-6 Sol High只读复核，未改冻结输入。

新批实际进度：15:17:57正式第1轮完整通过，真实单调1982.62s，分支为独立TLC退款→T份额→A最终份额。Q=100000000仅计一次，三笔P合计99999999543=C0，支出费2305+强关费457=2762 Shannon，真实SDK Applied上链、逐笔since/lineage、终态和65.16s稳定通过，并经GPT-6 Sol High独立核验。固定1+3目前1/4，第二轮独立实例执行中；旧批失败不改写，三条TEST-MAP复选框保持映射含义，整批尚未完成。


### 2026-10-30 最终收尾（用户接受两轮）

用户明确要求“本次退款以两轮独立通过收尾，不补第3/4轮”。本次仅调整重复次数，不改LSP-REFUND-01～03的行为/费用/资金/终态/连续稳定断言，三条TEST-MAP及复选框不变。固定843两轮完整通过（host1982.62s、1983.24s），均取得自然独立TLC退款→T份额→A最终份额，付款Failed/发票Received/双端关闭、真实SDK Applied、逐笔since与总账守恒及65s稳定均完成；本次按用户接受的2/2完成，原1+3历史仅执行2/4，不写4/4，3/4不再是待补任务。其他未自然取得的分支仍按原范围边界说明。

为重启设置的host新clone门禁在第二轮导出/停止后拒绝后续VM创建（原拒绝78被控制器/监督器包装退出1）；无第3/4样本执行，无产品断言失败。所有自有进程和VM已停止，指定端口释放，原04/旧夜证据不改写；15份本次及旧843停止态VM磁盘、固定工具和完整证据已在宿主持久目录保存。原13:00→21:00预算未重置，重启后不自动续跑。准确结论、hash和重启交接见完整报告（本地证据：`/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/report/lsp-refund-84333ee-20261030T1300/RESULT.md`）与环境收尾（本地证据：`/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/report/lsp-refund-84333ee-20261030T1300/final-environment.json`）。

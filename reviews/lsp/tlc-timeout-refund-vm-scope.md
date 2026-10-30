# Gate1：专用 VM 受控时间下的 TLC 超时退款

用户已明确确认本 Gate1，当前入口为 [VM Gate2 完整行集、隔离预检、资金断言、预算与最小适配](tlc-timeout-refund.md)。下文保留 Gate1 依据与当时预算；Gate2 将真实链/SDK预检与新含TLC自检合并计时，仍待人工确认，尚未安装、启动或运行。

2026-10-28，本轮只评审环境、时间隔离、验证边界和预算。依据 [交接](../../docs/analysis/pr-1623-handoff-2026-10-27.md)、[原用例与 Gate3 失败记录](tlc-timeout-refund.md)及本轮只读核查，建议以 **专用 Linux ARM64 VM，单次推进 guest 墙钟**，缩短真实 A→T 付款中必须存在的约四小时 TLC 等待。候选方案尚未安装或实测，不能承诺已经可运行。

原 LSP-REFUND-01～03 和 TEST-MAP 保留；本轮不改正式用例行、自动化、产品代码或宿主机时间，不运行测试、启动 VM、安装依赖或重建产物。原文的自然等待长预算未获批准，保留为历史方案。本 Gate1 获批后只进入 Gate2，重新展示这三条用例的受控时间前提、完整参数、断言和执行边界。

## 可用环境与基线

| 本轮只读结果 | 对方案的影响 |
| --- | --- |
| 测试分支 `codex/lsp-core-regressions`；已有暂存/未暂存/未跟踪内容保持原样 | 新范围文档之外只同步评审入口与纠正反馈；不清理工作区 |
| GitHub PR #1623 open，head 与本地干净产品源码均为 `04c206465b48da85b99aa58e80afe9801a2cb2db`，base 为 `2620b5b3fdca082092ce57797d0c22b65c33af59` | 不切换版本、不 fetch/reset；未来 Linux 构建仍锁定完整 SHA 与 Cargo.lock |
| 实际 FNN 返回 `fnn Fiber v0.10.0-rc1 (04c2064 2026-10-23)`；FNN/SDK agent 均为 Mach-O ARM64；build.json 为 dev + `fiber-bin/debug-add-tlc` | macOS 产物不能直接在 Linux 中运行；Linux 需同源码/锁文件/profile/features 的独立构建。debug 也有固定四小时 reserve，不能把换构建类型当成短时方案 |
| macOS 26.6.2 / Darwin 25.6.0 ARM64，12 逻辑 CPU、32 GiB RAM、`kern.hv_support=1` | 满足候选原生 ARM64 虚拟化的宿主前提；尚不证明 guest 时钟可以受控且不被回拨 |
| 内置盘可用约 43 GiB；现有 Mac Cargo target 约 13 GiB | 候选 VM 先按 4 vCPU、8 GiB RAM、32 GiB 动态磁盘上限设计，构建并行最多 2；宿主可用低于 8 GiB 或 guest 低于 4 GiB 即停止。数值是资源限额，未证明足够完成冷构建；不复制 Mac target/venv、不自动扩盘或删除文件 |
| `/Volumes/2T` 另有约 1.6 TiB 可用 | 文件系统与 VM 磁盘兼容性未核实；不默认把 VM 放到该卷，不据此声称磁盘阻断已消除 |
| PATH、常用安装目录和实例目录未发现 Lima、UTM、Colima、OrbStack、QEMU、Parallels、Multipass、Tart 等可用专用 VM | 当前没有核实可直接使用的专用 VM；仍需后续门禁批准准备环境 |
| 只发现 Docker Desktop 4.46.0 / CLI 28.4.0；`desktop-linux` daemon 连接失败 | 不把它记作正在运行的空环境；不启动或复用其共享 VM，不在普通容器中改时钟 |
| 框架 CURRENT_TEST 指向 CKB 0.202.0；官方发布确有 Linux aarch64 资产；现有 ckb-cli 为 1.15.0 | 未来固定同版 CKB、CLI、原快照和合约字节。CLI Linux 资产查询本轮网络失败，其取得方式留作 Gate2 准备项；不降级或改用本机另一个版本 |

候选采用 **Lima VZ + Linux ARM64 + plain 模式**。官方 [VZ 文档](https://lima-vm.io/docs/config/vmtype/vz/)支持 macOS 原生虚拟化；[plain 文档](https://lima-vm.io/docs/config/plain/)明确禁用宿主时钟同步、共享挂载、动态端口转发、guest agent、containerd、Rosetta 和 SSH agent 转发，保留 SSH/配置能力。这是选择依据，不是已验证配置；Gate2 固定实际 Lima/guest 镜像版本与摘要，不能在执行时使用浮动 latest。

Linux 构建遵循产品 `rust-toolchain.toml` 的 1.95.0、原锁文件和构建选项，不直接沿用 Dockerfile 中不同的 Rust 版本和 release profile。测试仓库将冻结本范围所需的当前源码，复制到 guest 本地文件系统，另存来源摘要；原始快照仅复制工作副本，部署字节仍按既有可信对照校验。Linux 产物另存独立目录和构建记录，不能覆盖 Mac 产物或声称两者二进制相同。若需要改产品源码才能构建，停止并报告。

## Spec

### SPEC-01：只有专用 guest 的墙钟允许发生一次受控跃迁
Condition: 全部 CKB、miner、A/T FNN、SDK、Python 驱动和观察器均在同一专用 VM 内；宿主仅控制与收集证据，guest 无其他业务；先完成时钟能力预检。
Expected: 待确认：guest 关闭 NTP/chrony/systemd-timesyncd 等实际存在的网络校时和 VM 宿主同步机制；只允许一次预先限定的正向 CLOCK_REALTIME 调整。宿主时间不变，guest 单调时间持续计时；未知跳变、回拨、同步、挂起/恢复或重启使该轮失效并停止，不补跳或重置预算。
Observable: VM 配置与身份、校时服务状态、宿主与 guest 各自 wall/monotonic 采样、唯一跳变事件的前后值/偏移/执行结果、链与产品进程连续性。两个系统的 monotonic 原点不可直接相减，只比较各自时间增量及观测界限。
Basis: 用户要求不改宿主时间；[Linux time namespaces](https://man7.org/linux/man-pages/man7/time_namespaces.7.html)不隔离 CLOCK_REALTIME；[clock_gettime](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)说明单调时间不受墙钟跳变影响；Lima plain 的同步禁用须再实测。
Source: inference
Testing: not_tested — Gate2 定义能力预检与独立宿主截止；本轮不安装、开机、改时钟或执行预检。

### SPEC-02：先证明未成熟保护，再由真实链证明到期和资金路径
Condition: 原真实 A→T 单笔 1 CKB hold 付款已完整 ACK，T 的含目标 TLC 强关交易已 canonical 确认；未交 preimage；取得至少 65 秒自然未成熟窗口和真实 FNN watchtower 扫描证据。
Expected: 待确认：之后才按双方实际一致的 expiry E 单次推进 guest 墙钟至 E 严格过期之后的小幅余量；继续正常挖块。只有真实 median、epoch 和当前输入 since 满足原判断才进入退款验收；原 SDK R/S/Applied、witness、公钥、逐 outpoint 资金守恒、后继结算及无重复退款断言全部保留。允许自然独立 TLC 退款或最终 Settlement sweep，不操控 T 的合法顺序。
Observable: 跳变前后连续样本和真实 canonical 链响应、原 funding→commitment→每个后继、交易与签名链、实际分支；墙钟过期不能替代链成熟。Tlc key 未出现仍不计该分支覆盖。
Basis: [原 Gate2 的 SPEC-01/02 与两种路径账本](tlc-timeout-refund.md)、固定源码 watchtower actor / SDK 链验证；四小时 reserve 见 `fiber/config.rs:42` 和 `fiber/graph.rs:2177–2202`。
Source: inference
Testing: not_tested — Gate2 保留产品断言，补齐一次跳变、真实链追赶、索引和预算失败的判定。

### SPEC-03：业务收敛和有限时长稳定性仍独立验收
Condition: SPEC-02 的资金路径已被独立证明；同一原付款、发票和通道继续由正常产品进程处理，未重新付款、重新批准或修改存储。
Expected: 待确认：仍要求原付款 Failed、发票 Received、A/T 正确强关终态和 hash、公开 WAITING_ONCHAIN_SETTLEMENT 清除、目标 TLC 移除状态，以及至少 65 秒自然稳定窗口；60 秒 watchtower 与 300 秒 Hosted 关闭识别周期不缩短。结果只记为 Linux VM 受控时间验证，不能转记为四小时自然等待或 macOS 原产物通过。
Observable: 同一 H/channel 的 RPC/HTTP/WS、公开 flags、账本、自然扫描与连续采样；记录真实经过时长和 guest 虚拟经过时长，分别标明宿主真实日期与 guest 时间。
Basis: [原 Gate2 SPEC-03 和证据边界](tlc-timeout-refund.md)；用户要求保持产品与基线，沿用已知归因并保留全部证据。
Source: inference
Testing: not_tested — Gate2 写明授权/发票/付款的逻辑期限及固定 1+3 的执行前提；不能依据时间跳变后单个 Failed 状态认定链退款成功。

## 测试树

<!-- TEST-TREE-BEGIN -->
- 受控时间环境资格
  - guest 独占、无共享时钟/可写宿主挂载，宿主未被调时 [pending] — SPEC-01；Gate2 固定配置、资源、证据和停止条件。
  - 唯一正向跳变、guest monotonic 连续、至少 360 秒无重新同步 [pending] — SPEC-01；先在可丢弃的预检实例证明，不占正式业务样本。
- 原退款行为在明确环境下复核
  - 唯一真实付款、完整 ACK、含 TLC 强关及 65 秒自然未成熟保护 [pending] — SPEC-02；Gate2 对齐原第一条用例，不缩短自然窗口。
  - 跳后正常挖块，真实 median/epoch/since 共同成熟 [pending] — SPEC-02；不能伪造 RPC、改区块时间戳或以固定块数代替。
  - 实际独立 TLC 或最终 sweep 的签名、资金归属、后继结算和守恒 [pending] — SPEC-02；沿用原第二条用例和分支缺口。
  - 原付款/发票/通道终态与 65 秒自然稳定 [pending] — SPEC-03；对齐原第三条用例，保留 300 秒识别周期。
- 本轮不声称覆盖
  - 四小时自然等待的存活、重试节奏、资源增长与真实竞态分布 [not_applicable] — 受控时间无法替代，仍留为长周期验证缺口。
  - macOS 原二进制、生产公网时间/共识、其他 VM 平台 [not_applicable] — 当前候选仅独立 Linux ARM64 devnet。
  - 未取得的退款分支、更多资产/拓扑与原保留范围 [unanalysed] — 继续沿用原 Gate1，不以重复取景补齐。
<!-- TEST-TREE-END -->

## 用例范围与最小适配边界（Gate2 入口）

<!-- TEST-CASES-BEGIN -->
不新增独立产品行为或重复用例行。正式定义仍唯一保留于 [LSP-REFUND-01～03](tlc-timeout-refund.md)；本 Gate1 确认后，Gate2 再完整展示三行的受控环境前提和共享参数。三个现有映射不变，但当前测试尚不支持本 VM 方案；其复选框不能解释为本方案已经实现或通过。
<!-- TEST-CASES-END -->

拟限定以下适配，当前不实现：

1. **保留合法的长逻辑期限。** 候选参数为 final delta 300000ms、limit 14700000ms、SDK min delta 14580000ms、max expiry `t_auth+14820000ms`；发票 expiry/payment timeout 各 21600s。初始 outgoing 授权仍只到 `t_auth+120000ms`，从 `t_auth` 起 10 秒内完成批准持久化并开始唯一付款；不延长授权窗口、不按后来 E 反推批准。跳变发生在完整 ACK 之后，已有 TLC 的链上批准仍绑定原 D 与费用上限。Gate2 核对所有 token/证书/授权的实际有效期；跳后失效不得重签 token 或重授权补救。
2. **局部控制器与明确的时间阶段。** 仅为本模式加入“自然保护→一次跳变→自然收敛”状态，E 取双方实际记录，目标墙钟值为 E 严格过期后的固定小余量（Gate2 冻结，候选 `E+5秒`）；命令执行预算不作为额外可选跳幅。保留 `_sample` 的时钟一致性检查，将其改为只在这一个获准事件切换偏移基准；非事件期间仍检测漂移。原 E 到 monotonic 的换算相应分段，所有阶段和总预算沿 monotonic 连续计时，不重新计时或取消采样要求。
3. **时钟执行权限只在 guest。** 不复用会直接调用系统调时的 `framework.util.change_time`，不运行宿主 sudo/date/NTP 修改；控制器核对 VM 身份与 guest 本地标记后才可在 guest 调时。plain 模式之外还需核对实际校时服务和恢复钩子；停掉网络校时不等于禁掉全部同步。运行期只保留所需 SSH 控制，测试依赖本地隔离链，不访问公网服务。
4. **实际链验证和独立预算。** 不模拟 CKB median/epoch，不修改矿工/合约/节点源码或既有扫描周期，不设置未来区块字段。guest 正常 miner 产生区块后才检查 canonical 链与 since；epoch 相对延迟仍可能要求继续出块。宿主单调计时监控 VM 总截止，guest 相对计时器和 Python monotonic 的行为先在预检中确认；宿主挂起/监控失联也不能算有效样本。
5. **每轮独立、证据不回滚。** 只从无业务数据的基础镜像启动新的工作副本；不恢复运行中快照跳过生命周期。结束先停止本轮进程并导出证据，再重建下一轮环境，不在活节点上回拨 guest 时钟。保留失败实例/磁盘和全部输出直至证据完整，资源不足则停止，不删原快照或历史 report 腾空间。结果导出新目录，禁止覆盖既有证据。

能力预检至少要证实：宿主 wall/mono 无不期望变化；guest wall 按要求只跳一次、mono/相对截止不跳；至少 360 秒保持偏移不被校回；正常 CKB 块能推进真实 median 与 since，独立 SDK 链验证和原有授权继续有效。Gate2 分开定义纯时钟与真实链/授权预检的实例，均与正式样本独立，每个实例最多一次跳变，不在已跳过的实例回拨后跑正式样本。预检不算三条产品用例通过；任何一项不成立，报告具体能力阻断，不能扩大偏差容忍、追加跳变或改产品绕过。通过后才具备提交后续运行决定的依据。

## 预算：首次准备与预热运行分开

下表是**拟议停止上限，不是实测耗时或成功保证**。本轮不消耗这些执行预算；Gate2 固定命令/阶段后仍需批准，准备超时先报告，不自动申请更多资源或无限续跑。

| 阶段 | 拟议宿主真实时间上限 | 边界 |
| --- | --- | --- |
| 首次 VM/镜像/系统依赖准备 | 60 分钟 | 固定版本；含 VM 安装、镜像、Linux CKB/CLI 与系统依赖取得，网络或权限阻断单独报告 |
| 首次同版 Linux FNN/SDK/驱动及依赖准备 | 120 分钟 | 含 Rust 工具链/依赖、Python venv、固定 04/锁文件/dev/features 的构建；不改产品；资源或 Linux 兼容性不足即停止 |
| 首次时钟/链/授权能力预检 | 45 分钟 | 含快照工作副本、合约核对、至少 360 秒跳后自然观察和结果整理；不能略过后直接开始正式 1+3 |
| 已有可用基础 VM 后，每个完整生命周期 | 36 分钟 | 准备 600s + 业务 1500s + 收尾 60s；须已有可启动基础 VM、匹配 Linux 产物、完整 venv 与可信快照，不合格就回到环境未就绪，不能在预算外补装依赖 |
| 正式固定 1+3 | 最多 144 分钟 | 沿用四个独立完整样本，不合并共享付款、不替换失败轮；仍待 Gate2/3 执行授权 |
| 新含 TLC 适配自检 + 正式 1+3 | 最多 180 分钟，另加相关短自检/聚焦回归 | 若新适配自检本身需一个完整生命周期，照实再计一轮；Gate2 列出短项预算，不能把它们隐去后声称整批只需 36 分钟 |

首次准备三个上限合计 **225 分钟（3小时45分）**，加一个完整生命周期为 **261 分钟（4小时21分）**；不存在另一个无界依赖准备阶段。首次仍可能因构建/隔离不满足而失败；本方案主要减少重复验证中的四小时自然等待，不保证首次从零准备比原单轮更快。内置盘空间紧，下载、构建、复制和运行中均监控空间，计入基础镜像、活动工作盘、保留的失败盘、VM 缓存和证据副本；32 GiB guest 上限不是宿主额外总占用的保证。若资源不足，先交回资源选择，不自动使用外置盘。OOM 或持续 swap 导致超时同样是环境阻断，不自动扩内存、磁盘或并行度。

预热单轮业务的初步顺序上限为：完整 ACK 60s → 强关确认 60s → 未成熟窗口 75s（完整跨度≥65s）→ 单次跳变控制 30s → 真实成熟/索引 180s → 资金 480s → 业务收敛 360s → 稳定 75s（完整跨度≥65s）。合计 **1320s < 1500s**，各阶段串行消耗同一宿主单调截止，未用总余量不能延长已超时阶段。30s 包括命令、读回与确认，180s 成熟阶段不能补做未完成的调时；收尾也受独立宿主截止约束。能力预检必须证明真实出块追赶可在候选成熟预算内完成，否则回到预算评审，不自动延长。原单 RPC 2s、完整样本 3s、完成间隔≤5s和链高进展检查保留；跳变不允许制造未观察的退款盲区，事件时并行观察与时间界限在 Gate2 写清。

## 停止规则与交接

- 时间隔离/构建/成熟预检不成立属于环境或适配阻断；不写成退款产品失败。真实业务场景前提缺失仍为场景未取得；充分前提后的资金/签名/终态错误才按产品证据处理。超出预算不自动等同于某个已知问题。
- #1674、#1706 和 08/10/TIMEOUT-12 的最终归因沿用交接，仅新源码、新证据或不同症状再调查。任何非零停止后续批次；产品失败不换时序、换分支或重跑取成功。受控时间引入的新症状保留其环境标签，不能未经证据直接归入旧 bug，也不能抹去真实资金错误。
- 本轮没有新的运行通过项：此前 `adapter-existing` 1 passed 和 `adapter-tlc-1` 的四小时 reserve 参数失败保留原义，原聚焦回归及固定 1+3 仍未运行；24 的历史通过不计作 04 通过。金额、SDK verified 路径及“结算到已授权 sponsor 地址，不等于租户独立钱包取回”的边界不变。

下一门禁：请评审上述候选 VM/时间隔离、SPEC-01～03、资源限额与预算。批准本 Gate1 后只展开 Gate2 的完整行集、时钟证据与最小适配，不自动安装、启动 VM、写自动化或运行测试。

## 只读复核与静态检查

2026-10-28，GPT 6.1 sol 分别复核时间隔离/产品断言与资源/预算，无剩余 Gate1 文档阻断；已按建议明确授权的 `t_auth` 起点、预检实例隔离和全部磁盘副本成本。未触发 Daybreak，未使用替代模型。复核意见不等于 VM 能力或产品运行通过。

- `gh api repos/nervosnetwork/fiber/pulls/1623 --jq '{state,head:.head.sha,base:.base.sha}'` 返回 open / `04c206465b48da85b99aa58e80afe9801a2cb2db` / `2620b5b3fdca082092ce57797d0c22b65c33af59`；本地产品 Git 与 FNN 版本相符。版本读取未启动节点。
- `python3 scripts/check_test_map.py` → `review cases: 106`、`automated cases: 102`，退出 1：原有 6 个 PMP/SETTLE 孤儿映射及历史 report overlay 的 16 个重复 ID；本次未增删 TEST-MAP，未清理历史证据。
- `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/tlc-timeout-refund-vm-scope.md` → `cases: 0`，退出 1：上述历史重复 ID，加本 Gate1 仅范围、未定义正式行；SPEC/pending 分支仍待用户决定，不宣称完整用例设计检查通过。
- `git diff --check` 退出 0；新文件 `git diff --no-index --check /dev/null reviews/lsp/tlc-timeout-refund-vm-scope.md` 无空白错误诊断，退出 1（新文件差异）。本轮仅更新文档，未执行 pytest、适配自检、节点/VM、构建或调时。

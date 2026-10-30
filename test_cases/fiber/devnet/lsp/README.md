# Hosted LSP 通道签名集成测试

## 84333ee 收尾结论与新会话入口（2026-10-31）

**本轮专项测试已带已知问题收尾；不建议对产品提交给出无条件合并通过。** 用户已取消多 preimage 本地补跑，不再扩充场景、启动测试或补退款第3/4轮。下方历史章节中的“下一批”“待今晚执行”“需补跑”等计划，以本节最终决定为准。

- 被测产品：`nervosnetwork/fiber#1623`，固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；测试基准不是当前 Git 分支的提交号。未改产品代码。
- 已登记76个LSP场景：56个该版本通过、2个产品失败、1个竞争相关测试失败、17个没有该版本完整业务结果。73个有自动化映射；映射率、执行率均不是PR核心逻辑或代码覆盖率。104项Rust测试另计。
- 退款REFUND-01～03已按用户最终接受的两轮独立通过完成，包含资格、正常对照、实际链上支出、费用及资金守恒。原1+3没有完整执行，不再待补。
- 本节是最新收尾与继续工作的入口；评审行和TEST-MAP仍分别以 `reviews/lsp/` 和测试源码为事实来源。

### 核心覆盖与实际边界

| PR核心行为 | 现有验证结果与限制 |
| --- | --- |
| SDK/Agent签名、授权及迁移 | 82+16+4+1+1共104项Rust测试通过；包含非法输入拒绝与迁移。 |
| Hosted通道、付款、重试与原存储恢复 | 正常付款、重复提交、SDK恢复、整个FNN重启恢复及同通道连续付款后恢复通过；RECOVERY-05增强和08均有实测。 |
| 租户订阅、浏览器鉴权与通道过滤 | 相关当前版本测试通过；8个早期订阅ID只有旧版本结果，没有转记843通过。 |
| 服务接纳与投递一致性 | DELIVERY-01、03～06通过；02在真实接纳后受控丢回复时出现上下游结果不一致。 |
| 签名期限、强关承诺与关闭恢复 | TIMEOUT-01/02/03/06/08/10/11/12通过；07保留竞争等待失败，04/05沿#1674历史归因。受控竞争结果不证明所有自然时序。 |
| 链上超时退款 | 两轮REFUND-01～03完整通过；批准的收款配置不证明独立用户收款地址与运营方出资地址分离的能力。 |

### 合并前问题与有限后续

| 问题 | 当前结论 | 修复后的最小验证 |
| --- | --- | --- |
| DELIVERY-02 | 上游付款失败、同incoming key下游成功。早期一致性断言停止，未完成最终资金和30秒稳定窗口，不能宣称已证明永久损失。 | 有修复提交后审相关diff，定点执行已有02及直接受影响检查。 |
| INVOICE-CANCEL-01 | 合法tenant token取消Open发票被Unauthorized拒绝；02受同一入口阻断。 | 修复入口后执行已有01/02；若明确排除该能力，须记录产品范围决定，不能改写为通过。 |
| #1674 / TIMEOUT-04/05 | 历史开通超时产品问题尚未闭环；本轮没有在843重新执行04/05。 | 修复版定点验证04/05，沿用既有归因。#1706已修复且相关回归通过，不列当前阻断。 |
| 独立用户地址收款 | 当前正向能力未证明。SDK已有错误目的地拒签测试，不能再把它当全新负向缺口。 | 若PR承诺独立地址收款，则需修复与已有确认场景验收；若限制原型范围，明确记录限制。不得把已批准的运营方地址退款等同用户独立取回。 |

其他残余：PAYMENT-04已实现但停在环境准备，Hosted Received取消与永久缺授权后的完整资金收尾未完整验证；多preimage现有上游CI在连接准备阶段失败，没有业务结果，用户已取消本地补跑。上述残余不自动变成新一批任务。最后保存的PR状态含合并冲突；最终合并版本需核对冲突解决及修复diff，并满足必需CI。

**完成标准：** 固定版本核心行为已有代表性验证，实际成功/失败/未运行有证据且归因明确，剩余风险已交付。本轮达到这一标准，可以结束测试工作。产品修复回来后才重新进入有限定点验证，不默认重跑104项、退款或其他无关回归。没有修复或相关新证据时，下一步是等待开发处理已知问题。

### 测试代码提交关系与可复现边界

- 测试仓库目标分支为 `sunchengzhu/fiber-py-integration-test:codex/lsp-core-regressions`。[PR #2](https://github.com/sunchengzhu/fiber-py-integration-test/pull/2)已合并；[订阅过滤#3](https://github.com/sunchengzhu/fiber-py-integration-test/pull/3)、[Watchtower诊断#4](https://github.com/sunchengzhu/fiber-py-integration-test/pull/4)、[取消入口#5](https://github.com/sunchengzhu/fiber-py-integration-test/pull/5)、[接纳一致性#6](https://github.com/sunchengzhu/fiber-py-integration-test/pull/6)已提交、尚未合并。
- `codex/lsp-84333ee-closeout` 整合上述代码的本地最终内容，以及RECOVERY-05/08、PAYMENT-04、退款夜跑源码和最终记录，供一次审阅。与#3～#6有内容重叠；不要把整合PR与这些PR当成互不相干的补丁依次合并。原PR保持不变，不在本次自动关闭或合并。
- 整合分支是**草稿交付**。PAYMENT-04准备问题未修复、没有业务通过记录；退款原启动脚本仍固定04版本及本机输入，不能直接复现843两轮补救批。843使用的独立补救批输入保留在原本地证据中，本次没有移植或重新执行启动器。
- 夜跑源码独立放在 `lsp_nightly/`，`manual_nightly`及默认deselect保持；不加入普通测试、Makefile或定时CI。本次仅整合源码、运行记录及静态检查，不启动节点/VM或产品测试。
- `report/`、`tmp/`、下载包、编译缓存、节点密钥、VM磁盘均未提交。GitHub上的摘要可读，原始证据仍只在下列本机目录，不能声称已公开上传可复验的全部原始日志。

### 本次整合检查（不运行产品测试）

- `black --check .`：退出0，428个Python文件无需格式修改。20个本次复制的Python文件与原实现AST一致；Rust、Shell、配置文件字节保持原样，原45个源文件未变。
- Python语法20文件、`bash -n` 3个脚本及 `git diff --check` 均通过。本次没有运行pytest、构建、节点或VM。
- `python3 scripts/check_test_map.py`：项目级128评审/121映射，退出1；仅6个基线已有孤儿PMP-01～05、SETTLE-01，无重复评审ID。退款评审与代码已一起纳入整合树，因此不再产生原工作树的3个REFUND孤儿。项目计数不等于上文76个LSP场景的口径。
- GPT-6 Sol High只读复核了源码提交边界、退款历史入口及收尾交接。格式与静态检查不代替业务执行；既有失败和未运行状态保持。

### 证据定位

原主工作树及本地证据根目录：`/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test`。以下均是相对此根目录的本地路径，不是GitHub仓库文件：

| 结果 | 本地证据 |
| --- | --- |
| DELIVERY-02产品失败 | `report/lsp-delivery-84333ee-20261030T013955/`，正式02及其原始状态 |
| 租户取消入口失败 | `report/lsp-invoice-cancel-84333ee-20261030T003644/` |
| DELIVERY-03～06通过 | `report/lsp-night-new-84333ee-20261030T030349/RESULT.md`；同批退款资格失败不计正式退款结果 |
| 两轮完整退款通过 | `report/lsp-refund-84333ee-20261030T1300/RESULT.md` |
| 104项Rust通过 | `report/lsp-closeout-84333ee-20261030/execution-211837/RESULT.md` |
| RECOVERY-05增强、4项超时通过及07竞争失败 | `report/lsp-closeout-84333ee-20261030/execution-214323/RESULT.md` |
| 其余4项超时通过、清理与复核 | `report/lsp-closeout-84333ee-20261030/execution-220814/RESULT.md` |

最新成功批已归档必要证据并清理本批临时目录，自有进程退出、端口释放；全部旧失败证据保留。原仓库 `/Users/sunchengzhu/project/fiber-py-integration-test` 也保留退款源码、历史04入口和无关本地修改，本次不覆盖。

### 可直接给新会话的任务

> 继续Fiber PR #1623的已收尾测试工作，先读AGENTS.md和本README顶部“84333ee收尾结论与新会话入口”，必要时读取对应评审及原本地证据。固定产品84333ee，本轮测试工作已结束，不能解释为全部通过或可无条件合并。当前只核对测试整合PR和产品修复状态，报告是否存在需要定点验证的实际diff；没有修复就不启动测试。后续范围限DELIVERY-02、取消01/02、#1674对应04/05及明确纳入产品承诺的独立收款问题。多preimage本地补跑取消，退款两轮已完成，不补3/4，不重跑无关通过项。若需要新增/实质修改用例或启动新批，先给我有限方案和预算并等确认。保留证据和其他改动，清理自己产生的临时文件。复核用GPT-6 Sol High。

---

## 以下为各版本历史记录

本文件保留普通 LSP 的运行版本、已知归因及验证边界。开通计时器 [#1674](https://github.com/nervosnetwork/fiber/issues/1674) 与 watchtower 陈旧请求遮蔽 [#1706](https://github.com/nervosnetwork/fiber/issues/1706) 均有历史失败证据；#1706 已按下文指定修复提交完成定点回归，不能把旧版失败写成修复版现状。先复用各版本归因和证据，不当作未知问题重复定位。

接纳一致性固定84333ee，六行均有TEST-MAP。第九批正式01通过、02产品一致性失败后停止；后续独立夜批03～06各单次通过，当前正式通过5/6。02在受控丢弃接纳回复、真实5秒调用超时后观测到原K失败而同K下游付款成功，早期断言即停，未完成最终资金与30秒稳定判据；其他行通过不能冲销此失败。第七/八批测试准备与观察问题保留历史，此新产品失败不归入旧#1674/#1706。各批证据见文末。

2026-10-29 评审边界补充：既有 watchtower 测试主动批准 T 的 sponsor 钱包，资金守恒通过不证明独立用户收款归属。新[实测反馈 Gate1](../../../../reviews/lsp/field-feedback-scope.md)已列独立目的地、服务接纳竞态、租户取消、授权拒签收尾及长期状态等候选；Gate1已获确认，本轮方向1/2的[Gate2](../../../../reviews/lsp/watchtower-settlement.md#独立收款与目的地替换gate22026-10-29)补强01并新增05/06，02仅澄清历史判据；行集已确认并进入Gate3：05建立映射，旧01过时映射移除，01/06等待修复版；执行另记本轮结果。历史#1706修复及订阅过滤通过维持原范围。

2026-10-28 更新：#1706 已在指定修复提交 `3ce369e` 重编并完成定点验证，适配自检与 watchtower 四条单轮共 5/5 通过，GPT 6.1 sol 复核无阻断。详见文末修复记录；默认基线仍为 04，其历史失败不覆盖、不抹去。

订阅过滤最新状态：用户授权更新LSP分支后，20～28在独立匹配的 `84333ee` 产物上完成相关3/3及固定1+3共48/48，退出码均0，见[最新记录](#84333ee-订阅过滤-gate3完成2026-10-29)。此前[04产物准备失败](#04c2064-订阅过滤-gate3准备失败2026-10-28)完整保留；该次没有执行产品样本。

2026-10-30整体盘点（PAYMENT-04接入映射后更新）：正式LSP ID为76个（本工作树普通73、原仓库退款3），固定843为 **48通过、2个产品失败、26个尚无该版本正式结果**；有结果50/76（约66%），通过48/76（约63%），不是全PR代码覆盖率。48包括订阅过滤及相关订阅12、watchtower旧02/新05共2、[普通核心/延迟付款/浏览器回归](#84333ee-普通lsp回归30方法通过2026-10-30)对应25、DELIVERY通过5、退款3及[新增RECOVERY-08](#84333ee-连续付款后原sdk存储恢复gate3通过2026-10-30)。退款三个ID映射同一方法，两轮独立通过按用户要求收尾，不再待补第3/4轮，见退款最终证据（本地证据：`../../../../report/lsp-refund-84333ee-20261030T1300/RESULT.md`）。失败为DELIVERY-02、INVOICE-CANCEL-01。

26个无843结果的ID必须分开处理：新增PAYMENT-04已实现，最新192130批在pytest加载的实际类缺少隔离路径时准备报错，未执行合约对齐或业务步骤；旧版已执行、仅需最终版本回归的19个（普通订阅8、TIMEOUT除04/05外9、WATCHTOWER-03/04）；沿旧#1674归因等待修复的TIMEOUT-04/05；已写但未执行的INVOICE-CANCEL-02（受与01相同的入口缺陷阻断）；未实现的WATCHTOWER-01/06及INVOICE-CANCEL-03（分别待独立收款支持和Received取消契约）。已批准的实测反馈候选方向不等于已实现用例；真正新行为须从该范围核对，不把上述旧回归包装成新覆盖。普通订阅8ID/11方法重新展开的Gate2暂缓，不作为下一批新增场景推进。

真实映射口径为73/76，未映射为WATCHTOWER-01/06及INVOICE-CANCEL-03。当时退款评审和自动化位于原仓库 `/Users/sunchengzhu/project/fiber-py-integration-test`，当时的工作树未包含它们（本次整合树已纳入）；项目检查器还会扫描report测试副本，导致退款孤儿映射提示。不能把单工作树扫描总数或旧正文中的40/74、44/74、47/74历史时点当最新结果，也不据此重跑已完成样本。原证据和各批历史结论保留。

候选12对应的[新增LSP-PAYMENT-04](../../../../reviews/lsp/delayed-payment-recovery.md#lsp-payment-04-gate2缺授权后的同进程恢复84333ee)已有自动化和TEST-MAP。最新192130批补入既有合约对齐调用，经GPT-6 Sol High复核后仅执行一次；pytest在setup_class的隔离路径断言报错（1 error in7.60s、exit1）即停。runner向预导入类设置路径，但pytest实际加载另一模块中的类，tmp_path_name仍为None；CKB已在默认tmp启动后才被断言拦下。未执行合约对齐、FNN初始化或任何付款/资金断言。属于本批执行准备错误，不能计产品业务失败或通过。见最新结果及目录隔离勘误（本地证据：`../../../../report/lsp-payment04-84333ee-20261030T192130/RESULT.md`）。旧批、旧19项版本回归及已知失败修复记录保留。

本目录使用真实 FNN、SDK 签名和 CKB devnet，验证 Hosted 通道、签名订阅（含浏览器鉴权）、重试/恢复、付款及超时行为。各批次的固定版本、覆盖边界和真实结果在下文分别记录，不把不同版本或不同范围的通过数合并为当前全量通过。watchtower 的隔离链合约预检阻断已解决；2026-10-27 的旧版02诊断曾独立复现陈旧首项遮蔽有效后继请求，显式批准后完整240s仍未恢复，后续#1706修复版定点回归另见上文及下文记录。

本文的运行结论随 Git 保存；标为“本地证据”的 `report/...` 路径均相对仓库根目录，原始报告、节点日志、失败数据和代码快照全部保留在本机，不随 Git 提交或推送。历史命令和退出码按当时执行情况保留；复现时使用新的输出目录，避免覆盖原始结果。

| 测试文件 | 场景 | 评审表 |
| --- | --- | --- |
| `test_channel_signing_isolation.py` | 单租户等待不阻塞另一租户；跨租户读取、提交被拒绝 | [LSP-SIGN-01～03](../../../../reviews/lsp/channel-signing-isolation.md) |
| `test_channel_signing_retry.py` | 相同、冲突、旧签名提交；请求断线、响应超时；支付只结算一次 | [LSP-RETRY-01～06](../../../../reviews/lsp/channel-signing-retry.md) |
| `test_channel_signing_recovery.py` | 正常开通→收款→协作关闭；SDK/FNN中途恢复；同通道十笔付款及后段恢复 | [LSP-RECOVERY-01～08](../../../../reviews/lsp/channel-signing-recovery.md) |
| `test_signing_subscriptions.py` | 当前工作补发、实时状态、租户及 host 范围、真实 SDK 重连、独立订阅与按连接取消 | [LSP-SUBSCRIPTION-01～07、10～13](../../../../reviews/lsp/signing-subscriptions.md) |
| `test_browser_signing_subscriptions.py` | 浏览器子协议鉴权、token 编码兼容、握手/RPC 拒绝及双租户隔离 | [LSP-SUBSCRIPTION-14～19](../../../../reviews/lsp/signing-subscriptions.md) |
| `test_signing_subscription_filters.py` | 默认/显式/空过滤、参数拒绝、不可见ID、256/257及固定数组兼容；843正式48/48通过 | [LSP-SUBSCRIPTION-20～28](../../../../reviews/lsp/signing-subscriptions.md) |
| `test_channel_signing_deadline.py` | 开通超时、支付截止保护、指定承诺强关及受控 B 败方恢复 | [LSP-TIMEOUT-01～08、10～12](../../../../reviews/lsp/channel-signing-deadline.md) |
| `test_delayed_payment_recovery.py` | 真实付款在在线延迟、SDK 完全离线和其他租户先结算后恢复 | [LSP-PAYMENT-01～03](../../../../reviews/lsp/delayed-payment-recovery.md) |
| `test_delivery_acceptance.py` | Hosted 接纳超时、原K重投与冲突的逐K资金一致性 | [LSP-DELIVERY-01～06](../../../../reviews/lsp/delivery-acceptance-consistency.md) |
| `test_hosted_invoice_cancellation.py` | 真实租户取消Open发票、跨租户隔离；Received契约待确认 | [LSP-INVOICE-CANCEL-01～03](../../../../reviews/lsp/hosted-invoice-cancellation.md) |

## 准备环境

以下命令从测试仓库根目录执行。已完成的 devnet 准备步骤可跳过；需要目标 Fiber 源码要求的
Rust 工具链和本机构建依赖，以及现有框架使用的 `lsof`。
本分支基于测试仓库 `v0.10.0` 的 `6088115`，沿用该版本的
`source/fiber/data.2026.0929.tar.gz` 链快照。

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m pip install -r test_cases/fiber/devnet/lsp/requirements.txt
venv/bin/python -m download
cp download/0.202.0/ckb-cli source/ckb-cli
```

以下命令准备默认/历史 `04c206465b48da85b99aa58e80afe9801a2cb2db` FNN、SDK agent 和本地 SDK 控制驱动。下文 `24b5c38` 的运行记录保留原版本，不能用此构建复现并仍标作旧版结果。首次准备源码目录：

```bash
git clone --no-checkout https://github.com/nervosnetwork/fiber.git download/fiber/source-pr-1623
git -C download/fiber/source-pr-1623 fetch origin pull/1623/head
git -C download/fiber/source-pr-1623 checkout --detach 04c206465b48da85b99aa58e80afe9801a2cb2db
venv/bin/python scripts/build_lsp_test_binaries.py --source download/fiber/source-pr-1623
```

也可将 `--source` 指向已有的同版本干净 checkout。产物、上游公开测试认证材料和构建清单放在
`download/fiber/pr-1623-04c2064/`，不提交到 Git；启动测试时会校验版本、二进制和驱动源码摘要。
构建入口先在300秒上限内用 `cargo fetch` 准备驱动的额外依赖，然后以 `--locked --offline` 编译；首次构建需要网络，不依赖开发者机器恰好已有完整缓存。

单独验证修复版本时，构建脚本可显式传 `--revision <完整 SHA>`，产物独立写入
`download/fiber/pr-1623-<SHA前7位>/`；可用 `--target-dir <目录>` 复用空闲的 Cargo 缓存。
运行普通 LSP 用例时仅在该命令设置 `LSP_TEST_REVISION=<同一完整 SHA>`，仍会严格检查构建清单与产物摘要。
不设置时继续使用 `04c2064`；不同版本的验证结果分别记录，不转记为当前 PR head 通过。
本次固定 `84333ee` 的独立批次通过显式完整 `--revision`、对应干净源码和独立匹配 bundle 运行，实际参数与产物摘要见各批次 `run.json`；不沿用上述默认04命令冒充843验证。
原 `download/fiber/pr-1623/` 中的 `24b5c38` 二进制、构建清单及历史运行证据继续保留；已有源码目录只在确认干净后切换，不能重克隆覆盖。
`_sdk_driver.rs` 只为 Python 提供真实 SDK 的授权、签名存储和恢复观察入口，不修改产品源码。
当前上游对 nonce 复用保留警告，功能测试通过不等于该安全问题已从根本修复。

## 运行本批 16 条

测试占用本地固定端口 8114、8125、8227～8230；专用 WS listener、各租户代理及控制端口动态分配。须串行运行，不能与其他使用同组端口的测试并发。
每条重新准备 Fiber 节点、租户及通道；进程恢复场景仅在该条用例内部复用原数据。
两个 FNN 使用独立数据目录同时启动，双方 RPC 就绪后才连接；公共节点在首次启动前配好 LSP。
节点准备和租户准备的实际耗时会输出到日志，便于定位后续变慢的步骤。
当前 `make fiber_test` 的目录列表尚不包含 LSP，使用下面的显式命令：

```bash
export PYTHONUNBUFFERED=1
export CKB_CLI_HOME="$(mktemp -d)"
mkdir -p report/lsp-core16
venv/bin/python -m pytest -vv -s --tb=short \
  test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_retry.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_recovery.py \
  --junitxml=report/lsp-core16/regression.xml \
  --html=report/lsp-core16/regression.html
```

以下三轮历史结果使用 FNN/SDK `8419c005`。
2026-10-20 在旧测试仓库基线 `v0.9.1 / 852c97d` 及最终驱动上实测：
`16 passed in 2643.36s`，退出码 0，无跳过。
2026-10-22 在 `v0.10.0 / 6088115` 基线上完整回归：`16 passed in 2579.42s`，无失败、错误或跳过。
优化 LSP 节点准备后，相同基线、FNN/SDK 和 16 条用例再次通过：`16 passed in 1473.33s`，
退出码 0，无失败、错误或跳过。整轮从 42 分 59 秒降到 24 分 33 秒，耗时减少约 43%。

2026-10-22 将 FNN、SDK agent 和测试驱动一起升级到 `4028884` 后，沿用原场景和断言回归：
先跑正常开通→收款→协作关闭，`1 passed in 112.12s`；再以
`-k 'not test_checked_open_pay_and_close'` 运行上述三个文件，`15 passed, 1 deselected in 1368.61s`。
两次退出码均为 0，合计 16 条全部通过，无失败、错误或跳过；排除项就是已单独通过的主流程。
总执行时间 24 分 41 秒，用例集合与上一轮相同。原始日志及 HTML/JUnit 报告位于
`report/lsp-core16-4028884-20261022/` 的 `smoke.*` 和 `regression.*`（本地报告不提交）。
这些是本批范围的执行结果，不代表整个 LSP PR 已验收。

## 通道签名订阅：迁移与执行结果

当前 `24b5c38` 的 [签名订阅用例](../../../../reviews/lsp/signing-subscriptions.md)已获人工确认；14 个方法位于 `test_signing_subscriptions.py`，对应 11 个 LSP-SUBSCRIPTION 行为，TEST-MAP 已同步。

先执行正常主流程，再执行订阅及受影响的重试/恢复；最后完整 LSP 目录的 40 条按以下顺序串行回归：

```bash
venv/bin/python -m pytest -vv -s --tb=short --durations=20 \
  test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_retry.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_recovery.py \
  test_cases/fiber/devnet/lsp/test_signing_subscriptions.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py \
  --junitxml=report/lsp-subscription-24b5c38/regression-final.xml \
  --html=report/lsp-subscription-24b5c38/regression-final.html
```

2026-10-23 在 `24b5c38` 同源 FNN/SDK/驱动上执行：主流程 `1 passed in 112.47s`、
聚焦订阅与恢复 `7 passed in 612.86s`，退出码均为 0。随后完整 40 条执行
`5 failed, 35 passed in 4152.55s`，退出码 1，无错误或跳过；其中核心 16/16、订阅 13/14、
既有 deadline 6/10 通过。原始日志、JUnit、HTML、退出码位于
本地证据 `report/lsp-subscription-24b5c38`
的 `smoke.*`、`focused.*`、`regression.*`。

首轮失败的完整节点数据另存于 `initial-failures/`，后续重跑不会覆盖它们。定位如下：

| 范围 | 定位与处理 |
| --- | --- |
| `LSP-SUBSCRIPTION-10` | 测试沿用的旧 Bruno operator token 缺少 `write("subscriptions")`，认证层直接返回 Unauthorized。已在本地驱动用公开 devnet 测试私钥签发具备 subscriptions 写权限、channels 读权限且无 tenant/node 身份的 host 凭据。首个复跑通过认证后又发现准备金额恰好等于自动接受门槛，辅助方法与节点对相等边界的判断不同，导致重复 accept；已仅将本用例改为严格高于门槛的金额，不触发额外付款。两次修复均保留原断言。 |
| `LSP-TIMEOUT-04/05` | 已知产品问题 [Fiber #1674](https://github.com/nervosnetwork/fiber/issues/1674)：180/60 秒配置正确，安装钱包签名后未重新安排普通期限；第 60 秒的旧检查被忽略且不重排，240 秒内未中止。05 失败于中止前提，尚未执行晚到签名。源码见 `channel.rs` 的 `post_start`、`install_external_funding_signed_tx`、`CheckFundingTimeout`；不延长等待或修改产品。 |
| `LSP-TIMEOUT-08/10` | 旧夹具的“A 必然先强关”假设失效：A/T 在同一 TLC 截止都尝试强关，本轮 T 的交易先确认，A 被 `RBFRejected`。对端关闭扫描周期为 300 秒，本例只等 60 秒，不能据此断言 A 永久卡死。即使复跑 A 获胜，也不能将这一不确定性记为修复；需要重新评审归因与夹具，当前不改为“任一方关闭即通过”。 |

上述 deadline 自动化和评审预期本次未改。它们保留在完整回归中，失败与已通过的订阅迁移分开交接。

operator 两项准备修复后，单条验证为 `1 passed in 97.26s`，退出码 0；见 `operator-fix2.*`。
此前的 Unauthorized 保留于 `regression.*`，重复 accept 的失败保留于 `operator-fix.*` 及
`operator-fix-data/`，不以修复后的结果覆盖它们。

修复后完整执行上述 40 条：**`2 failed, 38 passed in 4123.17s (1:08:43)`，退出码 1**，
无错误或跳过。核心 16/16、签名订阅 14/14 全部通过，既有 deadline 8/10 通过。
最终 HTML 报告（本地证据：`report/lsp-subscription-24b5c38/regression-final.html`）、
JUnit（本地证据：`report/lsp-subscription-24b5c38/regression-final.xml`）、
原始日志（本地证据：`report/lsp-subscription-24b5c38/regression-final.log`）及 `.exit` 均已保存。

最终仅 `LSP-TIMEOUT-04/05` 失败，均为 240 秒内未中止；节点数据保存在 `final-failures/`。
`LSP-TIMEOUT-08/10` 本轮通过，但自动化未修改，首轮双方强关竞争的风险仍在，不能宣称已修复或稳定通过。
修复这个归因问题需要重新设计能区分两方保护的夹具，不能通过放宽为任意关闭交易来满足原有预期。

本轮 FNN 付款重启的故障切断阶段出现一次 WebSocket 库内部 `EOFError: stream ended` 日志；
随后新订阅、完整待签交付、付款终态及清理均通过。该日志与底层库关流竞态一致，未作为业务失败或通过依据。
FNN 产品源码未修改，原有 deadline 测试与无关本地改动保留。测试结束后进程及固定端口已清理。

GPT 6.1 sol 已独立复核最终代码、同源构建摘要、TEST-MAP 及实际日志/JUnit/退出码：
本批核心和订阅 30 个方法无剩余代码阻塞；确认完整目录仍有上述 2 个产品失败，
且 08/10 的首次竞争风险不能因本轮通过而消除。

## 24b5c38：开通超时失败与强关不稳定的复现证据

### 已知问题关联：#1674

`LSP-TIMEOUT-04/05` 归入已有
[Fiber #1674：External funding: ordinary opening timeout is not scheduled after signed submission](https://github.com/nervosnetwork/fiber/issues/1674)。
该 issue 由 sunchengzhu 于 2026-09-29 提交，2026-10-23 经 GitHub API 核实时仍为 Open。
[原问题记录](../../../../docs/analysis/issue-external-funding-open-timeout-after-signed-submission.md)在正式 v0.9.1 上通过暂停对端复现；
本轮在 `24b5c38` 的 Hosted LSP 待通道签名阶段复现，均为钱包签名提交后缺少普通开通期限检查的同一根因。
05 被阻塞在中止前提，尚无迟到签名处理另有缺陷的证据；08/10 的双方强关竞争不属于此 issue。

后续会话先核对本节证据、issue 进展与实际目标 SHA。相同版本和失败特征沿用 #1674 的归因及留档，
避免重复建 issue 或为重复定位而重跑；目标版本、修复状态或失败特征变化时，再做针对性验证。
保留既有测试预期和真实失败记录，不能因已有 issue 将失败记为通过，也不能把此处历史 Open 状态当作实时状态。

以下仅分析固定提交 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3` 的两轮现有结果；
本次整理没有重新启动节点，没有修改产品、测试输入或断言。A 是 Hosted 租户，T 是公共 LSP，
两侧通道 actor 位于同一个 FNN 进程；不要把普通节点 P 当成此处参与强关竞争的 T。
下表及时间线使用 **2026-10-23 北京时间（Asia/Shanghai）**；节点日志的 `Z` 时间为 UTC，需要加 8 小时。

| 用例 | 首轮 `regression.*` | 最终轮 `regression-final.*` | 当前结论 |
| --- | --- | --- | --- |
| `LSP-TIMEOUT-04` | 等待中止失败 | 同样失败 | 外部注资完成后的普通开通计时器调度缺口 |
| `LSP-TIMEOUT-05` | 等待中止失败 | 同样失败 | 与 04 共因；尚未执行晚到通道签名提交 |
| `LSP-TIMEOUT-08` | A 的强关交易未确认 | 通过 | 两方强关竞争；原夹具不能保证 A 的承诺获胜 |
| `LSP-TIMEOUT-10` | A 的强关交易未确认 | 通过 | 同上；本轮通过没有消除首轮暴露的风险 |

### 04/05 的复现入口和具体步骤

完成前文环境准备，确认 FNN/SDK/驱动版本及摘要匹配，并确保固定端口空闲后，从仓库根目录串行运行：

```bash
export PYTHONUNBUFFERED=1
export CKB_CLI_HOME="$(mktemp -d /tmp/lsp24-ckb-cli.XXXXXX)"
lsp_repro_dir=$(mktemp -d "$PWD/report/lsp-timeout-repro.XXXXXX")
venv/bin/python -m pytest -vv -s --tb=short \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_opening_signature_timeout_aborts_before_broadcast \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_late_channel_signature_after_abort \
  --junitxml="$lsp_repro_dir/result.xml" \
  --html="$lsp_repro_dir/result.html" > "$lsp_repro_dir/run.log" 2>&1
lsp_exit=$?
printf '%s\n' "$lsp_exit" > "$lsp_repro_dir/result.exit"
```

这是复用已有测试的复现命令，本次未另跑这一条命令；两轮完整回归均已实际执行这两个方法。
新报告目录不会覆盖上述留档，框架仍会使用正常的 `tmp/` 测试目录，因此不要并行运行。

1. 启动启用 LSP 的真实 FNN 和 SDK，配置 `funding_timeout_seconds: 180`、
   `external_funding_timeout_seconds: 60`。通过 SDK 开通 A–T 私有 CKB 通道，取得未签外部注资交易。
2. 在 60 秒内调用 `sign_external_funding_tx` 签署钱包交易，再由所属租户调用
   `submit_signed_funding_tx`。此步骤提交的是钱包注资签名，不是后续的通道承诺签名。
3. HTTP gate 截获真实 SDK 生成的 `submit_channel_signature`，保存完整提交但不向 FNN 转发。
   SDK 用 `--ack-held-events` 确认暂停事件并保持订阅；查询须仍为 `SignatureRequired`，
   且请求 ID 与保存提交一致。测试期间不重启 FNN/SDK、不提交这份通道签名。
4. 每秒调用 A 的 `list_channels({"only_pending": true})`，等待目标通道出现
   `Closed | FUNDING_ABORTED`，最多等待 240 秒。普通期限应从通道 `created_at` 起算 180 秒，
   **不是钱包提交后再算 180 秒**。
5. 04 原本还应检查中止时间、注资未上链、原输入仍为 live、T 侧也已中止；
   05 原本应在中止后直连提交保存的旧通道签名，验证不返回 `Applied`、通道不复活、原输入仍未花费。
   两轮实际都在第 4 步失败，以上后续断言均未到达。

实现入口为 [配置与等待](test_channel_signing_deadline.py)第 30～89 行、
[04/05 方法](test_channel_signing_deadline.py)第 480～508 行，以及
[真实钱包提交与待签检查点](_lsp_test.py)第 339～440 行。

### 04/05 的源码闭环

| 源码位置（固定 SHA） | 与失败的关系 |
| --- | --- |
| [`post_start`，channel.rs:5301](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L5301) | actor 启动时仍等待外部注资，安排外部期限检查；此路径不会同时安排普通 180 秒检查。 |
| [`install_external_funding_signed_tx`，4047](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L4047) | 钱包签名安装后置 `signed_submitted = true`、清空外部阶段起点并保存状态；没有安排普通开通期限检查。 |
| [`can_abort_funding_on_timeout` / `has_funding_timeout_elapsed`，11764](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L11764) | 日志中的 `CollaboratingFundingTx`、`SigningCommitment` 都允许超时中止；已提交外部钱包签名后，适用期限切换为 `created_at + funding_timeout_seconds`。 |
| [`CheckFundingTimeout`，4404](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L4404) | 约第 60 秒收到旧检查，此时普通 180 秒未到，进入 `Ignore stale funding timeout check` 分支；该分支只记录日志，没有重新调度。 |
| [`schedule_timeout_event`，4438](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L4438) | 使用一次性 `send_after` / `send_message`；旧检查被忽略后不会自动再来一次。周期 TLC 维护也不替代开通期限检查。 |

因此缺失的是**阶段切换后的普通期限检查事件**。源码路径与两轮观察共同支持这个判断；
不是仅从一次 `None` 推断产品问题，也不是多等几秒就能补足的 180 秒预算问题。
现有执行只证明 240 秒观察窗口内未中止，不把它夸大为已实测无限期等待。

### 04/05 的最终轮日志时间线

04 的完整 channel ID 为 `0x4b4a9049559ade527786d9c9131d5fbcbb927c6576ad78a7f789ac20a4c2d628`；
05 为 `0xd5c6a48629b42854501b93821846e8408aabff79ac51b56c27b157b8ad233cbd`。
对应证据分别保存在
04 节点日志（本地证据：`report/lsp-subscription-24b5c38/final-failures/test_opening_signature_timeout_aborts_before_broadcast/fiber/node1/node.log`）与
05 节点日志（本地证据：`report/lsp-subscription-24b5c38/final-failures/test_late_channel_signature_after_abort/fiber/node1/node.log`）。

| 观察点 | 04（北京时间） | 05（北京时间） | 两份 node.log 的行号 |
| --- | --- | --- | --- |
| 创建日志 | 11:25:28.861850 | 11:14:20.818880 | 146；最终 ID 创建在 190、迁移在 213 |
| 钱包签名验证成功 | 11:25:29.080694 | 11:14:21.047455 | 583 |
| 对端同步签名后的注资交易 | 11:25:29.083079 | 11:14:21.049863 | 599 |
| 旧检查被忽略 | 11:26:28.866～11:26:29.025 | 11:15:20.820～11:15:20.984 | 629、633、637、641 |
| 失败后的清理断开 | 11:29:30.476678 | 11:18:22.451290 | 715，原因为 `PeerDisConnected`，不是 `AbortFunding` |

创建日志只是时间参照，不冒充未打印的 `created_at` 字段。两次清理距创建日志约 241.6 秒。
留档发生在清理之后；断开连接也可能留下失败开通记录，不能把清理后的 `Failed` 或合成的
`FUNDING_ABORTED` 反过来当作 180 秒超时已触发的证据。
对应 04 配置（本地证据：`report/lsp-subscription-24b5c38/final-failures/test_opening_signature_timeout_aborts_before_broadcast/fiber/node1/config.yml`）及
05 配置（本地证据：`report/lsp-subscription-24b5c38/final-failures/test_late_channel_signature_after_abort/fiber/node1/config.yml`）第 2～3 行均确为 180/60；
各自 `sdk-A/agent.log` 第 1 行记录 `saved signature held by test; subscription stays connected`。
最终失败栈（本地证据：`report/lsp-subscription-24b5c38/regression-final.log`）第 2152～2166 行均为：

```text
_wait_abort(timeout=240)
AssertionError: opening was not aborted within 240s: None
```

这里的 `None` 是测试没有筛到 `Closed | FUNDING_ABORTED`，**不表示 RPC 返回空列表**。
[`list_channels`，rpc/channel.rs:526](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/rpc/channel.rs#L526)
会查询失败开通状态；第 601～643 行还会从 actor 已删除的失败开通记录合成 `FUNDING_ABORTED`。
同轮外部注资超时 01 也使用这一等待方法并通过，因此没有证据支持换查询选项就能修复 04/05。

### 08/10 为什么首轮失败、最终轮通过

两条都注入短期限 TLC（22 秒，debug 构建的安全预留约 1333 毫秒），但检查点不同：
08 停在承载 TLC 的签名尚未应用时，A 可用承诺仍不含目标 TLC；10 已完成含 TLC 的承诺签署，
扣住下一份撤销签名。两条都要求 A 的特定已签承诺最终确认，随后还要验证各自的业务结果。

当前 [`signature_tlc_deadline_reached`，channel.rs:6582](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L6582)
允许“正在等待外部签名 **或** 属于 internal channel”触发 TLC 截止保护。
[`is_internal_channel`，store_impl/mod.rs:1067](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/store/store_impl/mod.rs#L1067)
将 T 对 Hosted A 的通道判为 internal，A 的 namespaced store 则返回 false。
结果是 A 因待签请求触发保护，T 即使不等待外部签名，也能对同一 TLC 截止触发保护。
[`channel_activity_timed_out`，6675](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L6675)
还排除了 internal 通道的普通 ACK 超时，因此原先用“早于 30 秒”来排除 T 强关的依据不成立。

首轮证据：

| 用例 | T 的关闭交易 | A 的关闭交易 | 原始证据 |
| --- | --- | --- | --- |
| 08 | `0x1344fe92f2fedf0a6bb43028f541d41a2851fa7e6bac18b05dd871279e84a1da`，区块 2156 确认 | `0xf55e672955f3628167153049357a294d188b1e11465283d859681306da93e53f`，`RBFRejected` | node.log（本地证据：`report/lsp-subscription-24b5c38/initial-failures/test_node_protects_without_any_submission/fiber/node1/node.log`）第 1069、1077 行；北京时间 03:08:02.870 |
| 10 | `0xd25a82d4626a1ac4faeb42db12a541e1af9cddaf0fa65de06afc193e7635d741`，区块 1377 确认 | `0x6f7e93af991cb99440b62e62bbfb00183e6febc29ac47ec048f4be416079932e`，`RBFRejected` | node.log（本地证据：`report/lsp-subscription-24b5c38/initial-failures/test_force_close_uses_commitment_with_target_tlc/fiber/node1/node.log`）第 1057、1065 行；北京时间 02:55:56.861 |

两次拒绝的原始原因相同：

```text
RBF rejected: Tx's current fee is 457, expect it to >= 1142 to replace old txs
```

457 是 A 交易的当前手续费，1142 是替换所需下限，不是 T 的实际手续费。
08 的日志第 961、977 行显示 A/T 分别在 03:07:54.863412 / 03:07:54.866276 触发安全截止。
10 的日志第 961、977 行显示 A/T 分别在 02:55:52.796730 / 02:55:52.799879 触发安全截止，
只相差约 3 毫秒。A 先触发保护也不保证先入池；两份关闭交易花费同一注资输出，
首轮 T 的交易先被接受，A 的交易又不满足替换费用要求。这些证据指向交易竞争，不是 SDK 签名校验失败，
也不是 CKB 没有挖块。

失败时 [测试 `_confirm_force_close`](test_channel_signing_deadline.py)第 342～362 行只等待 A 侧关闭哈希，
确认窗口为 60 秒；而 [`CHECK_CHANNELS_SHUTDOWN_INTERVAL`，network.rs:256](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs#L256)
是 300 秒，Hosted 网络也在第 9129 行注册此周期检查。第 3123 行扫描 `ShuttingDown` 通道，
[第 4860～4905 行](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs#L4860)
具备识别对端承诺确认的路径。故本次短窗口内 A 仍为 `WAITING_COMMITMENT_CONFIRMATION`，
**不足以证明 A 永久卡死**；实际跨过该周期后的结果未在这两条失败中验证。

延长等待即使能识别 T 的交易，也不等于原行要求的“A 的已签承诺确认”。测试第 388 行还会比对
确认交易的 canonical signing message 与 SDK 保存的 A 承诺；不能把“任意一方关闭”替换成原预期。
另外，第 391～393 行要求两侧关闭哈希不同也不适合作为发起方证明：
[`update_close_transaction_confirmed`，channel.rs:11710](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs#L11710)
会记录实际确认交易哈希，双方最终可能观察到同一交易。本轮两条实际失败在确认等待阶段，尚未走到此额外断言。

最终轮 08/10 均为 PASS（日志（本地证据：`report/lsp-subscription-24b5c38/regression-final.log`）第 1716～1717、1930 行），
期间没有修改 deadline 测试或产品。正确结论是原夹具无法稳定排除双方竞争，不能把这次通过记为修复。
这只解释了失败的直接原因，**尚不能排除 A 交易被拒后无法正确识别对端关闭的产品缺陷**，该恢复路径未在失败窗口内验证完成。
后续明确区分“A 已启动保护”“哪方承诺实际确认”“对端关闭如何被识别”；
[08/10 稳定性改造 Gate1](../../../../reviews/lsp/channel-signing-deadline-scope.md#0810-稳定性改造范围)与 [Gate2 完整用例及共同断言](../../../../reviews/lsp/channel-signing-deadline.md)均已获用户确认，本轮 Gate3 已完成。Python 已接入广播隔离；前述旧两轮结果不作为新版通过证据，本轮运行在下一节单独留档。自然竞争后败方的恢复仍是未排除的产品疑点。

## 08/10 广播隔离 Gate3 验证（24b5c38）

2026-10-23，按用户已确认的两条用例与共同断言，仅改造 `LSP-TIMEOUT-08/10`。原 TEST-MAP ID 与评审复选框保留，映射现在对应新的输入、步骤和断言；其他超时方法的行为未变。
只有这两条在独立环境中启用 `_commitment_broadcast_gate.py`；A/T 当前承诺分别唯一绑定到 SDK 记录，A 原始交易转发真实 CKB，T 的匹配交易返回明确测试注入错误，未知目标交易使测试失败。先停本条矿工，取得 A 真实接受及 T 实际拦截两项证据后才恢复挖块，再验证确认交易、注资输入、本地强关记录及各自业务结果。

FNN/SDK/驱动继续使用 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`，构建清单及驱动源码摘要由每次测试启动校验；源码 checkout 干净，无产品修改或重新构建。CKB 为随包 `0.202.0`，沿用 `data.2026.0929.tar.gz` 和当前合约模板，未据此推断新的 fiber-scripts 提交。

本轮记录位于 lsp-timeout-isolation-24b5c38.bi2JVH（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH`）。每次运行的 `.log`、`.xml`、`.html`、`.exit` 独立保存；同名子目录按方法保存 `evidence.json` 与 FNN/SDK/CKB 日志，成功与失败均留档。没有把旧的 `report/<test_method>` 目录当本轮成功证据。

| 批次 | 实际结果 | 退出码 | 原始输出 |
| --- | --- | --- | --- |
| 首次 08 聚焦 `focus08` | `1 failed in 105.00s`：CKB 已花费 cell 返回 unknown，测试错误要求 dead | 1 | 日志（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/focus08.log`） |
| 修正后聚焦 `focused` | `2 passed in 225.19s` | 0 | 日志（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/focused.log`） |
| 固定复跑第 1 轮 `stability-1` | `2 passed in 221.74s` | 0 | 日志（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/stability-1.log`） |
| 固定复跑第 2 轮 `stability-2` | `2 passed in 221.87s` | 0 | 日志（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/stability-2.log`） |
| 固定复跑第 3 轮 `stability-3` | `2 passed in 225.72s` | 0 | 日志（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/stability-3.log`） |

修正后的聚焦与固定复跑合计 **8/8 通过**：每条 1 次聚焦加 3 次固定复跑，各批退出 0、无跳过；复跑之间没有修改测试代码。最初 1 次测试断言错误另行保留，不计作成功。结束后固定测试端口无监听，未发现遗留 FNN/CKB/SDK 进程，产品源码仍干净。本轮不是完整 LSP 目录回归。

GPT 6.1 sol 已在全部运行结束后独立复核最终代码、各批退出码/JUnit 和 8 份成功证据，无阻断项。逐份确认 A 真实接受、T 实际拦截、承诺与 funding 匹配、真实确认、本地关闭及门禁无错误；08 的晚到拒绝后稳定观察为 5.022～5.033 秒，10 的最终 Open 查询均距发票到期约 145 秒。A 首次广播在 D 后 0.653～2.665 秒，确认距首次转发 4.135～4.483 秒，本地关闭距确认 4.768～8.040 秒，均在批准预算内。独立复核未把这批结果扩展到自然竞争恢复。

首次失败属于测试对 RPC 状态语义的错误理解：CKB 0.202.0 官方随包文档（本地参考：`download/0.202.0/docs/rpc.md#type-cellwithstatus`）明确 `dead` 已弃用，`unknown` 包含已不再 live。修正保留完整证明链：准备时同一 funding 为 live；A 的实际广播获得真实 hash；该 hash 的真实确认交易花费同一 funding；规范化消息匹配 A 的指定完整承诺且区别于 T；最后检查 cell 不再 live（dead/unknown 且 cell=null）。不是仅以 unknown 证明花费。首次失败时已到达 committed 与输入检查，后续承诺匹配、本地关闭及晚到提交尚未执行；完整结果以修正后的运行认定。

实际使用的 pytest 入口如下；聚焦通过后冻结代码，额外执行固定 3 轮，每轮两条串行，任何失败即停止定位，不重跑掩盖失败。每轮设置独立的 `LSP_DEADLINE_ARTIFACTS`、日志和报告路径；以后复现时另建批次目录，保留上述原始报告：

```bash
export PYTHONUNBUFFERED=1
export CKB_CLI_HOME="$(mktemp -d /tmp/lsp-timeout-ckb-cli.XXXXXX)"
lsp_run_name=stability-1
export LSP_DEADLINE_ARTIFACTS="$PWD/report/lsp-timeout-isolation-24b5c38.bi2JVH/$lsp_run_name"
venv/bin/python -m pytest -o addopts= -vv -s --tb=short --durations=5 \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_node_protects_without_any_submission \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_force_close_uses_commitment_with_target_tlc \
  --junitxml="$LSP_DEADLINE_ARTIFACTS.xml" --html="$LSP_DEADLINE_ARTIFACTS.html" \
  > "$LSP_DEADLINE_ARTIFACTS.log" 2>&1
```

静态检查：两文件 `py_compile`、`git diff --check` 退出 0；`python3 scripts/check_test_map.py` 退出 1，仍为既有全仓孤儿映射和历史 report overlay 的重复 ID；`check_test_design.py --review reviews/lsp/channel-signing-deadline.md` 识别 10 条，退出 1，同样报告历史重复 ID，并列出刻意保留的 SPEC-09 恢复预期待确认项。检查原始输出（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/test-map.log`）与设计检查（本地证据：`report/lsp-timeout-isolation-24b5c38.bi2JVH/test-design.log`）均保存实际退出码，不把全仓检查写成通过。

该轮结束时，自然竞争后 A 的关闭交易被真实 RBFRejected、T 获胜后的关闭识别与收敛仍待单独核实，不能凭隔离结果排除 Fiber 产品 bug。后续独立诊断见下一节。此次隔离验证也不覆盖 watchtower 结算或链上资金取回；04/05 的已知 #1674 不在本轮重跑范围。

## 24b5c38 自然竞争后的恢复诊断（2026-10-23）

**本批结论：检查点 A 已实测自动恢复，未出现“A 被真实 RBF 拒绝后永久卡死”。** T 确认后首次采样恢复约 264.6 秒，完整观察 331.8 秒；此前 60 秒窗口不足以判断产品恢复失败。本批检查点 B 的三次无额外时序控制的竞争均由 A 获胜，未取得 B 的 T 获胜分支；后续受控时序复现及 330 秒观察见下节。旧 08/10 要求 A 指定承诺确认，仍需保留已批准的广播隔离设计，不能改为任意赢家即通过。

用户另行授权保留 A/T 竞争，复现 T 获胜、A 真实 RBFRejected，并从 T 确认起观察 300 秒扫描周期加 30 秒余量。
本节是独立诊断，不能用前节广播隔离的 8/8 代替，也不改变已确认的 `LSP-TIMEOUT-08/10`、TEST-MAP 或用例表。
使用同一 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3` FNN/SDK/驱动构建；启动时验证构建清单、二进制哈希及版本。
Python 诊断入口为 [diagnose_competing_close.py](diagnose_competing_close.py)，明确指定方法才运行；没有修改产品代码。

### 复现条件与观察方式

1. 使用原 LSP pytest 基类建立真实 Hosted A—公共 LSP T 通道，保持双方进程与挖块运行。
2. 创建 hold invoice，注入 22 秒 TLC，保留原安全截止 `D = expiry - 1333 ms`。检查点 A 扣住含 TLC 承诺的签名；检查点 B 应用该签名后扣住 `SendRevokeAndAck`。两者分别对应旧 08/10 的竞争位置。
3. 在 D 前保存唯一 SDK A/T 承诺记录、各自 canonical signing message 与 funding outpoint。发票有效期为 600 秒，避免诊断窗口中无关到期干扰；不提交 preimage。
4. 链 RPC 观察代理永不 `arm()`，双方交易原样送真实 CKB，保存请求和原始响应；canonical 分类在转发后进行，不延迟特定一方，不注入拒绝，不停矿、不手动强关、不重启、不在准备完成后提交签名。
5. 要求 T 实际 `committed` 且输入精确花费该 funding，同时 A 的匹配承诺收到真实 CKB `-1111 / PoolRejectedRBF`，`data` 含 `RBFRejected`。A 自然获胜时记为“未取得目标场景”，保存非零退出码，不记为恢复通过；B 获取上限固定为三次。
6. 从首次查到 T 已确认起，用单调时钟观察至少 330 秒，每约 2 秒保存 A/T 状态、签名状态、真实交易、链 tip 与索引器 tip；即使提前恢复，也继续到窗口结束。检查 A 自动变为 `Closed/UNCOOPERATIVE_REMOTE`、关闭哈希等于 T 的真实交易且 `NoSignatureRequired`，结合 HostedTenant 日志确认恢复来源。

仓库根目录复现命令（目录必须尚不存在；复现 B 时将检查点改为 `B`，并为 artifacts 与 XML 使用独立路径，串行运行）：

```bash
LSP_NATURAL_ARTIFACTS=report/lsp-natural-repro-A \
LSP_NATURAL_CHECKPOINT=A \
venv/bin/python -u -m pytest \
  test_cases/fiber/devnet/lsp/diagnose_competing_close.py::TestNaturalCompetition::test_observe_competing_close \
  -v -s -o addopts= --junitxml=report/lsp-natural-repro-A.xml
```

### 本轮原始记录

| 批次 | 真实竞争结果 | 确认后观察 / 首次采样恢复 | pytest 原始结果 |
| --- | --- | --- | --- |
| A1（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-A1/evidence.json`） | T 确认；A 真实 RBFRejected；最终 A 远端关闭，双方关闭哈希相同 | 331.792 秒 / 264.613 秒 | 日志（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-A1.log`）：`1 passed in 437.67s`；退出码（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-A1.exit`） 0 |
| B1（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B1/evidence.json`） | A 自然获胜，未取得目标场景；未运行 330 秒恢复观察 | 不适用 | 日志（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B1.log`）：`1 failed in 103.80s`；退出码（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B1.exit`） 1，失败原因为 `scenario_not_acquired_A_won` |
| B2（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B2/evidence.json`） | A 自然获胜，未取得目标场景；未运行 330 秒恢复观察 | 不适用 | 日志（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B2.log`）：`1 failed in 103.58s`；退出码（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B2.exit`） 1，失败原因为 `scenario_not_acquired_A_won` |
| B3（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B3/evidence.json`） | A 自然获胜，达到三次获取上限；未运行 330 秒恢复观察 | 不适用 | 日志（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B3.log`）：`1 failed in 105.96s`；退出码（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B3.exit`） 1，失败原因为 `scenario_not_acquired_A_won` |

A1 的关键证据（时间为北京时间）：

- T 实际关闭交易 `0x4db883924e1fb44c0b2853f06c325aa21b608169e84f77d13147968c9a228a9e`，在区块 1255（`0x4e7`）确认；其输入花费 `0xddcf39ad3c644205e9e485ecb8c351e1f3bca6bb5600c8280fa370a88b5ac62b:0`。首次观察确认时间 18:22:25.497，见 observations.jsonl（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-A1/observations.jsonl`） 第 13、16 行。
- A 实际广播交易 `0x83a426178a51cc581bcc4a69e07abdd0162fc29f34201a6fbfde4ea3eaa78fc4` 被真实 CKB 拒绝：`Tx's current fee is 457, expect it to >= 1142 to replace old txs`。原始响应在 observations 第 14 行；fnn.log（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-A1/fnn.log`） 第 1077、1081、1089 行记录其 rejected/ClosingTransactionFailed。
- 18:26:49.115 的精确 funding lock 索引查询返回 T 的 input 交易，随后读到真实 committed，见 fnn-chain-reads.jsonl（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-A1/fnn-chain-reads.jsonl`） 第 104～105 行。
- 18:26:49.129，fnn.log 第 1201～1211 行明确属于 **HostedTenant A / actor 0.12**：先 `is shutdown by remote`，随后从 `ShuttingDown(WAITING_COMMITMENT_CONFIRMATION)` 转为 `Closed(UNCOOPERATIVE_REMOTE | WAITING_ONCHAIN_SETTLEMENT)`。不是 watchtower 的 `PeriodicCheck` 日志。
- 首次状态采样确认恢复在 18:26:50.160，即确认后 264.613 秒；至 18:27:57.337 结束，恢复后 34 个采样全部保持完整恢复条件，无回退。176 个总采样最大间隔约 2.129 秒；链高由 1230 增至 1584，最终索引器同步至 1584。代理 `armed=null`、`errors=[]`，没有拦截事件。

GPT 6.1 sol 已独立核对 A1 的原始交易、SDK 规范消息、真实拒绝、完整窗口和 Hosted A 扫描恢复，并最终复核 B1/B2/B3 的未取得场景记录及四处文档，未发现阻断项。三次 B 的非零退出没有被记为产品失败或恢复通过。
A1 启动后诊断脚本补强了最终状态断言、`-1111` 识别和唯一记录检查；不宣称 A1 执行了后补代码。其原始响应本已含 `RBFRejected`，独立复核从保存的完整采样补验了最终状态与恢复后无回退，未放宽业务判断。

### 源码为什么表现为“先失败，过几分钟恢复”

- [channel.rs:2733～2748](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs) 广播当前完整承诺并进入 `WAITING_COMMITMENT_CONFIRMATION`；[in_flight_ckb_tx_actor.rs:358～373](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/in_flight_ckb_tx_actor.rs) 对真实拒绝发 `ClosingTransactionFailed` 并结束该交易跟踪。
- [network.rs:2514～2520](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs) 处理失败时只移除 tracer 并记录日志，不立即更改通道状态或查询 T 的关闭。第 256 行规定关闭扫描间隔 300 秒；Hosted A 在第 9125～9131 行注册自己的周期扫描。
- network.rs 第 3123～3145 行明确把 `ShuttingDown(..)` 纳入扫描；[ckb/client.rs:187～215、321～334](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/ckb/client.rs) 按 funding lock 精确查询 input 花费，再取得完整关闭交易。
- network.rs 第 4860～4906 行确认交易 committed、单输出及远端承诺锁匹配后发送 `ClosingTransactionConfirmed(force=true, close_by_us=false)`；channel.rs 第 11716～11747 行把 A 改为远端强关并记录 T 的真实 hash。周期是从 actor 启动计时，故不必恰好在 T 确认后第 300 秒恢复。

Watchtower 也会发出相同 funding lock 查询，单看查询不能判定 A 已扫描；上述 HostedTenant 识别日志、随后的远端关闭状态和真实 T hash 构成完整证据。
这次诊断只判断关闭识别和状态收敛；`WAITING_ONCHAIN_SETTLEMENT` 仍存在，不代表 watchtower 结算或资金取回完成。`LSP-TIMEOUT-04/05` 的已知 #1674 未由此消除。

静态验证：诊断脚本 `py_compile`、`git diff --check` 均退出 0；源码 checkout 仍干净并位于固定提交。
`python3 scripts/check_test_map.py` 退出 1（原始输出（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/test-map.log`）），报告既有孤儿映射及历史 report overlay 重复 ID；本轮未增删映射。
`check_test_design.py --root <本仓库> --review reviews/lsp/channel-signing-deadline.md` 退出 1（原始输出（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/test-design.log`）），识别 10 条，仍报告历史重复 ID 和明确保留的 SPEC-09 正式恢复回归待评审项。不能把这两个全仓检查写成通过。

## 24b5c38 检查点 B 的竞争与恢复诊断续查（2026-10-23）

用户进一步授权先分析前三次 A 获胜，再取得 B 的 T 获胜/A 真实 RBF 场景并观察完整扫描窗口；仍不改产品代码、不屏蔽任何一方广播。
本节单独记录受控 RPC 时序复现，与前节无额外延迟的自然采样分开；正式 `LSP-TIMEOUT-10` 的广播隔离断言及 TEST-MAP 不变。

### 前三次为什么都是 A 获胜

前三次的原始代理记录显示 A 均先进入真实 CKB，T 也确实发送，但后来者不满足 RBF 替换费用要求。时间为北京时间：

| 原批次 | A 比 T 早触发保护 | A 请求到达链代理 | T 请求到达链代理 | 实际结果 |
| --- | --- | --- | --- | --- |
| B1 | 5.363 ms | 18:30:01.655 | 18:30:01.665 | A 先接受；T 真实 -1111/RBFRejected |
| B2 | 3.931 ms | 18:32:15.672 | 18:32:15.680 | A 先接受；T 真实 -1111/RBFRejected |
| B3 | 5.818 ms | 18:34:31.728 | 18:34:31.738 | A 先接受；T 真实 -1111/RBFRejected |

原始数据分别见 B1 evidence（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B1/evidence.json`）、B2 evidence（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B2/evidence.json`）、B3 evidence（本地证据：`report/lsp-natural-24b5c38.8Z1lDd/attempt-B3/evidence.json`） 的 `broadcasts.events`，以及对应 `fnn.log` 的第 961/973/957 行起的双方保护日志。
三次 A 的发送均领先 T 8～10 ms；原始拒绝响应均为手续费 457、替换至少要求 1142，不能解释为 T 没有参与竞争，也没有证据支持 B 必然由 A 获胜。

源码和旧反例解释了为什么“先触发”不保证“先入池”：

- [channel.rs:5291～5298](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/channel.rs) 为每个 ChannelActor 单独注册维护定时器；[network.rs:250～254](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/network.rs) 在本次 debug 构建中每 3 秒检查。前三轮 A 实际稍早触发是定时相位证据，不是规定 A 优先的仲裁规则。
- channel.rs 第 11635～11647 行构造强关承诺时异步刷新 deps；两个独立 InFlight actor 又分别在 [in_flight_ckb_tx_actor.rs:239](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/fiber/in_flight_ckb_tx_actor.rs) 等待 `get_transaction`，随后才在第 263 行向共享 chain actor 发 `SendTx`。这些异步等待允许顺序反转。
- [ckb/actor.rs:303～310](https://github.com/nervosnetwork/fiber/blob/24b5c38bc098aeb29de5f6af7ac28dc667f218e3/crates/fiber-lib/src/ckb/actor.rs) 在共享 actor 内等待真实 `send_transaction`，实际发送串行。第 323～330 行还把 `-1111` 和重复交易一起打印为 `already in pool`，该日志不能单独证明接受；本次以原始 CKB 响应和真实链确认判定。
- 旧 10 的 T 获胜日志（本地证据：`report/lsp-subscription-24b5c38/initial-failures/test_force_close_uses_commitment_with_target_tlc/fiber/node1/node.log`） 第 961/977 行中 A 仍先触发约 3.149 ms，第 1021/1041 行 A 也先进入 `Executing send_tx`，但第 1049 行先接受的是 T，第 1065 行明确 A `Rejected(RBFRejected)`。反转与异步查询后进入共享邮箱的路径吻合；旧样本未捕获原始查询时序，不能声称已证明是哪次查询造成反转。

### 本次如何保留真实竞争并取得相反顺序

仅在手动诊断中设置 `LSP_NATURAL_DELAY_A_PREFLIGHT=1`，对 A 实际关闭哈希的首次 `get_transaction` 响应开启一次固定 **250 ms** 窗口。以目标 channel ID 和 T 公钥匹配 FNN 的既有 `Spawning InFlightCkbTxActor ... Closing` 日志，唯一确定 A 的实际哈希；真实广播后再以 SDK canonical message 独立验证 A/T 身份，并检查 B 的完整 A 承诺包含准确的目标 TLC 与 expiry。

同一 A 哈希还会被 tracer 并发查询，因此窗口内的匹配 unknown 响应统一等到同一个固定释放时间，全部保存真实响应及接收、上游返回、释放时间。等待不持代理共享锁，不阻塞 T，也不发生在共享 `SendTx` handler 内。窗口固定到时释放，不等待 T 接受/确认、不延续到恢复阶段；所有 `send_transaction` 均原样转发，无测试注入错误。

这会控制一次查询返回顺序，因此称为**受控时序复现**，不宣称无干预自然获胜。仍要求 T 真实 committed 且精确花费 funding、A 真实 RBFRejected，以及所有延迟早于 T 确认结束；A 必须真实发送，不能以迟迟未广播替代败方。随后持续至少 330 秒观察，确认 A 自动识别远端关闭、记录 T 的真实 hash 并清除待签状态。

复现命令（artifacts 目录必须尚不存在，端口空闲；在仓库根目录运行）：

```bash
LSP_NATURAL_ARTIFACTS=report/lsp-B-timing-repro \
LSP_NATURAL_CHECKPOINT=B LSP_NATURAL_DELAY_A_PREFLIGHT=1 \
venv/bin/python -u -m pytest \
  test_cases/fiber/devnet/lsp/diagnose_competing_close.py::TestNaturalCompetition::test_observe_competing_close \
  -v -s -o addopts= --junitxml=report/lsp-B-timing-repro.xml
```

### 检查点 B 的实际结果

在干净的 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3` FNN/SDK/驱动上执行一次上述受控时序诊断，独立目录为 timed-B1（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/evidence.json`）。pytest 原始日志（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1.log`） 为 `1 passed in 436.69s`，退出码（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1.exit`） 为 0；此结果只属于检查点 B 的**受控查询时序**，不与前三次未取得目标分支的自然竞争混计。

- B 准备态是 `SignatureRequired / SendRevokeAndAck`；SDK A 本地完整承诺为版本 2，canonical signing message `0x8bed8012…53d28`，含目标 `payment_hash=0x56920455…47cb4`、`expiry=1792754196634`。T 的远端记录是不同的版本 1、`for_remote=true`，canonical `0xc11ccb60…db14`。测试在 D 前核对记录唯一性、目标 TLC 和 funding outpoint `0xcb651b1f…f4f2:0`，广播后再按规范消息匹配真实 A/T 交易，而非仅凭广播先后猜测归属。完整记录（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/evidence.json`）保留原值。
- FNN 第 993、997 行（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/fnn.log`）标出 A 对该 channel 的实际关闭哈希 `0x842d64f0…9509e`。代理仅对这一哈希的两次真实 `get_transaction` unknown 响应等待同一固定释放点：tracer 查询约延迟 253 ms，带 `"0x0", true` 的发送前检查约延迟 257 ms；原始响应未改变，T 的请求没有等待。T 的 `send_transaction` 于单调时钟 `351688.415374` 转发并被真实 CKB 接受；A 于 `351688.668710` 转发，收到原始 `-1111 / PoolRejectedRBF`，`data=RBFRejected`，费用 457、最低替换费 1142。代理记录显示两次延迟都在 A 广播前结束、T 在窗口内真实发送，`armed=null`、`errors=[]`，没有广播门禁或伪造拒绝。代理与时序原始记录（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/evidence.json`）可复核全部请求、响应和时间。
- T 的真实交易 `0x3b1a87eb…c0cb60` 输入精确花费上述 funding，在区块 `0x4e8`（1256）确认。A 的真实拒绝同时见 FNN 第 1077～1089 行（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/fnn.log`）。从首次确认起连续观察 `330.655` 秒；首次完整恢复采样在确认后 `261.775` 秒，恢复后的 34 次采样均保持 A 为 `Closed / UNCOOPERATIVE_REMOTE | WAITING_ONCHAIN_SETTLEMENT`、关闭哈希等于 T、`NoSignatureRequired`，没有回退。全程共 178 次采样，其中确认后 164 次；最大间隔约 2.116 秒，最终链 tip 与索引器 tip 都达到 `0x632`。原始状态在 observations.jsonl（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/observations.jsonl`）。
- FNN 第 1201～1211 行（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/fnn.log`）明确是 **HostedTenant A / actor 0.12** 于 `11:21:05Z` 查得 `is shutdown by remote`，随后从 `ShuttingDown(WAITING_COMMITMENT_CONFIRMATION)` 转为 `Closed(UNCOOPERATIVE_REMOTE | WAITING_ONCHAIN_SETTLEMENT)`；此前的链查询（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/fnn-chain-reads.jsonl`）多次返回花费该 funding 的 T 交易，其中第 103～104 行紧邻状态恢复。证据支持周期扫描最终收敛，不把第 103 行说成 FNN 第一次发现 T。watchtower 的 `PeriodicCheck` 是另外的日志，不能用它替代 HostedTenant 恢复证据。

**判断范围：** 在本次受控查询时序、真实双方竞争、真实 T 胜出与 A RBF 拒绝的检查点 B 路径上，Fiber 在完整扫描窗口内自动识别远端关闭；没有观察到此前担心的“败方永久卡在等待确认”产品 bug。检查点 A 另有无额外时序控制的自然成功样本，但本次 B 的 250 ms 查询延迟不用于推断无干预竞态的发生概率，也不证明所有自然顺序、watchtower 结算或资金取回正确。`WAITING_ONCHAIN_SETTLEMENT` 仍在；正式恢复回归仍需独立评审，原 `LSP-TIMEOUT-08/10` 的 A 承诺确认断言和 TEST-MAP 未改。

诊断脚本在这次执行后将 A 的失败判定收紧为同时要求 `code=-1111` 且错误 `data` 含 `RBFRejected`；已保存的本次原始响应满足新条件，离线证据复核（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/timed-B1/evidence.json`）通过，但没有把执行结果冒称为后补代码重新跑过。`py_compile`、`git diff --check` 均退出 0，源码 checkout 仍干净且在固定提交；TEST-MAP 检查（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/test-map.log`）退出 1（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/test-map.exit`），为既有 PMP/SETTLE 孤儿映射及历史 report overlay 重复 ID；设计检查（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/test-design.log`）识别 10 条、退出 1（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/test-design.exit`），另含 SPEC-09 正式恢复行为待人工确定。尝试按评审文件限制映射检查（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/scoped-test-map.log`）退出 2（本地证据：`report/lsp-natural-B-24b5c38.Anhyq8/scoped-test-map.exit`）：本仓库脚本不支持 `--review`，所以采用上述项目级结果。本次未改评审用例行或 TEST-MAP。

GPT 6.1 sol 在执行前完成诊断脚本的静态复核；其最终结果复核调用曾被 Daybreak 的 `403 Forbidden` 拒绝。按用户后续指定的 Daybreak 可用模型，GPT 6 sol 已对**当前收紧后的脚本、原始证据、固定源码与本节结论完成最终只读复核，未发现阻断项**。复核确认检查点 B 的真实 T 确认/A RBF、HostedTenant A 的恢复、完整 330 秒窗口，以及后补断言由原始响应满足；没有把后补代码冒称为已重新执行。结论仍仅适用于本次受控查询时序下的关闭识别。

## 24b5c38 SPEC-09：LSP-TIMEOUT-12 独立败方恢复（2026-10-23）

用户已通过 [Gate2 完整用例、预算和断言](../../../../reviews/lsp/channel-signing-deadline.md#lsp-timeout-12检查点-b-独立败方恢复)，本批只实现检查点 B 的受控查询时序回归。固定 FNN/SDK/驱动版本为 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`，基类在每次进程启动前校验版本、摘要及驱动源文件摘要；构建清单副本（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/build.json`）保留本批依据。产品、Rust 驱动及公共框架未修改。

新增 Python 方法 `TestChannelSigningDeadline::test_checkpoint_b_loser_recovers_remote_close` 与 TEST-MAP；仅该方法在 setup 连接新的 `_competing_close_observer.py`，原 08/10 的广播隔离入口及断言保持不变。新观察器原样转发双方发送，A 的真实 unknown 查询共用固定 250 ms 释放点，保存真正响应写出时间；真实 code/data 双条件证明 A 的 RBF 拒绝。独立 CKB 查询验证 T 的实际交易和精确 funding input 索引后，再开始 330 秒窗口；逐轮验证状态与健康，首次恢复后全部样本不回退且稳定至少 10 秒，最晚 340 秒结束。RPC 的连接、读取、解析及整轮处理使用测试专用绝对时间限制，不沿用手动诊断的独立长超时。

全部尝试均保存在 本批目录（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO`），包括 `.log/.xml/.html/.exit`、逐轮 observations、原始广播/链读取、FNN/SDK/CKB 日志及最终 evidence；修复前的代码分别保存在 initial-code/revised-code，当前固定批次代码在 final-code。失败不会被后续成功覆盖。

| 尝试 | 实际结果 | 判断边界 |
| --- | --- | --- |
| focused-1（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/focused-1.log`） | `1 failed in 80.85s`，退出 1 | 准备阶段健康检查把框架字符串 CKB PID 当整数比较，发生 TypeError；已转为整数。未取得竞争/恢复场景，属于用例问题 |
| focused-2（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/focused-2.log`） | `1 failed in 106.82s`，退出 1 | 已取得 T 真实确认、A RBF 和精确索引；测试把 TransactionView 附加 hash 字段传给只接受原始交易的驱动，解码失败。已按原 08/10 方式只去掉该附加字段，并以该次保存的原始交易离线核对 SDK T 消息；未执行完整恢复窗口 |
| focused-3（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/focused-3.log`） | `1 passed in 436.51s`，退出 0 | 首次恢复距索引就绪 264.819 秒；完整观察 330.989 秒，恢复后稳定 66.169 秒，最大完整样本间隔 2.018 秒；原始 evidence（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/focused-3/evidence.json`） 与 Hosted A 日志齐全 |
| stability-1（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/stability-1.log`） | `1 passed in 435.43s`，退出 0 | 首次恢复 264.774 秒；完整观察 331.056 秒，恢复后稳定 66.283 秒；evidence（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/stability-1/evidence.json`） |
| stability-2（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/stability-2.log`） | `1 passed in 437.10s`，退出 0 | 首次恢复 264.543 秒；完整观察 330.667 秒，恢复后稳定 66.124 秒；evidence（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/stability-2/evidence.json`） |
| stability-3（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/stability-3.log`） | `1 passed in 437.23s`，退出 0 | 首次恢复 262.564 秒；完整观察 330.743 秒，恢复后稳定 68.179 秒；evidence（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/stability-3/evidence.json`） |

修复后聚焦加固定 3 次复跑为 **4/4 通过**；四次使用逐字相同的 final-code，每次固定复跑开始前 `cmp` 校验退出 0，且各有独立 channel、SDK A 公钥和 funding 交易。恢复窗口每次 166 个完整样本，首次恢复 262.564～264.819 秒、完整观察 330.667～331.056 秒、恢复后稳定 66.124～68.179 秒；最大完整样本间隔不超过 2.024 秒。清理用时均小于 0.115 秒，无代理或清理异常。每次都满足真实 T 获胜/A RBF、精确输入索引、持续恢复谓词与 Hosted A 日志要求，没有用通过重试覆盖失败。

两次失败均为 Python 用例实现问题，不记为产品恢复失败，也不转记为恢复通过。执行前 GPT 6.1 sol 还指出并已修正：阶段截止异常的结果分类、A 被拒原始交易 hash 与延迟查询 hash 的精确绑定，以及代理无法在清理预算内退出时的非零结果。原始交易编码按本地 `ckb-gen-types 1.1.1` 的 Molecule RawTransaction 六字段计算，并对已保存的真实 CKB 接受 hash 与 A spawn hash 做交叉验证；该 helper 不改变或广播交易。

本次聚焦实际命令（复现时更换输出路径；`LSP_RECOVERY_ARTIFACTS` 必须是尚不存在的独立目录）：

```bash
CKB_CLI_HOME=/tmp/lsp-spec09-cli.oTldtL \
LSP_RECOVERY_ARTIFACTS="$PWD/report/lsp-spec09-24b5c38.Xv5YGO/focused-3" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short --durations=5 \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_checkpoint_b_loser_recovers_remote_close \
  --junitxml=report/lsp-spec09-24b5c38.Xv5YGO/focused-3.xml \
  --html=report/lsp-spec09-24b5c38.Xv5YGO/focused-3.html \
  > report/lsp-spec09-24b5c38.Xv5YGO/focused-3.log 2>&1
```

固定复跑依次将上述输出名换成 `stability-1/2/3`，参数与代码保持一致；shell 保存每次真实退出码，失败即停，不补足成功次数。共享 setup 增加 12 专用分支后，另按 Gate2 要求对原 08/10 各回归一次：**`2 passed in 218.11s`，退出 0**。原始 日志（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/related-08-10.log`）、JUnit（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/related-08-10.xml`）、退出码（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/related-08-10.exit`）与两条证据目录（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/related-08-10`）保留。实际命令：

```bash
CKB_CLI_HOME=/tmp/lsp-spec09-cli.oTldtL \
LSP_DEADLINE_ARTIFACTS="$PWD/report/lsp-spec09-24b5c38.Xv5YGO/related-08-10" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short --durations=5 \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_node_protects_without_any_submission \
  test_cases/fiber/devnet/lsp/test_channel_signing_deadline.py::TestChannelSigningDeadline::test_force_close_uses_commitment_with_target_tlc \
  --junitxml=report/lsp-spec09-24b5c38.Xv5YGO/related-08-10.xml \
  --html=report/lsp-spec09-24b5c38.Xv5YGO/related-08-10.html \
  > report/lsp-spec09-24b5c38.Xv5YGO/related-08-10.log 2>&1
```

映射检查实际命令 `python3 scripts/check_test_map.py`：`review cases: 90`、`automated cases: 86`，退出 **1**；12 已正确映射，未映射的四项为 H32V2-35、PR1672-01、PR1675-01/02，仍有既有 PMP-01～05/SETTLE-01 孤儿映射及历史 report overlay 的 16 个重复评审 ID。原始输出（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/test-map.log`）及退出码（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/test-map.exit`）均保留。

设计检查实际命令 `python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/channel-signing-deadline.md`：识别 `cases: 11`，退出 **1**，仅报上述既有重复 ID；输出（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/test-design.log`）与退出码（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/test-design.exit`）保留。两项全仓检查不写成通过，也不跨范围清理旧记录。

静态编译与单条收集均退出 0；最终 `git diff --check`、冻结代码比较、61 个本批本地链接/锚点及空白检查均退出 0。AST 对比原有 52 个方法，仅 setup 增加 12 专用分支，其他 51 个方法保持不变。已批准 11 行仅修改 12 的映射复选框，业务预期未变。固定产品源码 HEAD 仍为上述 SHA、工作区干净；未改产品、驱动或公共框架，保留原有无关本地改动。最终静态检查原始输出（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/final-static.log`）及退出码（本地证据：`report/lsp-spec09-24b5c38.Xv5YGO/final-static.exit`）保留。

**GPT 6.1 sol 独立终审完成，无阻断项，未触发 Daybreak。** 已核对代码、4/4 原始恢复证据、08/10 的 2/2 结果及四份最终文档一致性；所有七次 pytest 尝试的退出码与 JUnit 相符，两个早期夹具失败完整保留。本条只验证所取得的受控 B 败方关闭识别；不证明无干预竞态概率、A 受控时序、watchtower 结算或链上资金取回。本轮没有发现新的产品失败；已知 04/05 问题继续沿用 #1674，未在本批重跑或宣称解决。

## 历史签名通知运行记录（4028884）

以下为 `4028884` 的历史 SSE 批次，共 9 条行为，包含初始快照、实时推送、
租户隔离、无效订阅、原会话重连、真实 SDK 自动恢复，以及新客户端接管与旧 SDK 停止重试。
历史自动化原位于 `test_sse_signing_events.py`，共 13 个方法：无效订阅的五种输入分别使用独立环境。
下列命令是该历史版本的执行入口，不能直接据此宣布新 WS 版本通过：

```bash
venv/bin/python -m pytest -vv -s --tb=short --durations=15 \
  test_cases/fiber/devnet/lsp/test_sse_signing_events.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_retry.py::TestChannelSigningRetry::test_identical_retry_preserves_next_request \
  --junitxml=report/lsp-sse/regression.xml \
  --html=report/lsp-sse/regression.html
```

最后一条是原有重复提交回归，用于验证共享 gate 转发入口的默认行为；不计入新增 SSE 用例。

2026-10-22 在 `4028884` 上执行上述范围：`14 passed in 1314.14s`（21 分 54 秒），退出码 0，
无失败、错误或跳过。日志、JUnit 和 HTML 位于 `report/lsp-sse-4028884-20261022/regression.*`。
GPT 6.1 sol 对照批准用例完成了代码及结果复核，未发现需要修改的问题。

`python3 scripts/check_test_map.py` 检查评审行与 `TEST-MAP` 的对应关系。复选框只表示存在映射；
核心 16 行和签名订阅 11 行均有映射，对应本批 30 个方法。全库检查退出码为 1：
仓库原有 `PMP-01～05`、`SETTLE-01` 缺少对应评审行，另有 `report/` 下旧测试副本产生 16 个重复核心 ID。
本批没有旧 SSE 孤立映射；保留这些既有全库问题，不跨范围改动。设计检查覆盖本次 3 份评审共 24 行，
仅受同一批旧副本重复 ID 阻断，退出码 1；映射与结构检查均不等于行为执行通过。

## 24b5c38：真实付款延迟签名恢复（2026-10-24）

用户确认 [Gate2 三行、预算与共同断言](../../../../reviews/lsp/delayed-payment-recovery.md)后实现
`LSP-PAYMENT-01～03`，分别验证在线扣签、SDK 完全离线且零租户请求、A 等签时 B 独立完成付款。
所有付款均由 P 经 T 发起一次，使用真实 SDK 签名；目标为含原 TLC 的 `CompleteReceivedCommitment`，
持有至少 35 秒后恢复，最终核对付款、发票、资金、费用、锁定额和至少 5 秒稳定性。
02 要求原 WS 两侧关闭且在途 HTTP 清空后才计离线窗口；03 要求 B 在 A 放行之前完成并保持混合资金断言。

FNN/SDK/驱动固定 `24b5c38bc098aeb29de5f6af7ac28dc667f218e3`；实际二进制、驱动及源码摘要均已核对，
源码 checkout 干净。仅新增 LSP Python 测试及扩展同目录 HTTP gate 的审计，保留其原有故障模式和默认超时；
未改 Rust 驱动、产品、公共框架或无关本地内容。本批不覆盖更新的 PR HEAD、业务超期、watchtower 和链上取回。

本地证据根目录：`report/lsp-payment-24b5c38-20261024.F9NllT/`。
每轮独立保存 `.log/.xml/.html/.exit`，每条另存 `observations.jsonl`、HTTP/WS 审计、FNN/SDK 数据和日志及 CKB 日志。
`focused-1/` 与 `focused-2/` 保存各自实现和 gate 快照；`frozen-sha256.txt` 记录最终实现及二进制摘要。
以下报告路径均为仓库根目录下的本地证据，不提交到 Git。

首轮 `focused-1`：`3 passed in 394.37s (0:06:34)`，退出 0。
独立复核发现 actor 自动重建断言只覆盖 A–T，尚未覆盖 P–T/B–T；首轮实际日志没有重建证据。
已按原 Gate2 要求补齐全部基线通道检查，未改变产品预期。首轮结果完整保留，不计入修正后固定批次。
修正后冻结代码，`focused-2`：`3 passed in 398.09s (0:06:38)`，退出 0。

复现时创建新的输出目录，从仓库根目录串行运行；避免重复使用已有证据目录：

```bash
mkdir -p report
export CKB_CLI_HOME="$(mktemp -d)"
export LSP_PAYMENT_REPORT_DIR="$(mktemp -d "$PWD/report/lsp-payment-24b5c38.XXXXXX")"
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short --durations=5 \
  test_cases/fiber/devnet/lsp/test_delayed_payment_recovery.py \
  --junitxml="$LSP_PAYMENT_REPORT_DIR.xml" --html="$LSP_PAYMENT_REPORT_DIR.html" \
  > "$LSP_PAYMENT_REPORT_DIR.log" 2>&1
payment_run_exit=$?
printf '%s\n' "$payment_run_exit" > "$LSP_PAYMENT_REPORT_DIR.exit"
```

本轮实际使用 `CKB_CLI_HOME=/tmp/lsp-payment-cli.VIpJiT`，每轮 `LSP_PAYMENT_REPORT_DIR` 指向上述根目录下
对应轮次子目录；`-o addopts=` 避免默认 HTML 输出覆盖旧报告。固定复跑前逐轮比较当前实现和 gate 与冻结快照；
任何失败均保存结果并停止后续轮次定位，不以无限重跑择优。

冻结后结果（均无失败、错误或跳过）：

| 轮次 / 本地报告前缀 | 原始 pytest 结果 | 退出码 |
| --- | --- | --- |
| `focused-2` | `3 passed in 398.09s (0:06:38)` | 0 |
| `stability-1` | `3 passed in 389.69s (0:06:29)` | 0 |
| `stability-2` | `3 passed in 386.04s (0:06:26)` | 0 |
| `stability-3` | `3 passed in 401.91s (0:06:41)` | 0 |

即聚焦 1 轮加固定 3 轮，共 **12/12 通过**，与修正前首轮分开计算。
四次完整离线窗口为 35.048～35.055 秒，HTTP 接收/转发、WS 请求和控制调用均无新增；
恢复使用新 PID、原身份和授权，新连接真实交付同一 R，首个签名体与原 S 一致。
四次双租户场景中 B 在检查点后 4.224～4.247 秒先完成，最终混合样本均在 A 等待满 35 秒后取得；
B 结算后 A–T 余额未变、A 腿仍锁 1,000,000、P–T 仍锁 1,005,000 Shannon。
最终 A 的实际费用均为 5,000、B 均为 10,000 Shannon，T 三通道净增 15,000，六端余额与费用对应，锁定额/TLC 清空。
所有原目标签名首次真实转发均 Applied，最终稳定观察 5.066～5.100 秒，单个完整样本最长约 0.123 秒；
付款业务段均在 42.603～43.316 秒内完成，独立于通道准备耗时。未观察到产品失败；结论仅限本批固定版本与三种受控等待路径。

静态检查：新增文件 AST 通过；LSP 目录 `--collect-only -q` 为 `44 tests collected in 0.14s`，退出 0，
仅表示收集成功，不当作全部 44 条执行通过。`git diff --check` 退出 0，56 个相对文档路径存在。
`python3 scripts/check_test_map.py`：93 个评审 ID、89 个已映射，本批 3/3 一一映射；退出 1 仍为原有
`PMP-01～05`/`SETTLE-01` 孤儿映射与历史 report overlay 的 16 个重复 ID，未跨范围修改。
`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root /Users/sunchengzhu/project/fiber-py-integration-test --review reviews/lsp/delayed-payment-recovery.md`
识别 3 条，退出 1 的错误项仅为同一批历史重复 ID；SPEC-03 推断行为和未分析叶子的提示仍保留，
前者已由用户在本批 Gate2 明确确认，后者仍不属于本轮范围。检查原文及退出码在 `final-test-map.*`、`final-test-design.*`。

受共享 HTTP gate 审计改动影响，另行执行已有 `LSP-RETRY-04/05`，保留其原代码及断言：

```bash
CKB_CLI_HOME=/tmp/lsp-payment-cli.VIpJiT PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short --durations=5 \
  test_cases/fiber/devnet/lsp/test_channel_signing_retry.py::TestChannelSigningRetry::test_unsent_signature_recovers_after_disconnect \
  test_cases/fiber/devnet/lsp/test_channel_signing_retry.py::TestChannelSigningRetry::test_applied_signature_recovers_after_http_timeout \
  --junitxml=report/lsp-payment-24b5c38-20261024.F9NllT/related-retry.xml \
  --html=report/lsp-payment-24b5c38-20261024.F9NllT/related-retry.html
```

实际 stdout/stderr 重定向至同前缀 `.log`，退出码保存于 `.exit`：
`2 passed in 169.87s (0:02:49)`，退出 0，无失败、错误或跳过。
04 请求未送达后真实重订阅耗时 3.096 秒；05 真正 Applied 后响应未写出，SDK 自然超时 10.003 秒，
随后 11.126 秒取得新订阅，旧 S1 幂等和新 R2 保留等既有断言继续成立。
这是受影响共享夹具的相关回归，不代表本轮重新跑过全部 44 条。

GPT 6.1 sol 独立复核最终代码、冻结摘要、构建版本、四轮 JSONL/HTTP/WS/FNN 原始证据、JUnit 和退出码，
确认新增 **12/12** 与相关旧回归 **2/2** 的断言和执行结果一致；首轮 actor 检查遗漏已补齐，当前无本范围剩余阻断项。
未触发 Daybreak，无需切换模型。最终实现仍与 `focused-2` 快照一致，产品源码 checkout 干净；
固定端口 8114、8125、8227～8230 全部空闲，本条持有的 FNN/SDK 进程均退出，`tmp` 为 0B。
全部首轮及复跑证据约 58 MiB 保留在本地根目录；本轮未提交或推送，未删除无关本地内容。

## 04c2064 最小兼容回归（2026-10-24）

用户批准将下一批验证基线切至 `04c206465b48da85b99aa58e80afe9801a2cb2db`，先跑最小兼容回归，再整理 watchtower Gate1。
相对 `24b5c38` 的两笔提交只改浏览器 WS 鉴权、tenant token 无填充编码及相关测试/文档/依赖；
本轮验证现有 SDK 的 Bearer 路径，不验证新增浏览器 subprotocol。

干净源码 checkout 已切至该 SHA，`venv/bin/python scripts/build_lsp_test_binaries.py --source download/fiber/source-pr-1623`
构建退出 0，FNN 为 `fnn Fiber v0.10.0-rc1 (04c2064 2026-10-23)`。
新版独立放在 `download/fiber/pr-1623-04c2064/`；原 `download/fiber/pr-1623/` 的 24 版 FNN/SDK/驱动及清单未覆盖，
三份旧二进制实际摘要与历史清单一致。产品源码工作区干净，未修改 FNN/SDK/合约或本地 Rust 驱动。

测试改动仅为版本/产物目录固定，以及 `_lsp_test.py` 的可选 `LSP_RUN_ARTIFACTS`：
在既有清理之前保留每条用例的 HTTP/WS 记录、FNN/SDK 文件和 CKB 日志，成功也留存；
使用新目录且拒绝覆盖，跳过通用失败归档对旧 `report/<method>` 的删除。
归档不是数据库一致性备份；未设置环境变量时保留原清理方式。两条用例的步骤、断言和 TEST-MAP 均未改变。

| 既有用例 | 本次检查 | 实际结果 |
| --- | --- | --- |
| `LSP-RECOVERY-01` / `test_checked_open_pay_and_close` | 新注册 token 的 HTTP/SDK WS 入口、真实开通、P 经 T 付款给 A、四端余额、协作关闭及精确输出 | PASS；付款金额 1,000,000 Shannon，路由费 5,000，四端 local 增量 `(1000000, -1000000, -1005000, 1005000)`；关闭交易确认，输出 `(50001000000, 49998999472)`，费用 528 |
| `LSP-SUBSCRIPTION-02` / `test_next_request_arrives_on_original_subscription` | 原订阅收到 R1，应用 S1 后先收到真实 R2 再查询交叉核对，真实 SDK 签名后通道完成 | PASS；原连接后续事件及最终通道断言通过 |

本轮仅执行一次上述两条，**`2 passed in 201.45s (0:03:21)`，退出 0**，无失败、错误或跳过。
两条归档中，新注册 `tenant_token` 均非空且无 `=`；SDK 的真实 WS 已送达帧分别为 25 和 7，归档连接的 `errors` 均为空，
HTTP 审计含真实注册、开通和签名提交。帧数用于核对证据，不是新的次数契约。
首条 SDK 日志曾在本地 fulfillment 授权完成前拒绝 TLC 移除，随后恢复并满足全部原断言；该日志不单独算作产品失败或额外回归通过。

本地证据根目录（相对仓库根目录，仅保存在本机，不提交）：`report/lsp-compat-04c2064-20261024.hkbapv/`。
其中 `build.log/.exit`、新旧 `build.json`、`historical-binaries.sha256`、本轮 `code/` 快照、
`collect.log/.exit` 和 `compat-1.log/.xml/.html/.exit` 保存实际输入、输出与退出码；
`compat-1/<test_method>/` 内保留 `A-http.json`、`A-ws.json`、两节点文件、SDK 状态/存储及 CKB 日志。

当时实际执行命令如下；复现须创建新报告目录，不能复用这个归档路径：

```bash
CKB_CLI_HOME=/tmp/lsp-compat-cli.QNK0Pz \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-compat-04c2064-20261024.hkbapv/compat-1" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short --durations=5 \
  test_cases/fiber/devnet/lsp/test_channel_signing_recovery.py::TestChannelSigningRecovery::test_checked_open_pay_and_close \
  test_cases/fiber/devnet/lsp/test_signing_subscriptions.py::TestSigningSubscriptions::test_next_request_arrives_on_original_subscription \
  --junitxml=report/lsp-compat-04c2064-20261024.hkbapv/compat-1.xml \
  --html=report/lsp-compat-04c2064-20261024.hkbapv/compat-1.html \
  > report/lsp-compat-04c2064-20261024.hkbapv/compat-1.log 2>&1
lsp_compat_exit=$?
printf '%s\n' "$lsp_compat_exit" > report/lsp-compat-04c2064-20261024.hkbapv/compat-1.exit
```

本次通过只适用于上述两个既有用例及新版实际入口，不将旧 24 版的历史回归转记，也不声明其余 42 条、浏览器鉴权或 watchtower 通过。
固定测试端口执行后均无监听，`tmp/` 为 0B；保留无关本地改动和全部旧证据。下一步为 [watchtower Gate1 范围评审](../../../../reviews/lsp/watchtower-settlement-scope.md)，尚未改 watchtower 自动化。

最终检查：两条收集、Python 静态编译及 `git diff --check` 均退出 0。`python3 scripts/check_test_map.py` 退出 1，
93 个评审 ID / 89 个有映射；既有四项未映射、PMP-01～05/SETTLE-01 孤儿及历史 report overlay 的 16 个重复评审 ID 均保留，
本轮未增删 TEST-MAP。watchtower Gate1 的设计检查最终退出 1：相同历史重复 ID、当前阶段无正式用例行、三个源码观察预期和待展开分支需人工确认；
初次 Source 格式错误已修正，原始与最终输出及退出码分别保存在 `test-design.*` 和 `test-design-final.*`。

**GPT 6.1 sol 独立复核完成，无阻断项，未触发 Daybreak。** 已核对本轮版本/归档代码、新旧 bundle 每项实际摘要、产品源码状态、
JUnit 两条零失败/错误/跳过、token 格式与原始 WS/HTTP 证据，并完成 watchtower Gate1 源码与范围复核。
这不替代 watchtower Gate1 的人工确认，也不代表运行了 watchtower 场景。

## 04c2064 watchtower Gate3：合约预检阻断（2026-10-25）

用户已确认 [四条用例及 02 分段边界](../../../../reviews/lsp/watchtower-settlement.md)。已加入 `test_watchtower_settlement.py` 的 `LSP-WATCHTOWER-01～04` 映射、独立 CKB 适配与审计、原 Agent 授权/拒签和适配签名入口；这些目前是**待运行验收的实现**，映射存在不代表通过。02 永远不计入原 Agent 自动事件链恢复覆盖。产品 checkout 保持干净 `04c206465b48da85b99aa58e80afe9801a2cb2db`；没有升级链上合约、改变快照或修改 FNN/SDK 产品代码。

正式流程要求“适配自检 → 聚焦一轮四条 → 固定三轮四条”。本次停在适配的环境预检，**正式聚焦和三轮复跑全部未运行（0/16 已执行）**，不能记成四条产品失败或通过。也不能把这次意外预检失败当成预先设计的负向自检通过。

| 尝试 | 原始结果 | 归因与处理 |
| --- | --- | --- |
| selfcheck-1 | `1 failed in 194.82s`，退出 1 | 测试夹具开启 ack-held-events 后只放行 gate，没有明确提交扣住的首次开通签名；未完成通道准备。已修复，保留原始结果 |
| selfcheck-2 | `1 failed in 97.11s`，退出 1 | A/B 真实通道开通后，watchtower-configure 返回 `contract bytes differ: commitment-lock`；环境预检未满足，未进入强关、自检主体或产品四条 |

两次命令主体相同，仅使用各自目录：

```bash
CKB_CLI_HOME=/tmp/lsp-watchtower-cli-20261025 \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-watchtower-04c2064-20261025/selfcheck-2" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short \
  --junitxml=report/lsp-watchtower-04c2064-20261025/selfcheck-2.xml \
  test_cases/fiber/devnet/lsp/test_watchtower_settlement.py::TestWatchtowerAdapter
```

完整证据保存在本地 `report/lsp-watchtower-04c2064-20261025/`：`selfcheck-{1,2}.log/.xml/.exit`；对应子目录的 `test_adapter_rejects_invalid_authorization/fiber-1/` 含 SDK、HTTP/WS、节点与链验证日志。`selfcheck-2-sources/` 记录该轮源码和 build.json；其后代码继续修正并静态验证，不能用该轮结果声称最终源码已运行。`pre-change/` 保存修改前 04 驱动、构建清单及驱动/构建脚本来源，旧 24 产物未动。`build-1～9.log` 保留构建及修正过程，不仅保留最后成功输出。

阻断的真实链证据在 `selfcheck-2/test_adapter_rejects_invalid_authorization/fiber-1/ckb-verifier.jsonl`；相关响应的 `selfcheck_fault` 为 `null`，不是故障注入：

- 可信模板 CommitmentLock Type ID args：`0x082d30abbb75c3db217a78eee4f3e0d5a46c90b56c11dec77f3060319f323808`，code_hash：`0xf3775d5328de71717f2c5614fa06b9b93c48b7d90c1e135c0812c74ee3126453`。
- 实际 live outpoint：`0x157446f77b9468f63ae741dc66e6e987b470eb2e5f66fdde62d7c90f96042202:0`；107,784 字节；SHA256 `ebf8614c1c7970ba9566820e07dd4c3402ea1ce57f3c08e6f2142f5b448954a8`。
- 本地 `source/contract/fiber/commitment-lock` 与固定 04 上游 `tests/deploy/contracts/commitment-lock` **逐字节一致**，均为 80,880 字节；SHA256 `a7762721ef239b15adbdddca8d772db6e1c001d9f81e23ccc74e1392329931d7`。不是选错本地文件，也不能因 Type ID/code_hash 相同就忽略数据差异。
- 链来自 `framework/basic_fiber.py` 的 `source/fiber/data.2026.0929.tar.gz` 快照。该路径没有在本批自动更新合约；当前证据只能确定部署内容不符，不宣称已识别链上二进制的源码版本或 Fiber 产品 bug。

GPT 6.1 sol 已独立复核两份合约、原始无注入链响应、selfcheck-2 JUnit/退出码及干净产品版本，确认这是环境前置阻断，未触发 Daybreak。代码曾经复核提出的夹具/计时/断言问题已据反馈修正，**仍需在合约环境修正后通过完整适配自检、正式 1+3 批次与最终结果复核，当前不能宣布 Gate3 完成**。

恢复入口：先由用户决定环境处理。建议仅为本批建立明确隔离的临时 devnet 工作副本，在开通前将同一 CommitmentLock Type ID 更新为已固定并核对摘要的 04 合约，再重新执行全套预检；原始快照、旧历史环境和证据继续保留。这是待确认方案，本轮未实施。已批准 Gate2 明确“字节不符失败，不自动部署或升级”，故不能静默接受链上旧字节、换信任源或跳过校验。环境恢复后还需复核 funds/sponsor 夹具和全部 selfcheck 分支；不要仅重跑正式四条。

本轮最终静态验证：构建 `build-9` 退出 0；清单全部产物与驱动/适配源码摘要匹配。`pytest --collect-only` 为 `5 tests collected in 0.16s`（四条正式方法、一条适配自检），退出 0；Python 编译、文档本地链接和 `git diff --check` 通过。映射检查为 97 个评审 ID / 93 个有映射，退出 1，仅报告既有六个孤儿映射和历史 overlay 的 16 个重复 ID；设计检查识别四行，退出 1，同样既有重复 ID及 SPEC-02 的 inference 人工决策提示（用户本轮已明确接受）。这些静态结果不代表功能通过。检查输出见同目录 `collect-final.log/.exit`、`test-map.log/.exit`、`test-design.log/.exit`。结束时本批固定端口无监听，`tmp` 为 0B。

最终静态复核还修正了 legacy commitment args 长度边界，避免适配自检索引越界；新增控制截止仅用于 watchtower 操作，普通开通/付款控制保持既有时限。GPT 6.1 sol 确认当前应以环境阻断交接，不能宣布实现或 Gate3 通过。


## 04c2064 WebSocket 既有订阅回归与下一步（2026-10-26）

用户收到开发者“方案稳定”的反馈后要求优先推进 WebSocket。当天只读查询 PR #1623，仍为 open，head 为 `04c206465b48da85b99aa58e80afe9801a2cb2db`；本地产品 checkout 干净且同源，构建清单中全部产物及驱动/适配源码摘要一致。没有切换产品版本或更新合约。

watchtower 被阻断的直接原因是独立链验证所信任的 CommitmentLock 字节与当前 devnet live code 不符，详见上一节；普通签名订阅测试不调用该配置。两条路径分别记录，不能因 watchtower 预检失败就停止已有 WebSocket 验证，也不能用普通开通通过证明强关结算环境合格。

本轮只运行既有已批准的 `test_signing_subscriptions.py`：14 个方法对应 11 个 `LSP-SUBSCRIPTION-*` 行为，其中 04 有四种拒绝输入。先跑实时推送探针，随后排除同一方法运行其余 13 条，不把两次命令说成重复稳定性复跑。

| 批次 | 原始结果 | 范围 |
| --- | --- | --- |
| probe | `1 passed in 81.23s`，退出 0 | 原订阅实时收到下一真实签名请求，最终原通道完成 |
| remaining | `13 passed, 1 deselected in 1067.55s`，退出 0 | 其余 13 个已有方法；排除的 1 条就是已单独通过的 probe |

实际命令（分别保存 stdout/stderr 到同名 `.log`，shell 保存真实退出码到 `.exit`）：

```bash
CKB_CLI_HOME=/tmp/lsp-ws-cli-20261026 \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-websocket-04c2064-20261026/probe" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short \
  --junitxml=report/lsp-websocket-04c2064-20261026/probe.xml \
  test_cases/fiber/devnet/lsp/test_signing_subscriptions.py::TestSigningSubscriptions::test_next_request_arrives_on_original_subscription

CKB_CLI_HOME=/tmp/lsp-ws-cli-20261026 \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-websocket-04c2064-20261026/remaining" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s --tb=short \
  --junitxml=report/lsp-websocket-04c2064-20261026/remaining.xml \
  test_cases/fiber/devnet/lsp/test_signing_subscriptions.py \
  -k 'not test_next_request_arrives_on_original_subscription'
```

本地证据统一保留于 `report/lsp-websocket-04c2064-20261026/`：`probe`、`remaining` 下按测试保存 SDK、HTTP/WS 和节点日志；对应 `.log/.xml/.exit` 记录命令结果；`sources/` 保存此次测试相关源文件、摘要、构建清单及实际产品 HEAD/干净状态。历史 24 结果、watchtower 两轮失败原始证据及无关改动保留。

下一批建议为 [浏览器鉴权补充 Gate1](../../../../reviews/lsp/signing-subscriptions-scope.md#2026-10-26浏览器鉴权补充-gate1)：正常子协议接入与 token 输入兼容、握手冲突拒绝、权限及租户范围。GPT 6.1 sol 已复核范围和源码，未触发 Daybreak；新增完整行集与自动化尚未获批。现有回归走 Bearer header，不能计作浏览器子协议、TLS/代理、watchtower 真实待签或链上结算通过。

本轮未修改测试实现或 TEST-MAP。`python3 scripts/check_test_map.py` 为 97 个评审 ID / 93 个有映射，退出 1，仍为既有六个孤儿映射及历史报告 overlay 的 16 个重复 ID；输出保存为 `test-map.log/.exit`。未删除报告或跨范围修正历史问题。

最终核对两个 JUnit：共 **14 个唯一方法通过，0 failure / error / skip**，对应 11 个已批准行为；不是同一方法重复计数，且不是 1+3 稳定性批次。归档源文件与运行结束时源码摘要一致，产品 checkout 仍为干净 04。固定测试端口 8114/8125/8227/8228/8229/8230 均无监听。结构化核对结果在本地 `report/lsp-websocket-04c2064-20261026/verification.json`。

GPT 6.1 sol 最终独立复核通过，未触发 Daybreak：两份 JUnit 与真实退出码、14 个唯一方法与源码集合、11 个映射 ID、构建清单及五项产物摘要一致，逐方法 SDK/HTTP/WS/节点日志齐全。复核结论仅为上述 Bearer WebSocket 现有回归通过，保留浏览器与 watchtower 验证边界。


## 04c2064 浏览器鉴权 Gate3（2026-10-26）

用户明确通过 [14～19完整行集、共同断言及预算](../../../../reviews/lsp/signing-subscriptions.md#浏览器鉴权-gate2共同断言输入与预算04c2064)后完成本批Gate3。`test_browser_signing_subscriptions.py` 对应6个行为、11个独立方法：五种握手错误与两种缺权限输入独立执行；正常接入、编码兼容、无效Biscuit、双租户隔离各一条。正式聚焦加固定三轮共 **44/44通过**；共用改动相关的既有订阅回归 **14/14通过**。每批零失败、错误或跳过；没有将探索轮计入正式结果，也不表示所有LSP模块已全量回归。

固定FNN/SDK源码为干净的 `04c206465b48da85b99aa58e80afe9801a2cb2db`。共用观察器仅增加可选子协议与握手预算参数；本地测试驱动新增有效padding凭证夹具，先验证原token签名并保留唯一tenant/node，仅用公开devnet测试私钥签发。旧缺权限分支及默认Bearer行为保持。没有修改FNN/SDK产品代码、更新链上合约或扩展Rust压力测试。

### 实际结果和修正

| 批次 | 原始结果 | 退出码 | 口径 |
| --- | --- | --- | --- |
| focus-attempt-1 | `5 passed in 503.67s`，随后KeyboardInterrupt | 2 | 探索轮；第6条被人工中断，不计入正式44个实例 |
| focus | `11 passed in 922.93s` | 0 | 修正后正式聚焦一轮 |
| stability-1 | `11 passed in 923.40s` | 0 | 固定复跑第1轮 |
| stability-2 | `11 passed in 911.64s` | 0 | 固定复跑第2轮 |
| stability-3 | `11 passed in 918.65s` | 0 | 固定复跑第3轮 |
| related-subscriptions | `14 passed in 1127.42s` | 0 | 旧Bearer订阅方法回归，单列不计入新44实例 |

初审修正了三个夹具问题：unittest可能吞掉一次性清理alarm，改为逐回调使用同一剩余30秒截止；核心浏览器证据先落盘，再复制体积较大的节点目录；终态增加host侧精确通道集合断言。追加核对发现原断言只比较双方完整outpoint和原funding hash，仍应独立检查输出索引0；依据固定 `channel.rs::get_funding_transaction_outpoint()` 补上最后4字节为0，因此人工中断探索轮后重新执行正式1+3。没有发生产品断言失败，未把被中断方法或补充前结果当成最终断言通过。

每条新用例保存真实101/400、协商协议不回显凭证、RPC错误与无授权通知、完整R1/R2及原SDK完成证据。终态检查双方ChannelReady/NoSignatureRequired、原funding hash及index 0、注资committed、余额相互对应、无pending TLC、host/tenant无额外通道及连续稳定窗口。初始/后续事件阶段、业务完成和整体预算均使用共享截止；不按连接或租户倍增等待，不重试筛掉失败。四个正式新批次使用同一冻结源码，均完整运行11个方法。

### 命令与本地证据

构建命令：`python3 scripts/build_lsp_test_binaries.py --source download/fiber/source-pr-1623`，`build-1`退出0。实际pytest命令如下；每轮仅替换 `run`，stdout/stderr写入同名`.log`，shell另存真实`.exit`。任一非零退出即停止后续批次。

```bash
run=focus
CKB_CLI_HOME=/tmp/lsp-browser-cli-20261026 \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-browser-04c2064-20261026/$run" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s -x --tb=short \
  --junitxml="report/lsp-browser-04c2064-20261026/$run.xml" \
  test_cases/fiber/devnet/lsp/test_browser_signing_subscriptions.py
```

固定三轮分别使用 `stability-1/2/3`；旧回归使用 `related-subscriptions`，target改为 `test_cases/fiber/devnet/lsp/test_signing_subscriptions.py`，其余参数相同。探索轮使用 `focus-attempt-1`，源码与修正后批次分开保留。

完整本地证据根为 `report/lsp-browser-04c2064-20261026/`：各批次`.log/.xml/.exit`；同名目录中每条方法旁独立`.browser.json`（新用例），方法目录中的SDK、HTTP/WS代理、节点与CKB日志；`focus-attempt-1-sources/`和`final-sources/`分别保留两版源码与构建清单。`pre-change/`保留改动前04驱动二进制、清单及驱动源码。全部证据含探索轮均保留，旧24、04普通订阅和watchtower诊断报告未动；report、二进制和临时文件不加入Git。

### 验证及边界

GPT 6.1 sol 完成代码和最终运行结果的独立复核，未触发Daybreak：四轮各11个唯一方法、44份浏览器证据及日志齐全；旧回归14个唯一方法与原始JUnit/退出码一致；冻结源码与最终实现逐字节一致，构建产物摘要匹配，产品checkout干净且固定04。探索轮独立排除。测试结束后固定端口8114/8125/8227/8228/8229/8230无监听，`tmp`为0B。

收集为11条，退出0；Python编译、文档本地链接及`git diff --check`通过。`python3 scripts/check_test_map.py`为103个评审ID/99个映射，新六行均已映射，退出1仍为既有六个孤儿和历史报告overlay的16个重复ID。skill设计检查识别17行，退出1仍有相同历史重复、保留后续分支和SPEC-06源码观察人工确认提示（用户已明确通过本批完整行集）；原始输出在`test-map.*`、`test-design.*`。不为使检查器全绿而删除历史证据或跨范围修改评审。

本次是Python对服务器浏览器WS线协议入口的功能验证，不声称真实浏览器页面、TLS/代理、全局压力、watchtower真实待签或链上资金取回通过。watchtower的合约字节预检问题继续独立保留。当前可执行LSP源码无SSE命名；历史协议事实和原始报告路径保留以便追溯。

## 04c2064 watchtower 隔离环境恢复与正式验证（2026-10-27）

用户已授权仅为本批建立隔离 devnet、更新固定 04 CommitmentLock，并执行适配自检与四条正式 1+3；原快照、历史证据和无关改动保留，不修改产品源码。每个 pytest 类使用独有 `tmp/lsp-watchtower-*` 工作目录，从原快照解压后、任何 FNN/通道启动前，通过现有 Type ID 更新 helper 部署可信字节。保持原 Type ID/lock，独立核对交易 committed/canonical、唯一 live outpoint、实际字节和索引；合约更新计入准备的 300 秒。原 `source/fiber/data.2026.0929.tar.gz` 及可信合约文件未变，摘要记录于本轮根目录 `original-inputs.sha256`。

本地证据根（相对仓库根目录，不提交）：`report/lsp-watchtower-isolated-04c2064-20261027/`。每轮 `.log/.xml/.exit`、各方法 SDK/FNN/CKB 与 HTTP/WS/独立链审计均保留；类级 `*-isolated-contract.json` 保存更新前后代码 cell、交易与 canonical header。`selfcheck-*-sources`、`pre-change`、`final-sources` 和 `final-v2-sources` 区分实现版本，不覆盖旧 24/04 结果。

### 夹具修正与全部尝试

| 批次 | 实际结果 | 归因/计数 |
| --- | --- | --- |
| selfcheck-1 | setup 中主动中断，`no tests ran in 44.30s`，退出 2 | 独立复核发现准备截止误加到清理阶段，停止修正；工作目录另存 `interrupted-workdir`，不计通过 |
| selfcheck-2 | `1 failed in 102.67s`，退出 1 | 本地过滤误要求 A 的远端承诺记录具有聚合签名；T 的真实确认交易已匹配该记录 |
| selfcheck-3 | `1 failed in 102.69s`，退出 1 | 本地费用模板硬编码旧 57 字节 args，少算 1 Shannon；真实协商 58 字节，链上费用 457 |
| selfcheck-4 | `1 failed in 113.59s`，退出 1 | Python 将 RPC 的 `{"type":"Settlement"}` 枚举误当字符串 |
| selfcheck-5 | `1 passed in 114.69s`，退出 0 | 11 项负向检查、三种链证据故障和费用上限拒绝通过，GPT 6.1 sol 复核原始证据 |
| focus（旧观察循环） | `4 passed in 1462.61s`，退出 0 | 四条核心行为/资金通过，但复核发现 02 实际最大采样间隔 2.278s，超过已批准 2s；不能算全部约束验收通过 |
| stability-1（旧观察循环） | setup 中主动中断，`no tests ran in 82.47s`，退出 2 | 因上述采样偏差停止计划；后两轮未运行 |
| selfcheck-6（修正后） | `1 passed in 113.57s`，退出 0 | 新冻结源码自检通过，正式完整 1+3 另行重新计数 |

远端承诺修正依据固定 SDK `lifecycle.rs::complete`：只有持有 peer partial 时才保存聚合签名；A 的 `for_remote=true` 记录可以已验证但 `complete_signature=None`。`signer.rs::prepare_onchain` 不要求该字段。取消 Python/Rust 测试夹具的错误过滤，仍要求唯一已验证记录、T 强关方向、规范化消息、原 funding、可信 deps、真实 canonical 确认及 SDK 完整链验证；不伪造记录或签名。费用模板改为读取 T 持久化的 `commitment_contract_features.lock_args_len()`，不按失败交易反推费用或提高批准上限。

观察循环改为每秒目标调度，每次检查受 2s 截止约束；实际采样完成间隔显式 `<=2s`，最后一次成功采样须覆盖 130s/65s 后才结束。证据记录 `samples`、`max_sample_gap` 和实际时长。原负向 140s、稳定 75s及业务总预算不变。上述修正均已由 GPT 6.1 sol 只读复核，未触发 Daybreak。

### 修正后正式批次

`final-v2-sources` 为修正后冻结实现，按顺序执行并在首个非零结果停止；没有以补跑替换失败。

| 批次 | 原始结果 | 退出码 |
| --- | --- | --- |
| focus-v2 | `4 passed in 1463.19s` | 0 |
| stability-v2-1 | `1 failed, 3 passed in 1407.11s`；失败为 02 | 1 |
| stability-v2-2 | 前轮失败，未运行 | 无 |
| stability-v2-3 | 前轮失败，未运行 | 无 |

修正后正式共执行 8 个实例，7 通过、1 失败；固定稳定性验收未完成，不能声明 Gate3 全部通过。聚焦 02 负向观察为 130.810s/131 次采样/max gap 1.161s，失败轮也完整观察 130.759s/131 次/max gap 1.209s，因此本次失败不再是采样精度问题。独立复核已确认聚焦四条全部资金/签名及观察约束成立。

命令主体（每轮替换 `RUN`；自检改为 `TestWatchtowerAdapter`）：

```bash
CKB_CLI_HOME=/tmp/lsp-watchtower-isolated-cli-20261027 \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-watchtower-isolated-04c2064-20261027/$RUN" \
PYTHONUNBUFFERED=1 venv/bin/python -m pytest -o addopts= -vv -s -x --tb=short \
  --junitxml="report/lsp-watchtower-isolated-04c2064-20261027/$RUN.xml" \
  test_cases/fiber/devnet/lsp/test_watchtower_settlement.py::TestWatchtowerSettlement
```

本批范围始终为无 pending TLC 的四条已批准行为，结算到预先批准的 D。02 只证明原 Agent 缺批准拒签与批准后适配结算两段，不计原 Agent 自动恢复、含 TLC 兑现/退款、惩罚或租户独立钱包取回。


### 02 复跑失败：陈旧待签工作持续暴露（产品侧问题证据，恢复影响有边界）

固定产品版本为 `04c2064`。复现入口是上述命令的 `TestWatchtowerSettlement::test_missing_approval_then_adapted_settlement`，原始失败来自完整四条类级顺序的 `stability-v2-1`，不保证单独运行每次出现。场景为 T 强关、A 尚未批准，原 Agent 拒签，T 先结算自己的份额；A 的原待签交易随后变成死输入。测试没有阻止正常竞争，也没有向 A 提供签名或批准。

失败 channel：`0xf1d86cbd9cae84000654290a9e0ded519d902b3fa0ac2fd9fad4e811bd382997`。
原 request：`0xa0e3910ab258bcb8237015c9fb56429b4ee1135047d51a2fac04c557d77ad1e0`。
原 commitment outpoint：`0xe1c2ebf21e8717e686113659d9143f7b800f8adb7b0aabb24c855d11eebd4f44:0`。
T 实际支出：`0x92091af88d2132545f81f9df37ecb30a9110709b657da06fa40590f15b2ed37f`，确认块 `0x2cb7`，精确消费上述原 commitment；后继保留 49,999,999,543 Shannon。

时间均为 Asia/Shanghai（UTC+8）：

| 时间 | 实际证据 |
| --- | --- |
| 15:32:01.740 | 原 Agent 对仍 live 的请求拒签：`watchtower request requires local authorization`，`adapted=false` |
| 15:32:05.030 | 第一份完整 ledger 已确认 T 支出，A 未结算 |
| 15:33:01 / 15:34:01 | FNN 两次 PeriodicCheck 都已观察到 T 的同一支出；不是扫描线程未运行 |
| T 支出被观察后 2.093～119.650s | 10 次 WS 通知/重订阅快照仍交付同一旧 request，输入仍指向已被 T 消费的 commitment |
| 15:34:12.499 | 未批准观察完成 130.759s，131 次采样均无 A 支出；HTTP 审计中 A 的签名提交为 0 |
| 15:34:12.502 | `get_watchtower_signing_status` 仍返回同一旧 request；独立 `get_live_cell` 对其输入返回 `unknown`，测试在要求有效工作处失败 |

从第一份 T 支出 ledger 到末次独立 live 查询为 **127.472s**（若从更早的交易确认 RPC 计约 127.65s），跨两次 60s 扫描；因此不是只看到一次瞬态失效。原始文件在本轮根目录下 `stability-v2-1/test_missing_approval_then_adapted_settlement/`：`fiber-1/watchtower-evidence.jsonl` 第 1941 行为原 Agent 拒签，第 1961 行为 T 确认交易，第 1974 行为第一份 T 支出 ledger，第 4261～4263 行为完整负向窗口、旧状态与 unknown 输入；`A-ws.json` 保留全部重订阅事件，`A-http.json` 证明零签名提交；`fiber-1/node.log` 第 1749～1782 行记录两次后续扫描及 T 支出识别。

固定源码对应机制：

- [RPC 读取](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L395)直接从 signer store 生成状态；[状态转换](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L498)取 `first_pending()`，没有验证输入当前 live。
- [pending 结构与取首项](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-types/src/watchtower.rs#L140)使用 `BTreeMap` 按 request ID 排序，首项不是“最新”或“仍有效”的含义。
- [actor 更新](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L2188)对相同 pending 直接返回，否则插入新 pending；该路径未清理已死输入的旧项。所核对的显式 pending 移除在[提交签名](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L468)路径，而本条 A 未签名。

**结论边界：** 已实证服务端在死输入后持续暴露陈旧待签工作，按产品侧问题留证处理；“新有效请求已生成但被排序遮蔽”目前只是源码支持的机制推断，未读取持久化全部 pending 证实。本条在负向窗口末尾的 live 前提失败，未执行显式批准、有限重建或完整批准后 240s 窗口，不能宣称批准后永久不恢复、资金丢失或超出恢复 SLA。不能跳过旧请求、从 DB 挑新请求或删除 signer 状态使测试通过。后两轮保持未运行，产品代码不改；后续由用户决定修复跟踪或独立扩大诊断窗口。

GPT 6.1 sol 已只读复核上述失败时间线、WS/RPC/真实链证据与源码边界，未触发 Daybreak。未自动新建 issue，也不将该场景关联为开通计时器 #1674 的同一问题。


### 本轮最终校验与相关回归

共享测试驱动费用模板调整后，另在普通原快照环境运行 `test_channel_signing_recovery.py::TestChannelSigningRecovery::test_checked_open_pay_and_close`，命令参数同上、RUN=`related-core`，结果 **`1 passed in 112.85s`，退出 0**。真实付款金额 1,000,000 Shannon，路由费 5,000，四端余额增量 `(1000000, -1000000, -1005000, 1005000)`；协作关闭输出 `(50001000000, 49998999472)`、费用 528，均确认。该结果单列，不抵消 watchtower 02 失败。

最终 `python3 scripts/check_test_map.py`：103 个评审 ID/99 个映射，四条 watchtower 映射仍完整，退出 1 原因为既有 PMP-01～05/SETTLE-01 孤儿与历史 report overlay 的 16 个重复 ID。skill `check_test_design.py --root <repo> --review reviews/lsp/watchtower-settlement.md` 识别四行，退出 1 为相同历史重复及已人工接受的 SPEC-02 决策提示；输出分别保存在 `test-map-final.*`、`test-design-final.*`。本轮未新增/删除行为 ID，未跨范围清理历史证据。Python 编译、相对文件链接检查与 `git diff --check` 通过。

`final-v2-sources` 的六份测试源码与当前实现逐字节一致，构建清单五项产物摘要匹配，产品 checkout 保持干净固定 04；`shasum -a 256 -c original-inputs.sha256` 对原快照、本地及固定源码合约全部 OK。两次主动中断的残留工作数据归档后清理，结束时固定端口 8114/8125/8227～8230 无监听、`tmp` 为 0B；本轮完整证据约 686 MiB，未提交或推送，保留无关改动。

GPT 6.1 sol 已独立复核代码、自检、聚焦及复跑失败的原始资金/签名/观察证据、版本与文档结论，未触发 Daybreak。交接为**隔离环境已修复，自检通过，正式稳定性验收被 02 产品侧陈旧工作问题阻断**，不宣布四条 1+3 全部通过。

## 04c2064 watchtower 02 陈旧请求遮蔽与批准后恢复诊断（2026-10-27）

后续跟踪：用户已提交 [Fiber #1706](https://github.com/nervosnetwork/fiber/issues/1706)，2026-10-27 经 GitHub API 核实为 open。下文“未自动创建 issue”保留诊断当时事实；现在此场景已有独立 issue，不再是未跟踪问题。

**结论：已确认 FNN 产品 bug。** 同一通道同时存在旧死输入请求和新的有效后继请求；RPC/WS 只展示按 request ID 排序的旧首项，SDK 正确拒绝死输入。显式批准后完整观察 **240.356 秒**，三次正常处理仍全部失败，A 没有 watchtower 签名提交或结算。新的后继请求已由真实 SDK `prepare_onchain` 独立验证成功，因此这次不再是“可能尚未生成新请求”或“只看到瞬态陈旧状态”。固定源码为 `04c206465b48da85b99aa58e80afe9801a2cb2db`，产品 checkout、FNN/SDK/正式驱动产物及正式四条测试均未修改。

本节补足上一节未执行的批准后窗口；原始失败和当时的结论边界仍保留。它不是开通计时器 #1674 的同一场景，也不证明永久卡死或资金丢失。正式 `LSP-WATCHTOWER-02` 继续按产品缺陷阻断，未将这次诊断计入四条正式 1+3 的通过数；原 Agent 自动恢复仍未覆盖。

### 复现步骤与取证方法

1. 使用独立快照副本和已核对的固定 04 合约，正常开通 A/T 非零份额、无 TLC 通道，保持 A 未批准。T 自然强关和结算自身份额，原 Agent 对仍有效的首个请求真实拒签；完成原 130 秒负向窗口。
2. 通过只读 RocksDB helper 导出该通道完整 External signer 状态、排序后的全部 pending 和原始序列化值；对每个请求重算 ID，独立查询所有输入 live 状态，并与公开 RPC 首项对照。仅在诊断专用配置增加 `admin` 模块，调用产品 `backup` 获取一致 checkpoint；不改产品或正式配置，不暂停扫描、不调整竞争、不删除旧请求。
3. 记录负向窗口末尾的陈旧请求，继续调用原 `Agent.authorize(Watchtower)`，批准原 D 和每笔 10,000 Shannon。授权返回后开始 240 秒单调时钟窗口；在约 0/120/240 秒显式处理当前 RPC 工作，原 WS 处理/重连保持运行。每约 5 秒查询状态和独立资金账本，始终不从 DB 挑选新项用于签名。
4. 批准后约 120 秒，把完整 SDK 存储复制到独立目录，对**全部** pending 逐项执行与既有适配器相同的唯一 recovery ancestor、可信 deps、所有输入、目的地/sponsor、费用及 SDK `prepare_onchain` 检查，然后立即返回。无签名、提交、rounds 更新或故障注入；Fiber RPC URL 故意为不可用的 `127.0.0.1:1`，不初始化 Agent，不运行事件循环。它读取副本身份密钥以打开 signer，但不输出密钥。执行前后副本四个文件摘要完全相同。
5. 满 240 秒后再采集 RPC、全部 pending、资金账本和产品 checkpoint。读取前后 checkpoint 的实际 DB，与相应直读的 `raw_state` 逐字节一致，排除只复制运行中目录或旧快照导致的假象。

诊断脚本及原始证据根（相对仓库根，不提交）：`report/lsp-watchtower02-diagnosis-04c2064-20261027/`。入口为 `test_watchtower02_diagnosis.py`，只继承已批准夹具并复制 02 的拒签/负向部分；不替换正式映射测试。命令如下（本机端口需要允许本地节点运行的执行环境；复跑使用新 RUN）：

```bash
CKB_CLI_HOME=/tmp/lsp-watchtower02-diagnosis-cli-20261027 \
LSP_RUN_ARTIFACTS="$PWD/report/lsp-watchtower02-diagnosis-04c2064-20261027/attempt-4" \
PYTHONUNBUFFERED=1 PYTHONPATH="$PWD" venv/bin/python -m pytest -o addopts= -vv -s -x --tb=short \
  --junitxml=report/lsp-watchtower02-diagnosis-04c2064-20261027/attempt-4.xml \
  report/lsp-watchtower02-diagnosis-04c2064-20261027/test_watchtower02_diagnosis.py::TestWatchtower02Diagnosis::test_missing_approval_then_adapted_settlement
```

### 关键证据

本轮 channel：`0x03622ee6ffe1e8cc8b3e3abfb74f25e8d1bfb10e247442fbec05308a2f0eb016`。

| 项目 | 实际值 |
| --- | --- |
| 旧请求（排序首项） | `0x304d7137a4fbcc887c631fcf2cf9b45729b539ba12bda2aae0529e7fd9ca9ea2` |
| 旧 commitment 输入 | `0xa0f5d333096572aabd2348233d8a2d59e19a8a7928d5a2408f621bda17582fd0:0` |
| T 已确认结算 / 新 commitment 输入 | `0x96a3ca2560588cfa381bf4990766df58c900517b8103b4b1deceafbd774d2bab:0` |
| 被遮蔽的新请求 | `0x9858a1783989d0dc1838b9be12ec610479a2f5f0f17c4334eab4bc8173dd0b35` |
| SDK 独立验证 | 旧项 `valid=false`，`input is not live`；新项 `valid=true`，授权费用 638 Shannon |
| 窗口末输入状态 | 旧项两个 input 均 `unknown`；新项两个 input 均 `live` |
| 实际资金 | T 支出 50,000,000,000 Shannon，费用 785；后继保留 A 的 49,999,999,543 Shannon，A 未结算 |
| 提交 | A 的全部 HTTP 审计中 `submit_watchtower_signature` 为 0 |

时间为 Asia/Shanghai（UTC+8）。下列行号对应 `attempt-4/test_missing_approval_then_adapted_settlement/fiber-1/watchtower-evidence.jsonl`：

| 时间 / 相对批准 | 证据行 | 结果 |
| --- | --- | --- |
| 20:01:54.191 | 1944 | 原 Agent 对有效请求因无本地批准拒签 |
| 20:04:05.043 | 4251 | 负向观察 130.852s，131 次采样，最大间隔 1.181s，无 A 支出 |
| 20:04:05.119 | 4258～4261 | 双 pending、旧死/新 live、RPC 旧首项；一致备份 `1793102645121` |
| 20:04:05.144 | 4262～4263 | 原批准 API 返回 `saved=true`，开始 240s 窗口 |
| +0.227 / +120.247 / +240.267s | control 原始请求/响应；汇总 5309 | 三次显式处理均为 `invalid signing content: independent chain verification: input is not live` |
| 20:06:06.721 | 4786 | 全部 pending 独立 SDK 检查完成，旧失败、新成功，副本未变 |
| 20:08:05.500 | 5281～5282 | 最后采样覆盖 +240.356s，仍旧死/新 live、A 未结算 |
| 20:08:05.529～.795 | 5283～5309 | 结束一致备份 `1793102885501` 和最终原始状态；仍双 pending、无已签项 |

49 次恢复观测全部返回旧 request ID，49 次账本均只有 T 支出。目标采样约 5 秒，实际最大间隔 **6.347 秒**（+120s 独立 SDK 检查耗时 1.164s）；本诊断不宣称满足正式用例的 2 秒采样约束。整个批准后 240.356s 窗口完成，没有提前成功退出或因单次死输入报错结束。FNN `node.log` 第 1809、1827、1889、1907 行分别为 20:04:53、20:05:53、20:06:53、20:07:53 的四轮扫描，扫描线程持续运行。

`A-http.json`、`A-ws.json`、SDK `agent.log`、`independent-chain.jsonl` 与独立 CKB 审计完整保留。SDK 只检输入/逐项结果/原始链证据/副本摘要在 `attempt-4-sdk-validation/`；备份导出为 `attempt-4-checkpoint-1793102645121.json` 和 `attempt-4-checkpoint-1793102885501.json`。更早自动备份 `1793102539842` 仅含旧项；开通前备份 `1793102446842` 尚无该 signer，reader 正确报 0 项，不计产品失败。原始失败轮也只读导出为 `historical-pending.json`，同样证明旧 a0e391… 与后继 ed7843… 并存；历史数据未覆盖。

### 源码归因与边界

- [WatchtowerExternalSignerState](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-types/src/watchtower.rs#L140)：pending 是按 request ID 排序的 `BTreeMap`；[first_pending](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-types/src/watchtower.rs#L160)直接取首项。
- [RPC 状态转换](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L498)只暴露这一项，没有检查输入仍 live；[WS 状态发布](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/signing/mod.rs#L171)调用同一转换，因此重订阅也继续收到旧首项。
- [actor 新增 pending](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/watchtower/actor.rs#L2188)保留已存在项、插入新项；此路径没有淘汰死输入旧项。后继已真实生成，排除“扫描没运行/后继工作尚未构建”的归因。
- [签名提交路径](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/crates/fiber-lib/src/rpc/watchtower.rs#L468)才移除对应 pending，而正确 SDK 不会为死输入签名。[SDK 真实链检查](https://github.com/chenyukang/fiber/blob/04c206465b48da85b99aa58e80afe9801a2cb2db/tests/fiber-lsp-sdk-agent/src/chain.rs#L284)拒绝非 live 输入；这一拒绝属于正确保护。

因果链为：**旧输入被 T 合法花费 → 旧 pending 遗留 → 新有效 pending 排在后面 → RPC/WS 持续只展示旧项 → SDK 正确拒签 → A 的正常批准后流程无法推进。** 建议作为 FNN 的陈旧待签状态清理/有效工作选择缺陷处理。未修改产品、未尝试删 DB 或绕过公开查询签新项、未自动创建 GitHub issue。240 秒是已批准的测试窗口，不冒称产品文档承诺的恢复 SLA；结论不是资金丢失、永久锁死，也不是原 Agent 自动恢复已经验证。

### 全部尝试、退出码与复核

| 尝试 | 实际原始结果 | 归因 |
| --- | --- | --- |
| attempt-1 | `1 error in 38.01s`，退出 1 | 沙箱内 CKB 准备阶段 RPC 超时，未进入产品场景 |
| attempt-2 | `no tests ran in 137.07s`，退出 2 | 发现当前模板未启用 admin 备份模块，精确中断本轮 pytest 后修正诊断配置；已归档当时全部节点/SDK证据 |
| attempt-3 | `1 error in 37.91s`，退出 1 | 启动命令误回到沙箱内，同样在 CKB 准备阶段失败；原日志重命名归档，未丢弃 |
| attempt-4 | `1 passed in 485.37s`，退出 0 | **仅代表目标陈旧场景和完整诊断观测成功取得，产品恢复结果为失败**；不计正式02通过 |

只读工具的全部构建日志也保留：首次误用默认 Rust 1.91.1（固定源码要求 1.95.0），第二次发现当前 RocksDB iterator 无 `status()` 方法，修正后 reader 编译成功；validator 在执行前对齐内部 Settlement 枚举与 RPC tagged JSON，最终编译成功。它们是诊断工具准备问题，不计产品失败；没有重编/替换 FNN 或正式 SDK driver。`original-sources/` 保留本轮开始时的正式夹具、适配器、驱动与构建清单，正式文件保持一致。

GPT 6.1 sol 已独立复核只读导出、只检 helper、复制存储摘要、真实 pending/链/SDK 结果、三次处理与完整窗口，未触发 Daybreak。本次新增的结论是**已证实有效后继请求被旧项遮蔽，显式批准后在完整窗口内仍不恢复，属于产品 bug**；四条正式稳定性验收仍未完成。

本轮最终检查：`python3 scripts/check_test_map.py` 仍为 103 个评审 ID/99 个映射，退出 1 仅为既有 PMP-01～05/SETTLE-01 孤儿及历史 report overlay 的 16 个重复 ID；design 检查仍识别四行，退出 1 为相同重复项和已人工接受的 SPEC-02 提示，完整输出在本次证据根 `test-map.*` / `test-design.*`。本轮未修改行为行、TEST-MAP 或正式自动化。`git diff --check`、诊断 Python 编译、正式源码/构建清单与本轮初始副本的比较均通过；原快照、本地和固定源码合约摘要全部 OK，产品工作树干净。

## 3ce369e：#1706 修复定点验证（2026-10-28）

用户要求根据 [jjy 的修复说明](https://github.com/nervosnetwork/fiber/issues/1706#issuecomment-6461510181)重新编译并复用调整后的本地用例。固定验证提交为 `3ce369e5c4b224638817ab99aec8c3e0fcb85d3a`，父提交是历史失败版本 `04c2064`；查询时 PR head 已为 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，本轮不将定点结果转记到该 head。

当前无 TLC 的四条及适配自检位于 `test_watchtower_settlement.py`。本轮未修改用例预期或断言、未改产品代码；仅给构建脚本增加显式版本/缓存目录参数，给普通 LSP 夹具增加单次命令的 `LSP_TEST_REVISION`，默认仍是 04。

修复仅修改 `watchtower/actor.rs` 及其上游测试：扫描到已确认交易的输入后，清理引用已花费输入的 pending 和 signed 项，保留有效并发工作和 last_applied，再发布状态。SDK API、合约、Cargo.lock 未变。使用独立源码 `download/fiber/source-pr-1623-3ce369e/` 和独立产物 `download/fiber/pr-1623-3ce369e/`；原源码仍干净固定 04，原快照、合约及 04 构建清单摘要核对不变。

本地证据根：`report/lsp-issue1706-3ce369e-20261028/`，保留构建/收集/检查输出与退出码，每批 pytest 的 `.log/.xml/.exit`、各方法的 HTTP/WS、SDK/FNN/CKB 和账本证据。构建实际命令如下，退出 0；产物为 `fnn Fiber v0.10.0-rc1 (3ce369e 2026-10-28)`，同源 SDK/驱动及摘要由测试启动再次校验。

```bash
venv/bin/python scripts/build_lsp_test_binaries.py \
  --source download/fiber/source-pr-1623-3ce369e \
  --revision 3ce369e5c4b224638817ab99aec8c3e0fcb85d3a \
  --target-dir download/fiber/source-pr-1623/target
```

运行均设置独立 `CKB_CLI_HOME`、`LSP_RUN_ARTIFACTS` 和 `LSP_TEST_REVISION=3ce369e5c4b224638817ab99aec8c3e0fcb85d3a`，以 `venv/bin/python -m pytest -o addopts= -vv -s --tb=short` 执行 `test_cases/fiber/devnet/lsp/test_watchtower_settlement.py` 中以下选择项；JUnit 写同名 `.xml`，stdout/stderr 写 `.log`，shell 保存真实退出码。后续复现使用新的报告目录，不能覆盖本轮。

| 批次 | pytest 选择项 | 结果 |
| --- | --- | --- |
| selfcheck | `TestWatchtowerAdapter::test_adapter_rejects_invalid_authorization` | `1 passed in 114.57s`，exit 0 |
| focus02 | `TestWatchtowerSettlement::test_missing_approval_then_adapted_settlement` | `1 passed in 363.48s`，exit 0 |
| related（加 `-x`，首次失败即停） | `TestWatchtowerSettlement::test_authorized_settlement`、`test_cross_tenant_read`、`test_cross_tenant_submit` | `3 passed in 1117.54s`，exit 0 |

### 02 命中原缺陷条件的证据

以下路径相对证据根的 `focus02/test_missing_approval_then_adapted_settlement/`：

- 旧请求 R0=`0x4196c8c1ae1ad5c727a69a2c009dd75ff1c7f2c4f9be2f83b3e6689994e1230c`，输入为 commitment `0x275f83f2600e910ccc5b3794df6db36ea942ca170a1035f783aeb6c0e92ff8aa:0`；T 的已确认交易 `0x03536414984cc2dea83b8bc0e2270ce18e099e29a1cd10eaf9751226efc1bbaa` 花费该输入，留下 A 份额的后继输出。
- 新请求 R1=`0xbabfa4940ce7ed1436558565415ff6633abd1bd1f45254af653af0115e52da45` 使用该 T 交易的输出 0。**R0 < R1**，但原 SDK 订阅已收到 R1；批准前两条均有原 Agent 缺本地授权的拒签事件。不能把通过归结为新 ID 更小而碰巧绕过遮蔽。
- `fiber-1/watchtower-evidence.jsonl` 第 4251 行：未批准观察 130.815s、131 次采样、最大间隔 1.178s，A 无结算。第 4254 行批准 saved=true；第 4255 行显式处理返回 R1、授权费用 638。
- 同文件第 6884 行：两方最终账本及 65.708s 稳定观察、66 次采样、最大间隔 1.080s。A 的真实结算交易为 `0xbbb28df74156df883a5ef25c22c639ea36e9a312a7f7d7e02129837ff109fd31`，后继余额 R=0。原断言已核对 R1 的 Applied 签名确实进入链上 witness、目的地、逐笔输入输出及费用守恒。
- 最终两笔 P 为 `50,000,000,000` 与 `49,999,999,543` Shannon；费用为 785 与 638，强关费 457。账本将 sponsor 输入/找零与用户份额分开计算，不把钱包总额当结算额。HTTP 与 WS 原始证据分别在 `A-http.json`、`A-ws.json`，SDK 原始拒签/事件在 `fiber-1/sdk-A/agent.log`。

此结果证明本轮自然取得的陈旧首项场景在修复提交上能继续取得有效请求并完成结算；不代表原 Agent 自动事件链恢复、不代表含 TLC 退款或全量 LSP 回归通过，也没有重新执行历史四条完整 1+3 稳定性批次。fee-input-only 清理、已签缓存、重组及全部并发排列不由本条 Python 回归单独证明。

### 最终核对与独立复核

三份 JUnit 共 **5 个唯一方法通过，0 failure / error / skip**，三批退出均为 0。相关 01、03 的稳定窗口分别为 65.686s、65.704s；04 的 B/A 分别为 65.717s、65.694s，每个窗口均 66 个样本，最大采样间隔不超过 1.065s。03 的 B→A 读取、04 的 B→A 有效签名提交均被拒绝，所属租户正向对照及最终结算通过。所有原始失败版本记录保留，本轮没有重试覆盖失败。

GPT 6.1 sol 已独立复核修复源码、版本选择、5 个方法的原始日志/JUnit/退出码、02 的 R0<R1 与真实花费/后继/Applied witness 因果链，以及 01/03/04 的隔离和资金证据，最终无阻断项，未触发 Daybreak。

`py_compile`、目标文件收集（5 条）、`git diff --check` 通过；`check_test_map.py` 为 106 评审 / 102 映射，退出 1，仍为既有六个孤儿映射及十六个历史重复 ID。设计检查识别本批 4 行，退出 1，为相同历史重复及已由用户接受的 SPEC-02 分段决策提示；不将两项检查写成全绿；这些数字是当时完整本地工作区的统计，不是本 PR 的覆盖率。原产品源码与独立修复源码均干净，快照/合约/04 构建清单摘要仍一致。本轮节点与固定端口已清理，无关本地数据及原有 `tmp/` 内容保留。


## 普通 LSP 增量的 PR 整理验证（2026-10-28）

本次来源分支以测试仓库 `cf93727` 为基准，提交浏览器鉴权、真实付款延迟恢复、无 TLC watchtower 的19个方法/13个新行为ID及必要共用适配。退款 VM/nightly 控制与用例保留在原工作区，不纳入此PR；两份Rust驱动恢复为已经验证的普通 `final-v2-sources` 快照，不含退款专用入口。默认产品仍固定04；上面的24、04和3ce运行结果分别有效，不重新合并计数。

独立工作树的提交前检查：普通LSP `pytest --collect-only -q` 收集60条、退出0；全仓 `black --check --no-cache .` 通过413个文件、退出0；Python格式化前后AST一致。4个既有LSP文件的格式修正单独提交，未修改用例语义。映射检查为103评审/99映射、退出1，只剩原PMP-01～05与SETTLE-01六个孤儿；本工作树不含本地report副本，无重复评审ID。三份相关评审的设计检查识别24行、退出0，已批准的分段观察与保留分支提示继续保留。

精简后的driver在独立临时manifest及APFS复制缓存中执行 `cargo build --locked --offline --manifest-path <临时目录>/Cargo.toml`，退出0，实际编译17.90秒；只读取原固定04源码，没有覆盖原产品产物。原仓库本地证据 `report/lsp-reviewed-pr-validation-eeh9jcij/` 保存构建和检查输出。GPT6.1 sol独立复核依赖、版本、源码范围及格式语义，未发现阻断；本次没有重新运行节点、业务回归或夜间样本，收集与编译不算新的产品通过。


## 04c2064 订阅过滤 Gate3：准备失败（2026-10-28）

用户已批准20～28九行、28的固定版本数组兼容及150分钟执行预算；实现位于 `test_signing_subscription_filters.py`，共12方法，23有四处TEST-MAP，其余各一处。GPT 6.1 sol代码复核发现清理失败/超时的保留和停进程问题，已改为每方法独立且带唯一批次的目录、始终保留原数据、精确自有进程紧急停止；完整pytest生命周期由执行器外层截止覆盖。修正后代码和执行器复核均无剩余阻塞，未触发Daybreak。

**只执行了一次，已停止：环境产物版本校验失败，不是产品行为失败。** 本地证据根为当前worktree的 `report/lsp-filters-04c2064-20261028T203635/`；该worktree为 `/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test`，不是原脏工作区。启动北京时间2026-10-28 20:36:35，150分钟起点 `788486.062594041`、绝对截止 `797486.062594041`；环境阶段截止 `789386.067535583`，实际约29.41秒失败，未到预算上限，也未重置或重启。

执行命令为原已有Python环境运行 `report/.../runner.py` 的启动原件 `/private/tmp/lsp_filters_gate3_run.py`。准备中的失败命令：

```text
/Users/sunchengzhu/project/fiber-py-integration-test/venv/bin/python scripts/build_lsp_test_binaries.py   --source /Users/sunchengzhu/project/fiber-py-integration-test/download/fiber/source-pr-1623   --revision 04c206465b48da85b99aa58e80afe9801a2cb2db   --target-dir /private/tmp/lsp-filter-target-20261028T203635
```

原始关键输出及退出码：

```text
Finished `dev` profile [unoptimized] target(s) in 0.94s
Compiling lsp-integration-driver v0.1.0 (.../driver-build)
Finished `dev` profile [unoptimized] target(s) in 16.83s
AssertionError: fnn Fiber v0.10.0-rc1 (3ce369e 2026-10-28)
build-matched-bundle.exit: 1
runner exit: 1
```

| 阶段 | 实际结果 |
| --- | --- |
| 固定源码/原状态核对、独立缓存克隆、CKB复制 | 已完成，单步退出0；产品checkout为干净完整04 |
| 本地driver编译尝试 | Cargo编译退出成功；不等于匹配bundle建立完成或任何业务通过 |
| 产物版本校验 | 失败，构建脚本退出1；自报3ce而非04，无有效build.json交付 |
| 适配自检、pytest收集 | 未运行；执行器在构建失败处停止 |
| 相关聚焦3条 | 0执行；不是0/3断言失败 |
| 正式1+3，预定48实例 | 0执行；没有正式通过结果 |

只读复核确认：原source目录下target、APFS克隆target、新worktree复制出的fnn三个SHA256完全相同，为 `8c318cf67563846c1883cbc98cf66b34550a7ec7b3c6e3c49fb76c34cf42e5b3`；原04 bundle的fnn仍自报04，SHA256为 `d7d60aaba98120db740412a4ca4f7cf26e2973f1f5d5d9ad93b229d62ddb1d22`。这证明沿用了已有缓存中的不匹配FNN，不能据此断言仅版本字符串过期，也不能认可其余缓存内容正确。不得改版本字符串或绕过现有断言来取通过。

原产品源码仍干净固定04；原工作区Git状态前后完全一致，原bundle及退款夜跑未动。本次无pytest/节点启动；停止后默认测试端口无监听，未发现本次runner或构建遗留进程。失败产物保留在当前worktree `download/fiber/pr-1623-04c2064/`，**未通过版本校验、不可用于验证**；独立缓存及CKB副本也保留，不覆盖原产物。

证据包括 `run.json`（实际阶段/命令/截止/源码哈希）、`runner.py`、各命令 `.log/.exit`、`stop.txt`、`post-stop-artifacts.log`、`original-status-after.log`、`failed-attempt-sources/`（源码、构建脚本、执行时评审快照）及 `review.txt`。GPT 6.1 sol对停止与环境归因再次独立复核，确认未运行后续批次；没有把#1674/#1706或24/3ce历史通过套到本批。

映射勾选只表示这九行已有实现，不能解释为验证通过。本轮按“失败即停”结束，不自动重建或续跑。后续若另行批准，应在新的独立输出中可信重建固定04所需上游产物，重新核对版本/清单/源码摘要后再按新批次执行；本次失败记录与产物继续保留。

停止后仅做文档/映射维护检查：`git diff --check`退出0；设计检查26行、退出0；`python3 scripts/check_test_map.py`为112评审/108映射，退出1仍只因既有PMP-01～05、SETTLE-01六个孤立映射，无重复ID。20～28全部有映射，23对应四个方法。原始输出保存在本次证据根的 `post-stop-design.log/.exit`、`post-stop-map.log/.exit`；这些是停止后的维护检查，不是恢复执行适配自检或功能验证。

## 84333ee 订阅过滤 Gate3：完成（2026-10-29）

用户明确授权更新到LSP分支最新代码后，查询PR #1623的 `chenyukang/fiber:lsp-support` 并独立fetch，固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9` 执行，不在批次中追随head变化。仅本批选择843，原04源码、bundle、脏工作区及退款夜跑保持原样；此前04准备失败不转记通过。GPT 6.1 sol已复核04→843差异：订阅RPC/types/鉴权、相关SDK核心及Cargo.lock未变，已批准20～28预期继续适用，无需修改行集或产品。

**结果：相关3/3，正式固定1+3共48/48通过；无失败、错误或跳过。** 从北京时间2026-10-28 23:51:36准备开始，到2026-10-29约01:11:26执行结束，共4789.563秒（79.83分钟），未触及150分钟上限。单调时钟起点800187.207479708、总截止809187.207479708；各阶段预算不重置，实际完整pytest进程含类初始化和清理均在阶段截止内。

| 阶段 | 实际结果 | 进程墙钟秒 | 退出码 |
| --- | --- | --- | --- |
| 独立产物与适配自检 | 版本/摘要、语法、格式、设计和12方法收集完成；映射检查只有既有六个孤立映射 | 92.548 | 构建/其他检查0；映射1，既有集合精确校验通过 |
| 相关订阅回归 | 3/3：真实R2、独立取消、双租户initial/live隔离 | 275.544 | 0 |
| focus | 12/12 | 1106.447 | 0 |
| stability-1 | 12/12 | 1110.384 | 0 |
| stability-2 | 12/12 | 1101.383 | 0 |
| stability-3 | 12/12 | 1103.249 | 0 |

本地证据根为本worktree的 `report/lsp-filters-84333ee-20261028T235136/`；`run.json` 保存完整实际命令、固定顺序、各命令PID/起止/截止/退出码和冻结源码摘要，最终status=passed；所有命令的.log/.exit、每批.xml/.html、48份.filters.json、各方法SDK/FNN/CKB证据及原始数据目录完整保留。入口是 `venv/bin/python /private/tmp/lsp_filters_latest_run.py`（实际Python为原仓库venv绝对路径），执行器原文已复制为证据根的 `runner.py`。各pytest实际均使用 `-x -vv -s -o addopts=`、独立HTML/JUnit路径、`LSP_TEST_REVISION=84333eea8488a8afc7e4474aa4bbd0e7e973cee9` 和阶段/整批绝对截止；逐项argv以run.json为准，不用默认report覆盖历史。

匹配构建实际命令为：

```bash
/Users/sunchengzhu/project/fiber-py-integration-test/venv/bin/python scripts/build_lsp_test_binaries.py \
  --source /Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/download/fiber/source-pr-1623-84333ee \
  --revision 84333eea8488a8afc7e4474aa4bbd0e7e973cee9 \
  --target-dir /private/tmp/lsp-filter-84333ee-target-20261028T235136
```

构建退出0，FNN实际输出 `fnn Fiber v0.10.0-rc1 (84333ee 2026-10-28)`。新target由原缓存APFS复制后，仅在该副本清理七个本地包并实际重新编译；Cargo警告忽略pkgid的URL/version限定，同名registry版本也被清理/重编，共移除13,871文件、9.7GiB，不能称全部第三方缓存未动。原target未清理。七包均有新源码路径的实际Compiling记录，五个交付文件、两份锁文件和驱动源码摘要与manifest一致，源码构建前后干净；批次前后19个LSP Python/Rust源码摘要一致。

TEST-MAP：20～28九个ID均已映射，23有四个方法，其余各一，共12方法；每轮12实例，共48，不等于48个独立行为ID。设计检查26行退出0；项目映射检查112评审/108映射、退出1，仅既有PMP-01～05与SETTLE-01六个孤立映射，无重复ID。本批未扩改其他评审文档，映射数和勾选不代表功能覆盖率。

GPT 6.1 sol产物、首轮及最终证据复核均通过，未触发Daybreak。最终独立审计确认48份完整快照、52条租户R1/R2与签名匹配、304条正确归属通知、8个空订阅零通知并取消、24项目标typed work恰一、64个非法输入精确-32602以及52条正确原通道终态，详情在 `independent-review.txt`。证据边界：filters JSON保存完整输入/响应、全连接通知、R1/S1/R2及终态，但没有逐次保存每个Applied响应、中间查询、committed查询或5秒稳定窗口的全部原始RPC；这些由冻结源码中已执行的断言及通过JUnit支持，不能表述为全量RPC重放证明。21/26去重仅证明有界窗口；同身份多通道严格子集、命名参数运行入口、跨重连exactly-once未覆盖。资金检查证明原通道正常完成、原funding outpoint、余额镜像与无pending TLC，不代表TLC强关退款守恒。未运行退款夜跑、watchtower或全量普通LSP；旧#1674/#1706归因与历史结果保持原样。

收尾维护：`git diff --check`退出0，设计26行退出0，映射检查退出1仍为上述既有六个孤立项。原工作区Git状态与启动快照一致，原04和本次843产品源码均干净；19个冻结源码摘要一致，无本worktree残留节点进程。最初只读进程列表检查遇到非UTF-8字节解码错误，改为替换解码完成核验，不涉及产品测试重跑；见 `final-integrity.json`。


## 84333ee 独立收款诊断 Gate3：因测试适配缺陷停批（2026-10-29）

用户已确认WATCHTOWER-01/02/05/06行集、费用分配和预算，并授权固定`84333eea8488a8afc7e4474aa4bbd0e7e973cee9`先实现、GPT6.1sol复核，再在54分钟内依次执行适配自检、旧02相关回归、05单次诊断；01/06等待修复版。本批未切版本、未改产品、原快照或退款夜跑。

代码已新增05的真实SDK prepare-only诊断、D_A/S独立意图与错付候选核验、零签名/提交和65秒观察；旧02保留D=S分段验证。原01方法仍是历史D=S测试，已移除对新版独立到账01的过时TEST-MAP；当前02～05有映射，01/06未映射。映射不表示本次完成产品验证。

本地证据：`report/lsp-watchtower-05-84333ee-20261029T193040/`。实际命令为`/Users/sunchengzhu/project/fiber-py-integration-test/venv/bin/python /tmp/lsp_watchtower_05_runner.py`；运行时完整执行器保存在该证据目录的`runner.py`，各子命令/绝对截止/退出码见`run.json`。北京时间19:30:40启动，约90秒后停止，未到54分钟上限。

| 实际阶段 | 结果与边界 |
| --- | --- |
| 版本/资源预检 | 通过；干净源码与FNN自报均为84333ee，已有bundle摘要匹配 |
| 独立driver-only构建 | 阶段约26.8秒，构建命令退出0；Cargo原始输出`Finished dev profile ... in 19.85s`。仅构建本地driver及依赖，原FNN/agent复用并核验，新bundle在本次report内，原bundle未覆盖 |
| 适配静态自检 | 约2.1秒；合法参数退出0，同钱包/扩大费限/未知字段三项各按预期退出1；AST及两方法收集成功。此处未调用真实链上的SDK prepare，不能当05通过 |
| 旧02相关回归 | 启动后约59.2秒，在准备阶段主动SIGINT中断，退出2；日志`KeyboardInterrupt`、`no tests ran in 58.99s`，JUnit `tests=0, failures=0, errors=0`。不是产品断言失败或通过 |
| 05单次诊断 | 未启动，未取得真实SDK拒绝样本，未运行65秒观察 |
| 收尾 | 整批`batch.exit=1`、`status=stopped`；最终核验通过，本批PGID残留列表为空、测试端口空闲，产品源码干净、原工作区Git状态和旧bundle摘要保持不变 |

**停批原因是本地测试实现错误，先前代码复核也漏掉了此项。** 在旧02准备过程中继续核对843接口，发现产品`OnchainSpendAuthorization.destination`使用`EntityHex`序列化；新Rust诊断原样导出的`authorization.destination`因此为packed Script十六进制字符串，但Python05将其与RPC Script对象直接比较。这会导致假失败，所以在05启动前中止本批；操作与归因见`manual-stop.json`，不归产品、#1674或#1706。收集成功、编译成功和参数自检不能证明这项跨语言schema正确。

停批后仅修正代码并静态复核，**没有重建或重跑**：保留原始authorization，另从实际`auth.destination`导出`authorization_destination_rpc`，Python与事先批准D_A完整比较，不删除目的地断言、也不用intent反证自身。无节点selfcheck补入真实授权类型的内存序列化、packed字段与RPC字段一致性检查；不访问链、不签名或提交。修正后的下一批执行计划单独保存为`runner-after-schema-fix.py`，没有执行。当前report内bundle仍对应停止时的旧代码，不能当修正后匹配产物使用。

全部运行证据与原bundle保留；冻结源码逐文件原字节保留为`sources/<原路径>.snapshot`，防止评审/映射扫描把证据副本当活跃源。初次静态映射检查因此报告了本批证据副本引起的6个重复ID，随后只调整本批证据文件后缀、保留原字节，并重新检查。中断时仍存在的4份节点/SDK日志另复制到`interrupted-setup-logs/`，原临时目录保留；不会将旧02尚未完成的环境准备记作业务样本。

修正后GPT6.1sol静态复核通过，未重新编译或运行。最终设计检查6行退出0；映射检查114/108、无重复ID，退出1仍仅因六个既有孤立映射（PMP-01～05、SETTLE-01）；Python AST与git diff --check通过。已核对21份冻结源码的原始摘要全部保留。临时CKB链由中断清理流程移除，未保留完整临时CKB数据库；原链快照未变，已保存构建/运行日志、合约预检、JUnit/HTML、停止原因及仍存在的节点/SDK日志，不把准备现场视为完整业务样本。


## 84333ee 独立收款诊断 Gate3：修正后单次批次完成（2026-10-29）

用户明确授权用修正后代码重新构建并执行一批：适配自检→旧02相关回归→05单次诊断，固定完整`84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，54分钟硬截止，任何失败即停止。01/06及退款夜跑不动；未修改产品或原链快照。上次`20261029T193040`停止记录、bundle、冻结源码、日志及修正后计划全部保留，本次写入全新目录。

本地证据：`report/lsp-watchtower-05-84333ee-20261029T195244/`。实际启动命令：

```bash
/Users/sunchengzhu/project/fiber-py-integration-test/venv/bin/python   report/lsp-watchtower-05-84333ee-20261029T193040/runner-after-schema-fix.py
```

本次运行时执行器保存在新目录`runner.py`；具体子命令、PID、阶段截止、日志和退出码保存在`run.json`及各阶段文件。北京时间19:52:44启动，约20:02:14完成，总耗时**570.293秒（9分30秒）**；`batch.exit=0`、`status=passed`，没有重跑或补充轮次。

| 实际阶段 | 结果 |
| --- | --- |
| 预检 | 1.334秒，通过；源码干净、完整SHA正确，FNN自报`fnn Fiber v0.10.0-rc1 (84333ee 2026-10-28)`，原bundle摘要匹配、所需端口空闲 |
| 独立driver构建 | 阶段24.272秒，通过；构建命令退出0，Cargo原始输出`Finished dev profile ... in 18.15s`。复制独立匹配缓存，仅编译本地driver，原FNN/agent核验后复用；新bundle在本次report内，未覆盖任何旧产物 |
| 适配自检与收集 | 2.116秒，通过；合法参数和真实授权类型的内存schema序列化自检退出0；同钱包、扩大费限、未知字段各按预期退出1；Python AST正常，两方法收集退出0。此阶段没有真实链SDK样本 |
| 旧02相关回归 | 命令退出0，用时362.676秒；JUnit `tests=1, failures=0, errors=0, skipped=0`，pytest时间362.498秒 |
| 05单次诊断 | 命令退出0，用时179.203秒；JUnit `tests=1, failures=0, errors=0, skipped=0`，pytest时间178.861秒 |
| 收尾 | 0.684秒，通过；本批PGID残留列表为空、测试端口空闲、源码仍干净，原工作区Git状态和旧bundle摘要未变；21份冻结文件与执行时源一致 |

**旧02只证明历史D=S的分段路径。** 原`Agent.handle_event`真实因缺本地批准拒签，`adapted=false`；负向窗口130.834秒、131次采样，最大间隔1.182秒，无A结算。明确批准后取得真实Applied，复核65字节签名进入A已committed结算交易的witness；T/A解锁份额分别为50,000,000,000 / 49,999,999,543 Shannon，两笔结算费785 / 638 Shannon，强关费457 Shannon，逐笔及累计守恒。终态稳定65.722秒、66次采样，最大间隔1.027秒。不转记为独立用户到账或原Agent自动恢复通过。

**05取得真实SDK拒绝及无副作用证据。** 实际`auth.destination`导出的RPC Script与预先批准D_A完整一致，D_A与T的S不同，原始EntityHex授权仍保存。真实候选的输入/祖先、成熟、可信deps、request hash、record/witness与A解锁归属一致；资金快照为：

| 候选资金项 | Shannon |
| --- | ---: |
| A合法应得份额 | 50,000,000,000 |
| 输出至D_A | 0 |
| S辅助输入 | 100,000,000,000 |
| 输出至S（合并份额和找零） | 149,999,999,215 |
| 合法后继commitment | 49,999,999,543 |
| 实际交易费 | 785 |

原SDK `prepare_onchain`确实被调用，返回`prepared=false`，最先拒绝层级为`sdk_sponsor`，原始错误：`invalid signing content: commitment validation: fee input is not approved plain CKB`。这不是旧夹具的提前拦截。后续65.546秒、66次采样、最大间隔1.181秒内，零A Settlement签名提交、SDK snapshot不变、批准未改变，沿真实链未发现A份额解锁；没有调用sign/submit或广播该候选。

GPT6.1sol已独立核对本次schema自检、固定版本与复用产物、旧02的拒签/Applied/witness/资金，以及05的真实授权、错误候选、原SDK拒绝、连续观察和清理记录，复核通过。**05通过只说明独立D_A批准下，当前真实候选被sponsor约束拒绝；不证明输出目的地校验已经执行，不证明产品已修复或A已独立到账。** 新01/06仍等待修复版本，未执行，退款夜跑未启动。

TEST-MAP仍为02～05已映射，新01/06未映射；本次新增执行结论仅为旧02一次相关回归、05一次有限诊断，不累计成1+3或全PR通过。成功/失败分目录保留，冻结证据使用`.snapshot`后缀，不参与活跃评审/映射扫描。

本批文档/映射核验：`python3 scripts/check_test_map.py`输出114条评审、108条映射、无重复ID，退出1仍仅因既有PMP-01～05及SETTLE-01六个孤立映射；本批没有新增孤立映射。设计检查`cases: 6`、退出0（工具仍提示历史/推断Spec需要人工决定，本批行集与费用已获明确批准）。`git diff --check`退出0。前后两批各21份冻结源码均按原摘要核对一致；没有覆盖上次停止证据。

## 84333ee 接纳一致性 Gate3：资格构建受限停批（2026-10-29）

用户确认 `LSP-DELIVERY-01～06` 行集、逐方资金断言和原 `run_node` 薄包装，授权固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9` 做 GPT 6 sol 代码复核、一次资格及六行单次验证，硬上限120分钟，失败即停。Daybreak 限制后改用 GPT 6 sol，薄包装、Python断言及批次脚本的确定性静态问题已修正并复核；这不等于编译或产品通过。

唯一批次的证据根为 `report/lsp-delivery-84333ee-20261029T212218/`，入口为 `scripts/run_lsp_delivery_batch.py`，`run.json` 与 `batch.exit` 是最终阶段和退出码事实来源。预检通过：产品HEAD精确匹配84333ee、工作树干净，复用的基础bundle版本、锁文件和清单摘要匹配，既有目标缓存克隆成功。随后 `build-wrapper` 退出1；其日志显示 `cargo metadata --offline` 在编译前尝试将 `chacha20poly1305 v0.10.1` 解包到 `/Users/sunchengzhu/.cargo/registry/src/...`，系统返回 `Operation not permitted (os error 1)`。这是当前执行环境的 Cargo 缓存写入权限失败，不是 FNN 产品失败；没有取得薄包装运行资格。构建阶段开始后约5.00秒停批，整批单调时钟约7.94秒，远早于120分钟硬上限，没有重跑或换分支。

| 阶段 | 结果 | 证据与边界 |
| --- | --- | --- |
| 预检 | 通过 | `product-head/status`、`original-status`、`base-version` 均 exit 0；固定843基础清单/摘要核对通过 |
| 独立构建 | 停止 | `clone-reviewed-cache.exit=0`；`build-wrapper.exit=1`，内部 Cargo metadata exit 101；`build-wrapper.log` 保存原始EPERM与 Python traceback，尚未编译薄包装 |
| 传输自检、真实正常付款资格、01～06 | 全部未运行 | 无相应命令、JUnit或产品样本；不可把 TEST-MAP 或旧版本结果记为本批通过 |
| 收尾 | 部分完成 | 产品与原工作区最终 Git 状态命令 exit 0，原工作区前后 porcelain 字节一致；最终进程清单调用 `ps` 被同一沙盒以 `Operation not permitted` 拒绝，因此 `final-evidence` 失败且未生成进程清单。停批后单独连接检查六个预定端口均返回未监听；不能据此宣称完成进程清单核验 |

`run.json` 最终 `status=stopped`，`batch.exit=1`；`stop.txt` 记录构建断言停批，`run.json.stop_reason` 另保留收尾权限失败。停批后只读核对另存于 `post-stop-integrity.json`：产品仍为干净843、原工作区状态与预检一致、五份冻结代码与基础bundle摘要一致、JUnit文件为空。六个预定端口的 `connect_ex` 原始值均为 **1（EPERM）**，只能说明受限环境不准探测，不能证明端口空闲；`ps` 也不可用。已保存启动前六份源码的原字节 `.snapshot`、独立缓存克隆、部分 `node-build`、全部已执行命令日志及退出码，原bundle和前次运行证据未覆盖。构建前没有启动 FNN、SDK或CKB产品样本，退款夜跑未动。

TEST-MAP：六行均有映射，评审行均为 `[x]`；这一状态只表示测试代码存在，六行实际执行 **0/6**。本次 `check_test_design.py --root . --review reviews/lsp/delivery-acceptance-consistency.md` 识别六行、exit 0，Spec仍有按已确认边界解释的人工提示；`python3 scripts/check_test_map.py` 为120条评审、114个映射、无重复ID，exit 1仍只因既有PMP-01～05与SETTLE-01六个孤立映射。Python AST、Rust 2021格式检查及 `git diff --check` 在启动前均 exit 0。

后续若授权**新的**批次，先准备可写、隔离且带所需锁定依赖的 Cargo 缓存，使离线 metadata 不触碰受限的用户缓存；将进程残留检查改为当前沙盒可执行的方式并重新复核。不能续跑或覆盖本次证据，也不能从本次资格失败推断六行产品行为。

## 84333ee 接纳一致性 Gate3：第二批类型编译失败停批（2026-10-29）

用户要求继续后，在新证据根 `report/lsp-delivery-84333ee-20261029T214529/` 启动唯一新批次，沿用84333ee和120分钟硬上限；前一批 `...T212218/` 原封保留。启动前修正批次脚本：将Cargo registry/git以 APFS 克隆至本批独立 `CARGO_HOME`，端口预检仅接受明确的 `ECONNREFUSED`，收尾只核验本批启动的进程组与六个指定IPv4 TCP端口。这三处经GPT6sol只读复核，无确定阻断；本次在允许本机loopback的执行环境运行。

预检通过，固定产品HEAD精确匹配且工作树干净，基础bundle版本/摘要及六个端口资格通过；目标缓存、Cargo registry和git克隆均 exit0。`build-wrapper` 经过138.7秒退出1：离线 metadata 已通过，Cargo编译到测试薄包装时报告唯一 `E0308 mismatched types`，`fiber.public_key()` 为 tentacle `PublicKey`，测试控制函数却要求 FNN `Pubkey`。这是**测试侧薄包装编译错误**，不是FNN产品失败。按资格失败即停，没有启动传输自检、真实正常付款或01～06，未改产品、锁文件或退款夜跑。

| 阶段 | 结果 | 原始证据 |
| --- | --- | --- |
| 预检及独立缓存准备 | 通过 | `run.json`、`product-head/status`、`base-version`、`clone-reviewed-cache`、`clone-cargo-registry/git` 日志和各 `.exit`；均为0 |
| 构建资格 | 失败即停 | `build-wrapper.exit=1`，`build-wrapper.log` 中原始 Rust `E0308` 及 Cargo build exit101；未生成合格薄包装 |
| 传输自检、正常付款及六行 | 全部未运行 | 无这些阶段的命令、JUnit或产品样本；实际执行 **0/6** |
| 收尾 | 通过 | `product-final-status` 和 `original-final-status` exit0；`residual-processes.json` 记录本批全部进程组 absent、六个端口 `connect_ex=61 (ECONNREFUSED)`。此证据只覆盖本批进程组和指定本机TCP端口，不是全系统进程清单 |

`run.json` 为 `status=stopped`，`batch.exit=1`；总单调时钟157.778秒，远低于120分钟。旧报告、当前失败编译日志、独立构建目录、克隆目标及启动前六份源码 `.snapshot` 均保留。停批**之后**，仅修改测试薄包装：先用原 tentacle `PublicKey` 生成与上游一致的 Network actor 注册名，再转为 `Pubkey` 供 `NodeInfo` 身份比较；`rustfmt --edition 2021 --check` exit0，GPT6sol按843源码静态复核类型与注册名一致。此修正未编译或运行，不能把第二批失败重写为通过；第二批冻结快照保留原错误版本。

TEST-MAP仍为六个ID均已映射，场景勾选表示有代码，不表示六行通过。120条评审/114个映射的项目检查退出1仍仅为既有PMP-01～05、SETTLE-01六个孤立映射，无本批新孤立ID或重复评审ID。下一次必须是新的单次批次；不能续跑本次或为挑分支反复重跑。

## 84333ee 接纳一致性 Gate3：第三批控制端未认证停批（2026-10-29）

第二批停下并修正测试薄包装公钥类型后，在新证据根 `report/lsp-delivery-84333ee-20261029T215109/` 启动第三批，固定产品/SDK仍为84333ee。旧两批证据与原快照均保留。预检、独立缓存与薄包装构建通过，`build-wrapper.exit=0`（142.2秒）；进程内回复端口 `transport-selfcheck.exit=0`（约2.0秒），其事件明确标记只测内存传输、不是产品通过。

真实正常付款对照已启动CKB、两台FNN、SDK租户和通道准备；在正式付款前 `_DeliveryBase.setUp()` 请求控制端 `status` 时，Unix socket 已连接但2秒内没有回复，pytest `normal-control.exit=1`，JUnit为1 failed、0 passed，整批 `status=stopped`、`batch.exit=1`。原始 `normal-control.log/.xml`、FNN/CKB/SDK/事件/观察日志在本批证据根。根因有直接证据：薄包装控制端先绑定socket，再以**未携带Biscuit Bearer token** 的 HTTP 客户端循环调用 `node_info`；`fiber-1/node.log` 持续记录 `Biscuit authorization failed ... no authorization header`，`events.jsonl` 为空，控制端未进入socket accept循环，也未发出 `ready`。这属于测试侧控制端鉴权缺陷，不能通过延长Python的2秒socket等待来证明夹具合格，更不是843产品失败。

构建资格158.636秒、自检2.182秒、正常对照到失败89.57秒；总单调时钟253.202秒，未触及120分钟上限。按资格失败即停，`LSP-DELIVERY-01～06` **0/6未运行**，没有真实接纳/重投或付款结果。收尾通过：产品和原工作区状态与预检一致，`residual-processes.json` 的本批进程组全部 absent，指定六个IPv4 TCP端口均为 `ECONNREFUSED`；清理范围不扩写为全系统进程清单。

停批**之后**仅修测试侧控制端：Python传入原bundle中已经用于FNN RPC的 `operator-token` **路径**，Rust用该token为本机 `node_info` 设置 `Authorization: Bearer`，保留90秒有界就绪和后续 `NodeInfo` 邮箱屏障。GPT6sol按843源码及既有夹具复核认证API、token来源和自检分支，未发现确定阻断；`rustfmt --edition 2021 --check`、Python AST与`git diff --check`退出0。此修正尚未重编或运行；第三批冻结的源码 `.snapshot` 保留原未认证版本。六行TEST-MAP及评审复选框不变，映射仍不等于验证通过。

## 84333ee 接纳一致性 Gate3：第四批通道快照序列化停批（2026-10-29）

第三批停下并修正控制端RPC鉴权后，在新证据根 `report/lsp-delivery-84333ee-20261029T215950/` 启动第四批，固定84333ee不变。预检、独立Cargo构建与进程内传输自检均通过，`build-wrapper.exit=0`、`transport-selfcheck.exit=0`；真实CKB/FNN/SDK及租户准备完成，控制端发出带`NodeInfo`邮箱屏障的 `ready`，已对一笔正常资格付款捕获原 `AcceptTrampolineDelivery`。因此本批证明前次鉴权障碍已消除，但正常付款**没有**完成资金与终态资格断言。

正常对照在读取控制端 `snapshot` 时socket由对端关闭，pytest `normal-control.exit=1`、JUnit为1 failed。`fiber-1/node.log` 精确记录测试薄包装 `_delivery_node.rs:310` 的 `serde_json::Value` 序列化 panic：`number out of range`；100ms观察任务先遇同一快照路径，控制请求随后遇到，`events.jsonl`保留ready、armed、captured及StoreChange。源码显示固定843默认通道约束 `max_tlc_value_in_flight=u128::MAX`，而当前serde_json Value不能承载超过u64的整数，故高置信度归因于测试适配器把完整通道状态放进 `json!`；冻结证据不能区分local/remote约束中具体哪一个先触发。此失败不是产品断言失败，正式六行仍 **0/6未运行**。

整批单调时钟248.888秒，`run.json.status=stopped`、`batch.exit=1`；构建155.908秒、自检2.011秒、正常资格到失败88.102秒，均未触及120分钟上限。`final-evidence`通过：固定产品与原工作区状态未变，本批已知进程组全部absent，六个指定端口均明确 `ECONNREFUSED`。第四批的构建、JUnit、事件、节点、CKB、SDK及源码 `.snapshot` 全部保留，与前三批不混写。

停批**之后**只改测试侧快照传输：Rust流式 `serde_json::to_string` 把完整通道状态作为 `channels_json` 文本放入控制/观察事件，Python对直接和100ms事件均以`json.loads`恢复完整通道数组及精确大整数；逐K、逐方资金与终态断言不变。观察任务的变化指纹排除该原始文本，避免通道HashMap键顺序导致伪变化；原K TLC、delivery、session仍触发100ms事件，每次直接快照仍包含所有通道。GPT6sol静态复核了大整数无损路径和两类消费端，未编译或运行该修正。四批原证据保留，TEST-MAP六行仍映射但0/6未验证。

## 84333ee 接纳一致性 Gate3：第五批非字符串通道键停批（2026-10-29）

第四批停下并修改测试侧大整数传输后，在独立证据根 `report/lsp-delivery-84333ee-20261029T220838/` 启动第五批。`run.json` 记录预检、独立构建、传输自检均通过，`build-wrapper.exit=0`、`transport-selfcheck.exit=0`。正常对照启动真实CKB、FNN、SDK与通道，并捕获、转发、缓冲原 `AcceptTrampolineDelivery`。失败前的一份完整采样显示四条通道均为 `ChannelReady`、各有一条待处理TLC；A与T-A各为1,000,000 Shannon，P与T-P各为1,005,000 Shannon，当前费用为5,000 Shannon。中途路径与资金断言已通过，但这不是最终结算或费用归属通过。

正常对照在 `_held_checkpoint` 读取首次快照时收到控制端 `{"ok":false,"error":"channel serialization: key must be a string"}`，`normal-control.exit=1`，JUnit为1 failed。事件保留 ready、armed、captured、forwarded、buffered，随后五次 `snapshot_failed` 为同一错误；本批没有节点panic。固定843源码中完整持久化通道状态含以 `TLCId`、`NonceSlot` 等结构类型为键的Map，不能作为JSON对象直接序列化；它还包含不应导出到控制事件的签名私钥。因此归因为测试薄包装快照设计错误，不是已证实的产品行为失败。真实资格付款未取得最终资金和终态证明，正式 `LSP-DELIVERY-01～06` **0/6未运行**。

本批 `run.json.status=stopped`、`batch.exit=1`；正常对照约91.858秒后停，总单调时钟约250.477秒，未触及120分钟上限。`final-evidence`通过：产品仍为干净84333ee，原工作区的既有改动与预检一致，本批记录的进程组在归档时全部absent，指定六个本机TCP端口均为 `ECONNREFUSED`。本批源码 `.snapshot`、构建、JUnit、事件、观察、CKB/FNN/SDK日志和原始退出码均保留，前四批证据未覆盖。

停批**之后**仅修测试侧快照：逐通道导出ID、状态、双方余额与锁定额，以及TLC的ID、方向、hash、金额、状态与完成类别；所有 `u128` 金额为精确十进制字符串，排除原始signer、onion和shared secret。100ms观察仍以原K捕获、delivery、session变化为指纹，直接快照另含通道摘要。Python直接和事件路径同步使用 `channels`，逐K与逐方资金断言未降低；原始RocksDB证据仍保留完整持久化状态。GPT6sol对固定843类型、序列化边界及两类Python消费路径静态复核未见确定阻断；该修正尚未重编或运行，不能改写第五批结果。

## 84333ee 接纳一致性 Gate3：第六批费用字段误用停批（2026-10-29）

第五批停下并改为安全通道字段投影后，新批证据根为 `report/lsp-delivery-84333ee-20261029T221906/`。固定84333ee产品树干净，独立构建 `build-wrapper.exit=0`，传输自检 `transport-selfcheck.exit=0`；正常付款资格对照的真实请求被捕获并转发，快照与签名保持/放行路径已越过前次失败点。最终采样显示付款 `Success`、发票 `Paid`，原K的上游TLC为 `RemoveTlcFulfill`，delivery 为 `Succeeded`，下游session及唯一attempt为 `Success`。上游P支出1,005,000 Shannon、T-P收入1,005,000，T-A支出1,000,000、A收入1,000,000，LSP净差额5,000；四条通道最终均无待处理TLC、锁定额为0。`events.jsonl` 无 `snapshot_failed`。这些是资格对照中的观测事实，尚未通过完整资金与稳定期断言。

`normal-control.exit=1`、JUnit为1 failed：`_assert_key_outcomes` 错把 `request.previous_tlc.forwarding_fee=0` 当作T本次费用，断言 `1,005,000 == 1,000,000 + 0`。固定843源码在 `network.rs` 要求上游额与 `amount_to_forward` 的差额等于本次 `build_max_fee_amount`；该请求分别为1,005,000、1,000,000、5,000。`previous_tlc.forwarding_fee` 属于外层普通转发路径，本次为0。因此失败归因于**测试判据字段误用**，不是已证实的产品异常。该失败发生在后续 `_funds` 最终账本断言和30秒稳定采样之前，资格不能记通过，正式 `LSP-DELIVERY-01～06` 仍 **0/6未运行**。

`run.json.status=stopped`、`batch.exit=1`；预检1.875秒、构建154.637秒、自检1.990秒、正常对照至失败89.403秒、收尾0.995秒，总单调时钟248.903秒，未触及120分钟上限。收尾保留原工作区的既有改动，产品仍为干净843；本批记录的进程组归档时全部absent，指定六个TCP端口均为 `ECONNREFUSED`。源码 `.snapshot`、JUnit、事件、观察、节点与链日志和退出码均保留，前五批不覆盖。

停批**之后**只把该测试断言改为核对 `原上游TLC额 == amount_to_forward + build_max_fee_amount`，仍由 `_funds` 独立验证实际付款费 `f=U−M`、逐通道余额、锁定额和净收入，不把最大预算普遍当成实收费用。GPT6sol按固定843源码和第六批事实只读复核字段语义；该修正尚未运行，不改写第六批结果或已确认的六行用例预期。


## 84333ee 接纳一致性 Gate3：第七批01终态判据未过（2026-10-30）

用户授权持续推进并免逐阶段确认后，本次固定84333ee、120分钟硬上限执行；独立路径参数与上次费用字段修正经GPT 6 sol复核。证据目录为 `report/lsp-delivery-84333ee-20261030T002446/`，`runner.py`及`run.json`保存实际命令、输入目录、冻结源码、截止与退出码；旧六批未覆盖。

构建退出0（139.7秒），传输自检退出0（1.8秒），真实正常付款对照127.3秒退出0，已完成逐K、逐方资金、零锁定和30秒稳定观察。正式01运行211.1秒退出1；02～06未运行，`batch.exit=1/status=stopped`。源码保持干净843、原工作区状态与基础产物未变，本批进程组和指定端口收尾通过。

01同一K的事件单调毫秒序列为：captured 69707 → caller_timeout 74711（约4999ms，原回复端口关闭）→ forwarded 74713 → buffered 74724。节点真实记录原调用超时；产品记录最终为 `Failed(upstream TLC was removed before hosted delivery dispatch)`、attempt_count=0，未建立下游session。付款Failed、发票Open、fee=0，四通道余额回基线且锁定额为0；上游两端RPC仍各列出一条 `RemoveAckConfirmed/RemoveTlcFail` TLC记录。

测试在 `_finish(recovery_until)` 等待 `pending_tlcs` 全空，120秒截止后经 `_pause` 抛 `_PaymentBudgetExpired: late payment result is diagnostic only`，未进入最终逐K断言及30秒稳定窗口。GPT 6 sol两份独立只读审计一致确认：超时与延后接纳已真实触发；本样本未复现上游失败而下游付款，01仍不得记通过，RPC残留条目的终态语义须按固定源码进一步核实，不把等待超时直接归为产品资金缺陷。本批不重跑、不跳过01运行后续行。TEST-MAP六行保持，但实际正式通过0/6，已执行1/6。

2026-10-30 后续源码核实：RPC pending_tlcs 包含已确认失败的历史条目。测试终态已改为核对无活跃TLC；只对与T原始Store逐字段一致的RemoveTlcFail/RemoveAckConfirmed且有确认序号的历史条目作排除，原样证据仍保留。逐K、下游结果、零锁定、余额、费用和30秒稳定断言继续保留；第七批仍记失败。修正经GPT 6 sol复核，离线冻结证据及九项不匹配负向检查不算产品通过，新批结果另记。


## 84333ee Hosted租户发票取消：真实入口拒绝（2026-10-30）

用户已授权按顺序持续推进，无需逐阶段确认。01/02已实施并建立TEST-MAP，03的Received取消契约仍未确定且未映射。本次仅对固定84333ee执行01单次诊断，15分钟总上限、完整pytest进程最多480秒；失败即停，不运行02/03。真实Agent链配置与安全预像释放控制入口经GPT 6 sol复核，但本次在取消入口前即被产品阻断，没有执行正向释放。

证据为 `report/lsp-invoice-cancel-84333ee-20261030T003644/`：`runner.py/run.json`保存实际命令、源码与产物摘要、绝对截止和退出码。独立driver-only构建命令21.60秒退出0（阶段25.29秒）、收集退出0；01运行93.55秒退出1，非预算到期；最终收尾通过、`residual-processes.json=[]`，产品仍干净843、原工作区及旧产物未变。

真实A tenant token先创建仅含payment hash的发票，客户端保留preimage，`get_invoice=Open`且SDK授权保存；随后A自己的 `cancel_invoice` 收到JSON-RPC `-32999 Unauthorized`。原始 `cancel-01.log:107`、用例 `observations.jsonl` 第151～155条及 `fiber-1/node.log:1246` 一致，节点明确输出 `tenant token is not allowed to call cancel_invoice`。固定源码 `crates/fiber-lib/src/rpc/tenant.rs` 的允许列表缺少该方法，与Luso报告一致，归为产品租户入口缺口。

入口拒绝后按规则停止，没有send_payment/get_payment或后置资金快照；只能证明真实租户取消入口失败，不能把基线无TLC/镜像余额说成取消前后资金已验证。01的旧付款失败、资金回基线和新付款成功步骤未运行，02/03未运行。GPT 6 sol独立审计原始请求、发票、身份、节点日志、退出码和边界；本次不重跑已知拒绝，不使用operator token绕过。

## 84333ee 接纳一致性 Gate3：第八批逐K完成采样缺口停批（2026-10-30）

固定843新批的独立证据根为 `report/lsp-delivery-84333ee-20261030T004329/`。预检约1.9秒、独立构建约152.3秒、自检约2.0秒均通过；第七批后仅针对确认失败历史的活跃TLC判据修正已在本批运行。真实正常付款对照约211.8秒后 `normal-control.exit=1`、JUnit 1 failed，`_PaymentBudgetExpired: payment operation exceeded ...` 出现在120秒恢复截止；整批 `status=stopped`、`batch.exit=1`。按资格失败即停，正式01～06没有启动，完整正式通过仍0/6。

正常对照的最后原始样本显示付款 `Success`、发票 `Paid`、delivery `Succeeded`、下游唯一session/attempt `Success`；四端RPC `pending_tlcs=[]`、offered/received锁定额0，T侧原始通道TLC列表也为空。阻断来自测试对**原K移除原因的逐次观察要求**：730份直接快照中，前5份 `upstream_tlc` 仍是 `Inbound Committed` 且 `removed_reason=None`，从第6份起725份为 `None`；4份100ms事件快照同样未见移除原因。薄包装在当前Store里查 `get_all_received_tlcs().find(id)`，清理后即返回空；观察指纹不含通道字段，完成瞬态没有被事件持久记录。`_finish` 因无 `removed_reason` 不进入终态，`_assert_key_outcomes` 的完成证据也因此未满足；后续逐K/资金断言及30秒稳定期未完成。不能以聚合Success或列表清空替代已确认用例的逐K证据，也不能把测试的采样缺口归因产品。

`run.json`、`normal-control.log/.xml/.exit`、`events.jsonl`、730份直接快照所在 `observations.jsonl` 及版本/清理材料保留。第七批01的原caller超时后转交事实和安全失败样本仍独立有效，但两批均不能转记01通过。本组暂停，不继续重跑竞态分支；本批未修改产品或退款环境。

## 84333ee 普通LSP回归：30方法通过（2026-10-30）

取消01单次诊断后的普通向后兼容回归使用同一新driver-only bundle：`report/lsp-invoice-cancel-84333ee-20261030T003644/bundle`，FNN自报 `fnn Fiber v0.10.0-rc1 (84333ee 2026-10-28)`。独立批次报告为 `report/lsp-invoice-cancel-regression-84333ee-20261030T005117/`；执行器副本 `runner.py`、`run.json` 保存固定源码SHA `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`、bundle与基础产物摘要、24份冻结LSP源码摘要、每条实际命令/进程/绝对截止及退出码。调用入口为原项目 Python 环境执行 `/private/tmp/fiber-cancel-prep-20261030/lsp_invoice_cancel_regression_runner.py --bundle <上述bundle绝对路径>`；各阶段实际pytest argv、环境与报告路径以 `run.json` 为准。

按 `-x -vv -s -o addopts=` 串行执行核心三个文件 `test_channel_signing_isolation.py`、`test_channel_signing_retry.py`、`test_channel_signing_recovery.py`，再执行 `test_delayed_payment_recovery.py`，最后执行 `test_browser_signing_subscriptions.py`。三个收集命令均退出0；对应JUnit、HTML、原始日志及各阶段证据目录分别为 `core-16.*`、`delayed-3.*`、`browser-11.*`。实际结果为核心 **16/16 passed**（pytest 1507.68秒、进程1507.96秒）、延迟付款 **3/3 passed**（pytest 390.48秒、进程390.82秒）、浏览器 **11/11 passed**（pytest 924.81秒、进程925.27秒）；三个JUnit各为0 failure/error/skip，各阶段退出0、`budget_expired=false`。合计30个方法，对应25个不重复正式ID：SIGN-01～03、RETRY-01～06、RECOVERY-01～07、PAYMENT-01～03、SUBSCRIPTION-14～19；浏览器11方法只覆盖六个ID，不能按方法数计ID。

全批同一个单调时钟60分钟硬截止，阶段上限依次2200/750/1100秒并受总剩余时间裁切，不重置预算；实际从起点到最终证据完成2828.229秒（47.14分钟），`batch.exit=0`、`run.json.status=passed`。收尾检查通过、`residual-processes.json=[]`，指定测试端口空闲；固定843产品源码仍干净，原项目状态、基础bundle和本批bundle摘要核对未变。这些是固定843上普通功能的独立回归，不改变取消01在真实tenant `cancel_invoice` 入口 `-32999 Unauthorized` 的失败，不能视为取消后旧付款资金或新付款已通过；02未运行、03待契约。第七/八批delivery仍无正式通过，原项目退款三行未取得夜跑通过证据。

## 84333ee 接纳一致性 Gate3：第九批01通过、02产品一致性失败（2026-10-30）

独立证据根为 `report/lsp-delivery-84333ee-20261030T013955/`。执行入口 `scripts/run_lsp_delivery_batch.py`，实际命令及参数以本批 `runner.py`、`run.json.commands` 和各 `.log/.exit/.xml` 为准：原项目 `/Users/sunchengzhu/project/fiber-py-integration-test/venv/bin/python -m pytest -x -vv -s -o addopts=`，分别指定 `test_delivery_acceptance.py::TestDeliveryQualification::test_normal_control_payment_qualifies_real_path`、`TestDeliveryAcceptance::test_accept_after_original_caller_timeout`、`TestDeliveryAcceptance::test_buffered_reply_lost_after_real_acceptance`。环境使用固定产品源码 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`、`report/lsp-invoice-cancel-84333ee-20261030T003644/bundle` 为基础产物，复制第八批已验证薄包装到本批独立bundle；`run.json` 保留输入及冻结源码/产物摘要。预检约1.85秒、复用构建约1.28秒、传输自检约2.23秒，均通过；这不是重新全量编译。

正常付款资格对照 `normal-control.exit=0`（126.63秒，JUnit 1 passed），正式01 `delivery-01.exit=0`（121.48秒，JUnit 1 passed）。01事件 `captured 69637 → caller_timeout 74648 → forwarded 74650 → buffered 74663`（相对单调毫秒）：真实原调用约5秒超时且原回复端口关闭后才转交同一K，产品安全失败、下游无支出；逐K、四方资金/零活跃锁及完整30秒稳定断言均通过。本批薄包装通过同进程actor代理受控安排接纳请求时序；此处不声称普通网络流量自然复现同一竞态。01计入固定843正式通过，delivery累计 **1/6**。

正式02 `delivery-02.exit=1`（91.68秒，JUnit 1 failed）。测试薄包装在同进程actor调用上受控丢弃服务接纳回复（`drop_reply`）；产品服务、真实5秒调用超时与原回复端口关闭均真实，不能写成普通网络流量自然复现。事件 `captured 69667 → forwarded 69675 → buffered 69684 → caller_timeout 74671` 显示同一原K的 `Buffered` 已在真实调用超时前持久化。原K上游记录为 `RemoveTlcFail/RemoveAckConfirmed`，但 `previous_keys=[K]` 的下游唯一session及attempt为 `Success`；末次原始样本付款 `Failed`、fee=0、发票 `Paid`。相对准备时基线，P与T-P两端余额差额均0，T-A本地余额−1,000,000、A本地余额+1,000,000，对应远端镜像，四端锁定额0。代码在 `test_delivery_acceptance.py:548` 的“original K failed but downstream paid”早期一致性断言停止；正式最终资金断言及30秒稳定窗口**未执行**，因此不能称已证明最终持久损失。这是已确认故障注入场景下的固定843产品一致性失败，不归入历史开通计时器#1674或watchtower#1706。

失败即停，03～06没有命令、JUnit或产品样本；未为挑选竞态结果重跑。整批 `run.json.status=stopped`、`batch.exit=1`，共约346.53秒，低于单一120分钟总上限；`final-evidence`约1.37秒通过。产品源码仍为干净843，原项目状态与批前保存值一致；`residual-processes.json` 只确认本批进程组全部absent、六个指定本机TCP端口 `connect_ex=61 (ECONNREFUSED)`，不扩写为全系统无残留。02的原始逐K事件、四方快照、RPC与节点日志、JUnit均在本批 `cases/test_buffered_reply_lost_after_real_acceptance/` 和根目录；01原始证据在对应 `cases/test_accept_after_original_caller_timeout/`。固定843独立正式通过数由39增至 **40/74**，有TEST-MAP仍 **71/74**；02失败与03～06未跑均不计通过。取消01入口失败和退款夜跑未通过结论不变。


## 2026-10-30 本轮收尾提交与后续边界

本轮固定 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，未修改产品源码、宿主时间或退款夜跑。普通相关回归30/30方法通过（25个独立ID），接纳正常对照与01通过、02产品一致性失败后停止；租户取消01以真实tenant token复现权限拒绝。以目前登记的74个正式LSP ID为分母，71个有真实TEST-MAP（约96%），固定843有42个已执行结果（约57%：40通过、2产品失败）；40/74约54%。这些是已登记场景的映射和版本结果比例，不是整个PR代码覆盖率，也不把旧版本通过并入843。

已提交的测试PR：[订阅过滤 #3](https://github.com/sunchengzhu/fiber-py-integration-test/pull/3)（`b26117d0`）、[Watchtower目的地诊断 #4](https://github.com/sunchengzhu/fiber-py-integration-test/pull/4)（`687b23ab`）、[租户发票取消 Draft #5](https://github.com/sunchengzhu/fiber-py-integration-test/pull/5)（`317f8c46`）、[接纳回复丢失 Draft #6](https://github.com/sunchengzhu/fiber-py-integration-test/pull/6)（`8217a23c`）。#3/#4目标为 `codex/lsp-core-regressions`；#5/#6基于#4分支，合并顺序须先#4。本轮没有合并这些PR；旧#2已合并的事实不变。远端没有返回CI检查，不能称CI通过。

后续先取得产品修复提交，再定点复核DELIVERY-02和INVOICE-CANCEL-01，并按失败即停规则继续未运行的DELIVERY-03～06、INVOICE-CANCEL-02。WATCHTOWER-01/06仍待独立用户收款支持，INVOICE-CANCEL-03的Received取消契约仍待产品明确；#1674沿旧归因。退款01～03仍由用户手动夜跑，本轮没有执行。其余只有旧版本证据的场景需在最终验收版本补足相关回归，不能据本轮结果宣布产品PR测试全部完成。

最终静态检查：新delivery/取消评审设计检查均退出0（6/3行，开放产品决策如实保留），新Python文件与runner的Black检查退出0，diff检查退出0。项目级映射检查为123评审/116映射、无重复ID，退出1仅仍列六个既有孤立映射PMP-01～05、SETTLE-01；此计数包含非LSP范围，不能与上面的74场景分母混用。所有批次报告、源码快照、节点日志和退出码保留；最新批次自有进程组已退出、指定端口已释放，原工作区既有改动及原构建未改写。


## 843 新场景单次夜间批次启动（2026-10-30 03:03）

用户已批准仅执行退款 LSP-REFUND-01～03（资格、正常结算对照、正式固定1+3）和独立 LSP-DELIVERY-03～06 各单次。固定84333eea8488a8afc7e4474aa4bbd0e7e973cee9；主执行GPT-6.1 Sol High，独立复核GPT-6 Sol High。全夜起点北京时间03:03:49，单调898120.398231083，8小时绝对截止926920.398231083（北京时间11:03:49）；退款411分钟和接纳45分钟上限不扩大。

新证据根为 `/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/report/lsp-night-new-84333ee-20261030T030349/`，以 `nightly.stage`、`refund-supervision.json`、`run.json` 和实际进程为准。独立运行目录 `/private/tmp/lsp843-20261030-030349` 使用内盘APFS与短Lima路径；原04脚本、产物、快照保留。843独立源码/资产/输入检查通过，时钟保护与隔离辅助26项自检通过，独立Sol复核通过；03:09左右已启动新基础VM的系统准备，仍未取得Linux构建、时钟或链资格，不能计作退款执行。

本轮不重跑旧19项回归、已知DELIVERY-02和取消01。宿主8GiB/guest4GiB硬底线、失败停止、最多两轮有证据辅助修复、统一截止和保留全部证据持续生效。当前记录是启动状态，最终结果另行追加；TEST-MAP不代表通过。


## 843 单次夜间新场景结果（2026-10-30）

本夜固定84333ee，DELIVERY-03/04/05/06各单次通过（122.62/116.86/116.93/125.58秒），完整资金断言和30秒稳定窗已执行；delivery批488.48秒、退出0。未重跑旧01/02、取消01或19项普通回归。退款Linux构建、纯时钟及旧适配通过；第1轮辅助修复只重编driver，随后TLC资格在180秒相对epoch成熟窗口超时：时间戳/索引已满足，真实链仅推进27/200 epoch，尚无退款支出。SDK正负检查、正常结算及正式固定1+3未运行，退款不能记产品失败或通过。原始JUnit墙钟14972秒受guest调时影响，非真实4小时。

全部8个本次VMStopped，21个本次进程组absent，6端口拒绝；843源码clean，原04产物和快照保留。主执行GPT-6.1 Sol High，独立复核GPT-6 Sol High；全夜8小时、退款411分钟和原更短阶段截止均未重置，修复只用1轮。详见本夜完整结果（本地证据：`../../../../report/lsp-night-new-84333ee-20261030T030349/RESULT.md`）。

沿用本会话此前74条LSP场景的统计口径，固定843正式通过40→44/74（约59%），有结果46/74（44通过、2既有产品失败），映射仍71/74；映射与这些登记比例都不代表完整PR源码覆盖。退款01～03的TEST-MAP仍保留且不算通过。后续退款须先重新评审真实epoch成熟窗口。

2026-10-30午后退款新批已获准并启动：固定843，预算修正和42项离线自检经GPT-6 Sol High复核；新base冻结匹配，资格/正常对照和两轮正式退款完整通过；用户明确以两轮收尾，本次验收完成。原1+3历史仅执行2/4，第3/4轮未跑且不再待补，未记4/4。已安全停止，可以重启。实际状态与证据：lsp-refund-84333ee-20261030T1300（本地证据：`/Users/sunchengzhu/.codex/worktrees/lsp-reviewed-regressions/fiber-py-integration-test/report/lsp-refund-84333ee-20261030T1300/STATUS.md`）；绝对截止21:00，旧夜结果不改写。

## 84333ee 连续付款后原SDK存储恢复：Gate3通过（2026-10-30）

用户确认LSP-RECOVERY-08完整Gate2及30分钟预算后，本窗口完成一个新方法；只为`_start_payment`增加可选原P–T通道输入，并让`_finish_payment`返回已验证结果和稳定样本，旧调用默认行为保持。08已建立TEST-MAP，评审复选框同步。实现及结果证据均经GPT-6 Sol High独立复核。

精确收集06/08两条退出0；旧06单次1 passed（pytest103.82秒）、新增08单次1 passed（207.16秒），各退出0，无failure/error/skip，`batch.exit=0`。从首次准备到执行/自动清理约646.44秒，未重置30分钟预算、未追加轮次。固定干净84333ee，使用既有匹配bundle，没有构建或改产品、没有操作退款环境。

08复用原两条通道和同一SDK存储完成十笔唯一付款；第9笔对应撤销签名已落盘但未转发时，旧SDK退出，新PID通过新订阅恢复同一请求/提交体，首次实际转发Applied，第10笔继续成功。十笔均Success/Paid，每笔1,000,000 Shannon、费用5,000；四端累计local增量为(+10,000,000,-10,000,000,-10,050,000,+10,050,000)，T净收入50,000等于费用总和。逐笔/累计资金、原通道和funding outpoint、零TLC/锁定、每笔5秒稳定及恢复后的历史终态/费用复查均通过。整库snapshot与records仅为诊断数据，不算单通道序列化大小或长期压力验证。

本批自有进程组均为空，六端口已释放，隔离临时目录已清理；保留约19.2MB完整证据、原bundle与旧快照，结束时约18GiB可用。证据与实际命令：本批RESULT（本地证据：`../../../../report/lsp-recovery08-84333ee-20261030T171222/RESULT.md`）、同目录run.json、两份JUnit、sequence.jsonl与final.json。映射检查124评审/117已映射，exit1为9个既有孤儿映射，没有新增孤儿或重复ID。


## 84333ee 缺授权拒签后的显式授权恢复：Gate3预算与编排停止（2026-10-30）

用户确认PAYMENT-04的Gate2及30分钟预算后，新增一个独立Python方法和TEST-MAP，复用既有驱动和匹配产物；没有构建或修改产品，没有操作退款。GPT-6 Sol High内容复核最终通过，但未保存能够证明600秒阶段内完成的时间。启动前阶段断言失败后，执行者的编排未依据失败退出码阻断下一调用，误启动唯一pytest，随即停止；没有重跑，也没有扩大或重置预算。

实际静态/版本适配自检退出0，精确收集1条退出0；pytest在节点准备期被中断，JUnit为tests=0、日志为`no tests ran in 25.93s`。观察文件只有environment_start及incomplete，未进入真实拒签、补授权、第一/第二笔付款或任何资金断言。整批batch.exit=1；run.json记录payment04中断125，但清理中的PermissionError使独立payment04.exit未写出，不把该记录当正常完整退出。PAYMENT-04保持“已映射、业务未验证”，不新增产品失败归因。

停止后的独立检查确认两组自有进程均为空、六端口拒绝连接；测试已导出本批CKB/Fiber日志与节点数据，剩余空临时目录已清除，产品HEAD仍为干净84333ee，原产物及历史证据保留。详见RESULT（本地证据：`../../../../report/lsp-payment04-84333ee-20261030T181026/RESULT.md`）、同目录run.json、payment04.log/.xml、stop-boundary.json、post-stop-verification.json和cleanup.json。原final.json的defunct和temp_preserved是停止当时快照，不覆盖后续清理结论。

最终文档设计检查4行、exit0；映射检查125评审/118映射、exit1仅列原有9个孤儿映射，无重复ID或新增孤儿。04一行的TEST-MAP已核对，但这些静态检查不替代缺失的实际业务执行。


## 84333ee PAYMENT-04编排修正新批：链验证配置准备失败（2026-10-30）

用户授权修正编排后单次运行04，使用独立证据根`report/lsp-payment04-84333ee-20261030T182922/`，保留旧181026批。新入口内部核验Sol批准时间、600秒阶段预算及runner/依赖摘要，拒绝后无法启动后续命令；进程检查或停止异常也完整保存命令退出和结束信息。GPT-6 Sol High复核通过，13项纯模拟编排自检退出0；实际版本/产物自检退出0，收集唯一04退出0。

正式单次pytest **1 failed in85.24s**，payment04.exit和batch.exit均1，未重跑。在setUp的preimage-configure控制中返回`genesis contract differs from local auth`。prepared表明原两条通道和四端基准已取得；没有ready/hash_only_invoice/send/拒签/settled，因此没有付款到账、费用或资金守恒结果。实际编排与清理正常，不能把本次失败归给上批编排错误或产品授权业务。

具体归因经Sol复核：普通FiberTest选择CURRENT_TEST并恢复预置链，auth依赖位于部署交易；固定843原Agent ChainVerifier却逐项比较创世第5/6/7输出，auth首项即不一致。属于测试链布局与验证入口不兼容；不意味着auth文件本身损坏，funding/commitment两项尚未比较。后续需按真实部署位置适配并保留链/字节校验，本批不继续改或跑。

固定843产品保持clean、bundle及04代码摘要不变，未构建、未改产品/退款。正式执行与自动收尾距新批保守起点约332.37秒，30分钟截止未重置；最终清理证明自有进程全空、六端口释放、本批临时目录删除，全部新旧证据保留。详见RESULT（本地证据：`../../../../report/lsp-payment04-84333ee-20261030T182922/RESULT.md`）、同目录run.json、JUnit、final.json及后续cleanup.json。04保持已映射、业务未验证；总计仍48通过/2产品失败/26无该版本业务结果（76ID）。

最终文档设计检查4行、exit0；项目映射125评审/118映射、exit1仅列9个既有孤儿映射，无新增孤儿或重复ID，diff检查exit0。检查输出保存在本批document-checks.json。


## 84333ee PAYMENT-04实际部署适配新批：字节校验拒绝不一致合约（2026-10-30）

新批`report/lsp-payment04-84333ee-20261030T184212`新增两个本地驱动控制并只调整04的链配置/安全释放入口；复用原Agent公开ChannelSigner的authorize_preimage_release及tenant RPC顺序，只有持久安全批准后才settle。真实部署定位复用现有Chain，保留独立CKB、Type ID、本地合约字节和主链校验。产品、原Agent、共享Chain适配及旧控制未改；退款未动。

GPT-6 Sol High复核、13项纯模拟编排自检通过；独立target克隆2.10秒、driver-only构建81.57秒、静态匹配检查和收集均退出0。唯一04 pytest **1 failed in85.78s**，进程86.66秒、payment04.exit=1、batch.exit=1。prepared后配置链时返回contract bytes differ: commitment-lock；未进入ready/创建发票/付款/拒签/安全释放或资金断言。

链上FundingLock为74800B且与本地SHA一致；CommitmentLock实际Type ID活输出为0x157446…:0，107784B、SHA256 ebf8614c1c7970ba9566820e07dd4c3402ea1ce57f3c08e6f2142f5b448954a8；受信本地文件80880B、SHA256 a7762721ef239b15adbdddca8d772db6e1c001d9f81e23ccc74e1392329931d7。字节验证正确拒绝，不意味着部署位置仍读错；auth/sighash检查尚未执行。证据来自已保存的真实CKB响应，没有重启查询。

本次遗漏了现有Watchtower的prepare_isolated_contract：在独立CKB启动后、FNN启动前把同一Type ID对齐受信合约并完整验证。Sol只读复核确认环境适配归因及该最小后续措施；本批失败即停，未修后重跑，不计新增产品失败。产品固定843且clean、运行时源/产物摘要不变。独立Cargo target和运行临时目录已清理，四组自有进程为空、六端口释放；旧缓存、历史证据及新匹配bundle保留。完整命令、字节比较及清理见RESULT（本地证据：`../../../../report/lsp-payment04-84333ee-20261030T184212/RESULT.md`）。04仍已映射、业务未验证，76ID口径保持48通过/2产品失败/26无该版本业务结果。

最终静态检查：设计4行exit0；项目映射125评审/118映射，exit1为9个既有孤儿，无新增孤儿或重复ID；diff exit0。输出保存在本批document-checks.json。


## 84333ee PAYMENT-04合约对齐新批：实际pytest类未收到隔离路径（2026-10-30）

本批在源码中补入既有Watchtower合约对齐调用，计划在CKB初始化后、FNN初始化前调用，但本次未执行到；该操作保留Type ID、受信字节、主链和活输出校验。准备阶段共用pytest启动起点180秒，没有重置600秒单条或1800秒整批截止。GPT-6 Sol High代码复核通过，13项编排模拟、6项准备生命周期模拟和精确收集退出0；这些模拟未覆盖真实pytest模块加载，不能视为环境资格通过。

唯一真实pytest **1 error in7.60s**，payment04.exit=1、batch.exit=1，失败即停、未重跑。BOOTSTRAP设置的是完整包名导入的TestPaymentAuthorizationRecovery，pytest默认prepend实际加载basename模块中的另一类；实际cls.tmp_path_name为None。新setup_class先调用super后才检查隔离路径，因此已在默认tmp/contract/node启动CKB。断言在合约对齐之前失败，未启动FNN、未建目标发票、未付款或执行资金断言。执行者和Sol复核均漏掉这一实际加载差异，不归因产品。

**历史隔离表述勘误：**181026、182922、184212的runner使用同一BOOTSTRAP；182922和184212已完成类级初始化，实际也使用默认tmp，而非各批命名的运行目录。181026被中断，具体到达阶段仍以其原日志为准。CKB_CLI_HOME和报告目录分别独立不等于整条运行链隔离。此前“独立运行目录/隔离链”的表述不成立；仅删除命名空目录也不足以证明默认tmp未被使用。原报告与证据不覆盖，产品业务未执行的结论不变。

本批在class异常处理内保存CKB配置/日志，框架teardown已停止并清理本次实际node目录；后续只删除本批命名的空CKB CLI目录，保留默认tmp其他内容、历史证据与旧bundle。最终两组自有进程为空、六端口释放；产品仍固定843且clean，不改产品、不动退款。本批未构建，未产生新的Cargo target。完整结果、命令、JUnit、源码快照、复核与清理见RESULT（本地证据：`../../../../report/lsp-payment04-84333ee-20261030T192130/RESULT.md`）。04仍已映射、业务未验证；76ID口径保持48通过/2产品失败/26无该版本业务结果。

后续修正应在实际pytest类入口、任何节点启动之前读取并验证隔离路径，记录实际模块名与节点目录；必须用真实pytest收集对象验证设置确实生效。这里只记录下一次所需修正，本批没有修后重跑。

最终静态检查：设计4行exit0（SPEC-03/04为已确认的人工契约提示）；项目映射125评审/118映射，exit1为9个既有孤儿，无新增孤儿或重复ID；diff检查exit0。原始输出保存在本批document-checks.json。这些检查不替代04业务执行。

## 84333ee 四项收尾补证：磁盘阻塞，尚未新增业务结果（2026-10-30）

用户要求完成SDK/Agent和受影响迁移的现成单测、持久delivery整FNN恢复、上游多preimage失败归因、9项超时回归。固定源码和实际bundle均核验为干净84333ee；不动PAYMENT04及退款。

上游失败归因已完成：`watchtower/force-close-preimage-multiple`的随机端口替换级联将Node1端口18345变为124768，最早connect_peer即失败，后续未有效创建通道/TLC或强关；不能把最后到账0当资金损失。替换函数在base已存在，目标多preimage结算仍无本次有效通过证据。原日志、节点artifact、固定源码和确定性离线重建均保存在归因报告（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/upstream-ci/watchtower-preimage-multiple-analysis.md`）。

复核发现现有RECOVERY05已经执行真实付款中的完整FNN原数据重启，本次只增强原delivery执行键/身份/期限、最终Succeeded及稳定窗直接观察，保留原四端资金和零锁定断言；不新增重复ID或恢复环境，不声称Deferred冷恢复。该补强经GPT-6 Sol High静态复核通过。RECOVERY05加TIMEOUT01/02/03/06/07/08/10/11/12共10方法收集通过exit0，实际pytest类隔离赋值检查通过；收集不是执行。

宿主初始约1.74GiB，清理确认无占用的10个可再生Cargo缓存后约3.77GiB，低于8GiB底线，故本批未启动编译、节点或任何业务测试；SDK/Agent/迁移、增强RECOVERY05和9个TIMEOUT均未运行，既有48通过/2产品失败统计不增加。全部原报告、bundle、旧04与退款VM/快照保留。已请求用户再腾空间；不得为推进而删历史或降低断言。完整状态及继续入口见本批RESULT（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/RESULT.md`）。

映射仍使用RECOVERY05，未增加ID。设计检查exit0；项目映射exit1是9个既有孤儿，无新增孤儿/重复评审ID；git diff --check通过。

### 后续磁盘核查与第二次缓存清理

用户追问是否再次被测试占满后，只读核查确认当前没有FNN/CKB/pytest/Cargo/VM进程；本批证据约3.3MB。19:21批末约10.7GiB至20:23约1.7GiB的空间下降尚未找到直接来源，不能归因于没有执行的本批用例。另确认7份delivery Cargo依赖副本和旧watchtower target缓存为本任务遗留、凌晨后未再写入；只清理其可再生部分，保留全部bundle、原顶层产物、源码、报告、退款VM与快照。最终空闲约6.10GiB（仍低于8GiB），本轮累计从约1.74GiB实际释放约4.36GiB；APFS共享克隆的du不能直接相加。23份受保护产物摘要未变。详细路径及实际前后空间见unit-tests/cargo-cleanup-result.json与watchtower-cache-cleanup-result.json。未启动任何构建或业务测试。

## 临时产物清理与防止磁盘再次耗尽（2026-10-30）

用户要求执行者自行清理产生的临时产物，不再靠反复请求腾空间推进。清理前约6.1GiB可用，本轮清理后约19.3GiB（实际df，非du相加）；此前1.74→6.1GiB的缓存清理记录仍保留。本轮没有构建产品、启动VM或执行产品测试。

- 原项目04源码target的incremental/build/deps/.fingerprint为遗漏的可再生缓存，约14GiB目录的大部分由此组成；仅移除这些缓存，源码保持clean，顶层原产物及04 bundle摘要未变。
- 移除多余843 filter缓存和旧04 filter缓存子目录、12个已Stopped阶段VM的/tmp来源复制品；report中15个完整保全副本及3个基底均保留，不以缺CKB原始DB的tar替代唯一VM盘。清理记录含213项SHA与207项size/mtime保护核对，未做整盘哈希。
- 四批订阅过滤遗留的运行目录已完整压缩到completed-filter-runtimes.tar.gz（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/completed-filter-runtimes.tar.gz`），3160个普通/硬链接文件与源文件逐字节摘要一致后删除tmp来源；包括CKB原始数据。归档SHA和精确路径见filter-runtime-cleanup.json（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/filter-runtime-cleanup.json`）。原节点/SDK日志、JUnit及所有历史运行结果保持。

防复发：两个构建脚本显式CARGO_INCREMENTAL=0；delivery runner复用明确的任务专用target和Cargo home，分别非阻塞独占锁定，不每批克隆依赖；已验证wrapper直接引用。每条命令前、中、后核对8GiB底线和本批空闲下降2GiB上限，预算不逐命令重置；异常终止也保存退出码/清理错误，不能把权限失败当清理成功。只清理确认属于本批且进程已退出的CLI临时目录，报告/共享缓存保留。默认tmp或异常runtime尚未纳入自动删除，须按AGENTS核对归属、归档后清理，不能整体rmtree。

17项离线负例/正常路径自检通过exit0，包含两缓存锁、权限错误落盘、final失败留证和不向已退出旧PGID发信号；这不是产品回归通过。全仓映射125评审/118映射、exit1仍为同9个既有孤儿，无新增ID/重复ID；三个脚本语法、CLI帮助和git diff --check通过。GPT-6 Sol High最终复核结论见review.md（本地证据：`../../../../report/lsp-runner-disk-guard-20261030/review.md`）。磁盘规则已写入AGENTS.md，后续批次复用，不重新堆积每批缓存。

## 84333ee 四项收尾续跑：实际结果（2026-10-30 21:18批）

用户授权沿原预算执行，实际证据见本批RESULT（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-211837/RESULT.md`），当前指针为`report/lsp-closeout-84333ee-active-run.txt`。固定干净`84333eea8488a8afc7e4474aa4bbd0e7e973cee9`，复用184212匹配bundle及单份Cargo target；GPT-6 Sol High完成执行入口和结果归因复核。以下均为本次结果，不改判此前暂停批次。

| 已批准事项 | 实际结果 |
| --- | --- |
| SDK、Agent和三组迁移 | 五条命令各执行一次、全部exit0：82+16+4+1+1=104 passed，0 failed。迁移显式启用rocksdb；准备、构建及执行共367.26秒，小于60分钟。 |
| 加强RECOVERY-05 | 单次pytest 1 failed in94.53s、exit1。真实付款的delivery已读到`in_flight`、attempt_count=1，但新增`observe_delivery(before_restart)`写证据时父目录尚未创建，抛出FileNotFoundError；未调用FNN重启，未取得恢复、付款终态或最终资金结果。属于测试辅助实现遗漏，不是已证实产品失败。 |
| 上游multi-preimage CI归因 | 沿用已完成的原日志/源码归因：顺序端口替换使18345变为124768，首步连接失败；该目标场景仍未验证，不能声称CI通过或产品资金损失。 |
| TIMEOUT01/02/03/06/07/08/10/11/12 | 因前项失败全部未启动；没有重跑、挑选竞争分支或执行已知04/05。 |

失败后的tar命令exit0，但macOS额外生成`._recovery05`成员，使严格归档校验失败并覆盖了runner最终reason；原pytest/JUnit明确保留首个失败原因。原partial归档、run.json和清理失败记录均保留。随后仅做清理：用Python归档剩余10个目录/文件条目并逐项摘要核对，确认自有进程组退出、9端口释放后移除本批独立runtime，耗时仍在原600秒内。见cleanup-completed.json（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-211837/focused/cleanup-completed.json`）。标准测试teardown已导出FNN/SDK数据，CKB原始目录由既有teardown清理；不宣称归档包含完整CKB数据库。

产品源码、bundle和运行时测试源码摘要未漂移；共享可复用缓存、报告和全部历史证据保留，无退款操作。本批结束清理后可用约17.61GiB，较整批起点下降约1.44GiB，未触发8GiB底线或2GiB增长上限。原600/4500秒预算未延长，TIMEOUT预算未使用。TEST-MAP继续对应原RECOVERY-05，不新增ID、不把旧通过转记为本次增强通过；104项Rust测试不折算为LSP行为ID。项目映射检查125评审/118映射、exit1仍为9个既有孤儿，无新增孤儿或重复ID。

## 84333ee 证据目录及归档修复后的新批（2026-10-30 21:43批）

用户授权保留211837失败证据，修正后新批单次执行RECOVERY-05，通过后串行运行原九项TIMEOUT；104项已通过Rust测试只引用原结果，不重跑。新指针仍为`report/lsp-closeout-84333ee-active-run.txt`，实际结果见execution-214323/RESULT（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-214323/RESULT.md`）。固定干净843与原184212 bundle，不改产品、合约、宿主时间或退款。

修复仅补RECOVERY-05证据写入前的父目录创建，并修正新执行入口：证据目的地写入/读回预检，TIMEOUT-12独占创建的recovery叶目录保持不存在；Python tar避免macOS系统tar合成AppleDouble，逐项核对归档及来源未变化后清理；原执行首因和附带清理异常分别落盘。GPT-6 Sol High复核无阻断，三项离线检查exit0（目录契约、含普通/硬链接/符号链接的归档及源变化拒绝删除、首因保留并停止下一阶段），实际10方法收集exit0。准备核对确认九项超时只消费funding输出，不增加无关的commitment-lock升级。

| 用例 | 本批实际结果 |
| --- | --- |
| RECOVERY-05 | 1 passed/150.86秒、exit0。FNN新PID、原SDK同进程；同一delivery/incoming key从in_flight经原数据重启后继续in_flight，最终succeeded并连续五次稳定。付款Success、发票Paid；金额1,000,000 Shannon、fee5,000，四端local余额变化为(1,000,000,-1,000,000,-1,005,000,1,005,000)，remote镜像、原通道/注资、零TLC/锁定、5秒稳定断言均通过。 |
| TIMEOUT-01/02/03/06 | 各执行一次并通过；JUnit分别121.861/117.511/135.645/73.271秒。 |
| TIMEOUT-07 | 单次失败，146.399秒。逾期签名未Applied、承诺未推进和进入保护的断言已执行；随后等待A侧关闭确认60秒超时，A为ShuttingDown/WAITING_COMMITMENT_CONFIRMATION、无shutdown hash。同channel的T交易5c1b48b9…已确认，A交易448863f3…为RBFRejected，符合原07未修的自然竞争假设；不归#1674/#1706，不据此新增产品失败或证明恢复永远失败，未延长到完整300秒扫描窗口。正式07仍记失败。 |
| TIMEOUT-08/10/11/12 | 按失败即停均未运行，不用历史通过替代本版本结果，不为得到A获胜分支重跑。 |

超时组实际`4 passed, 1 failed in597.96s`、exit1，整批exit1。两个归档命令均exit0，每组剩余8项均验证通过且源清单未变；两个独立runtime及owner目录已删除，最终4个自有PGID absent、9端口释放、清理错误为空。正式启动至最终清理751.30秒（RECOVERY阶段152.16秒、TIMEOUT阶段598.97秒），原600/4500/5100秒截止均未重置或延长。最终空闲17.599GiB，相对原包含单测的全局起点下降1.449GiB，未触线；共享缓存、全部新旧证据保留。本批证据约19.74MB，继续明确不宣称保存标准teardown已删的完整CKB数据库。

GPT-6 Sol High的RECOVERY结果复核（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-214323/focused/recovery05-result-review.md`）与TIMEOUT07归因复核（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-214323/focused/timeout07-result-review.md`）分别留档。原TEST-MAP/行预期未变，没有新增ID；本次通过不包含未执行四项。设计检查8行、exit0，既有SPEC-04长期压力/状态字节边界提示保留；映射125评审/118映射、exit1仍为9个既有孤儿，无新增孤儿或重复ID。


## 84333ee 剩余四项超时场景：全部通过（2026-10-30 22:08批）

按用户“优先补主要逻辑、尽快完成”的要求，只运行已确认且214323批未执行的TIMEOUT-08/10/12/11，不新增用例或重跑失败07。固定干净84333ee与184212匹配bundle，无构建、产品修改、宿主时间或退款操作。GPT-6 Sol High复核入口及最终原始证据；三阶段串行，各方法一次，全部exit0。详见完整结果（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-220814/RESULT.md`）。

| 原映射场景 | 本次实际证明 |
| --- | --- |
| TIMEOUT-08/10 | 2 passed，方法114.084/107.606秒。真实A承诺上链、精确花费原funding:0，T实际竞争广播按已批准方案拦截；08匹配旧无TLC承诺且晚提交被真实拒绝，稳定5.016秒；10匹配含目标hash/expiry的完整承诺，发票仍Open。 |
| TIMEOUT-12 | 1 passed，方法434.003秒。真实T关闭确认/A收到RBFRejected，同funding输入已索引；A在264.800秒恢复为远端关闭。完整观察330.957秒，恢复后66.157秒/33个状态样本无回退。固定查询时序控制的结果不扩写为所有自然竞态通过。 |
| TIMEOUT-11 | 1 passed，方法171.773秒。关闭确认后及目标发票自身有效期结束后仍Received而非Paid，收款侧local余额不增加。只证明可观察发票与通道账面未误结算，不等于付款方退款或最终解锁。 |

正式执行含归档清理832.283秒，小于1800秒；阶段600/720/480秒上限未重置。三个剩余runtime各8项归档逐项核验、源清单未变后删除；最终6个自有PGID absent、9端口释放、无runtime或清理错误。剩余17.483GiB，相对包含原104项单测的固定空间基线下降1.565GiB，满足8GiB底线和2GiB总下降限制。旧证据、原产物和共享缓存保留；标准teardown已删除的完整CKB数据库不冒充已归档。

原TEST-MAP与评审行保持，无新增ID；旧TIMEOUT-07仍是60秒A确认等待失败，不被本批独立12结果改判。104项Rust单测、已通过的增强RECOVERY-05及两轮退款均只引用原结果，不重复运行。

## 84333ee 主要逻辑收尾范围（2026-10-30）

目前重点覆盖已有：SDK/Agent及受影响迁移104项；正常付款、签名/撤销、重复提交、原存储恢复、整FNN恢复与连续付款；租户订阅隔离/过滤；接纳一致性正常及故障分支；真实强关承诺、竞争后恢复、无preimage不误结算；两轮链上超时退款及资金守恒。映射存在、旧版本通过和本次执行通过继续分开记录，不给整个PR推算代码覆盖率。不再把普通重复回归、长期压力或PAYMENT-04环境工程作为默认收尾任务。

以下为此前收尾候选清单（历史）：本文件顶部最终结论已取消多preimage本地补跑，不再作为本轮待办。

1. **已有产品失败修复后的定点验证。** DELIVERY-02真实接纳后丢回复导致上游失败、下游成功；早期一致性断言已失败，后续完整资金/30秒稳定断言未执行，不能称已证明永久资金损失。INVOICE-CANCEL-01真实tenant token在取消入口被Unauthorized拒绝，修复后才执行01并继续隔离负向02。TIMEOUT-04/05沿既有#1674开通超时问题，当前GitHub仍OPEN；没有源码变化不重新定位或重复运行。取得修复SHA后只审相关diff并跑这些已有映射；#1706已关闭且843相关回归通过，不列作当前阻断。
2. **独立用户收款与错误目的地拒签。** WATCHTOWER-01/06仍无843正向支持，用户收款D_A必须区别于运营方sponsor S；已有05仅证明更早的sponsor检查拒绝，不能替代到账或输出归属验证。需产品明确此能力是否属于本PR承诺；若属于，必须修复并用已确认01/06验收。已有D=S结算与退款通过不能抹掉该边界。
3. **多preimage强关结算的有效执行。** 当前上游CI在首个connect_peer前因端口级联替换18345→124768失效，未有效进入通道/TLC/结算。需修正上游测试启动配置为完整字段的一次映射、预检三个RPC与三个P2P端口，然后单次运行现有force-close-preimage-multiple并核对实际支出和资金；保留原失败。相邻单preimage通过不替代这一项。当前本机没有Bruno、udt-init或上游部署/节点配置，直接复用Python bundle不能运行该套件；不为这一行默认另建大套环境。原始归因见分析（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/upstream-ci/watchtower-preimage-multiple-analysis.md`）。
4. **最终可合并版本核对。** 当前PR head仍84333ee、六个LSP相关CI作业成功，但PR显示CONFLICTING，不能宣布已可合并。作者解决冲突和上述问题后，针对最终提交diff补相关验证；不重跑全部已通过项。当前状态证据见PR快照（本地证据：`../../../../report/lsp-closeout-84333ee-20261030/execution-220814/pr-state.json`）。

PAYMENT-04“缺授权后同进程补授权恢复”和Received发票取消的未明确契约保留为残余边界，不能记通过；只有产品将其纳入本PR必须支持的契约才提升为本次阻断。已完成退款不再补第3/4轮；原07自然竞争失败保留，不靠重跑挑A获胜。上述项得到修复验证或明确的产品范围裁定后，即可出具限定范围的测试结论，不继续无限追加外围场景。

最终文档检查：超时评审设计11行exit0、git diff --check退出0；项目级映射125评审/118映射，exit1仍为9个既有孤儿（REFUND-01～03、PMP-01～05、SETTLE-01），无新增孤儿或重复评审ID。本次只补实际运行说明，原TEST-MAP不变；不将映射检查称为全绿。原始输出见本批document-checks.json。

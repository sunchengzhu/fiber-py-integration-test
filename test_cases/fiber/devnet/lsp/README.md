# Hosted LSP 通道签名集成测试

本文件保留普通 LSP 的运行版本、已知归因及验证边界。已知产品问题：开通计时器 [#1674](https://github.com/nervosnetwork/fiber/issues/1674)、watchtower 陈旧请求遮蔽 [#1706](https://github.com/nervosnetwork/fiber/issues/1706)（用户已提交）；先复用归因和证据，再决定修复版本回归，不当作未知问题重复定位。

2026-10-28 更新：#1706 已在指定修复提交 `3ce369e` 重编并完成定点验证，适配自检与 watchtower 四条单轮共 5/5 通过，GPT 6.1 sol 复核无阻断。详见文末修复记录；默认基线仍为 04，其历史失败不覆盖、不抹去。

本目录使用真实 FNN、SDK 签名和 CKB devnet，验证 Hosted 通道、签名订阅（含浏览器鉴权）、重试/恢复、付款及超时行为。各批次的固定版本、覆盖边界和真实结果在下文分别记录，不把不同版本或不同范围的通过数合并为当前全量通过。watchtower 的隔离链合约预检阻断已解决；02 已经独立复现并确认产品 bug：陈旧首项遮蔽有效后继请求，显式批准后完整 240s 仍未恢复；正式验收未完成，见文末 2026-10-27 诊断记录。

本文的运行结论随 Git 保存；标为“本地证据”的 `report/...` 路径均相对仓库根目录，原始报告、节点日志、失败数据和代码快照全部保留在本机，不随 Git 提交或推送。历史命令和退出码按当时执行情况保留；复现时使用新的输出目录，避免覆盖原始结果。

| 测试文件 | 场景 | 评审表 |
| --- | --- | --- |
| `test_channel_signing_isolation.py` | 单租户等待不阻塞另一租户；跨租户读取、提交被拒绝 | [LSP-SIGN-01～03](../../../../reviews/lsp/channel-signing-isolation.md) |
| `test_channel_signing_retry.py` | 相同、冲突、旧签名提交；请求断线、响应超时；支付只结算一次 | [LSP-RETRY-01～06](../../../../reviews/lsp/channel-signing-retry.md) |
| `test_channel_signing_recovery.py` | 正常开通→收款→协作关闭；SDK/FNN 在开通、支付或关闭中途恢复 | [LSP-RECOVERY-01～07](../../../../reviews/lsp/channel-signing-recovery.md) |
| `test_signing_subscriptions.py` | 当前工作补发、实时状态、租户及 host 范围、真实 SDK 重连、独立订阅与按连接取消 | [LSP-SUBSCRIPTION-01～07、10～13](../../../../reviews/lsp/signing-subscriptions.md) |
| `test_browser_signing_subscriptions.py` | 浏览器子协议鉴权、token 编码兼容、握手/RPC 拒绝及双租户隔离 | [LSP-SUBSCRIPTION-14～19](../../../../reviews/lsp/signing-subscriptions.md) |
| `test_channel_signing_deadline.py` | 开通超时、支付截止保护、指定承诺强关及受控 B 败方恢复 | [LSP-TIMEOUT-01～08、10～12](../../../../reviews/lsp/channel-signing-deadline.md) |
| `test_delayed_payment_recovery.py` | 真实付款在在线延迟、SDK 完全离线和其他租户先结算后恢复 | [LSP-PAYMENT-01～03](../../../../reviews/lsp/delayed-payment-recovery.md) |

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

当前 FNN、SDK agent 和本地 SDK 控制驱动固定使用
`04c206465b48da85b99aa58e80afe9801a2cb2db`。下文 `24b5c38` 的运行记录保留原版本，不能用当前构建复现并仍标作旧版结果。首次准备源码目录：

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

## Watchtower05 独立复现输入

历史 `report/lsp-watchtower-05-*` 只保存当时证据，运行不依赖该目录。调用者需准备**干净且精确为 84333eea8488a8afc7e4474aa4bbd0e7e973cee9 的 Fiber 源码**、同版本基础 bundle（含 `build.json`、FNN/agent、凭证与 `driver-build/Cargo.lock`）、可写 Cargo target、以及本测试 checkout 内尚不存在的输出路径。`--driver-only` 校验源码、锁文件、基础产物摘要和 FNN 版本，只构建本地测试驱动并复用基础 FNN/agent：

```bash
REVISION=84333eea8488a8afc7e4474aa4bbd0e7e973cee9
python3 scripts/build_lsp_test_binaries.py \
  --source "$FIBER_SOURCE" --revision "$REVISION" --driver-only \
  --base-bundle "$LSP_BASE_BUNDLE" --target-dir "$LSP_CARGO_TARGET" \
  --output "$PWD/download/fiber/watchtower-05-$REVISION"
LSP_TEST_REVISION="$REVISION" \
LSP_TEST_BUNDLE="$PWD/download/fiber/watchtower-05-$REVISION" \
python -m pytest -x -vv -s -o addopts= \
  test_cases/fiber/devnet/lsp/test_watchtower_settlement.py::TestWatchtowerSettlement::test_missing_approval_then_adapted_settlement \
  test_cases/fiber/devnet/lsp/test_watchtower_settlement.py::TestWatchtowerDestinationRejection::test_independent_destination_rejects_operator_payout
```

上述测试需本仓库既有 devnet/CKB 环境与合约配置；命令是复现入口，不代表本独立分支重新执行过节点。

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

## 84333ee Hosted租户发票取消：真实入口拒绝（2026-10-30）

用户已授权按顺序持续推进，无需逐阶段确认。01/02已实施并建立TEST-MAP，03的Received取消契约仍未确定且未映射。本次仅对固定84333ee执行01单次诊断，15分钟总上限、完整pytest进程最多480秒；失败即停，不运行02/03。真实Agent链配置与安全预像释放控制入口经GPT 6 sol复核，但本次在取消入口前即被产品阻断，没有执行正向释放。

证据为 `report/lsp-invoice-cancel-84333ee-20261030T003644/`：`runner.py/run.json`保存实际命令、源码与产物摘要、绝对截止和退出码。独立driver-only构建命令21.60秒退出0（阶段25.29秒）、收集退出0；01运行93.55秒退出1，非预算到期；最终收尾通过、`residual-processes.json=[]`，产品仍干净843、原工作区及旧产物未变。

真实A tenant token先创建仅含payment hash的发票，客户端保留preimage，`get_invoice=Open`且SDK授权保存；随后A自己的 `cancel_invoice` 收到JSON-RPC `-32999 Unauthorized`。原始 `cancel-01.log:107`、用例 `observations.jsonl` 第151～155条及 `fiber-1/node.log:1246` 一致，节点明确输出 `tenant token is not allowed to call cancel_invoice`。固定源码 `crates/fiber-lib/src/rpc/tenant.rs` 的允许列表缺少该方法，与Luso报告一致，归为产品租户入口缺口。

入口拒绝后按规则停止，没有send_payment/get_payment或后置资金快照；只能证明真实租户取消入口失败，不能把基线无TLC/镜像余额说成取消前后资金已验证。01的旧付款失败、资金回基线和新付款成功步骤未运行，02/03未运行。GPT 6 sol独立审计原始请求、发票、身份、节点日志、退出码和边界；本次不重跑已知拒绝，不使用operator token绕过。

### 复现实参

固定源码 SHA 为 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`。下面的 `SOURCE` 必须是该提交的干净源码；`BASE_BUNDLE` 必须是与该提交匹配且清单摘要通过验证的既有基础 bundle。两者及 Cargo 缓存由执行环境提供，不依赖本 PR 中的本地 `report/`。`BUNDLE` 必须在当前测试 checkout 内，满足 `_lsp_test.py` 的路径约束；每次使用新的 `RUN_DIR` 和 `TARGET`。

```bash
TEST_PYTHON=/absolute/path/to/prepared/test-venv/bin/python
REVISION=84333eea8488a8afc7e4474aa4bbd0e7e973cee9
SOURCE=/absolute/path/to/clean/fiber-84333ee
BASE_BUNDLE=/absolute/path/to/matching/84333ee/base-bundle
REVIEWED_TARGET=/absolute/path/to/reviewed/cargo-target
TARGET=/private/tmp/lsp-invoice-cancel-target-unique
RUN_DIR="$PWD/report/lsp-invoice-cancel-84333ee-unique"
BUNDLE="$RUN_DIR/bundle"
EVIDENCE="$RUN_DIR/cases"
cp -cR "$REVIEWED_TARGET" "$TARGET"
"$TEST_PYTHON" scripts/build_lsp_test_binaries.py \
  --source "$SOURCE" --revision "$REVISION" --driver-only \
  --base-bundle "$BASE_BUNDLE" --output "$BUNDLE" --target-dir "$TARGET"
mkdir "$EVIDENCE"
LSP_TEST_REVISION="$REVISION" LSP_TEST_BUNDLE="$BUNDLE" \
LSP_PAYMENT_REPORT_DIR="$EVIDENCE" LSP_RUN_ARTIFACTS="$EVIDENCE" \
PYTHONPATH="$PWD" CKB_CLI_HOME="$EVIDENCE/ckb-cli-home" \
"$TEST_PYTHON" -m pytest -x -vv -s -o addopts= \
  --junitxml="$EVIDENCE/01.xml" --html="$EVIDENCE/01.html" \
  test_cases/fiber/devnet/lsp/test_hosted_invoice_cancellation.py::TestHostedInvoiceCancellation::test_open_invoice_cancelled_old_payment_fails_new_payment_succeeds
```

该命令只选择 01。历史批次使用独立执行器强制 15 分钟总上限及 pytest 进程 480 秒上限；手工复现也须施加同等进程组截止，不得因默认 pytest 无硬截止而无限等待。

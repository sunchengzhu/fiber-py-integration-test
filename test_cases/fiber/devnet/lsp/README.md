# Hosted LSP 通道签名集成测试

本批使用真实 FNN、SDK 签名和 CKB devnet，覆盖私有 CKB 通道的开通、单笔收款、协作关闭，
以及租户隔离、签名重试和 SDK/FNN 进程恢复。当前收录核心业务 16 条、签名订阅 14 个方法（11 个行为）及 deadline 11 条，共 41 个方法。历史完整回归使用当时的 40 条；新增 12 的聚焦与固定复跑在下文单独记录，不能合称当前 41 条已全量通过。
本批未新增 watchtower 链上资金取回、租户主动付款、UDT 或 MPP 用例。

本文的运行结论随 Git 保存；标为“本地证据”的 `report/...` 路径均相对仓库根目录，原始报告、节点日志、失败数据和代码快照全部保留在本机，不随 Git 提交或推送。历史命令和退出码按当时执行情况保留；复现时使用新的输出目录，避免覆盖原始结果。

| 测试文件 | 场景 | 评审表 |
| --- | --- | --- |
| `test_channel_signing_isolation.py` | 单租户等待不阻塞另一租户；跨租户读取、提交被拒绝 | [LSP-SIGN-01～03](../../../../reviews/lsp/channel-signing-isolation.md) |
| `test_channel_signing_retry.py` | 相同、冲突、旧签名提交；请求断线、响应超时；支付只结算一次 | [LSP-RETRY-01～06](../../../../reviews/lsp/channel-signing-retry.md) |
| `test_channel_signing_recovery.py` | 正常开通→收款→协作关闭；SDK/FNN 在开通、支付或关闭中途恢复 | [LSP-RECOVERY-01～07](../../../../reviews/lsp/channel-signing-recovery.md) |
| `test_signing_subscriptions.py` | 当前工作补发、实时状态、租户及 host 范围、真实 SDK 重连、独立订阅与按连接取消 | [LSP-SUBSCRIPTION-01～07、10～13](../../../../reviews/lsp/signing-subscriptions.md) |
| `test_channel_signing_deadline.py` | 开通超时、支付截止保护、指定承诺强关及受控 B 败方恢复 | [LSP-TIMEOUT-01～08、10～12](../../../../reviews/lsp/channel-signing-deadline.md) |

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

FNN、SDK agent 和本地 SDK 控制驱动固定使用
`24b5c38bc098aeb29de5f6af7ac28dc667f218e3`。新建独立源码目录：

```bash
git clone --no-checkout https://github.com/nervosnetwork/fiber.git download/fiber/source-pr-1623
git -C download/fiber/source-pr-1623 fetch origin pull/1623/head
git -C download/fiber/source-pr-1623 checkout --detach 24b5c38bc098aeb29de5f6af7ac28dc667f218e3
venv/bin/python scripts/build_lsp_test_binaries.py --source download/fiber/source-pr-1623
```

也可将 `--source` 指向已有的同版本干净 checkout。产物、上游公开测试认证材料和构建清单放在
`download/fiber/pr-1623/`，不提交到 Git；启动测试时会校验版本、二进制和驱动源码摘要。
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

## 历史 SSE 运行记录（4028884）

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

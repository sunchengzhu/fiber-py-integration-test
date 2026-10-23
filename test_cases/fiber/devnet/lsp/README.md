# Hosted LSP 通道签名集成测试

本批使用真实 FNN、SDK 签名和 CKB devnet，覆盖私有 CKB 通道的开通、单笔收款、协作关闭，
以及租户隔离、签名重试和 SDK/FNN 进程恢复。本次 WS 迁移提交收录核心业务 16 条、签名订阅 14 个方法（11 个行为），共 30 个方法。下述历史完整回归还包含当时本地的 10 条 deadline 测试；deadline 自动化与详细证据由后续独立提交纳入。
本批未新增 watchtower 链上资金取回、租户主动付款、UDT 或 MPP 用例。

本文的运行结论随 Git 保存；标为“本地证据”的 `report/...` 路径均相对仓库根目录，原始报告、节点日志、失败数据和代码快照全部保留在本机，不随 Git 提交或推送。历史命令和退出码按当时执行情况保留；复现时使用新的输出目录，避免覆盖原始结果。

| 测试文件 | 场景 | 评审表 |
| --- | --- | --- |
| `test_channel_signing_isolation.py` | 单租户等待不阻塞另一租户；跨租户读取、提交被拒绝 | [LSP-SIGN-01～03](../../../../reviews/lsp/channel-signing-isolation.md) |
| `test_channel_signing_retry.py` | 相同、冲突、旧签名提交；请求断线、响应超时；支付只结算一次 | [LSP-RETRY-01～06](../../../../reviews/lsp/channel-signing-retry.md) |
| `test_channel_signing_recovery.py` | 正常开通→收款→协作关闭；SDK/FNN 在开通、支付或关闭中途恢复 | [LSP-RECOVERY-01～07](../../../../reviews/lsp/channel-signing-recovery.md) |
| `test_signing_subscriptions.py` | 当前工作补发、实时状态、租户及 host 范围、真实 SDK 重连、独立订阅与按连接取消 | [LSP-SUBSCRIPTION-01～07、10～13](../../../../reviews/lsp/signing-subscriptions.md) |

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

当前 `24b5c38` 的 [签名订阅用例](../../../../reviews/lsp/signing-subscriptions.md)已获人工确认；14 个方法位于 `test_signing_subscriptions.py`，对应 11 个 LSP-SUBSCRIPTION 行为，TEST-MAP 已同步。核心重试和恢复检查点已适配同一版本的真实 SDK WS 重订阅；旧 SSE 文件退休，历史结果保留在下节。

当前提交的核心与订阅 30 个方法可串行运行；每次复现使用新的输出目录：

```bash
venv/bin/python -m pytest -vv -s --tb=short \
  test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_retry.py \
  test_cases/fiber/devnet/lsp/test_channel_signing_recovery.py \
  test_cases/fiber/devnet/lsp/test_signing_subscriptions.py
```

2026-10-23 的同源 `24b5c38` 验证：正常主流程 `1 passed in 112.47s`、聚焦订阅与恢复 `7 passed in 612.86s`，均退出 0。随后包含当时本地 10 条 deadline 的 40 条历史完整运行，首次为 `5 failed, 35 passed in 4152.55s`，修正 operator 测试准备后为 **`2 failed, 38 passed in 4123.17s`，退出 1**。其中本次提交的核心 **16/16**、签名订阅 **14/14** 全部通过；不能把历史 40 条写成全部通过。

订阅 10 的初始失败分别来自旧 operator 凭据缺少 subscriptions 写权限、准备金额恰好触及自动接受门槛；补齐 devnet 测试凭据能力并避开该准备边界后，单条 `1 passed in 97.26s`，原业务断言保留。首轮及修复后结果均保存在本地证据 `report/lsp-subscription-24b5c38/`，包括 `regression.*`、`operator-fix.*`、`operator-fix2.*`、`regression-final.*` 及对应节点数据。

历史完整运行最后两条失败为 `LSP-TIMEOUT-04/05`：普通开通计时器调度缺口，由 [Fiber #1674](https://github.com/nervosnetwork/fiber/issues/1674) 跟踪。旧 08/10 首轮还暴露 A/T 强关竞争下的夹具假设问题；这些 deadline 行和后续恢复验证另行提交，不归为 WS 迁移通过证据。

GPT 6.1 sol 已独立复核本批代码、构建版本与原始日志/JUnit/退出码：核心与订阅 30 个方法无剩余代码阻塞，保留上述已知产品失败与测试风险。产品源码未修改。

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

# Hosted LSP 通道签名集成测试

本批使用真实 FNN、SDK 签名和 CKB devnet，覆盖私有 CKB 通道的开通、单笔收款、协作关闭，
以及租户隔离、签名重试和 SDK/FNN 进程恢复。共 16 条；不覆盖业务签名截止保护、watchtower
强关后的资金取回、租户主动付款、UDT 或 MPP。

| 测试文件 | 场景 | 评审表 |
| --- | --- | --- |
| `test_channel_signing_isolation.py` | 单租户等待不阻塞另一租户；跨租户读取、提交被拒绝 | [LSP-SIGN-01～03](../../../../reviews/lsp/channel-signing-isolation.md) |
| `test_channel_signing_retry.py` | 相同、冲突、旧签名提交；请求断线、响应超时；支付只结算一次 | [LSP-RETRY-01～06](../../../../reviews/lsp/channel-signing-retry.md) |
| `test_channel_signing_recovery.py` | 正常开通→收款→协作关闭；SDK/FNN 在开通、支付或关闭中途恢复 | [LSP-RECOVERY-01～07](../../../../reviews/lsp/channel-signing-recovery.md) |

## 准备环境

以下命令从测试仓库根目录执行。已完成的 devnet 准备步骤可跳过；需要目标 Fiber 源码要求的
Rust 工具链和本机构建依赖，以及现有框架使用的 `lsof`。
本分支基于测试仓库 `v0.10.0` 的 `6088115`，沿用该版本的
`source/fiber/data.2026.0929.tar.gz` 链快照。

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m download
cp download/0.202.0/ckb-cli source/ckb-cli
```

FNN、SDK agent 和本地 SDK 控制驱动固定使用
`8419c005e2d0e737c5abf7e0f881aaedbc6fd300`。新建独立源码目录：

```bash
git clone --no-checkout https://github.com/nervosnetwork/fiber.git download/fiber/source-pr-1623
git -C download/fiber/source-pr-1623 fetch origin pull/1623/head
git -C download/fiber/source-pr-1623 checkout --detach 8419c005e2d0e737c5abf7e0f881aaedbc6fd300
venv/bin/python scripts/build_lsp_test_binaries.py --source download/fiber/source-pr-1623
```

也可将 `--source` 指向已有的同版本干净 checkout。产物、上游公开测试认证材料和构建清单放在
`download/fiber/pr-1623/`，不提交到 Git；启动测试时会校验版本、二进制和驱动源码摘要。
`_sdk_driver.rs` 只为 Python 提供真实 SDK 的授权、签名存储和恢复观察入口，不修改产品源码。
当前上游对 nonce 复用保留警告，功能测试通过不等于该安全问题已从根本修复。

## 运行本批 16 条

测试占用本地固定端口 8114、8125、8227～8230，须串行运行，不能与其他使用同组端口的测试并发。
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

2026-10-20 在旧测试仓库基线 `v0.9.1 / 852c97d`、上述固定 FNN/SDK 版本及最终驱动上实测：
`16 passed in 2643.36s`，退出码 0，无跳过。
2026-10-22 在 `v0.10.0 / 6088115` 基线上完整回归：`16 passed in 2579.42s`，无失败、错误或跳过。
优化 LSP 节点准备后，相同基线、FNN/SDK 和 16 条用例再次通过：`16 passed in 1473.33s`，
退出码 0，无失败、错误或跳过。整轮从 42 分 59 秒降到 24 分 33 秒，耗时减少约 43%。
这些是本批范围的执行结果，不代表整个 LSP PR 已验收。

`python3 scripts/check_test_map.py` 检查评审行与 `TEST-MAP` 的对应关系。复选框只表示存在映射；
本批 16 条均有映射。仓库原有 `PMP-01～05`、`SETTLE-01` 缺少对应评审行，会使全库检查退出码为 1，
与本批执行结果分开处理。

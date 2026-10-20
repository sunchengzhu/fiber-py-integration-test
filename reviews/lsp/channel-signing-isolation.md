# Hosted LSP 通道签名请求的租户隔离用例评审

评审范围：同一个公共 LSP 的两个租户，在开通各自私有通道时，通道签名请求只能由所属租户读取和提交。首批仅包含下表三行。

原始评审源码版本：[Fiber PR #1623](https://github.com/nervosnetwork/fiber/pull/1623)，HEAD `774e61bbe54b8ab335b235458d14df2f8feea23d`，base `271e13c2911247baf6f178be52cab98e23fb5fd4`。

测试仓库验证基线：`852c97daeb41b9b3824dae184d4952ddad1069d1`。

当前执行目标为 `8419c005e2d0e737c5abf7e0f881aaedbc6fd300`，用例 ID 和业务预期不变。
构建与运行步骤见 [LSP 测试说明](../../test_cases/fiber/devnet/lsp/README.md)；下文旧 SHA 链接保留原始预期依据。

本批从固定提交的差异、认证入口、租户路由、签名查询/提交处理及相应上游测试推导预期。验证边界仅限下表三条，尚未完成整个 PR 的逐行代码审查；此前的文档和 CI 调研不作为本地验证结果。

## 接口说明

- 公共 LSP 记为 T；A、B 是 T 内部的两个租户运行时，各有独立 RootSigner、签名存储、Biscuit 和私有通道 A–T、B–T。A、B 不是两个独立 FNN 进程。
- 身份由 `Authorization: Bearer <租户 Biscuit>` 中经认证的 authority `tenant(...)` 决定。请求中的 `channel_id` 选择该租户命名空间内的通道，不授予访问另一租户的权限。测试使用注册返回的真实租户 token，不使用 operator token 执行被测操作。
- `get_channel_signing_status({channel_id})` 返回持久化的签名状态。`SignatureRequired` 包含 `request_id`、待推进的转换及签名内容；读取本身不应用签名。
- `submit_channel_signature({channel_id, request_id, partial_signature, next_material})` 提交客户端基于该请求生成的 MuSig2 部分签名及后续公开材料。首次有效提交返回 `{"type":"Applied"}`，随后继续处理该通道的签名请求，直到 `ChannelReady`。
- 查询和提交分别经过租户存储与租户运行时路由，故读隔离、写隔离需要分别验证。另一租户的真实通道在当前租户下应按“找不到通道”处理，不返回其待签内容，不消耗其请求。
- 本批不验证资金钱包签名算法、SDK 的 Auto/Manual 审批策略、watchtower 签名或支付结算。外部注资签名只是创建真实通道的前置条件，与通道 remote signer 分开。

## 本批配置与观察方式

| 配置或输入 | 作用 | 本批如何使用及原因 |
| --- | --- | --- |
| `services` 中的 `lsp`、`rpc.enabled_modules` 中的 `lsp`/`channel` | 启动 Hosted LSP 服务并暴露管理、通道 RPC | 在 T 上显式启用；普通节点模板当前没有启用 LSP |
| `rpc.biscuit_public_key`、`rpc.biscuit_private_key_path` | 验证身份并签出租户 token | 使用匹配的测试密钥；由 operator 完成注册准备，由 A、B 各自的有效 token 调用被测接口 |
| `lsp.max_active_tenants` | 限制同时活跃的租户数量 | 配置为 2，容纳 A、B；本批不触发容量驱逐，避免把准入失败误认为隔离成功 |
| `fiber.auto_accept_channel_ckb_funding_amount` | 自动接受传入通道并提供本端注资；设为 0 会禁用自动接受 | 配置为 500 CKB；提前给 T 准备两笔独立资金，并在开通通道前完成两个租户钱包的充值，避免后续充值花掉待签通道预留的输入 |
| `public: false`、目标为 T 的公钥 | 创建租户至公共 LSP 的私有通道 | A、B 各建一条通道，使用可区分的注资输入，避免注资竞争干扰隔离判断 |
| `external_channel_signer` | 提供客户端生成的通道公钥、承诺点和公开 nonce | 分别来自 A、B 的真实 SDK 签名端，保证走外部签名路径 |
| 有效的 `channel_id`、`request_id` 和签名提交体 | 确保负例只改变租户身份 | 跨租户提交保持签名体逐字段不变，只替换 Bearer token；随后让所有者提交同一份签名体证明它有效 |

在两条通道都明确进入 `SignatureRequired` 后再执行被测操作，不能以固定睡眠猜测状态。暂缓签名仅用于稳定取样，操作在请求有效期内完成；签名超时另批评审。

“请求保持不变”指所有者再次查询时，整个 `status`（包括 `request_id`、`transition`、`content` 及可选结算材料）与操作前一致，通道没有因越权调用进入新的状态。最终通过租户及 T 两侧的 `list_channels` 确认对应通道达到 `ChannelReady`。不以日志或 HTTP 200 单独判定成功；拒绝必须是 FNN 返回的 JSON-RPC 错误，连接失败或测试超时不能算通过。

## 待评审用例

| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-SIGN-01` | - [x] 同一 LSP 中 A、B 各自的私有通道均等待外部签名；A 使用自己的 token 查询并提交 SDK 生成的有效签名，继续完成开通，期间暂缓 B 的签名；随后恢复 B 签名 | A 的首次提交返回 `Applied`，A–T 两侧达到 `ChannelReady`；在恢复 B 签名前，B 的待签请求与通道状态保持不变；恢复后 B 的首次提交也返回 `Applied`，B–T 两侧达到 `ChannelReady` | 一个租户等待签名阻塞其他租户，或应用签名时误推进其他租户的通道 | P0 |
| `LSP-SIGN-02` | - [x] 同一 LSP 中 A、B 各自的私有通道均等待外部签名；A 用自己的有效 token 和 B 的真实 `channel_id` 查询签名状态，B 再对 A 做对称查询；随后各自正常签名 | 两次越权查询均返回找不到通道的 RPC 错误，不返回另一租户的待签内容；A、B 用自己的 token 复查时原请求和通道状态均未改变；各自正常签名后，两条通道在对应双方达到 `ChannelReady` | 通过已知通道 ID 读取其他租户的交易签名内容，或只读请求改变待签状态 | P0 |
| `LSP-SIGN-03` | - [x] 同一 LSP 中 A、B 各自的私有通道均等待外部签名；取得 B 的 SDK 对当前请求生成、尚未提交的完整有效签名体，由 A 的有效 token 原样提交；对 A 的签名体做对称操作；随后各所有者用自己的 token 提交原签名体 | 两次越权提交均返回找不到通道的 RPC 错误；两租户的原请求和通道状态均未改变；原签名体由所属租户首次提交时返回 `Applied`，继续签名后，两条通道在对应双方达到 `ChannelReady` | 仅凭有效签名绕过租户授权，或越权失败后请求被消耗、nonce 材料被改写而无法恢复开通 | P0 |

三行均为 P0：它们共同验证多租户签名的基本权限边界及正常使用能力。第三行使用有效签名，避免无效签名本身的校验失败掩盖租户路由错误；本批不把已经成功应用的签名再次提交，因此没有声称覆盖重复提交的幂等性。

## 场景展开

以下步骤解释上面三行的执行顺序和观察位置，沿用同一用例 ID 与预期，不增加独立测试点。

### 共同前置状态

1. 启动真实 CKB devnet 与公共 LSP T；T 启用 Biscuit 认证，允许同时激活两个租户。
2. 分别注册 A、B，取得各自的有效租户 token；两端签名密钥和持久化存储彼此独立。
3. A、B 各自申请一条到 T 的私有通道，提供各自 SDK 的外部签名材料，分别完成钱包注资签名及提交。
4. 暂缓两条通道的首次客户端签名提交，直到各所有者均可查到自己的 `SignatureRequired`。记录各自的完整签名状态及通道状态。两条通道尚未达到 `ChannelReady`。

每条用例从独立的共同前置状态开始，不依赖另一条用例留下的通道。测试判断的是同一 LSP 内的租户隔离；CKB、FNN、签名端版本未匹配或共同前置未达成时，应报告环境或准备失败，不能把它当作越权请求被正确拒绝。

### LSP-SIGN-01：正常开通时互不阻塞

1. 保持 B 的签名尚未提交；A 用自己的 token 查询并提交当前请求的有效 SDK 签名。检查首次提交返回 `Applied`。
2. 继续处理 A 后续的开通签名请求，直到 A 和 T 对该通道都报告 `ChannelReady`。此时不需要先完成 B 的签名。
3. 用 B 的 token 复查 B：仍是原来的待签请求，完整签名状态及通道状态均未改变。
4. B 用自己的 token 提交原请求的有效签名，检查首次提交返回 `Applied`；继续签名，直到 B 和 T 对该通道都报告 `ChannelReady`。

这里 B 等待自己的签名是正常前置条件；预期现象是 A 可以继续开通，B 提交签名后也能开通。没有模拟 B 掉线、签名错误或超时，也不要求固定毫秒级的完成时延。

### LSP-SIGN-02：其他租户不能读取待签请求

1. 用 A 的有效 token 查询 B 的真实通道 ID，检查 FNN 返回找不到通道的 JSON-RPC 错误，不返回 B 的待签内容。
2. 用 B 的有效 token 查询 A 的真实通道 ID，检查同样的拒绝结果。
3. A、B 分别查询自己的通道，检查两份完整签名状态及通道状态均与操作前一致。自身查询成功也是 token 有效、RPC 可用的对照。
4. A、B 分别正常签名，继续到两条通道在租户和 T 两侧都达到 `ChannelReady`。

只改变调用者身份与目标通道的所属关系，不使用不存在的通道 ID 或无效 token，否则不能证明跨租户读取被隔离。

### LSP-SIGN-03：有效签名也不能跨租户提交

1. A、B 的 SDK 分别为各自当前请求生成有效签名提交体，均暂不提交到 T。
2. 用 A 的有效 token 提交 B 的完整签名体，检查找不到通道的 JSON-RPC 错误；用 B 的有效 token 原样提交 A 的签名体，检查同样的拒绝结果。
3. A、B 分别查询自己的通道，检查两份完整签名状态及通道状态均未改变。
4. 各所有者用自己的 token 提交刚才被越权提交的同一份签名体，首次提交均应返回 `Applied`。不重新签名或替换请求内容来绕过可能被损坏的原请求。
5. 继续处理后续开通签名请求，直到两条通道在租户和 T 两侧都达到 `ChannelReady`。

这一步把“租户无权提交”和“签名本身无效”区分开；所有者能够应用原签名并完成开通，才证明越权失败没有损坏后续正常流程。它不验证已经应用过的签名再次提交时的幂等行为。

## 源码依据与已有覆盖

本批已阅读的关键路径均固定在上述 HEAD：

- [认证中间件](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/rpc/middleware.rs#L62)从验证后的 token 注入租户身份；[租户 RPC 边界](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/rpc/tenant.rs#L17)允许本批两个签名方法。
- [签名查询及提交 RPC](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/rpc/channel.rs#L348)分别调用租户查询和运行时；[LSP 服务](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/service.rs#L418)在租户命名空间查找状态；[签名命令路由](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/fiber/network.rs#L3221)只查当前运行时的通道。
- [上游跨租户签名测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/signer_isolation.rs#L451)已断言越权查询、提交失败，原请求不变且所有者可成功提交。其注资使用 mock，不等于独立 FNN 与真实 CKB 的本地集成验证。
- [上游双租户并发测试](https://github.com/nervosnetwork/fiber/blob/774e61bbe54b8ab335b235458d14df2f8feea23d/crates/fiber-lib/src/lsp/tests/integration.rs#L657)还验证请求串用失败、签名端恢复后两通道就绪。本批补充 Python 测试仓库中真实进程、HTTP 认证、SDK 签名和真实链上注资的组合验证，并保留 A/B 对称检查。

测试仓库已有的普通节点恢复、结算测试可复用基础能力，但没有 Hosted LSP 身份与 remote signer：

- `test_cases/fiber/devnet/send_payment/offline/test_restart.py`：普通节点重启后支付成功及余额变化。
- `test_cases/fiber/devnet/connect_peer/test_channel_actor_disconnect_reconnect.py`：普通节点断连/重连的通道和 TLC 观察；另一个 `disconnect_peer/test_reconnect_one_channel.py` 当前标记为 skip，不能计作通过的恢复验证。
- `test_cases/fiber/devnet/settle_invoice/test_settle_invoice.py`：hold invoice 结算与普通支付状态。
- `test_cases/fiber/devnet/watch_tower/test_watch_tower.py`：普通通道强关和链上结算余额。

## 相邻范围与后续小批次

| 范围 | 已定位的上游内容 | 本轮边界与仍需分析的行为 |
| --- | --- | --- |
| 租户生命周期和完整 RPC 隔离 | `lsp/tests/integration.rs`、`rpc/tenant.rs`、`rpc/biscuit.rs` | 本批只分析通道签名隔离；注册凭证、管理方法拒绝、发票/支付/列表隔离另批 |
| 通道签名恢复和重复提交 | `lsp/tests/signer_isolation.rs`、`fiber/tests/external_signer_restart.rs`、Bruno `lsp-remote-signer` | 已定位冷查询、驱逐恢复、各签名转换的重启、截止时间和幂等测试；尚未逐项核对实现与断言。需区分租户驱逐、整个 FNN 重启、签名端重启、传输掉线和恢复后的请求有效性 |
| Watchtower 外部签名 | `watchtower/external_signing_tests.rs`、Bruno `lsp-remote-signer-watchtower*` | 后续核对租户命名空间、签名超时/重放、驱逐后扫描、preimage 与撤销路径，并通过链上花费及最终余额验证结算 |
| 离线支付与结算一致性 | `lsp/tests/mod.rs`、`lsp/tests/integration.rs`、Bruno `lsp` | 后续核对离线缓存、重连、上下游结算恢复和重复投递；联合判断支付/发票终态、TLC 清理、余额及结算次数 |

本次只查看一次 PR 检查汇总：其中 `lsp`、`lsp-remote-signer` 和四项 `lsp-remote-signer-watchtower*` E2E 显示 SUCCESS（[上游运行](https://github.com/nervosnetwork/fiber/actions/runs/35499891496)）。这只说明相应 CI 作业结果，不证明上述风险全部覆盖，也不替代本地运行。

## 运行环境与版本约束

| 项目 | 本批自动化使用的环境 | 验证边界 |
| --- | --- | --- |
| FNN | 本批测试在自身的 `fiber_version` 中指定 `download/fiber/pr-1623/fnn`，模板复用 `CURRENT_DEV`；当前版本为 `fnn Fiber v0.10.0-rc1 (8419c00 2026-10-16)` | 预合并版本选择仅保留在测试侧，公共框架不增加 PR 专用枚举；普通测试仍使用原有默认版本 |
| 客户端签名端 | 同一干净提交构建官方 `fiber-lsp-sdk-agent` 和本地 `lsp-integration-driver`；测试通过本地驱动调用真实 SDK/agent | 包版本 `0.1.0` 不能单独证明匹配；启动前校验构建来源、二进制及驱动源码摘要 |
| 构建 | `scripts/build_lsp_test_binaries.py` 检查固定 HEAD 和已跟踪文件无修改；以 `--locked` 构建官方产物，随后构建本地 SDK 控制驱动 | 使用 dev profile 和 `fiber-bin/debug-add-tlc`；测试专用注资签名 RPC 不代表生产钱包接口 |
| Python 与 CKB | Python 3.13.2、pytest 7.3.2、默认 CKB 0.202.0 与仓库 devnet 数据 | 使用真实链上注资；本批不证明其他链、合约或移动端平台的兼容性 |
| 配置及 RPC | 测试为公共节点启用 LSP service/module、匹配的测试 Biscuit 密钥及双租户容量 | 租户请求带各自 token；operator 仅用于准备及读取公共节点状态 |
| 注资与签名控制 | 两个租户钱包和公共节点资金在开通前准备；两个独立 SDK 进程经测试 HTTP 转发器连接 FNN | 第一份有效签名暂不转发，越权验证直接请求真实 FNN；不能把转发器的暂缓响应当作产品拒绝结果 |

构建脚本将上游公开的测试 Biscuit 密钥与 operator token 一并复制到独立产物目录，
并生成用于校验产物的 `build.json`。不使用实际钱包凭证。产品原工作区保持原分支；
可使用任意检出上述固定提交、没有已跟踪文件修改的独立 checkout 构建。
若后续升级 PR 提交，先检查本批路径的变化，预期有实质变化时重新评审相应行。

自动化位于 `test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py`，复用
`FiberTest` 的 CKB/FNN 生命周期与通用 RPC；节点、租户和开通准备提取到同目录的 `_lsp_test.py`，供后续 LSP 用例复用。
每个测试方法仍重新创建 A、B，
通过局部转发器 `_signer_gate.py` 截留 SDK 的首次提交；所有者直接提交成功后才放行。
若 SDK 已经发出了相同请求，转发器回送刚取得的真实 `Applied` 结果，避免测试准备意外
引入重复提交。后续不同请求照常转发。Python 不重写 MuSig2，自动化也不修改产品源码。
测试驱动事先保存明确的本地开通授权，使用真实 SDK 验证与签名；不覆盖移动钱包的用户审批交互。

## 自动化范围与执行入口

- `LSP-SIGN-01`、`LSP-SIGN-02`、`LSP-SIGN-03` 分别映射到一个测试方法；勾选框只表示映射存在，不表示测试通过。
- 本批终点为双方 `ChannelReady`，尚不证明支付或链上结算的一致性；后续范围按上表小批推进。
- 构建缺失、摘要不匹配或固定端口已占用时明确失败，不跳过用例，也不换用旧 FNN。
- 使用仓库固定 devnet 端口，不与其他占用同组端口的测试并行运行。测试负责清理自己的节点与 SDK 进程。

```bash
# 先把独立 Fiber checkout 检出到 8419c005e2d0e737c5abf7e0f881aaedbc6fd300
python3 scripts/build_lsp_test_binaries.py --source /path/to/clean/fiber

# 仅运行本批三个场景
venv/bin/python -m pytest -vv -s test_cases/fiber/devnet/lsp/test_channel_signing_isolation.py

# 全仓库映射检查
python3 scripts/check_test_map.py
```

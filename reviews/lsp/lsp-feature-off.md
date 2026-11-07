# `lsp` feature 关闭的构建与启动回归

范围：候选 `56c761c45c271c086b05c8d5ea3e033448f5fdf8` 的 `fiber-bin` 可选 `lsp` feature。验证无 `lsp` feature 的构建仍是可用的普通 FNN，以及带 `lsp` 配置时会在启动前明确拒绝。该文不重新验证 hosted LSP 业务；默认开启 lsp 的 hosted 用例已有 Python/Rust 覆盖。

依据：[fiber-bin feature 定义](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-bin/Cargo.toml)（默认 `fnn/rocksdb`、`watchtower`、`lsp`，可显式关闭）；[无 lsp 配置检查](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-bin/src/main.rs#L476-L481)；[Makefile 的 no-default-features 编译矩阵](../../download/fiber/source-pr-1623-56c761c4/Makefile#L26-L32)。

## Spec

### SPEC-01：无 `lsp` 构建仍是可用的普通 FNN

Condition: 用同一候选源码构建 `fiber-bin`，显式 `--no-default-features --features "fnn/rocksdb watchtower"`，产物不包含 hosted LSP；用不含 `lsp:` 配置的普通 devnet 配置启动该产物。
Expected: FNN 正常启动并完成 RPC `node_info`；普通 `list_channels`/`list_peers` 可用；`lsp_get_status` 因方法不存在而返回 JSON-RPC method-not-found，而不是启动失败或 panic；停止时正常退出。
Observable: 构建命令和产物；启动日志；`node_info`；普通 RPC；`lsp_get_status` 的错误码/消息；进程退出码。
Basis: [feature 开关定义](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-bin/Cargo.toml)；[hosted LSP 只由 lsp feature/service 注册](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-bin/src/main.rs#L476-L490)；[无 lsp 时 tenant/alias 为 no-op 的注册代码](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-lib/src/rpc/tenant.rs#L255-L269)。
Source: explicit
Testing: required

### SPEC-02：无 `lsp` 构建对 `lsp:` 配置明确拒绝

Condition: 同一无 lsp 构建，配置文件的 `services` 显式包含 `lsp`（可同时保留 `lsp:` 段）；启动 FNN。
Expected: 进程在 RPC 监听前退出并返回非零；stderr 明确包含 binary 构建时没有 `lsp` feature 的拒绝文本，而不是静默忽略配置、panic、或先被 biscuit 等其他配置错误截走。
Observable: 启动命令退出码、stderr/stdout 错误文本、RPC 端口是否监听、进程是否残留。
Basis: [无 lsp 构建的显式配置拒绝](../../download/fiber/source-pr-1623-56c761c4/crates/fiber-bin/src/main.rs#L476-L481)。
Source: explicit
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- `lsp` feature 关闭
  - 无 lsp 构建 + 普通配置（services 无 lsp）正常启动：LSP-FEATURE-01 [primary] -> SPEC-01
  - 同一构建 + services 显式含 lsp，在 RPC 监听前拒绝：LSP-FEATURE-02 [primary] -> SPEC-02
  - 默认 lsp 构建的 hosted 业务 [not_applicable] — 已由现有 Python/Rust hosted LSP 用例覆盖，不在本文重复。
  - 其他 feature 组合（sqlite/portable/wasm）[unanalysed] — 不同构建矩阵，不在本批。
<!-- TEST-TREE-END -->

## 用例

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-FEATURE-01` | - [x] 用候选源码构建无 `lsp` feature 的 `fiber-bin`；以普通 devnet 配置（`services` 无 lsp）启动；调用 `node_info`、普通 `list_channels`/`list_peers`，再用原始 JSON-RPC POST 调 `lsp_get_status`；正常停止 | 构建 provenance 成立（无 lsp feature、版本/hash 匹配）；普通 FNN 正常启动并返回 `node_info`；普通 RPC 可用；`lsp_get_status` 返回 JSON-RPC method-not-found `-32601`，日志无 LSP service 启动，不 panic、不留下 hosted LSP；进程可正常退出 | 关闭 lsp 后普通节点无法启动，或仍偷偷注册 hosted LSP/RPC，或默认 lsp 二进制冒充通过 | P1 |
| `LSP-FEATURE-02` | - [x] 用同一无 `lsp` 构建，配置 `services` 显式含 `lsp`（并有 `lsp:` 段）后启动 | 在 RPC 监听前以非零退出；stderr 含 binary 构建时没有 `lsp` feature 的拒绝文本，且不是 biscuit/其他配置错误；RPC 端口不监听，无残留进程 | 只加 `lsp:` 不触发、静默忽略配置、被其他错误截走、启动到半可用状态/panic | P1 |
<!-- TEST-CASES-END -->

## 验证设计

- 独立预期：SPEC-01 的构建 provenance、普通 RPC 成功、`lsp_get_status` method-not-found 分开断言；`lsp_get_status` 用原始 HTTP JSON-RPC 断言 `error.code == -32601`，不用只保留 message 的 RPC 客户端。SPEC-02 的退出码、stderr 目标文本、端口不监听分开记录；stderr 必须匹配 `built without the \`lsp\` feature`，并排除 biscuit 错误。
- 环境：`download/fiber/source-pr-1623-56c761c4`，`cargo build --locked -p fiber-bin --no-default-features --features "fnn/rocksdb watchtower"`；先验证 warm target 的 `--offline` 可行性，或明确允许有界网络。复用任务专用 warm target（加锁），设置 `CARGO_PROFILE_DEV_DEBUG=0`，产物放独立路径，记录构建前后空闲空间；不覆盖默认 lsp bundle。普通 devnet 启动只替换二进制路径，使用 `SimpleNamespace`/显式 binary 注入，不复用 `LspTestBase` 的固定 revision 门禁。
- 证据：保存构建命令/产物 hash、启动日志、`node_info` 与 `lsp_get_status` 原始响应、`lsp:` 配置启动的 stderr/退出码、端口检查结果。
- 证明边界：只证明 feature-off 的构建/启动边界，不证明 hosted LSP 业务、其他 feature 组合或 P2P 兼容性。构建失败单独 report，不能算 SPEC-01 启动失败；默认 lsp 构建仍由现有 hosted 用例覆盖。
- Case 2 用 direct `subprocess.Popen`（不经 shell）捕获 stdout/stderr 和 returncode；进程退出后再检查 RPC 端口 closed。不能使用会等待 RPC 的 `Fiber.start()`，否则会以 300 秒超时代替产品拒绝。

## B review 与处理

第一轮 B review 为 **G1 not ready**，阻断项已处理：

| Finding | 处理 |
| --- | --- |
| B-01：只加 `lsp:` 不触发无 lsp 拒绝 | Case 2 前提改为 `services` 显式含 `lsp`；普通 Case 1 的 services 不含 lsp |
| B-02：`Fiber.start()` 等 RPC，拿不到退出码/stderr | Case 2 改为 direct Popen + wait + returncode/stderr + 退出后端口检查 |
| B-03：`lsp_get_status` 不能证明无 lsp，客户端丢 code | 用原始 HTTP JSON-RPC 断言 -32601；增加构建 provenance/日志无 LSP service；默认 lsp 二进制不能冒充 |
| B-04：构建/空间/离线未验证 | 明确 warm target 锁、`CARGO_PROFILE_DEV_DEBUG=0`、构建前后空间、先验证 offline；构建失败单独归因 |
| B-05：二进制注入/版本漂移 | 明确 SimpleNamespace/显式 binary 注入，`--version`/sha256 provenance，不用 LspTestBase 固定 revision |

## ccac337 复审修复

2026-11-07 针对 `ccac337` 复审的 R1/R2/N1 修复：

| Finding | 处理 |
| --- | --- |
| R1：按端口清理无法保证本次子进程 | Case 2 的 probe 进程保存为测试自有句柄；成功、失败、超时和 teardown 都按 PID `terminate`/`wait`/`kill` 回收，Case 2 不再调用按端口反查的 `Fiber.stop()`；启动前检查 8248/8249 空闲，端口冲突作为环境错误且不终止无关进程 |
| R2：Case 01 无法单独证明 feature-off 构建 | Case 01 与 Case 02 共用 `_run_feature_off_probe()`：用同一二进制启动带 `services: lsp` 的配置，必须看到 `built without the \`lsp\` feature` 且不能监听 RPC。默认 LSP 二进制会在 probe 阶段失败，不能只看版本字符串通过 |
| N1：退出后端口检查不能证明未监听 | probe 在进程运行期间持续探测 RPC 端口；一旦观察到监听即失败，并保留最终端口关闭检查 |

复跑：`2 passed in 102.82s`。Case 01 先执行 feature-off probe，再以普通配置启动；Case 02 独立执行 probe。进程句柄和端口冲突路径已按上述方式收口。

## 未分析分支

- 无 lsp 构建下，旧的 tenant/alias RPC 是否应返回 no-op 还是 method-not-found：本 Case 只观察 `lsp_get_status` 不存在；其他 tenant alias 方法不在本批。
- 其他 feature 组合和 wasm 构建不在本批。

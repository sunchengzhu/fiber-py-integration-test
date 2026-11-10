# QUERY-01/02、ADMIN-AUTH-01/03 可选共享环境

四条已有发票查询和权限测试现在可以串行复用真实 A/B 开户及通道准备。默认仍为独立模式；每条继续创建自己的发票、执行原业务判断，并检查资金、状态及前序数据。ADMIN-AUTH-01 补齐了已有评审要求的拒绝后合法查询。

产品固定为 `76307312e8de518c9a32074e6d16867c04de4f86`，工程基于已合并 [PR #19](https://github.com/sunchengzhu/fiber-py-integration-test/pull/19) 的 `f888044e56064289b5e64188272a6cad58ea1821`。原用例与映射事实来源仍为 [Hosted 租户边界](../../reviews/lsp/hosted-tenant-boundaries.md) 和 [TestTenantQueryIsolation](../../test_cases/fiber/devnet/lsp/test_tenant_boundaries.py)，没有新增业务 ID 或修改用例行。

## 范围与入口

全部方法位于 `test_tenant_boundaries.py::TestTenantQueryIsolation`；下表仅索引工程复用范围。

| 原用例 | 原生方法 | 每条新数据 |
| --- | --- | --- |
| LSP-TENANT-QUERY-01 | `test_default_namespace_invoice_query_is_isolated` | A/B 各一张 Open 发票 |
| LSP-TENANT-QUERY-02 | `test_explicit_tenant_target_is_rejected` | A/B 各一张 Open 发票 |
| LSP-ADMIN-AUTH-01 | `test_tenant_token_cannot_list_tenants` | A 一张 Open 发票 |
| LSP-ADMIN-AUTH-03 | `test_tenant_token_cannot_parse_invoice` | A 一张 Open 发票 |

同一组仍新建六个不同 hash，不发起付款。`_new_hold` 会创建真实 invoice 并写入 SDK inbound 授权/preimage，所以发票和授权存储会累积，不能称为完全不变的纯读环境。

使用已有同源 bundle、合格空间与空闲端口，在测试工作区执行。每次指定全新的绝对证据路径：

```bash
LSP_TEST_REVISION=76307312e8de518c9a32074e6d16867c04de4f86 \
LSP_TEST_BUNDLE="$PWD/download/fiber/pr-1623-7630731" \
LSP_INVOICE_QUERY_ENV_MODE=shared \
LSP_INVOICE_QUERY_KEEP_RUNTIME=1 \
LSP_PAYMENT_REPORT_DIR=/absolute/fresh-run/business \
CKB_CLI_HOME=/absolute/fresh-run/ckb-cli \
python -m pytest -o addopts= -p no:cacheprovider -x -vv -s \
  test_cases/fiber/devnet/lsp/test_tenant_boundaries.py::TestTenantQueryIsolation::test_default_namespace_invoice_query_is_isolated \
  test_cases/fiber/devnet/lsp/test_tenant_boundaries.py::TestTenantQueryIsolation::test_explicit_tenant_target_is_rejected \
  test_cases/fiber/devnet/lsp/test_tenant_boundaries.py::TestTenantQueryIsolation::test_tenant_token_cannot_list_tenants \
  test_cases/fiber/devnet/lsp/test_tenant_boundaries.py::TestTenantQueryIsolation::test_tenant_token_cannot_parse_invoice
```

独立对照设置 `LSP_INVOICE_QUERY_ENV_MODE=independent`，四条各启新进程和环境。`LSP_INVOICE_QUERY_KEEP_RUNTIME=1` 保留成功运行目录；默认成功收尾仍沿用原行为，失败保留不依赖这个开关。原付款查询的 `LSP_QUERY_ENV_MODE`/`LSP_QUERY_KEEP_RUNTIME` 开关保持独立。

不能把整个五条类作为共享入口：ADMIN-AUTH-02 会明确拒绝进入共享组，不能静默跳过或自动重建。全套回归应在共享组关闭后另起独立进程执行该条，避免固定端口冲突。普通 LSP 空间门槛仍为至少 8 GiB，不降低等待或预算换取速度。

## 状态、断言与版本依据

- 保留真实 T/P FNN、A/B SDK、注册、external funding 和 A–T/B–T/T–P 三条 ChannelReady 通道；没有裁剪拓扑或改用未注资/mock 环境。
- owner 只绑定资源句柄；各方法的结果、证据、cleanup 栈和本条数据保持独立，业务截止时间不超过原 owner 的绝对预算。
- 每条前后先检查进程身份、operator 的 Active runtime、计数和原 channel_id 集合，再进行可能 ensure runtime 的租户查询。active/registered 计数使用 `_number` 解析真实十六进制数量。
- 六端原通道/出点、ChannelReady、镜像余额、零 TLC 锁定/无 pending TLC 和 NoSignatureRequired 均检查；本组没有付款，不套用出站付款方向公式、Paid 状态或付款五秒采样窗口。
- 前序目录以 `(tenant_id, payment_hash)` 保存深拷贝快照，不以重复标签 a/b 覆盖；新旧发票的 Open 状态、地址/hash/完整内容持续核对。不清 DB，不重置余额、nonce 或授权历史。
- 保留原默认隔离、跨 tenant 目标拒绝、operator 同目标正向和 operator-only 分类判断。ADMIN-AUTH-01 在拒绝后先由 operator 检查 runtime/计数/通道，再合法查询自身发票；后置检查参与该条原生结果。

763 的 [查询契约](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/docs/notes/hosted-lsp.md#L265-L278) 与 [tenant 解析](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/rpc/tenant.rs#L310-L383) 要求正确选择目标命名空间。[LSP service](https://github.com/nervosnetwork/fiber/blob/76307312e8de518c9a32074e6d16867c04de4f86/crates/fiber-lib/src/lsp/service.rs#L485-L505) 的 ListTenants 只读 registry/status，而 GetTenantRpcContext 会调用 supervisor.ensure。普通 tenant 读取可能重新拉起 runtime，因此 ADMIN-AUTH-02 的两次 evict 拒绝后只能由 operator 观察，本批继续独立。其他四条的健康检查也不能先用 tenant 读取修复现场。

## 公共生命周期与失败保留

[HostedEnvironmentReuse](../../test_cases/fiber/devnet/lsp/_query_environment.py) 从原 QUERY-04～06 混入类提取资源归属、限时回收与归档接口；付款专用 checkpoint 保留在 QueryEnvironmentPilot，发票组使用 [InvoiceQueryEnvironment](../../test_cases/fiber/devnet/lsp/_invoice_query_environment.py) 自己的判断。

- independent 的证据初始化也进入统一异常处理：目录创建/首条记录失败先标记失效，再保存 root 级备用诊断；二次诊断或清理异常只附加说明，保留原始异常。
- 同一类 CKB 环境失效后，两种模式均拒绝后续方法自动重建，避免覆盖现场。恢复使用新的运行批次。
- independent 清理异常同样标记失效。失效时即便 keep-runtime=false，teardown 也不进入节点目录删除；一个 FNN 停止失败仍会尝试其他 FNN。类级 CKB/矿工按 PID/cwd 身份核验回收，并保留原目录。
- owner 正常清理受原 row 截止时间与最多 60 秒限制；异常/期限耗尽后逐项恢复，每个回调最多 15 秒，失败回调最多重试一次。最终归档另用最多 60 秒，不延长业务期限，也不把恢复成功转换成通过。
- 最终归档在资源处理后执行；保留部分归档、原异常和 cleanup-status，缓存已完成收尾结果以避免重复执行。archive_complete 不能单独代替原生退出码与进程退出检查。
- 方法运行中的 DB 副本只作诊断；停止后的 FNN/SDK 最终归档和 CKB 备份才用于结束状态核验。

## 固定 76307312 的验证

2026-11-10 的最终版本使用相同声明输入和同源二进制，所有真实执行均保留原目录。

| 范围 | 原生结果 | 完整回执耗时 |
| --- | --- | --- |
| 本批四条，各自独立进程/环境 | **4 passed，0 failed/errors/skipped** | 101.721 + 114.234 + 105.729 + 97.128 = **418.812 秒** |
| 本批四条，同一环境串行 | **4 passed，0 failed/errors/skipped** | **148.824 秒** |
| 既有 QUERY-04～06，共享影响回归 | **3 passed，0 failed/errors/skipped** | **212.991 秒，单独统计** |

本批节省 **269.988 秒，耗时减少 64.5%**。计时从 native wrapper 启动被测命令至 JUnit/执行后输入核验完成，含 pytest、环境准备、业务、测试内归档与进程收束；不含离线回归、定位、自审、外层复制及统一链备份。影响回归不计入四条提速比较。该比例只代表本机单轮，未外推全套或长期性能。

共享四条的进程/租户/通道身份一致；每种模式创建 2/2/1/1 张新发票，两种模式合计十二个不同 hash。共享目录累计 2→4→5→6 张 Open 发票，历史复查 2/6/14/11 次，共 33 次。原隔离与拒绝后合法查询、资金和签名状态检查成立。结论限于实际观测点，不声称连续观察所有内部事件。

### 离线检查的数量与范围

- **146 项仓库检查全部通过**，由五份 framework 测试组成；本批新增发票/权限工程回归及原付款组默认失败影响回归，不新增业务 ID。
- 另外四项本地旧复核探针原样重放通过（含两个真实 SIGALRM 回调超时），合计 **150 passed，exit 0**。
- 最后复核又加入三项仅本地保存的进程级探针：目录/首条记录失败各回收两个实际替代子进程，部分归档失败回收六个。原文件、部分归档、诊断及原始异常保留，正常删除分支未被调用，合计 **153 passed，exit 0**。
- 上述七项本地探针不属于 PR 仓库测试数量；使用受控替代进程验证生命周期，不是新的产品节点或业务场景。默认 keep-runtime=false 故障覆盖与真实对照 keep-runtime=1 的正常路径分别验证。
- Black、差异空白检查与原八行评审结构检查通过。映射检查仍为 147 条评审/141 条映射，exit 1 仅为既有 PMP-01～05、SETTLE-01 六个孤儿映射，无新增孤儿或重复 ID。

仓库检查可串行重放：

```bash
python -m pytest -o addopts= -p no:cacheprovider -q \
  test_cases/framework/test_lsp_invoice_query_environment.py \
  test_cases/framework/test_lsp_query_environment.py \
  test_cases/framework/test_lsp_tenant_payment_queries.py \
  test_cases/framework/test_lsp_payment05_oracles.py \
  test_cases/framework/test_lsp_setup_cleanup.py
```

### QUERY-04～06 的影响回归

付款业务文件、Hosted/outbound fixture 及资金、费用、历史、稳定窗口判据未变；此次只调整公共 setup/cleanup/teardown 失败入口，owner 限时回收与付款 checkpoint 保持。

原始材料复算六笔付款：每笔实际费用 5,000 Shannon，两段 TLC、六端累计余额、Paid/Success 历史与查询目标矩阵成立。各六个完整稳定样本，跨度 **5.238 / 6.159 / 5.932 秒**，最大间隔 **1.049 / 1.322 / 1.413 秒**；前序历史复查仍为 0/4/8，原五秒、至少三样本、最大两秒间隔未放宽。

### 资源、失败记录与原始材料

最终六套环境的自有进程（含 miner）无残留，六个固定端口关闭；328 个 FNN/SDK 最终文件及六份停止后 CKB 备份的 462 个文件逐一摘要一致，原 runtime 继续保留。

首轮十六进制计数错误、默认独立模式的部分归档/初始化失败、早期探针构造错误和旧对照材料均保留；均未混入本轮正式提速比较。本轮未删除文件、开启并行或运行退款长用例。

原生命令、JUnit/stdout、输入/二进制摘要、HTTP/SDK/TLC/节点记录、逐文件备份清单与复核材料仅在主工作区 local-evidence 保存，不提交到仓库：

- `lsp-invoice-shared-763-20261110/`：首轮实现、类型错误和正常对照。
- `lsp-invoice-shared-review-763-20261110/`：默认失败分支的首次缺口复核。
- `lsp-invoice-shared-fix-763-20261110/`：修复前后回归、最终真实对照及影响回归。
- `lsp-invoice-shared-fix-review-763-20261110/`：最后 153 项复核、原始文件重核及两项缺口关闭结论。

## 后续候选（未实施）

保留此前优化顺序作为后续单独评审线索：先评估单 A 的 INVOICE-CANCEL-01/03（资金方向 P→T→A、门控复原和完整 30 秒稳定观察不能省略）；签名/浏览器订阅需要每条新的签名工作/通道，不能直接复用已就绪通道。763 支持独立 signer 增加通道，不能套用旧单通道假设。重启、Delivery 故障、强关/超时、Watchtower、功能开关和退款长场景不直接复用本批环境。本次仅交付上述四条，没有推进其他候选。

# Gate2：Hosted delivery 接纳一致性

2026-10-30：用户授权按既定顺序持续完成，不再逐项等待 Gate1/Gate2 确认。本次修正后的新批仍固定84333ee、120分钟上限、正常付款对照先于六行单次验证，任何失败停止该批；不为选择竞态结果重跑。运行脚本已改为显式传入基础产物和缓存目录，不依赖某次本地报告路径：

```bash
python scripts/run_lsp_delivery_batch.py --source <干净843源码> \
  --base-bundle <843基础产物目录> --target-cache <任务专用可写Cargo目标目录> \
  --cargo-home <一次初始化后复用的任务Cargo依赖目录> \
  --protected-worktree <保留原改动的测试工作区> --python <项目Python解释器>
```

基础产物须包含当前真实SDK测试驱动，不能传入旧的delivery包装产物。每批独立保存输入路径、冻结源码、版本、退出码和原始日志；此前六批结果保持不变。

范围：[已确认 Gate1](field-feedback-scope.md) 的方向 5/6/7：接纳前超时、持久化接纳后丢回复、同 incoming key 原样及冲突重投。固定 FNN/SDK/产品库 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`。2026-10-29 用户已明确确认本文件 `LSP-DELIVERY-01～06` 行集、资金断言和调整后的薄包装方案，并授权 Gate3 的实现、GPT 6 sol 复核、资格验证及六行单次执行；产品代码、原工作区与退款夜跑不动。下文历史 Gate2 提案文字保留，执行结果另记于 LSP 运行说明。

**已确认的方案：现有外部 FNN + Python/SDK 夹具没有内部接纳门禁；测试侧薄包装直接复用原 `run_node`，通过同进程 actor registry 接入接纳代理。** 前版分别调用 `start_network` 等接口重建启动流程的方案被替换，减少启动接线的复制和偏离；六行与资金判据不变。独立测试产物仍须编译和取得资格，组件 mock 通过不能替代这六行。六行已建立 Python TEST-MAP；映射仅表示有代码，不表示执行通过。

## 接口、状态与共同前提

- `K=(incoming_channel_id, incoming_tlc_id)` 标识 T 收到的一次具体 TLC，**不含 tenant，也不等同 payment hash**。`AcceptTrampolineDelivery(request, reply)` 是进程内 actor 消息，不是 HTTP/WS RPC。公开 `lsp_get_payment_delivery({payment_hash})` 返回 active 或最近记录，单凭它不能证明原 K。
- 843 的调用方等待 5,000ms；服务执行 `accept` 后先安排 deadline/Resume，再发送回复；回复失败不回滚。正常持久状态为 `Deferred → Dispatching → InFlight → SettlingUpstream → Succeeded/Failed`，临时错误可能回到 Deferred。`Succeeded` 应包括上游兑现，`attempt_count` 是 dispatch 尝试次数，不能当作有效付款次数。
- dispatch 前还有真实上游检查：Removed 会阻止支出，Unknown 会等待。因此源码显示风险窗口，**不证明本地已复现资金损失**。两个超时行必须保留完整事件顺序、真实上游结果和下游结果，安全收敛也如实报告所取得分支。
- 每行新建 Fiber/SDK 数据和通道；P 是普通付款节点，T 是公共 LSP，A 是 Hosted 租户。使用真实 CKB devnet、RocksDB、SDK 密钥/批准/签名和 P—T—A 路径，plain CKB、禁 MPP。06 增加真实 B—T 私有通道、B 独立身份和有效发票，仅用于 Gate1 已包含的目标冲突，不展开跨租户矩阵。开通资金沿用已有夹具：P 提供 1,000 CKB，A/T（06 的 B/T）各 500 CKB，以实际资金可用量和储备检查为准。
- 各通道 ChannelReady、无 pending TLC/待签/锁定额后保存基线。每行原 A 发票净额 `M=1,000,000 Shannon`，06 的 B 发票相同金额、不同 hash；各自有匹配的真实 SDK 本地授权。发票/授权有效期 3,600s，final TLC delta 3,600,000ms，payment expiry limit 86,400,000ms，`max_fee_amount=10,000 Shannon`。T 的公开配置 `lsp-max-buffer-duration-ms=600000` 限制 buffering；保存实际 hint/expiry/deadline，不能用 buffer=0 绕过接纳。原 RPC 仅调用一次 `send_payment`，timeout 120s；这不是强关或链上退款测试。
- **一次 RPC 不等于一次 incoming。** 产品可能自动重试新 K，保留这些尝试，不改重试常量、不由代理伪造拒绝来禁重试。`send_payment_with_router` 会清除 trampoline hops，不能用它替代本路径。按 K 保存每次 TLC/请求/下游 session，原 K 失败不能被同 hash 后续成功覆盖；无法逐 K 归因时为夹具不合格。120s payment timeout 也不等于即时终止，产品状态检查有周期，不能以到时自动判 Failed。
- 03/05/06 在**真实 InFlight 且 A 的目标签名被现有 HTTP gate 暂扣**的稳定窗口操作，SDK 仍在线；这个 gate 仅固定重投观察窗口，不能用来声称控制了内部接纳超时。04 先正常完成一笔付款并保存 Succeeded。所有 replay 均在原 hint/授权有效期内，过期后的 replay 不在本批承诺内。

## Spec

### SPEC-01：调用超时不能产生无对应上游收入的下游支出
Condition: 原 K 的接纳请求在服务接纳前被延迟，或真实服务已持久化且返回 Buffered 但原调用方没有收到回复，调用方真实跨过 5 秒超时。
Expected: 恢复后原 K 要么上下游一致成功且只支付一次，要么安全失败且不发生有效下游支出；原 K 已不可逆失败而其下游成功属于失败，不能用后续新 K 的成功抵消。待确认：采用本批“恢复 120s + 稳定 30s”的有界验收窗口；这是测试上限，不是已发布的产品恢复 SLA，也不指定产品必须新增哪一种查询/撤销 API。
Observable: 捕获/转发/持久化/Buffered/原调用超时的单调时序，原 K 上游 TLC remove/兑现证据、下游 session 的 previous_tlcs 绑定、delivery、真实签名、余额与锁定额。
Basis: 已确认 Gate1 SPEC-02；[调用超时及错误路径](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L5312)、[接纳先于回复](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/service.rs#L519)、[dispatch 前检查上游](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/service.rs#L866)、[settle 跳过非 Pending 上游](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L8842)。安全断言沿用已确认范围，恢复时限为本次提案。
Source: inference
Testing: required

### SPEC-02：同 K 原样重投保留原执行
Condition: 原注册/hint 仍有效，完整请求经产品规范化后相同；原执行处于 InFlight 或 Succeeded。
Expected: 返回原执行的接纳结果，原身份/请求/创建时间/deadline 不变，不因重投新增 dispatch 或有效付款；成功终态不复活。InFlight 完成一次原付款，Succeeded 重投前后余额、记录和零锁定额不变。
Observable: 同一 K 的完整记录、原样请求/回复、dispatch 与下游付款记录、双段 TLC/余额及 Succeeded 稳定窗口。
Basis: [same-key 比较与返回原记录](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L415)、[终态 Resume 不执行](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/service.rs#L777)；上游 [manager 单测](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/tests/mod.rs#L766)没有真实资金和调用超时。本批不把上游单测算成本地通过。
Source: observation
Testing: required

### SPEC-03：同 K 的金额冲突不能改写原付款
Condition: A 的原 K 已 InFlight，保持原 invoice/hash/key，仅把 amount_to_forward 从 M 改为 M+1。
Expected: 在发票金额校验拒绝，原记录及暂停窗口资金不变；放行后仅原 M 的 A 付款成功。本行不声称执行了后续 same-key 比较分支。
Observable: 唯一字段差异、真实拒绝阶段、原记录、A 发票、目标 TLC 金额与最终资金。
Basis: [先核发票金额再查 key](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L405)。
Source: observation
Testing: required

### SPEC-04：同 K 不能被另一合法租户的目标重绑定
Condition: A 原 K 已 InFlight；B 有真实绑定私有通道和有效同额发票，构造保留原 incoming key、改用 B 合法 hash/目标的请求，前置 invoice/amount/asset 校验可通过。
Expected: 到 existing execution 的 tenant/channel/request 冲突检查被拒绝；原 A 记录不改，B 不创建 delivery、不接收 TLC/资金，B 发票仍 Open；解除原 A gate 后仅 A 收到 M。
Observable: A/B 的注册及原生发票、请求差异、B 规范化目标、拒绝来源、按 K 记录和 B hash 索引、A/B 余额及发票。
Basis: [强制 next_node_id 后按 K 比较 tenant/channel/request](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L403)。只改 next_node_id 会被产品覆盖，不是有效目标冲突；只造假 private_channel_id 也不算真实租户目标验证。
Source: observation
Testing: required

## 测试树

<!-- TEST-TREE-BEGIN -->
- 接纳结果不确定时的资金一致性
  - 接纳前真正跨过 actor 5 秒再放行：LSP-DELIVERY-01 [primary] -> SPEC-01
  - 真实接纳后扣留 actor 回复直到原调用超时：LSP-DELIVERY-02 [primary] -> SPEC-01
- 同一次 incoming 的原样重投
  - InFlight 重投后原付款只完成一次：LSP-DELIVERY-03 [primary] -> SPEC-02
  - Succeeded 重投不复活或重复付款：LSP-DELIVERY-04 [primary] -> SPEC-02
- 同一次 incoming 的冲突重投
  - 原发票金额冲突在前置校验拒绝：LSP-DELIVERY-05 [primary] -> SPEC-03
  - 另一有效租户目标在 existing-key 检查拒绝：LSP-DELIVERY-06 [primary] -> SPEC-04
- Failed 终态重投、相同 hash 新 K 接纳政策、接纳后进程重启 [pending] — 本批不展开；重启属于 Gate1 方向 8，其他状态另按风险选择，不能记为已覆盖。
<!-- TEST-TREE-END -->

## 用例

所有行继承上述真实拓扑和逐 K 账本。01/02 的“失败”指原上游 TLC 的最终失败，不是 HTTP 错误或仅 actor 超时；“只支付一次”必须同时有实际付款和余额证据。

<!-- TEST-CASES-BEGIN -->
| 用例 | 场景 | 预期结果 | 防止的问题 | 优先级 |
| --- | --- | --- | --- | --- |
| `LSP-DELIVERY-01` | - [x] 捕获 P→T→A 的真实原 K，请求尚未交给接纳服务；证明原调用 5 秒超时后，仅放行该原请求一次 | 原 K 最终上下游一致成功且仅付一次，或无下游支出的安全失败；原 K 失败后不得由其下游向 A 支付；记录后续新 K，逐执行与总账均一致 | 排队请求在调用方失败后继续支出，或新尝试成功掩盖原执行损失 | P0 |
| `LSP-DELIVERY-02` | - [x] 原 K 已真实持久化、服务返回 Buffered 并安排恢复；代理不传回该回复，保留原 reply port 至原调用真实 5 秒超时，随后解除故障 | 按原 K 查清已接纳事实，原执行上下游结果一致且最多一次有效付款；成功有对应上游收入，失败无下游支出，不能仅凭回复超时判业务失败或通过 | 已接纳工作继续付款而上游已经失败，或恢复重复付款 | P0 |
| `LSP-DELIVERY-03` | - [x] A 原 K 真实 InFlight，暂扣目标签名固定状态；将捕获的完整原请求按同 K 重投一次，再放行原签名 | 重投被接纳为原执行，暂停窗口原记录和资金不变，不新增 dispatch；恢复后仅原付款成功一次，双段余额、实际费用和零 TLC 锁定额一致 | 同 key 重投生成第二次付款或延长原 delivery 生命周期 | P0 |
| `LSP-DELIVERY-04` | - [x] 原 K 已正常 Succeeded、上下游结算且无锁定，原 hint 仍有效；完整原请求按同 K 重投一次 | 返回原接纳结果，原 Succeeded 记录、dispatch 次数和余额保持不变；连续 30 秒没有新 TLC、签名工作或有效付款 | 已完成执行被重放后复活或重复扣款 | P0 |
| `LSP-DELIVERY-05` | - [x] A 原 K 真实 InFlight 并暂扣签名；保持原 invoice/hash/key，仅把 amount_to_forward 从 M 改为 M+1 重投一次，再放行原签名 | 真实发票金额校验拒绝，原记录和暂停窗口资金不变；仅原 M 完成，最终费用与余额正确；不把该结果计为 existing-key 比较覆盖 | 冲突金额覆盖原付款，或把早期拒绝误当幂等冲突检查通过 | P1 |
| `LSP-DELIVERY-06` | - [x] A 原 K 真实 InFlight 并暂扣签名；B 已有真实通道和合法同额发票，保留原 K 改投 B 的合法 hash/目标一次，再恢复 A | 前置校验成立后在 existing-key 冲突处拒绝；A 原记录不变，B 无 delivery/TLC/资金变化且发票仍 Open；最后仅 A 收到 M | incoming key 被另一合法租户目标占用，或只改被规范化覆盖的字段造成假覆盖 | P0 |
<!-- TEST-CASES-END -->

## 触发方案与资格门槛

### 原入口薄包装与同进程代理

固定843的[原 `run_node`](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-bin/src/main.rs#L193)已负责 CKB/合约、StoreActor、NetworkActor、Hosted runtime、LSP、RPC、事件转发和退出清理。测试侧以 `include!` 将未修改的原 `main.rs` 纳入一个独立模块，并在同模块增加很小的入口包装调用私有 `run_node`；这样不复制该函数，也不另写一套节点接线。Rust 的 [include 语义](https://doc.rust-lang.org/std/macro.include.html)允许将文件作为当前模块的 items 引入；当前 main 文件未发现阻止这种包含的根属性或相对 crate 引用，但实际编译仍是资格检查，不能仅凭语言规则宣布产物可用。

包装只沿用原 `main/run` 的必要前置准备：umask、logger、Tokio runtime、配置读取、原迁移/`sync_writes` 开库、OutputPort watcher；在调用原 `run_node` 前保留同一个 Store clone，供按 K 只读观察。仅支持本批普通启动配置，拒绝 `restore/check_validate` 等无关分支；这些前置语义须逐项与原代码核对。不能调用完整原 `main()` 后凭空取得 Store：`HostedTenantRpcContext.store` 是 `pub(crate)`，StoreActor 也没有公开返回 Store 的消息，故不采用这条缺少账本读取能力的捷径。

原 main 把 LSP 注册为 `lsp service`（`:515`），NetworkActor 使用 `Network {:?}`（`fiber/network.rs:10014`）。锁定的 ractor 0.15.13 提供强类型 `ActorRef::where_is`，测试控制任务可在**同一进程**找到这些真实 actor，再以公开 `SetLspService`（`network.rs:1109、6410`）将 NetworkActor 的服务引用改为代理。必须先等原 RPC 启动完成，再安装代理，并以同一 NetworkActor 邮箱中排在 SetLspService 之后的可回复命令作为处理屏障；控制端取得屏障应答、身份核对与代理就绪确认后才允许第一笔付款，不能只凭 send_message 成功。避免安装过早又被原 main 的 SetLspService 覆盖。

- P 使用原匹配 FNN；T 是“复用843原启动流程的测试包装产物”，A/B 使用原真实 SDK。匹配原 fiber-bin 的依赖、Cargo.lock、features/cfg、构建 profile 和产品库版本；尤其只允许一套匹配的 fnn/ractor 依赖实例，否则类型/registry可能不相通。原 main 文件与产品源码必须字节不变，不通过构建脚本改写注入；包含来源、包装差异和产物身份均留证。
- 只将 T NetworkActor 的 LSP 引用指向同消息类型代理；LspService/runtime factory 的 public_network_actor 仍是真实 T，RPC/WS 直接连真实 service。service 自己的 Resume/Expire 不经代理。原节点运行与控制任务必须并发，控制任务有界退出，保留原 shutdown 流程。结果仍称“843 产品库的真实 actor 集成验证”，**不能称原 fnn 二进制被外部透明注入，也不代表完整 CLI 所有分支通过**。
- 代理只对指定 K 的一次 Accept 控制转发或回复，其余消息原样传递。不能在代理 `handle` 内阻塞等待 gate/真实回复；使用受控任务和一次性状态，保持邮箱可处理其他消息。禁止改变产品状态机、重试/时间常量、业务错误或签名校验，禁止 mock settlement、写入伪造 delivery 或手工修复余额。
- 只读检查通过同一进程共享 Store handle 的产品接口按 K 查询完整记录、按 hash 列出关联记录、读取真实通道/session；不要另开锁定中的 RocksDB，也不把一次 batch commit 解释为断电 fsync 耐久性。前置检查还需确认 P/T 原 TLC 完成证据可取得，不能以轮询错过关键状态后猜测。
- Python 负责准备、故障命令、原 RPC/SDK gate、资金断言、绝对预算与归档。拟新增一个接纳专项 Python 文件和一个仅此组使用的薄包装/代理；优先复用现有 SDK 驱动、生命周期和余额读取，不改默认产物选择或普通测试发现范围。若必须复制 `run_node` 或重建主要启动流程才能编译，停止并报告，不自动回退前版重搭方案。本轮不创建这些文件，不插入 TEST-MAP 占位注释。

方案比较与排除依据：

| 方案 | 能证明什么 / 限制 | 本批选择 |
| --- | --- | --- |
| 原入口薄包装 + 同进程接纳代理 | 复用原真实节点启动与资金路径；可持有原 Store 并控制同 K 接纳/回复；仍需编译资格 | 优先候选 |
| 原 FNN + HTTP/CKB 代理 | 可控外部网络/签名，但内部 Accept/reply 不经过网络；EnsureTenant/Evict 的等待也未找到可精确控制的外部关口 | 不冒充01/02；不能提供同 K 内部重投 |
| 原 FNN + SIGSTOP、压力或随机 sleep | 会同时改变调用方计时/调度，不能证明接纳前后边界 | 不采用 |
| 上游 test/bench helper + 普通 Python 资金对照 | `NetworkNode::new_with_config` 无条件使用 MockChainActor/MockCkbChainClient；组件故障证据与另一笔正常资金对照不能相加成本表通过 | 可作其他层级测试，不替代本批 |
| 在产品 main/service 加 test-only hook | 接线直接，但需要修改产品源码，与当前约束不符 | 不采用，不自行增加许可 |

dev RPC 的 `add_tlc` 不构造本路径的 trampoline onion/previous_tlc，也没有接纳/回复门禁；`cfg(test)` 下的消息/settlement hold 不是 release FNN 的接纳钩子。外部进程无法使用同进程 registry，不将普通 wrapper 描述成动态注入现成 fnn。

### 各故障的精确顺序

1. **01 接纳前**：代理捕获真实 request 并持续保留原 reply port；此时按 K 无 delivery 且尚未转发。等待真实 NetworkActor 的原 `call_t!` 超时事件（关联唯一故障 K），在事件后至多 1s 发出原 request，不再等待上游完全 Removed 才挑安全分支；使用代理自己的观察 reply port 接收真实服务结果，不向已超时原调用方补造回复。必须保留“未转发 → 原调用超时 → 转发 → 服务接纳/拒绝”的顺序；网络 actor/时钟一直运行。若记录不足或放行延误，报触发未取得，不重新跑来选分支。
2. **02 已接纳后**：代理仅替换内部 reply port，把真实 request 交给真实 service；收到真实 Buffered 后按 K 读到记录，保存该记录及 Resume 已安排的依据。原 reply port 一直保留而不回复，直到真实 5s Timeout，再丢弃。立即丢 port 可能只得到 channel closed，不能算本行；若真实服务未在调用超时前返回 Buffered，也不能算本行。service 自身恢复正常推进，不额外挡住上游检查来制造损失。
3. **03/05/06 active 重投**：先有真实 InFlight 与 pending SDK 签名的稳定检查点，固定原完整记录。通过代理控制入口将捕获 request 直接重投给真实 service 一次，保留 K 和响应。03 原样；05 仅 M→M+1；06 改为 B 真实注册发票/hash/目标且金额/资产仍合法。06 保存产品规范化后的预期目标和真实冲突错误来源，不通过调用私有 helper 或伪造登记绕过前置条件。分别读回原记录/索引/余额，再放行原 A 签名。
4. **04 成功终态重投**：另一个新环境正常完成原付款，确认按 K 的 Succeeded 和实际资金，再原样重投一次；记录返回 Buffered 只是 service 对已有记录的接纳答复，不是又一次付款成功。

原产品的 Timeout 日志不带 K，资格阶段必须建立唯一在途故障 K 与代理事件、原 reply port 的 5s timeout/持续持有/关闭变化、真实 NetworkActor Timeout 日志及 actor 存活的对应关系。port 关闭单独不能区分超时与调用任务退出；并发调用造成无法关联时停止为资格失败。02 读回记录时 Resume 可能已经推进状态，允许 Deferred 或可验证的合法后继状态，不能为保留 Deferred 而挡住真实恢复。

上述同 K 内部重投验证服务的防御行为，不宣称是外部用户可直接调用的 RPC，也不声称真实 P2P 必然产生这种冲突。正常对照必须证明真实发票路径确实进入 Accept 而非 NotHosted。资格自检检查代理一次性命中、非目标透传、原 port 生命周期、按 K 读取及退出清理；随后一次无故障真实 P→T→A 控制付款核对完整资金。出现 FakeRuntimeFactory/NoopNetworkActor、只能借测试模块 mock chain、需要复制支付业务或新产品钩子时立即停为夹具缺口，不扩大适配。

## 资金断言与结果分类

以开通完成后的余额为基准，通道 funding 费不混入付款费用；本批没有关闭提现，funding outpoint 应保持 live、无 shutdown tx。采集 P/PT、T/TP、T/TA、A/AT（06 加 B/TB）的两端镜像余额、offered/received 锁定额、pending TLC 的 K/hash/金额/方向/expiry。记录原 K 上游实际金额 `U`、下游实际净额 `M`，成功费用 `f=U-M` 必须满足 `0≤f≤10,000`，并与真实 P payment fee 及 T 两通道净增交叉核对，不能把 max_fee 当实收费用。

| 可证实结果 | 必须同时满足的资金判据 |
| --- | --- |
| 仅一笔一致成功 | `ΔP=-(M+f)`；`ΔT(PT)=M+f`；`ΔT(TA)=-M`；`ΔA=M`；T 净增 `f`，全体净和 0；两段 TLC 对应原成功 K，付款 Success/发票 Paid/delivery Succeeded，一次有效下游支付，最终锁定均 0 |
| 该 hash 全部尝试安全失败 | 每方最终余额回到付款前基准，实际支付费用 0，A 不为 Paid；所有 K/下游均无有效付款且 TLC/锁定清空；delivery 的失败与原 TLC 失败一致，发票仅保持实际合法未付款状态，不额外要求 Cancelled |
| 原 K 失败、同 hash 后续 K 成功 | 逐 K 分别核对真实上游结果及下游 `trampoline_context.previous_tlcs`，原 K 无有效下游付款；成功收入/支出只能归给对应成功执行，再按实际成功执行求和验证总账；P 最终 Success 或 hash 的最近 delivery 不能覆盖原 K 的失败 |
| 暂扣签名/冲突观察窗口 | local/remote 余额保持各自基准状态，现有原 TLC 允许保留相应锁定但不得多一份；按双方一致语义读取锁定，不把已包含在 local_balance 的 offered 锁定再加一次算总资产；可用额单列 `local_balance-offered_tlc_balance` |
| 重投与 B 目标冲突 | 03/04 原样重投、05/06 拒绝各自的额外实际支出为 0；原请求、tenant/private_channel、created_at、deadline 不变；稳定窗口原完整 delivery 不变，04 终态亦不变；06 的 B 发票仍 Open，B 无 delivery/新 TLC，双方 B 通道余额不变 |

稳定窗口内如原 delivery 自然推进，不能只删掉发生变化的字段让断言通过：应记录完整变化并判断检查点资格；若无法隔离重投影响，则本行触发不合格，不重跑挑状态。release 后 `attempt_count` 可以因真实正常恢复变化，但不得把它当成功次数，必须独立核对实际付款/余额。01/02 不以总和守恒代替逐方检查：P 未付、T 减 M、A 增 M 仍然总和为 0，却是需要阻断的损失。

恢复计时到期仍有 pending、Deferred/SettlingUpstream 等非终态：记录“有界恢复未通过/终态未取得”，保留锁定资金与原状态，停止后续行；没有已确认 SLA 时不直接标产品超时 bug，也不能算安全成功。确证“原 K 最终失败 + 其下游有效付款”才是本目标的产品一致性失败；环境/编译/触发资格失败单独分类。相同 #1674/#1706 症状沿用旧归因，新的接纳症状不强行归入这两个 issue。

## 预算、最小验证与停止条件

**已确认的 Gate3 执行边界：硬上限 120 分钟，一次资格流程加六行各一次，不自动追加 1+3 或全量回归。** 本调整减少适配代码和偏离风险；首次批次在编译前停止，不凭此承诺正式样本的实际耗时。120 分钟从第一条构建/准备命令开始，使用同一个 monotonic 截止时间，失败或到期立即停止后续批次，清理包含在预算内。代码复核不冒充执行；若实现期间发现需要产品修改或扩大为另一套节点框架，先停止交接，不把额外工作塞进本方案。

| 阶段 | 硬上限 | 内容与失败处理 |
| --- | --- | --- |
| 独立产物及资格 | 60 分钟 | 预检 5 分钟、匹配产物/薄包装构建 30 分钟、代理自检 5 分钟、真实无故障控制付款和安装屏障/存储/清理资格 20 分钟；任一失败即停，原 main/产品库/产物/合约哈希均留证，不能用旧版本替代 |
| 正式六行 | 每行 8 分钟，共最多 48 分钟 | 每行环境/通道与检查点≤240s；一次故障/重投控制≤10s（原 caller Timeout 必须真实观察）；解除后终态≤120s；稳定观察30s；保留并清理≤60s，共460s，余20s只作调度余量。各子截止不重置，不借用后行预算 |
| 收尾、映射与复核材料 | 12 分钟 | 保存每行版本/请求/完整记录/时序/余额/签名/日志/退出码，核对仅本批进程与端口已结束；更新现有 LSP 运行说明、行旁 TEST-MAP 与复选框。失败行证据先保存再清理，未运行项明确列出 |

正式顺序建议 **01 → 02 → 03 → 04 → 05 → 06**，每行新环境、单次故障；若 01/02 暴露产品失败或无法取得触发资格，03～06 不自动换路继续。正常资格付款已覆盖本适配器的连接/签名/支付主路径；本轮不另跑旧版延迟签名长等待套件，也不把该正常控制付款记为新 Case 通过。重复稳定性或失败修复后的新批次需要另行授权，不能为取得某个竞态分支反复重跑。

最少证据包括：产品/SDK/适配器版本与源码差异；启动接线和 RocksDB/合约配置；各进程/端口/数据目录；原 K 与全部后继 K；原 request/变体字段差异与真实回复；单调时序及原 Timeout 日志；按 K 的原始 delivery、真实上下游 session/TLC/完成证据；签名门审计；付款/发票终态；逐方余额/锁定/实付费用；稳定采样与最大间隔；完整退出码。采样通常1s、完整样本间隔≤3s；关键接纳/回复/超时顺序必须来自事件记录，不能靠1s采样推断。

## 当前交接

前版Gate2经 GPT 6.1 sol 静态复核，无设计阻断项；用户要求再比较方案后，进一步核查了黑盒外部依赖、test/bench helper、原main可见性及同进程registry，改为上述原入口薄包装候选。调整后的全文再次经 GPT 6.1 sol 只读复核，无新增技术阻断；确认同一控制任务顺序发送 SetLspService、再等待 NodeInfo 应答可作为安装处理屏障。六行、资金断言和停止条件保持原评审内容。Gate3 实现期间触发 Daybreak 限制，按用户指示改用 GPT 6 sol 完成代码复核；首次资格构建结果见下文。

静态检查：`python3 /Users/sunchengzhu/project/ai-test-agent/scripts/check_test_design.py --root . --review reviews/lsp/delivery-acceptance-consistency.md` 识别六行、exit 0；四个 Spec 的人工决策提示和未展开分支仍须按已确认的验证边界解释。`python3 scripts/check_test_map.py` 为120条评审、114个已映射ID，无重复ID；exit 1仍仅因既有PMP-01～05、SETTLE-01六个孤立映射，新六行均已映射。`git diff --check` exit 0；这些检查不执行产品测试，不表示产品通过。

当前六行均已映射。GPT6sol完成静态复核后启动首次资格批次：固定843预检通过，独立构建因执行沙盒禁止向 `~/.cargo/registry/src` 解包而退出1，按资格失败即停；传输自检、真实付款对照和六行未运行。原始证据保存在本工作树 `report/lsp-delivery-84333ee-20261029T212218/`，详见[首次停批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3资格构建受限停批2026-10-29)。该次权限失败不归为产品问题。

用户要求继续后，第二批使用独立可写 Cargo 缓存和准确端口预检，在允许本机loopback的环境通过准备；测试薄包装编译时发现 `PublicKey`/`Pubkey` 类型不匹配，按资格失败即停，原始证据保存在 `report/lsp-delivery-84333ee-20261029T214529/`。停批后仅修正测试侧网络actor注册名与节点身份的类型转换，GPT6sol按固定843源码静态复核，尚未重新编译。两批均未执行任何正式样本，120秒恢复/30秒稳定窗口未被使用，不能从编译失败推断产品行为；见[第二批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第二批类型编译失败停批2026-10-29)。

第三批在 `report/lsp-delivery-84333ee-20261029T215109/` 构建和传输自检通过，真实FNN/SDK/CKB启动；正常付款对照尚未付款，就因测试控制端以未认证的 `node_info` 等待RPC就绪，socket `status` 超时而停批。产品日志持续报告缺 Authorization header，控制事件文件为空，故不能把这次解释为产品行为失败。停批后只对测试薄包装传入原operator token路径并设置本机RPC认证头，GPT6sol静态复核，尚未编译；详见[第三批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第三批控制端未认证停批2026-10-29)。三批的正式六行仍0/6，原证据分别保留。

第四批在 `report/lsp-delivery-84333ee-20261029T215950/` 构建、自检和控制端认证就绪通过，资格付款已捕获真实接纳请求，但完整通道状态放入`serde_json::Value`时遇默认`u128::MAX`限额而panic，正常付款资金终态未证实。停批后仅修测试适配器：通道状态以原始JSON文本传输，由Python恢复精确大整数，100ms观察指纹不因通道HashMap键顺序产生伪事件；GPT6sol静态复核，尚未重编。正式六行仍0/6，不把资格准备中的真实请求当通过；见[第四批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第四批通道快照序列化停批2026-10-29)。

第五批在 `report/lsp-delivery-84333ee-20261029T220838/` 构建、自检通过，并启动真实正常付款对照；中途四通道资金和待处理TLC断言通过，但首次快照因完整通道状态含非字符串Map键而报 `channel serialization: key must be a string`。正常付款最终结算未验证，六行正式样本仍0/6，没有产品行为失败结论。停批后仅把测试侧通道快照改为安全字段投影，排除signer/onion/shared secret，金额以十进制字符串保存；GPT6sol静态复核，尚未重编。第五批及前四批证据分别保留，见[第五批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第五批非字符串通道键停批2026-10-29)。

第六批在 `report/lsp-delivery-84333ee-20261029T221906/` 构建、自检通过，正常资格对照观测到原K成功、下游唯一session/attempt成功及5,000 Shannon净差额；但测试断言将 `previous_tlc.forwarding_fee=0` 错当本次T的费用，未进入完整最终资金与30秒稳定判据。固定843要求上游额与 `amount_to_forward` 的差额等于 `build_max_fee_amount`，本次为1,005,000−1,000,000=5,000。停批后只修该测试字段引用，GPT6sol静态复核；第六批仍exit1、六行正式样本0/6，见[第六批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第六批费用字段误用停批2026-10-29)。

第七批固定843，独立证据 `report/lsp-delivery-84333ee-20261030T002446/`：预检、wrapper构建、自检均通过；真实正常付款对照 `1 passed in 127.3s`，首次取得完整资格。随后01单次触发真实时序：原K接纳请求先被捕获，原调用约4,999ms超时且原回复端口关闭，2ms后才转交同一请求，服务返回 `Buffered`。该K随后记录 `Failed(upstream TLC was removed before hosted delivery dispatch)`、`attempt_count=0`；上游TLC为 `RemoveTlcFail/RemoveAckConfirmed`，付款 `Failed`、发票仍 `Open`，下游session和attempt均为0，四端余额与基线一致。**没有取得“原K失败、下游成功”或资金损失证据，也不把01记为通过。**

01的120秒恢复窗口直到截止仍未通过测试终态门槛，`delivery-01.exit=1`、JUnit 1 failed，异常为 `_PaymentBudgetExpired: late payment result is diagnostic only`。最后样本中付款和delivery均为Failed、原K已记录失败完成、锁定额均为0；但 `list_channels.pending_tlcs` 仍含两条状态为 `RemoveAckConfirmed` 的历史条目，当前 `_finish` 要求该列表为空，因而不能进入最终逐K/资金断言及30秒稳定期。此处是测试终态判据待核问题；在确认固定843对已确认移除TLC的RPC呈现契约前不调整断言或重跑。第七批按失败即停，02～06未运行；六行仍无完整正式通过，前六批证据不覆盖。见[第七批运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第七批01终态判据未过2026-10-30)。

固定843源码核对：[RPC 投影](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/rpc/channel.rs#L565)、[失败确认语义](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-types/src/channel.rs#L581)和[后续清理](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/channel.rs#L8442)显示，RPC 的 `pending_tlcs` 实际遍历 `all_tlcs()`；失败移除获确认后，`RemoveAckConfirmed` 条目可暂留至后续签名清理，列表非空本身不证明仍锁定资金。测试只在该RPC条目与公共节点T原始通道快照的 channel ID、对端身份、TLC ID、hash、金额、双方相反方向及状态唯一对应，且原始记录为 `RemoveTlcFail`、`removed_confirmed_at` 非空、hash属于本批A/B付款时，才从终态和资金断言使用的**活跃视图**排除。原RPC样本与原始快照仍完整留证，未知或不匹配记录继续阻断；逐K失败/下游session、锁定额、余额、实际费用和30秒稳定断言不放宽。此为第七批之后的测试判据修正，**第七批仍exit1，不转记为通过**；修正后的产品行为尚未运行。

离线冻结证据核对（不启动节点、不计产品通过）：使用第七批最后一组原始RPC样本和同一时点的原始T通道快照，新谓词只排除P/T-P两条受证据确认的失败历史；原样本字节意义未改变，父类资金断言在活跃视图通过而在未过滤原样本拒绝。把RPC hash、金额、状态，或原始removed、确认序号、方向、金额、通道ID、记录唯一性分别改坏的九个内存负向均保留条目并阻断；这只验证测试判据对该冻结样本的选择性，不是第七批重新执行，也不证明30秒稳定期。

GPT 6 sol再次独立复核后确认修正无确定阻断：双端活跃状态、零锁定和资金镜像必须一致，但已确认失败的历史列表可以因各端异步清理而不同；不增加无产品依据的双端历史同时存在要求。新执行使用取消诊断后匹配的843基础SDK产物，新增预像控制入口不改变本组既有签名/付款路径。

第八批固定843的新证据为 `report/lsp-delivery-84333ee-20261030T004329/`。上批之后的活跃TLC判据修正已经实际进入本批源码，但正常付款资格对照 `normal-control.exit=1`、JUnit 1 failed，约211.8秒后在120秒恢复截止抛 `_PaymentBudgetExpired`；按资格失败即停，正式01～06均未运行，仍0/6。末样本已见付款 `Success`、发票 `Paid`、delivery `Succeeded`、下游唯一session/attempt `Success`，四端RPC待处理TLC和锁定额均0，T原始通道TLC列表也已清空。这些是观测事实，资格的完整逐K/资金与稳定判据没有执行完，不能将正常对照记通过。

本次阻断与第七批的已确认失败历史列表不同：`_finish` 另要求逐K `tlc_history` 观察到非空 `removed_reason`。冻结的730份直接快照里，原K前5份仅见 `Inbound Committed`、`removed_reason=None`，其后725份 `upstream_tlc=None`；4份事件快照也没有移除原因。薄包装以 `get_all_received_tlcs().find(id)` 读取当前状态，原记录在后续签名中清理后便不可见；当前观察指纹还排除通道字段，因此瞬态完成没有留下持久逐K样本。即便跳过 `_finish` 的该门槛，`_assert_key_outcomes` 的 completed 证据断言也会因同一缺口失败。**这是测试观察证据不足，不能归为产品失败，也不能仅凭成功聚合状态宣告逐K验收通过。** 第七批01已取得的超时后接纳事实和其exit1保持原结论；本批未重跑01，不以此选择其他竞态结果。此组暂停，转普通回归。

后续测试判据仅对正常资格对照和03～06的单个 `observe` 捕获增加受限成功证据：全程无 caller timeout、快照失败或未知事件；唯一原K、delivery、成功session/attempt在hash、金额和preimage上精确绑定；原K历史中从未观察到失败或其他移除原因；真实四端余额、实际费用、存续funding、零活跃锁和30秒稳定仍须逐次成立。若观察到原始完成原因，仍按原逐K原因断言；01/02超时或多K绝不使用这一替代。该路径只证明单K的经济成功，**不声称观察到了原始 `RemoveTlcFulfill`**。第八批仍为资格失败、正式0/6；离线样本核对不计产品测试通过，须以更新后的新批次重新验证。

离线抽取当前判据对第八批冻结末态的样本、原K早期TLC、准备资金基准和完整事件记录作一次核对，单K成功路径与父类四端资金断言均接受；将捕获改为多K、加入真实超时事件、改为已观察原K失败、错绑session K、复制第二条成功attempt、改变P余额各一个内存负例，六例均拒绝。这仅检验判据选择性；第八批没有重新执行，也没有完成30秒稳定窗。

第九批固定843的独立报告为 `report/lsp-delivery-84333ee-20261030T013955/`，执行器 `scripts/run_lsp_delivery_batch.py` 的实际参数、冻结源码/产物摘要及各命令退出码见本批 `runner.py`、`run.json` 和 `.log/.exit/.xml`。使用取消诊断后的843基础SDK bundle，复用第八批已验证的薄包装到新bundle；预检、复用构建和传输自检均通过。真实正常付款资格对照 `exit=0`、126.63秒、JUnit 1 passed；正式01 `exit=0`、121.48秒、JUnit 1 passed。01事件为 `captured 69637 → caller_timeout 74648 → forwarded 74650 → buffered 74663`（相对单调毫秒），原调用真实约5秒超时、回复端口关闭后，同一K才转交；产品安全失败且没有下游支出，逐K、资金与30秒稳定断言完成。正式通过从0增为 **1/6**，第七批原失败和第八批资格失败仍按各自证据保留。

正式02 `exit=1`、91.68秒、JUnit 1 failed：同进程actor薄包装在产品服务接纳后受控丢弃回复（`drop_reply`），产品服务、真实5秒调用超时及原回复端口关闭均真实；不是普通网络流量自然复现。事件 `captured 69667 → forwarded 69675 → buffered 69684 → caller_timeout 74671`，证明 `Buffered` 已在超时前持久化。原K上游为 `RemoveTlcFail/RemoveAckConfirmed`，而 `previous_keys=[K]` 的下游唯一session/attempt均 `Success`；末样本付款 `Failed`、fee=0、发票 `Paid`，P/T-P余额回准备基线，T-A本地余额−1,000,000、A本地余额+1,000,000，镜像端相反、锁定额0。测试在 `test_delivery_acceptance.py:548` 的早期“original K failed but downstream paid”断言即停；正式终态资金断言和30秒稳定期**未执行**，不可称最终持久资金损失。这是已确认故障注入场景下的新产品接纳一致性失败，不归于历史#1674/#1706。

失败即停，03～06无命令、JUnit或产品样本，未重跑竞态；整批 `run.json.status=stopped`、`batch.exit=1`，约346.53秒，低于同一120分钟总预算。最终证据阶段通过，固定843产品源码干净、原项目Git状态与批前一致，本批进程组均absent、六个指定本机端口均 `ECONNREFUSED`；清理检查只覆盖本批进程组与这些端口。第九批完整原始证据、失败日志、事件和节点日志见[运行记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第九批01通过02产品一致性失败2026-10-30)。六行仍有TEST-MAP，当前正式通过 **1/6**；映射不等于通过。


### 2026-10-30 独立夜间批结果

固定843的独立新批中，LSP-DELIVERY-03～06各执行一次并通过，逐K、四端资金及30秒稳定窗口均完成；总488.48秒、batch.exit=0。仅复用代码和产物摘要匹配的已有正常资格，没有重跑01/02。六行正式通过从1/6增至5/6，02的原产品一致性失败保留；不由本批通过冲销。映射行和用例预期不变。原始命令/源码/事件/JUnit及收尾见本夜结果（本地证据：`../../report/lsp-night-new-84333ee-20261030T030349/RESULT.md`）。

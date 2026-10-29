# LSP 实测反馈 Gate1：Watchtower 方向 1/2 摘录

2026-10-29 用户已确认完整 Gate1；本文件仅保存本分支所需的 Watchtower 两个方向，完整候选范围由后续独立变更维护。来源：[LusoCryptoLabs 实测反馈](https://github.com/nervosnetwork/fiber/pull/1623#issuecomment-6418454010)。分析固定产品 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；评论者的结果不是本地复现结论。

| 序号与候选场景 | 前提与操作 | 要验证的结果或待确认点 | 建议优先级 |
| --- | --- | --- | --- |
| 1. 用户收款与 sponsor 分离 | A 只批准自己的 D_A，D_A≠S；T 强关生成真实工作 | 错付 S 必须拒签；正向必须把 A 净份额付给 D_A、S 找零单列；当前产品结构阻塞，先确认契约 | P0 |
| 2. 金额守恒但目的地被换 | 固定原批准，仅把合法候选 payout 换成 S/D_B，check-only | 仍须拒签且零提交，不因金额/费用正确放过错付；不广播变异交易 | P1 |

正式 ID、条件、资金公式和实现边界见[Watchtower Gate2](watchtower-settlement.md#独立收款与目的地替换gate22026-10-29)。

## Delivery 方向 5/6/7

### SPEC-02：接纳调用超时不能造成上游失败、下游独立成功
Condition: 一笔真实 incoming TLC 通过 T 投递给租户；接纳调用在服务处理前或持久化后遭遇超时/丢回复，随后恢复或重启。
Expected: 对同一次 incoming 执行，上下游与 delivery 状态必须一致；上游已不可逆失败后不能再单方面完成下游支出。完全相同执行重投不得多付款，冲突内容不得修改原记录。待确认：超时后的查证/撤销机制、终态和恢复时限；传输超时本身不等于业务失败。
Observable: 原 incoming_channel_id + incoming_tlc_id、tenant/payment hash 关联、delivery 持久状态、上下游 TLC、付款/发票终态、双方余额与费用、真实接纳/回复先后证据。
Basis: [5 秒 actor 调用及超时错误](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/fiber/network.rs#L5312)；[服务接纳、安排恢复后才回复](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/service.rs#L519)；[执行 key](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L23)及[重复/冲突规则](https://github.com/nervosnetwork/fiber/blob/84333eea8488a8afc7e4474aa4bbd0e7e973cee9/crates/fiber-lib/src/lsp/delivery.rs#L415)。key 不含 tenant；相同 hash 的多个 active incoming 也不能假设均可接受。
Source: inference
Testing: 固定84333ee Gate3 第九批正常对照与接纳前超时 01 已通过；已持久化接纳后丢回复的 02 复现原 K 确认失败、同 K 下游付款成功，末次资金采样出现单边支出，30 秒稳定期未执行；同 K 重投 03～06 未运行。详见[第九批记录](../../test_cases/fiber/devnet/lsp/README.md#84333ee-接纳一致性-gate3第九批02复现上下游不一致2026-10-30)。

| 序号与候选场景 | 前提与操作 | 要验证的结果或待确认点 | 建议优先级 |
| --- | --- | --- | --- |
| 5. 接纳前调用超时 | incoming 已排队但尚未处理，调用方越过 5 秒后再放行 | 不出现上游最终失败、下游成功；真实接纳顺序和资金结果必须可证 | P0 |
| 6. 接纳成功但回复丢失 | delivery 已持久化，再丢 actor 回复并恢复 | 查清已接纳事实，同一次 incoming 至多一次有效付款，上下游终态一致 | P0 |
| 7. 同一次 incoming 重投 | 相同 channel+TLC ID 先原样重放，再提交金额/目标冲突内容 | 原样幂等、冲突拒绝，原记录不变；不能换新 key 冒充重试 | P0 |

正式 ID、资金公式和测试边界见[接纳一致性 Gate2](delivery-acceptance-consistency.md)。

# LSP 实测反馈 Gate1：Watchtower 方向 1/2 摘录

2026-10-29 用户已确认完整 Gate1；本文件仅保存本分支所需的 Watchtower 两个方向，完整候选范围由后续独立变更维护。来源：[LusoCryptoLabs 实测反馈](https://github.com/nervosnetwork/fiber/pull/1623#issuecomment-6418454010)。分析固定产品 `84333eea8488a8afc7e4474aa4bbd0e7e973cee9`；评论者的结果不是本地复现结论。

| 序号与候选场景 | 前提与操作 | 要验证的结果或待确认点 | 建议优先级 |
| --- | --- | --- | --- |
| 1. 用户收款与 sponsor 分离 | A 只批准自己的 D_A，D_A≠S；T 强关生成真实工作 | 错付 S 必须拒签；正向必须把 A 净份额付给 D_A、S 找零单列；当前产品结构阻塞，先确认契约 | P0 |
| 2. 金额守恒但目的地被换 | 固定原批准，仅把合法候选 payout 换成 S/D_B，check-only | 仍须拒签且零提交，不因金额/费用正确放过错付；不广播变异交易 | P1 |

正式 ID、条件、资金公式和实现边界见[Watchtower Gate2](watchtower-settlement.md#独立收款与目的地替换gate22026-10-29)。

**English** | [中文](#user-content-chinese-version)

# External funding: ordinary opening timeout is not scheduled after signed submission

已提交：[nervosnetwork/fiber#1674](https://github.com/nervosnetwork/fiber/issues/1674)，提交日期 2026-09-29；
2026-10-23 经 GitHub API 核实时仍为 Open。本文是该 issue 的本地记录，后续沿用原 issue 跟踪。
`LSP-TIMEOUT-04/05` 在 `24b5c38` 的两轮回归复现了同一计时器调度缺口；
新场景的步骤、源码与日志见 [LSP 诊断记录](../../test_cases/fiber/devnet/lsp/README.md#已知问题关联1674)。
05 的晚到通道签名提交尚未执行；下文保留 v0.9.1 的原始复现依据。

## Summary

After a wallet submits a signed external-funding transaction to FNN, Fiber switches its timeout decision from the external-submission deadline to the ordinary opening deadline. The previously scheduled external check arrives before the ordinary deadline and correctly leaves the channel open, but no new check is scheduled. On the official v0.9.1 release, the initiating FNN kept running, yet the channel was still in `CollaboratingFundingTx` after the 180 s opening deadline instead of being aborted.

## Environment and reproduction

- Official [Fiber v0.9.1 release](https://github.com/nervosnetwork/fiber/releases/tag/v0.9.1), CKB `0.202.0` devnet (FNN log timestamps are UTC).
- Initiating FNN configuration: `external_funding_timeout_seconds = 60`, `funding_timeout_seconds = 180`. These shortened values preserve the [release defaults' ordering](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/config.rs#L93-L97): external deadline first (default 5 min), ordinary deadline later (default 1 day).

1. Connect two v0.9.1 FNN nodes. On the initiating node, call `open_channel_with_external_funding` and obtain the unsigned transaction. Sign it with an external CKB wallet.
2. Pause the peer FNN process with `SIGSTOP`, then call `submit_signed_funding_tx` on the still-running initiating node before the 60 s external deadline. The peer cannot process the final transaction or continue the opening; the initiating node accepts the signed transaction.
3. Keep the initiating node running and poll `list_channels({"pubkey": peer_pubkey, "include_closed": true})` for that channel ID every 10 s. The last recorded poll was about 192 s after the unsigned transaction was stored, beyond the 180 s opening deadline.

Pausing the peer holds the channel in `CollaboratingFundingTx`; the [timeout check is handled locally by the initiating FNN](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3852-L3880), which keeps running.

Related history: [Issue #1358](https://github.com/nervosnetwork/fiber/issues/1358) covered an ignored external check caused by sub-millisecond timestamp rounding after a restart, before signed submission; [PR #1367](https://github.com/nervosnetwork/fiber/pull/1367) added 1 ms of scheduling grace. Here the initiating node is not restarted after channel creation, and signed submission moves the applicable deadline about 120 s later. That fix does not schedule the missing check.

## Expected and observed

**Expected:** `funding_timeout_seconds` is [documented as an automatic-close timeout](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/config.rs#L402-L419), [measured from channel creation](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/config.rs#L93-L97). Once the signed transaction is submitted, [Fiber's predicate](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L10221-L10244) selects that ordinary deadline. For `CollaboratingFundingTx`, [can_abort_funding_on_timeout() explicitly returns true](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L10202-L10218), so the initiating FNN should abort the opening if it remains in this state when the deadline expires.

**Observed:** The signed transaction was validated about 1 s after the unsigned transaction was stored. The initiating-node log records two ignored timeout checks around the 60 s external deadline. At the last poll, about 192 s after unsigned storage, the channel was still `CollaboratingFundingTx`; no funding-timeout abort for this channel appeared in the initiating-node log.

## Evidence

Initiating-node log excerpt for channel `0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098` (verbatim):

```text
  2026-09-29T14:24:07.550563Z DEBUG fnn::fiber::channel: Storing unsigned funding tx for external funding channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098): Byte32(0x628a813d9a87cc745f70b70c42cdf31ec7d8a142bf3628d1bc24e933f47df3f7)
  2026-09-29T14:24:08.703927Z DEBUG fnn::fiber::channel: Validated signed funding tx for external funding channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098): Hash256(0x628a813d9a87cc745f70b70c42cdf31ec7d8a142bf3628d1bc24e933f47df3f7)
  2026-09-29T14:25:07.357700Z DEBUG fnn::fiber::channel: Ignore stale funding timeout check for channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098) in state CollaboratingFundingTx(CollaboratingFundingTxFlags(OUR_TX_COMPLETE_SENT | THEIR_TX_COMPLETE_SENT))
  2026-09-29T14:25:07.554290Z DEBUG fnn::fiber::channel: Ignore stale funding timeout check for channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098) in state CollaboratingFundingTx(CollaboratingFundingTxFlags(OUR_TX_COMPLETE_SENT | THEIR_TX_COMPLETE_SENT))
```

Reproduction output excerpt (verbatim; timestamps here are Unix seconds):

```text
OPEN 1790691847.764 0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098
PEER_PAUSED 1790691848.585 pid=21388
SUBMIT 1790691848.715 {"channel_id": "0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098", "funding_tx_hash": "0x628a813d9a87cc745f70b70c42cdf31ec7d8a142bf3628d1bc24e933f47df3f7"}
POLL 1790692029.100 {"state_name": "CollaboratingFundingTx", "state_flags": "OUR_TX_COMPLETE_SENT|THEIR_TX_COMPLETE_SENT|COLLABORATION_COMPLETED"}
POLL 1790692039.122 {"state_name": "CollaboratingFundingTx", "state_flags": "OUR_TX_COMPLETE_SENT|THEIR_TX_COMPLETE_SENT|COLLABORATION_COMPLETED"}
```

The last poll at `1790692039.122` is 2026-09-29 14:27:19.122 UTC, more than 191 s after the unsigned transaction was stored at 14:24:07.550 UTC. The 180 s deadline from channel creation had therefore passed.

## Cause in Fiber v0.9.1

1. [Signed submission](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3499-L3513) sets `signed_submitted = true`; [the timeout predicate](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L10221-L10244) then uses `created_at + funding_timeout_seconds`.
2. [The existing external checks](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3632-L3644) arrive around 60 s. [The handler](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3852-L3880) correctly ignores them because the ordinary deadline has not elapsed, but schedules no replacement.
3. [Actor startup](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L4670-L4690) schedules the deadline applicable at that time; [signed submission](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3595-L3618) does not schedule the newly applicable ordinary check.

## Suggested fix

When signed submission ends the external-submission wait, schedule a funding-timeout check for `created_at + funding_timeout_seconds`. Keep the existing behavior of leaving the channel open when an earlier external check arrives before the ordinary deadline.

---

<a id="chinese-version"></a>

# 中文版

## External funding：提交已签名交易后，FNN 未按开通期限中止通道

### 概要

开通 external funding 通道时，FNN 先等待钱包提交已签名的 funding transaction。本次将等待钱包的期限设为 60 秒，将通道开通超时设为从创建起 180 秒。钱包及时提交后，FNN 在约 60 秒时没有关闭通道是对的，因为 180 秒还没到；问题是 FNN 也没有安排到 180 秒时再检查。我们用正式发布的 v0.9.1 复现：发起节点一直运行，对端暂时无法继续处理开通消息；超过 180 秒后，通道仍停在 `CollaboratingFundingTx`，没有因开通超时而中止。

### 环境与复现

- 使用 [Fiber v0.9.1 正式版](https://github.com/nervosnetwork/fiber/releases/tag/v0.9.1) 和 CKB `0.202.0` devnet（FNN 日志时间为 UTC）。
- 发起节点配置：`external_funding_timeout_seconds = 60`、`funding_timeout_seconds = 180`。缩短时间只是为了加快复现；两者仍与[默认值](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/config.rs#L93-L97)保持相同的先后顺序：等待钱包的期限先到（默认 5 分钟），通道开通期限后到（默认 1 天）。

1. 启动并连接两个 v0.9.1 FNN 节点。发起节点调用 `open_channel_with_external_funding`，取得未签名的 funding transaction；外部 CKB 钱包为这笔交易签名。
2. 用 `SIGSTOP` 暂停对端 FNN，使它暂时不能处理后续开通消息。随后在 60 秒等待期限内，钱包向仍在运行的发起节点调用 `submit_signed_funding_tx`；发起节点成功接收已签名交易。
3. 发起节点始终保持运行。每 10 秒调用 `list_channels({"pubkey": peer_pubkey, "include_closed": true})`，根据通道 ID 查看这条通道的状态。最后一次查询发生在未签名交易保存约 192 秒后，已经超过 180 秒的开通期限。

暂停对端是为了让通道停在 `CollaboratingFundingTx`；超时检查由持续运行的发起节点[在本地处理](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3852-L3880)。

相关历史：[Issue #1358](https://github.com/nervosnetwork/fiber/issues/1358) 发生在钱包尚未提交签名、节点重启之后。时间戳不足 1 毫秒的误差使检查被忽略；[PR #1367](https://github.com/nervosnetwork/fiber/pull/1367) 为此给检查时间增加了 1 毫秒余量。本次创建通道后，发起节点没有重启，钱包已经提交交易，适用期限比原先的检查时间晚约 120 秒；上述修复无法补上这次缺失的检查。

### 预期与实际

**预期：** 配置项 `funding_timeout_seconds` [控制 FNN 何时自动关闭仍未开通的通道](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/config.rs#L402-L419)，时间[从创建通道起算](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/config.rs#L93-L97)。钱包提交已签名交易后，[FNN 的超时判断](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L10221-L10244)就改用这个开通期限。对于 `CollaboratingFundingTx`，[can_abort_funding_on_timeout() 明确返回 true](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L10202-L10218)，因此 180 秒到了而通道仍停在该状态时，发起节点应中止开通。

**实际：** 发起节点保存未签名交易约 1 秒后，就验证通过了钱包提交的已签名交易。约 60 秒时，发起节点日志中有两条忽略超时检查的记录。到最后一次查询时，距离保存未签名交易已约 192 秒，通道仍停在 `CollaboratingFundingTx`；节点日志也没有这条通道因开通超时而中止的记录。

### 证据

发起节点的日志摘录：通道 `0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098`（原文）：

```text
  2026-09-29T14:24:07.550563Z DEBUG fnn::fiber::channel: Storing unsigned funding tx for external funding channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098): Byte32(0x628a813d9a87cc745f70b70c42cdf31ec7d8a142bf3628d1bc24e933f47df3f7)
  2026-09-29T14:24:08.703927Z DEBUG fnn::fiber::channel: Validated signed funding tx for external funding channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098): Hash256(0x628a813d9a87cc745f70b70c42cdf31ec7d8a142bf3628d1bc24e933f47df3f7)
  2026-09-29T14:25:07.357700Z DEBUG fnn::fiber::channel: Ignore stale funding timeout check for channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098) in state CollaboratingFundingTx(CollaboratingFundingTxFlags(OUR_TX_COMPLETE_SENT | THEIR_TX_COMPLETE_SENT))
  2026-09-29T14:25:07.554290Z DEBUG fnn::fiber::channel: Ignore stale funding timeout check for channel Hash256(0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098) in state CollaboratingFundingTx(CollaboratingFundingTxFlags(OUR_TX_COMPLETE_SENT | THEIR_TX_COMPLETE_SENT))
```

复现过程的输出摘录（原文；此处时间戳为 Unix 秒）：

```text
OPEN 1790691847.764 0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098
PEER_PAUSED 1790691848.585 pid=21388
SUBMIT 1790691848.715 {"channel_id": "0x2de7ff195d11642428303c2dd5821fd0b22ea0d7903d1b7593f1891e9fecf098", "funding_tx_hash": "0x628a813d9a87cc745f70b70c42cdf31ec7d8a142bf3628d1bc24e933f47df3f7"}
POLL 1790692029.100 {"state_name": "CollaboratingFundingTx", "state_flags": "OUR_TX_COMPLETE_SENT|THEIR_TX_COMPLETE_SENT|COLLABORATION_COMPLETED"}
POLL 1790692039.122 {"state_name": "CollaboratingFundingTx", "state_flags": "OUR_TX_COMPLETE_SENT|THEIR_TX_COMPLETE_SENT|COLLABORATION_COMPLETED"}
```

最后一次查询的时间 `1790692039.122` 对应 2026-09-29 14:27:19.122 UTC。未签名交易在 14:24:07.550 UTC 保存，两者相隔超过 191 秒；通道创建得更早，所以从创建起算的 180 秒期限肯定也已过去。

### Fiber v0.9.1 中的原因

1. FNN [收到钱包提交的已签名交易](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3499-L3513)后，把 `signed_submitted` 设为 `true`。[超时判断](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L10221-L10244)随之改用 `created_at + funding_timeout_seconds`。
2. FNN [先前安排的检查](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3632-L3644)约在 60 秒时到来。这时 180 秒尚未过去，[FNN 忽略检查](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3852-L3880)是对的，却没有安排 180 秒到期后的下一次检查。
3. [ChannelActor 启动时](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L4670-L4690)只会按当时适用的期限安排检查；[收到已签名交易时](https://github.com/nervosnetwork/fiber/blob/9a561b3e7b786001488b61303a0663d9f4f22259/crates/fiber-lib/src/fiber/channel.rs#L3595-L3618)没有安排新的检查。

### 建议修复

FNN 收到已签名交易后，应按 `created_at + funding_timeout_seconds` 安排一次开通超时检查。先前的检查如果在这个期限前到来，仍不应提前关闭通道。

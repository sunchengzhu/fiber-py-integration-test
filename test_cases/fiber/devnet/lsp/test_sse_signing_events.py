"""PR #1623: real SSE snapshots, tenant isolation, reconnect and takeover."""

import json
import subprocess
import time

from test_cases.fiber.devnet.lsp._lsp_test import (
    BUNDLE,
    ChannelSigningTestBase,
    stop_agent,
)
from test_cases.fiber.devnet.lsp._sse_observer import (
    ObservedSignatureGate,
    SseConnection,
)


class SseTestBase(ChannelSigningTestBase):
    gate_class = ObservedSignatureGate
    agent_extra_args = ("--ack-held-events",)

    def setUp(self):
        self.observers = []
        super().setUp()
        for tenant in self.tenants:
            self._window(tenant, 900)
            self._wait(
                lambda: "event: saved signature held by test; SSE stays connected"
                in self._agent_log(tenant),
                "SDK did not acknowledge the deliberately held event",
            )
            assert not tenant["gate"].forwarded

    def _wait(self, predicate, message, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.1)
        raise AssertionError(message)

    def _agent_log(self, tenant):
        return tenant["status_file"].with_name("agent.log").read_text()

    def _state(self, tenant):
        return tenant["client"].call(
            "get_channel_signing_status", [{"channel_id": tenant["channel_id"]}]
        )

    def _window(self, tenant, seconds):
        channel = self._channel(tenant["client"], tenant["channel_id"])
        created = int(channel["created_at"], 16) / 1000
        assert created + 86400 - time.time() >= seconds, "insufficient opening budget"

    def _stop_preparation_sdk(self):
        for tenant in self.tenants:
            stop_agent(tenant["agent"])
            assert tenant["agent"].poll() is not None
            tenant["gate"].close_streams()
            assert self._state(tenant) == tenant["before"]

    def _connect(self, tenant, session=None, headers=None, query=""):
        if headers is None:
            headers = dict(tenant["client"].other_params, Accept="text/event-stream")
            if session is not None:
                headers["x-lsp-session-id"] = session
        stream = SseConnection(self.fiber1.client.url + "/lsp/events" + query, headers)
        self.observers.append(stream)
        self.addCleanup(stream.close)
        return stream

    def _valid_stream(self, stream):
        assert stream.status == 200, (stream.status, stream.body)
        assert stream.content_type.split(";")[0] == "text/event-stream"
        assert stream.session_id and len(stream.session_id) == 32
        int(stream.session_id, 16)
        assert not stream.errors, stream.errors

    def _snapshot_events(self, stream, expected):
        self._valid_stream(stream)

        def complete():
            assert not stream.errors, stream.errors
            frames = stream.frames()
            for index, (_, name, _) in enumerate(frames):
                if name == "lsp.snapshot_complete":
                    return frames[: index + 1]
            assert not stream.ended.is_set(), "stream ended before snapshot_complete"
            return None

        frames = self._wait(complete, "SSE initial snapshot did not complete")
        signatures = [
            payload["payload"]
            for _, name, payload in frames
            if name == "lsp.channel.signature_required"
        ]
        # Include cardinality: duplicate frames must not disappear into a set.
        assert len(signatures) == len(expected), signatures
        assert sorted(json.dumps(p, sort_keys=True) for p in signatures) == sorted(
            json.dumps(p, sort_keys=True) for p in expected
        ), signatures
        return signatures

    def _new_event(self, stream, tenant, previous_id):
        def find():
            assert not stream.errors, stream.errors
            for _, name, payload in stream.frames():
                if name == "lsp.channel.signature_required":
                    value = payload["payload"]
                    if value["status"]["request_id"] != previous_id:
                        assert value["channel_id"] == tenant["channel_id"], value
                        return value
            assert not stream.ended.is_set(), "original SSE connection closed"
            return None

        # Do not poll signing-status RPC here: the event must arrive by itself.
        value = self._wait(find, "no next signature on the original SSE connection")
        assert value == self._state(tenant)
        assert time.monotonic() - stream.responded < 300
        return value

    def _submit_saved(self, tenant, submission=None):
        submission = submission or tenant["gate"].submission
        result = tenant["client"].call("submit_channel_signature", [submission])
        assert result == {"type": "Applied"}, result

    def _assert_owner(self, stream, tenant):
        self._valid_stream(stream)
        assert not stream.ended.is_set(), "owner stream unexpectedly closed"
        for _, name, payload in stream.frames():
            if name == "lsp.channel.signature_required":
                assert payload["payload"]["channel_id"] == tenant["channel_id"], payload

    def _finish_channels(self, restart=True):
        for observer in self.observers:
            observer.close()
        for tenant in self.tenants:
            self._window(tenant, 180)
            if restart:
                stop_agent(tenant["agent"])
                tenant["gate"].close_streams()
                tenant["gate"].release()
                tenant["agent"] = subprocess.Popen(
                    tenant["command"], stdout=tenant["log"], stderr=subprocess.STDOUT
                )
                self.addCleanup(stop_agent, tenant["agent"])
            # For a live SDK with an acknowledged held event, the caller submits
            # that saved signature before entering this terminal-state check.
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                assert tenant["agent"].poll() is None, self._agent_log(tenant)[-1500:]
                local = self._channel(tenant["client"], tenant["channel_id"])
                public = self._channel(self.fiber1.client, tenant["channel_id"])
                if (
                    local["state"]["state_name"]
                    == public["state"]["state_name"]
                    == "ChannelReady"
                    and self._state(tenant)["status"]["type"] == "NoSignatureRequired"
                ):
                    break
                time.sleep(0.2)
            else:
                raise AssertionError(
                    f"original channel did not finish: {local['state']}"
                )
            assert len(tenant["client"].list_channels({})["channels"]) == 1
            assert local["channel_outpoint"] == public["channel_outpoint"]
            outpoint = bytes.fromhex(local["channel_outpoint"][2:])
            assert len(outpoint) == 36
            assert "0x" + outpoint[:32].hex() == tenant["funding_tx_hash"]
            tx = self.node.getClient().get_transaction(tenant["funding_tx_hash"])
            assert tx["tx_status"]["status"] == "committed", tx
            stable = (local, public)
            for _ in range(5):
                time.sleep(1)
                assert self._state(tenant)["status"]["type"] == "NoSignatureRequired"
                for client, before in zip(
                    (tenant["client"], self.fiber1.client), stable
                ):
                    after = self._channel(client, tenant["channel_id"])
                    for key in (
                        "state",
                        "channel_outpoint",
                        "local_balance",
                        "remote_balance",
                        "pending_tlcs",
                    ):
                        assert after[key] == before[key], (key, before[key], after[key])


class TestSseSigningEvents(SseTestBase):
    # TEST-MAP: LSP-SSE-01
    def test_initial_snapshot_preserves_pending_request(self):
        """1. 冻结真实请求后停止准备 SDK。2. 核对完整快照与未推进状态。3. 恢复原通道。"""
        # 1. 冻结请求，避免 SDK 与观察者无意互相接管。
        self._stop_preparation_sdk()
        before = self._state(self.tenant)

        # 2. 读完快照再比较全部请求，通知不得应用签名。
        stream = self._connect(self.tenant)
        self._snapshot_events(stream, [before])
        assert self._state(self.tenant) == before

        # 3. 继续原通道并检查真实注资及稳定终态。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-02
    def test_next_request_arrives_on_original_connection(self):
        """1. 建立含 R1 的订阅。2. 应用 S1，不轮询等待同连接 R2。3. 完成原通道。"""
        # 1. 读取完整初始快照。
        self._stop_preparation_sdk()
        stream = self._connect(self.tenant)
        self._snapshot_events(stream, [self.tenant["before"]])

        # 2. 原 HTTP 流上等新事件，之后才查询 RPC 作比对。
        self._submit_saved(self.tenant)
        self._new_event(
            stream, self.tenant, self.tenant["before"]["status"]["request_id"]
        )

        # 3. 不重建通道，继续签名并核对终态。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-05
    def test_reconnect_replays_unsubmitted_request_in_same_session(self):
        """1. 收到冻结 R1。2. 关闭连接并带原会话重连，检查相同快照。3. 完成原通道。"""
        # 1. 保存初始快照与会话。
        self._stop_preparation_sdk()
        first = self._connect(self.tenant)
        self._snapshot_events(first, [self.tenant["before"]])

        # 2. 真正结束旧传输；显式保留会话而非主动接管。
        first.close()
        assert first.ended.is_set()
        second = self._connect(self.tenant, first.session_id)
        assert second.session_id == first.session_id
        self._snapshot_events(second, [self.tenant["before"]])
        assert self._state(self.tenant) == self.tenant["before"]

        # 3. 签名仍只应用于原通道。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-06
    def test_sdk_reconnects_without_restart(self):
        """1. 确认 SDK 已处理暂停事件。2. 切断 SSE，核对同进程自动恢复。3. 应用一次签名完成原通道。"""
        # 1. 准备结束时已经看到真实 SDK 的暂停确认日志。
        tenant, gate = self.tenant, self.gate
        pid = tenant["agent"].pid
        first = gate.connections()[-1]
        # SDK subscribes before opening; R1 arrives after its empty initial snapshot.
        assert self._new_event(first, tenant, None) == tenant["before"]
        count = len(gate.connections())
        attempts = len(gate.attempts)

        # 2. 只切断传输，绝不手工订阅或重启 SDK。
        gate.cut(first)
        second = self._wait(
            lambda: (
                gate.connections()[count] if len(gate.connections()) > count else None
            ),
            "SDK did not automatically reconnect",
        )
        assert second.request_session == first.session_id
        assert second.session_id == first.session_id
        self._snapshot_events(second, [tenant["before"]])
        self._wait(
            lambda: len(gate.attempts) > attempts,
            "SDK did not resubmit stored signature",
        )
        assert tenant["agent"].pid == pid and tenant["agent"].poll() is None
        assert gate.attempts[attempts][1] == gate.submission
        assert not gate.forwarded
        assert self._state(tenant) == tenant["before"]

        # 3. 已确认暂停事件不会自行重发，直连应用真实 S1 后放行后续轮次。
        gate.release()
        self._submit_saved(tenant)
        self._finish_channels(restart=False)

    # TEST-MAP: LSP-SSE-07
    def test_reconnect_snapshot_contains_only_current_request(self):
        """1. 应用 R1 并冻结 R2。2. 重连后完整快照只包含 R2。3. 完成原通道。"""
        # 1. 旧请求已真实应用，下一轮只观察不提交。
        self._stop_preparation_sdk()
        first = self._connect(self.tenant)
        self._snapshot_events(first, [self.tenant["before"]])
        self._submit_saved(self.tenant)
        current = self._new_event(
            first, self.tenant, self.tenant["before"]["status"]["request_id"]
        )

        # 2. 新连接与旧缓冲分开，以快照结束标记判定 R1 缺席。
        first.close()
        second = self._connect(self.tenant, first.session_id)
        assert second.session_id == first.session_id
        self._snapshot_events(second, [current])
        assert self._state(self.tenant) == current

        # 3. 原通道继续，不能另开通道绕过恢复。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-09
    def test_replaced_sdk_stops_retrying(self):
        """1. 真实 SDK 已确认暂停事件。2. 新连接接管，检查旧 SDK 的 409 和自行退出。3. 观察不重试并恢复原通道。"""
        # 1. 不杀 SDK，保留原进程和 H1。
        tenant, gate = self.tenant, self.gate
        first = gate.connections()[-1]
        assert self._new_event(first, tenant, None) == tenant["before"]
        count = len(gate.connections())
        log_offset = len(self._agent_log(tenant))

        # 2. 只读客户端主动接管，409 必须来自真实 FNN。
        replacement = self._connect(tenant)
        self._snapshot_events(replacement, [tenant["before"]])
        assert replacement.session_id != first.session_id
        assert first.ended.wait(10), "old SDK stream did not end after takeover"
        rejected = self._wait(
            lambda: next(
                (s for s in gate.connections()[count:] if s.status == 409), None
            ),
            "old SDK did not receive a real 409",
        )
        assert rejected.request_session == first.session_id
        tenant["agent"].wait(timeout=10)
        ending = self._agent_log(tenant)[log_offset:]
        assert "tenant event reader stopped" in ending, ending
        assert "panicked" not in ending, ending
        assert len(gate.connections()) == count + 1
        self._submit_saved(tenant)
        self._new_event(replacement, tenant, tenant["before"]["status"]["request_id"])

        # 3. 不能用短暂静默代替停止证据；新会话在观察期间仍有效。
        until = rejected.responded + 65
        while time.monotonic() < until:
            assert len(gate.connections()) == count + 1
            assert tenant["agent"].poll() is not None
            self._assert_owner(replacement, tenant)
            time.sleep(0.2)
        self._finish_channels()


class TestSseTenantIsolation(SseTestBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-SSE-03
    def test_snapshot_and_live_events_are_tenant_scoped(self):
        """1. 两租户独立订阅。2. 分别推进真实请求并检查归属。3. 观察一个心跳周期后完成双方通道。"""
        # 1. 冻结两份请求，完整快照不得串租户。
        self._stop_preparation_sdk()
        streams = [self._connect(t) for t in self.tenants]
        for stream, tenant in zip(streams, self.tenants):
            self._snapshot_events(stream, [tenant["before"]])

        # 2. 双方都必须实际出现新事件。
        for stream, tenant in zip(streams, self.tenants):
            self._submit_saved(tenant)
            self._new_event(stream, tenant, tenant["before"]["status"]["request_id"])

        # 3. 心跳 25 秒加 5 秒余量内检查所有帧，而非只看首帧。
        until = time.monotonic() + 30
        while time.monotonic() < until:
            for stream, tenant in zip(streams, self.tenants):
                self._assert_owner(stream, tenant)
            time.sleep(0.2)
        self._finish_channels()

    # TEST-MAP: LSP-SSE-08
    def test_takeover_rejects_old_session_without_affecting_other_tenant(self):
        """1. A/B 建立独立会话。2. 新 A 接管，旧会话重连被拒。3. 新 A 与原 B 收到后续请求并完成通道。"""
        # 1. 准备冻结请求与两个真实初始快照。
        self._stop_preparation_sdk()
        a, b = self.tenants
        old, other = self._connect(a), self._connect(b)
        self._snapshot_events(old, [a["before"]])
        self._snapshot_events(other, [b["before"]])

        # 2. 没有会话头表示主动接管；旧 H1 不得夺回新连接。
        new = self._connect(a)
        self._snapshot_events(new, [a["before"]])
        assert new.session_id != old.session_id
        assert old.ended.wait(10), "old HTTP stream survived takeover"
        rejected = self._connect(a, old.session_id)
        assert rejected.status == 409, (rejected.status, rejected.body)
        assert not rejected.frames()

        # 3. 用拒绝之后才产生的新事件证明两条正确连接都能继续。
        for stream, tenant in ((new, a), (other, b)):
            self._submit_saved(tenant)
            self._new_event(stream, tenant, tenant["before"]["status"]["request_id"])
            self._assert_owner(stream, tenant)
        self._finish_channels()


class TestSseInvalidSubscriptions(SseTestBase):
    tenant_labels = ("A", "B")

    def _reject_without_eviction(self, kind, expected):
        self._stop_preparation_sdk()
        a, b = self.tenants
        current = self._connect(a)
        self._snapshot_events(current, [a["before"]])
        headers = dict(a["client"].other_params)
        query = ""
        if kind == "missing":
            headers = {}
        elif kind == "invalid":
            headers["Authorization"] = "Bearer invalid"
        elif kind == "operator":
            headers["Authorization"] = (
                "Bearer " + (BUNDLE / "operator-token").read_text().strip()
            )
        elif kind == "query":
            query = "?tenant=" + b["status"]["tenant_id"]
        elif kind == "session":
            headers["x-lsp-session-id"] = "invalid"
        else:
            raise AssertionError(kind)
        rejected = self._connect(a, headers=headers, query=query)
        assert rejected.status == expected, (rejected.status, rejected.body)
        assert not rejected.frames() and b"signature_required" not in rejected.body
        assert self._state(a) == a["before"]
        assert self._state(b) == b["before"]
        self._submit_saved(a)
        self._new_event(current, a, a["before"]["status"]["request_id"])
        self._assert_owner(current, a)

    # TEST-MAP: LSP-SSE-04
    def test_missing_token_does_not_evict_subscriber(self):
        """1. 缺少认证应被拒且不挤掉合法连接。2. 完成原通道。"""
        # 1. 在独立环境验证 401 和原流后续事件。
        self._reject_without_eviction("missing", 401)
        # 2. 合法业务继续完成。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-04
    def test_invalid_token_does_not_evict_subscriber(self):
        """1. 无效认证应被拒且不挤掉合法连接。2. 完成原通道。"""
        # 1. 在独立环境验证 403 和原流后续事件。
        self._reject_without_eviction("invalid", 403)
        # 2. 合法业务继续完成。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-04
    def test_operator_token_does_not_evict_subscriber(self):
        """1. operator token 不得订阅租户事件。2. 合法连接继续开通。"""
        # 1. 在独立环境验证 403 和原流后续事件。
        self._reject_without_eviction("operator", 403)
        # 2. 合法业务继续完成。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-04
    def test_tenant_query_does_not_evict_subscriber(self):
        """1. A 使用真实 B 的身份参数不能更换订阅归属。2. 原通道继续完成。"""
        # 1. 在独立环境验证 400、双方状态和原流后续事件。
        self._reject_without_eviction("query", 400)
        # 2. 合法业务继续完成。
        self._finish_channels()

    # TEST-MAP: LSP-SSE-04
    def test_malformed_session_does_not_evict_subscriber(self):
        """1. 畸形会话头应被拒且不挤掉合法连接。2. 原通道继续完成。"""
        # 1. 在独立环境验证 400 和原流后续事件。
        self._reject_without_eviction("session", 400)
        # 2. 合法业务继续完成。
        self._finish_channels()

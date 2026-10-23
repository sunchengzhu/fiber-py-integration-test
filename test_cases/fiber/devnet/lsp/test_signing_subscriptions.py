"""PR #1623: current signing work, scoped subscriptions and SDK recovery."""

import json
import subprocess
import time

from test_cases.fiber.devnet.lsp._lsp_test import (
    BUNDLE,
    ChannelSigningTestBase,
    stop_agent,
)
from test_cases.fiber.devnet.lsp._subscription_observer import SubscriptionObserver


class SubscriptionTestBase(ChannelSigningTestBase):
    agent_extra_args = ("--ack-held-events",)

    def setUp(self):
        self.observers = []
        super().setUp()
        for tenant in self.tenants:
            self._window(tenant, 300)
            self._wait(
                lambda: "event: saved signature held by test; subscription stays connected"
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
        assert (
            created + self.opening_window_seconds - time.time() >= seconds
        ), "insufficient opening budget"

    def _stop_preparation_sdk(self):
        for tenant in self.tenants:
            stop_agent(tenant["agent"])
            assert tenant["agent"].poll() is not None
            tenant["subscription_proxy"].close_streams()
            assert self._state(tenant) == tenant["before"]

    def _connect(self, tenant=None, headers=None):
        if headers is None:
            headers = dict((tenant or self.tenant)["client"].other_params)
        observer = SubscriptionObserver(self.ws_url, headers)
        self.observers.append(observer)
        self.addCleanup(observer.close)
        return observer

    def _subscribe(self, observer):
        subscription = observer.subscribe("channel_signing")
        assert type(subscription) in (str, int), subscription
        assert not observer.errors, observer.errors
        return subscription

    def _events(self, observer, subscription):
        assert not observer.errors, observer.errors
        return [
            result
            for _, actual, result in observer.frames()
            if type(actual) is type(subscription) and actual == subscription
        ]

    def _wait_data(self, observer, subscription, expected):
        result = observer.wait_event(
            subscription,
            lambda event: event == {"type": "channel_signing", "data": expected},
            timeout=60,
        )
        assert result == {"type": "channel_signing", "data": expected}, result
        return result["data"]

    def _observe(self, check, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            check()
            time.sleep(0.1)
        check()

    def _new_event(self, observer, subscription, tenant, previous_id):
        result = observer.wait_event(
            subscription,
            lambda event: (
                event.get("type") == "channel_signing"
                and event["data"]["status"]["type"] == "SignatureRequired"
                and event["data"]["status"]["request_id"] != previous_id
            ),
            timeout=60,
        )
        value = result["data"]
        assert value["channel_id"] == tenant["channel_id"], value
        # This query is deliberately after the live notification, never its trigger.
        assert value == self._state(tenant)
        request_id = value["status"]["request_id"]
        self._wait(
            lambda: tenant["gate"].submissions.get(request_id),
            "real SDK did not save the following held signature",
        )
        assert not tenant["gate"].forwarded
        return value

    def _submit_saved(self, tenant, submission=None):
        self._window(tenant, 300)
        submission = submission or tenant["gate"].submission
        result = tenant["client"].call("submit_channel_signature", [submission])
        assert result == {"type": "Applied"}, result

    def _assert_owner(self, observer, subscription, tenant):
        assert not observer.ended.is_set(), "owner connection unexpectedly closed"
        for event in self._events(observer, subscription):
            assert event["type"] == "channel_signing", event
            assert event["data"]["channel_id"] == tenant["channel_id"], event

    def _assert_pending_only(self, observer, subscription, expected):
        self._assert_owner(observer, subscription, self.tenant)
        assert self._events(observer, subscription), "no pending request delivered"
        for event in self._events(observer, subscription):
            assert event == {"type": "channel_signing", "data": expected}, event

    def _finish_channels(self, restart=True):
        for tenant in self.tenants:
            self._window(tenant, 300)
            if restart:
                stop_agent(tenant["agent"])
                tenant["subscription_proxy"].close_streams()
                tenant["gate"].release()
                tenant["agent"] = subprocess.Popen(
                    tenant["command"], stdout=tenant["log"], stderr=subprocess.STDOUT
                )
                self.addCleanup(stop_agent, tenant["agent"])
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                assert tenant["agent"].poll() is None, self._agent_log(tenant)[-1500:]
                assert not tenant["gate"].errors, tenant["gate"].errors
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


class TestSigningSubscriptions(SubscriptionTestBase):
    # TEST-MAP: LSP-SUBSCRIPTION-01
    def test_initial_subscription_preserves_pending_request(self):
        """1. 冻结真实请求并停止准备 SDK。2. 核对完整补发与未推进状态。3. 恢复原通道。"""
        # 1. SDK 已保存 S1，停止进程但保留原存储。
        self._stop_preparation_sdk()
        before = self._state(self.tenant)

        # 2. 没有完成标记；完整 R1 到达后有界观察当前集合。
        observer = self._connect()
        subscription = self._subscribe(observer)
        self._wait_data(observer, subscription, before)
        self._observe(lambda: self._assert_pending_only(observer, subscription, before))
        assert self._state(self.tenant) == before

        # 3. 原存储继续签名并检查真实注资及稳定终态。
        self._finish_channels()

    # TEST-MAP: LSP-SUBSCRIPTION-02
    def test_next_request_arrives_on_original_subscription(self):
        """1. 建立含 R1 的订阅。2. 应用 S1，不查询等待原订阅 R2。3. 完成原通道。"""
        # 1. 观察器与暂停提交的真实 SDK 同时订阅。
        observer = self._connect()
        subscription = self._subscribe(observer)
        self._wait_data(observer, subscription, self.tenant["before"])

        # 2. 先收到事件才调用查询交叉核对，S2 继续由 gate 冻结。
        self._submit_saved(self.tenant)
        self._new_event(
            observer,
            subscription,
            self.tenant,
            self.tenant["before"]["status"]["request_id"],
        )

        # 3. 不重建通道，继续签名并核对终态。
        self._finish_channels()

    # TEST-MAP: LSP-SUBSCRIPTION-05
    def test_reconnect_replays_unsubmitted_request(self):
        """1. 收到冻结 R1。2. 关闭连接并重新订阅，核对完整 R1。3. 同订阅收到 R2 后完成原通道。"""
        # 1. 第一条连接收到未应用的完整请求。
        first = self._connect()
        first_id = self._subscribe(first)
        self._wait_data(first, first_id, self.tenant["before"])

        # 2. 使用原 token 建立新连接，不附带已移除的会话参数。
        first.close()
        assert first.ended.is_set()
        second = self._connect()
        second_id = self._subscribe(second)
        self._wait_data(second, second_id, self.tenant["before"])
        self._observe(
            lambda: self._assert_pending_only(second, second_id, self.tenant["before"])
        )
        assert self._state(self.tenant) == self.tenant["before"]

        # 3. 同一新订阅收到主动产生的 R2，证明补发后的连接仍工作。
        self._submit_saved(self.tenant)
        self._new_event(
            second,
            second_id,
            self.tenant,
            self.tenant["before"]["status"]["request_id"],
        )
        self._finish_channels()

    # TEST-MAP: LSP-SUBSCRIPTION-06
    def test_sdk_reconnects_without_restart(self):
        """1. 确认 SDK 已处理暂停事件并放行提交。2. 切断真实连接，核对同进程自动恢复。3. 核对 SDK 首次应用原签名并完成通道。"""
        # 1. setUp 已等到 processed 成功日志，记录实际交付和原 PID。
        tenant, gate = self.tenant, self.gate
        proxy = tenant["subscription_proxy"]
        pid = tenant["agent"].pid
        first = proxy.connections()[-1]
        expected = {"type": "channel_signing", "data": tenant["before"]}
        assert any(event == expected for _, _, event in first.delivered_frames())
        count, attempts = len(proxy.connections()), len(gate.attempts)
        self._window(tenant, 300)
        gate.release()
        # The original event has already been acknowledged: opening the HTTP
        # gate alone must not submit S1. Recovery must be driven by new WS work.
        assert not gate.forwarded

        # 2. 只切断当前 SDK 传输；新连接、成功订阅及 R1 均来自原 SDK。
        proxy.cut(first)
        second = self._wait(
            lambda: next(
                (
                    connection
                    for connection in proxy.connections()[count:]
                    if any(
                        item.get("topic") == "channel_signing"
                        and "subscription_id" in item
                        and "delivered_at" in item
                        for item in connection.subscriptions
                    )
                ),
                None,
            ),
            "SDK did not automatically reconnect and subscribe",
        )
        subscription = next(
            item["subscription_id"]
            for item in second.subscriptions
            if item.get("topic") == "channel_signing"
            and "subscription_id" in item
            and "delivered_at" in item
        )
        delivered_at = self._wait(
            lambda: next(
                (
                    at
                    for at, actual, event in second.delivered_frames()
                    if type(actual) is type(subscription)
                    and actual == subscription
                    and event == expected
                ),
                None,
            ),
            "new SDK subscription did not receive complete pending R1",
        )
        self._wait(
            lambda: len(gate.attempts) > attempts, "SDK did not resubmit saved S1"
        )
        assert tenant["agent"].pid == pid and tenant["agent"].poll() is None
        assert (
            gate.attempts[attempts][0] >= delivered_at
        ), "S1 was attempted before the new subscription delivered R1"
        assert gate.attempts[attempts][1] == gate.submission

        # 3. 首次实际转发来自恢复后的真实 SDK，不能用 Python 直连提交替代。
        submission, response = self._wait(
            lambda: gate.forwarded[0] if gate.forwarded else None,
            "reconnected SDK did not submit its saved signature to FNN",
        )
        assert submission == gate.submission
        assert response.get("result") == {"type": "Applied"}, response
        assert "error" not in response, response
        self._finish_channels(restart=False)
        assert tenant["agent"].pid == pid and tenant["agent"].poll() is None

    # TEST-MAP: LSP-SUBSCRIPTION-07
    def test_reconnect_replays_only_current_request(self):
        """1. 应用 R1 并冻结 R2。2. 重连补发 R2 且不回放 R1。3. 同订阅观察后续状态并完成原通道。"""
        # 1. 旧请求已真实应用，下一轮由真实 SDK 保存但不提交。
        first = self._connect()
        first_id = self._subscribe(first)
        self._wait_data(first, first_id, self.tenant["before"])
        self._submit_saved(self.tenant)
        current = self._new_event(
            first, first_id, self.tenant, self.tenant["before"]["status"]["request_id"]
        )

        # 2. 新连接收齐冻结当前工作，再有界检查 R1 不出现。
        first.close()
        second = self._connect()
        second_id = self._subscribe(second)
        self._wait_data(second, second_id, current)
        self._observe(lambda: self._assert_pending_only(second, second_id, current))
        assert self._state(self.tenant) == current

        # 3. 恢复签名，直到同一订阅收到后续正向状态均不允许 R1 重放。
        self._finish_channels()
        self._wait_data(second, second_id, self._state(self.tenant))
        previous_id = self.tenant["before"]["status"]["request_id"]
        for event in self._events(second, second_id):
            assert event["data"]["status"].get("request_id") != previous_id, event

    # TEST-MAP: LSP-SUBSCRIPTION-10
    def test_operator_subscribes_only_to_host_signing_state(self):
        """1. 租户与 operator 分别订阅。2. 推进租户并检查私有请求不泄露。3. 新建 host 通道验证正向事件并完成原通道。"""
        # 1. operator 具有 host 订阅权限，不沿用旧版一律拒绝的预期。
        owner = self._connect()
        owner_id = self._subscribe(owner)
        self._wait_data(owner, owner_id, self.tenant["before"])
        # The registration operator fixture lacks write(subscriptions). Mint a
        # host-scoped test credential with both required topic capabilities.
        fixture = json.loads(
            subprocess.check_output(
                [str(BUNDLE / "lsp-integration-driver"), "operator-subscription-token"],
                input=json.dumps(
                    {"private_key_file": str(BUNDLE / "biscuit-private-key")}
                ),
                text=True,
                timeout=10,
            )
        )
        operator = self._connect(
            headers={"Authorization": "Bearer " + fixture["token"]}
        )
        operator_id = self._subscribe(operator)

        # 2. A–T 同一 ID 的 host NoSignatureRequired 合法，租户私有待签不合法。
        self._submit_saved(self.tenant)
        current = self._new_event(
            owner, owner_id, self.tenant, self.tenant["before"]["status"]["request_id"]
        )

        def private_request_absent():
            for event in self._events(operator, operator_id):
                assert event["type"] == "channel_signing", event
                if event["data"]["channel_id"] == self.channel_id:
                    assert event["data"]["status"]["type"] != "SignatureRequired", event
                assert event["data"] not in (self.tenant["before"], current), event

        self._observe(private_request_absent)

        # 3. 订阅后新建 T–P，本地签名状态事件证明 operator 原订阅仍有效。
        auto_accept_min = int(
            self.fiber2.client.node_info()[
                "open_channel_auto_accept_min_ckb_funding_amount"
            ],
            16,
        )
        assert auto_accept_min > 0, "host fixture requires automatic channel acceptance"
        # At equality the shared helper manually accepts a channel P has already
        # auto-accepted. Stay above that unrelated boundary and avoid a payment.
        host_channel = self.open_channel(
            self.fiber1, self.fiber2, auto_accept_min + 100 * 100000000, 0
        )
        assert host_channel != self.channel_id
        expected = self.fiber1.client.call(
            "get_channel_signing_status", [{"channel_id": host_channel}]
        )
        assert expected["status"]["type"] == "NoSignatureRequired", expected
        self._wait_data(operator, operator_id, expected)
        private_request_absent()
        self._finish_channels()
        private_request_absent()

    # TEST-MAP: LSP-SUBSCRIPTION-11
    def test_same_tenant_connections_receive_independent_updates(self):
        """1. 同租户两连接各自收到 R1。2. 单次应用 S1 后两订阅收到 R2。3. 完成原通道。"""
        # 1. 不把两个连接的 ID 当成全局唯一标识。
        first, second = self._connect(), self._connect()
        first_id, second_id = self._subscribe(first), self._subscribe(second)
        for observer, subscription in ((first, first_id), (second, second_id)):
            self._wait_data(observer, subscription, self.tenant["before"])

        # 2. 新客户端不能接管或关闭旧客户端；同一次状态变化投递两份。
        self._submit_saved(self.tenant)
        current = self._new_event(
            first, first_id, self.tenant, self.tenant["before"]["status"]["request_id"]
        )
        self._wait_data(second, second_id, current)
        for observer, subscription in ((first, first_id), (second, second_id)):
            self._assert_owner(observer, subscription, self.tenant)
        assert self._state(self.tenant) == current

        # 3. 同一原通道和原注资完成，状态保持稳定。
        self._finish_channels()

    # TEST-MAP: LSP-SUBSCRIPTION-12
    def test_unsubscribe_preserves_other_subscriptions(self):
        """1. 同连接两订阅及另连接一订阅收到 R1。2. 取消其中一个后生成 R2。3. 其他订阅继续且被取消者不收新请求。"""
        # 1. 明确三个独立订阅均已收到当前工作。
        first, second = self._connect(), self._connect()
        cancelled = self._subscribe(first)
        kept = self._subscribe(first)
        other = self._subscribe(second)
        assert type(cancelled) is not type(kept) or cancelled != kept
        for observer, subscription in (
            (first, cancelled),
            (first, kept),
            (second, other),
        ):
            self._wait_data(observer, subscription, self.tenant["before"])

        # 2. 成功取消之后才应用 S1，旧缓冲 R1 不计作取消失败。
        assert first.unsubscribe(cancelled) is True
        self._submit_saved(self.tenant)
        current = self._new_event(
            first, kept, self.tenant, self.tenant["before"]["status"]["request_id"]
        )
        self._wait_data(second, other, current)

        # 3. 正向证明两条保留订阅有效后继续观察五秒，再完成原业务。
        def cancelled_request_absent():
            self._assert_owner(first, kept, self.tenant)
            self._assert_owner(second, other, self.tenant)
            for event in self._events(first, cancelled):
                assert (
                    event["data"]["status"].get("request_id")
                    != current["status"]["request_id"]
                ), event

        self._observe(cancelled_request_absent)
        self._finish_channels()
        cancelled_request_absent()

    # TEST-MAP: LSP-SUBSCRIPTION-13
    def test_cross_connection_and_unknown_unsubscribe_preserve_subscriptions(self):
        """1. 建立 ID 不重合的两个连接订阅。2. 尝试跨连接与未知 ID 取消。3. 原订阅均收到新 R2 并完成业务。"""
        # 1. 跨连接 ID 可能复用；只选择目标连接并未拥有的 ID 作为测试输入。
        first = self._connect()
        first_id = self._subscribe(first)
        self._wait_data(first, first_id, self.tenant["before"])
        for _ in range(4):
            second = self._connect()
            second_id = self._subscribe(second)
            if type(first_id) is not type(second_id) or first_id != second_id:
                break
            second.close()
        else:
            raise AssertionError(
                "could not prepare distinct subscription IDs in four connections"
            )
        self._wait_data(second, second_id, self.tenant["before"])
        unknown = f"unknown-subscription-{time.monotonic_ns()}"
        assert unknown not in (first_id, second_id)

        # 2. 两次请求均来自 C2，不能取消 C1 或误伤 C2 本身。
        assert second.unsubscribe(first_id) is False
        assert second.unsubscribe(unknown) is False

        # 3. 两条原订阅都收到失败取消后才产生的新请求。
        self._submit_saved(self.tenant)
        current = self._new_event(
            first, first_id, self.tenant, self.tenant["before"]["status"]["request_id"]
        )
        self._wait_data(second, second_id, current)
        self._assert_owner(first, first_id, self.tenant)
        self._assert_owner(second, second_id, self.tenant)
        self._finish_channels()


class TestSubscriptionIsolation(SubscriptionTestBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-SUBSCRIPTION-03
    def test_initial_and_live_events_are_tenant_scoped(self):
        """1. 两租户分别收到自己的完整 R1。2. 观察五秒后依次产生 R2。3. 持续检查归属并完成两条原通道。"""
        # 1. 初始集合冻结，完整事件不能串租户。
        pairs = [(self._connect(tenant), tenant) for tenant in self.tenants]
        subscriptions = [self._subscribe(observer) for observer, _ in pairs]
        for (observer, tenant), subscription in zip(pairs, subscriptions):
            self._wait_data(observer, subscription, tenant["before"])

        # 2. 负向观察之后，两条原订阅必须各自产生新的正向事件。
        def owners_only():
            for (observer, tenant), subscription in zip(pairs, subscriptions):
                self._assert_owner(observer, subscription, tenant)

        self._observe(owners_only)
        for (observer, tenant), subscription in zip(pairs, subscriptions):
            self._submit_saved(tenant)
            self._new_event(
                observer, subscription, tenant, tenant["before"]["status"]["request_id"]
            )
            owners_only()

        # 3. 一直检查到双方新 R2 到达，之后完成原注资对应的两条通道。
        owners_only()
        self._finish_channels()
        owners_only()


class TestInvalidSubscriptions(SubscriptionTestBase):
    def _reject_subscription(self, kind):
        tenant = self.tenant
        current = self._connect()
        subscription = self._subscribe(current)
        self._wait_data(current, subscription, tenant["before"])
        headers = dict(tenant["client"].other_params)
        if kind == "missing":
            headers = {}
        elif kind == "invalid":
            headers["Authorization"] = "Bearer invalid"
        else:
            assert kind in ("subscriptions-write", "channel-signing-read"), kind
            fixture = json.loads(
                subprocess.check_output(
                    [str(BUNDLE / "lsp-integration-driver"), "subscription-token"],
                    input=json.dumps(
                        {
                            "token": tenant["status"]["tenant_token"],
                            "private_key_file": str(BUNDLE / "biscuit-private-key"),
                            "missing_permission": kind,
                        }
                    ),
                    text=True,
                    timeout=10,
                )
            )
            headers["Authorization"] = "Bearer " + fixture["token"]
        # A successful constructor proves the upgrade itself was not the rejection.
        rejected = self._connect(headers=headers)
        if kind == "subscriptions-write":
            reply = rejected.request(
                "get_channel_signing_status", [{"channel_id": self.channel_id}]
            )
            assert reply.get("result") == tenant["before"], reply
        elif kind == "channel-signing-read":
            # Unknown cancellation proves write(subscriptions); topic read still fails.
            assert rejected.unsubscribe(f"unknown-{time.monotonic_ns()}") is False
            reply = rejected.request(
                "get_channel_signing_status", [{"channel_id": self.channel_id}]
            )
            assert "error" in reply and "result" not in reply, reply
        reply = rejected.request("subscribe", ["channel_signing"])
        assert "error" in reply and "result" not in reply, reply
        assert isinstance(reply["error"].get("code"), int), reply
        assert not rejected.frames(), rejected.frames()
        assert self._state(tenant) == tenant["before"]
        return current, subscription, rejected

    def _verify_rejected_subscription_recovery(self, current, subscription, rejected):
        tenant = self.tenant
        self._submit_saved(tenant)
        self._new_event(
            current, subscription, tenant, tenant["before"]["status"]["request_id"]
        )

        def no_unauthorized_event():
            self._assert_owner(current, subscription, tenant)
            assert not rejected.frames(), rejected.frames()

        self._observe(no_unauthorized_event)
        self._finish_channels()
        no_unauthorized_event()

    # TEST-MAP: LSP-SUBSCRIPTION-04
    def test_missing_token_does_not_disrupt_subscription(self):
        """1. 缺少 token 的 subscribe 返回错误且无事件。2. 原合法订阅收到新请求并完成通道。"""
        # 1. 独立环境验证 RPC 拒绝，不把 WS 握手失败当作通过。
        original = self._reject_subscription("missing")

        # 2. 继续推进 R2、观察无泄露并检查原通道终态。
        self._verify_rejected_subscription_recovery(*original)

    # TEST-MAP: LSP-SUBSCRIPTION-04
    def test_invalid_token_does_not_disrupt_subscription(self):
        """1. 无效 token 的 subscribe 返回错误且无事件。2. 原合法订阅收到新请求并完成通道。"""
        # 1. 独立环境验证 RPC 拒绝，不把 WS 握手失败当作通过。
        original = self._reject_subscription("invalid")

        # 2. 继续推进 R2、观察无泄露并检查原通道终态。
        self._verify_rejected_subscription_recovery(*original)

    # TEST-MAP: LSP-SUBSCRIPTION-04
    def test_missing_subscription_write_does_not_disrupt_subscription(self):
        """1. 有 topic 读权限但缺订阅写权限的有效凭证被拒。2. 原订阅收到新请求并完成通道。"""
        # 1. 先以成功的签名查询证明读权限与身份有效，再验证 subscribe 拒绝。
        original = self._reject_subscription("subscriptions-write")

        # 2. 继续推进 R2、观察无泄露并检查原通道终态。
        self._verify_rejected_subscription_recovery(*original)

    # TEST-MAP: LSP-SUBSCRIPTION-04
    def test_missing_channel_read_does_not_disrupt_subscription(self):
        """1. 有订阅写权限但缺 topic 读权限的有效凭证被拒。2. 原订阅收到新请求并完成通道。"""
        # 1. 未知 ID 取消返回 false 证明写权限，签名查询与 subscribe 均拒绝。
        original = self._reject_subscription("channel-signing-read")

        # 2. 继续推进 R2、观察无泄露并检查原通道终态。
        self._verify_rejected_subscription_recovery(*original)

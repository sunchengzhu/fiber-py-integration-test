"""PR #1623 / 04c2064: browser WebSocket credentials on real signing work."""

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from unittest.case import _Outcome

from websockets.exceptions import InvalidStatus

from test_cases.fiber.devnet.lsp._lsp_test import BUNDLE, stop_agent
from test_cases.fiber.devnet.lsp._subscription_observer import SubscriptionObserver
from test_cases.fiber.devnet.lsp.test_signing_subscriptions import SubscriptionTestBase

PROTOCOL = "fiber-rpc"
CREDENTIAL = "base64url.bearer.authorization.fiber."


class _BrowserSubscriptionBase(SubscriptionTestBase):
    """Bound real operations; keep old subscription helpers' defaults unchanged."""

    @contextmanager
    def _budget(self, seconds, until=float("inf")):
        now = time.monotonic()
        previous = signal.getitimer(signal.ITIMER_REAL)
        handler = signal.getsignal(signal.SIGALRM)
        depth = getattr(self, "_alarm_depth", 0)
        assert not previous[0] or depth, "another timer owns SIGALRM"
        old_due = now + previous[0] if previous[0] else float("inf")
        due = min(now + seconds, until, self.total_until, self.business_until, old_due)
        assert due > now, "browser subscription budget exhausted"

        def expired(*_args):
            raise AssertionError("browser subscription operation exceeded its deadline")

        self._alarm_depth = depth + 1
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, due - time.monotonic()))
        try:
            yield due
            assert time.monotonic() <= due, "late browser result is diagnostic only"
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, handler)
            self._alarm_depth = depth
            if old_due != float("inf") and old_due > time.monotonic():
                signal.setitimer(signal.ITIMER_REAL, old_due - time.monotonic())

    def _record(self, stage, **values):
        self.browser_evidence.append(
            {"stage": stage, "monotonic": time.monotonic(), **values}
        )

    def setup_method(self, method):
        started = time.monotonic()
        dual = len(self.tenant_labels) == 2
        self.total_until = started + (600 if dual else 540)
        self.preparation_until = started + (240 if dual else 180)
        self.business_until = float("inf")
        self.browser_evidence = []
        self._record(
            "prepare",
            total_until=self.total_until,
            preparation_until=self.preparation_until,
        )
        try:
            with self._budget(240, self.preparation_until):
                super().setup_method(method)
        except BaseException:
            self.doCleanups()
            raise

    def setUp(self):
        with self._budget(240, self.preparation_until):
            super().setUp()
            for tenant in self.tenants:
                self._window(tenant, 360)
                self._record(
                    "frozen",
                    tenant=tenant["label"],
                    request=tenant["before"],
                    submission=tenant["gate"].submission,
                    funding=tenant["funding_tx_hash"],
                )
        self.business_until = min(time.monotonic() + 300, self.total_until - 30)
        self._record("business_start", until=self.business_until)

    def doCleanups(self):
        self.business_until = float("inf")
        if not hasattr(self, "cleanup_until"):
            self.cleanup_until = min(time.monotonic() + 30, self.total_until)
        self._save_browser_evidence()
        outcome = self._outcome or _Outcome()
        # unittest catches cleanup exceptions. Arm the same remaining deadline
        # separately for each callback, so it cannot swallow a one-shot alarm
        # and then run the remaining callbacks without any timer.
        while self._cleanups:
            if time.monotonic() >= self.cleanup_until:
                self._record(
                    "cleanup_deadline",
                    remaining=[item[0].__name__ for item in self._cleanups],
                )
                with outcome.testPartExecutor(self):
                    raise AssertionError(
                        "browser cleanup deadline exhausted; resources may remain"
                    )
                break
            function, args, kwargs = self._cleanups.pop()
            with outcome.testPartExecutor(self):
                with self._budget(30, self.cleanup_until):
                    self._callCleanup(function, *args, **kwargs)
        return outcome.success

    def _save_browser_evidence(self):
        root = os.environ.get("LSP_RUN_ARTIFACTS")
        if not root:
            return
        destination = Path(root)
        destination.mkdir(parents=True, exist_ok=True)
        observations = []
        for observer in getattr(self, "observers", []):
            with observer.lock:
                observations.append(
                    {
                        "messages": list(observer.messages),
                        "errors": list(observer.errors),
                    }
                )
        (destination / f"{self._testMethodName}.browser.json").write_text(
            json.dumps(
                {"stages": self.browser_evidence, "observers": observations}, indent=2
            )
            + "\n"
        )

    def teardown_method(self, method):
        self.business_until = float("inf")
        if not hasattr(self, "cleanup_until"):
            self.cleanup_until = min(time.monotonic() + 30, self.total_until)
        # Persist handshake/RPC evidence before copying potentially large node dirs.
        self._save_browser_evidence()
        with self._budget(30, self.cleanup_until):
            super().teardown_method(method)

    def _rpc(self, client, method, params):
        with self._budget(10):
            return client.call(method, params)

    def _credential(self, permission):
        with self._budget(10) as due:
            fixture = json.loads(
                subprocess.check_output(
                    [str(BUNDLE / "lsp-integration-driver"), "subscription-token"],
                    input=json.dumps(
                        {
                            "token": self.tenant["status"]["tenant_token"],
                            "private_key_file": str(BUNDLE / "biscuit-private-key"),
                            "missing_permission": permission,
                        }
                    ),
                    text=True,
                    timeout=max(0.001, due - time.monotonic()),
                )
            )
        return fixture["token"]

    def _connect_browser(self, tenant=None, *, token=None, bearer=False):
        tenant = tenant or self.tenant
        token = token if token is not None else tenant["status"]["tenant_token"]
        protocols = None if bearer else [PROTOCOL, CREDENTIAL + token.rstrip("=")]
        headers = {"Authorization": "Bearer " + token} if bearer else {}
        with self._budget(10) as due:
            observer = SubscriptionObserver(
                self.ws_url,
                headers,
                subprotocols=protocols,
                open_timeout=max(0.001, due - time.monotonic()),
            )
        self.observers.append(observer)
        self.addCleanup(observer.close)
        response = observer.client.response
        self._record(
            "handshake",
            tenant=tenant["label"],
            bearer=bearer,
            request_headers=list(observer.client.request.headers.raw_items()),
            status=response.status_code,
            headers=list(response.headers.raw_items()),
        )
        assert response.status_code == 101, response
        negotiated = response.headers.get_all("Sec-WebSocket-Protocol")
        if bearer:
            assert observer.client.subprotocol is None and not negotiated, negotiated
        else:
            assert observer.client.subprotocol == PROTOCOL and negotiated == [
                PROTOCOL
            ], negotiated
            assert CREDENTIAL not in str(response.headers) and token not in str(
                response.headers
            )
        return observer

    def _subscribe_browser(self, observer, tenant=None):
        with self._budget(10):
            identity = observer.subscribe()
        assert type(identity) in (str, int), identity
        return observer, identity, tenant or self.tenant

    def _initial(self, bindings):
        with self._budget(60) as due:
            for observer, identity, tenant in bindings:
                expected = {"type": "channel_signing", "data": tenant["before"]}
                assert (
                    observer.wait_event(
                        identity,
                        lambda event: event == expected,
                        timeout=max(0.001, due - time.monotonic()),
                    )
                    == expected
                )
                assert (
                    self._rpc(
                        tenant["client"],
                        "get_channel_signing_status",
                        [{"channel_id": tenant["channel_id"]}],
                    )
                    == tenant["before"]
                )
                assert not tenant["gate"].forwarded
        self._owners(bindings)

    def _owners(self, bindings, rejected=()):
        for observer, identity, tenant in bindings:
            assert not observer.ended.is_set() and not observer.errors
            for event in self._events(observer, identity):
                assert event["type"] == "channel_signing", event
                assert event["data"]["channel_id"] == tenant["channel_id"], event
                if event["data"]["status"]["type"] == "SignatureRequired":
                    for other in self.tenants:
                        if other is not tenant:
                            assert (
                                event["data"]["status"]["request_id"]
                                not in other["gate"].submissions
                            ), event
        for observer in rejected:
            assert not observer.errors and not observer.frames(), observer.frames()

    def _observe_browser(self, bindings, rejected=()):
        with self._budget(6):
            end = time.monotonic() + 5
            while time.monotonic() < end:
                self._owners(bindings, rejected)
                time.sleep(0.1)
            self._owners(bindings, rejected)

    def _advance(self, bindings, rejected=()):
        # One deadline for every connection and both tenants; query only after delivery.
        with self._budget(60) as due:
            for tenant in self.tenants:
                with self._budget(10):
                    self._window(tenant, 180)
                result = self._rpc(
                    tenant["client"],
                    "submit_channel_signature",
                    [tenant["gate"].submission],
                )
                assert result == {"type": "Applied"}, result
                current = None
                for observer, identity, owner in bindings:
                    if owner is not tenant:
                        continue
                    old_id = tenant["before"]["status"]["request_id"]
                    event = observer.wait_event(
                        identity,
                        lambda item: (
                            item.get("type") == "channel_signing"
                            and item["data"]["status"]["type"] == "SignatureRequired"
                            and item["data"]["status"]["request_id"] != old_id
                        ),
                        timeout=max(0.001, due - time.monotonic()),
                    )
                    assert event["data"]["channel_id"] == tenant["channel_id"], event
                    if current is not None:
                        assert current == event["data"], event
                    current = event["data"]
                assert current is not None
                assert (
                    self._rpc(
                        tenant["client"],
                        "get_channel_signing_status",
                        [{"channel_id": tenant["channel_id"]}],
                    )
                    == current
                )
                while current["status"]["request_id"] not in tenant["gate"].submissions:
                    assert time.monotonic() < due, "SDK did not save S2"
                    time.sleep(0.1)
                assert not tenant["gate"].forwarded
                self._record(
                    "next_request",
                    tenant=tenant["label"],
                    result=result,
                    request=current,
                    submission=tenant["gate"].submissions[
                        current["status"]["request_id"]
                    ],
                )
                self._owners(bindings, rejected)

    def _finish_browser(self, bindings, rejected=()):
        # All original channels share this deadline; no re-registration or new funding.
        with self._budget(120) as due:
            for tenant in self.tenants:
                with self._budget(10):
                    self._window(tenant, 180)
                stop_agent(tenant["agent"])
                tenant["subscription_proxy"].close_streams()
                tenant["gate"].release()
                tenant["agent"] = subprocess.Popen(
                    tenant["command"], stdout=tenant["log"], stderr=subprocess.STDOUT
                )
                self.addCleanup(stop_agent, tenant["agent"])
            while True:
                ready = True
                snapshots = []
                for tenant in self.tenants:
                    assert tenant["agent"].poll() is None and not tenant["gate"].errors
                    with self._budget(10):
                        local = self._channel(tenant["client"], tenant["channel_id"])
                        public = self._channel(self.fiber1.client, tenant["channel_id"])
                    status = self._rpc(
                        tenant["client"],
                        "get_channel_signing_status",
                        [{"channel_id": tenant["channel_id"]}],
                    )
                    ready &= (
                        local["state"]["state_name"]
                        == public["state"]["state_name"]
                        == "ChannelReady"
                        and status["status"]["type"] == "NoSignatureRequired"
                    )
                    snapshots.append((tenant, local, public))
                self._owners(bindings, rejected)
                if ready:
                    break
                assert time.monotonic() < due, "original channels did not finish"
                time.sleep(0.2)
            host_channels = self._rpc(self.fiber1.client, "list_channels", [{}])[
                "channels"
            ]
            assert len(host_channels) == len(self.tenants), host_channels
            assert {c["channel_id"] for c in host_channels} == {
                t["channel_id"] for t in self.tenants
            }
            for tenant, local, public in snapshots:
                assert (
                    len(self._rpc(tenant["client"], "list_channels", [{}])["channels"])
                    == 1
                )
                assert local["channel_outpoint"] == public["channel_outpoint"]
                point = bytes.fromhex(local["channel_outpoint"][2:])
                assert (
                    len(point) == 36
                    and "0x" + point[:32].hex() == tenant["funding_tx_hash"]
                )
                # The pinned channel protocol constructs its funding OutPoint
                # from the submitted funding transaction and output index zero.
                assert point[32:] == b"\x00" * 4, local["channel_outpoint"]
                assert not local["pending_tlcs"] and not public["pending_tlcs"]
                assert int(local["local_balance"], 16) == int(
                    public["remote_balance"], 16
                )
                assert int(local["remote_balance"], 16) == int(
                    public["local_balance"], 16
                )
                with self._budget(10):
                    funding = self.node.getClient().get_transaction(
                        tenant["funding_tx_hash"]
                    )
                assert funding["tx_status"]["status"] == "committed", funding
                self._record(
                    "ready",
                    tenant=tenant["label"],
                    local=local,
                    public=public,
                    funding_status=funding["tx_status"],
                )
        with self._budget(10):
            end = time.monotonic() + 5
            while time.monotonic() < end:
                for tenant, local, public in snapshots:
                    for client, before in (
                        (tenant["client"], local),
                        (self.fiber1.client, public),
                    ):
                        with self._budget(10):
                            after = self._channel(client, tenant["channel_id"])
                        for key in (
                            "state",
                            "channel_outpoint",
                            "local_balance",
                            "remote_balance",
                            "pending_tlcs",
                        ):
                            assert before[key] == after[key], (key, before, after)
                    assert (
                        self._rpc(
                            tenant["client"],
                            "get_channel_signing_status",
                            [{"channel_id": tenant["channel_id"]}],
                        )["status"]["type"]
                        == "NoSignatureRequired"
                    )
                self._owners(bindings, rejected)
                time.sleep(0.2)
        self._record("complete")

    def _handshake_rejected(self, kind):
        with self._budget(300):
            good = self._subscribe_browser(self._connect_browser())
            self._initial([good])
            token = self.tenant["status"]["tenant_token"]
            credential = CREDENTIAL + token
            protocols = [PROTOCOL, credential]
            headers = {}
            if kind == "missing-protocol":
                protocols = [credential]
            elif kind == "multiple":
                protocols.append(credential)
            elif kind == "conflict":
                headers["Authorization"] = "Bearer " + token
            elif kind == "empty":
                protocols = [PROTOCOL, CREDENTIAL]
            else:
                assert kind == "encoding"
                protocols = [PROTOCOL, CREDENTIAL + "!"]
            self._record(
                "invalid_handshake_input",
                kind=kind,
                protocols=protocols,
                headers=headers,
            )
            with self._budget(10):
                try:
                    unexpected = SubscriptionObserver(
                        self.ws_url, headers, subprotocols=protocols
                    )
                except InvalidStatus as error:
                    response = error.response
                    self._record(
                        "rejected_handshake",
                        status=response.status_code,
                        headers=list(response.headers.raw_items()),
                        body=bytes(response.body).hex(),
                    )
                    assert response.status_code == 400, response
                else:
                    self.observers.append(unexpected)
                    self.addCleanup(unexpected.close)
                    raise AssertionError(
                        "invalid browser credentials upgraded successfully"
                    )
            self._observe_browser([good])
            self._advance([good])
            self._observe_browser([good])
            self._finish_browser([good])

    def _rpc_rejected(self, kind):
        with self._budget(300):
            good = self._subscribe_browser(self._connect_browser())
            self._initial([good])
            token = (
                base64.urlsafe_b64encode(b"not a Biscuit").decode().rstrip("=")
                if kind == "invalid"
                else self._credential(kind).rstrip("=")
            )
            rejected = self._connect_browser(token=token)
            self._record("rpc_rejection_input", kind=kind)
            if kind == "subscriptions-write":
                with self._budget(10):
                    reply = rejected.request(
                        "get_channel_signing_status", [{"channel_id": self.channel_id}]
                    )
                assert reply.get("result") == self.tenant["before"], reply
            elif kind == "channel-signing-read":
                # This connection has no subscriptions, so this ID cannot be its own.
                with self._budget(10):
                    assert (
                        rejected.unsubscribe("unknown-browser-permission-check")
                        is False
                    )
                with self._budget(10):
                    reply = rejected.request(
                        "get_channel_signing_status", [{"channel_id": self.channel_id}]
                    )
                assert "error" in reply and "result" not in reply, reply
            with self._budget(10):
                reply = rejected.request("subscribe", ["channel_signing"])
            assert "error" in reply and "result" not in reply, reply
            assert type(reply["error"]["code"]) is int, reply
            assert not rejected.frames()
            assert (
                self._rpc(
                    self.client,
                    "get_channel_signing_status",
                    [{"channel_id": self.channel_id}],
                )
                == self.tenant["before"]
            )
            self._observe_browser([good], [rejected])
            self._advance([good], [rejected])
            self._observe_browser([good], [rejected])
            self._finish_browser([good], [rejected])


class TestBrowserSigningSubscriptions(_BrowserSubscriptionBase):
    # TEST-MAP: LSP-SUBSCRIPTION-14
    def test_browser_registration_token_receives_real_work(self):
        """1. 原始注册凭证握手并收到R1。2. 原订阅先收到R2。3. 原SDK完成通道。"""
        with self._budget(300):
            # 1. 原文未填充，不进行第二次编码；核对真实握手与完整初始内容。
            token = self.tenant["status"]["tenant_token"]
            assert "=" not in token
            decoded = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            assert base64.urlsafe_b64encode(decoded).decode().rstrip("=") == token
            binding = self._subscribe_browser(self._connect_browser(token=token))
            self._initial([binding])

            # 2. 不重连、不先查询，应用真实S1后接收新R2。
            self._advance([binding])

            # 3. 原身份和存储完成原通道并检查资金及稳定终态。
            self._finish_browser([binding])

    # TEST-MAP: LSP-SUBSCRIPTION-15
    def test_browser_padded_token_and_bearer_inputs_are_compatible(self):
        """1. 准备实际需要填充的同一凭证。2. 三入口收取相同R1/R2。3. 完成原通道。"""
        with self._budget(300):
            # 1. 只做编码兼容；三个输入必须对应相同签名token字节。
            original = self.tenant["status"]["tenant_token"]
            padded = original + "=" * (-len(original) % 4)
            if not padded.endswith("="):
                padded = self._credential("none")
            plain = padded.rstrip("=")
            assert padded != plain and len(padded) - len(plain) in (1, 2)
            raw = base64.b64decode(padded, altchars=b"-_", validate=True)
            assert base64.urlsafe_b64encode(raw).decode() == padded
            assert (
                base64.b64decode(
                    plain + "=" * (-len(plain) % 4), altchars=b"-_", validate=True
                )
                == raw
            )
            self._record("encoding_inputs", padded=padded, plain=plain)

            # 2. 三个独立连接共享初始及实时阶段截止，同一S1仅应用一次。
            bindings = [
                self._subscribe_browser(self._connect_browser(token=plain)),
                self._subscribe_browser(
                    self._connect_browser(token=padded, bearer=True)
                ),
                self._subscribe_browser(
                    self._connect_browser(token=plain, bearer=True)
                ),
            ]
            self._initial(bindings)
            self._advance(bindings)

            # 3. 三条订阅不增加签名推进，恢复原SDK完成原通道。
            self._finish_browser(bindings)

    # TEST-MAP: LSP-SUBSCRIPTION-16
    def test_browser_missing_protocol_rejected_by_server(self):
        """1. 冻结合法订阅。缺协议握手返回400。原订阅继续且通道完成。"""
        # 1. 独立输入执行完整握手拒绝、真实R2和通道终态断言。
        self._handshake_rejected("missing-protocol")

    # TEST-MAP: LSP-SUBSCRIPTION-16
    def test_browser_multiple_credentials_rejected_by_server(self):
        """1. 冻结合法订阅。重复凭证握手返回400。原订阅继续且通道完成。"""
        # 1. 不通过客户端本地异常代替真实服务器拒绝。
        self._handshake_rejected("multiple")

    # TEST-MAP: LSP-SUBSCRIPTION-16
    def test_browser_conflicting_credentials_rejected_by_server(self):
        """1. 冻结合法订阅。双入口凭证握手返回400。原订阅继续且通道完成。"""
        # 1. 即便header和子协议使用同一token也要求服务器拒绝。
        self._handshake_rejected("conflict")

    # TEST-MAP: LSP-SUBSCRIPTION-16
    def test_browser_empty_credential_rejected_by_server(self):
        """1. 冻结合法订阅。空凭证握手返回400。原订阅继续且通道完成。"""
        # 1. HTTP合法的空后缀必须实际到达服务端。
        self._handshake_rejected("empty")

    # TEST-MAP: LSP-SUBSCRIPTION-16
    def test_browser_invalid_encoding_rejected_by_server(self):
        """1. 冻结合法订阅。非法编码握手返回400。原订阅继续且通道完成。"""
        # 1. 使用协议合法但base64url非法的感叹号后缀。
        self._handshake_rejected("encoding")

    # TEST-MAP: LSP-SUBSCRIPTION-17
    def test_browser_invalid_biscuit_rejected_after_upgrade(self):
        """1. 保留合法订阅并以无效Biscuit取得101。订阅RPC拒绝。原通道完成。"""
        # 1. 区分合法编码和真实认证；必须在升级之后获得RPC拒绝。
        self._rpc_rejected("invalid")

    # TEST-MAP: LSP-SUBSCRIPTION-18
    def test_browser_missing_write_rejected_after_upgrade(self):
        """1. 缺写凭证取得101。查询可用而订阅拒绝。原订阅继续且通道完成。"""
        # 1. 独立执行缺写输入，并证明互补读取权限有效。
        self._rpc_rejected("subscriptions-write")

    # TEST-MAP: LSP-SUBSCRIPTION-18
    def test_browser_missing_read_rejected_after_upgrade(self):
        """1. 缺读凭证取得101。取消可用而读取及订阅拒绝。原通道完成。"""
        # 1. 独立执行缺读输入，并证明互补订阅写权限有效。
        self._rpc_rejected("channel-signing-read")


class TestBrowserSubscriptionIsolation(_BrowserSubscriptionBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-SUBSCRIPTION-19
    def test_browser_initial_and_live_work_remains_tenant_scoped(self):
        """1. A/B浏览器订阅各自R1。2. 依次产生各自R2并检查隔离。3. 两原通道完成。"""
        with self._budget(300):
            # 1. 两方都收到真实初始工作，5秒窗口持续检查归属。
            bindings = [
                self._subscribe_browser(self._connect_browser(tenant), tenant)
                for tenant in self.tenants
            ]
            self._initial(bindings)
            self._observe_browser(bindings)

            # 2. 两方都收到后续正向R2后继续观察，排除空连接静默假通过。
            self._advance(bindings)
            self._observe_browser(bindings)

            # 3. 原SDK和注资各自保留，统一截止内完成两条通道。
            self._finish_browser(bindings)

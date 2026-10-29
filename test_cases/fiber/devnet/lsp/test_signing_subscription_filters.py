"""PR #1623: real channel-signing filters on the explicitly selected revision."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from unittest.case import _Outcome

import framework.config as framework_config
from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._subscription_observer import SubscriptionObserver
from test_cases.fiber.devnet.lsp.test_signing_subscriptions import SubscriptionTestBase

ROUND_UNTIL = float(os.environ.get("LSP_FILTER_ROUND_UNTIL", time.monotonic() + 1800))
BATCH_UNTIL = float(os.environ.get("LSP_FILTER_BATCH_UNTIL", "inf"))
TOPIC = "channel_signing"


class _FilterSubscriptionBase(SubscriptionTestBase):
    """Local budgets and evidence; leave the existing suites' helpers unchanged."""

    @classmethod
    def setup_class(cls):
        artifacts = os.environ.get("LSP_RUN_ARTIFACTS")
        run = (
            f"{Path(artifacts).parent.name}-{Path(artifacts).name}"
            if artifacts
            else f"manual-{os.getpid()}"
        )
        cls.tmp_path_name = f"tmp/lsp-filters-{run}/{cls.__name__}"
        assert time.monotonic() < min(ROUND_UNTIL, BATCH_UNTIL - 300) - 30
        super().setup_class()

    @classmethod
    def teardown_class(cls):
        # Keep the class chain even after archive failure; do not call node.clean().
        try:
            if "node" in cls.__dict__:
                cls.node.stop()
        finally:
            if hasattr(cls, "_original_tmp_path_name"):
                framework_config.TMP_PATH = cls._original_tmp_path_name

    @contextmanager
    def _budget(self, seconds, until=float("inf")):
        now = time.monotonic()
        previous = signal.getitimer(signal.ITIMER_REAL)
        handler = signal.getsignal(signal.SIGALRM)
        depth = getattr(self, "_alarm_depth", 0)
        assert not previous[0] or depth, "another timer owns SIGALRM"
        old_due = now + previous[0] if previous[0] else float("inf")
        due = min(
            now + seconds,
            until,
            self.total_until,
            self.work_until,
            self.business_until,
            old_due,
        )
        assert due > now, "filter budget exhausted; later cases must not run"

        def expired(*_args):
            raise AssertionError("filter operation exceeded its absolute deadline")

        self._alarm_depth = depth + 1
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, due - time.monotonic()))
        try:
            yield due
            assert time.monotonic() <= due, "late result is diagnostic only"
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, handler)
            self._alarm_depth = depth
            if old_due != float("inf") and old_due > time.monotonic():
                signal.setitimer(signal.ITIMER_REAL, old_due - time.monotonic())

    def _record(self, stage, **values):
        self.evidence.append({"stage": stage, "monotonic": time.monotonic(), **values})

    def setup_method(self, method):
        started = time.monotonic()
        dual = len(self.tenant_labels) == 2
        self.total_until = min(
            started + (690 if dual else 630), ROUND_UNTIL, BATCH_UNTIL - 300
        )
        self.work_until = self.total_until - 30
        self.preparation_until = min(started + (240 if dual else 180), self.work_until)
        self.business_until = float("inf")
        self.evidence = []
        self.cleanup_failed = False
        self.fibers = []
        self.tenants = []
        self._method_tmp_before = framework_config.TMP_PATH
        framework_config.TMP_PATH = f"{self.tmp_path_name}/{method.__name__}"
        self.bindings = []
        self.current = {}
        self.observers = []
        self.artifacts = Path(
            os.environ.get(
                "LSP_RUN_ARTIFACTS",
                f"{get_project_root()}/report/lsp-filters-{os.getpid()}",
            )
        )
        self._record(
            "prepare",
            total_until=self.total_until,
            preparation_until=self.preparation_until,
            round_until=ROUND_UNTIL,
            batch_until=BATCH_UNTIL,
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
                self._window(tenant, 720)
                self._record(
                    "frozen",
                    tenant=tenant["label"],
                    request=tenant["before"],
                    submission=tenant["gate"].submission,
                    funding=tenant["funding_tx_hash"],
                )
        self.business_until = min(time.monotonic() + 420, self.work_until)
        self._record("business_start", until=self.business_until)

    def _save_evidence(self):
        self.artifacts.mkdir(parents=True, exist_ok=True)
        observations = []
        for observer in self.observers:
            with observer.lock:
                observations.append(
                    {
                        "messages": list(observer.messages),
                        "errors": list(observer.errors),
                        "ended": observer.ended.is_set(),
                    }
                )
        bindings = [
            {
                "observer": self.observers.index(b["observer"]),
                "subscription": b["id"],
                "tenant": b["tenant"]["label"],
                "empty": b["empty"],
                "cancelled": b["cancelled"],
            }
            for b in self.bindings
        ]
        target = self.artifacts / f"{self._testMethodName}.filters.json"
        target.write_text(
            json.dumps(
                {
                    "stages": self.evidence,
                    "bindings": bindings,
                    "observers": observations,
                },
                indent=2,
            )
            + "\n"
        )

    def _begin_cleanup(self):
        self.business_until = float("inf")
        self.work_until = self.total_until
        if not hasattr(self, "cleanup_until"):
            self.cleanup_until = min(time.monotonic() + 30, self.total_until)

    def _emergency_stop(self):
        # Never enter an expired alarm before signalling the exact owned children.
        processes = [t.get("agent") for t in getattr(self, "tenants", [])]
        processes += [getattr(f, "process", None) for f in self.fibers]
        for process in processes:
            if process is not None and process.poll() is None:
                self._record("emergency_kill", pid=process.pid)
                process.kill()
        for process in processes:
            remaining = self.cleanup_until - time.monotonic()
            if process is not None and remaining > 0:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    self.cleanup_failed = True
        alive = [p.pid for p in processes if p is not None and p.poll() is None]
        assert not alive, f"owned child processes did not stop: {alive}"

    def doCleanups(self):
        self._begin_cleanup()
        outcome = self._outcome or _Outcome()
        try:
            with outcome.testPartExecutor(self):
                try:
                    with self._budget(30, self.cleanup_until - 2):
                        self._save_evidence()
                except BaseException:
                    self.cleanup_failed = True
                    raise
            while self._cleanups:
                if time.monotonic() >= self.cleanup_until - 2:
                    self.cleanup_failed = True
                    self._record(
                        "cleanup_deadline",
                        remaining=[x[0].__name__ for x in self._cleanups],
                    )
                    with outcome.testPartExecutor(self):
                        raise AssertionError(
                            "cleanup budget exhausted; original directories retained"
                        )
                    break
                function, args, kwargs = self._cleanups.pop()
                with outcome.testPartExecutor(self):
                    try:
                        with self._budget(30, self.cleanup_until - 2):
                            self._callCleanup(function, *args, **kwargs)
                    except BaseException:
                        self.cleanup_failed = True
                        raise
        finally:
            if self.cleanup_failed:
                self._emergency_stop()
        return outcome.success

    def teardown_method(self, method):
        self._begin_cleanup()
        try:
            with self._budget(30, self.cleanup_until - 2):
                self._save_evidence()
                previous = os.environ.get("LSP_RUN_ARTIFACTS")
                os.environ["LSP_RUN_ARTIFACTS"] = str(self.artifacts)
                try:
                    self._archive_run()
                finally:
                    if previous is None:
                        os.environ.pop("LSP_RUN_ARTIFACTS", None)
                    else:
                        os.environ["LSP_RUN_ARTIFACTS"] = previous
        except BaseException:
            self.cleanup_failed = True
            raise
        finally:
            self._emergency_stop()
            framework_config.TMP_PATH = self._method_tmp_before
            # Every method has its own directory. Keep originals even after a good copy.
            print("Original filter data retained:", [f.tmp_path for f in self.fibers])

    def _rpc(self, client, method, params):
        with self._budget(10):
            return client.call(method, params)

    def _connect_filter(self, tenant=None):
        tenant = tenant or self.tenant
        with self._budget(10) as due:
            observer = SubscriptionObserver(
                self.ws_url,
                tenant["client"].other_params,
                open_timeout=max(0.001, due - time.monotonic()),
            )
        self.observers.append(observer)
        self.addCleanup(observer.close)
        self._record(
            "handshake",
            observer=self.observers.index(observer),
            tenant=tenant["label"],
            status=observer.client.response.status_code,
        )
        assert observer.client.response.status_code == 101
        return observer

    def _request(self, observer, params, method="subscribe"):
        identity = observer.next_id + 1
        self._record(
            "request",
            observer=self.observers.index(observer),
            request_id=identity,
            method=method,
            params=params,
        )
        with self._budget(10) as due:
            response = observer.request(
                method, params, timeout=max(0.001, due - time.monotonic())
            )
        self._record(
            "response", observer=self.observers.index(observer), response=response
        )
        assert type(response.get("id")) is int and response["id"] == identity, response
        assert response.get("jsonrpc") == "2.0", response
        return response

    def _subscribe_filter(
        self, observer, params, tenant=None, *, empty=False, unique=False
    ):
        response = self._request(observer, params)
        assert "error" not in response and type(response.get("result")) in (
            str,
            int,
        ), response
        identity = response["result"]
        assert not any(
            b["observer"] is observer
            and type(b["id"]) is type(identity)
            and b["id"] == identity
            for b in self.bindings
        ), response
        self.bindings.append(
            {
                "observer": observer,
                "id": identity,
                "tenant": tenant or self.tenant,
                "empty": empty,
                "unique": unique,
                "cancelled": False,
            }
        )
        return identity

    def _reject_filter(self, observer, params, code):
        response = self._request(observer, params)
        assert "result" not in response and "error" in response, response
        assert type(response["error"].get("code")) is int, response
        assert response["error"]["code"] == code, response
        self._check_frames("initial")

    def _check_frames(self, phase):
        for observer in self.observers:
            assert not observer.errors and not observer.ended.is_set(), observer.errors
            for _, identity, event in observer.frames():
                bindings = [
                    b
                    for b in self.bindings
                    if b["observer"] is observer
                    and type(b["id"]) is type(identity)
                    and b["id"] == identity
                ]
                assert len(bindings) == 1, (
                    "orphan subscription notification",
                    identity,
                    event,
                )
                binding = bindings[0]
                assert not binding["empty"], ("empty filter received work", event)
                tenant = binding["tenant"]
                assert event["type"] == TOPIC, event
                assert event["data"]["channel_id"] == tenant["channel_id"], event
                if phase == "initial":
                    assert event["data"] == tenant["before"], event
                elif (
                    phase == "live"
                    and event["data"]["status"]["type"] == "SignatureRequired"
                ):
                    allowed = [tenant["before"], self.current.get(tenant["label"])]
                    assert event["data"] in allowed, event
                for other in self.tenants:
                    if other is not tenant:
                        assert event["data"] != other["before"], event
                        assert event["data"] != self.current.get(other["label"]), event
                        if event["data"]["status"]["type"] == "SignatureRequired":
                            assert (
                                event["data"]["status"]["request_id"]
                                not in other["gate"].submissions
                            ), event
        for binding in self.bindings:
            if not binding["unique"] or phase == "finish":
                continue
            expected = [binding["tenant"]["before"]]
            if phase == "live":
                expected.append(self.current[binding["tenant"]["label"]])
            for work in expected:
                events = self._events(binding["observer"], binding["id"])
                assert (
                    sum(e == {"type": TOPIC, "data": work} for e in events) == 1
                ), events

    def _initial(self):
        with self._budget(60) as due:
            for binding in self.bindings:
                if binding["empty"]:
                    continue
                expected = {"type": TOPIC, "data": binding["tenant"]["before"]}
                assert (
                    binding["observer"].wait_event(
                        binding["id"],
                        lambda e: e == expected,
                        timeout=max(0.001, due - time.monotonic()),
                    )
                    == expected
                )
        self._check_frames("initial")

    def _observe_filters(self, phase):
        with self._budget(6):
            end = time.monotonic() + 5
            while time.monotonic() < end:
                self._check_frames(phase)
                time.sleep(0.1)
            self._check_frames(phase)
        if phase == "initial":
            for tenant in self.tenants:
                assert (
                    self._rpc(
                        tenant["client"],
                        "get_channel_signing_status",
                        [{"channel_id": tenant["channel_id"]}],
                    )
                    == tenant["before"]
                )
                assert not tenant["gate"].forwarded

    def _advance_filters(self):
        with self._budget(60) as due:
            for tenant in self.tenants:
                with self._budget(10):
                    self._window(tenant, 480)
                    self._submit_saved(tenant)
                current = None
                for binding in self.bindings:
                    if binding["tenant"] is not tenant or binding["empty"]:
                        continue
                    event = binding["observer"].wait_event(
                        binding["id"],
                        lambda e: e.get("type") == TOPIC
                        and e["data"]["status"]["type"] == "SignatureRequired"
                        and e["data"]["status"]["request_id"]
                        != tenant["before"]["status"]["request_id"],
                        timeout=max(0.001, due - time.monotonic()),
                    )
                    assert event["data"]["channel_id"] == tenant["channel_id"], event
                    assert current is None or event["data"] == current, event
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
                request_id = current["status"]["request_id"]
                while request_id not in tenant["gate"].submissions:
                    assert time.monotonic() < due, "SDK did not save S2"
                    time.sleep(0.1)
                assert not tenant["gate"].forwarded
                self.current[tenant["label"]] = current
                self._record(
                    "next_request",
                    tenant=tenant["label"],
                    request=current,
                    submission=tenant["gate"].submissions[request_id],
                )
        self._observe_filters("live")

    def _cancel_empty(self):
        for binding in self.bindings:
            if binding["empty"]:
                response = self._request(
                    binding["observer"], [binding["id"]], "unsubscribe"
                )
                assert (
                    "error" not in response and response.get("result") is True
                ), response
                binding["cancelled"] = True
        self._check_frames("live")

    def _finish_filters(self):
        with self._budget(120):
            self._finish_channels()  # Preserves the existing 300-second window guard.
            host = self._rpc(self.fiber1.client, "list_channels", [{}])["channels"]
            assert {c["channel_id"] for c in host} == {
                t["channel_id"] for t in self.tenants
            }
            assert len(host) == len(self.tenants), host
            stable = []
            for tenant in self.tenants:
                with self._budget(10):
                    local = self._channel(tenant["client"], tenant["channel_id"])
                    public = self._channel(self.fiber1.client, tenant["channel_id"])
                point = bytes.fromhex(local["channel_outpoint"][2:])
                assert len(point) == 36 and point[32:] == b"\x00" * 4, local
                assert "0x" + point[:32].hex() == tenant["funding_tx_hash"]
                assert local["channel_outpoint"] == public["channel_outpoint"]
                assert not local["pending_tlcs"] and not public["pending_tlcs"]
                assert int(local["local_balance"], 16) == int(
                    public["remote_balance"], 16
                )
                assert int(local["remote_balance"], 16) == int(
                    public["local_balance"], 16
                )
                stable.extend(
                    [
                        (tenant["client"], tenant, local),
                        (self.fiber1.client, tenant, public),
                    ]
                )
                self._record(
                    "ready", tenant=tenant["label"], local=local, public=public
                )
        with self._budget(10):
            end = time.monotonic() + 5
            while time.monotonic() < end:
                for client, tenant, before in stable:
                    with self._budget(10):
                        after = self._channel(client, tenant["channel_id"])
                    for key in (
                        "state",
                        "channel_outpoint",
                        "local_balance",
                        "remote_balance",
                        "pending_tlcs",
                    ):
                        assert after[key] == before[key], (key, before, after)
                    assert (
                        self._rpc(
                            tenant["client"],
                            "get_channel_signing_status",
                            [{"channel_id": tenant["channel_id"]}],
                        )["status"]["type"]
                        == "NoSignatureRequired"
                    )
                self._check_frames("finish")
                time.sleep(0.2)
        self._record("complete")

    def _reject_group(self, params, code):
        observer = self._connect_filter()
        with self._budget(40):
            self._subscribe_filter(observer, [TOPIC])
            self._initial()
            for item in params:
                self._reject_filter(observer, item, code)
        self._observe_filters("initial")
        self._advance_filters()
        self._finish_filters()


class TestSigningSubscriptionFilters(_FilterSubscriptionBase):
    # TEST-MAP: LSP-SUBSCRIPTION-20
    def test_default_option_forms(self):
        """1. 四种默认参数订阅。2. 核对R1并推进真实R2。3. 完成原通道。"""
        # 1. 省略、null、空对象和字段null保留为不同线级输入。
        observer = self._connect_filter()
        with self._budget(40):
            for params in (
                [TOPIC],
                [TOPIC, None],
                [TOPIC, {}],
                [TOPIC, {"channel_ids": None}],
            ):
                self._subscribe_filter(observer, params)
        # 2. 四个订阅共享真实签名推进及观察窗口。
        self._initial()
        self._observe_filters("initial")
        self._advance_filters()
        # 3. 原注资和双方就绪状态保持。
        self._finish_filters()

    # TEST-MAP: LSP-SUBSCRIPTION-21
    def test_explicit_and_duplicate_channel_ids(self):
        """1. 显式与重复ID订阅。2. 两个冻结窗口检查各一份工作。3. 完成原通道。"""
        # 1. 重复ID不在客户端预先去重。
        observer = self._connect_filter()
        with self._budget(40):
            for ids in ([self.channel_id], [self.channel_id, self.channel_id]):
                self._subscribe_filter(
                    observer, [TOPIC, {"channel_ids": ids}], unique=True
                )
        # 2. 在同一订阅检查完整R1和真实R2各一份。
        self._initial()
        self._observe_filters("initial")
        self._advance_filters()
        # 3. 恢复真实SDK签名并核对资金终态。
        self._finish_filters()

    # TEST-MAP: LSP-SUBSCRIPTION-22
    def test_empty_channel_filter(self):
        """1. 建立默认和空过滤订阅。2. 推进后空订阅仍无事件并可取消。3. 完成原通道。"""
        # 1. 同连接正向对照和空集合分别登记ID。
        observer = self._connect_filter()
        with self._budget(40):
            self._subscribe_filter(observer, [TOPIC])
            self._subscribe_filter(observer, [TOPIC, {"channel_ids": []}], empty=True)
        # 2. 检查初始和实时窗口，取消证明空订阅自身有效。
        self._initial()
        self._observe_filters("initial")
        self._advance_filters()
        self._cancel_empty()
        # 3. 原通道继续完成。
        self._finish_filters()

    # TEST-MAP: LSP-SUBSCRIPTION-23
    def test_invalid_topic_and_options_field(self):
        """1. 准备四个topic/字段错误。2. 逐项拒绝后原订阅收到R2并完成通道。"""
        # 1. 其他字段保持有效，每个错误单独发送。
        params = [["not_a_topic"], [0], [TOPIC, {"tenant_id": "B"}], [TOPIC, 0]]
        # 2. helper逐项核对RPC，再以一次真实R2和资金终态作组内对照。
        self._reject_group(params, -32602)

    # TEST-MAP: LSP-SUBSCRIPTION-23
    def test_invalid_parameter_types(self):
        """1. 准备四个类型错误。2. 逐项拒绝后原订阅收到R2并完成通道。"""
        # 1. 字段null兼容不混入这里，数组元素0确为非法。
        params = [
            [TOPIC, True],
            [TOPIC, "invalid"],
            [TOPIC, {"channel_ids": {}}],
            [TOPIC, {"channel_ids": [0]}],
        ]
        # 2. 服务端错误、全连接归属及原通道终态都必须满足。
        self._reject_group(params, -32602)

    # TEST-MAP: LSP-SUBSCRIPTION-23
    def test_invalid_hash_lengths_and_null_element(self):
        """1. 准备null元素及短长奇数Hash。2. 逐项拒绝后推进R2并完成通道。"""
        # 1. 31/33字节和奇数十六进制分别保留原始输入。
        values = [None, "0x" + "00" * 31, "0x" + "00" * 33, "0x0"]
        # 2. 不把Python校验异常当服务端拒绝。
        self._reject_group(
            [[TOPIC, {"channel_ids": [value]}] for value in values], -32602
        )

    # TEST-MAP: LSP-SUBSCRIPTION-23
    def test_invalid_hex_and_options_sequences(self):
        """1. 准备非法字符及三种错误数组。2. 逐项拒绝后推进R2并完成通道。"""
        # 1. options数组与channel_ids数组是不同层次。
        params = [
            [TOPIC, {"channel_ids": ["0x" + "gg" * 32]}],
            [TOPIC, []],
            [TOPIC, [None, None]],
            [TOPIC, [self.channel_id]],
        ]
        # 2. 缺字段、额外字段和字段类型错误都应为解析拒绝。
        self._reject_group(params, -32602)

    # TEST-MAP: LSP-SUBSCRIPTION-24
    def test_unknown_channel_and_mixed_orders(self):
        """1. 确认未知Hash前提。2. 单个及两种混合顺序整体拒绝并恢复原通道。"""
        # 1. 未知ID格式正确，与所有现有host/租户通道区分。
        unknown = "0x" + "ff" * 32
        clients = [self.fiber1.client] + [t["client"] for t in self.tenants]
        for client in clients:
            channels = self._rpc(client, "list_channels", [{}])["channels"]
            assert unknown not in {c["channel_id"] for c in channels}
        try:
            self._rpc(
                self.client, "get_channel_signing_status", [{"channel_id": unknown}]
            )
        except Exception as error:
            assert (
                "not found" in str(error).lower() and unknown[2:] in str(error).lower()
            ), error
            self._record("unknown_channel", channel_id=unknown, error=str(error))
        else:
            raise AssertionError("unknown channel unexpectedly exists")
        # 2. 不允许前置合法项形成部分订阅。
        ids = [[unknown], [self.channel_id, unknown], [unknown, self.channel_id]]
        self._reject_group([[TOPIC, {"channel_ids": value}] for value in ids], -32001)

    # TEST-MAP: LSP-SUBSCRIPTION-26
    def test_256_repeated_channel_ids(self):
        """1. 发送256项原数组。2. 检查R1/R2工作未因重复增发。3. 完成原通道。"""
        # 1. 长度边界使用同一个真实通道ID。
        observer = self._connect_filter()
        ids = [self.channel_id] * 256
        assert len(ids) == 256
        with self._budget(40):
            self._subscribe_filter(observer, [TOPIC, {"channel_ids": ids}], unique=True)
        # 2. 只证明数组长度与去重，不声称256条通道覆盖。
        self._initial()
        self._observe_filters("initial")
        self._advance_filters()
        # 3. 真实业务完成且资金归属正确。
        self._finish_filters()

    # TEST-MAP: LSP-SUBSCRIPTION-27
    def test_257_repeated_channel_ids_rejected(self):
        """1. 构造257项原数组。2. 拒绝后原订阅仍推进并完成通道。"""
        # 1. 服务端必须在去重前校验原始长度。
        ids = [self.channel_id] * 257
        assert len(ids) == 257
        # 2. 业务拒绝与格式拒绝分层，原U仍收到R2。
        self._reject_group([[TOPIC, {"channel_ids": ids}]], -32001)

    # TEST-MAP: LSP-SUBSCRIPTION-28
    def test_fixed_version_options_array_compatibility(self):
        """1. 建立对象对照和三种数组订阅。2. 核对全集空集单A语义。3. 完成原通道。"""
        # 1. 沿用已确认的数组兼容预期，受测提交由构建清单固定。
        observer = self._connect_filter()
        with self._budget(40):
            self._subscribe_filter(observer, [TOPIC])
            self._subscribe_filter(observer, [TOPIC, [None]])
            self._subscribe_filter(observer, [TOPIC, [[]]], empty=True)
            self._subscribe_filter(observer, [TOPIC, [[self.channel_id]]])
        # 2. 非空者有完整R1/R2，空者始终无事件且可取消。
        self._initial()
        self._observe_filters("initial")
        self._advance_filters()
        self._cancel_empty()
        # 3. 不改产品行为，原身份原通道继续完成。
        self._finish_filters()


class TestSigningSubscriptionFilterIsolation(_FilterSubscriptionBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-SUBSCRIPTION-25
    def test_foreign_channel_and_mixed_orders(self):
        """1. 双租户各自证明R1存在。2. A指定B的三种列表整体拒绝。3. 两方推进R2并完成原通道。"""
        # 1. 每租户只开一条私有通道，不伪造多通道子集。
        a, b = self.tenants
        owner = self._connect_filter(a)
        other = self._connect_filter(b)
        with self._budget(40):
            self._subscribe_filter(owner, [TOPIC], a)
            self._subscribe_filter(other, [TOPIC], b)
            self._initial()
            # 2. 三个拒绝加两个合法对照共享五次请求的预算。
            for ids in (
                [b["channel_id"]],
                [a["channel_id"], b["channel_id"]],
                [b["channel_id"], a["channel_id"]],
            ):
                self._reject_filter(owner, [TOPIC, {"channel_ids": ids}], -32001)
        self._observe_filters("initial")
        # 3. 全连接持续检查越权及孤立事件，两租户都必须正向推进。
        self._advance_filters()
        self._finish_filters()

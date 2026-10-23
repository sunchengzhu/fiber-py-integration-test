"""PR #1623: real signer retries, transport recovery, and payment accounting."""

import copy
import time

from test_cases.fiber.devnet.lsp._lsp_test import ChannelSigningTestBase


class TestChannelSigningRetry(ChannelSigningTestBase):
    # TEST-MAP: LSP-RETRY-01
    def test_identical_retry_preserves_next_request(self):
        submission, following = self._apply_and_pause_next()
        before = self._snapshot(self.client)
        for _ in range(3):
            self._submit(submission, "AlreadyApplied")
            assert self._status() == following
            assert self._snapshot(self.client) == before
        self._finish_opening()

    # TEST-MAP: LSP-RETRY-02
    def test_conflicting_retry_preserves_original_receipt(self):
        submission, following = self._apply_and_pause_next()
        before = self._snapshot(self.client)
        changed_signature = copy.deepcopy(submission)
        changed_signature["partial_signature"] = "0x" + "01" * 32
        assert changed_signature != submission
        changed_material = copy.deepcopy(submission)
        changed_material["next_material"]["next_commitment_point"] = self.public_key
        assert changed_material != submission
        for conflict in (changed_signature, changed_material):
            self._submit(conflict, expected=None)
            assert self._status() == following
            assert self._snapshot(self.client) == before
            self._submit(submission, "AlreadyApplied")
            assert self._status() == following
        self._finish_opening()

    # TEST-MAP: LSP-RETRY-03
    def test_older_receipt_is_rejected_after_next_apply(self):
        self._finish_opening()
        with self.gate.lock:
            applied = [
                copy.deepcopy(params)
                for params, reply in self.gate.forwarded
                if reply.get("result") == {"type": "Applied"}
            ]
        assert len(applied) >= 2, applied
        older, latest = applied[-2:]
        assert older["request_id"] != latest["request_id"]
        before = [
            self._snapshot(client) for client in (self.client, self.fiber1.client)
        ]
        for _ in range(5):
            time.sleep(1)
            assert [
                self._snapshot(client) for client in (self.client, self.fiber1.client)
            ] == before
        self._submit(older, expected=None)
        self._submit(latest, "AlreadyApplied")
        assert self._status() == {"type": "NoSignatureRequired"}
        assert [
            self._snapshot(client) for client in (self.client, self.fiber1.client)
        ] == before

    # TEST-MAP: LSP-RETRY-04
    def test_unsent_signature_recovers_after_disconnect(self):
        """
        1. 保存未送达的有效签名，注入 HTTP 断线并拦住恢复订阅。
        2. 核对原请求不变且从未提交，放行同一 SDK 的新订阅并核对补发。
        3. 放行真实提交，核对首次应用及原通道、原注资完成。
        """
        # 1. HTTP 请求未转发；真正断线触发原 SDK 重新连接。
        original, submission = self._pending()
        sdk_pid = self.tenant["agent"].pid
        self.gate.arm_fault("disconnect", submission)
        attempted_at, connection, request = self._wait_for_fault_resubscription()

        # 2. 新 subscribe 尚未转发，复核 R1 后才允许服务器补发。
        assert self._status() == original
        assert self.gate.forwarded == []
        with self.subscription_proxy.lock:
            assert any(
                item["message"] == request and item["forwarded_at"] is None
                for item in connection.requests
            )
        with self.gate.lock:
            self.gate.fault_mode = None
            self.gate.fault_submission = None
        self.subscription_proxy.resume_subscriptions()
        self._wait_for_subscription_request(original, self.gate.fault_started)
        assert self.tenant["agent"].pid == sdk_pid
        print(
            f"SDK WS resubscribe after unsent request: "
            f"{attempted_at - self.gate.fault_started:.3f}s"
        )

        # 3. 首次真实上游结果必须 Applied，签名体及原业务身份不变。
        self._finish_opening()
        with self.gate.lock:
            first_params, first_reply = self.gate.forwarded[0]
        assert first_params == submission
        assert first_reply.get("result") == {"type": "Applied"}, first_reply

    # TEST-MAP: LSP-RETRY-05
    def test_applied_signature_recovers_after_http_timeout(self):
        """
        1. 真实应用 S1，保持 HTTP 无响应，由 SDK 自然经历请求超时。
        2. 观察同一 SDK 重新订阅并收到 R2，冻结下一提交后重交 S1。
        3. 核对幂等与 R2 不变，完成原通道且不重复注资。
        """
        # 1. 不发送 HTTP 头、正文或 EOF，记录客户端自然关闭请求。
        original, submission = self._pending()
        sdk_pid = self.tenant["agent"].pid
        self.gate.arm_fault("lose_response", submission)
        attempted_at, _, _ = self._wait_for_fault_resubscription()
        assert self.gate.fault_applied is not None
        for _ in range(20):
            if self.gate.client_closed is not None:
                break
            time.sleep(0.1)
        assert self.gate.client_closed is not None, "SDK did not cancel HTTP request"
        assert self.gate.client_closed - self.gate.fault_started >= 9
        print(
            f"SDK natural HTTP cancellation: "
            f"{self.gate.client_closed - self.gate.fault_started:.3f}s; "
            f"WS resubscribe: {attempted_at - self.gate.fault_started:.3f}s"
        )

        # 2. 原 SDK 的真实新订阅交付 R2，不能用 Python 查询代替恢复。
        following, _ = self._pending(previous=original["request_id"])
        self._wait_for_subscription_request(following, self.gate.fault_started)
        assert self.tenant["agent"].pid == sdk_pid
        before = self._snapshot(self.client)
        self._submit(submission, "AlreadyApplied")
        assert self._status() == following
        assert self._snapshot(self.client) == before

        # 3. 上游仅首次应用一次，保持最近记录后完成原通道。
        with self.gate.lock:
            assert len(self.gate.forwarded) == 1, self.gate.forwarded
            forwarded_submission, reply = self.gate.forwarded[0]
            assert forwarded_submission == submission
            assert reply.get("result") == {"type": "Applied"}, reply
        self._finish_opening()

    # TEST-MAP: LSP-RETRY-06
    def test_payment_retry_settles_balances_once(self):
        self._finish_opening()
        payer = self.fiber2.client
        payer.timeout = 10
        payer.try_count = 1
        public_channel = self.open_channel(
            self.fiber2, self.fiber1, 1000 * 100000000, 0
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            nodes = payer.graph_nodes({})["nodes"]
            announced = any(
                node["pubkey"] == self.public_key
                and "TRAMPOLINE_ROUTING_REQUIRED" in node["features"]
                for node in nodes
            )
            if (
                announced
                and self._channel(self.fiber1.client, public_channel)["state"][
                    "state_name"
                ]
                == "ChannelReady"
            ):
                break
            time.sleep(1)
        else:
            assert False, f"payer did not learn the ready LSP trampoline route: {nodes}"
        endpoints = [
            (self.client, self.channel_id),
            (self.fiber1.client, self.channel_id),
            (payer, public_channel),
            (self.fiber1.client, public_channel),
        ]
        before = [self._snapshot(client, channel) for client, channel in endpoints]
        assert all(not item["pending_tlcs"] for item in before)
        amount = 1_000_000
        preimage = self.generate_random_preimage()
        invoice = self.client.new_invoice(
            {
                "amount": hex(amount),
                "currency": "Fibd",
                "expiry": hex(3600),
                # Leave time for SDK authorization and the reviewed retry window.
                "final_expiry_delta": hex(3_600_000),
                "payment_preimage": preimage,
                "allow_trampoline_routing": True,
                "allow_mpp": False,
            }
        )
        payment_hash = invoice["invoice"]["data"]["payment_hash"]
        now_ms = int(time.time() * 1000)
        self.signer_control(
            self.tenant,
            "invoice",
            {
                "authorization": {
                    "payment_hash": payment_hash,
                    "hash_algorithm": "ckb_hash",
                    "inbound": True,
                    "amount": amount,
                    "expires_at_ms": now_ms + 3_600_000,
                    "min_tlc_expiry_delta_ms": 900_000,
                    "max_tlc_expiry_ms": now_ms + 172_800_000,
                },
                "preimage": preimage,
            },
        )
        with self.gate.lock:
            self.gate.passthrough = False
        payment = payer.send_payment(
            {
                "invoice": invoice["invoice_address"],
                "max_fee_amount": hex(10_000),
                # Cap routing's random expiry extension below the SDK's 48-hour bound.
                "tlc_expiry_limit": hex(86_400_000),
                "timeout": hex(300),
            }
        )
        assert payment["payment_hash"] == payment_hash
        pending, submission = self._pending()
        assert pending["transition"] in (
            "SendCommitmentSigned",
            "CompleteReceivedCommitment",
        ), pending
        assert any(
            tlc["payment_hash"] == payment_hash for tlc in pending["settlement"]["tlcs"]
        ), pending
        self.signer_control(
            self.tenant,
            "fulfill",
            {
                "payment_hash": payment_hash,
                "preimage": preimage,
            },
        )
        tlcs = self._channel(self.client)["pending_tlcs"]
        assert tlcs and all(tlc["payment_hash"] == payment_hash for tlc in tlcs), tlcs
        deadline_ms = min(int(tlc["expiry"], 16) for tlc in tlcs) - 2000 * 2 // 3
        assert deadline_ms - time.time() * 1000 >= 180_000
        self._submit(submission)
        following, _ = self._pending(previous=pending["request_id"])
        paused = self._snapshot(self.client)
        for _ in range(3):
            self._submit(submission, "AlreadyApplied")
            assert self._status() == following
            assert self._snapshot(self.client) == paused
        assert deadline_ms - time.time() * 1000 >= 120_000
        self.gate.release()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            payment = payer.get_payment({"payment_hash": payment_hash})
            received = self.client.get_invoice({"payment_hash": payment_hash})
            after = [self._snapshot(client, channel) for client, channel in endpoints]
            if (
                payment["status"] == "Success"
                and received["status"] == "Paid"
                and all(not item["pending_tlcs"] for item in after)
                and self._status()["type"] == "NoSignatureRequired"
            ):
                break
            assert payment["status"] != "Failed", payment
            time.sleep(1)
        else:
            assert False, f"payment did not settle: {payment}, {received}, {after}"
        fee = int(payment["fee"], 16)
        assert 0 <= fee <= 10_000
        expected_changes = (amount, -amount, -amount - fee, amount + fee)
        for previous, current, delta in zip(before, after, expected_changes):
            assert current["state"]["state_name"] == "ChannelReady"
            assert current["channel_outpoint"] == previous["channel_outpoint"]
            assert (
                int(current["local_balance"], 16) - int(previous["local_balance"], 16)
                == delta
            )
            assert (
                int(current["remote_balance"], 16) - int(previous["remote_balance"], 16)
                == -delta
            )
            assert int(current["offered_tlc_balance"], 16) == 0
            assert int(current["received_tlc_balance"], 16) == 0
        for left, right in ((0, 1), (2, 3)):
            assert after[left]["local_balance"] == after[right]["remote_balance"]
            assert after[left]["remote_balance"] == after[right]["local_balance"]
        print(
            f"Hosted payment settled once: amount={amount}, fee={fee}, deltas={expected_changes}"
        )
        for _ in range(5):
            time.sleep(1)
            assert [
                self._snapshot(client, channel) for client, channel in endpoints
            ] == after
            assert self._status()["type"] == "NoSignatureRequired"
            assert (
                payer.get_payment({"payment_hash": payment_hash})["status"] == "Success"
            )
            assert (
                self.client.get_invoice({"payment_hash": payment_hash})["status"]
                == "Paid"
            )

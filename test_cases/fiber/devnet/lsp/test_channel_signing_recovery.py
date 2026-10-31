"""PR #1623: checked SDK lifecycle and real SDK/FNN process recovery."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from test_cases.fiber.devnet.lsp._lsp_test import ChannelSigningTestBase, stop_agent


class _SequenceBudgetExpired(BaseException):
    pass


class TestChannelSigningRecovery(ChannelSigningTestBase):
    def _check_opening_window(self, seconds):
        created = int(self._channel(self.client)["created_at"], 16) / 1000
        assert created + 86400 - time.time() >= seconds

    def _finish_opening(self):
        super()._finish_opening()
        before = [self._snapshot(c) for c in (self.client, self.fiber1.client)]
        for _ in range(5):
            time.sleep(1)
            assert [
                self._snapshot(c) for c in (self.client, self.fiber1.client)
            ] == before
            assert self._status()["type"] == "NoSignatureRequired"

    def _kill_sdk(self):
        self.saved_identity = json.loads(self.tenant["status_file"].read_text())
        self.saved_controls = list(self.tenant["control_calls"])
        self.old_sdk_pid = self.tenant["agent"].pid
        assert self.tenant["agent"].poll() is None
        self.tenant["agent"].kill()
        assert self.tenant["agent"].wait(timeout=10) != 0

    def _restore_sdk(self, pending, expected_submission=None):
        assert self.tenant["agent"].poll() is not None
        # Delete only the disposable status output, never the signer store.
        self.tenant["status_file"].unlink()
        started = time.monotonic()
        self.tenant["agent"] = subprocess.Popen(
            self.tenant["command"], stdout=self.tenant["log"], stderr=subprocess.STDOUT
        )
        self.addCleanup(stop_agent, self.tenant["agent"])
        assert self.tenant["agent"].pid != self.old_sdk_pid
        deadline = started + 60
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            with self.gate.lock:
                attempts = [
                    body
                    for t, body in self.gate.attempts
                    if t >= started and body["request_id"] == pending["request_id"]
                ]
            if attempts and self.tenant["status_file"].exists():
                break
            time.sleep(0.2)
        else:
            assert False, "new SDK process did not sign the original pending request"
        self._wait_for_subscription_request(pending, started)
        restored = json.loads(self.tenant["status_file"].read_text())
        for field in (
            "tenant_id",
            "root_signer_pubkey",
            "tenant_token",
            "bound_channel_ids",
        ):
            assert restored[field] == self.saved_identity[field], field
        assert self.channel_id in restored["bound_channel_ids"]
        assert self.tenant["control_calls"] == self.saved_controls
        assert self._status() == pending
        if expected_submission is not None:
            assert attempts[0] == expected_submission
        print(
            f"SDK process recovered: {self.old_sdk_pid} -> {self.tenant['agent'].pid}"
        )

    def _restart_fnn(self, pending):
        sdk_pid = self.tenant["agent"].pid
        controls = list(self.tenant["control_calls"])
        self.subscription_proxy.freeze()
        with self.gate.lock:
            self.gate.passthrough = False
        # Wait for the current SDK event handler before stopping the server.
        self.signer_control(self.tenant, "records")
        old_pid = int(
            subprocess.check_output(
                ["lsof", "-t", f"-iTCP:{self.fiber1.rpc_port}", "-sTCP:LISTEN"],
                text=True,
            ).strip()
        )
        stopped = time.monotonic()
        self.fiber1.stop()
        while time.monotonic() < stopped + 30:
            try:
                os.kill(old_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.2)
        else:
            assert False, "FNN did not exit normally within 30 seconds"
        self.fiber1.start()
        new_pid = int(
            subprocess.check_output(
                ["lsof", "-t", f"-iTCP:{self.fiber1.rpc_port}", "-sTCP:LISTEN"],
                text=True,
            ).strip()
        )
        assert new_pid != old_pid
        assert self.tenant["agent"].pid == sdk_pid
        assert self.tenant["agent"].poll() is None
        # The unchanged client still uses the original tenant token.
        assert self._status() == pending
        assert self.tenant["control_calls"][:-1] == controls
        self.subscription_proxy.resume()
        self._wait_for_subscription_request(pending, stopped)
        assert self.tenant["agent"].pid == sdk_pid
        print(f"Hosted FNN process recovered: {old_pid} -> {new_pid}; SDK stayed alive")

    def _check_first_forward(self, submission):
        with self.gate.lock:
            forwarded = [
                (body, reply)
                for body, reply in self.gate.forwarded
                if body["request_id"] == submission["request_id"]
            ]
        assert forwarded and forwarded[0][0] == submission, forwarded
        assert forwarded[0][1].get("result") == {"type": "Applied"}, forwarded

    def _start_payment(self, pause=True, public_channel=None):
        payer = self.fiber2.client
        payer.timeout = 10
        payer.try_count = 1
        if public_channel is None:
            public_channel = self.open_channel(
                self.fiber2, self.fiber1, 1000 * 100000000, 0
            )
        for _ in range(60):
            if (
                any(
                    n["pubkey"] == self.public_key
                    and "TRAMPOLINE_ROUTING_REQUIRED" in n["features"]
                    for n in payer.graph_nodes({})["nodes"]
                )
                and self._channel(self.fiber1.client, public_channel)["state"][
                    "state_name"
                ]
                == "ChannelReady"
            ):
                break
            time.sleep(1)
        else:
            assert False, "payer did not learn the LSP route"
        endpoints = [
            (self.client, self.channel_id),
            (self.fiber1.client, self.channel_id),
            (payer, public_channel),
            (self.fiber1.client, public_channel),
        ]
        before = [self._snapshot(c, ch) for c, ch in endpoints]
        assert all(not c["pending_tlcs"] for c in before)
        amount, preimage = 1_000_000, self.generate_random_preimage()
        invoice = self.client.new_invoice(
            {
                "amount": hex(amount),
                "currency": "Fibd",
                "expiry": hex(3600),
                # Match the reviewed recovery window and SDK's 15-minute minimum.
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
        self.payment = {
            "hash": payment_hash,
            "preimage": preimage,
            "amount": amount,
            "endpoints": endpoints,
            "before": before,
            "fulfilled": False,
            "authorization_expiry": now_ms + 3_600_000,
        }
        with self.gate.lock:
            self.gate.passthrough = not pause
        result = payer.send_payment(
            {
                "invoice": invoice["invoice_address"],
                "max_fee_amount": hex(10_000),
                # Cap routing's random expiry extension below the SDK's 48-hour bound.
                "tlc_expiry_limit": hex(86_400_000),
                "timeout": hex(1200),
            }
        )
        assert result["payment_hash"] == payment_hash

    def _authorize_fulfillment(self):
        if self.payment["fulfilled"]:
            return
        records = self.signer_control(self.tenant, "records")
        if any(
            t["payment_hash"] == self.payment["hash"]
            for r in records
            for t in r["tlcs"]
        ):
            self.signer_control(
                self.tenant,
                "fulfill",
                {
                    "payment_hash": self.payment["hash"],
                    "preimage": self.payment["preimage"],
                },
            )
            self.payment["fulfilled"] = True

    def _check_payment_window(self, seconds):
        tlcs = self._channel(self.client)["pending_tlcs"]
        assert tlcs and all(
            t["payment_hash"] == self.payment["hash"] for t in tlcs
        ), tlcs
        expiries = [int(t["expiry"], 16) for t in tlcs]
        records = self.signer_control(self.tenant, "records")
        expiries.extend(t["expiry"] for r in records for t in r["tlcs"])
        cutoff = min((expiry // 1000) * 1000 - 1334 for expiry in expiries)
        cutoff = min(cutoff, self.payment["authorization_expiry"])
        assert (
            cutoff - time.time() * 1000 >= seconds * 1000
        ), "insufficient recovery window"

    def _finish_payment(self, delivery_check=None):
        self.gate.release()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            self._authorize_fulfillment()
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            paid = self.fiber2.client.get_payment(
                {"payment_hash": self.payment["hash"]}
            )
            received = self.client.get_invoice({"payment_hash": self.payment["hash"]})
            after = [self._snapshot(c, ch) for c, ch in self.payment["endpoints"]]
            assert paid["status"] != "Failed", paid
            if (
                paid["status"] == "Success"
                and received["status"] == "Paid"
                and all(not c["pending_tlcs"] for c in after)
                and self._status()["type"] == "NoSignatureRequired"
                and (
                    delivery_check is None
                    or delivery_check("completion")["status"] == "succeeded"
                )
            ):
                break
            time.sleep(1)
        else:
            assert False, f"payment did not finish: {paid}, {received}, {after}"
        assert self.payment["fulfilled"]
        amount, fee = self.payment["amount"], int(paid["fee"], 16)
        assert 0 <= fee <= 10_000
        deltas = (amount, -amount, -amount - fee, amount + fee)
        for old, new, delta in zip(self.payment["before"], after, deltas):
            assert new["state"]["state_name"] == "ChannelReady"
            assert new["channel_outpoint"] == old["channel_outpoint"]
            assert (
                int(new["local_balance"], 16) - int(old["local_balance"], 16) == delta
            )
            assert (
                int(new["remote_balance"], 16) - int(old["remote_balance"], 16)
                == -delta
            )
            assert (
                int(new["offered_tlc_balance"], 16)
                == int(new["received_tlc_balance"], 16)
                == 0
            )
        for left, right in ((0, 1), (2, 3)):
            assert after[left]["local_balance"] == after[right]["remote_balance"]
            assert after[left]["remote_balance"] == after[right]["local_balance"]
        stability = []
        for _ in range(5):
            time.sleep(1)
            stable = [self._snapshot(c, ch) for c, ch in self.payment["endpoints"]]
            assert stable == after
            stability.append({"at": time.monotonic(), "balances": stable})
            assert self._status()["type"] == "NoSignatureRequired"
            assert (
                self.fiber2.client.get_payment({"payment_hash": self.payment["hash"]})[
                    "status"
                ]
                == "Success"
            )
            assert (
                self.client.get_invoice({"payment_hash": self.payment["hash"]})[
                    "status"
                ]
                == "Paid"
            )
            if delivery_check is not None:
                assert delivery_check("stable")["status"] == "succeeded"
        print(
            f"Payment settled once: {self.payment['hash']}, fee={fee}, deltas={deltas}"
        )
        return paid, received, after, stability

    def _start_close(self, pause=False):
        self.close_before = self._channel(self.client)
        assert not self.close_before["pending_tlcs"]
        assert self._status()["type"] == "NoSignatureRequired"
        self.signer_control(
            self.tenant, "close", {"fee": self.tenant["opening"]["close_fee"]}
        )
        with self.gate.lock:
            self.gate.passthrough = not pause
        self.fiber1.client.shutdown_channel(
            {"channel_id": self.channel_id, "force": False, "fee_rate": hex(1000)}
        )

    def _finish_close(self, expected_transaction=None):
        self.gate.release()
        clients = (self.client, self.fiber1.client)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            channels = [
                next(
                    c
                    for c in client.list_channels({"include_closed": True})["channels"]
                    if c["channel_id"] == self.channel_id
                )
                for client in clients
            ]
            hashes = [c["shutdown_transaction_hash"] for c in channels]
            if hashes[0] and hashes[0] == hashes[1]:
                break
            time.sleep(1)
        else:
            assert False, f"missing matching cooperative close transaction: {channels}"
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            closed_tx = self.node.getClient().get_transaction(hashes[0])
            status = closed_tx["tx_status"]["status"]
            assert status != "rejected", closed_tx
            if status == "committed":
                break
            self.Miner.miner_with_version(self.node, "0x0")
            time.sleep(1)
        else:
            assert False, f"cooperative close did not confirm: {closed_tx}"
        tx = closed_tx["transaction"]
        assert (
            closed_tx["tx_status"]["status"] == "committed" and tx["hash"] == hashes[0]
        )
        if expected_transaction is not None:
            # The hash commits to these raw fields; witnesses contain the completed signature.
            for field in (
                "version",
                "cell_deps",
                "header_deps",
                "inputs",
                "outputs",
                "outputs_data",
            ):
                assert tx[field] == expected_transaction[field], field
        point = bytes.fromhex(self.close_before["channel_outpoint"][2:])
        expected_point = {
            "tx_hash": "0x" + point[:32].hex(),
            "index": hex(int.from_bytes(point[32:], "little")),
        }
        assert (
            len(tx["inputs"]) == 1
            and tx["inputs"][0]["previous_output"] == expected_point
        )
        assert len(tx["outputs"]) == 2 and tx["outputs_data"] == ["0x", "0x"]
        terms, fee = (
            self.tenant["opening"]["parameters"],
            self.tenant["opening"]["close_fee"],
        )
        amounts = (
            int(self.close_before["local_balance"], 16)
            + terms["local_reserved_ckb_amount"],
            int(self.close_before["remote_balance"], 16)
            + terms["remote_reserved_ckb_amount"]
            - fee,
        )
        scripts = (
            self.tenant["shutdown_script"],
            self.tenant["opening"]["remote_shutdown_script"],
        )
        assert scripts[0] != scripts[1]
        for script, amount in zip(scripts, amounts):
            outputs = [o for o in tx["outputs"] if o["lock"] == script]
            assert (
                len(outputs) == 1 and int(outputs[0]["capacity"], 16) == amount
            ), outputs
            assert outputs[0]["type"] is None
        funding = self.node.getClient().get_transaction(expected_point["tx_hash"])[
            "transaction"
        ]
        capacity = int(
            funding["outputs"][int(expected_point["index"], 16)]["capacity"], 16
        )
        assert capacity - sum(int(o["capacity"], 16) for o in tx["outputs"]) == fee
        while time.monotonic() < deadline:
            active = [client.list_channels({})["channels"] for client in clients]
            if all(
                not any(c["channel_id"] == self.channel_id for c in side)
                for side in active
            ):
                break
            time.sleep(1)
        else:
            assert False, f"closed channel remained active: {active}"
        for client in clients:
            channel = next(
                c
                for c in client.list_channels({"include_closed": True})["channels"]
                if c["channel_id"] == self.channel_id
            )
            assert channel["state"]["state_name"] == "Closed"
            assert channel["shutdown_transaction_hash"] == hashes[0]
        print(f"Cooperative close committed: {hashes[0]}, outputs={amounts}, fee={fee}")

    # TEST-MAP: LSP-RECOVERY-01
    def test_checked_open_pay_and_close(self):
        self._finish_opening()
        self._start_payment(pause=False)
        self._finish_payment()
        self._start_close()
        self._finish_close()

    # TEST-MAP: LSP-RECOVERY-02
    def test_sdk_restart_with_saved_unsubmitted_opening_signature(self):
        """
        1. 保存已签但未送达的开通请求，核对安全余量。
        2. 强制退出 SDK，以原存储新进程订阅恢复原请求并生成相同签名。
        3. 放行首次应用，核对原通道及原注资完成。
        """
        # 1. 保存已签但未送达的开通请求，核对安全余量。
        pending, submission = self._pending()
        assert not self.gate.forwarded
        self._check_opening_window(900)
        # 2. 强制退出 SDK，以原存储新进程订阅恢复原请求并生成相同签名。
        self._kill_sdk()
        assert self._status() == pending
        self._restore_sdk(pending, submission)

        # 3. 放行首次应用，核对原通道及原注资完成。
        self._check_opening_window(180)
        self._finish_opening()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-03
    def test_sdk_restart_without_learning_applied_result(self):
        """
        1. 在转发 S1 前冻结全部 WS 通知和新订阅，应用后扣住 HTTP 响应。
        2. 确认旧 SDK 未收到 R2 后强制退出，以原存储新进程订阅恢复 R2。
        3. 重交 S1 核对幂等且 R2 不变，放行后完成原通道及原注资。
        """
        # 1. 在下一次 S1 已到代理、尚未到 FNN 时建立同步冻结屏障。
        first, submission = self._pending()
        self._check_opening_window(900)
        checkpoint = {}

        def freeze_before_forward(mode):
            assert mode == "lose_response"
            checkpoint["frozen_at"] = self.subscription_proxy.freeze()

        self.gate.on_fault = freeze_before_forward
        self.gate.arm_fault("lose_response", submission)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert not self.gate.errors, self.gate.errors
            if self.gate.fault_applied is not None:
                break
            time.sleep(0.05)
        else:
            assert False, "upstream did not apply the intercepted signature"
        assert checkpoint["frozen_at"] < self.gate.fault_applied

        # 2. 代理实际交付记录没有越过冻结点；新进程只能读服务器新补发。
        self._kill_sdk()
        for connection in self.subscription_proxy.connections():
            assert all(
                at <= checkpoint["frozen_at"]
                for at, _, _ in connection.delivered_frames()
            )
        assert (
            self.gate.client_closed is None
            or self.gate.client_closed >= self.gate.fault_applied
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            following = self._status()
            if (
                following["type"] == "SignatureRequired"
                and following["request_id"] != first["request_id"]
            ):
                break
            time.sleep(0.2)
        else:
            assert False, f"next signing request did not appear: {following}"
        with self.gate.lock:
            assert not any(
                body["request_id"] == following["request_id"]
                for _, body in self.gate.attempts
            )
            self.gate.fault_mode = None
            self.gate.fault_submission = None
            self.gate.on_fault = None
        self.subscription_proxy.resume()
        self._restore_sdk(following)

        # 3. 保留真实幂等、完整 R2、原通道和注资身份的判断。
        self._submit(submission, "AlreadyApplied")
        assert self._status() == following
        self._check_opening_window(180)
        self._finish_opening()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-04
    def test_hosted_fnn_restart_with_pending_opening_signature(self):
        """
        1. 冻结未送达的开通签名并保存完整请求。
        2. 正常重启整个 FNN，同一 SDK 重新订阅取得原请求。
        3. 放行签名，核对首次应用及原通道原注资完成。
        """
        # 1. 冻结未送达的开通签名并保存完整请求。
        pending, submission = self._pending()
        assert not self.gate.forwarded
        self._check_opening_window(900)
        # 2. 正常重启整个 FNN，同一 SDK 重新订阅取得原请求。
        self._restart_fnn(pending)

        # 3. 放行签名，核对首次应用及原通道原注资完成。
        self._check_opening_window(180)
        self._finish_opening()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-05
    def test_hosted_fnn_restart_preserves_payment_receipt_and_next_request(self):
        """
        1. 发起唯一支付并应用关联承诺 S1，冻结 R2，记录未完成 delivery 的原执行键。
        2. 正常重启整个 FNN，以原数据恢复同一 delivery 和 R2，重交 S1仍幂等。
        3. 恢复原支付，核对 delivery 成功、TLC 清理及四端余额只结算一次并稳定。
        """
        # 1. 发起唯一支付并应用关联承诺 S1，冻结 R2，记录未完成 delivery 的原执行键。
        self._finish_opening()
        self._start_payment()
        first, submission = self._pending()
        assert first["transition"] in (
            "SendCommitmentSigned",
            "CompleteReceivedCommitment",
        )
        assert any(
            t["payment_hash"] == self.payment["hash"]
            for t in first["settlement"]["tlcs"]
        )
        self._authorize_fulfillment()
        assert self.payment["fulfilled"]
        self._check_payment_window(900)
        self._submit(submission)
        following, _ = self._pending(first["request_id"])
        original = None

        def observe_delivery(stage):
            record = self.fiber1.client.call(
                "lsp_get_payment_delivery", [{"payment_hash": self.payment["hash"]}]
            )
            observation = {"stage": stage, "at": time.monotonic(), "delivery": record}
            print("Persisted delivery: " + json.dumps(observation))
            root = os.environ.get("LSP_RUN_ARTIFACTS")
            if root:
                path = Path(root) / (self._testMethodName + ".delivery.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a") as stream:
                    stream.write(json.dumps(observation) + "\n")
            assert record["payment_hash"] == self.payment["hash"], record
            assert record["private_channel_id"] == self.channel_id, record
            identity = json.loads(self.tenant["status_file"].read_text())
            assert record["tenant_id"] == identity["tenant_id"], record
            assert (
                record["incoming_channel_id"] == self.payment["endpoints"][2][1]
            ), record
            assert record["status"] in (
                "deferred",
                "dispatching",
                "in_flight",
                "settling_upstream",
                "succeeded",
            ), record
            assert record["failure_reason"] is None, record
            if original is not None:
                for field in (
                    "payment_hash",
                    "incoming_channel_id",
                    "incoming_tlc_id",
                    "tenant_id",
                    "private_channel_id",
                    "created_at",
                    "buffer_deadline",
                ):
                    assert record[field] == original[field], (field, original, record)
                assert int(record["attempt_count"], 16) >= int(
                    original["attempt_count"], 16
                )
            return record

        original = observe_delivery("before_restart")
        assert original["status"] in ("in_flight", "settling_upstream"), original
        assert int(original["attempt_count"], 16) >= 1, original
        upstream = self._channel(self.fiber1.client, original["incoming_channel_id"])
        incoming = [
            t
            for t in upstream["pending_tlcs"]
            if t["payment_hash"] == self.payment["hash"]
        ]
        assert len(incoming) == 1, incoming
        assert incoming[0]["id"] == original["incoming_tlc_id"], (incoming, original)

        # 2. 正常重启整个 FNN，以原数据恢复同一 delivery 和 R2，重交 S1仍幂等。
        self._restart_fnn(following)
        observe_delivery("after_restart")
        self._submit(submission, "AlreadyApplied")
        assert self._status() == following

        # 3. 恢复原支付，核对 delivery 成功、TLC 清理及四端余额只结算一次并稳定。
        self.fiber2.connect_peer(self.fiber1)
        self._check_payment_window(180)
        self._finish_payment(delivery_check=observe_delivery)

    # TEST-MAP: LSP-RECOVERY-06
    def test_sdk_restart_preserves_payment_revocation_and_authorizations(self):
        """
        1. 保存支付授权及该支付的撤销签名，保持其未提交。
        2. 以原存储重启 SDK，通过新订阅恢复原请求和相同提交体。
        3. 首次应用撤销签名并完成原支付，核对资金只结算一次。
        """
        # 1. 保存支付授权及该支付的撤销签名，保持其未提交。
        self._finish_opening()
        self._start_payment()
        pending, submission = self._pending()
        assert any(
            t["payment_hash"] == self.payment["hash"]
            for t in pending["settlement"]["tlcs"]
        )
        self._authorize_fulfillment()
        assert self.payment["fulfilled"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if pending["transition"] == "SendRevokeAndAck":
                break
            assert pending["transition"] in (
                "SendCommitmentSigned",
                "CompleteReceivedCommitment",
                "CompleteReceivedRevokeAndAck",
            ), pending
            self._submit(submission)
            pending, submission = self._pending(pending["request_id"])
        else:
            assert False, "payment's SendRevokeAndAck checkpoint did not appear"
        assert time.monotonic() < deadline, "revocation checkpoint exceeded 60 seconds"
        version = int(pending["content"]["slot"]["commitment_number"], 16)
        records = self.signer_control(self.tenant, "records")
        assert any(
            not r["for_remote"]
            and r["version"] == version
            and r["complete"]
            and any(t["payment_hash"] == self.payment["hash"] for t in r["tlcs"])
            for r in records
        ), "revocation must replace the commitment carrying this payment"
        assert not any(
            s["request_id"] == submission["request_id"] for s, _ in self.gate.forwarded
        )
        self._check_payment_window(900)
        # 2. 以原存储重启 SDK，通过新订阅恢复原请求和相同提交体。
        self._kill_sdk()
        self._restore_sdk(pending, submission)

        # 3. 首次应用撤销签名并完成原支付，核对资金只结算一次。
        self._check_payment_window(180)
        self._finish_payment()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-07
    def test_sdk_restart_preserves_close_authorization_and_outputs(self):
        """
        1. 完成收款并批准关闭，冻结已保存但未送达的关闭签名。
        2. 以原存储重启 SDK，新订阅恢复原关闭请求且不重新授权。
        3. 首次应用后确认关闭交易，核对原注资只花费一次及输出地址金额。
        """
        # 1. 完成收款并批准关闭，冻结已保存但未送达的关闭签名。
        self._finish_opening()
        self._start_payment(pause=False)
        self._finish_payment()
        self._start_close(pause=True)
        pending, submission = self._pending()
        assert pending["transition"] == "SendClosingSigned"
        content = pending["content"]["content"]
        assert content["type"] == "CooperativeCloseTransaction"
        assert not any(
            s["request_id"] == submission["request_id"] for s, _ in self.gate.forwarded
        )
        # 2. 以原存储重启 SDK，新订阅恢复原关闭请求且不重新授权。
        self._kill_sdk()
        self._restore_sdk(pending, submission)

        # 3. 首次应用后确认关闭交易，核对原注资只花费一次及输出地址金额。
        self._finish_close(content["transaction"])
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-08
    def test_sequential_payments_survive_sdk_restart(self):
        """
        1. 同两条通道完成前八笔唯一付款，逐笔核对资金和稳定窗口。
        2. 保存第九笔撤销签名，退出SDK后保留原存储并恢复同一请求。
        3. 完成第九、第十笔，核对历史终态、累计费用及原通道身份。
        """
        evidence = Path(os.environ.get("LSP_RUN_ARTIFACTS", self.fiber1.tmp_path))
        evidence.mkdir(parents=True, exist_ok=True)
        ledger = evidence / "sequence.jsonl"
        command = list(self.tenant["command"])
        store = Path(command[command.index("--store") + 1]) / "snapshot.bin"
        original_pid = self.tenant["agent"].pid
        started = time.monotonic()
        deadline = min(
            started + 690, float(os.environ.get("LSP_RECOVERY08_DEADLINE", "inf"))
        )

        def record(kind, **values):
            with ledger.open("a") as stream:
                stream.write(
                    json.dumps({"kind": kind, "at": time.monotonic(), **values}) + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())

        def metric(completed):
            records = self.signer_control(self.tenant, "records")
            record(
                "metric",
                completed=completed,
                whole_store_bytes=store.stat().st_size,
                record_count=len(records),
                records=[
                    {k: r[k] for k in ("version", "for_remote", "complete")}
                    for r in records
                ],
            )

        def expired(_signum, _frame):
            raise _SequenceBudgetExpired("RECOVERY-08 global deadline expired")

        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        assert previous_timer == (0.0, 0.0), "unexpected existing alarm"
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.monotonic()))
        completed, seen_preimages, seen_hashes = [], set(), set()
        try:
            # 1. 仅准备一次P–T；后续十笔复用两条通道及原SDK存储。
            self._finish_opening()
            public_channel = self.open_channel(
                self.fiber2, self.fiber1, 1000 * 100000000, 0
            )
            endpoints = [
                (self.client, self.channel_id),
                (self.fiber1.client, self.channel_id),
                (self.fiber2.client, public_channel),
                (self.fiber1.client, public_channel),
            ]
            baseline = [self._snapshot(c, ch) for c, ch in endpoints]
            assert all(
                c["state"]["state_name"] == "ChannelReady" and not c["pending_tlcs"]
                for c in baseline
            )
            record(
                "baseline",
                balances=baseline,
                sdk_pid=original_pid,
                store_path=str(store),
            )
            metric(0)
            for number in range(1, 11):
                payment_started = time.monotonic()
                assert self.tenant["agent"].pid == (
                    original_pid if number <= 9 else recovered_pid
                )
                assert list(self.tenant["command"]) == command
                self._start_payment(pause=(number == 9), public_channel=public_channel)
                assert self.payment["endpoints"] == endpoints
                payment_hash, preimage = self.payment["hash"], self.payment["preimage"]
                assert (
                    payment_hash not in seen_hashes and preimage not in seen_preimages
                )
                seen_hashes.add(payment_hash)
                seen_preimages.add(preimage)
                record(
                    "sent_once",
                    number=number,
                    payment_hash=payment_hash,
                    started=payment_started,
                    before=self.payment["before"],
                )
                if number == 9:
                    # 2. 仅推进至本笔撤销检查点；S9必须仍由恢复后的真实SDK首次提交。
                    pending, submission = self._pending()
                    assert any(
                        t["payment_hash"] == payment_hash
                        for t in pending["settlement"]["tlcs"]
                    )
                    self._authorize_fulfillment()
                    assert self.payment["fulfilled"]
                    checkpoint_deadline = min(time.monotonic() + 60, deadline)
                    while time.monotonic() < checkpoint_deadline:
                        if pending["transition"] == "SendRevokeAndAck":
                            break
                        assert pending["transition"] in (
                            "SendCommitmentSigned",
                            "CompleteReceivedCommitment",
                            "CompleteReceivedRevokeAndAck",
                        ), pending
                        self._submit(submission)
                        pending, submission = self._pending(pending["request_id"])
                    else:
                        assert (
                            False
                        ), "ninth payment revocation checkpoint did not appear"
                    assert time.monotonic() < checkpoint_deadline
                    version = int(pending["content"]["slot"]["commitment_number"], 16)
                    records = self.signer_control(self.tenant, "records")
                    assert any(
                        not r["for_remote"]
                        and r["version"] == version
                        and r["complete"]
                        and any(t["payment_hash"] == payment_hash for t in r["tlcs"])
                        for r in records
                    ), "checkpoint must belong to ninth payment"
                    with self.gate.lock:
                        assert not any(
                            s["request_id"] == submission["request_id"]
                            for s, _ in self.gate.forwarded
                        )
                        assert any(
                            t >= payment_started and s == submission
                            for t, s in self.gate.attempts
                        )
                    self._check_payment_window(900)
                    record(
                        "checkpoint",
                        pending=pending,
                        submission=submission,
                        records=records,
                    )
                    self._kill_sdk()
                    saved_store = evidence / "ninth-stopped-snapshot.bin"
                    shutil.copy2(store, saved_store)
                    digest = hashlib.sha256(saved_store.read_bytes()).hexdigest()
                    assert hashlib.sha256(store.read_bytes()).hexdigest() == digest
                    record(
                        "sdk_stopped",
                        pid=self.old_sdk_pid,
                        snapshot_sha256=digest,
                        identity_sha256=hashlib.sha256(
                            json.dumps(self.saved_identity, sort_keys=True).encode()
                        ).hexdigest(),
                    )
                    self._restore_sdk(pending, submission)
                    recovered_pid = self.tenant["agent"].pid
                    record(
                        "sdk_restored",
                        old_pid=original_pid,
                        new_pid=recovered_pid,
                        recovery_seconds=time.monotonic() - payment_started,
                    )
                    self._check_payment_window(180)
                paid, received, after, stability = self._finish_payment()
                if number == 9:
                    self._check_first_forward(submission)
                fee = int(paid["fee"], 16)
                completed.append({"hash": payment_hash, "fee": fee})
                # 3. 逐笔断言复用_finish_payment；累计账本独立从零点计算。
                fees = sum(p["fee"] for p in completed)
                amount = number * 1_000_000
                deltas = (amount, -amount, -amount - fees, amount + fees)
                for old, current, delta in zip(baseline, after, deltas):
                    assert current["channel_id"] == old["channel_id"]
                    assert current["channel_outpoint"] == old["channel_outpoint"]
                    assert (
                        int(current["local_balance"], 16)
                        - int(old["local_balance"], 16)
                        == delta
                    )
                    assert (
                        int(current["remote_balance"], 16)
                        - int(old["remote_balance"], 16)
                        == -delta
                    )
                assert (
                    sum(
                        int(after[i]["local_balance"], 16)
                        - int(baseline[i]["local_balance"], 16)
                        for i in (1, 3)
                    )
                    == fees
                )
                record(
                    "settled",
                    number=number,
                    payment_hash=payment_hash,
                    paid=paid,
                    invoice=received,
                    fee=fee,
                    cumulative_fees=fees,
                    balances=after,
                    stability=stability,
                    duration_seconds=time.monotonic() - payment_started,
                )
                if number in (1, 4, 8, 9, 10):
                    metric(number)
                if number in (9, 10):
                    history = []
                    for old in completed:
                        payment = self.fiber2.client.get_payment(
                            {"payment_hash": old["hash"]}
                        )
                        invoice = self.client.get_invoice({"payment_hash": old["hash"]})
                        assert (
                            payment["status"] == "Success"
                            and invoice["status"] == "Paid"
                        )
                        assert int(payment["fee"], 16) == old["fee"]
                        history.append(
                            {"hash": old["hash"], "paid": payment, "invoice": invoice}
                        )
                    record("history_verified", completed=number, history=history)
            assert len(completed) == len(seen_hashes) == len(seen_preimages) == 10
            record("passed", completed=10, elapsed_seconds=time.monotonic() - started)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            record(
                "finished",
                completed=len(completed),
                elapsed_seconds=time.monotonic() - started,
            )

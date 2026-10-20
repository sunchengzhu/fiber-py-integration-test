"""PR #1623: checked SDK lifecycle and real SDK/FNN process recovery."""

import json
import os
import subprocess
import time

from test_cases.fiber.devnet.lsp._lsp_test import ChannelSigningTestBase, stop_agent


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
                queries = [t for t in self.gate.queries if t >= started]
                attempts = [
                    body
                    for t, body in self.gate.attempts
                    if t >= started and body["request_id"] == pending["request_id"]
                ]
            if queries and attempts and self.tenant["status_file"].exists():
                break
            time.sleep(0.2)
        else:
            assert (
                False
            ), "new SDK process did not query and sign the original pending request"
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
        with self.gate.lock:
            self.gate.pause_queries = True
            self.gate.passthrough = False
        # Drain any in-flight poll before stopping the upstream server.
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
        with self.gate.lock:
            self.gate.pause_queries = False
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

    def _start_payment(self, pause=True):
        payer = self.fiber2.client
        payer.timeout = 10
        payer.try_count = 1
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

    def _finish_payment(self):
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
        for _ in range(5):
            time.sleep(1)
            assert [
                self._snapshot(c, ch) for c, ch in self.payment["endpoints"]
            ] == after
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
        print(
            f"Payment settled once: {self.payment['hash']}, fee={fee}, deltas={deltas}"
        )

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
        pending, submission = self._pending()
        assert not self.gate.forwarded
        self._check_opening_window(900)
        self._kill_sdk()
        assert self._status() == pending
        self._restore_sdk(pending, submission)
        self._check_opening_window(180)
        self._finish_opening()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-03
    def test_sdk_restart_without_learning_applied_result(self):
        first, submission = self._pending()
        self._check_opening_window(900)
        self.gate.arm_fault("lose_response", submission)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert not self.gate.errors, self.gate.errors
            if self.gate.fault_applied is not None:
                break
            time.sleep(0.05)
        else:
            assert False, "upstream did not apply the intercepted signature"
        # No successful response was written; prevent any later query from revealing R2.
        with self.gate.lock:
            self.gate.pause_queries = True
            assert not self.gate.repolled.is_set()
        self._kill_sdk()
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
            assert not self.gate.repolled.is_set()
            self.gate.fault_mode = None
            self.gate.fault_submission = None
            self.gate.pause_queries = False
        self._restore_sdk(following)
        self._submit(submission, "AlreadyApplied")
        assert self._status() == following
        self._check_opening_window(180)
        self._finish_opening()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-04
    def test_hosted_fnn_restart_with_pending_opening_signature(self):
        pending, submission = self._pending()
        assert not self.gate.forwarded
        self._check_opening_window(900)
        self._restart_fnn(pending)
        self._check_opening_window(180)
        self._finish_opening()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-05
    def test_hosted_fnn_restart_preserves_payment_receipt_and_next_request(self):
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
        self._restart_fnn(following)
        self._submit(submission, "AlreadyApplied")
        assert self._status() == following
        self.fiber2.connect_peer(self.fiber1)
        self._check_payment_window(180)
        self._finish_payment()

    # TEST-MAP: LSP-RECOVERY-06
    def test_sdk_restart_preserves_payment_revocation_and_authorizations(self):
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
        self._kill_sdk()
        self._restore_sdk(pending, submission)
        self._check_payment_window(180)
        self._finish_payment()
        self._check_first_forward(submission)

    # TEST-MAP: LSP-RECOVERY-07
    def test_sdk_restart_preserves_close_authorization_and_outputs(self):
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
        self._kill_sdk()
        self._restore_sdk(pending, submission)
        self._finish_close(content["transaction"])
        self._check_first_forward(submission)

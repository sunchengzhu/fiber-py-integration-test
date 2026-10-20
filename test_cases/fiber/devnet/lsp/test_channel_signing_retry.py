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
        original, submission = self._pending()
        self.gate.arm_fault("disconnect", submission)
        self._wait_for_fault_repoll()
        assert self.gate.fault_started is not None
        assert self._status() == original
        assert self.gate.forwarded == []
        print(
            f"SDK retried status after disconnect in "
            f"{self.gate.repolled_at - self.gate.fault_started:.3f}s"
        )
        self._finish_opening()
        with self.gate.lock:
            first_params, first_reply = self.gate.forwarded[0]
        assert first_params == submission
        assert first_reply.get("result") == {"type": "Applied"}, first_reply

    # TEST-MAP: LSP-RETRY-05
    def test_applied_signature_recovers_after_http_timeout(self):
        original, submission = self._pending()
        self.gate.arm_fault("lose_response", submission)
        self._wait_for_fault_repoll()
        assert self.gate.fault_applied is not None
        for _ in range(20):
            if self.gate.client_closed is not None:
                break
            time.sleep(0.1)
        assert (
            self.gate.client_closed is not None
        ), "SDK did not cancel its unacknowledged request"
        print(
            f"SDK cancelled unacknowledged submission in "
            f"{self.gate.client_closed - self.gate.fault_started:.3f}s; "
            f"next status query at {self.gate.repolled_at - self.gate.fault_started:.3f}s"
        )
        following, _ = self._pending(previous=original["request_id"])
        before = self._snapshot(self.client)
        self._submit(submission, "AlreadyApplied")
        assert self._status() == following
        assert self._snapshot(self.client) == before
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

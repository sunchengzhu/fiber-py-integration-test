"""PR #1623: signing-deadline exits, funding aborts, and no-preimage outcomes."""

import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import re
import tempfile
import time

import requests

from test_cases.fiber.devnet.lsp._lsp_test import (
    BUNDLE,
    REVISION,
    ChannelSigningTestBase,
    stop_agent,
)
from test_cases.fiber.devnet.lsp._commitment_broadcast_gate import (
    CommitmentBroadcastGate,
    REMOTE_ERROR,
)
from test_cases.fiber.devnet.lsp._competing_close_observer import CompetingCloseObserver

# These two never send the wallet funding signature, so setup stops before any
# channel signature request exists.
WALLET_HOLD_TESTS = {
    "test_external_funding_timeout_aborts_opening",
    "test_late_wallet_submission_after_abort",
}
ISOLATED_CLOSE_TESTS = {
    "test_node_protects_without_any_submission",
    "test_force_close_uses_commitment_with_target_tlc",
}
RECOVERY_TEST = "test_checkpoint_b_loser_recovers_remote_close"


class _RecoveryBudgetExpired(BaseException):
    """An absolute test deadline that HTTP libraries cannot silently retry."""


def ckb_hash(preimage):
    """Fiber's default CkbHash: blake2b-256 with the CKB personalization."""
    return (
        "0x"
        + hashlib.blake2b(
            bytes.fromhex(preimage.replace("0x", "")),
            digest_size=32,
            person=b"ckb-default-hash",
        ).hexdigest()
    )


def _raw_transaction_hash(tx):
    """CKB Molecule RawTransaction hash (witnesses are not part of the tx ID).

    Checked against real CKB accepted hashes as well as the A spawn hash; this
    distinguishes dependency refreshes that share a canonical signing message.
    """

    def number(value, size=4):
        return (int(value, 16) if isinstance(value, str) else value).to_bytes(
            size, "little"
        )

    def raw(value):
        return bytes.fromhex(value.removeprefix("0x"))

    def fixed(items):
        return number(len(items)) + b"".join(items)

    def table(fields):
        offset = 4 * (len(fields) + 1)
        offsets = []
        for field in fields:
            offsets.append(number(offset))
            offset += len(field)
        return number(offset) + b"".join(offsets) + b"".join(fields)

    def outpoint(value):
        return raw(value["tx_hash"]) + number(value["index"])

    def script(value):
        args = raw(value["args"])
        return table(
            [
                raw(value["code_hash"]),
                bytes(
                    [{"data": 0, "type": 1, "data1": 2, "data2": 4}[value["hash_type"]]]
                ),
                number(len(args)) + args,
            ]
        )

    encoded = table(
        [
            number(tx["version"]),
            fixed(
                [
                    outpoint(d["out_point"])
                    + bytes([{"code": 0, "dep_group": 1}[d["dep_type"]]])
                    for d in tx["cell_deps"]
                ]
            ),
            fixed([raw(h) for h in tx["header_deps"]]),
            fixed(
                [
                    number(i["since"], 8) + outpoint(i["previous_output"])
                    for i in tx["inputs"]
                ]
            ),
            table(
                [
                    table(
                        [
                            number(o["capacity"], 8),
                            script(o["lock"]),
                            script(o["type"]) if o["type"] else b"",
                        ]
                    )
                    for o in tx["outputs"]
                ]
            ),
            table([number(len(raw(d))) + raw(d) for d in tx["outputs_data"]]),
        ]
    )
    return (
        "0x"
        + hashlib.blake2b(
            encoded, digest_size=32, person=b"ckb-default-hash"
        ).hexdigest()
    )


class TestChannelSigningDeadline(ChannelSigningTestBase):
    # Save signatures without converting this deliberate checkpoint into subscription
    # reconnect failures and exponential backoff. Python submits the real result.
    agent_extra_args = ("--ack-held-events",)
    # The hosting FNN runs with a 180 s opening timeout and a 60 s external
    # funding timeout, both written into its own config by the suite base.
    opening_window_seconds = 180
    opening_window_margin = 60
    fiber_config_extra = {
        "funding_timeout_seconds": 180,
        "external_funding_timeout_seconds": 60,
    }
    tlc_amount = 1_000_000
    # Both A and T can protect at this deadline. Only 08/10 isolate T's broadcast.
    tlc_lifetime_seconds = 22

    def setup_method(self, method):
        self.broadcast_gate = None
        if method.__name__ == RECOVERY_TEST:
            root = os.environ.get("LSP_RECOVERY_ARTIFACTS")
            self.recovery_directory = (
                Path(root)
                if root
                else Path(tempfile.mkdtemp(prefix="lsp-loser-recovery-", dir="report"))
                / "case"
            )
            self.recovery_directory.mkdir(parents=True, exist_ok=False)
            self.recovery_evidence = {
                "revision": REVISION,
                "case": "LSP-TIMEOUT-12",
                "result": "incomplete",
                "observations": [],
            }
            self.recovery_observer = CompetingCloseObserver(
                self.node.rpcUrl, self.recovery_directory
            )
            self.start_fiber_config = {
                **self.start_fiber_config,
                "ckb_rpc_url": self.recovery_observer.url,
            }
            self.addCleanup(self._recovery_cleanup)
        if method.__name__ in ISOLATED_CLOSE_TESTS:
            self.deadline_evidence = {"test": method.__name__, "observations": []}
            self.broadcast_gate = CommitmentBroadcastGate(
                self.node.rpcUrl, BUNDLE / "lsp-integration-driver"
            )
            self.start_fiber_config = {
                **self.start_fiber_config,
                "ckb_rpc_url": self.broadcast_gate.url,
            }
            # Registered first: SDK and FNN cleanup runs before the chain proxy.
            self.addCleanup(self._close_broadcast_gate)
        try:
            super().setup_method(method)
        except BaseException:
            if self.broadcast_gate is not None or method.__name__ == RECOVERY_TEST:
                self.doCleanups()
            raise

    def _close_broadcast_gate(self):
        try:
            for fiber in getattr(self, "fibers", []):
                process = getattr(fiber, "process", None)
                if process is not None:
                    stop_agent(process)
            self._stop_owned_miner(time.monotonic() + 5)
        finally:
            self.broadcast_gate.stop()
            self.deadline_evidence["broadcasts"] = self.broadcast_gate.snapshot()
            directory = (
                Path(
                    os.environ.get(
                        "LSP_DEADLINE_ARTIFACTS", "report/lsp-timeout-isolated"
                    )
                )
                / self._testMethodName
            )
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "evidence.json").write_text(
                json.dumps(self.deadline_evidence, indent=2) + "\n"
            )
            node_path = Path(self.fiber1.tmp_path) if hasattr(self, "fiber1") else None
            for label, path in (
                ("fnn.log", node_path / "node.log" if node_path else None),
                ("sdk.log", node_path / "sdk-A/agent.log" if node_path else None),
                ("ckb.log", Path(self.node.ckb_dir) / "data/logs/run.log"),
                ("ckb-stdout.log", Path(self.node.ckb_dir) / "node.log"),
            ):
                if path is not None and path.exists():
                    shutil.copy2(path, directory / label)
            print(f"isolated deadline evidence: {directory}")
            assert not self.deadline_evidence["broadcasts"][
                "errors"
            ], self.deadline_evidence["broadcasts"]["errors"]

    def setUp(self):
        if self._testMethodName in WALLET_HOLD_TESTS:
            self.submit_external_funding = False
        super().setUp()

    def _finish_opening(self):
        # The deliberately held event has been consumed. Submit its real saved
        # signature explicitly; release first so the following event can proceed.
        _, submission = self._pending()
        self.gate.release()
        self._submit(submission)
        super()._finish_opening()

    # ---------------------------------------------------------------- helpers

    def _channel_view(self, client):
        channels = client.list_channels({"include_closed": True})["channels"]
        return next((c for c in channels if c["channel_id"] == self.channel_id), None)

    def _abort_entry(self, client):
        """The synthesized failure entry only, never the in-progress opening."""
        channels = client.list_channels({"only_pending": True})["channels"]
        entry = next((c for c in channels if c["channel_id"] == self.channel_id), None)
        if entry is None:
            return None
        state = entry["state"]
        if (
            state["state_name"] == "Closed"
            and "FUNDING_ABORTED" in state["state_flags"]
        ):
            return entry
        return None

    def _wait_abort(self, timeout):
        deadline = time.monotonic() + timeout
        entry = None
        while time.monotonic() < deadline:
            entry = self._abort_entry(self.client)
            if entry is not None:
                return entry
            time.sleep(1)
        assert False, f"opening was not aborted within {timeout}s: {entry}"

    def _assert_funding_aborted(self, entry):
        assert entry["state"]["state_name"] == "Closed", entry
        assert "FUNDING_ABORTED" in entry["state"]["state_flags"], entry

    def _assert_inputs_unspent(self, unsigned_tx):
        ckb = self.node.getClient()
        for cell_input in unsigned_tx["inputs"]:
            previous = cell_input["previous_output"]
            cell = ckb.get_live_cell(previous["index"], previous["tx_hash"])
            assert cell["status"] == "live", (previous, cell)

    def _assert_funding_not_on_chain(self, tx_hash):
        tx = self.node.getClient().get_transaction(tx_hash)
        assert tx["tx_status"]["status"] == "unknown", tx

    def _funding_outpoint(self, view):
        raw = bytes.fromhex(view["channel_outpoint"][2:])
        return {
            "tx_hash": "0x" + raw[:32].hex(),
            "index": hex(int.from_bytes(raw[32:], "little")),
        }

    def _commitment_hash(self, client):
        view = self._channel_view(client)
        assert view is not None, "channel disappeared"
        return view["latest_commitment_transaction_hash"]

    def _invoice_status(self, payment_hash):
        return self.client.get_invoice({"payment_hash": payment_hash})["status"]

    def _submit_raw(self, submission, timeout=10):
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                self.client.url,
                headers=self.client.other_params,
                json={
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "submit_channel_signature",
                    "params": [submission],
                },
                timeout=timeout,
            )
        response.raise_for_status()
        return response.json()

    def _assert_not_applied(self, body):
        assert body.get("result") is None, body
        assert "error" in body, body

    # ------------------------------------------------------- payment fixture

    def _new_hold_invoice(self, expiry_seconds):
        preimage = self.generate_random_preimage()
        payment_hash = ckb_hash(preimage)
        invoice = self.client.new_invoice(
            {
                "amount": hex(self.tlc_amount),
                "currency": "Fibd",
                "expiry": hex(expiry_seconds),
                "payment_hash": payment_hash,
                "hash_algorithm": "ckb_hash",
                "final_expiry_delta": hex(self.tlc_lifetime_seconds * 1000),
                "allow_mpp": False,
                "allow_trampoline_routing": False,
            }
        )
        assert invoice["invoice"]["data"]["payment_hash"] == payment_hash, invoice
        now_ms = int(time.time() * 1000)
        self.signer_control(
            self.tenant,
            "invoice",
            {
                "authorization": {
                    "payment_hash": payment_hash,
                    "hash_algorithm": "ckb_hash",
                    "inbound": True,
                    "amount": self.tlc_amount,
                    "expires_at_ms": now_ms + 300_000,
                    "min_tlc_expiry_delta_ms": 5_000,
                    "max_tlc_expiry_ms": now_ms + 600_000,
                },
                "preimage": preimage,
            },
        )
        return payment_hash, preimage, now_ms

    def _inject_tlc(self, payment_hash, lifetime_seconds):
        expiry_ms = int(time.time() * 1000) + lifetime_seconds * 1000
        result = self.fiber1.client.call(
            "add_tlc",
            [
                {
                    "channel_id": self.channel_id,
                    "amount": hex(self.tlc_amount),
                    "payment_hash": payment_hash,
                    "expiry": hex(expiry_ms),
                    "hash_algorithm": "ckb_hash",
                }
            ],
        )
        return result["tlc_id"]

    def _wait_tlc(self, payment_hash, timeout=30):
        deadline = time.monotonic() + timeout
        tlcs = []
        while time.monotonic() < deadline:
            tlcs = self._channel(self.client)["pending_tlcs"]
            if any(t["payment_hash"] == payment_hash for t in tlcs):
                return
            time.sleep(0.5)
        assert False, f"injected TLC did not reach the tenant: {tlcs}"

    def _tlc_expiry(self, payment_hash):
        tlcs = self._channel(self.client)["pending_tlcs"]
        found = [
            int(t["expiry"], 16) for t in tlcs if t["payment_hash"] == payment_hash
        ]
        assert len(found) == 1, tlcs
        return found[0]

    def _prepare_payment(self, lifetime_seconds=None, expiry_seconds=90):
        """Checkpoint A: TLC visible and a real signature request held by the gate."""
        lifetime_seconds = lifetime_seconds or self.tlc_lifetime_seconds
        payment_hash, preimage, created_ms = self._new_hold_invoice(expiry_seconds)
        commitment_before = self._commitment_hash(self.client)
        injected_at = time.monotonic()
        tlc_id = self._inject_tlc(payment_hash, lifetime_seconds)
        self._wait_tlc(payment_hash)
        status, submission = self._pending()
        assert self._invoice_status(payment_hash) == "Open"
        print(
            f"checkpoint A commitment={self._commitment_hash(self.client)} "
            f"before={commitment_before} invoice=Open"
        )
        expiry = self._tlc_expiry(payment_hash)
        return {
            "hash": payment_hash,
            "preimage": preimage,
            "tlc_id": tlc_id,
            "expiry": expiry,
            "deadline": expiry - 1333,
            "invoice_expires_at": created_ms / 1000 + expiry_seconds,
            "commitment_before": commitment_before,
            "request": status,
            "submission": submission,
            "injected_at": injected_at,
        }

    def _to_checkpoint_b(self, payment):
        """Apply the TLC commitment signature and hold the next request."""
        previous = payment["request"]["request_id"]
        self._submit(payment["submission"])
        status, submission = self._pending(previous=previous)
        assert status["transition"] == "SendRevokeAndAck", status
        payment["b_request"] = status
        payment["b_submission"] = submission
        records = self.signer_control(self.tenant, "records")
        print(
            f"checkpoint B commitment={self._commitment_hash(self.client)} "
            f"records={[(r['version'], r['complete'], [t['payment_hash'][:12] for t in r['tlcs']]) for r in records]}"
        )
        assert self._commitment_hash(self.client) != payment["commitment_before"]
        signed = [
            record
            for record in records
            if record["complete"]
            and not record["for_remote"]
            and record["transaction_hash"] == self._commitment_hash(self.client)
        ]
        assert len(signed) == 1, records
        assert any(
            t["payment_hash"] == payment["hash"] and t["expiry"] == payment["expiry"]
            for t in signed[0]["tlcs"]
        ), signed
        assert self._invoice_status(payment["hash"]) == "Open"
        return payment

    def _next_or_done(self, previous, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._status()
            if status["type"] == "NoSignatureRequired":
                return None
            if (
                status["type"] == "SignatureRequired"
                and status["request_id"] != previous
            ):
                with self.gate.lock:
                    submission = copy.deepcopy(
                        self.gate.submissions.get(status["request_id"])
                    )
                if submission is not None:
                    return status, submission
            time.sleep(0.2)
        return None

    def _drive_to_received(self, payment):
        """Apply every remaining request until the hold invoice turns Received."""
        if "b_submission" in payment:
            previous = payment["b_request"]["request_id"]
            self._submit(payment["b_submission"])
        else:
            previous = payment["request"]["request_id"]
            self._submit(payment["submission"])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (
                self._invoice_status(payment["hash"]) == "Received"
                and self._status()["type"] == "NoSignatureRequired"
            ):
                return
            following = self._next_or_done(previous, timeout=10)
            if following is not None:
                previous = following[0]["request_id"]
                self._submit(following[1])
        assert False, (
            f"invoice did not turn Received: {self._invoice_status(payment['hash'])}, "
            f"{self._status()['type']}"
        )

    def _wait_past_deadline(self, payment, extra_seconds=1.0):
        target = payment["deadline"] / 1000 + extra_seconds
        while time.time() < target:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            time.sleep(0.2)
        return time.monotonic()

    def _wait_protection(self, timeout=15):
        deadline = time.monotonic() + timeout
        view = None
        while time.monotonic() < deadline:
            view = self._channel_view(self.client)
            if view and view["state"]["state_name"] == "ShuttingDown":
                assert (
                    "WAITING_COMMITMENT_CONFIRMATION" in view["state"]["state_flags"]
                ), view
                return view, time.monotonic()
            time.sleep(0.5)
        assert False, f"deadline protection did not start: {view}"

    def _confirm_transaction(self, tx_hash, timeout=60):
        deadline = time.monotonic() + timeout
        tx = None
        while time.monotonic() < deadline:
            tx = self.node.getClient().get_transaction(tx_hash)
            status = tx["tx_status"]["status"]
            assert status != "rejected", tx
            if status == "committed":
                return tx
            self.Miner.miner_with_version(self.node, "0x0")
            time.sleep(1)
        assert False, f"transaction did not confirm: {tx}"

    def _confirm_force_close(self, funding, timeout=60):
        """Wait for this side's closing transaction to confirm and spend the funding."""
        deadline = time.monotonic() + timeout
        view = None
        tx_hash = None
        while time.monotonic() < deadline:
            view = self._channel_view(self.client)
            if view and view["shutdown_transaction_hash"]:
                tx_hash = view["shutdown_transaction_hash"]
                tx = self.node.getClient().get_transaction(tx_hash)
                if tx["tx_status"]["status"] == "committed":
                    assert tx["transaction"]["inputs"][0]["previous_output"] == {
                        "tx_hash": funding["tx_hash"],
                        "index": funding["index"],
                    }, tx["transaction"]
                    return view, tx
            self.Miner.miner_with_version(self.node, "0x0")
            time.sleep(1)
        assert False, f"force close did not confirm: {tx_hash}, {view}"

    def _assert_force_close_uses(self, funding, commitment_after):
        records = self.signer_control(self.tenant, "records")
        signed = [
            record
            for record in records
            if record["complete"]
            and not record["for_remote"]
            and record["transaction_hash"] == commitment_after
        ]
        assert len(signed) == 1, records
        view, observed_at = self._wait_protection()
        # Force close refreshes cell_deps. Bind the confirmed transaction to the
        # exact SDK-verified commitment using Fiber's signed transaction message,
        # which excludes deps and witnesses, rather than comparing different hashes.
        assert view["latest_commitment_transaction_hash"] == commitment_after, view
        closed, tx = self._confirm_force_close(funding)
        assert closed["state"]["state_name"] == "Closed", closed
        assert closed["shutdown_transaction_hash"], closed
        # CKB returns a TransactionView; its hash is RPC metadata, not part of
        # the Transaction accepted by the canonical-message decoder.
        transaction = tx["transaction"].copy()
        transaction.pop("hash")
        message = subprocess.check_output(
            [str(BUNDLE / "lsp-integration-driver"), "commitment-message"],
            input=json.dumps(transaction),
            text=True,
        ).strip()
        assert message == signed[0]["signing_message"], (
            "confirmed close does not match the saved signed commitment",
            message,
            signed[0],
        )
        peer = self._channel_view(self.fiber1.client)
        if peer and peer["shutdown_transaction_hash"]:
            assert (
                peer["shutdown_transaction_hash"] != closed["shutdown_transaction_hash"]
            )
        return view, tx, observed_at

    def _arm_signature_gate(self):
        """After the opening finished, hold the next channel signature again."""
        self._finish_opening()
        with self.gate.lock:
            self.gate.passthrough = False
        assert self._status()["type"] == "NoSignatureRequired"

    # These bounded observations are exclusive to the reviewed 08/10 isolation.
    def _remaining(self, until, cap=10):
        remaining = until - time.monotonic()
        assert remaining > 0, "isolated deadline observation budget exhausted"
        return min(cap, remaining)

    def _observe(self, stage, **values):
        entry = {
            "stage": stage,
            "monotonic": time.monotonic(),
            "wall_ms": time.time() * 1000,
            **values,
        }
        self.deadline_evidence["observations"].append(entry)
        print(f"deadline {stage}: {json.dumps(entry)}")

    def _isolated_rpc(self, client, method, params, until):
        url = client if isinstance(client, str) else client.url
        headers = {} if isinstance(client, str) else client.other_params
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 81, "method": method, "params": params},
                timeout=self._remaining(until),
            )
            response.raise_for_status()
            body = response.json()
        self._remaining(until)
        assert "error" not in body and "result" in body, (method, body)
        return body["result"]

    def _isolated_view(self, client, until):
        channels = self._isolated_rpc(
            client, "list_channels", [{"include_closed": True}], until
        )["channels"]
        matches = [c for c in channels if c["channel_id"] == self.channel_id]
        assert len(matches) == 1, channels
        return matches[0]

    def _isolated_status(self, until):
        return self._isolated_rpc(
            self.client,
            "get_channel_signing_status",
            [{"channel_id": self.channel_id}],
            until,
        )["status"]

    def _isolated_records(self, until):
        payload = {"operation": "records", "channel_id": self.channel_id}
        with socket.create_connection(
            ("127.0.0.1", self.tenant["control_port"]),
            timeout=self._remaining(until),
        ) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode())
            data = b""
            while b"\n" not in data:
                connection.settimeout(self._remaining(until))
                part = connection.recv(65536)
                assert part, "SDK records connection closed without a reply"
                data += part
            reply = json.loads(data.split(b"\n", 1)[0])
        self._remaining(until)
        assert "error" not in reply, reply
        return reply["result"]

    def _isolation_health(self, until):
        self._remaining(until)
        assert self.tenant["agent"].poll() is None, "SDK exited"
        assert self.fiber1.process.poll() is None, "hosting FNN exited"
        assert not self.gate.errors, self.gate.errors
        audit = self.broadcast_gate.snapshot()
        assert not audit["errors"], audit["errors"]
        return audit

    def _isolated_pending(self, until, previous=None):
        while True:
            self._isolation_health(until)
            status = self._isolated_status(until)
            if status["type"] == "SignatureRequired":
                with self.gate.lock:
                    submission = copy.deepcopy(
                        self.gate.submissions.get(status["request_id"])
                    )
                if submission is not None and status["request_id"] != previous:
                    return status, submission
            time.sleep(min(0.2, self._remaining(until)))

    def _stop_owned_miner(self, until):
        pid = self.node.ckb_miner_pid
        self.node.stop_miner()
        if pid <= 0:
            return pid
        while True:
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    return pid
            except ChildProcessError:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return pid
            time.sleep(min(0.05, self._remaining(until)))

    def _pause_isolated_miner(self):
        until = time.monotonic() + 10
        view = self._isolated_view(self.client, until)
        assert view["state"]["state_name"] == "ChannelReady", view
        funding = self._funding_outpoint(view)
        tx = self._isolated_rpc(
            self.node.rpcUrl, "get_transaction", [funding["tx_hash"]], until
        )
        assert tx["tx_status"]["status"] == "committed", tx
        while True:
            indexer = self._isolated_rpc(self.node.rpcUrl, "get_indexer_tip", [], until)
            if indexer and int(indexer["block_number"], 16) >= int(
                tx["tx_status"]["block_number"], 16
            ):
                break
            time.sleep(min(0.1, self._remaining(until)))
        # stop_miner sends SIGTERM but does not reap/wait for its child.
        until = time.monotonic() + 5
        pid = self._stop_owned_miner(until)
        assert pid > 0, "expected this test's background miner"
        stable_since, last_tip = None, None
        while True:
            self._remaining(until)
            tip = self._isolated_rpc(
                self.node.rpcUrl, "get_tip_block_number", [], until
            )
            if tip != last_tip:
                stable_since = time.monotonic()
            last_tip = tip
            if stable_since is not None and time.monotonic() - stable_since >= 1:
                self._observe("miner_paused", pid=pid, tip=tip, funding=funding)
                return funding
            time.sleep(min(0.1, self._remaining(until)))

    def _prepare_isolated_close(self, checkpoint):
        self._arm_signature_gate()
        funding = self._pause_isolated_miner()
        invoice_seconds = 180 if checkpoint == "B" else 90
        payment_hash, _, _ = self._new_hold_invoice(invoice_seconds)
        until = time.monotonic() + 10
        invoice = self._isolated_rpc(
            self.client, "get_invoice", [{"payment_hash": payment_hash}], until
        )
        timestamp = invoice["invoice"]["data"]["timestamp"]
        created_ms = int(timestamp, 16) if isinstance(timestamp, str) else timestamp
        before = self._isolated_view(self.client, until)[
            "latest_commitment_transaction_hash"
        ]
        # This preparation cap is conservative: the actual TLC timestamp is read back below.
        until = time.monotonic() + self.tlc_lifetime_seconds - 1.333 - 5
        self._inject_tlc(payment_hash, self.tlc_lifetime_seconds)
        status, submission = self._isolated_pending(until)
        view = self._isolated_view(self.client, until)
        tlcs = [t for t in view["pending_tlcs"] if t["payment_hash"] == payment_hash]
        assert len(tlcs) == 1, view
        expiry = int(tlcs[0]["expiry"], 16)
        deadline_ms = expiry - 1333
        deadline = time.monotonic() + deadline_ms / 1000 - time.time()
        until = min(until, deadline - 5)
        if checkpoint == "B":
            body = self._submit_raw(submission, timeout=self._remaining(until))
            assert body.get("result") == {"type": "Applied"}, body
            status, submission = self._isolated_pending(until, status["request_id"])
            assert status["transition"] == "SendRevokeAndAck", status
        local = self._isolated_view(self.client, until)
        remote = self._isolated_view(self.fiber1.client, until)
        records = self._isolated_records(until)
        local_hash = local["latest_commitment_transaction_hash"]
        remote_hash = remote["latest_commitment_transaction_hash"]
        local_records = [
            r
            for r in records
            if r["complete"]
            and not r["for_remote"]
            and r["transaction_hash"] == local_hash
        ]
        remote_records = [
            r
            for r in records
            if r["for_remote"] and r["transaction_hash"] == remote_hash
        ]
        assert len(local_records) == len(remote_records) == 1, records
        signed, peer_signed = local_records[0], remote_records[0]
        assert signed["signing_message"] != peer_signed["signing_message"]
        target_tlcs = [t for t in signed["tlcs"] if t["payment_hash"] == payment_hash]
        if checkpoint == "A":
            assert local_hash == before and not target_tlcs, signed
        else:
            assert local_hash != before and len(target_tlcs) == 1, signed
            assert target_tlcs[0]["expiry"] == expiry, signed
            assert deadline_ms / 1000 + 95 < created_ms / 1000 + invoice_seconds
        assert (
            self._isolated_rpc(
                self.client, "get_invoice", [{"payment_hash": payment_hash}], until
            )["status"]
            == "Open"
        )
        local = self._isolated_view(self.client, until)
        assert local["latest_commitment_transaction_hash"] == local_hash
        assert (
            self._isolated_view(self.fiber1.client, until)[
                "latest_commitment_transaction_hash"
            ]
            == remote_hash
        )
        assert local["state"]["state_name"] == "ChannelReady", local
        assert self._isolated_status(until) == status
        assert (
            self._isolated_rpc(
                self.node.rpcUrl, "get_live_cell", [funding, False], until
            )["status"]
            == "live"
        )
        self.broadcast_gate.arm(
            funding,
            signed["signing_message"],
            peer_signed["signing_message"],
            deadline_ms,
        )
        self._remaining(until)
        with self.gate.lock:
            forwarded = copy.deepcopy(self.gate.forwarded)
        payment = {
            "hash": payment_hash,
            "expiry": expiry,
            "deadline_ms": deadline_ms,
            "deadline": deadline,
            "until": deadline + (95 if checkpoint == "B" else 110),
            "invoice_expires_at": created_ms / 1000 + invoice_seconds,
            "funding": funding,
            "local": signed,
            "remote": peer_signed,
            "request": status,
            "submission": submission,
            "forwarded": forwarded,
        }
        self._observe(
            "armed",
            checkpoint=checkpoint,
            payment_hash=payment_hash,
            expiry=expiry,
            deadline_ms=deadline_ms,
            invoice_expires_at=payment["invoice_expires_at"],
            local_record=signed,
            remote_record=peer_signed,
            request_id=status["request_id"],
        )
        return payment

    def _confirm_isolated_close(self, payment):
        until = payment["deadline"] + 15
        while True:
            audit = self._isolation_health(until)
            view = self._isolated_view(self.client, until)
            local = [
                e
                for e in audit["events"]
                if e["classification"] == "local" and e.get("actual_hash")
            ]
            remote = [
                e
                for e in audit["events"]
                if e["classification"] == "remote"
                and e["outcome"] == "blocked"
                and e["response"].get("error") == REMOTE_ERROR
            ]
            if local and remote and view["state"]["state_name"] == "ShuttingDown":
                assert (
                    "WAITING_COMMITMENT_CONFIRMATION" in view["state"]["state_flags"]
                ), view
                break
            time.sleep(min(0.2, self._remaining(until)))
        for event in local + remote:
            assert (
                payment["deadline_ms"]
                <= event["received_wall_ms"]
                <= payment["deadline_ms"] + 15_000
            ), event
        self._observe(
            "protection",
            state=view["state"],
            local_sends=len(local),
            remote_blocks=len(remote),
        )
        first_forward = min(
            e["forwarded_monotonic"]
            for e in audit["events"]
            if e["classification"] == "local" and e["forwarded_monotonic"] is not None
        )
        until = min(payment["until"], first_forward + 60)
        assert self._remaining(until, 60) > 3, "no budget to resume miner"
        self.node.start_miner()
        self._remaining(until)
        tx_hash = local[0]["actual_hash"]
        while True:
            self._isolation_health(until)
            tx = self._isolated_rpc(
                self.node.rpcUrl, "get_transaction", [tx_hash], until
            )
            assert tx["tx_status"]["status"] != "rejected", tx
            if tx["tx_status"]["status"] == "committed":
                committed_at = time.monotonic()
                self._observe("chain_confirmation", hash=tx_hash, response=tx)
                break
            time.sleep(min(0.2, self._remaining(until)))
        transaction = copy.deepcopy(tx["transaction"])
        transaction.pop("hash", None)
        assert any(
            i["previous_output"] == payment["funding"] for i in transaction["inputs"]
        ), transaction
        cell = self._isolated_rpc(
            self.node.rpcUrl, "get_live_cell", [payment["funding"], False], until
        )
        # CKB 0.202 deprecates 'dead': spent cells normally return 'unknown'.
        # The committed transaction's exact input above proves the spend;
        # 'unknown' by itself would not prove it (docs/rpc.md:5853 in the bundle).
        assert cell["status"] in ("dead", "unknown") and cell["cell"] is None, cell
        message = subprocess.check_output(
            [str(BUNDLE / "lsp-integration-driver"), "commitment-message"],
            input=json.dumps(transaction),
            text=True,
            timeout=self._remaining(until),
        ).strip()
        assert message == payment["local"]["signing_message"]
        assert message != payment["remote"]["signing_message"]
        self._observe(
            "committed",
            hash=tx_hash,
            transaction=transaction,
            signing_message=message,
            funding_cell=cell,
        )
        until = min(payment["until"], committed_at + 15)
        while True:
            self._isolation_health(until)
            view = self._isolated_view(self.client, until)
            if view["state"]["state_name"] == "Closed":
                closed_at = time.monotonic()
                break
            time.sleep(min(0.2, self._remaining(until)))
        assert "UNCOOPERATIVE_LOCAL" in view["state"]["state_flags"], view
        assert view["shutdown_transaction_hash"] == tx_hash, view
        assert (
            view["latest_commitment_transaction_hash"]
            == payment["local"]["transaction_hash"]
        ), view
        with self.gate.lock:
            assert (
                self.gate.forwarded == payment["forwarded"]
            ), "SDK forwarded a held signature"
        assert not any(op == "fulfill" for op, _ in self.tenant["control_calls"])
        self._observe("local_closed", view=view)
        self._remaining(until)
        return view, until, closed_at

    def _closed_snapshot(self, until):
        view = self._isolated_view(self.client, until)
        return {
            "view": {
                k: v
                for k, v in view.items()
                if k
                in (
                    "state",
                    "shutdown_transaction_hash",
                    "latest_commitment_transaction_hash",
                    "local_commitment_number",
                    "remote_commitment_number",
                )
            },
            "complete_records": [
                r for r in self._isolated_records(until) if r["complete"]
            ],
            "signing_status": self._isolated_status(until),
        }

    # -------------------------------------------------------- opening cases

    # SPEC-09 helpers are exclusive to 12; the 08/10 isolation stays unchanged.
    @contextmanager
    def _recovery_budget(self, until, cap):
        now = time.monotonic()
        previous = signal.getitimer(signal.ITIMER_REAL)
        old_handler = signal.getsignal(signal.SIGALRM)
        depth = getattr(self, "_recovery_alarm_depth", 0)
        assert not previous[0] or depth, "another timer owns SIGALRM"
        old_due = now + previous[0] if previous[0] else None
        due = min(until, now + cap, getattr(self, "recovery_until", float("inf")))
        if old_due is not None:
            due = min(due, old_due)
        if due <= now:
            raise _RecoveryBudgetExpired("absolute recovery deadline exhausted")

        def expired(*_args):
            raise _RecoveryBudgetExpired(f"recovery operation exceeded {due:.6f}")

        self._recovery_alarm_depth = depth + 1
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, due - time.monotonic()))
        try:
            yield due
            if time.monotonic() > due:
                raise _RecoveryBudgetExpired("late recovery result is diagnostic only")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            self._recovery_alarm_depth = depth
            if old_due is not None and old_due > time.monotonic():
                signal.setitimer(signal.ITIMER_REAL, old_due - time.monotonic())

    def _recovery_rpc(self, client, method, params, until):
        url = client if isinstance(client, str) else client.url
        headers = {} if isinstance(client, str) else client.other_params
        with self._recovery_budget(until, 1) as due:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(
                    url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 91,
                        "method": method,
                        "params": params,
                    },
                    timeout=max(0.001, due - time.monotonic()),
                )
                response.raise_for_status()
                body = response.json()
                assert "error" not in body and "result" in body, (method, body)
                return body["result"]

    def _recovery_view(self, client, until):
        channels = self._recovery_rpc(
            client, "list_channels", [{"include_closed": True}], until
        )["channels"]
        found = [c for c in channels if c["channel_id"] == self.channel_id]
        assert len(found) == 1, ("channel missing or ambiguous", channels)
        return found[0]

    def _recovery_status(self, until):
        return self._recovery_rpc(
            self.client,
            "get_channel_signing_status",
            [{"channel_id": self.channel_id}],
            until,
        )["status"]

    def _recovery_pending(self, until, previous=None):
        while time.monotonic() < until:
            status = self._recovery_status(until)
            if status["type"] == "SignatureRequired":
                with self.gate.lock:
                    submission = copy.deepcopy(
                        self.gate.submissions.get(status["request_id"])
                    )
                if submission and status["request_id"] != previous:
                    return status, submission
            self._recovery_health()
            time.sleep(max(0, min(0.1, until - time.monotonic())))
        raise AssertionError("checkpoint B preparation deadline exhausted")

    def _recovery_record(self, stage, **values):
        item = {"stage": stage, "monotonic": time.monotonic(), **values}
        self.recovery_evidence["observations"].append(item)
        with (self.recovery_directory / "observations.jsonl").open("a") as stream:
            stream.write(json.dumps(item) + "\n")
        return item

    def _recovery_health(self):
        for fiber in self.fibers:
            if fiber.process.poll() is not None:
                self._recovery_fail(
                    "runtime_failure_product_not_excluded", "FNN exited"
                )
        if self.tenant["agent"].poll() is not None:
            self._recovery_fail("runtime_failure_product_not_excluded", "SDK exited")
        for label, pid in (
            ("CKB", self.node.ckb_pid),
            ("miner", self.node.ckb_miner_pid),
        ):
            pid = int(pid)
            assert pid > 0, (label, pid)
            os.kill(pid, 0)
        with self.gate.lock:
            assert not self.gate.errors, self.gate.errors
            if hasattr(self, "recovery_forwarded"):
                assert (
                    self.gate.forwarded == self.recovery_forwarded
                ), "new signature forwarded"
        assert not self.recovery_observer.snapshot()[
            "errors"
        ], self.recovery_observer.snapshot()["errors"]

    def _recovery_fail(self, kind, message):
        self.recovery_evidence["result"] = kind
        raise AssertionError(message)

    def _recovery_decode(self, tx, until):
        transaction = {key: value for key, value in tx.items() if key != "hash"}
        with self._recovery_budget(until, 1) as due:
            return subprocess.check_output(
                [str(BUNDLE / "lsp-integration-driver"), "commitment-message"],
                input=json.dumps(transaction),
                text=True,
                timeout=max(0.001, due - time.monotonic()),
            ).strip()

    def _recovery_broadcasts(self, payment, until):
        events = self.recovery_observer.snapshot()["events"]
        found = {"A": [], "T": []}
        for event in events:
            if payment["funding"] not in event["inputs"]:
                continue
            assert (
                event["received_monotonic"] >= payment["deadline"]
            ), "early funding spend"
            if not event.get("response"):
                continue
            key = event["raw_request"]
            if key not in self.recovery_decoded:
                message = self._recovery_decode(event["transaction"], until)
                roles = [
                    side
                    for side in ("A", "T")
                    if payment[side]["signing_message"] == message
                ]
                assert len(roles) == 1, ("unknown target funding spend", event)
                self.recovery_decoded[key] = roles[0]
                self._recovery_record(
                    "broadcast_classified", side=roles[0], message=message, event=event
                )
            found[self.recovery_decoded[key]].append(event)
        return found

    def _recovery_timing(self, payment, accepted, rejected, t_commit=None):
        timing = self.recovery_observer.timing_snapshot()
        episode, delayed = timing["episode"], timing["delayed_queries"]
        assert episode and delayed, "fixed query window did not activate"
        assert (
            _raw_transaction_hash(rejected["transaction"])
            == episode["transaction_hash"]
        ), "A rejected transaction differs from delayed hash"
        assert (
            _raw_transaction_hash(accepted["transaction"]) == accepted["actual_hash"]
        ), "T raw transaction hash differs from CKB acceptance"
        start, release = episode["started_at"], episode["release_at"]
        assert start >= payment["deadline"] and abs(release - start - 0.250) < 0.000001
        assert start <= accepted["forwarded_monotonic"] < release, accepted
        assert start <= accepted["upstream_response_monotonic"] < release, accepted
        preflight = [
            q
            for q in delayed
            if q["request"]["params"] == [episode["transaction_hash"], "0x0", True]
        ]
        assert preflight, "only tracer was delayed; broadcaster preflight is missing"
        assert any(
            q.get("response_written_monotonic", float("inf"))
            <= rejected["forwarded_monotonic"]
            for q in preflight
        )
        for query in delayed:
            written = query.get("response_written_monotonic")
            assert written is not None and release <= written <= release + 0.100, query
            assert query["upstream_response_monotonic"] <= written
            assert query["response"]["result"]["tx_status"]["status"] == "unknown"
            if t_commit is not None:
                assert (
                    written < t_commit
                ), "query delay remained active after observed confirmation"
        return timing

    def _recovery_sample(self, payment, winner_hash, until):
        started = time.monotonic()
        with self._recovery_budget(until, 3) as due:
            self._recovery_health()
            sample = {
                "started": started,
                "local": self._recovery_view(self.client, due),
                "signing": self._recovery_status(due),
            }
            sample["tip"] = self._recovery_rpc(
                self.node.rpcUrl, "get_tip_block_number", [], due
            )
            sample["indexer_tip"] = self._recovery_rpc(
                self.node.rpcUrl, "get_indexer_tip", [], due
            )
            sample["transaction"] = (
                self._recovery_rpc(
                    self.node.rpcUrl, "get_transaction", [winner_hash], due
                )
                if winner_hash
                else None
            )
            sample["tx_observed"] = time.monotonic()
            sample["indexed_input"] = None
            tx = sample["transaction"]
            if tx and tx["tx_status"]["status"] == "committed":
                assert tx["transaction"]["hash"] == winner_hash
                assert payment["funding"] in [
                    i["previous_output"] for i in tx["transaction"]["inputs"]
                ]
                cursor = None
                pages = []
                for _ in range(3):
                    params = [
                        {
                            "script": payment["funding_lock"],
                            "script_type": "lock",
                            "script_search_mode": "exact",
                            "group_by_transaction": False,
                        },
                        "desc",
                        "0x64",
                    ]
                    if cursor is not None:
                        params.append(cursor)
                    page = self._recovery_rpc(
                        self.node.rpcUrl, "get_transactions", params, due
                    )
                    pages.append(page)
                    for entry in page["objects"]:
                        if (
                            entry["tx_hash"] == winner_hash
                            and entry["io_type"] == "input"
                        ):
                            index = int(entry["io_index"], 16)
                            assert index < len(tx["transaction"]["inputs"]), entry
                            if (
                                tx["transaction"]["inputs"][index]["previous_output"]
                                == payment["funding"]
                            ):
                                sample["indexed_input"] = entry
                    if sample["indexed_input"] or not page["objects"]:
                        break
                    assert (
                        page["last_cursor"] != cursor
                    ), "indexer cursor did not advance"
                    cursor = page["last_cursor"]
                sample["index_pages"] = pages
            sample["reads_finished"] = time.monotonic()
            self._recovery_record("sample", **sample)
            sample["finished"] = time.monotonic()
            self._recovery_record(
                "sample_complete", started=started, finished=sample["finished"]
            )
        return sample

    @staticmethod
    def _recovery_ready(sample):
        tx, tip = sample["transaction"], sample["indexer_tip"]
        return bool(
            tx
            and tx["tx_status"]["status"] == "committed"
            and tip
            and int(tip["block_number"], 16) >= int(tx["tx_status"]["block_number"], 16)
            and sample["indexed_input"]
        )

    @staticmethod
    def _recovery_complete(sample, winner_hash):
        local = sample["local"]
        flags = local["state"].get("state_flags", "")
        return (
            local["state"]["state_name"] == "Closed"
            and "UNCOOPERATIVE_REMOTE" in flags
            and "UNCOOPERATIVE_LOCAL" not in flags
            and local["shutdown_transaction_hash"] == winner_hash
            and sample["signing"]["type"] == "NoSignatureRequired"
        )

    def _recovery_logs(self, payment):
        text = (Path(self.fiber1.tmp_path) / "node.log").read_text()
        blocks = list(re.finditer(r"(?m)^  \d{4}-[^\n]+(?:\n(?!\s*$)[^\n]*)*", text))
        actor_pattern = (
            r'in ractor::actor::Actor with id: "([^"]+)", name: "HostedTenant 0x'
            + re.escape(payment["a_pubkey"].removeprefix("0x"))
            + '"'
        )
        recognition = None
        for block in blocks:
            value = block.group(0)
            actor = re.search(actor_pattern, value)
            if not actor:
                continue
            if f"channel Hash256({self.channel_id}) is shutdown by remote" in value:
                recognition = (actor.group(1), block.start(), value)
            elif (
                recognition
                and actor.group(1) == recognition[0]
                and "Updating channel state from" in value
                and "to Closed(CloseFlags(UNCOOPERATIVE_REMOTE" in value
            ):
                return {
                    "actor_id": actor.group(1),
                    "recognition": recognition[2],
                    "transition": value,
                    "recognition_line": text[: recognition[1]].count("\n") + 1,
                    "transition_line": text[: block.start()].count("\n") + 1,
                }
        return None

    def _recovery_cleanup(self):
        if getattr(self, "recovery_cleaned", False):
            return
        self.recovery_cleaned = True
        started = time.monotonic()
        until = started + 60
        errors = []
        try:
            processes = [
                f.process for f in getattr(self, "fibers", []) if hasattr(f, "process")
            ]
            processes += [t["agent"] for t in getattr(self, "tenants", [])]
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=max(0.001, min(5, until - time.monotonic())))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=max(0.001, min(5, until - time.monotonic())))
            self.recovery_observer.stop(until=until)
            if (
                "CKB observer did not stop within cleanup budget"
                in self.recovery_observer.snapshot()["errors"]
            ):
                errors.append("CKB observer did not stop within cleanup budget")
            self._stop_owned_miner(min(until, time.monotonic() + 5))
        except BaseException as error:
            errors.append(f"{type(error).__name__}: {error}")
        finally:
            self.recovery_evidence["broadcasts"] = self.recovery_observer.snapshot()
            self.recovery_evidence["query_timing"] = (
                self.recovery_observer.timing_snapshot()
            )
            node = Path(self.fiber1.tmp_path) if hasattr(self, "fiber1") else None
            for label, path in (
                ("fnn.log", node / "node.log" if node else None),
                ("sdk.log", node / "sdk-A/agent.log" if node else None),
                ("ckb.log", Path(self.node.ckb_dir) / "data/logs/run.log"),
            ):
                if path is not None and path.exists():
                    shutil.copy2(path, self.recovery_directory / label)
            if time.monotonic() > until:
                errors.append("cleanup exceeded 60 seconds")
            self.recovery_evidence["cleanup"] = {
                "started": started,
                "finished": time.monotonic(),
                "errors": errors,
            }
            (self.recovery_directory / "evidence.json").write_text(
                json.dumps(self.recovery_evidence, indent=2) + "\n"
            )
            print(f"SPEC-09 evidence: {self.recovery_directory}", flush=True)
        assert not errors, errors

    # TEST-MAP: LSP-TIMEOUT-01
    def test_external_funding_timeout_aborts_opening(self):
        unsigned = self.tenant["opened"]["unsigned_funding_tx"]
        view = self._channel(self.client)
        created = int(view["created_at"], 16) / 1000
        assert view["state"]["state_name"] == "NegotiatingFunding", view
        assert "AWAITING_EXTERNAL_FUNDING" in view["state"]["state_flags"], view
        entry = self._wait_abort(timeout=150)
        aborted_at = time.time()
        self._assert_funding_aborted(entry)
        print(
            f"aborted {aborted_at - created:.1f}s after channel creation: {entry['state']}"
        )
        # The external funding timer (60 s) fired well before the 180 s opening timeout.
        assert created + 58 <= aborted_at <= created + 120, (created, aborted_at)
        self._assert_inputs_unspent(unsigned)
        self._assert_funding_aborted(self._abort_entry(self.fiber1.client))

    # TEST-MAP: LSP-TIMEOUT-02
    def test_late_wallet_submission_after_abort(self):
        self._wait_abort(timeout=150)
        before_tenant = self.client.list_channels({})["channels"]
        unsigned = self.tenant["opened"]["unsigned_funding_tx"]
        signed = self.fiber2.client.call(
            "sign_external_funding_tx",
            [
                {
                    "unsigned_funding_tx": unsigned,
                    "private_key": self.tenant["private_key"],
                }
            ],
        )
        body = None
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                self.client.url,
                headers=self.client.other_params,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "submit_signed_funding_tx",
                    "params": [
                        {
                            "channel_id": self.channel_id,
                            "signed_funding_tx": signed["signed_funding_tx"],
                        }
                    ],
                },
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
        assert body.get("result") is None, body
        assert "error" in body, body
        # No revived channel, no second channel, and the wallet input stays unspent.
        self._assert_funding_aborted(self._abort_entry(self.client))
        assert self.client.list_channels({})["channels"] == before_tenant
        self._assert_inputs_unspent(unsigned)

    # TEST-MAP: LSP-TIMEOUT-03
    def test_stale_external_funding_timer_keeps_opening_alive(self):
        view = self._channel(self.client)
        created = int(view["created_at"], 16) / 1000
        assert self._status()["type"] == "SignatureRequired"
        target = created + 65
        while time.time() < target:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            time.sleep(1)
        assert (
            self._abort_entry(self.client) is None
        ), "stale timer aborted a funded opening"
        assert self._abort_entry(self.fiber1.client) is None
        assert self._status()["type"] == "SignatureRequired"
        print(
            f"external funding deadline passed at {time.time() - created:.1f}s without abort"
        )
        self._finish_opening()
        assert time.time() - created < self.opening_window_seconds

    # TEST-MAP: LSP-TIMEOUT-04
    def test_opening_signature_timeout_aborts_before_broadcast(self):
        unsigned = self.tenant["opened"]["unsigned_funding_tx"]
        created = int(self._channel(self.client)["created_at"], 16) / 1000
        assert self._status()["type"] == "SignatureRequired"
        entry = self._wait_abort(timeout=240)
        aborted_at = time.time()
        self._assert_funding_aborted(entry)
        print(
            f"aborted {aborted_at - created:.1f}s after channel creation: {entry['state']}"
        )
        # The normal 180 s opening timeout fired, and the funding tx never broadcast.
        assert created + 178 <= aborted_at <= created + 240, (created, aborted_at)
        self._assert_funding_not_on_chain(self.tenant["funding_tx_hash"])
        self._assert_inputs_unspent(unsigned)
        self._assert_funding_aborted(self._abort_entry(self.fiber1.client))

    # TEST-MAP: LSP-TIMEOUT-05
    def test_late_channel_signature_after_abort(self):
        self._wait_abort(timeout=240)
        with self.gate.lock:
            submission = copy.deepcopy(self.gate.submission)
        assert submission is not None
        before_tenant = self.client.list_channels({})["channels"]
        before_entry = self._abort_entry(self.client)
        body = self._submit_raw(submission)
        self._assert_not_applied(body)
        self._assert_funding_aborted(self._abort_entry(self.client))
        assert self._abort_entry(self.client)["state"] == before_entry["state"]
        assert self.client.list_channels({})["channels"] == before_tenant
        self._assert_inputs_unspent(self.tenant["opened"]["unsigned_funding_tx"])

    # -------------------------------------------------------- payment cases

    # TEST-MAP: LSP-TIMEOUT-06
    def test_short_expiry_fixture_reaches_checkpoints(self):
        self._arm_signature_gate()
        payment = self._prepare_payment()
        print(
            f"checkpoint A: request={payment['request']['request_id']} "
            f"expiry={payment['expiry']} deadline={payment['deadline']}"
        )
        self._to_checkpoint_b(payment)
        print(
            f"checkpoint B: request={payment['b_request']['request_id']}, invoice Open"
        )
        # Keep driving all asynchronous signature/ACK steps until Received.
        previous = payment["b_request"]["request_id"]
        self._submit(payment["b_submission"])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (
                self._invoice_status(payment["hash"]) == "Received"
                and self._status()["type"] == "NoSignatureRequired"
            ):
                break
            following = self._next_or_done(previous, timeout=10)
            if following is not None:
                previous = following[0]["request_id"]
                self._submit(following[1])
        assert self._status()["type"] == "NoSignatureRequired"
        assert (
            self._invoice_status(payment["hash"]) == "Received"
        ), f"hold invoice did not turn Received: {self._invoice_status(payment['hash'])}"
        print(
            f"fixture reaches Received: {payment['hash']} "
            f"invoice={self._invoice_status(payment['hash'])}"
        )

    # TEST-MAP: LSP-TIMEOUT-07
    def test_signature_after_deadline_is_not_applied(self):
        self._arm_signature_gate()
        payment = self._to_checkpoint_b(self._prepare_payment())
        funding = self._funding_outpoint(self._channel(self.client))
        expected = self._commitment_hash(self.client)
        self._wait_past_deadline(payment)
        submitted_at = time.monotonic()
        assert submitted_at - payment["injected_at"] < 28, (
            submitted_at - payment["injected_at"]
        )
        body = self._submit_raw(payment["b_submission"])
        self._assert_not_applied(body)
        assert self._commitment_hash(self.client) == expected
        _, _, observed_at = self._assert_force_close_uses(funding, expected)
        assert observed_at - payment["injected_at"] < 30
        # The protection clears the pending request.
        deadline = time.monotonic() + 15
        while (
            time.monotonic() < deadline
            and self._status()["type"] == "SignatureRequired"
        ):
            time.sleep(0.5)
        assert self._status()["type"] != "SignatureRequired", self._status()

    # TEST-MAP: LSP-TIMEOUT-08
    def test_node_protects_without_any_submission(self):
        """
        1. 就绪后停矿，扣住检查点 A 签名，唯一绑定旧无 TLC 承诺并隔离 T 广播。
        2. 不交新签名，确认 A 自主保护；真实接受 A、拦截 T 后恢复挖块并确认本地强关。
        3. 核对待签已清除，提交原签名得到真实拒绝，连续五秒确认请求与承诺未复活。
        """
        # 1. 就绪后停矿，扣住检查点 A 签名并绑定双方承诺。
        payment = self._prepare_isolated_close("A")

        # 2. 只有实际接受 A、拦截 T 后才恢复挖块，验证旧承诺确认与本地强关。
        _, cleanup_until, _ = self._confirm_isolated_close(payment)
        while self._isolated_status(cleanup_until)["type"] != "NoSignatureRequired":
            self._isolation_health(cleanup_until)
            time.sleep(min(0.2, self._remaining(cleanup_until)))

        # 3. 原签名仅提交一次；以提交前快照验证五秒内没有复活或新承诺。
        before = self._closed_snapshot(payment["until"])
        assert before["signing_status"]["type"] == "NoSignatureRequired", before
        body = self._submit_raw(
            payment["submission"], timeout=self._remaining(payment["until"])
        )
        self._assert_not_applied(body)
        self._remaining(payment["until"])
        self._observe("late_submission_rejected", response=body, before=before)
        stable_until = time.monotonic() + 5
        assert (
            stable_until < payment["until"]
        ), "insufficient stability observation budget"
        while True:
            self._isolation_health(payment["until"])
            after = self._closed_snapshot(payment["until"])
            assert after == before, (before, after)
            if time.monotonic() >= stable_until:
                break
            time.sleep(max(0, min(0.2, stable_until - time.monotonic())))
        self._observe("late_submission_stable", after=after)

    # TEST-MAP: LSP-TIMEOUT-10
    def test_force_close_uses_commitment_with_target_tlc(self):
        """
        1. 就绪后停矿，到达检查点 B，扣住撤销签名并绑定含目标 TLC 的完整承诺。
        2. 隔离 T 竞争广播，验证 A 自主保护、真实链确认及本地强关记录。
        3. 不交 preimage，核对原完整承诺的 TLC 内容准确，发票在有效期内仍为 Open。
        """
        # 1. 就绪后停矿，准备 180 秒发票及检查点 B，始终扣留下一撤销签名。
        payment = self._prepare_isolated_close("B")

        # 2. 验证 A 实际广播的含 TLC 承诺真实确认，不能接受对端承诺替代。
        _, _, closed_at = self._confirm_isolated_close(payment)

        # 3. 关闭后五秒内检查同一 SDK 完整记录和仍有效的 Open 发票。
        until = min(payment["until"], closed_at + 5)
        records = self._isolated_records(until)
        assert payment["local"] in records, records
        invoice = self._isolated_rpc(
            self.client, "get_invoice", [{"payment_hash": payment["hash"]}], until
        )
        assert (
            time.time() < payment["invoice_expires_at"]
        ), "invoice observation was too late"
        assert invoice["status"] == "Open", invoice
        self._isolation_health(until)
        self._observe(
            "invoice_open",
            status=invoice["status"],
            expires_at=payment["invoice_expires_at"],
            local_record=payment["local"],
        )

    # TEST-MAP: LSP-TIMEOUT-12
    def test_checkpoint_b_loser_recovers_remote_close(self):
        """
        1. 持续挖块，准备 B 的完整含 TLC 承诺与扣留撤销请求，唯一绑定双方交易。
        2. 一次固定 250 ms 查询窗口保留真实竞争，取得 T 接受与 A 真实 RBF 拒绝。
        3. 独立确认 T 精确花费原注资，等待同一输入索引可见后开始恢复窗口。
        4. 完整观察 330 秒及恢复后至少 10 秒，逐样本验证 A 远端关闭与 Hosted 归因。
        5. 保存全部证据并在独立 60 秒预算内清理，不用超期读取补成通过。
        """
        self.recovery_decoded = {}
        phase = "preparation"
        try:
            # 1. 准备完整检查点 B；保持矿工运行，余量不足直接失败。
            self._arm_signature_gate()
            payment_hash, _, _ = self._new_hold_invoice(600)
            until = time.monotonic() + 10
            invoice = self._recovery_rpc(
                self.client, "get_invoice", [{"payment_hash": payment_hash}], until
            )
            timestamp = invoice["invoice"]["data"]["timestamp"]
            created_ms = int(timestamp, 16) if isinstance(timestamp, str) else timestamp
            local_before = self._recovery_view(self.client, until)
            funding = self._funding_outpoint(local_before)
            live = self._recovery_rpc(
                self.node.rpcUrl, "get_live_cell", [funding, False], until
            )
            assert live["status"] == "live" and live["cell"]
            funding_tx = self._recovery_rpc(
                self.node.rpcUrl, "get_transaction", [funding["tx_hash"]], until
            )
            assert funding_tx["tx_status"]["status"] == "committed"
            until = time.monotonic() + 22 - 1.333 - 5
            with self._recovery_budget(until, 1):
                self._inject_tlc(payment_hash, 22)
            status, submission = self._recovery_pending(until)
            local = self._recovery_view(self.client, until)
            tlcs = [
                t for t in local["pending_tlcs"] if t["payment_hash"] == payment_hash
            ]
            assert len(tlcs) == 1, tlcs
            expiry = int(tlcs[0]["expiry"], 16)
            wall, mono = time.time(), time.monotonic()
            d_ms = expiry - 1333
            deadline = mono + d_ms / 1000 - wall
            self.recovery_until = deadline + 445
            until = min(until, deadline - 5)
            assert created_ms / 1000 + 600 > d_ms / 1000 + 450
            assert self._recovery_rpc(
                self.client, "submit_channel_signature", [submission], until
            ) == {"type": "Applied"}
            status, held_submission = self._recovery_pending(
                until, status["request_id"]
            )
            assert status["transition"] == "SendRevokeAndAck", status
            local = self._recovery_view(self.client, until)
            remote = self._recovery_view(self.fiber1.client, until)
            with self._recovery_budget(until, 1):
                records = self._isolated_records(until)
            a_records = [
                r
                for r in records
                if r["complete"]
                and not r["for_remote"]
                and r["transaction_hash"] == local["latest_commitment_transaction_hash"]
            ]
            t_records = [
                r
                for r in records
                if r["for_remote"]
                and r["transaction_hash"]
                == remote["latest_commitment_transaction_hash"]
            ]
            assert len(a_records) == len(t_records) == 1, records
            a, t = a_records[0], t_records[0]
            assert a["signing_message"] != t["signing_message"]
            assert (
                a["transaction_hash"]
                != local_before["latest_commitment_transaction_hash"]
            )
            target = [x for x in a["tlcs"] if x["payment_hash"] == payment_hash]
            assert len(target) == 1 and target[0]["expiry"] == expiry
            assert (
                self._recovery_rpc(
                    self.client, "get_invoice", [{"payment_hash": payment_hash}], until
                )["status"]
                == "Open"
            )
            assert self._recovery_status(until) == status
            for client, saved in ((self.client, local), (self.fiber1.client, remote)):
                current = self._recovery_view(client, until)
                assert current["state"]["state_name"] == "ChannelReady"
                assert (
                    current["latest_commitment_transaction_hash"]
                    == saved["latest_commitment_transaction_hash"]
                )
            assert (
                self._recovery_rpc(
                    self.node.rpcUrl, "get_live_cell", [funding, False], until
                )["status"]
                == "live"
            )
            assert not any(
                funding in e["inputs"]
                for e in self.recovery_observer.snapshot()["events"]
            )
            with self.gate.lock:
                self.recovery_forwarded = copy.deepcopy(self.gate.forwarded)
            payment = {
                "hash": payment_hash,
                "expiry": expiry,
                "deadline_ms": d_ms,
                "deadline": deadline,
                "invoice_created_ms": created_ms,
                "invoice_expires_at": created_ms / 1000 + 600,
                "funding": funding,
                "funding_lock": live["cell"]["output"]["lock"],
                "A": a,
                "T": t,
                "a_pubkey": remote["pubkey"],
                "t_pubkey": local["pubkey"],
                "request": status,
                "wall": wall,
                "monotonic": mono,
            }
            assert (
                held_submission["request_id"] == status["request_id"]
            ), held_submission
            self.recovery_observer.configure_query_timing(
                Path(self.fiber1.tmp_path) / "node.log",
                self.channel_id,
                local["pubkey"],
                deadline,
            )
            assert time.monotonic() <= until, "checkpoint B prepared too late"
            self.recovery_evidence.update(
                {
                    "channel_id": self.channel_id,
                    "payment": payment,
                    "signature_forwarded_baseline": self.recovery_forwarded,
                    "held_request_id": held_submission["request_id"],
                    "prepared_at": time.monotonic(),
                    "mode": "controlled_query_timing_250ms",
                }
            )
            self._recovery_record(
                "prepared", local=local, remote=remote, signing=status
            )

            # 2. 仅观察真实竞争；未取得 T 胜/A RBF 时非零退出，不自动调整时序。
            phase = "acquisition"
            accepted = rejected = None
            t_commit = None
            acquisition_until = deadline + 15
            while time.monotonic() < acquisition_until:
                events = self._recovery_broadcasts(payment, acquisition_until)
                accepted = next((e for e in events["T"] if e.get("actual_hash")), None)
                rejected = next(
                    (
                        e
                        for e in events["A"]
                        if (e["response"].get("error") or {}).get("code") == -1111
                        and "RBFRejected"
                        in str((e["response"].get("error") or {}).get("data", ""))
                    ),
                    None,
                )
                sample = self._recovery_sample(
                    payment,
                    accepted["actual_hash"] if accepted else None,
                    acquisition_until,
                )
                tx = sample["transaction"]
                if t_commit is None and tx and tx["tx_status"]["status"] == "committed":
                    t_commit = sample["tx_observed"]
                    self.recovery_evidence["t_commit"] = t_commit
                    self._recovery_record("T_committed", transaction=tx)
                if accepted and rejected:
                    break
                time.sleep(max(0, min(0.25, acquisition_until - time.monotonic())))
            if not accepted or not rejected:
                self._recovery_fail(
                    "scenario_not_acquired",
                    "did not obtain real T acceptance and A RBF within D+15s",
                )
            assert accepted["upstream_response_monotonic"] <= acquisition_until
            assert rejected["upstream_response_monotonic"] <= acquisition_until
            self._recovery_timing(payment, accepted, rejected)
            winner_hash = accepted["actual_hash"]
            self.recovery_evidence.update(
                {
                    "winner_hash": winner_hash,
                    "T_accepted": accepted,
                    "A_rejected": rejected,
                }
            )

            # 3. 首次确认与精确索引可见分别记录，绝不重置期限。
            phase = "confirmation"
            confirm_until = min(
                self.recovery_until, accepted["forwarded_monotonic"] + 60
            )
            while t_commit is None:
                if time.monotonic() >= confirm_until:
                    self._recovery_fail(
                        "confirmation_failure_product_not_excluded",
                        "T not committed within 60s",
                    )
                sample = self._recovery_sample(payment, winner_hash, confirm_until)
                tx = sample["transaction"]
                if tx and tx["tx_status"]["status"] == "committed":
                    t_commit = sample["tx_observed"]
                    self.recovery_evidence["t_commit"] = t_commit
                    self._recovery_record("T_committed", transaction=tx)
                    break
                time.sleep(max(0, min(0.25, confirm_until - time.monotonic())))
            self._recovery_timing(payment, accepted, rejected, t_commit)
            assert (
                self._recovery_decode(
                    sample["transaction"]["transaction"], confirm_until
                )
                == t["signing_message"]
            )
            a_hash = self.recovery_observer.timing_snapshot()["episode"][
                "transaction_hash"
            ]
            a_tx = self._recovery_rpc(
                self.node.rpcUrl, "get_transaction", [a_hash], confirm_until
            )
            assert not a_tx or a_tx["tx_status"]["status"] != "committed", a_tx
            spent = self._recovery_rpc(
                self.node.rpcUrl, "get_live_cell", [funding, False], confirm_until
            )
            assert (
                spent["status"] in ("dead", "unknown") and spent["cell"] is None
            ), spent
            ready_until = min(self.recovery_until, t_commit + 30)
            phase = "indexing"
            while not self._recovery_ready(sample):
                if time.monotonic() >= ready_until:
                    self._recovery_fail(
                        "chain_not_ready", "exact funding input not indexed within 30s"
                    )
                sample = self._recovery_sample(payment, winner_hash, ready_until)
                if not self._recovery_ready(sample):
                    time.sleep(max(0, min(0.25, ready_until - time.monotonic())))
            t_ready = sample["finished"]
            assert t_ready <= ready_until
            self.recovery_evidence["t_ready"] = t_ready
            self._recovery_record("chain_ready", sample=sample)
            print(
                f"SPEC-09 T committed; exact input indexed; observing 330s: {winner_hash}",
                flush=True,
            )

            # 4. 每个完整样本均核对链与恢复状态，保留整个扫描窗口和至少十秒稳定期。
            phase = "recovery"
            recovery_due, hard_due = t_ready + 330, min(
                self.recovery_until, t_ready + 340
            )
            recovered = None
            previous = None
            progress = []
            logged = t_ready
            while True:
                now = sample["finished"]
                complete = self._recovery_complete(sample, winner_hash)
                if recovered is not None and not complete:
                    self._recovery_fail(
                        "recovery_regression",
                        "A regressed after complete remote recovery",
                    )
                if not self._recovery_ready(sample):
                    self._recovery_fail(
                        "chain_health_failure",
                        "confirmed funding input lost index visibility",
                    )
                tip = int(sample["tip"], 16)
                index_tip = int(sample["indexer_tip"]["block_number"], 16)
                if previous:
                    assert (
                        now - previous["finished"] <= 5
                    ), "complete sample gap exceeded 5 seconds"
                    assert tip >= int(
                        previous["tip"], 16
                    ), "chain height went backwards"
                    assert index_tip >= int(
                        previous["indexer_tip"]["block_number"], 16
                    ), "index height went backwards"
                progress.append((now, tip))
                older = [p for p in progress if p[0] <= now - 30]
                if older:
                    assert (
                        tip > older[-1][1]
                    ), "no chain progress in a rolling 30-second window"
                assert (
                    abs(
                        (time.time() - payment["wall"])
                        - (time.monotonic() - payment["monotonic"])
                    )
                    < 0.5
                ), "wall clock jumped"
                if complete and recovered is None:
                    if now > recovery_due:
                        self._recovery_fail(
                            "recovery_timeout",
                            "first complete recovery was later than 330 seconds",
                        )
                    recovered = now
                    self.recovery_evidence["t_recover"] = recovered
                    self._recovery_record(
                        "A_recovered", after_ready=recovered - t_ready
                    )
                    print(
                        f"SPEC-09 A recovered after {recovered - t_ready:.3f}s; continuing full window",
                        flush=True,
                    )
                if recovered is not None and now >= max(recovery_due, recovered + 10):
                    with self._recovery_budget(hard_due, 1):
                        logs = self._recovery_logs(payment)
                        assert (
                            logs
                        ), "correct business state lacks Hosted A recovery attribution logs"
                        self._recovery_health()
                        self._recovery_broadcasts(payment, hard_due)
                        self._recovery_timing(payment, accepted, rejected, t_commit)
                        self.recovery_evidence.update(
                            {
                                "result": "passed",
                                "hosted_recovery": logs,
                                "observation_finished": now,
                                "observed_seconds": now - t_ready,
                                "stable_seconds": now - recovered,
                                "last_sample": sample,
                            }
                        )
                        self._recovery_record(
                            "passed",
                            observed_seconds=now - t_ready,
                            stable_seconds=now - recovered,
                        )
                    break
                if recovered is None and time.monotonic() >= recovery_due:
                    self._recovery_fail(
                        "recovery_timeout",
                        "A failed to recover within the full 330-second scan window",
                    )
                if time.monotonic() >= hard_due:
                    self._recovery_fail(
                        "evidence_failure",
                        "insufficient full-window/stability evidence by 340 seconds",
                    )
                if now - logged >= 30:
                    print(
                        f"SPEC-09 observed={now-t_ready:.1f}s A={sample['local']['state']} tip={tip}",
                        flush=True,
                    )
                    logged = now
                previous = sample
                next_due = min(
                    hard_due, recovery_due if recovered is None else hard_due
                )
                time.sleep(
                    max(
                        0,
                        min(
                            2 - (time.monotonic() - sample["started"]),
                            next_due - time.monotonic(),
                        ),
                    )
                )
                if recovered is None and time.monotonic() >= recovery_due:
                    self._recovery_fail(
                        "recovery_timeout", "A failed to recover within 330 seconds"
                    )
                sample = self._recovery_sample(payment, winner_hash, next_due)
        except BaseException as error:
            if self.recovery_evidence["result"] in ("incomplete", "passed"):
                self.recovery_evidence["result"] = "evidence_or_fixture_failure"
                if (
                    isinstance(error, _RecoveryBudgetExpired)
                    and phase == "acquisition"
                    and time.monotonic() >= acquisition_until
                ):
                    self.recovery_evidence["result"] = "scenario_not_acquired"
                elif (
                    isinstance(error, _RecoveryBudgetExpired)
                    and phase == "recovery"
                    and recovered is None
                    and time.monotonic() >= recovery_due
                ):
                    self.recovery_evidence["result"] = "recovery_timeout"
            if "sample" in locals():
                self.recovery_evidence["last_sample"] = sample
            self.recovery_evidence["failure"] = f"{type(error).__name__}: {error}"
            if isinstance(error, _RecoveryBudgetExpired):
                raise AssertionError(str(error)) from error
            raise
        finally:
            # 5. 失败也保存证据；清理不追加业务查询或改变已记录的业务判断。
            self._recovery_cleanup()

    # TEST-MAP: LSP-TIMEOUT-11
    def test_no_preimage_outcome_after_close(self):
        self._arm_signature_gate()
        balance_before = int(self._channel(self.client)["local_balance"], 16)
        # TLC-A: its whole exchange is applied, so the hold invoice becomes Received.
        first = self._prepare_payment(lifetime_seconds=60)
        self._drive_to_received(first)
        assert self._invoice_status(first["hash"]) == "Received"
        # TLC-B: an independent TLC provides the pending request that reaches D.
        second = self._to_checkpoint_b(self._prepare_payment())
        assert second["expiry"] < first["expiry"]
        assert (
            first["expiry"] - second["expiry"] > 5_000
        ), "TLC-A must remain outside ordinary expiry handling until TLC-B protects the channel"
        funding = self._funding_outpoint(self._channel(self.client))
        expected = self._commitment_hash(self.client)
        records = self.signer_control(self.tenant, "records")
        signed = [
            r
            for r in records
            if r["complete"]
            and not r["for_remote"]
            and r["transaction_hash"] == expected
        ]
        assert len(signed) == 1, records
        assert all(
            any(
                t["payment_hash"] == payment["hash"]
                and t["expiry"] == payment["expiry"]
                for t in signed[0]["tlcs"]
            )
            for payment in (first, second)
        ), signed
        self._wait_past_deadline(second)
        self._assert_force_close_uses(funding, expected)
        assert self._invoice_status(first["hash"]) == "Received"
        assert self._invoice_status(first["hash"]) != "Paid"
        assert self._invoice_status(second["hash"]) != "Paid"
        after = self._channel_view(self.client)
        assert int(after["local_balance"], 16) == balance_before, after
        target = first["invoice_expires_at"] + 5
        while time.time() < target:
            time.sleep(1)
        assert self._invoice_status(first["hash"]) == "Received", self._invoice_status(
            first["hash"]
        )
        assert (
            int(self._channel_view(self.client)["local_balance"], 16) == balance_before
        )
        print(f"no-preimage outcome kept invoice Received: {first['hash']}")

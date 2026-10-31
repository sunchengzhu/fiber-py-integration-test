"""84333ee: real Hosted delivery acceptance, timeout and same-key replay."""

import copy
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import time

from test_cases.fiber.devnet.lsp._lsp_test import (
    BUNDLE,
    ChannelSigningTestBase,
    REVISION,
)
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
    _DelayedPaymentBase,
    _number,
    _outpoint,
)


class _DeliveryBase(_DelayedPaymentBase):
    tenant_labels = ("A",)
    lsp_config_extra = {"max_buffer_duration_ms": 600000}

    def setup_method(self, method):
        assert REVISION == "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"
        self.preparation_started = time.monotonic()
        self.row_until = self.preparation_started + 480
        self.preparation_until = self.preparation_started + 240
        self.business_until = self.row_until - 60
        root = os.environ.get("LSP_DELIVERY_REPORT_DIR")
        if root is None:
            Path("report").mkdir(exist_ok=True)
            root = tempfile.mkdtemp(prefix="lsp-delivery-84333ee-", dir="report")
        self.evidence_dir = Path(root).resolve() / method.__name__
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        # Unix sockets have a short platform path limit; evidence is copied before cleanup.
        self.control_dir = Path(tempfile.mkdtemp(prefix="lsp-delivery-", dir="/tmp"))
        self.control_path = self.control_dir / "control.sock"
        self.events_path = self.control_dir / "events.jsonl"
        self.host_binary = str(Path(os.environ["LSP_DELIVERY_NODE"]).resolve())
        self.host_process_env = {
            "LSP_DELIVERY_CONTROL": str(self.control_path),
            "LSP_DELIVERY_EVENTS": str(self.events_path),
            "LSP_DELIVERY_OPERATOR_TOKEN_PATH": str(BUNDLE / "operator-token"),
        }
        self.result = "incomplete"
        self.offline = False
        self.payments = {}
        self.all_keys = {}
        self.tlc_history = {}
        self.session_history = {}
        self.snapshot_event_offset = 0
        self.previous_sample = None
        self._record(
            "environment_start",
            revision=REVISION,
            host=self.host_binary,
            preparation_until=self.preparation_until,
            row_until=self.row_until,
        )
        self.addCleanup(self._archive)
        try:
            with self._budget(self.preparation_until, 240):
                ChannelSigningTestBase.setup_method(self, method)
        except BaseException:
            self.doCleanups()
            raise

    def setUp(self):
        # Existing fixture provides real wallets, channels, SDK authorization and HTTP gate.
        super().setUp()
        status = self._delivery("status", self.preparation_until)
        assert status["ready"], status
        self._record("installation_barrier", status=status)

    def _prepare_invoice(self, tenant, amount):
        # B is a valid independently authorized same-amount target, never a fake binding.
        return super()._prepare_invoice(tenant, 1_000_000)

    def doCleanups(self):
        self.business_until = float("inf")
        self.cleanup_until = min(self.row_until, time.monotonic() + 60)
        with self._budget(self.cleanup_until, 60):
            # Registered LIFO cleanup stops SDK/FNN before the last archiver copies RocksDB.
            return ChannelSigningTestBase.doCleanups(self)

    def _archive(self):
        try:
            super()._archive()
            for path in self.control_dir.iterdir():
                if path.is_file() and not path.is_socket():
                    shutil.copy2(path, self.evidence_dir / path.name)
        finally:
            # Never erase previous evidence directories.
            shutil.rmtree(self.control_dir)

    def _delivery(self, command, until, **values):
        payload = {"command": command, **values}
        with self._budget(until, 2) as due:
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(max(0.001, due - time.monotonic()))
                conn.connect(str(self.control_path))
                conn.sendall((json.dumps(payload) + "\n").encode())
                data = b""
                while b"\n" not in data:
                    conn.settimeout(max(0.001, due - time.monotonic()))
                    part = conn.recv(1024 * 1024)
                    assert part, "delivery controller closed without reply"
                    data += part
                body = json.loads(data.split(b"\n", 1)[0])
        self._record("delivery_control", payload=payload, response=body)
        assert body["ok"], body
        return body["result"]

    def _events(self):
        if not self.events_path.exists():
            return []
        text = self.events_path.read_text()
        lines = text[: text.rfind("\n") + 1].splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def _send(self, label, until):
        payment = self.payments[label]
        assert "sent" not in payment, "send_payment must only be invoked once"
        payment["sent"] = time.monotonic()
        payment["sent_wall_ms"] = int(time.time() * 1000)
        reply = self._rpc(
            self.fiber2.client,
            "send_payment",
            [
                {
                    "invoice": payment["invoice"],
                    "max_fee_amount": hex(10_000),
                    "tlc_expiry_limit": hex(86_400_000),
                    "timeout": hex(120),
                }
            ],
            until,
        )
        assert reply["payment_hash"] == payment["hash"], reply

    def _snapshot_delivery(self, until):
        new_events = []
        if self.events_path.exists():
            with self.events_path.open("rb") as stream:
                stream.seek(0, 2)
                assert (
                    stream.tell() >= self.snapshot_event_offset
                ), "delivery event log was truncated"
                stream.seek(self.snapshot_event_offset)
                data = stream.read()
            complete = data.rfind(b"\n") + 1
            new_events = [
                json.loads(line)
                for line in data[:complete].splitlines()
                if line.strip()
            ]
            self.snapshot_event_offset += complete
        snapshot = self._delivery("snapshot", until)
        for capture in snapshot["captures"]:
            key = json.dumps(capture["key"], sort_keys=True)
            original = self.all_keys.setdefault(key, copy.deepcopy(capture["request"]))
            assert (
                original == capture["request"]
            ), "captured request changed for original K"
        # The event log is ordered. The direct read fills any gap before the next
        # observer tick, without replaying old observations on every sample.
        for current in [e for e in new_events if e["event"] == "snapshot"] + [snapshot]:
            for capture in current["captures"]:
                tlc = capture["upstream_tlc"]
                if tlc is not None:
                    key = json.dumps(capture["key"], sort_keys=True)
                    history = self.tlc_history.setdefault(key, [])
                    if not history or (
                        history[-1]["removed_reason"] is None
                        and tlc["removed_reason"] is not None
                    ):
                        history.append(copy.deepcopy(tlc))
                    elif history[-1]["removed_reason"] is not None:
                        assert (
                            tlc["removed_reason"] == history[-1]["removed_reason"]
                        ), "original TLC completion regressed or changed"
            for entry in current["sessions"]:
                session = entry["session"]
                if session["request"]["payment_hash"] not in {
                    p["hash"] for p in self.payments.values()
                }:
                    continue
                assert (
                    len(entry["previous_keys"]) == 1
                ), "downstream session cannot be attributed to one K"
                identity = json.dumps(
                    [
                        session["request"]["payment_hash"],
                        session["created_at"],
                        entry["previous_keys"],
                    ],
                    sort_keys=True,
                )
                previous = self.session_history.get(identity)
                if previous and previous["session"]["status"] in ("Success", "Failed"):
                    assert (
                        session["status"] == previous["session"]["status"]
                    ), "downstream terminal outcome regressed or changed"
                    assert len(entry["attempts"]) >= len(
                        previous["attempts"]
                    ), "downstream attempt history regressed"
                self.session_history[identity] = copy.deepcopy(entry)
        self._record("per_key_snapshot", snapshot=snapshot)
        return snapshot

    def _sample(self, until):
        started = time.monotonic()
        with self._budget(until, 3):
            views = self._views(until)
            payments, invoices, signing, records = {}, {}, {}, {}
            for label, payment in self.payments.items():
                tenant = payment["tenant"]
                invoices[label] = self._rpc(
                    tenant["client"],
                    "get_invoice",
                    [{"payment_hash": payment["hash"]}],
                    until,
                )
                signing[label] = self._signing(tenant, until)
                records[label] = self._control(tenant, "records", until)
                if "sent" in payment:
                    payments[label] = self._rpc(
                        self.fiber2.client,
                        "get_payment",
                        [{"payment_hash": payment["hash"]}],
                        until,
                    )
            for key, view in views.items():
                assert view["state"]["state_name"] == "ChannelReady", (key, view)
                assert (
                    view["channel_outpoint"] == self.baseline[key]["channel_outpoint"]
                )
                assert not view["shutdown_transaction_hash"], view
            for key in ["P"] + ["T-" + t["label"] for t in self.tenants]:
                cell = self._rpc(
                    self.node.rpcUrl,
                    "get_live_cell",
                    [_outpoint(self.baseline[key]["channel_outpoint"]), False],
                    until,
                )
                assert cell["status"] == "live", (key, cell)
            tip = _number(
                self._rpc(self.node.rpcUrl, "get_tip_block_number", [], until)
            )
            self._health(tip)
            finished = time.monotonic()
            if self.previous_sample is not None:
                assert (
                    finished - self.previous_sample <= 3
                ), "complete sample interval exceeded 3s"
            self.previous_sample = finished
            return self._record(
                "sample",
                started=started,
                finished=finished,
                views=views,
                payments=payments,
                invoices=invoices,
                signing=signing,
                records=records,
            )

    def _capture_path(self, label, sample):
        payment = self.payments[label]
        payment["tlcs"] = self._path_tlcs(label, sample)
        payment["upstream_amount"] = _number(payment["tlcs"]["P"]["amount"])
        assert (
            payment["amount"]
            <= payment["upstream_amount"]
            <= payment["amount"] + 10_000
        )
        self._record(
            "path_deadlines",
            label=label,
            tlcs=payment["tlcs"],
            payment_timeout_ms=120000,
            invoice_expiry_ms=payment["invoice_expiry"],
            authorization=payment["authorization"],
        )
        self._margin(label, 0)

    def _margin(self, label, seconds):
        # Reviewed expiry is one hour; this suite needs at most the remaining row budget.
        payment = self.payments[label]
        assert (
            min(payment["invoice_expiry"], payment["authorization"]["expires_at_ms"])
            - time.time() * 1000
            > (self.row_until - time.monotonic()) * 1000
        )

    def _arm(self, mode):
        self._delivery(
            "arm",
            self.preparation_until,
            mode=mode,
            payment_hash=self.payments["A"]["hash"],
        )

    @staticmethod
    def _record_for(snapshot, key):
        records = [d for d in snapshot["deliveries"] if d["key"] == key]
        assert len(records) == 1, (key, records)
        return records[0]

    def _held_checkpoint(self):
        until = self.preparation_until
        self._send("A", until)
        while True:
            status = self._signing(self.tenant, until)
            if status["type"] == "SignatureRequired":
                assert status["transition"] == "CompleteReceivedCommitment", status
                with self.gate.lock:
                    submission = copy.deepcopy(
                        self.gate.submissions.get(status["request_id"])
                    )
                if submission:
                    break
            self._pause(until, 0.05)
        assert status["session_evidence"]["peer_partial_signature"], status
        assert status["settlement"] and not status["settlement"]["for_remote"], status
        targets = [
            t
            for t in status["settlement"]["tlcs"]
            if t["payment_hash"] == self.payments["A"]["hash"]
        ]
        assert len(targets) == 1 and targets[0]["inbound"]
        assert _number(targets[0]["payment_amount"]) == 1_000_000
        self.request, self.submission = status, submission
        self.holding = True
        self.checkpoint_sample = self._sample(until)
        self._capture_path("A", self.checkpoint_sample)
        self._funds(self.checkpoint_sample, set())
        snap = self._snapshot_delivery(until)
        assert len(snap["captures"]) == 1, "checkpoint requires unique incoming K"
        self.original_key = snap["captures"][0]["key"]
        self.original_record = copy.deepcopy(self._record_for(snap, self.original_key))
        assert self.original_record["status"] == "InFlight", self.original_record
        self._assert_held(self.checkpoint_sample, snap)
        return snap

    def _assert_held(self, sample, snapshot):
        assert sample["signing"]["A"] == self.request
        assert self._signature_forwards() == self.forwarded_before
        with self.gate.lock:
            assert self.gate.submissions[self.request["request_id"]] == self.submission
        assert self._record_for(snapshot, self.original_key) == self.original_record
        assert self._path_tlcs("A", sample) == self.payments["A"]["tlcs"]
        self._funds(sample, set())
        assert (
            sample["views"] == self.checkpoint_sample["views"]
        ), "held channel state changed"
        if "B" in self.payments:
            assert sample["invoices"]["B"]["status"] == "Open"
            assert not any(
                d["payment_hash"] == self.payments["B"]["hash"]
                for d in snapshot["deliveries"]
            )

    def _release_signature(self, until, await_target=False):
        if await_target:
            # A caller timeout can precede dispatch or follow a safely failed K.
            # Only submit a real SDK signature for the original A settlement.
            while True:
                status = self._signing(self.tenant, until)
                if status["type"] == "SignatureRequired":
                    assert status["transition"] == "CompleteReceivedCommitment", status
                    assert status["session_evidence"]["peer_partial_signature"], status
                    settlement = status["settlement"]
                    assert settlement and not settlement["for_remote"], status
                    targets = [
                        t
                        for t in settlement["tlcs"]
                        if t["payment_hash"] == self.payments["A"]["hash"]
                    ]
                    assert len(targets) == 1 and targets[0]["inbound"], status
                    assert _number(targets[0]["payment_amount"]) == 1_000_000
                    with self.gate.lock:
                        submission = copy.deepcopy(
                            self.gate.submissions.get(status["request_id"])
                        )
                    if submission is not None:
                        assert submission["channel_id"] == self.channel_id
                        assert submission["request_id"] == status["request_id"]
                        self.request, self.submission = status, submission
                        self._record(
                            "timeout_target_signature",
                            request=status,
                            submission=submission,
                        )
                        break
                payment = self._rpc(
                    self.fiber2.client,
                    "get_payment",
                    [{"payment_hash": self.payments["A"]["hash"]}],
                    until,
                )
                if (
                    payment["status"] == "Failed"
                    and status["type"] != "SignatureRequired"
                ):
                    self._record(
                        "timeout_no_target_signature", payment=payment, signing=status
                    )
                    break
                self._pause(until, 0.1)
        if hasattr(self, "request"):
            assert self._signing(self.tenant, until) == self.request
        self.gate.release()
        if hasattr(self, "submission"):
            reply = self._rpc(
                self.client, "submit_channel_signature", [self.submission], until
            )
            assert reply["type"] in ("Applied", "AlreadyApplied"), reply
            self._record(
                "target_signature_applied", submission=self.submission, reply=reply
            )
        self.holding = False

    def _authorize_ready(self, sample, until):
        payment = self.payments["A"]
        if payment["fulfilled"]:
            return
        committed = [
            r
            for r in sample["records"]["A"]
            if r["complete"]
            and not r["for_remote"]
            and any(t["payment_hash"] == payment["hash"] for t in r["tlcs"])
        ]
        if committed:
            self._control(
                self.tenant,
                "fulfill",
                until,
                {"payment_hash": payment["hash"], "preimage": payment["preimage"]},
            )
            payment["fulfilled"] = True

    def _replay(self, variant, until):
        assert not hasattr(
            self, "replay_response"
        ), "only one controlled replay allowed"
        values = {"variant": variant}
        if variant == "amount":
            values["amount_to_forward"] = 1_000_001
        if variant == "hash":
            values["payment_hash"] = self.payments["B"]["hash"]
        response = self._delivery("replay", until, **values)
        original = next(iter(self.all_keys.values()))
        expected = copy.deepcopy(original)
        if variant == "amount":
            expected["amount_to_forward"] = response["request"]["amount_to_forward"]
            assert _number(expected["amount_to_forward"]) == 1_000_001
        elif variant == "hash":
            expected["payment_hash"] = self.payments["B"]["hash"]
        assert (
            response["request"] == expected
        ), "replay changed fields outside approved variant"
        self.replay_response = copy.deepcopy(response)
        self._record("replay_result", variant=variant, response=response)
        return response

    def _active_sample(self, sample, snapshot):
        """Use a copy; retain raw RPC samples and exclude only proven failed history."""
        known_hashes = {payment["hash"] for payment in self.payments.values()}
        active_views = {}
        for label, view in sample["views"].items():
            # The wrapper exports T's original channel state. Peer RPC views
            # have the opposite TLC direction and name T as their remote peer.
            on_host = label.startswith("T-")
            peer_field = "remote_pubkey" if on_host else "local_pubkey"
            channels = [
                channel
                for channel in snapshot["channels"]
                if channel["id"] == view["channel_id"]
                and channel[peer_field] == view["pubkey"]
            ]
            active = []
            for tlc in view["pending_tlcs"]:
                if tlc["payment_hash"] not in known_hashes or len(channels) != 1:
                    active.append(tlc)
                    continue
                if not isinstance(tlc["status"], dict) or len(tlc["status"]) != 1:
                    active.append(tlc)
                    continue
                direction, state = next(iter(tlc["status"].items()))
                if (
                    direction not in ("Inbound", "Outbound")
                    or state != "RemoveAckConfirmed"
                ):
                    active.append(tlc)
                    continue
                raw_direction = (
                    direction
                    if on_host
                    else ("Outbound" if direction == "Inbound" else "Inbound")
                )
                matches = [
                    original
                    for original in channels[0]["tlcs"]
                    if _number(original["id"]) == _number(tlc["id"])
                    and original["direction"]
                    == ("offered" if raw_direction == "Outbound" else "received")
                    and original["payment_hash"] == tlc["payment_hash"]
                    and int(original["amount"]) == _number(tlc["amount"])
                    and original["status"] == {raw_direction: state}
                    and original["removed"] == "RemoveTlcFail"
                    and original["removed_confirmed_at"] is not None
                ]
                if len(matches) != 1:
                    active.append(tlc)
            active_views[label] = {**view, "pending_tlcs": active}
        return {**sample, "views": active_views}

    def _finish(self, until, require_success=False):
        self.previous_sample = None
        self._record("recovery_start", until=until)
        while True:
            sample = self._sample(until)
            self._authorize_ready(sample, until)
            snapshot = self._snapshot_delivery(until)
            active_sample = self._active_sample(sample, snapshot)
            for capture in snapshot["captures"]:
                key = capture["key"]
                history = self.tlc_history.get(json.dumps(key, sort_keys=True), [])
                failures = [
                    t
                    for t in history
                    if isinstance(t["removed_reason"], dict)
                    and "RemoveTlcFail" in t["removed_reason"]
                ]
                paid = [
                    entry
                    for entry in self.session_history.values()
                    if key in entry["previous_keys"]
                    and entry["session"]["status"] == "Success"
                ]
                assert not (failures and paid), (
                    "product inconsistency: original K failed but downstream paid",
                    key,
                    failures,
                    paid,
                )
            state = sample["payments"]["A"]["status"]
            terminal = state in ("Success", "Failed") and all(
                not v["pending_tlcs"]
                and _number(v["offered_tlc_balance"]) == 0
                and _number(v["received_tlc_balance"]) == 0
                for v in active_sample["views"].values()
            )
            terminal = terminal and all(
                d["status"] == "Succeeded"
                or (isinstance(d["status"], dict) and "Failed" in d["status"])
                for d in snapshot["deliveries"]
            )
            raw_complete = all(
                any(
                    t["removed_reason"] is not None
                    for t in self.tlc_history.get(
                        json.dumps(c["key"], sort_keys=True), []
                    )
                )
                for c in snapshot["captures"]
            )
            terminal = terminal and (
                raw_complete
                or self._single_key_success_candidate(snapshot, require_success)
            )
            terminal = terminal and all(
                entry["session"]["status"] in ("Success", "Failed")
                for entry in self.session_history.values()
            )
            if terminal:
                self._assert_final(sample, snapshot, require_success, active_sample)
                break
            self._pause(until, 0.1)
        self.final_sample, self.final_snapshot = sample, snapshot
        return sample, snapshot

    def _assert_final(self, sample, snapshot, require_success, active_sample=None):
        active_sample = active_sample or self._active_sample(sample, snapshot)
        success = sample["payments"]["A"]["status"] == "Success"
        assert success or not require_success, sample["payments"]
        # Every original/successor K must be independently justified before aggregate funds.
        self._assert_key_outcomes(sample, snapshot, require_success)
        if success:
            assert sample["invoices"]["A"]["status"] == "Paid", sample["invoices"]
            succeeded = [
                d for d in snapshot["deliveries"] if d["status"] == "Succeeded"
            ]
            assert len(succeeded) == 1, succeeded
            winning_key = json.dumps(succeeded[0]["key"], sort_keys=True)
            self.payments["A"]["upstream_amount"] = _number(
                self.tlc_history[winning_key][-1]["amount"]
            )
            self._funds(active_sample, {"A"})
        else:
            assert sample["invoices"]["A"]["status"] != "Paid", sample["invoices"]
            assert _number(sample["payments"]["A"]["fee"]) == 0
            # No saved transient path is allowed to imply a remaining lock after failure.
            path = self.payments["A"].pop("tlcs", None)
            try:
                self._funds(active_sample, set())
            finally:
                if path is not None:
                    self.payments["A"]["tlcs"] = path
        if "B" in self.payments:
            assert sample["invoices"]["B"]["status"] == "Open", sample["invoices"]
            assert not any(
                d["payment_hash"] == self.payments["B"]["hash"]
                for d in snapshot["deliveries"]
            ), snapshot["deliveries"]

    def _single_key_success_candidate(self, snapshot, require_success):
        """Only a single observed K can use economic success if raw removal vanished."""
        if not require_success or len(snapshot["captures"]) != 1:
            return False
        capture = snapshot["captures"][0]
        history = self.tlc_history.get(json.dumps(capture["key"], sort_keys=True), [])
        return (
            capture["mode"] == "observe"
            and bool(history)
            and not any(t["removed_reason"] is not None for t in history)
        )

    def _assert_single_key_success_evidence(self, sample, snapshot, capture, history):
        """Prove one K's economic success without claiming its raw removal was seen."""
        key = capture["key"]
        payment = self.payments["A"]
        assert len(snapshot["captures"]) == len(self.all_keys) == 1
        assert len(snapshot["deliveries"]) == len(snapshot["sessions"]) == 1
        assert len(self.session_history) == 1
        assert self.original_key == key and self.all_keys == {
            json.dumps(key, sort_keys=True): capture["request"]
        }
        assert capture["mode"] == "observe" and capture["forwarded"]
        assert capture["reply"] == "Ok(Ok(Buffered))" and capture["timeout"] is False
        assert history and all(t["removed_reason"] is None for t in history)
        assert sample["payments"]["A"]["status"] == "Success"
        assert sample["invoices"]["A"]["status"] == "Paid"

        request = capture["request"]
        previous = request["previous_tlc"]
        assert key == {
            "incoming_channel_id": previous["prev_channel_id"],
            "incoming_tlc_id": previous["prev_tlc_id"],
        }
        assert request["payment_hash"] == payment["hash"]
        assert _number(request["amount_to_forward"]) == payment["amount"]
        assert len(history) == 1, history
        upstream = history[0]
        assert upstream["tlc_id"] == {"Received": key["incoming_tlc_id"]}
        assert upstream["payment_hash"] == payment["hash"]
        assert upstream["status"] == {"Inbound": "Committed"}
        assert _number(upstream["amount"]) == _number(
            request["amount_to_forward"]
        ) + _number(request["build_max_fee_amount"])
        assert _number(upstream["amount"]) == payment["upstream_amount"]

        delivery = snapshot["deliveries"][0]
        entry = snapshot["sessions"][0]
        assert delivery["key"] == key and delivery["request"] == request
        assert delivery["payment_hash"] == payment["hash"]
        assert delivery["status"] == "Succeeded"
        assert delivery["attempt_count"] >= 1
        assert entry["previous_keys"] == [key]
        session = entry["session"]
        assert session["status"] == "Success"
        assert session["request"]["allow_mpp"] is False
        assert session["request"]["payment_hash"] == payment["hash"]
        assert _number(session["request"]["amount"]) == payment["amount"]
        successful_attempts = [
            attempt for attempt in entry["attempts"] if attempt["status"] == "Success"
        ]
        assert len(successful_attempts) == 1, entry["attempts"]
        attempt = successful_attempts[0]
        assert attempt["preimage"] == payment["preimage"]
        historical = next(iter(self.session_history.values()))
        assert historical == entry, "historical session must be this exact K/attempt"

        events = self._events()
        assert all(
            e["event"]
            in (
                "ready",
                "snapshot",
                "armed",
                "captured",
                "forwarded",
                "buffered",
                "store_change",
                "replay_request",
                "replay_reply",
            )
            for e in events
        ), "timeout, snapshot failure or unknown event prevents economic-only proof"
        for name in ("captured", "forwarded", "buffered"):
            matching = [e for e in events if e["event"] == name]
            assert len(matching) == 1 and matching[0]["key"] == key, (name, matching)
        assert [
            e["event"]
            for e in events
            if e["event"] in ("captured", "forwarded", "buffered")
        ] == ["captured", "forwarded", "buffered"]
        captured = next(e for e in events if e["event"] == "captured")
        assert captured["mode"] == "observe"
        assert captured["original_port_closed"] is False
        replay_requests = [e for e in events if e["event"] == "replay_request"]
        replay_replies = [e for e in events if e["event"] == "replay_reply"]
        if hasattr(self, "replay_response"):
            assert len(replay_requests) == len(replay_replies) == 1
            assert replay_requests[0]["request"] == self.replay_response["request"]
            assert replay_replies[0]["request"] == self.replay_response["request"]
            assert replay_replies[0]["reply"] == self.replay_response["reply"]
            assert events.index(replay_requests[0]) < events.index(replay_replies[0])
        else:
            assert not replay_requests and not replay_replies

    def _assert_key_outcomes(self, sample, snapshot, require_success):
        # Implemented against the wrapper's raw product serialization below; missing proof fails.
        assert snapshot["captures"], "no real AcceptTrampolineDelivery captured"
        for entry in self.session_history.values():
            assert entry["session"]["request"]["allow_mpp"] is False, entry
            assert all(
                json.dumps(key, sort_keys=True) in self.all_keys
                for key in entry["previous_keys"]
            ), "downstream references uncaptured K"
        for capture in snapshot["captures"]:
            key = capture["key"]
            history = self.tlc_history.get(json.dumps(key, sort_keys=True), [])
            completed = [t for t in history if t["removed_reason"] is not None]
            if not completed and self._single_key_success_candidate(
                snapshot, require_success
            ):
                self._assert_single_key_success_evidence(
                    sample, snapshot, capture, history
                )
                continue
            assert completed, ("missing original TLC completion evidence", key)
            reason = completed[-1]["removed_reason"]
            deliveries = [d for d in snapshot["deliveries"] if d["key"] == key]
            sessions = [
                entry
                for entry in self.session_history.values()
                if key in entry["previous_keys"]
            ]
            downstream_success = [
                s for s in sessions if s["session"]["status"] == "Success"
            ]
            successes = [
                a
                for entry in sessions
                for a in entry["attempts"]
                if a["status"] == "Success"
            ]
            assert len(successes) <= 1, (key, successes)
            assert all(
                entry["session"]["status"] in ("Success", "Failed")
                for entry in sessions
            ), sessions
            assert len(downstream_success) <= 1, (key, downstream_success)
            fulfilled = isinstance(reason, dict) and "RemoveTlcFulfill" in reason
            if fulfilled:
                assert len(deliveries) == 1 and deliveries[0]["status"] == "Succeeded"
                request = deliveries[0]["request"]
                # The trampoline fee budget is the spread on this incoming TLC;
                # previous_tlc.forwarding_fee belongs to the outer onion hop.
                assert _number(completed[-1]["amount"]) == _number(
                    request["amount_to_forward"]
                ) + _number(request["build_max_fee_amount"])
                assert len(downstream_success) == len(successes) == 1, (key, sessions)
                assert (
                    reason["RemoveTlcFulfill"]["payment_preimage"]
                    == self.payments["A"]["preimage"]
                )
                assert successes[0]["preimage"] == self.payments["A"]["preimage"]
                assert (
                    downstream_success[0]["session"]["request"]["amount"] == 1_000_000
                )
            else:
                assert not downstream_success, (
                    "upstream failed but downstream paid",
                    key,
                    sessions,
                )
                assert all(
                    isinstance(d["status"], dict) and "Failed" in d["status"]
                    for d in deliveries
                ), (key, deliveries)

    def _stable(self, require_success):
        stable_until = time.monotonic() + 30
        self.previous_sample = None
        while time.monotonic() < stable_until:
            sample = self._sample(stable_until + 3)
            snapshot = self._snapshot_delivery(stable_until + 3)
            self._assert_final(sample, snapshot, require_success)
            assert (
                sample["payments"] == self.final_sample["payments"]
            ), "payment changed after terminal"
            assert (
                snapshot["deliveries"] == self.final_snapshot["deliveries"]
            ), "delivery revived"
            self._pause(stable_until + 3, 0.1)
        self.result = "passed"
        self._record(
            "passed",
            stable_seconds=30,
            all_keys=self.all_keys,
            tlc_history=self.tlc_history,
            session_history=self.session_history,
        )

    def _timeout_fault(self, mode):
        fault_until = time.monotonic() + 10
        while True:
            events = self._events()
            timeout = [e for e in events if e["event"] == "caller_timeout"]
            forwarded = [e for e in events if e["event"] == "forwarded"]
            buffered = [e for e in events if e["event"] == "buffered"]
            if timeout and forwarded and (mode == "delay_accept" or buffered):
                break
            self._pause(fault_until, 0.02)
        assert len(timeout) == 1, timeout
        assert (
            "Failed to consult LSP delivery service: timeout" in self._log_since_send()
        )
        snapshot = self._snapshot_delivery(fault_until)
        captures = snapshot["captures"]
        original = captures[0]
        self.original_key = original["key"]
        relevant = [e for e in events if e.get("key") == self.original_key]
        assert not any(
            e["event"]
            in ("unattributed_timeout", "duplicate_timeout", "snapshot_failed")
            for e in events
        ), events
        assert self._delivery("release", fault_until)["released"]
        self._record("timeout_qualification", events=relevant, snapshot=snapshot)
        captured = [e for e in relevant if e["event"] == "captured"]
        forwarded = [e for e in relevant if e["event"] == "forwarded"]
        assert len(captured) == len(forwarded) == 1
        assert captured[0]["timeout_ms"] == 5000, captured
        # Capture occurs after the NetworkActor began call_t!, so its elapsed
        # interval can be slightly shorter than the caller's real five seconds.
        assert 4500 <= timeout[0]["elapsed_ms"] <= 6000, timeout
        assert timeout[0]["original_port_closed"], timeout
        if mode == "delay_accept":
            assert (
                captured[0]["monotonic_ms"]
                < timeout[0]["monotonic_ms"]
                <= forwarded[0]["monotonic_ms"]
            )
            assert forwarded[0]["monotonic_ms"] - timeout[0]["monotonic_ms"] <= 1000
            assert captured[0]["delivery"] is None, captured
            assert captured[0]["store_error"] is None, captured
        else:
            buffered = [e for e in relevant if e["event"] == "buffered"]
            assert len(buffered) == 1 and buffered[0]["delivery"] is not None
            assert not buffered[0]["original_port_closed"], buffered
            assert (
                forwarded[0]["monotonic_ms"]
                < buffered[0]["monotonic_ms"]
                < timeout[0]["monotonic_ms"]
            )

    def _active_replay(self, variant, before):
        fault_until = time.monotonic() + 10
        # Take two complete stable InFlight samples before replay, without masking fields.
        first = self._sample(fault_until)
        self._assert_held(first, self._snapshot_delivery(fault_until))
        response = self._replay(variant, fault_until)
        if variant == "same":
            assert response["reply"] == "Ok(Ok(Buffered))", response
        elif variant == "amount":
            assert (
                response["reply"]
                == 'Ok(Err("delivery amount does not match hosted invoice"))'
            ), response
        else:
            assert (
                response["reply"]
                == 'Ok(Err("hosted payment execution already exists with different data"))'
            ), response
        after = self._snapshot_delivery(fault_until)
        self._assert_held(self._sample(fault_until), after)
        assert before["deliveries"] == after["deliveries"]
        assert (
            before["sessions"] == after["sessions"]
        ), "replay dispatched another payment"


class TestDeliveryQualification(_DeliveryBase):
    def test_normal_control_payment_qualifies_real_path(self):
        """No TEST-MAP: adapter qualification does not count as any delivery case."""
        self._arm("observe")
        self._held_checkpoint()
        self._release_signature(self.preparation_until)
        self._finish(time.monotonic() + 120, require_success=True)
        self._stable(True)
        qualified = self._delivery("status", self.row_until - 60)
        assert qualified["capture_count"] == 1 and not qualified["armed"], qualified
        self._record("qualification_passed", status=qualified)


class TestDeliveryAcceptance(_DeliveryBase):
    # TEST-MAP: LSP-DELIVERY-01
    def test_accept_after_original_caller_timeout(self):
        """
        1. 准备真实 P–T–A 路径，暂存原接纳请求并保留回复端口。
        2. 观察真实调用超时，一秒内转交原请求并核对逐 K 时序。
        3. 恢复签名，核对每个 K 上下游结果、逐方资金与三十秒稳定。
        """
        # 1. 原请求只在真实调用超时之后进入服务。
        self._arm("delay_accept")
        self._send("A", self.preparation_until)

        # 2. 保留端口并验证真实超时与接纳事件。
        self._timeout_fault("delay_accept")

        # 3. 完整结算及稳定窗口由同一绝对预算约束。
        recovery_until = time.monotonic() + 120
        self._release_signature(recovery_until, await_target=True)
        self._finish(recovery_until)
        self._stable(False)

    # TEST-MAP: LSP-DELIVERY-02
    def test_buffered_reply_lost_after_real_acceptance(self):
        """
        1. 准备真实路径，将原请求转交服务但保留原回复端口。
        2. 确认持久记录及 Buffered 先于真实超时，随后丢弃回复。
        3. 核对所有 K 的实际支出和收入，恢复后稳定观察三十秒。
        """
        # 1. 只替换服务回复端口，不改变真实恢复流程。
        self._arm("drop_reply")
        self._send("A", self.preparation_until)

        # 2. 以真实日志和端口生命周期验证丢回复触发资格。
        self._timeout_fault("drop_reply")

        # 3. 核对每次自动重试及双方资金，不能以最终成功洗掉原 K 失败。
        recovery_until = time.monotonic() + 120
        self._release_signature(recovery_until, await_target=True)
        self._finish(recovery_until)
        self._stable(False)

    # TEST-MAP: LSP-DELIVERY-03
    def test_same_key_replay_preserves_inflight_execution(self):
        """
        1. 原付款处于真实 InFlight 且真实 SDK 签名被暂扣。
        2. 原样重投一次，核对原完整记录、签名窗口及资金不变。
        3. 放行原签名，只完成一笔真实付款并稳定观察三十秒。
        """
        # 1. 取得真实 InFlight 和签名检查点。
        self._arm("observe")
        before = self._held_checkpoint()

        # 2. 对比完整记录和付款 session，禁止新增 dispatch。
        self._active_replay("same", before)

        # 3. 逐方核对净额、实际费用及最终零锁定。
        self._release_signature(time.monotonic() + 2)
        self._finish(time.monotonic() + 120, require_success=True)
        self._stable(True)

    # TEST-MAP: LSP-DELIVERY-04
    def test_same_key_replay_preserves_succeeded_execution(self):
        """
        1. 正常完成一笔真实付款并保存原 K 的 Succeeded 记录。
        2. 在授权有效期内原样重投一次，核对余额和完整终态不变。
        3. 连续三十秒确认付款未复活且锁定额保持零。
        """
        # 1. 正常完成原真实付款，保存逐 K 和资金证明。
        self._arm("observe")
        self._held_checkpoint()
        self._release_signature(self.preparation_until)
        self._finish(time.monotonic() + 120, require_success=True)

        # 2. 成功终态的接纳应返回已有结果，不能增加付款或改写记录。
        until = time.monotonic() + 10
        before = self._snapshot_delivery(until)
        assert self._replay("same", until)["reply"] == "Ok(Ok(Buffered))"
        after = self._snapshot_delivery(until)
        assert before["deliveries"] == after["deliveries"]
        assert before["sessions"] == after["sessions"]

        # 3. 逐方资金和完整终态稳定三十秒。
        self._stable(True)

    # TEST-MAP: LSP-DELIVERY-05
    def test_amount_conflict_rejected_before_existing_key_comparison(self):
        """
        1. 原付款真实 InFlight，扣住 A 的原 SDK 签名。
        2. 仅将转发额 M 改成 M+1，确认发票金额阶段拒绝且原状态不变。
        3. 放行原签名，仅原 M 结算并核对实际费用与稳定资金。
        """
        # 1. 准备原真实付款和签名窗口。
        self._arm("observe")
        before = self._held_checkpoint()

        # 2. 核对唯一字段变更及真实发票金额拒绝阶段。
        self._active_replay("amount", before)

        # 3. 原付款仅完成一次，保持三十秒稳定。
        self._release_signature(time.monotonic() + 2)
        self._finish(time.monotonic() + 120, require_success=True)
        self._stable(True)


class TestDeliveryTargetConflict(_DeliveryBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-DELIVERY-06
    def test_valid_other_tenant_target_cannot_replace_original_key(self):
        """
        1. 准备 A/B 独立真实通道、同额发票和本地授权，暂扣 A 的 InFlight 签名。
        2. 保留原 K 改投合法 B hash，确认规范化目标后在 existing-key 拒绝。
        3. B 发票保持 Open 且无支出，放行 A 后只完成原 M 并稳定三十秒。
        """
        # 1. B 独立身份、真实私有通道和有效发票由准备阶段建立。
        assert self.payments["A"]["hash"] != self.payments["B"]["hash"]
        assert (
            self.tenants[0]["status"]["tenant_id"]
            != self.tenants[1]["status"]["tenant_id"]
        )

        self._arm("observe")
        before = self._held_checkpoint()

        # 2. 产品自行以 B hash 规范化合法目标，不伪造绑定。
        self._active_replay("hash", before)

        # 3. 同时核对 B 无新增 TLC/付款/余额变化与 A 的唯一结算。
        self._release_signature(time.monotonic() + 2)
        self._finish(time.monotonic() + 120, require_success=True)
        self._stable(True)

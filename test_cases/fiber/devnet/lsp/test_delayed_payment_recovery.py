"""PR #1623 / 24b5c38: real payments survive delayed Hosted signatures."""

import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time

import requests
from websockets.protocol import State

from test_cases.fiber.devnet.lsp._lsp_test import (
    ChannelSigningTestBase,
    REVISION,
    stop_agent,
)


class _PaymentBudgetExpired(BaseException):
    """Do not let an HTTP client's ordinary exception retry consume the budget."""


def _number(value):
    return int(value, 16) if isinstance(value, str) else value


def _outpoint(value):
    raw = bytes.fromhex(value[2:])
    assert len(raw) == 36, value
    return {
        "tx_hash": "0x" + raw[:32].hex(),
        "index": hex(int.from_bytes(raw[32:], "little")),
    }


class _DelayedPaymentBase(ChannelSigningTestBase):
    agent_extra_args = ("--ack-held-events",)
    tenant_rpc_timeout = 2

    @contextmanager
    def _budget(self, until, cap):
        now = time.monotonic()
        previous = signal.getitimer(signal.ITIMER_REAL)
        handler = signal.getsignal(signal.SIGALRM)
        depth = getattr(self, "_alarm_depth", 0)
        assert not previous[0] or depth, "another timer owns SIGALRM"
        old_due = now + previous[0] if previous[0] else None
        due = min(until, now + cap, getattr(self, "business_until", float("inf")))
        if old_due is not None:
            due = min(due, old_due)
        if due <= now:
            raise _PaymentBudgetExpired("payment absolute budget exhausted")

        def expired(*_args):
            raise _PaymentBudgetExpired(f"payment operation exceeded {due:.6f}")

        self._alarm_depth = depth + 1
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, due - time.monotonic()))
        try:
            yield due
            if time.monotonic() > due:
                raise _PaymentBudgetExpired("late payment result is diagnostic only")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, handler)
            self._alarm_depth = depth
            if old_due is not None and old_due > time.monotonic():
                signal.setitimer(signal.ITIMER_REAL, old_due - time.monotonic())

    def _record(self, stage, **values):
        entry = {
            "stage": stage,
            "monotonic": time.monotonic(),
            "wall_ms": int(time.time() * 1000),
            **values,
        }
        with (self.evidence_dir / "observations.jsonl").open("a") as stream:
            stream.write(json.dumps(entry) + "\n")
        return entry

    def setup_method(self, method):
        self.preparation_started = time.monotonic()
        self.preparation_until = self.preparation_started + 900
        root = os.environ.get("LSP_PAYMENT_REPORT_DIR")
        if root is None:
            Path("report").mkdir(exist_ok=True)
            root = tempfile.mkdtemp(prefix="lsp-payment-24b5c38-", dir="report")
        self.evidence_dir = Path(root) / method.__name__
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        self.result = "incomplete"
        self.business_until = float("inf")
        self.offline = False
        self.payments = {}
        self._record("environment_start", revision=REVISION)
        # Run last, after the SDK and FNN cleanups, before pytest removes data.
        self.addCleanup(self._archive)
        try:
            with self._budget(self.preparation_until, 900):
                super().setup_method(method)
        except BaseException:
            self.doCleanups()
            raise

    def setUp(self):
        with self._budget(self.preparation_until, 900):
            super().setUp()
            for tenant in self.tenants:
                # There is no tenant HTTP bypass once payment preparation starts.
                tenant["client"].url = tenant["gate"].url
                tenant["gate"].forward_timeout = 2
                tenant["gate"].release()
                submitted = self._rpc(
                    tenant["client"],
                    "submit_channel_signature",
                    [tenant["gate"].submission],
                    self.preparation_until,
                )
                assert submitted["type"] == "Applied", submitted
            while True:
                channels = self._views(self.preparation_until)
                ready = all(
                    channels[key]["state"]["state_name"] == "ChannelReady"
                    for key in channels
                )
                statuses = [
                    self._signing(t, self.preparation_until) for t in self.tenants
                ]
                if ready and all(s["type"] == "NoSignatureRequired" for s in statuses):
                    break
                self._pause(self.preparation_until, 0.2)
            self.public_channel = self.open_channel(
                self.fiber2,
                self.fiber1,
                1000 * 100000000,
                0,
                other_config={"commitment_delay_epoch": "0x10000000001"},
            )
            while True:
                nodes = self._rpc(
                    self.fiber2.client, "graph_nodes", [{}], self.preparation_until
                )["nodes"]
                if any(
                    n["pubkey"] == self.public_key
                    and "TRAMPOLINE_ROUTING_REQUIRED" in n["features"]
                    for n in nodes
                ):
                    break
                self._pause(self.preparation_until, 0.2)
            self.baseline = self._views(self.preparation_until)
            for view in self.baseline.values():
                assert view["state"]["state_name"] == "ChannelReady", view
                assert not view["pending_tlcs"], view
                assert (
                    _number(view["offered_tlc_balance"])
                    == _number(view["received_tlc_balance"])
                    == 0
                )
                assert (
                    view["channel_outpoint"] and not view["shutdown_transaction_hash"]
                )
            for tenant in self.tenants:
                self._prepare_invoice(
                    tenant, 1_000_000 if tenant["label"] == "A" else 2_000_000
                )
            self.log_path = Path(self.fiber1.tmp_path) / "node.log"
            self.log_offset = self.log_path.stat().st_size
            self.node_log_offsets = [
                (
                    Path(fiber.tmp_path) / "node.log",
                    (Path(fiber.tmp_path) / "node.log").stat().st_size,
                )
                for fiber in self.fibers
            ]
            with self._budget(self.preparation_until, 2):
                listeners = subprocess.check_output(
                    [
                        "lsof",
                        "-t",
                        f"-iTCP:{self.node.rpcUrl.rsplit(':', 1)[1]}",
                        "-sTCP:LISTEN",
                    ],
                    text=True,
                    timeout=2,
                ).split()
                assert len(set(listeners)) == 1, listeners
                self.actual_ckb_pid = int(listeners[0])
                self.ckb_process_identity = subprocess.check_output(
                    ["ps", "-p", str(self.actual_ckb_pid), "-o", "lstart=,command="],
                    text=True,
                    timeout=2,
                ).strip()
                assert "ckb run" in self.ckb_process_identity, self.ckb_process_identity
            self.old_streams = self.subscription_proxy.connections()
            self.allowed_streams = list(self.old_streams)
            assert self.old_streams and all(
                s.downstream.state is State.OPEN and s.upstream.state is State.OPEN
                for s in self.old_streams
            )
            while self.gate.audit_snapshot()["active"]:
                self._pause(self.preparation_until, 0.05)
            assert (
                self._signing(self.tenant, self.preparation_until)["type"]
                == "NoSignatureRequired"
            )
            self.forwarded_before = self._signature_forwards()
            with self.gate.lock:
                self.gate.passthrough = False
            self._record(
                "prepared",
                baseline=self.baseline,
                parameters={
                    "commitment_delay_epoch": self.channel_open_options[
                        "commitment_delay_epoch"
                    ],
                    "trusted_epoch_duration_ms": 2000,
                },
                payments={
                    k: {x: v for x, v in p.items() if x != "tenant"}
                    for k, p in self.payments.items()
                },
            )

    def doCleanups(self):
        self.business_until = float("inf")
        self.cleanup_until = time.monotonic() + 60
        with self._budget(self.cleanup_until, 60):
            return super().doCleanups()

    def _archive(self):
        self._record("result", result=self.result)
        for tenant in getattr(self, "tenants", []):
            audit = tenant["gate"].audit_snapshot()
            (self.evidence_dir / f"{tenant['label']}-http.json").write_text(
                json.dumps(audit, indent=2) + "\n"
            )
            self._record(
                "tenant_control", label=tenant["label"], calls=tenant["control_calls"]
            )
            self._record(
                "websocket",
                label=tenant["label"],
                connections=self._ws_evidence(tenant),
            )
        for index, fiber in enumerate(getattr(self, "fibers", []), 1):
            source = Path(fiber.tmp_path)
            if source.exists():
                shutil.copytree(
                    source, self.evidence_dir / f"fiber-{index}", dirs_exist_ok=True
                )
        for relative, name in (
            ("data/logs/run.log", "ckb.log"),
            ("node.log", "ckb-node.log"),
            ("ckb.miner.log", "ckb-miner.log"),
        ):
            source = Path(self.node.ckb_dir) / relative
            if source.exists():
                shutil.copy2(source, self.evidence_dir / name)

    def teardown_method(self, method):
        # The generic failure archiver replaces report/<method>; every run here
        # has its own preserved directory. Only this test's two node dirs are removed.
        self.business_until = float("inf")
        until = getattr(self, "cleanup_until", time.monotonic() + 60)
        with self._budget(until, 60):
            for fiber in getattr(self, "fibers", []):
                stop_agent(fiber.process)
                fiber.clean()

    def _rpc(self, client, method, params, until):
        url = client if isinstance(client, str) else client.url
        headers = {} if isinstance(client, str) else client.other_params
        started = time.monotonic()
        with self._budget(until, 2) as due:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(
                    url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 94,
                        "method": method,
                        "params": params,
                    },
                    timeout=max(0.001, due - time.monotonic()),
                )
                response.raise_for_status()
                body = response.json()
            self._record(
                "rpc", method=method, params=params, response=body, started=started
            )
            assert "error" not in body and "result" in body, (method, body)
            return body["result"]

    def _control(self, tenant, operation, until, values=None):
        assert (
            not self.offline or tenant["label"] != "A"
        ), "control request during A offline window"
        payload = {
            "operation": operation,
            "channel_id": tenant["channel_id"],
            **(values or {}),
        }
        started = time.monotonic()
        with self._budget(until, 2) as due:
            with socket.create_connection(
                ("127.0.0.1", tenant["control_port"]),
                timeout=max(0.001, due - time.monotonic()),
            ) as conn:
                conn.sendall((json.dumps(payload) + "\n").encode())
                data = b""
                while b"\n" not in data:
                    conn.settimeout(max(0.001, due - time.monotonic()))
                    part = conn.recv(65536)
                    assert part, "SDK closed without a control reply"
                    data += part
                body = json.loads(data.split(b"\n", 1)[0])
            tenant["control_calls"].append((operation, time.monotonic()))
            self._record(
                "control",
                label=tenant["label"],
                payload=payload,
                response=body,
                started=started,
            )
            assert "error" not in body, body
            return body["result"]

    def _pause(self, until, seconds=2):
        with self._budget(until, seconds + 0.1):
            time.sleep(min(seconds, max(0, until - time.monotonic())))

    def _signing(self, tenant, until):
        assert (
            not self.offline or tenant["label"] != "A"
        ), "A signing query while offline"
        return self._rpc(
            tenant["client"],
            "get_channel_signing_status",
            [{"channel_id": tenant["channel_id"]}],
            until,
        )["status"]

    def _views(self, until):
        public = self._rpc(
            self.fiber1.client, "list_channels", [{"include_closed": True}], until
        )["channels"]
        result = {}
        endpoints = [("T-" + t["label"], public, t["channel_id"]) for t in self.tenants]
        if hasattr(self, "public_channel"):
            payer = self._rpc(
                self.fiber2.client, "list_channels", [{"include_closed": True}], until
            )["channels"]
            endpoints += [
                ("P", payer, self.public_channel),
                ("T-P", public, self.public_channel),
            ]
        for tenant in self.tenants:
            if self.offline and tenant["label"] == "A":
                continue
            channels = self._rpc(
                tenant["client"], "list_channels", [{"include_closed": True}], until
            )["channels"]
            endpoints.append((tenant["label"], channels, tenant["channel_id"]))
        for key, channels, channel_id in endpoints:
            matches = [c for c in channels if c["channel_id"] == channel_id]
            assert len(matches) == 1, (key, channels)
            result[key] = matches[0]
        return result

    def _prepare_invoice(self, tenant, amount):
        preimage = self.generate_random_preimage()
        invoice = self._rpc(
            tenant["client"],
            "new_invoice",
            [
                {
                    "amount": hex(amount),
                    "currency": "Fibd",
                    "expiry": hex(3600),
                    "final_expiry_delta": hex(3_600_000),
                    "payment_preimage": preimage,
                    "allow_trampoline_routing": True,
                    "allow_mpp": False,
                }
            ],
            self.preparation_until,
        )
        now_ms = int(time.time() * 1000)
        payment_hash = invoice["invoice"]["data"]["payment_hash"]
        auth = {
            "payment_hash": payment_hash,
            "hash_algorithm": "ckb_hash",
            "inbound": True,
            "amount": amount,
            "expires_at_ms": now_ms + 3_600_000,
            "min_tlc_expiry_delta_ms": 900_000,
            "max_tlc_expiry_ms": now_ms + 172_800_000,
        }
        self._control(
            tenant,
            "invoice",
            self.preparation_until,
            {"authorization": auth, "preimage": preimage},
        )
        created = _number(invoice["invoice"]["data"]["timestamp"])
        self.payments[tenant["label"]] = {
            "tenant": tenant,
            "hash": payment_hash,
            "amount": amount,
            "preimage": preimage,
            "invoice": invoice["invoice_address"],
            "invoice_expiry": created + 3_600_000,
            "authorization": auth,
            "fulfilled": False,
        }

    def _send(self, label, until):
        payment = self.payments[label]
        assert "sent" not in payment, "a payment must only be sent once"
        payment["sent"] = time.monotonic()
        payment["sent_wall_ms"] = int(time.time() * 1000)
        result = self._rpc(
            self.fiber2.client,
            "send_payment",
            [
                {
                    "invoice": payment["invoice"],
                    "max_fee_amount": hex(10_000),
                    "tlc_expiry_limit": hex(86_400_000),
                    "timeout": hex(1200),
                }
            ],
            until,
        )
        assert result["payment_hash"] == payment["hash"], result

    def _signature_forwards(self):
        return [
            r
            for r in self.gate.audit_snapshot()["requests"]
            if r["method"] == "submit_channel_signature"
            and r["forward_started_at"] is not None
        ]

    def _ws_evidence(self, tenant):
        proxy = tenant["subscription_proxy"]
        with proxy.lock:
            return [
                {
                    "started": c.started,
                    "ended": c.ended.is_set(),
                    "downstream": c.downstream.state.name,
                    "upstream": c.upstream.state.name if c.upstream else None,
                    "requests": copy.deepcopy(c.requests),
                    "subscriptions": copy.deepcopy(c.subscriptions),
                    "delivered": copy.deepcopy(c.delivered_events),
                    "errors": list(c.errors),
                    "transport_errors": list(c.transport_errors),
                }
                for c in proxy.streams
            ]

    def _health(self, tip):
        for fiber in self.fibers:
            assert (
                fiber.process.poll() is None
            ), "FNN exited; product failure not excluded"
        # The generic ckb_pid is guessed by its shell launcher. Bind liveness to
        # the actual RPC listener and unchanged process identity instead.
        os.kill(self.actual_ckb_pid, 0)
        identity = subprocess.check_output(
            ["ps", "-p", str(self.actual_ckb_pid), "-o", "lstart=,command="],
            text=True,
            timeout=2,
        ).strip()
        assert identity == self.ckb_process_identity, "CKB listener restarted"
        os.kill(
            int(self.node.ckb_miner_pid), 0
        )  # Miner is a directly recorded Popen PID.
        for tenant in self.tenants:
            if self.offline and tenant["label"] == "A":
                assert tenant["agent"].poll() is not None
            else:
                assert (
                    tenant["agent"].poll() is None
                ), "SDK exited; product failure not excluded"
            assert not tenant["gate"].errors, tenant["gate"].errors
            assert not tenant["subscription_proxy"].errors, tenant[
                "subscription_proxy"
            ].errors
        now = time.monotonic()
        if not hasattr(self, "last_tip") or tip > self.last_tip:
            self.last_tip, self.tip_advanced_at = tip, now
        assert (
            now - self.tip_advanced_at < 30
        ), "no chain height increase in rolling 30s"
        channel_ids = {view["channel_id"] for view in self.baseline.values()}
        for path, offset in self.node_log_offsets:
            assert path.stat().st_size >= offset, "FNN log truncated/restarted"
            with path.open() as stream:
                stream.seek(offset)
                recent = stream.read()
            # Pinned actors.rs emits this exact diagnostic for supervised failure.
            assert "Actor unexpectedly panicked" not in recent, path
            for line in recent.splitlines():
                if any(channel_id in line for channel_id in channel_ids):
                    assert (
                        "no corresponding channel actor, starting it now" not in line
                    ), line
        if getattr(self, "holding", False) and not self.offline:
            assert (
                self.subscription_proxy.connections() == self.allowed_streams
            ), "A WS resubscribed while held"
            for stream in self.old_streams:
                assert not stream.ended.is_set()
                assert stream.downstream.state is stream.upstream.state is State.OPEN

    def _sample(self, until):
        started = time.monotonic()
        with self._budget(until, 5):
            views = self._views(until)
            payments, invoices, signing, records = {}, {}, {}, {}
            for label, payment in self.payments.items():
                if "sent" not in payment:
                    continue
                payments[label] = self._rpc(
                    self.fiber2.client,
                    "get_payment",
                    [{"payment_hash": payment["hash"]}],
                    until,
                )
                assert payments[label]["status"] != "Failed", payments[label]
                if self.offline and label == "A":
                    continue
                tenant = payment["tenant"]
                invoices[label] = self._rpc(
                    tenant["client"],
                    "get_invoice",
                    [{"payment_hash": payment["hash"]}],
                    until,
                )
                signing[label] = self._signing(tenant, until)
                records[label] = self._control(tenant, "records", until)
            cells = {}
            for key in ["P"] + ["T-" + t["label"] for t in self.tenants]:
                cells[key] = self._rpc(
                    self.node.rpcUrl,
                    "get_live_cell",
                    [_outpoint(self.baseline[key]["channel_outpoint"]), False],
                    until,
                )
                assert cells[key]["status"] == "live", cells[key]
            tip = _number(
                self._rpc(self.node.rpcUrl, "get_tip_block_number", [], until)
            )
            self._health(tip)
            for key, view in views.items():
                assert view["state"]["state_name"] == "ChannelReady", (key, view)
                assert (
                    view["channel_outpoint"] == self.baseline[key]["channel_outpoint"]
                )
                assert not view["shutdown_transaction_hash"], view
            finished = time.monotonic()
            previous = getattr(self, "previous_sample", None)
            if previous is not None:
                assert (
                    finished - previous <= 7
                ), f"complete sample gap: {finished - previous:.3f}s"
            self.previous_sample = finished
            return self._record(
                "sample",
                started=started,
                finished=finished,
                offline=self.offline,
                views=views,
                payments=payments,
                invoices=invoices,
                signing=signing,
                records=records,
                funding=cells,
                tip=tip,
            )

    def _path_tlcs(self, label, sample):
        payment = self.payments[label]
        found = {}
        for key, direction in (
            (label, "Inbound"),
            ("T-" + label, "Outbound"),
            ("P", "Outbound"),
            ("T-P", "Inbound"),
        ):
            if key not in sample["views"]:
                continue
            tlcs = [
                t
                for t in sample["views"][key]["pending_tlcs"]
                if t["payment_hash"] == payment["hash"]
            ]
            assert len(tlcs) == 1, (label, key, tlcs)
            tlc = tlcs[0]
            assert direction in tlc["status"], (key, tlc)
            found[key] = {k: tlc[k] for k in ("id", "payment_hash", "amount", "expiry")}
            if key in (label, "T-" + label):
                assert _number(tlc["amount"]) == payment["amount"], tlc
        if label in found:
            assert found[label] == found["T-" + label]
        assert found["P"] == found["T-P"]
        return found

    def _capture_path(self, label, sample):
        payment = self.payments[label]
        payment["tlcs"] = self._path_tlcs(label, sample)
        payment["upstream_amount"] = _number(payment["tlcs"]["P"]["amount"])
        assert (
            payment["amount"]
            <= payment["upstream_amount"]
            <= payment["amount"] + 10_000
        )
        expiries = [_number(t["expiry"]) for t in payment["tlcs"].values()]
        cutoffs = [
            payment["invoice_expiry"],
            payment["authorization"]["expires_at_ms"],
            payment["sent_wall_ms"] + 1_200_000,
        ]
        for expiry in expiries:
            cutoffs.extend(
                (
                    expiry - 1333,
                    expiry // 1000 * 1000 - 1334,
                    expiry // 1000 * 1000 - 900_000,
                )
            )
        payment["safety_until_ms"] = min(cutoffs)
        self._margin(label, 900)
        self._record(
            "path_deadlines", label=label, tlcs=payment["tlcs"], cutoffs_ms=cutoffs
        )

    def _margin(self, label, seconds):
        payment = self.payments[label]
        remaining = payment["safety_until_ms"] - time.time() * 1000
        assert remaining >= seconds * 1000, (
            label,
            "insufficient business margin",
            remaining,
        )

    def _log_since_send(self):
        with self.log_path.open() as stream:
            stream.seek(self.log_offset)
            return stream.read()

    def _checkpoint(self):
        self.t_send = time.monotonic()
        self.business_until = self.t_send + 420
        until = self.t_send + 60
        with self._budget(until, 60):
            self._send("A", until)
            while True:
                status = self._signing(self.tenant, until)
                if status["type"] == "SignatureRequired":
                    assert status["transition"] == "CompleteReceivedCommitment", (
                        "reviewed checkpoint not obtained; do not apply a different transition",
                        status,
                    )
                    with self.gate.lock:
                        submission = copy.deepcopy(
                            self.gate.submissions.get(status["request_id"])
                        )
                    if submission is not None:
                        break
                self._pause(until, 0.1)
            assert status["session_evidence"]["peer_partial_signature"]
            assert submission["channel_id"] == self.channel_id
            assert submission["request_id"] == status["request_id"]
            settlement = status["settlement"]
            assert settlement is not None and settlement["for_remote"] is False, status
            target = [
                t
                for t in settlement["tlcs"]
                if t["payment_hash"] == self.payments["A"]["hash"]
            ]
            assert (
                len(target) == 1 and _number(target[0]["payment_amount"]) == 1_000_000
            ), target
            assert target[0]["inbound"] is True, target
            sample = self._sample(until)
            self._capture_path("A", sample)
            records = [
                t
                for record in sample["records"]["A"]
                for t in record["tlcs"]
                if t["payment_hash"] == self.payments["A"]["hash"]
            ]
            assert records and all(
                _number(t["expiry"]) == _number(target[0]["expiry"]) for t in records
            ), records
            assert _number(target[0]["expiry"]) == _number(
                self.payments["A"]["tlcs"]["A"]["expiry"]
            )
            log = self._log_since_send()
            lines = [line for line in log.splitlines() if self.channel_id in line]
            waits = [
                i for i, line in enumerate(lines) if "set_waiting_ack(true)" in line
            ]
            sends = [
                i
                for i, line in enumerate(lines)
                if "send commitment signed: CommitmentSigned" in line
            ]
            assert len(waits) == len(sends) == 1 and waits[0] < sends[0], lines
            assert not any(
                "set_waiting_ack(false)" in line for line in lines[sends[0] + 1 :]
            ), lines
            assert self._signature_forwards() == self.forwarded_before
            self.request, self.submission = status, submission
            self.commitments = {
                key: sample["views"][key]["latest_commitment_transaction_hash"]
                for key in ("A", "T-A")
            }
            self.checkpoint_log = lines
            self.holding = True
            self.t_checkpoint = time.monotonic()
            self._assert_waiting(sample)
            self._record(
                "checkpoint",
                request=status,
                submission=submission,
                protocol_lines=lines,
                captured_at=self.t_checkpoint,
            )
        return sample

    def _assert_waiting(self, sample):
        assert sample["payments"]["A"]["status"] not in ("Success", "Failed")
        if not self.offline:
            assert sample["signing"]["A"] == self.request
            assert sample["invoices"]["A"]["status"] in ("Open", "Received")
        assert (
            self._signature_forwards() == self.forwarded_before
        ), "A signature was forwarded during hold"
        with self.gate.lock:
            assert self.gate.submissions[self.request["request_id"]] == self.submission
        current_tlcs = self._path_tlcs("A", sample)
        for key, tlc in current_tlcs.items():
            assert tlc == self.payments["A"]["tlcs"][key], (key, tlc)
        for key in ("A", "T-A"):
            if key in sample["views"]:
                assert (
                    sample["views"][key]["latest_commitment_transaction_hash"]
                    == self.commitments[key]
                )
        lines = [
            line
            for line in self._log_since_send().splitlines()
            if self.channel_id in line
            and (
                "set_waiting_ack(" in line
                or "send commitment signed: CommitmentSigned" in line
            )
        ]
        expected = [
            line
            for line in self.checkpoint_log
            if "set_waiting_ack(" in line
            or "send commitment signed: CommitmentSigned" in line
        ]
        assert lines == expected, (
            "ACK cleared or commitment advanced while A held",
            lines,
        )

    def _funds(self, sample, completed):
        views = sample["views"]
        deltas = {key: 0 for key in self.baseline}
        locks = {key: [0, 0] for key in self.baseline}
        fees = {}
        expected_tlcs = {key: set() for key in self.baseline}
        for label, payment in self.payments.items():
            if label in completed:
                fee = _number(sample["payments"][label]["fee"])
                assert 0 <= fee <= 10_000
                assert payment["upstream_amount"] == payment["amount"] + fee
                fees[label] = fee
                deltas[label] += payment["amount"]
                deltas["T-" + label] -= payment["amount"]
                deltas["P"] -= payment["amount"] + fee
                deltas["T-P"] += payment["amount"] + fee
            elif "tlcs" in payment:
                locks[label][1] += payment["amount"]
                locks["T-" + label][0] += payment["amount"]
                locks["P"][0] += payment["upstream_amount"]
                locks["T-P"][1] += payment["upstream_amount"]
                for key in (label, "T-" + label, "P", "T-P"):
                    expected_tlcs[key].add(payment["hash"])
        for key, current in views.items():
            before = self.baseline[key]
            assert (
                _number(current["local_balance"]) - _number(before["local_balance"])
                == deltas[key]
            ), (key, current, deltas)
            assert (
                _number(current["remote_balance"]) - _number(before["remote_balance"])
                == -deltas[key]
            )
            assert [
                _number(current["offered_tlc_balance"]),
                _number(current["received_tlc_balance"]),
            ] == locks[key], (key, current, locks)
            assert {
                t["payment_hash"] for t in current["pending_tlcs"]
            } == expected_tlcs[key], (key, current)
        for label in ["P"] + list(self.payments):
            if label in views:
                assert (
                    views[label]["local_balance"]
                    == views["T-" + label]["remote_balance"]
                )
                assert (
                    views[label]["remote_balance"]
                    == views["T-" + label]["local_balance"]
                )
        if completed == set(self.payments):
            income = sum(
                _number(views[k]["local_balance"])
                - _number(self.baseline[k]["local_balance"])
                for k in views
                if k.startswith("T-")
            )
            assert income == sum(fees.values()), (income, fees)
        elif completed == {"B"}:
            assert _number(views["P"]["local_balance"]) - _number(
                views["P"]["offered_tlc_balance"]
            ) == (
                _number(self.baseline["P"]["local_balance"])
                - self.payments["B"]["amount"]
                - fees["B"]
                - self.payments["A"]["upstream_amount"]
            )

    def _wait_held(self, started):
        until = started + 40
        with self._budget(until, 40):
            while True:
                sample = self._sample(until)
                self._assert_waiting(sample)
                self._funds(sample, set())
                if self.offline:
                    self._assert_offline_audit()
                if sample["finished"] >= started + 35:
                    return sample
                self._pause(until, min(2, started + 35 - time.monotonic()))

    def _offline_fingerprint(self):
        audit = self.gate.audit_snapshot()
        return {
            "received": audit["received"],
            "forwarded": audit["forwarded"],
            "active": audit["active"],
            "controls": list(self.tenant["control_calls"]),
            "connections": [
                (c.started, len(c.requests))
                for c in self.subscription_proxy.connections()
            ],
        }

    def _assert_offline_audit(self):
        assert (
            self._offline_fingerprint() == self.offline_fingerprint
        ), "A request during complete offline interval"
        for stream in self.subscription_proxy.connections():
            assert stream.ended.is_set()
            assert stream.downstream.state is stream.upstream.state is State.CLOSED

    def _take_offline(self):
        until = self.t_checkpoint + 20
        with self._budget(until, 20):
            self.saved_identity = json.loads(self.tenant["status_file"].read_text())
            self.saved_controls = list(self.tenant["control_calls"])
            self.old_pid = self.tenant["agent"].pid
            self.tenant["agent"].kill()
            with self._budget(until, 10):
                assert self.tenant["agent"].wait(timeout=10) != 0
            while True:
                streams = self.subscription_proxy.connections()
                closed = all(
                    c.ended.is_set()
                    and c.downstream.state is State.CLOSED
                    and c.upstream is not None
                    and c.upstream.state is State.CLOSED
                    for c in streams
                )
                if closed and self.gate.audit_snapshot()["active"] == 0:
                    break
                self._pause(until, 0.1)
            self.offline = True
            self.offline_fingerprint = self._offline_fingerprint()
            self.t_offline = time.monotonic()
            self._record(
                "offline_start",
                pid=self.old_pid,
                audit=self.offline_fingerprint,
                websocket=self._ws_evidence(self.tenant),
            )

    def _restore(self):
        self._assert_offline_audit()
        self._margin("A", 240)
        assert self.business_until - time.monotonic() >= 205
        self._record("offline_end", audit=self._offline_fingerprint())
        self.offline = False
        started = time.monotonic()
        until = started + 60
        self.previous_sample = (
            None  # Offline preparation/recovery has its own bounded phases.
        )
        with self._budget(until, 60):
            self.tenant["status_file"].unlink()
            self.tenant["agent"] = subprocess.Popen(
                self.tenant["command"],
                stdout=self.tenant["log"],
                stderr=subprocess.STDOUT,
            )
            self.addCleanup(stop_agent, self.tenant["agent"])
            assert self.tenant["agent"].pid != self.old_pid
            expected = {
                "type": "channel_signing",
                "data": {"channel_id": self.channel_id, "status": self.request},
            }
            while True:
                assert self.tenant["agent"].poll() is None
                deliveries = [
                    (c, identity)
                    for at, c, identity, topic in self.subscription_proxy.successful_subscriptions()
                    if at >= started
                    and c.started >= started
                    and topic == "channel_signing"
                    and any(
                        delivered >= started
                        and type(sub) is type(identity)
                        and sub == identity
                        and event == expected
                        for delivered, sub, event in c.delivered_frames()
                    )
                ]
                with self.gate.lock:
                    attempts = [
                        body for at, body in self.gate.attempts if at >= started
                    ]
                if deliveries and attempts and self.tenant["status_file"].exists():
                    break
                self._pause(until, 0.1)
            assert attempts[0] == self.submission, attempts
            identity = json.loads(self.tenant["status_file"].read_text())
            for field in (
                "tenant_id",
                "root_signer_pubkey",
                "tenant_token",
                "bound_channel_ids",
            ):
                assert identity[field] == self.saved_identity[field], field
            assert self.channel_id in identity["bound_channel_ids"]
            assert self.tenant["control_calls"] == self.saved_controls
            assert self._signing(self.tenant, until) == self.request
            self.old_streams = [
                c for c in self.subscription_proxy.connections() if c.started >= started
            ]
            # Old sessions must stay closed; only these new sessions may be open.
            self.allowed_streams = self.subscription_proxy.connections()
            for stream in self.allowed_streams:
                if stream.started < started:
                    assert stream.ended.is_set()
                    assert (
                        stream.downstream.state is stream.upstream.state is State.CLOSED
                    )
            sample = self._sample(until)
            self._assert_waiting(sample)
            self._funds(sample, set())
            # _assert_waiting compared actual hash/id/amount/expiry with the saved
            # path; the same full R plus this margin also covers SDK revalidation.
            self._margin("A", 180)
            self.restored = True
            self._record(
                "sdk_restored",
                old_pid=self.old_pid,
                new_pid=self.tenant["agent"].pid,
                request=self.request,
                first_signature=attempts[0],
                websocket=self._ws_evidence(self.tenant),
            )

    def _release_original(self):
        until = time.monotonic() + 15
        with self._budget(until, 15):
            self._margin("A", 180)
            assert self.business_until - time.monotonic() >= 145
            assert self._signing(self.tenant, until) == self.request
            assert self._signature_forwards() == self.forwarded_before
            with self.gate.lock:
                assert (
                    self.gate.submissions[self.request["request_id"]] == self.submission
                )
            self.gate.release()
            self.holding = False
            result = self._rpc(
                self.client, "submit_channel_signature", [self.submission], until
            )
            assert result["type"] in ("Applied", "AlreadyApplied"), result
            forwarded = [
                r
                for r in self._signature_forwards()
                if r["params"]["request_id"] == self.request["request_id"]
            ]
            assert forwarded and forwarded[0]["params"] == self.submission, forwarded
            assert forwarded[0]["reply"].get("result") == {"type": "Applied"}, forwarded
            self.t_applied = forwarded[0]["forward_finished_at"]
            self._record(
                "released",
                applied_at=self.t_applied,
                response=result,
                forwarded=forwarded,
            )
            self.previous_sample = None

    def _authorize(self, label, sample, until):
        payment = self.payments[label]
        if payment["fulfilled"]:
            return
        valid = [
            r
            for r in sample["records"].get(label, [])
            if r["complete"]
            and not r["for_remote"]
            and any(t["payment_hash"] == payment["hash"] for t in r["tlcs"])
        ]
        if valid:
            expected_expiry = _number(payment["tlcs"][label]["expiry"])
            for record in valid:
                target_tlcs = [
                    t for t in record["tlcs"] if t["payment_hash"] == payment["hash"]
                ]
                assert (
                    len(target_tlcs) == 1
                    and _number(target_tlcs[0]["expiry"]) == expected_expiry
                ), record
            self._control(
                payment["tenant"],
                "fulfill",
                until,
                {"payment_hash": payment["hash"], "preimage": payment["preimage"]},
            )
            payment["fulfilled"] = True

    def _complete(self, sample, labels):
        for label in labels:
            if (
                sample["payments"][label]["status"] != "Success"
                or sample["invoices"][label]["status"] != "Paid"
            ):
                return False
            if sample["signing"][label]["type"] != "NoSignatureRequired":
                return False
            payment = self.payments[label]
            if any(
                t["payment_hash"] == payment["hash"]
                for v in sample["views"].values()
                for t in v["pending_tlcs"]
            ):
                return False
        return True

    def _finish_and_stabilize(self):
        until = self.t_applied + 120
        labels = set(self.payments)
        with self._budget(until, 120):
            while True:
                sample = self._sample(until)
                self._authorize("A", sample, until)
                if self._complete(sample, labels):
                    self._funds(sample, labels)
                    break
                self._pause(until)
        first = sample["finished"]
        stable_until = first + 10
        with self._budget(stable_until, 10):
            while True:
                self._pause(
                    stable_until, min(2, max(0.01, first + 5 - time.monotonic()))
                )
                stable = self._sample(stable_until)
                assert self._complete(stable, labels)
                self._funds(stable, labels)
                if stable["finished"] >= first + 5:
                    break
        assert all(p["fulfilled"] for p in self.payments.values())
        self.result = "passed"
        self._record(
            "passed",
            completed=list(labels),
            stable_seconds=stable["finished"] - first,
            business_seconds=stable["finished"] - self.t_send,
        )


class TestDelayedPaymentRecovery(_DelayedPaymentBase):
    # TEST-MAP: LSP-PAYMENT-01
    def test_online_delayed_signature_preserves_real_payment(self):
        """
        1. 准备真实付款，扣住 CompleteReceivedCommitment 并证明 T 已等 ACK。
        2. SDK 和原订阅保持在线，连续 35 秒检查原付款、资金和原请求。
        3. 只提交一次原签名，完成原付款并稳定检查至少 5 秒。
        """
        # 1. 发起唯一付款并取得原请求、真实签名和联合 ACK 检查点。
        self._checkpoint()

        # 2. 跨过普通活动阈值，连续核对原业务与锁定额。
        self._wait_held(self.t_checkpoint)

        # 3. 恢复真实签名，按实际费用核对完整结算与稳定性。
        self._release_original()
        self._finish_and_stabilize()

    # TEST-MAP: LSP-PAYMENT-02
    def test_offline_sdk_restores_original_payment_without_tenant_queries(self):
        """
        1. 取得真实付款原请求和签名，结束 SDK 及全部旧连接和在途请求。
        2. 完整离线至少 35 秒，只观察公共侧并证明 A 的请求审计不变。
        3. 用原存储新进程恢复原请求与签名，核对身份授权和新订阅补发。
        4. 只提交一次原签名，核对原付款资金和至少 5 秒稳定终态。
        """
        # 1. 保存明确 ACK 检查点后有界退出，离线窗口从全部请求结束起算。
        self._checkpoint()
        self._take_offline()
        self.previous_sample = None

        # 2. 不请求 A/SDK，连续观察公共侧和零请求审计。
        self._wait_held(self.t_offline)

        # 3. 原存储恢复新 PID，要求新连接真实交付完整 R、首签等于 S。
        self._restore()

        # 4. 放行并核对唯一原付款、资金镜像和稳定终态。
        self._release_original()
        self._finish_and_stabilize()


class TestDelayedPaymentTenantIsolation(_DelayedPaymentBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-PAYMENT-03
    def test_other_tenant_settles_before_held_payment_resumes(self):
        """
        1. 两租户预先就绪并授权，A 的真实付款停在联合 ACK 检查点。
        2. 五秒内发送唯一 B 付款，A 未放行时完成 B 并稳定检查混合资金。
        3. A 等待至少 35 秒后恢复原签名，核对两笔金额、费用及六端余额。
        """
        # 1. 共享 P–T 基线只保存一份，A/B 付款与授权上下文分开。
        self._checkpoint()

        # 2. B 正常签名和兑现，必须在 A 仍待签时先完成且稳定至少五秒。
        with self._budget(self.t_checkpoint + 5, 5):
            payment = self.payments["B"]
            assert (
                min(
                    payment["invoice_expiry"], payment["authorization"]["expires_at_ms"]
                )
                - time.time() * 1000
                >= 900_000
            )
            self._send("B", self.t_checkpoint + 5)
        until = self.t_checkpoint + 120
        stable_started = None
        with self._budget(until, 120):
            while True:
                sample = self._sample(until)
                self._assert_waiting(sample)
                if "tlcs" not in self.payments["B"]:
                    if all(
                        any(
                            t["payment_hash"] == payment["hash"]
                            for t in sample["views"][key]["pending_tlcs"]
                        )
                        for key in ("B", "T-B", "P", "T-P")
                    ):
                        self._capture_path("B", sample)
                if "tlcs" in self.payments["B"]:
                    self._authorize("B", sample, until)
                if self._complete(sample, {"B"}):
                    self._funds(sample, {"B"})
                    stable_started = stable_started or sample["finished"]
                    if (
                        sample["finished"] >= stable_started + 5
                        and sample["finished"] >= self.t_checkpoint + 35
                    ):
                        break
                else:
                    assert stable_started is None, "B completed state regressed"
                self._pause(until)
        assert sample["finished"] <= self.t_checkpoint + 125
        self._record(
            "B_completed_A_pending", sample=sample, stable_started=stable_started
        )

        # 3. 混合观察成立后才放行 A；最终只收取各笔实际路由费一次。
        self._release_original()
        self._finish_and_stabilize()

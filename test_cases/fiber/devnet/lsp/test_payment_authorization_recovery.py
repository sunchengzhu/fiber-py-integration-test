"""PR #1623 / 84333ee: explicit authorization recovers a real rejected payment."""

import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import time

import yaml

from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._watchtower_rpc import ChainAudit
from test_cases.fiber.devnet.lsp.test_watchtower_settlement import _WatchtowerBase
from test_cases.fiber.devnet.lsp._lsp_test import ChannelSigningTestBase, REVISION
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
    _DelayedPaymentBase,
    _number,
    _outpoint,
)

FIXED_REVISION = "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"
AMOUNT = 1_000_000


class TestPaymentAuthorizationRecovery(_DelayedPaymentBase):
    tenant_labels = ("A",)

    @classmethod
    def setup_class(cls):
        # The runner's pytest start includes CKBlifecycle and contract alignment.
        row_started = float(os.environ["LSP_PAYMENT04_ROW_START"])
        timer = object.__new__(cls)
        timer.business_until = float("inf")
        artifacts = Path(os.environ["LSP_RUN_ARTIFACTS"])
        try:
            with timer._budget(row_started + 180, 180):
                super().setup_class()
                root = Path(get_project_root()).resolve()
                assert cls.tmp_path_name, "isolated runtime path is required"
                isolated = (root / cls.tmp_path_name).resolve()
                assert isolated.is_relative_to(root) and isolated != root
                assert Path(cls.node.ckb_dir).resolve().is_relative_to(isolated)
                # Reuse only the reviewed alignment operation, not Watchtower's lifecycle.
                _WatchtowerBase.prepare_isolated_contract.__func__(cls, root)
                (artifacts / "preparation-class.json").write_text(
                    json.dumps(
                        {
                            "row_started": row_started,
                            "preparation_deadline": row_started + 180,
                            "aligned_at": time.monotonic(),
                            "chain_dir": cls.node.ckb_dir,
                            "stage": "contract_aligned_before_any_fnn",
                        },
                        indent=2,
                    )
                    + "\n"
                )
        except BaseException as error:
            failure = {"error": repr(error), "at": time.monotonic()}
            if hasattr(cls, "node"):
                for name, target in (
                    ("dev.toml", "ckb-dev.toml"),
                    ("ckb.toml", "ckb.toml"),
                    ("node.log", "ckb-node.log"),
                    ("data/logs/run.log", "ckb.log"),
                ):
                    try:
                        source = Path(cls.node.ckb_dir) / name
                        if source.is_file():
                            shutil.copy2(source, artifacts / target)
                    except BaseException as archive_error:
                        failure.setdefault("archive_errors", []).append(
                            {
                                "source": name,
                                "error": repr(archive_error),
                            }
                        )
                try:
                    with timer._budget(
                        min(row_started + 600, time.monotonic() + 60), 60
                    ):
                        super().teardown_class()
                except BaseException as cleanup_error:
                    failure["cleanup_error"] = repr(cleanup_error)
            (artifacts / "preparation-class-failure.json").write_text(
                json.dumps(failure, indent=2) + "\n"
            )
            raise

    def setup_method(self, method):
        assert REVISION == FIXED_REVISION
        self.row_started = float(os.environ["LSP_PAYMENT04_ROW_START"])
        self.row_until = self.row_started + 600
        self.preparation_started = self.row_started
        self.preparation_until = self.row_started + 180
        self.business_until = float("inf")
        root = Path(os.environ["LSP_PAYMENT_REPORT_DIR"])
        self.evidence_dir = root / method.__name__
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        self.result, self.offline, self.payments = "incomplete", False, {}
        self._record(
            "environment_start",
            revision=REVISION,
            row_started=self.row_started,
            row_deadline=self.row_until,
            preparation_deadline=self.preparation_until,
        )
        self.addCleanup(self._archive)
        try:
            with self._budget(self.preparation_until, 180):
                ChannelSigningTestBase.setup_method(self, method)
        except BaseException:
            self.doCleanups()
            raise

    def _prepare_invoice(self, tenant, amount):
        # Preparation must neither create a preimage-bearing invoice nor authorize it.
        pass

    def setUp(self):
        super().setUp()
        self.gate.release()
        assert self.gate.passthrough and self.gate.fault_mode is None
        self.original_pid = self.tenant["agent"].pid
        self.original_command = list(self.tenant["command"])
        self.original_identity = json.loads(self.tenant["status_file"].read_text())
        config = yaml.load(
            Path(self.fiber1.fiber_config_path).read_text(), Loader=yaml.BaseLoader
        )
        scripts = {entry["name"]: entry for entry in config["fiber"]["scripts"]}
        self.chain_audit = ChainAudit(
            self.node.rpcUrl, self.evidence_dir / "ckb-verifier.jsonl", transparent=True
        )
        self.addCleanup(self.chain_audit.close)
        configured = self._command(
            "preimage-configure-deployed",
            self.preparation_until,
            config={
                "url": self.chain_audit.url,
                "scripts": scripts,
                "contracts": str(Path(get_project_root()) / "source/contract/fiber"),
                "audit": str(self.evidence_dir / "independent-chain.jsonl"),
            },
        )
        assert configured["configured"] is True, configured
        assert (
            len(configured["funding_deps"]) == 2
            and len(configured["settlement_deps"]) == 3
        )
        assert configured["funding_deps"][1] == configured["settlement_deps"][1]
        self._record("ready", sdk_pid=self.original_pid, baseline=self.baseline)

    def doCleanups(self):
        self.business_until = float("inf")
        self.cleanup_until = min(self.row_until, time.monotonic() + 60)
        with self._budget(self.cleanup_until, 60):
            return super(_DelayedPaymentBase, self).doCleanups()

    def _command(self, operation, until, **values):
        payload = {"operation": operation, "channel_id": self.channel_id, **values}
        started = time.monotonic()
        with self._budget(until, 10) as due:
            with socket.create_connection(
                ("127.0.0.1", self.tenant["control_port"]),
                timeout=max(0.001, due - time.monotonic()),
            ) as conn:
                conn.sendall((json.dumps(payload) + "\n").encode())
                data = b""
                while b"\n" not in data:
                    conn.settimeout(max(0.001, due - time.monotonic()))
                    chunk = conn.recv(65536)
                    assert chunk, "SDK control closed without reply"
                    data += chunk
        response = json.loads(data.split(b"\n", 1)[0])
        self.tenant["control_calls"].append((operation, time.monotonic()))
        self._record("control", started=started, payload=payload, response=response)
        assert "error" not in response, response
        return response["result"]

    def _new_invoice(self, until):
        preimage = self.generate_random_preimage()
        payment_hash = (
            "0x"
            + hashlib.blake2b(
                bytes.fromhex(preimage[2:]), digest_size=32, person=b"ckb-default-hash"
            ).hexdigest()
        )
        params = {
            "amount": hex(AMOUNT),
            "currency": "Fibd",
            "expiry": hex(3600),
            "final_expiry_delta": hex(3_600_000),
            "payment_hash": payment_hash,
            "hash_algorithm": "ckb_hash",
            "allow_trampoline_routing": True,
            "allow_mpp": False,
        }
        invoice = self._rpc(self.client, "new_invoice", [params], until)
        assert invoice["invoice"]["data"]["payment_hash"] == payment_hash
        now = int(time.time() * 1000)
        payment = {
            "hash": payment_hash,
            "preimage": preimage,
            "amount": AMOUNT,
            "invoice": invoice["invoice_address"],
            "invoice_expiry": _number(invoice["invoice"]["data"]["timestamp"])
            + 3_600_000,
            "authorization": {
                "payment_hash": payment_hash,
                "hash_algorithm": "ckb_hash",
                "inbound": True,
                "amount": AMOUNT,
                "expires_at_ms": now + 3_600_000,
                "min_tlc_expiry_delta_ms": 900_000,
                "max_tlc_expiry_ms": now + 172_800_000,
            },
        }
        assert (
            self._rpc(
                self.client, "get_invoice", [{"payment_hash": payment_hash}], until
            )["status"]
            == "Open"
        )
        self._record("hash_only_invoice", hash=payment_hash, params=params)
        self.payments = {"A": payment}
        return payment

    def _observe_payment(self, payment, until):
        with self._budget(until, 5):
            views = self._views(until)
            paid = self._rpc(
                self.fiber2.client,
                "get_payment",
                [{"payment_hash": payment["hash"]}],
                until,
            )
            invoice = self._rpc(
                self.client, "get_invoice", [{"payment_hash": payment["hash"]}], until
            )
            signing = self._signing(self.tenant, until)
            funding = {
                k: self._rpc(
                    self.node.rpcUrl,
                    "get_live_cell",
                    [_outpoint(self.baseline[k]["channel_outpoint"]), False],
                    until,
                )
                for k in ("A", "P")
            }
            tip = _number(
                self._rpc(self.node.rpcUrl, "get_tip_block_number", [], until)
            )
            sample = self._record(
                "payment_sample",
                hash=payment["hash"],
                views=views,
                paid=paid,
                invoice=invoice,
                signing=signing,
                funding=funding,
                tip=tip,
            )
            self._health(tip)
            assert self.tenant["agent"].pid == self.original_pid
            assert list(self.tenant["command"]) == self.original_command
            assert (
                json.loads(self.tenant["status_file"].read_text())
                == self.original_identity
            )
            assert self.gate.passthrough and self.gate.fault_mode is None
            for key, view in views.items():
                assert view["state"]["state_name"] == "ChannelReady", (key, view)
                assert view["channel_id"] == self.baseline[key]["channel_id"]
                assert (
                    view["channel_outpoint"] == self.baseline[key]["channel_outpoint"]
                )
                assert not view["shutdown_transaction_hash"], (key, view)
            assert all(cell["status"] == "live" for cell in funding.values()), funding
            return sample

    def _funds_for(self, sample, count, fees, settled):
        expected = {
            "A": count * AMOUNT,
            "T-A": -count * AMOUNT,
            "P": -(count * AMOUNT + fees),
            "T-P": count * AMOUNT + fees,
        }
        for key, current in sample["views"].items():
            old = self.baseline[key]
            assert (
                _number(current["local_balance"]) - _number(old["local_balance"])
                == expected[key]
            ), (key, current)
            assert (
                _number(current["remote_balance"]) - _number(old["remote_balance"])
                == -expected[key]
            )
            if settled:
                assert not current["pending_tlcs"], (key, current)
                assert (
                    _number(current["offered_tlc_balance"])
                    == _number(current["received_tlc_balance"])
                    == 0
                )
        for left, right in (("A", "T-A"), ("P", "T-P")):
            assert (
                sample["views"][left]["local_balance"]
                == sample["views"][right]["remote_balance"]
            )
            assert (
                sample["views"][left]["remote_balance"]
                == sample["views"][right]["local_balance"]
            )
        assert (
            sum(
                _number(sample["views"][key]["local_balance"])
                - _number(self.baseline[key]["local_balance"])
                for key in ("T-A", "T-P")
            )
            == fees
        )

    def _delivered_requests(self, pending):
        expected = {
            "type": "channel_signing",
            "data": {"channel_id": self.channel_id, "status": pending},
        }
        matches = []
        for (
            accepted,
            connection,
            identity,
            topic,
        ) in self.subscription_proxy.successful_subscriptions():
            if topic != "channel_signing":
                continue
            for delivered, sub_id, event in connection.delivered_frames():
                if (
                    type(sub_id) is type(identity)
                    and sub_id == identity
                    and event == expected
                ):
                    matches.append((delivered, connection.started, accepted))
        return sorted(matches)

    def _no_unauthorized_activity(self, payment):
        requests = self.gate.audit_snapshot()["requests"]
        for request in requests:
            if request["received_at"] < payment["sent"]:
                continue
            assert request["method"] != "submit_channel_signature", request
            assert not (
                request["method"] in ("settle_invoice", "create_preimage")
                and payment["hash"] in json.dumps(request["params"])
            ), request
            assert payment["preimage"] not in json.dumps(request["params"]), request

    def _visible_path(self, payment, sample, pending=None, record=None):
        # Before signing, some endpoints need not expose an active TLC yet.
        tlcs = {}
        expiries = []
        for key, direction in (
            ("A", "Inbound"),
            ("T-A", "Outbound"),
            ("P", "Outbound"),
            ("T-P", "Inbound"),
        ):
            visible = sample["views"][key]["pending_tlcs"]
            assert all(t["payment_hash"] == payment["hash"] for t in visible), (
                key,
                visible,
            )
            assert len(visible) <= 1, (key, visible)
            if not visible:
                continue
            tlc = visible[0]
            assert direction in tlc["status"], (key, tlc)
            amount = _number(tlc["amount"])
            if key in ("A", "T-A"):
                assert amount == AMOUNT
            else:
                assert AMOUNT <= amount <= AMOUNT + 10_000
                if "upstream_amount" in payment:
                    assert payment["upstream_amount"] == amount
                payment["upstream_amount"] = amount
            tlcs[key] = {k: tlc[k] for k in ("id", "payment_hash", "amount", "expiry")}
            expiries.append(_number(tlc["expiry"]))
        assert (
            "upstream_amount" in payment
        ), "missing actual upstream amount/expiry evidence"
        for left, right in (("A", "T-A"), ("P", "T-P")):
            if left in tlcs and right in tlcs:
                assert tlcs[left] == tlcs[right]
        if pending is not None:
            target = [
                t
                for t in pending["settlement"]["tlcs"]
                if t["payment_hash"] == payment["hash"]
            ]
            assert len(target) == 1 and target[0]["inbound"]
            assert _number(target[0]["payment_amount"]) == AMOUNT
            expiries.append(_number(target[0]["expiry"]))
        if record is not None:
            expiries.extend(
                _number(t["expiry"])
                for t in record["tlcs"]
                if t["payment_hash"] == payment["hash"]
            )
        assert expiries, "no actual TLC expiry evidence"
        cutoffs = [
            payment["invoice_expiry"],
            payment["authorization"]["expires_at_ms"],
            payment["sent_wall_ms"] + 1_200_000,
        ]
        # Fixed test topology uses one epoch and a trusted 2000 ms devnet epoch.
        terms = self.tenant["opening"]["parameters"]
        assert terms["epoch_duration_ms"] == 2000
        since = int.from_bytes(bytes(terms["delay_epoch"]), "little")
        assert since >> 56 == 0xA0 and since & 0x00FFFFFFFFFFFFFF == 0x10000000001
        assert (
            _number(self.channel_open_options["commitment_delay_epoch"])
            == 0x10000000001
        )
        for expiry in expiries:
            cutoffs.extend(
                (
                    expiry - 1333,
                    expiry // 1000 * 1000 - 1334,
                    expiry // 1000 * 1000 - 900_000,
                )
            )
        payment["safety_until_ms"] = min(
            cutoffs + [payment.get("safety_until_ms", float("inf"))]
        )
        self._record(
            "visible_path",
            hash=payment["hash"],
            tlcs=tlcs,
            cutoffs_ms=cutoffs,
            safety_until_ms=payment["safety_until_ms"],
        )

    def _complete_payment(self, payment, number, previous_fees, before, until):
        # Wait only for evidence; release-preimage itself is called exactly once.
        while True:
            records = self._control(self.tenant, "records", until)
            latest = next(
                (r for r in reversed(records) if r["complete"] and not r["for_remote"]),
                None,
            )
            if latest and any(
                t["payment_hash"] == payment["hash"] for t in latest["tlcs"]
            ):
                break
            self._pause(until, 0.2)
        held = self._observe_payment(payment, until)
        self._visible_path(payment, held, record=latest)
        self._margin("A", 180)
        self._record("safe_release_start", hash=payment["hash"], recovery_record=latest)
        released = self._command(
            "release-preimage-deployed",
            until,
            payment_hash=payment["hash"],
            preimage=payment["preimage"],
        )
        assert released == {"released": True}, released
        audit = self.gate.audit_snapshot()["requests"]
        assert any(
            r["method"] == "settle_invoice"
            and payment["hash"] in json.dumps(r["params"])
            and r["forward_started_at"] is not None
            and r["reply"] is not None
            and "error" not in r["reply"]
            for r in audit
        ), "original Agent did not settle the invoice"
        while True:
            sample = self._observe_payment(payment, until)
            assert sample["paid"]["status"] != "Failed", sample
            if (
                sample["paid"]["status"] == "Success"
                and sample["invoice"]["status"] == "Paid"
                and sample["signing"]["type"] == "NoSignatureRequired"
                and all(not c["pending_tlcs"] for c in sample["views"].values())
            ):
                break
            self._pause(until, 0.2)
        fee = _number(sample["paid"]["fee"])
        assert 0 <= fee <= 10_000 and payment["upstream_amount"] == AMOUNT + fee
        self._funds_for(sample, number, previous_fees + fee, True)
        for key, delta in {
            "A": AMOUNT,
            "T-A": -AMOUNT,
            "P": -AMOUNT - fee,
            "T-P": AMOUNT + fee,
        }.items():
            assert (
                _number(sample["views"][key]["local_balance"])
                - _number(before[key]["local_balance"])
                == delta
            )
            assert (
                _number(sample["views"][key]["remote_balance"])
                - _number(before[key]["remote_balance"])
                == -delta
            )
        stable_start = time.monotonic()
        for _ in range(5):
            self._pause(until, 1)
            stable = self._observe_payment(payment, min(until, stable_start + 10))
            assert (
                stable["paid"]["status"] == "Success"
                and stable["invoice"]["status"] == "Paid"
            )
            assert _number(stable["paid"]["fee"]) == fee
            assert stable["signing"]["type"] == "NoSignatureRequired"
            self._funds_for(stable, number, previous_fees + fee, True)
            assert stable["views"] == sample["views"]
        assert 5 <= time.monotonic() - stable_start <= 10
        self._record(
            "settled",
            number=number,
            hash=payment["hash"],
            fee=fee,
            cumulative_fees=previous_fees + fee,
            views=sample["views"],
        )
        return fee, sample["views"]

    # TEST-MAP: LSP-PAYMENT-04
    def test_missing_authorization_recovers_same_process_and_next_payment(self):
        """
        1. 只创建hash发票，真实付款触发SDK缺授权拒签并自然重连。
        2. 同进程明确补授权，由原SDK恢复原请求并安全释放后完成付款。
        3. 原通道再完成一笔付款，核对逐笔/累计资金和原付款历史。
        """
        # 1. 目标hash无预授权；代理全放行，拒签必须来自真实SDK。
        payment = self._new_invoice(self.preparation_until)
        assert not any(
            op
            in ("invoice", "fulfill", "release-preimage", "release-preimage-deployed")
            for op, _ in self.tenant["control_calls"]
        )
        log = self.tenant["status_file"].with_name("agent.log")
        log_offset = log.stat().st_size
        self.business_until = min(self.row_until - 60, time.monotonic() + 360)
        until = min(self.business_until, time.monotonic() + 60)
        self._send("A", until)
        pending = None
        rejected_at = None
        first_connection = None
        observation_completed = False
        while True:
            sample = self._observe_payment(payment, until)
            self._funds_for(sample, 0, 0, False)
            self._no_unauthorized_activity(payment)
            assert sample["paid"]["status"] not in ("Success", "Failed"), sample
            assert sample["invoice"]["status"] in ("Open", "Received"), sample
            status = sample["signing"]
            with log.open() as stream:
                stream.seek(log_offset)
                errors = stream.read()
            if pending is None and status["type"] == "SignatureRequired":
                assert any(
                    t["payment_hash"] == payment["hash"]
                    and _number(t["payment_amount"]) == AMOUNT
                    and t["inbound"]
                    for t in status["settlement"]["tlcs"]
                ), status
                deliveries = self._delivered_requests(status)
                if deliveries and "TLC has no local payment authorization" in errors:
                    pending = status
                    first_connection = deliveries[0][1]
                    rejected_at = time.monotonic()
                    self._visible_path(payment, sample, pending=pending)
                    self._margin("A", 900)
                    self._record(
                        "real_rejection",
                        pending=pending,
                        log_offset=log_offset,
                        sdk_errors=errors,
                        deliveries=deliveries,
                        sdk_pid=self.original_pid,
                    )
            if pending is not None:
                assert (
                    status == pending
                ), "original request changed before authorization"
                deliveries = self._delivered_requests(pending)
                reconnected = [
                    d
                    for d in deliveries
                    if d[1] > first_connection and d[0] > deliveries[0][0]
                ]
                if not observation_completed and time.monotonic() >= rejected_at + 10:
                    assert (
                        time.monotonic() <= rejected_at + 15
                    ), "rejection observation exceeded 15s"
                    observation_completed = True
                    self._record("rejection_window_complete", pending=pending)
                if observation_completed and reconnected:
                    self._record(
                        "natural_redelivery", pending=pending, deliveries=reconnected
                    )
                    break
            self._pause(until, 1)

        # 2. 控制分支保存授权；不重启、不重发、不由Python提交签名。
        self._margin("A", 180)
        until = min(self.business_until, time.monotonic() + 60)
        auth_started = time.monotonic()
        result = self._command(
            "invoice",
            until,
            authorization=payment["authorization"],
            preimage=payment["preimage"],
        )
        assert result == {"saved": True}, result
        self._record("authorization_saved", hash=payment["hash"], started=auth_started)
        while True:
            assert (
                self.tenant["agent"].pid == self.original_pid
                and self.tenant["agent"].poll() is None
            )
            matches = [
                r
                for r in self.gate.audit_snapshot()["requests"]
                if r["method"] == "submit_channel_signature"
                and r["params"]["request_id"] == pending["request_id"]
            ]
            if matches and matches[0]["reply"] is not None:
                first = matches[0]
                assert (
                    first["received_at"] >= auth_started
                    and first["action"] == "forward"
                ), first
                assert first["reply"].get("result") == {"type": "Applied"}, first
                self._record(
                    "first_applied",
                    pending=pending,
                    audit=first,
                    sdk_pid=self.original_pid,
                )
                break
            self._pause(until, 0.1)
        first_fee, first_views = self._complete_payment(
            payment,
            1,
            0,
            self.baseline,
            min(self.business_until, time.monotonic() + 90),
        )

        # 3. 同两条通道、同PID完成下一笔；重新核对两笔历史与累计账本。
        second_until = min(self.business_until, time.monotonic() + 90)
        second = self._new_invoice(second_until)
        assert (
            second["hash"] != payment["hash"]
            and second["preimage"] != payment["preimage"]
        )
        assert self._command(
            "invoice",
            second_until,
            authorization=second["authorization"],
            preimage=second["preimage"],
        ) == {"saved": True}
        self._send("A", second_until)
        second_fee, final_views = self._complete_payment(
            second, 2, first_fee, first_views, second_until
        )
        until = min(self.business_until, time.monotonic() + 20)
        for old, fee in ((payment, first_fee), (second, second_fee)):
            paid = self._rpc(
                self.fiber2.client,
                "get_payment",
                [{"payment_hash": old["hash"]}],
                until,
            )
            invoice = self._rpc(
                self.client, "get_invoice", [{"payment_hash": old["hash"]}], until
            )
            assert paid["status"] == "Success" and invoice["status"] == "Paid"
            assert _number(paid["fee"]) == fee
            self._record(
                "history_verified", hash=old["hash"], paid=paid, invoice=invoice
            )
        self.result = "passed"
        self._record(
            "passed",
            hashes=[payment["hash"], second["hash"]],
            fees=[first_fee, second_fee],
            final_views=final_views,
            same_sdk_pid=self.original_pid,
        )

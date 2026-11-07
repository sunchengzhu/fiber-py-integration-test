"""Authorized 01/02 implementation draft for fixed 84333ee Hosted invoice cancellation.

The first tenant cancel is expected to fail on 843's allowlist. Keep the full
post-cancel assertions for a separately pinned repair revision; do not substitute
an operator credential or call settle_invoice directly from Python. Received
cancellation (03) remains an open product-contract decision.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import time

import yaml

from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._lsp_test import (
    ChannelSigningTestBase,
    REVISION,
    RETEST_REVISION,
)
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
    _DelayedPaymentBase,
    _number,
    _outpoint,
)

FIXED_REVISION = "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"
AMOUNT = 1_000_000
FEE_CAP = 10_000


def _ckb_hash(preimage):
    return (
        "0x"
        + hashlib.blake2b(
            bytes.fromhex(preimage.removeprefix("0x")),
            digest_size=32,
            person=b"ckb-default-hash",
        ).hexdigest()
    )


class _CancellationBase(_DelayedPaymentBase):
    tenant_labels = ("A",)

    @classmethod
    def setup_class(cls):
        root = Path(__file__).resolve().parents[4]
        (root / "tmp").mkdir(exist_ok=True)
        cls.tmp_path_name = str(
            Path(tempfile.mkdtemp(prefix="lsp-cancel-", dir=root / "tmp")).relative_to(
                root
            )
        )
        super().setup_class()
        cls.prepare_isolated_contract(root)

    @classmethod
    def prepare_isolated_contract(cls, root):
        """Align this class's devnet before FNN starts, as the watchtower suite does."""
        path = root / "source/contract/fiber/commitment-lock"
        expected = path.read_bytes()
        assert hashlib.sha256(expected).hexdigest() == (
            "a7762721ef239b15adbdddca8d772db6e1c001d9f81e23ccc74e1392329931d7"
        ), "not the reviewed 04c2064 commitment-lock"
        script = {
            "code_hash": "0x" + "00" * 25 + "545950455f4944",
            "hash_type": "type",
            "args": "0x082d30abbb75c3db217a78eee4f3e0d5a46c90b56c11dec77f3060319f323808",
        }
        client = cls.node.getClient()
        search = {
            "script": script,
            "script_type": "type",
            "script_search_mode": "exact",
            "with_data": True,
        }
        cells = client.get_cells(search, "asc", "0x10", None)["objects"]
        assert len(cells) == 1, cells
        old = cells[0]
        report_root = Path(os.environ.get("LSP_PAYMENT_REPORT_DIR", root / "report"))
        report_root.mkdir(parents=True, exist_ok=True)
        evidence_path = report_root / f"{cls.__name__}-isolated-contract.json"
        assert not evidence_path.exists(), evidence_path
        evidence = {
            "revision": REVISION,
            "chain_dir": cls.node.ckb_dir,
            "before": old,
            "expected_sha256": hashlib.sha256(expected).hexdigest(),
        }
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        tx_hash = cls.Contract.upgrade_ckb_type_contract(
            cls.Config.MINER_PRIVATE_1,
            str(path),
            old["out_point"]["tx_hash"],
            int(old["out_point"]["index"], 16),
            fee=200000,
            api_url=cls.node.rpcUrl,
        )
        evidence["submitted"] = tx_hash
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        confirmed = cls.Miner.miner_until_tx_committed(cls.node, tx_hash)
        tx = confirmed["transaction"]
        assert tx["outputs"][0]["type"] == script
        assert tx["outputs"][0]["lock"] == old["output"]["lock"]
        assert any(i["previous_output"] == old["out_point"] for i in tx["inputs"])
        assert bytes.fromhex(tx["outputs_data"][0].removeprefix("0x")) == expected
        header = client.call("get_header", [confirmed["tx_status"]["block_hash"]])
        assert client.get_block_hash(header["number"]) == header["hash"]
        live = client.get_live_cell("0x0", tx_hash, True)
        assert live["status"] == "live"
        assert bytes.fromhex(
            live["cell"]["data"]["content"].removeprefix("0x")
        ) == expected
        cells = client.get_cells(search, "asc", "0x10", None)["objects"]
        assert len(cells) == 1 and cells[0]["out_point"] == {
            "tx_hash": tx_hash,
            "index": "0x0",
        }
        evidence.update(confirmed=confirmed, canonical_header=header, after=cells[0])
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")

    def setup_method(self, method):
        assert REVISION == FIXED_REVISION or (
            RETEST_REVISION is not None and REVISION == RETEST_REVISION
        ), "use a separately reviewed revision for repair regression"
        self.preparation_started = time.monotonic()
        self.preparation_until = self.preparation_started + 240
        self.business_until = self.preparation_started + 420
        self.row_until = self.preparation_started + 480
        root = os.environ.get("LSP_PAYMENT_REPORT_DIR")
        if root is None:
            Path("report").mkdir(exist_ok=True)
            root = tempfile.mkdtemp(prefix="lsp-cancel-84333ee-", dir="report")
        self.evidence_dir = Path(root).resolve() / method.__name__
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        self.result = "incomplete"
        self.offline = False
        self.payments = {}
        self._record(
            "environment_start",
            revision=REVISION,
            preparation_until=self.preparation_until,
            business_until=self.business_until,
            row_until=self.row_until,
        )
        self.addCleanup(self._archive)
        try:
            with self._budget(self.preparation_until, 240):
                ChannelSigningTestBase.setup_method(self, method)
        except BaseException:
            self.doCleanups()
            raise

    def _prepare_invoice(self, tenant, amount):
        # Parent setUp invokes this for its old preimage-bearing fixture. A fresh
        # hash-only invoice is created explicitly in each scenario instead.
        pass

    def setUp(self):
        super().setUp()
        for tenant in self.tenants:
            tenant["gate"].release()
        self._record(
            "cancel_fixture_ready",
            tenant_ids={
                t["label"]: json.loads(t["status_file"].read_text())["tenant_id"]
                for t in self.tenants
            },
        )

    def doCleanups(self):
        self.business_until = float("inf")
        self.cleanup_until = min(self.row_until, time.monotonic() + 60)
        first_error = None
        while self._cleanups:
            if time.monotonic() >= self.cleanup_until:
                self._record(
                    "cleanup_deadline",
                    remaining=[item[0].__name__ for item in self._cleanups],
                )
                raise AssertionError("cancellation cleanup deadline exhausted")
            function, args, kwargs = self._cleanups.pop()
            try:
                # Re-arm the same absolute deadline for every callback.
                with self._budget(self.cleanup_until, 60):
                    self._callCleanup(function, *args, **kwargs)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
        return True

    def teardown_method(self, method):
        self.cleanup_until = min(
            self.row_until,
            getattr(self, "cleanup_until", self.row_until),
            time.monotonic() + 60,
        )
        return super().teardown_method(method)

    def _new_hold(self, tenant, label, until):
        preimage = self.generate_random_preimage()
        payment_hash = _ckb_hash(preimage)
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
        assert "payment_preimage" not in params
        invoice = self._rpc(tenant["client"], "new_invoice", [params], until)
        assert invoice["invoice"]["data"]["payment_hash"] == payment_hash
        assert self._invoice(tenant, {"hash": payment_hash}, until)["status"] == "Open"
        now_ms = int(time.time() * 1000)
        authorization = {
            "payment_hash": payment_hash,
            "hash_algorithm": "ckb_hash",
            "inbound": True,
            "amount": AMOUNT,
            "expires_at_ms": now_ms + 3_600_000,
            "min_tlc_expiry_delta_ms": 900_000,
            "max_tlc_expiry_ms": now_ms + 172_800_000,
        }
        self._control(
            tenant,
            "invoice",
            until,
            {"authorization": authorization, "preimage": preimage},
        )
        payment = {
            "tenant": tenant,
            "hash": payment_hash,
            "preimage": preimage,
            "invoice": invoice["invoice_address"],
            "amount": AMOUNT,
            "invoice_expiry": _number(invoice["invoice"]["data"]["timestamp"])
            + 3_600_000,
            "authorization": authorization,
        }
        self.payments[label] = payment
        self._record(
            "hash_only_invoice",
            label=label,
            params=params,
            payment_hash=payment_hash,
            tenant_id=json.loads(tenant["status_file"].read_text())["tenant_id"],
        )
        return payment

    def _invoice(self, tenant, payment, until):
        return self._rpc(
            tenant["client"], "get_invoice", [{"payment_hash": payment["hash"]}], until
        )

    def _cancel(self, tenant, payment, until):
        # This tenant client holds the real tenant Biscuit from the original Agent.
        token = tenant["client"].other_params["Authorization"]
        assert (
            token.startswith("Bearer ")
            and token != self.fiber1.client.other_params["Authorization"]
        )
        result = self._rpc(
            tenant["client"],
            "cancel_invoice",
            [{"payment_hash": payment["hash"]}],
            until,
        )
        assert result["status"] == "Cancelled", result
        assert self._invoice(tenant, payment, until)["status"] == "Cancelled"
        return result

    def _authorize_cancellation(self, tenant, payment, until):
        self._control(
            tenant,
            "cancel",
            until,
            {"payment_hash": payment["hash"]},
        )
        self._record("local_cancel_authorized", payment_hash=payment["hash"])

    def _pause_submissions(self, tenant):
        with tenant["gate"].lock:
            tenant["gate"].passthrough = False

    def _release_submissions(self, tenant):
        tenant["gate"].release()

    def _wait_new_submission(self, tenant, before, until):
        while True:
            with tenant["gate"].lock:
                fresh = [
                    request_id
                    for request_id in tenant["gate"].submissions
                    if request_id not in before
                ]
            if fresh:
                return fresh[0]
            self._pause(until, 0.05)

    def _submit_held(self, tenant, request_id, until):
        with tenant["gate"].lock:
            submission = copy.deepcopy(tenant["gate"].submissions[request_id])
        assert submission["channel_id"] == tenant["channel_id"], submission
        result = self._rpc(
            tenant["client"],
            "submit_channel_signature",
            [submission],
            until,
        )
        assert result["type"] in ("Applied", "AlreadyApplied"), result
        self._record(
            "held_signature_submitted",
            request_id=request_id,
            result=result,
        )
        return result

    def _payment(self, payment, until):
        return self._rpc(
            self.fiber2.client,
            "get_payment",
            [{"payment_hash": payment["hash"]}],
            until,
        )

    def _send_payment(self, payment, until):
        result = self._rpc(
            self.fiber2.client,
            "send_payment",
            [
                {
                    "invoice": payment["invoice"],
                    "max_fee_amount": hex(FEE_CAP),
                    "tlc_expiry_limit": hex(86_400_000),
                    "timeout": hex(120),
                }
            ],
            until,
        )
        assert result["payment_hash"] == payment["hash"], result
        payment["sent"] = time.monotonic()
        return result

    def _observe(self, payment, until):
        views = self._views(until)
        payer = self._payment(payment, until)
        invoice = self._invoice(payment["tenant"], payment, until)
        tip = _number(self._rpc(self.node.rpcUrl, "get_tip_block_number", [], until))
        self._health(tip)
        for key, view in views.items():
            assert view["state"]["state_name"] == "ChannelReady", (key, view)
            assert view["channel_outpoint"] == self.baseline[key]["channel_outpoint"]
            assert not view["shutdown_transaction_hash"]
        for key in ("P",) + tuple("T-" + t["label"] for t in self.tenants):
            cell = self._rpc(
                self.node.rpcUrl,
                "get_live_cell",
                [_outpoint(self.baseline[key]["channel_outpoint"]), False],
                until,
            )
            assert cell["status"] == "live", (key, cell)
        return self._record(
            "cancel_sample",
            hash=payment["hash"],
            views=views,
            payer=payer,
            invoice=invoice,
            tip=tip,
        )

    @staticmethod
    def _active_tlcs(view):
        # list_channels exposes every TLC record, including removed ones whose
        # status is RemoveAckConfirmed. Those are terminal bookkeeping, not
        # still-pending funds; only non-terminal records count as pending.
        active = []
        for tlc in view["pending_tlcs"]:
            status = tlc.get("status")
            if isinstance(status, dict):
                state = next(iter(status.values()), None)
            else:
                state = status
            if state != "RemoveAckConfirmed":
                active.append(tlc)
        return active

    def _assert_settled_funds(self, sample, recipient, amount, fee):
        assert 0 <= fee <= FEE_CAP
        expected = {key: 0 for key in self.baseline}
        if recipient is not None:
            expected.update(
                {
                    "P": -(amount + fee),
                    "T-P": amount + fee,
                    "T-" + recipient: -amount,
                    recipient: amount,
                }
            )
        views = sample["views"]
        for key, view in views.items():
            original = self.baseline[key]
            assert (
                _number(view["local_balance"]) - _number(original["local_balance"])
                == expected[key]
            ), key
            assert (
                _number(view["remote_balance"]) - _number(original["remote_balance"])
                == -expected[key]
            ), key
            assert _number(view["offered_tlc_balance"]) == 0, key
            assert _number(view["received_tlc_balance"]) == 0, key
            assert not self._active_tlcs(view), key
        for key in ("A", "B"):
            if key in views:
                assert (
                    views[key]["local_balance"] == views["T-" + key]["remote_balance"]
                )
                assert (
                    views[key]["remote_balance"] == views["T-" + key]["local_balance"]
                )
        assert views["P"]["local_balance"] == views["T-P"]["remote_balance"]
        assert views["P"]["remote_balance"] == views["T-P"]["local_balance"]
        lsp_income = sum(expected[k] for k in expected if k.startswith("T-"))
        assert lsp_income == fee

    def _no_old_release(self, payment):
        for tenant in self.tenants:
            audit = tenant["gate"].audit_snapshot()["requests"]
            assert not any(
                r["method"] in ("settle_invoice", "create_preimage")
                and payment["hash"] in json.dumps(r["params"])
                for r in audit
            ), audit

    def _sdk_control(self, tenant, operation, until, values):
        payload = {"operation": operation, "channel_id": tenant["channel_id"], **values}
        with self._budget(until, 10) as due:
            with socket.create_connection(
                ("127.0.0.1", tenant["control_port"]),
                timeout=max(0.001, due - time.monotonic()),
            ) as conn:
                conn.sendall((json.dumps(payload) + "\n").encode())
                data = b""
                while b"\n" not in data:
                    conn.settimeout(max(0.001, due - time.monotonic()))
                    part = conn.recv(65536)
                    assert part, "SDK control closed without reply"
                    data += part
        body = json.loads(data.split(b"\n", 1)[0])
        tenant["control_calls"].append((operation, time.monotonic()))
        self._record("control", label=tenant["label"], payload=payload, response=body)
        assert "error" not in body, body
        return body["result"]

    def _configure_chain(self, tenant, until):
        # Resolve the deployed Type ID contracts independently instead of comparing
        # the fixed devnet genesis against the local contract directory.
        config = yaml.load(
            Path(self.fiber1.fiber_config_path).read_text(), Loader=yaml.BaseLoader
        )
        scripts = {item["name"]: item for item in config["fiber"]["scripts"]}
        result = self._sdk_control(
            tenant,
            "preimage-configure-deployed",
            until,
            {
                "config": {
                    "url": self.node.rpcUrl,
                    "scripts": scripts,
                    "contracts": str(
                        Path(get_project_root()) / "source/contract/fiber"
                    ),
                    "audit": str(self.evidence_dir / "independent-chain.jsonl"),
                }
            },
        )
        assert result["configured"] is True

    def _safe_release(self, tenant, payment, until):
        # The newest complete local record must contain this hash. Older records
        # may legitimately contain it too; the original Agent decides release.
        while True:
            records = self._control(tenant, "records", until)
            latest = next(
                (r for r in reversed(records) if r["complete"] and not r["for_remote"]),
                None,
            )
            if latest is not None and any(
                t["payment_hash"] == payment["hash"] for t in latest["tlcs"]
            ):
                break
            self._pause(until, 0.1)
        while True:
            invoice = self._invoice(tenant, payment, until)
            if invoice["status"] == "Received":
                break
            self._pause(until, 0.1)
        result = self._sdk_control(
            tenant,
            "release-preimage-deployed",
            until,
            {
                "payment_hash": payment["hash"],
                "preimage": payment["preimage"],
            },
        )
        assert result["released"] is True
        self._record(
            "safe_preimage_release",
            payment_hash=payment["hash"],
            recovery_record=latest,
        )

    def _wait_terminal(self, payment, expected_payment, expected_invoice, until):
        while True:
            sample = self._observe(payment, until)
            if (
                sample["payer"]["status"] == expected_payment
                and sample["invoice"]["status"] == expected_invoice
            ):
                if all(
                    not self._active_tlcs(v)
                    and _number(v["offered_tlc_balance"]) == 0
                    and _number(v["received_tlc_balance"]) == 0
                    for v in sample["views"].values()
                ):
                    return sample
            self._pause(until, 0.1)


class TestHostedInvoiceCancellation(_CancellationBase):
    # TEST-MAP: LSP-INVOICE-CANCEL-01
    def test_open_invoice_cancelled_old_payment_fails_new_payment_succeeds(self):
        """
        1. A 以真实租户身份创建仅含 hash 的 Open 发票并取消。
        2. P 尝试旧发票，核对失败终态、零费用和全部通道余额回基线。
        3. 独立新发票经原 Agent 安全释放，按实际费用核对付款和资金。
        """
        until = self.business_until
        # 1. 原 A token 取消原 hash；843 的 allowlist 拒绝应保留为诊断证据。
        old = self._new_hold(self.tenant, "old", until)
        self._cancel(self.tenant, old, until)

        # 2. 旧 hash 没有 SDK 预像释放，异步终态和四端资金均需证实。
        # 先扣住新 TLC 的签名，等 TLC 在 SDK 状态中存在后再写本地退款授权；
        # 这样失败移除到达时 SDK 已能接受，而不是在“新 TLC 已 resolved”处拒绝。
        before = set(self.tenant["gate"].submissions)
        self._pause_submissions(self.tenant)
        self._send_payment(old, until)
        request_id = self._wait_new_submission(self.tenant, before, until)
        self._authorize_cancellation(self.tenant, old, until)
        self._release_submissions(self.tenant)
        self._submit_held(self.tenant, request_id, until)
        failed = self._wait_terminal(old, "Failed", "Cancelled", until)
        assert _number(failed["payer"]["fee"]) == 0
        self._assert_settled_funds(failed, None, 0, 0)
        self._no_old_release(old)

        # 3. 新 hash 先通过原 Agent 链验证，再由其 tenant token 释放预像。
        fresh = self._new_hold(self.tenant, "fresh", until)
        self._configure_chain(self.tenant, until)
        self._send_payment(fresh, until)
        self._safe_release(self.tenant, fresh, until)
        settled = self._wait_terminal(fresh, "Success", "Paid", until)
        fee = _number(settled["payer"]["fee"])
        self._assert_settled_funds(settled, "A", AMOUNT, fee)
        self._no_old_release(old)
        self.result = "passed"


    # TEST-MAP: LSP-INVOICE-CANCEL-03
    def test_received_invoice_without_preimage_can_be_cancelled(self):
        """
        1. A 的 hold invoice 经真实 P→T→A 付款进入 Received，节点无 preimage。
        2. A 用 tenant token 取消，原付款失败、TLC/锁定额清理、旧发票不复活。
        3. 新建发票并完成一笔付款，确认通道仍可正常使用。
        """
        until = self.business_until
        payment = self._new_hold(self.tenant, "received", until)
        self._send_payment(payment, until)
        while True:
            invoice = self._invoice(self.tenant, payment, until)
            payer = self._payment(payment, until)
            views = self._views(until)
            pending = [
                tlc
                for view in views.values()
                for tlc in view["pending_tlcs"]
                if tlc["payment_hash"] == payment["hash"]
            ]
            if (
                invoice["status"] == "Received"
                and payer["status"] == "Inflight"
                and pending
            ):
                break
            assert payer["status"] not in ("Success", "Failed"), (invoice, payer)
            self._pause(until, 0.1)
        # The SDK must locally authorize the refund before it can sign the
        # commitment that removes the hold TLC. RPC cancellation alone is not
        # sufficient.
        self._authorize_cancellation(self.tenant, payment, until)
        self._cancel(self.tenant, payment, until)
        failed = self._wait_terminal(payment, "Failed", "Cancelled", until)
        assert _number(failed["payer"]["fee"]) == 0
        self._assert_settled_funds(failed, None, 0, 0)
        self._no_old_release(payment)

        # The cancelled invoice and failed payment must remain terminal for a
        # full 30-second window; a later background retry must not revive them.
        stable_until = time.monotonic() + 30
        assert stable_until <= until - 60, (
            "insufficient budget for the full 30-second cancellation stability window",
            until - time.monotonic(),
        )
        while time.monotonic() < stable_until:
            assert self._invoice(self.tenant, payment, until)["status"] == "Cancelled"
            assert self._payment(payment, until)["status"] == "Failed"
            self._pause(until, 0.2)

        fresh = self._new_hold(self.tenant, "fresh", until)
        self._configure_chain(self.tenant, until)
        self._send_payment(fresh, until)
        self._safe_release(self.tenant, fresh, until)
        settled = self._wait_terminal(fresh, "Success", "Paid", until)
        self._assert_settled_funds(
            settled, "A", AMOUNT, _number(settled["payer"]["fee"])
        )
        self.result = "passed"

class TestHostedInvoiceCancellationIsolation(_CancellationBase):
    tenant_labels = ("A", "B")

    # TEST-MAP: LSP-INVOICE-CANCEL-02
    def test_other_tenant_cannot_cancel_owned_invoice(self):
        """
        1. A/B 各创建真实 Open hash-only 发票，B 取消自己的发票。
        2. B 用同一租户身份取消 A 发票必须被拒，A 状态与资金不变。
        3. A 经原 Agent 安全释放其发票，按实际费用核对全部通道。
        """
        until = self.business_until
        a, b = self.tenants
        # 1. 正向入口证明 B token 能取消自己，而非统一拒绝。
        target = self._new_hold(a, "A", until)
        own = self._new_hold(b, "B", until)
        self._cancel(b, own, until)

        # 2. 跨租户必须得到真实 RPC error，并保持 A 的原状态与零资金。
        before = self._views(until)
        try:
            self._rpc(
                b["client"], "cancel_invoice", [{"payment_hash": target["hash"]}], until
            )
        except AssertionError as error:
            assert "cancel_invoice" in str(error), error
        else:
            assert False, "B unexpectedly cancelled A's invoice"
        assert self._invoice(a, target, until)["status"] == "Open"
        after = self._views(until)
        for key in ("A", "T-A"):
            for field in (
                "channel_id",
                "channel_outpoint",
                "state",
                "local_balance",
                "remote_balance",
                "offered_tlc_balance",
                "received_tlc_balance",
                "pending_tlcs",
            ):
                assert after[key][field] == before[key][field], (key, field)
        self._assert_settled_funds({"views": before}, None, 0, 0)
        self._assert_settled_funds({"views": after}, None, 0, 0)

        # 3. A's genuine Agent verifies funding before its tenant-token settlement.
        self._configure_chain(a, until)
        self._send_payment(target, until)
        self._safe_release(a, target, until)
        settled = self._wait_terminal(target, "Success", "Paid", until)
        fee = _number(settled["payer"]["fee"])
        self._assert_settled_funds(settled, "A", AMOUNT, fee)
        assert self._invoice(b, own, until)["status"] == "Cancelled"
        self.result = "passed"

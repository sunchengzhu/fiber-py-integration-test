"""Hosted external-signer outbound payment: A -> T -> ordinary node P."""

import hashlib
import time

from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import HostedTenantFixture
from test_cases.fiber.devnet.lsp._lsp_test import REVISION, RETEST_REVISION

# The reviewed Hosted outbound payment gate: the fixed 843 revision or an
# explicitly declared repair-revision regression.
FIXED_REVISION = "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"


def revision_allowed(revision, retest_revision):
    return revision == FIXED_REVISION or (
        retest_revision is not None and revision == retest_revision
    )


def _payment_hash(preimage):
    return "0x" + hashlib.blake2b(
        bytes.fromhex(preimage.removeprefix("0x")),
        digest_size=32,
        person=b"ckb-default-hash",
    ).hexdigest()


class TestHostedOutboundPayment(HostedTenantFixture):
    tenant_labels = ("A",)

    @classmethod
    def setup_class(cls):
        assert revision_allowed(
            REVISION, RETEST_REVISION
        ), "use a separately reviewed revision for repair regression"
        super().setup_class()

    # TEST-MAP: LSP-PAYMENT-05
    def test_hosted_tenant_pays_ordinary_node(self):
        """
        1. A 的真实外部签名通道已就绪，P 已有 T–P 路由。
        2. A 发起真实 invoice payment，经 T 到 P。
        3. 断言 A 付款成功、P 发票 Paid；准备或终态失败均正常失败。
        """
        a = self.tenants[0]
        preimage = self.generate_random_preimage()
        payment_hash = _payment_hash(preimage)
        params = {
            "amount": hex(1_000_000),
            "currency": "Fibd",
            "expiry": hex(600),
            "payment_preimage": preimage,
            "hash_algorithm": "ckb_hash",
            "allow_trampoline_routing": True,
            "allow_mpp": False,
        }
        invoice = self.fiber2.client.call("new_invoice", [params])
        assert invoice["invoice"]["data"]["payment_hash"] == payment_hash
        # The SDK must locally authorize the outbound A-T TLC before it signs
        # the commitment. The first trampoline segment carries the invoice
        # amount plus the effective fee cap: min(max_fee=10_000, 5/1000).
        now_ms = int(time.time() * 1000)
        authorized_amount = 1_000_000 + min(10_000, 1_000_000 * 5 // 1000)
        authorization = {
            "payment_hash": payment_hash,
            "hash_algorithm": "ckb_hash",
            "inbound": False,
            "amount": authorized_amount,
            "expires_at_ms": now_ms + 600_000,
            "min_tlc_expiry_delta_ms": 300_000,
            "max_tlc_expiry_ms": now_ms + 86_400_000,
        }
        self._control(
            a,
            "outgoing-payment",
            self.business_until,
            {"authorization": authorization},
        )
        result = a["client"].call(
            "send_payment",
            [
                {
                    "invoice": invoice["invoice_address"],
                    "max_fee_amount": hex(10_000),
                    "tlc_expiry_limit": hex(86_400_000),
                    "timeout": hex(120),
                    "trampoline_hops": [self.fiber1.get_pubkey()],
                }
            ],
        )
        # A's SDK must also authorize fulfillment once the outbound TLC has
        # been accepted. P's settlement reveals the preimage, but the local
        # resolution still has to be persisted before A can sign its removal.
        fulfill_until = min(self.business_until, time.monotonic() + 30)
        while True:
            records = self._control(a, "records", fulfill_until)
            if any(
                tlc["payment_hash"] == payment_hash
                for record in records
                for tlc in record["tlcs"]
            ):
                break
            self._pause(fulfill_until, 0.1)
        self._control(
            a,
            "fulfill",
            fulfill_until,
            {"payment_hash": payment_hash, "preimage": preimage},
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            payment = a["client"].call(
                "get_payment", [{"payment_hash": result["payment_hash"]}]
            )
            invoice_state = self.fiber2.client.call(
                "get_invoice", [{"payment_hash": payment_hash}]
            )
            if payment["status"] in ("Success", "Failed"):
                break
            time.sleep(1)
        assert payment["status"] == "Success", (payment, invoice_state)
        assert invoice_state["status"] == "Paid", invoice_state
        self.result = "passed"

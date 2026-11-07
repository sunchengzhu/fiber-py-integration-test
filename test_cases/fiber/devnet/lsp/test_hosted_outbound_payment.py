"""Hosted external-signer outbound payment: A -> T -> ordinary node P."""

import hashlib
import time

import pytest

from test_cases.fiber.devnet.lsp.test_hosted_invoice_cancellation import _CancellationBase


def _payment_hash(preimage):
    return "0x" + hashlib.blake2b(
        bytes.fromhex(preimage.removeprefix("0x")),
        digest_size=32,
        person=b"ckb-default-hash",
    ).hexdigest()


class TestHostedOutboundPayment(_CancellationBase):
    tenant_labels = ("A",)

    # TEST-MAP: LSP-PAYMENT-05
    @pytest.mark.xfail(
        strict=False,
        reason="known product gap: hosted external-signer outbound payment does not finalize",
    )
    def test_hosted_tenant_pays_ordinary_node(self):
        """
        1. A 的真实外部签名通道已就绪，P 已有 T–P 路由。
        2. A 发起真实 invoice payment，经 T 到 P。
        3. 断言 A 付款成功、P 发票 Paid；当前产品停在 Inflight 则 xfail。
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
        # the commitment. The A-T amount includes T's 1000 ppm forwarding fee.
        now_ms = int(time.time() * 1000)
        authorization = {
            "payment_hash": payment_hash,
            "hash_algorithm": "ckb_hash",
            "inbound": False,
            "amount": 1_001_000,
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

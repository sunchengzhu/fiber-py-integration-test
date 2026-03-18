from test_cases.fiber.devnet.open_channel_with_external_funding.external_funding_base import (
    ExternalFundingBase,
)


class TestExternalFundingCompatibility(ExternalFundingBase):
    """
    PR-1120 backward compatibility coverage.

    Mapped doc case:
    - T-20 normal open_channel flow should remain unchanged
    """

    __test__ = True

    def test_normal_open_channel_flow_still_works(self):
        """
        T-20: verify the new external funding RPCs do not regress the existing
        normal open_channel -> pay -> close workflow.
        """
        self.open_channel(self.fiber1, self.fiber2, 200 * 100000000, 0)
        channel_id = self.fiber1.get_client().list_channels(
            {"pubkey": self.fiber2.get_pubkey()}
        )["channels"][0]["channel_id"]

        invoice_amount = 10 * 100000000
        invoice = self.fiber2.get_client().new_invoice(
            {
                "amount": hex(invoice_amount),
                "currency": "Fibd",
                "description": "normal open_channel compatibility payment",
                "expiry": "0xe10",
                "final_cltv": "0x28",
                "payment_preimage": self.generate_random_preimage(),
                "hash_algorithm": "sha256",
            }
        )
        before_channel = self._get_channel_by_id(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), channel_id
        )
        payment = self.fiber1.get_client().send_payment(
            {"invoice": invoice["invoice_address"]}
        )
        self.wait_payment_state(self.fiber1, payment["payment_hash"], "Success")
        after_channel = self._get_channel_by_id(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), channel_id
        )
        assert int(before_channel["local_balance"], 16) - int(
            after_channel["local_balance"], 16
        ) == invoice_amount

        self.fiber1.get_client().shutdown_channel(
            {
                "channel_id": channel_id,
                "close_script": self.get_account_script(self.fiber1.account_private),
                "fee_rate": "0x3FC",
            }
        )
        close_tx_hash = self.wait_and_check_tx_pool_fee(1000, False, 120)
        self.Miner.miner_until_tx_committed(self.node, close_tx_hash, True)
        self._wait_both_channel_closed(channel_id)

        closed_channel = self._get_channel_by_id(
            self.fiber1.get_client(),
            self.fiber2.get_pubkey(),
            channel_id,
            include_closed=True,
        )
        assert closed_channel["state"]["state_name"] == "Closed"

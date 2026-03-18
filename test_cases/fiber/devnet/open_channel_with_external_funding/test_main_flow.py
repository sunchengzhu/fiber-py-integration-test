from test_cases.fiber.devnet.open_channel_with_external_funding.external_funding_base import (
    ExternalFundingBase,
)


class TestOpenChannelWithExternalFunding(ExternalFundingBase):
    """
    PR-1120 main integration flow.

    Mapped doc cases:
    - T-03 full lifecycle: open -> sign/submit -> ready -> pay -> close
    - T-04 both peers reach ChannelReady after funding confirmation
    """

    __test__ = True

    def test_main_flow(self):
        """
        T-03/T-04 combined happy path.

        This is the end-to-end regression case that proves an externally funded
        channel can be opened, used for payment, and cooperatively closed while
        both peers observe the expected state transitions.
        """
        # Step 0: prepare an external wallet that funds the channel on-chain.
        # Validation target: the funding source is not fiber1's own CKB key.
        context = self._open_external_funding_channel(public=True)
        channel_id = context["channel_id"]
        funding_amount = context["funding_amount"]
        external_lock_script = context["external_lock_script"]
        receiver_lock_script = context["receiver_lock_script"]
        external_balance_before = self._get_lock_capacity(external_lock_script)
        receiver_balance_before = self._get_lock_capacity(receiver_lock_script)
        node_info = self.fiber1.get_client().node_info()
        print(
            f"fiber1 version: {node_info['version']}, commit_hash: {node_info['commit_hash']}"
        )

        context["signed_funding_tx"] = self._sign_external_funding_tx(
            context["unsigned_funding_tx"], context["external_private_key"]
        )
        context["submit_result"] = self._submit_external_funding(
            context["channel_id"], context["signed_funding_tx"]
        )
        context["funding_tx_hash"] = context["submit_result"]["funding_tx_hash"]
        expected_external_spend = self._get_script_capacity_delta_in_transaction(
            context["signed_funding_tx"], external_lock_script
        )

        assert context["submit_result"]["channel_id"] == channel_id
        assert context["funding_tx_hash"].startswith("0x")
        assert expected_external_spend >= funding_amount

        self.Miner.miner_until_tx_committed(self.node, context["funding_tx_hash"], True)

        # T-04: after the signed funding tx is accepted and confirmed, both peers
        # should complete the commitment handshake and reach ChannelReady.
        self._wait_both_channel_ready(channel_id)
        receiver_channel_before_payment = self._get_channel_by_id(
            self.fiber2.get_client(), self.fiber1.get_pubkey(), channel_id
        )
        assert int(receiver_channel_before_payment["local_balance"], 16) == 0
        receiver_balance_after_open = self._get_lock_capacity(receiver_lock_script)
        assert receiver_balance_after_open < receiver_balance_before

        # T-03 (payment part): pay through the externally funded channel.
        # Validation target:
        # - invoice payment reaches Success
        # - fiber1 local_balance decreases exactly by the invoice amount
        invoice_amount = 10 * 100000000
        invoice = self.fiber2.get_client().new_invoice(
            {
                "amount": hex(invoice_amount),
                "currency": "Fibd",
                "description": "external funding channel payment",
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
            {
                "invoice": invoice["invoice_address"],
            }
        )
        self.wait_payment_state(self.fiber1, payment["payment_hash"], "Success")
        after_channel = self._get_channel_by_id(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), channel_id
        )
        receiver_channel_after_payment = self._get_channel_by_id(
            self.fiber2.get_client(), self.fiber1.get_pubkey(), channel_id
        )
        sender_channel_before_payment = int(before_channel["local_balance"], 16)
        sender_channel_after_payment = int(after_channel["local_balance"], 16)
        receiver_channel_before_payment_balance = int(
            receiver_channel_before_payment["local_balance"], 16
        )
        receiver_channel_after_payment_balance = int(
            receiver_channel_after_payment["local_balance"], 16
        )
        # Payment formulas for this PR-1120 main flow:
        # - sender local_balance before payment = funding_amount - DEFAULT_MIN_DEPOSIT_CKB
        #   e.g. 200 CKB - 99 CKB = 101 CKB
        # - sender local_balance delta = invoice_amount
        # - receiver local_balance after payment = 0 + invoice_amount
        self._print_payment_balance_summary(
            funding_amount,
            sender_channel_before_payment,
            sender_channel_after_payment,
            receiver_channel_before_payment_balance,
            receiver_channel_after_payment_balance,
            invoice_amount,
        )
        assert sender_channel_before_payment - sender_channel_after_payment == (
            invoice_amount
        )
        assert receiver_channel_after_payment_balance == invoice_amount

        # T-03 (close part): cooperatively close the channel and confirm the close tx.
        # Validation target:
        # - close tx enters the pool and gets committed
        # - both sides can observe the channel in Closed state with include_closed=True
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

        # Final chain balance checks:
        # - the external wallet's total chain loss should equal the exact fee-adjusted
        #   net spend in the funding tx
        # - the receiver's post-close chain gain should equal the exact fee-adjusted
        #   amount delivered to its lock script by the committed cooperative close tx
        external_balance_after = self._get_lock_capacity(external_lock_script)
        receiver_balance_after = self._get_lock_capacity(receiver_lock_script)
        expected_receiver_gain = self._get_script_capacity_change_from_committed_tx(
            close_tx_hash, receiver_lock_script
        )
        external_balance_delta = external_balance_before - external_balance_after
        receiver_balance_delta = receiver_balance_after - receiver_balance_after_open

        # Final settlement formulas:
        # - external wallet total chain delta = chain before funding - chain after close
        #   = funding_amount + opening fee
        # - receiver post-close chain delta = chain after close - chain after open
        #   = DEFAULT_MIN_DEPOSIT_CKB + invoice_amount - close fee share
        self._print_funding_settlement_summary(
            external_balance_before,
            external_balance_after,
            external_balance_delta,
            expected_external_spend,
        )
        self._print_close_settlement_summary(
            receiver_balance_after_open,
            receiver_balance_after,
            receiver_balance_delta,
            expected_receiver_gain,
            invoice_amount,
        )

        assert external_balance_delta == expected_external_spend
        assert receiver_balance_delta == expected_receiver_gain

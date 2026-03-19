import copy
import json
import os
import tempfile
import time

from framework.basic_fiber import FiberTest
from framework.config import DEFAULT_MIN_DEPOSIT_CKB
from framework.test_fiber import FiberConfigPath


class ExternalFundingBase(FiberTest):
    __test__ = False

    fiber_version = FiberConfigPath.PR1120

    def _sign_external_funding_tx(self, unsigned_funding_tx, external_private_key):
        tx_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                tx_file = tmp.name
                json.dump(
                    {
                        "transaction": unsigned_funding_tx,
                        "multisig_configs": {},
                        "signatures": {},
                    },
                    tmp,
                )

            external_account = self.Ckb_cli.util_key_info_by_private_key(
                external_private_key
            )
            self.Ckb_cli.tx_add_multisig_config(
                external_account["address"]["testnet"],
                tx_file,
                self.node.rpcUrl,
            )
            sign_data = self.Ckb_cli.tx_sign_inputs(
                external_private_key, tx_file, self.node.rpcUrl
            )
            for signature in sign_data:
                self.Ckb_cli.tx_add_signature(
                    signature["lock-arg"],
                    signature["signature"],
                    tx_file,
                    self.node.rpcUrl,
                )
            return self.Tx.build_tx_info(tx_file)
        finally:
            if tx_file and os.path.exists(tx_file):
                os.remove(tx_file)

    def _clone_tx(self, tx):
        return copy.deepcopy(tx)

    def _build_external_open_params(
        self,
        external_private_key,
        funding_amount,
        public=True,
        extra_params=None,
    ):
        params = {
            "pubkey": self.fiber2.get_pubkey(),
            "funding_amount": hex(funding_amount),
            "public": public,
            "shutdown_script": self.get_account_script(self.fiber1.account_private),
            "funding_lock_script": self.get_account_script(external_private_key),
        }
        if extra_params:
            params.update(extra_params)
        return params

    def _open_external_funding_channel(
        self,
        funding_amount=200 * 100000000,
        public=True,
        external_balance=1000,
        extra_params=None,
    ):
        external_private_key = self.generate_account(external_balance)
        open_result = self.fiber1.get_client().open_channel_with_external_funding(
            self._build_external_open_params(
                external_private_key, funding_amount, public, extra_params
            )
        )
        return {
            "funding_amount": funding_amount,
            "external_private_key": external_private_key,
            "external_lock_script": self.get_account_script(external_private_key),
            "receiver_lock_script": self.get_account_script(self.fiber2.account_private),
            "channel_id": open_result["channel_id"],
            "unsigned_funding_tx": open_result["unsigned_funding_tx"],
            "open_result": open_result,
        }

    def _submit_external_funding(self, channel_id, signed_funding_tx):
        return self.fiber1.get_client().submit_signed_funding_tx(
            {
                "channel_id": channel_id,
                "signed_funding_tx": signed_funding_tx,
            }
        )

    def _open_sign_submit_external_channel(
        self,
        funding_amount=200 * 100000000,
        public=True,
        external_balance=1000,
        extra_params=None,
    ):
        context = self._open_external_funding_channel(
            funding_amount, public, external_balance, extra_params
        )
        signed_funding_tx = self._sign_external_funding_tx(
            context["unsigned_funding_tx"], context["external_private_key"]
        )
        submit_result = self._submit_external_funding(
            context["channel_id"], signed_funding_tx
        )
        context["signed_funding_tx"] = signed_funding_tx
        context["submit_result"] = submit_result
        context["funding_tx_hash"] = submit_result["funding_tx_hash"]
        return context

    def _get_channel_by_id(self, client, pubkey, channel_id, include_closed=False):
        channels = client.list_channels(
            {"pubkey": pubkey, "include_closed": include_closed}
        )["channels"]
        for channel in channels:
            if channel["channel_id"] == channel_id:
                return channel
        raise AssertionError(f"channel not found: {channel_id}")

    def _find_channel_by_id(self, client, pubkey, channel_id, include_closed=False):
        channels = client.list_channels(
            {"pubkey": pubkey, "include_closed": include_closed}
        )["channels"]
        for channel in channels:
            if channel["channel_id"] == channel_id:
                return channel
        return None

    def _wait_until_channel_absent(
        self, client, pubkey, channel_id, timeout=20, include_closed=False
    ):
        for _ in range(timeout):
            channel = self._find_channel_by_id(
                client, pubkey, channel_id, include_closed=include_closed
            )
            if channel is None:
                return
            time.sleep(1)
        raise AssertionError(f"channel still exists after timeout: {channel_id}")

    def _wait_until_channel_condition(
        self, client, pubkey, channel_id, predicate, timeout=20, include_closed=False
    ):
        last_channel = None
        for _ in range(timeout):
            channel = self._find_channel_by_id(
                client, pubkey, channel_id, include_closed=include_closed
            )
            if channel is not None:
                last_channel = channel
                if predicate(channel):
                    return channel
            time.sleep(1)
        raise AssertionError(
            f"channel did not satisfy predicate in time: {channel_id}, last={last_channel}"
        )

    def _wait_until_state_not(
        self, client, pubkey, channel_id, excluded_state, timeout=20
    ):
        return self._wait_until_channel_condition(
            client,
            pubkey,
            channel_id,
            lambda channel: channel["state"]["state_name"] != excluded_state,
            timeout=timeout,
        )

    def _wait_both_channel_ready(self, channel_id, timeout=120):
        self.wait_for_channel_state(
            self.fiber1.get_client(),
            self.fiber2.get_pubkey(),
            "ChannelReady",
            timeout,
            channel_id=channel_id,
        )
        self.wait_for_channel_state(
            self.fiber2.get_client(),
            self.fiber1.get_pubkey(),
            "ChannelReady",
            timeout,
            channel_id=channel_id,
        )

    def _wait_both_channel_closed(self, channel_id, timeout=120):
        self.wait_for_channel_state(
            self.fiber1.get_client(),
            self.fiber2.get_pubkey(),
            "Closed",
            timeout,
            include_closed=True,
            channel_id=channel_id,
        )
        self.wait_for_channel_state(
            self.fiber2.get_client(),
            self.fiber1.get_pubkey(),
            "Closed",
            timeout,
            include_closed=True,
            channel_id=channel_id,
        )

    def _get_lock_capacity(self, lock_script):
        return int(
            self.node.getClient()
            .get_cells_capacity(
                {
                    "script": lock_script,
                    "script_type": "lock",
                    "script_search_mode": "exact",
                }
            )["capacity"],
            16,
        )

    def _get_script_capacity_delta_in_transaction(self, tx, lock_script):
        input_total = 0
        for tx_input in tx["inputs"]:
            previous_output = tx_input["previous_output"]
            previous_tx = self.node.getClient().get_transaction(
                previous_output["tx_hash"]
            )["transaction"]
            previous_cell = previous_tx["outputs"][int(previous_output["index"], 16)]
            if previous_cell["lock"] == lock_script:
                input_total += int(previous_cell["capacity"], 16)

        output_total = 0
        for output in tx["outputs"]:
            if output["lock"] == lock_script:
                output_total += int(output["capacity"], 16)
        return input_total - output_total

    def _get_script_capacity_change_from_committed_tx(self, tx_hash, lock_script):
        tx = self.node.getClient().get_transaction(tx_hash)["transaction"]
        input_total = 0
        for tx_input in tx["inputs"]:
            previous_output = tx_input["previous_output"]
            previous_tx = self.node.getClient().get_transaction(
                previous_output["tx_hash"]
            )["transaction"]
            previous_cell = previous_tx["outputs"][int(previous_output["index"], 16)]
            if previous_cell["lock"] == lock_script:
                input_total += int(previous_cell["capacity"], 16)

        output_total = 0
        for output in tx["outputs"]:
            if output["lock"] == lock_script:
                output_total += int(output["capacity"], 16)
        return output_total - input_total

    def _format_capacity(self, value):
        return f"{value / 100000000:.8f} CKB"

    def _print_comparison(self, title, rows):
        print(f"[{title}]")
        for label, value in rows:
            print(f"  {label}: {value}")

    def _cap_row(self, label, value):
        return (label, self._format_capacity(value))

    def _formula_row(self, label, left, operator, right, result):
        return (
            label,
            f"{self._format_capacity(left)} {operator} "
            f"{self._format_capacity(right)} = {self._format_capacity(result)}",
        )

    def _print_payment_balance_summary(
        self,
        funding_amount,
        sender_before,
        sender_after,
        receiver_before,
        receiver_after,
        invoice_amount,
    ):
        self._print_comparison(
            "Payment channel balances",
            [
                self._cap_row("sender local_balance before payment", sender_before),
                self._cap_row("sender local_balance after payment", sender_after),
                self._formula_row(
                    "sender formula",
                    funding_amount,
                    "-",
                    DEFAULT_MIN_DEPOSIT_CKB,
                    sender_before,
                ),
                self._cap_row(
                    "sender paid through channel", sender_before - sender_after
                ),
                self._cap_row("receiver local_balance before payment", receiver_before),
                self._cap_row("receiver local_balance after payment", receiver_after),
                self._formula_row(
                    "receiver formula",
                    receiver_before,
                    "+",
                    invoice_amount,
                    receiver_after,
                ),
                self._cap_row("invoice amount", invoice_amount),
            ],
        )

    def _print_funding_settlement_summary(
        self,
        external_balance_before,
        external_balance_after,
        external_balance_delta,
        expected_external_spend,
    ):
        self._print_comparison(
            "Funding tx settlement",
            [
                self._cap_row(
                    "external wallet chain before funding", external_balance_before
                ),
                self._cap_row("external wallet chain after close", external_balance_after),
                self._cap_row(
                    "external wallet total chain delta", external_balance_delta
                ),
                self._cap_row(
                    "expected funding tx net spend", expected_external_spend
                ),
                self._formula_row(
                    "external formula",
                    external_balance_before,
                    "-",
                    external_balance_after,
                    external_balance_delta,
                ),
            ],
        )

    def _print_close_settlement_summary(
        self,
        receiver_balance_after_open,
        receiver_balance_after,
        receiver_balance_delta,
        expected_receiver_gain,
        invoice_amount,
    ):
        self._print_comparison(
            "Cooperative close settlement",
            [
                self._cap_row("receiver chain after open", receiver_balance_after_open),
                self._cap_row("receiver chain after close", receiver_balance_after),
                self._cap_row(
                    "receiver post-close chain delta", receiver_balance_delta
                ),
                self._cap_row("expected close tx net gain", expected_receiver_gain),
                self._formula_row(
                    "receiver close formula",
                    receiver_balance_after,
                    "-",
                    receiver_balance_after_open,
                    receiver_balance_delta,
                ),
                (
                    "receiver theoretical gross",
                    f"{self._format_capacity(DEFAULT_MIN_DEPOSIT_CKB)} + "
                    f"{self._format_capacity(invoice_amount)}",
                ),
            ],
        )

    def _restart_fiber(self, fiber):
        fiber.stop()
        fiber.start(fnn_log_level=self.fnn_log_level)
        time.sleep(1)

import re
import time

import pytest

from test_cases.fiber.devnet.open_channel_with_external_funding.external_funding_base import (
    ExternalFundingBase,
)


class TestExternalFundingParams(ExternalFundingBase):
    """
    PR-1120 parameter validation coverage.

    Mapped doc cases:
    - T-12 tlc_expiry_delta lower-bound validation
    - T-13 commitment_delay_epoch lower-bound validation
    - T-24 funding_amount lower-bound validation
    """

    __test__ = True

    def test_tlc_expiry_delta_too_small(self):
        """T-12: tlc_expiry_delta below the minimum should be rejected by RPC."""
        with pytest.raises(Exception) as exc_info:
            self._open_external_funding_channel(
                public=True, extra_params={"tlc_expiry_delta": "0x1"}
            )

        error_message = exc_info.value.args[0]
        error_pattern = r"TLC expiry delta is too small, expect larger than \d+, got 1"
        assert re.search(error_pattern, error_message), (
            f"Expected pattern '{error_pattern}' "
            f"not found in actual string '{error_message}'"
        )

    def test_commitment_delay_epoch_too_small(self):
        """T-13: commitment_delay_epoch of zero should be rejected by RPC."""
        with pytest.raises(Exception) as exc_info:
            self._open_external_funding_channel(
                public=True, extra_params={"commitment_delay_epoch": "0x0"}
            )

        error_message = exc_info.value.args[0]
        error_pattern = (
            r"Commitment delay epoch .+ is less than the minimal value .+"
        )
        assert re.search(error_pattern, error_message), (
            f"Expected pattern '{error_pattern}' "
            f"not found in actual string '{error_message}'"
        )

    def test_funding_amount_too_small(self):
        """T-24: funding_amount of zero should be rejected by RPC."""
        with pytest.raises(Exception) as exc_info:
            self._open_external_funding_channel(funding_amount=0, public=True)

        error_message = exc_info.value.args[0]
        error_pattern = (
            r"The funding amount \(0\) should be greater than or equal to \d+"
        )
        assert re.search(error_pattern, error_message), (
            f"Expected pattern '{error_pattern}' "
            f"not found in actual string '{error_message}'"
        )


class TestExternalFundingTimeoutLifecycle(ExternalFundingBase):
    """
    PR-1120 timeout and lifecycle coverage.

    Mapped doc cases:
    - T-14 timeout cleanup before signature submission
    - T-15 stale timeout must not abort a submitted channel
    - T-16 abandon while AwaitingExternalFunding
    - T-17 restart drops non-persisted AwaitingExternalFunding channel
    """

    __test__ = True

    start_fiber_config = {
        "fiber_external_funding_timeout_seconds": 1,
        "fiber_funding_timeout_seconds": 10,
    }

    def test_external_funding_timeout_aborts_pending_channel(self):
        """
        T-14: if no signed funding tx is submitted before timeout, the pending
        channel should disappear and later submit attempts should fail.
        """
        context = self._open_external_funding_channel(public=True)
        signed_funding_tx = self._sign_external_funding_tx(
            context["unsigned_funding_tx"], context["external_private_key"]
        )

        time.sleep(2)
        self._wait_until_channel_absent(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), context["channel_id"], 5
        )

        with pytest.raises(Exception) as exc_info:
            self._submit_external_funding(context["channel_id"], signed_funding_tx)

        error_message = exc_info.value.args[0]
        error_pattern = r"Channel not found error: Hash256\(0x[0-9a-f]{64}\)"
        assert re.search(error_pattern, error_message), (
            f"Expected pattern '{error_pattern}' "
            f"not found in actual string '{error_message}'"
        )

    def test_signed_submission_is_not_aborted_by_stale_timeout(self):
        """
        T-15: after a timely submit_signed_funding_tx call, a previously
        scheduled timeout event must not tear down the channel.
        """
        context = self._open_sign_submit_external_channel(public=True)

        time.sleep(2)
        channel = self._find_channel_by_id(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), context["channel_id"]
        )
        assert channel is not None
        assert channel["state"]["state_name"] != "Closed"

        self.Miner.miner_until_tx_committed(self.node, context["funding_tx_hash"], True)
        self._wait_both_channel_ready(context["channel_id"], 120)

    def test_abandon_channel_while_awaiting_external_funding(self):
        """T-16: abandon_channel should actively cancel AwaitingExternalFunding."""
        context = self._open_external_funding_channel(public=True)

        response = self.fiber1.get_client().abandon_channel(
            {"channel_id": context["channel_id"]}
        )
        assert response is None or response == {}
        self._wait_until_channel_absent(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), context["channel_id"], 5
        )

    def test_restart_drops_awaiting_external_funding_channel(self):
        """
        T-17: AwaitingExternalFunding is intentionally non-persistent, so the
        channel should be lost after a node restart.
        """
        context = self._open_external_funding_channel(public=True)
        signed_funding_tx = self._sign_external_funding_tx(
            context["unsigned_funding_tx"], context["external_private_key"]
        )

        self._restart_fiber(self.fiber1)
        self.fiber1.connect_peer(self.fiber2)
        self._wait_until_channel_absent(
            self.fiber1.get_client(), self.fiber2.get_pubkey(), context["channel_id"], 5
        )

        with pytest.raises(Exception) as exc_info:
            self._submit_external_funding(context["channel_id"], signed_funding_tx)

        error_message = exc_info.value.args[0]
        error_pattern = r"Channel not found error: Hash256\(0x[0-9a-f]{64}\)"
        assert re.search(error_pattern, error_message), (
            f"Expected pattern '{error_pattern}' "
            f"not found in actual string '{error_message}'"
        )

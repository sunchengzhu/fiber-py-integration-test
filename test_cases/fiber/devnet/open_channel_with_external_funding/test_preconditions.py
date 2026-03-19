import re
import time

import pytest

from test_cases.fiber.devnet.open_channel_with_external_funding.external_funding_base import (
    ExternalFundingBase,
)


class TestExternalFundingPreconditions(ExternalFundingBase):
    """
    PR-1120 precondition coverage.

    Mapped doc case:
    - T-25 open_channel_with_external_funding requires an active peer connection
    """

    __test__ = True

    def test_open_channel_with_external_funding_requires_connected_peer(self):
        """
        T-25: when the target peer is disconnected, the RPC should fail with a
        peer/connect related error instead of creating a pending channel.
        """
        self.fiber1.get_client().disconnect_peer({"pubkey": self.fiber2.get_pubkey()})

        for _ in range(10):
            if len(self.fiber1.get_client().list_peers()["peers"]) == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("fiber1 still shows connected peers after disconnect")

        with pytest.raises(Exception) as exc_info:
            self._open_external_funding_channel(public=True)

        error_message = exc_info.value.args[0]
        error_pattern = r"Peer Pubkey\([^)]+\) is not connected"
        assert re.search(error_pattern, error_message), (
            f"Expected pattern '{error_pattern}' "
            f"not found in actual string '{error_message}'"
        )

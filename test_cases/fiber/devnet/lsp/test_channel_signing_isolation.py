"""PR #1623: tenant isolation of real SDK channel-signature requests."""

import time

import requests

from test_cases.fiber.devnet.lsp._lsp_test import LspTestBase


class TestChannelSigningIsolation(LspTestBase):
    def _assert_unchanged(self, tenant):
        assert (
            tenant["client"].call(
                "get_channel_signing_status", [{"channel_id": tenant["channel_id"]}]
            )
            == tenant["before"]
        )
        assert (
            self._channel_state(tenant["client"], tenant["channel_id"])
            == tenant["state"]
        )

    def _assert_not_found(self, client, method, params):
        # Bypass the test gate: rejection must come from the real FNN.
        response = requests.post(
            client.url,
            headers=client.other_params,
            json={
                "jsonrpc": "2.0",
                "id": 42,
                "method": method,
                "params": [params],
            },
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        assert "result" not in body, body
        assert body.get("error", {}).get("code") == -32000, body
        assert "not found" in body["error"]["message"], body
        assert not body["error"].get("data"), body

    def _finish_opening(self, tenant):
        tenant["gate"].apply_and_release(tenant["client"])
        for _ in range(120):
            assert tenant["agent"].poll() is None, f"SDK {tenant['label']} exited"
            local = self._channel_state(tenant["client"], tenant["channel_id"])
            public = self._channel_state(self.fiber1.client, tenant["channel_id"])
            if local["state_name"] == public["state_name"] == "ChannelReady":
                return
            time.sleep(1)
        assert (
            False
        ), f"{tenant['label']} channel did not become ready: tenant={local}, public={public}"

    # TEST-MAP: LSP-SIGN-01
    def test_pending_tenant_does_not_block_another_tenant(self):
        a, b = self.tenants
        self._finish_opening(a)
        self._assert_unchanged(b)
        self._finish_opening(b)

    # TEST-MAP: LSP-SIGN-02
    def test_tenant_cannot_read_another_tenants_signing_request(self):
        a, b = self.tenants
        for caller, owner in ((a, b), (b, a)):
            self._assert_not_found(
                caller["client"],
                "get_channel_signing_status",
                {
                    "channel_id": owner["channel_id"],
                },
            )
        for tenant in self.tenants:
            self._assert_unchanged(tenant)
        for tenant in self.tenants:
            self._finish_opening(tenant)

    # TEST-MAP: LSP-SIGN-03
    def test_tenant_cannot_submit_another_tenants_valid_signature(self):
        a, b = self.tenants
        for caller, owner in ((a, b), (b, a)):
            self._assert_not_found(
                caller["client"], "submit_channel_signature", owner["gate"].submission
            )
        for tenant in self.tenants:
            self._assert_unchanged(tenant)
        for tenant in self.tenants:
            self._finish_opening(tenant)

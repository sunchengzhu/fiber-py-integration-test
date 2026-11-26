"""PR #1623: tenant isolation of real SDK channel-signature requests."""

import time

import requests

from scripts.build_lsp_test_binaries import MERGED_LSP_REVISION
from test_cases.fiber.devnet.lsp._lsp_test import (
    DEFERRED_FUNDING_WINDOW,
    LspTestBase,
    REVISION,
)


class TestChannelSigningIsolation(LspTestBase):
    defer_external_funding = REVISION == MERGED_LSP_REVISION
    if defer_external_funding:
        fiber_config_extra = {
            **LspTestBase.fiber_config_extra,
            "external_funding_timeout_seconds": DEFERRED_FUNDING_WINDOW,
        }

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
        deadline = time.monotonic() + 120
        tenant["gate"].apply_and_release(tenant["client"])
        if self.defer_external_funding:
            self._submit_deferred_funding(tenant, deadline)
        local = public = None
        while time.monotonic() < deadline:
            assert tenant["agent"].poll() is None, f"SDK {tenant['label']} exited"
            local = self._channel_state(tenant["client"], tenant["channel_id"])
            public = self._channel_state(self.fiber1.client, tenant["channel_id"])
            if local["state_name"] == public["state_name"] == "ChannelReady":
                if self.defer_external_funding:
                    self._assert_original_funding_confirmed(tenant)
                assert time.monotonic() < deadline, "opening confirmed after deadline"
                return
            time.sleep(1)
        raise AssertionError(
            f"{tenant['label']} channel did not become ready: tenant={local}, public={public}"
        )

    # TEST-MAP: LSP-SIGN-01
    def test_pending_tenant_does_not_block_another_tenant(self):
        """
        1. 取得 A、B 各自的待签状态及输入互不重叠的原注资提案。
        2. 让 A 完成原开通，确认 B 的待签请求和通道状态仍未变化。
        3. 让 B 完成原开通，核对各自的原注资确认。
        """
        # 1. 使用准备阶段各自保存的真实待签请求和原提案。
        a, b = self.tenants

        # 2. B 保持待签，A 先完成原开通。
        self._finish_opening(a)
        self._assert_unchanged(b)
        if self.defer_external_funding:
            assert not b["gate"].released and "funding_tx_hash" not in b
            print("Tenant B retained its original signing request while A was ready")

        # 3. B 在同一通道完成原开通和注资。
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

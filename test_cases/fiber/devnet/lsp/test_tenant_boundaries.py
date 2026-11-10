"""Hosted tenant query and admin boundary checks on the current LSP head."""

import requests

from test_cases.fiber.devnet.lsp._invoice_query_environment import (
    InvoiceQueryEnvironment,
)
from test_cases.fiber.devnet.lsp.test_hosted_invoice_cancellation import (
    _CancellationBase,
)


class TestTenantQueryIsolation(InvoiceQueryEnvironment, _CancellationBase):
    """Real A/B tenant channels; no extra payment for the query boundary."""

    tenant_labels = ("A", "B")

    def _rpc_error(self, client, method, params):
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                client.url,
                headers=client.other_params,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params,
                },
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
        if self._invoice_selected:
            self._record(
                "tenant_boundary_rejection",
                method=method,
                params=params,
                response=body,
                http_status=response.status_code,
            )
        assert "error" in body, (method, body)
        return body["error"]

    # TEST-MAP: LSP-TENANT-QUERY-01
    def test_default_namespace_invoice_query_is_isolated(self):
        """
        1. 真实 A/B 租户各自开户并创建 Open 发票。
        2. B 不带 tenant_id 查询 A 的 payment hash。
        3. B/A 分别查询自己的发票，确认 token 有效且 A 状态不变。
        """
        a, b = self.tenants
        a_payment = self._new_hold(a, "a", self.business_until)
        b_payment = self._new_hold(b, "b", self.business_until)

        error = self._rpc_error(
            b["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
        )
        assert "invoice not found" in error.get("message", "").lower(), error

        own_b = self._rpc(
            b["client"],
            "get_invoice",
            [{"payment_hash": b_payment["hash"]}],
            self.business_until,
        )
        own_a = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert own_b["status"] == "Open", own_b
        assert own_a["status"] == "Open", own_a
        assert own_a["invoice_address"] == a_payment["invoice"], own_a
        assert own_b["invoice_address"] == b_payment["invoice"], own_b
        self.result = "passed"

    @staticmethod
    def _tenant_id(tenant):
        return tenant["status"]["tenant_id"]

    # TEST-MAP: LSP-TENANT-QUERY-02
    def test_explicit_tenant_target_is_rejected(self):
        """
        1. A/B 真实开户并各自创建 Open 发票。
        2. B 带 tenant_id=A 查 A 发票；operator 带同一目标查 A。
        3. A 再查自己的发票，确认状态不变。
        """
        a, b = self.tenants
        a_payment = self._new_hold(a, "a", self.business_until)
        b_payment = self._new_hold(b, "b", self.business_until)
        a_id = self._tenant_id(a)

        own_b = self._rpc(
            b["client"],
            "get_invoice",
            [{"payment_hash": b_payment["hash"]}],
            self.business_until,
        )
        assert own_b["status"] == "Open", own_b

        error = self._rpc_error(
            b["client"],
            "get_invoice",
            [
                {
                    "payment_hash": a_payment["hash"],
                    "tenant_id": a_id,
                }
            ],
        )
        assert "cannot query another tenant" in error.get("message", "").lower(), error

        operator_view = self._rpc(
            self.fiber1.client,
            "get_invoice",
            [
                {
                    "payment_hash": a_payment["hash"],
                    "tenant_id": a_id,
                }
            ],
            self.business_until,
        )
        own_a = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert operator_view["status"] == "Open", operator_view
        assert operator_view["invoice_address"] == a_payment["invoice"], operator_view
        assert own_a["status"] == "Open", own_a
        assert own_a["invoice_address"] == a_payment["invoice"], own_a
        self.result = "passed"

    # TEST-MAP: LSP-ADMIN-AUTH-01
    def test_tenant_token_cannot_list_tenants(self):
        """
        1. A 用 tenant token 查询自己的发票，证明 token 有效。
        2. A 调 lsp_list_tenants，预期被拒绝。
        3. operator 确认 A/B runtime 和通道未变，再由 A 合法查询自身发票。
        """
        # 1. 创建真实 Open 发票，并用 A 的合法查询证明 token 有效。
        a, b = self.tenants
        a_payment = self._new_hold(a, "a", self.business_until)

        own_a = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert own_a["status"] == "Open", own_a

        # 2. 同一 tenant token 调 operator 列表方法必须被拒绝。
        error = self._rpc_error(a["client"], "lsp_list_tenants", [])
        assert error, error

        # 3. 先由 operator 观察，再验证拒绝后的合法 tenant 查询。
        listed = self._rpc(
            self.fiber1.client,
            "lsp_list_tenants",
            [],
            self.business_until,
        )
        ids = {tenant["tenant_id"] for tenant in listed["tenants"]}
        assert {self._tenant_id(a), self._tenant_id(b)} <= ids, listed
        # Operator 健康检查先于 tenant 查询，避免重新拉起 runtime 掩盖错误。
        self._check_query_environment()
        after = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert after["status"] == "Open", after
        assert after["invoice_address"] == a_payment["invoice"], after
        self.result = "passed"

    # TEST-MAP: LSP-ADMIN-AUTH-02
    def test_tenant_token_cannot_evict_tenants(self):
        """
        1. A 用 tenant token 查询自己的发票，证明 token 有效；记录 operator 状态。
        2. A 用 tenant token 驱逐 B 和自己，预期均被拒绝。
        3. 只由 operator 重新读取状态，确认 runtime/计数/通道未变。
        """
        a, b = self.tenants
        a_payment = self._new_hold(a, "a", self.business_until)
        own_a = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert own_a["status"] == "Open", own_a

        before_status = self._rpc(
            self.fiber1.client,
            "lsp_get_status",
            [],
            self.business_until,
        )
        before_tenants = self._rpc(
            self.fiber1.client,
            "lsp_list_tenants",
            [],
            self.business_until,
        )
        before_by_id = {
            tenant["tenant_id"]: tenant for tenant in before_tenants["tenants"]
        }
        before_channels = {
            key: {channel["channel_id"] for channel in value["channels"]}
            for key, value in before_by_id.items()
        }
        assert before_by_id[self._tenant_id(a)]["runtime_status"] == "active"
        assert before_by_id[self._tenant_id(b)]["runtime_status"] == "active"

        for target in (b, a):
            error = self._rpc_error(
                a["client"],
                "lsp_evict_tenant",
                [{"tenant_id": self._tenant_id(target)}],
            )
            assert error, error

        after_status = self._rpc(
            self.fiber1.client,
            "lsp_get_status",
            [],
            self.business_until,
        )
        after_tenants = self._rpc(
            self.fiber1.client,
            "lsp_list_tenants",
            [],
            self.business_until,
        )
        after_by_id = {
            tenant["tenant_id"]: tenant for tenant in after_tenants["tenants"]
        }
        after_channels = {
            key: {channel["channel_id"] for channel in value["channels"]}
            for key, value in after_by_id.items()
        }
        assert after_status["active_tenants"] == before_status["active_tenants"]
        assert after_status["registered_tenants"] == before_status["registered_tenants"]
        for key in (self._tenant_id(a), self._tenant_id(b)):
            assert after_by_id[key]["runtime_status"] == "active", after_by_id[key]
            assert after_channels[key] == before_channels[key], key
        self.result = "passed"

    # TEST-MAP: LSP-ADMIN-AUTH-03
    def test_tenant_token_cannot_parse_invoice(self):
        """
        1. A 用 tenant token 创建发票并成功读取，证明 token 和 read("invoices") 有效。
        2. A 调 operator-only 的 parse_invoice，预期被拒绝。
        3. A 再读自己的发票，确认状态未被改变。
        """
        a, _ = self.tenants
        a_payment = self._new_hold(a, "a", self.business_until)
        own = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert own["status"] == "Open", own

        error = self._rpc_error(
            a["client"],
            "parse_invoice",
            [{"invoice": a_payment["invoice"]}],
        )
        assert error, error

        after = self._rpc(
            a["client"],
            "get_invoice",
            [{"payment_hash": a_payment["hash"]}],
            self.business_until,
        )
        assert after["status"] == "Open", after
        assert after["invoice_address"] == own["invoice_address"], after
        self.result = "passed"

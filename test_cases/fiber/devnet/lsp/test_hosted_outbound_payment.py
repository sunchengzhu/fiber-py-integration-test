"""PR #1623: real Hosted A -> public T -> ordinary P outbound payment."""

from test_cases.fiber.devnet.lsp._hosted_outbound import (
    FIXED_REVISION,
    HostedOutboundFixture,
    revision_allowed,
)
from test_cases.fiber.devnet.lsp._lsp_test import REVISION, RETEST_REVISION


class TestHostedOutboundPayment(HostedOutboundFixture):
    runtime_prefix = "lsp-payment05-"
    evidence_prefix = "lsp-payment05-"

    @classmethod
    def setup_class(cls):
        assert revision_allowed(
            REVISION, RETEST_REVISION
        ), "use the fixed candidate or a separately reviewed revision for retest"
        super().setup_class()

    # TEST-MAP: LSP-PAYMENT-05
    def test_hosted_tenant_pays_ordinary_node(self):
        """
        1. 完成 A 经 T 到 P 的真实付款，核对前像、TLC、资金、费用和稳定终态。
        """
        # 1. 复用同一真实出站流程及原有断言；只有全部通过才标记本用例成功。
        self._complete_outbound_payment(self.tenants[0])
        self.result = "passed"

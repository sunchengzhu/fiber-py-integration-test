"""Four existing invoice/query cases, with separate opt-in Hosted reuse."""

from copy import deepcopy
import os

from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import HostedTenantFixture
from test_cases.fiber.devnet.lsp._lsp_test import REVISION, RETEST_REVISION
from test_cases.fiber.devnet.lsp._query_environment import HostedEnvironmentReuse
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import _number

FIXED_INVOICE_REVISION = "76307312e8de518c9a32074e6d16867c04de4f86"

INVOICE_QUERY_METHODS = {
    "test_default_namespace_invoice_query_is_isolated": 2,
    "test_explicit_tenant_target_is_rejected": 2,
    "test_tenant_token_cannot_list_tenants": 1,
    "test_tenant_token_cannot_parse_invoice": 1,
}


def _assert_invoice_funds(before, after):
    """No payments: all six endpoints stay ready, mirrored and unlocked."""
    assert set(before) == set(after) == {"A", "T-A", "B", "T-B", "P", "T-P"}
    for key, view in after.items():
        original = before[key]
        assert view["state"]["state_name"] == "ChannelReady", (key, view)
        assert view["channel_id"] == original["channel_id"], key
        assert view["channel_outpoint"] == original["channel_outpoint"], key
        assert view["channel_outpoint"] and not view["shutdown_transaction_hash"], key
        for field in ("local_balance", "remote_balance"):
            assert _number(view[field]) == _number(original[field]), (key, field)
        assert _number(view["offered_tlc_balance"]) == 0, (key, view)
        assert _number(view["received_tlc_balance"]) == 0, (key, view)
        assert not view["pending_tlcs"], (key, view)
    for left, right in (("A", "T-A"), ("B", "T-B"), ("P", "T-P")):
        assert _number(after[left]["local_balance"]) == _number(
            after[right]["remote_balance"]
        )
        assert _number(after[left]["remote_balance"]) == _number(
            after[right]["local_balance"]
        )


class InvoiceQueryEnvironment(HostedEnvironmentReuse):
    mode_variable = "LSP_INVOICE_QUERY_ENV_MODE"
    keep_variable = "LSP_INVOICE_QUERY_KEEP_RUNTIME"
    owner_fixture = HostedTenantFixture

    @classmethod
    def setup_class(cls):
        assert (
            REVISION == FIXED_INVOICE_REVISION or REVISION == RETEST_REVISION
        ), "invoice query reuse requires explicit pinned retest revision"
        disk = os.statvfs(get_project_root())
        if disk.f_bavail * disk.f_frsize < 8 * 2**30:
            raise RuntimeError("invoice-query qualification: free disk below 8GiB")
        super().setup_class()

    def setup_method(self, method):
        self._invoice_selected = method.__name__ in INVOICE_QUERY_METHODS
        self._invoice_current = {}
        super().setup_method(method)

    def _validate_shared_method(self, method):
        assert method.__name__ in INVOICE_QUERY_METHODS, (
            "method is not eligible for shared invoice environment: " + method.__name__
        )

    def setUp(self):
        super().setUp()
        if self._invoice_selected and self._query_mode == "independent":
            self._check_query_environment()

    def _invoice_operator_state(self):
        """These operator calls do not ensure/restart a tenant runtime."""
        status = self._rpc(
            self.fiber1.client, "lsp_get_status", [], self.business_until
        )
        listed = self._rpc(
            self.fiber1.client, "lsp_list_tenants", [], self.business_until
        )
        by_id = {t["tenant_id"]: t for t in listed["tenants"]}
        tenants = {}
        for tenant in self.tenants:
            tenant_id = tenant["status"]["tenant_id"]
            runtime = by_id[tenant_id]
            assert runtime["runtime_status"] == "active", runtime
            channels = runtime["channels"]
            assert {c["channel_id"] for c in channels} == {tenant["channel_id"]}
            assert all(c["online"] for c in channels), channels
            tenants[tenant_id] = {
                "runtime_status": runtime["runtime_status"],
                "channel_ids": sorted(c["channel_id"] for c in channels),
            }
        active = _number(status["active_tenants"])
        registered = _number(status["registered_tenants"])
        assert active >= len(self.tenants), status
        assert registered >= len(self.tenants), status
        return {
            "active_tenants": active,
            "registered_tenants": registered,
            "all_tenant_ids": sorted(by_id),
            "tenants": tenants,
        }

    def _check_query_environment(self):
        owner = type(self)._query_owner if self._query_mode == "shared" else self
        identity = self._query_identity()
        operator = self._invoice_operator_state()
        initial = getattr(owner, "_invoice_initial", None)
        if initial is not None:
            assert identity == initial["identity"], "shared invoice identity changed"
            assert operator == initial["operator"], "operator runtime/counters changed"
        # Never perform a tenant RPC before the operator-only runtime checks.
        views = self._views(self.business_until)
        before = initial["views"] if initial is not None else owner.baseline
        _assert_invoice_funds(before, views)
        signing = {}
        for tenant in self.tenants:
            signing[tenant["label"]] = self._signing(tenant, self.business_until)
            assert signing[tenant["label"]]["type"] == "NoSignatureRequired", signing
        if initial is None:
            owner._invoice_initial = deepcopy(
                {"identity": identity, "operator": operator, "views": views}
            )
        catalog = {}
        if self._query_mode == "shared":
            for checkpoint in self._query_checkpoints:
                for key, invoice in checkpoint["invoices"].items():
                    assert key not in catalog, ("duplicate prior invoice", key)
                    catalog[key] = invoice
        for key, invoice in self._invoice_current.items():
            assert key not in catalog, ("invoice reused between cases", key)
            catalog[key] = invoice
        assert len({key[1] for key in catalog}) == len(catalog), "reused invoice hash"
        by_id = {t["status"]["tenant_id"]: t for t in self.tenants}
        for (tenant_id, payment_hash), expected in catalog.items():
            actual = self._rpc(
                by_id[tenant_id]["client"],
                "get_invoice",
                [{"payment_hash": payment_hash}],
                self.business_until,
            )
            assert actual == expected, (tenant_id, payment_hash, actual, expected)
            assert actual["status"] == "Open", actual
            self._record(
                "invoice_history_checked",
                tenant_id=tenant_id,
                payment_hash=payment_hash,
                invoice=actual,
            )
        disk = os.statvfs(self.evidence_dir)
        assert disk.f_bavail * disk.f_frsize >= 8 * 2**30, "free disk below 8GiB"
        self._record(
            "invoice_environment_checked",
            identity=identity,
            operator=operator,
            views=views,
            signing=signing,
            prior_cases=(
                len(self._query_checkpoints) if self._query_mode == "shared" else 0
            ),
            invoice_count=len(catalog),
        )

    def _new_hold(self, tenant, label, until):
        payment = super()._new_hold(tenant, label, until)
        if not self._invoice_selected:
            return payment
        invoice = self._invoice(tenant, payment, until)
        assert invoice["status"] == "Open", invoice
        assert invoice["invoice_address"] == payment["invoice"], invoice
        assert invoice["invoice"]["data"]["payment_hash"] == payment["hash"], invoice
        key = (tenant["status"]["tenant_id"], payment["hash"])
        assert key not in self._invoice_current, ("duplicate current invoice", key)
        self._invoice_current[key] = deepcopy(invoice)
        return payment

    def _finish_shared_case(self):
        assert len(self._invoice_current) == INVOICE_QUERY_METHODS[self._testMethodName]
        self._check_query_environment()
        if self._query_mode == "shared":
            type(self)._query_checkpoints.append(
                {
                    "case": self._testMethodName,
                    "invoices": deepcopy(self._invoice_current),
                }
            )

    def doCleanups(self):
        if getattr(self, "_query_mode", "independent") == "shared":
            return super().doCleanups()
        if not getattr(self, "_invoice_selected", False):
            return super().doCleanups()
        if getattr(self, "_query_owner_cleanup_done", False):
            return self._cleanup_query_owner()
        # Use the same bounded resource drain and final archive in independent
        # mode, too. A postcondition error must not prevent resource reclamation.
        try:
            if self.result == "passed":
                self._finish_shared_case()
            else:
                type(self)._query_failed = True
        except BaseException as error:
            self.result = "invoice_checkpoint_failure"
            type(self)._query_failed = True
            try:
                self._cleanup_query_owner()
            except BaseException as cleanup_error:
                error.add_note(f"additional invoice cleanup error: {cleanup_error!r}")
            raise
        return self._cleanup_query_owner()

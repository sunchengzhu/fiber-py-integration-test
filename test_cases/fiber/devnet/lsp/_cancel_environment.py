"""Reuse only the two single-tenant cancellation scenarios; keep incoming funds."""

from copy import deepcopy
import os

from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import HostedTenantFixture
from test_cases.fiber.devnet.lsp._lsp_test import (
    DEFAULT_REVISION,
    REVISION,
    RETEST_REVISION,
)
from test_cases.fiber.devnet.lsp._query_environment import HostedEnvironmentReuse
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import _number

CANCEL_METHODS = (
    "test_open_invoice_cancelled_old_payment_fails_new_payment_succeeds",
    "test_received_invoice_without_preimage_can_be_cancelled",
)


def _assert_incoming_funds(before, after, amount=0, fee=0):
    """P pays amount+fee, A receives amount, T keeps the measured spread."""
    deltas = {"P": -amount - fee, "T-P": amount + fee, "A": amount, "T-A": -amount}
    assert set(before) == set(after) == set(deltas)
    assert amount >= 0 and fee >= 0
    for key, delta in deltas.items():
        old, new = before[key], after[key]
        assert new["state"]["state_name"] == "ChannelReady", (key, new)
        for field in ("channel_id", "channel_outpoint"):
            assert new[field] and new[field] == old[field], (key, field)
        assert not new["shutdown_transaction_hash"], key
        assert (
            _number(new["local_balance"]) - _number(old["local_balance"]) == delta
        ), key
        assert (
            _number(new["remote_balance"]) - _number(old["remote_balance"]) == -delta
        ), key
        assert (
            _number(new["offered_tlc_balance"])
            == _number(new["received_tlc_balance"])
            == 0
        )
        for tlc in new["pending_tlcs"]:
            assert list(tlc["status"].values()) == ["RemoveAckConfirmed"], (key, tlc)
    for left, right in (("A", "T-A"), ("P", "T-P")):
        assert _number(after[left]["local_balance"]) == _number(
            after[right]["remote_balance"]
        )
        assert _number(after[left]["remote_balance"]) == _number(
            after[right]["local_balance"]
        )


class CancellationEnvironment(HostedEnvironmentReuse):
    mode_variable = "LSP_CANCEL_ENV_MODE"
    keep_variable = "LSP_CANCEL_KEEP_RUNTIME"
    owner_fixture = HostedTenantFixture

    @classmethod
    def setup_class(cls):
        assert REVISION == DEFAULT_REVISION or REVISION == RETEST_REVISION
        super().setup_class()

    def setup_method(self, method):
        self._cancel_current = {}
        self._cancel_terminal = {}
        self._cancel_baseline = None
        super().setup_method(method)

    def _validate_shared_method(self, method):
        assert (
            method.__name__ in CANCEL_METHODS
        ), "not a single-tenant cancellation case"

    def setUp(self):
        super().setUp()
        self.tenant = self.tenants[0]
        self.client = self.tenant["client"]
        if self._query_mode == "shared":
            # The preceding case's incoming payment is part of this baseline.
            self.baseline = deepcopy(self._views(self.business_until))
            # Keep the owner's original health cursor: starting a fresh cursor
            # would hide panics or actor restarts from preceding shared methods.
            self.node_log_offsets = deepcopy(type(self)._query_owner.node_log_offsets)
        self._cancel_baseline = deepcopy(self.baseline)

    def _cancel_operator(self):
        listed = self._rpc(
            self.fiber1.client, "lsp_list_tenants", [], self.business_until
        )
        expected = self.tenants[0]["status"]["tenant_id"]
        assert len(listed["tenants"]) == 1, listed
        tenant = listed["tenants"][0]
        assert (
            tenant["tenant_id"] == expected and tenant["runtime_status"] == "active"
        ), tenant
        assert {c["channel_id"] for c in tenant["channels"]} == {
            self.tenants[0]["channel_id"]
        }
        assert all(c["online"] for c in tenant["channels"]), tenant

    def _check_query_environment(self):
        owner = type(self)._query_owner
        identity = self._query_identity()
        self._cancel_operator()  # Detect inactivity before tenant calls can ensure it.
        initial = getattr(owner, "_cancel_initial", None)
        if initial is None:
            owner._cancel_initial = deepcopy(identity)
        else:
            assert identity == initial, "cancellation environment identity changed"
        views = self._views(self.business_until)
        assert (
            self._signing(self.tenants[0], self.business_until)["type"]
            == "NoSignatureRequired"
        )
        if self._cancel_terminal:
            successes = [
                x
                for x in self._cancel_terminal.values()
                if x["payer"]["status"] == "Success"
            ]
            failures = [
                x
                for x in self._cancel_terminal.values()
                if x["payer"]["status"] == "Failed"
            ]
            assert len(successes) == len(failures) == 1
            assert successes[0]["invoice"]["status"] == "Paid"
            assert failures[0]["invoice"]["status"] == "Cancelled"
            assert _number(failures[0]["payer"]["fee"]) == 0
            fee = _number(successes[0]["payer"]["fee"])
            amount = successes[0]["amount"]
            _assert_incoming_funds(self._cancel_baseline, views, amount, fee)
        else:
            before = (
                self._query_checkpoints[-1]["views"]
                if self._query_checkpoints
                else owner.baseline
            )
            _assert_incoming_funds(before, views)
        for checkpoint in self._query_checkpoints:
            for payment_hash, expected in checkpoint["terminal"].items():
                payment = {"hash": payment_hash, "tenant": self.tenants[0]}
                assert (
                    self._invoice(self.tenants[0], payment, self.business_until)
                    == expected["invoice"]
                )
                assert self._payment(payment, self.business_until) == expected["payer"]
                if expected["invoice"]["status"] == "Cancelled":
                    self._no_old_release(payment)
                self._record(
                    "cancel_prior_history_checked",
                    payment_hash=payment_hash,
                    invoice=expected["invoice"],
                    payer=expected["payer"],
                )
        disk = os.statvfs(self.evidence_dir)
        assert disk.f_bavail * disk.f_frsize >= 8 * 2**30, "free disk below 8GiB"
        self._record(
            "cancel_environment_checked",
            identity=identity,
            views=views,
            prior_cases=len(self._query_checkpoints),
        )
        return views

    def _new_hold(self, tenant, label, until):
        payment = super()._new_hold(tenant, label, until)
        old = {h for c in self._query_checkpoints for h in c["terminal"]}
        assert (
            payment["hash"] not in self._cancel_current and payment["hash"] not in old
        )
        self._cancel_current[payment["hash"]] = payment["amount"]
        return payment

    def _wait_terminal(self, payment, expected_payment, expected_invoice, until):
        sample = super()._wait_terminal(
            payment, expected_payment, expected_invoice, until
        )
        self._cancel_terminal[payment["hash"]] = deepcopy(
            {
                "payer": sample["payer"],
                "invoice": sample["invoice"],
                "amount": payment["amount"],
            }
        )
        return sample

    def _finish_shared_case(self):
        assert len(self._cancel_current) == len(self._cancel_terminal) == 2
        views = self._check_query_environment()
        type(self)._query_checkpoints.append(
            {
                "case": self._testMethodName,
                "views": deepcopy(views),
                "terminal": deepcopy(self._cancel_terminal),
            }
        )

    def doCleanups(self):
        if getattr(self, "_query_mode", "independent") == "shared":
            return super().doCleanups()
        if getattr(self, "result", "incomplete") != "passed":
            type(self)._query_failed = True
        return self._cleanup_query_owner()

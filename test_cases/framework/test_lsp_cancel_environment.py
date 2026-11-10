"""Incoming cancellation accounting, history and failure-state regressions."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

import test_cases.fiber.devnet.lsp._cancel_environment as cancel_env
from test_cases.fiber.devnet.lsp._cancel_environment import _assert_incoming_funds
import test_cases.fiber.devnet.lsp.test_hosted_invoice_cancellation as native_cases
from test_cases.framework.test_lsp_tenant_payment_queries import _views


def views():
    return {k: v for k, v in _views().items() if k not in ("B", "T-B")}


def incoming(before, amount=1_000_000, fee=5_000):
    after = deepcopy(before)
    for key, delta in {
        "P": -amount - fee,
        "T-P": amount + fee,
        "A": amount,
        "T-A": -amount,
    }.items():
        after[key]["local_balance"] = hex(int(before[key]["local_balance"], 16) + delta)
        after[key]["remote_balance"] = hex(
            int(before[key]["remote_balance"], 16) - delta
        )
    return after


def test_incoming_funds_and_unchanged_cancelled_payment():
    before = views()
    _assert_incoming_funds(before, before)
    _assert_incoming_funds(before, incoming(before), 1_000_000, 5_000)


@pytest.mark.parametrize("fault", ["reverse", "fee", "repeat", "pending", "outpoint"])
def test_incoming_funds_reject_wrong_direction_fee_or_repetition(fault):
    before = views()
    after = incoming(before)
    if fault == "reverse":
        after = incoming(before, -1_000_000, -5_000)
    elif fault == "fee":
        after = incoming(before, fee=6_000)
    elif fault == "repeat":
        after = incoming(after)
    elif fault == "pending":
        after["A"]["pending_tlcs"] = [{"status": {"Inbound": "Committed"}}]
    else:
        after["A"]["channel_outpoint"] = "changed"
    with pytest.raises(AssertionError):
        _assert_incoming_funds(before, after, 1_000_000, 5_000)


def test_cancel_checkpoint_uses_cumulative_baseline_and_rechecks_history(
    tmp_path, monkeypatch
):
    obj = object.__new__(native_cases.TestHostedInvoiceCancellation)
    monkeypatch.setattr(
        native_cases.TestHostedInvoiceCancellation, "_query_owner", obj, raising=False
    )
    monkeypatch.setattr(
        native_cases.TestHostedInvoiceCancellation,
        "_query_checkpoints",
        [],
        raising=False,
    )
    obj._query_mode = "shared"
    obj._testMethodName = "case-one"
    obj._cancel_current = {"old": 1_000_000, "fresh": 1_000_000}
    obj._cancel_terminal = {
        "old": {
            "invoice": {"status": "Cancelled"},
            "payer": {"status": "Failed", "fee": "0x0"},
            "amount": 1_000_000,
        },
        "fresh": {
            "invoice": {"status": "Paid"},
            "payer": {"status": "Success", "fee": hex(5000)},
            "amount": 1_000_000,
        },
    }
    obj._cancel_baseline = obj.baseline = views()
    current = incoming(obj.baseline)
    obj._views = lambda _: deepcopy(current)
    obj._query_identity = lambda: {"runtime": "same", "pids": [1, 2]}
    obj._cancel_operator = lambda: None
    obj._signing = lambda *_: {"type": "NoSignatureRequired"}
    obj.tenants = [{"label": "A"}]
    obj.business_until = float("inf")
    obj.evidence_dir = tmp_path
    events = []
    obj._record = lambda name, **fields: events.append((name, fields))
    store = deepcopy(obj._cancel_terminal)
    obj._invoice = lambda _, payment, __: deepcopy(store[payment["hash"]]["invoice"])
    obj._payment = lambda payment, _: deepcopy(store[payment["hash"]]["payer"])
    old_checks = []
    obj._no_old_release = lambda payment: old_checks.append(payment["hash"])
    obj._finish_shared_case()
    assert len(obj._query_checkpoints) == 1
    obj._cancel_current = {}
    obj._cancel_terminal = {}
    obj._check_query_environment()
    assert old_checks == ["old"]
    assert len([n for n, _ in events if n == "cancel_prior_history_checked"]) == 2
    current["A"]["local_balance"] = hex(int(current["A"]["local_balance"], 16) + 1)
    with pytest.raises(AssertionError):
        obj._check_query_environment()
    current = incoming(obj.baseline)
    store["old"]["invoice"]["status"] = "Open"
    with pytest.raises(AssertionError):
        obj._check_query_environment()


def test_cancel_independent_failure_uses_bounded_final_archive(monkeypatch):
    obj = object.__new__(native_cases.TestHostedInvoiceCancellation)
    obj._query_mode = "independent"
    obj.result = "preparation_failure"
    monkeypatch.setattr(
        native_cases.TestHostedInvoiceCancellation,
        "_query_failed",
        False,
        raising=False,
    )
    seen = []
    obj._cleanup_query_owner = lambda: seen.append("bounded-final-archive") or True
    assert obj.doCleanups() is True
    assert obj._query_failed and seen == ["bounded-final-archive"]


def test_cancel_shared_keeps_original_health_log_cursor(monkeypatch, tmp_path):
    obj = object.__new__(native_cases.TestHostedInvoiceCancellation)
    obj._query_mode = "shared"
    owner = SimpleNamespace(node_log_offsets=[(tmp_path / "node.log", 123)])
    monkeypatch.setattr(type(obj), "_query_owner", owner, raising=False)
    monkeypatch.setattr(cancel_env.HostedEnvironmentReuse, "setUp", lambda _: None)
    obj.tenants = [{"client": "A"}]
    obj.business_until = float("inf")
    obj._views = lambda _: views()
    obj.setUp()
    assert obj.node_log_offsets == owner.node_log_offsets
    assert obj.node_log_offsets is not owner.node_log_offsets

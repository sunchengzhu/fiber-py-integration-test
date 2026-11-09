"""Offline checks that PAYMENT-05 rejects incorrect accounting/trace evidence."""

from copy import deepcopy

import pytest

from test_cases.fiber.devnet.lsp.test_hosted_outbound_payment import (
    _active_target_tlcs,
    _assert_outbound_funds,
    _trace_add_tlc,
)

H = "0x" + "12" * 32
C = "0x" + "34" * 32


def test_receiver_trace_requires_complete_assigned_tlc_fields():
    line = f"Channel actor processing message: message: PeerMessage(AddTlc(AddTlc {{ channel_id: {C}, tlc_id: 7, amount: 1000000, payment_hash: {H}, expiry: 1800000000000, hash_algorithm: CkbHash }}))"
    assert _trace_add_tlc(line) == {
        "channel_id": C,
        "payment_hash": H,
        "tlc_id": 7,
        "amount": 1000000,
        "expiry": 1800000000000,
    }
    assert _trace_add_tlc(line.replace("PeerMessage", "Command")) is None
    with pytest.raises(ValueError, match="expiry"):
        _trace_add_tlc(line.replace("expiry: 1800000000000, ", ""))


def _balances():
    before, after = {}, {}
    for key, delta in {
        "A": -1005000,
        "T-A": 1005000,
        "P": 1000000,
        "T-P": -1000000,
    }.items():
        before[key] = {
            "channel_id": C,
            "channel_outpoint": "funding-" + key,
            "state": {"state_name": "ChannelReady"},
            "local_balance": hex(10**9),
            "remote_balance": hex(10**9),
            "offered_tlc_balance": "0x0",
            "received_tlc_balance": "0x0",
            "shutdown_transaction_hash": None,
        }
        after[key] = {
            **deepcopy(before[key]),
            "local_balance": hex(10**9 + delta),
            "remote_balance": hex(10**9 - delta),
        }
    return before, after


def test_outbound_four_endpoint_conservation():
    before, after = _balances()
    _assert_outbound_funds(before, after, 1000000, 1005000, 5000)


@pytest.mark.parametrize(
    "mutation",
    [
        "payer_direction",
        "duplicate_recipient",
        "wrong_fee",
        "locked",
        "mirror",
        "funding_changed",
    ],
)
def test_outbound_oracle_rejects_bad_economic_evidence(mutation):
    before, after = _balances()
    fee = 5000
    if mutation == "payer_direction":
        after["A"]["local_balance"] = hex(10**9 + 1005000)
    elif mutation == "duplicate_recipient":
        after["P"]["local_balance"] = hex(10**9 + 2000000)
        after["T-P"]["local_balance"] = hex(10**9 - 2000000)
    elif mutation == "wrong_fee":
        fee = 10000
    elif mutation == "locked":
        after["A"]["offered_tlc_balance"] = "0x1"
    elif mutation == "mirror":
        after["T-A"]["remote_balance"] = hex(10**9)
    else:
        after["P"]["channel_outpoint"] = "replacement-funding"
    with pytest.raises(AssertionError):
        _assert_outbound_funds(before, after, 1000000, 1005000, fee)


def test_terminal_tlc_history_is_not_an_active_lock():
    old = {"payment_hash": H, "status": {"Inbound": "RemoveAckConfirmed"}}
    live = {"payment_hash": H, "status": {"Outbound": "Committed"}}
    other = {"payment_hash": "0x" + "56" * 32, "status": {"Outbound": "Committed"}}
    assert _active_target_tlcs({"pending_tlcs": [old, live, other]}, H) == [live]

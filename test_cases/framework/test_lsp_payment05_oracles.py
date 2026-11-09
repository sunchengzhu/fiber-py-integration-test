"""Offline checks that PAYMENT-05 rejects incorrect accounting/trace evidence."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

import test_cases.fiber.devnet.lsp.test_hosted_outbound_payment as outbound

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


def _exercise_outbound_body(tmp_path, monkeypatch, scenario, trace):
    """Drive the real test body with controlled observations, without nodes."""
    clock = [0.0]
    preimage = "0x" + "42" * 32
    payment_hash = outbound._payment_hash(preimage)
    before, after = _balances()
    for left, right, channel in (("A", "T-A", C), ("P", "T-P", "0x" + "56" * 32)):
        for key in (left, right):
            for views in (before, after):
                views[key]["channel_id"] = channel
                views[key]["channel_outpoint"] = "funding-" + left
                views[key]["pending_tlcs"] = []
    obj = object.__new__(outbound.TestHostedOutboundPayment)
    obj.tenants = [{"client": "A"}]
    obj.fiber2 = SimpleNamespace(client="P")
    obj.business_until = 420.0
    obj.public_key = "T"
    obj.evidence_dir = tmp_path
    (tmp_path / "observations.jsonl").write_text("")
    state = {"fulfilled": False, "pre_samples": 0, "fingerprints": 0}
    trace.update(object=obj, state=state, samples=[], success_samples=[], events=[])
    original_dumps = outbound.json.dumps

    def record(stage, **values):
        row = {"stage": stage, **values}
        trace["events"].append(row)
        with (tmp_path / "observations.jsonl").open("a") as stream:
            stream.write(original_dumps(row) + "\n")

    def rpc(client, method, params, until):
        record("rpc", method=method, params=params)
        if method == "new_invoice":
            return {
                "invoice": {
                    "data": {"payment_hash": payment_hash, "timestamp": hex(1000000)}
                },
                "invoice_address": "test-invoice",
            }
        if method == "get_invoice":
            return {"status": "Open"}
        if method == "send_payment":
            return {"payment_hash": payment_hash}
        raise AssertionError(method)

    def control(tenant, operation, until, values):
        if operation == "fulfill":
            state["fulfilled"] = True
        return {"saved": True}

    logs = {key: {"tlcs": {}} for key in ("T-A", "P")}

    def sample(tenant, target, sources, until):
        assert target == payment_hash
        if trace["samples"] and clock[0] - trace["samples"][-1]["finished"] > 2:
            # Preserve the real sampling seam's guard while mocking RPC traffic.
            obj._fail_outbound(
                "observation_limit", "complete sample interval exceeded 2 seconds"
            )
        for key, amount in (("T-A", 1005000), ("P", 1000000)):
            logs[key]["tlcs"][0] = {
                "channel_id": before[key]["channel_id"],
                "tlc_id": 0,
                "amount": amount,
                "payment_hash": payment_hash,
                "expiry": 2000000,
            }
        views = deepcopy(after)
        observed = preimage
        if not state["fulfilled"]:
            state["pre_samples"] += 1
            sequence = {
                "early_overcredit": [1000000, 2000000, 1000000],
                "early_reversal": [1000000, 0, 1000000],
            }.get(scenario)
            if sequence:
                delta = sequence[min(state["pre_samples"] - 1, 2)]
                views["P"]["local_balance"] = hex(10**9 + delta)
                views["P"]["remote_balance"] = hex(10**9 - delta)
                views["T-P"]["local_balance"] = hex(10**9 - delta)
                views["T-P"]["remote_balance"] = hex(10**9 + delta)
                observed = preimage if state["pre_samples"] >= 3 else None
            views["A"], views["T-A"] = deepcopy(before["A"]), deepcopy(before["T-A"])
        result = {
            "views": views,
            "payment": {
                "status": "Success" if state["fulfilled"] else "Inflight",
                "payment_preimage": observed,
                "fee": hex(5000),
            },
            "invoice": {"status": "Paid"},
            "signing": {"type": "NoSignatureRequired"},
            "records": [{"tlcs": [{"payment_hash": payment_hash}]}],
            "finished": clock[0],
        }
        trace["samples"].append(deepcopy(result))
        if state["fulfilled"]:
            trace["success_samples"].append(clock[0])
        record("payment05_sample", **result)
        return result

    def dumps(value, *args, **kwargs):
        if isinstance(value, dict) and set(value) == {
            "views",
            "payment",
            "invoice",
            "signing",
        }:
            state["fingerprints"] += 1
            if scenario == "post_sample_delay" and state["fingerprints"] == 3:
                clock[0] += 3.5
        return original_dumps(value, *args, **kwargs)

    obj._record = record
    obj._rpc = rpc
    obj._control = control
    obj._views = lambda until: deepcopy(before)
    obj._signing = lambda tenant, until: {"type": "NoSignatureRequired"}
    obj._qualify_trace = lambda: logs
    obj._outbound_sample = sample
    obj._pause = lambda until, seconds: clock.__setitem__(0, clock[0] + seconds)
    obj.generate_random_preimage = lambda: preimage
    with monkeypatch.context() as patch:
        patch.setattr(outbound.time, "monotonic", lambda: clock[0])
        patch.setattr(outbound.time, "time", lambda: 1000 + clock[0])
        patch.setattr(outbound.json, "dumps", dumps)
        obj.test_hosted_tenant_pays_ordinary_node()


@pytest.mark.parametrize(
    "scenario,message",
    [
        ("early_overcredit", "unexpected receiver balance"),
        ("early_reversal", "receiver balance reversed"),
    ],
)
def test_pre_fulfill_receiver_fault_is_rejected(
    tmp_path, monkeypatch, scenario, message
):
    trace = {}
    with pytest.raises(AssertionError, match=message):
        _exercise_outbound_body(tmp_path, monkeypatch, scenario, trace)
    assert not trace["state"]["fulfilled"]
    assert not any(row["stage"] == "payment05_passed" for row in trace["events"])


def test_post_sample_processing_delay_cannot_fill_stability_window(
    tmp_path, monkeypatch
):
    trace = {}
    with pytest.raises(
        AssertionError,
        match="observation_limit: complete sample interval exceeded 2 seconds",
    ):
        _exercise_outbound_body(tmp_path, monkeypatch, "post_sample_delay", trace)
    assert trace["success_samples"] == [0, 1, 2]
    assert not any(row["stage"] == "payment05_passed" for row in trace["events"])


def test_outbound_body_accepts_fresh_stable_normal_flow(tmp_path, monkeypatch):
    trace = {}
    _exercise_outbound_body(tmp_path, monkeypatch, "normal", trace)
    passed = next(row for row in trace["events"] if row["stage"] == "payment05_passed")
    fresh_span = trace["success_samples"][-1] - trace["success_samples"][0]
    assert trace["object"].result == "passed"
    assert fresh_span >= 5
    assert passed["stability_seconds"] == pytest.approx(fresh_span)

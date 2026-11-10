"""Offline ordering checks for Delivery evidence, with real regression rejection."""

import copy
import json

import pytest

import test_cases.fiber.devnet.lsp.test_delivery_acceptance as delivery

KEY = {"incoming_channel_id": "0x" + "12" * 32, "incoming_tlc_id": 0}
HASH = "0x" + "34" * 32
FULFILL = {"RemoveTlcFulfill": {"payment_preimage": "0x" + "56" * 32}}
FAIL = {"RemoveTlcFail": {"error_code": "TemporaryNodeFailure"}}


def snapshot(sequence, reason=None, *, absent=False, status=None, attempts=1):
    result = {
        "snapshot_sequence": sequence,
        "captures": [
            {
                "key": KEY,
                "request": {"payment_hash": HASH},
                "upstream_tlc": None if absent else {"removed_reason": reason},
            }
        ],
        "sessions": [],
        "deliveries": [],
        "channels": [],
    }
    if status:
        result["sessions"] = [
            {
                "session": {
                    "request": {"payment_hash": HASH},
                    "created_at": 1,
                    "status": status,
                },
                "previous_keys": [KEY],
                "attempts": [{"id": i} for i in range(attempts)],
            }
        ]
    return result


def observer(tmp_path, calls):
    case = object.__new__(delivery.TestDeliveryAcceptance)
    case.events_path = tmp_path / "events.jsonl"
    case.snapshot_event_offset = 0
    case.snapshot_last_sequence = 0
    case.all_keys = {}
    case.tlc_history = {}
    case.session_history = {}
    case.payments = {"A": {"hash": HASH}}
    case._record = lambda *args, **kwargs: None
    queue = iter(calls)

    def control(command, until):
        assert command == "snapshot"
        events, response = next(queue)
        with case.events_path.open("a") as stream:
            for event in events:
                stream.write(
                    json.dumps(
                        {
                            **copy.deepcopy(event),
                            "event": "snapshot",
                            "monotonic_ms": event["snapshot_sequence"] * 100,
                        }
                    )
                    + "\n"
                )
        return copy.deepcopy(response)

    case._delivery = control
    return case


def test_delayed_pending_event_does_not_follow_a_newer_direct_completion(tmp_path):
    pending, complete, pruned = (
        snapshot(1),
        snapshot(2, FULFILL),
        snapshot(3, absent=True),
    )
    case = observer(tmp_path, [([pending, complete], complete), ([pruned], pruned)])
    case._snapshot_delivery(1000)
    case._snapshot_delivery(1000)
    history = case.tlc_history[json.dumps(KEY, sort_keys=True)]
    assert [row["removed_reason"] for row in history] == [None, FULFILL]
    assert case.snapshot_last_sequence == 3
    assert len(case.events_path.read_text().splitlines()) == 3


@pytest.mark.parametrize(
    "later", [None, FAIL, {"RemoveTlcFulfill": {"payment_preimage": "0x" + "78" * 32}}]
)
def test_true_tlc_completion_regression_or_change_is_rejected(tmp_path, later):
    first, second = snapshot(1, FULFILL), snapshot(2, later)
    case = observer(tmp_path, [([first], first), ([second], second)])
    case._snapshot_delivery(1000)
    with pytest.raises(
        AssertionError, match="original TLC completion regressed or changed"
    ):
        case._snapshot_delivery(1000)


def test_true_downstream_terminal_regression_is_rejected(tmp_path):
    first, second = snapshot(1, status="Success"), snapshot(2, status="InFlight")
    case = observer(tmp_path, [([first], first), ([second], second)])
    case._snapshot_delivery(1000)
    with pytest.raises(
        AssertionError, match="downstream terminal outcome regressed or changed"
    ):
        case._snapshot_delivery(1000)


def test_true_attempt_history_loss_is_rejected(tmp_path):
    first = snapshot(1, status="Success", attempts=2)
    second = snapshot(2, status="Success", attempts=1)
    case = observer(tmp_path, [([first], first), ([second], second)])
    case._snapshot_delivery(1000)
    with pytest.raises(AssertionError, match="downstream attempt history regressed"):
        case._snapshot_delivery(1000)


@pytest.mark.parametrize("sequences", [[1, 3], [1, 1], [2, 1]])
def test_missing_duplicate_or_reordered_snapshot_is_rejected(tmp_path, sequences):
    events = [snapshot(n) for n in sequences]
    case = observer(tmp_path, [(events, events[-1])])
    with pytest.raises(AssertionError, match="snapshot sequence"):
        case._snapshot_delivery(1000)


def test_direct_response_must_be_bound_to_its_logged_snapshot(tmp_path):
    case = observer(tmp_path, [([snapshot(1)], snapshot(2, FULFILL))])
    with pytest.raises(AssertionError, match="direct snapshot"):
        case._snapshot_delivery(1000)


def test_snapshot_log_truncation_is_rejected(tmp_path):
    first, second = snapshot(1), snapshot(2)
    case = observer(tmp_path, [([first], first), ([], second)])
    case._snapshot_delivery(1000)
    case.events_path.write_text("")
    with pytest.raises(AssertionError, match="event log was truncated"):
        case._snapshot_delivery(1000)


def test_direct_response_with_same_sequence_cannot_change_logged_facts(tmp_path):
    logged, response = snapshot(1), snapshot(1, FULFILL)
    case = observer(tmp_path, [([logged], response)])
    with pytest.raises(AssertionError, match="direct snapshot differs"):
        case._snapshot_delivery(1000)

"""The approved valid-B replay must carry both B's hash and B's routing target."""

import copy

import pytest

import test_cases.fiber.devnet.lsp.test_delivery_acceptance as delivery

A = "02" + "12" * 32
B = "03" + "34" * 32
A_HASH = "0x" + "56" * 32
B_HASH = "0x" + "78" * 32
ORIGINAL = {
    "payment_hash": A_HASH,
    "next_node_id": A,
    "amount_to_forward": 1_000_000,
    "previous_tlc": {"prev_channel_id": "0x" + "90" * 32, "prev_tlc_id": 7},
    "remaining_trampoline_onion": [1, 2, 3],
}


def replay_case(mutate=None):
    case = object.__new__(delivery.TestDeliveryTargetConflict)
    case.all_keys = {"original": copy.deepcopy(ORIGINAL)}
    case.payments = {"B": {"hash": B_HASH}}
    case.baseline = {"T-B": {"pubkey": B}}
    case._record = lambda *args, **kwargs: None
    captured = []

    def control(command, until, **values):
        assert command == "replay"
        captured.append(values)
        request = copy.deepcopy(ORIGINAL)
        for field in ("payment_hash", "next_node_id", "amount_to_forward"):
            if field in values:
                request[field] = values[field]
        if mutate:
            mutate(request)
        return {"request": request, "reply": "existing-key rejection"}

    case._delivery = control
    return case, captured


def test_valid_b_hash_and_target_preserve_original_key_and_other_fields():
    case, calls = replay_case()
    result = case._replay("hash", 1000)
    assert calls == [{"variant": "hash", "payment_hash": B_HASH, "next_node_id": B}]
    assert result["request"] == {**ORIGINAL, "payment_hash": B_HASH, "next_node_id": B}
    assert case.all_keys["original"] == ORIGINAL


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_to_forward", 2),
        ("next_node_id", A),
        ("payment_hash", A_HASH),
        ("previous_tlc", {}),
    ],
)
def test_valid_target_replay_rejects_unapproved_request_changes(field, value):
    case, _ = replay_case(lambda request: request.update({field: value}))
    with pytest.raises(AssertionError, match="outside approved variant"):
        case._replay("hash", 1000)

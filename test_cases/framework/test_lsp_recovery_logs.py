"""Offline checks for exact Hosted recovery attribution in raw FNN logs."""

from types import SimpleNamespace

import pytest

import test_cases.fiber.devnet.lsp.test_channel_signing_deadline as deadline

CHANNEL = "0x" + "12" * 32
PUBKEY = "0x02" + "34" * 32


def _logs(*, colored, mutation=None):
    recognition = f"channel Hash256({CHANNEL}) is shutdown by remote"
    transition = (
        "Updating channel state from ShuttingDown(ShuttingDownFlags(WAITING_COMMITMENT_CONFIRMATION)) "
        "to Closed(CloseFlags(UNCOOPERATIVE_REMOTE | WAITING_ONCHAIN_SETTLEMENT))"
    )
    key = PUBKEY if mutation != "other_tenant" else "0x03" + "56" * 32
    if mutation == "other_channel":
        recognition = recognition.replace(CHANNEL, "0x" + "78" * 32)
    if mutation == "local_close":
        transition = transition.replace("UNCOOPERATIVE_REMOTE", "UNCOOPERATIVE_LOCAL")

    def entry(message, actor_id):
        return (
            f"  2026-11-09T15:35:44.435651Z DEBUG fnn::fiber::network: {message}\n"
            "    at crates/fiber-lib/src/fiber/network.rs:4945\n"
            f'    in ractor::actor::Actor with id: "{actor_id}", name: "HostedTenant {key}"\n'
        )

    blocks = [
        entry(recognition, "0.12"),
        entry(transition, "0.13" if mutation == "other_actor" else "0.12"),
    ]
    if mutation == "missing_recognition":
        blocks = blocks[1:]
    if mutation == "missing_transition":
        blocks = blocks[:1]
    if mutation == "reverse_order":
        blocks.reverse()
    text = "\n".join(blocks)
    if colored:
        text = "\n".join(
            f"{line[:2]}\x1b[2m{line[2:]}\x1b[0m" if line else line
            for line in text.split("\n")
        )
    return text


def _read(tmp_path, text):
    (tmp_path / "node.log").write_text(text)
    case = object.__new__(deadline.TestChannelSigningDeadline)
    case.fiber1 = SimpleNamespace(tmp_path=str(tmp_path))
    case.channel_id = CHANNEL
    return case._recovery_logs({"a_pubkey": PUBKEY})


@pytest.mark.parametrize("colored", [False, True], ids=["plain", "ansi"])
def test_recovery_logs_attribute_same_hosted_actor_and_preserve_line_numbers(
    tmp_path, colored
):
    raw = _logs(colored=colored)
    result = _read(tmp_path, raw)
    assert result is not None
    assert result["actor_id"] == "0.12"
    assert result["recognition_line"] == 1
    assert result["transition_line"] == 5
    assert CHANNEL in result["recognition"]
    assert PUBKEY in result["transition"]
    assert (
        tmp_path / "node.log"
    ).read_text() == raw, "raw evidence must not be rewritten"


@pytest.mark.parametrize(
    "mutation",
    [
        "other_tenant",
        "other_channel",
        "other_actor",
        "missing_recognition",
        "missing_transition",
        "local_close",
        "reverse_order",
    ],
)
def test_recovery_logs_reject_unrelated_or_incomplete_attribution(tmp_path, mutation):
    assert _read(tmp_path, _logs(colored=True, mutation=mutation)) is None

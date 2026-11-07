"""F2 SDK supplement: reviewed TLC validation cases without nodes or natural-time waiting."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

pytestmark = pytest.mark.manual_nightly


def number(value):
    return (
        int(value, 16 if value.startswith("0x") else 10)
        if isinstance(value, str)
        else value
    )


def raw(value):
    return bytes.fromhex(value.removeprefix("0x"))


def ckb_hash(value):
    return hashlib.blake2b(value, digest_size=32, person=b"ckb-default-hash").digest()


def check_baseline(baseline):
    """Decode committed bytes and compute the payout independently of SDK results."""
    hlen = {"legacy": 20, "full_hash": 32}[baseline["feature"]]
    assert baseline["payment_hash_len"] == hlen
    record = baseline["record"]
    assert record["reference"]["for_remote"] is True
    assert number(record["reference"]["version"]) == 2
    assert len(record["tlcs"]) == 1
    tlc = record["tlcs"][0]
    creation = baseline["creation"]
    assert (
        number(creation["derivation_index"])
        == number(tlc["local_key_commitment_number"])
        == 1
    )
    assert creation["witness_index"] == 0
    assert number(creation["previous_reference"]["version"]) == number(
        creation["derivation_index"]
    )
    assert creation["previous_reference"]["for_remote"] is True
    assert creation["local_public_key"] == tlc["local_public_key"]
    assert creation["remote_public_key"] == tlc["remote_public_key"]
    amount = number(tlc["payment_amount"])
    assert amount == 100_000_000
    assert tlc["inbound"] is False and tlc["hash_algorithm"] == "sha256"
    authorization = baseline["payment_authorization"]
    assert authorization["inbound"] is False
    assert number(authorization["amount"]) == amount
    assert authorization["payment_hash"] == tlc["payment_hash"]
    assert len(raw(tlc["payment_hash"])) == 32
    assert raw(tlc["payment_hash"]) == bytes.fromhex("35" * 32)

    body = raw(baseline["witness_body"])
    entry_len = 65 + hlen
    assert body[0] == 1 and len(body) == 1 + entry_len + 72
    entry = body[1 : 1 + entry_len]
    assert entry == raw(tlc["entry"])
    assert entry[0] == 2  # SHA-256, A offered as viewed in the remote record.
    assert int.from_bytes(entry[1:17], "little") == amount
    assert entry[17 : 17 + hlen] == raw(tlc["payment_hash"])[:hlen]
    assert entry[17 + hlen : 37 + hlen] == ckb_hash(raw(tlc["remote_public_key"]))[:20]
    assert entry[37 + hlen : 57 + hlen] == ckb_hash(raw(tlc["local_public_key"]))[:20]
    expiry = number(tlc["expiry"])
    assert int.from_bytes(entry[-8:], "little") == (
        0x4000000000000000 | (expiry // 1000)
    )
    balances = body[1 + entry_len :]
    assert balances[:20] == ckb_hash(raw(record["remote_settlement_key"]))[:20]
    assert balances[36:56] == ckb_hash(raw(record["local_settlement_key"]))[:20]
    ma, mt = number(record["local_amount"]), number(record["remote_amount"])
    assert int.from_bytes(balances[20:36], "little") == mt
    assert int.from_bytes(balances[56:72], "little") == ma

    chain = baseline["chain"]
    source = chain["source_cell"]["output"]
    args = raw(source["lock"]["args"])
    assert len(args) == (57 if hlen == 20 else 58)
    assert args[36:56] == ckb_hash(body)[:20] and args[56] == 0
    assert args[57:] == (b"" if hlen == 20 else b"\x01")
    assert int.from_bytes(args[28:36], "big") == number(record["reference"]["version"])
    assert source == record["transaction"]["outputs"][0]
    assert source["type"] is None and chain["source_cell"]["data"] == "0x"
    funding_capacity = number(baseline["funding"]["outputs"][0]["capacity"])
    c0 = number(source["capacity"])
    assert ma + mt + amount == funding_capacity
    assert funding_capacity - c0 == number(
        baseline["opening_parameters"]["commitment_fee"]
    )
    assert number(chain["median_time_ms"]) // 1000 > expiry // 1000

    request = baseline["request"]
    assert request["key_purpose"] == {
        "type": "Tlc",
        "commitment_number": number(creation["derivation_index"]),
    }
    tx = request["transaction"]
    approval = baseline["authorization"]
    assert approval["source"] == record["reference"]
    assert len(tx["inputs"]) == 2
    assert tx["inputs"][0]["previous_output"] == chain["source_outpoint"]
    assert tx["inputs"][1]["previous_output"] == chain["sponsor_outpoint"]
    assert approval["additional_inputs"] == [chain["sponsor_outpoint"]]
    assert tx["cell_deps"] == approval["cell_deps"]
    assert number(tx["inputs"][1]["since"]) == (0x4000000000000000 | expiry // 1000)
    assert number(tx["inputs"][0]["since"]) == int.from_bytes(args[20:28], "little")
    assert tx["witnesses"] == [
        "0x" + (bytes([16, 0, 0, 0] * 4 + [1]) + body + bytes(67)).hex()
    ]
    assert len(tx["outputs"]) == 2 and tx["outputs_data"] == ["0x", "0x"]
    remaining, destination = tx["outputs"]
    expected_lock = copy.deepcopy(source["lock"])
    next_body = b"\x00" + balances
    assert raw(baseline["remaining_witness_body"]) == next_body
    expected_lock["args"] = (
        "0x" + (args[:36] + ckb_hash(next_body)[:20] + b"\x01" + args[57:]).hex()
    )
    assert remaining["lock"] == expected_lock and remaining["type"] is None
    assert (
        destination["lock"] == approval["destination"] and destination["type"] is None
    )
    sponsor = chain["sponsor_cell"]["output"]
    assert sponsor["lock"] == approval["destination"] and sponsor["type"] is None
    assert chain["sponsor_cell"]["data"] == "0x"
    s, r, o, fee = map(
        number,
        (
            sponsor["capacity"],
            remaining["capacity"],
            destination["capacity"],
            approval["fee"],
        ),
    )
    assert r == c0 - amount
    assert o == s + amount - fee
    assert c0 + s - r - o == fee and 0 <= fee <= 10_000


def _same_except_witness(baseline, changed):
    expected = copy.deepcopy(baseline["request"])
    expected["transaction"]["witnesses"] = changed["transaction"]["witnesses"]
    return changed == expected


def _assert_witness_variant(baseline, call, offset, name):
    changed = call["input"]
    assert call["error"]["reason"] == (
        "commitment validation: settlement witness is not committed by live input"
    )
    assert changed["key_purpose"] == baseline["request"]["key_purpose"]
    assert _same_except_witness(baseline, changed)
    before = raw(baseline["request"]["transaction"]["witnesses"][0])
    after = raw(changed["transaction"]["witnesses"][0])
    assert len(before) == len(after)
    assert [i for i, (a, b) in enumerate(zip(before, after)) if a != b] == [offset]
    if name == "wrong_tlc_direction":
        assert after[18] == before[18] ^ 1
    elif name == "wrong_tlc_amount":
        assert int.from_bytes(after[19:35], "little") == (
            int.from_bytes(before[19:35], "little") + 1
        )


def _assert_residual_variant(baseline, call):
    changed = call["input"]
    expected = copy.deepcopy(baseline["request"])
    expected["transaction"]["outputs"][0]["lock"]["args"] = changed["transaction"][
        "outputs"
    ][0]["lock"]["args"]
    assert changed == expected
    before = raw(baseline["request"]["transaction"]["outputs"][0]["lock"]["args"])
    after = raw(changed["transaction"]["outputs"][0]["lock"]["args"])
    assert len(before) == len(after)
    assert [i for i, (a, b) in enumerate(zip(before, after)) if a != b] == [36]


# TEST-MAP: LSP-REFUND-F2-01
# TEST-MAP: LSP-REFUND-F2-02
# TEST-MAP: LSP-REFUND-F2-03
# TEST-MAP: LSP-REFUND-F2-04
def test_sdk_tlc_refund_validation_cases():
    """
    1. 在快速入口剩余预算内构造两种 witness 格式的有效 SDK 历史，独立核对付款与资金字节。
    2. 二者各准备正向前置、五项局部错误变体和恢复后的正向请求，验证具体 SDK 拒绝与状态不变。
    3. 核对共 14 个具名结果；旧真实链 F2 仍由 skip 类表示未完成。
    """
    # 1. 仅启动本地 SDK helper；继承父进程组，由统一入口负责最终超时收尾。
    bundle = Path(os.environ["LSP_REFUND_F2_BUNDLE"])
    report = Path(os.environ["LSP_REFUND_F2_REPORT_DIR"])
    deadline = float(os.environ["LSP_REFUND_F2_DEADLINE"])
    remaining = deadline - time.monotonic()
    assert remaining > 0, "no shared execution budget left"
    output, error = report / "sdk-results.jsonl", report / "sdk-stderr.log"
    with output.open("xb") as stdout, error.open("xb") as stderr:
        process = subprocess.Popen(
            [str(bundle / "lsp-refund-f2-fast")], stdout=stdout, stderr=stderr
        )
        try:
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
            pytest.fail("SDK helper exceeded the shared execution deadline")
    assert code == 0, f"SDK helper exit {code}; see {output} and {error}"
    assert time.monotonic() < deadline
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    baselines = [r for r in rows if r["type"] == "baseline"]
    calls = [r for r in rows if r["type"] == "call"]
    completed = [r for r in rows if r["type"] == "complete"]
    assert (
        len(rows) == 17
        and len(baselines) == 2
        and len(calls) == 14
        and len(completed) == 1
    )
    assert {r["feature"] for r in baselines} == {"legacy", "full_hash"}
    assert all(r["case_id"] == "LSP-REFUND-F2-SDK" for r in baselines)
    assert completed[0]["case_id"] == "LSP-REFUND-F2-SDK"
    assert completed[0]["features"] == 2 and completed[0]["calls"] == 14

    expected_names = [
        "positive_before",
        "wrong_tlc_index",
        "wrong_tlc_hash",
        "wrong_tlc_amount",
        "wrong_tlc_direction",
        "wrong_tlc_residual",
        "positive_after",
    ]
    assert len({(c["feature"], c["name"]) for c in calls}) == 14
    assert {(c["feature"], c["name"]) for c in calls} == {
        (f, n) for f in ("legacy", "full_hash") for n in expected_names
    }

    for baseline in baselines:
        check_baseline(baseline)
        feature = baseline["feature"]
        group = [c for c in calls if c["feature"] == feature]
        assert [c["name"] for c in group] == expected_names
        for call in group:
            assert call["authorization"] == baseline["authorization"]
            assert (
                call["store_before_digest"]
                == call["store_after_digest"]
                == baseline["store_digest"]
            )
            assert len(raw(call["store_before_digest"])) == 32
            assert 0 <= call["elapsed_ms"] < 270_000
            assert call["chain_calls"], "SDK never reached the controlled chain boundary"
            methods = {c["method"] for c in call["chain_calls"]}
            assert {"live_cell", "verify_commitment_lineage", "verify_maturity"} <= methods
            # Witness-binding failures can reject before median_time_ms is queried;
            # positive/residual paths are expected to reach it.
            if call["name"] in ("positive_before", "positive_after", "wrong_tlc_residual"):
                assert "median_time_ms" in methods
        by_name = {c["name"]: c for c in group}
        for name in ("positive_before", "positive_after"):
            call = by_name[name]
            assert call["input"] == baseline["request"]
            assert call["error"] is None
            assert call["returned_content"] == baseline["request"]
            assert call["returned_authorization"] == baseline["authorization"]
        index = by_name["wrong_tlc_index"]
        changed = copy.deepcopy(baseline["request"])
        changed["key_purpose"]["commitment_number"] += 1
        assert index["input"] == changed
        assert index["returned_content"] is None
        assert index["returned_authorization"] is None
        assert index["error"]["variant"] == "InvalidContent"
        assert index["error"]["reason"] == "commitment validation: wrong TLC signing key"
        hlen = baseline["payment_hash_len"]
        _assert_witness_variant(
            baseline,
            by_name["wrong_tlc_hash"],
            18 + 17 + hlen // 2,
            "wrong_tlc_hash",
        )
        _assert_witness_variant(
            baseline, by_name["wrong_tlc_amount"], 19, "wrong_tlc_amount"
        )
        _assert_witness_variant(
            baseline, by_name["wrong_tlc_direction"], 18, "wrong_tlc_direction"
        )
        residual = by_name["wrong_tlc_residual"]
        _assert_residual_variant(baseline, residual)
        assert residual["error"]["reason"] == (
            "commitment validation: unapproved on-chain destination"
        )

    print(
        "F2 SDK: 2 formats; 4 valid preparations; 10 named negative rejections; store unchanged"
    )

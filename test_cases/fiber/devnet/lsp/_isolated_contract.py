"""Align an isolated devnet's Type ID cell with the reviewed commitment-lock binary."""

import hashlib
import json
from pathlib import Path

from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._lsp_test import REVISION

EXPECTED_SHA256 = "a7762721ef239b15adbdddca8d772db6e1c001d9f81e23ccc74e1392329931d7"
TYPE_ID_SCRIPT = {
    "code_hash": "0x" + "00" * 25 + "545950455f4944",
    "hash_type": "type",
    "args": "0x082d30abbb75c3db217a78eee4f3e0d5a46c90b56c11dec77f3060319f323808",
}


def align_devnet_commitment_lock(cls, evidence_path):
    """Upgrade the single Type ID cell before any FNN starts, then verify bytes.

    ``cls`` must expose node/Contract/Miner/Config like the LSP test classes do.
    The caller owns the evidence path; an existing file is never replaced.
    """
    root = Path(get_project_root()).resolve()
    contract_path = root / "source/contract/fiber/commitment-lock"
    expected = contract_path.read_bytes()
    assert (
        hashlib.sha256(expected).hexdigest() == EXPECTED_SHA256
    ), "not the reviewed 04c2064 commitment-lock"
    client = cls.node.getClient()
    search = {
        "script": TYPE_ID_SCRIPT,
        "script_type": "type",
        "script_search_mode": "exact",
        "with_data": True,
    }
    cells = client.get_cells(search, "asc", "0x10", None)["objects"]
    assert len(cells) == 1, cells
    old = cells[0]
    evidence_path = Path(evidence_path).resolve()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    assert not evidence_path.exists(), evidence_path
    evidence = {
        "revision": REVISION,
        "chain_dir": cls.node.ckb_dir,
        "before": old,
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
    }
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    tx_hash = cls.Contract.upgrade_ckb_type_contract(
        cls.Config.MINER_PRIVATE_1,
        str(contract_path),
        old["out_point"]["tx_hash"],
        int(old["out_point"]["index"], 16),
        fee=200000,
        api_url=cls.node.rpcUrl,
    )
    evidence["submitted"] = tx_hash
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    confirmed = cls.Miner.miner_until_tx_committed(cls.node, tx_hash)
    tx = confirmed["transaction"]
    assert tx["outputs"][0]["type"] == TYPE_ID_SCRIPT
    assert tx["outputs"][0]["lock"] == old["output"]["lock"]
    assert any(i["previous_output"] == old["out_point"] for i in tx["inputs"])
    assert bytes.fromhex(tx["outputs_data"][0].removeprefix("0x")) == expected
    header = client.call("get_header", [confirmed["tx_status"]["block_hash"]])
    assert client.get_block_hash(header["number"]) == header["hash"]
    live = client.get_live_cell("0x0", tx_hash, True)
    assert live["status"] == "live"
    assert bytes.fromhex(live["cell"]["data"]["content"].removeprefix("0x")) == expected
    cells = client.get_cells(search, "asc", "0x10", None)["objects"]
    assert len(cells) == 1 and cells[0]["out_point"] == {
        "tx_hash": tx_hash,
        "index": "0x0",
    }
    evidence.update(confirmed=confirmed, canonical_header=header, after=cells[0])
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence

"""Hosted no-TLC settlement; 02 is split-path, 05 is SDK prepare-only evidence."""

import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time

import requests
import yaml

from test_cases.fiber.devnet.lsp._watchtower_rpc import ChainAudit
from test_cases.fiber.devnet.lsp._lsp_test import (
    ChannelSigningTestBase,
    BUNDLE,
    REVISION,
)


def number(value):
    return (
        int(value, 16)
        if isinstance(value, str) and value.startswith("0x")
        else int(value)
    )


def raw(value):
    return bytes.fromhex(value.removeprefix("0x"))


def digest(value):
    return hashlib.blake2b(value, digest_size=32, person=b"ckb-default-hash").digest()


class WatchtowerBudgetExpired(BaseException):
    pass


class _WatchtowerBase(ChannelSigningTestBase):
    tenant_labels = ("A", "B")
    agent_extra_args = ("--ack-held-events",)
    tenant_rpc_timeout = 10

    @contextmanager
    def budget(self, seconds):
        now = time.monotonic()
        old_timer = signal.getitimer(signal.ITIMER_REAL)
        old_handler = signal.getsignal(signal.SIGALRM)
        due = min(now + seconds, getattr(self, "total_due", float("inf")))
        if old_timer[0]:
            due = min(due, now + old_timer[0])

        def expired(*_):
            raise WatchtowerBudgetExpired(f"watchtower deadline exceeded: {due}")

        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, max(0.000001, due - now))
        try:
            yield due
            assert time.monotonic() <= due, "late result"
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            if old_timer[0] and now + old_timer[0] > time.monotonic():
                signal.setitimer(
                    signal.ITIMER_REAL, now + old_timer[0] - time.monotonic()
                )

    @classmethod
    def setup_class(cls):
        cls.chain_started = time.monotonic()
        root = Path(__file__).resolve().parents[4]
        (root / "tmp").mkdir(exist_ok=True)
        cls.tmp_path_name = str(
            Path(
                tempfile.mkdtemp(prefix="lsp-watchtower-", dir=root / "tmp")
            ).relative_to(root)
        )
        timer = object.__new__(cls)
        timer.total_due = float(os.environ.get("LSP_WATCHTOWER_ROUND_UNTIL", "inf")) - 60
        try:
            with timer.budget(300):
                super().setup_class()
                cls.prepare_isolated_contract(root)
        except BaseException:
            if hasattr(cls, "node"):
                cls.teardown_class()
            raise
        cls.chain_unaccounted = True

    @classmethod
    def prepare_isolated_contract(cls, root):
        """Update only this class's extracted devnet, before any FNN starts."""
        path = root / "source/contract/fiber/commitment-lock"
        expected = path.read_bytes()
        assert hashlib.sha256(expected).hexdigest() == (
            "a7762721ef239b15adbdddca8d772db6e1c001d9f81e23ccc74e1392329931d7"
        ), "not the reviewed 04c2064 commitment-lock"
        script = {
            "code_hash": "0x" + "00" * 25 + "545950455f4944",
            "hash_type": "type",
            "args": "0x082d30abbb75c3db217a78eee4f3e0d5a46c90b56c11dec77f3060319f323808",
        }
        client = cls.node.getClient()
        search = {
            "script": script,
            "script_type": "type",
            "script_search_mode": "exact",
            "with_data": True,
        }
        cells = client.get_cells(search, "asc", "0x10", None)["objects"]
        assert len(cells) == 1, cells
        old = cells[0]
        evidence = {
            "revision": REVISION,
            "chain_dir": cls.node.ckb_dir,
            "before": old,
            "expected_sha256": hashlib.sha256(expected).hexdigest(),
        }
        evidence_path = Path(os.environ["LSP_RUN_ARTIFACTS"]) / (
            cls.__name__ + "-isolated-contract.json"
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        assert not evidence_path.exists(), evidence_path
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        tx_hash = cls.Contract.upgrade_ckb_type_contract(
            cls.Config.MINER_PRIVATE_1,
            str(path),
            old["out_point"]["tx_hash"],
            number(old["out_point"]["index"]),
            fee=200000,
            api_url=cls.node.rpcUrl,
        )
        evidence["submitted"] = tx_hash
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        confirmed = cls.Miner.miner_until_tx_committed(cls.node, tx_hash)
        tx = confirmed["transaction"]
        assert tx["outputs"][0]["type"] == script
        assert tx["outputs"][0]["lock"] == old["output"]["lock"]
        assert any(i["previous_output"] == old["out_point"] for i in tx["inputs"])
        assert raw(tx["outputs_data"][0]) == expected
        header = client.call("get_header", [confirmed["tx_status"]["block_hash"]])
        assert client.get_block_hash(header["number"]) == header["hash"]
        live = client.get_live_cell("0x0", tx_hash, True)
        assert (
            live["status"] == "live"
            and raw(live["cell"]["data"]["content"]) == expected
        )
        cells = client.get_cells(search, "asc", "0x10", None)["objects"]
        assert len(cells) == 1 and cells[0]["out_point"] == {
            "tx_hash": tx_hash,
            "index": "0x0",
        }
        evidence.update(confirmed=confirmed, canonical_header=header, after=cells[0])
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")

    @classmethod
    def teardown_class(cls):
        super().teardown_class()
        directory = Path(__file__).resolve().parents[4] / cls.tmp_path_name
        # Remove empty parents only; preserve any unexpected remaining evidence.
        for child in (directory / "contract", directory / "fiber", directory):
            if child.exists() and not any(child.iterdir()):
                child.rmdir()

    def setup_method(self, method):
        self.started = (
            type(self).chain_started
            if type(self).chain_unaccounted
            else time.monotonic()
        )
        type(self).chain_unaccounted = False
        self.phase_deadlines = {}
        caps = {
            "test_authorized_settlement": 1260,
            "test_missing_approval_then_adapted_settlement": 1440,
            "test_cross_tenant_read": 1320,
            "test_cross_tenant_submit": 2100,
            "test_independent_destination_rejects_operator_payout": 1020,
        }
        self.cleanup_due = min(
            self.started + caps.get(method.__name__, 1260),
            float(os.environ.get("LSP_WATCHTOWER_ROUND_UNTIL", "inf")),
        )
        self.total_due = self.cleanup_due - 60
        self.prep_due = min(self.started + 300, self.total_due)
        self.evidence = []
        self.requests_seen = {}
        with self.budget(self.prep_due - time.monotonic()):
            super().setup_method(method)

    def teardown_method(self, method):
        # Reserve cleanup inside the original deadline; never renew it on failure.
        self.total_due = self.cleanup_due
        with self.budget(60):
            super().teardown_method(method)

    def record(self, stage, **data):
        row = {"stage": stage, "at": time.monotonic(), "wall": time.time(), **data}
        self.evidence.append(row)
        path = Path(self.fiber1.tmp_path) / "watchtower-evidence.jsonl"
        with path.open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    def rpc(self, method, params, client=None, error=False):
        target = client or self.node.getClient()
        url = getattr(target, "url", None) or self.node.rpcUrl
        headers = getattr(target, "other_params", {})
        with self.budget(10), requests.Session() as session:
            session.trust_env = False
            reply = session.post(
                url,
                headers=headers,
                json={"id": 1, "jsonrpc": "2.0", "method": method, "params": params},
                timeout=10,
            ).json()
        self.record("rpc", method=method, params=params, reply=reply)
        if error:
            assert "error" in reply and "result" not in reply, reply
            return reply
        assert "error" not in reply, reply
        return reply["result"]

    def control(self, tenant, operation, values=None, error=False):
        payload = {
            "operation": operation,
            "channel_id": tenant["channel_id"],
            **(values or {}),
        }
        with self.budget(10), socket.create_connection(
            ("127.0.0.1", tenant["control_port"]), timeout=10
        ) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode())
            with connection.makefile("r") as stream:
                reply = json.loads(stream.readline())
        self.record("control", tenant=tenant["label"], request=payload, reply=reply)
        if error:
            assert "error" in reply, reply
        else:
            assert "error" not in reply, reply
        return reply.get("result", reply)

    def setUp(self):
        with self.budget(self.prep_due - time.monotonic()):
            super().setUp()
            for tenant in self.tenants:
                self.tenant, self.client, self.channel_id, self.gate = (
                    tenant,
                    tenant["client"],
                    tenant["channel_id"],
                    tenant["gate"],
                )
                self.gate.release()
                self._submit(self.gate.submission)
                self._finish_opening()
                tenant["baseline"] = self._channel(tenant["client"])
                assert not tenant["baseline"]["pending_tlcs"]
                tenant["records"] = self.control(tenant, "watchtower-records")
                assert any(r["complete"] for r in tenant["records"])
                p = raw(tenant["baseline"]["channel_outpoint"])
                tenant["funding"] = {
                    "tx_hash": "0x" + p[:32].hex(),
                    "index": hex(int.from_bytes(p[32:], "little")),
                }
            self.a = self.tenants[0]
            self.b = self.tenants[1] if len(self.tenants) > 1 else None
            # The destination is independently derived from T's local wallet key.
            wallet = self.Ckb_cli.util_key_info_by_private_key(
                self.account1_private_key
            )
            self.destination = {
                "code_hash": self.Config.CKB_DEFAULT_CONFIG[
                    "ckb_block_assembler_code_hash"
                ],
                "hash_type": "type",
                "args": wallet["lock_arg"],
            }
            config = yaml.load(
                Path(self.fiber1.fiber_config_path).read_text(), Loader=yaml.BaseLoader
            )
            scripts = {s["name"]: s for s in config["fiber"]["scripts"]}
            self.chain_audit = ChainAudit(
                self.node.rpcUrl, Path(self.fiber1.tmp_path) / "ckb-verifier.jsonl"
            )
            self.addCleanup(self.chain_audit.close)
            self.chain_config = {
                "url": self.chain_audit.url,
                "scripts": scripts,
                "contracts": str(Path("source/contract/fiber").resolve()),
            }
        with self.budget(min(60, self.prep_due - time.monotonic())):
            for tenant in self.tenants:
                tenant["deps"] = self.control(
                    tenant,
                    "watchtower-configure",
                    {
                        "config": {
                            **self.chain_config,
                            "audit": str(
                                tenant["status_file"].with_name(
                                    "independent-chain.jsonl"
                                )
                            ),
                        }
                    },
                )
        sponsor_cells = self.rpc(
            "get_cells",
            [
                {
                    "script": self.destination,
                    "script_type": "lock",
                    "script_search_mode": "exact",
                },
                "asc",
                "0x64",
            ],
        )["objects"]
        plain = [
            c
            for c in sponsor_cells
            if c["output"]["type"] is None and c["output_data"] == "0x"
        ]
        assert (
            sum(number(c["output"]["capacity"]) for c in plain)
            >= len(self.tenants) * 1000 * 100000000
        )
        assert len(
            [c for c in plain if number(c["output"]["capacity"]) >= 1000 * 100000000]
        ) >= len(
            self.tenants
        ), "each channel requires a separate >=1000 CKB sponsor cell"
        self.record(
            "prepared", revision=REVISION, destination=self.destination, sponsors=plain
        )
        assert time.monotonic() <= self.prep_due, "preparation exceeded 300 seconds"

    def approve(self, tenant):
        with self.budget(30):
            self.control(
                tenant,
                "watchtower-authorize",
                {"destination": self.destination, "max_fee": 10000},
            )
            policy = json.loads(
                (
                    tenant["status_file"].parent / "store/watchtower-approvals.json"
                ).read_text()
            )[tenant["channel_id"]]
            assert policy == {"destination": self.destination, "max_fee": 10000}, policy

    def inspect(self, tx, signature=None):
        value = {"transaction": {k: v for k, v in tx.items() if k != "hash"}}
        if signature is not None:
            value["signature"] = signature
        result = json.loads(
            subprocess.check_output(
                [str(BUNDLE / "lsp-integration-driver"), "inspect-onchain"],
                input=json.dumps(value),
                text=True,
                timeout=10,
            )
        )
        if "hash" in tx:
            assert result["tx_hash"] == tx["hash"]
        return result

    def transaction(self, txhash):
        reply = self.rpc("get_transaction", [txhash])
        if reply is None or reply["tx_status"]["status"] != "committed":
            return None
        header = self.rpc("get_header", [reply["tx_status"]["block_hash"]])
        canonical = self.rpc("get_header_by_number", [header["number"]])
        assert canonical["hash"] == header["hash"]
        self.inspect(reply["transaction"])
        return reply["transaction"]

    def spend(self, point):
        parent = self.transaction(point["tx_hash"])
        assert parent
        lock = parent["outputs"][number(point["index"])]["lock"]
        result = self.rpc(
            "get_transactions",
            [
                {"script": lock, "script_type": "lock", "script_search_mode": "exact"},
                "asc",
                "0x64",
            ],
        )
        assert len(result["objects"]) < 100, "indexer page bound"
        for item in result["objects"]:
            if item.get("io_type") != "input":
                continue
            tx = self.transaction(item["tx_hash"])
            if tx and any(i["previous_output"] == point for i in tx["inputs"]):
                return tx
        return None

    def close_and_mature(self, tenant):
        with self.budget(120):
            self.rpc(
                "shutdown_channel",
                [{"channel_id": tenant["channel_id"], "force": True}],
                self.fiber1.client,
            )
            while not (tx := self.spend(tenant["funding"])):
                time.sleep(1)
            assert len(tx["inputs"]) == len(tx["outputs"]) == 1, tx
            assert tx["cell_deps"] == tenant["deps"]["funding_deps"]
            assert tx["inputs"][0]["previous_output"] == tenant["funding"]
            message = subprocess.check_output(
                [str(BUNDLE / "lsp-integration-driver"), "commitment-message"],
                input=json.dumps({k: v for k, v in tx.items() if k != "hash"}),
                text=True,
                timeout=10,
            ).strip()
            records = [
                r for r in tenant["records"] if r["reference"]["tx_hash"] == message
            ]
            assert len(records) == 1, (message, tenant["records"])
            # T holds the aggregate signature for A's remote commitment.
            # A's verified record need not contain that signature; the real
            # canonical CKB confirmation proves the broadcast witness was valid.
            assert records[0]["reference"]["for_remote"] is True
            self.record(
                "verified-remote-commitment",
                tenant=tenant["label"],
                source=records[0],
                confirmed=tx,
                signing_message=message,
            )
            tenant["source"] = records[0]
            tenant["commitment"] = tx
            funding = self.transaction(tenant["funding"]["tx_hash"])
            cf = number(
                funding["outputs"][number(tenant["funding"]["index"])]["capacity"]
            )
            c0 = number(tx["outputs"][0]["capacity"])
            assert (
                sum(int(records[0][k]) for k in ("local_amount", "remote_amount")) == cf
            )
            assert (
                int(records[0]["local_amount"])
                == number(tenant["baseline"]["local_balance"])
                + tenant["opening"]["parameters"]["local_reserved_ckb_amount"]
            )
            assert (
                int(records[0]["remote_amount"])
                == number(tenant["baseline"]["remote_balance"])
                + tenant["opening"]["parameters"]["remote_reserved_ckb_amount"]
            )
            assert (
                int(records[0]["local_amount"]) > 0
                and int(records[0]["remote_amount"]) > 0
            )
            assert cf - c0 == tenant["opening"]["parameters"]["commitment_fee"]
            tenant["funding_capacity"], tenant["close_fee"] = cf, cf - c0
        with self.budget(180):
            origin = self.rpc("get_transaction", [tx["hash"]])["tx_status"][
                "block_hash"
            ]
            epoch = number(self.rpc("get_header", [origin])["epoch"])

            def fraction(e):
                n, i, l = (e & 0xFFFFFF), (e >> 24) & 0xFFFF, (e >> 40) & 0xFFFF
                assert l > 0 and i < l, "invalid epoch fraction"
                return n, i, l

            n, i, l = fraction(epoch)
            while True:
                tip = self.rpc("get_tip_header", [])
                tn, ti, tl = fraction(number(tip["epoch"]))
                if (tn - n - 1) * tl * l + ti * l - i * tl >= 0:
                    break
                # Real CKB blocks, no changed epoch configuration or wall clock.
                for _ in range(20):
                    self.rpc("generate_block", [])
            self.record(
                "mature", tenant=tenant["label"], origin_epoch=hex(epoch), tip=tip
            )
            # Pin the exact observed maturity tip; a moving miner must not extend
            # the indexer's target indefinitely. SDK also checks every input since.
            while True:
                indexed = self.rpc("get_indexer_tip", [])
                if indexed and number(indexed["block_number"]) >= number(tip["number"]):
                    break
                time.sleep(1)
            self.record(
                "maturity-indexed", tenant=tenant["label"], tip=tip, indexed=indexed
            )
        self.phase_deadlines[(tenant["label"], "work")] = time.monotonic() + 180

    def status(self, tenant):
        status = self.rpc(
            "get_watchtower_signing_status",
            [{"channel_id": tenant["channel_id"]}],
            tenant["client"],
        )["status"]
        if status["type"] == "SignatureRequired":
            self.requests_seen[status["request_id"]] = copy.deepcopy(status)
        return status

    def current(self, tenant, signature=False):
        due = self.phase_deadlines[(tenant["label"], "work")]
        with self.budget(due - time.monotonic()):
            while True:
                status = self.status(tenant)
                if not signature:
                    for audit in tenant["gate"].audit_snapshot()["requests"]:
                        if (
                            audit["method"] == "submit_watchtower_signature"
                            and (audit.get("reply") or {}).get("result", {}).get("type")
                            == "Applied"
                        ):
                            tenant.setdefault(
                                "settlement_due", self.first_work_time(tenant) + 240
                            )
                            return status, copy.deepcopy(audit["params"])
                if status["type"] == "SignatureRequired":
                    tx = status["content"]["transaction"]
                    assert status["content"]["key_purpose"] == {
                        "type": "Settlement"
                    }, status
                    live = self.rpc(
                        "get_live_cell", [tx["inputs"][0]["previous_output"], True]
                    )
                    if live["status"] == "live":
                        submissions = tenant["gate"].watchtower_submissions
                        if not signature or status["request_id"] in submissions:
                            checked = self.inspect(tx)
                            assert checked["request_id"] == status["request_id"]
                            tenant.setdefault(
                                "settlement_due", self.first_work_time(tenant) + 240
                            )
                            return status, copy.deepcopy(
                                submissions.get(status["request_id"])
                            )
                time.sleep(1)

    def first_work_time(self, tenant):
        times = []
        for connection in tenant["subscription_proxy"].connections():
            for at, _, event in connection.delivered_frames():
                if (
                    event.get("type") == "watchtower_signing"
                    and event["data"]["channel_id"] == tenant["channel_id"]
                    and event["data"]["status"]["type"] == "SignatureRequired"
                ):
                    times.append(at)
        for audit in tenant["gate"].audit_snapshot()["requests"]:
            if (
                audit["method"] == "get_watchtower_signing_status"
                and (audit.get("reply") or {})
                .get("result", {})
                .get("status", {})
                .get("type")
                == "SignatureRequired"
            ):
                times.append(audit["received_at"])
        return min(times) if times else time.monotonic()

    def ledger(self, tenant):
        point = {"tx_hash": tenant["commitment"]["hash"], "index": "0x0"}
        source = tenant["source"]
        initial = raw(source["witness"])
        rows = []
        sides = []
        expected_body = initial
        while len(rows) < 2:
            tx = self.spend(point)
            if not tx:
                break
            assert tx["cell_deps"] == tenant["deps"]["settlement_deps"]
            parent = self.transaction(point["tx_hash"])["outputs"][0]
            c = number(parent["capacity"])
            w = raw(tx["witnesses"][0])
            assert w[:17] == bytes([16, 0, 0, 0] * 4 + [1]) and w[17] == 0
            body = w[17:90]
            assert (
                body == expected_body
            ), "entire settlement state must follow previous witness"
            assert digest(body)[:20] == raw(parent["lock"]["args"])[36:56]
            side = w[90] - 254
            assert side in (0, 1) and side not in sides and w[91] == 0
            offset = 1 + 36 * side
            assert body[offset : offset + 36] == initial[offset : offset + 36]
            assert body[offset : offset + 20] != bytes(20)
            next_body = bytearray(body)
            next_body[offset : offset + 36] = bytes(36)
            expected_body = bytes(next_body)
            sponsor = 0
            for i in tx["inputs"][1:]:
                prev = self.transaction(i["previous_output"]["tx_hash"])
                idx = number(i["previous_output"]["index"])
                cell = prev["outputs"][idx]
                assert (
                    cell["lock"] == self.destination
                    and cell["type"] is None
                    and prev["outputs_data"][idx] == "0x"
                )
                sponsor += number(cell["capacity"])
            rem = 0
            dest = 0
            next_point = None
            for index, out in enumerate(tx["outputs"]):
                assert out["type"] is None and tx["outputs_data"][index] == "0x"
                if out["lock"] == self.destination:
                    dest += number(out["capacity"])
                else:
                    assert next_point is None and index == 0
                    expected = copy.deepcopy(parent["lock"])
                    args = raw(expected["args"])
                    expected["args"] = (
                        "0x"
                        + (
                            args[:36] + digest(next_body)[:20] + b"\x01" + args[57:]
                        ).hex()
                    )
                    assert out["lock"] == expected
                    rem = number(out["capacity"])
                    next_point = {"tx_hash": tx["hash"], "index": "0x0"}
            fee = c + sponsor - rem - dest
            assert 0 <= fee <= 10000
            payout = c - rem
            final = body[1 + 36 * (1 - side) : 1 + 36 * (1 - side) + 20] == bytes(20)
            assert (next_point is None) == final
            assert payout == (
                c
                if final
                else int.from_bytes(body[offset + 20 : offset + 36], "little")
            )
            is_a = side == int(source["reference"]["for_remote"])
            if is_a:
                matches = []
                for audit in tenant["gate"].audit_snapshot()["requests"]:
                    if (
                        audit["method"] != "submit_watchtower_signature"
                        or (audit.get("reply") or {}).get("result", {}).get("type")
                        != "Applied"
                    ):
                        continue
                    submission = audit["params"]
                    if raw(submission["signature"]) == w[92:157]:
                        matches.append(submission)
                assert matches, "A signature not actually Applied and used on chain"
                status = self.requests_seen.get(matches[0]["request_id"])
                if status is None:
                    for audit in tenant["gate"].audit_snapshot()["requests"]:
                        candidate = (
                            (audit.get("reply") or {})
                            .get("result", {})
                            .get("status", {})
                        )
                        if candidate.get("request_id") == matches[0]["request_id"]:
                            status = candidate
                assert status, "missing exact original signing request"
                checked = self.inspect(
                    status["content"]["transaction"], matches[0]["signature"]
                )
                assert checked["request_id"] == matches[0]["request_id"]
                assert checked["recovered_key"] == source["local_key"]
                authorizations = [
                    json.loads(line)
                    for line in tenant["status_file"]
                    .with_name("independent-chain.jsonl")
                    .read_text()
                    .splitlines()
                ]
                authorizations = [
                    a
                    for a in authorizations
                    if a.get("request_id") == matches[0]["request_id"]
                    and "authorization" in a
                ]
                assert authorizations and all(
                    a["authorization"]["fee"] == fee for a in authorizations
                )
                assert {
                    k: v
                    for k, v in status["content"]["transaction"].items()
                    if k != "witnesses"
                } == {k: v for k, v in tx.items() if k not in ("witnesses", "hash")}
            rows.append(
                {
                    "tx_hash": tx["hash"],
                    "side": side,
                    "a": is_a,
                    "C": c,
                    "S": sponsor,
                    "R": rem,
                    "D": dest,
                    "F": fee,
                    "P": payout,
                }
            )
            sides.append(side)
            if next_point is None:
                break
            point = next_point
        self.record("ledger", tenant=tenant["label"], rows=rows)
        if len(rows) == 2:
            c0 = number(tenant["commitment"]["outputs"][0]["capacity"])
            assert sum(r["P"] for r in rows) == c0
            assert (
                sum(r["D"] - r["S"] + r["F"] for r in rows) + tenant["close_fee"]
                == tenant["funding_capacity"]
            )
        return rows

    def finish(self, tenant):
        with self.budget(tenant["settlement_due"] - time.monotonic()):
            while len(rows := self.ledger(tenant)) != 2:
                self.status(tenant)
                time.sleep(1)
        with self.budget(75):
            tip = self.rpc("get_tip_header", [])
            while number(self.rpc("get_indexer_tip", [])["block_number"]) < number(
                tip["number"]
            ):
                time.sleep(1)
            start = time.monotonic()
            previous, max_gap, samples = start, 0.0, 0
            while True:
                sample_start = time.monotonic()
                with self.budget(2):
                    assert self.ledger(tenant) == rows
                sampled = time.monotonic()
                max_gap = max(max_gap, sampled - previous)
                assert max_gap <= 2, f"stability sampling gap {max_gap:.3f}s"
                previous, samples = sampled, samples + 1
                if sampled - start >= 65:
                    break
                time.sleep(max(0, sample_start + 1 - time.monotonic()))
        self.record(
            "complete",
            tenant=tenant["label"],
            rows=rows,
            stable_seconds=time.monotonic() - start,
            max_sample_gap=max_gap,
            samples=samples,
        )

    def isolation(self, write):
        for attempt in range(3):
            status, submission = self.current(self.a, signature=True)
            cross_due = self.phase_deadlines.setdefault(
                ("A", "cross"), time.monotonic() + 30
            )
            with self.budget(cross_due - time.monotonic()):
                args = {"channel_id": self.a["channel_id"]}
                response = self.rpc(
                    (
                        "submit_watchtower_signature"
                        if write
                        else "get_watchtower_signing_status"
                    ),
                    [submission if write else args],
                    self.b["client"],
                    error=True,
                )
                assert status["request_id"] not in json.dumps(response)
                after = self.status(self.a)
                live = self.rpc(
                    "get_live_cell",
                    [
                        status["content"]["transaction"]["inputs"][0][
                            "previous_output"
                        ],
                        True,
                    ],
                )
                if live["status"] != "live":
                    self.record("isolation_scene_lost", attempt=attempt)
                    continue
                assert after == status
                # Route owner's real submission through its audit gate, with hold released.
                self.a["gate"].hold_watchtower = False
                original = self.a["client"].url
                self.a["client"].url = self.a["gate"].url
                try:
                    reply = self.rpc(
                        "submit_watchtower_signature", [submission], self.a["client"]
                    )
                finally:
                    self.a["client"].url = original
                assert reply == {"type": "Applied"}, reply
                self.a["settlement_due"] = time.monotonic() + 240
                return
        raise AssertionError(
            "valid isolation checkpoint not obtained in three attempts"
        )


class TestWatchtowerSettlement(_WatchtowerBase):
    # Historical D=S oracle only; new independent-payout 01 awaits a product fix.
    def test_authorized_settlement(self):
        """
        1. 预先批准真实地址与费用。
        2. T 强关并等待成熟工作。
        3. 核对双方资金与稳定窗口。
        """
        # 1. 预先批准真实地址与费用。
        self.approve(self.a)
        # 2. T 强关并等待成熟工作。
        self.close_and_mature(self.a)
        self.current(self.a)
        # 3. 核对双方资金与稳定窗口。
        self.finish(self.a)

    # TEST-MAP: LSP-WATCHTOWER-02
    def test_missing_approval_then_adapted_settlement(self):
        """
        1. 未授权时取得原 Agent 拒签。
        2. 观察 130 秒无 A 结算。
        3. 明确批准后适配结算，不声称原事件链恢复。
        """
        # 1. 未授权时取得原 Agent 拒签。
        assert not (
            self.a["status_file"].parent / "store/watchtower-approvals.json"
        ).exists()
        self.close_and_mature(self.a)
        self.current(self.a)
        with self.budget(
            self.phase_deadlines[(self.a["label"], "work")] - time.monotonic()
        ):
            while True:
                events = [
                    json.loads(line.split("watchtower-event: ", 1)[1])
                    for line in self.a["status_file"]
                    .with_name("agent.log")
                    .read_text()
                    .splitlines()
                    if "watchtower-event: " in line
                ]
                refused = [
                    e
                    for e in events
                    if e["error"] == "watchtower request requires local authorization"
                    and not e["adapted"]
                    and e["event"]["data"]["channel_id"] == self.a["channel_id"]
                ]
                if refused:
                    current = self.status(self.a)
                    if any(e["event"]["data"]["status"] == current for e in refused):
                        assert (
                            self.rpc(
                                "get_live_cell",
                                [
                                    current["content"]["transaction"]["inputs"][0][
                                        "previous_output"
                                    ],
                                    True,
                                ],
                            )["status"]
                            == "live"
                        )
                        self.record("original_agent_refusal", event=refused[-1])
                        break
                time.sleep(1)
        # 2. 观察 130 秒无 A 结算。
        store_snapshot = self.a["status_file"].parent / "store/snapshot.bin"
        snapshot_before = hashlib.sha256(store_snapshot.read_bytes()).hexdigest()
        with self.budget(140):
            start = time.monotonic()
            previous, max_gap, samples = start, 0.0, 0
            while True:
                sample_start = time.monotonic()
                with self.budget(2):
                    assert not self.a["gate"].watchtower_submissions
                    assert (
                        hashlib.sha256(store_snapshot.read_bytes()).hexdigest()
                        == snapshot_before
                    )
                    assert not any(r["a"] for r in self.ledger(self.a))
                sampled = time.monotonic()
                max_gap = max(max_gap, sampled - previous)
                assert max_gap <= 2, f"negative sampling gap {max_gap:.3f}s"
                previous, samples = sampled, samples + 1
                if sampled - start >= 130:
                    break
                time.sleep(max(0, sample_start + 1 - time.monotonic()))
            self.record(
                "unapproved-observation",
                samples=samples,
                seconds=sampled - start,
                max_sample_gap=max_gap,
            )
            end = self.status(self.a)
            assert end["type"] == "SignatureRequired"
            assert (
                self.rpc(
                    "get_live_cell",
                    [
                        end["content"]["transaction"]["inputs"][0]["previous_output"],
                        True,
                    ],
                )["status"]
                == "live"
            )
        # 3. 明确批准后适配结算，不声称原事件链恢复。
        self.approve(self.a)
        self.a["settlement_due"] = time.monotonic() + 240
        self.control(self.a, "watchtower-process")
        self.finish(self.a)

    # TEST-MAP: LSP-WATCHTOWER-03
    def test_cross_tenant_read(self):
        """
        1. 验证 B 自身读权限并扣留 A 真实签名。
        2. B 读取 A 被拒。
        3. A 正向结算并验证资金。
        """
        # 1. 验证 B 自身读权限并扣留 A 真实签名。
        self.status(self.b)
        self.approve(self.a)
        self.a["gate"].hold_watchtower = True
        self.close_and_mature(self.a)
        # 2. B 读取 A 被拒。
        self.isolation(False)
        # 3. A 正向结算并验证资金。
        self.finish(self.a)
        self.status(self.b)

    # TEST-MAP: LSP-WATCHTOWER-04
    def test_cross_tenant_submit(self):
        """
        1. B 自身完成真实签名结算。
        2. B 提交 A 有效签名被拒。
        3. A 用原签名完成并验证资金。
        """
        # 1. B 自身完成真实签名结算。
        self.approve(self.b)
        self.close_and_mature(self.b)
        self.current(self.b)
        self.finish(self.b)
        # 2. B 提交 A 有效签名被拒。
        self.approve(self.a)
        self.a["gate"].hold_watchtower = True
        self.close_and_mature(self.a)
        self.isolation(True)
        # 3. A 用原签名完成并验证资金。
        self.finish(self.a)
        assert len(self.ledger(self.b)) == 2


class TestWatchtowerAdapter(_WatchtowerBase):
    """Unmapped adapter checks; never reported as product scenario passes."""

    agent_extra_args = ("--ack-held-events", "--watchtower-check-only")

    def test_adapter_rejects_invalid_authorization(self):
        for fault, expected in [
            ("canonical", "non-canonical"),
            ("transaction_hash", "hash mismatch"),
            ("contract_bytes", "bytes differ"),
        ]:
            self.chain_audit.fault = fault
            try:
                result = self.control(
                    self.a,
                    "watchtower-configure",
                    {
                        "config": {
                            **self.chain_config,
                            "audit": str(
                                self.a["status_file"].with_name("negative-chain.jsonl")
                            ),
                        }
                    },
                    error=True,
                )
                assert expected in result["error"], result
            finally:
                self.chain_audit.fault = None
        self.approve(self.a)
        self.close_and_mature(self.a)
        self.current(self.a)
        result = self.control(self.a, "watchtower-check")
        assert len(result["checks"]) == 11, result
        # A real persisted approval with an insufficient cap must fail closed.
        self.control(
            self.a,
            "watchtower-authorize",
            {"destination": self.destination, "max_fee": 1},
        )
        refused = self.control(self.a, "watchtower-check", error=True)
        assert "fee exceeds local cap" in refused["error"]
        self.approve(self.a)
        assert not self.a["gate"].watchtower_submissions


class TestWatchtowerDestinationRejection(_WatchtowerBase):
    """84333ee: one real candidate, original SDK validation, no signing path."""

    tenant_labels = ("A",)
    agent_extra_args = ("--ack-held-events", "--watchtower-diagnostic-only")

    def assert_operator_payout_candidate(self, status):
        """Independently bind the wrong payout to A's still-unsettled share."""
        assert status["type"] == "SignatureRequired"
        assert status["content"]["key_purpose"] == {"type": "Settlement"}
        tx = status["content"]["transaction"]
        assert self.inspect(tx)["request_id"] == status["request_id"]
        rows = self.ledger(self.a)
        assert not any(row["a"] for row in rows), rows
        point = {
            "tx_hash": rows[-1]["tx_hash"] if rows else self.a["commitment"]["hash"],
            "index": "0x0",
        }
        assert tx["inputs"][0]["previous_output"] == point
        parent = self.transaction(point["tx_hash"])["outputs"][0]
        body = bytearray(raw(self.a["source"]["witness"]))
        for row in rows:
            offset = 1 + 36 * row["side"]
            body[offset:offset + 36] = bytes(36)
        witness = raw(tx["witnesses"][0])
        assert witness[:17] == bytes([16, 0, 0, 0] * 4 + [1])
        assert witness[17:90] == bytes(body)
        side = witness[90] - 254
        assert side == int(self.a["source"]["reference"]["for_remote"])
        assert witness[91] == 0
        assert digest(body)[:20] == raw(parent["lock"]["args"])[36:56]
        offset = 1 + 36 * side
        assert body[offset:offset + 20] != bytes(20)
        final = body[1 + 36 * (1-side):1 + 36 * (1-side) + 20] == bytes(20)
        capacity = number(parent["capacity"])
        entitled = capacity if final else int.from_bytes(body[offset+20:offset+36], "little")
        assert entitled > 0
        body[offset:offset + 36] = bytes(36)
        expected_remainder = copy.deepcopy(parent["lock"])
        args = raw(expected_remainder["args"])
        expected_remainder["args"] = "0x" + (
            args[:36] + digest(body)[:20] + b"\x01" + args[57:]
        ).hex()
        remainder, sponsor_output, remainder_count = 0, 0, 0
        for index, output in enumerate(tx["outputs"]):
            assert output["type"] is None and tx["outputs_data"][index] == "0x"
            assert output["lock"] != self.a["shutdown_script"], "candidate already pays A"
            if output["lock"] == self.destination:
                sponsor_output += number(output["capacity"])
            else:
                assert not final and index == 0 and output["lock"] == expected_remainder
                remainder_count += 1
                remainder += number(output["capacity"])
        assert remainder_count == (0 if final else 1)
        assert remainder == capacity - entitled
        assert sponsor_output > 0
        sponsor_input, seen = 0, {json.dumps(point, sort_keys=True)}
        for value in tx["inputs"][1:]:
            outpoint = value["previous_output"]
            key = json.dumps(outpoint, sort_keys=True)
            assert key not in seen
            seen.add(key)
            live = self.rpc("get_live_cell", [outpoint, True])
            assert live["status"] == "live", "candidate sponsor no longer live"
            cell = live["cell"]
            assert cell["output"]["lock"] == self.destination
            assert cell["output"]["type"] is None and cell["data"]["content"] == "0x"
            sponsor_input += number(cell["output"]["capacity"])
        assert tx["cell_deps"] == self.a["deps"]["settlement_deps"]
        fee = capacity + sponsor_input - remainder - sponsor_output
        assert 0 <= fee <= 10000
        self.record(
            "operator-payout-candidate", request=status, input=point,
            A_entitled=entitled, A_output=0, sponsor_input=sponsor_input,
            sponsor_output=sponsor_output, remainder=remainder, fee=fee,
        )
        return fee

    # TEST-MAP: LSP-WATCHTOWER-05
    def test_independent_destination_rejects_operator_payout(self):
        """
        1. 固定A独立退出地址和T赞助地址，持久化原SDK批准。
        2. T真实强关成熟，核对错付候选并取得原SDK只验证拒绝。
        3. 连续65秒核对零签名提交及A份额未解锁，保留拒绝层级。
        """
        # 1. 固定A独立退出地址和T赞助地址，持久化原SDK批准。
        assert REVISION == "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"
        destination = self.a["shutdown_script"]
        wallet = self.Ckb_cli.util_key_info_by_private_key(self.a["private_key"])
        assert destination["args"] == wallet["lock_arg"]
        assert destination != self.destination
        policy_path = self.a["status_file"].parent / "store/watchtower-approvals.json"
        self.control(self.a, "watchtower-authorize", {"destination": destination, "max_fee": 10000})
        policy = json.loads(policy_path.read_text())[self.a["channel_id"]]
        assert policy == {"destination": destination, "max_fee": 10000}
        self.record("independent-payout-intent", destination=destination,
                    sponsor=self.destination, policy=policy)

        # 2. T真实强关成熟，核对错付候选并取得原SDK只验证拒绝。
        self.close_and_mature(self.a)
        self.current(self.a)
        with self.budget(self.phase_deadlines[(self.a["label"], "work")] - time.monotonic()):
            seen = set()
            while True:
                assert len(seen) < 3, "three-work diagnostic limit"
                result = self.control(self.a, "watchtower-diagnose", {"sponsor": self.destination})
                request_id = result.get("request_id")
                assert request_id and request_id not in seen, "same invalid work repeated"
                seen.add(request_id)
                assert len(seen) <= 3, "three-work diagnostic limit"
                if result.get("checkpoint_invalid"):
                    assert result["sdk_called"] is False
                    self.record("diagnostic-checkpoint-invalid", result=result)
                    self.current(self.a)
                    continue
                assert result["sdk_called"] is True, result
                assert result["prepared"] is False, result
                assert result["rejection_layer"] in ("sdk_sponsor", "sdk_output_destination"), result
                assert result["snapshot_unchanged"] and result["approval_unchanged"], result
                assert result["snapshot_before_hash"] == result["snapshot_after_hash"], result
                assert result["check_only"] and not result["can_sign"] and not result["can_submit"]
                assert all(result["checks"].values()), result
                status = result["request"]
                live = self.rpc("get_live_cell", [status["content"]["transaction"]["inputs"][0]["previous_output"], True])
                if live["status"] != "live":
                    self.record("diagnostic-checkpoint-consumed", result=result, live=live)
                    self.current(self.a)
                    continue
                fee = self.assert_operator_payout_candidate(status)
                assert result["authorization_destination_rpc"] == destination
                assert number(result["authorization"]["fee"]) == fee
                assert json.loads(policy_path.read_text())[self.a["channel_id"]] == policy
                self.record("independent-payout-rejected", result=result)
                break

        # 3. 连续65秒核对零签名提交及A份额未解锁，保留拒绝层级。
        assert self.total_due - time.monotonic() >= 75, "insufficient full observation budget"
        store_snapshot = self.a["status_file"].parent / "store/snapshot.bin"
        snapshot_before = hashlib.sha256(store_snapshot.read_bytes()).hexdigest()
        with self.budget(75):
            start = previous = time.monotonic()
            samples, max_gap = 0, 0.0
            while True:
                sample_start = time.monotonic()
                with self.budget(2):
                    assert not self.a["gate"].watchtower_submissions
                    assert hashlib.sha256(store_snapshot.read_bytes()).hexdigest() == snapshot_before
                    assert not any(
                        row["method"] == "submit_watchtower_signature"
                        for row in self.a["gate"].audit_snapshot()["requests"]
                    )
                    assert not any(row["a"] for row in self.ledger(self.a))
                    assert json.loads(policy_path.read_text())[self.a["channel_id"]] == policy
                sampled = time.monotonic()
                max_gap = max(max_gap, sampled - previous)
                assert max_gap <= 2, f"negative sampling gap {max_gap:.3f}s"
                previous, samples = sampled, samples + 1
                if sampled - start >= 65:
                    break
                time.sleep(max(0, sample_start + 1 - time.monotonic()))
            self.record("independent-payout-observation", seconds=sampled-start,
                        samples=samples, max_sample_gap=max_gap,
                        rejection_layer=result["rejection_layer"],
                        snapshot_sha256=snapshot_before,
                        error=result["error"], independent_payout_verified=False)

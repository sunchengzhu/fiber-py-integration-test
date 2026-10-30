"""04c2064: one real A -> T hold payment, VM controlled-time on-chain timeout refund."""

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import time

import pytest
import requests
import yaml

from test_cases.fiber.devnet.lsp._lsp_test import ChannelSigningTestBase, REVISION
from test_cases.fiber.devnet.lsp_nightly._refund_ledger import RefundLedger
from test_cases.fiber.devnet.lsp_nightly._vm_time import GuestClock
from test_cases.fiber.devnet.lsp._watchtower_rpc import ChainAudit
from test_cases.fiber.devnet.lsp.test_watchtower_settlement import (
    _WatchtowerBase,
    number,
    raw,
)


class _RefundBase(RefundLedger, _WatchtowerBase):
    tenant_labels = ("A",)
    amount = 100_000_000

    @classmethod
    def setup_class(cls):
        # Reject accidental host/daily execution before the inherited CKB setup.
        cls.vm_clock = GuestClock(os.environ["LSP_RUN_ARTIFACTS"])
        expected = "preflight" if cls.__name__ == "TestTlcRefundAdapter" else "formal"
        assert cls.vm_clock.identity["mode"] == expected
        cls.total_due = min(
            cls.vm_clock.identity["guest_deadline_mono"] - 60,
            cls.vm_clock.identity["guest_started_mono"] + 300,
        )
        try:
            super().setup_class()
        except BaseException:
            cls.vm_clock.close()
            raise

    @classmethod
    def teardown_class(cls):
        try:
            super().teardown_class()
        finally:
            cls.vm_clock.close()

    def setup_method(self, method):
        self.started = self.vm_clock.identity["guest_started_mono"]
        self.prep_due = min(self.started + 600, time.monotonic() + 300)
        self.cleanup_due = min(
            self.started + 2160, self.vm_clock.identity["guest_deadline_mono"]
        )
        self.total_due = self.cleanup_due - 60
        self.evidence, self.requests_seen, self.phase_deadlines = [], {}, {}
        self.transaction_cache, self.inspection_cache = {}, {}
        self.sample_headers = {}
        self.observing = False
        self.payment_hash = "0x" + hashlib.sha256(os.urandom(32)).hexdigest()
        # This endpoint only receives FNN traffic. Python and the SDK use other URLs.
        audit_path = Path(os.environ["LSP_RUN_ARTIFACTS"]) / (
            method.__name__ + "-fnn-ckb.jsonl"
        )
        assert not audit_path.exists(), audit_path
        self.fnn_chain_audit = ChainAudit(
            self.node.rpcUrl, audit_path, role="fnn", transparent=True
        )
        self.addCleanup(self.fnn_chain_audit.close)
        self.start_fiber_config = {
            **type(self).start_fiber_config,
            "ckb_rpc_url": self.fnn_chain_audit.url,
        }
        with self.budget(self.prep_due - time.monotonic()):
            ChannelSigningTestBase.setup_method(self, method)

    def setUp(self):
        with self.budget(self.prep_due - time.monotonic()):
            ChannelSigningTestBase.setUp(self)
            self.a = self.tenant
            self.gate.release()
            self._submit(self.gate.submission)
            self._finish_opening()
            self.a["baseline"] = self._channel(self.client)
            self.t_baseline = self._channel(self.fiber1.client)
            assert not self.a["baseline"]["pending_tlcs"]
            assert not self.t_baseline["pending_tlcs"]
            point = raw(self.a["baseline"]["channel_outpoint"])
            self.a["funding"] = {
                "tx_hash": "0x" + point[:32].hex(),
                "index": hex(int.from_bytes(point[32:], "little")),
            }
            assert (
                self.t_baseline["channel_outpoint"]
                == self.a["baseline"]["channel_outpoint"]
            )
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
            self.chain_audit = ChainAudit(
                self.node.rpcUrl, Path(self.fiber1.tmp_path) / "ckb-verifier.jsonl"
            )
            self.addCleanup(self.chain_audit.close)
            self.chain_config = {
                "url": self.chain_audit.url,
                "scripts": {s["name"]: s for s in config["fiber"]["scripts"]},
                "contracts": str(Path("source/contract/fiber").resolve()),
                "single_tlc": {
                    "payment_hash": self.payment_hash,
                    "amount": str(self.amount),
                },
            }
            self.a["deps"] = self.control(
                self.a,
                "watchtower-configure",
                {
                    "config": {
                        **self.chain_config,
                        "audit": str(
                            self.a["status_file"].with_name("independent-chain.jsonl")
                        ),
                    }
                },
            )
            sponsors = self.rpc(
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
            assert len(sponsors) < 100, "sponsor page incomplete"
            plain = [
                c
                for c in sponsors
                if c["output"]["type"] is None and c["output_data"] == "0x"
            ]
            assert (
                sum(number(c["output"]["capacity"]) for c in plain)
                >= 1000 * 100_000_000
            )
            self.approve(self.a)
            self.record(
                "prepared-refund",
                revision=REVISION,
                baseline=self.a["baseline"],
                public_baseline=self.t_baseline,
                destination=self.destination,
                sponsors=plain,
            )

    def _request(self, method, params, client=None, timeout=2):
        target = client or self.node.getClient()
        url = getattr(target, "url", None) or self.node.rpcUrl
        started = time.monotonic()
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                url,
                headers=getattr(target, "other_params", {}),
                json={"id": 1, "jsonrpc": "2.0", "method": method, "params": params},
                timeout=timeout,
            )
            response.raise_for_status()
            reply = response.json()
        finished = time.monotonic()
        assert finished - started <= timeout, (method, finished - started)
        assert "error" not in reply and "result" in reply, (method, reply)
        return {
            "method": method,
            "params": params,
            "reply": reply,
            "started": started,
            "finished": finished,
        }

    def rpc(self, method, params, client=None, error=False):
        if not self.observing or error:
            return super().rpc(method, params, client, error)
        row = self._request(method, params, client)
        self.record("observation-rpc", **row)
        return row["reply"]["result"]

    def inspect(self, tx, signature=None):
        # Pure byte/hash/signature computation is immutable; chain facts are not cached.
        key = (json.dumps(tx, sort_keys=True), signature)
        if key not in self.inspection_cache:
            self.inspection_cache[key] = super().inspect(tx, signature)
        return self.inspection_cache[key]

    def transaction(self, txhash):
        if txhash not in self.transaction_cache:
            tx = super().transaction(txhash)
            if tx is None:
                return None
            status = self.rpc("get_transaction", [txhash])["tx_status"]
            header = self.rpc("get_header", [status["block_hash"]])
            self.transaction_cache[txhash] = (tx, header)
        tx, header = self.transaction_cache[txhash]
        # Every sample rechecks each containing block against the current canonical chain.
        if not self.observing or header["number"] not in self.sample_headers:
            self.sample_headers[header["number"]] = self.rpc(
                "get_header_by_number", [header["number"]]
            )
        assert (
            self.sample_headers[header["number"]]["hash"] == header["hash"]
        ), "canonical history changed"
        return tx

    def _sample(self):
        started = time.monotonic()
        self.sample_headers = {}
        self.observing = True
        try:
            with self.budget(3):
                queries = {
                    "tip": ("get_tip_header", [], None),
                    "indexed": ("get_indexer_tip", [], None),
                    "A": ("list_channels", [{"include_closed": True}], self.client),
                    "T": (
                        "list_channels",
                        [{"include_closed": True}],
                        self.fiber1.client,
                    ),
                    "payment": (
                        "get_payment",
                        [{"payment_hash": self.payment_hash}],
                        self.client,
                    ),
                    "invoice": (
                        "get_invoice",
                        [{"payment_hash": self.payment_hash}],
                        self.fiber1.client,
                    ),
                    "signing": (
                        "get_channel_signing_status",
                        [{"channel_id": self.channel_id}],
                        self.client,
                    ),
                    "watchtower": (
                        "get_watchtower_signing_status",
                        [{"channel_id": self.channel_id}],
                        self.client,
                    ),
                }
                with ThreadPoolExecutor(max_workers=len(queries)) as pool:
                    pending = {
                        key: pool.submit(self._request, *args)
                        for key, args in queries.items()
                    }
                    responses = {
                        key: future.result(timeout=3) for key, future in pending.items()
                    }
                sample = {key: row["reply"]["result"] for key, row in responses.items()}
                sample["median"] = self.rpc(
                    "get_block_median_time", [sample["tip"]["hash"]]
                )
                canonical = self.rpc("get_header_by_number", [sample["tip"]["number"]])
                assert canonical["hash"] == sample["tip"]["hash"]
                for side in ("A", "T"):
                    channels = sample[side]["channels"]
                    assert (
                        len(channels) == 1
                        and channels[0]["channel_id"] == self.channel_id
                    ), channels
                    sample[side] = channels[0]
                    assert (
                        channels[0]["channel_outpoint"]
                        == self.a["baseline"]["channel_outpoint"]
                    )
                    tlcs = channels[0]["pending_tlcs"]
                    assert len(tlcs) <= 1, "second established TLC"
                    for tlc in tlcs:
                        assert (
                            tlc["payment_hash"] == self.payment_hash
                            and number(tlc["amount"]) == self.amount
                        )
                        assert (
                            tlc["forwarding_channel_id"] is None
                            and tlc["forwarding_tlc_id"] is None
                        )
                        if hasattr(self, "tlc_ids"):
                            assert tlc["id"] == self.tlc_ids[side]
                work = sample["watchtower"]["status"]
                if work["type"] == "SignatureRequired":
                    self.requests_seen[work["request_id"]] = copy.deepcopy(work)
                sample["ledger"] = (
                    self.refund_ledger() if "commitment" in self.a else None
                )
                finished = time.monotonic()
                assert finished - started <= 3
                self.vm_clock.check()
                assert self.a["agent"].poll() is None
                assert all(f.process.poll() is None for f in self.fibers)
                os.kill(int(self.node.ckb_miner_pid), 0)
                assert not self.gate.errors and not self.subscription_proxy.errors
                height = number(sample["tip"]["number"])
                if height > getattr(self, "last_height", -1):
                    self.last_height, self.height_advanced = height, finished
                assert (
                    finished - self.height_advanced < 30
                ), "no chain height growth in rolling 30s"
                assert sample["payment"]["payment_hash"] == self.payment_hash
                assert (
                    sample["payment"]["status"] != "Success"
                    and sample["payment"]["payment_preimage"] is None
                )
                assert sample["invoice"]["status"] != "Paid"
                self.record(
                    "sample",
                    started=started,
                    finished=finished,
                    responses=responses,
                    sample=sample,
                )
                return sample
        finally:
            self.observing = False

    def _wait(self, due, predicate):
        with self.budget(due - time.monotonic()):
            while True:
                start = time.monotonic()
                sample = self._sample()
                if predicate(sample):
                    return sample
                time.sleep(max(0, start + 1 - time.monotonic()))

    def send_hold_payment(self):
        with self.budget(self.prep_due - time.monotonic()):
            invoice = self.rpc(
                "new_invoice",
                [
                    {
                        "amount": hex(self.amount),
                        "currency": "Fibd",
                        "payment_hash": self.payment_hash,
                        "hash_algorithm": "sha256",
                        "allow_mpp": False,
                        "expiry": hex(21600),
                        "final_expiry_delta": hex(300_000),
                    }
                ],
                self.fiber1.client,
            )
            parsed = self.rpc(
                "parse_invoice",
                [{"invoice": invoice["invoice_address"]}],
                self.fiber1.client,
            )["invoice"]
            assert parsed == invoice["invoice"]
            assert (
                parsed["currency"] == "Fibd" and number(parsed["amount"]) == self.amount
            )
            assert parsed["data"]["payment_hash"] == self.payment_hash
            attrs = {
                key: value
                for attr in parsed["data"]["attrs"]
                for key, value in attr.items()
            }
            assert attrs["payee_public_key"].removeprefix(
                "0x"
            ) == self.public_key.removeprefix("0x")
            assert attrs["hash_algorithm"] == "sha256" and "udt_script" not in attrs
            assert number(attrs["expiry_time"]) == 21600
            assert number(attrs["final_htlc_minimum_expiry_delta"]) == 300_000
            assert not any(
                "mpp" in feature.lower() for feature in attrs.get("feature", [])
            )
            now = int(time.time() * 1000)
            self.authorization = {
                "payment_hash": self.payment_hash,
                "hash_algorithm": "sha256",
                "inbound": False,
                "amount": self.amount,
                "expires_at_ms": now + 120_000,
                "min_tlc_expiry_delta_ms": 14_580_000,
                "max_tlc_expiry_ms": now + 14_820_000,
            }
            assert self.control(
                self.a, "outgoing-payment", {"authorization": self.authorization}
            ) == {"saved": True}
            invoice_created = number(parsed["data"]["timestamp"])
            assert now + 14_820_000 + 5000 + 1_500_000 < invoice_created + 21_600_000
            self.send_mono, self.send_wall = time.monotonic(), time.time()
            assert self.send_wall * 1000 - now <= 10_000
            self.total_due = min(self.total_due, self.send_mono + 1500)
            result = self.rpc(
                "send_payment",
                [
                    {
                        "invoice": invoice["invoice_address"],
                        "final_tlc_expiry_delta": hex(300_000),
                        "tlc_expiry_limit": hex(14_700_000),
                        "timeout": hex(21600),
                        "max_fee_amount": hex(0),
                        "max_parts": hex(1),
                        "keysend": False,
                        "allow_self_payment": False,
                    }
                ],
                self.client,
            )
            assert result["payment_hash"] == self.payment_hash
            self.record(
                "sole-send",
                authorization=self.authorization,
                result=result,
                send_mono=self.send_mono,
                send_wall=self.send_wall,
            )
        sample = self._wait(
            self.send_mono + 60,
            lambda s: s["payment"]["status"] == "Inflight"
            and s["invoice"]["status"] == "Received"
            and s["signing"]["status"]["type"] == "NoSignatureRequired"
            and all(
                len(s[side]["pending_tlcs"]) == 1
                and s[side]["pending_tlcs"][0]["status"] == {direction: "Committed"}
                for side, direction in (("A", "Outbound"), ("T", "Inbound"))
            ),
        )
        self.tlc_ids = {
            side: sample[side]["pending_tlcs"][0]["id"] for side in ("A", "T")
        }
        self.expiry_ms = number(sample["A"]["pending_tlcs"][0]["expiry"])
        assert self.expiry_ms == number(sample["T"]["pending_tlcs"][0]["expiry"])
        assert (
            self.send_wall * 1000 + 14_580_000
            <= self.expiry_ms
            <= self.authorization["max_tlc_expiry_ms"]
        )
        routes = sample["payment"]["routers"]
        # SessionRoute includes both payer and final receiver, even for one edge.
        assert len(routes) == 1 and len(routes[0]["nodes"]) == 2, routes
        hop = routes[0]["nodes"][0]
        assert hop["channel_outpoint"] == self.a["baseline"]["channel_outpoint"]
        assert (
            number(hop["amount"]) == self.amount
            and number(sample["payment"]["fee"]) == 0
        )
        receiver = routes[0]["nodes"][1]
        assert receiver["pubkey"].removeprefix("0x") == self.public_key.removeprefix(
            "0x"
        )
        assert number(receiver["amount"]) == self.amount
        assert raw(receiver["channel_outpoint"]) == bytes(36)
        with self.budget(self.send_mono + 60 - time.monotonic()):
            self.a["records"] = self.control(self.a, "watchtower-tlc-records")
            assert {r["reference"]["for_remote"] for r in self.a["records"]} == {
                False,
                True,
            }
            assert any(
                r["complete"] and not r["reference"]["for_remote"]
                for r in self.a["records"]
            )
        self.record("complete-ack-checkpoint", sample=sample, records=self.a["records"])
        self.assert_single_tlc_history()
        audits = self.gate.audit_snapshot()["requests"]
        applied = {
            r["params"]["request_id"]
            for r in audits
            if r["method"] == "submit_channel_signature"
            and (r.get("reply") or {}).get("result", {}).get("type") == "Applied"
            and r["received_at"] >= self.send_mono
        }
        statuses = [
            (r.get("reply") or {}).get("result", {}).get("status", {})
            for r in audits
            if r["method"] == "get_channel_signing_status"
        ]
        for connection in self.subscription_proxy.connections():
            statuses.extend(
                event["data"]["status"]
                for _, _, event in connection.delivered_frames()
                if event.get("type") == "channel_signing"
                and event["data"]["channel_id"] == self.channel_id
            )
        transitions = {
            status.get("transition")
            for status in statuses
            if status.get("request_id") in applied
        }
        assert {
            "SendRevokeAndAck",
            "CompleteReceivedRevokeAndAck",
        } <= transitions, transitions
        self.record("applied-ack-proof", request_ids=sorted(applied), statuses=statuses)
        self.checkpoint_at = time.monotonic()

    def assert_single_tlc_history(self):
        # Inspect all retained signing requests, including ones absent from final routers.
        seen = set()

        def visit(value):
            if isinstance(value, dict):
                if {
                    "tlc_id",
                    "local_key_commitment_number",
                    "payment_amount",
                    "payment_hash",
                } <= value.keys():
                    assert (
                        value["payment_hash"] == self.payment_hash
                        and value["inbound"] is False
                    ), value
                    assert number(value["payment_amount"]) == self.amount
                    assert number(value["tlc_id"]) == number(
                        self.tlc_ids["A"]
                    ), "second TLC in signing history"
                    seen.add(
                        (
                            number(value["tlc_id"]),
                            number(value["local_key_commitment_number"]),
                        )
                    )
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.gate.audit_snapshot()["requests"])
        for connection in self.subscription_proxy.connections():
            visit([event for _, _, event in connection.delivered_frames()])
        assert len(seen) == 1, ("expected one TLC creation identity", seen)
        self.record("single-tlc-history", identities=sorted(seen))

    def force_close(self):
        with self.budget(
            min(self.checkpoint_at + 60, self.send_mono + 120) - time.monotonic()
        ):
            self.rpc(
                "shutdown_channel",
                [{"channel_id": self.channel_id, "force": True}],
                self.fiber1.client,
            )
            while not (tx := self.spend(self.a["funding"])):
                time.sleep(1)
            assert (
                self.expiry_ms / 1000 - time.time() >= 120
            ), "insufficient pre-expiry close margin"
            self.verify_commitment(tx)
            status = self.rpc("get_transaction", [tx["hash"]])["tx_status"]
            self.commitment_header = self.rpc("get_header", [status["block_hash"]])
            self.close_confirmed_at = time.monotonic()

    def _window(self, predicate, name):
        previous = time.monotonic()
        start = None
        max_gap, count = 0, 0
        with self.budget(75):
            while True:
                tick = time.monotonic()
                sample = self._sample()
                predicate(sample)
                end = time.monotonic()
                max_gap = max(max_gap, end - previous)
                assert max_gap <= 5, (name, "sample gap", max_gap)
                previous, count = end, count + 1
                if start is None:
                    start = end
                if end - start >= 65:
                    break
                time.sleep(max(0, tick + 1 - time.monotonic()))
        self.record(name, started=start, finished=end, samples=count, max_gap=max_gap)
        return start, end

    def protect_immature(self):
        def protected(sample):
            assert number(sample["median"]) // 1000 <= self.expiry_ms // 1000
            assert sample["invoice"]["status"] == "Received"
            ledger = sample["ledger"]
            assert not ledger["complete"]
            assert all(row["kind"] == "T" for row in ledger["rows"]), ledger

        start, end = self._window(protected, "immature-window")
        self.assert_fnn_scan(start, end)

    def assert_fnn_scan(self, start, end):
        with self.fnn_chain_audit.lock:
            audit = [
                json.loads(line)
                for line in self.fnn_chain_audit.path.read_text().splitlines()
            ]
        audit = [row for row in audit if start <= row["started"] <= row["at"] <= end]
        assert all(
            row["role"] == "fnn" and row["selfcheck_fault"] is None for row in audit
        )
        lock = self.a["commitment"]["outputs"][0]["lock"]
        prefix = {**lock, "args": "0x" + raw(lock["args"])[:36].hex()}
        matches = []
        for tip_row in audit:
            if (
                tip_row["request"]["method"] != "get_tip_header"
                or "error" in tip_row["reply"]
            ):
                continue
            tip = tip_row["reply"]["result"]
            medians = [
                r
                for r in audit
                if r["request"]["method"] == "get_block_median_time"
                and r["request"]["params"] == [tip["hash"]]
                and r["started"] >= tip_row["at"]
                and "error" not in r["reply"]
                and r["reply"].get("result") is not None
                and number(r["reply"]["result"]) // 1000 <= self.expiry_ms // 1000
            ]
            if not medians:
                continue
            scans = [
                r
                for r in audit
                if r["request"]["method"] in ("get_cells", "get_transactions")
                and r["started"] >= medians[0]["at"]
                and "error" not in r["reply"]
                and r["request"]["params"][0].get("script") == prefix
                and r["request"]["params"][0].get("script_search_mode") == "prefix"
                and r["request"]["params"][0].get("script_type") == "lock"
                and r["request"]["params"][0].get("group_by_transaction") is True
                and [
                    number(v)
                    for v in r["request"]["params"][0]
                    .get("filter", {})
                    .get("block_range", [])
                ]
                == [number(self.commitment_header["number"]), number(tip["number"]) + 1]
            ]
            if {r["request"]["method"] for r in scans} == {
                "get_cells",
                "get_transactions",
            }:
                matches.append({"tip": tip_row, "median": medians[0], "scans": scans})
        assert matches, "no actual target FNN watchtower scan in immature window"
        self.record("fnn-scan-proof", matches=matches)

    def jump_guest_clock(self):
        self.record(
            "vm-jump-intent",
            expiry_ms=self.expiry_ms,
            instance=self.vm_clock.identity["instance"],
        )
        with self.budget(30):
            event = self.vm_clock.jump(
                self.expiry_ms, observe=self._sample, payment_hash=self.payment_hash
            )
        self.record("vm-jump-complete", event=event)

    def mature(self):
        epoch = number(self.commitment_header["epoch"])
        n, i, length = epoch & 0xFFFFFF, (epoch >> 24) & 0xFFFF, (epoch >> 40) & 0xFFFF
        assert length and i < length
        due = min(self.vm_clock.event["after_mono"] + 180, self.total_due)
        indexed_target = None

        def ready(sample):
            nonlocal indexed_target
            e = number(sample["tip"]["epoch"])
            tn, ti, tl = e & 0xFFFFFF, (e >> 24) & 0xFFFF, (e >> 40) & 0xFFFF
            assert tl and ti < tl
            mature = (
                number(sample["median"]) // 1000 > self.expiry_ms // 1000
                and (tn - n - 1) * tl * length + ti * length - i * tl >= 0
            )
            if mature and indexed_target is None:
                indexed_target = number(sample["tip"]["number"])
            return (
                mature
                and sample["indexed"] is not None
                and number(sample["indexed"]["block_number"]) >= indexed_target
            )

        sample = self._wait(due, ready)
        self.mature_at = time.monotonic()
        self.record("mature-indexed", sample=sample, work_due=self.mature_at + 480)

    def business_complete(self, sample):
        if sample["payment"]["status"] != "Failed":
            return False
        assert number(sample["payment"]["fee"]) == 0
        assert sample["invoice"]["status"] == "Received"
        for side, direction, removed in (
            ("A", "UNCOOPERATIVE_REMOTE", "RemoteRemoved"),
            ("T", "UNCOOPERATIVE_LOCAL", "LocalRemoved"),
        ):
            channel = sample[side]
            if channel["state"]["state_name"] != "Closed":
                return False
            flags = channel["state"]["state_flags"]
            assert direction in flags, channel
            assert channel["shutdown_transaction_hash"] == self.a["commitment"]["hash"]
            if "WAITING_ONCHAIN_SETTLEMENT" in flags:
                return False
            for tlc in channel["pending_tlcs"]:
                allowed = {removed, "RemoveAckConfirmed"}
                if side == "A":
                    allowed |= {"RemoveWaitPrevAck", "RemoveWaitAck"}
                if (
                    tlc["status"].get("Outbound" if side == "A" else "Inbound")
                    not in allowed
                ):
                    return False
        return True


@pytest.mark.manual_nightly
class TestTlcTimeoutRefund(_RefundBase):
    # TEST-MAP: LSP-REFUND-01
    # TEST-MAP: LSP-REFUND-02
    # TEST-MAP: LSP-REFUND-03
    def test_hold_payment_timeout_refund(self):
        """
        1. 唯一真实付款完整确认后由 T 强关，证明连续未成熟窗口不能提前退款。
        2. 仅在 guest 单次推进至 E+5秒，等待真实链成熟并核对签名及完整资金账本。
        3. 原付款失败、发票保持 Received、关闭处理完成，并连续稳定至少 65 秒。
        """
        # 1. 完整承诺检查点及真实未成熟保护。
        self.send_hold_payment()
        self.force_close()
        self.protect_immature()

        # 2. 单次 guest 调时后自然结算，仅统计实际取得的分支。
        self.jump_guest_clock()
        self.mature()
        sample = self._wait(self.mature_at + 480, lambda s: s["ledger"]["complete"])
        final = sample["ledger"]
        funds_at = time.monotonic()
        self.record("funds-complete", ledger=final, converges_by=funds_at + 360)

        # 3. 原业务终态及严格连续稳定窗口。
        self._wait(funds_at + 360, self.business_complete)
        log = (Path(self.fiber1.tmp_path) / "node.log").read_text()
        assert any(
            self.channel_id in line and "on-chain settlement completed" in line
            for line in log.splitlines()
        ), "missing same-channel settlement completion log"

        def stable(sample):
            assert self.business_complete(sample)
            assert sample["ledger"] == final, "funds changed after completion"

        self._window(stable, "stable-window")
        self.assert_single_tlc_history()
        self.record(
            "refund-complete",
            branch=final["branch"],
            ledger=final,
            seconds=time.monotonic() - self.started,
        )


@pytest.mark.manual_nightly
class TestTlcRefundAdapter(_RefundBase):
    """Read-only adapter checks; these do not count toward product 1+3."""

    agent_extra_args = ("--ack-held-events", "--watchtower-check-only")

    def test_single_tlc_adapter(self):
        self.send_hold_payment()
        self.force_close()
        self.protect_immature()
        self.jump_guest_clock()
        self.mature()
        self._wait(
            self.mature_at + 480,
            lambda s: s["watchtower"]["status"]["type"] == "SignatureRequired",
        )
        result = self.control(self.a, "watchtower-check")
        assert result["check_only"] is True
        assert (
            result.get("source")
            and result.get("authorization")
            and result.get("request_id")
        )
        self.record("sdk-positive-prepare", result=result)
        # The positive check above is read-only; retain the full natural offset window.
        if time.monotonic() < self.vm_clock.event["after_mono"] + 360:
            self._wait(
                self.vm_clock.event["after_mono"] + 365,
                lambda sample: time.monotonic()
                >= self.vm_clock.event["after_mono"] + 360,
            )
        self.vm_clock.check()
        checks = {row["case"] for row in result["checks"]}
        assert "wrong_tlc_index" in checks, result
        assert all(
            key in checks
            for key in (
                "wrong_tlc_hash",
                "wrong_tlc_amount",
                "wrong_tlc_direction",
                "wrong_tlc_residual",
            )
        ), result
        assert not self.gate.watchtower_submissions
        self.record("adapter-only-complete", result=result)

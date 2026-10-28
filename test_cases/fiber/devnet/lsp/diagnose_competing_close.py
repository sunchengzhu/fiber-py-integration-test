"""Manual 24b5c38 diagnosis; explicitly select the method, not a mapped regression.

Both A/T broadcasts reach real CKB. No arm(), rejection injection, miner pause,
manual close, restart, or signature submission after the prepared checkpoint.
Optional B reproduction delays one fixed 250 ms window of A transaction-status
responses, before shared SendTx. Both broadcasts still reach real CKB unchanged.
"""

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from test_cases.fiber.devnet.lsp import test_channel_signing_deadline as deadline
from test_cases.fiber.devnet.lsp._commitment_broadcast_gate import (
    CommitmentBroadcastGate,
)
from test_cases.fiber.devnet.lsp._lsp_test import BUNDLE, REVISION, stop_agent


class _ObservingProxy(CommitmentBroadcastGate):
    """Reuse unarmed byte-preserving forwarding; also retain indexer scan RPCs."""

    def __init__(self, upstream_url, directory):
        self.read_log = directory / "fnn-chain-reads.jsonl"
        self.timing_rule = None
        self.timing_episode = None
        self.delayed_queries = []
        super().__init__(upstream_url, BUNDLE / "lsp-integration-driver")

    def arm(self, *_args, **_kwargs):
        raise AssertionError("natural competition must never arm a broadcast gate")

    def configure_query_timing(self, log_path, channel_id, remote_pubkey, deadline_ms):
        """Bind A by its channel and peer; no transaction is sent by this helper."""
        self.timing_rule = {
            "log_path": str(log_path),
            "channel_id": channel_id,
            "remote_pubkey": remote_pubkey.removeprefix("0x"),
            "deadline_ms": deadline_ms,
            "delay_ms": 250,
        }

    def timing_snapshot(self):
        with self.lock:
            return copy.deepcopy(
                {
                    "rule": self.timing_rule,
                    "episode": self.timing_episode,
                    "delayed_queries": self.delayed_queries,
                }
            )

    def _delay_status_response(self, payload, result, received, upstream_done):
        rule = self.timing_rule
        if rule is None or payload.get("method") != "get_transaction":
            return
        # The tracer can query the same hash concurrently with the broadcaster.
        # Delay all matching responses only until the same fixed release time.
        with self.lock:
            if (
                self.timing_episode
                and time.monotonic() >= self.timing_episode["release_at"]
            ):
                return
        body = json.loads(result[2])
        if (body.get("result") or {}).get("tx_status", {}).get("status") != "unknown":
            return
        if received[1] < rule["deadline_ms"]:
            return
        pattern = (
            r"Spawning InFlightCkbTxActor: tx_hash=Hash256\((0x[0-9a-f]{64})\), "
            r"tx_kind=Closing\(Pubkey\("
            + re.escape(rule["remote_pubkey"])
            + r"\), Hash256\("
            + re.escape(rule["channel_id"])
            + r"\), true\)"
        )
        log_text = Path(rule["log_path"]).read_text()
        matches = list(re.finditer(pattern, log_text))
        hashes = {match.group(1) for match in matches}
        if len(hashes) > 1:
            self._failure("ambiguous A closing transaction hashes for timing diagnosis")
            return
        if not hashes or payload["params"][0] not in hashes:
            return
        now = time.monotonic()
        with self.lock:
            if self.timing_episode is None:
                self.timing_episode = {
                    "transaction_hash": payload["params"][0],
                    "started_at": now,
                    "release_at": now + 0.250,
                    "source_log_match": matches[0].group(0),
                }
            release_at = self.timing_episode["release_at"]
        # Never hold the shared proxy lock or wait for T acceptance/confirmation.
        time.sleep(max(0, release_at - time.monotonic()))
        with self.lock:
            self.delayed_queries.append(
                {
                    "request": payload,
                    "response": body,
                    "received_monotonic": received[0],
                    "upstream_response_monotonic": upstream_done,
                    "released_monotonic": time.monotonic(),
                }
            )

    def _request(self, payload, raw, authorization, received):
        result = super()._request(payload, raw, authorization, received)
        upstream_done = time.monotonic()
        self._delay_status_response(payload, result, received, upstream_done)
        if payload.get("method") in (
            "get_transactions",
            "get_transaction",
            "get_cells",
        ):
            entry = {
                "received_monotonic": received[0],
                "received_wall_ms": received[1],
                "upstream_response_monotonic": upstream_done,
                "response_monotonic": time.monotonic(),
                "request": payload,
                "http_status": result[0],
                "response": json.loads(result[2]),
            }
            with self.lock:
                with self.read_log.open("a") as stream:
                    stream.write(json.dumps(entry) + "\n")
        return result


class TestNaturalCompetition(deadline.TestChannelSigningDeadline):
    def setup_method(self, method):
        self.artifacts = Path(os.environ["LSP_NATURAL_ARTIFACTS"])
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.evidence = {
            "revision": REVISION,
            "checkpoint": os.environ.get("LSP_NATURAL_CHECKPOINT", "A"),
            "observations": [],
            "result": "incomplete",
        }
        self.observer = _ObservingProxy(self.node.rpcUrl, self.artifacts)
        self.start_fiber_config = {
            **self.start_fiber_config,
            "ckb_rpc_url": self.observer.url,
        }
        self.addCleanup(self._save_diagnosis)
        try:
            super().setup_method(method)
        except BaseException:
            self.doCleanups()
            raise

    def _save_diagnosis(self):
        try:
            for fiber in getattr(self, "fibers", []):
                process = getattr(fiber, "process", None)
                if process is not None:
                    stop_agent(process)
            self._stop_owned_miner(time.monotonic() + 5)
        finally:
            self.observer.stop()
            self.evidence["broadcasts"] = self.observer.snapshot()
            self.evidence["query_timing"] = self.observer.timing_snapshot()
            (self.artifacts / "evidence.json").write_text(
                json.dumps(self.evidence, indent=2) + "\n"
            )
            node_path = Path(self.fiber1.tmp_path) if hasattr(self, "fiber1") else None
            for label, path in (
                ("fnn.log", node_path / "node.log" if node_path else None),
                ("sdk.log", node_path / "sdk-A/agent.log" if node_path else None),
                ("ckb.log", Path(self.node.ckb_dir) / "data/logs/run.log"),
                ("ckb-stdout.log", Path(self.node.ckb_dir) / "node.log"),
            ):
                if path is not None and path.exists():
                    shutil.copy2(path, self.artifacts / label)
            print(f"natural competition artifacts: {self.artifacts}", flush=True)

    def _record(self, stage, **values):
        item = {
            "stage": stage,
            "monotonic": time.monotonic(),
            "wall_ms": time.time() * 1000,
            **values,
        }
        self.evidence["observations"].append(item)
        with (self.artifacts / "observations.jsonl").open("a") as stream:
            stream.write(json.dumps(item) + "\n")
        return item

    def _natural_health(self):
        assert self.tenant["agent"].poll() is None, "SDK exited"
        assert self.fiber1.process.poll() is None, "FNN exited"
        assert not self.gate.errors, self.gate.errors
        audit = self.observer.snapshot()
        assert audit["armed"] is None and not audit["errors"], audit
        assert all(e["outcome"] != "blocked" for e in audit["events"])
        return audit

    def test_observe_competing_close(self):
        # Prepare the same held-signature checkpoint, leaving mining and A/T active.
        self._arm_signature_gate()
        payment = self._prepare_payment(expiry_seconds=600)
        if self.evidence["checkpoint"] == "B":
            payment = self._to_checkpoint_b(payment)
        until = time.monotonic() + 10
        local = self._isolated_view(self.client, until)
        remote = self._isolated_view(self.fiber1.client, until)
        funding = self._funding_outpoint(local)
        records = self._isolated_records(until)
        signed_records = [
            r
            for r in records
            if r["complete"]
            and not r["for_remote"]
            and r["transaction_hash"] == local["latest_commitment_transaction_hash"]
        ]
        peer_records = [
            r
            for r in records
            if r["for_remote"]
            and r["transaction_hash"] == remote["latest_commitment_transaction_hash"]
        ]
        assert len(signed_records) == len(peer_records) == 1, records
        signed, peer = signed_records[0], peer_records[0]
        assert signed["signing_message"] != peer["signing_message"]
        if self.evidence["checkpoint"] == "B":
            target = [t for t in signed["tlcs"] if t["payment_hash"] == payment["hash"]]
            assert len(target) == 1 and target[0]["expiry"] == payment["expiry"], signed
        assert (
            local["state"]["state_name"]
            == remote["state"]["state_name"]
            == "ChannelReady"
        )
        assert (
            self._isolated_rpc(
                self.node.rpcUrl, "get_live_cell", [funding, False], until
            )["status"]
            == "live"
        )
        assert (
            time.time() * 1000 < payment["deadline"] - 5000
        ), "checkpoint prepared too late"
        with self.gate.lock:
            forwarded_before = copy.deepcopy(self.gate.forwarded)
        self.evidence.update(
            {
                "channel_id": self.channel_id,
                "funding": funding,
                "deadline_ms": payment["deadline"],
                "local_record": signed,
                "remote_record": peer,
            }
        )
        if os.environ.get("LSP_NATURAL_DELAY_A_PREFLIGHT") == "1":
            assert self.evidence["checkpoint"] == "B", "controlled timing is only for B"
            self.observer.configure_query_timing(
                Path(self.fiber1.tmp_path) / "node.log",
                self.channel_id,
                local["pubkey"],
                payment["deadline"],
            )
            self.evidence["mode"] = "controlled_query_timing_250ms"
        else:
            self.evidence["mode"] = "unmodified_forwarding"
        self._record("prepared", local=local, remote=remote, signing=self._status())
        print(
            f"natural checkpoint={self.evidence['checkpoint']} channel={self.channel_id}; both broadcasts enabled",
            flush=True,
        )

        # Observe the natural winner. Classification is after forwarding, never on its path.
        decoded = {}
        accepted = {}
        local_rejection = None
        winner = None
        committed_at = None
        recovered_at = None
        last_progress = 0
        acquisition_until = time.monotonic() + 90
        while True:
            audit = self._natural_health()
            for event in audit["events"]:
                if funding not in event["inputs"] or event["outcome"] == "received":
                    continue
                key = event["raw_request"]
                if key not in decoded:
                    message = subprocess.check_output(
                        [str(BUNDLE / "lsp-integration-driver"), "commitment-message"],
                        input=json.dumps(event["transaction"]),
                        text=True,
                        timeout=2,
                    ).strip()
                    decoded[key] = (
                        "A"
                        if message == signed["signing_message"]
                        else "T" if message == peer["signing_message"] else "unknown"
                    )
                    assert decoded[key] != "unknown", event
                    self._record(
                        "broadcast_classified",
                        side=decoded[key],
                        event=event,
                        message=message,
                    )
                side = decoded[key]
                if event["actual_hash"]:
                    accepted[side] = event["actual_hash"]
                error = (event["response"] or {}).get("error", {})
                if (
                    side == "A"
                    and error.get("code") == -1111
                    and "RBFRejected" in str(error.get("data", ""))
                ):
                    local_rejection = event
            until = time.monotonic() + 20
            transactions = {
                side: self._isolated_rpc(
                    self.node.rpcUrl, "get_transaction", [tx_hash], until
                )
                for side, tx_hash in accepted.items()
            }
            if committed_at is None:
                committed = [
                    (side, tx)
                    for side, tx in transactions.items()
                    if tx and tx["tx_status"]["status"] == "committed"
                ]
                if committed:
                    assert len(committed) == 1, committed
                    winner, winning_tx = committed[0]
                    assert funding in [
                        i["previous_output"]
                        for i in winning_tx["transaction"]["inputs"]
                    ]
                    committed_at = time.monotonic()
                    self.evidence.update(
                        {
                            "winner": winner,
                            "winner_hash": accepted[winner],
                            "committed_at": committed_at,
                        }
                    )
                    self._record(
                        "winner_committed", winner=winner, transaction=winning_tx
                    )
                    print(
                        f"natural winner={winner} hash={accepted[winner]}", flush=True
                    )
                    if winner != "T":
                        self.evidence["result"] = "scenario_not_acquired_A_won"
                        assert (
                            False
                        ), "Natural A win: requested T-win scenario not acquired; evidence retained"
                    print("T committed; starting 330s observation", flush=True)

            local = self._isolated_view(self.client, until)
            remote = self._isolated_view(self.fiber1.client, until)
            status = self._isolated_status(until)
            tip = self._isolated_rpc(
                self.node.rpcUrl, "get_tip_block_number", [], until
            )
            indexer_tip = self._isolated_rpc(
                self.node.rpcUrl, "get_indexer_tip", [], until
            )
            self._record(
                "sample",
                local=local,
                remote=remote,
                signing=status,
                tip=tip,
                indexer_tip=indexer_tip,
                transactions=transactions,
            )
            if committed_at is not None:
                if (
                    local["state"]["state_name"] == "Closed"
                    and "UNCOOPERATIVE_REMOTE" in local["state"]["state_flags"]
                    and local["shutdown_transaction_hash"] == accepted["T"]
                    and status["type"] == "NoSignatureRequired"
                ):
                    if recovered_at is None:
                        recovered_at = time.monotonic()
                        self._record(
                            "A_recovered",
                            after_commit_seconds=recovered_at - committed_at,
                        )
                if time.monotonic() - committed_at >= 330:
                    break
            else:
                assert (
                    time.monotonic() < acquisition_until
                ), "No confirmed natural winner within 90s"
            if time.monotonic() - last_progress >= 20:
                elapsed = (
                    None
                    if committed_at is None
                    else round(time.monotonic() - committed_at, 1)
                )
                print(
                    f"natural elapsed={elapsed} A={local['state']} T={remote['state']} real_RBF={local_rejection is not None} tip={tip}",
                    flush=True,
                )
                last_progress = time.monotonic()
            time.sleep(2)

        assert (
            local_rejection is not None
        ), "T committed but no real A RBFRejected: scenario not acquired"
        self.evidence["real_A_rejection"] = local_rejection
        timing = self.observer.timing_snapshot()
        if timing["rule"] is not None:
            assert (
                timing["episode"] is not None and timing["delayed_queries"]
            ), "timing window did not activate"
            episode = timing["episode"]
            earliest_release = min(
                q["released_monotonic"] for q in timing["delayed_queries"]
            )
            local_events = [
                e
                for e in self.observer.snapshot()["events"]
                if decoded.get(e["raw_request"]) == "A"
            ]
            remote_events = [
                e
                for e in self.observer.snapshot()["events"]
                if decoded.get(e["raw_request"]) == "T"
                and e["actual_hash"] == accepted["T"]
            ]
            assert local_events and remote_events
            assert (
                min(e["received_monotonic"] for e in remote_events)
                < episode["release_at"]
            )
            assert (
                min(e["received_monotonic"] for e in local_events) >= earliest_release
            )
            assert (
                max(q["released_monotonic"] for q in timing["delayed_queries"])
                < committed_at
            )
            # FNN binds the logged actual hash; real broadcast canonical identifies A independently.
            assert all(
                q["request"]["params"][0] == episode["transaction_hash"]
                for q in timing["delayed_queries"]
            )
            self._record("controlled_timing_verified", timing=timing)
        with self.gate.lock:
            assert (
                self.gate.forwarded == forwarded_before
            ), "signature was forwarded during observation"
        samples = [o for o in self.evidence["observations"] if o["stage"] == "sample"]
        assert int(samples[-1]["tip"], 16) > int(
            samples[0]["tip"], 16
        ), "mining stalled"
        assert int(samples[-1]["indexer_tip"]["block_number"], 16) >= int(
            winning_tx["tx_status"]["block_number"], 16
        )
        self._natural_health()
        self.evidence.update(
            {
                "observed_after_commit_seconds": time.monotonic() - committed_at,
                "recovered_after_commit_seconds": (
                    None if recovered_at is None else recovered_at - committed_at
                ),
                "result": (
                    "recovered"
                    if recovered_at is not None
                    else "not_recovered_after_full_window"
                ),
            }
        )
        self._record(
            "finished",
            result=self.evidence["result"],
            local=local,
            remote=remote,
            signing=status,
        )
        assert (
            recovered_at is not None
        ), "A did not recover after T committed + full 330s; inspect source and captured scan RPCs"
        assert (
            local["state"]["state_name"] == "Closed"
            and local["shutdown_transaction_hash"] == accepted["T"]
        )
        assert (
            "UNCOOPERATIVE_REMOTE" in local["state"]["state_flags"]
            and status["type"] == "NoSignatureRequired"
        )

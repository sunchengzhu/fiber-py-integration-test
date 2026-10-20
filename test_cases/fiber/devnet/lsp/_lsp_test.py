"""Shared preparation for Hosted LSP tests using real SDK signers."""

import copy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
from types import SimpleNamespace

import requests
import yaml

from framework.basic_fiber import FiberTest
from framework.fiber_rpc import FiberRPCClient
from framework.test_fiber import FiberConfigPath
from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._signer_gate import SignatureGate
from test_cases.fiber.devnet.lsp._retry_signer_gate import RetrySignatureGate

REVISION = "8419c005e2d0e737c5abf7e0f881aaedbc6fd300"
BUNDLE = Path(get_project_root()) / "download/fiber/pr-1623"
BISCUIT_PUBLIC_KEY = (
    "ed25519/17b172749be74276f0ed35a5d0685752684a3c5722114bba447a2f301136db79"
)


def stop_agent(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class LspTestBase(FiberTest):
    tenant_labels = ("A", "B")
    gate_class = SignatureGate
    channel_open_options = {"commitment_delay_epoch": "0x10000000001"}
    tenant_rpc_timeout = 30
    agent_extra_args = ()
    # Extra keys written into the hosting FNN's `fiber:` section. Deadline suites
    # shorten the two opening timers here instead of changing a shared template.
    fiber_config_extra = {}
    # Deadline suites that hold the wallet funding submission keep this false.
    submit_external_funding = True
    # Keep the pre-merge binary selection local to this suite.
    fiber_version = SimpleNamespace(
        fiber_config_path=FiberConfigPath.CURRENT_DEV.fiber_config_path,
        fiber_bin_path=str((BUNDLE / "fnn").relative_to(get_project_root())),
    )
    start_fiber_config = {
        "fiber_auto_accept_channel_ckb_funding_amount": 500 * 100000000
    }

    @classmethod
    def setup_class(cls):
        assert (BUNDLE / "build.json").exists(), (
            "Build the pinned FNN and SDK agent first: "
            "python3 scripts/build_lsp_test_binaries.py --source <clean Fiber checkout>"
        )
        manifest = json.loads((BUNDLE / "build.json").read_text())
        assert manifest["revision"] == REVISION
        assert manifest.get(
            "includes_test_driver"
        ), "Rebuild with scripts/build_lsp_test_binaries.py without --upstream-only"
        for name in (
            "fnn",
            "fiber-lsp-sdk-agent",
            "lsp-integration-driver",
            "biscuit-private-key",
            "operator-token",
        ):
            assert (
                hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest()
                == manifest["sha256"][name]
            ), name
        assert (
            manifest["driver_source_sha256"]
            == hashlib.sha256(
                Path(__file__).with_name("_sdk_driver.rs").read_bytes()
            ).hexdigest()
        ), "Rebuild the LSP test driver after changing its source"
        version = subprocess.check_output([str(BUNDLE / "fnn"), "--version"], text=True)
        assert REVISION[:7] in version and "dirty" not in version, version
        print(f"LSP integration binaries: {version.strip()}, SDK source {REVISION}")
        for port in (8114, 8125, 8227, 8228, 8229, 8230):
            with socket.socket() as sock:
                assert (
                    sock.connect_ex(("127.0.0.1", port)) != 0
                ), f"test port {port} already in use"
        super().setup_class()

    def setUp(self):
        # FiberTest supplies the chain, public node and a separate funding-signing node.
        self.public_key = self.fiber1.get_pubkey()
        self.fiber1.stop()
        config_path = Path(self.fiber1.fiber_config_path)
        # Preserve the template's hex scalars; YAML 1.1 loaders turn them into integers.
        config = config_path.read_text()
        for anchor in ("services:\n", "rpc:\n", "  enabled_modules:\n"):
            assert (
                config.count(anchor) == 1
            ), f"missing or repeated config anchor: {anchor}"
        config = config.replace("services:\n", "services:\n  - lsp\n")
        config = config.replace(
            "  enabled_modules:\n", "  enabled_modules:\n    - lsp\n"
        )
        config = config.replace(
            "rpc:\n",
            "rpc:\n"
            f"  biscuit_public_key: {BISCUIT_PUBLIC_KEY}\n"
            f"  biscuit_private_key_path: {json.dumps(str(BUNDLE / 'biscuit-private-key'))}\n",
        )
        if self.fiber_config_extra:
            assert config.count("fiber:\n") == 1, "missing or repeated fiber section"
            extra = "".join(
                f"  {key}: {value}\n" for key, value in self.fiber_config_extra.items()
            )
            config = config.replace("fiber:\n", "fiber:\n" + extra, 1)
        config_path.write_text(config + "\nlsp:\n  max_active_tenants: 2\n")
        operator_token = (BUNDLE / "operator-token").read_text().strip()
        self.fiber1.client = FiberRPCClient(
            self.fiber1.client.url,
            {"Authorization": f"Bearer {operator_token}"},
            try_count=1,
            timeout=10,
        )
        self.fiber1.start()
        self.tenants = []

        # Allocate all wallets before opening channels, so the faucet cannot spend
        # public-node inputs already reserved by an unsigned funding transaction.
        funding_accounts = [self.generate_account(1000) for _ in self.tenant_labels]
        donor = self.generate_account(3000)
        for _ in self.tenant_labels:
            tx_hash = self.Ckb_cli.wallet_transfer_by_private_key(
                donor, self.account1["address"]["testnet"], 1000, self.node.rpcUrl, 3000
            )
            self.Miner.miner_until_tx_committed(self.node, tx_hash, True)

        for label, private_key in zip(self.tenant_labels, funding_accounts):
            directory = Path(self.fiber1.tmp_path) / f"sdk-{label}"
            directory.mkdir()
            status_file = directory / "status.json"
            gate = self.gate_class(self.fiber1.client.url)
            self.addCleanup(gate.close)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                control_port = sock.getsockname()[1]
            log = (directory / "agent.log").open("w")
            self.addCleanup(log.close)
            agent_command = [
                str(BUNDLE / "lsp-integration-driver"),
                "--rpc",
                gate.url,
                "--store",
                str(directory / "store"),
                "--status-file",
                str(status_file),
                "--control-addr",
                f"127.0.0.1:{control_port}",
                "--operator-token",
                operator_token,
            ]
            agent_command.extend(self.agent_extra_args)
            agent = subprocess.Popen(
                agent_command,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            self.addCleanup(stop_agent, agent)
            for _ in range(60):
                assert (
                    agent.poll() is None
                ), f"SDK {label} exited; see {directory / 'agent.log'}"
                if status_file.exists():
                    try:
                        status = json.loads(status_file.read_text())
                        break
                    except json.JSONDecodeError:
                        pass
                time.sleep(1)
            else:
                assert (
                    False
                ), f"SDK {label} did not register; see {directory / 'agent.log'}"
            client = FiberRPCClient(
                self.fiber1.client.url,
                {"Authorization": f"Bearer {status['tenant_token']}"},
                try_count=1,
                timeout=self.tenant_rpc_timeout,
            )
            self.fiber1.client.call(
                "lsp_ensure_tenant", [{"tenant_id": status["tenant_id"]}]
            )
            # Distinct wallets prevent the two external funding transactions sharing inputs.
            wallet = self.Ckb_cli.util_key_info_by_private_key(private_key)
            funding_script = {
                "code_hash": self.Config.CKB_DEFAULT_CONFIG[
                    "ckb_block_assembler_code_hash"
                ],
                "hash_type": "type",
                "args": wallet["lock_arg"],
            }
            tenant = {
                "label": label,
                "client": client,
                "gate": gate,
                "agent": agent,
                "status": status,
                "command": agent_command,
                "control_port": control_port,
                "status_file": status_file,
                "log": log,
                "shutdown_script": funding_script,
                "control_calls": [],
            }
            config = yaml.load(config_path.read_text(), Loader=yaml.BaseLoader)
            scripts = {item["name"]: item for item in config["fiber"]["scripts"]}
            # The real SDK saves the wallet intent and independently verifies funding.
            opened = self.signer_control(
                tenant,
                "open",
                {
                    "params": {
                        **self.channel_open_options,
                        "pubkey": self.public_key,
                        "funding_amount": hex(500 * 100000000),
                        "commitment_fee_rate": hex(1000),
                        "public": False,
                        "shutdown_script": funding_script,
                        "funding_lock_script": funding_script,
                        "external_channel_signer": status[
                            "channel_open_signer_material"
                        ],
                    },
                    "funding_lock": scripts["FundingLock"]["script"],
                    "commitment_lock": scripts["CommitmentLock"]["script"],
                    "commitment_cell_deps": len(scripts["FundingLock"]["cell_deps"]),
                    "ckb_rpc_url": self.node.rpcUrl,
                },
            )
            channel_id = opened["channel_id"]
            tenant["channel_id"] = channel_id
            tenant["private_key"] = private_key
            tenant["opened"] = opened
            opening_input = {
                "database": str(Path(self.fiber1.tmp_path) / "fiber/store"),
                "channel_id": channel_id,
                "shutdown_script": funding_script,
                "signer_material": status["channel_open_signer_material"],
                "commitment_lock": scripts["CommitmentLock"]["script"],
                "funding_dep_count": len(scripts["FundingLock"]["cell_deps"]),
            }
            opening = json.loads(
                subprocess.check_output(
                    [str(BUNDLE / "lsp-integration-driver"), "opening"],
                    input=json.dumps(opening_input),
                    text=True,
                )
            )
            tenant["opening"] = opening
            for _ in range(30):
                bound = json.loads(status_file.read_text())
                if channel_id in bound["bound_channel_ids"]:
                    break
                time.sleep(1)
            else:
                assert False, f"SDK {label} did not bind channel {channel_id}"
            if self.submit_external_funding:
                signed = self.fiber2.client.call(
                    "sign_external_funding_tx",
                    [
                        {
                            "unsigned_funding_tx": opened["unsigned_funding_tx"],
                            "private_key": private_key,
                        }
                    ],
                )
                funding = client.call(
                    "submit_signed_funding_tx",
                    [
                        {
                            "channel_id": channel_id,
                            "signed_funding_tx": signed["signed_funding_tx"],
                        }
                    ],
                )
                tenant["funding_tx_hash"] = funding["funding_tx_hash"]
            self.tenants.append(tenant)

        if not self.submit_external_funding:
            # The wallet still owes its funding signature; no channel signature exists yet.
            return

        for tenant in self.tenants:
            for _ in range(60):
                assert tenant["agent"].poll() is None, f"SDK {tenant['label']} exited"
                if tenant["gate"].captured.is_set():
                    break
                time.sleep(1)
            else:
                assert False, f"SDK {tenant['label']} did not produce a signature"
            before = tenant["client"].call(
                "get_channel_signing_status", [{"channel_id": tenant["channel_id"]}]
            )
            assert before["status"]["type"] == "SignatureRequired", before
            assert (
                tenant["gate"].authorization
                == tenant["client"].other_params["Authorization"]
            )
            assert tenant["gate"].submission["channel_id"] == tenant["channel_id"]
            assert (
                tenant["gate"].submission["request_id"]
                == before["status"]["request_id"]
            )
            tenant["before"] = before
            tenant["state"] = self._channel_state(
                tenant["client"], tenant["channel_id"]
            )
            assert tenant["state"]["state_name"] != "ChannelReady"

    def _channel_state(self, client, channel_id):
        channels = client.list_channels({})["channels"]
        matching = [
            channel for channel in channels if channel["channel_id"] == channel_id
        ]
        assert len(matching) == 1, f"expected channel {channel_id}, got {channels}"
        return matching[0]["state"]

    def signer_control(self, tenant, operation, values=None):
        payload = {
            "operation": operation,
            "channel_id": tenant.get("channel_id"),
            **(values or {}),
        }
        with socket.create_connection(
            ("127.0.0.1", tenant["control_port"]), timeout=20
        ) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode())
            with connection.makefile("r") as stream:
                reply = json.loads(stream.readline())
        assert "error" not in reply, reply
        tenant["control_calls"].append((operation, time.monotonic()))
        return reply["result"]


class ChannelSigningTestBase(LspTestBase):
    tenant_labels = ("A",)
    gate_class = RetrySignatureGate
    tenant_rpc_timeout = 10
    # One epoch, index zero, length one. The pinned debug build uses 2 s/epoch.
    channel_open_options = {"commitment_delay_epoch": "0x10000000001"}
    # Applicable opening timeout and the margin this suite still needs after setup.
    opening_window_seconds = 86400
    opening_window_margin = 180

    def setUp(self):
        super().setUp()
        self.tenant = self.tenants[0]
        self.client = self.tenant["client"]
        self.channel_id = self.tenant["channel_id"]
        self.gate = self.tenant["gate"]
        created = int(self._channel(self.client)["created_at"], 16) / 1000
        assert created + self.opening_window_seconds - time.time() >= (
            self.opening_window_margin
        )

    def _channel(self, client, channel_id=None):
        channel_id = channel_id or self.channel_id
        channels = client.list_channels({})["channels"]
        found = [item for item in channels if item["channel_id"] == channel_id]
        assert len(found) == 1, channels
        return found[0]

    def _status(self):
        return self.client.call(
            "get_channel_signing_status", [{"channel_id": self.channel_id}]
        )["status"]

    def _pending(self, previous=None):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            status = self._status()
            if status["type"] == "SignatureRequired":
                request_id = status["request_id"]
                with self.gate.lock:
                    submission = copy.deepcopy(self.gate.submissions.get(request_id))
                if request_id != previous and submission is not None:
                    return status, submission
            time.sleep(0.2)
        assert False, f"SDK did not prepare the next signature: {status}"

    def _submit(self, submission, expected="Applied"):
        # Direct to FNN: the gate must never fabricate an idempotency result.
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                self.client.url,
                headers=self.client.other_params,
                json={
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "submit_channel_signature",
                    "params": [submission],
                },
                timeout=10,
            )
        response.raise_for_status()
        body = response.json()
        if expected is None:
            assert "result" not in body, body
            assert body.get("error", {}).get("code") == -32000, body
        else:
            assert "error" not in body, body
            assert body["result"] == {"type": expected}, body
        return body

    def _apply_and_pause_next(self):
        first, submission = self._pending()
        self._submit(submission)
        following, _ = self._pending(previous=first["request_id"])
        return submission, following

    def _snapshot(self, client, channel_id=None):
        channel = self._channel(client, channel_id)
        return {
            key: channel[key]
            for key in (
                "channel_id",
                "channel_outpoint",
                "state",
                "local_balance",
                "remote_balance",
                "offered_tlc_balance",
                "received_tlc_balance",
                "pending_tlcs",
                "latest_commitment_transaction_hash",
            )
        }

    def _finish_opening(self):
        self.gate.release()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            local = self._channel(self.client)
            public = self._channel(self.fiber1.client)
            if (
                local["state"]["state_name"]
                == public["state"]["state_name"]
                == "ChannelReady"
                and self._status()["type"] == "NoSignatureRequired"
            ):
                break
            time.sleep(1)
        else:
            current = self._status()
            requests = (self.tenant["before"]["status"], current)
            summaries = [
                {
                    "transition": r.get("transition"),
                    "slot": r.get("content", {}).get("slot"),
                    "counter": r.get("content", {}).get("commitment_counter"),
                    "outputs": r.get("content", {})
                    .get("content", {})
                    .get("transaction", {})
                    .get("outputs"),
                }
                for r in requests
            ]
            records = self.signer_control(self.tenant, "records")
            log_tail = (
                self.tenant["status_file"]
                .with_name("agent.log")
                .read_text()
                .splitlines()[-5:]
            )
            assert False, (
                f"opening did not finish: tenant={local['state']}, public={public['state']}; "
                f"initial/current signing={summaries}; SDK records={records}; SDK log={log_tail}"
            )
        assert len(self.client.list_channels({})["channels"]) == 1
        assert local["channel_outpoint"] == public["channel_outpoint"]
        assert local["channel_outpoint"] is not None
        funding_outpoint = bytes.fromhex(local["channel_outpoint"][2:])
        assert len(funding_outpoint) == 36
        assert "0x" + funding_outpoint[:32].hex() == self.tenant["funding_tx_hash"]
        transaction = self.node.getClient().get_transaction(
            "0x" + funding_outpoint[:32].hex()
        )
        assert transaction["tx_status"]["status"] == "committed", transaction
        assert not local["pending_tlcs"] and not public["pending_tlcs"]

    def _wait_for_fault_repoll(self):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            if self.gate.repolled.is_set():
                return
            time.sleep(0.1)
        assert False, "SDK did not start a new status query after the injected fault"

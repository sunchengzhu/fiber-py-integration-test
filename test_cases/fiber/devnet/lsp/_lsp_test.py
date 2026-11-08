"""Shared preparation for Hosted LSP tests using real SDK signers."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from types import SimpleNamespace

import requests
import yaml

from framework.basic_fiber import FiberTest, XUDT_TX_HASH
from framework.fiber_rpc import FiberRPCClient
from framework.helper.udt_contract import UdtContract, issue_udt_tx
from framework.test_fiber import Fiber, FiberConfigPath, wait_for_port
from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._signer_gate import SignatureGate
from test_cases.fiber.devnet.lsp._retry_signer_gate import RetrySignatureGate
from test_cases.fiber.devnet.lsp._subscription_observer import SubscriptionProxy

PROJECT_ROOT = Path(get_project_root()).resolve()
REVISION = os.environ.get(
    "LSP_TEST_REVISION", "04c206465b48da85b99aa58e80afe9801a2cb2db"
)
assert len(REVISION) == 40 and all(
    c in "0123456789abcdef" for c in REVISION
), "LSP_TEST_REVISION must be a full lowercase commit SHA"
RETEST_REVISION = os.environ.get("LSP_RETEST_REVISION")
if RETEST_REVISION is not None:
    assert len(RETEST_REVISION) == 40 and all(
        c in "0123456789abcdef" for c in RETEST_REVISION
    ), "LSP_RETEST_REVISION must be a full lowercase commit SHA"
BUNDLE = Path(
    os.environ.get(
        "LSP_TEST_BUNDLE",
        str(PROJECT_ROOT / "download/fiber" / f"pr-1623-{REVISION[:7]}"),
    )
).resolve()
assert BUNDLE.is_relative_to(
    PROJECT_ROOT
), "LSP_TEST_BUNDLE must stay inside this test checkout"
BISCUIT_PUBLIC_KEY = (
    "ed25519/17b172749be74276f0ed35a5d0685752684a3c5722114bba447a2f301136db79"
)
BUNDLE_MANIFEST = "build.json"


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_env_path(name, purpose):
    """Fail before node startup when this batch's external path is not declared."""
    value = os.environ.get(name)
    assert value, f"{name} is required {purpose}"
    return Path(value).resolve()


def require_runtime_inputs():
    """Validate non-Git devnet inputs before any CKB/FNN process starts."""
    required = {
        "CKB node binary (download/0.202.0/ckb)": PROJECT_ROOT / "download/0.202.0/ckb",
        "ckb-cli in download/0.202.0": PROJECT_ROOT / "download/0.202.0/ckb-cli",
        "ckb-cli used by framework (source/ckb-cli)": PROJECT_ROOT / "source/ckb-cli",
        "CKB dev spec": PROJECT_ROOT / "source/template/ckb/v118/specs/dev.toml",
        "CKB default db options": PROJECT_ROOT
        / "source/template/ckb/default.db-options",
        "Fiber dev config template": PROJECT_ROOT / "source/fiber/dev_config_3.yml.j2",
        "Fiber dev.toml": PROJECT_ROOT / "source/fiber/dev.toml",
        "Fiber devnet snapshot": PROJECT_ROOT / "source/fiber/data.2026.0929.tar.gz",
    }
    for label, path in required.items():
        assert path.is_file(), f"missing {label}: {path}"
    for name in ("ckb", "ckb-cli"):
        assert os.access(
            PROJECT_ROOT / "download/0.202.0" / name, os.X_OK
        ), f"{name} is not executable: {PROJECT_ROOT / 'download/0.202.0' / name}"
    assert os.access(
        PROJECT_ROOT / "source/ckb-cli", os.X_OK
    ), f"source/ckb-cli is not executable: {PROJECT_ROOT / 'source/ckb-cli'}"


def validate_bundle(bundle=BUNDLE, revision=REVISION):
    """Verify the pinned FNN/SDK/driver bundle before CKB or FNN starts."""
    bundle = Path(bundle).resolve()
    manifest_path = bundle / BUNDLE_MANIFEST
    assert manifest_path.is_file(), (
        f"LSP bundle has no {BUNDLE_MANIFEST}: {bundle}; build the pinned FNN and SDK agent first: "
        "python3 scripts/build_lsp_test_binaries.py --source <clean Fiber checkout> "
        f"--revision {revision}"
    )
    manifest = json.loads(manifest_path.read_text())
    assert (
        manifest.get("revision") == revision
    ), f"bundle revision {manifest.get('revision')} != LSP_TEST_REVISION {revision}"
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
        path = bundle / name
        assert path.is_file(), f"LSP bundle is missing {name}: {path}"
        assert sha256_file(path) == manifest["sha256"][name], f"{name} digest mismatch"
    for name in ("fnn", "fiber-lsp-sdk-agent", "lsp-integration-driver"):
        assert os.access(
            bundle / name, os.X_OK
        ), f"{name} is not executable: {bundle / name}"
    assert manifest["driver_source_sha256"] == sha256_file(
        Path(__file__).with_name("_sdk_driver.rs")
    ), "Rebuild the LSP test driver after changing its source"
    assert manifest["chain_source_sha256"] == sha256_file(
        Path(__file__).with_name("_watchtower_chain.rs")
    ), "Rebuild the watchtower adapter after changing its source"
    version = subprocess.check_output(
        [str(bundle / "fnn"), "--version"], text=True
    ).strip()
    assert revision[:7] in version and "dirty" not in version, version
    assert (
        manifest.get("fnn_version", "").strip() == version
    ), f"bundle manifest says {manifest.get('fnn_version')!r}, binary reports {version!r}"
    return manifest


def validate_delivery_wrapper(wrapper, revision=REVISION):
    """Verify the review-built FNN wrapper and its recorded build inputs."""
    wrapper = Path(wrapper).resolve()
    assert wrapper.is_file(), f"LSP_DELIVERY_NODE is not a file: {wrapper}"
    assert os.access(wrapper, os.X_OK), f"delivery wrapper is not executable: {wrapper}"
    bundle = wrapper.parent
    manifest_path = bundle / BUNDLE_MANIFEST
    assert manifest_path.is_file(), (
        f"delivery wrapper has no sibling {BUNDLE_MANIFEST}: {bundle}; "
        "use scripts/build_lsp_delivery_node.py output"
    )
    manifest = json.loads(manifest_path.read_text())
    assert (
        manifest.get("revision") == revision
    ), f"delivery wrapper revision {manifest.get('revision')} != LSP_TEST_REVISION {revision}"
    assert manifest.get("delivery_kind") == (
        "original-run-node-wrapper-with-in-process-proxy"
    ), f"unexpected delivery wrapper kind: {manifest.get('delivery_kind')!r}"
    expected = (manifest.get("sha256") or {}).get("lsp-delivery-node")
    assert expected, "delivery manifest has no lsp-delivery-node digest"
    assert sha256_file(wrapper) == expected, "lsp-delivery-node binary digest mismatch"
    adapter_sources = {
        path.name: sha256_file(path)
        for path in Path(__file__)
        .with_name("_delivery_node.rs")
        .parent.glob("_delivery*.rs")
    }
    assert (
        manifest.get("delivery_source_sha256") == adapter_sources
    ), "Rebuild the delivery wrapper after changing its adapter source"
    build_dir = bundle / "node-build"
    assert build_dir.is_dir(), f"delivery bundle is missing node-build: {build_dir}"
    for name, expected_digest in adapter_sources.items():
        source = build_dir / name
        assert source.is_file(), f"delivery build input is missing: {source}"
        assert sha256_file(source) == expected_digest, f"{source} digest mismatch"
    delivery_lock = build_dir / "Cargo.lock"
    assert delivery_lock.is_file(), f"delivery lock is missing: {delivery_lock}"
    assert sha256_file(delivery_lock) == manifest.get(
        "delivery_lock_sha256"
    ), "delivery wrapper lock digest mismatch"
    version = subprocess.check_output(
        [str(bundle / "fnn"), "--version"], text=True
    ).strip()
    assert revision[:7] in version and "dirty" not in version, version
    assert (
        manifest.get("fnn_version", "").strip() == version
    ), f"delivery manifest says {manifest.get('fnn_version')!r}, binary reports {version!r}"
    return manifest


def stop_agent(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class LspFiber(Fiber):
    """Fiber node whose process is owned and verified by this test batch."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.process = None
        self.binary = None
        self.process_env = {}

    def _port_is_open(self):
        with socket.socket() as sock:
            sock.settimeout(1)
            return sock.connect_ex(("127.0.0.1", int(self.rpc_port))) == 0

    def _log_tail(self, lines=20):
        path = Path(self.tmp_path) / "node.log"
        if not path.is_file():
            return "<no node.log>"
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])

    def start(
        self,
        password="password0",
        fnn_log_level="debug",
        binary=None,
        env=None,
        wait=True,
    ):
        """Start this node as a direct child; never through shell `&` or pid.txt."""
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError(
                f"FNN already running for {self.tmp_path} (pid {self.process.pid})"
            )
        binary = Path(binary or self.binary or (BUNDLE / "fnn")).resolve()
        assert binary.is_file(), f"missing FNN binary: {binary}"
        assert os.access(binary, os.X_OK), f"FNN binary is not executable: {binary}"
        log_path = Path(self.tmp_path) / "node.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as log:
            process = subprocess.Popen(
                [str(binary), "-c", self.fiber_config_path, "-d", self.tmp_path],
                env={
                    **os.environ,
                    **self.extra_env,
                    **(env or self.process_env),
                    "FIBER_SECRET_KEY_PASSWORD": password,
                    "RUST_LOG": f"info,fnn={fnn_log_level}",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        self.process = process
        self.binary = binary
        if wait:
            self.wait_ready()
        return process

    def wait_ready(self, timeout=300):
        """Wait for this owned process's RPC port, failing fast if it exited."""
        process = self.process
        assert process is not None, f"no owned FNN process for {self.tmp_path}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"FNN exited with {process.returncode} before RPC was ready; "
                    f"log: {self.tmp_path}/node.log\n{self._log_tail()}"
                )
            try:
                wait_for_port(self.rpc_port, timeout=1, open=True)
                return
            except TimeoutError:
                pass
        raise TimeoutError(
            f"FNN RPC port {self.rpc_port} did not open within {timeout}s; "
            f"log: {self.tmp_path}/node.log\n{self._log_tail()}"
        )

    def stop(self):
        """Gracefully stop only the process this test started."""
        process = self.process
        if process is None:
            if self._port_is_open():
                raise RuntimeError(
                    f"refusing to kill unowned listener on port {self.rpc_port}; "
                    "this node was not started by the current test"
                )
            self._wait_store_lock_released()
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                raise TimeoutError(
                    f"FNN pid {process.pid} did not exit within 30s after SIGTERM; "
                    f"log: {self.tmp_path}/node.log\n{self._log_tail()}"
                ) from None
        wait_for_port(self.rpc_port, timeout=30, open=False)
        self._wait_store_lock_released()

    def force_stop(self):
        """Kill only the owned process, then verify it actually exited."""
        process = self.process
        if process is None:
            if self._port_is_open():
                raise RuntimeError(
                    f"refusing to kill unowned listener on port {self.rpc_port}; "
                    "this node was not started by the current test"
                )
            return
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                raise TimeoutError(
                    f"FNN pid {process.pid} did not exit within 30s after SIGKILL; "
                    f"log: {self.tmp_path}/node.log\n{self._log_tail()}"
                ) from None
        wait_for_port(self.rpc_port, timeout=30, open=False)


def cleanup_owned_lsp_nodes(fibers, archive=None, failure=None):
    """Stop nodes, preserve failure evidence, then clean owned runtime dirs.

    Only after every owned process is confirmed stopped and the optional
    ``archive(fibers, failure) -> list[str]`` callback succeeds are directories
    removed. Archive errors or unconfirmed process exits keep the source
    directories and are returned; the caller attaches them to the original
    setup exception. The function is idempotent and continues with other
    resources when one of them fails.
    """
    errors = []
    eligible = []
    for fiber in reversed(list(fibers)):
        try:
            process = getattr(fiber, "process", None)
            if process is not None:
                fiber.force_stop()
            elif getattr(fiber, "_port_is_open", lambda: False)():
                raise RuntimeError(
                    f"refusing to clean unowned listener on port {fiber.rpc_port}"
                )
        except BaseException as error:
            # This resource keeps its directory; other owned nodes may still
            # be archived and cleaned below.
            errors.append(f"{fiber.tmp_path}: {error!r}")
        else:
            eligible.append(fiber)

    remaining = [fiber for fiber in eligible if Path(fiber.tmp_path).exists()]
    if archive is not None and remaining:
        try:
            archive_errors = archive(remaining, failure) or []
        except BaseException as error:
            archive_errors = [f"failure archive: {error!r}"]
        if archive_errors:
            errors.extend(archive_errors)
            # Necessary evidence is not preserved: keep eligible source dirs.
            return errors

    for fiber in eligible:
        try:
            fiber.clean()
        except BaseException as error:
            errors.append(f"{fiber.tmp_path} clean: {error!r}")
    return errors


def start_owned_lsp_nodes(
    fibers, add_cleanup, connect=None, fnn_log_level="debug", archive=None
):
    """Start the suite's nodes and recover on partial startup/wait failure.

    ``add_cleanup`` is normally ``unittest.TestCase.addCleanup``. Registration
    happens right after each successful start; the explicit cleanup below does
    not rely on unittest running those callbacks after a setup failure. The
    optional archive callback runs after owned processes stop and before the
    runtime directories are deleted.
    """
    try:
        for fiber in fibers:
            fiber.start(fnn_log_level=fnn_log_level, wait=False)
            add_cleanup(stop_agent, fiber.process)
        for fiber in fibers:
            fiber.wait_ready()
        if connect is not None:
            connect()
    except BaseException as error:
        for message in cleanup_owned_lsp_nodes(fibers, archive=archive, failure=error):
            error.add_note(f"node setup cleanup error: {message}")
        raise


class LspTestBase(FiberTest):
    tenant_labels = ("A", "B")
    gate_class = SignatureGate
    channel_open_options = {"commitment_delay_epoch": "0x10000000001"}
    tenant_rpc_timeout = 30
    agent_extra_args = ()
    # Extra keys written into the hosting FNN's `fiber:` section. Deadline suites
    # shorten the two opening timers here instead of changing a shared template.
    fiber_config_extra = {}
    # A reviewed suite may wrap only Public T; ordinary tests and payer P keep FNN.
    host_binary = None
    host_process_env = {}
    lsp_config_extra = {}
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
        require_runtime_inputs()
        manifest = validate_bundle()
        cls.bundle_manifest = manifest
        cls.bundle_manifest_sha256 = sha256_file(BUNDLE / BUNDLE_MANIFEST)
        print(
            f"LSP integration binaries: {manifest['fnn_version']}, "
            f"SDK source {REVISION}, bundle manifest {cls.bundle_manifest_sha256}"
        )
        for port in (8114, 8125, 8227, 8228, 8229, 8230):
            with socket.socket() as sock:
                assert (
                    sock.connect_ex(("127.0.0.1", port)) != 0
                ), f"test port {port} already in use"
        super().setup_class()

    @staticmethod
    def _failure_node_files(source):
        source = Path(source)
        return [
            relative
            for relative in ("node.log", "config.yml", "dev.toml")
            if (source / relative).is_file()
        ]

    def _failure_ckb_files(self):
        node = getattr(self, "node", None)
        ckb_dir = getattr(node, "ckb_dir", None)
        files = {}
        if ckb_dir:
            for relative in (
                "node.log",
                "data/logs/run.log",
                "ckb.miner.log",
                "ckb.toml",
                "ckb-miner.toml",
                "dev.toml",
            ):
                candidate = Path(ckb_dir) / relative
                if candidate.is_file():
                    files[relative] = candidate
        return files

    def _failure_archive_valid(self, root, fibers):
        """True only when this archive fully covers every current source node."""
        root = Path(root)
        manifest_path = root / "failure.json"
        if not manifest_path.is_file():
            return False
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            return False
        if manifest.get("archive_errors"):
            return False

        entries = {}
        for entry in manifest.get("nodes", []):
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            if isinstance(source, str):
                entries[source] = entry

        ckb_files = self._failure_ckb_files()
        recorded_ckb = manifest.get("ckb_files") or {}
        if set(recorded_ckb) != set(ckb_files):
            return False
        for relative in ckb_files:
            target = root / "ckb" / relative.replace("/", "-")
            try:
                if (
                    not target.is_file()
                    or sha256_file(target) != recorded_ckb[relative]
                ):
                    return False
            except OSError:
                return False

        for fiber in fibers:
            source = str(Path(fiber.tmp_path).resolve())
            entry = entries.get(source)
            if entry is None or not entry.get("complete"):
                return False
            directory_name = entry.get("dir")
            if (
                not isinstance(directory_name, str)
                or not directory_name
                or "/" in directory_name
                or "\\" in directory_name
            ):
                return False
            recorded_files = entry.get("files") or {}
            required = self._failure_node_files(source)
            if set(recorded_files) != set(required):
                return False
            for relative in required:
                target = root / directory_name / relative
                try:
                    if (
                        not target.is_file()
                        or sha256_file(target) != recorded_files[relative]
                    ):
                        return False
                except OSError:
                    return False
        return True

    def _archive_node_setup_failure(self, method_name, fibers, failure):
        """Copy minimal node logs/config/version before a failed setup deletes them.

        Reuse requires the same source-node path, the same required-file set, and
        archived bytes matching the hashes recorded in failure.json. Current
        source bytes are not re-hashed, so source content changes alone do not
        force a new archive. failure.json presence alone is never proof: a
        partial first copy or an archived subset of nodes forces a new sibling
        archive directory. Existing evidence directories are never rewritten.
        """
        evidence_dir = getattr(self, "evidence_dir", None)
        if evidence_dir is not None:
            base = Path(evidence_dir) / "setup-failure"
        else:
            base_env = os.environ.get("LSP_RUN_ARTIFACTS")
            base = Path(base_env) if base_env else Path(get_project_root()) / "report"
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            base = base / f"{method_name}-setup-failure-{stamp}-{os.getpid()}"

        directory = base
        suffix = 2
        while directory.exists():
            if self._failure_archive_valid(directory, fibers):
                self._setup_failure_archive = str(directory)
                return []
            directory = Path(f"{base}-{suffix}")
            suffix += 1
            if suffix > 50:
                return [f"no usable failure evidence directory for {base}"]

        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            return [f"create node failure evidence dir {directory}: {error!r}"]
        self._setup_failure_archive = str(directory)

        manifest = {
            "kind": "node-setup-failure",
            "method": method_name,
            "revision": REVISION,
            "bundle": str(BUNDLE),
            "bundle_manifest_sha256": getattr(
                type(self), "bundle_manifest_sha256", None
            ),
            "failure": repr(failure),
            "nodes": [],
            "ckb_files": {},
            "archive_errors": [],
        }

        for index, fiber in enumerate(fibers, 1):
            source = Path(fiber.tmp_path).resolve()
            directory_name = (
                "node-" + hashlib.sha256(str(source).encode()).hexdigest()[:12]
            )
            if (directory / directory_name).exists():
                directory_name = f"{directory_name}-{index}"
            node_dir = directory / directory_name
            process = getattr(fiber, "process", None)
            entry = {
                "source": str(source),
                "dir": directory_name,
                "complete": False,
                "files": {},
                "pid": getattr(process, "pid", None),
                "returncode": getattr(process, "returncode", None),
            }
            try:
                node_dir.mkdir(parents=True, exist_ok=False)
            except OSError as error:
                manifest["archive_errors"].append(f"create {node_dir}: {error!r}")
                manifest["nodes"].append(entry)
                continue
            node_errors = 0
            for relative in self._failure_node_files(source):
                target = node_dir / relative
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / relative, target)
                    entry["files"][relative] = sha256_file(target)
                except OSError as error:
                    node_errors += 1
                    manifest["archive_errors"].append(
                        f"copy {source / relative}: {error!r}"
                    )
            entry["complete"] = node_errors == 0
            manifest["nodes"].append(entry)

        for relative, candidate in self._failure_ckb_files().items():
            target = directory / "ckb" / relative.replace("/", "-")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
                manifest["ckb_files"][relative] = sha256_file(target)
            except OSError as error:
                manifest["archive_errors"].append(f"copy {candidate}: {error!r}")

        try:
            (directory / "failure.json").write_text(
                json.dumps(manifest, indent=2) + "\n"
            )
        except OSError as error:
            manifest["archive_errors"].append(f"write failure.json: {error!r}")
        print(f"node setup failure evidence: {directory}")
        return manifest["archive_errors"]

    def setup_method(self, method):
        # Keep FiberTest's fresh nodes, chain preparation and cleanup contract.
        started = time.monotonic()
        self.did_pass = None
        self.beginNum = hex(self.node.getClient().get_tip_block_number())
        self.fibers = []
        self.new_fibers = []
        self.fiber1 = LspFiber(
            self.fiber_version,
            self.account1_private_key,
            "fiber/node1",
            {
                "rpc_listening_addr": f"127.0.0.1:{self.fiber1_rpc_port}",
                "fiber_listening_addr": f"/ip4/127.0.0.1/tcp/{self.fiber1_p2p_port}",
            },
        )
        self.fiber2 = LspFiber(
            self.fiber_version,
            self.account2_private_key,
            "fiber/node2",
            {
                "rpc_listening_addr": f"127.0.0.1:{self.fiber2_rpc_port}",
                "fiber_listening_addr": f"/ip4/127.0.0.1/tcp/{self.fiber2_p2p_port}",
            },
        )
        self.fibers.extend((self.fiber1, self.fiber2))
        self.udtContract = UdtContract(XUDT_TX_HASH, 0)
        deploy_hash, deploy_index = self.udtContract.get_deploy_hash_and_index()
        self.node.getClient().clear_tx_pool()
        for _ in range(5):
            self.Miner.miner_with_version(self.node, "0x0")
        tx_hash = issue_udt_tx(
            self.udtContract,
            self.node.rpcUrl,
            self.account1_private_key,
            self.account1_private_key,
            1000 * 100000000,
        )
        self.Miner.miner_until_tx_committed(self.node, tx_hash)
        self.node.start_miner()
        update_config = {
            "ckb_rpc_url": self.node.rpcUrl,
            "ckb_udt_whitelist": True,
            "xudt_script_code_hash": self.Contract.get_ckb_contract_codehash(
                deploy_hash, deploy_index, True, self.node.rpcUrl
            ),
            "xudt_cell_deps_tx_hash": deploy_hash,
            "xudt_cell_deps_index": deploy_index,
            **self.start_fiber_config,
        }
        for fiber in self.fibers:
            fiber.prepare(update_config=update_config)

        # Configure Hosted LSP before the first start, avoiding a stop/start cycle.
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
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            ws_port = sock.getsockname()[1]
        self.ws_url = f"ws://127.0.0.1:{ws_port}"
        config = config.replace(
            "rpc:\n",
            "rpc:\n"
            f"  ws_listening_addr: 127.0.0.1:{ws_port}\n"
            f"  biscuit_public_key: {BISCUIT_PUBLIC_KEY}\n"
            f"  biscuit_private_key_path: {json.dumps(str(BUNDLE / 'biscuit-private-key'))}\n",
        )
        if self.fiber_config_extra:
            assert config.count("fiber:\n") == 1, "missing or repeated fiber section"
            extra = "".join(
                f"  {key}: {value}\n" for key, value in self.fiber_config_extra.items()
            )
            config = config.replace("fiber:\n", "fiber:\n" + extra, 1)
        lsp_options = {"max_active_tenants": 2, **self.lsp_config_extra}
        config_path.write_text(
            config
            + "\nlsp:\n"
            + "".join(f"  {key}: {value}\n" for key, value in lsp_options.items())
        )
        operator_token = (BUNDLE / "operator-token").read_text().strip()
        self.fiber1.client = FiberRPCClient(
            self.fiber1.client.url,
            {"Authorization": f"Bearer {operator_token}"},
            try_count=1,
            timeout=10,
        )
        # The nodes have independent stores and ports; start both before waiting.
        # LspFiber owns each direct child, avoiding the shared pid.txt path.
        node_start = time.monotonic()
        for fiber in self.fibers:
            if fiber is self.fiber1:
                fiber.binary = str(self.host_binary or BUNDLE / "fnn")
                fiber.process_env = dict(self.host_process_env)
            else:
                fiber.binary = str(BUNDLE / "fnn")
                fiber.process_env = {}
        start_owned_lsp_nodes(
            self.fibers,
            self.addCleanup,
            connect=lambda: self.fiber1.connect_peer(self.fiber2),
            fnn_log_level=self.fnn_log_level,
            archive=lambda fibers, failure: self._archive_node_setup_failure(
                method.__name__, fibers, failure
            ),
        )
        time.sleep(1)
        print(
            f"LSP nodes ready: startup={time.monotonic() - node_start:.2f}s, "
            f"setup={time.monotonic() - started:.2f}s"
        )

    def setUp(self):
        started = time.monotonic()
        self.public_key = self.fiber1.get_pubkey()
        config_path = Path(self.fiber1.fiber_config_path)
        operator_token = (BUNDLE / "operator-token").read_text().strip()
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
            subscription_proxy = SubscriptionProxy(self.ws_url)
            self.addCleanup(subscription_proxy.close)
            # Hold a new subscribe before the SDK can recover from a deliberately
            # unsent HTTP request. Other HTTP faults keep their natural timing.
            if isinstance(gate, RetrySignatureGate):
                gate.on_fault = lambda mode, proxy=subscription_proxy: (
                    proxy.pause_subscriptions() if mode == "disconnect" else None
                )
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                control_port = sock.getsockname()[1]
            log = (directory / "agent.log").open("w")
            self.addCleanup(log.close)
            agent_command = [
                str(BUNDLE / "lsp-integration-driver"),
                "--rpc",
                gate.url,
                "--ws-rpc",
                subscription_proxy.url,
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
                env={**os.environ, "LSP_NODE_ID": str(self.public_key)},
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
                "subscription_proxy": subscription_proxy,
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
        print(f"LSP tenants ready: {time.monotonic() - started:.2f}s")

    def _archive_run(self):
        """Keep successful-run evidence too, before the framework removes nodes."""
        destination = Path(os.environ["LSP_RUN_ARTIFACTS"]) / self._testMethodName
        destination.mkdir(parents=True, exist_ok=False)
        for tenant in getattr(self, "tenants", []):
            proxy = tenant["subscription_proxy"]
            with proxy.lock:
                streams = [
                    {
                        "started": link.started,
                        "requests": link.requests,
                        "responses": link.responses,
                        "subscriptions": link.subscriptions,
                        "delivered_events": link.delivered_events,
                        "errors": link.errors,
                    }
                    for link in proxy.connections()
                ]
                (destination / f"{tenant['label']}-ws.json").write_text(
                    json.dumps(streams, indent=2) + "\n"
                )
            if isinstance(tenant["gate"], RetrySignatureGate):
                (destination / f"{tenant['label']}-http.json").write_text(
                    json.dumps(tenant["gate"].audit_snapshot(), indent=2) + "\n"
                )
        for index, fiber in enumerate(getattr(self, "fibers", []), 1):
            if Path(fiber.tmp_path).exists():
                shutil.copytree(fiber.tmp_path, destination / f"fiber-{index}")
        for relative, name in (
            ("data/logs/run.log", "ckb.log"),
            ("node.log", "ckb-node.log"),
            ("ckb.miner.log", "ckb-miner.log"),
        ):
            source = Path(self.node.ckb_dir) / relative
            if source.exists():
                shutil.copy2(source, destination / name)

    def teardown_method(self, method):
        if not os.environ.get("LSP_RUN_ARTIFACTS"):
            return super().teardown_method(method)
        # Do not let the generic failure archiver replace an older report/<method>.
        try:
            self._archive_run()
        finally:
            for fiber in getattr(self, "fibers", []):
                fiber.force_stop()
                fiber.clean()

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
        self.subscription_proxy = self.tenant["subscription_proxy"]
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

    def _wait_for_fault_resubscription(self):
        """Observe this SDK's new subscribe attempt after the HTTP fault."""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.gate.errors, self.gate.errors
            assert not self.subscription_proxy.errors, self.subscription_proxy.errors
            fault_at = self.gate.fault_started
            if fault_at is not None:
                for (
                    at,
                    connection,
                    request,
                ) in self.subscription_proxy.subscribe_attempts():
                    if (
                        connection.started >= fault_at
                        and at >= fault_at
                        and request["params"][0] == "channel_signing"
                    ):
                        return at, connection, request
            time.sleep(0.1)
        assert False, "SDK did not reconnect and subscribe after the HTTP fault"

    def _wait_for_subscription_request(self, pending, after, timeout=60):
        """Require a new SDK connection, accepted subscription and exact delivery."""
        deadline = time.monotonic() + timeout
        expected = {
            "type": "channel_signing",
            "data": {"channel_id": self.channel_id, "status": pending},
        }
        while time.monotonic() < deadline:
            assert self.tenant["agent"].poll() is None
            assert not self.subscription_proxy.errors, self.subscription_proxy.errors
            for (
                accepted,
                connection,
                identity,
                topic,
            ) in self.subscription_proxy.successful_subscriptions():
                if (
                    connection.started < after
                    or accepted < after
                    or topic != "channel_signing"
                ):
                    continue
                for delivered, sub_id, event in connection.delivered_frames():
                    if (
                        delivered >= after
                        and type(sub_id) is type(identity)
                        and sub_id == identity
                        and event == expected
                    ):
                        return connection, identity
            time.sleep(0.1)
        assert False, f"new SDK subscription did not deliver original request {pending}"

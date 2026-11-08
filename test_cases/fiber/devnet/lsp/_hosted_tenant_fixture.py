"""Neutral lifecycle and evidence fixture shared by Hosted tenant suites.

Business helpers stay in the concrete suite; this module only owns class
isolation, preparation budgets, per-method evidence and cleanup deadlines.
"""

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time

import framework.config as framework_config
from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._isolated_contract import align_devnet_commitment_lock
from test_cases.fiber.devnet.lsp._lsp_test import (
    BUNDLE,
    REVISION,
    ChannelSigningTestBase,
)
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
    _DelayedPaymentBase,
)


def _command_text(command, timeout=5):
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _listener_pids(port):
    output = _command_text(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
    return sorted({int(line) for line in output.splitlines() if line.isdigit()})


def _pid_cwd(pid):
    try:
        output = subprocess.check_output(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines():
        if line.startswith("n"):
            return Path(line[1:]).resolve()
    return None


def _pid_command(pid):
    return _command_text(["ps", "-p", str(pid), "-o", "command="])


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # An unreaped child is a zombie: the process already exited even though
    # kill(pid, 0) still succeeds. Do not report it as a live listener/cleanup
    # failure; ps is the portable macOS/Linux check here.
    state = _command_text(["ps", "-p", str(pid), "-o", "stat="])
    if state.startswith("Z"):
        return False
    return True


def _wait_pid_gone(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)
    return not _pid_alive(pid)


def _port_open(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def _wait_port_closed(port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_open(port):
            return True
        time.sleep(0.2)
    return not _port_open(port)


def _pid_value(value):
    """Normalize the frame's historical PID representation, including str."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _verified_store(node):
    store = getattr(node, "_lsp_verified_ckb", None)
    if store is None:
        store = {}
        try:
            setattr(node, "_lsp_verified_ckb", store)
        except BaseException:
            pass
    return store


def _verify_and_stop_pid(pid, ckb_dir, label, store, errors):
    """Stop one PID only after cwd/command verification.

    A PID verified in an earlier cleanup call keeps that identity across
    repeated calls; if its identity is readable again it must still match.
    """
    try:
        command = _pid_command(pid)
        cwd = _pid_cwd(pid)
    except BaseException as error:
        errors.append(f"{label} pid {pid} identity check: {error!r}")
        return False
    stored = store.get(pid)
    if stored is not None:
        if command and cwd is not None:
            if command != stored["command"] or str(cwd) != stored["cwd"]:
                errors.append(f"refusing to stop {label} pid {pid}: identity changed")
                return False
    else:
        if not command or "ckb" not in command or cwd != ckb_dir:
            errors.append(f"refusing to stop unverified {label} pid {pid}")
            return False
        store[pid] = {"command": command, "cwd": str(cwd)}
    try:
        os.kill(pid, signal.SIGTERM)
        if not _wait_pid_gone(pid, 30):
            os.kill(pid, signal.SIGKILL)
            if not _wait_pid_gone(pid, 5):
                errors.append(f"{label} pid {pid} did not exit")
                return False
    except ProcessLookupError:
        pass
    except BaseException as error:
        errors.append(f"{label} pid {pid}: {error!r}")
        return False
    if _pid_alive(pid):
        errors.append(f"{label} pid {pid} is still alive")
        return False
    return True


def _stop_verified_ckb(node):
    """Stop the CKB node only when process identity can be verified.

    Returns cleanup errors instead of raising so the caller can still restore
    framework state and report the original preparation failure. A missing RPC
    listener is never treated as proof that the process exited.
    """
    errors = []
    ckb_dir = Path(node.ckb_dir).resolve()
    store = _verified_store(node)

    miner_pid = _pid_value(getattr(node, "ckb_miner_pid", -1))
    if miner_pid is not None and miner_pid > 0 and _pid_alive(miner_pid):
        stopped = _verify_and_stop_pid(miner_pid, ckb_dir, "CKB miner", store, errors)
        if stopped or not _pid_alive(miner_pid):
            node.ckb_miner_pid = -1

    port = int(str(node.rpcUrl).rsplit(":", 1)[1])
    listener_pids = set(_listener_pids(port))
    recorded_raw = getattr(node, "ckb_pid", -1)
    recorded = _pid_value(recorded_raw)
    if recorded is None and recorded_raw not in (-1, None, "", 0, "0", "-1"):
        errors.append(f"invalid recorded CKB pid: {recorded_raw!r}")

    candidates = set(listener_pids)
    if recorded is not None and recorded > 0:
        candidates.add(recorded)
    for pid in tuple(store):
        if _pid_alive(pid):
            candidates.add(pid)
        else:
            store.pop(pid, None)

    for pid in sorted(candidates):
        if _pid_alive(pid):
            _verify_and_stop_pid(pid, ckb_dir, "CKB", store, errors)

    # A process may close its RPC socket before it exits. Wait for both
    # conditions independently; never infer process exit from port closure.
    if listener_pids and _port_open(port):
        if not _wait_port_closed(port, 10):
            errors.append(f"CKB RPC port {port} is still open")
    for pid in tuple(store):
        if not _pid_alive(pid):
            store.pop(pid, None)
    return errors


class HostedTenantFixture(_DelayedPaymentBase):
    """Prepare an isolated CKB devnet and one A/B tenant fixture per method."""

    tenant_labels = ("A",)
    # Keep the budgets that these suites had before the split; a suite may
    # override them explicitly instead of inheriting another suite's values.
    preparation_budget = 240
    business_budget = 420
    row_budget = 480
    runtime_prefix = "lsp-cancel-"
    evidence_prefix = "lsp-hosted-"

    @classmethod
    def _runtime_dir(cls, root):
        name = getattr(cls, "tmp_path_name", None)
        if not name:
            return None
        root = Path(root).resolve()
        directory = (root / name).resolve()
        if directory == root or not directory.is_relative_to(root):
            return None
        return directory

    @classmethod
    def _remove_empty_runtime_dirs(cls, root):
        directory = cls._runtime_dir(root)
        if directory is None or not directory.exists():
            return
        # Preserve any unexpected remaining evidence; remove only empty parents.
        for child in (directory / "contract", directory / "fiber", directory):
            if child.exists() and not any(child.iterdir()):
                child.rmdir()

    @classmethod
    def _remove_runtime_dir(cls, root):
        directory = cls._runtime_dir(root)
        if directory is None:
            return [f"refusing to remove unexpected runtime path for {root}"]
        if not directory.exists():
            return []
        try:
            shutil.rmtree(directory)
        except OSError as error:
            return [f"remove {directory}: {error!r}"]
        return []

    @classmethod
    def _archive_class_setup_failure(cls, root, failure):
        """Preserve the minimal class-setup failure evidence before deletion."""
        errors = []
        directory = None
        try:
            base_env = os.environ.get("LSP_PAYMENT_REPORT_DIR")
            base = Path(base_env).resolve() if base_env else Path(root) / "report"
            base.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            directory = base / (
                f"{cls.__name__}-class-setup-failure-{stamp}-{os.getpid()}"
            )
            directory.mkdir(parents=True, exist_ok=False)
        except BaseException as error:
            return [f"create class failure evidence dir: {error!r}"], None

        def copy(source, target):
            try:
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            except OSError as error:
                errors.append(f"copy {source}: {error!r}")

        runtime = cls._runtime_dir(root)
        if runtime is not None:
            for relative in (
                "contract/node/node.log",
                "contract/node/ckb.toml",
                "contract/node/ckb-miner.toml",
                "contract/node/dev.toml",
                "contract/node/data/logs/run.log",
                "contract/node/ckb.miner.log",
            ):
                copy(runtime / relative, directory / relative)

        node = getattr(cls, "node", None)
        if node is not None:
            for relative in (
                "node.log",
                "data/logs/run.log",
                "ckb.miner.log",
                "ckb.toml",
                "ckb-miner.toml",
                "dev.toml",
            ):
                copy(
                    Path(node.ckb_dir) / relative,
                    directory / "ckb" / relative.replace("/", "-"),
                )

        metadata = {
            "kind": "class-setup-failure",
            "test_class": cls.__name__,
            "revision": REVISION,
            "bundle": str(BUNDLE),
            "bundle_manifest_sha256": getattr(cls, "bundle_manifest_sha256", None),
            "runtime_dir": str(runtime) if runtime is not None else None,
            "ckb_dir": str(node.ckb_dir) if node is not None else None,
            "ckb_pid": (
                str(getattr(node, "ckb_pid", None)) if node is not None else None
            ),
            "failure": repr(failure),
        }
        try:
            (directory / "failure.json").write_text(
                json.dumps(metadata, indent=2) + "\n"
            )
        except OSError as error:
            errors.append(f"write failure.json: {error!r}")
        return errors, directory

    @classmethod
    def _recover_failed_setup(cls, root, failure=None):
        """Idempotently stop verified resources, archive evidence, then clean."""
        errors = []
        node = getattr(cls, "node", None)
        if node is not None:
            try:
                errors.extend(_stop_verified_ckb(node))
            except BaseException as error:
                errors.append(f"CKB cleanup: {error!r}")

        if not errors:
            runtime = cls._runtime_dir(root)
            archive = getattr(cls, "_hosted_failure_archive", None)
            if runtime is not None and runtime.exists():
                if archive is None:
                    archive_errors, directory = cls._archive_class_setup_failure(
                        root, failure
                    )
                    if archive_errors:
                        errors.extend(archive_errors)
                    elif directory is not None:
                        cls._hosted_failure_archive = str(directory)
                elif not Path(archive).exists():
                    errors.append(f"class failure evidence is missing: {archive}")

        if not errors and node is not None:
            try:
                node.clean()
            except BaseException as error:
                errors.append(f"clean {node.ckb_dir}: {error!r}")
        if not errors:
            errors.extend(cls._remove_runtime_dir(root))

        original = getattr(cls, "_hosted_original_tmp", None)
        if original is not None:
            try:
                framework_config.TMP_PATH = original
            except BaseException as error:
                errors.append(f"restore TMP_PATH: {error!r}")
        return errors

    @classmethod
    def setup_class(cls):
        root = Path(get_project_root()).resolve()
        cls._hosted_original_tmp = framework_config.TMP_PATH
        cls._hosted_setup_failed = False
        cls._hosted_failure_archive = None
        try:
            (root / "tmp").mkdir(exist_ok=True)
            cls.tmp_path_name = str(
                Path(
                    tempfile.mkdtemp(prefix=cls.runtime_prefix, dir=root / "tmp")
                ).relative_to(root)
            )
            super().setup_class()
            report_root = Path(
                os.environ.get("LSP_PAYMENT_REPORT_DIR", root / "report")
            ).resolve()
            report_root.mkdir(parents=True, exist_ok=True)
            align_devnet_commitment_lock(
                cls, report_root / f"{cls.__name__}-isolated-contract.json"
            )
        except BaseException as error:
            cls._hosted_setup_failed = True
            for message in cls._recover_failed_setup(root, error):
                error.add_note(f"class setup cleanup error: {message}")
            archive = getattr(cls, "_hosted_failure_archive", None)
            if archive is not None:
                error.add_note(f"class setup failure evidence: {archive}")
            raise

    @classmethod
    def teardown_class(cls):
        if getattr(cls, "_hosted_setup_failed", False):
            # Never fall back to the framework's port-based kill after a failed
            # class setup; retry only the identity-verified cleanup instead.
            for message in cls._recover_failed_setup(
                Path(get_project_root()).resolve()
            ):
                print(f"class setup cleanup warning: {message}")
            archive = getattr(cls, "_hosted_failure_archive", None)
            if archive is not None:
                print(f"class setup failure evidence: {archive}")
            return
        super().teardown_class()
        cls._remove_empty_runtime_dirs(Path(get_project_root()).resolve())

    def setup_method(self, method):
        self.preparation_started = time.monotonic()
        self.preparation_until = self.preparation_started + self.preparation_budget
        self.business_until = self.preparation_started + self.business_budget
        self.row_until = self.preparation_started + self.row_budget
        root = os.environ.get("LSP_PAYMENT_REPORT_DIR")
        if root is None:
            Path("report").mkdir(exist_ok=True)
            root = tempfile.mkdtemp(prefix=self.evidence_prefix, dir="report")
        self.evidence_dir = Path(root).resolve() / method.__name__
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        self.result = "incomplete"
        self.offline = False
        self.payments = {}
        self._record(
            "environment_start",
            revision=REVISION,
            bundle=str(BUNDLE),
            bundle_manifest_sha256=getattr(type(self), "bundle_manifest_sha256", None),
            preparation_until=self.preparation_until,
            business_until=self.business_until,
            row_until=self.row_until,
        )
        self.addCleanup(self._archive)
        try:
            with self._budget(self.preparation_until, self.preparation_budget):
                # This suite's own setup_method owns preparation; keep the
                # framework/tenant lifecycle below it.
                ChannelSigningTestBase.setup_method(self, method)
        except BaseException:
            self.doCleanups()
            raise

    def setUp(self):
        super().setUp()
        for tenant in self.tenants:
            tenant["gate"].release()
        self._record(
            "hosted_fixture_ready",
            tenant_ids={
                t["label"]: json.loads(t["status_file"].read_text())["tenant_id"]
                for t in self.tenants
            },
        )

    def _prepare_invoice(self, tenant, amount):
        # Hosted suites create hash-only invoices per scenario instead of
        # inheriting the delayed-payment fixture's preimage-bearing invoice.
        pass

    def doCleanups(self):
        self.business_until = float("inf")
        self.cleanup_until = min(self.row_until, time.monotonic() + 60)
        first_error = None
        while self._cleanups:
            if time.monotonic() >= self.cleanup_until:
                self._record(
                    "cleanup_deadline",
                    remaining=[item[0].__name__ for item in self._cleanups],
                )
                raise AssertionError("hosted fixture cleanup deadline exhausted")
            function, args, kwargs = self._cleanups.pop()
            try:
                # Re-arm the same absolute deadline for every callback.
                with self._budget(self.cleanup_until, 60):
                    self._callCleanup(function, *args, **kwargs)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
        return True

    def teardown_method(self, method):
        self.cleanup_until = min(
            self.row_until,
            getattr(self, "cleanup_until", self.row_until),
            time.monotonic() + 60,
        )
        return super().teardown_method(method)

"""Isolate batch runtimes and copy raw logs before native fixture teardown."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from scripts.lsp_parallel import PILOT_CLASSES, validate_ports
from scripts.lsp_ci_progress import emit
from framework.test_node import CkbNode
from framework.test_fiber import Fiber
from framework.util import get_ckb_configs


def install_runtime_retention():
    """CI-only: retain stores for export, preserving all native stop callbacks."""
    from framework.util import get_project_root
    from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import HostedTenantFixture

    root = Path(get_project_root()).resolve()

    def preserve(path):
        path = Path(path).resolve()
        if (
            not path.is_relative_to(root / "tmp")
            or path == root / "tmp"
            or not path.relative_to(root / "tmp").parts[0].startswith("lsp-")
        ):
            raise RuntimeError(f"refusing to retain unrelated runtime: {path}")
        destination = Path(os.environ["LSP_REGRESSION_CASE"]) / "retained-paths.jsonl"
        with destination.open("a") as stream:
            stream.write(json.dumps({"path": str(path)}) + "\n")

    CkbNode.clean = lambda node: preserve(node.ckb_dir)
    Fiber.clean = lambda node: preserve(node.tmp_path)

    def keep_failed_setup(cls, root):
        runtime = cls._runtime_dir(root)
        if runtime is not None:
            preserve(runtime)
        return []

    HostedTenantFixture._remove_runtime_dir = classmethod(keep_failed_setup)


class PilotCkbNode(CkbNode):
    """Own the pilot/CI CKB child directly, without the legacy global pid.txt."""

    @classmethod
    def init_dev_by_port(cls, config, directory, rpc_port, p2p_port):
        return cls(config, directory, *get_ckb_configs(p2p_port, rpc_port))

    def start(self):
        with (Path(self.ckb_dir) / "node.log").open("w") as log:
            self._lsp_process = subprocess.Popen(
                ["./ckb", "run", "--indexer", "--skip-spec-check"],
                cwd=self.ckb_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        self.ckb_pid = self._lsp_process.pid
        time.sleep(3)  # Preserve the framework's existing startup wait.

    def stop(self):
        self.stop_miner()
        process = getattr(self, "_lsp_process", None)
        if process is not None:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=30)
        self.ckb_pid = -1


def pytest_runtest_logstart(nodeid, location):
    emit("start", nodeid)


def pytest_runtest_logreport(report):
    detail = (
        str(getattr(report, "longrepr", ""))[:4000]
        if getattr(report, "failed", False)
        else ""
    )
    emit(
        "phase", report.nodeid, phase=report.when, outcome=report.outcome, detail=detail
    )


def pytest_runtest_logfinish(nodeid, location):
    emit("finish", nodeid)


def pytest_collection_modifyitems(items):
    expected = json.loads(os.environ["LSP_REGRESSION_SELECTORS"])
    if [item.nodeid for item in items] != expected:
        raise ValueError("native selection/order differs from the serial job plan")
    if os.environ.get("LSP_REGRESSION_RETAIN") == "1":
        install_runtime_retention()
    raw_ports = os.environ.get("LSP_REGRESSION_PORTS")
    ports = validate_ports(json.loads(raw_ports)) if raw_ports is not None else None
    if ports is not None and any(
        item.cls.__name__ not in PILOT_CLASSES for item in items
    ):
        raise ValueError(
            "port remapping is only qualified for browser/filter pilot classes"
        )
    for item in items:
        item.cls.tmp_path_name = os.environ["LSP_REGRESSION_RUNTIME"]
        if os.environ.get("LSP_REGRESSION_RETAIN") == "1":
            item.cls.CkbNode = PilotCkbNode
        if ports is not None:
            item.cls.CkbNode = PilotCkbNode
            item.cls._lsp_parallel = True
            for name, port in ports.items():
                setattr(item.cls, name, port)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    case = getattr(item, "instance", None)
    if case is not None and (
        getattr(case, "_node_mode", "independent") == "shared"
        or getattr(case, "_node_keep", False)
    ):
        if report.when == "call":
            case._node_case_passed = report.passed
        if report.failed or report.skipped:
            type(case)._node_failed = True


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    errors, sources = [], []
    instance = None
    try:
        instance = getattr(item, "instance", None)
        node = getattr(item.cls, "node", None)
        if node is not None:
            sources.append(("ckb", Path(node.ckb_dir)))
        for index, fiber in enumerate(getattr(instance, "fibers", [])):
            sources.append((f"fiber-{index}", Path(fiber.tmp_path)))
        directory = (
            Path(os.environ["LSP_REGRESSION_CASE"]) / "before-teardown" / item.name
        )
        directory.mkdir(parents=True, exist_ok=False)
        for label, source in sources:
            for relative in (
                "node.log",
                "config.yml",
                "ckb.toml",
                "ckb-miner.toml",
                "dev.toml",
                "data/logs/run.log",
                "ckb.miner.log",
            ):
                path = source / relative
                if path.is_file():
                    try:
                        target = directory / label / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
                    except OSError as error:
                        errors.append(f"{path}: {error!r}")
        (directory / "runtime.json").write_text(
            json.dumps(
                {
                    "sources": [(label, str(path)) for label, path in sources],
                    "worker": os.environ.get("LSP_REGRESSION_WORKER"),
                    "port_map": json.loads(
                        os.environ.get("LSP_REGRESSION_PORTS", "null")
                    ),
                    "actual_endpoints": {
                        "ckb": getattr(node, "rpcUrl", None),
                        "fibers": [
                            getattr(getattr(f, "client", None), "url", None)
                            for f in getattr(instance, "fibers", [])
                        ],
                        "ws": getattr(instance, "ws_url", None),
                    },
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
    except Exception as error:
        errors.append(repr(error))
    # Mark the owner before fixture/class teardown, including on the last case.
    if (
        errors
        and instance is not None
        and (
            getattr(instance, "_node_mode", "independent") == "shared"
            or getattr(instance, "_node_keep", False)
        )
    ):
        type(instance)._node_failed = True
    # Evidence failures must never prevent the fixture's own resource cleanup.
    yield
    if errors:
        raise RuntimeError(f"raw evidence copy failed: {errors}")

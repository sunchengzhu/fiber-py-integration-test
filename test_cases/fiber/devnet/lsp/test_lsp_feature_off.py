"""Build/start boundary for a fiber-bin compiled without the optional lsp feature."""

import hashlib
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from types import SimpleNamespace

import requests

from framework.basic_fiber import FiberTest
from framework.test_fiber import Fiber, FiberConfigPath
from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._lsp_test import REVISION


class TestLspFeatureOff(FiberTest):
    """No hosted LSP service, but the ordinary Fiber node must still run."""

    fiber_rpc_port = "8248"
    fiber_p2p_port = "8249"

    def setup_method(self, method):
        binary = Path(os.environ["LSP_NOLSP_FNN"]).resolve()
        assert binary.is_file(), binary
        self.binary = binary
        relative = os.path.relpath(binary, get_project_root())
        version = SimpleNamespace(
            fiber_config_path=FiberConfigPath.CURRENT_DEV.fiber_config_path,
            fiber_bin_path=relative,
        )
        self.fiber = Fiber.init_by_port(
            version,
            self.account1_private_key,
            "fiber/nolsp",
            self.fiber_rpc_port,
            self.fiber_p2p_port,
        )
        self.fiber.prepare(update_config={"ckb_rpc_url": self.node.rpcUrl})
        self.fiber_started = False
        self.config_process = None

    def teardown_method(self, method):
        try:
            if self.fiber_started:
                self.fiber.stop()
        finally:
            self._stop_config_process()
            self.fiber.clean()

    def _stop_config_process(self):
        process = self.config_process
        self.config_process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _assert_ports_free(self):
        for port in (self.fiber_rpc_port, self.fiber_p2p_port):
            with socket.socket() as sock:
                assert (
                    sock.connect_ex(("127.0.0.1", int(port))) != 0
                ), f"port {port} is already in use; refusing to disturb an unrelated process"

    def _run_feature_off_probe(self):
        """Prove the binary rejects an lsp service before any RPC listener starts."""
        self._assert_ports_free()
        config_path = Path(self.fiber.fiber_config_path)
        source = config_path.read_text()
        assert source.count("services:\n") == 1
        config = source.replace("services:\n", "services:\n  - lsp\n", 1)
        config += "\nlsp:\n  max_active_tenants: 2\n"
        config_path.write_text(config)
        try:
            with tempfile.TemporaryDirectory(prefix="lsp-feature-off-logs-") as logs:
                stdout_path = Path(logs) / "stdout.log"
                stderr_path = Path(logs) / "stderr.log"
                with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
                    process = subprocess.Popen(
                        [
                            str(self.binary),
                            "-c",
                            str(config_path),
                            "-d",
                            self.fiber.tmp_path,
                        ],
                        stdout=stdout,
                        stderr=stderr,
                        text=True,
                        env={
                            **os.environ,
                            "FIBER_SECRET_KEY_PASSWORD": "password0",
                            "RUST_LOG": "info,fnn=debug",
                        },
                    )
                    self.config_process = process
                    listened = False
                    deadline = time.monotonic() + 60
                    try:
                        while process.poll() is None:
                            with socket.socket() as sock:
                                if (
                                    sock.connect_ex(
                                        ("127.0.0.1", int(self.fiber_rpc_port))
                                    )
                                    == 0
                                ):
                                    listened = True
                                    break
                            assert (
                                time.monotonic() < deadline
                            ), "feature-off probe did not exit"
                            time.sleep(0.05)
                        if process.poll() is None:
                            self._stop_config_process()
                        process.wait(timeout=10)
                    finally:
                        self._stop_config_process()
                combined = stdout_path.read_text() + stderr_path.read_text()
            assert (
                not listened
            ), f"binary listened on RPC before rejecting lsp: {combined}"
            assert process.returncode != 0, (process.returncode, combined)
            assert "built without the `lsp` feature" in combined, combined
            assert "biscuit" not in combined.lower(), combined
            with socket.socket() as sock:
                assert sock.connect_ex(("127.0.0.1", int(self.fiber_rpc_port))) != 0
            return combined
        finally:
            self._stop_config_process()
            config_path.write_text(source)

    def _assert_binary_provenance(self):
        version = subprocess.check_output(
            [str(self.binary), "--version"], text=True, timeout=15
        )
        assert REVISION[:7] in version and "dirty" not in version, version
        expected = os.environ.get("LSP_NOLSP_FNN_SHA256")
        if expected:
            actual = hashlib.sha256(self.binary.read_bytes()).hexdigest()
            assert actual == expected, (actual, expected)

    def _rpc_raw(self, method, params):
        response = requests.post(
            self.fiber.client.url,
            headers=self.fiber.client.other_params,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    # TEST-MAP: LSP-FEATURE-01
    def test_without_lsp_feature_starts_ordinary_node(self):
        """
        1. 无 lsp feature 构建以普通 devnet 配置启动。
        2. 普通 RPC 可用，hosted LSP RPC 不存在，日志没有 LSP service 启动。
        """
        self._assert_binary_provenance()
        self._run_feature_off_probe()
        self._assert_ports_free()
        self.fiber_started = True
        self.fiber.start()
        node = self.fiber.client.call("node_info", [])
        assert node["pubkey"], node
        assert self.fiber.client.call("list_channels", [{}])["channels"] == []
        self.fiber.client.call("list_peers", [])

        body = self._rpc_raw("lsp_get_status", [])
        assert body["error"]["code"] == -32601, body
        log = (Path(self.fiber.tmp_path) / "node.log").read_text()
        assert "Starting multi-tenant LSP service" not in log

    # TEST-MAP: LSP-FEATURE-02
    def test_lsp_config_is_rejected_before_rpc(self):
        """
        1. 同一无 lsp 构建，services 显式含 lsp 并配置 lsp 段。
        2. 进程在 RPC 监听前退出，错误明确说明构建时没有 lsp feature。
        """
        self._assert_binary_provenance()
        self._run_feature_off_probe()

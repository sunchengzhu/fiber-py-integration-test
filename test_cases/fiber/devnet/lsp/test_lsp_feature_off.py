"""Build/start boundary for a fiber-bin compiled without the optional lsp feature."""

import hashlib
import os
from pathlib import Path
import socket
import subprocess
import time
from types import SimpleNamespace

import requests

from framework.basic_fiber import FiberTest
from framework.test_fiber import Fiber, FiberConfigPath, wait_for_port
from framework.util import get_project_root


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

    def teardown_method(self, method):
        # Case 2 exits before listening; stop() handles both started and already gone.
        self.fiber.stop()
        self.fiber.clean()

    def _assert_binary_provenance(self):
        version = subprocess.check_output(
            [str(self.binary), "--version"], text=True, timeout=15
        )
        assert "56c761c" in version, version
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
        config_path = Path(self.fiber.fiber_config_path)
        config = config_path.read_text()
        assert config.count("services:\n") == 1
        config = config.replace("services:\n", "services:\n  - lsp\n", 1)
        config += "\nlsp:\n  max_active_tenants: 2\n"
        config_path.write_text(config)

        process = subprocess.Popen(
            [
                str(self.binary),
                "-c",
                str(config_path),
                "-d",
                self.fiber.tmp_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                "FIBER_SECRET_KEY_PASSWORD": "password0",
                "RUST_LOG": "info,fnn=debug",
            },
        )
        out, err = process.communicate(timeout=60)
        assert process.returncode != 0, (process.returncode, out, err)
        combined = out + err
        assert "built without the `lsp` feature" in combined, combined
        assert "biscuit" not in combined.lower(), combined
        with socket.socket() as sock:
            assert sock.connect_ex(("127.0.0.1", int(self.fiber.rpc_port))) != 0

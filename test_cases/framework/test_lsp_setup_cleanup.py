"""Offline engineering checks for LSP setup recovery and entry gates.

These checks use short local processes and fakes; they never start CKB or FNN.
They assert observable cleanup/refusal behaviour, not business cases.
"""

import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

import framework.config as framework_config
import test_cases.fiber.devnet.lsp._hosted_tenant_fixture as hosted_fixture
import test_cases.fiber.devnet.lsp._lsp_test as lsp_test
import test_cases.fiber.devnet.lsp.test_hosted_outbound_payment as payment05
import test_cases.fiber.devnet.lsp.test_payment_authorization_recovery as payment04


class _FakeFiber:
    def __init__(
        self,
        tmp_path,
        process=None,
        start_error=None,
        ready_error=None,
        stop_error=None,
        clean_error=None,
    ):
        self.tmp_path = str(tmp_path)
        self.rpc_port = 0
        self.process = process
        self.start_error = start_error
        self.ready_error = ready_error
        self.stop_error = stop_error
        self.clean_error = clean_error
        self.cleaned = False

    def start(self, fnn_log_level="debug", wait=False):
        if self.start_error is not None:
            raise self.start_error

    def wait_ready(self):
        if self.ready_error is not None:
            raise self.ready_error

    def force_stop(self):
        if self.stop_error is not None:
            raise self.stop_error
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)

    def clean(self):
        if self.clean_error is not None:
            raise self.clean_error
        self.cleaned = True
        import shutil

        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def _port_is_open(self):
        return False


def _sleeper():
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop(process):
    if process is not None and process.poll() is None:
        process.kill()
        process.wait(timeout=5)


def test_partial_start_failure_cleans_owned_nodes_and_is_idempotent(tmp_path):
    first = _sleeper()
    fiber1 = _FakeFiber(tmp_path / "node1", process=first)
    fiber2 = _FakeFiber(tmp_path / "node2", start_error=RuntimeError("second start"))
    registered = []
    try:
        with pytest.raises(RuntimeError, match="second start"):
            lsp_test.start_owned_lsp_nodes(
                [fiber1, fiber2], lambda function, argument: registered.append(function)
            )
        assert first.poll() is not None
        assert fiber1.cleaned and fiber2.cleaned
        assert lsp_test.cleanup_owned_lsp_nodes([fiber1, fiber2]) == []
        assert lsp_test.cleanup_owned_lsp_nodes([fiber1, fiber2]) == []
    finally:
        _stop(first)


def test_wait_ready_failure_cleans_both_owned_nodes(tmp_path):
    first, second = _sleeper(), _sleeper()
    fiber1 = _FakeFiber(tmp_path / "node1", process=first)
    fiber2 = _FakeFiber(
        tmp_path / "node2", process=second, ready_error=RuntimeError("ready timeout")
    )
    try:
        with pytest.raises(RuntimeError, match="ready timeout"):
            lsp_test.start_owned_lsp_nodes(
                [fiber1, fiber2], lambda function, argument: None
            )
        assert first.poll() is not None and second.poll() is not None
        assert fiber1.cleaned and fiber2.cleaned
    finally:
        _stop(first)
        _stop(second)


def test_one_cleanup_failure_does_not_block_other_owned_nodes(tmp_path):
    first, second = _sleeper(), _sleeper()
    fiber1 = _FakeFiber(
        tmp_path / "node1", process=first, stop_error=RuntimeError("cannot stop")
    )
    fiber2 = _FakeFiber(tmp_path / "node2", process=second)
    try:
        errors = lsp_test.cleanup_owned_lsp_nodes([fiber1, fiber2])
        assert len(errors) == 1 and "cannot stop" in errors[0]
        assert second.poll() is not None
        assert fiber2.cleaned
        assert not fiber1.cleaned
        assert first.poll() is None
    finally:
        _stop(first)
        _stop(second)


class _FakeNode:
    def __init__(self, ckb_dir, rpc_url, ckb_pid=-1):
        self.ckb_dir = str(ckb_dir)
        self.rpcUrl = rpc_url
        self.ckb_miner_pid = -1
        self.ckb_pid = ckb_pid
        self.cleaned = False

    def clean(self):
        self.cleaned = True
        import shutil

        shutil.rmtree(self.ckb_dir, ignore_errors=True)


class _FakeFixture(hosted_fixture.HostedTenantFixture):
    pass


def _spawn_listener(directory, port_file):
    code = """
import socket, sys, time
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", 0))
sock.listen()
open(sys.argv[1], "w").write(str(sock.getsockname()[1]))
time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(port_file)],
        cwd=directory,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if port_file.is_file():
                return process, int(port_file.read_text())
            assert process.poll() is None, "listener exited before reporting its port"
            time.sleep(0.05)
        raise AssertionError("listener did not report a port")
    except BaseException:
        _stop(process)
        raise


def test_failed_class_setup_stops_verified_ckb_and_restores_tmp_path(
    tmp_path, monkeypatch
):
    root = tmp_path
    runtime = root / "run"
    runtime.mkdir()
    port_file = runtime / "port"
    process, port = _spawn_listener(runtime, port_file)
    node = _FakeNode(runtime, f"http://127.0.0.1:{port}")
    evidence = root / "evidence"
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(evidence))
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = node
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setattr(framework_config, "TMP_PATH", "changed-tmp")
    # The listener is a short Python stand-in; only its command identity is faked.
    monkeypatch.setattr(hosted_fixture, "_pid_command", lambda pid: "ckb run")
    try:
        assert _FakeFixture._recover_failed_setup(root) == []
        assert process.poll() is not None
        assert framework_config.TMP_PATH == "original-tmp"
        assert not runtime.exists()
        assert list(evidence.glob("*-class-setup-failure-*"))
        assert _FakeFixture._recover_failed_setup(root) == []
    finally:
        _stop(process)
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


def test_failed_class_setup_never_kills_unverified_listener(tmp_path, monkeypatch):
    root = tmp_path
    runtime = root / "run"
    runtime.mkdir()
    other = root / "other"
    other.mkdir()
    port_file = root / "port"
    process, port = _spawn_listener(other, port_file)
    node = _FakeNode(runtime, f"http://127.0.0.1:{port}")
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = node
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(root / "evidence"))
    monkeypatch.setattr(framework_config, "TMP_PATH", "changed-tmp")
    monkeypatch.setattr(hosted_fixture, "_pid_command", lambda pid: "ckb run")
    try:
        errors = _FakeFixture._recover_failed_setup(root)
        assert errors and "unverified" in errors[0]
        assert process.poll() is None
        assert framework_config.TMP_PATH == "original-tmp"
        assert runtime.exists()
    finally:
        _stop(process)
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


class _Harness(lsp_test.LspTestBase):
    def __init__(self):
        self.evidence_dir = None
        self.node = None
        self._setup_failure_archive = None


def _wait_port_open(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"port {port} did not open")


def test_failed_class_setup_keeps_original_error_and_archive_path(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "evidence"
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(evidence))
    _FakeFixture.tmp_path_name = None
    _FakeFixture.node = None
    _FakeFixture._hosted_failure_archive = None
    _FakeFixture._hosted_setup_failed = False
    monkeypatch.setattr(
        lsp_test.LspTestBase,
        "setup_class",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("setup boom"))),
    )
    try:
        with pytest.raises(RuntimeError, match="setup boom") as captured:
            _FakeFixture.setup_class()
        notes = "\n".join(getattr(captured.value, "__notes__", []))
        assert "class setup failure evidence:" in notes
        assert "setup boom" in str(captured.value)
        runtime_name = _FakeFixture.tmp_path_name
        assert runtime_name
        assert not (Path(hosted_fixture.get_project_root()) / runtime_name).exists()
        archives = list(evidence.glob("*-class-setup-failure-*"))
        assert len(archives) == 1
        failure = json.loads((archives[0] / "failure.json").read_text())
        assert "setup boom" in failure["failure"]
    finally:
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None
        _FakeFixture._hosted_setup_failed = False


def test_class_setup_archives_unique_diagnostic_before_cleanup(tmp_path, monkeypatch):
    root = tmp_path
    runtime = root / "run"
    node_dir = runtime / "contract" / "node"
    node_dir.mkdir(parents=True)
    (node_dir / "node.log").write_text("UNIQUE-CLASS-SETUP-LOG\n")
    (node_dir / "ckb.toml").write_text("UNIQUE-CLASS-SETUP-CONFIG\n")
    evidence = root / "evidence"
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(evidence))
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = _FakeNode(node_dir, "http://127.0.0.1:1")
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setattr(framework_config, "TMP_PATH", "changed-tmp")
    try:
        errors = _FakeFixture._recover_failed_setup(
            root, RuntimeError("contract alignment failed")
        )
        assert errors == []
        assert not runtime.exists()
        archives = list(evidence.glob("*-class-setup-failure-*"))
        assert len(archives) == 1
        archive = archives[0]
        assert "UNIQUE-CLASS-SETUP-LOG" in (archive / "ckb" / "node.log").read_text()
        assert "UNIQUE-CLASS-SETUP-CONFIG" in (archive / "ckb" / "ckb.toml").read_text()
        failure = json.loads((archive / "failure.json").read_text())
        assert "contract alignment failed" in failure["failure"]
        assert failure["revision"]
        assert framework_config.TMP_PATH == "original-tmp"
    finally:
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


def test_class_setup_archive_failure_keeps_runtime_and_reports(tmp_path, monkeypatch):
    root = tmp_path
    runtime = root / "run"
    node_dir = runtime / "contract" / "node"
    node_dir.mkdir(parents=True)
    (node_dir / "node.log").write_text("PRESERVED-AFTER-ARCHIVE-FAILURE\n")
    evidence = root / "evidence"
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(evidence))
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = _FakeNode(node_dir, "http://127.0.0.1:1")
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setattr(framework_config, "TMP_PATH", "changed-tmp")
    monkeypatch.setattr(
        _FakeFixture,
        "_archive_class_setup_failure",
        classmethod(lambda cls, root, failure: (["archive failed"], None)),
    )
    try:
        errors = _FakeFixture._recover_failed_setup(root, RuntimeError("boom"))
        assert errors and "archive failed" in errors[0]
        assert runtime.exists()
        assert "PRESERVED-AFTER-ARCHIVE-FAILURE" in (node_dir / "node.log").read_text()
        assert framework_config.TMP_PATH == "original-tmp"
        assert _FakeFixture._hosted_failure_archive is None
    finally:
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


def test_node_setup_failure_archives_logs_before_deleting(tmp_path):
    evidence = tmp_path / "business" / "method"
    evidence.mkdir(parents=True)
    ckb_dir = tmp_path / "ckb"
    ckb_dir.mkdir()
    (ckb_dir / "node.log").write_text("UNIQUE-CKB-LOG\n")
    fiber_dir = tmp_path / "fiber"
    fiber_dir.mkdir()
    (fiber_dir / "node.log").write_text("UNIQUE-FNN-LOG\n")
    (fiber_dir / "config.yml").write_text("UNIQUE-FNN-CONFIG\n")
    harness = _Harness()
    harness.evidence_dir = evidence
    harness.node = _FakeNode(ckb_dir, "http://127.0.0.1:1")
    fiber = _FakeFiber(fiber_dir, start_error=RuntimeError("start boom"))
    archive = lambda fibers, failure: harness._archive_node_setup_failure(
        "method", fibers, failure
    )
    with pytest.raises(RuntimeError, match="start boom"):
        lsp_test.start_owned_lsp_nodes(
            [fiber], lambda function, argument: None, archive=archive
        )
    assert not fiber_dir.exists()
    archive_dir = evidence / "setup-failure"
    failure = json.loads((archive_dir / "failure.json").read_text())
    assert "start boom" in failure["failure"]
    assert failure["archive_errors"] == []
    entry = next(
        item for item in failure["nodes"] if Path(item["source"]) == fiber_dir.resolve()
    )
    assert entry["complete"] is True
    archived = archive_dir / entry["dir"]
    assert "UNIQUE-FNN-LOG" in (archived / "node.log").read_text()
    assert "UNIQUE-FNN-CONFIG" in (archived / "config.yml").read_text()
    assert "UNIQUE-CKB-LOG" in (archive_dir / "ckb" / "node.log").read_text()
    assert lsp_test.cleanup_owned_lsp_nodes([fiber], archive=archive) == []
    assert len(list(evidence.glob("setup-failure*"))) == 1


def test_repeated_cleanup_reuses_archive_and_removes_remaining_dir(tmp_path):
    evidence = tmp_path / "business" / "method"
    evidence.mkdir(parents=True)
    ckb_dir = tmp_path / "ckb"
    ckb_dir.mkdir()
    (ckb_dir / "node.log").write_text("REPEAT-CLEANUP-CKB\n")
    fiber_dir = tmp_path / "fiber"
    fiber_dir.mkdir()
    (fiber_dir / "node.log").write_text("REPEAT-CLEANUP-FNN\n")
    harness = _Harness()
    harness.evidence_dir = evidence
    harness.node = _FakeNode(ckb_dir, "http://127.0.0.1:1")
    fiber = _FakeFiber(fiber_dir, clean_error=RuntimeError("clean once"))
    archive = lambda fibers, failure: harness._archive_node_setup_failure(
        "method", fibers, failure
    )
    errors = lsp_test.cleanup_owned_lsp_nodes([fiber], archive=archive)
    assert errors and "clean once" in errors[0]
    assert fiber_dir.exists()
    assert len(list(evidence.glob("setup-failure*"))) == 1
    fiber.clean_error = None
    assert lsp_test.cleanup_owned_lsp_nodes([fiber], archive=archive) == []
    assert not fiber_dir.exists()
    assert len(list(evidence.glob("setup-failure*"))) == 1


def _complete_archive_logs(evidence):
    logs = []
    for manifest_path in evidence.glob("setup-failure*/failure.json"):
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("archive_errors"):
            continue
        for entry in manifest.get("nodes", []):
            if not entry.get("complete") or "node.log" not in entry.get("files", {}):
                continue
            path = manifest_path.parent / entry["dir"] / "node.log"
            if path.is_file():
                logs.append((str(path), path.read_text().strip()))
    return sorted(logs, key=lambda item: item[1])


def test_partial_copy_failure_is_not_reused_as_complete(tmp_path, monkeypatch):
    evidence = tmp_path / "business" / "method"
    evidence.mkdir(parents=True)
    harness = _Harness()
    harness.evidence_dir = evidence
    harness.node = _FakeNode(tmp_path / "ckb", "http://127.0.0.1:1")
    fiber_dir = tmp_path / "fiber"
    fiber_dir.mkdir()
    log = fiber_dir / "node.log"
    log.write_text("UNIQUE-PARTIAL-COPY\n")
    fiber = _FakeFiber(fiber_dir)
    archive = lambda fibers, failure: harness._archive_node_setup_failure(
        "method", fibers, failure
    )
    real_copy = lsp_test.shutil.copy2
    injected = {"left": 1}

    def flaky_copy(source, target, *args, **kwargs):
        if Path(source).resolve() == log.resolve() and injected["left"]:
            injected["left"] -= 1
            raise OSError("injected copy failure")
        return real_copy(source, target, *args, **kwargs)

    monkeypatch.setattr(lsp_test.shutil, "copy2", flaky_copy)
    first = lsp_test.cleanup_owned_lsp_nodes([fiber], archive=archive)
    assert first and "injected copy failure" in " ".join(first)
    assert log.exists()
    partial = [
        json.loads(path.read_text())
        for path in evidence.glob("setup-failure*/failure.json")
    ]
    assert partial and any(item.get("archive_errors") for item in partial)

    injected["left"] = 0
    second = lsp_test.cleanup_owned_lsp_nodes([fiber], archive=archive)
    assert second == []
    assert not fiber_dir.exists()
    completed = _complete_archive_logs(evidence)
    assert (
        completed == [(completed[0][0], "UNIQUE-PARTIAL-COPY")] if False else completed
    )
    assert [text for _, text in completed] == ["UNIQUE-PARTIAL-COPY"]
    assert lsp_test.cleanup_owned_lsp_nodes([fiber], archive=archive) == []
    assert [text for _, text in _complete_archive_logs(evidence)] == [
        "UNIQUE-PARTIAL-COPY"
    ]


def test_later_node_is_archived_without_reusing_other_subset(tmp_path):
    evidence = tmp_path / "business" / "method"
    evidence.mkdir(parents=True)
    harness = _Harness()
    harness.evidence_dir = evidence
    harness.node = _FakeNode(tmp_path / "ckb", "http://127.0.0.1:1")
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "node.log").write_text("UNIQUE-NODE-A\n")
    (b_dir / "node.log").write_text("UNIQUE-NODE-B\n")
    a_process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    a = _FakeFiber(a_dir, process=a_process, stop_error=RuntimeError("A stop failed"))
    b = _FakeFiber(b_dir)
    archive = lambda fibers, failure: harness._archive_node_setup_failure(
        "method", fibers, failure
    )
    try:
        first = lsp_test.cleanup_owned_lsp_nodes([a, b], archive=archive)
        assert first and "A stop failed" in " ".join(first)
        assert (a_dir / "node.log").exists()
        assert not b_dir.exists()
        completed = _complete_archive_logs(evidence)
        assert [text for _, text in completed] == ["UNIQUE-NODE-B"]
        b_archive = completed[0][0]

        a.stop_error = None
        second = lsp_test.cleanup_owned_lsp_nodes([a, b], archive=archive)
        assert second == []
        assert a_process.poll() is not None
        assert not a_dir.exists()
        completed = _complete_archive_logs(evidence)
        assert [text for _, text in completed] == [
            "UNIQUE-NODE-A",
            "UNIQUE-NODE-B",
        ]
        assert Path(b_archive).read_text().strip() == "UNIQUE-NODE-B"

        third = lsp_test.cleanup_owned_lsp_nodes([a, b], archive=archive)
        assert third == []
        assert [text for _, text in _complete_archive_logs(evidence)] == [
            "UNIQUE-NODE-A",
            "UNIQUE-NODE-B",
        ]
    finally:
        _stop(a_process)


def test_node_setup_archive_failure_keeps_runtime_and_original_error(tmp_path):
    fiber_dir = tmp_path / "fiber"
    fiber_dir.mkdir()
    (fiber_dir / "node.log").write_text("KEEP-ME-ON-ARCHIVE-FAILURE\n")
    fiber = _FakeFiber(fiber_dir, start_error=RuntimeError("start boom"))

    def archive(fibers, failure):
        raise RuntimeError("archive boom")

    with pytest.raises(RuntimeError, match="start boom") as captured:
        lsp_test.start_owned_lsp_nodes(
            [fiber], lambda function, argument: None, archive=archive
        )
    assert fiber_dir.exists()
    assert "KEEP-ME-ON-ARCHIVE-FAILURE" in (fiber_dir / "node.log").read_text()
    assert any(
        "archive boom" in note for note in getattr(captured.value, "__notes__", [])
    )


def test_string_ckb_pid_without_listener_is_stopped(tmp_path, monkeypatch):
    root = tmp_path
    runtime = root / "run"
    runtime.mkdir()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=runtime,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    node = _FakeNode(runtime, "http://127.0.0.1:1", ckb_pid=str(process.pid))
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(root / "evidence"))
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = node
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setattr(hosted_fixture, "_pid_command", lambda pid: "ckb run")
    try:
        assert _FakeFixture._recover_failed_setup(root) == []
        assert process.poll() is not None
        assert not runtime.exists()
    finally:
        _stop(process)
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


def test_string_ckb_pid_unverified_is_not_killed(tmp_path, monkeypatch):
    root = tmp_path
    runtime = root / "run"
    runtime.mkdir()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=runtime,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    node = _FakeNode(runtime, "http://127.0.0.1:1", ckb_pid=str(process.pid))
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(root / "evidence"))
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = node
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setattr(hosted_fixture, "_pid_command", lambda pid: "python sleep")
    try:
        errors = _FakeFixture._recover_failed_setup(root)
        assert errors and "unverified" in errors[0]
        assert process.poll() is None
        assert runtime.exists()
        assert framework_config.TMP_PATH == "original-tmp"
    finally:
        _stop(process)
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


def test_slow_exit_closes_port_before_process_exit(tmp_path, monkeypatch):
    root = tmp_path
    runtime = root / "run"
    runtime.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    code = """
import os, signal, socket, sys, time
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", int(sys.argv[1])))
sock.listen()
def stop(_signum, _frame):
    sock.close()
    time.sleep(1.5)
    os._exit(0)
signal.signal(signal.SIGTERM, stop)
time.sleep(30)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(port)],
        cwd=runtime,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    node = _FakeNode(runtime, f"http://127.0.0.1:{port}", ckb_pid=str(process.pid))
    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(root / "evidence"))
    _FakeFixture.tmp_path_name = "run"
    _FakeFixture.node = node
    _FakeFixture._hosted_original_tmp = "original-tmp"
    _FakeFixture._hosted_failure_archive = None
    monkeypatch.setattr(hosted_fixture, "_pid_command", lambda pid: "ckb run")
    try:
        _wait_port_open(port)
        started = time.monotonic()
        assert _FakeFixture._recover_failed_setup(root) == []
        assert time.monotonic() - started >= 1.4
        assert process.poll() is not None
        assert not runtime.exists()
        assert _FakeFixture._recover_failed_setup(root) == []
        assert len(list((root / "evidence").glob("*-class-setup-failure-*"))) == 1
    finally:
        _stop(process)
        _FakeFixture.tmp_path_name = None
        _FakeFixture.node = None


@pytest.mark.parametrize(
    "revision,retest,allowed",
    (
        ("84333eea8488a8afc7e4474aa4bbd0e7e973cee9", None, False),
        (
            "56c761c45c271c086b05c8d5ea3e033448f5fdf8",
            "56c761c45c271c086b05c8d5ea3e033448f5fdf8",
            True,
        ),
        ("56c761c45c271c086b05c8d5ea3e033448f5fdf8", None, False),
        ("76307312e8de518c9a32074e6d16867c04de4f86", None, True),
        (
            "76307312e8de518c9a32074e6d16867c04de4f86",
            "76307312e8de518c9a32074e6d16867c04de4f86",
            True,
        ),
    ),
)
def test_payment05_revision_gate(monkeypatch, revision, retest, allowed):
    calls = []
    monkeypatch.setattr(
        hosted_fixture.HostedTenantFixture,
        "setup_class",
        classmethod(lambda cls: calls.append("base")),
    )
    monkeypatch.setattr(payment05, "REVISION", revision)
    monkeypatch.setattr(payment05, "RETEST_REVISION", retest)
    if allowed:
        payment05.TestHostedOutboundPayment.setup_class()
        assert calls == ["base"]
    else:
        with pytest.raises(AssertionError, match="separately reviewed revision"):
            payment05.TestHostedOutboundPayment.setup_class()
        assert calls == []


def test_payment04_requires_report_dir_before_start_or_chain(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(payment04, "REVISION", payment04.FIXED_REVISION)
    monkeypatch.setattr(payment04, "RETEST_REVISION", None)
    monkeypatch.setenv("LSP_PAYMENT04_ROW_START", "100.0")
    monkeypatch.setenv("LSP_RUN_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.delenv("LSP_PAYMENT_REPORT_DIR", raising=False)
    monkeypatch.setattr(
        payment04.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: calls.append("mkdtemp"),
    )
    monkeypatch.setattr(
        payment04,
        "align_devnet_commitment_lock",
        lambda *args, **kwargs: calls.append("chain"),
    )
    monkeypatch.setattr(
        payment04.ChannelSigningTestBase,
        "setup_class",
        classmethod(lambda cls: calls.append("start")),
    )
    with pytest.raises(AssertionError, match="LSP_PAYMENT_REPORT_DIR"):
        payment04.TestPaymentAuthorizationRecovery.setup_class()
    assert calls == []

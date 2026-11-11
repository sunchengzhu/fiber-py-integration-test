"""Pilot scheduling/ports with synthetic children only; never starts CKB/FNN."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from scripts import lsp_parallel as parallel
from scripts import lsp_regression_runtime as runtime
from scripts import run_lsp_regression as runner
from framework.test_node import CkbNode, CkbNodeConfigPath


def pilot_jobs():
    return [
        {"group": g, "nodeids": list(runner.GROUPS[g])} for g in parallel.PILOT_GROUPS
    ]


def test_only_the_two_complete_groups_are_parallel_eligible():
    jobs = pilot_jobs()
    parallel.validate_plan(jobs, runner.GROUPS)
    for invalid in (
        jobs[:1],
        jobs + jobs[:1],
        [jobs[0], jobs[0]],
        [{**jobs[0], "nodeids": jobs[0]["nodeids"][:-1]}, jobs[1]],
        [{"group": None, "nodeids": jobs[0]["nodeids"]}, jobs[1]],
    ):
        with pytest.raises(ValueError):
            parallel.validate_plan(invalid, runner.GROUPS)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "bool", "range", "extra"])
def test_bad_port_maps_fail_before_any_runtime_is_allocated(fault):
    ports = dict(zip(parallel.PORT_FIELDS, range(24000, 24007)))
    if fault == "missing":
        ports.pop("lsp_ws_port")
    if fault == "duplicate":
        ports["lsp_ws_port"] = ports["ckb_rpc_port"]
    if fault == "bool":
        ports["ckb_rpc_port"] = True
    if fault == "range":
        ports["ckb_rpc_port"] = 65536
    if fault == "extra":
        ports["unqualified_port"] = 24008
    with pytest.raises(ValueError):
        parallel.validate_ports(ports)


def test_live_port_and_file_lease_are_not_reused_or_stopped(tmp_path):
    with socket.socket() as unrelated:
        unrelated.bind(("127.0.0.1", 0))
        unrelated.listen()
        occupied = unrelated.getsockname()[1]
        bases = (occupied - len(parallel.PORT_FIELDS) + 1, 26000, 26016, 26032, 26048)
        with parallel.PortLease(tmp_path, bases) as first:
            assert occupied not in first.values()
            with parallel.PortLease(tmp_path, bases) as second:
                assert not set(first.values()) & set(second.values())
            assert unrelated.getsockname()[1] == occupied
        # File locks are released without deleting the inode or old metadata.
        assert list(tmp_path.glob("*.lock"))
        with parallel.PortLease(tmp_path, bases) as again:
            assert again == first


def test_port_injection_reaches_ckb_miner_fnn_and_websocket(tmp_path, monkeypatch):
    ports = dict(zip(parallel.PORT_FIELDS, range(24000, 24007)))
    job = pilot_jobs()[0]
    e = runner.environment(
        tmp_path / "bundle", tmp_path / "job", job, port_map=ports, worker_id=0
    )
    for key in (
        "LSP_REGRESSION_SELECTORS",
        "LSP_REGRESSION_RUNTIME",
        "LSP_REGRESSION_PORTS",
    ):
        monkeypatch.setenv(key, e[key])
    cls = type("TestBrowserSigningSubscriptions", (), {})
    runtime.pytest_collection_modifyitems(
        [SimpleNamespace(nodeid=n, cls=cls) for n in job["nodeids"]]
    )
    assert all(getattr(cls, k) == v for k, v in ports.items())
    assert cls.CkbNode is runtime.PilotCkbNode and cls._lsp_parallel
    node = cls.CkbNode.init_dev_by_port(
        CkbNodeConfigPath.CURRENT_TEST,
        "contract/node",
        cls.ckb_rpc_port,
        cls.ckb_p2p_port,
    )
    assert node.rpcUrl == "http://127.0.0.1:24000"
    assert node.ckb_miner_config["ckb_miner_rpc_url"] == "127.0.0.1:24000"
    assert node.ckb_config["ckb_network_listen_addresses"] == ["/ip4/0.0.0.0/tcp/24001"]
    # Stale caller values cannot turn a subsequent ordinary job into a worker.
    monkeypatch.setenv("LSP_REGRESSION_PORTS", json.dumps(ports))
    normal = runner.environment(
        tmp_path / "bundle",
        tmp_path / "ordinary",
        {"group": None, "nodeids": [job["nodeids"][0]]},
    )
    assert (
        "LSP_REGRESSION_PORTS" not in normal and "LSP_REGRESSION_WORKER" not in normal
    )


def test_serial_plugin_keeps_the_original_ckb_startup(monkeypatch):
    job = pilot_jobs()[0]
    monkeypatch.delenv("LSP_REGRESSION_PORTS", raising=False)
    monkeypatch.setenv("LSP_REGRESSION_SELECTORS", json.dumps(job["nodeids"]))
    monkeypatch.setenv("LSP_REGRESSION_RUNTIME", "tmp/serial-unchanged")
    cls = type("TestBrowserSigningSubscriptions", (), {"CkbNode": CkbNode})
    runtime.pytest_collection_modifyitems(
        [SimpleNamespace(nodeid=n, cls=cls) for n in job["nodeids"]]
    )
    assert cls.CkbNode is CkbNode and not getattr(cls, "_lsp_parallel", False)


def test_two_owned_ckb_starts_keep_exact_pids_and_reap_independently(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import _stop_verified_ckb

    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "pid.txt"
    marker.write_text("unrelated PID evidence")
    nodes = []
    with parallel.PortLease(tmp_path / "locks") as ports:
        for i, port in enumerate(list(ports.values())[:2]):
            directory = tmp_path / f"ckb {i};$unused"
            directory.mkdir()
            binary = directory / "ckb"
            binary.write_text(
                f"#!{sys.executable}\nimport socket,time\n"
                f"s=socket.socket();s.bind(('127.0.0.1',{port}));s.listen()\n"
                "time.sleep(30)\n"
            )
            binary.chmod(0o755)
            node = runtime.PilotCkbNode.__new__(runtime.PilotCkbNode)
            node.ckb_dir, node.rpcUrl = str(directory), f"http://127.0.0.1:{port}"
            node.ckb_pid = node.ckb_miner_pid = -1
            nodes.append(node)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda n: n.start(), nodes))
            assert len({n.ckb_pid for n in nodes}) == 2
            assert all(n.ckb_pid == n._lsp_process.pid for n in nodes)
            assert marker.read_text() == "unrelated PID evidence"
            assert _stop_verified_ckb(nodes[0]) == []
            assert nodes[0]._lsp_process.returncode is not None
            assert nodes[1]._lsp_process.poll() is None
            assert _stop_verified_ckb(nodes[1]) == []
            assert nodes[1]._lsp_process.returncode is not None
            assert marker.read_text() == "unrelated PID evidence"
        finally:
            for node in nodes:
                process = getattr(node, "_lsp_process", None)
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize("explicit", [False, True])
def test_udt_issuance_forwards_optional_transaction_path(monkeypatch, explicit):
    from framework.helper import udt_contract as udt

    calls = []
    monkeypatch.setattr(
        udt, "util_key_info_by_private_key", lambda _: {"lock_arg": "a"}
    )
    monkeypatch.setattr(
        udt, "invoke_ckb_contract", lambda **kw: calls.append(kw) or "transaction"
    )
    contract = SimpleNamespace(
        issue=lambda *args: ("arg", "data"), contract_hash="hash", contract_tx_index=0
    )
    options = {"tx_file": "/isolated/udt-issue.json"} if explicit else {}
    assert (
        udt.issue_udt_tx(contract, "rpc", "owner", "account", 1, **options)
        == "transaction"
    )
    assert calls[0]["tx_file"] == options.get("tx_file")
    assert calls[0]["skip_type_cells"] and calls[0]["api_url"] == "rpc"


def test_two_transaction_builds_do_not_share_a_file(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from framework.helper import contract as helper

    barrier = threading.Barrier(2)
    monkeypatch.setattr(helper, "get_ckb_contract_codehash", lambda *a, **kw: "code")
    monkeypatch.setattr(
        helper,
        "util_key_info_by_private_key",
        lambda _: {"address": {"testnet": "addr"}, "lock_arg": "arg"},
    )
    monkeypatch.setattr(
        helper,
        "wallet_get_live_cells",
        lambda *a, **kw: {
            "live_cells": [
                {"tx_hash": "cell", "output_index": 0, "capacity": "1000.0 (CKB)"}
            ]
        },
    )
    monkeypatch.setattr(
        helper,
        "RPCClient",
        lambda url: SimpleNamespace(
            get_transaction=lambda _: {"tx_status": {"block_hash": url + "-header"}}
        ),
    )

    def initialize(path, api):
        Path(path).write_text(json.dumps({"api": api, "calls": []}))
        barrier.wait(timeout=5)

    def update(path, operation, api=None):
        data = json.loads(Path(path).read_text())
        if api is not None:
            assert data["api"] == api
        data["calls"].append(operation)
        Path(path).write_text(json.dumps(data))

    monkeypatch.setattr(helper, "tx_init", initialize)
    monkeypatch.setattr(
        helper,
        "tx_add_multisig_config",
        lambda address, path, api: update(path, "multisig", api),
    )
    monkeypatch.setattr(
        helper, "tx_add_input", lambda h, i, path, api: update(path, "input", api)
    )
    monkeypatch.setattr(helper, "tx_add_header_dep", lambda h, path: update(path, h))
    monkeypatch.setattr(
        helper, "tx_add_output", lambda o, data, path: update(path, "output")
    )
    monkeypatch.setattr(
        helper, "tx_add_cell_dep", lambda h, i, path: update(path, "dep")
    )
    monkeypatch.setattr(
        helper,
        "tx_sign_inputs",
        lambda key, path, api: [{"lock-arg": "arg", "signature": "sig"}],
    )
    monkeypatch.setattr(
        helper,
        "tx_add_signature",
        lambda arg, sig, path, api: update(path, "sign", api),
    )
    monkeypatch.setattr(helper, "tx_info", lambda path, api: update(path, "info", api))
    monkeypatch.setattr(
        helper, "tx_send", lambda path, api: update(path, "send", api) or api
    )

    def build(i):
        return helper.invoke_ckb_contract(
            "key",
            "hash",
            0,
            "arg",
            api_url=f"worker-{i}",
            tx_file=str(tmp_path / f"tx-{i}.json"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(build, range(2))) == ["worker-0", "worker-1"]
    for i in range(2):
        data = json.loads((tmp_path / f"tx-{i}.json").read_text())
        assert data["api"] == f"worker-{i}"
        assert data["calls"] == [
            "multisig",
            "input",
            f"worker-{i}-header",
            "output",
            "dep",
            "sign",
            "info",
            "send",
        ]


def test_port_injection_rejects_unqualified_classes(monkeypatch):
    ports = dict(zip(parallel.PORT_FIELDS, range(24000, 24007)))
    monkeypatch.setenv("LSP_REGRESSION_PORTS", json.dumps(ports))
    monkeypatch.setenv("LSP_REGRESSION_SELECTORS", '["unqualified"]')
    with pytest.raises(ValueError, match="only qualified"):
        runtime.pytest_collection_modifyitems(
            [SimpleNamespace(nodeid="unqualified", cls=type("Other", (), {}))]
        )


def test_local_worker_failure_does_not_cancel_other_worker(tmp_path):
    barrier = threading.Barrier(2)
    seen = []

    def run(job, directory, bundle, timeout, **options):
        barrier.wait(timeout=5)
        seen.append((dict(options["port_map"]), directory, options["cancel_event"]))
        assert not options["cancel_event"].is_set()
        if job["group"] == "subscription-filters":
            time.sleep(0.1)
        return {
            **job,
            "exit_code": 1 if job["group"] == "browser-auth" else 0,
            "duration_seconds": 0.1,
            "errors": [],
            "outcomes": {
                n: "failure" if job["group"] == "browser-auth" else "passed"
                for n in job["nodeids"]
            },
        }

    results = []
    parallel.run_two_jobs(
        pilot_jobs(), tmp_path, tmp_path / "bundle", 5, run, results, runner.write_json
    )
    assert len(results) == 2 and not set(seen[0][0].values()) & set(seen[1][0].values())
    assert seen[0][1] != seen[1][1] and not seen[0][2].is_set()
    assert results[1]["exit_code"] == 0


def test_global_disk_exhaustion_cancels_both_and_collects_results(
    tmp_path, monkeypatch
):
    calls = 0

    def disk(_):
        nonlocal calls
        calls += 1
        return SimpleNamespace(free=20 * 2**30 if calls == 1 else 7 * 2**30)

    monkeypatch.setattr(parallel.shutil, "disk_usage", disk)

    def run(job, directory, bundle, timeout, **options):
        assert options["cancel_event"].wait(timeout=5)
        return {
            **job,
            "exit_code": 2,
            "duration_seconds": 0.2,
            "errors": ["cancelled"],
            "outcomes": {n: "not_run" for n in job["nodeids"]},
        }

    results = []
    with pytest.raises(RuntimeError, match="disk floor/budget"):
        parallel.run_two_jobs(
            pilot_jobs(),
            tmp_path,
            tmp_path / "bundle",
            5,
            run,
            results,
            runner.write_json,
        )
    assert len(results) == 2 and all(r["errors"] for r in results)


def test_worker_evidence_init_failure_is_recorded_and_other_worker_finishes(tmp_path):
    def run(job, directory, bundle, timeout, **_):
        if job["group"] == "browser-auth":
            raise OSError("evidence init failure")
        return {
            **job,
            "exit_code": 0,
            "duration_seconds": 0.1,
            "errors": [],
            "outcomes": {n: "passed" for n in job["nodeids"]},
        }

    results = []
    parallel.run_two_jobs(
        pilot_jobs(), tmp_path, tmp_path / "bundle", 5, run, results, runner.write_json
    )
    assert "evidence init failure" in results[0]["errors"][0]
    assert (tmp_path / "job-000/result.json").is_file() and results[1]["exit_code"] == 0


def test_both_worker_diagnostic_writes_fail_without_hiding_peer_result(tmp_path):
    attempts = []

    def run(job, directory, bundle, timeout, **options):
        assert not options["cancel_event"].is_set()
        if job["group"] == "browser-auth":
            raise OSError("worker initialization failed")
        return {
            **job,
            "exit_code": 0,
            "duration_seconds": 0.1,
            "errors": [],
            "outcomes": {n: "passed" for n in job["nodeids"]},
        }

    def denied(path, row):
        attempts.append(path.name)
        raise PermissionError(path.name + " denied")

    results = []
    parallel.run_two_jobs(pilot_jobs(), tmp_path, tmp_path, 5, run, results, denied)
    assert attempts == ["result.json", "worker-0-failure.json"]
    assert len(results) == 2 and results[1]["exit_code"] == 0
    assert len(results[0]["errors"]) == 3
    assert "worker initialization failed" in results[0]["errors"][0]
    assert "result.json denied" in results[0]["errors"][1]
    assert "worker-0-failure.json denied" in results[0]["errors"][2]


def test_parallel_timeout_reaps_only_its_child_and_keeps_other_result(
    tmp_path, monkeypatch
):
    child = tmp_path / "synthetic.py"
    child.write_text("""import json,os,signal,socket,sys,time
from pathlib import Path
import xml.etree.ElementTree as ET
sockets=[]
for port in json.loads(os.environ['LSP_REGRESSION_PORTS']).values():
 s=socket.socket();s.bind(('127.0.0.1',port));s.listen();sockets.append(s)
print('owned synthetic raw evidence',flush=True)
def report(*_):
 root=ET.Element('testsuites');suite=ET.SubElement(root,'testsuite')
 for n in json.loads(os.environ['LSP_REGRESSION_SELECTORS']):
  f,c,m=n.split('::');ET.SubElement(suite,'testcase',classname=f[:-3].replace('/','.')+'.'+c,name=m)
 ET.ElementTree(root).write(sys.argv[1])
 sys.exit(1 if os.environ['LSP_REGRESSION_WORKER']=='0' else 0)
signal.signal(signal.SIGINT,report)
time.sleep(30 if os.environ['LSP_REGRESSION_WORKER']=='0' else .7)
report()
""")
    monkeypatch.setattr(runner, "pytest_command", lambda: [sys.executable, str(child)])
    # run_job's original command shape is replaced with this child and its own
    # JUnit path; all process ownership/wait/drain/port checks remain real.
    popen = subprocess.Popen

    def launch(command, **kw):
        target = Path(kw["env"]["LSP_REGRESSION_CASE"]) / "junit.xml"
        return popen([sys.executable, str(child), str(target)], **kw)

    monkeypatch.setattr(runner.subprocess, "Popen", launch)

    def run(job, directory, bundle, timeout, **kw):
        return runner.run_job(
            job, directory, bundle, 0.3 if kw["worker_id"] == 0 else 5, **kw
        )

    results = []
    parallel.run_two_jobs(
        pilot_jobs(), tmp_path, tmp_path / "bundle", 5, run, results, runner.write_json
    )
    assert "TimeoutExpired" in results[0]["errors"] and results[0]["exit_code"] == 1
    assert results[1]["exit_code"] == 0 and not results[1]["errors"]
    assert all(not runner.group_exists(r["pid"]) for r in results)
    assert all(
        "owned synthetic raw evidence"
        in (tmp_path / f"job-{i:03d}/stdout.log").read_text()
        for i in (0, 1)
    )


def test_default_cli_is_serial_and_unqualified_parallel_rejected(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        runner, "collect", lambda *_: [n for j in pilot_jobs() for n in j["nodeids"]]
    )
    monkeypatch.setattr(
        sys, "argv", ["runner", "--plan-only", "--output", str(tmp_path / "serial")]
    )
    assert runner.main() == 0
    assert json.loads((tmp_path / "serial/plan.json").read_text())["workers"] == 1
    monkeypatch.setattr(
        runner, "collect", lambda *_: list(runner.GROUPS["invoice-query"])
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--workers", "2", "--plan-only", "--output", str(tmp_path / "bad")],
    )
    assert runner.main() != 0 and (tmp_path / "bad/batch-error.json").exists()


def test_sigterm_cancels_both_workers_and_preserves_native_results(tmp_path):
    # Drive the real CLI/controller and native process cleanup with sleeping
    # synthetic children. No unittest/FNN classes are collected or run.
    controller = tmp_path / "controller.py"
    output = tmp_path / "evidence"
    controller.write_text('''import json,os,signal,subprocess,sys,time
from pathlib import Path
from scripts import run_lsp_regression as r
from scripts.lsp_parallel import PILOT_GROUPS
r.collect=lambda *_:[n for g in PILOT_GROUPS for n in r.GROUPS[g]]
original=r.subprocess.Popen
source="""import json,os,signal,sys,time
from pathlib import Path
import xml.etree.ElementTree as ET
def stop(*_):
 root=ET.Element('testsuites');suite=ET.SubElement(root,'testsuite')
 for n in json.loads(os.environ['LSP_REGRESSION_SELECTORS']):
  f,c,m=n.split('::');ET.SubElement(suite,'testcase',classname=f[:-3].replace('/','.')+'.'+c,name=m)
 ET.ElementTree(root).write(Path(os.environ['LSP_REGRESSION_CASE'])/'junit.xml');sys.exit(1)
signal.signal(signal.SIGINT,stop)
(Path(os.environ['LSP_REGRESSION_CASE'])/'ready').write_text(str(os.getpid()))
print('raw synthetic before stop',flush=True)
time.sleep(30)
"""
def launch(command,**kw):return original([sys.executable,'-c',source],**kw)
r.subprocess.Popen=launch
signal.signal(signal.SIGTERM,r.interrupt_on_termination)
sys.exit(r.main())
''')
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "build.json").write_text(json.dumps({"revision": runner.REVISION}))
    env = {**os.environ, "PYTHONPATH": str(runner.ROOT)}
    with (tmp_path / "controller.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(controller),
                "--workers",
                "2",
                "--output",
                str(output),
                "--bundle",
                str(bundle),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            until = time.monotonic() + 10
            while len(list(output.glob("job-*/ready"))) < 2:
                assert process.poll() is None, (tmp_path / "controller.log").read_text()
                assert time.monotonic() < until
                time.sleep(0.02)
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=15) != 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    summary = json.loads((output / "summary.json").read_text())
    assert summary["workers"] == 2 and summary["finished_jobs"] == 2
    assert all("InterruptedError" in r["errors"] for r in summary["results"])
    assert all(not runner.group_exists(r["pid"]) for r in summary["results"])
    assert all((output / f"job-{i:03d}/junit.xml").exists() for i in (0, 1))
    assert all(
        "raw synthetic before stop" in (output / f"job-{i:03d}/stdout.log").read_text()
        for i in (0, 1)
    )

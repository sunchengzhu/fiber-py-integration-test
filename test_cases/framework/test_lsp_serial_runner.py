"""Serial scheduling and native failure evidence; no business/node execution."""

import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

import framework.config as framework_config
import framework.test_node as node_module
from scripts import lsp_regression_runtime as runtime
from scripts import run_lsp_regression as runner

SEVEN = [nodeid for group in runner.GROUPS.values() for nodeid in group]
EVICT = runner.INVOICE + "test_tenant_token_cannot_evict_tenants"


def write_native(path, nodeids, statuses=None):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for nodeid, status in zip(nodeids, statuses or ["passed"] * len(nodeids)):
        file, cls, method = nodeid.split("::")
        row = ET.SubElement(
            suite,
            "testcase",
            classname=file[:-3].replace("/", ".") + "." + cls,
            name=method,
        )
        if status != "passed":
            ET.SubElement(row, status)
    ET.ElementTree(root).write(path)


def test_plan_groups_only_the_seven_and_keeps_evict_independent():
    # A destructive method between eligible methods must never join the owner.
    selected = [SEVEN[0], EVICT, *SEVEN[1:]]
    jobs = runner.build_plan(selected)
    assert [len(job["nodeids"]) for job in jobs] == [4, 1, 3]
    assert jobs[1] == {"group": None, "nodeids": [EVICT]}
    assert sorted(n for job in jobs for n in job["nodeids"]) == sorted(selected)
    independent = runner.build_plan(selected, independent=True)
    assert len(independent) == 8 and all(job["group"] is None for job in independent)


def test_partial_group_stays_independent_without_adding_methods():
    jobs = runner.build_plan(SEVEN[:2])
    assert jobs == [{"group": None, "nodeids": [nodeid]} for nodeid in SEVEN[:2]]


@pytest.mark.parametrize(
    "selected", [[], [SEVEN[0], SEVEN[0]], [SEVEN[0].replace("/lsp/", "/lsp_nightly/")]]
)
def test_invalid_or_nightly_plan_is_rejected(selected):
    with pytest.raises(ValueError):
        runner.build_plan(selected)


def test_delivery_still_requires_qualification_and_runs_it_first():
    fault = (
        runner.SUITE
        + "/test_delivery_acceptance.py::TestDeliveryAcceptance::test_fault"
    )
    with pytest.raises(ValueError, match="qualification"):
        runner.build_plan([fault])
    jobs = runner.build_plan([SEVEN[0], fault, runner.QUALIFICATION])
    assert jobs[0]["nodeids"] == [runner.QUALIFICATION]


@pytest.mark.parametrize("group", [None, *runner.GROUPS])
def test_environment_does_not_leak_shared_flags_budgets_or_pytest_parallelism(
    monkeypatch, tmp_path, group
):
    for name in ("LSP_QUERY_ENV_MODE", "LSP_INVOICE_QUERY_ENV_MODE"):
        monkeypatch.setenv(name, "shared")
    monkeypatch.setenv("LSP_WATCHTOWER_ROUND_UNTIL", "1")
    monkeypatch.setenv("LSP_TEST_REVISION", "0" * 40)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-n auto")
    monkeypatch.setenv("PYTEST_PLUGINS", "unrelated")
    env = runner.environment(
        tmp_path / "bundle", tmp_path / "job", {"group": group, "nodeids": SEVEN}
    )
    assert env["LSP_TEST_REVISION"] == env["LSP_RETEST_REVISION"] == runner.REVISION
    assert env["LSP_QUERY_ENV_MODE"] == (
        "shared" if group == "payment-query" else "independent"
    )
    assert env["LSP_INVOICE_QUERY_ENV_MODE"] == (
        "shared" if group == "invoice-query" else "independent"
    )
    assert env["PYTEST_ADDOPTS"] == "" and "PYTEST_PLUGINS" not in env
    assert "LSP_WATCHTOWER_ROUND_UNTIL" not in env
    assert env["LSP_QUERY_KEEP_RUNTIME"] == env["LSP_INVOICE_QUERY_KEEP_RUNTIME"] == "1"
    next_env = runner.environment(
        tmp_path / "bundle", tmp_path / "other", {"group": None, "nodeids": [EVICT]}
    )
    assert env["CKB_CLI_HOME"] != next_env["CKB_CLI_HOME"]
    assert env["LSP_PAYMENT_REPORT_DIR"] != next_env["LSP_PAYMENT_REPORT_DIR"]


def test_native_missing_skipped_failure_and_teardown_errors_cannot_be_passes(tmp_path):
    path = tmp_path / "junit.xml"
    write_native(path, SEVEN[:3], ["passed", "failure", "skipped"])
    outcomes = runner.native_outcomes(path, SEVEN[:4])
    assert list(outcomes.values()) == ["passed", "failure", "skipped", "not_run"]
    write_native(path, [SEVEN[0], SEVEN[0]], ["passed", "error"])
    assert runner.native_outcomes(path, [SEVEN[0]]) == {SEVEN[0]: "error"}
    write_native(path, [SEVEN[0], SEVEN[0]])
    with pytest.raises(ValueError, match="duplicate native pass"):
        runner.native_outcomes(path, [SEVEN[0]])
    write_native(path, [EVICT])
    with pytest.raises(ValueError, match="unexpected native testcase"):
        runner.native_outcomes(path, [SEVEN[0]])


def test_runtime_rejects_extra_or_reordered_methods(monkeypatch):
    monkeypatch.setenv("LSP_REGRESSION_SELECTORS", json.dumps(SEVEN[:2]))
    items = [SimpleNamespace(nodeid=n, cls=type("Case", (), {})) for n in SEVEN[:2]]
    monkeypatch.setenv("LSP_REGRESSION_RUNTIME", "tmp/fresh")
    runtime.pytest_collection_modifyitems(items)
    assert all(item.cls.tmp_path_name == "tmp/fresh" for item in items)
    with pytest.raises(ValueError, match="selection/order"):
        runtime.pytest_collection_modifyitems(list(reversed(items)))


@pytest.mark.parametrize(
    "name",
    [
        "run with spaces",
        "run; echo marker && echo marker | cat",
        "run-$(echo marker)-`echo marker`",
        "run-'quoted'-\"double\"-*[1]\t\n",
    ],
    ids=["spaces", "separators", "substitutions", "quotes-globs-whitespace"],
)
def test_output_path_cannot_change_runtime_or_cleanup_operands(
    monkeypatch, tmp_path, name
):
    directory = tmp_path / name / "job-000"
    directory.mkdir(parents=True)
    original = directory / "evidence.txt"
    original.write_text("retained evidence\n")
    job = {"group": None, "nodeids": [EVICT]}
    env = runner.environment(tmp_path / "bundle", directory, job)
    runtime_name = env["LSP_REGRESSION_RUNTIME"]
    assert re.fullmatch(r"tmp/lsp-serial-[0-9a-f]{32}", runtime_name)
    assert env["LSP_REGRESSION_CASE"] == str(directory)
    assert env["LSP_PAYMENT_REPORT_DIR"] == str(directory / "business")
    for key in ("LSP_REGRESSION_SELECTORS", "LSP_REGRESSION_RUNTIME"):
        monkeypatch.setenv(key, env[key])
    item = SimpleNamespace(nodeid=EVICT, cls=type("Case", (), {}))
    runtime.pytest_collection_modifyitems([item])
    monkeypatch.setattr(framework_config, "TMP_PATH", item.cls.tmp_path_name)
    node = node_module.CkbNode.init_dev_by_port(
        node_module.CkbNodeConfigPath.CURRENT_TEST, "contract/node", 8114, 8125
    )  # Construction only: no prepare, start or RPC.
    expected = runner.ROOT / runtime_name / "contract/node"
    assert Path(node.ckb_dir) == expected
    commands = []
    monkeypatch.setattr(node_module, "run_command", commands.append)
    node.clean()  # Capture the real cleanup command; never execute its shell.
    assert len(commands) == 1
    assert shlex.split(commands[0]) == ["rm", "-rf", str(expected)]
    assert original.read_text() == "retained evidence\n"


def test_runtime_names_are_fresh_even_for_same_output_basename(tmp_path):
    job = {"group": None, "nodeids": [EVICT]}
    directories = [tmp_path / "one/run/job-000", tmp_path / "two/run/job-000"]
    directories.append(directories[0])
    names = [
        runner.environment(tmp_path / "bundle", directory, job)[
            "LSP_REGRESSION_RUNTIME"
        ]
        for directory in directories
    ]
    assert len(set(names)) == 3
    assert all(re.fullmatch(r"tmp/lsp-serial-[0-9a-f]{32}", name) for name in names)


def test_evidence_copy_failure_yields_for_native_cleanup_and_keeps_original(
    monkeypatch, tmp_path
):
    source = tmp_path / "source"
    source.mkdir()
    original = source / "node.log"
    original.write_text("original bytes\n")
    monkeypatch.setenv("LSP_REGRESSION_CASE", str(tmp_path / "evidence"))
    item = SimpleNamespace(
        name="case",
        cls=SimpleNamespace(node=None),
        instance=SimpleNamespace(fibers=[SimpleNamespace(tmp_path=source)]),
    )

    def fail_copy(*_args):
        raise OSError("partial archive")

    monkeypatch.setattr(runtime.shutil, "copy2", fail_copy)
    hook = runtime.pytest_runtest_teardown(item, None)
    next(hook)  # Control reaches the fixture cleanup even though copying failed.
    with pytest.raises(RuntimeError, match="partial archive"):
        next(hook)
    assert original.read_text() == "original bytes\n"
    diagnostic = tmp_path / "evidence/before-teardown/case/runtime.json"
    assert json.loads(diagnostic.read_text())["errors"]


def test_evidence_directory_failure_still_yields_for_native_cleanup(
    monkeypatch, tmp_path
):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("keep me")
    monkeypatch.setenv("LSP_REGRESSION_CASE", str(blocked))
    item = SimpleNamespace(name="case", cls=SimpleNamespace(node=None), instance=None)
    hook = runtime.pytest_runtest_teardown(item, None)
    next(hook)
    with pytest.raises(RuntimeError, match="raw evidence copy failed"):
        next(hook)
    assert blocked.read_text() == "keep me"


@pytest.mark.parametrize("bad", ["missing", "skipped", "error", "nonzero"])
def test_entry_stops_incomplete_jobs_and_never_retries(monkeypatch, tmp_path, bad):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "build.json").write_text(json.dumps({"revision": runner.REVISION}))
    output = tmp_path / "evidence"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--only-shared-groups",
            "--output",
            str(output),
            "--bundle",
            str(bundle),
        ],
    )
    monkeypatch.setattr(runner, "collect", lambda *_: SEVEN)
    started = []

    def run_job(job, directory, *_args):
        started.append(job)
        return {
            "nodeids": job["nodeids"],
            "exit_code": 1 if bad == "nonzero" else 0,
            "outcomes": {
                n: ("skipped" if bad == "skipped" else "passed") for n in job["nodeids"]
            },
            "duration_seconds": 1,
            "errors": [bad] if bad in ("missing", "error") else [],
        }

    monkeypatch.setattr(runner, "run_job", run_job)
    code = runner.main()
    assert code != 0
    assert len(started) == (2 if bad == "nonzero" else 1)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["finished_jobs"] == len(started)
    if len(started) == 1:
        assert summary["unstarted_methods"] == list(runner.GROUPS["payment-query"])


def test_timeout_retains_stdout_native_failure_and_reaps_owned_child(
    monkeypatch, tmp_path
):
    # A real subprocess writes a native failure and exits on the pytest SIGINT grace.
    monkeypatch.setattr(runner, "check_environment", lambda: 20 * 2**30)
    script = tmp_path / "standin.py"
    script.write_text(
        "import signal,sys,time\nfrom pathlib import Path\np=Path(sys.argv[1])\ndef stop(*_):\n p.write_text(sys.argv[2]);sys.exit(1)\nsignal.signal(signal.SIGINT,stop)\nprint('raw evidence before timeout',flush=True)\ntime.sleep(30)\n"
    )
    report = tmp_path / "native.xml"
    write_native(report, [SEVEN[0]], ["failure"])
    jobdir = tmp_path / "job"
    command = [
        sys.executable,
        str(script),
        str(jobdir / "junit.xml"),
        report.read_text(),
    ]
    monkeypatch.setattr(runner, "pytest_command", lambda: command)
    row = runner.run_job(
        {"group": None, "nodeids": [SEVEN[0]]}, jobdir, tmp_path / "bundle", 0.3
    )
    assert "TimeoutExpired" in row["errors"]
    assert row["exit_code"] == 1 and row["outcomes"] == {SEVEN[0]: "failure"}
    assert "raw evidence before timeout" in (jobdir / "stdout.log").read_text()
    assert not runner.group_exists(row["pid"])
    assert json.loads((jobdir / "result.json").read_text())["junit_sha256"]


def test_outer_cleanup_reaps_owned_descendant_without_touching_other_process(tmp_path):
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    owned = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])",
        ],
        start_new_session=True,
    )
    try:
        owned.wait(timeout=5)
        assert runner.drain_group(owned)
        assert not runner.group_exists(owned.pid)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
        if runner.group_exists(owned.pid):
            os.killpg(owned.pid, signal.SIGKILL)


def test_make_preserves_default_prepare_and_exposes_explicit_lsp_entry():
    default = subprocess.check_output(["make", "-n"], cwd=runner.ROOT, text=True)
    assert "python3 -m venv venv" in default
    assert "scripts/run_lsp_regression.py" not in default
    explicit = subprocess.check_output(
        ["make", "-n", "lsp_test", "PYTHON=python3", "LSP_ARGS=--only-shared-groups"],
        cwd=runner.ROOT,
        text=True,
    )
    assert (
        explicit.strip() == "python3 scripts/run_lsp_regression.py --only-shared-groups"
    )


def test_sigterm_uses_job_cleanup_and_retains_failure_report(tmp_path):
    report = tmp_path / "native.xml"
    write_native(report, [SEVEN[0]], ["failure"])
    child = tmp_path / "child.py"
    ready = tmp_path / "ready"
    child.write_text(
        "import signal,sys,time\nfrom pathlib import Path\ndef stop(*_):\n Path(sys.argv[1]).write_text(sys.argv[2]);sys.exit(1)\nsignal.signal(signal.SIGINT,stop)\nPath(sys.argv[3]).write_text('ready')\nprint('original evidence',flush=True)\ntime.sleep(30)\n"
    )
    jobdir = tmp_path / "job"
    job = {"group": None, "nodeids": [SEVEN[0]]}
    code = (
        "import signal,sys; from pathlib import Path; from scripts import run_lsp_regression as r; "
        "signal.signal(signal.SIGTERM,r.interrupt_on_termination); "
        "r.check_environment=lambda:20*2**30; "
        f"r.pytest_command=lambda:{[sys.executable, str(child), str(jobdir/'junit.xml'), report.read_text(), str(ready)]!r}; "
        f"row=r.run_job({job!r},Path({str(jobdir)!r}),Path({str(tmp_path/'bundle')!r}),30); "
        "sys.exit(1 if row['errors'] else 0)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=runner.ROOT,
        env={**os.environ, "PYTHONPATH": str(runner.ROOT)},
        start_new_session=True,
    )
    try:
        until = time.monotonic() + 5
        while not ready.exists() and parent.poll() is None and time.monotonic() < until:
            time.sleep(0.02)
        assert ready.exists()
        parent.terminate()
        assert parent.wait(timeout=10) == 1
        record = json.loads((jobdir / "result.json").read_text())
        assert "KeyboardInterrupt" in record["errors"]
        assert record["outcomes"] == {SEVEN[0]: "failure"}
        assert not runner.group_exists(record["pid"])
        assert "original evidence" in (jobdir / "stdout.log").read_text()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)

"""CI engineering regressions; synthetic pytest/processes only, no CKB or FNN."""

import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
import yaml

from scripts import lsp_ci as ci
from scripts import lsp_ci_build as builder
from scripts import lsp_ci_progress as progress
from scripts import run_lsp_regression as runner

REVISION = "a" * 40
INTEGRATION = "b" * 40


@pytest.fixture(autouse=True)
def isolate_synthetic_ci_environment(monkeypatch):
    for name in (
        "GITHUB_STEP_SUMMARY",
        "GITHUB_OUTPUT",
        "LSP_CI_PLAN_RESULT",
        "LSP_CI_BUILD_RESULT",
        "LSP_CI_TESTS_RESULT",
    ):
        monkeypatch.delenv(name, raising=False)


def nodes(count=4):
    return [
        f"{runner.SUITE}/test_tenant_boundaries.py::TestSynthetic::test_{i}"
        for i in range(count)
    ]


@pytest.mark.parametrize("value", ["", "ABCDEF1", "a" * 40])
def test_resolution_uses_head_once_or_exact_commit(value):
    calls = []
    resolved = "abcdef1" + "a" * 33 if value == "ABCDEF1" else REVISION

    def api(path):
        calls.append(path)
        return {
            "sha": resolved,
            "state": "open",
            "head": {"sha": resolved},
            "merge_commit_sha": "c" * 40,
        }

    assert ci.resolve_commit(value, api) == resolved
    assert len(calls) == 1
    assert calls[0].endswith("pulls/1623" if not value else "commits/" + value.lower())


@pytest.mark.parametrize(
    "value", ["main", "$(id)", "a;echo x", "abcdef", "a" * 41, "a\noutput=bad"]
)
def test_bad_commit_does_not_reach_api(value):
    with pytest.raises(ValueError):
        ci.resolve_commit(value, lambda _: pytest.fail("API must not be called"))


def test_closed_pr_still_uses_its_head_and_manual_mismatch_is_rejected():
    assert (
        ci.resolve_commit(
            "",
            lambda _: {
                "state": "closed",
                "head": {"sha": REVISION},
                "merge_commit_sha": "c" * 40,
            },
        )
        == REVISION
    )
    with pytest.raises(ValueError):
        ci.resolve_commit("aaaaaaa", lambda _: {"sha": "c" * 40})


def test_partition_preserves_complete_shared_groups_and_rejects_unknown_cases():
    selected = [n for group in runner.GROUPS.values() for n in group]
    buckets = ci.partition(selected)
    assert len({n for b in buckets for n in b["nodeids"]}) == len(selected)
    for group in runner.GROUPS.values():
        assert sum(set(group) <= set(b["nodeids"]) for b in buckets) == 1
    with pytest.raises(ValueError):
        ci.partition([runner.SUITE + "/test_unassigned.py::TestUnassigned::test_a"])
    with pytest.raises(ValueError):
        ci.partition([selected[0], selected[0]])
    with pytest.raises(ValueError):
        ci.partition([selected[0].replace("/lsp/", "/lsp_nightly/")])


def fixture_plan(tmp_path, count=4):
    selected = nodes(count)
    plan = {
        "revision": REVISION,
        "integration_commit": INTEGRATION,
        "buckets": [
            {"id": "query", "label": "查询", "nodeids": selected, "count": count}
        ],
        "cases": [
            {
                "nodeid": n,
                "case": f"EX-{i}",
                "description": "<script>unsafe</script> 中文用例",
            }
            for i, n in enumerate(selected)
        ],
    }
    path = tmp_path / "plan.json"
    ci.write(path, plan)
    directory = tmp_path / "results/query"
    directory.mkdir(parents=True)
    ci.write(
        directory / "job.json",
        {
            "revision": REVISION,
            "integration_commit": INTEGRATION,
            "nodeids": selected,
            "exit_code": 0,
        },
    )
    ci.write(
        directory / "entry/summary.json",
        {"revision": REVISION, "workers": 1, "unstarted_methods": []},
    )
    ci.write(
        directory / "runtime-retention.json",
        {
            "unavailable": [],
            "originals_deleted": False,
            "archive_sha256": "f" * 64,
            "files": 1,
        },
    )
    return path, directory, selected


def native_job(directory, selected, outcomes, index=0):
    child = directory / "entry" / f"job-{index:03d}"
    child.mkdir(parents=True)
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for n, status in zip(selected, outcomes):
        if status == "not_run":
            continue
        file, cls, method = n.split("::")
        testcase = ET.SubElement(
            suite,
            "testcase",
            classname=file[:-3].replace("/", ".") + "." + cls,
            name=method,
        )
        if status != "passed":
            ET.SubElement(testcase, status, message="<script>trace</script>").text = (
                "raw failure"
            )
    ET.ElementTree(root).write(child / "junit.xml")
    ci.write(
        child / "command.json",
        {"nodeids": selected, "environment": {"LSP_TEST_REVISION": REVISION}},
    )
    ci.write(
        child / "result.json",
        {
            "nodeids": selected,
            "exit_code": int(any(s != "passed" for s in outcomes)),
            "errors": [],
            "junit_sha256": ci.sha(child / "junit.xml"),
        },
    )
    return child


def test_report_distinguishes_missing_unstarted_interrupted_and_native_results(
    tmp_path,
):
    path, directory, selected = fixture_plan(tmp_path)
    child = native_job(directory, selected, ["passed", "failure", "not_run", "not_run"])
    (child / "events.jsonl").write_text(
        json.dumps({"event": "start", "nodeid": selected[2]}) + "\n"
    )
    result = ci.render_report(path, tmp_path / "results", tmp_path / "report")
    d = ci.read(tmp_path / "report/report.json")
    assert result == 1 and [r["status"] for r in d["cases"]] == [
        "passed",
        "failure",
        "incomplete",
        "not_run",
    ]
    assert len(d["cases"]) == 4 and d["counts"] == {
        "passed": 1,
        "failure": 1,
        "incomplete": 1,
        "not_run": 1,
    }
    page = (tmp_path / "report/index.html").read_text()
    assert (
        "<script>unsafe</script>" not in page and "<script>trace</script>" not in page
    )
    assert "&lt;script&gt;" in page and 'data-status="not_run"' in page
    assert "<progress" in page


@pytest.mark.parametrize(
    "fault",
    [
        "missing_job",
        "wrong_revision",
        "missing_result",
        "bad_hash",
        "malformed_xml",
        "extra_native",
        "duplicate_pass",
        "bad_summary",
    ],
)
def test_bad_or_missing_evidence_never_becomes_success_or_hides_inventory(
    tmp_path, fault
):
    path, directory, selected = fixture_plan(tmp_path, 1)
    child = native_job(directory, selected, ["passed"])
    if fault == "missing_job":
        (directory / "job.json").unlink()
    if fault == "wrong_revision":
        d = ci.read(directory / "job.json")
        d["revision"] = "c" * 40
        ci.write(directory / "job.json", d)
    if fault == "missing_result":
        (child / "result.json").unlink()
    if fault == "bad_hash":
        (child / "junit.xml").write_text("<testsuites/>")
    if fault == "malformed_xml":
        (child / "junit.xml").write_text("<")
    if fault in ("extra_native", "duplicate_pass"):
        tree = ET.parse(child / "junit.xml")
        suite = next(tree.iter("testsuite"))
        row = next(tree.iter("testcase"))
        ET.SubElement(
            suite,
            "testcase",
            **{
                **row.attrib,
                "name": "unexpected" if fault == "extra_native" else row.get("name"),
            },
        )
        tree.write(child / "junit.xml")
        d = ci.read(child / "result.json")
        d["junit_sha256"] = ci.sha(child / "junit.xml")
        ci.write(child / "result.json", d)
    if fault == "bad_summary":
        (directory / "entry/summary.json").write_text("{")
    assert ci.render_report(path, tmp_path / "results", tmp_path / "report") == 1
    d = ci.read(tmp_path / "report/report.json")
    assert len(d["cases"]) == 1 and d["problems"] and not d["complete"]
    if fault != "bad_summary":
        assert d["cases"][0]["status"] != "passed"


def test_progress_finish_without_junit_is_not_a_pass(tmp_path):
    path, directory, selected = fixture_plan(tmp_path, 1)
    child = directory / "entry/job-000"
    child.mkdir()
    (child / "events.jsonl").write_text(
        "\n".join(
            json.dumps({"event": stage, "nodeid": selected[0]})
            for stage in ["start", "finish"]
        )
    )
    assert ci.render_report(path, tmp_path / "results", tmp_path / "report") == 1
    assert (
        ci.read(tmp_path / "report/report.json")["cases"][0]["status"] == "incomplete"
    )


def test_all_native_passes_complete_and_summary_is_written(tmp_path, monkeypatch):
    path, directory, selected = fixture_plan(tmp_path, 1)
    native_job(directory, selected, ["passed"])
    summary = tmp_path / "github-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert ci.render_report(path, tmp_path / "results", tmp_path / "report") == 0
    assert ci.read(tmp_path / "report/report.json")["complete"] and summary.is_file()


def test_missing_plan_is_explicitly_unknown_and_nonzero(tmp_path):
    assert (
        ci.render_report(tmp_path / "missing.json", tmp_path, tmp_path / "report") == 1
    )
    assert "计划 未取得" in (tmp_path / "report/index.html").read_text()


def test_progress_telemetry_write_failure_does_not_interrupt_teardown(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("LSP_REGRESSION_PROGRESS", "1")
    monkeypatch.setenv("LSP_REGRESSION_CASE", str(tmp_path / "absent"))
    progress.emit("phase", nodes()[0], phase="teardown", outcome="passed")
    assert "progress unavailable" in capsys.readouterr().out


def test_actual_pytest_hooks_emit_start_phases_and_finish(tmp_path):
    directory = tmp_path / "case"
    directory.mkdir()
    test = tmp_path / "test_example.py"
    test.write_text("""class TestSynthetic:
 def test_example(self):
  import json,os
  from pathlib import Path
  from framework.test_node import CkbNode
  from framework.util import get_project_root
  p=Path(get_project_root())/os.environ['LSP_REGRESSION_RUNTIME']/'contract/node'
  p.mkdir(parents=True,exist_ok=False);(p/'database').write_text('synthetic database')
  node=CkbNode.__new__(CkbNode);node.ckb_dir=str(p);node.clean()
  assert (p/'database').read_text()=='synthetic database'
""")
    expected = "test_example.py::TestSynthetic::test_example"
    env = {
        **os.environ,
        "PYTHONPATH": str(runner.ROOT),
        "PYTEST_ADDOPTS": "",
        "PYTEST_PLUGINS": "",
        "LSP_REGRESSION_PROGRESS": "1",
        "LSP_REGRESSION_SELECTORS": json.dumps([expected]),
        "LSP_REGRESSION_RUNTIME": "tmp/lsp-ci-synthetic-"
        + __import__("uuid").uuid4().hex,
        "LSP_REGRESSION_CASE": str(directory),
        "LSP_REGRESSION_RETAIN": "1",
    }
    x = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--rootdir=" + str(tmp_path),
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-p",
            "scripts.lsp_regression_runtime",
            "--basetemp=" + str(tmp_path / "pytest-tmp"),
            str(test),
            "--junitxml=" + str(tmp_path / "junit.xml"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    (tmp_path / "child.log").write_text(x.stdout + x.stderr)
    assert x.returncode == 0, x.stdout + x.stderr
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
    ]
    assert [e["event"] for e in events] == [
        "start",
        "phase",
        "phase",
        "phase",
        "finish",
    ]
    assert [e.get("phase") for e in events if e["event"] == "phase"] == [
        "setup",
        "call",
        "teardown",
    ]
    assert all(e["nodeid"] == expected for e in events)
    kept = [
        json.loads(l)
        for l in (directory / "retained-paths.jsonl").read_text().splitlines()
    ]
    assert len(kept) == 1 and (Path(kept[0]["path"]) / "database").is_file()


def test_revision_cli_propagates_one_sha_without_expanding_parallel(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "REVISION", runner.DEFAULT_REVISION)
    monkeypatch.setattr(runner, "collect", lambda *a: nodes(1))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--revision",
            REVISION,
            "--plan-only",
            "--output",
            str(tmp_path / "plan"),
        ],
    )
    assert runner.main() == 0
    value = ci.read(tmp_path / "plan/plan.json")
    assert value["revision"] == REVISION and value["bundle"].endswith("pr-1623-aaaaaaa")
    env = runner.environment(tmp_path / "bundle")
    assert env["LSP_TEST_REVISION"] == env["LSP_RETEST_REVISION"] == REVISION
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--revision",
            REVISION,
            "--workers",
            "2",
            "--plan-only",
            "--output",
            str(tmp_path / "bad"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2 and not (tmp_path / "bad").exists()


def test_evidence_upload_failure_cannot_turn_all_native_passes_green(
    tmp_path, monkeypatch
):
    path, directory, selected = fixture_plan(tmp_path, 1)
    native_job(directory, selected, ["passed"])
    monkeypatch.setenv("LSP_CI_TESTS_RESULT", "failure")
    assert ci.render_report(path, tmp_path / "results", tmp_path / "report") == 1
    data = ci.read(tmp_path / "report/report.json")
    assert data["counts"] == {"passed": 1} and not data["complete"]
    assert data["stages"]["tests"] == "failure"


def test_build_disk_stop_reaps_owned_process_and_keeps_first_error(tmp_path):
    log = tmp_path / "build.log"

    def guard():
        if log.is_file() and "ready" in log.read_text():
            raise progress.DiskBudgetExceeded("synthetic build budget")

    with pytest.raises(progress.DiskBudgetExceeded):
        builder.execute(
            [sys.executable, "-u", "-c", "import time;print('ready');time.sleep(30)"],
            tmp_path,
            log,
            dict(os.environ),
            guard,
            10,
        )
    record = ci.read(log.with_suffix(".json"))
    assert "synthetic build budget" in record["error"] and not runner.group_exists(
        record["pid"]
    )
    assert "ready" in log.read_text()


def test_partial_progress_line_is_retried_not_lost(tmp_path, capsys):
    path = tmp_path / "events.jsonl"
    row = json.dumps({"event": "start", "nodeid": nodes()[0]})
    path.write_text(row[:15])
    cursor = [0]
    progress.display_events(tmp_path, nodes(), cursor)
    assert cursor == [0]
    path.write_text(row + "\n")
    progress.display_events(tmp_path, nodes(), cursor)
    assert "[LSP 1/4]" in capsys.readouterr().out


def test_disk_floor_and_batch_growth_are_both_enforced(tmp_path, monkeypatch):
    free = [20 * 2**30, 19 * 2**30, 17 * 2**30]
    monkeypatch.setattr(
        progress.shutil, "disk_usage", lambda _: SimpleNamespace(free=free.pop(0))
    )
    guard = progress.disk_guard(tmp_path, 2)
    guard()
    with pytest.raises(progress.DiskBudgetExceeded):
        guard()


def test_build_reserve_can_be_smaller_than_maximum_growth(tmp_path, monkeypatch):
    values = [14 * 2**30, 13 * 2**30, 7 * 2**30]
    monkeypatch.setattr(
        progress.shutil, "disk_usage", lambda _: SimpleNamespace(free=values.pop(0))
    )
    guard = progress.disk_guard(tmp_path, 12, reserve_gib=2)
    guard()
    with pytest.raises(progress.DiskBudgetExceeded):
        guard()


def test_owned_ci_ckb_stop_reaps_only_its_direct_child():
    from scripts.lsp_regression_runtime import PilotCkbNode

    first = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True
    )
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True
    )
    try:
        node = PilotCkbNode.__new__(PilotCkbNode)
        node._lsp_process, node.ckb_pid, node.ckb_miner_pid = first, first.pid, -1
        node.stop()
        assert first.returncode is not None and node.ckb_pid == -1
        assert unrelated.poll() is None
    finally:
        for process in (first, unrelated):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_disk_stop_interrupts_synthetic_child_and_keeps_raw_evidence(
    tmp_path, monkeypatch
):
    child = tmp_path / "child.py"
    child.write_text("""import json,os,signal,sys,time
from pathlib import Path
import xml.etree.ElementTree as ET
p=Path(os.environ['LSP_REGRESSION_CASE'])
def stop(*_):
 root=ET.Element('testsuites');suite=ET.SubElement(root,'testsuite')
 for n in json.loads(os.environ['LSP_REGRESSION_SELECTORS']):
  f,c,m=n.split('::');ET.SubElement(suite,'testcase',classname=f[:-3].replace('/','.')+'.'+c,name=m)
 ET.ElementTree(root).write(p/'junit.xml');sys.exit(1)
signal.signal(signal.SIGINT,stop)
(p/'ready').write_text(str(os.getpid()))
print('synthetic raw before disk stop',flush=True)
time.sleep(30)
""")
    original = subprocess.Popen
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda command, **kw: original([sys.executable, str(child)], **kw),
    )
    job = {"group": None, "nodeids": nodes(1)}
    directory = tmp_path / "run"

    def guard():
        if (directory / "ready").exists():
            raise progress.DiskBudgetExceeded("synthetic floor exhausted")

    result = runner.run_job(
        job, directory, tmp_path / "bundle", 10, progress=True, guard=guard
    )
    assert result["exit_code"] == 1 and any(
        "DiskBudgetExceeded" in e for e in result["errors"]
    )
    assert (
        not runner.group_exists(result["pid"]) and (directory / "junit.xml").is_file()
    )
    assert "synthetic raw before disk stop" in (directory / "stdout.log").read_text()


def test_runtime_archive_keeps_original_database_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    source = tmp_path / "tmp/lsp-owned/contract/node"
    source.mkdir(parents=True)
    (source / "database").write_bytes(b"original database")
    bucket = tmp_path / "bucket"
    ci.write(
        bucket / "entry/job-000/before-teardown/test/runtime.json",
        {"sources": [["ckb", str(source)]]},
    )
    ci.retain_runtime(bucket)
    assert (source / "database").read_bytes() == b"original database"
    manifest = ci.read(bucket / "runtime-manifest.json")
    assert len(manifest) == 1
    with tarfile.open(bucket / "runtime.tar.gz") as tar:
        assert (
            hashlib.sha256(tar.extractfile(manifest[0]["path"]).read()).hexdigest()
            == manifest[0]["sha256"]
        )


def test_valid_binary_bundle_restores_modes_and_refuses_overwrite(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(builder, "ROOT", tmp_path / "workspace")
    builder.ROOT.mkdir()
    payload = b"verified binary"
    name = "download/fnn"
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(payload), 0o755
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.addfile(info, io.BytesIO(payload))
    manifest = tmp_path / "manifest.json"
    ci.write(
        manifest,
        {"revision": REVISION, "files": {name: hashlib.sha256(payload).hexdigest()}},
    )
    builder.install(archive, manifest, REVISION)
    target = builder.ROOT / name
    assert target.read_bytes() == payload and os.access(target, os.X_OK)
    with pytest.raises(ValueError, match="overwrite"):
        builder.install(archive, manifest, REVISION)
    assert target.read_bytes() == payload


@pytest.mark.parametrize(
    "fault", ["traversal", "symlink", "duplicate", "revision", "checksum"]
)
def test_bad_binary_artifacts_are_rejected(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(builder, "ROOT", tmp_path / "workspace")
    builder.ROOT.mkdir()
    payload = b"binary"
    name = "../outside" if fault == "traversal" else "download/fnn"
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o755
    if fault == "symlink":
        info.type = tarfile.SYMTYPE
        info.linkname = "/outside"
        info.size = 0
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.addfile(info, io.BytesIO(payload))
        if fault == "duplicate":
            tar.addfile(info, io.BytesIO(payload))
    manifest = tmp_path / "manifest.json"
    ci.write(
        manifest,
        {
            "revision": "c" * 40 if fault == "revision" else REVISION,
            "files": {
                name: (
                    "bad"
                    if fault == "checksum"
                    else hashlib.sha256(payload).hexdigest()
                )
            },
        },
    )
    with pytest.raises(ValueError):
        builder.install(archive, manifest, REVISION)
    assert not (tmp_path / "outside").exists()


def test_native_success_does_not_override_test_source_drift(tmp_path, monkeypatch):
    plan_path, directory, selected = fixture_plan(tmp_path, 1)
    monkeypatch.setattr(ci.subprocess, "check_output", lambda *a, **kw: INTEGRATION)
    monkeypatch.setattr(
        ci.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0)
    )
    manifests = [{"test.py": "before"}, {"test.py": "after"}]
    monkeypatch.setattr(ci, "input_fingerprints", lambda: manifests.pop(0))
    output = tmp_path / "new"
    assert ci.run_bucket(plan_path, "query", output) == 2
    d = ci.read(output / "job.json")
    assert not d["inputs_unchanged"] and d["source_drift"] == ["test.py"]


def test_batch_deadline_does_not_start_next_job_and_retains_unstarted_plan(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "REVISION", runner.DEFAULT_REVISION)
    monkeypatch.setattr(runner, "collect", lambda *a: nodes(1))
    monkeypatch.setattr(
        runner,
        "run_job",
        lambda *a, **kw: pytest.fail("expired batch must not start a job"),
    )
    bundle = tmp_path / "bundle"
    ci.write(bundle / "build.json", {"revision": runner.DEFAULT_REVISION})
    out = tmp_path / "entry"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--bundle",
            str(bundle),
            "--output",
            str(out),
            "--batch-timeout",
            "0.000001",
        ],
    )
    assert runner.main() == 2
    assert ci.read(out / "summary.json")["unstarted_methods"] == nodes(1)


@pytest.mark.parametrize("fetch_failure", [False, True])
def test_cold_build_fetches_locked_dependencies_before_offline_delivery(
    tmp_path, monkeypatch, fetch_failure
):
    root, source, target = (tmp_path / n for n in ("workspace", "product", "target"))
    root.mkdir()
    source.mkdir()
    (source / "Cargo.toml").write_text("[workspace]\n")
    lock = source / "Cargo.lock"
    lock.write_text("version = 4\n# includes unbuilt optional/platform dependencies\n")
    original_lock = lock.read_bytes()
    cache = set()
    stages = []
    monkeypatch.setattr(builder, "ROOT", root)
    monkeypatch.setattr(builder, "disk_guard", lambda *a, **kw: lambda: None)

    def identity(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return REVISION + "\n"
        if command[:2] == ["git", "status"]:
            return ""
        assert command[-1] == "--version"
        return "Fiber (" + REVISION[:7] + ")"

    monkeypatch.setattr(builder.subprocess, "check_output", identity)

    def put(relative):
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"synthetic binary")

    def execute(command, cwd, log_path, env, guard, timeout=5400):
        log_path.write_text("synthetic build step\n")
        assert (source / "Cargo.lock").read_bytes() == original_lock
        guard()
        if str(command[1]).endswith("download.py"):
            stages.append("ckb")
            put("download/0.202.0/ckb")
            put("download/0.202.0/ckb-cli")
            (root / "source").mkdir()
        elif str(command[1]).endswith("build_lsp_test_binaries.py"):
            stages.append("base")
            put("download/fiber/pr-1623-" + REVISION[:7] + "/fnn")
        elif command[:2] == ["cargo", "fetch"]:
            stages.append("fetch")
            assert command == [
                "cargo",
                "fetch",
                "--locked",
                "--manifest-path",
                str(source / "Cargo.toml"),
            ]
            assert cwd == source and timeout == 300
            if fetch_failure:
                raise RuntimeError("synthetic dependency fetch failed")
            cache.add("bincode-2.0.1")
        elif str(command[1]).endswith("build_lsp_delivery_node.py"):
            stages.append("delivery")
            if "bincode-2.0.1" not in cache:
                raise RuntimeError("bincode missing; --offline was specified")
            put("download/fiber/delivery-" + REVISION[:7] + "/lsp-delivery-node")
        else:
            assert command[:2] == ["cargo", "build"] and "--locked" in command
            stages.append("nolsp")
            (target / "debug").mkdir(parents=True)
            (target / "debug/fnn").write_bytes(b"synthetic fnn")

    monkeypatch.setattr(builder, "execute", execute)
    output = root / "output"
    if fetch_failure:
        with pytest.raises(RuntimeError, match="dependency fetch failed"):
            builder.build(source, REVISION, target, output)
        assert stages == ["ckb", "base", "fetch"]
        assert not (output / "runtime.tar.gz").exists()
    else:
        builder.build(source, REVISION, target, output)
        assert stages == ["ckb", "base", "fetch", "delivery", "nolsp"]
        assert ci.read(output / "runtime-manifest.json")["revision"] == REVISION
        assert (output / "runtime.tar.gz").is_file()
    assert lock.read_bytes() == original_lock


def test_workflow_has_no_schedule_no_runtime_parallel_and_always_reports():
    workflow = yaml.load(
        (runner.ROOT / ".github/workflows/lsp-ci.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_call"}
    strategy = workflow["jobs"]["tests"]["strategy"]
    assert strategy["max-parallel"] == "1" and strategy["fail-fast"] == "false"
    assert workflow["jobs"]["report"]["if"] == "always()"
    assert workflow["permissions"] == {"contents": "read"}
    source = (runner.ROOT / "scripts/lsp_ci.py").read_text()
    assert '"--workers",\n        "1"' in source or '"--workers", "1"' in source

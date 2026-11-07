"""Deterministic checks for the F2 fast runner; no FNN, SDK batch or long test."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.manual_nightly

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_lsp_refund_f2_fast as runner  # noqa: E402


def _copy_bundle(source, target):
    target.mkdir()
    shutil.copy2(source / "build.json", target / "build.json")
    shutil.copy2(source / "lsp-refund-f2-fast", target / "lsp-refund-f2-fast")
    shutil.copytree(source / "helper-build", target / "helper-build")


def _mutate_manifest(bundle, key, value):
    path = bundle / "build.json"
    manifest = json.loads(path.read_text())
    if key == "sha256":
        manifest["sha256"]["lsp-refund-f2-fast"] = value
    else:
        manifest[key] = value
    path.write_text(json.dumps(manifest, indent=2) + "\n")


# TEST-MAP: LSP-REFUND-F2-05
def test_preflight_rejects_missing_or_mismatched_bundle(tmp_path):
    deadline = time.monotonic() + 15
    events = io.StringIO()
    with pytest.raises((FileNotFoundError, ValueError)):
        runner.preflight(tmp_path / "missing", deadline, events, time.monotonic())

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "build.json").write_text('{"kind":"wrong"}')
    with pytest.raises((KeyError, ValueError)):
        runner.preflight(bad, deadline, events, time.monotonic())

    # Exercise actual bundle mutations: version, source, lock, helper source,
    # helper lock/manifest, and binary digest must each fail in preflight.
    source_bundle = Path(os.environ["LSP_REFUND_F2_BUNDLE"])
    source = Path(json.loads((source_bundle / "build.json").read_text())["source"])
    cases = (
        (
            "revision",
            "wrong",
            ValueError,
            "fast bundle kind or fixed product revision mismatch",
        ),
        ("source", str(tmp_path / "missing-source"), FileNotFoundError, None),
        ("cargo_lock_sha256", "0" * 64, ValueError, source / "Cargo.lock"),
        ("helper_source_sha256", "0" * 64, ValueError, runner.HELPER_SOURCE),
        ("helper_lock_sha256", "0" * 64, ValueError, "bundle/helper-build/Cargo.lock"),
        (
            "helper_manifest_sha256",
            "0" * 64,
            ValueError,
            "bundle/helper-build/Cargo.toml",
        ),
        ("sha256", "0" * 64, ValueError, "bundle/lsp-refund-f2-fast"),
    )
    mutated_bundle = None
    for key, value, error_type, target in cases:
        bundle = tmp_path / f"bundle-{key}"
        _copy_bundle(source_bundle, bundle)
        _mutate_manifest(bundle, key, value)
        if key == "revision":
            mutated_bundle = bundle
        with pytest.raises(error_type) as error:
            runner.preflight(
                bundle, time.monotonic() + 15, events, time.monotonic()
            )
        if target is not None:
            if isinstance(target, str) and target.startswith("bundle/"):
                target = bundle / target.removeprefix("bundle/")
            if key == "revision":
                expected = target
            else:
                expected = f"SHA256 mismatch: {target}"
            assert str(error.value) == expected, (key, str(error.value))

    # Exercise the actual entry too: missing and mutated manifests must fail in
    # preflight, not start SDK/pytest.
    for index, bundle in enumerate((tmp_path / "missing", mutated_bundle)):
        output = tmp_path / f"entry-output-{index}"
        completed = subprocess.run(
            [
                str(ROOT / "venv/bin/python"),
                str(ROOT / "scripts/run_lsp_refund_f2_fast.py"),
                "--bundle",
                str(bundle),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert completed.returncode != 0, completed
        assert "environment failure" in completed.stderr, completed.stderr
        assert (output / "result.json").is_file()


# TEST-MAP: LSP-REFUND-F2-06
def test_outer_registry_reaps_separate_self_test_group(tmp_path):
    registry = Path(os.environ["LSP_REFUND_F2_OWNED_PIDS"])
    command = [
        sys.executable,
        "-c",
        (
            "import os,subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
            "start_new_session=True); "
            "open(os.environ['LSP_REFUND_F2_OWNED_PIDS'],'a').write(str(p.pid)+chr(10)); "
            "print(p.pid, flush=True); time.sleep(30)"
        ),
    ]
    result = runner.supervise(
        command,
        cwd=runner.ROOT,
        env=dict(os.environ),
        output=tmp_path,
        started_at=time.monotonic(),
        term_after=0.4,
        kill_after=0.7,
        hard_after=2.0,
    )
    assert result["exit_code"] == 124, result
    child_pid = int((tmp_path / "stdout.log").read_text().strip())
    owned = registry.read_text().splitlines()
    assert str(child_pid) in owned, owned
    # Drop pytest's own group; the test must not kill its carrier. Keep the
    # separately registered self-test group and exercise the actual fallback.
    filtered = tmp_path / "filtered-pids"
    filtered.write_text(
        "\n".join(line for line in owned if line != str(os.getpgrp())) + "\n"
    )
    runner._kill_registered(filtered)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"registered child {child_pid} survived outer cleanup")


# TEST-MAP: LSP-REFUND-F2-06
def test_supervisor_terminates_owned_group_and_preserves_unrelated(tmp_path):
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        start_new_session=True,
    )
    runner._register_group(unrelated.pid)
    command = [
        sys.executable,
        "-c",
        (
            "import signal,subprocess,sys,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
            "print('ready', flush=True); time.sleep(10)"
        ),
    ]
    try:
        result = runner.supervise(
            command,
            cwd=runner.ROOT,
            env=dict(os.environ),
            output=tmp_path,
            started_at=time.monotonic(),
            term_after=0.3,
            kill_after=0.6,
            hard_after=2.0,
        )
        assert unrelated.poll() is None, "unrelated process was killed"
        assert result["exit_code"] == 124, result
        assert result["term_sent"] and result["kill_sent"], result
        assert result["group_remaining"] is False, result
        assert (tmp_path / "stdout.log").read_text() == "ready\n"
        assert (tmp_path / "supervisor.jsonl").read_text().strip()
        registry = os.environ.get("LSP_REFUND_F2_OWNED_PIDS")
        assert registry and Path(registry).is_file(), registry
        report_env = os.environ.get("LSP_REFUND_F2_REPORT_DIR")
        if report_env:
            evidence = Path(report_env) / "runner-selftest-evidence"
            evidence.mkdir(parents=True, exist_ok=True)
            for name in ("stdout.log", "stderr.log", "supervisor.jsonl"):
                shutil.copy2(tmp_path / name, evidence / name)
    finally:
        unrelated.terminate()
        try:
            unrelated.wait(timeout=5)
        except subprocess.TimeoutExpired:
            unrelated.kill()
            unrelated.wait(timeout=5)

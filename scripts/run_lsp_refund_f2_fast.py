#!/usr/bin/env python3
"""Run only the prepared SDK refund fast checks within one 300-second budget."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
REVISION = "56c761c45c271c086b05c8d5ea3e033448f5fdf8"
HELPER_SOURCE = ROOT / "test_cases/fiber/devnet/lsp_nightly/_tlc_refund_adapter_fast.rs"
SELECTORS = (
    "test_cases/fiber/devnet/lsp_nightly/test_tlc_refund_adapter_fast.py",
    "test_cases/framework/test_lsp_refund_f2_runner.py",
)
PREFLIGHT_SECONDS = 15.0
# Leave one second within the preflight limit to kill git and write a failure result.
PREFLIGHT_CHECK_SECONDS = PREFLIGHT_SECONDS - 1.0
TERM_SECONDS = 270.0
KILL_SECONDS = 275.0
HARD_SECONDS = 300.0
_owned_groups = set()
_registry_path = None


def _register_group(pgid):
    """Record a child PGID where the outer runner can reap it on forced exit."""
    path = os.environ.get("LSP_REFUND_F2_OWNED_PIDS")
    if not path:
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, f"{pgid}\n".encode())
    finally:
        os.close(fd)


def _kill_registered(path):
    if path is None:
        return
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return
    for line in lines:
        try:
            _signal_group(int(line), signal.SIGKILL)
        except (TypeError, ValueError):
            continue


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _event(stream, started_at, event, **fields):
    stream.write(
        json.dumps(dict(event=event, elapsed=time.monotonic() - started_at, **fields))
        + "\n"
    )
    stream.flush()


def _digest(path, deadline):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            if time.monotonic() >= deadline:
                raise TimeoutError("15-second preflight deadline exceeded")
            value.update(block)
    return value.hexdigest()


def _git(source, args, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("15-second preflight deadline exceeded")
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *args]
    child = subprocess.Popen(
        command,
        cwd=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _owned_groups.add(child.pid)
    try:
        stdout, stderr = child.communicate(timeout=remaining)
        if child.returncode:
            raise ValueError(f"git {' '.join(args)} failed: {stderr.strip()}")
        return stdout.strip()
    finally:
        _signal_group(child.pid, signal.SIGKILL)
        try:
            child.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        _owned_groups.discard(child.pid)


def preflight(bundle, deadline, events, started_at):
    """Validate local inputs; the caller also installs an interrupting deadline."""
    manifest = json.loads((bundle / "build.json").read_text())
    if manifest["kind"] != "lsp-refund-f2-fast" or manifest["revision"] != REVISION:
        raise ValueError("fast bundle kind or fixed product revision mismatch")
    if not manifest.get("build_command"):
        raise ValueError("fast bundle does not record its build command")
    source = Path(manifest["source"])
    if not source.is_absolute():
        raise ValueError("manifest source must be an absolute product checkout path")
    source = source.resolve(strict=True)
    for args, expected in (
        (["rev-parse", "HEAD"], REVISION),
        (["status", "--porcelain", "--untracked-files=no"], ""),
    ):
        begin = time.monotonic()
        command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *args]
        _event(
            events, started_at, "preflight-command", command=command, cwd=str(source)
        )
        actual = _git(source, args, deadline)
        if actual != expected:
            raise ValueError(
                f"product checkout is not the clean fixed HEAD: git {' '.join(args)}"
            )
        _event(
            events,
            started_at,
            "preflight-check",
            check="product-git",
            command=command,
            seconds=time.monotonic() - begin,
        )
    checks = [
        (source / "Cargo.lock", manifest["cargo_lock_sha256"]),
        (HELPER_SOURCE, manifest["helper_source_sha256"]),
        (bundle / "helper-build/main.rs", manifest["helper_source_sha256"]),
        (bundle / "helper-build/Cargo.lock", manifest["helper_lock_sha256"]),
        (bundle / "helper-build/Cargo.toml", manifest["helper_manifest_sha256"]),
        (bundle / "lsp-refund-f2-fast", manifest["sha256"]["lsp-refund-f2-fast"]),
    ]
    for path, expected in checks:
        begin = time.monotonic()
        actual = _digest(path, deadline)
        if actual != expected:
            raise ValueError(f"SHA256 mismatch: {path}")
        _event(
            events,
            started_at,
            "preflight-check",
            check="sha256",
            path=str(path),
            sha256=actual,
            seconds=time.monotonic() - begin,
        )
    if not os.access(bundle / "lsp-refund-f2-fast", os.X_OK):
        raise ValueError("fast helper is not executable")
    free = shutil.disk_usage(ROOT).free
    if free < 8 * 1024**3:
        raise ValueError(f"less than 8 GiB free: {free} bytes")
    if time.monotonic() >= deadline:
        raise TimeoutError("15-second preflight deadline exceeded")
    _event(events, started_at, "preflight-complete", free_bytes=free)
    return manifest


def supervise(
    command,
    *,
    cwd,
    env,
    output,
    started_at,
    term_after=TERM_SECONDS,
    kill_after=KILL_SECONDS,
    hard_after=HARD_SECONDS,
):
    """Supervise one owned session; short thresholds are available to future unit checks."""
    if not 0 < term_after < kill_after < hard_after:
        raise ValueError("expected 0 < TERM < KILL < hard deadline")
    term_at, kill_at = started_at + term_after, started_at + kill_after
    # Reserve the end of the shared budget for result writing and exit.
    finish_at = started_at + hard_after - min(5.0, (hard_after - kill_after) / 2)
    result = {
        "command": list(command),
        "started_mono": started_at,
        "term_at": term_at,
        "kill_at": kill_at,
        "hard_at": started_at + hard_after,
        "timed_out": False,
        "term_sent": False,
        "kill_sent": False,
    }
    if time.monotonic() >= term_at:
        return dict(
            result, exit_code=124, timed_out=True, reason="no execution budget left"
        )
    with (output / "stdout.log").open("wb", buffering=0) as stdout, (
        output / "stderr.log"
    ).open("wb", buffering=0) as stderr, (output / "supervisor.jsonl").open(
        "a"
    ) as events:
        child = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        pgid = child.pid
        _owned_groups.add(pgid)
        try:
            _register_group(pgid)
        except BaseException:
            _signal_group(pgid, signal.SIGKILL)
            try:
                child.wait(timeout=1)
            finally:
                _owned_groups.discard(pgid)
            raise
        result["pid"] = result["pgid"] = pgid
        _event(
            events,
            started_at,
            "child-start",
            pid=child.pid,
            pgid=pgid,
            command=list(command),
        )
        residual_children = False
        try:
            while True:
                code = child.poll()
                alive = _group_exists(pgid)
                now = time.monotonic()
                if code is not None and not alive:
                    break
                if code is not None and not result["term_sent"]:
                    # A completed pytest must not leave a helper behind.
                    residual_children = True
                    term_at, kill_at = now, min(kill_at, now + 5.0)
                if now >= term_at and not result["term_sent"]:
                    result["timed_out"] = code is None
                    result["term_sent"] = True
                    _signal_group(pgid, signal.SIGTERM)
                    _event(events, started_at, "term", pgid=pgid)
                if now >= kill_at and not result["kill_sent"]:
                    result["kill_sent"] = True
                    _signal_group(pgid, signal.SIGKILL)
                    _event(events, started_at, "kill", pgid=pgid)
                if now >= finish_at:
                    result["timed_out"] = True
                    break
                time.sleep(min(0.05, max(0.001, finish_at - now)))
        finally:
            if _group_exists(pgid):
                _signal_group(pgid, signal.SIGKILL)
                result["kill_sent"] = True
            try:
                child.wait(timeout=max(0.001, min(0.5, finish_at - time.monotonic())))
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
            result["child_exit_code"] = child.returncode
            result["group_remaining"] = _group_exists(pgid)
            if not result["group_remaining"]:
                _owned_groups.discard(pgid)
            _event(
                events,
                started_at,
                "cleanup",
                child_exit_code=child.returncode,
                group_remaining=result["group_remaining"],
            )
    result["exit_code"] = (
        124
        if result["timed_out"]
        else 1 if residual_children or result["group_remaining"] else child.returncode
    )
    result["elapsed"] = time.monotonic() - started_at
    return result


def main():
    started_at = time.monotonic()

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    def preflight_timeout(_signum, _frame):
        raise TimeoutError("15-second preflight deadline exceeded")

    def emergency_timeout(_signum, _frame):
        for pgid in tuple(_owned_groups):
            _signal_group(pgid, signal.SIGKILL)
        _kill_registered(_registry_path)
        # The normal path writes the result. This last guard cannot wait on I/O.
        os._exit(124)

    signal.signal(signal.SIGALRM, preflight_timeout)
    signal.signal(signal.SIGTERM, interrupted)
    signal.setitimer(signal.ITIMER_REAL, PREFLIGHT_CHECK_SECONDS)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, help="A new report directory; existing paths are refused"
    )
    parser.add_argument(
        "--junitxml",
        type=Path,
        help="Fresh native JUnit path supplied by the evidence wrapper",
    )
    args = parser.parse_args()
    name = f"lsp-refund-f2-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    output = (args.output or ROOT / "report" / name).absolute()
    output.mkdir(parents=True, exist_ok=False)
    global _registry_path
    _registry_path = output / "owned-pids"
    print(f"F2 report: {output}", flush=True)
    result = {"started_mono": started_at, "output": str(output), "exit_code": 2}
    preflight_complete = False
    try:
        bundle = args.bundle.resolve(strict=True)
        junit = (args.junitxml or output / "junit.xml").absolute()
        if junit.exists() or junit.is_symlink():
            raise ValueError(f"refusing to replace existing JUnit: {junit}")
        junit.parent.mkdir(parents=True, exist_ok=True)
        with (output / "supervisor.jsonl").open("a") as events:
            preflight(bundle, started_at + PREFLIGHT_CHECK_SECONDS, events, started_at)
        preflight_complete = True
        result["preflight_seconds"] = time.monotonic() - started_at
        signal.signal(signal.SIGALRM, emergency_timeout)
        signal.setitimer(
            signal.ITIMER_REAL,
            max(0.001, started_at + HARD_SECONDS - 1 - time.monotonic()),
        )
        env = dict(
            os.environ,
            PYTEST_ADDOPTS="",
            PYTHONUNBUFFERED="1",
            LSP_REFUND_F2_BUNDLE=str(bundle),
            LSP_REFUND_F2_REPORT_DIR=str(output),
            LSP_REFUND_F2_DEADLINE=str(started_at + TERM_SECONDS),
            LSP_REFUND_F2_HARD_DEADLINE=str(started_at + HARD_SECONDS),
            LSP_REFUND_F2_OWNED_PIDS=str(_registry_path),
        )
        command = [
            str(ROOT / "venv/bin/python"),
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-vv",
            "-s",
            "--tb=short",
            "--run-lsp-refund-nightly",
            f"--junitxml={junit}",
            *SELECTORS,
        ]
        result.update(
            supervise(command, cwd=ROOT, env=env, output=output, started_at=started_at)
        )
        result["junitxml"] = str(junit)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        TimeoutError,
    ) as error:
        result.update(exit_code=2, error=str(error), status="environment-failed")
        print(f"F2 environment failure: {error}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        result.update(exit_code=130, status="interrupted")
    finally:
        for pgid in tuple(_owned_groups):
            _signal_group(pgid, signal.SIGKILL)
        _kill_registered(_registry_path)
        # Result I/O is also part of the original budget, including failures in preflight.
        signal.signal(signal.SIGALRM, emergency_timeout)
        final_limit = HARD_SECONDS - 1 if preflight_complete else PREFLIGHT_SECONDS
        signal.setitimer(
            signal.ITIMER_REAL, max(0.001, started_at + final_limit - time.monotonic())
        )
    try:
        result["elapsed"] = time.monotonic() - started_at
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(
            f"F2 exit={result['exit_code']} elapsed={result['elapsed']:.3f}s",
            flush=True,
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build the reviewed LSP node and real SDK agent from one clean checkout."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

REVISION = "76307312e8de518c9a32074e6d16867c04de4f86"
ROOT = Path(__file__).resolve().parents[1]
F2_REVISION = "56c761c45c271c086b05c8d5ea3e033448f5fdf8"


def build_refund_f2(args):
    """Build only the reviewed offline SDK helper, without touching node bundles."""
    if args.revision != F2_REVISION:
        raise ValueError(f"F2 helper requires reviewed revision {F2_REVISION}")
    source, output, target = (
        args.source.resolve(),
        args.output.resolve(),
        args.target_dir.resolve(),
    )
    helper = ROOT / "test_cases/fiber/devnet/lsp_nightly/_tlc_refund_adapter_fast.rs"
    started = time.monotonic()
    hard_due = started + 600  # Explicit preparation, outside the 300s test runner.
    work_due = hard_due - 30  # Reserve time to reap every owned process group.
    initial_free = shutil.disk_usage(ROOT).free
    if initial_free < 8 * 1024**3:
        raise RuntimeError("F2 build requires at least 8 GiB free")
    owned = {}

    def check_budget():
        if time.monotonic() >= work_due:
            raise TimeoutError(
                "F2 build work exceeded 570 seconds; 30 seconds reserved for cleanup"
            )
        free = shutil.disk_usage(ROOT).free
        if free < 8 * 1024**3 or initial_free - free > 2 * 1024**3:
            raise RuntimeError(
                "F2 build disk budget exceeded (8 GiB floor / 2 GiB growth)"
            )
        if time.monotonic() >= work_due:
            raise TimeoutError("F2 build work deadline exceeded during resource check")
        return free

    def group_exists(pgid):
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False

    def signal_group(pgid, sig):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass

    def cleanup(process):
        # The Cargo parent may have exited while rustc/build-script children remain.
        process.poll()
        if group_exists(process.pid):
            signal_group(process.pid, signal.SIGTERM)
            term_due = min(time.monotonic() + 5, hard_due - 2)
            while group_exists(process.pid) and time.monotonic() < term_due:
                process.poll()
                time.sleep(min(0.05, max(0.001, term_due - time.monotonic())))
        if group_exists(process.pid):
            signal_group(process.pid, signal.SIGKILL)
            kill_due = min(time.monotonic() + 5, hard_due - 1)
            while group_exists(process.pid) and time.monotonic() < kill_due:
                process.poll()
                time.sleep(min(0.05, max(0.001, kill_due - time.monotonic())))
        process.poll()
        if group_exists(process.pid) or process.returncode is None:
            raise RuntimeError(f"F2 build process group {process.pid} did not exit")
        owned.pop(process.pid, None)

    def emergency_timeout(_signum, _frame):
        for pgid in tuple(owned):
            signal_group(pgid, signal.SIGKILL)
        # Do not let blocked filesystem I/O or process cleanup exceed 600 seconds.
        os._exit(124)

    def sha(path):
        check_budget()
        value = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                check_budget()
                value.update(block)
        check_budget()
        return value.hexdigest()

    def copy(source_path, destination):
        check_budget()
        with source_path.open("rb") as reader, destination.open("xb") as writer:
            while block := reader.read(1024 * 1024):
                check_budget()
                writer.write(block)
                writer.flush()
                check_budget()
        check_budget()
        shutil.copystat(source_path, destination)
        check_budget()

    def write(path, content):
        check_budget()
        with path.open("x") as stream:
            stream.write(content)
        check_budget()

    def check_source():
        check_budget()
        head = run(["git", "rev-parse", "HEAD"], capture=True, seconds=10).strip()
        dirty = run(["git", "status", "--porcelain"], capture=True, seconds=10)
        if head != args.revision or dirty:
            raise RuntimeError(
                "F2 product source must be clean and match the fixed revision"
            )
        check_budget()

    def run(command, capture=False, seconds=None):
        check_budget()  # Never start another Cargo command after work has expired.
        command_due = min(work_due, time.monotonic() + seconds) if seconds else work_due
        process = subprocess.Popen(
            command,
            cwd=source,
            env=env,
            start_new_session=True,
            text=capture,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
        owned[process.pid] = process
        stdout, stderr = None, None
        try:
            while True:
                check_budget()
                remaining = command_due - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"F2 build command deadline exceeded: {command}")
                if capture:
                    try:
                        stdout, stderr = process.communicate(
                            timeout=min(0.2, remaining)
                        )
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if process.poll() is not None:
                    break
                time.sleep(min(0.2, remaining))
            check_budget()  # Include disk growth in the final polling interval.
            if process.returncode:
                raise subprocess.CalledProcessError(
                    process.returncode, command, stdout, stderr
                )
        finally:
            cleanup(process)
        check_budget()
        return stdout

    env = dict(
        os.environ,
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_INCREMENTAL="0",
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_JOBS="2",
        CARGO_NET_OFFLINE="true",
    )

    def build_locked():
        check_budget()
        while True:
            check_budget()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(0.2, max(0.001, work_due - time.monotonic())))
        check_budget()
        output.mkdir(parents=True, exist_ok=False)
        check_budget()
        build = output / "helper-build"
        build.mkdir()
        check_budget()
        dependencies = "\n".join(
            f"{name} = {{ path = {json.dumps(str(source / path))} }}"
            for name, path in (
                ("fiber-lsp-sdk", "crates/fiber-lsp-sdk"),
                ("fiber-types", "crates/fiber-types"),
            )
        )
        write(
            build / "Cargo.toml",
            '[package]\nname = "lsp-refund-f2-fast"\nversion = "0.1.0"\nedition = "2021"\n'
            '[workspace]\n[[bin]]\nname = "lsp-refund-f2-fast"\npath = "main.rs"\n'
            "[dependencies]\n" + dependencies + "\n"
            'anyhow = "1"\nasync-trait = "0.1"\nhex = "0.4"\n'
            'ckb-types = "1"\nckb-jsonrpc-types = "1"\nserde_json = "1"\n'
            'musig2 = { version = "=0.2.4", features = ["secp256k1", "serde"] }\n'
            'tokio = { version = "1", features = ["macros", "rt"] }\n',
        )
        copy(helper, build / "main.rs")
        copy(source / "Cargo.lock", build / "Cargo.lock")
        # Resolve only this new local package against the copied lock, using cache.
        # Subsequent compilations use the resulting helper lock unchanged.
        command = [
            "cargo",
            "build",
            "--offline",
            "--manifest-path",
            str(build / "Cargo.toml"),
        ]
        print(f"F2-only build: {json.dumps(command)}", flush=True)
        print(
            f"free_before={initial_free}; growth_limit=2147483648; cache={target}",
            flush=True,
        )
        run(command)
        helper_lock = sha(build / "Cargo.lock")
        locked_command = [
            "cargo",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(build / "Cargo.toml"),
        ]
        run(locked_command)
        check_source()
        if sha(source / "Cargo.lock") != product_lock or sha(helper) != helper_digest:
            raise RuntimeError("F2 source changed while building")
        if sha(build / "Cargo.lock") != helper_lock:
            raise RuntimeError("F2 helper lock changed during locked build")
        binary = output / "lsp-refund-f2-fast"
        copy(target / "debug/lsp-refund-f2-fast", binary)
        manifest = {
            "kind": "lsp-refund-f2-fast",
            "revision": args.revision,
            "source": str(source),
            "cargo_lock_sha256": product_lock,
            "helper_source_sha256": helper_digest,
            "helper_lock_sha256": helper_lock,
            "helper_manifest_sha256": sha(build / "Cargo.toml"),
            "sha256": {binary.name: sha(binary)},
            "prepare_command": command,
            "build_command": locked_command,
            "profile": "dev",
            "target_dir": str(target),
            "duration_seconds": time.monotonic() - started,
            "free_before_bytes": initial_free,
            "free_after_bytes": check_budget(),
        }
        # Publish a success manifest only after all output and budget checks pass.
        temporary_manifest = output / "build.json.pending"
        write(temporary_manifest, json.dumps(manifest, indent=2) + "\n")
        check_budget()
        temporary_manifest.rename(output / "build.json")
        try:
            check_budget()
        except BaseException:
            (output / "build.json").unlink(missing_ok=True)
            raise
        print(f"Installed offline F2 SDK helper in {output}", flush=True)

    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, emergency_timeout)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, hard_due - 1 - time.monotonic()))
    try:
        check_source()
        product_lock = sha(source / "Cargo.lock")
        helper_digest = sha(helper)
        check_budget()
        target.mkdir(parents=True, exist_ok=True)
        check_budget()
        with (target / ".lsp-refund-f2-build.lock").open("a") as lock:
            try:
                build_locked()
            finally:
                # Keep the cache lock until all our descendants have been reaped.
                for process in tuple(owned.values()):
                    cleanup(process)
    finally:
        try:
            for process in tuple(owned.values()):
                cleanup(process)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
            if old_timer[0]:
                signal.setitimer(
                    signal.ITIMER_REAL,
                    max(0.001, old_timer[0] - (time.monotonic() - started)),
                    old_timer[1],
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--revision", default=REVISION, help="Exact reviewed Fiber commit"
    )
    parser.add_argument(
        "--target-dir", type=Path, help="Optional reusable Cargo build directory"
    )
    parser.add_argument(
        "--upstream-only",
        action="store_true",
        help="Build FNN and the upstream SDK agent without the local integration driver",
    )
    parser.add_argument("--driver-only", action="store_true")
    parser.add_argument(
        "--refund-f2-only",
        action="store_true",
        help="Build only the fixed-revision offline F2 SDK helper (no FNN)",
    )
    parser.add_argument("--base-bundle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.refund_f2_only:
        if (
            args.upstream_only
            or args.driver_only
            or args.base_bundle
            or not all((args.output, args.target_dir))
        ):
            parser.error(
                "--refund-f2-only requires --output and --target-dir and excludes other build modes"
            )
        if args.output.exists() or args.output.is_symlink():
            parser.error("--output must not already exist")
        build_refund_f2(args)
        return
    if args.driver_only:
        if args.upstream_only or not all(
            (args.base_bundle, args.output, args.target_dir)
        ):
            parser.error(
                "--driver-only requires --base-bundle, --output and --target-dir; incompatible with --upstream-only"
            )
        if args.output.exists() or args.output.is_symlink():
            parser.error("--output must not already exist")
    elif args.base_bundle or args.output:
        parser.error("--base-bundle and --output require --driver-only")
    if len(args.revision) != 40 or any(
        c not in "0123456789abcdef" for c in args.revision
    ):
        parser.error("--revision must be a full lowercase commit SHA")
    source = args.source.resolve()
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if revision != args.revision:
        parser.error(f"expected Fiber {args.revision}, got {revision}")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=source, check=True)
    target = (args.target_dir or source / "target").resolve()
    env = dict(
        os.environ,
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_INCREMENTAL="0",
        CARGO_TARGET_DIR=str(target),
    )
    command = [
        "cargo",
        "build",
        "--locked",
        "-p",
        "fiber-bin",
        "-p",
        "fiber-lsp-sdk-agent",
        "--features",
        "fiber-bin/debug-add-tlc",
    ]
    base_manifest = None
    reused_files = (
        "fnn",
        "fiber-lsp-sdk-agent",
        "biscuit-private-key",
        "operator-token",
    )
    if args.driver_only:
        base = args.base_bundle.resolve()
        base_manifest = json.loads((base / "build.json").read_text())
        assert base_manifest["revision"] == args.revision, "base revision mismatch"
        assert (
            base_manifest["cargo_lock_sha256"]
            == hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest()
        ), "base source lock mismatch"
        for name in reused_files:
            assert (
                hashlib.sha256((base / name).read_bytes()).hexdigest()
                == base_manifest["sha256"][name]
            ), f"base hash mismatch: {name}"
        assert (
            hashlib.sha256((base / "driver-build/Cargo.lock").read_bytes()).hexdigest()
            == base_manifest["driver_lock_sha256"]
        ), "base driver lock mismatch"
        base_version = subprocess.check_output(
            [str(base / "fnn"), "--version"], text=True
        ).strip()
        assert (
            base_version == base_manifest["fnn_version"]
            and args.revision[:7] in base_version
            and "dirty" not in base_version
        ), "base FNN version mismatch"
    else:
        subprocess.run(command, cwd=source, env=env, check=True)
    # Check again so a source change during compilation cannot be silently installed.
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=source, check=True)
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == args.revision
    )

    output = (
        args.output.resolve()
        if args.driver_only
        else ROOT / "download/fiber" / f"pr-1623-{args.revision[:7]}"
    )
    output.mkdir(parents=True, exist_ok=not args.driver_only)
    if not args.upstream_only:
        driver_source = ROOT / "test_cases/fiber/devnet/lsp/_sdk_driver.rs"
        driver_build = output / "driver-build"
        driver_build.mkdir(exist_ok=True)
        dependencies = "\n".join(
            f"{name} = {{ path = {json.dumps(str(source / path))} }}"
            for name, path in (
                ("fiber-lsp-sdk-agent", "tests/fiber-lsp-sdk-agent"),
                ("fiber-lsp-sdk", "crates/fiber-lsp-sdk"),
                ("fiber-types", "crates/fiber-types"),
                ("fiber-json-types", "crates/fiber-json-types"),
            )
        )
        (driver_build / "Cargo.toml").write_text(
            '[package]\nname = "lsp-integration-driver"\nversion = "0.1.0"\nedition = "2021"\n'
            '[workspace]\n[[bin]]\nname = "lsp-integration-driver"\npath = "main.rs"\n'
            "[dependencies]\n" + dependencies + "\n"
            'anyhow = "1.0"\nclap = { version = "4.5", features = ["derive"] }\n'
            'biscuit-auth = "=6.0.0"\n'
            'reqwest = { version = "0.12", features = ["json"] }\nasync-trait = "0.1"\nhex = "0.4"\nckb-system-scripts = "=0.5.4"\n'
            'secp256k1 = { version = "0.30", features = ["recovery", "global-context"] }\n'
            'ckb-types = "1"\nckb-jsonrpc-types = "1"\n'
            'serde = { version = "1.0", features = ["derive"] }\nserde_json = "1.0"\n'
            'tokio = { version = "1", features = ["io-util", "net", "macros", "rt-multi-thread", "time"] }\n'
            'rocksdb = { package = "ckb-rocksdb", version = "=0.21.1", default-features = false, features = ["lz4"] }\n'
        )
        shutil.copy2(driver_source, driver_build / "main.rs")
        chain_source = driver_source.with_name("_watchtower_chain.rs")
        shutil.copy2(chain_source, driver_build / chain_source.name)
        if not (driver_build / "Cargo.lock").exists():
            shutil.copy2(
                (
                    base / "driver-build/Cargo.lock"
                    if args.driver_only
                    else source / "Cargo.lock"
                ),
                driver_build / "Cargo.lock",
            )
        # Resolve and cache the driver's additional dependencies on a cold host.
        # The following build uses exactly this lock, with no further network access.
        if not args.driver_only:
            subprocess.run(
                ["cargo", "fetch", "--manifest-path", str(driver_build / "Cargo.toml")],
                cwd=source,
                env=env,
                check=True,
                timeout=300,
            )
        driver_command = [
            "cargo",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(driver_build / "Cargo.toml"),
        ]
        subprocess.run(
            driver_command,
            cwd=source,
            env=env,
            check=True,
        )
        shutil.copy2(
            target / "debug/lsp-integration-driver",
            output / "lsp-integration-driver",
        )
    if args.driver_only:
        for name in reused_files:
            shutil.copy2(base / name, output / name)
            assert (
                hashlib.sha256((output / name).read_bytes()).hexdigest()
                == base_manifest["sha256"][name]
            ), f"reused hash mismatch: {name}"
        subprocess.run(
            ["git", "diff", "--exit-code", "HEAD", "--"], cwd=source, check=True
        )
        assert (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip()
            == args.revision
        )
        assert (
            hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest()
            == base_manifest["cargo_lock_sha256"]
        )
        assert (
            hashlib.sha256((driver_build / "Cargo.lock").read_bytes()).hexdigest()
            == base_manifest["driver_lock_sha256"]
        )
    else:
        for name in ("fnn", "fiber-lsp-sdk-agent"):
            shutil.copy2(target / "debug" / name, output / name)
        # Public, test-only Biscuit fixtures shipped with this exact upstream revision.
        shutil.copy2(
            source / "tests/nodes/biscuit-test-private-key",
            output / "biscuit-private-key",
        )
        environment = (source / "tests/bruno/environments/test.bru").read_text()
        token = next(
            line.split(":", 1)[1].strip()
            for line in environment.splitlines()
            if line.strip().startswith("LSP_OPERATOR_TOKEN:")
        )
        (output / "operator-token").write_text(token + "\n")
    version = subprocess.check_output(
        [str(output / "fnn"), "--version"], text=True
    ).strip()
    assert args.revision[:7] in version and "dirty" not in version, version
    files = [
        "fnn",
        "fiber-lsp-sdk-agent",
        "biscuit-private-key",
        "operator-token",
    ]
    driver_manifest = {}
    if not args.upstream_only:
        files.append("lsp-integration-driver")
        driver_manifest = {
            "chain_source_sha256": hashlib.sha256(
                chain_source.read_bytes()
            ).hexdigest(),
            "driver_source_sha256": hashlib.sha256(
                driver_source.read_bytes()
            ).hexdigest(),
            "driver_lock_sha256": hashlib.sha256(
                (driver_build / "Cargo.lock").read_bytes()
            ).hexdigest(),
        }
    manifest = {
        "revision": args.revision,
        "cargo_lock_sha256": hashlib.sha256(
            (source / "Cargo.lock").read_bytes()
        ).hexdigest(),
        "build_command": driver_command if args.driver_only else command,
        "profile": "dev",
        "fnn_version": version,
        "includes_test_driver": not args.upstream_only,
        **driver_manifest,
        "sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in files
        },
    }
    if args.driver_only:
        manifest["reused_bundle"] = str(base)
        manifest["reused_manifest_sha256"] = hashlib.sha256(
            (base / "build.json").read_bytes()
        ).hexdigest()
        manifest["reused_build_command"] = base_manifest["build_command"]
    (output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Installed {version} and matching SDK agent in {output}")
    if args.upstream_only:
        print("Local integration driver was not rebuilt or included in this manifest.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build one revision's CI bundle; no local cache or runtime directory is deleted."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.lsp_ci import full_sha, sha, write
from scripts.lsp_ci_progress import disk_guard
from scripts.lsp_parallel import wait_child
from scripts.run_lsp_regression import drain_group


def execute(command, directory, log_path, env, guard, timeout=5400):
    """Stream build logs while checking time/disk; own only this child session."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cursor = [0]

    def tick():
        guard()
        with log_path.open("rb") as stream:
            stream.seek(cursor[0])
            chunk = stream.read()
            cursor[0] = stream.tell()
        if chunk:
            sys.stdout.write(chunk.decode(errors="replace"))
            sys.stdout.flush()

    started = time.monotonic()
    record = {"command": list(map(str, command)), "cwd": str(directory)}
    process = None
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            record["pid"] = process.pid
            wait_child(process, timeout, threading.Event(), tick=tick)
        tick()
        if process.returncode:
            raise RuntimeError(f"build command failed: exit {process.returncode}")
    except BaseException as error:
        record["error"] = repr(error)
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        raise
    finally:
        try:
            if process is not None:
                leaked = drain_group(process)
                record["exit_code"] = process.returncode
                if leaked and "error" not in record:
                    raise RuntimeError("build left owned background processes")
        finally:
            record["seconds"] = time.monotonic() - started
            record["log_sha256"] = sha(log_path)
            write(log_path.with_suffix(".json"), record)


def build(source, revision, target, output):
    revision = full_sha(revision)
    source, target, output = [Path(p).resolve() for p in (source, target, output)]
    output.mkdir(parents=True, exist_ok=False)
    if (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        != revision
    ):
        raise ValueError("source does not match resolved Fiber revision")
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=source, text=True
    ).strip():
        raise ValueError("product checkout must be clean")
    # Cold Rust compilation has a separate declared budget; tests keep 2GiB.
    space_check = disk_guard(ROOT, 12, reserve_gib=2)
    due = time.monotonic() + 170 * 60  # Leave 10 minutes for CI evidence upload.

    def guard():
        space_check()
        if time.monotonic() >= due:
            raise TimeoutError("CI build budget exhausted; preserving upload reserve")

    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(target),
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_INCREMENTAL="0",
        CARGO_BUILD_JOBS="2",
    )
    execute(
        [sys.executable, str(ROOT / "download.py")],
        ROOT,
        output / "ckb.log",
        env,
        guard,
        300,
    )
    shutil.copy2(ROOT / "download/0.202.0/ckb-cli", ROOT / "source/ckb-cli")
    base = ROOT / "download/fiber" / f"pr-1623-{revision[:7]}"
    delivery = ROOT / "download/fiber" / f"delivery-{revision[:7]}"
    nolsp = ROOT / "download/fiber" / f"nolsp-{revision[:7]}"
    for path in (base, delivery, nolsp):
        if path.exists():
            raise ValueError(f"refusing stale bundle: {path}")
    execute(
        [
            sys.executable,
            str(ROOT / "scripts/build_lsp_test_binaries.py"),
            "--source",
            str(source),
            "--revision",
            revision,
            "--target-dir",
            str(target),
        ],
        ROOT,
        output / "lsp-build.log",
        env,
        guard,
    )
    execute(
        [
            sys.executable,
            str(ROOT / "scripts/build_lsp_delivery_node.py"),
            "--source",
            str(source),
            "--revision",
            revision,
            "--base-bundle",
            str(base),
            "--output",
            str(delivery),
            "--target-dir",
            str(target),
        ],
        ROOT,
        output / "delivery-build.log",
        env,
        guard,
    )
    execute(
        [
            "cargo",
            "build",
            "--locked",
            "-p",
            "fiber-bin",
            "--no-default-features",
            "--features",
            "fnn/rocksdb,watchtower",
        ],
        source,
        output / "nolsp-build.log",
        env,
        guard,
    )
    nolsp.mkdir()
    shutil.copy2(target / "debug/fnn", nolsp / "fnn")
    version = subprocess.check_output(
        [str(nolsp / "fnn"), "--version"], text=True
    ).strip()
    if revision[:7] not in version or "dirty" in version:
        raise ValueError("no-LSP binary revision mismatch")
    write(
        nolsp / "build.json",
        {
            "revision": revision,
            "features": ["fnn/rocksdb", "watchtower"],
            "sha256": {"fnn": sha(nolsp / "fnn")},
            "fnn_version": version,
        },
    )
    paths = [
        ROOT / "download/0.202.0/ckb",
        ROOT / "download/0.202.0/ckb-cli",
        ROOT / "source/ckb-cli",
        base,
        delivery,
        nolsp,
    ]
    files = [
        p
        for path in paths
        for p in ([path] if path.is_file() else path.rglob("*"))
        if p.is_file()
    ]
    manifest = {str(p.relative_to(ROOT)): sha(p) for p in files}
    write(output / "runtime-manifest.json", {"revision": revision, "files": manifest})
    with tarfile.open(output / "runtime.tar.gz", "w:gz") as archive:
        for p in files:
            guard()
            archive.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
    guard()
    write(
        output / "artifact.json",
        {
            "revision": revision,
            "archive_sha256": sha(output / "runtime.tar.gz"),
            "files": len(files),
        },
    )


def install(archive, manifest_path, revision):
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest["revision"] != full_sha(revision):
        raise ValueError("binary artifact revision differs from selected revision")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) != len(manifest["files"]) or set(
            m.name for m in members
        ) != set(manifest["files"]):
            raise ValueError("archive members differ from build manifest")
        for member in members:
            destination = ROOT / member.name
            if (
                not member.isfile()
                or member.name.startswith("/")
                or ".." in Path(member.name).parts
                or not destination.resolve().is_relative_to(ROOT)
            ):
                raise ValueError("unsafe binary archive entry")
            if destination.exists() or destination.is_symlink():
                raise ValueError(f"refusing to overwrite runtime input: {destination}")
        for member in members:
            destination = ROOT / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as stream, destination.open("xb") as out:
                shutil.copyfileobj(stream, out)
            destination.chmod(member.mode & 0o777)
            if sha(destination) != manifest["files"][member.name]:
                raise ValueError("binary artifact file checksum mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("build")
    for flag in ("source", "target", "output"):
        p.add_argument("--" + flag, type=Path, required=True)
    p.add_argument("--revision", required=True)
    p = commands.add_parser("install")
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--revision", required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.source, args.revision, args.target, args.output)
    else:
        install(args.archive, args.manifest, args.revision)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Explicit one-command manual launcher. --check never starts a VM or builds."""

import argparse
import ast
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
REV = "04c206465b48da85b99aa58e80afe9801a2cb2db"
WORK = ROOT / "download/lsp-refund-vm"
SOURCE = ROOT / "download/fiber/source-pr-1623"
STANDALONE = WORK / "source-04-standalone"
BUNDLE = ROOT / "download/fiber/pr-1623-04c2064"
LIMA = WORK / "tools/lima-2.2.1/bin/limactl"
LOCK = WORK / "manual-batch.lock"
ASSETS = {
    "lima-2.2.1-Darwin-arm64.tar.gz": "9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e",
    "ubuntu-24.04-server-cloudimg-arm64.img": "1d6bffe64b848468ac97f821d369a4846d983de1800ccf6b5ec8853e85cefc55",
    "ckb_v0.202.0_aarch64-unknown-linux-gnu.tar.gz": "2324a81c3c5eef3cba43de6e80efde7f86e3ec2dcb1cfab114074cf99784cbec",
}


def run(*args):
    return subprocess.check_output(
        args,
        cwd=ROOT,
        text=True,
        timeout=60,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).strip()


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def active_batches():
    names = {"lsp_refund_vm.py", "lsp_refund_vm_nightly.sh", "lsp_refund_vm_launch.py"}
    active = []
    for row in run("ps", "-axo", "pid=,command=").splitlines():
        pid, command = row.strip().split(None, 1)
        if int(pid) == os.getpid():
            continue
        try:
            words = shlex.split(command)
        except ValueError:
            continue
        if any(Path(word).name in names for word in words[:4]):
            active.append({"pid": int(pid), "command": command})
    return active


def check():
    assert (
        platform.system() == "Darwin" and platform.machine() == "arm64"
    ), "requires macOS ARM64"
    assert run(str(LIMA), "--version").split()[-1] == "2.2.1", "requires Lima 2.2.1"
    hashes = {}
    for name, expected in ASSETS.items():
        path = WORK / "assets" / name
        assert (
            path.is_file() and sha(path) == expected
        ), f"fixed asset absent or changed: {name}"
        hashes[name] = expected
    trees = []
    for source in (SOURCE, STANDALONE):
        assert run("git", "-C", str(source), "rev-parse", "HEAD") == REV, str(source)
        assert not run(
            "git",
            "-C",
            str(source),
            "status",
            "--porcelain",
            "--untracked-files=normal",
        ), f"unclean source: {source}"
        tracked = run("git", "-C", str(source), "ls-files").splitlines()
        assert len(tracked) == 1196, f"expected 1196 tracked product files: {source}"
        trees.append(run("git", "-C", str(source), "rev-parse", "HEAD^{tree}"))
    assert trees[0] == trees[1]
    git = STANDALONE / ".git"
    assert (
        git.is_dir() and not git.is_symlink()
    ), "missing standalone Git directory; prepare it explicitly"
    assert run("git", "-C", str(STANDALONE), "rev-parse", "--git-common-dir") == ".git"
    assert (
        not (git / "objects/info/alternates").exists()
        and not (git / "commondir").exists()
    )
    run("git", "-C", str(STANDALONE), "fsck", "--full", "--no-reflogs")
    manifest = json.loads((BUNDLE / "build.json").read_text())
    assert manifest["revision"] == REV and manifest["profile"] == "dev"
    driver = BUNDLE / "driver-build"
    for source, copy, key in [
        ("_sdk_driver.rs", "main.rs", "driver_source_sha256"),
        ("_watchtower_chain.rs", "_watchtower_chain.rs", "chain_source_sha256"),
    ]:
        value = sha(ROOT / "test_cases/fiber/devnet/lsp" / source)
        assert (
            value == sha(driver / copy) == manifest[key]
        ), f"driver source differs: {source}"
    assert sha(driver / "Cargo.lock") == manifest["driver_lock_sha256"]
    assert sha(SOURCE / "Cargo.lock") == manifest["cargo_lock_sha256"]
    text = (driver / "Cargo.toml").read_text()
    assert text.count(str(SOURCE) + "/") == 4, "unexpected driver dependency paths"
    dependencies = "\n".join(
        f"{name} = {{ path = {json.dumps(str(SOURCE / path))} }}"
        for name, path in [
            ("fiber-lsp-sdk-agent", "tests/fiber-lsp-sdk-agent"),
            ("fiber-lsp-sdk", "crates/fiber-lsp-sdk"),
            ("fiber-types", "crates/fiber-types"),
            ("fiber-json-types", "crates/fiber-json-types"),
        ]
    )

    def literal(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id == "dependencies":
            return dependencies
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal(node.left) + literal(node.right)
        raise AssertionError(
            "builder Cargo.toml generation changed; review launcher validation"
        )

    calls = [
        node
        for node in ast.walk(
            ast.parse((ROOT / "scripts/build_lsp_test_binaries.py").read_text())
        )
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write_text"
        and "Cargo.toml" in ast.unparse(node.func.value)
    ]
    assert len(calls) == 1 and text == literal(
        calls[0].args[0]
    ), "driver Cargo.toml differs from current builder"
    for relative in (
        "venv/bin/python",
        "source/fiber/dev_config_3.yml.j2",
        "source/fiber/data.2026.0929.tar.gz",
        "scripts/lsp_refund_vm_system.sh",
        "scripts/lsp_refund_vm_build.sh",
        "scripts/lsp_refund_vm.yaml",
    ):
        assert (ROOT / relative).is_file(), f"required input absent: {relative}"
    assert (
        not active_batches()
    ), "another manual batch/launcher is alive; inspect its PID first"
    return dict(
        revision=REV,
        tree=trees[0],
        assets=hashes,
        driver_inputs={p.name: sha(p) for p in driver.iterdir() if p.is_file()},
    )


def pack(target):
    denied = {
        "target",
        "venv",
        ".venv",
        "tmp",
        "report",
        "store",
        "__pycache__",
        ".pytest_cache",
        ".DS_Store",
    }
    paths = [
        "framework",
        "test_cases/fiber/devnet/lsp",
        "test_cases/fiber/devnet/lsp_nightly",
        "test_cases/conftest.py",
        "test_cases/__init__.py",
        "test_cases/fiber/__init__.py",
        "test_cases/fiber/devnet/__init__.py",
        "pytest.ini",
        "requirements.txt",
        "source/template",
        "source/contract",
        "source/fiber/keys",
        "source/fiber/dev.toml",
        "source/fiber/dev_config_3.yml.j2",
        "source/fiber/data.2026.0929.tar.gz",
        "scripts/build_lsp_test_binaries.py",
    ]
    paths += [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "scripts").glob("lsp_refund_vm*"))
        if p.is_file()
    ]
    paths += [
        "download/lsp-refund-vm/assets/ckb_v0.202.0_aarch64-unknown-linux-gnu.tar.gz"
    ]
    paths += [
        str((BUNDLE / "driver-build" / name).relative_to(ROOT))
        for name in ("Cargo.toml", "Cargo.lock", "main.rs", "_watchtower_chain.rs")
    ]

    def filter_member(member):
        if any(
            part in denied for part in Path(member.name).parts
        ) or member.name.endswith(".pyc"):
            return None
        assert (
            not member.issym() and not member.islnk()
        ), f"input symlink requires review: {member.name}"
        return member

    with tarfile.open(target, "w") as archive:
        for name in paths:
            archive.add(ROOT / name, arcname=name, filter=filter_member)
        # Only committed product files plus its independent Git database are copied.
        destination = "download/fiber/source-pr-1623"
        for name in run("git", "-C", str(STANDALONE), "ls-files").splitlines():
            archive.add(
                STANDALONE / name, arcname=destination + "/" + name, recursive=False
            )
        archive.add(
            STANDALONE / ".git", arcname=destination + "/.git", filter=filter_member
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only input validation; no VM, build or launch",
    )
    args = parser.parse_args()
    started = (
        time.monotonic()
    )  # Includes validation and payload packaging in the 60-minute budget.
    handle = None
    if not args.check:
        handle = LOCK.open("a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another manual launch holds the global batch lock")
    evidence = check()
    if args.check:
        print(json.dumps(dict(ok=True, checks=evidence), indent=2))
        return
    run_dir = (
        ROOT
        / "report"
        / (
            "lsp-refund-vm-"
            + datetime.now().strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = run_dir / "inputs.tar"
    pack(payload)
    evidence["payload_sha256"] = sha(payload)
    evidence.update(
        system_started_mono=started, evidence=str(run_dir), payload=str(payload)
    )
    log = (run_dir / "launch.log").open("ab")
    process = subprocess.Popen(
        [
            "nohup",
            "caffeinate",
            "-i",
            "bash",
            str(ROOT / "scripts/lsp_refund_vm_nightly.sh"),
            str(run_dir),
            str(payload),
            evidence["payload_sha256"],
            str(started),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        pass_fds=(handle.fileno(),),
    )
    evidence["pid"] = process.pid
    (run_dir / "launch.json").write_text(json.dumps(evidence, indent=2) + "\n")
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(dict(pid=process.pid, evidence=str(run_dir))) + "\n")
    handle.flush()
    print(
        json.dumps(
            dict(
                pid=process.pid, evidence=str(run_dir), log=str(run_dir / "launch.log")
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Launch blocked: {error}")

#!/usr/bin/env python3
"""Build the reviewed LSP node and real SDK agent from one clean checkout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REVISION = "24b5c38bc098aeb29de5f6af7ac28dc667f218e3"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--upstream-only",
        action="store_true",
        help="Build FNN and the upstream SDK agent without the local integration driver",
    )
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if revision != REVISION:
        parser.error(f"expected Fiber {REVISION}, got {revision}")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=source, check=True)
    env = dict(
        os.environ, CARGO_PROFILE_DEV_DEBUG="0", CARGO_TARGET_DIR=str(source / "target")
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
    subprocess.run(command, cwd=source, env=env, check=True)
    # Check again so a source change during compilation cannot be silently installed.
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=source, check=True)
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == REVISION
    )

    output = ROOT / "download/fiber/pr-1623"
    output.mkdir(parents=True, exist_ok=True)
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
            'ckb-types = "1"\nckb-jsonrpc-types = "1"\n'
            'serde = { version = "1.0", features = ["derive"] }\nserde_json = "1.0"\n'
            'tokio = { version = "1", features = ["io-util", "net", "macros", "rt-multi-thread", "time"] }\n'
            'rocksdb = { package = "ckb-rocksdb", version = "=0.21.1", default-features = false, features = ["lz4"] }\n'
        )
        shutil.copy2(driver_source, driver_build / "main.rs")
        if not (driver_build / "Cargo.lock").exists():
            shutil.copy2(source / "Cargo.lock", driver_build / "Cargo.lock")
        subprocess.run(
            [
                "cargo",
                "build",
                "--offline",
                "--manifest-path",
                str(driver_build / "Cargo.toml"),
            ],
            cwd=source,
            env=env,
            check=True,
        )
        shutil.copy2(
            source / "target/debug/lsp-integration-driver",
            output / "lsp-integration-driver",
        )
    for name in ("fnn", "fiber-lsp-sdk-agent"):
        shutil.copy2(source / "target/debug" / name, output / name)
    # Public, test-only Biscuit fixtures shipped with this exact upstream revision.
    shutil.copy2(
        source / "tests/nodes/biscuit-test-private-key", output / "biscuit-private-key"
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
    assert REVISION[:7] in version and "dirty" not in version, version
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
            "driver_source_sha256": hashlib.sha256(
                driver_source.read_bytes()
            ).hexdigest(),
            "driver_lock_sha256": hashlib.sha256(
                (driver_build / "Cargo.lock").read_bytes()
            ).hexdigest(),
        }
    manifest = {
        "revision": REVISION,
        "cargo_lock_sha256": hashlib.sha256(
            (source / "Cargo.lock").read_bytes()
        ).hexdigest(),
        "build_command": command,
        "profile": "dev",
        "fnn_version": version,
        "includes_test_driver": not args.upstream_only,
        **driver_manifest,
        "sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in files
        },
    }
    (output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Installed {version} and matching SDK agent in {output}")
    if args.upstream_only:
        print("Local integration driver was not rebuilt or included in this manifest.")


if __name__ == "__main__":
    main()

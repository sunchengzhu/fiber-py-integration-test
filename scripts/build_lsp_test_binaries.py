#!/usr/bin/env python3
"""Build the reviewed LSP node and real SDK agent from one clean checkout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REVISION = "04c206465b48da85b99aa58e80afe9801a2cb2db"
ROOT = Path(__file__).resolve().parents[1]


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
    parser.add_argument("--base-bundle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.driver_only:
        if args.upstream_only or not all((args.base_bundle, args.output, args.target_dir)):
            parser.error("--driver-only requires --base-bundle, --output and --target-dir; incompatible with --upstream-only")
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
    env = dict(os.environ, CARGO_PROFILE_DEV_DEBUG="0", CARGO_TARGET_DIR=str(target))
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
    reused_files = ("fnn", "fiber-lsp-sdk-agent", "biscuit-private-key", "operator-token")
    if args.driver_only:
        base = args.base_bundle.resolve()
        base_manifest = json.loads((base / "build.json").read_text())
        assert base_manifest["revision"] == args.revision, "base revision mismatch"
        assert base_manifest["cargo_lock_sha256"] == hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest(), "base source lock mismatch"
        for name in reused_files:
            assert hashlib.sha256((base / name).read_bytes()).hexdigest() == base_manifest["sha256"][name], f"base hash mismatch: {name}"
        assert hashlib.sha256((base / "driver-build/Cargo.lock").read_bytes()).hexdigest() == base_manifest["driver_lock_sha256"], "base driver lock mismatch"
        base_version = subprocess.check_output([str(base / "fnn"), "--version"], text=True).strip()
        assert base_version == base_manifest["fnn_version"] and args.revision[:7] in base_version and "dirty" not in base_version, "base FNN version mismatch"
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

    output = args.output.resolve() if args.driver_only else ROOT / "download/fiber" / f"pr-1623-{args.revision[:7]}"
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
            shutil.copy2(base / "driver-build/Cargo.lock" if args.driver_only else source / "Cargo.lock", driver_build / "Cargo.lock")
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
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == base_manifest["sha256"][name], f"reused hash mismatch: {name}"
        subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=source, check=True)
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() == args.revision
        assert hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest() == base_manifest["cargo_lock_sha256"]
        assert hashlib.sha256((driver_build / "Cargo.lock").read_bytes()).hexdigest() == base_manifest["driver_lock_sha256"]
    else:
        for name in ("fnn", "fiber-lsp-sdk-agent"):
            shutil.copy2(target / "debug" / name, output / name)
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
        manifest["reused_manifest_sha256"] = hashlib.sha256((base / "build.json").read_bytes()).hexdigest()
        manifest["reused_build_command"] = base_manifest["build_command"]
    (output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Installed {version} and matching SDK agent in {output}")
    if args.upstream_only:
        print("Local integration driver was not rebuilt or included in this manifest.")


if __name__ == "__main__":
    main()

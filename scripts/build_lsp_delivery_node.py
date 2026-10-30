#!/usr/bin/env python3
"""Build the reviewed delivery wrapper without editing or replacing product sources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REVISION = "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product_clean(source):
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == REVISION
    )
    assert not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=source, text=True
    ).strip(), "product checkout must remain clean"


def packages(lock):
    return {
        (p["name"], p["version"], p.get("source"), p.get("checksum"))
        for p in tomllib.loads(lock.read_text())["package"]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--base-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    args = parser.parse_args()
    source, base, output, target = (
        p.resolve()
        for p in (args.source, args.base_bundle, args.output, args.target_dir)
    )
    assert not output.exists(), "output must be a new directory"
    assert output.is_relative_to(ROOT), "bundle must remain in this checkout"
    product_clean(source)
    base_manifest = json.loads((base / "build.json").read_text())
    assert base_manifest["revision"] == REVISION
    assert base_manifest["cargo_lock_sha256"] == digest(source / "Cargo.lock")
    assert base_manifest["profile"] == "dev"
    for name, checksum in base_manifest["sha256"].items():
        assert digest(base / name) == checksum, name
    suite = ROOT / "test_cases/fiber/devnet/lsp"
    for key, name in (
        ("driver_source_sha256", "_sdk_driver.rs"),
        ("chain_source_sha256", "_watchtower_chain.rs"),
    ):
        assert digest(suite / name) == base_manifest[key], "base SDK adapter is stale"
    version = subprocess.check_output([base / "fnn", "--version"], text=True).strip()
    assert version == base_manifest["fnn_version"] and "dirty" not in version
    assert REVISION[:7] in version
    upstream_main = source / "crates/fiber-bin/src/main.rs"
    upstream_hash = digest(upstream_main)
    output.mkdir(parents=True)
    build = output / "node-build"
    build.mkdir()

    # Keep the original bin's dependency/features selection; only the test crate
    # root and its control/JSON dependencies are added outside the product tree.
    original_manifest = (source / "crates/fiber-bin/Cargo.toml").read_text()
    dependencies = original_manifest.split("[features]", 1)[1]
    dependencies = dependencies.split("[dev-dependencies]", 1)[0]
    dependencies = dependencies.replace(
        'fnn = { path = "../fiber-lib" }',
        "fnn = { path = " + json.dumps(str(source / "crates/fiber-lib")) + " }",
    )
    dependencies = dependencies.replace(
        "[dependencies]\n",
        '[dependencies]\nserde_json = "1"\n',
        1,
    )
    (build / "Cargo.toml").write_text(
        '[package]\nname = "lsp-delivery-node"\nversion = "0.1.0"\nedition = "2021"\n'
        '[workspace]\n[[bin]]\nname = "lsp-delivery-node"\npath = "_delivery_node.rs"\n'
        "[features]" + dependencies
    )
    adapter_sources = sorted(suite.glob("_delivery*.rs"))
    assert suite / "_delivery_node.rs" in adapter_sources
    adapter_hashes = {p.name: digest(p) for p in adapter_sources}
    for path in adapter_sources:
        shutil.copy2(path, build / path.name)
    shutil.copy2(source / "Cargo.lock", build / "Cargo.lock")
    env = dict(
        os.environ,
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_INCREMENTAL="0",
        CARGO_TARGET_DIR=str(target),
        LSP_UPSTREAM_MAIN=str(upstream_main),
    )
    # The new crate needs a root lock entry. Resolve offline against the seeded
    # product lock, then reject any dependency identity absent from that lock.
    metadata = subprocess.check_output(
        [
            "cargo",
            "metadata",
            "--offline",
            "--format-version=1",
            "--manifest-path",
            str(build / "Cargo.toml"),
            "--features",
            "debug-add-tlc",
        ],
        env=env,
        cwd=source,
    )
    (build / "metadata.json").write_bytes(metadata)
    extra = packages(build / "Cargo.lock") - packages(source / "Cargo.lock")
    assert extra == {("lsp-delivery-node", "0.1.0", None, None)}, (
        "wrapper resolved dependencies outside the fixed product lock",
        extra,
    )
    resolved = json.loads(metadata)
    for name in ("fnn", "ractor"):
        assert len([p for p in resolved["packages"] if p["name"] == name]) == 1, name
    command = [
        "cargo",
        "build",
        "--locked",
        "--offline",
        "--manifest-path",
        str(build / "Cargo.toml"),
        "--features",
        "debug-add-tlc",
    ]
    subprocess.run(command, env=env, cwd=source, check=True)
    product_clean(source)
    assert digest(upstream_main) == upstream_hash
    assert adapter_hashes == {p.name: digest(p) for p in adapter_sources}
    for name, checksum in base_manifest["sha256"].items():
        shutil.copy2(base / name, output / name)
        assert digest(output / name) == checksum
        assert digest(base / name) == checksum
    shutil.copy2(target / "debug/lsp-delivery-node", output / "lsp-delivery-node")
    manifest = {
        **base_manifest,
        "reused_bundle": str(base),
        "reused_manifest_sha256": digest(base / "build.json"),
        "delivery_build_command": command,
        "delivery_source_sha256": adapter_hashes,
        "delivery_lock_sha256": digest(build / "Cargo.lock"),
        "upstream_main_sha256": upstream_hash,
        "delivery_product_source": str(source),
        "delivery_kind": "original-run-node-wrapper-with-in-process-proxy",
        "sha256": {
            **base_manifest["sha256"],
            "lsp-delivery-node": digest(output / "lsp-delivery-node"),
        },
    }
    (output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built fixed {REVISION[:7]} original-entry wrapper: {output}")


if __name__ == "__main__":
    main()

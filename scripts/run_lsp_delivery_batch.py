#!/usr/bin/env python3
"""Run the authorized 843 delivery qualification and six single-shot cases."""

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "download/fiber/source-pr-1623-84333ee"
CARGO_SEED = Path.home() / ".cargo"
REVISION = "84333eea8488a8afc7e4474aa4bbd0e7e973cee9"
TEST_FILE = "test_cases/fiber/devnet/lsp/test_delivery_acceptance.py"
CASES = [
    "TestDeliveryAcceptance::test_accept_after_original_caller_timeout",
    "TestDeliveryAcceptance::test_buffered_reply_lost_after_real_acceptance",
    "TestDeliveryAcceptance::test_same_key_replay_preserves_inflight_execution",
    "TestDeliveryAcceptance::test_same_key_replay_preserves_succeeded_execution",
    "TestDeliveryAcceptance::test_amount_conflict_rejected_before_existing_key_comparison",
    "TestDeliveryTargetConflict::test_valid_other_tenant_target_cannot_replace_original_key",
]
PORTS = (8114, 8125, 8227, 8228, 8229, 8230)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Batch:
    def __init__(self, args):
        self.source = args.source.resolve()
        self.base = args.base_bundle.resolve()
        self.original = args.protected_worktree.resolve()
        self.cache = args.target_cache.resolve()
        self.cargo_seed = args.cargo_seed.resolve()
        self.reuse_wrapper = (
            args.reuse_wrapper.resolve() if args.reuse_wrapper else None
        )
        self.reused_wrapper_hashes = None
        # Keep a virtualenv executable path: resolving its symlink may select
        # the system interpreter without the project's installed dependencies.
        self.python = args.python.absolute()
        self.started = time.monotonic()
        self.until = self.started + 120 * 60
        self.qualification_until = self.started + 60 * 60
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(time.time() + 8 * 3600))
        self.root = ROOT / "report" / f"lsp-delivery-84333ee-{stamp}"
        self.root.mkdir(parents=True, exist_ok=False)
        self.bundle = self.root / "bundle"
        self.target = Path("/private/tmp") / f"lsp-delivery-84333ee-target-{stamp}"
        self.cargo_home = Path("/private/tmp") / f"lsp-delivery-84333ee-cargo-{stamp}"
        self.phases = []
        self.commands = []
        self.active = None
        self.status = "running"
        self.reason = None
        self.base_hashes = None
        self.original_status = None
        self.frozen = None
        self.env = dict(
            os.environ,
            LSP_TEST_REVISION=REVISION,
            LSP_TEST_BUNDLE=str(self.bundle),
            LSP_DELIVERY_NODE=str(self.bundle / "lsp-delivery-node"),
            LSP_DELIVERY_REPORT_DIR=str(self.root / "cases"),
            PYTHONPATH=str(ROOT),
            PYTHONUNBUFFERED="1",
            CKB_CLI_HOME=str(self.root / "ckb-cli-home"),
            CARGO_HOME=str(self.cargo_home),
        )
        (self.root / "cases").mkdir()
        shutil.copy2(__file__, self.root / "runner.py")
        self.save()
        print(self.root, flush=True)

    def save(self):
        (self.root / "run.json").write_text(
            json.dumps(
                {
                    "revision": REVISION,
                    "started_monotonic": self.started,
                    "deadline_monotonic": self.until,
                    "qualification_deadline": self.qualification_until,
                    "status": self.status,
                    "active_phase": self.active,
                    "stop_reason": self.reason,
                    "phases": self.phases,
                    "commands": self.commands,
                    "base_hashes": self.base_hashes,
                    "frozen_sources": self.frozen,
                    "reused_wrapper_hashes": self.reused_wrapper_hashes,
                    "original_status": self.original_status,
                    "bundle": str(self.bundle),
                    "target": str(self.target),
                    "cargo_home": str(self.cargo_home),
                    "inputs": {
                        "source": str(self.source),
                        "base_bundle": str(self.base),
                        "target_cache": str(self.cache),
                        "cargo_seed": str(self.cargo_seed),
                        "protected_worktree": str(self.original),
                        "python": str(self.python),
                        "reuse_wrapper": (
                            str(self.reuse_wrapper) if self.reuse_wrapper else None
                        ),
                    },
                    "planned": [
                        TEST_FILE
                        + "::TestDeliveryQualification::test_normal_control_payment_qualifies_real_path"
                    ]
                    + [TEST_FILE + "::" + node for node in CASES],
                },
                indent=2,
            )
            + "\n"
        )

    def command(self, name, args, until, *, env=None, cleanup=5):
        start = time.monotonic()
        assert start < until - cleanup, f"{name}: insufficient time"
        record = {
            "name": name,
            "command": list(map(str, args)),
            "started": start,
            "deadline": until,
            "cwd": str(ROOT),
        }
        self.commands.append(record)
        self.save()
        process, code, timed_out = None, 125, False
        print("START " + name, flush=True)
        try:
            with (self.root / f"{name}.log").open("w") as log:
                process = subprocess.Popen(
                    list(map(str, args)),
                    cwd=ROOT,
                    env=env or self.env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
                record["pid"] = process.pid
                self.save()
                while process.poll() is None and time.monotonic() < until - cleanup:
                    time.sleep(0.2)
                if process.poll() is None:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGINT)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(
                            timeout=max(0.001, min(3, until - time.monotonic()))
                        )
                    except subprocess.TimeoutExpired:
                        pass
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(
                            timeout=max(0.001, min(2, until - time.monotonic()))
                        )
                    except subprocess.TimeoutExpired:
                        pass
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=max(0.001, until - time.monotonic()))
                code = 124 if timed_out else process.returncode
        except BaseException as error:
            record["exception"] = repr(error)
            raise
        finally:
            if process is not None:
                # The leader may have exited while one of its descendants remains.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                time.sleep(min(0.2, max(0, until - time.monotonic())))
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            record.update(exit=code, ended=time.monotonic())
            (self.root / f"{name}.exit").write_text(str(code) + "\n")
            self.save()
            print(
                f"END {name}: exit={code}, seconds={record['ended']-start:.1f}",
                flush=True,
            )
        assert code == 0, f"{name}: exit {code}"
        return (self.root / f"{name}.log").read_text()

    def phase(self, name, seconds, operation, *, qualification=False, final=False):
        start = time.monotonic()
        bound = self.until if final else self.until - 12 * 60
        if qualification:
            bound = min(bound, self.qualification_until)
        until = min(start + seconds, bound)
        assert until > start, f"{name}: budget exhausted"
        item = {"name": name, "started": start, "deadline": until, "status": "running"}
        self.active = name
        self.phases.append(item)
        self.save()
        try:
            operation(until)
            assert time.monotonic() <= until, f"{name}: over budget"
            item.update(status="passed", ended=time.monotonic())
        except BaseException as error:
            item.update(status="failed", error=repr(error), ended=time.monotonic())
            raise
        finally:
            self.active = None
            self.save()

    def sources(self):
        suite = ROOT / "test_cases/fiber/devnet/lsp"
        paths = [
            suite / "_lsp_test.py",
            suite / "_delivery_node.rs",
            suite / "test_delivery_acceptance.py",
            ROOT / "scripts/build_lsp_delivery_node.py",
            ROOT / "scripts/run_lsp_delivery_batch.py",
            ROOT / "reviews/lsp/delivery-acceptance-consistency.md",
        ]
        return {str(p.relative_to(ROOT)): digest(p) for p in paths}

    def freeze(self):
        assert (
            self.frozen == self.sources()
        ), "reviewed sources changed during execution"

    def preflight(self, until):
        assert (
            self.command(
                "product-head", ["git", "-C", self.source, "rev-parse", "HEAD"], until
            ).strip()
            == REVISION
        )
        assert not self.command(
            "product-status", ["git", "-C", self.source, "status", "--porcelain"], until
        ).strip()
        self.original_status = self.command(
            "original-status",
            ["git", "-C", self.original, "status", "--porcelain=v1"],
            until,
        )
        assert (
            self.python.is_file() and self.cache.is_dir() and not self.target.exists()
        )
        assert not self.cargo_home.exists()
        assert all((self.cargo_seed / name).is_dir() for name in ("registry", "git"))
        assert (self.base / "build.json").is_file() and not self.bundle.exists()
        base_manifest = json.loads((self.base / "build.json").read_text())
        assert base_manifest["revision"] == REVISION
        assert base_manifest["cargo_lock_sha256"] == digest(self.source / "Cargo.lock")
        self.base_hashes = {
            name: digest(self.base / name) for name in base_manifest["sha256"]
        }
        assert self.base_hashes == base_manifest["sha256"]
        assert (
            self.command(
                "base-version", [self.base / "fnn", "--version"], until
            ).strip()
            == base_manifest["fnn_version"]
        )
        for port in PORTS:
            with socket.socket() as sock:
                code = sock.connect_ex(("127.0.0.1", port))
                assert (
                    code == errno.ECONNREFUSED
                ), f"port unavailable or occupied: {port}, errno={code}"
        self.frozen = self.sources()
        for rel in self.frozen:
            destination = self.root / "sources" / (rel + ".snapshot")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, destination)
        (self.root / "sources/FORMAT.txt").write_text(
            "Frozen source bytes; add .snapshot to path in run.json.\n"
        )
        self.save()

    def build(self, until):
        self.freeze()
        if self.reuse_wrapper is not None:
            # Python-only assertion changes do not require recompiling the
            # unchanged wrapper. Reuse only a byte-verified matching build.
            previous = json.loads((self.reuse_wrapper / "build.json").read_text())
            base = json.loads((self.base / "build.json").read_text())
            assert previous["revision"] == REVISION
            assert previous["profile"] == base["profile"] == "dev"
            assert previous["reused_manifest_sha256"] == digest(
                self.base / "build.json"
            )
            assert previous["cargo_lock_sha256"] == digest(self.source / "Cargo.lock")
            assert previous["fnn_version"] == base["fnn_version"]
            assert previous["upstream_main_sha256"] == digest(
                self.source / "crates/fiber-bin/src/main.rs"
            )
            suite = ROOT / "test_cases/fiber/devnet/lsp"
            assert previous["delivery_source_sha256"] == {
                p.name: digest(p) for p in sorted(suite.glob("_delivery*.rs"))
            }
            for field, name in (
                ("driver_source_sha256", "_sdk_driver.rs"),
                ("chain_source_sha256", "_watchtower_chain.rs"),
            ):
                assert previous[field] == base[field] == digest(suite / name)
            assert previous["driver_lock_sha256"] == base["driver_lock_sha256"]
            assert (
                digest(self.base / "driver-build/Cargo.lock")
                == base["driver_lock_sha256"]
            )
            self.base_hashes["driver-build/Cargo.lock"] = base["driver_lock_sha256"]
            assert previous["delivery_lock_sha256"] == digest(
                self.reuse_wrapper / "node-build/Cargo.lock"
            )
            assert set(previous["sha256"]) == set(base["sha256"]) | {
                "lsp-delivery-node"
            }
            for name, checksum in previous["sha256"].items():
                assert digest(self.reuse_wrapper / name) == checksum, name
                if name in base["sha256"]:
                    assert checksum == base["sha256"][name], name
            self.reused_wrapper_hashes = {
                name: digest(self.reuse_wrapper / name)
                for name in ["build.json", "node-build/Cargo.lock", *previous["sha256"]]
            }
            self.command(
                "reuse-verified-wrapper",
                ["cp", "-cR", self.reuse_wrapper, self.bundle],
                until,
            )
            for name, checksum in self.reused_wrapper_hashes.items():
                assert digest(self.bundle / name) == checksum, name
            self.freeze()
            return
        self.command(
            "clone-reviewed-cache", ["cp", "-cR", self.cache, self.target], until
        )
        self.cargo_home.mkdir()
        self.command(
            "clone-cargo-registry",
            ["cp", "-cR", self.cargo_seed / "registry", self.cargo_home / "registry"],
            until,
        )
        self.command(
            "clone-cargo-git",
            ["cp", "-cR", self.cargo_seed / "git", self.cargo_home / "git"],
            until,
        )
        if (self.cargo_seed / "config.toml").is_file():
            shutil.copy2(
                self.cargo_seed / "config.toml", self.cargo_home / "config.toml"
            )
        self.command(
            "build-wrapper",
            [
                self.python,
                "scripts/build_lsp_delivery_node.py",
                "--source",
                self.source,
                "--base-bundle",
                self.base,
                "--output",
                self.bundle,
                "--target-dir",
                self.target,
            ],
            until,
        )
        manifest = json.loads((self.bundle / "build.json").read_text())
        assert manifest["revision"] == REVISION
        for name, checksum in manifest["sha256"].items():
            assert digest(self.bundle / name) == checksum, name
        self.freeze()

    def selfcheck(self, until):
        self.freeze()
        events = self.root / "transport-events.jsonl"
        self.command(
            "transport-selfcheck",
            [self.bundle / "lsp-delivery-node"],
            until,
            env=dict(
                self.env, LSP_DELIVERY_SELF_CHECK="1", LSP_DELIVERY_EVENTS=str(events)
            ),
        )
        rows = [json.loads(line) for line in events.read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["event"] == "transport_selfcheck"
        assert rows[0]["product_passed"] is False
        assert rows[0]["scope"] == "in-memory reply port lifecycle only"
        assert self.base_hashes == {
            name: digest(self.base / name) for name in self.base_hashes
        }

    def pytest_one(self, name, node, until):
        self.freeze()
        xml = self.root / f"{name}.xml"
        self.command(
            name,
            [
                self.python,
                "-m",
                "pytest",
                "-x",
                "-vv",
                "-s",
                "-o",
                "addopts=",
                "--junitxml=" + str(xml),
                TEST_FILE + "::" + node,
            ],
            until,
            cleanup=60,
        )
        cases = ET.parse(xml).findall(".//testcase")
        assert len(cases) == 1, f"{name}: expected one executed test"
        assert all(
            child.tag in ("system-out", "system-err", "properties")
            for child in cases[0]
        ), f"{name}: failure/error/skip in JUnit"
        self.freeze()

    def final(self, until):
        if self.frozen is not None:
            self.freeze()
        if self.base_hashes is not None:
            assert self.base_hashes == {
                name: digest(self.base / name) for name in self.base_hashes
            }
        if self.reused_wrapper_hashes is not None:
            assert self.reused_wrapper_hashes == {
                name: digest(self.reuse_wrapper / name)
                for name in self.reused_wrapper_hashes
            }
        assert not self.command(
            "product-final-status",
            ["git", "-C", self.source, "status", "--porcelain"],
            until,
        ).strip()
        if self.original_status is not None:
            assert self.original_status == self.command(
                "original-final-status",
                ["git", "-C", self.original, "status", "--porcelain=v1"],
                until,
            )
        groups = {row["pid"] for row in self.commands if "pid" in row}
        group_status = {}
        for group in groups:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                group_status[str(group)] = "absent"
            except OSError as error:
                group_status[str(group)] = f"unknown: errno={error.errno}"
            else:
                group_status[str(group)] = "present"
        port_status = {}
        for port in PORTS:
            with socket.socket() as sock:
                port_status[str(port)] = sock.connect_ex(("127.0.0.1", port))
        (self.root / "residual-processes.json").write_text(
            json.dumps(
                {
                    "scope": "batch-owned process groups and listed local TCP ports",
                    "groups": group_status,
                    "port_connect_errno": port_status,
                },
                indent=2,
            )
            + "\n"
        )
        assert all(status == "absent" for status in group_status.values()), group_status
        assert all(
            code == errno.ECONNREFUSED for code in port_status.values()
        ), port_status

    def run(self):
        try:
            self.phase("preflight", 5 * 60, self.preflight, qualification=True)
            self.phase("build", 30 * 60, self.build, qualification=True)
            self.phase("selfcheck", 5 * 60, self.selfcheck, qualification=True)
            self.phase(
                "normal-control",
                20 * 60,
                lambda until: self.pytest_one(
                    "normal-control",
                    "TestDeliveryQualification::test_normal_control_payment_qualifies_real_path",
                    until,
                ),
                qualification=True,
            )
            for number, node in enumerate(CASES, 1):
                self.phase(
                    f"delivery-{number:02d}",
                    8 * 60,
                    lambda until, node=node, number=number: self.pytest_one(
                        f"delivery-{number:02d}", node, until
                    ),
                )
            self.status = "passed"
        except BaseException as error:
            self.status = "stopped"
            self.reason = repr(error)
            (self.root / "stop.txt").write_text(self.reason + "\n")
            print("STOP: " + self.reason, flush=True)
        finally:
            try:
                self.phase("final-evidence", 12 * 60, self.final, final=True)
            except BaseException as error:
                self.status = "stopped"
                self.reason = (self.reason or "") + "; final: " + repr(error)
            self.active = None
            self.save()
            (self.root / "batch.exit").write_text(
                ("0" if self.status == "passed" else "1") + "\n"
            )
            print(f"FINAL {self.status}: {self.root}", flush=True)
        return 0 if self.status == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument(
        "--base-bundle",
        type=Path,
        required=True,
        help="Matching 84333ee bundle including the reviewed SDK driver",
    )
    parser.add_argument(
        "--target-cache",
        type=Path,
        required=True,
        help="Existing Cargo target to clone without changing the original",
    )
    parser.add_argument("--cargo-seed", type=Path, default=CARGO_SEED)
    parser.add_argument("--protected-worktree", type=Path, default=ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument(
        "--reuse-wrapper",
        type=Path,
        help="Reuse an unchanged, hash-verified wrapper bundle for Python-only changes",
    )
    sys.exit(Batch(parser.parse_args()).run())

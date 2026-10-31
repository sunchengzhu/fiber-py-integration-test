#!/usr/bin/env python3
"""Manual isolated Lima experiment; never installed as a scheduled/daily test.

prepare takes three reviewed local inputs: a source/input tar, a system setup
script, and a build script. They run only inside the dedicated guest. The tar
must unpack into /workspace (no Mac target, venv, tmp, report or active stores).
The setup script installs fixed CKB/CLI and disables guest time services. The
build script creates /workspace/venv, the pinned Linux bundle and trusted inputs.
No download fallback, dependency version substitution, or product patch is made
by this controller. prepare and run each write exclusive evidence directories.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid
import xml.etree.ElementTree as ET
import yaml

ROOT = Path(__file__).resolve().parents[1]
REVISION = "04c206465b48da85b99aa58e80afe9801a2cb2db"
HOME = ROOT / "tmp/v"
CONFIG = Path(__file__).with_suffix(".yaml")
HELPER = "/workspace/test_cases/fiber/devnet/lsp_nightly/_vm_time.py"
NETWORK_HELPER = "/workspace/scripts/lsp_refund_vm_network.py"
PREFIX = "lr-"
GIB = 1024**3
SELECTORS = {
    "old-adapter": "test_cases/fiber/devnet/lsp/test_watchtower_settlement.py::TestWatchtowerAdapter::test_adapter_rejects_invalid_authorization",
    "chain-adapter": "test_cases/fiber/devnet/lsp_nightly/test_tlc_timeout_refund.py::TestTlcRefundAdapter::test_single_tlc_adapter",
    "normal": "test_cases/fiber/devnet/lsp/test_watchtower_settlement.py::TestWatchtowerSettlement::test_authorized_settlement",
    "formal": "test_cases/fiber/devnet/lsp_nightly/test_tlc_timeout_refund.py::TestTlcTimeoutRefund::test_hold_payment_timeout_refund",
}
VERIFY_BUNDLE = """import hashlib,json,platform,subprocess
from pathlib import Path
root=Path('/workspace'); bundle=root/'download/fiber/pr-1623-04c2064'
p=bundle/'build.json'; manifest=json.loads(p.read_text())
assert platform.system()=='Linux' and platform.machine()=='aarch64'
assert manifest['revision']==REVISION and manifest['profile']=='dev'
assert 'fiber-bin/debug-add-tlc' in manifest['build_command']
for name,expected in manifest['sha256'].items():
    assert hashlib.sha256((bundle/name).read_bytes()).hexdigest()==expected,name
for name in ('fnn','fiber-lsp-sdk-agent','lsp-integration-driver'):
    assert (bundle/name).read_bytes()[:4]==b'\\x7fELF',name
for key,name in [('driver_source_sha256','_sdk_driver.rs'),('chain_source_sha256','_watchtower_chain.rs')]:
    assert hashlib.sha256((root/'test_cases/fiber/devnet/lsp'/name).read_bytes()).hexdigest()==manifest[key],key
assert subprocess.check_output(['git','-C',str(root/'download/fiber/source-pr-1623'),'rev-parse','HEAD'],text=True).strip()==REVISION
subprocess.run(['git','-C',str(root/'download/fiber/source-pr-1623'),'diff','--quiet','HEAD','--'],check=True)
ckb=subprocess.check_output([str(root/'download/0.202.0/ckb'),'--version'],text=True).strip()
cli=subprocess.check_output([str(root/'source/ckb-cli'),'--version'],text=True).strip()
assert '0.202.0' in ckb and '1.15.0' in cli,(ckb,cli)
files=set((root/'framework').rglob('*.py'))|set((root/'test_cases/fiber/devnet/lsp').glob('*.py'))|set((root/'test_cases/fiber/devnet/lsp').glob('*.rs'))
files|=set((root/'test_cases/fiber/devnet/lsp_nightly').glob('*.py'))
files|={root/'test_cases/fiber/devnet/lsp_nightly'/name for name in ('test_tlc_timeout_refund.py','_vm_time.py','_refund_ledger.py')}
files|={root/x for x in ('requirements.txt','pytest.ini','test_cases/conftest.py','download/0.202.0/ckb','source/ckb-cli')}
files|={root/x for x in ('test_cases/fiber/devnet/lsp/requirements.txt','scripts/build_lsp_test_binaries.py')}
files|={root/x for x in ('download/fiber/source-pr-1623/rust-toolchain.toml','download/fiber/source-pr-1623/Cargo.lock','download/fiber/pr-1623-04c2064/driver-build/Cargo.lock','source/fiber/data.2026.0929.tar.gz')}
files|={f for f in (root/'source/contract').rglob('*') if f.is_file()}
files|={f for f in (root/'source/template').rglob('*') if f.is_file()}
files|={f for f in (root/'source/fiber').glob('*') if f.is_file() and not any(s in f.suffixes for s in ('.tar','.tgz','.gz','.bz2','.xz','.zip'))}
files|={f for f in (root/'source/fiber/keys').rglob('*') if f.is_file()}
files|={f for f in (root/'scripts').glob('lsp_refund_vm*') if f.is_file()}
assert all(f.is_file() for f in files),'missing frozen input'
inputs={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(files)}
assert inputs['download/fiber/source-pr-1623/Cargo.lock']==manifest['cargo_lock_sha256']
assert inputs['download/fiber/pr-1623-04c2064/driver-build/Cargo.lock']==manifest['driver_lock_sha256']
tools=dict(rustc=subprocess.check_output([str(Path.home()/'.cargo/bin/rustc'),'-Vv'],text=True),cargo=subprocess.check_output([str(Path.home()/'.cargo/bin/cargo'),'-V'],text=True),python=subprocess.check_output([str(root/'venv/bin/python'),'--version'],text=True),pip=subprocess.check_output([str(root/'venv/bin/python'),'-m','pip','freeze','--all'],text=True))
assert '1.95.0' in tools['rustc']
print(json.dumps(dict(manifest=manifest,manifest_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),ckb=ckb,cli=cli,inputs=inputs,tools=tools)))
"""


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_junit(archive_path):
    """A zero pytest exit with an empty or skipped selection is not a pass."""
    with tarfile.open(archive_path) as archive:
        entries = [
            m for m in archive.getmembers() if m.name in ("result.xml", "./result.xml")
        ]
        assert (
            len(entries) == 1 and entries[0].isfile()
        ), "missing/duplicate JUnit result"
        assert entries[0].size <= 16 * 1024 * 1024, "oversized JUnit result"
        with archive.extractfile(entries[0]) as stream:
            root = ET.parse(stream).getroot()
    assert (
        len(root.findall(".//testcase")) == 1
    ), "expected exactly one executed testcase"
    for tag in ("failure", "error", "skipped"):
        assert not root.findall(".//" + tag), f"JUnit contains {tag}"
    for suite in root.iter():
        if suite.tag in ("testsuite", "testsuites"):
            for counter in ("failures", "errors", "skipped"):
                assert int(suite.get(counter, "0")) == 0, f"JUnit reports {counter}"
            if "tests" in suite.attrib:
                assert int(suite.get("tests")) == 1, "JUnit test count mismatch"
    return {"testcases": 1, "failures": 0, "errors": 0, "skipped": 0}


class Controller:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        HOME.mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ, LIMA_HOME=str(HOME), CARGO_BUILD_JOBS="2")
        self.lima = str(args.limactl.resolve())
        self.instances = set()
        self.last_host = None
        self.last_guest = {}
        self.boots = set()
        self.active = None
        self.audit = self.output / "host.jsonl"
        self.freeze = None
        self.active_due = None
        self.markers = {}
        self.labels = {}
        self.in_cleanup = False
        self.command_index = 0
        self.qual = {"pure_clock": False, "old_adapter": False, "chain_sdk": False}

    def record(self, **row):
        with self.audit.open("a") as stream:
            stream.write(
                json.dumps({"wall": time.time(), "mono": time.monotonic(), **row})
                + "\n"
            )

    def host(self):
        now = (time.monotonic(), time.time())
        if self.last_host and not self.in_cleanup:
            mono, wall = self.last_host
            assert now[0] - mono <= 5, "host heartbeat gap/suspend"
            assert abs((now[1] - now[0]) - (wall - mono)) < 2, "host wall clock changed"
        self.last_host = now
        free = shutil.disk_usage(HOME).free
        if not self.in_cleanup:
            assert free >= 8 * GIB, "host free disk below 8GiB"
        self.record(kind="host-heartbeat", free_bytes=free)

    def call(self, args, due, timeout=10, capture=True, input=None, label=None):
        self.host()
        remaining = due - time.monotonic()
        assert remaining > 0, "host absolute deadline exceeded"
        self.command_index += 1
        command_id = f"{self.command_index:06d}"
        directory = self.output / "commands"
        directory.mkdir(exist_ok=True)
        stdout_path, stderr_path = directory / (command_id + ".stdout"), directory / (
            command_id + ".stderr"
        )
        started, wall = time.monotonic(), time.time()
        end = min(due, started + timeout)
        label = label or Path(args[0]).name
        metadata = dict(
            command_id=command_id,
            label=label,
            started_mono=started,
            started_wall=wall,
            configured_timeout=timeout,
            effective_timeout=end - started,
            instance=self.active,
            stdout=str(stdout_path.relative_to(self.output)),
            stderr=str(stderr_path.relative_to(self.output)),
        )
        self.record(kind="command-start", **metadata)
        p, timed_out, error_type = None, False, None
        # Arguments, environment and stdin are deliberately absent from metadata.
        with stdout_path.open("wb") as output, stderr_path.open("wb") as errors:
            try:
                p = subprocess.Popen(
                    args,
                    env=self.env,
                    stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    start_new_session=True,
                )
                while True:
                    try:
                        p.communicate(
                            input=input,
                            timeout=min(1, max(0.01, end - time.monotonic())),
                        )
                        break
                    except subprocess.TimeoutExpired:
                        input = None
                        self.host()
                        if time.monotonic() >= end:
                            timed_out = True
                            raise TimeoutError(
                                f"command deadline exceeded: {label} ({command_id})"
                            )
                assert (
                    p.returncode == 0
                ), f"command failed ({p.returncode}): {label} ({command_id})"
            except BaseException as error:
                error_type = type(error).__name__
                if p is not None and p.poll() is None:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if p is not None:
                    p.wait()
                raise
            finally:
                self.record(
                    kind="command-end",
                    **metadata,
                    ended_mono=time.monotonic(),
                    ended_wall=time.time(),
                    exit_code=None if p is None else p.returncode,
                    timed_out=timed_out,
                    error_type=error_type,
                )
        return stdout_path.read_bytes().decode() if capture else ""

    def lc(self, *args, due, timeout=10, label=None):
        return self.call(
            [self.lima, "--tty=false", *args],
            due,
            timeout,
            label=label or "lima." + (args[0] if args else "command"),
        )

    def shell(self, name, command, due, timeout=2, label=None):
        assert name in self.instances, "instance not created by this controller"
        return self.lc(
            "shell",
            name,
            "--",
            "bash",
            "-lc",
            command,
            due=due,
            timeout=timeout,
            label=label or "guest.shell",
        )

    def version(self):
        assert (
            platform.system() == "Darwin" and platform.machine() == "arm64"
        ), "requires macOS ARM64 host"
        text = self.call(
            [self.lima, "--version"], time.monotonic() + 5, label="lima.version"
        )
        assert text.strip().split()[-1] == "2.2.1", f"wrong Lima version: {text}"
        self.record(
            kind="inputs",
            revision=REVISION,
            config_sha256=digest(CONFIG),
            lima_sha256=digest(self.lima),
            lima_version=text.strip(),
        )

    def state(self, name, due):
        data = self.lc("list", name, "--json", due=due)
        row = json.loads(data)
        if isinstance(row, list):
            assert len(row) == 1
            row = row[0]
        return row

    def guest(self, name, due, marked=True):
        if marked:
            code = (
                "import json,shutil,subprocess;d=json.loads(subprocess.check_output(['sudo','-n','python3',"
                + repr(HELPER)
                + ",'status']));d['free_bytes']=shutil.disk_usage('/').free;print(json.dumps(d))"
            )
        else:
            code = "import json,time,shutil;from pathlib import Path;print(json.dumps(dict(wall=time.time(),mono=time.monotonic(),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),free_bytes=shutil.disk_usage('/').free)))"
        command = "python3 -c " + shlex.quote(code)
        row = json.loads(
            self.shell(
                name,
                command,
                due,
                label="guest.clock-status" if marked else "guest.bootstrap-status",
            )
        )
        free = row["free_bytes"]
        assert free >= 4 * GIB, "guest free disk below 4GiB"
        old = self.last_guest.get(name)
        if old:
            assert row["boot_id"] == old["boot_id"], "guest reboot"
            assert row["mono"] >= old["mono"], "guest monotonic moved backwards"
            if marked and old.get("instance"):
                assert row["mono"] - old["mono"] <= 5, "guest heartbeat gap"
            change = (row["wall"] - row["mono"]) - (old["wall"] - old["mono"])
            event = row.get("event")
            if marked and event:
                assert self.labels[name] not in (
                    "old-adapter",
                    "normal",
                ), "clock event in no-jump regression"
                identity = self.markers[name]
                assert all(
                    event[k] == identity[k] for k in ("instance", "run_id", "boot_id")
                ), "event identity mismatch"
                if event["state"] == "completed":
                    assert (
                        abs(
                            row["wall"]
                            - row["mono"]
                            - (event["after_wall"] - event["after_mono"])
                        )
                        < 2
                    ), "guest drift after registered event"
                elif event["state"] == "consumed":
                    assert (
                        0 <= row["mono"] - event["before_mono"] <= 2
                    ), "guest jump remained incomplete"
                else:
                    raise AssertionError("unknown jump state")
            if abs(change) >= 2:
                assert marked and event, "unregistered/unknown guest clock change"
                assert (
                    not old.get("event") or old["event"]["state"] != "completed"
                ), "second clock change"
                assert (
                    abs(
                        old["wall"]
                        - old["mono"]
                        - (event["before_wall"] - event["before_mono"])
                    )
                    < 2
                ), "event does not bound original guest offset"
                if event["state"] == "consumed":
                    assert (
                        event["target"] - 2 <= row["wall"] <= event["target"] + 4
                    ), "clock outside registered syscall window"
        self.last_guest[name] = row
        self.record(kind="guest-heartbeat", instance=name, free_bytes=free, guest=row)
        return row

    def new(self, label, due, base=None):
        name = PREFIX + label.split("-")[0] + "-" + uuid.uuid4().hex[:8]
        assert (
            len(os.fsencode(str(HOME / name / "ssh.sock.1234567890123456"))) < 104
        ), "Lima UNIX socket path too long"
        assert not (HOME / name).exists()
        self.instances.add(name)
        self.active = name
        if base:
            self.lc(
                "clone", base, name, due=due, timeout=min(60, due - time.monotonic())
            )
            self.lc("start", name, due=due, timeout=min(60, due - time.monotonic()))
        else:
            self.lc(
                "start",
                "--name=" + name,
                str(CONFIG),
                due=due,
                timeout=min(3600, due - time.monotonic()),
            )
        runtime = yaml.safe_load((HOME / name / "lima.yaml").read_text())
        assert all(
            runtime.get(k) == v
            for k, v in {
                "vmType": "vz",
                "arch": "aarch64",
                "os": "Linux",
                "plain": True,
                "cpus": 4,
                "memory": "8GiB",
                "disk": "32GiB",
            }.items()
        ), "runtime VM configuration differs"
        assert not runtime.get("mounts") and not runtime.get(
            "networks"
        ), "unexpected mounts or additional networks"
        assert not runtime.get("rosetta", {}).get("enabled") and not runtime.get(
            "ssh", {}
        ).get("forwardAgent"), "unexpected host integration"
        assert not runtime.get("containerd", {}).get("system") and not runtime.get(
            "containerd", {}
        ).get("user"), "unexpected containerd"
        self.record(
            kind="runtime-config",
            instance=name,
            sha256=digest(HOME / name / "lima.yaml"),
            config=runtime,
        )
        row = self.guest(name, due, marked=False)
        assert row["boot_id"] not in self.boots, "reused boot identity"
        self.boots.add(row["boot_id"])
        self.record(
            kind="instance",
            instance=name,
            boot=row["boot_id"],
            lima=self.state(name, due),
        )
        return name

    def export(self, name, directory, due, final=False):
        # Only known evidence files are copied; guest paths never overwrite source.
        directory.mkdir(exist_ok=True, parents=True)
        target = directory / "guest-evidence.tar"
        temp = target.with_suffix(".tmp")
        # Snapshot each regular file at its current length. tarfile copies that
        # length even while a log grows; future snapshots carry the appended tail.
        exporter = "import os,sys,tarfile;os.chdir('/workspace/vm-evidence');t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|');[t.add(p,recursive=False) for d,ds,fs in os.walk('.') for p in [os.path.join(d,n) for n in fs] if not os.path.islink(p)];t.close()"
        with temp.open("wb") as stream, (directory / "export.log").open("ab") as errors:
            p = subprocess.Popen(
                [
                    self.lima,
                    "--tty=false",
                    "shell",
                    name,
                    "--",
                    "python3",
                    "-c",
                    exporter,
                ],
                env=self.env,
                stdout=stream,
                stderr=errors,
                start_new_session=True,
            )
            try:
                end = min(due, time.monotonic() + (15 if final else 2))
                while p.poll() is None:
                    self.host()
                    assert time.monotonic() < end, "evidence export deadline"
                    time.sleep(0.1)
                assert p.returncode == 0, "evidence export failed"
            except BaseException:
                if p.poll() is None:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                p.wait()
                raise
        with tarfile.open(temp) as archive:
            assert all(
                not Path(m.name).is_absolute()
                and ".." not in Path(m.name).parts
                and not m.issym()
                and not m.islnk()
                for m in archive
            ), "unsafe evidence archive"
        temp.replace(target)
        if final:
            self.record(kind="export-complete", instance=name, sha256=digest(target))

    def stop(self, name, due):
        self.in_cleanup = True
        try:
            self.lc("stop", name, due=due, timeout=min(30, due - time.monotonic()))
            assert self.state(name, due)["status"] == "Stopped", "guest not stopped"
            self.active = None
        finally:
            self.in_cleanup = False

    def emergency_stop(self):
        # Containment only after a failed budget/health check. Never resumes
        # business, issues a jump, claims success, or deletes the failed disk.
        if not self.active:
            return
        assert self.active in self.instances
        self.in_cleanup = True
        name = self.active
        try:
            due = time.monotonic() + 15
            try:
                self.record(
                    kind="emergency-containment",
                    instance=name,
                    reason="failed run; outside expired business budget",
                )
            except OSError:
                pass
            # Disk/log failure must not prevent the containment command itself.
            subprocess.run(
                [self.lima, "--tty=false", "stop", "--force", name],
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=True,
            )
            state = subprocess.check_output(
                [self.lima, "--tty=false", "list", name, "--json"],
                env=self.env,
                timeout=max(0.1, due - time.monotonic()),
                text=True,
            )
            row = json.loads(state)
            assert (row[0] if isinstance(row, list) else row)[
                "status"
            ] == "Stopped", "emergency stop not confirmed"
            self.active = None
        finally:
            self.in_cleanup = False

    def execute(self, name, command, due, directory, marked=False):
        directory.mkdir(exist_ok=True, parents=True)
        with (directory / "guest.log").open("wb") as log:
            p = subprocess.Popen(
                [self.lima, "--tty=false", "shell", name, "--", "bash", "-lc", command],
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            last_export = time.monotonic()
            try:
                while p.poll() is None:
                    self.host()
                    assert time.monotonic() < due, "stage deadline exceeded"
                    self.guest(name, due, marked=marked)
                    if marked and time.monotonic() - last_export >= 5:
                        self.export(name, directory, due)
                        last_export = time.monotonic()
                    time.sleep(0.25)
                assert p.returncode == 0, f"guest command failed: exit {p.returncode}"
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                (directory / "guest.exit").write_text(str(p.returncode) + "\n")

    def prepare(self):
        started = self.args.system_started_mono or time.monotonic()
        assert (
            0 <= time.monotonic() - started < 3600
        ), "system preparation budget already exhausted"
        system_due = started + 3600
        self.active_due = system_due
        name = self.new("base", system_due - 60)
        for path, expected in [
            (self.args.payload, self.args.payload_sha256),
            (self.args.system_script, None),
            (self.args.build_script, None),
        ]:
            assert path.is_file()
            if expected:
                assert digest(path) == expected, "payload hash mismatch"
            self.record(kind="prepare-input", path=str(path), sha256=digest(path))
            self.lc(
                "copy",
                str(path.resolve()),
                name + ":/tmp/" + path.name,
                due=system_due - 60,
                timeout=120,
            )
        self.shell(
            name,
            "sudo mkdir -p /workspace && sudo chown $(id -u):$(id -g) /workspace",
            system_due - 60,
        )
        with tarfile.open(self.args.payload) as archive:
            assert all(
                not Path(m.name).is_absolute() and ".." not in Path(m.name).parts
                for m in archive
            ), "unsafe payload paths"
        command = f"tar -xf {shlex.quote('/tmp/'+self.args.payload.name)} -C /workspace && bash {shlex.quote('/tmp/'+self.args.system_script.name)}"
        self.execute(name, command, system_due - 60, self.output / "system")
        build_started = (
            self.args.build_started_mono
            if self.args.build_started_mono is not None
            else time.monotonic()
        )
        assert (
            0 <= time.monotonic() - build_started < 7200
        ), "build preparation budget already exhausted"
        build_due = build_started + 7200
        self.record(
            kind="build-budget", started_mono=build_started, deadline_mono=build_due
        )
        self.active_due = build_due
        self.execute(
            name,
            f"cd /workspace && CARGO_BUILD_JOBS=2 bash {shlex.quote('/tmp/'+self.args.build_script.name)}",
            build_due - 60,
            self.output / "build",
        )
        clean = self.shell(
            name,
            'cd /workspace && test ! -e /run/lsp-refund-vm.json && test ! -e /run/lsp-refund-vm-jump.json && test -z "$(find tmp -mindepth 1 -print -quit 2>/dev/null)" && git -C download/fiber/source-pr-1623 diff --exit-code HEAD -- && git -C download/fiber/source-pr-1623 rev-parse HEAD',
            build_due,
        )
        assert clean.strip() == REVISION, "base product revision/clean-state mismatch"
        freeze = self.verify_bundle(name, build_due - 30)
        assert freeze["manifest"]["revision"] == REVISION
        freeze.update(base=name, config_sha256=digest(CONFIG), revision=REVISION)
        freeze["freeze_id"] = hashlib.sha256(
            json.dumps(freeze, sort_keys=True).encode()
        ).hexdigest()
        self.stop(name, build_due)
        (self.output / "base.json").write_text(json.dumps(freeze, indent=2) + "\n")

    def verify_bundle(self, name, due):
        code = "REVISION=" + repr(REVISION) + "\n" + VERIFY_BUNDLE
        return json.loads(
            self.shell(
                name,
                "python3 -c " + shlex.quote(code),
                due,
                timeout=10,
                label="guest.verify-frozen-bundle",
            )
        )

    def marker(self, name, label, due):
        mode = (
            "clock"
            if label == "clock"
            else "preflight" if label == "chain-adapter" else "formal"
        )
        # The no-TLC regressions do not consume VM clock qualification.
        if label in ("old-adapter", "normal"):
            mode = "clock"
        row = self.guest(name, due, marked=False)
        marker = dict(
            instance=name,
            run_id=uuid.uuid4().hex,
            boot_id=row["boot_id"],
            revision=REVISION,
            mode=mode,
            guest_started_mono=row["mono"] - (time.monotonic() - self.stage_started),
            guest_deadline_mono=row["mono"] + max(0, due - time.monotonic()),
            qualified=self.qual,
            freeze_id=self.freeze["freeze_id"],
        )
        code = (
            "import json,os;from pathlib import Path;p=Path('/run/lsp-refund-vm.json');assert not p.exists();assert not Path('/run/lsp-refund-vm-jump.json').exists();assert not Path('/run/lsp-refund-vm-jump.json.lock').exists();p.write_text("
            + repr(json.dumps(marker))
            + ");os.chmod(p,0o644)"
        )
        self.shell(
            name,
            "sudo -n python3 -c "
            + shlex.quote(code)
            + " && mkdir -p /workspace/vm-evidence",
            due,
            label="guest.write-run-marker",
        )
        self.record(kind="marker", marker=marker)
        self.markers[name] = marker
        self.labels[name] = label
        return marker

    def isolate(self, name, due):
        command = "sudo -n sh -c 'for s in systemd-timesyncd chrony chronyd ntp ntpd; do systemctl disable --now $s 2>/dev/null || true; done'"
        self.shell(name, command, due, timeout=5, label="isolate.time-services.disable")
        check = 'set -e; test "$(timedatectl show -p NTP --value)" = no; for s in systemd-timesyncd chrony chronyd ntp ntpd; do ! systemctl is-active --quiet $s || exit 1; done'
        # timedatectl uses 'no' on current systemd; fail closed on an unknown API.
        self.shell(name, check, due, timeout=5, label="isolate.time-services.check")
        processes = "import subprocess;from pathlib import Path;forbidden={'chronyd','ntpd','systemd-timesyn','vmtoolsd','qemu-ga'};running={Path(p).name for p in subprocess.check_output(['ps','-eo','comm='],text=True).splitlines()};assert not running&forbidden,running&forbidden"
        self.shell(
            name,
            "python3 -c " + shlex.quote(processes),
            due,
            label="isolate.time-processes.check",
        )
        self.record(
            kind="guest-time-services",
            instance=name,
            services=self.shell(
                name,
                "systemctl list-unit-files --no-pager | grep -E 'time|ntp|chron|cloud|guest|vmtool' || true",
                due,
                label="isolate.time-services.inventory",
            ),
        )
        boot_id = self.last_guest[name]["boot_id"]
        for phase in ("bootstrap", "seal", "verify"):
            command = (
                f"sudo -n python3 {NETWORK_HELPER} {phase} --instance {shlex.quote(name)} "
                f'--boot-id {shlex.quote(boot_id)} --ssh-connection "$SSH_CONNECTION"'
            )
            result = json.loads(
                self.shell(
                    name, command, due, timeout=5, label="isolate.network." + phase
                )
            )
            self.record(kind="guest-network", instance=name, phase=phase, result=result)
        self.record(
            kind="guest-isolation",
            instance=name,
            rules=self.shell(
                name,
                "sudo -n iptables-save && sudo -n ip6tables-save && timedatectl show",
                due,
                label="isolate.final-independent-readback",
            ),
        )

    def run(self):
        self.freeze = json.loads(self.args.base_manifest.read_text())
        body = {k: v for k, v in self.freeze.items() if k != "freeze_id"}
        assert (
            hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            == self.freeze["freeze_id"]
        ), "invalid base freeze manifest"
        assert self.freeze["revision"] == REVISION and self.freeze[
            "config_sha256"
        ] == digest(CONFIG)
        base = self.freeze["base"]
        assert (
            base.startswith(PREFIX) and (HOME / base).is_dir()
        ), "base outside dedicated LIMA_HOME"
        assert self.state(base, time.monotonic() + 5)["status"] == "Stopped"
        lock = HOME / (base + ".batch-consumed.json")
        with lock.open("x") as stream:
            json.dump(
                {
                    "freeze_id": self.freeze["freeze_id"],
                    "output": str(self.output),
                    "wall": time.time(),
                },
                stream,
            )
        self.record(kind="batch-consumed", lock=str(lock))
        plan = [
            ("clock", 540),
            ("old-adapter", 1260),
            ("chain-adapter", 2160),
            ("normal", 1260),
        ] + [("formal", 2160)] * 4
        for index, (label, cap) in enumerate(plan):
            started = time.monotonic()
            self.stage_started = started
            due = started + cap
            self.active_due = due
            directory = self.output / f"{index}-{label}"
            cleanup = 30 if label == "clock" else 60
            try:
                prep_due = min(
                    due - cleanup, started + (60 if label == "clock" else 300)
                )
                name = self.new(f"{index}-{label}", prep_due, base=base)
                verified = self.verify_bundle(name, prep_due)
                assert all(
                    verified[k] == self.freeze[k]
                    for k in ("manifest_sha256", "inputs", "tools")
                ), "base bundle/test inputs/toolchain changed"
                self.isolate(name, prep_due)
                marker = self.marker(name, label, due - cleanup)
                assert (
                    time.monotonic() < prep_due
                ), "instance preparation deadline exceeded"
                env = dict(
                    LSP_REFUND_VM_MODE=marker["mode"],
                    LSP_REFUND_VM_INSTANCE=name,
                    LSP_REFUND_VM_RUN_ID=marker["run_id"],
                    LSP_RUN_ARTIFACTS="/workspace/vm-evidence",
                    PYTHONUNBUFFERED="1",
                    PYTHONPATH="/workspace",
                )
                env.update(
                    {
                        key: ""
                        for key in (
                            "http_proxy",
                            "https_proxy",
                            "all_proxy",
                            "HTTP_PROXY",
                            "HTTPS_PROXY",
                            "ALL_PROXY",
                        )
                    }
                )
                env.update(
                    NO_PROXY="localhost,127.0.0.1,::1",
                    no_proxy="localhost,127.0.0.1,::1",
                )
                if label in ("old-adapter", "normal"):
                    env.pop("LSP_REFUND_VM_MODE")
                assignments = " ".join(k + "=" + shlex.quote(v) for k, v in env.items())
                if label == "clock":
                    command = f"cd /workspace && env {assignments} venv/bin/python {HELPER} pure-clock"
                else:
                    nightly = (
                        " --run-lsp-refund-nightly"
                        if label in ("chain-adapter", "formal")
                        else ""
                    )
                    command = f"cd /workspace && env {assignments} venv/bin/python -m pytest{nightly} -o addopts= -vv -s -x --tb=short --junitxml=/workspace/vm-evidence/result.xml {SELECTORS[label]}"
                self.execute(name, command, due - cleanup, directory, marked=True)
                self.export(name, directory, due, final=True)
                if label != "clock":
                    self.record(
                        kind="junit-verified",
                        stage=label,
                        result=validate_junit(directory / "guest-evidence.tar"),
                    )
                self.stop(name, due)
                if label == "clock":
                    self.qual["pure_clock"] = True
                if label == "old-adapter":
                    self.qual["old_adapter"] = True
                if label == "chain-adapter":
                    self.qual["chain_sdk"] = True
                self.record(
                    kind="stage-complete",
                    stage=label,
                    instance=name,
                    elapsed=time.monotonic() - started,
                    qualified=dict(self.qual),
                )
            except BaseException:
                # Preserve every disk, including successful ones. No implicit pruning.
                name = self.active
                self.record(kind="stage-failed", stage=label, instance=name)
                if time.monotonic() < due:
                    try:
                        self.export(
                            name,
                            directory,
                            min(due - 30, time.monotonic() + 15),
                            final=True,
                        )
                    except Exception as error:
                        self.record(kind="export-failed", error=str(error))
                    try:
                        self.stop(name, due)
                    except Exception as error:
                        self.record(kind="stop-failed", error=str(error))
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limactl", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--payload", required=True, type=Path)
    prepare.add_argument("--payload-sha256", required=True)
    prepare.add_argument("--system-script", required=True, type=Path)
    prepare.add_argument("--build-script", required=True, type=Path)
    prepare.add_argument(
        "--system-started-mono",
        type=float,
        help="Host monotonic before asset downloads; cannot extend the 60-minute system budget",
    )
    prepare.add_argument(
        "--build-started-mono",
        type=float,
        help="Original host monotonic build start; reuse after an environment preparation failure without extending 120 minutes",
    )
    run = sub.add_parser("run")
    run.add_argument("--base-manifest", required=True, type=Path)
    args = parser.parse_args()
    control = Controller(args)
    try:
        control.version()
        getattr(control, args.operation)()
    except BaseException as error:
        try:
            control.record(
                kind="failure", error=str(error), active_instance=control.active
            )
        except OSError:
            pass
        if (
            control.active
            and control.active_due
            and time.monotonic() < control.active_due
        ):
            try:
                control.stop(control.active, control.active_due)
            except Exception as stop_error:
                try:
                    control.record(kind="stop-failed", error=str(stop_error))
                except OSError:
                    pass
        if control.active:
            try:
                control.emergency_stop()
            except Exception as stop_error:
                try:
                    control.record(kind="emergency-stop-failed", error=str(stop_error))
                except OSError:
                    pass
        print(
            f"Stopped: {error}. Evidence: {control.output}; VM disks preserved under {HOME}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

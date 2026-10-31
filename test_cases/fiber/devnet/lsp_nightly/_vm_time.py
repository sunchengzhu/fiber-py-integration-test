"""Explicit guest-only clock control for the manual refund experiment."""

import concurrent.futures
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import threading
import time

MARKER = Path("/run/lsp-refund-vm.json")
EVENT = Path("/run/lsp-refund-vm-jump.json")
REVISION = "04c206465b48da85b99aa58e80afe9801a2cb2db"


def identity(qualify=True):
    assert platform.system() == "Linux", "VM clock control requires Linux guest"
    info = MARKER.lstat()
    assert (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o644
    )
    data = json.loads(MARKER.read_text())
    assert (
        data["boot_id"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    )
    assert data["revision"] == REVISION and data["freeze_id"]
    assert data["mode"] in ("clock", "preflight", "formal")
    assert time.monotonic() < data["guest_deadline_mono"]
    if qualify and data["mode"] != "clock":
        assert data["qualified"]["pure_clock"] and data["qualified"]["old_adapter"]
        if data["mode"] == "formal":
            assert data["qualified"]["chain_sdk"]
    return data


def status():
    data = identity(False)
    return dict(
        wall=time.time(),
        mono=time.monotonic(),
        boot_id=data["boot_id"],
        instance=data["instance"],
        run_id=data["run_id"],
        event=json.loads(EVENT.read_text()) if EVENT.exists() else None,
    )


def privileged_jump(expiry_ms, instance, run_id, boot_id, payment_hash):
    assert os.geteuid() == 0, "guest root required"
    data = identity()
    assert (data["instance"], data["run_id"], data["boot_id"]) == (
        instance,
        run_id,
        boot_id,
    )
    if data["mode"] != "clock":
        assert (
            payment_hash.startswith("0x") and len(bytes.fromhex(payment_hash[2:])) == 32
        )
    else:
        assert payment_hash == "clock-preflight"
    target = expiry_ms / 1000 + 5
    before_wall, before_mono = time.time(), time.monotonic()
    assert target > before_wall and target - before_wall <= 15000
    # Consuming the allowance happens before the syscall; unknown outcomes are never retried.
    fd = os.open(
        str(EVENT) + ".lock",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    os.close(fd)
    event = dict(
        instance=instance,
        run_id=run_id,
        boot_id=boot_id,
        expiry_ms=expiry_ms,
        payment_hash=payment_hash,
        target=target,
        before_wall=before_wall,
        before_mono=before_mono,
        state="consumed",
    )

    def save():
        temporary = Path(str(EVENT) + ".tmp")
        with temporary.open("w") as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(event, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, EVENT)

    save()
    time.clock_settime(time.CLOCK_REALTIME, target)
    event.update(after_wall=time.time(), after_mono=time.monotonic(), state="completed")
    elapsed = event["after_mono"] - before_mono
    assert 0 <= elapsed <= 2
    assert target <= event["after_wall"] <= target + elapsed + 2
    save()
    return event


class GuestClock:
    def __init__(self, artifacts, qualify=True):
        self.identity = identity(qualify)
        for key, env in [
            ("mode", "LSP_REFUND_VM_MODE"),
            ("instance", "LSP_REFUND_VM_INSTANCE"),
            ("run_id", "LSP_REFUND_VM_RUN_ID"),
        ]:
            assert self.identity[key] == os.environ.get(env), (
                key,
                "VM identity mismatch",
            )
        assert not EVENT.exists(), "instance already used a clock event"
        self.path = Path(artifacts) / "vm-clock.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.offset = time.time() - time.monotonic()
        self.error = None
        self.event = None
        self.intent = False
        self.stopped = threading.Event()
        self.lock = threading.RLock()
        self.previous = time.monotonic()
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def _read_event(self):
        info = EVENT.lstat()
        assert (
            info.st_uid == 0
            and stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o644
        )
        event = json.loads(EVENT.read_text())
        for key in ("instance", "run_id", "boot_id"):
            assert event[key] == self.identity[key]
        assert self.intent and event["expiry_ms"] == self.expected_expiry
        assert event["payment_hash"] == self.expected_hash
        return event

    def check(self):
        with self.lock:
            return self._check()

    def _check(self):
        if self.error:
            raise AssertionError("guest clock monitor failed: " + self.error)
        data = identity(False)
        assert data == self.identity, "guest marker changed"
        read_start = time.monotonic()
        wall, mono = time.time(), time.monotonic()
        assert mono - self.previous <= 5, "guest clock heartbeat gap"
        offset = self.offset
        event = None
        if EVENT.exists():
            event = self._read_event()
            if event["state"] == "completed":
                offset = event["after_wall"] - event["after_mono"]
                assert 0 <= event["after_mono"] - event["before_mono"] <= 2
                self.event = event
                if read_start <= event["after_mono"] and mono >= event["before_mono"]:
                    assert mono - read_start <= 2
                    assert self.offset - 2 <= wall - mono <= offset + 2
                    offset = wall - mono
            else:
                # Only the tightly bounded syscall interval may have an intermediate offset.
                assert mono - event["before_mono"] <= 2
                assert (
                    self.offset - 2
                    <= wall - mono
                    <= event["target"] - event["before_mono"] + 2
                )
                offset = wall - mono
        assert abs(wall - mono - offset) < 2, "unexpected guest wall clock change"
        with self.lock:
            self.previous = mono
            with self.path.open("a") as stream:
                stream.write(
                    json.dumps(
                        dict(
                            wall=wall,
                            mono=mono,
                            offset=wall - mono,
                            event=event,
                            boot_id=data["boot_id"],
                            run_id=data["run_id"],
                        )
                    )
                    + "\n"
                )
        return dict(wall=wall, mono=mono, offset=offset)

    def _monitor(self):
        try:
            while not self.stopped.wait(1):
                self.check()
        except BaseException as error:
            self.error = repr(error)

    def jump(self, expiry_ms, observe=None, payment_hash="clock-preflight"):
        assert not self.intent and not EVENT.exists()
        self.check()
        self.expected_expiry, self.intent = int(expiry_ms), True
        self.expected_hash = payment_hash
        command = [
            "sudo",
            "-n",
            sys.executable,
            str(Path(__file__).resolve()),
            "jump",
            str(int(expiry_ms)),
            self.identity["instance"],
            self.identity["run_id"],
            self.identity["boot_id"],
            payment_hash,
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                subprocess.run,
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=25,
            )
            start = time.monotonic()
            while not future.done():
                self.check()
                if observe is not None:
                    observe()
                assert time.monotonic() - start <= 30
                time.sleep(0.1)
            future.result()
        self.check()
        assert self.event is not None
        return self.event

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
        self.check()


def pure_clock():
    started = time.monotonic()
    clock = GuestClock(os.environ["LSP_RUN_ARTIFACTS"], qualify=False)
    assert clock.identity["mode"] == "clock"
    try:
        due = time.monotonic() + 60
        while time.monotonic() < due:
            clock.check()
            time.sleep(1)
        waits = []

        def relative(seconds):
            begin = time.monotonic()
            time.sleep(seconds)
            end = time.monotonic()
            assert seconds <= end - begin <= seconds + 2
            waits.append(dict(seconds=seconds, begin=begin, end=end))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(relative, seconds) for seconds in (10, 60)]
            time.sleep(0.1)
            event = clock.jump(int((time.time() + 14700 - 5) * 1000))
            end = event["after_mono"] + 360
            while time.monotonic() < end:
                clock.check()
                time.sleep(1)
            for future in futures:
                future.result()
        assert len(waits) == 2 and all(
            w["begin"] < event["before_mono"] <= event["after_mono"] < w["end"]
            for w in waits
        )
        assert (
            time.monotonic() - started <= 450
        )  # host separately includes startup/export in 540s
        print(json.dumps(dict(passed=True, event=event, waits=waits)))
    finally:
        clock.close()


if __name__ == "__main__":
    if sys.argv[1] == "status":
        print(json.dumps(status()))
    elif sys.argv[1] == "jump":
        print(json.dumps(privileged_jump(int(sys.argv[2]), *sys.argv[3:7])))
    elif sys.argv[1] == "pure-clock":
        pure_clock()
    else:
        raise SystemExit("unknown guest clock operation")

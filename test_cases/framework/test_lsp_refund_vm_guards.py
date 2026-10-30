"""Pure guard checks: no VM, node, subprocess, or real clock syscall."""

import json
from pathlib import Path
import stat
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_cases.fiber.devnet.lsp_nightly import _vm_time as clock


@pytest.fixture
def guest(monkeypatch, tmp_path):
    data = dict(
        boot_id="guest-boot",
        revision=clock.REVISION,
        freeze_id="frozen",
        mode="formal",
        instance="isolated-guest",
        run_id="one-run",
        guest_deadline_mono=1000,
        qualified=dict(pure_clock=True, old_adapter=True, chain_sdk=True),
    )
    metadata = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0)
    marker = SimpleNamespace(lstat=lambda: metadata, read_text=lambda: json.dumps(data))
    syscall = Mock(side_effect=AssertionError("real clock syscall is forbidden"))
    fake_time = SimpleNamespace(
        time=lambda: 1000.0,
        monotonic=lambda: 100.0,
        CLOCK_REALTIME=0,
        clock_settime=syscall,
    )
    monkeypatch.setattr(clock, "time", fake_time)
    monkeypatch.setattr(clock, "platform", SimpleNamespace(system=lambda: "Linux"))
    monkeypatch.setattr(
        clock,
        "os",
        SimpleNamespace(
            geteuid=lambda: 0,
            open=clock.os.open,
            close=clock.os.close,
            fchmod=clock.os.fchmod,
            fsync=clock.os.fsync,
            replace=clock.os.replace,
            O_WRONLY=clock.os.O_WRONLY,
            O_CREAT=clock.os.O_CREAT,
            O_EXCL=clock.os.O_EXCL,
            O_NOFOLLOW=clock.os.O_NOFOLLOW,
            environ={},
        ),
    )
    monkeypatch.setattr(clock, "MARKER", marker)
    monkeypatch.setattr(clock, "EVENT", tmp_path / "event.json")
    monkeypatch.setattr(
        clock,
        "Path",
        lambda value: (
            SimpleNamespace(read_text=lambda: "guest-boot\n")
            if str(value) == "/proc/sys/kernel/random/boot_id"
            else Path(value)
        ),
    )
    return SimpleNamespace(
        data=data, metadata=metadata, syscall=syscall, time=fake_time
    )


def jump(guest):
    return clock.privileged_jump(
        1_010_000,
        guest.data["instance"],
        guest.data["run_id"],
        guest.data["boot_id"],
        "0x" + "ab" * 32,
    )


def test_non_linux_rejected_before_clock_syscall(guest, monkeypatch):
    monkeypatch.setattr(clock.platform, "system", lambda: "Darwin")
    with pytest.raises(AssertionError, match="Linux guest"):
        jump(guest)
    guest.syscall.assert_not_called()
    assert not clock.EVENT.exists()


@pytest.mark.parametrize("invalid", ["boot", "permissions", "owner", "qualification"])
def test_invalid_guest_identity_rejected_before_clock_syscall(guest, invalid):
    if invalid == "boot":
        guest.data["boot_id"] = "different-boot"
    elif invalid == "permissions":
        guest.metadata.st_mode = stat.S_IFREG | 0o666
    elif invalid == "owner":
        guest.metadata.st_uid = 1000
    else:
        guest.data["qualified"]["chain_sdk"] = False
    with pytest.raises(AssertionError):
        jump(guest)
    guest.syscall.assert_not_called()
    assert not clock.EVENT.exists()


def test_failed_syscall_consumes_only_clock_allowance(guest):
    guest.syscall.side_effect = OSError("injected syscall failure")
    with pytest.raises(OSError, match="injected syscall failure"):
        jump(guest)
    event = json.loads(clock.EVENT.read_text())
    assert event["state"] == "consumed"
    with pytest.raises(FileExistsError):
        jump(guest)
    guest.syscall.assert_called_once_with(0, 1015.0)


def test_unregistered_wall_clock_jump_fails_monitor(guest, monkeypatch, tmp_path):
    # Keep the monitor synchronous: this test starts no background worker.
    monkeypatch.setattr(
        clock,
        "threading",
        SimpleNamespace(
            Event=threading.Event,
            RLock=threading.RLock,
            Thread=lambda **_kwargs: Mock(),
        ),
    )
    for key, field in [
        ("LSP_REFUND_VM_MODE", "mode"),
        ("LSP_REFUND_VM_INSTANCE", "instance"),
        ("LSP_REFUND_VM_RUN_ID", "run_id"),
    ]:
        clock.os.environ[key] = guest.data[field]
    monitor = clock.GuestClock(tmp_path)
    monitor.check()
    guest.time.time = lambda: 1100.0
    with pytest.raises(AssertionError, match="unexpected guest wall clock change"):
        monitor.check()
    guest.syscall.assert_not_called()

"""Pure mocked firewall checks; never invoke a firewall, VM or node."""

import importlib.util
import json
from pathlib import Path
import shlex

import pytest

spec = importlib.util.spec_from_file_location(
    "lsp_vm_network",
    Path(__file__).resolve().parents[2] / "scripts/lsp_refund_vm_network.py",
)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class Firewall:
    def __init__(self):
        self.policies = {tool: "ACCEPT" for tool in network.TOOLS}
        self.rules = {tool: [] for tool in network.TOOLS}
        self.probe_packets = 0
        self.other_packets = 999
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        tool = argv[0].removesuffix("-save")
        assert tool in network.TOOLS
        if argv[0].endswith("-save"):
            return "\n".join(
                f"[{self.probe_packets if '--comment' in r else self.other_packets}:60] "
                + shlex.join(["-A", "OUTPUT", *r])
                for r in self.rules[tool]
            )
        assert argv[1:3] == ["-w", "1"]
        action = argv[3]
        if action == "-S":
            return "\n".join(
                [
                    f"-P OUTPUT {self.policies[tool]}",
                    *[shlex.join(["-A", "OUTPUT", *r]) for r in self.rules[tool]],
                ]
            )
        assert argv[4] == "OUTPUT"
        if action == "-A":
            self.rules[tool].append(argv[5:])
        elif action == "-I":
            self.rules[tool].insert(int(argv[5]) - 1, argv[6:])
        elif action == "-D":
            self.rules[tool].remove(argv[5:])
        elif action == "-P":
            self.policies[tool] = argv[5]
        else:
            raise AssertionError(action)
        return ""


@pytest.fixture(
    params=["192.0.2.3 54321 192.0.2.4 22", "2001:db8::3 54321 2001:db8::4 22"]
)
def guest(request):
    firewall = Firewall()
    isolate = network.Isolation(
        network.ssh_flow(request.param), "lr-0-12345678", "guest-boot", firewall
    )
    return isolate, firewall


def test_requires_exact_tracked_flow_before_drop(guest):
    isolate, firewall = guest
    state = isolate.bootstrap()
    assert all(value == "ACCEPT" for value in firewall.policies.values())
    assert firewall.rules[isolate.flow["tool"]][1] == state["probe"]
    assert state["probe"][state["probe"].index("--ctstate") + 1] == "ESTABLISHED"
    with pytest.raises(AssertionError, match="no ESTABLISHED probe hit"):
        isolate.seal(state)
    assert all(value == "ACCEPT" for value in firewall.policies.values())
    firewall.probe_packets = 1
    sealed = isolate.seal(state)
    result = isolate.verify(sealed)
    assert result["phase"] == "verified" and sealed["probe_counter"]["packets"] == 1
    assert all(value == "DROP" for value in firewall.policies.values())
    assert all(
        [network.normalized(r) for r in firewall.rules[t]] == isolate.expected(t)
        for t in network.TOOLS
    )


def test_management_tuple_change_fails_before_drop(guest):
    isolate, firewall = guest
    state = isolate.bootstrap()
    firewall.probe_packets = 10
    changed = {**isolate.flow, "client_port": isolate.flow["client_port"] + 1}
    with pytest.raises(AssertionError, match="connection changed"):
        network.Isolation(changed, isolate.instance, isolate.boot_id, firewall).seal(
            state
        )
    assert all(value == "ACCEPT" for value in firewall.policies.values())


def test_unrelated_nonzero_counter_cannot_satisfy_probe(guest):
    isolate, firewall = guest
    state = isolate.bootstrap()
    firewall.other_packets = 100000
    with pytest.raises(AssertionError, match="no ESTABLISHED probe hit"):
        isolate.seal(state)


def test_changed_final_rules_are_not_accepted(guest):
    isolate, firewall = guest
    state = isolate.bootstrap()
    firewall.probe_packets = 1
    state = isolate.seal(state)
    firewall.rules["ip6tables"].append(["-j", "ACCEPT"])
    with pytest.raises(AssertionError, match="OUTPUT rules"):
        isolate.verify(state)


def test_old_rules_are_not_flushed_or_overwritten(guest):
    isolate, firewall = guest
    firewall.rules["iptables"].append(["-j", "ACCEPT"])
    with pytest.raises(AssertionError, match="not pristine"):
        isolate.bootstrap()
    assert not any("-P" in call or "-F" in call for call in firewall.calls)


def test_probe_must_keep_the_complete_tuple(guest):
    isolate, firewall = guest
    state = isolate.bootstrap()
    firewall.probe_packets = 1
    state["probe"] = ["-m", "conntrack", "--ctstate", "ESTABLISHED", "-j", "ACCEPT"]
    with pytest.raises((AssertionError, ValueError)):
        isolate.seal(state)
    assert all(value == "ACCEPT" for value in firewall.policies.values())


def test_counter_state_order_is_canonicalized():
    assert network.normalized(network.ESTABLISHED) == network.normalized(
        ["-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
    )


@pytest.mark.parametrize(
    "value", ["192.0.2.3 0 192.0.2.4 22", "192.0.2.3 22 2001:db8::4 22", "bad tuple"]
)
def test_bad_ssh_connection_is_rejected(value):
    with pytest.raises((AssertionError, ValueError)):
        network.ssh_flow(value)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_controller_command_audit_preserves_output_not_arguments(
    monkeypatch, tmp_path, exit_code
):
    spec = importlib.util.spec_from_file_location(
        "lsp_vm_host", Path(__file__).resolve().parents[2] / "scripts/lsp_refund_vm.py"
    )
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    controller = object.__new__(host.Controller)
    controller.output, controller.audit = tmp_path, tmp_path / "host.jsonl"
    controller.command_index, controller.active = 0, "lr-0-12345678"
    controller.env, controller.host = {"PRIVATE_ENV": "env-secret"}, lambda: None

    class Process:
        returncode = exit_code

        def __init__(self, args, **kwargs):
            assert args[-1] == "argument-secret"
            kwargs["stdout"].write(b"public stdout\n")
            kwargs["stderr"].write(b"public stderr\n")

        def communicate(self, **kwargs):
            assert kwargs["input"] == b"input-secret"
            return None, None

        def poll(self):
            return self.returncode

        def wait(self):
            return self.returncode

    monkeypatch.setattr(host.subprocess, "Popen", Process)
    if exit_code:
        with pytest.raises(AssertionError, match="command failed"):
            controller.call(
                ["fake", "argument-secret"],
                host.time.monotonic() + 10,
                input=b"input-secret",
                label="network.probe",
            )
    else:
        assert (
            controller.call(
                ["fake", "argument-secret"],
                host.time.monotonic() + 10,
                input=b"input-secret",
                label="network.probe",
            )
            == "public stdout\n"
        )
    log = controller.audit.read_text()
    assert all(
        secret not in log
        for secret in ("argument-secret", "env-secret", "input-secret")
    )
    rows = [json.loads(line) for line in log.splitlines()]
    assert [row["kind"] for row in rows] == ["command-start", "command-end"]
    assert rows[-1]["exit_code"] == exit_code and rows[-1]["timed_out"] is False
    assert rows[-1]["label"] == "network.probe"
    assert (tmp_path / rows[-1]["stdout"]).read_text() == "public stdout\n"
    assert (tmp_path / rows[-1]["stderr"]).read_text() == "public stderr\n"


def test_controller_timeout_has_command_level_evidence(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "lsp_vm_timeout",
        Path(__file__).resolve().parents[2] / "scripts/lsp_refund_vm.py",
    )
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    controller = object.__new__(host.Controller)
    controller.output, controller.audit = tmp_path, tmp_path / "host.jsonl"
    controller.command_index, controller.active, controller.env = 0, "lr-0-12345678", {}
    controller.host = lambda: None

    class Process:
        pid, returncode = 123, None

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, **kwargs):
            raise host.subprocess.TimeoutExpired("fake", 0)

        def poll(self):
            return self.returncode

        def wait(self):
            self.returncode = -9

    monkeypatch.setattr(host.subprocess, "Popen", Process)
    kills = []
    monkeypatch.setattr(host.os, "killpg", lambda *args: kills.append(args))
    with pytest.raises(TimeoutError, match="network.seal"):
        controller.call(
            ["fake"], host.time.monotonic() + 10, timeout=0, label="network.seal"
        )
    row = json.loads(controller.audit.read_text().splitlines()[-1])
    assert (
        row["timed_out"]
        and row["exit_code"] == -9
        and row["error_type"] == "TimeoutError"
    )
    assert len(kills) == 1

#!/usr/bin/env python3
"""Three-step OUTPUT isolation for one dedicated guest's SSH management flow.

bootstrap returns with ACCEPT, allowing conntrack to observe the existing SSH
round trip. seal is a later SSH command: only a matching ESTABLISHED rule's
packet counter proves this exact flow is tracked. verify is an independent SSH
round trip after DROP. This helper never changes a clock or starts a node.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shlex
import stat
import subprocess
import sys
import uuid

STATE = Path("/run/lsp-refund-vm-network.json")
TOOLS = ("iptables", "ip6tables")
LOOPBACK = ["-o", "lo", "-j", "ACCEPT"]
ESTABLISHED = ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"]


def ssh_flow(value):
    client, client_port, server, server_port = value.split()
    client, server = ipaddress.ip_address(client), ipaddress.ip_address(server)
    assert client.version == server.version, "mixed SSH address families"
    ports = (int(client_port), int(server_port))
    assert all(0 < port < 65536 for port in ports), "invalid SSH port"
    return dict(
        client=str(client),
        client_port=ports[0],
        server=str(server),
        server_port=ports[1],
        tool="iptables" if client.version == 4 else "ip6tables",
    )


def normalized(rule):
    rule = list(rule)
    if "--ctstate" in rule:
        index = rule.index("--ctstate") + 1
        rule[index] = ",".join(sorted(rule[index].split(",")))
    return rule


def probe_rule(flow, token):
    bits = 32 if flow["tool"] == "iptables" else 128
    return [
        "-s",
        f"{flow['server']}/{bits}",
        "-d",
        f"{flow['client']}/{bits}",
        "-p",
        "tcp",
        "-m",
        "tcp",
        "--sport",
        str(flow["server_port"]),
        "--dport",
        str(flow["client_port"]),
        "-m",
        "conntrack",
        "--ctstate",
        "ESTABLISHED",
        "-m",
        "comment",
        "--comment",
        "lr-ssh-probe-" + token,
        "-j",
        "ACCEPT",
    ]


def command(argv):
    try:
        return subprocess.check_output(
            argv, text=True, stderr=subprocess.PIPE, timeout=1
        )
    except subprocess.CalledProcessError as error:
        # Preserve the public firewall diagnostic in the host command's stderr.
        sys.stderr.write(error.stderr or "")
        raise


class Isolation:
    def __init__(self, flow, instance, boot_id, run=command):
        self.flow, self.instance, self.boot_id, self.run = flow, instance, boot_id, run

    def rules(self, tool):
        lines = [
            shlex.split(line)
            for line in self.run([tool, "-w", "1", "-S", "OUTPUT"]).splitlines()
        ]
        assert lines and lines[0][:2] == ["-P", "OUTPUT"], "missing OUTPUT policy"
        assert all(
            line[:2] == ["-A", "OUTPUT"] for line in lines[1:]
        ), "unexpected OUTPUT description"
        return lines[0][2], [normalized(line[2:]) for line in lines[1:]]

    def expected(self, tool, state=None):
        rules = [LOOPBACK, ESTABLISHED]
        if state and tool == self.flow["tool"]:
            rules.insert(1, state["probe"])
        return [normalized(rule) for rule in rules]

    def assert_rules(self, policy, state=None):
        observed = {}
        for tool in TOOLS:
            actual_policy, rules = self.rules(tool)
            assert actual_policy == policy and rules == self.expected(
                tool, state
            ), f"unexpected {tool} OUTPUT rules"
            observed[tool] = dict(policy=actual_policy, rules=rules)
        return observed

    def bootstrap(self):
        # No policy reset, flush, broad allow, or recovery of a previous attempt.
        for tool in TOOLS:
            assert self.rules(tool) == (
                "ACCEPT",
                [],
            ), "guest OUTPUT was not pristine ACCEPT"
        state = dict(
            phase="bootstrap",
            instance=self.instance,
            boot_id=self.boot_id,
            flow=self.flow,
            probe=probe_rule(self.flow, uuid.uuid4().hex),
        )
        for tool in TOOLS:
            for rule in (LOOPBACK, ESTABLISHED):
                self.run([tool, "-w", "1", "-A", "OUTPUT", *rule])
        self.run([self.flow["tool"], "-w", "1", "-I", "OUTPUT", "2", *state["probe"]])
        state["rules"] = self.assert_rules("ACCEPT", state)
        return state

    def identity(self, state, phase):
        assert (
            state["instance"] == self.instance and state["boot_id"] == self.boot_id
        ), "foreign network state"
        assert state["flow"] == self.flow, "SSH management connection changed"
        assert state["phase"] == phase, "wrong network phase; no automatic retry"
        expected = probe_rule(
            self.flow,
            state["probe"][state["probe"].index("--comment") + 1].removeprefix(
                "lr-ssh-probe-"
            ),
        )
        assert state["probe"] == expected, "probe does not bind the complete SSH tuple"

    def counter(self, state):
        text = self.run([self.flow["tool"] + "-save", "-c", "-t", "filter"])
        counts = []
        for line in text.splitlines():
            match = re.fullmatch(r"\[(\d+):(\d+)\] (.*)", line)
            if match:
                rule = shlex.split(match[3])
                if rule[:2] == ["-A", "OUTPUT"] and normalized(rule[2:]) == normalized(
                    state["probe"]
                ):
                    counts.append(dict(packets=int(match[1]), bytes=int(match[2])))
        assert (
            len(counts) == 1 and counts[0]["packets"] > 0
        ), "current SSH tuple has no ESTABLISHED probe hit"
        return counts[0]

    def seal(self, state):
        self.identity(state, "bootstrap")
        self.assert_rules("ACCEPT", state)
        count = self.counter(state)
        self.run([self.flow["tool"], "-w", "1", "-D", "OUTPUT", *state["probe"]])
        # Exact final rules are checked before changing either family policy.
        self.assert_rules("ACCEPT")
        for tool in TOOLS:
            self.run([tool, "-w", "1", "-P", "OUTPUT", "DROP"])
        state = {
            **state,
            "phase": "sealed",
            "probe_counter": count,
            "rules": self.assert_rules("DROP"),
        }
        return state

    def verify(self, state):
        self.identity(state, "sealed")
        return {**state, "phase": "verified", "rules": self.assert_rules("DROP")}


def read_state():
    info = STATE.lstat()
    assert (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o644
    )
    return json.loads(STATE.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("bootstrap", "seal", "verify"))
    parser.add_argument("--instance", required=True)
    parser.add_argument("--boot-id", required=True)
    parser.add_argument("--ssh-connection", required=True)
    args = parser.parse_args()
    assert (
        platform.system() == "Linux" and os.geteuid() == 0
    ), "dedicated Linux guest root required"
    assert re.fullmatch(
        r"lr-[a-z0-9]+-[a-f0-9]{8}", args.instance
    ), "unexpected instance identity"
    assert (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip() == args.boot_id
    ), "guest boot changed"
    isolate = Isolation(ssh_flow(args.ssh_connection), args.instance, args.boot_id)
    if args.phase == "bootstrap":
        # Consume the phase before touching rules; failures require a fresh VM.
        fd = os.open(STATE, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w") as stream:
            json.dump(dict(phase="initializing"), stream)
        result = isolate.bootstrap()
    else:
        result = getattr(isolate, args.phase)(read_state())
    temp = STATE.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
    os.fchmod(fd, 0o644)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, STATE)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

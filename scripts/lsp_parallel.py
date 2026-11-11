"""Two-job LSP pilot: independent processes, leased ports and bounded cancellation."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time

PILOT_GROUPS = ("browser-auth", "subscription-filters")
PILOT_CLASSES = ("TestBrowserSigningSubscriptions", "TestSigningSubscriptionFilters")
PORT_FIELDS = (
    "ckb_rpc_port",
    "ckb_p2p_port",
    "fiber1_rpc_port",
    "fiber1_p2p_port",
    "fiber2_rpc_port",
    "fiber2_p2p_port",
    "lsp_ws_port",
)
FLOOR_BYTES = 8 * 2**30
BUDGET_BYTES = 2 * 2**30


def validate_ports(ports):
    if not isinstance(ports, dict) or set(ports) != set(PORT_FIELDS):
        raise ValueError("parallel port map must contain exactly the seven pilot ports")
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports.values()):
        raise ValueError("invalid parallel port number")
    if len(set(ports.values())) != len(PORT_FIELDS):
        raise ValueError("parallel ports must be distinct")
    return ports


def validate_plan(jobs, groups):
    if len(jobs) != 2 or {j["group"] for j in jobs} != set(PILOT_GROUPS):
        raise ValueError(
            "2-worker pilot requires exactly the complete browser and filter groups"
        )
    if any(tuple(j["nodeids"]) != groups[j["group"]] for j in jobs):
        raise ValueError("parallel pilot may not split or extend a shared group")


class PortLease:
    """Keep a file lock for the full child lifetime; never remove lock files.

    Fixed blocks are below the usual ephemeral range. Other cooperating runners
    cannot take a block between the bind probe and the actual node startup.
    Existing external listeners are skipped and are never stopped.
    """

    def __init__(self, directory=None, bases=range(20000, 30000, 16)):
        self.directory = Path(
            directory or Path(tempfile.gettempdir()) / f"fiber-lsp-ports-{os.getuid()}"
        )
        self.bases = bases
        self.stream = None
        self.ports = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        for base in self.bases:
            stream = (self.directory / f"{base}.lock").open("a+")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stream.close()
                continue
            ports = validate_ports(
                dict(zip(PORT_FIELDS, range(base, base + len(PORT_FIELDS))))
            )
            probes = []
            try:
                for port in ports.values():
                    sock = socket.socket()
                    probes.append(sock)
                    sock.bind(("127.0.0.1", port))
            except OSError:
                stream.close()
                continue
            finally:
                for sock in probes:
                    sock.close()
            self.stream, self.ports = stream, ports
            try:
                stream.seek(0)
                stream.truncate()
                json.dump({"owner_pid": os.getpid(), "ports": ports}, stream)
                stream.flush()
            except BaseException:
                stream.close()
                raise
            return ports
        raise RuntimeError("no unused pilot port block; no process was stopped")

    def __exit__(self, *_):
        if self.stream is not None:
            self.stream.close()  # OS releases the lease; the lock inode stays stable.


def wait_child(process, timeout, cancel, tick=None):
    until = time.monotonic() + timeout
    while True:
        if tick is not None:
            tick()
        if cancel.is_set():
            raise InterruptedError("parallel batch interrupted")
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(0.2, remaining))
        except subprocess.TimeoutExpired:
            pass


def run_two_jobs(jobs, output, bundle, timeout, run_job, results, write_json):
    free_start = shutil.disk_usage(output).free
    if free_start < FLOOR_BYTES + BUDGET_BYTES:
        raise RuntimeError(
            "2-worker admission needs 8GiB floor plus 2GiB batch reserve"
        )
    cancel = threading.Event()

    def worker(index, job):
        directory = output / f"job-{index:03d}"
        try:
            with PortLease() as ports:
                return run_job(
                    job,
                    directory,
                    bundle,
                    timeout,
                    port_map=ports,
                    cancel_event=cancel,
                    worker_id=index,
                )
        except Exception as error:
            row = {
                **job,
                "worker": index,
                "exit_code": None,
                "duration_seconds": 0,
                "errors": [repr(error)],
                "outcomes": {n: "not_run" for n in job["nodeids"]},
            }
            try:
                directory.mkdir(parents=True, exist_ok=True)
                write_json(directory / "result.json", row)
            except OSError as diagnostic:
                row["errors"].append(repr(diagnostic))
                try:
                    write_json(output / f"worker-{index}-failure.json", row)
                except OSError as fallback:
                    # The outer summary can still retain both outcomes. A
                    # diagnostic permission failure must not hide its peer.
                    row["errors"].append(repr(fallback))
            return row

    pool = ThreadPoolExecutor(max_workers=2)
    futures = {pool.submit(worker, i, j): i for i, j in enumerate(jobs)}
    pending, collected = set(futures), set()
    try:
        while pending:
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                row = future.result()
                results.append(row)
                collected.add(future)
                print(
                    json.dumps(
                        {
                            "job": futures[future],
                            "group": row["group"],
                            "seconds": row["duration_seconds"],
                            "outcomes": row.get("outcomes"),
                            "errors": row["errors"],
                        }
                    ),
                    flush=True,
                )
            # A local failure does not interrupt the unrelated worker. Global
            # disk exhaustion or a user stop interrupts both with the same
            # existing SIGINT/grace/owned-process-group cleanup as serial jobs.
            free = shutil.disk_usage(output).free
            if free < FLOOR_BYTES or free_start - free > BUDGET_BYTES:
                raise RuntimeError("parallel batch disk floor/budget exhausted")
    except BaseException:
        cancel.set()
        raise
    finally:
        pool.shutdown(wait=True)
        for future in futures:
            if future not in collected:
                results.append(future.result())
        results.sort(
            key=lambda row: jobs.index(
                {"group": row["group"], "nodeids": row["nodeids"]}
            )
        )

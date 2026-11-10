#!/usr/bin/env python3
"""Run ordinary LSP tests serially; reuse only the two validated query groups."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SUITE = "test_cases/fiber/devnet/lsp"
REVISION = "76307312e8de518c9a32074e6d16867c04de4f86"
INVOICE = SUITE + "/test_tenant_boundaries.py::TestTenantQueryIsolation::"
PAYMENT = SUITE + "/test_tenant_payment_queries.py::TestTenantPaymentQueries::"
GROUPS = {
    "invoice-cancel": tuple(
        SUITE
        + "/test_hosted_invoice_cancellation.py::TestHostedInvoiceCancellation::"
        + name
        for name in (
            "test_open_invoice_cancelled_old_payment_fails_new_payment_succeeds",
            "test_received_invoice_without_preimage_can_be_cancelled",
        )
    ),
    "invoice-query": tuple(
        INVOICE + name
        for name in (
            "test_default_namespace_invoice_query_is_isolated",
            "test_explicit_tenant_target_is_rejected",
            "test_tenant_token_cannot_list_tenants",
            "test_tenant_token_cannot_parse_invoice",
        )
    ),
    "payment-query": tuple(
        PAYMENT + name
        for name in (
            "test_default_payment_namespace_is_isolated",
            "test_explicit_payment_target_rejects_other_tenant",
            "test_operator_payment_query_selects_explicit_tenant",
        )
    ),
}
QUALIFICATION = (
    SUITE + "/test_delivery_acceptance.py::TestDeliveryQualification::"
    "test_normal_control_payment_qualifies_real_path"
)
PORTS = (8114, 8125, 8227, 8228, 8229, 8230, 8248, 8249)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def is_delivery(nodeid):
    return Path(nodeid.split("::")[0]).name in (
        "test_delivery_acceptance.py",
        "test_delivery_fnn_restart.py",
    )


def build_plan(nodeids, independent=False):
    if not nodeids or len(set(nodeids)) != len(nodeids):
        raise ValueError("selection must contain nonempty, unique native methods")
    if any(not n.startswith(SUITE + "/") or len(n.split("::")) != 3 for n in nodeids):
        raise ValueError(
            "only ordinary LSP class methods are allowed; nightly excluded"
        )
    if any(is_delivery(n) for n in nodeids):
        if QUALIFICATION not in nodeids:
            raise ValueError(
                "include the Delivery qualification method before fault tests"
            )
        nodeids = [QUALIFICATION, *[n for n in nodeids if n != QUALIFICATION]]
    jobs, used = [], set()
    for nodeid in nodeids:
        if nodeid in used:
            continue
        group = next((key for key, values in GROUPS.items() if nodeid in values), None)
        # Partial selections stay independent: reuse is qualified only for full groups.
        shared = not independent and group and set(GROUPS[group]) <= set(nodeids)
        selected = list(GROUPS[group]) if shared else [nodeid]
        jobs.append({"group": group if shared else None, "nodeids": selected})
        used.update(selected)
    return jobs


def environment(bundle, directory=None, job=None, delivery=None, nolsp=None):
    # Prevent inherited shared flags, budgets, output paths or pytest -n options.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("LSP_") and k not in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")
    }
    env.update(
        LSP_TEST_REVISION=REVISION,
        LSP_RETEST_REVISION=REVISION,
        LSP_TEST_BUNDLE=str(bundle),
        LSP_QUERY_ENV_MODE="independent",
        LSP_INVOICE_QUERY_ENV_MODE="independent",
        LSP_CANCEL_ENV_MODE="independent",
        LSP_QUERY_KEEP_RUNTIME="1",
        LSP_INVOICE_QUERY_KEEP_RUNTIME="1",
        LSP_CANCEL_KEEP_RUNTIME="1",
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        PYTEST_ADDOPTS="",
    )
    if directory is not None:
        for variable, name in (
            ("LSP_RUN_ARTIFACTS", "nodes"),
            ("LSP_PAYMENT_REPORT_DIR", "business"),
            ("LSP_DELIVERY_REPORT_DIR", "delivery"),
            ("LSP_RECOVERY_ARTIFACTS", "recovery"),
            ("LSP_DEADLINE_ARTIFACTS", "deadline"),
            ("CKB_CLI_HOME", "ckb-cli"),
        ):
            env[variable] = str(directory / name)
        env["LSP_REGRESSION_CASE"] = str(directory)
        # Legacy framework commands use this path in a shell. Keep its basename
        # independent of the user-supplied evidence path, including whitespace.
        env["LSP_REGRESSION_RUNTIME"] = str(
            Path("tmp") / f"lsp-serial-{uuid.uuid4().hex}"
        )
        env["LSP_REGRESSION_SELECTORS"] = json.dumps(job["nodeids"])
        if job["group"]:
            variable = {
                "payment-query": "LSP_QUERY_ENV_MODE",
                "invoice-query": "LSP_INVOICE_QUERY_ENV_MODE",
                "invoice-cancel": "LSP_CANCEL_ENV_MODE",
            }[job["group"]]
            env[variable] = "shared"
        env["LSP_PAYMENT04_ROW_START"] = str(time.monotonic())
    if delivery:
        env["LSP_DELIVERY_NODE"] = str(delivery)
    if nolsp:
        env["LSP_NOLSP_FNN"] = str(nolsp)
        env["LSP_NOLSP_FNN_SHA256"] = digest(nolsp)
    return env


def pytest_command():
    return [sys.executable, "-m", "pytest", "-o", "addopts=", "-p", "no:cacheprovider"]


def collect(selectors, output, env):
    command = pytest_command() + ["--collect-only", "-q", *selectors]
    with (output / "collection.log").open("w") as log:
        result = subprocess.run(
            command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60
        )
    if result.returncode:
        raise ValueError("native collection failed; see collection.log")
    return [
        line.strip()
        for line in (output / "collection.log").read_text().splitlines()
        if line.startswith(SUITE + "/") and "::" in line and " " not in line
    ]


def check_environment():
    free = shutil.disk_usage(ROOT).free
    if free < 8 * 2**30:
        raise RuntimeError(f"free disk below 8 GiB: {free} bytes")
    for port in PORTS:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"occupied test port {port}; no process was stopped")
    return free


def group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def interrupt_on_termination(signum, _frame):
    # Let the same bounded job cleanup handle an external stop as Ctrl-C.
    raise KeyboardInterrupt(f"received signal {signum}")


def drain_group(process):
    """Only signal the session created for this job; never kill by name/port."""
    leaked = group_exists(process.pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not group_exists(process.pid):
            break
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        until = time.monotonic() + 5
        while group_exists(process.pid) and time.monotonic() < until:
            process.poll()
            time.sleep(0.1)
    process.wait(timeout=1)
    if group_exists(process.pid):
        raise RuntimeError(f"owned process group still exists: {process.pid}")
    return leaked


def native_outcomes(path, nodeids):
    expected = {
        (
            n.split("::")[0][:-3].replace("/", ".") + "." + n.split("::")[1],
            n.split("::")[2],
        ): n
        for n in nodeids
    }
    results = {}
    for row in ET.parse(path).getroot().iter("testcase"):
        key = (row.get("classname"), row.get("name"))
        if key not in expected:
            raise ValueError(f"unexpected native testcase: {key}")
        tags = {child.tag for child in row}
        status = next(
            (s for s in ("error", "failure", "skipped") if s in tags), "passed"
        )
        nodeid = expected[key]
        if nodeid in results and status == results[nodeid] == "passed":
            raise ValueError(f"duplicate native pass: {nodeid}")
        rank = {"passed": 0, "skipped": 1, "failure": 2, "error": 3}
        if nodeid not in results or rank[status] > rank[results[nodeid]]:
            results[nodeid] = status
    for nodeid in nodeids:
        results.setdefault(nodeid, "not_run")
    return results


def run_job(job, directory, bundle, timeout, delivery=None, nolsp=None):
    directory.mkdir()
    env = environment(bundle, directory, job, delivery, nolsp)
    runtime = ROOT / env["LSP_REGRESSION_RUNTIME"]
    if runtime.exists():
        raise ValueError(f"runtime already exists: {runtime}")
    command = pytest_command() + [
        "-p",
        "scripts.lsp_regression_runtime",
        "-x",
        "-vv",
        "-s",
        "--tb=short",
        *job["nodeids"],
        "--junitxml=" + str(directory / "junit.xml"),
    ]
    record = {
        **job,
        "command": command,
        "environment": {
            k: v for k, v in env.items() if k.startswith("LSP_") or k == "CKB_CLI_HOME"
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "free_bytes_before": check_environment(),
        "errors": [],
    }
    write_json(directory / "command.json", record)
    started = time.monotonic()
    process = None
    try:
        with (directory / "stdout.log").open("w") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            record["pid"] = process.pid
            try:
                process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                record["errors"].append(type(error).__name__)
                # Interrupt pytest first so its fixture teardown can archive.
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    record["errors"].append(
                        "pytest did not finish its 60s cleanup grace"
                    )
    finally:
        try:
            if process is not None:
                if drain_group(process):
                    record["errors"].append(
                        "owned processes required outer termination"
                    )
                record["exit_code"] = process.returncode
            record["outcomes"] = native_outcomes(
                directory / "junit.xml", job["nodeids"]
            )
            record["junit_sha256"] = digest(directory / "junit.xml")
            record["free_bytes_after"] = check_environment()
        except (
            OSError,
            ValueError,
            RuntimeError,
            ET.ParseError,
            subprocess.SubprocessError,
        ) as error:
            record["errors"].append(repr(error))
        record["duration_seconds"] = time.monotonic() - started
        if (directory / "stdout.log").exists():
            record["stdout_sha256"] = digest(directory / "stdout.log")
        write_json(directory / "result.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "selectors",
        nargs="*",
        help="ordinary LSP paths/nodeids; default: whole ordinary directory",
    )
    parser.add_argument(
        "--only-shared-groups",
        action="store_true",
        help="select exactly the seven validated methods",
    )
    parser.add_argument(
        "--independent",
        action="store_true",
        help="run each selected method in its own pytest process",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="collect and save the plan without starting nodes",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="fresh evidence directory; default: local-evidence/<unique batch>",
    )
    parser.add_argument(
        "--bundle", type=Path, default=ROOT / "download/fiber/pr-1623-7630731"
    )
    parser.add_argument("--delivery-node", type=Path)
    parser.add_argument("--nolsp-fnn", type=Path)
    parser.add_argument("--job-timeout", type=float, default=1800)
    parser.add_argument(
        "--junitxml",
        type=Path,
        help="fresh aggregate native JUnit path; default: <output>/junit.xml",
    )
    args = parser.parse_args()
    if args.only_shared_groups and args.selectors:
        parser.error("--only-shared-groups cannot be combined with selectors")
    if not math.isfinite(args.job_timeout) or args.job_timeout <= 0:
        parser.error("--job-timeout must be positive and finite")
    # Reject paths/options outside the ordinary suite before invoking pytest.
    selectors = args.selectors or (
        [n for group in GROUPS.values() for n in group]
        if args.only_shared_groups
        else [SUITE]
    )
    if any(
        not (s == SUITE or s.startswith(SUITE + "/"))
        or ".." in Path(s.split("::")[0]).parts
        for s in selectors
    ):
        parser.error("selectors must stay in the ordinary LSP directory")
    output = (
        args.output
        or ROOT
        / "local-evidence"
        / ("lsp-serial-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    ).absolute()
    output.mkdir(parents=True, exist_ok=False)
    junit = (args.junitxml or output / "junit.xml").absolute()
    results = []
    nodeids = []
    try:
        if junit.exists() or junit.is_symlink():
            raise ValueError(f"refusing to replace existing JUnit: {junit}")
        bundle = args.bundle.resolve()
        env = environment(bundle)
        nodeids = collect(selectors, output, env)
        jobs = build_plan(nodeids, args.independent)
        write_json(
            output / "plan.json",
            {
                "revision": REVISION,
                "bundle": str(bundle),
                "nodeids": nodeids,
                "jobs": jobs,
            },
        )
        print(
            f"{len(nodeids)} methods / {len(jobs)} serial jobs; evidence: {output}",
            flush=True,
        )
        if args.plan_only:
            return 0
        manifest = bundle / "build.json"
        if json.loads(manifest.read_text())["revision"] != REVISION:
            raise ValueError("bundle is not the fixed 76307312 revision")
        shutil.copy2(manifest, output / "build.json")
        if any(is_delivery(n) for n in nodeids) and not args.delivery_node:
            raise ValueError("--delivery-node is required for Delivery methods")
        if (
            any("/test_lsp_feature_off.py::" in n for n in nodeids)
            and not args.nolsp_fnn
        ):
            raise ValueError("--nolsp-fnn is required for feature-off methods")
        for index, job in enumerate(jobs):
            row = run_job(
                job,
                output / f"job-{index:03d}",
                bundle,
                args.job_timeout,
                args.delivery_node,
                args.nolsp_fnn,
            )
            results.append(row)
            print(
                json.dumps(
                    {
                        "job": index,
                        "group": job["group"],
                        "outcomes": row.get("outcomes"),
                        "seconds": row["duration_seconds"],
                        "errors": row["errors"],
                    }
                ),
                flush=True,
            )
            if row["errors"] or any(
                v in ("error", "skipped", "not_run")
                for v in row.get("outcomes", {}).values()
            ):
                raise RuntimeError("incomplete/unsafe job; batch stopped, no retry")
            if QUALIFICATION in job["nodeids"] and row.get("exit_code") != 0:
                raise RuntimeError(
                    "Delivery qualification failed; fault tests not started"
                )
        failed = any(
            r.get("exit_code") != 0 or set(r["outcomes"].values()) != {"passed"}
            for r in results
        )
        return int(failed)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        write_json(output / "batch-error.json", {"error": repr(error)})
        print(f"batch stopped: {error}; evidence: {output}", file=sys.stderr)
        return 2
    finally:
        write_json(
            output / "summary.json",
            {
                "revision": REVISION,
                "finished_jobs": len(results),
                "counts": dict(
                    Counter(v for r in results for v in r.get("outcomes", {}).values())
                ),
                "results": results,
                "unstarted_methods": [
                    n
                    for n in nodeids
                    if not any(n in row["nodeids"] for row in results)
                ],
            },
        )
        if not args.plan_only and not junit.exists() and not junit.is_symlink():
            aggregate = ET.Element("testsuites")
            for path in sorted(output.glob("job-*/junit.xml")):
                try:
                    native = ET.parse(path).getroot()
                    aggregate.extend(
                        list(native) if native.tag == "testsuites" else [native]
                    )
                except ET.ParseError:
                    pass  # The job stays failed; never invent replacement testcase records.
            junit.parent.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(aggregate).write(
                junit, encoding="utf-8", xml_declaration=True
            )


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt_on_termination)
    sys.exit(main())

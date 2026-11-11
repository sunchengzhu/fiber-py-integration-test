#!/usr/bin/env python3
"""Run ordinary LSP tests serially; reuse only explicitly qualified environment groups."""

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
import threading
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.lsp_parallel import validate_ports, validate_plan, wait_child, run_two_jobs
from scripts.lsp_ci_progress import DiskBudgetExceeded, disk_guard

SUITE = "test_cases/fiber/devnet/lsp"
REVISION = "76307312e8de518c9a32074e6d16867c04de4f86"
DEFAULT_REVISION = REVISION
INVOICE = SUITE + "/test_tenant_boundaries.py::TestTenantQueryIsolation::"
PAYMENT = SUITE + "/test_tenant_payment_queries.py::TestTenantPaymentQueries::"
GROUPS = {
    "subscription-auth": tuple(
        SUITE + "/test_signing_subscriptions.py::TestInvalidSubscriptions::" + name
        for name in (
            "test_missing_token_does_not_disrupt_subscription",
            "test_invalid_token_does_not_disrupt_subscription",
            "test_missing_subscription_write_does_not_disrupt_subscription",
            "test_missing_channel_read_does_not_disrupt_subscription",
        )
    ),
    "browser-auth": tuple(
        SUITE
        + "/test_browser_signing_subscriptions.py::TestBrowserSigningSubscriptions::"
        + name
        for name in (
            "test_browser_registration_token_receives_real_work",
            "test_browser_padded_token_and_bearer_inputs_are_compatible",
            "test_browser_missing_protocol_rejected_by_server",
            "test_browser_multiple_credentials_rejected_by_server",
            "test_browser_conflicting_credentials_rejected_by_server",
            "test_browser_empty_credential_rejected_by_server",
            "test_browser_invalid_encoding_rejected_by_server",
            "test_browser_invalid_biscuit_rejected_after_upgrade",
            "test_browser_missing_write_rejected_after_upgrade",
            "test_browser_missing_read_rejected_after_upgrade",
        )
    ),
    "subscription-filters": tuple(
        SUITE
        + "/test_signing_subscription_filters.py::TestSigningSubscriptionFilters::"
        + name
        for name in (
            "test_default_option_forms",
            "test_explicit_and_duplicate_channel_ids",
            "test_empty_channel_filter",
            "test_invalid_topic_and_options_field",
            "test_invalid_parameter_types",
            "test_invalid_hash_lengths_and_null_element",
            "test_invalid_hex_and_options_sequences",
            "test_unknown_channel_and_mixed_orders",
            "test_256_repeated_channel_ids",
            "test_257_repeated_channel_ids_rejected",
            "test_fixed_version_options_array_compatibility",
        )
    ),
    "subscription-streams": tuple(
        SUITE + "/test_signing_subscriptions.py::TestSigningSubscriptions::" + name
        for name in (
            "test_initial_subscription_preserves_pending_request",
            "test_next_request_arrives_on_original_subscription",
            "test_reconnect_replays_unsubmitted_request",
            "test_sdk_reconnects_without_restart",
            "test_reconnect_replays_only_current_request",
            "test_same_tenant_connections_receive_independent_updates",
            "test_unsubscribe_preserves_other_subscriptions",
            "test_cross_connection_and_unknown_unsubscribe_preserve_subscriptions",
        )
    ),
    "signing-retry": tuple(
        SUITE + "/test_channel_signing_retry.py::TestChannelSigningRetry::" + name
        for name in (
            "test_identical_retry_preserves_next_request",
            "test_conflicting_retry_preserves_original_receipt",
            "test_older_receipt_is_rejected_after_next_apply",
            "test_unsent_signature_recovers_after_disconnect",
            "test_applied_signature_recovers_after_http_timeout",
        )
    ),
    "signing-isolation": tuple(
        SUITE
        + "/test_channel_signing_isolation.py::TestChannelSigningIsolation::"
        + name
        for name in (
            "test_pending_tenant_does_not_block_another_tenant",
            "test_tenant_cannot_read_another_tenants_signing_request",
            "test_tenant_cannot_submit_another_tenants_valid_signature",
        )
    ),
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


def environment(
    bundle,
    directory=None,
    job=None,
    delivery=None,
    nolsp=None,
    *,
    port_map=None,
    worker_id=None,
):
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
        LSP_SIGNING_ENV_MODE="independent",
        LSP_SIGNING_KEEP_RUNTIME="0",
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
        if port_map is not None:
            env["LSP_REGRESSION_PORTS"] = json.dumps(validate_ports(port_map))
            env["LSP_REGRESSION_WORKER"] = str(worker_id)
        if any(
            n.split("::")[1]
            in (
                "TestChannelSigningRetry",
                "TestChannelSigningIsolation",
                "TestSigningSubscriptions",
                "TestInvalidSubscriptions",
                "TestBrowserSigningSubscriptions",
                "TestSigningSubscriptionFilters",
            )
            for n in job["nodeids"]
        ):
            env["LSP_SIGNING_KEEP_RUNTIME"] = "1"
        if job["group"]:
            variable = {
                "payment-query": "LSP_QUERY_ENV_MODE",
                "invoice-query": "LSP_INVOICE_QUERY_ENV_MODE",
                "invoice-cancel": "LSP_CANCEL_ENV_MODE",
                "signing-retry": "LSP_SIGNING_ENV_MODE",
                "signing-isolation": "LSP_SIGNING_ENV_MODE",
                "subscription-streams": "LSP_SIGNING_ENV_MODE",
                "subscription-auth": "LSP_SIGNING_ENV_MODE",
                "browser-auth": "LSP_SIGNING_ENV_MODE",
                "subscription-filters": "LSP_SIGNING_ENV_MODE",
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


def check_environment(ports=PORTS):
    free = shutil.disk_usage(ROOT).free
    if free < 8 * 2**30:
        raise RuntimeError(f"free disk below 8 GiB: {free} bytes")
    for port in ports:
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
    except PermissionError:
        # EPERM is not proof of exit, including transient orphan/zombie groups.
        return True


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
        except PermissionError:
            # Continue bounded probing; persistent denial must still fail below.
            pass
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


def run_job(
    job,
    directory,
    bundle,
    timeout,
    delivery=None,
    nolsp=None,
    *,
    port_map=None,
    cancel_event=None,
    worker_id=None,
    progress=False,
    guard=None,
    retain_runtime=False,
):
    directory.mkdir()
    env = environment(
        bundle, directory, job, delivery, nolsp, port_map=port_map, worker_id=worker_id
    )
    if progress:
        env["LSP_REGRESSION_PROGRESS"] = "1"
    if retain_runtime:
        env["LSP_REGRESSION_RETAIN"] = "1"

    def check_job_environment():
        return (
            check_environment()
            if port_map is None
            else check_environment(port_map.values())
        )

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
        "free_bytes_before": check_job_environment(),
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
            write_json(directory / "command.json", record)
            try:
                if progress or guard is not None:
                    from scripts.lsp_ci_progress import display_events

                    cursor = [0]

                    def tick():
                        if guard is not None:
                            guard()
                        if progress:
                            display_events(directory, job["nodeids"], cursor)

                    wait_child(
                        process,
                        timeout,
                        cancel_event or threading.Event(),
                        tick=tick,
                    )
                    if progress:
                        display_events(directory, job["nodeids"], cursor)
                elif cancel_event is None:
                    process.wait(timeout=timeout)
                else:
                    wait_child(process, timeout, cancel_event)
            except (
                subprocess.TimeoutExpired,
                KeyboardInterrupt,
                InterruptedError,
                DiskBudgetExceeded,
            ) as error:
                record["errors"].append(
                    type(error).__name__
                    + (
                        ": " + str(error)
                        if isinstance(error, DiskBudgetExceeded)
                        else ""
                    )
                )
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
            record["free_bytes_after"] = check_job_environment()
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
    global REVISION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "selectors",
        nargs="*",
        help="ordinary LSP paths/nodeids; default: whole ordinary directory",
    )
    parser.add_argument(
        "--only-shared-groups",
        action="store_true",
        help="select exactly the qualified shared groups",
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
    parser.add_argument("--bundle", type=Path)
    parser.add_argument(
        "--revision", default=DEFAULT_REVISION, help="Exact Fiber commit SHA"
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Stream native per-case lifecycle events",
    )
    parser.add_argument(
        "--disk-budget-gib",
        type=float,
        help="Optional serial batch growth limit, preserving 8GiB free",
    )
    parser.add_argument("--delivery-node", type=Path)
    parser.add_argument("--nolsp-fnn", type=Path)
    parser.add_argument("--job-timeout", type=float, default=1800)
    parser.add_argument(
        "--batch-timeout",
        type=float,
        help="Optional serial batch deadline; reserves native cleanup after interruption",
    )
    parser.add_argument(
        "--retain-runtime",
        action="store_true",
        help="CI-only: retain stopped stores for artifact export",
    )
    parser.add_argument(
        "--junitxml",
        type=Path,
        help="fresh aggregate native JUnit path; default: <output>/junit.xml",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=(1, 2),
        default=1,
        help="default 1; 2 only accepts complete browser+filter pilot groups",
    )
    args = parser.parse_args()
    if args.batch_timeout is not None and (
        not math.isfinite(args.batch_timeout)
        or args.batch_timeout <= 0
        or args.workers != 1
    ):
        parser.error("--batch-timeout requires a positive finite value and workers=1")
    if args.disk_budget_gib is not None and (
        not math.isfinite(args.disk_budget_gib)
        or args.disk_budget_gib <= 0
        or args.workers != 1
    ):
        parser.error("--disk-budget-gib requires a positive finite value and workers=1")
    if len(args.revision) != 40 or any(
        c not in "0123456789abcdef" for c in args.revision
    ):
        parser.error("--revision must be a full lowercase commit SHA")
    if args.workers == 2 and args.revision != DEFAULT_REVISION:
        parser.error(
            "2-worker pilot is qualified only for the default 76307312 revision"
        )
    if args.workers == 2 and args.retain_runtime:
        parser.error("--retain-runtime currently requires serial workers=1")
    REVISION = args.revision
    args.bundle = args.bundle or ROOT / "download/fiber" / f"pr-1623-{REVISION[:7]}"
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
    batch_started = time.monotonic()
    try:
        if junit.exists() or junit.is_symlink():
            raise ValueError(f"refusing to replace existing JUnit: {junit}")
        bundle = args.bundle.resolve()
        env = environment(bundle)
        nodeids = collect(selectors, output, env)
        jobs = build_plan(nodeids, args.independent)
        if args.workers == 2:
            if args.progress:
                raise ValueError("live progress currently requires serial workers=1")
            validate_plan(jobs, GROUPS)
        write_json(
            output / "plan.json",
            {
                "revision": REVISION,
                "bundle": str(bundle),
                "nodeids": nodeids,
                "jobs": jobs,
                "workers": args.workers,
            },
        )
        print(
            f"{len(nodeids)} methods / {len(jobs)} {'serial' if args.workers == 1 else '2-worker parallel'} jobs; evidence: {output}",
            flush=True,
        )
        if args.plan_only:
            return 0
        manifest = bundle / "build.json"
        if json.loads(manifest.read_text())["revision"] != REVISION:
            raise ValueError("bundle does not match the selected revision")
        shutil.copy2(manifest, output / "build.json")
        if any(is_delivery(n) for n in nodeids) and not args.delivery_node:
            raise ValueError("--delivery-node is required for Delivery methods")
        if (
            any("/test_lsp_feature_off.py::" in n for n in nodeids)
            and not args.nolsp_fnn
        ):
            raise ValueError("--nolsp-fnn is required for feature-off methods")
        if args.workers == 2:
            run_two_jobs(
                jobs, output, bundle, args.job_timeout, run_job, results, write_json
            )
        else:
            guard = (
                disk_guard(ROOT, args.disk_budget_gib)
                if args.disk_budget_gib is not None
                else None
            )
            for index, job in enumerate(jobs):
                remaining = args.job_timeout
                if args.batch_timeout is not None:
                    remaining = min(
                        remaining,
                        args.batch_timeout - (time.monotonic() - batch_started),
                    )
                    if remaining <= 0:
                        raise RuntimeError(
                            "serial batch deadline exhausted; remaining methods not started"
                        )
                print(
                    f"[LSP group {index + 1}/{len(jobs)}] {job['group'] or job['nodeids'][0]}",
                    flush=True,
                )
                options = {}
                if args.progress:
                    options["progress"] = True
                if guard is not None:
                    options["guard"] = guard
                if args.retain_runtime:
                    options["retain_runtime"] = True
                row = run_job(
                    job,
                    output / f"job-{index:03d}",
                    bundle,
                    remaining,
                    args.delivery_node,
                    args.nolsp_fnn,
                    **options,
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
            r.get("exit_code") != 0
            or r.get("errors")
            or set(r["outcomes"].values()) != {"passed"}
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
                "workers": args.workers,
                "duration_seconds": time.monotonic() - batch_started,
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

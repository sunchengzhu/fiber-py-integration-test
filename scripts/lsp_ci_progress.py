"""Optional lifecycle telemetry. Native JUnit remains the result authority."""

import json
import os
from pathlib import Path
import shutil
import time


class DiskBudgetExceeded(RuntimeError):
    pass


def disk_guard(root, budget_gib, reserve_gib=None):
    initial = shutil.disk_usage(root).free
    budget = budget_gib * 2**30
    reserve = budget if reserve_gib is None else reserve_gib * 2**30
    if initial < 8 * 2**30 + reserve:
        raise DiskBudgetExceeded("disk admission needs 8GiB floor plus batch reserve")

    def check():
        free = shutil.disk_usage(root).free
        if free < 8 * 2**30 or initial - free > budget:
            raise DiskBudgetExceeded(
                f"disk floor/growth budget exhausted: initial={initial}, free={free}, budget={budget}"
            )

    return check


def emit(event, nodeid, **fields):
    if os.environ.get("LSP_REGRESSION_PROGRESS") != "1":
        return
    try:
        path = Path(os.environ["LSP_REGRESSION_CASE"]) / "events.jsonl"
        row = {"event": event, "nodeid": nodeid, "utc": time.time(), **fields}
        with path.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
    except (OSError, KeyError) as error:
        # Telemetry must not interrupt pytest's own fixture teardown.
        print(f"[LSP progress unavailable] {error!r}", flush=True)


def display_events(directory, nodeids, cursor):
    path = directory / "events.jsonl"
    if not path.exists():
        return
    try:
        with path.open() as stream:
            stream.seek(cursor[0])
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line or not line.endswith("\n"):
                    cursor[0] = offset
                    break
                cursor[0] = stream.tell()
                try:
                    row = json.loads(line)
                    position = nodeids.index(row["nodeid"]) + 1
                except (ValueError, KeyError, TypeError):
                    continue
                label = {
                    "start": "▶ 开始",
                    "finish": "■ 收尾完成",
                    "phase": "阶段",
                }.get(row.get("event"))
                if label:
                    phase = " ".join(
                        str(row.get(k, "")) for k in ("phase", "outcome")
                    ).strip()
                    print(
                        f"[LSP {position}/{len(nodeids)}] {label} {phase} {row['nodeid']}",
                        flush=True,
                    )
                    if row.get("detail"):
                        print(
                            "[LSP detail] "
                            + str(row["detail"]).replace("\n", "\n[LSP detail] "),
                            flush=True,
                        )
    except OSError as error:
        print(f"[LSP progress unavailable] {error!r}", flush=True)

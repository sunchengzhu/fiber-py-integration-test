#!/usr/bin/env python3
"""Manual CI planning and reporting over native LSP execution evidence."""

import argparse
import ast
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import run_lsp_regression as runner

SUITE = runner.SUITE
CATEGORIES = {
    "query": (
        "查询与租户隔离",
        ("test_tenant_boundaries.py", "test_tenant_payment_queries.py"),
    ),
    "payment": (
        "付款恢复与发票取消",
        (
            "test_hosted_outbound_payment.py",
            "test_payment_authorization_recovery.py",
            "test_delayed_payment_recovery.py",
            "test_hosted_invoice_cancellation.py",
        ),
    ),
    "subscription": (
        "订阅与浏览器鉴权",
        (
            "test_signing_subscriptions.py",
            "test_browser_signing_subscriptions.py",
            "test_signing_subscription_filters.py",
        ),
    ),
    "signing": (
        "签名恢复、重试与隔离",
        (
            "test_channel_signing_recovery.py",
            "test_channel_signing_retry.py",
            "test_channel_signing_isolation.py",
        ),
    ),
    "deadline": ("签名超时与关闭", ("test_channel_signing_deadline.py",)),
    "watchtower": ("Watchtower 结算", ("test_watchtower_settlement.py",)),
    "delivery": (
        "Delivery 接纳与重启",
        ("test_delivery_acceptance.py", "test_delivery_fnn_restart.py"),
    ),
    "feature-off": ("关闭 LSP feature", ("test_lsp_feature_off.py",)),
}
LABELS = {
    "passed": "通过",
    "failure": "失败",
    "error": "错误",
    "skipped": "跳过",
    "not_run": "未执行",
    "incomplete": "执行中断 / 结果不完整",
}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def full_sha(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("resolved commit must be a full lowercase SHA")
    return value


def input_fingerprints():
    paths = {
        p
        for pattern in (
            "framework/**/*.py",
            "test_cases/fiber/devnet/lsp/*.py",
            "test_cases/fiber/devnet/lsp/*.rs",
            "scripts/lsp*.py",
        )
        for p in ROOT.glob(pattern)
        if p.is_file()
    }
    paths.update(
        ROOT / p
        for p in (
            "scripts/run_lsp_regression.py",
            "pytest.ini",
            "requirements.txt",
            "test_cases/conftest.py",
            "source/fiber/dev_config_3.yml.j2",
            "source/fiber/data.2026.0929.tar.gz",
        )
    )
    return {
        str(p.relative_to(ROOT)): sha(p) if p.is_file() else None for p in sorted(paths)
    }


def resolve_commit(value, api=None):
    value = value.strip()
    if value and not re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
        raise ValueError(
            "commit must be 7–40 hexadecimal characters, or empty for PR head"
        )
    if api is None:

        def api(path):
            return json.loads(
                subprocess.check_output(["gh", "api", path], text=True, timeout=30)
            )

    if value:
        result = api("repos/nervosnetwork/fiber/commits/" + value.lower())
        revision = full_sha(result["sha"])
        if not revision.startswith(value.lower()):
            raise ValueError("GitHub resolved a different commit")
    else:
        result = api("repos/nervosnetwork/fiber/pulls/1623")
        revision = full_sha(result["head"]["sha"])
    return revision


def metadata(nodeid):
    filename, cls, method = nodeid.split("::")
    source = (ROOT / filename).read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == method.split("[")[0]:
                    prefix = source.splitlines()[max(0, fn.lineno - 7) : fn.lineno - 1]
                    ids = re.findall(r"TEST-MAP:\s*([^\n]+)", "\n".join(prefix))
                    description = (ast.get_docstring(fn) or method).splitlines()[0]
                    return {"case": ", ".join(ids), "description": description[:180]}
    return {"case": "", "description": method}


def partition(nodeids):
    runner.build_plan(nodeids)  # Validate duplicates, suite and Delivery qualification.
    buckets = []
    assigned = []
    for key, (label, filenames) in CATEGORIES.items():
        selected = [n for n in nodeids if Path(n.split("::")[0]).name in filenames]
        if selected:
            runner.build_plan(selected)  # No shared group or qualification is split.
            buckets.append(
                {"id": key, "label": label, "nodeids": selected, "count": len(selected)}
            )
            assigned.extend(selected)
    if Counter(assigned) != Counter(nodeids):
        raise ValueError(
            "unassigned/duplicate CI cases: update the CI grouping before running"
        )
    return buckets


def plan(revision, output):
    revision = full_sha(revision)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    native = output / "collection"
    command = [
        sys.executable,
        str(ROOT / "scripts/run_lsp_regression.py"),
        "--revision",
        revision,
        "--plan-only",
        "--output",
        str(native),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    nodeids = read(native / "plan.json")["nodeids"]
    buckets = partition(nodeids)
    result = {
        "revision": revision,
        "integration_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "buckets": buckets,
        "cases": [{"nodeid": n, **metadata(n)} for n in nodeids],
    }
    write(output / "plan.json", result)
    matrix = {
        "include": [
            {"id": b["id"], "label": b["label"], "count": b["count"]} for b in buckets
        ]
    }
    print(json.dumps(matrix, ensure_ascii=False))
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("matrix=" + json.dumps(matrix, ensure_ascii=False) + "\n")
    return result


def run_bucket(plan_path, bucket_id, output):
    planned = read(plan_path)
    bucket = next(b for b in planned["buckets"] if b["id"] == bucket_id)
    revision = full_sha(planned["revision"])
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if actual != planned["integration_commit"]:
        raise ValueError("test source differs from the collected plan")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    inputs_before = input_fingerprints()
    write(
        output / "job.json",
        {
            "id": bucket_id,
            "revision": revision,
            "integration_commit": actual,
            "started_at": time.time(),
            "free_bytes_before": shutil.disk_usage(ROOT).free,
            "nodeids": bucket["nodeids"],
            "test_inputs": inputs_before,
        },
    )
    command = [
        sys.executable,
        str(ROOT / "scripts/run_lsp_regression.py"),
        "--revision",
        revision,
        "--workers",
        "1",
        "--progress",
        "--retain-runtime",
        "--disk-budget-gib",
        "2",
        "--batch-timeout",
        "9000",
        "--output",
        str(output / "entry"),
        "--delivery-node",
        str(ROOT / "download/fiber" / f"delivery-{revision[:7]}/lsp-delivery-node"),
        "--nolsp-fnn",
        str(ROOT / "download/fiber" / f"nolsp-{revision[:7]}/fnn"),
        *bucket["nodeids"],
    ]
    completed = subprocess.run(command, cwd=ROOT)
    value = read(output / "job.json")
    inputs_after = input_fingerprints()
    drift = sorted(
        p
        for p in inputs_before.keys() | inputs_after.keys()
        if inputs_before.get(p) != inputs_after.get(p)
    )
    value.update(exit_code=completed.returncode, finished_at=time.time())
    value.update(inputs_unchanged=not drift, source_drift=drift)
    write(output / "job.json", value)
    return completed.returncode or (2 if drift else 0)


def collect_results(bucket_dir, destination):
    bucket_dir, destination = Path(bucket_dir), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for path in bucket_dir.rglob("*"):
        if path.is_file() and path.name in {
            "plan.json",
            "summary.json",
            "command.json",
            "result.json",
            "junit.xml",
            "job.json",
            "events.jsonl",
            "batch-error.json",
            "runtime-retention.json",
        }:
            target = destination / path.relative_to(bucket_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def retain_runtime(bucket_dir):
    bucket_dir = Path(bucket_dir)
    bucket_dir.mkdir(parents=True, exist_ok=True)
    sources = set()
    unavailable = []
    initial = (
        read(bucket_dir / "job.json").get("free_bytes_before")
        if (bucket_dir / "job.json").is_file()
        else None
    )

    def check_space():
        free = shutil.disk_usage(ROOT).free
        if free < 8 * 2**30 or (initial is not None and initial - free > 2 * 2**30):
            raise RuntimeError(
                "runtime evidence export exceeded disk floor/batch budget"
            )

    for path in (bucket_dir / "entry").glob("job-*/before-teardown/*/runtime.json"):
        for _, source in read(path)["sources"]:
            resolved = Path(source).resolve()
            if not resolved.is_relative_to(ROOT / "tmp") or resolved == ROOT / "tmp":
                raise ValueError(f"refusing unrelated runtime: {source}")
            if resolved.is_dir():
                sources.add(resolved)
            else:
                unavailable.append(str(resolved))
    for path in (bucket_dir / "entry").glob("job-*/retained-paths.jsonl"):
        for line in path.read_text().splitlines():
            source = Path(json.loads(line)["path"]).resolve()
            if source == ROOT / "tmp" or not source.is_relative_to(ROOT / "tmp"):
                raise ValueError("retained path is outside the job's runtime")
            if source.is_dir():
                sources.add(source)
            else:
                unavailable.append(str(source))
    sources = {
        p
        for p in sources
        if not any(p != other and p.is_relative_to(other) for other in sources)
    }
    manifest = []
    # Snapshot only after native/outer process cleanup. Never delete originals.
    for path in (bucket_dir / "entry").glob("job-*/command.json"):
        pid = read(path).get("pid")
        if pid and runner.group_exists(pid):
            raise RuntimeError(
                f"owned process group still exists; runtime not frozen: {pid}"
            )
    with tarfile.open(bucket_dir / "runtime.tar.gz", "w:gz") as archive:
        for source in sorted(sources):
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"unexpected runtime symlink: {path}")
                if path.is_file():
                    check_space()
                    relative = str(path.relative_to(ROOT))
                    archive.add(path, arcname=relative, recursive=False)
                    manifest.append({"path": relative, "sha256": sha(path)})
    write(bucket_dir / "runtime-manifest.json", manifest)
    expected = {item["path"]: item["sha256"] for item in manifest}
    with tarfile.open(bucket_dir / "runtime.tar.gz", "r:gz") as archive:
        for item in archive:
            check_space()
            with archive.extractfile(item) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected.pop(
                    item.name
                ):
                    raise RuntimeError("runtime archive differs from original file")
    if expected:
        raise RuntimeError("runtime archive is incomplete")
    write(
        bucket_dir / "runtime-retention.json",
        {
            "sources": list(map(str, sorted(sources))),
            "unavailable": sorted(set(unavailable)),
            "archive_sha256": sha(bucket_dir / "runtime.tar.gz"),
            "files": len(manifest),
            "originals_deleted": False,
        },
    )
    if unavailable:
        raise RuntimeError("some runtime sources were not retained; upload fallback")


def results(plan_path, source):
    planned = read(plan_path)
    rows = {
        c["nodeid"]: {**c, "status": "not_run", "detail": "", "evidence": ""}
        for c in planned["cases"]
    }
    problems, observed = [], set()
    root = Path(source)
    aggregate = ET.Element("testsuites")
    for bucket in planned["buckets"]:
        directory = root / bucket["id"]
        for nodeid in bucket["nodeids"]:
            rows[nodeid]["bucket"] = bucket["label"]
        if not (directory / "job.json").is_file():
            problems.append(
                f"{bucket['label']}: 未取得任务记录，可能未启动或产物未上传"
            )
            continue
        try:
            job = read(directory / "job.json")
            if not isinstance(job, dict):
                raise ValueError("job record must be an object")
        except (OSError, ValueError) as error:
            problems.append(f"{bucket['label']}: 任务记录无效 {error}")
            continue
        if (
            job.get("revision") != planned["revision"]
            or job.get("integration_commit") != planned["integration_commit"]
            or job.get("nodeids") != bucket["nodeids"]
        ):
            problems.append(
                f"{bucket['label']}: 结果的版本或选择列表不匹配计划，拒绝计为通过"
            )
            continue
        if job.get("source_drift"):
            problems.append(f"{bucket['label']}: 测试源码在执行期间变化，结果不予确认")
            for n in bucket["nodeids"]:
                rows[n]["status"] = "incomplete"
            continue
        summary_path = directory / "entry/summary.json"
        if not summary_path.is_file():
            problems.append(f"{bucket['label']}: 运行中断，缺少最终调度汇总")
        else:
            try:
                summary = read(summary_path)
                if (
                    summary["revision"] != planned["revision"]
                    or summary["workers"] != 1
                ):
                    raise ValueError("summary identity mismatch")
                if summary.get("unstarted_methods"):
                    problems.append(f"{bucket['label']}: 有未启动的用例")
            except (OSError, ValueError, KeyError, TypeError) as error:
                problems.append(f"{bucket['label']}: 最终调度汇总无效 {error}")
        started = set()
        for event_path in directory.glob("entry/job-*/events.jsonl"):
            for line in event_path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    problems.append(f"{bucket['label']}: 进度事件不是对象")
                    continue
                n = event.get("nodeid")
                if n not in bucket["nodeids"]:
                    problems.append(f"{bucket['label']}: 进度事件包含计划外用例")
                    continue
                started.add(n)
                rows[n]["status"] = "incomplete"  # Telemetry alone never proves a pass.
        for command_path in sorted(directory.glob("entry/job-*/command.json")):
            try:
                record = read(command_path)
                selected = record["nodeids"]
                if (
                    not isinstance(selected, list)
                    or not selected
                    or not all(isinstance(n, str) for n in selected)
                    or len(selected) != len(set(selected))
                ):
                    raise ValueError("invalid child selector list")
            except (OSError, ValueError, KeyError, TypeError) as error:
                problems.append(f"{bucket['label']}: 子任务记录无效 {error}")
                continue
            if any(n not in bucket["nodeids"] or n in observed for n in selected):
                problems.append(
                    f"{bucket['label']}: 原生选择列表越界或重复，结果不予确认"
                )
                for n in selected:
                    if n in rows:
                        rows[n]["status"] = "incomplete"
                continue
            observed.update(selected)
            child = command_path.parent
            for n in selected:
                rows[n]["evidence"] = str(child.relative_to(root))
            try:
                final = read(child / "result.json")
                if not isinstance(final, dict):
                    raise ValueError("native result must be an object")
                if final.get("nodeids") != selected or final.get("junit_sha256") != sha(
                    child / "junit.xml"
                ):
                    raise ValueError("native result selection/checksum mismatch")
                env = record.get("environment", {})
                if env.get("LSP_TEST_REVISION") != planned["revision"]:
                    raise ValueError("native command revision mismatch")
                status = runner.native_outcomes(child / "junit.xml", selected)
                native = ET.parse(child / "junit.xml").getroot()
                aggregate.extend(
                    list(native) if native.tag == "testsuites" else [native]
                )
                for n, outcome in status.items():
                    rows[n]["status"] = (
                        outcome
                        if outcome != "not_run"
                        else ("incomplete" if n in started else "not_run")
                    )
                for testcase in native.iter("testcase"):
                    for n in selected:
                        if testcase.get("name") == n.split("::")[-1] and any(
                            testcase.find(t) is not None
                            for t in ("failure", "error", "skipped")
                        ):
                            rows[n]["detail"] = "\n".join(
                                (c.get("message", "") + "\n" + (c.text or ""))
                                for c in testcase
                                if c.tag in ("failure", "error", "skipped")
                            )[:12000]
            except (OSError, ValueError, ET.ParseError) as error:
                problems.append(
                    f"{bucket['label']} / {child.name}: 原生 JUnit 无效: {error}"
                )
                for n in selected:
                    rows[n]["status"] = "incomplete"
            result_file = child / "result.json"
            if result_file.is_file():
                try:
                    final = read(result_file)
                    if not isinstance(final, dict):
                        raise ValueError("native result must be an object")
                    if final.get("errors") or final.get("exit_code") not in (0, 1):
                        problems.append(
                            f"{bucket['label']} / {child.name}: 调度或资源异常 {final.get('errors')}"
                        )
                except (OSError, ValueError) as error:
                    problems.append(
                        f"{bucket['label']} / {child.name}: 资源检查记录无效 {error}"
                    )
            else:
                problems.append(
                    f"{bucket['label']} / {child.name}: 缺少最终资源检查记录"
                )
        if job.get("exit_code") != 0:
            problems.append(
                f"{bucket['label']}: 任务退出码 {job.get('exit_code', '未记录')}"
            )
        retention = directory / "runtime-retention.json"
        try:
            state = read(retention)
            if (
                state.get("unavailable")
                or state.get("originals_deleted") is not False
                or not state.get("archive_sha256")
                or not state.get("files")
            ):
                raise ValueError("原始状态归档不完整")
        except (OSError, ValueError, AttributeError) as error:
            problems.append(
                f"{bucket['label']}: 最终原始状态归档未确认，检查 fallback 产物: {error}"
            )
    counts = Counter(r["status"] for r in rows.values())
    return planned, list(rows.values()), problems, aggregate, counts


def render_report(plan_path, source, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    try:
        planned, rows, problems, aggregate, counts = results(plan_path, source)
    except (OSError, ValueError, KeyError, ET.ParseError) as error:
        planned, rows, problems, aggregate, counts = (
            {"revision": "未知", "integration_commit": "未知"},
            [],
            [f"无法可靠生成报告: {error}"],
            ET.Element("testsuites"),
            Counter(),
        )
    stages = {
        key: os.environ.get("LSP_CI_" + key.upper() + "_RESULT")
        for key in ("plan", "build", "tests")
    }
    for stage, status in stages.items():
        if status is not None and status != "success":
            problems.append(
                f"CI {stage} 阶段: {status}（包括断言、基础设施或上传失败）"
            )
    bad = bool(problems) or not rows or set(counts) != {"passed"}
    write(
        output / "report.json",
        {
            "revision": planned["revision"],
            "integration_commit": planned["integration_commit"],
            "counts": counts,
            "problems": problems,
            "cases": rows,
            "complete": not bad,
            "stages": stages,
        },
    )
    ET.ElementTree(aggregate).write(
        output / "junit.xml", encoding="utf-8", xml_declaration=True
    )
    esc = html.escape
    cards = "".join(
        f'<div class="card {key}"><b>{counts[key]}</b>{label}</div>'
        for key, label in LABELS.items()
    )
    table = []
    for row in rows:
        status = row["status"]
        table.append(
            f'<tr data-status="{status}"><td class="{status}">{LABELS[status]}</td><td>{esc(row["bucket"])}</td><td><b>{esc(row["case"])}</b> {esc(row["description"])}<details><summary>定位与证据</summary><code>{esc(row["nodeid"])}</code><p>组证据 artifact 内：<code>{esc(row["evidence"])}</code></p><pre>{esc(row["detail"])}</pre></details></td></tr>'
        )
    issues = "".join("<li>" + esc(p) + "</li>" for p in problems)
    options = '<option value="all">所有状态</option>' + "".join(
        f'<option value="{k}">{v}</option>' for k, v in LABELS.items()
    )
    planned_count = str(len(rows)) if rows else "未取得"
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Fiber LSP 测试结果</title><style>
body{{font:15px system-ui,sans-serif;background:#f4f6fa;color:#182639;max-width:1200px;margin:30px auto;padding:0 22px}}h1{{font-size:27px}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:white;border:1px solid #d8e0ec;border-top:4px solid currentColor;border-radius:8px;padding:14px 22px;min-width:100px}}.card b{{display:block;font-size:30px}}.passed{{color:#17683b}}.failure,.error{{color:#ad2525}}.skipped{{color:#8e6200}}.not_run{{color:#657184}}.incomplete{{color:#7143a5}}table{{border-collapse:collapse;width:100%;background:white;margin-top:18px}}th,td{{border:1px solid #d8e0ec;padding:12px;text-align:left;vertical-align:top}}th{{background:#e9eff7}}td:first-child{{min-width:95px;font-weight:650}}input,select{{padding:9px;border:1px solid #aebbd0;border-radius:5px;margin:18px 8px 0 0}}input{{width:48%}}code,pre{{overflow-wrap:anywhere;white-space:pre-wrap;font-size:12px}}.notice{{background:#fff5db;padding:12px;border-radius:6px}}summary{{cursor:pointer;margin-top:8px;color:#365c8d}}small{{color:#526379}}</style>
<h1>Fiber LSP 测试结果</h1><p>产品提交 <code>{esc(planned["revision"])}</code><br>测试提交 <code>{esc(planned["integration_commit"])}</code></p><p>计划 {planned_count} 条 · 原生报告 {sum(counts[k] for k in ('passed','failure','error','skipped'))} 条</p><progress aria-label="原生报告进度" style="width:100%;height:20px;margin-bottom:16px" max="{max(1,len(rows))}" value="{sum(counts[k] for k in ('passed','failure','error','skipped'))}"></progress><div class="cards">{cards}</div>
<p class="notice">这是执行结束后的快照。运行中请看 Actions 测试组状态及日志中的 [LSP] 逐条进度。进度事件不作为通过依据；未启动与已开始但缺少原生结果分别展示。详细日志和原始状态位于本轮各组证据 artifact。</p><ul>{issues}</ul><select id="status">{options}</select><input id="search" placeholder="搜索用例、场景 ID 或测试组" aria-label="搜索测试"><table><thead><tr><th>状态</th><th>测试组</th><th>用例</th></tr></thead><tbody>{''.join(table)}</tbody></table><small>通过/失败/错误/跳过来自原生 JUnit；缺失、重复或不匹配结果不会补成通过。历史失败不会自动豁免。</small><script>
function filter(){{const s=document.getElementById('status').value,q=document.getElementById('search').value.toLowerCase();for(const r of document.querySelectorAll('tbody tr'))r.hidden=(s!=='all'&&r.dataset.status!==s)||!r.textContent.toLowerCase().includes(q)}}document.getElementById('status').onchange=filter;document.getElementById('search').oninput=filter;
</script></html>"""
    (output / "index.html").write_text(page)
    summary = (
        f"## Fiber LSP 测试结果\n\n产品 `{planned['revision']}`；测试 `{planned['integration_commit']}`\n\n| 计划 | "
        + " | ".join(LABELS.values())
        + " |\n| --- | "
        + " | ".join("---:" for _ in LABELS)
        + " |\n| "
        + str(len(rows))
        + " | "
        + " | ".join(str(counts[k]) for k in LABELS)
        + " |\n\n完整筛选表见 **lsp-report** artifact 内 `index.html`（下载后打开）；各组日志/数据库见 **lsp-evidence-组名**。\n\n"
    )
    unfinished = [r for r in rows if r["status"] != "passed"]
    if unfinished:
        summary += "| 状态 | 测试组 | 用例 |\n| --- | --- | --- |\n" + "".join(
            f"| {LABELS[r['status']]} | {r['bucket']} | `{r['nodeid']}` |\n"
            for r in unfinished
        )
    if problems:
        summary += (
            "\n### 调度 / 证据问题\n\n" + "\n".join("- " + p for p in problems) + "\n"
        )
    (output / "summary.md").write_text(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
            stream.write(summary)
    print(summary)
    return int(bad)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("resolve")
    p.add_argument("--commit", default="")
    p = sub.add_parser("plan")
    p.add_argument("--revision", required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("collect")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("retain")
    p.add_argument("--source", type=Path, required=True)
    p = sub.add_parser("report")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "resolve":
        revision = resolve_commit(args.commit)
        print(revision)
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
                stream.write("revision=" + revision + "\n")
                stream.write("short_revision=" + revision[:7] + "\n")
    elif args.command == "plan":
        plan(args.revision, args.output)
    elif args.command == "run":
        return run_bucket(args.plan, args.bucket, args.output)
    elif args.command == "collect":
        collect_results(args.source, args.output)
    elif args.command == "retain":
        retain_runtime(args.source)
    else:
        return render_report(args.plan, args.source, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

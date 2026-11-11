"""Isolate batch runtimes and copy raw logs before native fixture teardown."""

import json
import os
from pathlib import Path
import shutil

import pytest


def pytest_collection_modifyitems(items):
    expected = json.loads(os.environ["LSP_REGRESSION_SELECTORS"])
    if [item.nodeid for item in items] != expected:
        raise ValueError("native selection/order differs from the serial job plan")
    for item in items:
        item.cls.tmp_path_name = os.environ["LSP_REGRESSION_RUNTIME"]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    case = getattr(item, "instance", None)
    if case is not None and (
        getattr(case, "_node_mode", "independent") == "shared"
        or getattr(case, "_node_keep", False)
    ):
        if report.when == "call":
            case._node_case_passed = report.passed
        if report.failed or report.skipped:
            type(case)._node_failed = True


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    errors, sources = [], []
    instance = None
    try:
        instance = getattr(item, "instance", None)
        node = getattr(item.cls, "node", None)
        if node is not None:
            sources.append(("ckb", Path(node.ckb_dir)))
        for index, fiber in enumerate(getattr(instance, "fibers", [])):
            sources.append((f"fiber-{index}", Path(fiber.tmp_path)))
        directory = (
            Path(os.environ["LSP_REGRESSION_CASE"]) / "before-teardown" / item.name
        )
        directory.mkdir(parents=True, exist_ok=False)
        for label, source in sources:
            for relative in (
                "node.log",
                "config.yml",
                "ckb.toml",
                "ckb-miner.toml",
                "dev.toml",
                "data/logs/run.log",
                "ckb.miner.log",
            ):
                path = source / relative
                if path.is_file():
                    try:
                        target = directory / label / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
                    except OSError as error:
                        errors.append(f"{path}: {error!r}")
        (directory / "runtime.json").write_text(
            json.dumps(
                {
                    "sources": [(label, str(path)) for label, path in sources],
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
    except Exception as error:
        errors.append(repr(error))
    # Mark the owner before fixture/class teardown, including on the last case.
    if (
        errors
        and instance is not None
        and (
            getattr(instance, "_node_mode", "independent") == "shared"
            or getattr(instance, "_node_keep", False)
        )
    ):
        type(instance)._node_failed = True
    # Evidence failures must never prevent the fixture's own resource cleanup.
    yield
    if errors:
        raise RuntimeError(f"raw evidence copy failed: {errors}")

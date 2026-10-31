import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-lsp-refund-nightly",
        action="store_true",
        default=False,
        help="Opt in to controlled LSP refund VM nightly tests",
    )
    parser.addoption(
        "--run-remote",
        action="store_true",
        default=False,
        help="Run tests that require access to remote authenticated Fiber nodes",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-lsp-refund-nightly"):
        return

    selected = []
    deselected = []
    for item in items:
        if item.get_closest_marker("manual_nightly") is not None:
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and hasattr(item, "_testcase"):
        item._testcase.did_pass = report.passed

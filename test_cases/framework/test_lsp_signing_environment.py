"""Node reuse must keep per-method signing material fresh and preserve failures."""

import json
from pathlib import Path
import signal
import time
from types import SimpleNamespace

import pytest

import test_cases.fiber.devnet.lsp._signing_environment as env
import test_cases.fiber.devnet.lsp._lsp_test as lsp
import test_cases.fiber.devnet.lsp._hosted_tenant_fixture as hosted
from scripts import lsp_regression_runtime as runtime


def test_signing_sdk_directory_is_fresh_only_in_shared_mode(tmp_path):
    obj = SimpleNamespace(
        _node_mode="independent", fiber1=SimpleNamespace(tmp_path=str(tmp_path))
    )
    assert env.SigningEnvironment._sdk_directory(obj, "A") == tmp_path / "sdk-A"
    obj._node_mode = "shared"
    a = env.SigningEnvironment._sdk_directory(obj, "A")
    b = env.SigningEnvironment._sdk_directory(obj, "A")
    assert a != b and a.parent == b.parent == tmp_path
    assert a.name.startswith("sdk-A-")


def test_shared_node_binding_does_not_copy_case_or_signer_state():
    cls = type(
        "TestInvalidSubscriptions",
        (env.SigningEnvironment,),
        {
            "_node_mode": "shared",
            "_node_keep": True,
            "_node_failed": False,
            "_node_owner": None,
            "_node_cases": [],
            "node": SimpleNamespace(
                getClient=lambda: SimpleNamespace(get_tip_block_number=lambda: 123)
            ),
        },
    )
    calls = []

    def prepare(owner, method):
        calls.append(method.__name__)
        for field in ("fibers", "fiber1", "fiber2", "udtContract", "ws_url"):
            setattr(owner, field, object())
        owner.payments = {"old": "do-not-copy"}

    first, second = cls(), cls()
    for case, method in zip((first, second), env.SIGNING_METHODS[cls.__name__][:2]):
        case._check_shared_signing_history = lambda: None
        assert case._bind_shared_signing_nodes(
            SimpleNamespace(__name__=method), prepare
        )
    assert len(calls) == 1 and first.fiber1 is second.fiber1
    assert first.tenants == second.tenants == [] and first.tenants is not second.tenants
    assert not hasattr(second, "payments") and not second._node_case_passed
    cls._node_failed = True
    with pytest.raises(AssertionError, match="invalidated"):
        second._bind_shared_signing_nodes(
            SimpleNamespace(__name__=env.SIGNING_METHODS[cls.__name__][0]), prepare
        )
    assert len(calls) == 1


def test_nested_resource_cap_never_extends_parent_deadline():
    previous = signal.getsignal(signal.SIGALRM)

    def parent(*_):
        raise TimeoutError("parent deadline")

    signal.signal(signal.SIGALRM, parent)
    signal.setitimer(signal.ITIMER_REAL, 0.05)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            with env._cleanup_cap(10):
                time.sleep(0.2)
        assert time.monotonic() - started < 0.2
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def cleanup_fixture(tmp_path, monkeypatch):
    calls = []
    source = tmp_path / "original"
    source.mkdir()
    (source / "node.log").write_text("raw bytes")
    sdk = SimpleNamespace(pid=100, poll=lambda: 0)
    fnn = SimpleNamespace(pid=101, poll=lambda: 0)
    fiber = SimpleNamespace(tmp_path=str(source), process=fnn)
    case = SimpleNamespace(
        _cleanups=[],
        tenants=[
            {
                "agent": sdk,
                "gate": SimpleNamespace(close=lambda: calls.append("gate")),
                "subscription_proxy": SimpleNamespace(
                    close=lambda: calls.append("proxy")
                ),
            }
        ],
        observers=[SimpleNamespace(close=lambda: calls.append("observer"))],
    )
    owner = SimpleNamespace(_cleanups=[], fibers=[fiber])
    cls = type(
        "Owned",
        (env.SigningEnvironment,),
        {
            "_node_owner": owner,
            "_node_cases": [case],
            "_node_checkpoints": [],
            "_node_artifacts": tmp_path / "evidence",
            "_node_artifacts_owned": True,
            "_node_failed": False,
            "node": SimpleNamespace(ckb_dir=str(tmp_path / "ckb")),
        },
    )
    monkeypatch.setattr(
        lsp, "stop_agent", lambda p: calls.append("process:" + str(p.pid))
    )
    monkeypatch.setattr(
        hosted, "_stop_verified_ckb", lambda _: calls.append("ckb") or []
    )
    return cls, case, source, calls


def test_cleanup_failure_still_drains_every_resource_and_archives(
    tmp_path, monkeypatch
):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)

    def bad():
        calls.append("bad")
        raise TimeoutError("callback timeout")

    case._cleanups = [(lambda: calls.append("next"), (), {}), (bad, (), {})]
    with pytest.raises(AssertionError, match="callback timeout"):
        cls._stop_node_environment()
    assert calls == [
        "bad",
        "next",
        "process:100",
        "gate",
        "proxy",
        "observer",
        "process:101",
        "ckb",
    ]
    report = json.loads((cls._node_artifacts / "final/cleanup-status.json").read_text())
    assert report["environment_invalidated"] and report["archive_complete"]
    assert (
        (source / "node.log").read_text()
        == (cls._node_artifacts / "final/fiber-1/node.log").read_text()
        == "raw bytes"
    )
    assert (
        len(json.loads((cls._node_artifacts / "final/manifest.json").read_text())) == 1
    )


def test_partial_archive_is_failed_and_original_is_retained(tmp_path, monkeypatch):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)

    def partial(src, dst, **_):
        Path(dst).mkdir(parents=True, exist_ok=True)
        raise OSError("partial archive")

    monkeypatch.setattr(env.shutil, "copytree", partial)
    with pytest.raises(AssertionError, match="partial archive"):
        cls._stop_node_environment()
    assert "ckb" in calls and "process:101" in calls
    report = json.loads((cls._node_artifacts / "final/cleanup-status.json").read_text())
    assert report["environment_invalidated"] and not report["archive_complete"]
    assert (source / "node.log").read_text() == "raw bytes"


def test_live_process_prevents_consistent_archive_claim(tmp_path, monkeypatch):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)
    cls._node_owner.fibers[0].process.poll = lambda: None
    with pytest.raises(AssertionError, match="still running"):
        cls._stop_node_environment()
    report = json.loads((cls._node_artifacts / "final/cleanup-status.json").read_text())
    assert not report["archive_complete"] and report["live_processes"] == [101]
    assert not (cls._node_artifacts / "final/fiber-1").exists()
    assert (source / "node.log").is_file()


@pytest.mark.parametrize("outcome", ["passed", "failed", "skipped"])
def test_native_report_drives_shared_case_validity(outcome):
    cls = type(
        "Case", (), {"_node_mode": "shared", "_node_keep": True, "_node_failed": False}
    )
    case = cls()
    report = SimpleNamespace(
        when="call",
        passed=outcome == "passed",
        failed=outcome == "failed",
        skipped=outcome == "skipped",
    )
    hook = runtime.pytest_runtest_makereport(SimpleNamespace(instance=case), None)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: report))
    assert case._node_case_passed == (outcome == "passed")
    assert case._node_failed == (outcome != "passed")


def test_host_channel_projection_checks_complete_union_before_case_assertions():
    cls = type(
        "Owned",
        (env.SigningEnvironment,),
        {
            "_node_mode": "shared",
            "_node_checkpoints": [{"tenants": [{"channel_id": "old"}]}],
        },
    )
    case = cls()
    case.tenants = [{"channel_id": "new"}]
    old, new, extra = ({"channel_id": name} for name in ("old", "new", "extra"))
    assert case._current_host_channels([old, new]) == [new]
    for invalid in ([new], [old], [old, new, extra], [old, new, new]):
        with pytest.raises(AssertionError):
            case._current_host_channels(invalid)
    case._node_mode = "independent"
    assert case._current_host_channels([new]) == [new]


def test_runner_signing_groups_match_qualified_methods_exactly():
    from scripts import run_lsp_regression as runner

    qualified = {cls: set(methods) for cls, methods in env.SIGNING_METHODS.items()}
    selected = {}
    for values in runner.GROUPS.values():
        for nodeid in values:
            _, cls, method = nodeid.split("::")
            if cls in qualified:
                selected.setdefault(cls, set()).add(method)
    assert selected == qualified


@pytest.mark.parametrize("failure", ["evidence-directory", "partial-setup"])
def test_shared_setup_failure_invalidates_and_restores_globals(
    tmp_path, monkeypatch, failure
):
    original_tmp = env.framework_config.TMP_PATH
    configuration = {"old": "unchanged"}
    calls = []

    class Parent:
        lsp_config_extra = configuration

        @classmethod
        def setup_class(cls):
            calls.append("setup")
            raise RuntimeError("partial preparation")

    cls = type("TestInvalidSubscriptions", (env.SigningEnvironment, Parent), {})
    monkeypatch.setenv("LSP_SIGNING_ENV_MODE", "shared")
    monkeypatch.setenv("LSP_REGRESSION_SELECTORS", "[selected]")
    monkeypatch.setenv("LSP_RUN_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(
        cls, "_stop_node_environment", classmethod(lambda c: calls.append("stop"))
    )
    if failure == "evidence-directory":
        (tmp_path / "node-environment").mkdir()
        (tmp_path / "node-environment/original").write_text("keep")
    with pytest.raises((FileExistsError, RuntimeError)):
        cls.setup_class()
    assert cls._node_failed and calls[-1] == "stop"
    assert (
        cls.lsp_config_extra is configuration
        and env.framework_config.TMP_PATH == original_tmp
    )
    if failure == "evidence-directory":
        assert calls == ["stop"]
        assert (tmp_path / "node-environment/original").read_text() == "keep"
    else:
        assert calls == ["setup", "stop"]


def test_evidence_failure_invalidates_owner_before_native_teardown(
    tmp_path, monkeypatch
):
    cls = type("Owned", (), {"_node_mode": "shared", "_node_failed": False})
    case = cls()
    item = SimpleNamespace(instance=case, cls=cls, name="last-case")
    monkeypatch.setenv("LSP_REGRESSION_CASE", str(tmp_path))
    (tmp_path / "before-teardown/last-case").mkdir(parents=True)
    hook = runtime.pytest_runtest_teardown(item, None)
    next(hook)  # fixture finalizer runs here and must see the invalid owner
    assert cls._node_failed
    with pytest.raises(RuntimeError, match="raw evidence copy failed"):
        next(hook)


@pytest.mark.parametrize("labels", [("A",), ("A", "B")])
def test_shared_capacity_covers_each_fresh_identity_and_restores_config(
    tmp_path, monkeypatch, labels
):
    config = {"configured": True}

    class Parent:
        lsp_config_extra = config
        tenant_labels = labels

        @classmethod
        def setup_class(cls):
            pass

    cls = type("TestChannelSigningIsolation", (env.SigningEnvironment, Parent), {})
    monkeypatch.setenv("LSP_SIGNING_ENV_MODE", "shared")
    monkeypatch.setenv("LSP_REGRESSION_SELECTORS", "[selected]")
    monkeypatch.setenv("LSP_RUN_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(cls, "_stop_node_environment", classmethod(lambda c: None))
    cls.setup_class()
    assert cls.lsp_config_extra["max_active_tenants"] == 3 * len(labels) + 1
    cls.teardown_class()
    assert cls.lsp_config_extra is config


def test_slow_ckb_stop_retries_once_and_preserves_initial_failure(
    tmp_path, monkeypatch
):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)
    attempts = []

    def stop(node):
        attempts.append(node)
        if len(attempts) == 1:
            raise TimeoutError("slow CKB exit")
        return []

    monkeypatch.setattr(hosted, "_stop_verified_ckb", stop)
    with pytest.raises(AssertionError, match="slow CKB exit"):
        cls._stop_node_environment()
    assert len(attempts) == 2
    report = json.loads((cls._node_artifacts / "final/cleanup-status.json").read_text())
    assert report["environment_invalidated"] and report["archive_complete"]
    assert report["errors"] and (source / "node.log").read_text() == "raw bytes"


@pytest.mark.parametrize("selected", [None, [], ["first", "second"], ["single"]])
def test_independent_retention_is_single_job_only_before_resources(
    tmp_path, monkeypatch, selected
):
    calls = []

    class Parent:
        lsp_config_extra = {}

        @classmethod
        def setup_class(cls):
            calls.append("setup")

    cls = type("Owned", (env.SigningEnvironment, Parent), {})
    monkeypatch.setenv("LSP_SIGNING_ENV_MODE", "independent")
    monkeypatch.setenv("LSP_SIGNING_KEEP_RUNTIME", "1")
    monkeypatch.setenv("LSP_RUN_ARTIFACTS", str(tmp_path))
    if selected is None:
        monkeypatch.delenv("LSP_REGRESSION_SELECTORS", raising=False)
    else:
        monkeypatch.setenv("LSP_REGRESSION_SELECTORS", json.dumps(selected))
    monkeypatch.setattr(
        cls, "_stop_node_environment", classmethod(lambda c: calls.append("cleanup"))
    )
    if selected == ["single"]:
        cls.setup_class()
        cls.teardown_class()
        assert calls == ["setup", "cleanup"]
    else:
        with pytest.raises(AssertionError, match="one method per serial job"):
            cls.setup_class()
        assert calls == ["cleanup"] and cls._node_failed


def test_existing_evidence_collision_cannot_rewrite_previous_archive(
    tmp_path, monkeypatch
):
    calls = []

    class Parent:
        lsp_config_extra = {}

        @classmethod
        def setup_class(cls):
            calls.append("allocated")

    cls = type("TestInvalidSubscriptions", (env.SigningEnvironment, Parent), {})
    root = tmp_path / "node-environment/final"
    root.mkdir(parents=True)
    files = {
        "manifest.json": b"old manifest",
        "cleanup-status.json": b"old failure",
        "raw.log": b"old raw log",
    }
    for name, content in files.items():
        (root / name).write_bytes(content)
    monkeypatch.setenv("LSP_SIGNING_ENV_MODE", "shared")
    monkeypatch.setenv("LSP_REGRESSION_SELECTORS", "[selected]")
    monkeypatch.setenv("LSP_RUN_ARTIFACTS", str(tmp_path))
    with pytest.raises(FileExistsError):
        cls.setup_class()
    assert not calls and not cls._node_artifacts_owned and cls._node_failed
    assert {f.name: f.read_bytes() for f in root.iterdir()} == files


def test_repeated_successful_cleanup_leaves_archive_and_callbacks_unchanged(
    tmp_path, monkeypatch
):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)
    cls._stop_node_environment()
    target = cls._node_artifacts / "final/cleanup-status.json"
    before = target.read_bytes(), target.stat().st_mtime_ns, list(calls)
    monkeypatch.setattr(
        env.shutil,
        "copytree",
        lambda *_a, **_k: pytest.fail("repeated successful cleanup copied again"),
    )
    cls._stop_node_environment()
    assert (target.read_bytes(), target.stat().st_mtime_ns, calls) == before
    assert cls._node_closed and cls._node_cleanup_done


def test_partial_archive_recovery_preserves_first_error_on_repeated_cleanup(
    tmp_path, monkeypatch
):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)
    copy = env.shutil.copytree
    count = 0

    def partial(src, dst, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            Path(dst).mkdir(parents=True)
            (Path(dst) / "node.log").write_text("partial")
            raise OSError("original partial archive failure")
        return copy(src, dst, **kwargs)

    monkeypatch.setattr(env.shutil, "copytree", partial)
    for _ in range(2):
        with pytest.raises(AssertionError, match="original partial archive failure"):
            cls._stop_node_environment()
    report = json.loads((cls._node_artifacts / "final/cleanup-status.json").read_text())
    assert report["environment_invalidated"] and report["archive_complete"]
    assert "original partial archive failure" in str(report["errors"])
    assert cls._node_failed and cls._node_closed
    assert (source / "node.log").read_bytes() == (
        cls._node_artifacts / "final/fiber-1/node.log"
    ).read_bytes()


def test_failed_retry_status_write_keeps_previous_error_record_atomically(
    tmp_path, monkeypatch
):
    cls, case, source, calls = cleanup_fixture(tmp_path, monkeypatch)
    copy = env.shutil.copytree
    monkeypatch.setattr(
        env.shutil,
        "copytree",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("first archive error")),
    )
    with pytest.raises(AssertionError, match="first archive error"):
        cls._stop_node_environment()
    status = cls._node_artifacts / "final/cleanup-status.json"
    before = status.read_bytes()
    monkeypatch.setattr(env.shutil, "copytree", copy)
    write = Path.write_text

    def fail_status(path, *args, **kwargs):
        if path.name.startswith("cleanup-status.json."):
            path.write_bytes(b"partial status")
            raise OSError("status write failure")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_status)
    with pytest.raises(AssertionError, match="status write failure"):
        cls._stop_node_environment()
    assert status.read_bytes() == before
    assert cls._node_failed and "first archive error" in str(cls._node_cleanup_errors)
    assert (source / "node.log").read_text() == "raw bytes"

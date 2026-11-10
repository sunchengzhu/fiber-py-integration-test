"""Offline lifecycle/pollution regressions for the QUERY shared-environment pilot."""

from copy import deepcopy
import json
import os
from types import SimpleNamespace

import pytest

from test_cases.fiber.devnet.lsp._hosted_outbound import HostedOutboundFixture
import test_cases.fiber.devnet.lsp._query_environment as pilot
from test_cases.framework.test_lsp_tenant_payment_queries import _views


@pytest.fixture
def environment(tmp_path, monkeypatch):
    events = []

    class Harness(pilot.QueryEnvironmentPilot, HostedOutboundFixture):
        _query_mode = "shared"
        _query_owner = None
        _query_failed = False
        _query_checkpoints = []
        _query_keep_runtime = True
        _hosted_original_tmp = "original-tmp"
        node = SimpleNamespace(ckb_dir=str(tmp_path / "ckb"))

        def _archive(self):
            self._record("result", result=self.result)
            events.append(("archive", self.evidence_dir.name, self.result))

        def _query_identity(self):
            return {"ckb_pid": 1, "fnn_pids": [2, 3], "sdk_pids": [4, 5]}

        def _views(self, until):
            return deepcopy(self.current_views)

        def _read_owned_payment(self, tenant, payment, until):
            return self.histories[payment["hash"]]

        def _rpc(self, client, method, params, until):
            assert method == "get_invoice"
            return {"status": "Paid"}

    def prepare(owner, method):
        owner._start_case_evidence(method)
        events.append(("start",))
        owner.addCleanup(lambda: events.append(("close_resources",)))
        for name in ("fiber1", "fiber2"):
            setattr(owner, name, SimpleNamespace(client=name, process=name))
        owner.fibers = [owner.fiber1, owner.fiber2]
        owner.tenants = [{"label": label} for label in ("A", "B")]
        owner.public_key, owner.public_channel = "public", "channel"
        owner.actual_ckb_pid, owner.ckb_process_identity = 1, "ckb-identity"

    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(tmp_path / "business"))
    monkeypatch.setattr(HostedOutboundFixture, "setup_method", prepare)
    monkeypatch.setattr(
        HostedOutboundFixture, "setUp", lambda owner: events.append(("tenants",))
    )
    monkeypatch.setattr(
        pilot, "stop_agent", lambda process: events.append(("stop", process))
    )
    monkeypatch.setattr(
        pilot, "_stop_verified_ckb", lambda node: events.append(("stop_ckb",)) or []
    )
    monkeypatch.setattr(pilot.framework_config, "TMP_PATH", "during-test")

    def case(name):
        obj = Harness()
        obj._testMethodName = name
        obj.current_views = _views()
        obj.histories = {
            "hash-A": {"status": "Success"},
            "hash-B": {"status": "Success"},
        }
        obj.setup_method(SimpleNamespace(__name__=name))
        obj.setUp()
        return obj

    return Harness, case, events


def _pass(obj):
    obj._query_prepared = (
        {label: {"hash": "hash-" + label} for label in ("A", "B")},
        {label: {"status": "Success"} for label in ("A", "B")},
    )
    obj._query_last_sample = {"views": obj.current_views}
    obj.result = "passed"
    obj.doCleanups()


def test_three_methods_share_resources_but_not_evidence_or_cleanups(environment):
    cls, case, events = environment
    objects = []
    for name in ("query04", "query05", "query06"):
        obj = case(name)
        assert obj.business_until <= cls._query_owner.business_until
        assert obj.row_until <= cls._query_owner.row_until
        _pass(obj)
        obj.teardown_method(None)
        objects.append(obj)
        assert not any(e[0] in ("close_resources", "stop") for e in events)
    assert sum(e[0] == "start" for e in events) == 1
    assert sum(e[0] == "tenants" for e in events) == 1
    assert len({id(o.fiber1) for o in objects}) == 1
    assert len({id(o._cleanups) for o in objects}) == 3
    assert len({o.evidence_dir for o in objects}) == 3
    cls.teardown_class()
    assert sum(e[0] == "close_resources" for e in events) == 1
    assert sum(e[0] == "stop" for e in events) == 2
    assert sum(e[0] == "stop_ckb" for e in events) == 1
    assert pilot.framework_config.TMP_PATH == "original-tmp"
    assert [e[1] for e in events if e[0] == "archive"] == [
        "query04",
        "query05",
        "query06",
        "shared_environment",
    ]


@pytest.mark.parametrize("pollution", ["balance", "history", "identity"])
def test_polluted_shared_environment_fails_and_cannot_rebuild(environment, pollution):
    cls, case, events = environment
    first = case("query04")
    _pass(first)
    if pollution == "balance":
        cls._query_checkpoints[-1]["views"]["A"]["local_balance"] = "0x1"
    elif pollution == "history":
        cls._query_checkpoints[-1]["expected"]["A"] = {"status": "Failed"}
    else:
        cls._query_owner._query_initial_identity["ckb_pid"] = 99
    with pytest.raises(AssertionError):
        case("query05")
    assert cls._query_failed
    with pytest.raises(AssertionError, match="invalidated"):
        case("query06")
    assert sum(e[0] == "start" for e in events) == 1
    assert any(e[:2] == ("archive", "query05") for e in events)
    cls.teardown_class()


def test_case_failure_keeps_evidence_and_invalidates_reuse(environment):
    cls, case, events = environment
    obj = case("query04")
    obj.result = "assertion_failure"
    obj.doCleanups()
    assert cls._query_failed
    assert ("archive", "query04", "assertion_failure") in events
    with pytest.raises(AssertionError, match="invalidated"):
        case("query05")
    cls.teardown_class()


def test_changed_prior_history_after_current_case_is_not_accepted(environment):
    cls, case, events = environment
    _pass(case("query04"))
    second = case("query05")
    second.histories["hash-A"] = {"status": "Failed"}
    with pytest.raises(AssertionError):
        _pass(second)
    assert cls._query_failed
    assert ("archive", "query05", "shared_checkpoint_failure") in events
    assert len(cls._query_checkpoints) == 1
    cls.teardown_class()


def test_preparation_failure_is_not_relabelled_success(environment, monkeypatch):
    cls, case, events = environment

    def fail(owner):
        raise RuntimeError("tenant preparation failed")

    monkeypatch.setattr(HostedOutboundFixture, "setUp", fail)
    with pytest.raises(RuntimeError, match="tenant preparation"):
        case("query04")
    assert cls._query_failed
    cls.teardown_class()
    assert ("archive", "shared_environment", "preparation_failure") in events
    assert sum(e[0] == "close_resources" for e in events) == 1


def test_default_independent_mode_delegates_original_fixture(environment):
    cls, case, events = environment
    cls._query_mode = "independent"
    obj = case("query04")
    assert cls._query_owner is None
    assert sum(e[0] == "start" for e in events) == 1
    assert sum(e[0] == "tenants" for e in events) == 1
    obj.doCleanups()
    obj.teardown_method(None)
    cls.teardown_class()
    assert sum(e[0] == "close_resources" for e in events) == 1
    assert sum(e[0] == "stop" for e in events) == 2


def test_unknown_mode_rejected_before_node_start(monkeypatch):
    monkeypatch.setenv("LSP_QUERY_ENV_MODE", "parallel")

    class Harness(pilot.QueryEnvironmentPilot):
        pass

    with pytest.raises(ValueError, match="independent or shared"):
        Harness.setup_class()


@pytest.mark.parametrize("exited", [True, False])
def test_empty_ps_reprobes_pid_without_hiding_a_live_process(monkeypatch, exited):
    import test_cases.fiber.devnet.lsp._hosted_tenant_fixture as hosted

    probes = []

    def kill(pid, sig):
        probes.append((pid, sig))
        if exited and len(probes) == 2:
            raise ProcessLookupError()

    monkeypatch.setattr(hosted.os, "kill", kill)
    monkeypatch.setattr(hosted, "_command_text", lambda argv: "")
    assert hosted._pid_alive(123) is (not exited)
    assert probes == [(123, 0), (123, 0)]


@pytest.mark.parametrize("failure", ["expired_deadline", "callback_timeout"])
def test_owner_cleanup_failure_finishes_resources_and_archive(environment, failure):
    import signal
    import time
    from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
        _PaymentBudgetExpired,
    )

    cls, case, events = environment
    _pass(case("query04"))
    owner = cls._query_owner
    owner.tenants[0]["agent"] = "sdk-A"
    owner.tenants[1]["agent"] = "sdk-B"
    owner.addCleanup(lambda: events.append(("close_proxy",)))
    calls = []
    if failure == "expired_deadline":
        owner.row_until = time.monotonic() - 1
        expected = AssertionError
    else:

        def timeout_once():
            calls.append("attempt")
            if len(calls) == 1:
                raise _PaymentBudgetExpired("callback cleanup timeout")
            events.append(("timed_out_resource_closed",))

        owner.addCleanup(timeout_once)
        expected = _PaymentBudgetExpired
    old_row = owner.row_until
    with pytest.raises(expected):
        cls.teardown_class()
    assert cls._query_failed
    assert ("close_resources",) in events and ("close_proxy",) in events
    assert all(("stop", p) in events for p in ["sdk-A", "sdk-B", "fiber1", "fiber2"])
    archive_index = next(
        i for i, e in enumerate(events) if e[:2] == ("archive", "shared_environment")
    )
    assert all(
        events.index(("stop", p)) < archive_index
        for p in ["sdk-A", "sdk-B", "fiber1", "fiber2"]
    )
    if failure == "callback_timeout":
        assert calls == ["attempt", "attempt"]
        assert events.index(("timed_out_resource_closed",)) < archive_index
    assert not owner._cleanups and owner.row_until == old_row
    assert ("stop_ckb",) in events
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    report = json.loads((owner.evidence_dir / "cleanup-status.json").read_text())
    assert report["archive_complete"] and report["errors"]
    assert report["environment_invalidated"]


@pytest.mark.parametrize("position", ["first", "later"])
@pytest.mark.parametrize("stage", ["directory", "first_record"])
def test_evidence_initialization_failure_invalidates_without_rebuild(
    environment, monkeypatch, position, stage
):
    from pathlib import Path

    cls, case, events = environment
    if position == "later":
        _pass(case("query04"))
    name = "query05" if position == "later" else "query04"
    if stage == "directory":
        original = Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path.name == name:
                raise OSError("evidence directory unavailable")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mkdir)
    else:
        original = cls._record

        def record(self, event, **values):
            if self.evidence_dir.name == name and event == "environment_start":
                raise OSError("first observation unavailable")
            return original(self, event, **values)

        monkeypatch.setattr(cls, "_record", record)
    with pytest.raises(OSError):
        case(name)
    assert cls._query_failed
    with pytest.raises(AssertionError, match="invalidated"):
        case("query06")
    assert sum(e[0] == "start" for e in events) == (1 if position == "later" else 0)
    root = Path(os.environ["LSP_PAYMENT_REPORT_DIR"])
    assert list(root.rglob("setup-failure-*.json"))
    cls.teardown_class()


def test_partial_initialization_keeps_original_error_when_cleanup_also_fails(
    environment, monkeypatch
):
    cls, case, events = environment
    original = cls._start_case_evidence
    objects = []

    def initialize(self, method):
        original(self, method)
        objects.append(self)

        def failed_cleanup():
            raise ValueError("secondary cleanup failure")

        self.addCleanup(failed_cleanup)
        raise OSError("primary evidence initialization failure")

    monkeypatch.setattr(cls, "_start_case_evidence", initialize)
    with pytest.raises(OSError, match="primary evidence") as error:
        case("query04")
    assert cls._query_failed and not objects[0]._cleanups
    assert any("secondary cleanup failure" in note for note in error.value.__notes__)
    cls.teardown_class()


def test_owner_archive_failure_keeps_partial_evidence_and_stops_every_resource(
    environment, monkeypatch
):
    cls, case, events = environment
    original = cls._archive

    def archive(self):
        if self.evidence_dir.name == "shared_environment":
            (self.evidence_dir / "partial-evidence.txt").write_text("original bytes")
            raise OSError("final archive unavailable")
        original(self)

    monkeypatch.setattr(cls, "_archive", archive)
    _pass(case("query04"))
    owner = cls._query_owner
    owner.tenants[0]["agent"] = "sdk-A"
    with pytest.raises(OSError, match="final archive"):
        cls.teardown_class()
    assert cls._query_failed and ("close_resources",) in events
    assert all(("stop", p) in events for p in ["sdk-A", "fiber1", "fiber2"])
    assert (owner.evidence_dir / "partial-evidence.txt").read_text() == "original bytes"
    assert not json.loads((owner.evidence_dir / "cleanup-status.json").read_text())[
        "archive_complete"
    ]
    assert ("stop_ckb",) in events


def test_owner_early_cleanup_is_idempotent_at_class_teardown(environment):
    cls, case, events = environment
    _pass(case("query04"))
    owner = cls._query_owner
    cls._query_failed = True
    owner.doCleanups()
    cls.teardown_class()
    assert sum(e[:2] == ("archive", "shared_environment") for e in events) == 1
    assert sum(e[0] == "close_resources" for e in events) == 1
    assert sum(e[0] == "stop" for e in events) == 2


def test_owner_error_keeps_primary_failure_and_raw_ckb_state(environment, monkeypatch):
    import time

    cls, case, events = environment
    _pass(case("query04"))
    cls._query_owner.row_until = time.monotonic() - 1
    cls._query_keep_runtime = False
    monkeypatch.setattr(
        pilot, "_stop_verified_ckb", lambda node: ["secondary CKB stop failure"]
    )
    with pytest.raises(AssertionError, match="cleanup deadline exhausted") as error:
        cls.teardown_class()
    assert any("secondary CKB stop failure" in note for note in error.value.__notes__)
    assert ("archive", "shared_environment", "environment_closed") in events
    assert cls._query_failed

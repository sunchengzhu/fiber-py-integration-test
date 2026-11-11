"""Offline regressions for the four invoice cases and real reuse lifecycle."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

import test_cases.fiber.devnet.lsp._invoice_query_environment as invoice_env
import test_cases.fiber.devnet.lsp._query_environment as lifecycle
from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import HostedTenantFixture
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
    _PaymentBudgetExpired,
)
import test_cases.fiber.devnet.lsp.test_tenant_boundaries as native_cases
from test_cases.framework.test_lsp_tenant_payment_queries import _views

METHODS = tuple(invoice_env.INVOICE_QUERY_METHODS)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    events, store = [], {}
    state = {"views": _views(), "runtime": "active", "serial": 0, "count": "0x2"}
    tenants = []
    for label in ("A", "B"):
        status = tmp_path / (label + ".json")
        status.write_text(json.dumps({"tenant_id": "id-" + label}))
        tenants.append(
            {
                "label": label,
                "client": label,
                "status": {"tenant_id": "id-" + label},
                "status_file": status,
                "channel_id": label.lower(),
                "agent": "sdk-" + label,
            }
        )

    class Harness(native_cases.TestTenantQueryIsolation):
        _query_mode = "shared"
        _query_keep_runtime = True
        _query_owner = None
        _query_failed = False
        _query_checkpoints = []
        _hosted_original_tmp = "original"
        node = SimpleNamespace(ckb_dir=str(tmp_path / "ckb"))

        def _query_identity(self):
            return {"fnn": [1, 2], "sdk": [3, 4], "channels": ["a", "b", "p"]}

        def _archive(self):
            (self.evidence_dir / "archive.txt").write_text(self.result)
            events.append(("archive", self.evidence_dir.name))

        def _views(self, until):
            events.append(("tenant-views",))
            return deepcopy(state["views"])

        def _signing(self, tenant, until):
            events.append(("tenant-signing", tenant["label"]))
            return {"type": "NoSignatureRequired"}

        def generate_random_preimage(self):
            state["serial"] += 1
            return "0x" + format(state["serial"], "064x")

        def _control(self, tenant, operation, until, values=None):
            events.append(("control", tenant["label"], operation))
            return {}

        def _rpc(self, client, method, params, until):
            events.append(("rpc", client, method))
            if method == "lsp_get_status":
                assert client == "operator"
                return {
                    "active_tenants": state["count"],
                    "registered_tenants": state["count"],
                }
            if method == "lsp_list_tenants":
                assert client == "operator"
                return {
                    "tenants": [
                        {
                            "tenant_id": "id-" + label,
                            "runtime_status": state["runtime"],
                            "channels": [{"channel_id": label.lower(), "online": True}],
                        }
                        for label in ("A", "B")
                    ]
                }
            if method == "new_invoice":
                data = deepcopy(params[0])
                data["timestamp"] = "0x1"
                invoice = {
                    "status": "Open",
                    "invoice": {"data": data},
                    "invoice_address": "invoice-" + data["payment_hash"],
                }
                store[("id-" + client, data["payment_hash"])] = deepcopy(invoice)
                return deepcopy(invoice)
            assert method == "get_invoice"
            tenant_id = params[0].get("tenant_id", "id-" + client)
            return deepcopy(store[(tenant_id, params[0]["payment_hash"])])

        def _rpc_error(self, client, method, params):
            events.append(("denied", client, method))
            if method == "get_invoice":
                message = (
                    "cannot query another tenant"
                    if "tenant_id" in params[0]
                    else "invoice not found"
                )
            else:
                message = "Unauthorized"
            return {"code": -32999, "message": message}

    def prepare(owner, method):
        owner._start_case_evidence(method)
        events.append(("start",))
        owner.addCleanup(lambda: events.append(("close-resources",)))
        owner.fiber1 = SimpleNamespace(client="operator", process="fnn-T")
        owner.fiber2 = SimpleNamespace(client="P", process="fnn-P")
        owner.fibers = [owner.fiber1, owner.fiber2]
        owner.tenants = tenants
        owner.public_key, owner.public_channel = "key", "p"
        owner.actual_ckb_pid, owner.ckb_process_identity = 1, "identity"
        owner.baseline = _views()

    monkeypatch.setenv("LSP_PAYMENT_REPORT_DIR", str(tmp_path / "business"))
    monkeypatch.setattr(HostedTenantFixture, "setup_method", prepare)
    monkeypatch.setattr(
        HostedTenantFixture, "setUp", lambda owner: events.append(("ready",))
    )
    monkeypatch.setattr(
        lifecycle, "stop_agent", lambda process: events.append(("stop", process))
    )
    monkeypatch.setattr(
        lifecycle, "_stop_verified_ckb", lambda node: events.append(("stop-ckb",)) or []
    )
    monkeypatch.setattr(lifecycle.framework_config, "TMP_PATH", "during")
    monkeypatch.setattr(
        invoice_env.os,
        "statvfs",
        lambda path: SimpleNamespace(f_bavail=16 * 2**30, f_frsize=1),
    )

    def case(method):
        obj = Harness()
        obj._testMethodName = method
        obj.setup_method(SimpleNamespace(__name__=method))
        obj.setUp()
        return obj

    def run(method):
        obj = case(method)
        getattr(obj, method)()
        if obj._query_mode == "shared":
            assert obj.business_until <= Harness._query_owner.business_until
            assert obj.row_until <= Harness._query_owner.row_until
        obj.doCleanups()
        obj.teardown_method(None)
        return obj

    return SimpleNamespace(
        cls=Harness, case=case, run=run, events=events, store=store, state=state
    )


@pytest.mark.parametrize("order", [METHODS, tuple(reversed(METHODS))])
def test_four_native_bodies_share_resources_and_keep_all_six_invoices(
    environment, order
):
    e = environment
    objects = [e.run(method) for method in order]
    assert sum(event == ("start",) for event in e.events) == 1
    assert len({id(obj.fiber1) for obj in objects}) == 1
    assert len({obj.evidence_dir for obj in objects}) == 4
    catalog = [
        key for checkpoint in e.cls._query_checkpoints for key in checkpoint["invoices"]
    ]
    assert len(catalog) == len(set(catalog)) == len(e.store) == 6
    assert sum(event[:1] == ("control",) for event in e.events) == 6
    assert not any(event[0] in ("stop", "close-resources") for event in e.events)
    e.cls.teardown_class()
    assert ("stop-ckb",) in e.events
    assert e.events.count(("close-resources",)) == 1
    assert ("archive", "shared_environment") in e.events


@pytest.mark.parametrize("mode", ["independent", "shared"])
def test_admin_list_denial_followed_by_operator_health_then_legal_tenant_query(
    environment, mode
):
    e = environment
    e.cls._query_mode = mode
    obj = e.case(METHODS[2])
    getattr(obj, METHODS[2])()
    denied = e.events.index(("denied", "A", "lsp_list_tenants"))
    later = e.events[denied + 1 :]
    assert ("rpc", "operator", "lsp_get_status") in later
    assert ("rpc", "A", "get_invoice") in later
    health = later.index(("rpc", "operator", "lsp_get_status"))
    tenant = next(
        i
        for i, event in enumerate(later)
        if event[:2] == ("rpc", "A") or event[0].startswith("tenant-")
    )
    assert health < tenant
    obj.doCleanups()
    e.cls.teardown_class()


@pytest.mark.parametrize("pollution", ["invoice", "balance", "runtime", "identity"])
def test_prior_pollution_invalidates_and_never_rebuilds(
    environment, pollution, monkeypatch
):
    e = environment
    e.run(METHODS[0])
    if pollution == "invoice":
        next(iter(e.store.values()))["invoice_address"] = "changed"
    elif pollution == "balance":
        e.state["views"]["A"]["local_balance"] = "0x1"
    elif pollution == "runtime":
        e.state["runtime"] = "cold"
    else:
        monkeypatch.setattr(e.cls, "_query_identity", lambda self: {"different": True})
    begin = len(e.events)
    with pytest.raises(AssertionError):
        e.case(METHODS[1])
    assert e.cls._query_failed
    if pollution == "runtime":
        assert not any(
            event[0].startswith("tenant-") or event[:2] == ("rpc", "A")
            for event in e.events[begin:]
        )
    with pytest.raises(AssertionError, match="invalidated"):
        e.case(METHODS[2])
    assert e.events.count(("start",)) == 1
    e.cls.teardown_class()


def test_postcondition_failure_is_raised_and_archived_before_next_method(environment):
    e = environment
    e.run(METHODS[0])
    obj = e.case(METHODS[1])
    getattr(obj, METHODS[1])()
    next(iter(e.store.values()))["status"] = "Cancelled"
    with pytest.raises(AssertionError):
        obj.doCleanups()
    assert e.cls._query_failed
    assert (obj.evidence_dir / "archive.txt").read_text() == "shared_checkpoint_failure"
    with pytest.raises(AssertionError, match="invalidated"):
        e.case(METHODS[2])
    e.cls.teardown_class()


def test_evict_is_never_silently_added_to_shared_group(environment):
    e = environment
    with pytest.raises(AssertionError, match="not eligible"):
        e.case("test_tenant_token_cannot_evict_tenants")
    assert e.cls._query_owner is None
    assert ("start",) not in e.events
    assert list(Path(e.cls.node.ckb_dir).parent.rglob("setup-failure-*.json"))
    e.cls.teardown_class()


@pytest.mark.parametrize("position", ["first", "later"])
def test_evidence_initialization_failure_retains_diagnostics_and_invalidates(
    environment, monkeypatch, position
):
    e = environment
    if position == "later":
        e.run(METHODS[0])
    original = e.cls._record

    def record(self, stage, **values):
        if self.evidence_dir.name == METHODS[1] and stage == "environment_start":
            raise OSError("original evidence failure")
        return original(self, stage, **values)

    monkeypatch.setattr(e.cls, "_record", record)
    with pytest.raises(OSError, match="original evidence failure"):
        e.case(METHODS[1])
    assert e.cls._query_failed
    with pytest.raises(AssertionError, match="invalidated"):
        e.case(METHODS[2])
    assert list(Path(e.cls.node.ckb_dir).parent.rglob("setup-failure-*.json"))
    e.cls.teardown_class()
    assert ("stop-ckb",) in e.events


@pytest.mark.parametrize("mode", ["independent", "shared"])
@pytest.mark.parametrize("failure", ["deadline", "timeout", "archive"])
def test_bounded_cleanup_drains_all_resources_keeps_original_failure_and_final_evidence(
    environment, mode, failure, monkeypatch
):
    e = environment
    e.cls._query_mode = mode
    obj = e.case(METHODS[0])
    getattr(obj, METHODS[0])()
    owner = e.cls._query_owner if mode == "shared" else obj
    attempts = []
    if failure == "deadline":
        owner.row_until = time.monotonic() - 1
        error = AssertionError
    elif failure == "timeout":

        def timeout_once():
            attempts.append(1)
            if len(attempts) == 1:
                raise _PaymentBudgetExpired("callback timeout")
            e.events.append(("retried-resource-closed",))

        owner.addCleanup(timeout_once)
        error = _PaymentBudgetExpired
    else:
        original = e.cls._archive

        def partial(self):
            if self is owner:
                (self.evidence_dir / "partial.txt").write_text("raw evidence")
                raise OSError("archive failed")
            return original(self)

        monkeypatch.setattr(e.cls, "_archive", partial)
        error = OSError
    with pytest.raises(error):
        if mode == "shared":
            obj.doCleanups()
            e.cls.teardown_class()
        else:
            obj.doCleanups()
    assert e.cls._query_failed
    assert ("close-resources",) in e.events
    assert all(("stop", p) in e.events for p in ("sdk-A", "sdk-B", "fnn-T", "fnn-P"))
    status = json.loads((owner.evidence_dir / "cleanup-status.json").read_text())
    assert status["remaining_callbacks"] == 0 and status["errors"]
    assert status["archive_complete"] == (failure != "archive")
    if failure == "archive":
        assert (owner.evidence_dir / "partial.txt").read_text() == "raw evidence"
    if mode == "independent":
        e.cls.teardown_class()
    assert ("stop-ckb",) in e.events


def test_independent_failure_still_drains_resources_and_archives(environment):
    e = environment
    e.cls._query_mode = "independent"
    obj = e.case(METHODS[0])
    getattr(obj, METHODS[0])()
    e.state["runtime"] = "cold"
    with pytest.raises(AssertionError):
        obj.doCleanups()
    assert e.cls._query_failed
    assert ("close-resources",) in e.events
    assert (
        obj.evidence_dir / "archive.txt"
    ).read_text() == "invoice_checkpoint_failure"
    e.cls.teardown_class()


def test_mode_is_separate_from_payment_query_switch(monkeypatch):
    monkeypatch.setenv("LSP_QUERY_ENV_MODE", "shared")
    monkeypatch.delenv("LSP_INVOICE_QUERY_ENV_MODE", raising=False)
    assert (
        invoice_env.InvoiceQueryEnvironment.mode_variable
        != lifecycle.QueryEnvironmentPilot.mode_variable
    )
    monkeypatch.setenv("LSP_INVOICE_QUERY_ENV_MODE", "parallel")
    monkeypatch.setattr(
        invoice_env.os,
        "statvfs",
        lambda path: SimpleNamespace(f_bavail=16 * 2**30, f_frsize=1),
    )
    with pytest.raises(ValueError, match="LSP_INVOICE_QUERY_ENV_MODE"):
        invoice_env.InvoiceQueryEnvironment.setup_class()


def test_unpinned_revision_rejects_other_head_before_node_start(monkeypatch):
    monkeypatch.setattr(invoice_env, "REVISION", "different-head")
    with pytest.raises(AssertionError, match="explicit pinned retest revision"):
        invoice_env.InvoiceQueryEnvironment.setup_class()


def test_explicit_matching_retest_revision_reaches_original_setup(monkeypatch):
    called = []
    monkeypatch.setattr(invoice_env, "REVISION", "a" * 40)
    monkeypatch.setattr(invoice_env, "RETEST_REVISION", "a" * 40)
    monkeypatch.setattr(
        invoice_env.os,
        "statvfs",
        lambda _: SimpleNamespace(f_bavail=16 * 2**30, f_frsize=1),
    )
    monkeypatch.setattr(
        lifecycle.HostedEnvironmentReuse,
        "setup_class",
        classmethod(lambda cls: called.append(cls)),
    )
    invoice_env.InvoiceQueryEnvironment.setup_class()
    assert called == [invoice_env.InvoiceQueryEnvironment]


def test_independent_repeated_cleanup_does_not_query_or_archive_again(environment):
    e = environment
    e.cls._query_mode = "independent"
    obj = e.run(METHODS[0])
    before = list(e.events)
    e.state["runtime"] = "cold"
    obj.doCleanups()
    assert e.events == before
    e.cls.teardown_class()


@pytest.mark.parametrize(
    "field,value",
    [
        ("channel_outpoint", "another-funding"),
        ("offered_tlc_balance", "0x1"),
        ("pending_tlcs", [{"payment_hash": "unexpected"}]),
    ],
)
def test_channel_or_locked_funds_change_fails_before_reuse(environment, field, value):
    e = environment
    e.run(METHODS[0])
    e.state["views"]["A"][field] = value
    with pytest.raises(AssertionError):
        e.case(METHODS[1])
    assert e.cls._query_failed
    e.cls.teardown_class()


def test_excluded_evict_independent_path_has_no_post_denial_tenant_calls(environment):
    e = environment
    e.cls._query_mode = "independent"
    method = "test_tenant_token_cannot_evict_tenants"
    obj = e.case(method)
    getattr(obj, method)()
    denied = [
        i
        for i, event in enumerate(e.events)
        if event == ("denied", "A", "lsp_evict_tenant")
    ]
    assert len(denied) == 2
    assert all(event[:2] == ("rpc", "operator") for event in e.events[denied[-1] + 1 :])
    assert obj._invoice_current == {}
    obj.doCleanups()
    e.cls.teardown_class()


@pytest.mark.parametrize("quantity", ["0x2", 2])
def test_operator_counter_accepts_real_hex_and_normalized_integer(
    environment, quantity
):
    e = environment
    e.state["count"] = quantity
    obj = e.case(METHODS[0])
    status = obj._invoice_operator_state()
    assert status["active_tenants"] == status["registered_tenants"] == 2
    getattr(obj, METHODS[0])()
    obj.doCleanups()
    e.cls.teardown_class()


def test_operator_hex_count_below_two_still_fails_and_invalidates(environment):
    e = environment
    e.state["count"] = "0x1"
    with pytest.raises(AssertionError):
        e.case(METHODS[0])
    assert e.cls._query_failed
    e.cls.teardown_class()


def test_default_independent_partial_archive_keeps_original_nodes(
    environment, monkeypatch, tmp_path
):
    import test_cases.fiber.devnet.lsp.test_delayed_payment_recovery as delayed

    e = environment
    e.cls._query_mode = "independent"
    e.cls._query_keep_runtime = False
    obj = e.case(METHODS[0])
    getattr(obj, METHODS[0])()
    clean_calls, originals = [], []
    for index, fiber in enumerate(obj.fibers):
        source = tmp_path / f"original-node-{index}"
        source.mkdir()
        raw = source / "original.db"
        raw.write_bytes(b"original database bytes")
        originals.append(raw)
        fiber.clean = lambda i=index: clean_calls.append(i)
    monkeypatch.setattr(delayed, "stop_agent", lambda process: None)

    def partial(self):
        (self.evidence_dir / "partial-archive.txt").write_bytes(b"partial copy")
        raise OSError("partial archive failure")

    monkeypatch.setattr(e.cls, "_archive", partial)
    try:
        with pytest.raises(OSError, match="partial archive"):
            obj.doCleanups()
        obj.teardown_method(None)
        assert not clean_calls
        assert all(p.read_bytes() == b"original database bytes" for p in originals)
        assert (
            obj.evidence_dir / "partial-archive.txt"
        ).read_bytes() == b"partial copy"
        status = json.loads((obj.evidence_dir / "cleanup-status.json").read_text())
        assert not status["archive_complete"] and status["environment_invalidated"]
        assert e.cls._query_failed
        assert all(
            ("stop", p) in e.events for p in ("sdk-A", "sdk-B", "fnn-T", "fnn-P")
        )
        with pytest.raises(AssertionError, match="invalidated"):
            e.case(METHODS[1])
        e.cls.teardown_class()
        assert ("stop-ckb",) in e.events
    finally:
        e.cls._query_keep_runtime = True


@pytest.mark.parametrize("stage", ["directory", "first_record"])
def test_default_independent_evidence_init_keeps_ckb_and_original_error(
    environment, monkeypatch, tmp_path, stage
):
    e = environment
    e.cls._query_mode = "independent"
    e.cls._query_keep_runtime = False
    marker = tmp_path / "ckb" / "original-state"
    marker.parent.mkdir()
    marker.write_bytes(b"original CKB state")
    if stage == "directory":
        original = Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path.name == METHODS[0]:
                raise OSError("primary evidence directory failure")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mkdir)
    else:
        original = e.cls._record

        def record(self, event, **values):
            if event == "environment_start":
                raise OSError("primary first record failure")
            return original(self, event, **values)

        monkeypatch.setattr(e.cls, "_record", record)
    try:
        with pytest.raises(OSError, match="primary"):
            e.case(METHODS[0])
        assert e.cls._query_failed
        diagnostics = list(tmp_path.rglob("setup-failure-*.json"))
        assert len(diagnostics) == 1
        diagnostic = json.loads(diagnostics[0].read_text())
        assert (
            diagnostic["environment_invalidated"] and "primary" in diagnostic["error"]
        )
        assert ("start",) not in e.events
        with pytest.raises(AssertionError, match="invalidated"):
            e.case(METHODS[1])
        e.cls.teardown_class()
        assert ("stop-ckb",) in e.events
        assert marker.read_bytes() == b"original CKB state"
        assert lifecycle.framework_config.TMP_PATH == "original"
    finally:
        e.cls._query_keep_runtime = True


def test_default_independent_init_preserves_primary_when_diagnostic_also_fails(
    environment, monkeypatch
):
    e = environment
    e.cls._query_mode = "independent"
    e.cls._query_keep_runtime = False

    def record(self, event, **values):
        raise OSError("primary first observation failure")

    def diagnostic(self, method, error):
        raise ValueError("secondary diagnostic failure")

    monkeypatch.setattr(e.cls, "_record", record)
    monkeypatch.setattr(e.cls, "_save_setup_failure", diagnostic)
    try:
        with pytest.raises(OSError, match="primary first") as error:
            e.case(METHODS[0])
        assert e.cls._query_failed
        assert any(
            "secondary diagnostic failure" in note for note in error.value.__notes__
        )
        e.cls.teardown_class()
        assert ("stop-ckb",) in e.events
    finally:
        e.cls._query_keep_runtime = True


def test_failed_independent_teardown_attempts_both_nodes_and_preserves_dirs(
    environment, monkeypatch
):
    e = environment
    e.cls._query_mode = "independent"
    e.cls._query_keep_runtime = False
    obj = e.case(METHODS[0])
    getattr(obj, METHODS[0])()
    obj.doCleanups()
    e.cls._query_failed = True
    attempted, cleaned = [], []
    for fiber in obj.fibers:
        fiber.clean = lambda: cleaned.append(True)

    def stop(process):
        attempted.append(process)
        if process == "fnn-T":
            raise RuntimeError("first FNN stop failure")

    monkeypatch.setattr(lifecycle, "stop_agent", stop)
    try:
        with pytest.raises(RuntimeError, match="first FNN"):
            obj.teardown_method(None)
        assert attempted == ["fnn-T", "fnn-P"]
        assert not cleaned
        e.cls.teardown_class()
        assert ("stop-ckb",) in e.events
    finally:
        e.cls._query_keep_runtime = True

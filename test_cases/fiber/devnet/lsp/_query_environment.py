"""Bounded Hosted resource ownership and QUERY-04..06 checkpoints.

The resource owner keeps unittest cleanup callbacks until class teardown. Each
native method has its own evidence, budgets, fresh payments and unchanged oracles.
"""

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import time

import framework.config as framework_config
from test_cases.fiber.devnet.lsp._hosted_outbound import HostedOutboundFixture
from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import _stop_verified_ckb
from test_cases.fiber.devnet.lsp._lsp_test import stop_agent


class HostedEnvironmentReuse:
    """Lifecycle only; each concrete group owns its eligibility and oracles."""

    mode_variable = "LSP_QUERY_ENV_MODE"
    keep_variable = "LSP_QUERY_KEEP_RUNTIME"
    owner_fixture = HostedOutboundFixture

    @classmethod
    def setup_class(cls):
        cls._query_mode = os.environ.get(cls.mode_variable, "independent")
        if cls._query_mode not in ("independent", "shared"):
            raise ValueError(f"{cls.mode_variable} must be independent or shared")
        cls._query_keep_runtime = os.environ.get(cls.keep_variable) == "1"
        cls._query_owner = None
        cls._query_failed = False
        cls._query_checkpoints = []
        super().setup_class()

    @classmethod
    def teardown_class(cls):
        errors = []
        owner = cls._query_owner
        try:
            if owner is not None:
                if getattr(owner, "result", "incomplete") == "incomplete":
                    owner.result = "environment_closed"
                try:
                    owner.doCleanups()
                except BaseException as error:
                    cls._query_failed = True
                    errors.append(error)
        finally:
            try:
                # An owner failure must retain the original CKB state too.
                if cls._query_keep_runtime or cls._query_failed or errors:
                    messages = _stop_verified_ckb(cls.node)
                    if messages:
                        errors.append(AssertionError("; ".join(messages)))
                else:
                    super().teardown_class()
            except BaseException as error:
                errors.append(error)
            finally:
                framework_config.TMP_PATH = cls._hosted_original_tmp
        if errors:
            cls._query_failed = True
            for error in errors[1:]:
                errors[0].add_note(f"additional class cleanup error: {error!r}")
            raise errors[0]

    def _save_setup_failure(self, method, error):
        root = Path(os.environ.get("LSP_PAYMENT_REPORT_DIR", "report")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        # A failed method directory must not prevent independent diagnostics.
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="setup-failure-", suffix=".json", dir=root, delete=False
        ) as stream:
            json.dump(
                {
                    "method": method.__name__,
                    "error": repr(error),
                    "environment_invalidated": True,
                    "runtime": str(self.node.ckb_dir),
                },
                stream,
                indent=2,
            )
            stream.write("\n")
            print(f"query setup failure evidence: {stream.name}")

    def _cleanup_query_owner(self):
        """Drain all owned resources and archive even after the row budget expires."""
        if getattr(self, "_query_owner_cleanup_done", False):
            if self._query_owner_cleanup_error is not None:
                raise self._query_owner_cleanup_error
            return True
        if getattr(self, "result", "incomplete") in (
            "incomplete",
            "preparation_failure",
        ):
            self.result = "preparation_failure"
            type(self)._query_failed = True
        self.business_until = float("inf")  # Cleanup never renews business time.
        deadline = min(getattr(self, "row_until", float("inf")), time.monotonic() + 60)
        errors, failures = [], []
        recovery = False

        def failed(error, phase):
            nonlocal recovery
            recovery = True
            type(self)._query_failed = True
            errors.append((error, phase))

        def attempt(function, args=(), kwargs=None, *, phase, until=None, cap=15):
            try:
                with self._budget(until or time.monotonic() + cap, cap):
                    self._callCleanup(function, *args, **(kwargs or {}))
                return True
            except BaseException as error:
                failed(error, phase)
                return False

        while self._cleanups:
            function, args, kwargs = self._cleanups.pop()
            # Final evidence is taken once, after resource cleanup and retries.
            if function == self._archive or (
                getattr(function, "__self__", None) is self
                and getattr(function, "__name__", "") == "_archive"
            ):
                continue
            if not recovery and time.monotonic() >= deadline:
                failed(
                    AssertionError("hosted fixture cleanup deadline exhausted"),
                    "deadline",
                )
            if not attempt(
                function,
                args,
                kwargs,
                phase=f"callback:{function.__name__}",
                until=None if recovery else deadline,
                cap=15 if recovery else 60,
            ):
                failures.append((function, args, kwargs))
        # A timed-out callback may have left its resource half closed. Retry it
        # once under a fresh bounded cleanup cap; retain the original failure.
        for function, args, kwargs in failures:
            attempt(function, args, kwargs, phase=f"retry:{function.__name__}")
        # Cover processes whose registering callback failed during preparation.
        for tenant in getattr(self, "tenants", []):
            process = tenant.get("agent")
            if process is not None:
                attempt(stop_agent, (process,), phase=f"sdk:{tenant['label']}")
        for index, fiber in enumerate(getattr(self, "fibers", []), 1):
            process = getattr(fiber, "process", None)
            if process is not None:
                attempt(stop_agent, (process,), phase=f"fnn:{index}")
        if not hasattr(self, "result"):
            self.result = "preparation_failure"
        archive_complete = attempt(self._archive, phase="final_archive", cap=60)
        report = {
            "archive_complete": archive_complete,
            "environment_invalidated": type(self)._query_failed,
            "errors": [
                {"phase": phase, "error": repr(error)} for error, phase in errors
            ],
            "remaining_callbacks": len(self._cleanups),
            "row_until": getattr(self, "row_until", None),
        }
        try:
            (self.evidence_dir / "cleanup-status.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
        except BaseException as error:
            failed(error, "cleanup_diagnostic")
        self._query_owner_cleanup_done = True
        self._query_owner_cleanup_error = errors[0][0] if errors else None
        if errors:
            for error, phase in errors[1:]:
                errors[0][0].add_note(
                    f"additional owner cleanup error ({phase}): {error!r}"
                )
            raise errors[0][0]
        return True

    def setup_method(self, method):
        if type(self)._query_failed:
            raise AssertionError("Hosted environment invalidated; no rebuild/retry")
        creating_owner = False
        try:
            # Evidence initialization can fail before the fixture registers any
            # cleanup. Both modes must invalidate and preserve the CKB owner.
            if self._query_mode == "independent":
                return super().setup_method(method)
            self._validate_shared_method(method)
            self._start_case_evidence(method)
            if type(self)._query_owner is None:
                creating_owner = True
                owner = type(self)()
                type(self)._query_owner = owner
                # Call the original fixture directly, without this mixin's hooks.
                self.owner_fixture.setup_method(
                    owner, SimpleNamespace(__name__="shared_environment")
                )
                self.owner_fixture.setUp(owner)
            owner = type(self)._query_owner
            self.business_until = min(self.business_until, owner.business_until)
            self.row_until = min(self.row_until, owner.row_until)
            # Bind only resource handles. Never copy unittest internals, cleanup
            # stacks, results, deadlines, evidence directories or payment state.
            for name in (
                "fibers",
                "fiber1",
                "fiber2",
                "tenants",
                "public_key",
                "public_channel",
                "actual_ckb_pid",
                "ckb_process_identity",
            ):
                setattr(self, name, getattr(owner, name))
            self._check_query_environment()
        except BaseException as error:
            type(self)._query_failed = True
            owner = type(self)._query_owner
            if (
                creating_owner
                and owner is not None
                and getattr(owner, "result", "incomplete") == "incomplete"
            ):
                owner.result = "preparation_failure"
            try:
                self._save_setup_failure(method, error)
            except BaseException as diagnostic_error:
                error.add_note(
                    f"setup failure diagnostic unavailable: {diagnostic_error!r}"
                )
            # pytest doesn't run unittest cleanups if setup_method fails.
            if self._cleanups:
                try:
                    self.result = "preparation_failure"
                    self.doCleanups()
                except BaseException as cleanup_error:
                    error.add_note(f"additional case cleanup error: {cleanup_error!r}")
            raise

    def setUp(self):
        if self._query_mode == "independent":
            super().setUp()
            self._record("query_environment_identity", identity=self._query_identity())
            return
        # The owner already opened channels, registered tenants and released gates.
        self._record(
            "query_environment_identity",
            identity=self._query_identity(),
            mode="shared",
            business_until=self.business_until,
            row_until=self.row_until,
        )

    def _query_identity(self):
        assert all(f.process.poll() is None for f in self.fibers), "FNN exited"
        assert all(t["agent"].poll() is None for t in self.tenants), "SDK exited"
        os.kill(self.actual_ckb_pid, 0)
        identity = subprocess.check_output(
            ["ps", "-p", str(self.actual_ckb_pid), "-o", "lstart=,command="],
            text=True,
            timeout=2,
        ).strip()
        assert identity == self.ckb_process_identity, "CKB identity changed"
        return {
            "ckb_pid": self.actual_ckb_pid,
            "ckb_identity": identity,
            "fnn_pids": [f.process.pid for f in self.fibers],
            "sdk_pids": {t["label"]: t["agent"].pid for t in self.tenants},
            "tenant_ids": {t["label"]: t["status"]["tenant_id"] for t in self.tenants},
            "channels": {t["label"]: t["channel_id"] for t in self.tenants},
            "public_channel": self.public_channel,
            "runtime": str(Path(self.node.ckb_dir).resolve()),
        }

    def doCleanups(self):
        if getattr(self, "_query_mode", "independent") != "shared":
            try:
                return super().doCleanups()
            except BaseException:
                type(self)._query_failed = True
                raise
        if self is type(self)._query_owner:
            return self._cleanup_query_owner()
        try:
            if self.result == "passed":
                self._finish_shared_case()
            else:
                type(self)._query_failed = True
        except BaseException:
            self.result = "shared_checkpoint_failure"
            type(self)._query_failed = True
            raise
        finally:
            try:
                super().doCleanups()
            except BaseException:
                type(self)._query_failed = True
                raise

    def teardown_method(self, method):
        if self._query_mode == "shared":
            return  # The class owner retains the live environment and all files.
        if self._query_keep_runtime or type(self)._query_failed:
            # An incomplete archive must never enter Fiber.clean(), even when
            # the caller did not opt into keeping successful runtimes.
            errors = []
            for fiber in getattr(self, "fibers", []):
                try:
                    stop_agent(getattr(fiber, "process", None))
                except BaseException as error:
                    type(self)._query_failed = True
                    errors.append(error)
            if errors:
                for error in errors[1:]:
                    errors[0].add_note(f"additional FNN stop error: {error!r}")
                raise errors[0]
            return
        return super().teardown_method(method)

    def _validate_shared_method(self, method):
        """A group may reject methods before creating or binding resources."""


class QueryEnvironmentPilot(HostedEnvironmentReuse):
    """The existing payment query guards remain specific to QUERY-04..06."""

    def _check_query_environment(self):
        from test_cases.fiber.devnet.lsp.test_tenant_payment_queries import (
            _assert_query_funds,
        )

        identity = self._query_identity()
        owner = type(self)._query_owner
        if not hasattr(owner, "_query_initial_identity"):
            owner._query_initial_identity = identity
        assert identity == owner._query_initial_identity, "shared identity changed"
        if self._query_checkpoints:
            # No payment is sent between methods. Prior six-endpoint balances
            # must still match the previous method's final snapshot exactly.
            views = self._views(self.business_until)
            _assert_query_funds(self._query_checkpoints[-1]["views"], views, {})
            assert all(not v["pending_tlcs"] for v in views.values()), views
        self._check_prior_query_histories()
        self._record(
            "shared_environment_checked",
            identity=identity,
            prior_cases=len(self._query_checkpoints),
        )

    def _check_prior_query_histories(self):
        for checkpoint in self._query_checkpoints:
            for tenant in self.tenants:
                label = tenant["label"]
                payment = checkpoint["payments"][label]
                assert self._read_owned_payment(
                    tenant, payment, self.business_until
                ) == (checkpoint["expected"][label])
                invoice = self._rpc(
                    self.fiber2.client,
                    "get_invoice",
                    [{"payment_hash": payment["hash"]}],
                    self.business_until,
                )
                assert invoice["status"] == "Paid", invoice
                self._record(
                    "shared_prior_history_checked",
                    case=checkpoint["case"],
                    label=label,
                    payment_hash=payment["hash"],
                )

    def _finish_shared_case(self):
        # Cross-method guards supplement, never replace, each method's
        # original funds/history/isolation and five-second assertions.
        self._check_prior_query_histories()
        payments, expected = self._query_prepared
        type(self)._query_checkpoints.append(
            {
                "case": self._testMethodName,
                "payments": payments,
                "expected": expected,
                "views": self._query_last_sample["views"],
            }
        )

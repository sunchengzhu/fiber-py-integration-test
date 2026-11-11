"""Shared CKB/FNN, with a fresh signer, credentials and channel for every method."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

import framework.config as framework_config

SIGNING_METHODS = {
    "TestInvalidSubscriptions": (
        "test_missing_token_does_not_disrupt_subscription",
        "test_invalid_token_does_not_disrupt_subscription",
        "test_missing_subscription_write_does_not_disrupt_subscription",
        "test_missing_channel_read_does_not_disrupt_subscription",
    ),
    "TestBrowserSigningSubscriptions": (
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
    ),
    "TestSigningSubscriptionFilters": (
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
    ),
    "TestSigningSubscriptions": (
        "test_initial_subscription_preserves_pending_request",
        "test_next_request_arrives_on_original_subscription",
        "test_reconnect_replays_unsubmitted_request",
        "test_sdk_reconnects_without_restart",
        "test_reconnect_replays_only_current_request",
        "test_same_tenant_connections_receive_independent_updates",
        "test_unsubscribe_preserves_other_subscriptions",
        "test_cross_connection_and_unknown_unsubscribe_preserve_subscriptions",
    ),
    "TestChannelSigningRetry": (
        "test_identical_retry_preserves_next_request",
        "test_conflicting_retry_preserves_original_receipt",
        "test_older_receipt_is_rejected_after_next_apply",
        "test_unsent_signature_recovers_after_disconnect",
        "test_applied_signature_recovers_after_http_timeout",
    ),
    "TestChannelSigningIsolation": (
        "test_pending_tenant_does_not_block_another_tenant",
        "test_tenant_cannot_read_another_tenants_signing_request",
        "test_tenant_cannot_submit_another_tenants_valid_signature",
    ),
}


@contextmanager
def _cleanup_cap(seconds):
    """Resource-only bound; never renew a business deadline."""
    handler = signal.getsignal(signal.SIGALRM)
    old = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expired(*_):
        raise TimeoutError("shared signing resource cleanup cap exhausted")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, old[0]) if old[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)
        if old[0] and old[0] > time.monotonic() - started:
            signal.setitimer(
                signal.ITIMER_REAL, old[0] - (time.monotonic() - started), old[1]
            )


class SigningEnvironment:
    @classmethod
    def setup_class(cls):
        cls._node_mode = os.environ.get("LSP_SIGNING_ENV_MODE", "independent")
        assert cls._node_mode in ("independent", "shared")
        cls._node_keep = os.environ.get("LSP_SIGNING_KEEP_RUNTIME") == "1"
        cls._node_owner = None
        cls._node_cases = []
        cls._node_checkpoints = []
        cls._node_failed = False
        cls._node_closed = False
        cls._node_cleanup_done = False
        cls._node_cleanup_errors = []
        cls._node_artifacts_owned = False
        cls._node_original_config = cls.lsp_config_extra
        cls._node_original_tmp = framework_config.TMP_PATH
        cls._node_identity_initial = None
        try:
            if cls._node_mode == "independent" and cls._node_keep:
                selected = json.loads(os.environ.get("LSP_REGRESSION_SELECTORS", "[]"))
                assert (
                    isinstance(selected, list) and len(selected) == 1
                ), "independent keep-runtime requires one method per serial job"
            if cls._node_mode == "shared":
                from test_cases.fiber.devnet.lsp._lsp_test import REVISION

                assert REVISION == "76307312e8de518c9a32074e6d16867c04de4f86"
                assert (
                    cls.__name__ in SIGNING_METHODS
                ), "class not qualified for signing reuse"
                assert os.environ.get(
                    "LSP_REGRESSION_SELECTORS"
                ), "use the serial runtime plugin"
                # Every method gets a distinct active tenant. Existing completed
                # tenants remain readable; do not evict/re-ensure them between cases.
                cls.lsp_config_extra = {
                    **cls.lsp_config_extra,
                    "max_active_tenants": len(SIGNING_METHODS[cls.__name__])
                    * len(getattr(cls, "tenant_labels", ("A",)))
                    + 1,
                }
            if cls._node_mode == "shared" or cls._node_keep:
                assert os.environ.get(
                    "LSP_RUN_ARTIFACTS"
                ), "fresh signing evidence path required"
                cls.tmp_path_name = "tmp/lsp-signing-" + uuid.uuid4().hex
                cls._node_artifacts = (
                    Path(os.environ["LSP_RUN_ARTIFACTS"]) / "node-environment"
                )
                cls._node_artifacts.mkdir(parents=True, exist_ok=False)
                cls._node_artifacts_owned = True
            super().setup_class()
        except BaseException as error:
            cls._node_failed = True
            if cls._node_mode == "shared" or cls._node_keep:
                try:
                    cls._stop_node_environment()
                except BaseException as cleanup:
                    error.add_note(f"shared class setup cleanup: {cleanup!r}")
            cls.lsp_config_extra = cls._node_original_config
            framework_config.TMP_PATH = cls._node_original_tmp
            raise

    def _bind_shared_signing_nodes(self, method, original_setup):
        if getattr(self, "_node_preparing", False):
            return False
        if self._node_mode != "shared":
            if self._node_keep:
                self._node_case_passed = False
                type(self)._node_cases.append(self)
            return False
        cls = type(self)
        assert not cls._node_failed and not getattr(
            cls, "_node_closed", False
        ), "signing environment invalidated; no rebuild/retry"
        assert (
            method.__name__ in SIGNING_METHODS[cls.__name__]
        ), "method not qualified for signing reuse"
        self._node_case_passed = False  # Set only by the native pytest report hook.
        cls._node_cases.append(self)
        try:
            if cls._node_owner is None:
                owner = type(self)()
                cls._node_owner = owner
                owner._node_preparing = True
                original_setup(owner, method)
            owner = cls._node_owner
            for name in ("fibers", "fiber1", "fiber2", "udtContract", "ws_url"):
                setattr(self, name, getattr(owner, name))
            self.new_fibers = []
            self.tenants = []
            self.did_pass = None
            self.beginNum = hex(self.node.getClient().get_tip_block_number())
            self._check_shared_signing_history()
            return True
        except BaseException:
            cls._node_failed = True
            raise

    def _sdk_directory(self, label):
        name = f"sdk-{label}"
        if self._node_mode == "shared":
            name += "-" + uuid.uuid4().hex
        return Path(self.fiber1.tmp_path) / name

    def _node_identity(self):
        from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import (
            _listener_pids,
            _pid_cwd,
        )

        pids = _listener_pids(self.ckb_rpc_port)
        assert (
            len(pids) == 1 and _pid_cwd(pids[0]) == Path(self.node.ckb_dir).resolve()
        ), pids
        assert all(f.process.poll() is None for f in self.fibers), "shared FNN exited"
        return {
            "ckb_pid": pids[0],
            "ckb_identity": subprocess.check_output(
                ["ps", "-p", str(pids[0]), "-o", "lstart=,command="], text=True
            ).strip(),
            "fnn_pids": [f.process.pid for f in self.fibers],
            "runtime": self.node.ckb_dir,
        }

    def _current_host_channels(self, channels):
        """Require the complete host set before applying per-case assertions."""
        if self._node_mode != "shared":
            return channels
        current = {t["channel_id"] for t in self.tenants}
        previous = {
            t["channel_id"]
            for checkpoint in type(self)._node_checkpoints
            for t in checkpoint["tenants"]
        }
        ids = [c["channel_id"] for c in channels]
        assert not current & previous, "channel identity reused between methods"
        assert len(ids) == len(set(ids)) and set(ids) == previous | current, (
            ids,
            previous,
            current,
        )
        return [c for c in channels if c["channel_id"] in current]

    @staticmethod
    def _ready_signing_view(client, channel_id):
        matches = [
            c
            for c in client.list_channels({})["channels"]
            if c["channel_id"] == channel_id
        ]
        assert len(matches) == 1, matches
        view = matches[0]
        assert (
            view["state"]["state_name"] == "ChannelReady"
            and not view["shutdown_transaction_hash"]
        ), view
        assert (
            int(view["offered_tlc_balance"], 16)
            == int(view["received_tlc_balance"], 16)
            == 0
        )
        assert not view["pending_tlcs"], view
        return {
            key: deepcopy(view[key])
            for key in (
                "channel_id",
                "channel_outpoint",
                "state",
                "local_balance",
                "remote_balance",
                "offered_tlc_balance",
                "received_tlc_balance",
                "pending_tlcs",
                "shutdown_transaction_hash",
            )
        }

    def _check_shared_signing_history(self, current=()):
        cls = type(self)
        with _cleanup_cap(10):
            identity = self._node_identity()
            if cls._node_identity_initial is None:
                cls._node_identity_initial = identity
            assert (
                identity == cls._node_identity_initial
            ), "shared node identity changed"
            previous = [
                t for checkpoint in cls._node_checkpoints for t in checkpoint["tenants"]
            ]
            ids = [t["status"]["tenant_id"] for t in (*previous, *current)]
            assert len(ids) == len(set(ids)), "tenant identity reused between methods"
            listed = self.fiber1.client.call("lsp_list_tenants", [])
            by_id = {t["tenant_id"]: t for t in listed["tenants"]}
            assert set(by_id) == set(ids), (by_id, ids)
            assert all(t["runtime_status"] == "active" for t in by_id.values()), listed
            # Only after operator-only liveness checks may old tenant RPCs run.
            history = []
            for checkpoint in cls._node_checkpoints:
                for tenant, expected in zip(checkpoint["tenants"], checkpoint["views"]):
                    own = self._ready_signing_view(
                        tenant["client"], tenant["channel_id"]
                    )
                    public = self._ready_signing_view(
                        self.fiber1.client, tenant["channel_id"]
                    )
                    assert [own, public] == expected, (
                        tenant["channel_id"],
                        own,
                        expected,
                    )
                    status = tenant["client"].call(
                        "get_channel_signing_status",
                        [{"channel_id": tenant["channel_id"]}],
                    )
                    assert status["status"]["type"] == "NoSignatureRequired", status
                    history.append(tenant["channel_id"])
        entry = {
            "identity": identity,
            "method": self._testMethodName,
            "prior_channels": history,
            "current_tenant_ids": [t["status"]["tenant_id"] for t in current],
        }
        (
            cls._node_artifacts
            / (self._testMethodName + ("-after.json" if current else "-before.json"))
        ).write_text(json.dumps(entry, indent=2) + "\n")

    def _shared_signing_teardown(self, method):
        if self._node_mode != "shared" and not self._node_keep:
            return False
        cls = type(self)
        try:
            if self._node_mode != "shared" and not getattr(
                self, "_node_case_passed", False
            ):
                cls._node_failed = True
            if self._node_mode == "shared":
                assert (
                    self._node_case_passed and not cls._node_failed
                ), "case failed; shared signing environment invalidated"
                self._check_shared_signing_history(self.tenants)
                snapshots = []
                for tenant in self.tenants:
                    own = self._ready_signing_view(
                        tenant["client"], tenant["channel_id"]
                    )
                    public = self._ready_signing_view(
                        self.fiber1.client, tenant["channel_id"]
                    )
                    assert own["channel_outpoint"] == public["channel_outpoint"]
                    assert (
                        own["local_balance"] == public["remote_balance"]
                        and own["remote_balance"] == public["local_balance"]
                    )
                    snapshots.append([own, public])
                cls._node_checkpoints.append(
                    {"tenants": list(self.tenants), "views": snapshots}
                )
        except BaseException:
            cls._node_failed = True
            raise
        finally:
            # This is a diagnostic live-node copy. The final class archive is
            # made only after every SDK and FNN has exited.
            try:
                self._archive_run()
            except BaseException:
                cls._node_failed = True
                raise
        return True

    @classmethod
    def _stop_node_environment(cls):
        from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import (
            _stop_verified_ckb,
        )
        from test_cases.fiber.devnet.lsp._lsp_test import stop_agent

        if getattr(cls, "_node_cleanup_done", False):
            return
        cls._node_closed = True
        if "_node_cleanup_errors" not in cls.__dict__:
            cls._node_cleanup_errors = []
        errors = cls._node_cleanup_errors

        def attempt(fn, *args):
            try:
                with _cleanup_cap(10):
                    fn(*args)
                return True
            except BaseException as error:
                errors.append(repr(error))
                return False

        for case in cls._node_cases:
            while case._cleanups:
                fn, args, kwargs = case._cleanups.pop()
                attempt(lambda fn=fn, args=args, kwargs=kwargs: fn(*args, **kwargs))
            for tenant in getattr(case, "tenants", []):
                attempt(stop_agent, tenant.get("agent"))
                for name in ("gate", "subscription_proxy"):
                    if tenant.get(name) is not None:
                        attempt(tenant[name].close)
            for observer in getattr(case, "observers", []):
                attempt(observer.close)
        owner = cls._node_owner
        if owner is not None:
            while owner._cleanups:
                fn, args, kwargs = owner._cleanups.pop()
                attempt(lambda fn=fn, args=args, kwargs=kwargs: fn(*args, **kwargs))
        fibers = {
            str(f.tmp_path): f
            for case in ([owner] if owner is not None else cls._node_cases)
            for f in getattr(case, "fibers", [])
        }
        for fiber in fibers.values():
            attempt(stop_agent, getattr(fiber, "process", None))
        if "node" in cls.__dict__:
            before = len(errors)
            attempt(lambda: errors.extend(_stop_verified_ckb(cls.node)))
            if len(errors) > before:
                # A partial/slow stop gets one bounded recovery attempt. Keep
                # the first error, even when resources exit during recovery.
                attempt(lambda: errors.extend(_stop_verified_ckb(cls.node)))

        def final_archive():
            target = cls._node_artifacts / "final"
            target.mkdir(parents=True, exist_ok=True)
            processes = [getattr(f, "process", None) for f in fibers.values()]
            processes += [
                t.get("agent")
                for c in cls._node_cases
                for t in getattr(c, "tenants", [])
            ]
            running = [p.pid for p in processes if p is not None and p.poll() is None]
            copied, manifest = [], []

            def archive(source, destination):
                shutil.copytree(source, destination, dirs_exist_ok=True)
                for path in source.rglob("*"):
                    if path.is_file():
                        copy = destination / path.relative_to(source)
                        with path.open("rb") as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        with copy.open("rb") as stream:
                            assert (
                                hashlib.file_digest(stream, "sha256").hexdigest()
                                == digest
                            )
                        manifest.append(
                            {"source": str(path), "copy": str(copy), "sha256": digest}
                        )

            if running:
                errors.append(f"owned processes still running: {running}")
            else:
                for i, fiber in enumerate(fibers.values(), 1):
                    copied.append(
                        attempt(archive, Path(fiber.tmp_path), target / f"fiber-{i}")
                    )

            def atomic_json(path, value):
                temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
                temporary.write_text(json.dumps(value, indent=2) + "\n")
                os.replace(temporary, path)

            atomic_json(target / "manifest.json", manifest)
            report = {
                "environment_invalidated": cls._node_failed or bool(errors),
                "errors": errors,
                "runtime": getattr(getattr(cls, "node", None), "ckb_dir", None),
                "completed_cases": len(cls._node_checkpoints),
                "fibers": list(fibers),
                "originals_retained": True,
                "live_processes": running,
                "archive_complete": not running
                and len(copied) == len(fibers)
                and all(copied),
            }
            atomic_json(target / "cleanup-status.json", report)

        if getattr(cls, "_node_artifacts_owned", False):
            try:
                final_archive()
            except BaseException as error:
                errors.append(repr(error))
        cls._node_failed = cls._node_failed or bool(errors)
        cls._node_cleanup_done = not errors
        if errors:
            raise AssertionError("shared signing cleanup: " + "; ".join(errors))

    @classmethod
    def teardown_class(cls):
        if cls._node_mode != "shared" and not cls._node_keep:
            return super().teardown_class()
        try:
            cls._stop_node_environment()
        finally:
            cls.lsp_config_extra = cls._node_original_config
            framework_config.TMP_PATH = cls._node_original_tmp

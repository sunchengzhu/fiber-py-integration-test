"""Full FNN restart keeps an InFlight hosted delivery as the same execution."""

import copy
import os
import subprocess
import time

from framework.test_fiber import wait_for_port
from test_cases.fiber.devnet.lsp._lsp_test import stop_agent
from test_cases.fiber.devnet.lsp.test_delivery_acceptance import _DeliveryBase


class TestDeliveryFnnRestart(_DeliveryBase):
    tenant_labels = ("A",)

    def _restart_public_t(self):
        old = self.fiber1.process
        assert old is not None and old.poll() is None
        old_pid = old.pid
        self.fiber1.stop()
        assert old.poll() is not None, "old Public T process did not exit"

        # The wrapper's events file is create_new; a restart must use a fresh
        # path while retaining the old file as evidence.
        old_events = self.events_path
        self.events_path = self.control_dir / f"events-restart-{int(time.time())}.jsonl"
        self.snapshot_event_offset = 0
        self.snapshot_last_sequence = 0
        self.host_process_env["LSP_DELIVERY_EVENTS"] = str(self.events_path)
        self.control_path.unlink(missing_ok=True)

        log_path = self.fiber1.tmp_path + "/node.log"
        with open(log_path, "a") as log:
            process = subprocess.Popen(
                [
                    self.host_binary,
                    "-c",
                    self.fiber1.fiber_config_path,
                    "-d",
                    self.fiber1.tmp_path,
                ],
                env={
                    **os.environ,
                    **self.fiber1.extra_env,
                    **self.host_process_env,
                    "FIBER_SECRET_KEY_PASSWORD": "password0",
                    "RUST_LOG": "info,fnn=debug",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        self.fiber1.process = process
        self.addCleanup(stop_agent, process)
        wait_for_port(self.fiber1.rpc_port, timeout=300, open=True)

        deadline = time.monotonic() + 120
        while True:
            try:
                status = self._delivery("status", deadline)
                break
            except (FileNotFoundError, ConnectionError, OSError):
                assert (
                    time.monotonic() < deadline
                ), "restarted delivery control did not recover"
                self._pause(deadline, 0.2)
        assert status["ready"], status

        # The public peer may reconnect automatically; a single explicit retry is
        # an environment prerequisite, not a delivery-recovery result.
        try:
            self.fiber2.connect_peer(self.fiber1)
        except Exception:
            pass
        while True:
            try:
                views = self._views(deadline)
            except Exception:
                assert (
                    time.monotonic() < deadline
                ), "channels did not recover after restart"
                self._pause(deadline, 0.2)
                continue
            if all(
                view["state"]["state_name"] == "ChannelReady" for view in views.values()
            ):
                break
            assert time.monotonic() < deadline, views
            self._pause(deadline, 0.2)
        self._record(
            "public_t_restarted",
            old_pid=old_pid,
            new_pid=process.pid,
            old_events=str(old_events),
            new_events=str(self.events_path),
        )

    @staticmethod
    def _upstream_tlc(snapshot, key):
        for channel in snapshot["channels"]:
            if channel["id"] != key["incoming_channel_id"]:
                continue
            for tlc in channel["tlcs"]:
                if str(tlc["id"]) == str(key["incoming_tlc_id"]):
                    return tlc
        raise AssertionError(("upstream TLC missing", key))

    @staticmethod
    def _matching_sessions(snapshot, key):
        return [
            entry for entry in snapshot["sessions"] if key in entry["previous_keys"]
        ]

    # TEST-MAP: LSP-DELIVERY-07
    def test_inflight_delivery_survives_full_fnn_restart(self):
        """
        1. 真实 P→T→A delivery 到达 InFlight 并扣住 A 的 settlement 签名。
        2. 记录原 delivery/key/attempt/TLC/session，停掉并重启整个 Public T。
        3. 重接 control，核对 store 投影和 LSP replay 仍返回原执行，不新建记录。
        """
        self._arm("observe")
        before = self._held_checkpoint()
        self.original_request = copy.deepcopy(before["captures"][0]["request"])
        self.original_record = copy.deepcopy(
            self._record_for(before, self.original_key)
        )
        before_tlc = self._upstream_tlc(before, self.original_key)
        before_sessions = self._matching_sessions(before, self.original_key)
        assert len(before_sessions) == 1, before_sessions
        before_session = copy.deepcopy(before_sessions[0])

        self._restart_public_t()

        after = self._snapshot_delivery(self.business_until)
        after_record = self._record_for(after, self.original_key)
        assert after_record["key"] == self.original_record["key"]
        assert after_record["request"] == self.original_record["request"]
        assert after_record["attempt_count"] == self.original_record["attempt_count"]
        assert after_record["status"] == self.original_record["status"]
        assert (
            len([d for d in after["deliveries"] if d["key"] == self.original_key]) == 1
        )
        assert self._upstream_tlc(after, self.original_key) == before_tlc

        after_sessions = self._matching_sessions(after, self.original_key)
        assert len(after_sessions) == 1, after_sessions
        assert (
            after_sessions[0]["session"]["created_at"]
            == before_session["session"]["created_at"]
        )
        assert (
            after_sessions[0]["session"]["request"]
            == before_session["session"]["request"]
        )
        assert len(after_sessions[0]["attempts"]) >= len(before_session["attempts"])

        replay = self._delivery(
            "replay_request",
            self.business_until,
            request=self.original_request,
        )
        assert replay["reply"].startswith("Ok(Ok("), replay
        assert replay["delivery"] is not None, replay
        assert replay["delivery"]["request"] == self.original_record["request"], replay
        assert (
            replay["delivery"]["attempt_count"] == self.original_record["attempt_count"]
        ), replay
        final = self._snapshot_delivery(self.business_until)
        assert [d for d in final["deliveries"] if d["key"] == self.original_key] == [
            after_record
        ], final
        self._record(
            "inflight_restart_verified",
            key=self.original_key,
            attempt_count=after_record["attempt_count"],
            replay=replay["reply"],
        )

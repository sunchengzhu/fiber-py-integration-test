"""Pause SDK submissions and inject transport faults without caching RPC results."""

import copy
import hashlib
import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests


class RetrySignatureGate:
    def __init__(self, upstream, forward_timeout=10):
        self.upstream = upstream
        self.forward_timeout = forward_timeout
        self.lock = threading.Lock()
        self._audit_records = []
        self._active = 0
        self._forward_count = 0
        self.captured = threading.Event()
        self.stopped = threading.Event()
        self.submission = None
        self.authorization = None
        self.submissions = {}
        self.attempts = []
        self.forwarded = []
        self.errors = []
        self.passthrough = False
        self.hold_watchtower = False
        self.watchtower_submissions = {}
        self.fault_mode = None
        self.fault_submission = None
        self.fault_started = None
        self.fault_applied = None
        self.client_closed = None
        self.on_fault = None
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received_at = time.monotonic()
                authorization = self.headers.get("Authorization", "")
                audit = {
                    "received_at": received_at,
                    "started_at": None,
                    "method": None,
                    "params": None,
                    "payload": None,
                    # Keep tokens out of the added header audit. The original
                    # gate.authorization remains available to existing tests.
                    "headers": {
                        "authorization_sha256": hashlib.sha256(
                            authorization.encode()
                        ).hexdigest(),
                        "content_type": self.headers.get("Content-Type"),
                        "user_agent": self.headers.get("User-Agent"),
                    },
                    "action": None,
                    "forward_started_at": None,
                    "forward_finished_at": None,
                    "reply": None,
                    "reply_sent_at": None,
                    "error": None,
                    "finished_at": None,
                }
                with gate.lock:
                    gate._audit_records.append(audit)
                    gate._active += 1
                try:
                    self.handle_rpc(audit)
                except (BrokenPipeError, ConnectionResetError) as error:
                    # An SDK request can expire while the test is pausing it.
                    with gate.lock:
                        audit["error"] = repr(error)
                except Exception as error:
                    with gate.lock:
                        audit["error"] = repr(error)
                        gate.errors.append(repr(error))
                    self.close_connection = True
                finally:
                    with gate.lock:
                        audit["finished_at"] = time.monotonic()
                        gate._active -= 1

            def handle_rpc(self, audit):
                with gate.lock:
                    audit["started_at"] = time.monotonic()
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                authorization = self.headers.get("Authorization", "")
                method = payload["method"]
                # Read-only RPCs such as node_info can have no parameters.
                params = payload["params"][0] if payload.get("params") else {}
                action = "forward"
                fault_triggered = False
                with gate.lock:
                    audit["payload"] = copy.deepcopy(payload)
                    audit["method"] = method
                    audit["params"] = copy.deepcopy(params)
                    if method == "submit_channel_signature":
                        gate.attempts.append((time.monotonic(), copy.deepcopy(params)))
                        if gate.authorization is None:
                            gate.authorization = authorization
                        assert gate.authorization == authorization
                        gate.submissions.setdefault(
                            params["request_id"], copy.deepcopy(params)
                        )
                        if gate.submission is None:
                            gate.submission = copy.deepcopy(params)
                            gate.captured.set()
                        if not gate.passthrough:
                            action = "pause"
                    if method == "submit_watchtower_signature":
                        gate.watchtower_submissions[params["request_id"]] = (
                            copy.deepcopy(params)
                        )
                        if gate.hold_watchtower:
                            action = "pause"
                    target = gate.fault_submission
                    if target and params.get("channel_id") == target["channel_id"]:
                        assert gate.authorization == authorization
                        if gate.fault_started is not None:
                            if gate.fault_mode == "disconnect":
                                action = "disconnect"
                        elif method == "submit_channel_signature" and params == target:
                            gate.fault_started = time.monotonic()
                            action = gate.fault_mode
                            fault_triggered = True
                    audit["action"] = action

                if fault_triggered and gate.on_fault is not None:
                    gate.on_fault(action)

                if action == "disconnect":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                if action == "pause":
                    reply = {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "error": {
                            "code": -32000,
                            "message": "test driver pauses this submission",
                        },
                    }
                else:
                    try:
                        with requests.Session() as session:
                            session.trust_env = False
                            with gate.lock:
                                audit["forward_started_at"] = time.monotonic()
                                gate._forward_count += 1
                            response = session.post(
                                gate.upstream,
                                json=payload,
                                headers={"Authorization": authorization},
                                timeout=gate.forward_timeout,
                            )
                            response.raise_for_status()
                            reply = response.json()
                            with gate.lock:
                                audit["reply"] = copy.deepcopy(reply)
                    finally:
                        with gate.lock:
                            audit["forward_finished_at"] = time.monotonic()
                    if method == "submit_channel_signature":
                        with gate.lock:
                            gate.forwarded.append((copy.deepcopy(params), reply))
                    if action == "lose_response":
                        assert reply.get("result") == {"type": "Applied"}, reply
                        with gate.lock:
                            gate.fault_applied = time.monotonic()
                        # Do not write headers, an error, or EOF. The SDK's own
                        # request deadline must cancel this socket first.
                        deadline = time.monotonic() + 60
                        while not gate.stopped.is_set():
                            readable, _, _ = select.select(
                                [self.connection], [], [], 0.2
                            )
                            if readable:
                                assert self.connection.recv(1, socket.MSG_PEEK) == b""
                                with gate.lock:
                                    gate.client_closed = time.monotonic()
                                self.close_connection = True
                                return
                            if time.monotonic() >= deadline:
                                raise AssertionError(
                                    "SDK did not cancel the unacknowledged request"
                                )
                        self.close_connection = True
                        return
                with gate.lock:
                    audit["reply"] = copy.deepcopy(reply)
                encoded = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                with gate.lock:
                    audit["reply_sent_at"] = time.monotonic()

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def audit_snapshot(self):
        """Return a consistent copy; payloads/replies are private test evidence."""
        with self.lock:
            return {
                "requests": copy.deepcopy(self._audit_records),
                "active": self._active,
                "received": len(self._audit_records),
                "forwarded": self._forward_count,
            }

    def arm_fault(self, mode, submission):
        assert mode in ("disconnect", "lose_response")
        with self.lock:
            assert self.fault_started is None
            self.fault_mode = mode
            self.fault_submission = copy.deepcopy(submission)

    def release(self):
        with self.lock:
            self.fault_mode = None
            self.fault_submission = None
            self.passthrough = True

    def close(self):
        self.stopped.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

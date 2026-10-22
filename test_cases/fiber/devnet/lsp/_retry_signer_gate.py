"""Pause SDK submissions and inject transport faults without caching RPC results."""

import copy
import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from test_cases.fiber.devnet.lsp._signer_gate import forward_events


class RetrySignatureGate:
    def __init__(self, upstream):
        self.upstream = upstream
        self.lock = threading.Lock()
        self.captured = threading.Event()
        self.stopped = threading.Event()
        self.submission = None
        self.authorization = None
        self.submissions = {}
        self.attempts = []
        self.queries = []
        self.pause_queries = False
        self.forwarded = []
        self.errors = []
        self.passthrough = False
        self.fault_mode = None
        self.fault_submission = None
        self.fault_started = None
        self.fault_applied = None
        self.client_closed = None
        self.repolled_at = None
        self.repolled = threading.Event()
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/lsp/events":
                    self.send_error(404)
                    return
                with gate.lock:
                    if gate.authorization is not None:
                        assert self.headers.get("Authorization") == gate.authorization
                    gate.queries.append(time.monotonic())
                    paused = gate.pause_queries
                    disconnected = (
                        gate.fault_started is not None
                        and gate.fault_mode == "disconnect"
                    )
                    if gate.fault_started is not None and gate.repolled_at is None:
                        gate.repolled_at = time.monotonic()
                        gate.repolled.set()
                if disconnected:
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                elif paused:
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    gate.forward_events(self)

            def do_POST(self):
                try:
                    self.handle_rpc()
                except (BrokenPipeError, ConnectionResetError):
                    # An SDK request can expire while the test is pausing it.
                    pass
                except Exception as error:
                    with gate.lock:
                        gate.errors.append(repr(error))
                    self.close_connection = True

            def handle_rpc(self):
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                authorization = self.headers.get("Authorization", "")
                method = payload["method"]
                params = payload["params"][0]
                action = "forward"
                with gate.lock:
                    if method == "get_channel_signing_status":
                        gate.queries.append(time.monotonic())
                        if gate.pause_queries:
                            action = "pause"
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
                    target = gate.fault_submission
                    if target and params.get("channel_id") == target["channel_id"]:
                        assert gate.authorization == authorization
                        if gate.fault_started is not None:
                            if method == "get_channel_signing_status":
                                if gate.repolled_at is None:
                                    gate.repolled_at = time.monotonic()
                                    gate.repolled.set()
                            if gate.fault_mode == "disconnect":
                                action = "disconnect"
                        elif method == "submit_channel_signature" and params == target:
                            gate.fault_started = time.monotonic()
                            action = gate.fault_mode

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
                    with requests.Session() as session:
                        session.trust_env = False
                        response = session.post(
                            gate.upstream,
                            json=payload,
                            headers={"Authorization": authorization},
                            timeout=10,
                        )
                        response.raise_for_status()
                        reply = response.json()
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
                encoded = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def forward_events(self, handler):
        forward_events(handler, self.upstream)

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

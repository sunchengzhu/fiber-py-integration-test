"""Observe real A/T broadcasts and delay one fixed window of A status replies."""

import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import urlsplit

from test_cases.fiber.devnet.lsp._commitment_broadcast_gate import _hash, _outpoint

MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_SEND_EVENTS = 4096
READ_METHODS = {"get_transaction", "get_transactions", "get_cells"}


class CompetingCloseObserver:
    """Forward original RPC bytes; no broadcast gate or synthetic CKB replies."""

    def __init__(self, upstream_url, directory):
        self.upstream_url = upstream_url
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.read_log = self.directory / "fnn-chain-reads.jsonl"
        self.broadcast_log = self.directory / "broadcasts.jsonl"
        self.lock = threading.Condition(threading.RLock())
        self.log_lock = threading.Lock()
        self.events = []
        self.errors = []
        self.timing_rule = None
        self.timing_episode = None
        self.delayed_queries = []
        self.active = 0
        self.stopped = False
        upstream = urlsplit(upstream_url)
        if upstream.scheme not in ("http", "https") or not upstream.hostname:
            raise ValueError("expected an HTTP(S) CKB upstream URL")
        self._upstream = upstream
        observer = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_POST(self):
                received = (time.monotonic(), int(time.time() * 1000))
                entry = delayed = None
                with observer.lock:
                    observer.active += 1
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY_BYTES:
                        raise ValueError("invalid CKB RPC Content-Length")

                    def stop_reading():
                        try:
                            self.connection.shutdown(socket.SHUT_RD)
                        except OSError:
                            pass

                    read_timer = threading.Timer(5, stop_reading)
                    read_timer.daemon = True
                    read_timer.start()
                    try:
                        raw = self.rfile.read(length)
                    finally:
                        read_timer.cancel()
                    if len(raw) != length:
                        raise ValueError("incomplete CKB RPC request body")
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError(
                            "CKB RPC batch/non-object request is unsupported"
                        )
                    entry = observer._entry(payload, raw, received)
                    status, content_type, body = observer._forward(
                        raw, self.headers, entry
                    )
                    delayed = observer._delay_status_response(entry)
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    self.wfile.flush()
                    written = time.monotonic()
                    with observer.lock:
                        entry["response_written_monotonic"] = written
                        entry["response_written_wall_ms"] = int(time.time() * 1000)
                        if delayed is not None:
                            delayed["released_monotonic"] = written
                            delayed["response_written_monotonic"] = written
                            release_at = observer.timing_episode["release_at"]
                            if not release_at <= written <= release_at + 0.100:
                                observer._failure(
                                    "A query response write missed fixed release tolerance",
                                    entry,
                                )
                    observer._persist(entry)
                except Exception as error:
                    observer._failure(
                        f"CKB observer failed: {type(error).__name__}: {error}", entry
                    )
                    if entry is not None:
                        try:
                            observer._persist(entry)
                        except OSError as log_error:
                            observer._failure(
                                f"cannot persist CKB observer failure: {log_error}"
                            )
                    # This is a transport/fixture failure, never a fabricated
                    # JSON-RPC result or a CKB rejection such as RBFRejected.
                    self.close_connection = True
                    try:
                        self.send_error(502, "LSP_TEST_CKB_OBSERVER_FAILED")
                    except (OSError, ValueError):
                        pass
                finally:
                    with observer.lock:
                        observer.active -= 1
                        observer.lock.notify_all()

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.thread.start()

    def _failure(self, message, entry=None):
        with self.lock:
            self.errors.append(message)
            if entry is not None:
                entry["failure"] = message
                entry["outcome"] = "error"

    def configure_query_timing(
        self, log_path, channel_id, remote_pubkey, deadline_monotonic
    ):
        """Bind A once, before D; only its real unknown replies may be delayed."""
        channel_id = _hash(channel_id)
        peer = remote_pubkey.removeprefix("0x").lower()
        if len(peer) != 66:
            raise ValueError("expected compressed remote public key")
        bytes.fromhex(peer)
        with self.lock:
            if self.stopped or self.timing_rule is not None:
                raise AssertionError(
                    "query timing already configured or observer stopped"
                )
            if time.monotonic() > deadline_monotonic - 5:
                raise AssertionError(
                    "less than 5 seconds left to configure query timing"
                )
            self.timing_rule = {
                "log_path": str(log_path),
                "channel_id": channel_id,
                "remote_pubkey": peer,
                "deadline_monotonic": deadline_monotonic,
                "delay_ms": 250,
                "configured_monotonic": time.monotonic(),
            }

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(
                {"armed": None, "events": self.events, "errors": self.errors}
            )

    def timing_snapshot(self):
        with self.lock:
            return copy.deepcopy(
                {
                    "rule": self.timing_rule,
                    "episode": self.timing_episode,
                    "delayed_queries": self.delayed_queries,
                }
            )

    def _entry(self, payload, raw, received):
        entry = {
            "request": payload,
            "raw_request": raw.decode(),
            "transaction": None,
            "inputs": [],
            "funding_outpoint": None,
            "message": None,
            "classification": "observed",
            "received_monotonic": received[0],
            "received_wall_ms": received[1],
            "forwarded_monotonic": None,
            "forwarded_wall_ms": None,
            "upstream_response_monotonic": None,
            "response_monotonic": None,
            "response_wall_ms": None,
            "response_written_monotonic": None,
            "response": None,
            "raw_response": None,
            "actual_hash": None,
            "outcome": "received",
        }
        with self.lock:
            if self.stopped:
                raise RuntimeError("CKB observer is stopping")
            if payload.get("method") == "send_transaction":
                if len(self.events) >= MAX_SEND_EVENTS:
                    raise RuntimeError("CKB send observation limit exceeded")
                self.events.append(entry)
                try:
                    entry["transaction"] = payload["params"][0]
                    entry["inputs"] = [
                        _outpoint(item["previous_output"])
                        for item in entry["transaction"]["inputs"]
                    ]
                except (KeyError, IndexError, TypeError, ValueError) as error:
                    self._failure(f"invalid send_transaction input: {error}", entry)
                    self._persist(entry)
                    raise
        return entry

    def _forward(self, raw, request_headers, entry):
        upstream = self._upstream
        connection_type = (
            http.client.HTTPSConnection
            if upstream.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(upstream.hostname, upstream.port, timeout=5)
        until = time.monotonic() + 5
        timed_out = threading.Event()
        active_socket = [None]

        def interrupt_socket():
            timed_out.set()
            sock = active_socket[0] or connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()

        timer = threading.Timer(5, interrupt_socket)
        timer.daemon = True
        timer.start()
        try:
            connection.connect()
            active_socket[0] = connection.sock
            connection.sock.settimeout(max(0.001, until - time.monotonic()))
            headers = {
                "Content-Type": request_headers.get("Content-Type", "application/json")
            }
            if request_headers.get("Authorization") is not None:
                headers["Authorization"] = request_headers["Authorization"]
            path = upstream.path or "/"
            if upstream.query:
                path += "?" + upstream.query
            with self.lock:
                entry["forwarded_monotonic"] = time.monotonic()
                entry["forwarded_wall_ms"] = int(time.time() * 1000)
            connection.request("POST", path, body=raw, headers=headers)
            response = connection.getresponse()
            body = response.read(MAX_BODY_BYTES + 1)
            done = time.monotonic()
            if timed_out.is_set() or done > until:
                raise TimeoutError("CKB upstream exceeded 5 second total budget")
            if len(body) > MAX_BODY_BYTES:
                raise ValueError("CKB upstream response body exceeded limit")
            with self.lock:
                entry.update(
                    {
                        "upstream_response_monotonic": done,
                        "response_monotonic": done,
                        "response_wall_ms": int(time.time() * 1000),
                        "http_status": response.status,
                        "raw_response": body.decode(errors="replace"),
                        "outcome": "forwarded",
                    }
                )
                try:
                    reply = json.loads(body)
                    entry["response"] = reply
                    if not isinstance(reply, dict):
                        raise ValueError("expected one CKB JSON-RPC response object")
                    if entry["request"].get("method") == "send_transaction":
                        if (
                            response.status == 200
                            and "result" in reply
                            and "error" not in reply
                        ):
                            entry["actual_hash"] = _hash(reply["result"])
                except (ValueError, TypeError) as error:
                    # Audit invalid upstream output, but return those exact
                    # bytes/status rather than changing what FNN receives.
                    self._failure(f"invalid CKB upstream response: {error}", entry)
            return (
                response.status,
                response.getheader("Content-Type", "application/json"),
                body,
            )
        finally:
            timer.cancel()
            connection.close()

    def _delay_status_response(self, entry):
        with self.lock:
            rule = copy.deepcopy(self.timing_rule)
            episode = copy.deepcopy(self.timing_episode)
        payload = entry["request"]
        if (
            rule is None
            or payload.get("method") != "get_transaction"
            or entry["received_monotonic"] < rule["deadline_monotonic"]
            or entry["http_status"] != 200
            or (episode and time.monotonic() >= episode["release_at"])
        ):
            return None
        reply = entry["response"]
        if (
            not isinstance(reply, dict)
            or "error" in reply
            or (reply.get("result") or {}).get("tx_status", {}).get("status")
            != "unknown"
        ):
            return None
        pattern = (
            r"Spawning InFlightCkbTxActor: tx_hash=Hash256\((0x[0-9a-f]{64})\), "
            r"tx_kind=Closing\(Pubkey\("
            + re.escape(rule["remote_pubkey"])
            + r"\), Hash256\("
            + re.escape(rule["channel_id"])
            + r"\), true\)"
        )
        with Path(rule["log_path"]).open("rb") as stream:
            log_bytes = stream.read(MAX_LOG_BYTES + 1)
        if len(log_bytes) > MAX_LOG_BYTES:
            raise ValueError("FNN log exceeds bounded A-hash binding read")
        matches = list(re.finditer(pattern, log_bytes.decode(errors="replace")))
        hashes = {match.group(1) for match in matches}
        if len(hashes) > 1:
            raise ValueError("ambiguous A closing hashes for channel and remote peer")
        if not hashes or payload.get("params", [None])[0] not in hashes:
            return None
        with self.lock:
            now = time.monotonic()
            if self.timing_episode is None:
                self.timing_episode = {
                    "transaction_hash": payload["params"][0],
                    "started_at": now,
                    "window_start": now,
                    "release_at": now + 0.250,
                    "source_log_match": matches[0].group(0),
                }
            release_at = self.timing_episode["release_at"]
            if now >= release_at:
                return None
            delayed = {
                "request": copy.deepcopy(payload),
                "response": copy.deepcopy(reply),
                "raw_response": entry["raw_response"],
                "received_monotonic": entry["received_monotonic"],
                "upstream_response_monotonic": entry["upstream_response_monotonic"],
                "release_at": release_at,
                "released_monotonic": None,
                "response_written_monotonic": None,
            }
            self.delayed_queries.append(delayed)
            entry["timing_release_at"] = release_at
        # A and T share this proxy. Never sleep with its lock held, and never
        # wait for T acceptance to decide when to release an A response.
        while time.monotonic() < release_at:
            time.sleep(max(0, release_at - time.monotonic()))
        return delayed

    def _persist(self, entry):
        method = entry["request"].get("method")
        path = self.broadcast_log if method == "send_transaction" else self.read_log
        if method != "send_transaction" and method not in READ_METHODS:
            return
        with self.lock:
            line = json.dumps(copy.deepcopy(entry), ensure_ascii=False) + "\n"
        with self.log_lock:
            with path.open("a") as stream:
                stream.write(line)

    def stop(self, until=None):
        """Stop this proxy within the caller's cleanup budget (default 8 s)."""
        until = time.monotonic() + 8 if until is None else until
        with self.lock:
            if self.stopped:
                return
            self.stopped = True
        stopper = threading.Thread(target=self.server.shutdown, daemon=True)
        stopper.start()
        stopper.join(timeout=max(0, until - time.monotonic()))
        self.server.server_close()
        self.thread.join(timeout=max(0, until - time.monotonic()))
        with self.lock:
            drained = self.lock.wait_for(
                lambda: self.active == 0, timeout=max(0, until - time.monotonic())
            )
            if not drained or self.thread.is_alive() or stopper.is_alive():
                self._failure("CKB observer did not stop within cleanup budget")

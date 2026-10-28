"""Isolate one competing commitment without synthesizing CKB acceptance."""

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
import time

import requests

MAX_REQUEST_BYTES = 10 * 1024 * 1024
MAX_SEND_EVENTS = 4096
REMOTE_ERROR = {
    "code": -32099,
    "message": "LSP_TEST_COMPETING_COMMITMENT_BLOCKED",
}


def _hash(value):
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise ValueError("expected a 32-byte hex hash")
    bytes.fromhex(value[2:])
    return value.lower()


def _outpoint(value):
    index = value["index"]
    index = int(index, 16) if isinstance(index, str) else index
    if type(index) is not int or not 0 <= index < 2**32:
        raise ValueError("invalid funding output index")
    return {"tx_hash": _hash(value["tx_hash"]), "index": hex(index)}


def _error_reply(identity, error):
    return json.dumps({"jsonrpc": "2.0", "id": identity, "error": error}).encode()


class CommitmentBroadcastGate:
    """A local CKB proxy; only armed funding spends are decoded and classified."""

    def __init__(self, upstream_url, decoder_path):
        self.upstream_url = upstream_url
        self.decoder_path = str(decoder_path)
        self.lock = threading.Condition(threading.RLock())
        self.events = []
        self.errors = []
        self.armed = None
        self.active = 0
        self.stopped = False
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_POST(self):
                received = (time.monotonic(), int(time.time() * 1000))
                with gate.lock:
                    gate.active += 1
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_REQUEST_BYTES:
                        raise ValueError("invalid CKB RPC Content-Length")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("incomplete CKB RPC request body")
                    payload = json.loads(raw)
                    # This client uses single requests. Reject the entire batch,
                    # rather than letting a target send bypass classification.
                    if not isinstance(payload, dict):
                        raise ValueError(
                            "CKB RPC batch/non-object request is unsupported"
                        )
                    status, content_type, body = gate._request(
                        payload, raw, self.headers.get("Authorization"), received
                    )
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as error:
                    gate._failure(
                        f"CKB proxy request failed: {type(error).__name__}: {error}"
                    )
                    body = _error_reply(
                        None,
                        {
                            "code": -32098,
                            "message": "LSP_TEST_CKB_PROXY_FAILED",
                        },
                    )
                    try:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except (OSError, ValueError):
                        pass
                finally:
                    with gate.lock:
                        gate.active -= 1
                        gate.lock.notify_all()

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # server_close must not join handlers without a timeout; stop() drains
        # them explicitly using the bounded active-handler wait below.
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self.thread.start()

    def _failure(self, message, event=None):
        with self.lock:
            self.errors.append(message)
            if event is not None:
                event["failure"] = message
                event["outcome"] = "error"

    def arm(self, funding_outpoint, local_message, remote_message, deadline_wall_ms):
        """Bind once, rejecting any previously received spend of this funding."""
        funding = _outpoint(funding_outpoint)
        local, remote = _hash(local_message), _hash(remote_message)
        with self.lock:
            assert (
                not self.stopped and self.armed is None
            ), "gate already armed or stopped"
            assert not self.errors, self.errors
            assert local != remote, "local and remote commitment messages must differ"
            wall_ms = int(time.time() * 1000)
            assert wall_ms <= deadline_wall_ms - 5000, "less than 5 seconds left to arm"
            prior = [event for event in self.events if funding in event["inputs"]]
            assert not prior, f"funding spend arrived before arming: {prior}"
            self.armed = {
                "funding_outpoint": funding,
                "local_message": local,
                "remote_message": remote,
                "deadline_wall_ms": deadline_wall_ms,
                "armed_monotonic": time.monotonic(),
                "armed_wall_ms": wall_ms,
            }
            return copy.deepcopy(self.armed)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(
                {
                    "armed": self.armed,
                    "events": self.events,
                    "errors": self.errors,
                }
            )

    def _request(self, payload, raw, authorization, received):
        event = None
        with self.lock:
            if self.stopped:
                raise RuntimeError("CKB proxy is stopping")
            if payload.get("method") == "send_transaction":
                if len(self.events) >= MAX_SEND_EVENTS:
                    raise RuntimeError("CKB send observation limit exceeded")
                event = {
                    "request": copy.deepcopy(payload),
                    "raw_request": raw.decode(),
                    "transaction": None,
                    "inputs": [],
                    "funding_outpoint": None,
                    "message": None,
                    "classification": "pre_arm" if self.armed is None else "other",
                    "received_monotonic": received[0],
                    "received_wall_ms": received[1],
                    "forwarded_monotonic": None,
                    "forwarded_wall_ms": None,
                    "response_monotonic": None,
                    "response_wall_ms": None,
                    "response": None,
                    "raw_response": None,
                    "actual_hash": None,
                    "outcome": "received",
                }
                self.events.append(event)
                # Parse all input references even before arming. Preserve a
                # malformed request as evidence instead of hiding its spend.
                try:
                    transaction = payload["params"][0]
                    event["transaction"] = copy.deepcopy(transaction)
                    event["inputs"] = [
                        _outpoint(item["previous_output"])
                        for item in transaction["inputs"]
                    ]
                except (KeyError, IndexError, TypeError, ValueError) as error:
                    event["classification"] = "invalid"
                    self._failure(f"invalid send_transaction input: {error}", event)
                    raise
            rule = copy.deepcopy(self.armed)

        if event is not None and rule and rule["funding_outpoint"] in event["inputs"]:
            with self.lock:
                event["funding_outpoint"] = rule["funding_outpoint"]
            try:
                if received[0] < rule["armed_monotonic"]:
                    raise ValueError("target funding spend received before arming")
                decoded = subprocess.run(
                    [self.decoder_path, "commitment-message"],
                    input=json.dumps(event["transaction"]),
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=2,
                )
                message = _hash(decoded.stdout.strip())
                classification = (
                    "local"
                    if message == rule["local_message"]
                    else "remote" if message == rule["remote_message"] else "unknown"
                )
                with self.lock:
                    event["message"] = message
                    event["classification"] = classification
                if classification == "unknown":
                    raise ValueError("unknown commitment spends target funding")
                if received[1] < rule["deadline_wall_ms"]:
                    raise ValueError(
                        "target commitment broadcast before its TLC deadline"
                    )
            except Exception as error:
                self._failure(
                    f"target transaction classification failed: {error}", event
                )
                reply = _error_reply(
                    payload.get("id"),
                    {
                        "code": -32098,
                        "message": "LSP_TEST_TARGET_COMMITMENT_INVALID",
                    },
                )
                self._record_response(event, 200, reply, "error")
                return 200, "application/json", reply
            if classification == "remote":
                reply = _error_reply(payload.get("id"), REMOTE_ERROR)
                self._record_response(event, 200, reply, "blocked")
                return 200, "application/json", reply

        # Original request bytes and the actual CKB status/body are preserved.
        # A rejected/failed upstream call is never converted into acceptance.
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        if event is not None:
            with self.lock:
                event["forwarded_monotonic"] = time.monotonic()
                event["forwarded_wall_ms"] = int(time.time() * 1000)
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(
                    self.upstream_url, data=raw, headers=headers, timeout=(1, 4)
                )
            if event is not None:
                self._record_response(
                    event, response.status_code, response.content, "forwarded"
                )
            return (
                response.status_code,
                response.headers.get("Content-Type", "application/json"),
                response.content,
            )
        except Exception as error:
            self._failure(
                f"CKB upstream forwarding failed: {type(error).__name__}: {error}",
                event,
            )
            raise

    def _record_response(self, event, status, raw, outcome):
        with self.lock:
            event["response_monotonic"] = time.monotonic()
            event["response_wall_ms"] = int(time.time() * 1000)
            event["http_status"] = status
            event["raw_response"] = raw.decode(errors="replace")
            event["outcome"] = outcome
            try:
                reply = json.loads(raw)
                event["response"] = reply
                if not isinstance(reply, dict):
                    raise ValueError("expected one CKB JSON-RPC response object")
                if outcome == "forwarded" and status == 200:
                    if "result" in reply and "error" not in reply:
                        event["actual_hash"] = _hash(reply["result"])
            except (ValueError, TypeError) as error:
                self._failure(f"invalid CKB send response: {error}", event)

    def stop(self):
        """Stop accepting calls and wait a bounded time for active handlers."""
        with self.lock:
            if self.stopped:
                return
            self.stopped = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        with self.lock:
            if not self.lock.wait_for(lambda: self.active == 0, timeout=8):
                self.errors.append("CKB proxy handlers did not stop within 8 seconds")

"""Hold a real SDK agent's first signature before it reaches the node."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import requests


class SignatureGate:
    def __init__(self, upstream):
        self.upstream = upstream
        self.lock = threading.Lock()
        self.captured = threading.Event()
        self.submission = None
        self.authorization = None
        self.released = False
        self.applied_response = None
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                authorization = self.headers.get("Authorization", "")
                reply = None
                if payload["method"] == "submit_channel_signature":
                    with gate.lock:
                        if not gate.released:
                            if gate.submission is None:
                                gate.submission = payload["params"][0]
                                gate.authorization = authorization
                                gate.captured.set()
                            # The agent retries its persisted signature; nothing is sent to FNN.
                            # Reply promptly because the SDK HTTP client has a 10-second timeout.
                            reply = {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "error": {
                                    "code": -32000,
                                    "message": "test driver holds signature",
                                },
                            }
                        elif payload["params"][0] == gate.submission:
                            # Deliver the real owner's response to an already waiting SDK call.
                            reply = {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": gate.applied_response,
                            }
                if reply is None:
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

    def apply_and_release(self, owner):
        # Serialize release with proxy handlers so no signature slips through first.
        with self.lock:
            assert self.submission is not None
            result = owner.call("submit_channel_signature", [self.submission])
            assert result == {"type": "Applied"}, result
            self.applied_response = result
            self.released = True

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

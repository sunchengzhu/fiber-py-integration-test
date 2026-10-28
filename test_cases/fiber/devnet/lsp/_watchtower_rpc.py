"""Audit the independent CKB source; faults are read-only adapter selfchecks."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import requests


class ChainAudit:
    def __init__(self, upstream, path, *, role="sdk-verifier", transparent=False):
        self.upstream, self.path = upstream, path
        self.role, self.transparent = role, transparent
        self.fault = None
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                started = time.monotonic()
                request = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                with requests.Session() as session:
                    session.trust_env = False
                    reply = session.post(
                        owner.upstream, json=request, timeout=10
                    ).json()
                fault = None if owner.transparent else owner.fault
                if fault == "canonical" and request["method"] == "get_header_by_number":
                    reply["result"]["hash"] = "0x" + "01" * 32
                elif (
                    fault == "transaction_hash"
                    and request["method"] == "get_transaction"
                ):
                    reply["result"]["transaction"]["hash"] = "0x" + "01" * 32
                elif (
                    fault == "contract_bytes"
                    and request["method"] == "get_live_cell"
                    and reply.get("result", {}).get("cell")
                ):
                    reply["result"]["cell"]["data"]["content"] = "0x00"
                with owner.lock, owner.path.open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "at": time.monotonic(),
                                "started": started,
                                "role": owner.role,
                                "request": request,
                                "reply": reply,
                                "selfcheck_fault": fault,
                            }
                        )
                        + "\n"
                    )
                body = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

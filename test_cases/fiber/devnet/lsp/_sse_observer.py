"""Bounded observation of real SSE bytes; no generated events or RPC results."""

import http.client
import json
import socket
import threading
import time
from urllib.parse import urlsplit

from test_cases.fiber.devnet.lsp._retry_signer_gate import RetrySignatureGate


class SseConnection:
    def __init__(self, url, headers, start=True):
        parsed = urlsplit(url)
        assert parsed.scheme == "http", "local devnet SSE only"
        self.started = time.monotonic()
        self.request_session = headers.get("x-lsp-session-id")
        self.events = []
        self.errors = []
        self.lock = threading.Lock()
        self.ended = threading.Event()
        self.cancelled = threading.Event()
        self.thread = None
        self.client = http.client.HTTPConnection(
            parsed.hostname, parsed.port, timeout=10
        )
        self.client.connect()
        self.socket = self.client.sock
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        try:
            self.client.request("GET", path, headers=headers)
            self.response = self.client.getresponse()
        except Exception:
            self.client.close()
            raise
        self.responded = time.monotonic()
        self.status = self.response.status
        self.session_id = self.response.getheader("x-lsp-session-id")
        self.content_type = self.response.getheader("Content-Type", "")
        self.body = b""
        self.socket.settimeout(65)
        if self.status != 200:
            self.body = self.response.read(65536)
            self.response.close()
            self.client.close()
            self.ended.set()
        elif start:
            self.start()

    def start(self, on_line=None):
        assert self.status == 200 and self.thread is None
        self.thread = threading.Thread(target=self._read, args=(on_line,), daemon=True)
        self.thread.start()

    def _read(self, on_line):
        name, data, frame_size = None, [], 0
        try:
            while not self.cancelled.is_set():
                line = self.response.readline(10 * 1024 * 1024 + 1)
                if not line:
                    break
                frame_size += len(line)
                assert frame_size <= 10 * 1024 * 1024, "oversized SSE frame"
                if on_line:
                    on_line(line)
                value = line.decode("utf-8").rstrip("\r\n")
                if not value:
                    if data:
                        payload = json.loads("\n".join(data))
                        assert payload["version"] == 1, payload
                        assert payload["type"] == name, payload
                        with self.lock:
                            assert (
                                len(self.events) < 256
                            ), "SSE observation limit exceeded"
                            self.events.append((time.monotonic(), name, payload))
                    name, data, frame_size = None, [], 0
                elif value.startswith("event:"):
                    name = value[6:].lstrip(" ")
                elif value.startswith("data:"):
                    data.append(value[5:].lstrip(" "))
        except Exception as error:
            if not self.cancelled.is_set():
                self.errors.append(repr(error))
        finally:
            self.response.close()
            self.client.close()
            self.ended.set()

    def frames(self):
        with self.lock:
            return list(self.events)

    def close(self):
        self.cancelled.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if self.thread:
            self.thread.join(timeout=5)
            assert not self.thread.is_alive(), "SSE reader did not exit"
        else:
            self.response.close()
            self.client.close()
            self.ended.set()


class ObservedSignatureGate(RetrySignatureGate):
    def __init__(self, upstream):
        self.streams = []
        self.downstreams = {}
        super().__init__(upstream)

    def forward_events(self, handler):
        headers = {
            key: handler.headers[key]
            for key in ("Authorization", "Accept", "x-lsp-session-id")
            if key in handler.headers
        }
        stream = SseConnection(self.upstream + "/lsp/events", headers, start=False)
        with self.lock:
            self.streams.append(stream)
            self.downstreams[stream] = handler.connection
        try:
            handler.send_response(stream.status)
            for name in ("Content-Type", "x-lsp-session-id", "Retry-After"):
                value = stream.response.getheader(name)
                if value:
                    handler.send_header(name, value)
            if stream.status != 200:
                handler.send_header("Content-Length", str(len(stream.body)))
            handler.end_headers()
            handler.wfile.flush()
            if stream.status != 200:
                handler.wfile.write(stream.body)
                return

            def relay(line):
                handler.wfile.write(line)
                handler.wfile.flush()

            stream.start(relay)
            # The real server caps a stream at 300 seconds. Cleanup can cancel sooner.
            assert stream.ended.wait(310), "upstream SSE exceeded its lifetime"
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stream.close()
            handler.close_connection = True

    def connections(self):
        with self.lock:
            return list(self.streams)

    def cut(self, stream):
        # Close both real sockets, not merely future GETs or a client timeout.
        stream.cancelled.set()
        with self.lock:
            downstream = self.downstreams[stream]
        try:
            downstream.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        stream.close()

    def close_streams(self):
        for stream in self.connections():
            if not stream.ended.is_set():
                self.cut(stream)

    def close(self):
        self.close_streams()
        super().close()

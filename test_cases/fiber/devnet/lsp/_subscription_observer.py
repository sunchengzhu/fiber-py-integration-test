"""Observe and gate real signing subscriptions without synthesizing RPC results."""

import json
import socket
import threading
import time
from urllib.parse import urlsplit

from websockets.exceptions import ConnectionClosed
from websockets.protocol import State
from websockets.sync.client import connect
from websockets.sync.server import serve

MAX_MESSAGE_SIZE = 10 * 1024 * 1024
MAX_OBSERVATIONS = 4096


def _append(items, item):
    assert len(items) < MAX_OBSERVATIONS, "subscription observation limit exceeded"
    items.append(item)


def _notification(message):
    if message.get("method") != "subscribe" or "id" in message:
        return None
    params = message["params"]
    identity, result = params["subscription"], params["result"]
    assert type(identity) in (str, int), message
    assert isinstance(result, dict) and "type" in result and "data" in result, message
    return identity, result


def _same_id(left, right):
    return type(left) is type(right) and left == right


class SubscriptionRpcError(RuntimeError):
    def __init__(self, response):
        self.response = response
        super().__init__(str(response["error"]))


class SubscriptionObserver:
    """One read-only connection, with independent subscriptions and bounded waits."""

    def __init__(self, url, headers=None, *, subprotocols=None, open_timeout=10):
        assert urlsplit(url).scheme == "ws", "local devnet WS only"
        self.started = time.monotonic()
        self.errors = []
        self.ended = threading.Event()
        self.cancelled = threading.Event()
        self.lock = threading.Condition(threading.RLock())
        self.events = []
        self.messages = []
        self.responses = {}
        self.next_id = 0
        self.client = connect(
            url,
            additional_headers=headers or {},
            subprotocols=subprotocols,
            compression=None,
            proxy=None,
            open_timeout=open_timeout,
            close_timeout=2,
            ping_interval=None,
            max_size=MAX_MESSAGE_SIZE,
        )
        self.responded = time.monotonic()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for raw in self.client:
                message = json.loads(raw)
                now = time.monotonic()
                with self.lock:
                    _append(self.messages, {"time": now, "message": message})
                    event = _notification(message)
                    if event is not None:
                        _append(self.events, (now, *event))
                    elif "id" in message:
                        identity = message["id"]
                        self.responses[(type(identity), identity)] = message
                    self.lock.notify_all()
        except ConnectionClosed:
            pass
        except Exception as error:
            if not self.cancelled.is_set():
                with self.lock:
                    self.errors.append(repr(error))
        finally:
            self.ended.set()
            with self.lock:
                self.lock.notify_all()

    def request(self, method, params, timeout=10):
        """Return the untouched envelope, including real subscription RPC errors."""
        deadline = time.monotonic() + timeout
        with self.lock:
            self.next_id += 1
            identity = self.next_id
            self.client.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": identity,
                        "method": method,
                        "params": params,
                    }
                )
            )
            key = (int, identity)
            while key not in self.responses:
                assert not self.errors, self.errors
                assert not self.ended.is_set(), f"WS ended before {method} response"
                remaining = deadline - time.monotonic()
                assert remaining > 0, f"timed out waiting for {method} response"
                self.lock.wait(remaining)
            return self.responses.pop(key)

    call = request

    def subscribe(self, topic="channel_signing", options=None):
        params = [topic] if options is None else [topic, options]
        response = self.request("subscribe", params)
        if "error" in response:
            raise SubscriptionRpcError(response)
        identity = response["result"]
        assert type(identity) in (str, int), response
        return identity

    def unsubscribe(self, identity):
        response = self.request("unsubscribe", [identity])
        if "error" in response:
            raise SubscriptionRpcError(response)
        assert type(response["result"]) is bool, response
        return response["result"]

    def frames(self):
        with self.lock:
            return list(self.events)

    def notifications(self):
        with self.lock:
            return [item for item in self.messages if _notification(item["message"])]

    def mark(self):
        return time.monotonic()

    def wait_event(self, identity, predicate, timeout=60, after=0):
        deadline = time.monotonic() + timeout
        with self.lock:
            while True:
                assert not self.errors, self.errors
                for at, subscription, result in self.events:
                    if (
                        at >= after
                        and _same_id(subscription, identity)
                        and predicate(result)
                    ):
                        return result
                assert not self.ended.is_set(), "subscription connection ended"
                remaining = deadline - time.monotonic()
                assert remaining > 0, "timed out waiting for subscription event"
                self.lock.wait(remaining)

    def close(self):
        self.cancelled.set()
        self.client.close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "subscription observer did not exit"


SubscriptionConnection = SubscriptionObserver


class ProxyConnection:
    """Evidence for one actual SDK-to-FNN connection pair."""

    def __init__(self, downstream, lock):
        self.downstream = downstream
        self.upstream = None
        self.lock = lock
        self.started = time.monotonic()
        self.connected_at = None
        self.ended = threading.Event()
        self.cancelled = threading.Event()
        self.errors = []
        self.transport_errors = []
        self.requests = []
        self.responses = []
        self.subscriptions = []
        self.events = []
        self.delivered_events = []
        self.notifications = []
        self.pending = {}
        self.frozen = False

    def frames(self):
        """Typed notifications received from FNN, before the delivery gate."""
        with self.lock:
            return list(self.events)

    def delivered_frames(self):
        """Typed notifications whose exact message was sent to the SDK socket."""
        with self.lock:
            return list(self.delivered_events)


class SubscriptionProxy:
    """Forward real JSON-RPC messages, with explicit transport fault checkpoints.

    Pausing notifications is a synchronous delivery barrier. Resuming closes all
    connections exposed to that barrier: buffered updates are never released as
    if they were the FNN's pending-state replay on a new connection.
    """

    def __init__(self, upstream):
        assert urlsplit(upstream).scheme == "ws", "local devnet WS only"
        self.upstream = upstream
        self.lock = threading.Condition(threading.RLock())
        self.stopped = threading.Event()
        self.errors = []
        self.streams = []
        self.notifications_paused = False
        self.subscriptions_paused = False
        self.server = serve(
            self._handle,
            "127.0.0.1",
            0,
            compression=None,
            open_timeout=10,
            close_timeout=2,
            ping_interval=None,
            max_size=MAX_MESSAGE_SIZE,
        )
        self.url = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def connections(self):
        with self.lock:
            return list(self.streams)

    def subscribe_attempts(self):
        with self.lock:
            return [
                (item["time"], link, item["message"])
                for link in self.streams
                for item in link.requests
                if item["message"].get("method") == "subscribe"
            ]

    def successful_subscriptions(self):
        with self.lock:
            return [
                (item["delivered_at"], link, item["subscription_id"], item["topic"])
                for link in self.streams
                for item in link.subscriptions
                if "subscription_id" in item and "delivered_at" in item
            ]

    def _handle(self, downstream):
        link = ProxyConnection(downstream, self.lock)
        with self.lock:
            link.frozen = self.notifications_paused
            _append(self.streams, link)
        outgoing = None
        try:
            headers = {}
            if "Authorization" in downstream.request.headers:
                headers["Authorization"] = downstream.request.headers["Authorization"]
            upstream = connect(
                self.upstream,
                additional_headers=headers,
                compression=None,
                proxy=None,
                open_timeout=10,
                close_timeout=2,
                ping_interval=None,
                max_size=MAX_MESSAGE_SIZE,
            )
            with self.lock:
                link.upstream = upstream
                link.connected_at = time.monotonic()
                cancelled = link.cancelled.is_set() or self.stopped.is_set()
            if cancelled:
                return
            outgoing = threading.Thread(
                target=self._relay, args=(link, True), daemon=True
            )
            outgoing.start()
            self._relay(link, False)
        except (ConnectionClosed, OSError, TimeoutError) as error:
            if not link.cancelled.is_set():
                link.transport_errors.append(repr(error))
        except Exception as error:
            with self.lock:
                link.errors.append(repr(error))
                self.errors.append(repr(error))
        finally:
            self.cut(link)
            if outgoing:
                outgoing.join(timeout=5)
                if outgoing.is_alive():
                    with self.lock:
                        self.errors.append("SDK request relay did not exit")
            link.ended.set()

    def _relay(self, link, from_sdk):
        source = link.downstream if from_sdk else link.upstream
        destination = link.upstream if from_sdk else link.downstream
        try:
            while self._active(link):
                try:
                    raw = source.recv(timeout=0.2)
                except TimeoutError:
                    continue
                message = json.loads(raw)
                now = time.monotonic()
                with self.lock:
                    if from_sdk:
                        self._forward_request(link, destination, raw, message, now)
                    else:
                        self._forward_response(link, destination, raw, message, now)
        except (ConnectionClosed, OSError):
            pass
        except Exception as error:
            if not link.cancelled.is_set() and not self.stopped.is_set():
                with self.lock:
                    link.errors.append(repr(error))
                    self.errors.append(repr(error))
        finally:
            self.cut(link)

    def _forward_request(self, link, destination, raw, message, now):
        record = {"time": now, "message": message, "forwarded_at": None}
        _append(link.requests, record)
        subscription = None
        if message.get("method") == "subscribe":
            subscription = {
                "attempted_at": now,
                "forwarded_at": None,
                "responded_at": None,
                "id": message["id"],
                "topic": message["params"][0],
            }
            _append(link.subscriptions, subscription)
            link.pending[(type(message["id"]), message["id"])] = subscription
            self._wait_gate(link, "subscriptions_paused")
        if not self._active(link):
            return
        destination.send(raw)
        record["forwarded_at"] = time.monotonic()
        if subscription is not None:
            subscription["forwarded_at"] = record["forwarded_at"]

    def _forward_response(self, link, destination, raw, message, now):
        record = {"time": now, "message": message, "delivered_at": None}
        _append(link.responses, record)
        event = _notification(message)
        subscription = None
        if event is not None:
            _append(link.events, (now, *event))
            _append(link.notifications, record)
            self._wait_gate(link, "notifications_paused")
        elif "id" in message:
            subscription = link.pending.get((type(message["id"]), message["id"]))
            if subscription is not None:
                subscription["responded_at"] = now
                subscription["response"] = message
                if "result" in message:
                    identity = message["result"]
                    assert type(identity) in (str, int), message
                    subscription["subscription_id"] = identity
        if not self._active(link):
            return
        destination.send(raw)
        record["delivered_at"] = time.monotonic()
        if subscription is not None:
            subscription["delivered_at"] = record["delivered_at"]
        if event is not None:
            _append(link.delivered_events, (record["delivered_at"], *event))

    def _active(self, link):
        return (
            not link.cancelled.is_set()
            and not self.stopped.is_set()
            and link.downstream.state is State.OPEN
            and link.upstream.state is State.OPEN
        )

    def _wait_gate(self, link, flag):
        deadline = time.monotonic() + 120
        while getattr(self, flag) and self._active(link):
            assert (
                time.monotonic() < deadline
            ), f"{flag} exceeded 120-second test budget"
            self.lock.wait(0.2)

    def pause_notifications(self):
        with self.lock:
            self.notifications_paused = True
            for link in self.streams:
                if not link.ended.is_set():
                    link.frozen = True
            return time.monotonic()

    def pause_subscriptions(self):
        with self.lock:
            self.subscriptions_paused = True
            return time.monotonic()

    def freeze(self):
        with self.lock:
            self.pause_notifications()
            self.pause_subscriptions()
            return time.monotonic()

    def resume_subscriptions(self):
        with self.lock:
            self.subscriptions_paused = False
            self.lock.notify_all()

    def resume(self):
        with self.lock:
            frozen = [
                link for link in self.streams if link.frozen and not link.ended.is_set()
            ]
            # Mark closed before notifying either relay. Old buffered messages
            # must not slip through between clearing the gates and socket close.
            for link in frozen:
                link.cancelled.set()
            self.notifications_paused = False
            self.subscriptions_paused = False
            self.lock.notify_all()
        for link in frozen:
            self.cut(link)

    release = resume

    def cut(self, link):
        """Cut both actual sockets, rather than simulating an RPC failure."""
        with self.lock:
            link.cancelled.set()
            sockets = [link.downstream, link.upstream]
            self.lock.notify_all()
        for connection in sockets:
            if connection is not None:
                try:
                    connection.socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()

    def close_streams(self):
        for link in self.connections():
            if not link.ended.is_set():
                self.cut(link)

    def close(self):
        self.stopped.set()
        self.server.shutdown()
        self.close_streams()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "subscription proxy listener did not exit"
        for link in self.connections():
            assert link.ended.wait(15), "subscription proxy connection did not exit"

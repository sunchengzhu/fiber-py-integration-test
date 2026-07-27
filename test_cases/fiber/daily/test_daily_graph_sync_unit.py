"""Deterministic, no-network unit tests for the daily graph-sync engine.

These exercise the state machine, incremental log parsing, pagination fail-closed
behaviour, digest content-sensitivity, config validation, the failure lifecycle
and cleanup handling without spawning fnn or touching the public network.

They are wired into CI by the ``daily_graph_sync_unit_test`` make target (run in
the Lint-and-Format workflow on every push/PR and again in the daily workflow
before the long E2E). They are NOT gated behind DAILY_SYNC_ENABLED, so they also
run on a plain ``pytest test_cases/fiber/daily/test_daily_graph_sync_unit.py``.
"""

import json
import os
import signal
import subprocess
import tempfile

import pytest

import framework.daily_graph_sync as dgs
from framework.daily_graph_sync import (
    AggregateReader,
    CleanupError,
    ConfigError,
    DailySyncNode,
    DeadlineExceeded,
    GraphError,
    NodeExited,
    NodeLogError,
    SyncAggregate,
    _channels_digest,
    _extract_commit_token,
    _is_retryable,
    _merge_channel,
    _merge_node,
    _nodes_digest,
    _to_int,
    parse_announced_addrs,
    parse_bootnodes,
    validate_public_ckb_url,
)

import time


# --------------------------------------------------------------------------
# A2 state machine
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "total,finished,active,passive,expected",
    [
        (2, 2, 0, 0, True),  # all finished
        (2, 0, 0, 2, True),  # all flipped to passive (the P0 case)
        (3, 1, 0, 2, True),  # mix of finished + passive, none active
        (2, 1, 1, 0, False),  # one still actively syncing
        (0, 0, 0, 0, False),  # no peers -> never "complete"
        (3, 1, 0, 1, False),  # finished+passive != total
    ],
)
def test_all_connected_finished(total, finished, active, passive, expected):
    assert (
        SyncAggregate(total, finished, active, passive).all_connected_finished
        is expected
    )


# --------------------------------------------------------------------------
# Incremental node.log reader
# --------------------------------------------------------------------------
def _agg_line(total, finished, active, passive):
    return (
        f"\x1b[2mts\x1b[0m TRACE fnn::fiber::gossip: num of peers: {total}, "
        f"num of finished syncing peers: {finished}, "
        f"num of active syncing peers: {active}, "
        f"num of passive syncing peers: {passive}\n"
    ).encode()


def test_reader_multiple_aggregates_single_poll():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "node.log")
    with open(p, "wb") as f:
        f.write(_agg_line(2, 1, 1, 0))
        f.write(_agg_line(2, 2, 0, 0))
    r = AggregateReader(p)
    agg = r.poll()
    assert (agg.total, agg.finished, agg.active, agg.passive) == (2, 2, 0, 0)
    assert r.ever_finished is True


def test_reader_half_line_carry_and_ever_finished_preserved():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "node.log")
    open(p, "wb").close()
    r = AggregateReader(p)
    # a finished>0 aggregate, then a partial line
    with open(p, "ab") as f:
        f.write(_agg_line(2, 1, 1, 0))
        f.write(b"ts TRACE fnn::fiber::gossip: num of peers: 2, num of finished ")
    agg = r.poll()
    assert agg.finished == 1  # partial line not parsed yet
    assert r.ever_finished is True
    # complete the partial line as an all-passive (finished=0) aggregate
    with open(p, "ab") as f:
        f.write(
            b"syncing peers: 0, num of active syncing peers: 0, "
            b"num of passive syncing peers: 2\n"
        )
    agg2 = r.poll()
    assert (agg2.finished, agg2.active, agg2.passive) == (0, 0, 2)
    assert agg2.all_connected_finished is True
    assert r.ever_finished is True  # preserved across the finished->passive flip


def test_reader_size_cap_fails_closed():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "node.log")
    with open(p, "wb") as f:
        f.write(_agg_line(1, 1, 0, 0))
    r = AggregateReader(p, max_bytes=5)
    with pytest.raises(NodeLogError):
        r.poll()
    assert r.capped is True


def test_reader_detects_truncation():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "node.log")
    with open(p, "wb") as f:
        f.write(_agg_line(2, 2, 0, 0))
    r = AggregateReader(p)
    r.poll()
    with open(p, "wb") as f:  # shrink/rotate under us
        f.write(b"short\n")
    with pytest.raises(NodeLogError):
        r.poll()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def test_to_int_variants():
    assert _to_int("0x10") == 16
    assert _to_int(5) == 5
    assert _to_int("7") == 7
    assert _to_int(None) == 0
    assert _to_int("not-a-number") == 0


def test_extract_commit_token():
    assert _extract_commit_token("bc361aa 2026-07-02") == "bc361aa"
    assert _extract_commit_token("abcdef1234567890") == "abcdef1234567890"
    assert _extract_commit_token("") == ""
    assert _extract_commit_token("no-hex-here") == ""
    # a leading short hex run is what fnn's node_info reports
    assert _extract_commit_token("deadbee dirty") == "deadbee"


# --------------------------------------------------------------------------
# Digests: content-sensitive, order-independent, self-excluded
# --------------------------------------------------------------------------
def test_nodes_digest_order_independent_and_case_insensitive():
    a = [
        {"pubkey": "0xAA", "timestamp": "0x1", "node_name": "a"},
        {"pubkey": "0xBB", "timestamp": 2, "node_name": "b"},
    ]
    b = list(reversed(a))
    assert _nodes_digest(a) == _nodes_digest(b)


def test_nodes_digest_reacts_to_content_change():
    base = [{"pubkey": "0xAA", "timestamp": 1, "node_name": "a", "addresses": ["x"]}]
    changed = [{"pubkey": "0xAA", "timestamp": 2, "node_name": "a", "addresses": ["x"]}]
    addr = [{"pubkey": "0xAA", "timestamp": 1, "node_name": "a", "addresses": ["y"]}]
    assert _nodes_digest(base) != _nodes_digest(changed)
    assert _nodes_digest(base) != _nodes_digest(addr)


def test_nodes_digest_self_exclusion():
    nodes = [{"pubkey": "0xAA", "timestamp": 1}, {"pubkey": "0xBB", "timestamp": 1}]
    assert _nodes_digest(nodes, self_pubkey="0xaa") != _nodes_digest(nodes)


def test_channels_digest_reacts_to_update_change():
    base = [
        {
            "channel_outpoint": "0xC1",
            "node1": "0xAA",
            "node2": "0xBB",
            "created_timestamp": 1,
            "update_info_of_node1": {"timestamp": 5, "enabled": True, "fee_rate": 1},
            "update_info_of_node2": None,
        }
    ]
    changed = [dict(base[0], update_info_of_node1={"timestamp": 6, "enabled": False})]
    assert _channels_digest(base) != _channels_digest(changed)
    # order independence
    two = base + [dict(base[0], channel_outpoint="0xC2")]
    assert _channels_digest(two) == _channels_digest(list(reversed(two)))


@pytest.mark.parametrize(
    "field,changed_value",
    [
        ("chain_hash", "0x02"),
        ("auto_accept_min_ckb_funding_amount", "0x65"),
        (
            "udt_cfg_infos",
            [{"name": "USDI", "script": {"code_hash": "0x02", "hash_type": "type"}}],
        ),
    ],
)
def test_nodes_digest_covers_all_node_announcement_fields(field, changed_value):
    base_node = {
        "pubkey": "0xAA",
        "timestamp": 1,
        "node_name": "alice",
        "version": "1.0",
        "addresses": ["/ip4/1.1.1.1/tcp/8228"],
        "features": [1, 2],
        "chain_hash": "0x01",
        "auto_accept_min_ckb_funding_amount": "0x64",
        "udt_cfg_infos": [
            {"name": "USDI", "script": {"code_hash": "0x01", "hash_type": "type"}}
        ],
    }
    changed_node = dict(base_node, **{field: changed_value})
    assert _nodes_digest([base_node]) != _nodes_digest([changed_node])


@pytest.mark.parametrize(
    "field,changed_value",
    [
        ("capacity", "0x65"),
        ("chain_hash", "0x02"),
        (
            "udt_type_script",
            {"code_hash": "0x02", "hash_type": "type", "args": "0xbb"},
        ),
    ],
)
def test_channels_digest_covers_all_channel_announcement_fields(field, changed_value):
    base_channel = {
        "channel_outpoint": "0xC1",
        "node1": "0xAA",
        "node2": "0xBB",
        "created_timestamp": 1,
        "capacity": "0x64",
        "chain_hash": "0x01",
        "udt_type_script": {
            "code_hash": "0x01",
            "hash_type": "type",
            "args": "0xaa",
        },
        "update_info_of_node1": {"timestamp": 2, "enabled": True},
        "update_info_of_node2": {"timestamp": 3, "enabled": True},
    }
    changed_channel = dict(base_channel, **{field: changed_value})
    assert _channels_digest([base_channel]) != _channels_digest([changed_channel])


# --------------------------------------------------------------------------
# CKB URL validation (fail closed)
# --------------------------------------------------------------------------
def test_validate_public_ckb_url():
    # clean public endpoints and a loopback http node are accepted
    validate_public_ckb_url("https://testnet.ckbapp.dev/")
    validate_public_ckb_url("https://mainnet.ckbapp.dev")
    validate_public_ckb_url("http://127.0.0.1:8114/")  # loopback http allowed
    validate_public_ckb_url("http://localhost:8114")
    for bad in (
        "https://host/secret-token",  # a path token must now be rejected
        "https://user@host/",
        "https://host/?token=abc",
        "https://host/#frag",
        "http://8.8.8.8/",  # plain http to a non-loopback host
        "ftp://host/",
        "https://",  # no hostname
    ):
        with pytest.raises(ConfigError):
            validate_public_ckb_url(bad)


# --------------------------------------------------------------------------
# Config parsing / prepare() validation
# --------------------------------------------------------------------------
_GOOD_CONFIG = """fiber:
  listening_addr: /ip4/0.0.0.0/tcp/8228
  announced_addrs:
    # - /ip4/1.2.3.4/tcp/8228   example only, commented
  bootnode_addrs:
    - /ip4/43.199.24.44/tcp/8228/p2p/Qm1
    - /ip4/54.255.71.126/tcp/8228/p2p/Qm2
  next_key: value
"""


def _make_node(config_text, tmp):
    cfg = os.path.join(tmp, "official.yml")
    with open(cfg, "w") as f:
        f.write(config_text)
    return DailySyncNode(
        "testnet",
        os.path.join(tmp, "fnn"),
        cfg,
        os.path.join(tmp, "_work"),
        "https://testnet.ckbapp.dev/",
    )


def test_parse_bootnodes_and_announced():
    d = tempfile.mkdtemp()
    cfg = os.path.join(d, "c.yml")
    with open(cfg, "w") as f:
        f.write(_GOOD_CONFIG)
    assert len(parse_bootnodes(cfg)) == 2
    assert parse_announced_addrs(cfg) == []


def test_prepare_happy_path_writes_secure_key():
    d = tempfile.mkdtemp()
    node = _make_node(_GOOD_CONFIG, d)
    node.prepare()
    assert len(node.bootnodes) == 2
    key_path = os.path.join(node.attempt_dir, "ckb", "key")
    assert os.path.exists(key_path)
    assert (os.stat(key_path).st_mode & 0o777) == 0o600


def test_prepare_rejects_missing_bootnodes():
    d = tempfile.mkdtemp()
    node = _make_node("fiber:\n  listening_addr: /ip4/0.0.0.0/tcp/8228\n", d)
    with pytest.raises(ConfigError):
        node.prepare()


def test_prepare_rejects_active_announced_addrs():
    d = tempfile.mkdtemp()
    bad = _GOOD_CONFIG.replace(
        "    # - /ip4/1.2.3.4/tcp/8228   example only, commented",
        "    - /ip4/9.9.9.9/tcp/8228",
    )
    node = _make_node(bad, d)
    with pytest.raises(ConfigError):
        node.prepare()


# --------------------------------------------------------------------------
# Pagination fail-closed
# --------------------------------------------------------------------------
def _node_for_rpc(tmp):
    return _make_node(_GOOD_CONFIG, tmp)


def _valid_graph_node(pubkey="0xA", timestamp=1, **changes):
    item = {
        "pubkey": pubkey,
        "timestamp": timestamp,
        "node_name": "node",
        "version": "test",
        "addresses": ["/ip4/1.1.1.1/tcp/8228"],
        "features": [],
        "chain_hash": dgs.GENESIS["testnet"],
        "auto_accept_min_ckb_funding_amount": "0x0",
        "udt_cfg_infos": [],
    }
    item.update(changes)
    return item


def _valid_graph_channel(outpoint="0xC1", **changes):
    item = {
        "channel_outpoint": outpoint,
        "node1": "0xAA",
        "node2": "0xBB",
        "created_timestamp": "0x1",
        "update_info_of_node1": None,
        "update_info_of_node2": None,
        "capacity": "0x64",
        "chain_hash": dgs.GENESIS["testnet"],
        "udt_type_script": None,
    }
    item.update(changes)
    return item


def test_paginate_happy_multi_page_dedup():
    node = _node_for_rpc(tempfile.mkdtemp())
    pages = [
        {"nodes": [_valid_graph_node()], "last_cursor": "0x01"},
        {
            "nodes": [
                _valid_graph_node(timestamp=2),  # newer dup, should win
                _valid_graph_node(pubkey="0xB"),
            ],
            "last_cursor": "0x02",
        },
        {"nodes": [], "last_cursor": "0x"},  # terminal empty page
    ]
    calls = {"i": 0}

    def fake_rpc(method, params, deadline):
        r = pages[calls["i"]]
        calls["i"] += 1
        return r

    node.rpc = fake_rpc
    items, _ = node.paginate("graph_nodes", "nodes", time.monotonic() + 60, _merge_node)
    by_pk = {i["pubkey"]: i for i in items}
    assert set(by_pk) == {"0xA", "0xB"}
    assert by_pk["0xA"]["timestamp"] == 2  # newest kept


@pytest.mark.parametrize(
    "field_name",
    [
        "pubkey",
        "timestamp",
        "node_name",
        "version",
        "addresses",
        "features",
        "chain_hash",
        "auto_accept_min_ckb_funding_amount",
        "udt_cfg_infos",
    ],
)
def test_graph_node_schema_requires_all_fields(field_name):
    item = _valid_graph_node()
    del item[field_name]
    with pytest.raises(GraphError, match=field_name):
        dgs._validate_node_item(item)


@pytest.mark.parametrize(
    "field_name",
    [
        "channel_outpoint",
        "node1",
        "node2",
        "created_timestamp",
        "update_info_of_node1",
        "update_info_of_node2",
        "capacity",
        "chain_hash",
        "udt_type_script",
    ],
)
def test_graph_channel_schema_requires_all_fields(field_name):
    item = _valid_graph_channel()
    del item[field_name]
    with pytest.raises(GraphError, match=field_name):
        dgs._validate_channel_item(item)


def test_graph_channel_schema_validates_directional_update():
    update = {
        "timestamp": "0x1",
        "enabled": True,
        "outbound_liquidity": None,
        "tlc_expiry_delta": "0x1",
        "tlc_minimum_value": "0x0",
        "fee_rate": "0x0",
    }
    dgs._validate_channel_item(_valid_graph_channel(update_info_of_node1=update))
    bad = dict(update)
    del bad["fee_rate"]
    with pytest.raises(GraphError, match="fee_rate"):
        dgs._validate_channel_item(_valid_graph_channel(update_info_of_node1=bad))


def test_paginate_fails_on_missing_cursor():
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda m, p, d: {"nodes": [_valid_graph_node()], "last_cursor": None}
    with pytest.raises(GraphError):
        node.paginate("graph_nodes", "nodes", time.monotonic() + 60, _merge_node)


def test_paginate_fails_on_duplicate_cursor():
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda m, p, d: {
        "nodes": [_valid_graph_node()],
        "last_cursor": "0x05",
    }
    with pytest.raises(GraphError):
        node.paginate("graph_nodes", "nodes", time.monotonic() + 60, _merge_node)


def test_paginate_fails_on_item_without_identity():
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda m, p, d: {"nodes": [{"foo": "bar"}], "last_cursor": "0x01"}
    with pytest.raises(GraphError):
        node.paginate("graph_nodes", "nodes", time.monotonic() + 60, _merge_node)


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        "not-an-object",
        {"last_cursor": "0x"},
        {"nodes": None, "last_cursor": "0x"},
        {"nodes": {}, "last_cursor": "0x01"},
        {"nodes": "not-an-array", "last_cursor": "0x01"},
        {"nodes": [42], "last_cursor": "0x01"},
        {"nodes": []},
        {"nodes": [], "last_cursor": None},
    ],
)
def test_paginate_rejects_malformed_graph_nodes_response(response):
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda m, p, d: response
    with pytest.raises(GraphError):
        node.paginate("graph_nodes", "nodes", time.monotonic() + 60, _merge_node)


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        "not-an-object",
        {"last_cursor": "0x"},
        {"channels": None, "last_cursor": "0x"},
        {"channels": {}, "last_cursor": "0x01"},
        {"channels": "not-an-array", "last_cursor": "0x01"},
        {"channels": [42], "last_cursor": "0x01"},
        {"channels": []},
        {"channels": [], "last_cursor": None},
    ],
)
def test_paginate_rejects_malformed_graph_channels_response(response):
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda m, p, d: response
    with pytest.raises(GraphError):
        node.paginate(
            "graph_channels", "channels", time.monotonic() + 60, _merge_channel
        )


@pytest.mark.parametrize(
    "method,key,item,merge",
    [
        (
            "graph_nodes",
            "nodes",
            {"channel_outpoint": "0xC1"},
            _merge_node,
        ),
        (
            "graph_channels",
            "channels",
            {"pubkey": "0xAA"},
            _merge_channel,
        ),
    ],
)
def test_paginate_requires_the_identity_for_the_requested_graph(
    method, key, item, merge
):
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda m, p, d: {key: [item], "last_cursor": "0x01"}
    with pytest.raises(GraphError):
        node.paginate(method, key, time.monotonic() + 60, merge)


def test_paginate_fails_on_max_pages(monkeypatch):
    monkeypatch.setattr(dgs, "MAX_PAGES", 3)
    node = _node_for_rpc(tempfile.mkdtemp())
    counter = {"i": 0}

    def fake_rpc(method, params, deadline):
        counter["i"] += 1
        return {
            "nodes": [_valid_graph_node(pubkey=hex(counter["i"]))],
            "last_cursor": hex(counter["i"]),
        }

    node.rpc = fake_rpc
    with pytest.raises(GraphError):
        node.paginate("graph_nodes", "nodes", time.monotonic() + 60, _merge_node)


# --------------------------------------------------------------------------
# RPC deadline bounding
# --------------------------------------------------------------------------
class _RpcResponse:
    def __init__(self, payload=None, json_error=None, http_error=None):
        self.payload = payload
        self.json_error = json_error
        self.http_error = http_error

    def raise_for_status(self):
        if self.http_error:
            raise self.http_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def test_jsonrpc_validates_http_and_envelope(monkeypatch):
    valid = _RpcResponse({"jsonrpc": "2.0", "id": 1, "result": {"value": "ok"}})
    monkeypatch.setattr(dgs.requests, "post", lambda *args, **kwargs: valid)
    assert dgs._jsonrpc("http://127.0.0.1", "m", [], 1) == {"value": "ok"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"id": 1, "result": {}},
        {"jsonrpc": "1.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -1}},
    ],
)
def test_jsonrpc_rejects_malformed_envelope(monkeypatch, payload):
    monkeypatch.setattr(
        dgs.requests, "post", lambda *args, **kwargs: _RpcResponse(payload)
    )
    with pytest.raises(RuntimeError):
        dgs._jsonrpc("http://127.0.0.1", "m", [], 1)


def test_jsonrpc_rejects_http_and_non_json_responses(monkeypatch):
    http_error = dgs.requests.exceptions.HTTPError("429")
    monkeypatch.setattr(
        dgs.requests,
        "post",
        lambda *args, **kwargs: _RpcResponse(http_error=http_error),
    )
    with pytest.raises(dgs.requests.exceptions.HTTPError):
        dgs._jsonrpc("http://127.0.0.1", "m", [], 1)

    monkeypatch.setattr(
        dgs.requests,
        "post",
        lambda *args, **kwargs: _RpcResponse(json_error=ValueError("html")),
    )
    with pytest.raises(RuntimeError, match="not valid JSON"):
        dgs._jsonrpc("http://127.0.0.1", "m", [], 1)


def test_rpc_past_deadline_raises():
    node = _node_for_rpc(tempfile.mkdtemp())
    with pytest.raises(DeadlineExceeded):
        node.rpc("node_info", [{}], time.monotonic() - 1)


def test_rpc_timeout_bounded_by_remaining(monkeypatch):
    node = _node_for_rpc(tempfile.mkdtemp())
    captured = {}

    def fake_jsonrpc(url, method, params, timeout):
        captured["timeout"] = timeout
        return {}

    monkeypatch.setattr(dgs, "_jsonrpc", fake_jsonrpc)
    node.rpc("node_info", [{}], time.monotonic() + 2)
    assert captured["timeout"] <= dgs.PER_CALL_TIMEOUT
    assert captured["timeout"] <= 2.5  # bounded by the ~2s remaining budget


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"peers": None},
        {"peers": [42]},
        {"peers": [{"pubkey": "0xAA"}]},
        {"peers": [{"pubkey": "0xAA", "address": None}]},
    ],
)
def test_list_peers_rejects_malformed_result(response):
    node = _node_for_rpc(tempfile.mkdtemp())
    node.rpc = lambda method, params, deadline: response
    with pytest.raises(GraphError):
        node.list_peers(time.monotonic() + 60)


def test_peer_snapshot_and_sample_gap_guards(monkeypatch):
    peers = [{"pubkey": "A", "address": "/ip4/1.1.1.1/tcp/1"}]
    same = list(reversed(peers))
    changed = [{"pubkey": "A", "address": "/ip4/2.2.2.2/tcp/1"}]
    assert dgs._peer_fingerprint(peers) == dgs._peer_fingerprint(same)
    assert dgs._peer_fingerprint(peers) != dgs._peer_fingerprint(changed)

    monkeypatch.setattr(dgs, "MAX_SAMPLE_GAP", 10)
    assert dgs._sample_gap_exceeded(None, 100) is False
    assert dgs._sample_gap_exceeded(90, 100) is False
    assert dgs._sample_gap_exceeded(89.9, 100) is True


# --------------------------------------------------------------------------
# Cleanup failure surfaces (and preserves the work dir)
# --------------------------------------------------------------------------
def test_clean_raises_and_preserves_on_rmtree_failure(monkeypatch):
    d = tempfile.mkdtemp()
    node = _make_node(_GOOD_CONFIG, d)
    os.makedirs(node.attempt_dir, exist_ok=True)

    def boom(path):
        raise OSError("busy")

    monkeypatch.setattr(dgs.shutil, "rmtree", boom)
    with pytest.raises(CleanupError):
        node.clean()
    assert os.path.isdir(node.attempt_dir)  # preserved for diagnosis


def test_stop_is_noop_without_process():
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.stop()  # proc is None -> must not raise


class _FakeProcess:
    def __init__(self, wait_outcomes):
        self.pid = 4321
        self.returncode = None
        self.wait_outcomes = list(wait_outcomes)
        self.wait_calls = []
        self.sent_signals = []

    def poll(self):
        return None

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        outcome = self.wait_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.returncode = outcome
        return outcome

    def send_signal(self, sig):
        self.sent_signals.append(sig)


def test_stop_terms_and_reaps_process_group(monkeypatch):
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.proc = _FakeProcess([0])
    signals = []
    monkeypatch.setattr(dgs.os, "getpgid", lambda pid: 9876)
    monkeypatch.setattr(dgs.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    node.stop()

    assert signals == [(9876, signal.SIGTERM)]
    assert node.proc.wait_calls == [20]


def test_stop_escalates_to_kill_and_reaps_process_group(monkeypatch):
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.proc = _FakeProcess([subprocess.TimeoutExpired("fnn", 20), 0])
    signals = []
    monkeypatch.setattr(dgs.os, "getpgid", lambda pid: 9876)
    monkeypatch.setattr(dgs.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    node.stop()

    assert signals == [(9876, signal.SIGTERM), (9876, signal.SIGKILL)]
    assert node.proc.wait_calls == [20, 20]


def test_stop_fails_closed_when_process_cannot_be_reaped(monkeypatch):
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.proc = _FakeProcess(
        [
            subprocess.TimeoutExpired("fnn", 20),
            subprocess.TimeoutExpired("fnn", 20),
        ]
    )
    signals = []
    monkeypatch.setattr(dgs.os, "getpgid", lambda pid: 9876)
    monkeypatch.setattr(dgs.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    with pytest.raises(CleanupError):
        node.stop()

    assert signals == [(9876, signal.SIGTERM), (9876, signal.SIGKILL)]
    assert node.proc.wait_calls == [20, 20]


# --------------------------------------------------------------------------
# ATTEMPTS boundary predicate (mirrors the guard in the E2E test)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,ok",
    [(1, True), (2, True), (0, False), (3, False), (-1, False)],
)
def test_attempts_boundary_predicate(value, ok):
    assert (1 <= value <= 2) is ok


# --------------------------------------------------------------------------
# ATTEMPTS env parsing (real parser used by the E2E wrapper)
# --------------------------------------------------------------------------
def test_attempts_env_parsing(monkeypatch):
    from test_cases.fiber.daily.test_daily_graph_sync import _parse_attempts

    monkeypatch.setenv("DAILY_SYNC_ATTEMPTS", "2")
    assert _parse_attempts() == 2
    monkeypatch.delenv("DAILY_SYNC_ATTEMPTS", raising=False)
    assert _parse_attempts() == 1  # default
    for bad in ("abc", "0", "3", "1.5"):
        monkeypatch.setenv("DAILY_SYNC_ATTEMPTS", bad)
        with pytest.raises(AssertionError):
            _parse_attempts()


# --------------------------------------------------------------------------
# AggregateReader.seq (peer-generation gate building block)
# --------------------------------------------------------------------------
def test_aggregate_reader_seq_increments_per_line():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "node.log")
    open(p, "wb").close()
    r = AggregateReader(p)
    assert r.seq == 0
    with open(p, "ab") as f:
        f.write(_agg_line(2, 1, 1, 0))
        f.write(_agg_line(2, 2, 0, 0))
    r.poll()
    assert r.seq == 2  # a fresh aggregate line advances the sequence
    with open(p, "ab") as f:
        f.write(_agg_line(2, 0, 0, 2))
    r.poll()
    assert r.seq == 3


# --------------------------------------------------------------------------
# Retryable classification (governs whether a second attempt runs)
# --------------------------------------------------------------------------
def test_is_retryable_classification():
    import requests

    # transient public-network / RPC hiccups -> retry allowed
    assert _is_retryable(DeadlineExceeded("x")) is True
    assert _is_retryable(requests.exceptions.ConnectionError("x")) is True
    assert _is_retryable(requests.exceptions.Timeout("x")) is True
    assert _is_retryable(RuntimeError("rpc error")) is True
    # config / chain / binary / filesystem / cleanup -> fail loud, no retry
    assert _is_retryable(ConfigError("x")) is False
    assert _is_retryable(GraphError("x")) is False
    assert _is_retryable(NodeLogError("x")) is False
    assert _is_retryable(CleanupError("x")) is False
    assert _is_retryable(NodeExited("x")) is False
    assert _is_retryable(OSError("x")) is False


# --------------------------------------------------------------------------
# YAML config parsing edge cases (inline / flow / null / wrong type)
# --------------------------------------------------------------------------
def _write(tmp, text):
    p = os.path.join(tmp, "c.yml")
    with open(p, "w") as f:
        f.write(text)
    return p


def test_parse_inline_flow_and_null_addrs():
    d = tempfile.mkdtemp()
    # inline flow list for announced_addrs -- the old regex parser missed this
    p = _write(
        d,
        "fiber:\n"
        "  bootnode_addrs: ['/ip4/1.1.1.1/tcp/8228/p2p/Qm1']\n"
        "  announced_addrs: ['/ip4/9.9.9.9/tcp/8228']\n",
    )
    assert parse_bootnodes(p) == ["/ip4/1.1.1.1/tcp/8228/p2p/Qm1"]
    assert parse_announced_addrs(p) == ["/ip4/9.9.9.9/tcp/8228"]
    # null announced_addrs -> empty
    p2 = _write(
        d,
        "fiber:\n  bootnode_addrs:\n    - /ip4/1.1.1.1/tcp/8228/p2p/Qm1\n"
        "  announced_addrs:\n",
    )
    assert parse_announced_addrs(p2) == []
    # scalar string announced_addrs -> single-element list
    p3 = _write(
        d, "fiber:\n  bootnode_addrs: []\n  announced_addrs: /ip4/9.9.9.9/tcp/8228\n"
    )
    assert parse_announced_addrs(p3) == ["/ip4/9.9.9.9/tcp/8228"]


def test_parse_rejects_wrong_type():
    d = tempfile.mkdtemp()
    p = _write(d, "fiber:\n  announced_addrs: 12345\n  bootnode_addrs: []\n")
    with pytest.raises(ConfigError):
        parse_announced_addrs(p)


def test_prepare_rejects_inline_announced_addrs():
    d = tempfile.mkdtemp()
    bad = (
        "fiber:\n"
        "  listening_addr: /ip4/0.0.0.0/tcp/8228\n"
        "  announced_addrs: ['/ip4/9.9.9.9/tcp/8228']\n"
        "  bootnode_addrs:\n"
        "    - /ip4/43.199.24.44/tcp/8228/p2p/Qm1\n"
    )
    node = _make_node(bad, d)
    with pytest.raises(ConfigError):
        node.prepare()


def test_malformed_yaml_returns_structured_attempt_failure(monkeypatch):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    _fixed_mkdtemp(monkeypatch, base)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    cfg = _write(base, "fiber:\n  bootnode_addrs: [unterminated\n")

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        cfg,
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )

    assert result.converged is False
    assert result.retryable is False
    assert result.failure_reason.startswith("ConfigError:")
    with open(os.path.join(report_dir, "summary.json")) as f:
        assert json.load(f) == result.to_dict()


# --------------------------------------------------------------------------
# Bootnode matching: PeerId across DNS/IP, host+port fallback
# --------------------------------------------------------------------------
def test_match_bootnodes_peerid_across_dns_and_ip():
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.bootnodes = ["/dns4/boot.example/tcp/8228/p2p/QmPEER"]
    peers = [{"pubkey": "0xpk", "address": "/ip4/5.5.5.5/tcp/8228/p2p/QmPEER"}]
    assert node.match_bootnodes(peers) == ["/ip4/5.5.5.5/tcp/8228/p2p/QmPEER"]


def test_match_bootnodes_hostport_fallback_and_mismatch():
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.bootnodes = ["/ip4/5.5.5.5/tcp/8228"]  # no /p2p PeerId
    assert node.match_bootnodes([{"address": "/ip4/5.5.5.5/tcp/8228"}])
    assert node.match_bootnodes([{"address": "/ip4/6.6.6.6/tcp/8228"}]) == []


def test_match_bootnodes_rejects_same_hostport_with_different_peerids():
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.bootnodes = ["/ip4/5.5.5.5/tcp/8228/p2p/QmBOOT"]
    peers = [{"address": "/ip4/5.5.5.5/tcp/8228/p2p/QmOTHER"}]
    assert node.match_bootnodes(peers) == []


# --------------------------------------------------------------------------
# Digest: cross-direction merge, deterministic tie-break, cross-page order
# --------------------------------------------------------------------------
def test_channel_merge_keeps_both_directions_across_pages():
    page_a = {
        "channel_outpoint": "0xC1",
        "node1": "0xAA",
        "node2": "0xBB",
        "created_timestamp": 1,
        "update_info_of_node1": {"timestamp": 9, "enabled": True},
        "update_info_of_node2": {"timestamp": 3, "enabled": True},
    }
    page_b = {
        "channel_outpoint": "0xC1",
        "node1": "0xAA",
        "node2": "0xBB",
        "created_timestamp": 1,
        "update_info_of_node1": {"timestamp": 5, "enabled": True},
        "update_info_of_node2": {"timestamp": 8, "enabled": False},
    }
    m1 = _merge_channel(_merge_channel(None, page_a), page_b)
    m2 = _merge_channel(_merge_channel(None, page_b), page_a)
    # newest update from EACH direction is kept, regardless of page order
    assert m1["update_info_of_node1"]["timestamp"] == 9
    assert m1["update_info_of_node2"]["timestamp"] == 8
    assert _channels_digest([page_a, page_b]) == _channels_digest([page_b, page_a])


def test_node_digest_tie_break_is_order_independent():
    a = {"pubkey": "0xAA", "timestamp": 1, "node_name": "z"}
    b = {"pubkey": "0xAA", "timestamp": 1, "node_name": "a"}  # same ts, differing name
    assert _merge_node(_merge_node(None, a), b) == _merge_node(_merge_node(None, b), a)
    assert _nodes_digest([a, b]) == _nodes_digest([b, a])


@pytest.mark.parametrize(
    "field,changed_value",
    [
        ("node1", "0xCC"),
        ("node2", "0xDD"),
        ("chain_hash", "0x02"),
        ("created_timestamp", 2),
        ("capacity", "0x65"),
        (
            "udt_type_script",
            {"code_hash": "0x02", "hash_type": "type", "args": "0xbb"},
        ),
    ],
)
def test_channel_merge_rejects_conflicting_immutable_fields(field, changed_value):
    channel = {
        "channel_outpoint": "0xC1",
        "node1": "0xAA",
        "node2": "0xBB",
        "chain_hash": "0x01",
        "created_timestamp": 1,
        "capacity": "0x64",
        "udt_type_script": {
            "code_hash": "0x01",
            "hash_type": "type",
            "args": "0xaa",
        },
        "update_info_of_node1": {"timestamp": 1, "enabled": True},
        "update_info_of_node2": None,
    }
    conflicting = dict(channel, **{field: changed_value})
    with pytest.raises(GraphError):
        _merge_channel(channel, conflicting)


# --------------------------------------------------------------------------
# Child env isolation (a stray parent FIBER_*/RPC_*/CKB_* cannot leak in)
# --------------------------------------------------------------------------
def test_start_strips_inherited_fiber_env(monkeypatch):
    node = _make_node(_GOOD_CONFIG, tempfile.mkdtemp())
    node.prepare()
    monkeypatch.setenv("FIBER_ANNOUNCED_ADDRS", "/ip4/6.6.6.6/tcp/8228")
    monkeypatch.setenv("CKB_NODE_RPC_URL", "http://evil.example")
    monkeypatch.setenv("RPC_LISTENING_ADDR", "0.0.0.0:9")
    monkeypatch.setenv("KEEP_ME", "1")
    captured = {}

    class _FakeProc:
        def poll(self):
            return None

    def fake_popen(cmd, env=None, **kw):
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(dgs.subprocess, "Popen", fake_popen)
    node.start()
    env = captured["env"]
    # the stray parent FIBER_* must be gone; our controlled overrides must win
    assert "FIBER_ANNOUNCED_ADDRS" not in env
    assert env["CKB_NODE_RPC_URL"] == node.ckb_url  # not the evil override
    assert env["RPC_LISTENING_ADDR"] == f"127.0.0.1:{node.rpc_port}"
    assert env["RUST_LOG"] == dgs.RUST_LOG
    assert env["KEEP_ME"] == "1"  # unrelated vars are preserved
    assert "FIBER_ANNOUNCED_ADDRS" in node.env_stripped_keys
    if node._log_fh:
        node._log_fh.close()


# --------------------------------------------------------------------------
# Failure lifecycle: every attempt gets a redacted summary and no secret leaks
# --------------------------------------------------------------------------
def _fixed_mkdtemp(monkeypatch, base):
    """Force run_attempt's work dir to a known location so we can inspect it."""
    work = os.path.join(base, "work")

    def fake_mkdtemp(*a, **k):
        os.makedirs(work, exist_ok=True)
        return work

    monkeypatch.setattr(dgs.tempfile, "mkdtemp", fake_mkdtemp)
    return work


def test_run_attempt_prepare_failure_writes_redacted_summary(monkeypatch):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    _fixed_mkdtemp(monkeypatch, base)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    cfg = _write(
        base, "fiber:\n  listening_addr: /ip4/0.0.0.0/tcp/8228\n"
    )  # no bootnodes

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        cfg,
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )
    assert result.converged is False
    assert result.retryable is False  # a config error must not be retried
    assert result.failure_reason.startswith("ConfigError")
    # a summary artifact exists even though the attempt failed before start
    assert os.path.exists(os.path.join(report_dir, "summary.json"))
    # nothing secret/heavy under the uploaded report tree
    leaked = [f for _, _, fs in os.walk(report_dir) for f in fs if f == "key"]
    assert leaked == []
    assert not os.path.exists(os.path.join(report_dir, "_work"))


def test_run_attempt_popen_failure_shreds_both_secrets_and_reports_cleanup(
    monkeypatch,
):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    work = _fixed_mkdtemp(monkeypatch, base)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})

    def failing_popen(cmd, **kwargs):
        # Model the second secret that fnn may create before process startup fails.
        data_dir = cmd[cmd.index("-d") + 1]
        fiber_dir = os.path.join(data_dir, "fiber")
        os.makedirs(fiber_dir, exist_ok=True)
        with open(os.path.join(fiber_dir, "sk"), "w") as f:
            f.write("second-secret")
        raise OSError("popen boom")

    # prepare() writes ckb/key; start() reaches the real Popen boundary and fails.
    monkeypatch.setattr(dgs.subprocess, "Popen", failing_popen)
    # and clean() fails, so the work dir is deliberately preserved for diagnosis
    monkeypatch.setattr(
        dgs.DailySyncNode,
        "clean",
        lambda self: (_ for _ in ()).throw(CleanupError("busy")),
    )
    cfg = _write(
        base,
        "fiber:\n  bootnode_addrs:\n    - /ip4/1.1.1.1/tcp/8228/p2p/Qm1\n",
    )

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        cfg,
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )
    assert result.retryable is False
    assert result.cleanup_failure  # surfaced, not swallowed
    # both possible secret files were shredded even though work is preserved
    assert not os.path.exists(os.path.join(work, "ckb", "key"))
    assert not os.path.exists(os.path.join(work, "fiber", "sk"))
    # summary.json on disk reflects the cleanup failure (written AFTER clean)
    with open(os.path.join(report_dir, "summary.json")) as f:
        on_disk = json.load(f)
    assert on_disk["cleanup_failure"]
    # and it never contains the raw secret key material
    assert "key" not in os.listdir(report_dir)


class _RunningProcess:
    returncode = None

    def poll(self):
        return None


class _FastConvergingNode:
    """Small no-network node double that reaches convergence in two samples."""

    def __init__(self, network, fnn_path, config_path, attempt_dir, ckb_url):
        self.network = network
        self.attempt_dir = attempt_dir
        self.log_path = os.path.join(attempt_dir, "node.log")
        self.proc = _RunningProcess()
        self.bootnodes = ["/ip4/5.5.5.5/tcp/8228/p2p/QmBOOT"]
        self.env_override_keys = []
        self.env_stripped_keys = []
        self.agg_reader = type(
            "_Reader", (), {"seq": 0, "ever_finished": False, "capped": False}
        )()

    def prepare(self):
        pass

    def start(self):
        with open(self.log_path, "wb") as f:
            f.write(b"log")

    def wait_rpc_ready(self, deadline):
        return {
            "pubkey": "0xSELF",
            "version": "test",
            "chain_hash": dgs.GENESIS[self.network],
        }

    def read_latest_aggregate(self):
        self.agg_reader.seq += 1
        self.agg_reader.ever_finished = True
        return SyncAggregate(total=1, finished=1, active=0, passive=0)

    def rpc(self, method, params, deadline):
        assert method == "list_peers"
        return {
            "peers": [
                {
                    "pubkey": "0xREMOTE",
                    "address": "/ip4/5.5.5.5/tcp/8228/p2p/QmBOOT",
                }
            ]
        }

    def list_peers(self, deadline):
        return self.rpc("list_peers", [], deadline)["peers"]

    def paginate(self, method, key, deadline, merge):
        if method == "graph_nodes":
            return [_valid_graph_node(pubkey="0xREMOTE")], 0.0
        return [
            _valid_graph_channel(
                node1="0xSELF",
                node2="0xREMOTE",
            )
        ], 0.0

    def match_bootnodes(self, peers):
        return [peers[0]["address"]]

    def stop(self):
        pass

    def shred_secret(self):
        pass

    def archive_log(self, report_dir, snapshot_size=None):
        raise OSError("archive failed")

    def clean(self):
        pass

    def write_summary(self, report_dir, result):
        os.makedirs(report_dir, exist_ok=True)
        with open(os.path.join(report_dir, "summary.json"), "w") as f:
            json.dump(result.to_dict(), f)


class _ProgressConvergingNode(_FastConvergingNode):
    """Successful double whose channel digest changes on the second sample."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_scans = 0

    def paginate(self, method, key, deadline, merge):
        if method == "graph_nodes":
            return [_valid_graph_node(pubkey="0xREMOTE")], 0.0
        self.channel_scans += 1
        return [
            _valid_graph_channel(
                node1="0xSELF",
                node2="0xREMOTE",
                capacity=hex(100 + self.channel_scans),
            )
        ], 0.0

    def archive_log(self, report_dir, snapshot_size=None):
        pass


def test_progress_logs_expose_live_ci_timeline(monkeypatch, capsys):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    monkeypatch.setattr(dgs, "DailySyncNode", _ProgressConvergingNode)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    monkeypatch.setattr(dgs, "STABLE_WINDOW", 0)
    monkeypatch.setattr(dgs, "POLL_INTERVAL", 0)
    monkeypatch.setattr(dgs, "PROGRESS_LOG_INTERVAL", 0)

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        _write(base, _GOOD_CONFIG),
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )

    output = capsys.readouterr().out
    assert result.converged is True
    for milestone in (
        "attempt started",
        "CKB precheck passed",
        "fnn config prepared",
        "fnn started",
        "RPC ready; node identity validated",
        "ActiveSyncingFinished observed",
        "configured bootnode connected",
        "first graph snapshot",
        "graph changed after active sync; stability window reset",
        "completion conditions satisfied; waiting for graph stability",
        "progress",
        "graph stability window satisfied; finalizing attempt",
        "PASS graph sync converged",
    ):
        assert milestone in output
    assert "active_sync_finished_s=" in output
    assert "last_digest_change_s=" in output
    assert "sync_duration_s=" in output
    with open(os.path.join(report_dir, "summary.json")) as f:
        summary = json.load(f)
    assert summary["sync_duration_seconds"] == result.converged_observed_seconds
    assert output.index("finalizing attempt") < output.index(
        "PASS graph sync converged"
    )


def test_progress_logs_do_not_expose_ckb_url_credentials(capsys):
    base = tempfile.mkdtemp()
    secret_url = "https://alice:super-secret@example.com/"

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        _write(base, _GOOD_CONFIG),
        os.path.join(base, "report"),
        ckb_url=secret_url,
    )

    output = capsys.readouterr().out
    assert result.converged is False
    assert "https://example.com" in output
    assert secret_url not in output
    assert "alice" not in output
    assert "super-secret" not in output


def test_archive_failure_turns_converged_attempt_into_hard_failure(monkeypatch, capsys):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    monkeypatch.setattr(dgs, "DailySyncNode", _FastConvergingNode)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    monkeypatch.setattr(dgs, "STABLE_WINDOW", 0)
    monkeypatch.setattr(dgs, "POLL_INTERVAL", 0)
    cfg = _write(base, _GOOD_CONFIG)

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        cfg,
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )

    assert result.converged is False
    assert result.retryable is False
    assert "archive failed" in result.failure_reason
    output = capsys.readouterr().out
    assert "PASS graph sync converged" not in output
    assert "attempt failed" in output
    with open(os.path.join(report_dir, "summary.json")) as f:
        on_disk = json.load(f)
    assert on_disk["converged"] is False
    assert on_disk["failure_reason"] == result.failure_reason


def test_result_file_write_failure_never_prints_pass(monkeypatch, capsys):
    base = tempfile.mkdtemp()
    monkeypatch.setattr(dgs, "DailySyncNode", _ProgressConvergingNode)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    monkeypatch.setattr(dgs, "STABLE_WINDOW", 0)
    monkeypatch.setattr(dgs, "POLL_INTERVAL", 0)
    monkeypatch.setattr(
        dgs,
        "_write_result_files",
        lambda *args: (_ for _ in ()).throw(OSError("result disk full")),
    )

    with pytest.raises(OSError, match="result disk full"):
        dgs.run_attempt(
            "testnet",
            os.path.join(base, "fnn"),
            _write(base, _GOOD_CONFIG),
            os.path.join(base, "report"),
            ckb_url="https://testnet.ckbapp.dev/",
        )

    output = capsys.readouterr().out
    assert "graph stability window satisfied; finalizing attempt" in output
    assert "PASS graph sync converged" not in output


class _ExitOnFinalPoll:
    returncode = 7

    def __init__(self):
        self.calls = 0

    def poll(self):
        self.calls += 1
        return self.returncode if self.calls >= 3 else None


class _ExitDuringFinalScanNode(_FastConvergingNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proc = _ExitOnFinalPoll()

    def archive_log(self, report_dir, snapshot_size=None):
        pass


def test_process_exit_during_final_scan_cannot_converge(monkeypatch):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    monkeypatch.setattr(dgs, "DailySyncNode", _ExitDuringFinalScanNode)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    monkeypatch.setattr(dgs, "STABLE_WINDOW", 0)
    monkeypatch.setattr(dgs, "POLL_INTERVAL", 0)

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        _write(base, _GOOD_CONFIG),
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )

    assert result.converged is False
    assert result.retryable is False
    assert result.failure_reason.startswith("NodeExited")


def test_constructor_failure_cleans_allocated_workdir(monkeypatch):
    base = tempfile.mkdtemp()
    report_dir = os.path.join(base, "report")
    work = _fixed_mkdtemp(monkeypatch, base)
    monkeypatch.setattr(dgs, "ckb_precheck", lambda url, net: {"endpoint": "redacted"})
    monkeypatch.setattr(
        dgs,
        "_free_tcp_port",
        lambda: (_ for _ in ()).throw(OSError("no port")),
    )

    result = dgs.run_attempt(
        "testnet",
        os.path.join(base, "fnn"),
        _write(base, _GOOD_CONFIG),
        report_dir,
        ckb_url="https://testnet.ckbapp.dev/",
    )

    assert result.converged is False
    assert result.retryable is False
    assert not os.path.exists(work)
    with open(os.path.join(report_dir, "summary.json")) as f:
        assert json.load(f)["failure_reason"].startswith("OSError")
